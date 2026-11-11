"""horch Task 실행·복구·정리(설계 5.4, 6.1, 6.4): 시작 장벽, 제목(실행 키)으로 찾기, 같은 Task 다시 띄우기, 정리(cleanup).

실행 기록(slot)은 상태 파일 안의 dict 다(작업: rounds[-1].work, 리뷰: rounds[-1].reviews[i]).
필드: title(실행 키), horch_task, dispatch, launched(시작 장벽 자식 {pid, started}), error, canceled, cleaned,
terminal(그 Dispatch 의 hc 터미널. launch 가 horch_task·dispatch 와 같은 갱신에서 쓴다. 관제의 리뷰 보기가 리뷰어를 이것으로 안다).
"""
from __future__ import annotations

import contextlib
import os
import subprocess
from typing import Iterator

from . import browser, procs, state, workspace
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


def left_running(exc: HteamError, info: dict, h) -> HteamError:
    """horch 워커가 이미 떴는데 실행 권한을 잃었다. 기록하지 않고(working 도 아님) 정리는 fix·drop 에 맡긴다.

    fix·drop 은 기록된 horch Task, 없으면 실행 키(제목)의 모든 Dispatch 를 horch 상태로 골라 정리한다. 이 실행자가
    살아 있는 동안 그 fix·drop 은 launching 으로 멈추고 마지막 전이(새 라운드·dropped)를 쓰지 않는다(tasks._closing).
    그래서 태스크가 닫힌 채(done·dropped) 이 오류가 나는 일은 hteam 밖에서 상태를 바꾼 경우뿐이다. 그때는 직접 정리한다.
    힌트의 horch 명령은 그대로 실행할 수 있게 h.cmd()(절대 경로와 --home)로 만든다."""
    if exc.code == "task_closed":
        did, cmd = info.get("dispatch") or "<Dispatch>", h.cmd()
        exc.hint = (f"horch 워커({info.get('dispatch') or info.get('task')})가 이미 떴지만 태스크가 이미 닫혀 기록하지 "
                    f"않았다. 직접 정리한다: {cmd} worker-abandon --dispatch {did} --kill 뒤 {cmd} worker-release "
                    f"--dispatch {did}")
    else:
        exc.hint = ("horch 워커가 이미 떴지만 working 으로 두지 않았다. 실행 키를 취소한 fix·drop 을 다시 부르면 horch "
                    "상태로 그 Dispatch 를 찾아 정리한다")
    exc.data = {**exc.data, "horch": info}
    return exc


def _send(barrier):
    def after_save(_st) -> None:
        die_at("after_child")
        barrier.send()
    return after_save


def _run_barrier(p, tid: str, pick, argv: list[str], expect, on_fresh=None) -> tuple[int, dict]:
    barrier = Barrier(argv)
    try:
        # 기록을 저장한 직후 같은 태스크 잠금 안에서 시작 바이트를 보낸다. 그래서 fix·drop 의 취소는 기록 전(그러면
        # 위 검사가 막는다)이나 바이트 뒤(horch 가 떴다. 기록·working 전이가 막는다)에만 저장된다
        with owned(p, tid, pick, expect, after_save=_send(barrier)) as st:
            pick(st)["launched"] = barrier.record()
            if on_fresh is not None:  # 새로 띄우는 실행이 본 것을 launched 와 같은 저장에 남긴다
                on_fresh(st)
    except BaseException:
        if not barrier.sent:  # 바이트를 보내다 실패했으면 자식을 두고(이미 떴을 수 있다) 오류만 낸다
            barrier.abort()
        raise
    try:
        code, out, err = barrier.go()
    except subprocess.TimeoutExpired:
        barrier.kill()  # 멈춘 horch 가 동시 수 자리를 붙잡지 않게. 그 Dispatch 는 horch 가 launch_failed 로 바꾼다
        raise HteamError("launch_timeout", f"{tid} 의 horch worker-start 가 제한 시간 안에 끝나지 않았다", FAIL,
                         "horch 를 끝냈다. 같은 명령을 다시 하면 제목으로 찾아 이어 한다") from None
    die_at("after_launch")
    return code, parse(out, err)


