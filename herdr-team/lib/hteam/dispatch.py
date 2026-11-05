"""horch Task 실행과 복구(설계 5.4, 6.1): 시작 장벽, 제목(실행 키)으로 찾기, 같은 Task 다시 띄우기.

실행 기록(slot)은 상태 파일 안의 dict 다(작업: rounds[-1].work, 리뷰: rounds[-1].reviews[i]).
필드: title(실행 키), horch_task, dispatch, launched(시작 장벽 자식 {pid, started}), error, canceled, cleaned.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
from typing import Iterator

from . import procs, state
from .errors import CONFLICT, FAIL, MISSING, HteamError
from .horch import agent_args, parse
from .launch import Barrier
from .util import die_at

ADOPT = ("launching", "active", "settled", "retained")


def new_slot(title: str) -> dict:
    return {"title": title, "horch_task": None, "dispatch": None, "launched": None, "error": None,
            "canceled": False, "cleaned": False}


def busy(st: dict, slot: dict) -> bool:
    """같은 키의 다른 hteam 실행자나 기록된 horch 자식이 아직 살아 있나(살아 있으면 exit 3 launching)."""
    launcher = st.get("launcher") or {}
    if launcher.get("key") == slot["title"] and launcher.get("pid") != os.getpid() \
            and procs.record_alive(launcher):
        return True
    return procs.record_alive(slot.get("launched"))


def latest_for_task(rows: list[dict], task: str) -> dict | None:
    mine = [r for r in rows if r.get("task") == task]
    return max(mine, key=lambda r: r["attempt"]) if mine else None


def find_by_title(rows: list[dict], title: str) -> tuple[dict | None, list[str]]:
    """제목이 같은 horch Task 의 최신 Dispatch. 같은 제목 Task 가 둘 이상이면 가장 최근 것과 경고."""
    tasks: dict[str, dict] = {}
    for r in rows:
        if r.get("title") == title:
            cur = tasks.get(r["task"])
            if cur is None or r["attempt"] > cur["attempt"]:
                tasks[r["task"]] = r
    if not tasks:
        return None, []
    ordered = sorted(tasks.values(), key=lambda r: (r.get("created_at") or "", r["id"]))
    chosen = ordered[-1]
    warnings = []
    if len(ordered) > 1:
        others = ", ".join(r["task"] for r in ordered[:-1])
        warnings.append(f"제목 {title!r} 인 horch Task 가 {len(ordered)}개다. 가장 최근 {chosen['task']} 를 쓰고 "
                        f"나머지({others})는 두었다")
    return chosen, warnings


def classify(row: dict) -> str:
    """최신 Dispatch 가 launching·active·settled·retained(또는 done 뒤 release)면 이어 붙이고, 아니면 같은 Task 를 다시 띄운다."""
    if row["state"] in ADOPT or (row["state"] == "released" and row.get("outcome")):
        return "adopt"
    return "retry"


def existing(h, slot: dict) -> tuple[str, dict | None, list[str]]:
    """("fresh"|"adopt"|"retry", 행, 경고). 기록된 Task 가 있으면 그것, 자식 pid 만 있으면 제목으로 찾는다."""
    if slot.get("horch_task"):
        row = latest_for_task(h.workers(), slot["horch_task"])
        if row is None:  # 새로 띄우면 같은 제목의 horch Task 가 둘이 된다
            raise HteamError("horch_task_missing", f"기록된 horch Task {slot['horch_task']} 가 worker-list 에 없다", FAIL,
                             "horch 홈(state/horch)과 Run 이 그대로인지 확인한다. 이 실행 키를 넘기려면 hteam fix, "
                             "버리려면 hteam drop")
        return classify(row), row, []
    if slot.get("launched"):
        row, warnings = find_by_title(h.workers(), slot["title"])
        return ("fresh", None, warnings) if row is None else (classify(row), row, warnings)
    return "fresh", None, []


def check_owner(st: dict, slot: dict) -> None:
    """이 실행자가 아직 이 실행 기록을 띄울 수 있나(설계 5.4·6.4). 태스크 잠금 안에서 부른다.

    fix·drop 은 끝나지 않은 실행 키에 canceled 를 먼저 저장하고 horch 상태로 정리한 뒤 새 라운드나 dropped 를 쓴다.
    그 뒤에 이 실행자가 기록을 쓰면 정리를 되돌린다. 취소됐거나 실행자 기록이 이 프로세스·이 실행 키가 아니면 exit 3."""
    if slot.get("canceled"):
        raise HteamError("launch_canceled", f"{slot['title']} 실행 키가 취소됐다", CONFLICT,
                         "앞선 fix·drop 이 끝나지 않았다. 같은 명령을 다시 한다")
    launcher = st.get("launcher") or {}
    if launcher.get("key") != slot["title"] or launcher.get("pid") != os.getpid():
        raise HteamError("launch_canceled", f"{slot['title']} 실행자 기록이 이 프로세스가 아니다(다른 명령이 바꿨다)",
                         CONFLICT, "hteam status 로 태스크 상태를 확인한다")


@contextlib.contextmanager
def owned(p, tid: str, pick, expect=None, after_save=None) -> Iterator[dict]:
    """태스크 잠금 아래에서 이전 상태(expect, 끝난 태스크가 아님)와 실행 권한(check_owner)을 확인한 뒤 상태를 내준다.
    after_save 는 state.edit 에 넘긴다(쓴 뒤 잠금 안에서 부른다)."""
    with state.edit(p, tid, expect=expect, after_save=after_save) as st:
        if st["status"] in state.CLOSED:
            raise state.closed_error(st)
        check_owner(st, pick(st))
        yield st


def left_running(exc: HteamError, info: dict) -> HteamError:
    """horch 워커가 이미 떴는데 실행 권한을 잃었다. 기록하지 않고(working 도 아님) 정리는 fix·drop 에 맡긴다.
    fix·drop 은 기록된 horch Task, 없으면 실행 키(제목)의 모든 Dispatch 를 horch 상태로 골라 정리한다."""
    exc.hint = "horch 워커가 이미 떴지만 working 으로 두지 않았다. 진행 중인 fix·drop 이 horch 상태로 그 Dispatch 를 정리한다"
    exc.data = {**exc.data, "horch": info}
    return exc


STARTED = "hteam_start_byte_sent"


def mark_started(exc: BaseException) -> BaseException:
    """시작 바이트를 보낸 뒤의 오류다: 워커가 떴는지 모른다. start-ready 는 그 태스크를 그 호출 동안 동시 수에 센다."""
    try:
        setattr(exc, STARTED, True)
    except Exception:
        pass
    return exc


def maybe_started(exc: BaseException) -> bool:
    return bool(getattr(exc, STARTED, False))


def _send(barrier):
    def after_save(_st) -> None:
        die_at("after_child")
        barrier.send()
    return after_save


def _run_barrier(p, tid: str, pick, argv: list[str], expect) -> tuple[int, dict]:
    barrier = Barrier(argv)
    try:
        # 기록을 저장한 직후 같은 태스크 잠금 안에서 시작 바이트를 보낸다. 그래서 fix·drop 의 취소는 기록 전(그러면
        # 위 검사가 막는다)이나 바이트 뒤(horch 가 떴다. 기록·working 전이가 막는다)에만 저장된다
        with owned(p, tid, pick, expect, after_save=_send(barrier)) as st:
            pick(st)["launched"] = barrier.record()
    except BaseException as exc:
        if barrier.sent:
            raise mark_started(exc)  # 바이트를 보내다 실패했다. horch 가 떴는지 모른다
        barrier.abort()
        raise
    try:
        code, out, err = barrier.go()
    except subprocess.TimeoutExpired:
        barrier.kill()  # 멈춘 horch 가 동시 수 자리를 붙잡지 않게. 그 Dispatch 는 horch 가 launch_failed 로 바꾼다
        raise mark_started(HteamError("launch_timeout", f"{tid} 의 horch worker-start 가 제한 시간 안에 끝나지 않았다",
                                      FAIL, "horch 를 끝냈다. 같은 명령을 다시 하면 제목으로 찾아 이어 한다")) from None
    except BaseException as exc:
        raise mark_started(exc)
    die_at("after_launch")
    return code, parse(out, err)


def launch(p, h, tid: str, pick, *, agent: str, model: str | None, effort: str | None, args: list[str],
           spec_file, expect=None) -> dict:
    """pick(st) 가 가리키는 실행 기록으로 horch 워커를 띄우거나 이어 붙인다. 실패하면 HteamError(launch_failed).

    기록을 쓸 때마다 owned 로 이전 상태(expect)·취소·실행자를 다시 확인한다. 어긋나면 exit 3(launch_canceled 등)."""
    slot = pick(state.require(p, tid))
    mode, row, warnings = existing(h, slot)
    if mode == "adopt":
        try:
            with owned(p, tid, pick, expect) as st:
                pick(st).update(horch_task=row["task"], dispatch=row["id"], error=None)
        except HteamError as exc:
            left_running(exc, {"task": row["task"], "dispatch": row["id"], "state": row["state"]})
            raise
        # 이어 붙인 Dispatch 의 실제 에이전트·모델을 돌려준다. 호출자가 라운드·시도 기록을 그것에 맞춘다
        return {"mode": "adopt", "horch_task": row["task"], "dispatch": row["id"], "terminal": row.get("terminal"),
                "state": row["state"], "agent": row.get("agent"), "model": row.get("model"),
                "effort": row.get("effort"), "warnings": warnings}
    opts = []
    if model:
        opts += ["--model", model]
    if effort:
        opts += ["--effort", effort]
    if mode == "retry":
        argv = h.argv("worker-start", "--task", row["task"], "--retry", "--agent", agent, "--cwd", str(p.root),
                      *opts, *agent_args(args))
    else:
        argv = h.argv("worker-start", "--agent", agent, "--title", slot["title"], "--spec-file", str(spec_file),
                      "--cwd", str(p.root), *opts, *agent_args(args))
    code, data = _run_barrier(p, tid, pick, argv, expect)
    ok = code == 0 and data.get("ok")
    try:
        with owned(p, tid, pick, expect) as st:
            s = pick(st)
            if ok:
                s.update(horch_task=data["task"], dispatch=data["dispatch"], error=None)
            else:
                s["horch_task"] = data.get("task") or s.get("horch_task")
                s["error"] = {"exit": code, **(data.get("error") or {})}
    except BaseException as exc:
        if ok and isinstance(exc, HteamError):
            left_running(exc, data)
        raise mark_started(exc)
    if not ok:
        err = data.get("error") or {}
        raise HteamError("launch_failed", f"horch worker-start 실패: {err.get('code')}: {err.get('message')}",
                         MISSING if code == MISSING else FAIL, err.get("hint") or "",
                         data={"horch": data, "warnings": warnings})
    if data.get("warning"):
        warnings.append(data["warning"])
    warnings += list(data.get("warnings") or [])
    return {"mode": mode, "horch_task": data["task"], "dispatch": data["dispatch"], "terminal": data.get("terminal"),
            "state": data.get("state"), "warnings": warnings}
