"""horch Task 실행과 복구(설계 5.4, 6.1): 시작 장벽, 제목(실행 키)으로 찾기, 같은 Task 다시 띄우기.

실행 기록(slot)은 상태 파일 안의 dict 다(작업: rounds[-1].work, 리뷰: rounds[-1].reviews[i]).
필드: title(실행 키), horch_task, dispatch, launched(시작 장벽 자식 {pid, started}), error, canceled, cleaned.
"""
from __future__ import annotations

import os

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
        return ("fresh", None, []) if row is None else (classify(row), row, [])
    if slot.get("launched"):
        row, warnings = find_by_title(h.workers(), slot["title"])
        return ("fresh", None, warnings) if row is None else (classify(row), row, warnings)
    return "fresh", None, []


def _run_barrier(p, tid: str, pick, argv: list[str]) -> tuple[int, dict]:
    barrier = Barrier(argv)
    try:
        with state.edit(p, tid) as st:
            pick(st)["launched"] = barrier.record()
    except BaseException:
        barrier.abort()
        raise
    die_at("after_child")
    code, out, err = barrier.go()
    die_at("after_launch")
    return code, parse(out, err)


def launch(p, h, tid: str, pick, *, agent: str, model: str | None, effort: str | None, args: list[str],
           spec_file) -> dict:
    """pick(st) 가 가리키는 실행 기록으로 horch 워커를 띄우거나 이어 붙인다. 실패하면 HteamError(launch_failed)."""
    slot = pick(state.require(p, tid))
    mode, row, warnings = existing(h, slot)
    if mode == "adopt":
        with state.edit(p, tid) as st:
            pick(st).update(horch_task=row["task"], dispatch=row["id"], error=None)
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
    code, data = _run_barrier(p, tid, pick, argv)
    ok = code == 0 and data.get("ok")
    with state.edit(p, tid) as st:
        s = pick(st)
        if ok:
            s.update(horch_task=data["task"], dispatch=data["dispatch"], error=None)
        else:
            s["horch_task"] = data.get("task") or s.get("horch_task")
            s["error"] = {"exit": code, **(data.get("error") or {})}
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