def launch(p, h, tid: str, pick, *, agent: str, model: str | None, effort: str | None, args: list[str],
           spec_file, expect=None, on_fresh=None, keep_open_tab: str | None = None,
           same_terminal: str | None = None, hidden: bool = False, cwd=None, env: dict[str, str] | None = None) -> dict:
    """pick(st) 가 가리키는 실행 기록으로 horch 워커를 띄우거나 이어 붙인다. 실패하면 HteamError(launch_failed).

    기록을 쓸 때마다 owned 로 이전 상태(expect)·취소·실행자를 다시 확인한다. 어긋나면 exit 3(launch_canceled 등).
    on_fresh(st) 는 기존 horch Task 없이 새로 띄울 때(fresh)만 launched 와 같은 저장에서 부른다. 이어 붙이거나(adopt)
    같은 horch Task 를 다시 띄우면(retry) 부르지 않는다.

    고정 에이전트(설계 5.4 의 6단계 문단): keep_open_tab 이면 그 에이전트 탭에 고정 터미널로(`--keep-open --tab`),
    same_terminal 이면 그 고정 터미널에 넣는다(`--terminal`, 모델·effort·인자·cwd 없음). 실행 키·시작 장벽·복구 규칙은 같다.
    hidden 이면 새로 띄우거나 같은 Task 를 다시 띄울 때 `--hidden`(herdr 라벨 없이, 고정 에이전트 태스크의 리뷰어, 설계 6.5 의
    1)을 더한다. 이어 붙이기는 그대로다.
    cwd 는 새로 띄우기·같은 Task 다시 띄우기의 `--cwd`(없으면 프로젝트 루트), env 는 `--env=KEY=VALUE`(이름 순서, 없거나
    비었으면 넣지 않는다)다. 작업 공간 태스크의 작업 워커·리뷰어가 슬롯의 작업 루트와 슬롯 env 를 준다(설계 5.10.3 의 5,
    5.10.4). 같은 터미널에 넣기(--terminal)에는 넣지 않는다(작업 공간 직무는 고정 에이전트가 없다).
    결과에 horch 의 placement·start_turn·delivery 를 더한다. 실행 기록에는 horch Task·Dispatch 와 함께 그 터미널을 쓴다."""
    slot = pick(state.require(p, tid))
    mode, row, warnings = existing(h, slot)
    if mode == "adopt":
        try:
            with owned(p, tid, pick, expect) as st:
                pick(st).update(horch_task=row["task"], dispatch=row["id"], terminal=row.get("terminal"), error=None)
        except HteamError as exc:
            left_running(exc, {"task": row["task"], "dispatch": row["id"], "state": row["state"]}, h)
            raise
        # 이어 붙인 Dispatch 의 실제 에이전트·모델을 돌려준다. 호출자가 라운드·시도 기록을 그것에 맞춘다
        return {"mode": "adopt", "horch_task": row["task"], "dispatch": row["id"], "terminal": row.get("terminal"),
                "state": row["state"], "outcome": row.get("outcome"), "summary": row.get("summary"),
                "agent": row.get("agent"), "model": row.get("model"), "effort": row.get("effort"),
                "placement": None, "start_turn": row.get("start_turn"), "delivery": row.get("delivery"),
                "warnings": warnings}
    if same_terminal:
        if mode == "retry":
            argv = h.argv("worker-start", "--terminal", same_terminal, "--task", row["task"], "--retry")
        else:
            argv = h.argv("worker-start", "--terminal", same_terminal, "--title", slot["title"], "--spec-file",
                          str(spec_file))
        return _start(p, h, tid, pick, argv, mode, expect, on_fresh, warnings)
    if agent == "codex" and browser.defines(args):
        # 사용자 Codex 의 같은 일을 하는 chrome-devtools 를 이 codex 에서만 끈다(설계 14장). 조회하지 못하면 끄지 않고 알린다
        off, warning = browser.user_off(p.root, args)
        args = [*args, *off]
        if warning:
            warnings.append(warning)
    opts = []
    if model:
        opts += ["--model", model]
    if effort:
        opts += ["--effort", effort]
    keep = ["--keep-open", "--tab", keep_open_tab] if keep_open_tab else []
    hide = ["--hidden"] if hidden else []
    where = ["--cwd", str(cwd or p.root), *workspace.env_args(env or {})]
    if mode == "retry":
        argv = h.argv("worker-start", "--task", row["task"], "--retry", "--agent", agent, *where,
                      *opts, *agent_args(args), *keep, *hide)
    else:
        argv = h.argv("worker-start", "--agent", agent, "--title", slot["title"], "--spec-file", str(spec_file),
                      *where, *opts, *agent_args(args), *keep, *hide)
    return _start(p, h, tid, pick, argv, mode, expect, on_fresh, warnings)


def _start(p, h, tid: str, pick, argv: list[str], mode: str, expect, on_fresh, warnings: list[str]) -> dict:
    """시작 장벽 뒤 horch worker-start 를 부르고 결과를 실행 기록에 쓴다(fresh·retry 공통)."""
    code, data = _run_barrier(p, tid, pick, argv, expect, on_fresh if mode == "fresh" else None)
    ok = code == 0 and data.get("ok")
    try:
        with owned(p, tid, pick, expect) as st:
            s = pick(st)
            if ok:
                s.update(horch_task=data["task"], dispatch=data["dispatch"], terminal=data.get("terminal"), error=None)
            else:
                s["horch_task"] = data.get("task") or s.get("horch_task")
                s["error"] = {"exit": code, **(data.get("error") or {})}
    except HteamError as exc:
        if ok:
            left_running(exc, data, h)
        raise
    if not ok:
        err = data.get("error") or {}
        raise HteamError("launch_failed", f"horch worker-start 실패: {err.get('code')}: {err.get('message')}",
                         MISSING if code == MISSING else FAIL, err.get("hint") or "",
                         data={"horch": data, "warnings": warnings})
    if data.get("warning"):
        warnings.append(data["warning"])
    warnings += list(data.get("warnings") or [])
    return {"mode": mode, "horch_task": data["task"], "dispatch": data["dispatch"], "terminal": data.get("terminal"),
            "state": data.get("state"), "placement": data.get("placement"), "start_turn": data.get("start_turn"),
            "delivery": data.get("delivery"), "warnings": warnings}


REVIEW_ENDED = ("settled", "retained", "abandoned", "released", "launch_failed")


def review_ended(row: dict) -> bool:
    """리뷰 Dispatch 가 끝났나: 끝난 상태이거나 터미널 판정이 exited·lost. 그러면 review-finish 로 마무리한다
    (status 의 reviewing next 와 review 의 기록된 시도 복구가 같은 기준을 쓴다)."""
    return row["state"] in REVIEW_ENDED or row.get("verdict") in ("exited", "lost")


def row_by_id(rows: list[dict], did: str | None) -> dict | None:
    return next((r for r in rows if r["id"] == did), None) if did else None


def slot_row(rows: list[dict], slot: dict) -> dict | None:
    """실행 기록의 현재 horch Dispatch: 기록된 Task 의 최신 시도, Task 가 없으면 실행 키(제목)로 찾은 것
    (기록 전에 죽은 실행자가 띄운 것), 그것도 없으면 기록된 Dispatch."""
    if slot.get("horch_task"):
        return latest_for_task(rows, slot["horch_task"])
    if slot.get("launched"):
        return find_by_title(rows, slot["title"])[0]
    return row_by_id(rows, slot.get("dispatch"))


def slot_rows(rows: list[dict], slot: dict) -> list[dict]:
    """실행 기록의 모든 horch Dispatch(정리 대상 고르기, 설계 6.4): 기록된 Task 의 모든 시도, Task 가 기록되지 않았으면
    그 실행 키(제목)의 모든 Task 의 시도. 둘 다 없으면 horch 를 실행한 적이 없다(시작 장벽)."""
    if slot.get("horch_task"):
        return [r for r in rows if r.get("task") == slot["horch_task"]]
    if slot.get("launched"):
        return [r for r in rows if r.get("title") == slot["title"]]
    return []


CLEANABLE = ("active", "settled", "retained", "abandoned")


def cleanup(h, did: str, *, kill: bool) -> dict:
    """Dispatch 정리(설계 6.4): settled·retained·abandoned 는 release, active 는 kill 이면 abandon --kill 뒤 release.
    고정 Dispatch(persistent)의 active 는 --kill 대신 --keep-terminal 로 abandon 한다(세션 상태는 부르는 쪽이 먼저
    확인했다, 5.9.5). 고정 Dispatch 의 release 는 터미널을 남긴다(herdr-orch 13.5).

    launch_failed 는 건드리지 않는다(horch 가 가드가 거부한 터미널을 정리한다). launching 이면 exit 3 launching,
    active 이고 kill 이 아니면 exit 3 worker_active. 상태는 이 호출에서 새로 묻는다."""
    row = row_by_id(h.workers(), did)
    if row is None:
        return {"dispatch": did, "before": None, "state": None, "outcome": None}
    before = s = row["state"]
    if s == "launching":
        raise HteamError("launching", f"Dispatch {did} 가 아직 launching 이다", CONFLICT, "잠시 뒤 다시 한다")
    if s == "active":
        if not kill:
            raise HteamError("worker_active", f"Dispatch {did} 가 아직 active 다", CONFLICT, "끝내려면 --force")
        h.ok("worker-abandon", "--dispatch", did, "--keep-terminal" if row.get("persistent") else "--kill")
        s = "abandoned"
    if s in ("settled", "retained", "abandoned"):
        h.ok("worker-release", "--dispatch", did)
        s = "released"
    return {"dispatch": did, "before": before, "state": s, "outcome": row.get("outcome")}
