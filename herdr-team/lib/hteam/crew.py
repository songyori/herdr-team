"""고정 에이전트(설계 5.9, 6단계): state/crew.json, 배정(5.9.4), 처음 띄운 뒤 기록·탭 이름·배치(5.9.2), 같은 터미널에 넣은 뒤
기록(5.9.3), 작업 터미널 확인과 잊기, fix·drop --force 의 세션 닫기(5.9.6), 수정 대기열과 큐 맞추기(5.9.5), 관제의 worker_done
정리와 재확인의 터미널 확인(8.6·8.7 의 2), status 의 crew(8.3).

crew.json 을 쓰는 것은 관제와 그 자식뿐이다(5.9.1). 쓰기는 늘 edit(crew.json.lock flock → 다시 읽기 → 고치기 → 원자 쓰기)다.
태스크 잠금 안에서 edit 를 잡아도 되고, edit 안에서 다른 hteam 잠금을 잡지 않는다.

리셋·인수인계(5.9.7): 묶음 끝 표시(mark_batch_reset)와 `hteam agent reset`(agent_reset)이 reset_pending 을 세우고, 관제가
틱마다 에이전트별 리셋 단계(begin_reset)를 돈다. 진행은 entry 의 resetting(starting → handoff → clear)에 남겨 관제가 어디서
죽어도 이어 한다. 인수인계 Dispatch 의 메시지(handoff_message)와 재확인(handoff_check)이 끝을 맡는다. 입력 유실 재투입
(not_started, 5.9.8)은 라운드 작업 기록의 resend 로 이어 붙인다."""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import time
from typing import Iterator

from . import config, dispatch, drive, herdr, outbox, queue, state
from .errors import FAIL, MISSING, USAGE, HteamError
from .horch import Horch, failure
from .paths import TEMPLATES, find_project, handoff_rel
from .util import (bad_side_file, die_at, dumps, fill, flock, local_age, local_now, now, read_json_strict, write_atomic,
                   write_json)

READY = ("idle", "done")  # 같은 터미널에 넣을 수 있는 세션 상태(herdr-orch 13.4)
FORGOT_LOG = "{name} 작업 터미널이 닫혀 잊음"
STUCK_TEXT = ("{name} 에이전트 작업 세션이 태스크 없이 {word} 로 멈춰 있다. 사용자에게 그 탭을 보고 넘기거나 작업 pane 을 닫아 "
              "달라고 한다(닫으면 관제가 다음 태스크 때 새 세션을 띄운다)")
UNKNOWN_TEXT = ("{name} 에이전트 작업 터미널({terminal}) 상태를 {minutes}분 넘게 확인하지 못했다. 새 세션을 띄우지 않고 기다린다. "
                "사용자에게 그 탭을 확인해 달라고 한다")
STOP_FAILED = ("{tid}: 일하는 중일 수 있는 이전 세션을 닫지 못했다({error}). 다시 띄우지 않았다. 사용자에게 그 에이전트 탭의 "
               "작업 pane 을 닫아 달라고 한 뒤 다시 한다")

# 리셋·인수인계(설계 5.9.7·8.6 원문)
HANDOFF_TEMPLATE = TEMPLATES / "handoff.md"  # 플러그인에서 바로 읽는다(프로젝트에 복사하지 않는다)
CLOSE_LIMIT = 3  # 비우기 실패 뒤 닫기 재시도 상한
UNKNOWN_CANCEL = ("{name} 에이전트의 작업 터미널 상태를 {minutes}분 넘게 알 수 없어 리셋(인수인계)을 취소했다. 터미널을 확인한 "
                  "뒤 필요하면 다시 요청한다")
BUSY_CANCEL = ("{name} 에이전트의 작업 세션이 {minutes}분 넘게 일하는 중이라 리셋(인수인계)을 취소했다. 그 탭을 확인한 뒤 "
               "필요하면 다시 요청한다")
INSERT_CANCEL = ("{name} 에이전트에 인수인계 태스크를 {n}번 넣지 못해 리셋을 취소했다: {code}: {message}. 작업 세션이 자동 압축 "
                 "중이거나 다른 일을 하면 실패한다. 화면을 본 뒤 다시 요청한다")
HANDOFF_FAILED = "{name} 에이전트가 인수인계를 쓰지 못했다: {summary}"
HANDOFF_STUCK = "{name} 에이전트 인수인계가 끝나지 않았다"
CLEAR_FAILED = "{name} 에이전트 세션을 비우지도 닫지도 못했다: {code}: {message}. 사용자에게 그 에이전트 탭의 작업 pane 을 닫아 달라고 한다"
HANDOFF_PAUSED = "{name} 에이전트가 인수인계 중 {word} 로 멈췄다({msg}). 사용자에게 그 탭을 보게 한다"
HANDOFF_GONE = "{name} 에이전트가 인수인계 중 끝났다"
IDLE_TWICE = "done 없이 턴을 두 번 마쳤다"  # 인수인계 두 번째 idle 의 요약
ENDED_NO_DONE = "done 없이 끝났다"  # 재확인이 본 끝난 인수인계(outcome 없음)의 요약
NOT_STARTED_LIMIT = "작업자 시작을 {n}번 확인하지 못했다"


def blank(name: str) -> dict:
    """5.9.1 의 entry 필드 전부를 기본값으로. name 은 부르는 쪽의 짝을 맞추려고 받는다(entry 에 이름 필드는 없다)."""
    return {"terminal": None, "terminal_argv": None, "agent": None, "model": None, "effort": None, "space": None,
            "tab": None, "work_pane": None, "view": None, "task": None, "dispatch": None, "queue": [],
            "since_reset": 0, "reset_tasks": [], "reset_pending": False, "resetting": None, "reset_failures": 0,
            "reset_busy_since": None, "reset_unknown_since": None, "close_failures": 0,
            "terminal_unknown_since": None, "terminal_unknown_asked": False, "launched_at": None,
            "last_reset_at": None, "layout_error": None, "layout_retried": False}


def load(p) -> dict:
    """crew.json. 없으면 {}. 있는데 읽지 못하거나 JSON 객체가 아니면 bad_side_file(exit 1, 손상을 빈 기록으로 보지 않는다)."""
    data = read_json_strict(p.crew_file, {})
    if not isinstance(data, dict):
        raise bad_side_file(p.crew_file, "JSON 객체가 아니다")
    return data


@contextlib.contextmanager
def edit(p) -> Iterator[dict]:
    """crew.json.lock flock 안에서 다시 읽은 dict 를 내주고, 블록이 예외 없이 끝나면 바뀌었을 때만 원자적으로 쓴다."""
    with flock(p.crew_lock):
        data = load(p)
        before = dumps(data)
        yield data
        if dumps(data) != before:
            write_json(p.crew_file, data)


def entry_of(data: dict, name: str) -> dict:
    """data 의 그 에이전트 entry(없으면 blank 를 넣는다). 빠진 필드는 기본값으로 채운다."""
    e = data.setdefault(name, {})
    for key, value in blank(name).items():
        e.setdefault(key, value)
    return e


def entry(p, name: str) -> dict:
    """읽기만: 빠진 필드를 기본값으로 본 entry(없으면 blank)."""
    return {**blank(name), **(load(p).get(name) or {})}


def agent_tab(root, space, name: str) -> str:
    """에이전트 탭 id(5.9.2 의 1): tb + SHA-1(herdr-team\\n<루트>\\n<space>\\ncrew\\n<이름>) 앞 32자."""
    return "tb" + hashlib.sha1(f"herdr-team\n{root}\n{space}\ncrew\n{name}".encode()).hexdigest()[:32]


def name_arg(c) -> str | None:
    """Claude 세션 제목 인자(5.9.2 의 2, X6). Codex 는 첫 리셋의 /clear <이름> 이 제목을 붙인다."""
    return f"--name={c.title} (Claude)" if c.agent == "claude" else None


def round_crew(rd: dict) -> str | None:
    """라운드 기록의 고정 에이전트 이름. "temp"·없음(6단계 앞 라운드)은 None(임시 워커)."""
    name = (rd or {}).get("crew")
    return name if name and name != "temp" else None


def probe(terminal: str, argv: list[str] | None) -> tuple[str, dict | None]:
    """작업 터미널 확인(5.9.3 의 2): ("gone"|"unknown"|"live", hc get 정보). 없으면(not_found)·끝났으면·argv 가 바뀌었으면
    gone, 그 밖의 hc 실패·판정 불가는 unknown. argv 가 None 이면 견주지 않는다."""
    try:
        info = herdr.get(terminal, timeout=3)
    except HteamError as exc:
        return ("gone", None) if exc.data.get("kind") == "not_found" else ("unknown", None)
    verdict = herdr.verdict(info, argv)
    if verdict in ("exited", "lost"):
        return "gone", info
    if verdict == "unverifiable":
        return "unknown", info
    return "live", info


def word(info: dict | None) -> str | None:
    """hc 가 보고한 세션 상태 낱말(idle·done·working·blocked·error, 보고 없음은 None)."""
    status = (info or {}).get("status")
    if isinstance(status, dict):
        return status.get("state")
    return status if isinstance(status, str) else None


def _reason_reset(c) -> str:
    return f"{c.title} 에이전트가 리셋(인수인계) 중이거나 리셋을 기다린다"


def _reason_busy(c) -> str:
    return f"{c.title} 에이전트가 바쁘고 임시 워커가 꺼져 있다([overflow] enabled = false)"


def _reason_unknown(c, terminal: str) -> str:
    return f"{c.title} 에이전트 작업 터미널({terminal}) 상태를 확인하지 못했다"


TEMP = {"kind": "temp", "crew": None}


def place(p, cfg, role: str, worker: str, *, crew_name: str | None = None) -> dict:
    """배정(5.9.4, 5.9.3 의 2). crew_name 을 주면(같은 라운드 복구) 그 에이전트를 보고, 바쁘면 넘치지 않고 기다린다.
    {"kind": "crew", "crew", "mode": "fresh"|"insert"(, "terminal", "entry")}·{"kind": "temp"}·{"kind": "wait", "reason"}."""
    c = cfg.crew.get(crew_name) if crew_name else cfg.crew_of(role)
    if c is None:
        return dict(TEMP)
    e = entry(p, c.name)
    if worker != (e["agent"] if e["terminal"] else c.agent):
        return dict(TEMP)
    if e["resetting"] or (e["reset_pending"] and not e["task"]):
        return {"kind": "wait", "crew": c, "reason": _reason_reset(c)}
    busy = bool(e["task"] or e["queue"] or e["reset_pending"])
    if not busy and e["terminal"]:
        verdict, info = probe(e["terminal"], e["terminal_argv"])
        if verdict == "gone":
            forget(p, c.name)
            return {"kind": "crew", "crew": c, "mode": "fresh"}
        if verdict == "unknown":
            with edit(p) as data:
                cur = entry_of(data, c.name)
                if not cur["terminal_unknown_since"]:
                    cur["terminal_unknown_since"] = local_now()
            return {"kind": "wait", "crew": c, "reason": _reason_unknown(c, e["terminal"])}
        if word(info) in READY:
            if e["terminal_unknown_since"] or e["terminal_unknown_asked"]:
                with edit(p) as data:
                    cur = entry_of(data, c.name)
                    cur["terminal_unknown_since"], cur["terminal_unknown_asked"] = None, False
            return {"kind": "crew", "crew": c, "mode": "insert", "terminal": e["terminal"], "entry": e}
        busy = True
    if busy:
        if cfg.overflow and not crew_name:
            return dict(TEMP)
        return {"kind": "wait", "crew": c, "reason": _reason_busy(c)}
    return {"kind": "crew", "crew": c, "mode": "fresh"}


def _close(p, terminal: str) -> tuple[int, dict]:
    return Horch(p.horch_home).call("terminal-close", "--terminal", terminal, "--abandon")


def forget(p, name: str, *, log: bool = False) -> None:
    """작업 터미널을 잊는다(5.9.3 의 2, 8.7 의 2): 터미널이 있으면 terminal-close --abandon 으로 남은 기록을 정리하고(결과와
    상관없이) entry 의 터미널·맡은 태스크·확인 불가 표시를 비운다. view 는 그대로다(6.5 의 보기 정리만 지운다)."""
    terminal = entry(p, name)["terminal"]
    if terminal:
        _close(p, terminal)
    with edit(p) as data:
        if name not in data:
            return  # 한 번도 띄우지 않은 에이전트는 entry 가 없다(5.9.1)
        e = entry_of(data, name)
        if e["terminal"] == terminal:
            e.update(terminal=None, terminal_argv=None, work_pane=None, task=None, dispatch=None,
                     terminal_unknown_since=None, terminal_unknown_asked=False)
    if log and terminal:
        drive.Drive(p).log(FORGOT_LOG.format(name=name))


def close_session(p, name: str, tid: str) -> None:
    """fix --force·drop --force 의 세션 닫기(5.9.6). terminal-close --abandon 이 성공해야 entry 를 비운다. 실패하면 아무것도
    바꾸지 않고 exit 1 stop_failed."""
    terminal = entry(p, name)["terminal"]
    if terminal:
        code, data = _close(p, terminal)
        if code != 0 or not data.get("ok"):
            err = data.get("error") or {}
            raise HteamError("stop_failed", STOP_FAILED.format(tid=tid, error=f"{err.get('code')}: {err.get('message')}"),
                             FAIL, data={"horch": data})
    with edit(p) as data:
        e = entry_of(data, name)
        if e["terminal"] == terminal:
            e.update(terminal=None, terminal_argv=None, work_pane=None, task=None, dispatch=None)


def detach(p, name: str) -> None:
    """drop --force 가 세션을 닫지 못했을 때(5.9.6): 그 세션에 다음 태스크를 넣지 않게 터미널만 잊는다."""
    with edit(p) as data:
        entry_of(data, name).update(terminal=None, terminal_argv=None, work_pane=None)


def free(p, tid: str) -> None:
    """그 태스크를 맡은 에이전트의 task·dispatch 를 비운다(drop 끝, 5.9.6). since_reset 은 세지 않는다."""
    if holder(p, tid) is None:
        return
    with edit(p) as data:
        for e in data.values():
            if isinstance(e, dict) and e.get("task") == tid:
                e["task"], e["dispatch"] = None, None


def holder(p, tid: str) -> str | None:
    """그 태스크를 지금 맡은 에이전트 이름(entry 의 task 가 tid)."""
    return next((name for name, e in load(p).items() if isinstance(e, dict) and e.get("task") == tid), None)


def after_launch(p, plc: dict, tid: str, rd: dict, res: dict) -> None:
    """working 전이 뒤(5.9.2 의 3–6, 5.9.3 의 4). 처음 띄웠으면 상태 저장이 먼저다: entry 를 쓴 뒤 terminal_argv·탭 이름·배치.
    같은 터미널에 넣었으면 task·dispatch 만 쓰고, 앞 배치가 실패했고 아직 다시 하지 않았으면 배치를 한 번 다시 한다."""
    c, terminal = plc["crew"], res.get("terminal")
    if plc["mode"] != "fresh":
        with edit(p) as data:
            e = entry_of(data, c.name)
            e.update(task=tid, dispatch=res["dispatch"])
            again = bool(e["layout_error"]) and not e["layout_retried"]
            if again:
                e["layout_retried"] = True
        if again:
            layout(p, c.name)
        return
    space = outbox._run(p).get("team_space")
    tab = agent_tab(p.root, space, c.name)
    with edit(p) as data:
        entry_of(data, c.name).update(
            terminal=terminal, agent=rd["agent"], model=rd["model"], effort=rd["effort"], space=space, tab=tab, task=tid,
            dispatch=res["dispatch"], launched_at=local_now(), since_reset=0, reset_tasks=[], terminal_argv=None,
            work_pane=None, layout_error=None, layout_retried=False)
    die_at("crew_saved")  # 테스트: 상태를 쓴 뒤 argv·탭 이름·배치 전에 죽는다(5.9.2 의 3)
    try:
        argv = herdr.get(terminal).get("argv")
    except HteamError:
        argv = None  # 다음 터미널 확인 때 채운다(그동안 argv 를 견주지 않는다)
    if argv is not None:
        with edit(p) as data:
            e = entry_of(data, c.name)
            if e["terminal"] == terminal:
                e["terminal_argv"] = argv
    herdr.rename_tab(tab, f"herdr-team {c.title}")
    layout(p, c.name)


def layout(p, name: str) -> None:
    """배치(5.9.2 의 5·6): 작업 pane 을 찾고, 보기 pane 이 있으면 pane.swap 으로 작업 pane 을 왼쪽에 둔 뒤 doc.get 의 줄 순서로
    확인한다(읽지 못하면 확인을 건너뛴다). work_pane·layout_error 를 쓴다. 실패는 태스크를 막지 않고 로그 한 줄."""
    e = entry(p, name)
    terminal, view = e["terminal"], e["view"] or {}
    error = None
    pane = herdr.pane_of(terminal)
    if pane is None:
        error = "작업 pane 을 찾지 못했다"
    elif view.get("pane"):
        try:
            herdr.swap(pane, view["pane"])
        except HteamError as exc:
            error = exc.message
        else:
            row = herdr.tab_row(e["tab"])
            if row and terminal in row and view.get("terminal") in row and \
                    row.index(terminal) > row.index(view["terminal"]):
                error = "작업 pane 이 왼쪽에 오지 않았다"
    with edit(p) as data:
        cur = entry_of(data, name)
        if cur["terminal"] == terminal:
            cur["work_pane"], cur["layout_error"] = pane, error
    if error:
        drive.Drive(p).log(f"{name} 배치 실패: {error}")


def work_done(p, tid: str, did: str) -> str | None:
    """관제의 작업 worker_done(5.9.3 끝, 8.6): 그 태스크를 맡은 에이전트를 비우고, 리셋 뒤 처음 끝낸 태스크면 since_reset 을
    센다(같은 태스크의 수정 라운드는 다시 세지 않는다). 그 에이전트 이름, 없으면 None."""
    with edit(p) as data:
        for name in list(data):
            if not isinstance(data[name], dict) or data[name].get("task") != tid:
                continue
            e = entry_of(data, name)
            e["task"], e["dispatch"] = None, None
            if tid not in e["reset_tasks"]:
                e["reset_tasks"].append(tid)
                e["since_reset"] = (e["since_reset"] or 0) + 1
            return name
    return None


# --- 수정 대기열(5.9.5) ---
def merged(old: dict | None, note: str | None, supplement: str | None,
           force_round: bool) -> tuple[str | None, str | None, bool]:
    """대기 수정(queued_fix)과 새 fix 요청의 병합(5.9.5): note 는 앞 지시 뒤에 새 지시를 줄마다 잇고(같은 줄은 한 번),
    supplement 는 새 값(없으면 앞 값), force_round 는 OR. old 가 없으면 새 요청 그대로."""
    if not old:
        return note, supplement, bool(force_round)
    lines = old["note"].split("\n") if old.get("note") else []
    for line in (note or "").split("\n"):
        if line and line not in lines:
            lines.append(line)
    return ("\n".join(lines) or None, supplement if supplement is not None else old.get("supplement"),
            bool(old.get("force_round")) or bool(force_round))


def enqueue(p, tid: str, name: str, *, note: str | None, supplement: str | None, force_round: bool,
            request: str | None) -> dict:
    """태스크의 queued_fix(기준 기록)를 먼저 쓰고 그다음 에이전트 queue 끝에 넣는다(이미 있으면 끝으로 옮긴다). 두 번째 fix 는
    note 를 줄마다 앞 note 뒤에 잇고(같은 줄은 한 번), supplement 는 이번 값(없으면 앞 값), force_round 는 OR, at 은 지금,
    request 는 처음 값이다. 같은 쓰기에서 관제 fix 이어 하기 표시(drive_fix)를 지운다(줄을 섰으면 이어 할 것이 없다)."""
    with state.edit(p, tid) as st:
        old = st.get("queued_fix") or None
        note, supplement, force_round = merged(old, note, supplement, force_round)
        st["queued_fix"] = {"note": note, "supplement": supplement, "force_round": force_round, "at": now(),
                            "request": old.get("request") if old else request}
        st.pop("drive_fix", None)
    with edit(p) as data:
        queue = entry_of(data, name)["queue"]
        if tid in queue:
            queue.remove(tid)
        queue.append(tid)
    return {"id": tid, "status": "queued", "agent": name}


def unqueue(p, tid: str) -> None:
    """모든 에이전트 queue 에서 그 태스크를 뺀다(없으면 쓰지 않는다)."""
    if not any(isinstance(e, dict) and tid in (e.get("queue") or []) for e in load(p).values()):
        return
    with edit(p) as data:
        for e in data.values():
            if isinstance(e, dict) and tid in (e.get("queue") or []):
                e["queue"] = [t for t in e["queue"] if t != tid]


def clear_queued(p, tid: str) -> None:
    """태스크의 queued_fix 를 지우고 큐에서 뺀다(드레인 거부, 5.9.5)."""
    with state.edit(p, tid) as st:
        st.pop("queued_fix", None)
    unqueue(p, tid)


def sync_queues(p) -> None:
    """큐 맞추기(5.9.5 끝, 재확인마다): 큐에서 queued_fix 없는 태스크를 빼고, queued_fix 가 있는데 큐에 없는 태스크를
    queued_fix.at 순서로 그 라운드의 에이전트 큐 끝에 더한다."""
    wanted: dict[str, tuple[str, str]] = {}  # 태스크 → (에이전트, queued_fix.at)
    for st in state.all_states(p):
        name = round_crew(state.current_round(st) or {})
        if st.get("queued_fix") and name:
            wanted[st["id"]] = (name, st["queued_fix"].get("at") or "")
    with edit(p) as data:
        for e in data.values():
            if isinstance(e, dict):
                e["queue"] = [t for t in e.get("queue") or [] if t in wanted]
        for _, tid, name in sorted((at, tid, name) for tid, (name, at) in wanted.items()
                                   if tid not in ((data.get(name) or {}).get("queue") or [])):
            entry_of(data, name)["queue"].append(tid)


# --- 재확인(8.7 의 2) ---
def check_terminals(d) -> list[tuple[str, str | None, str, str]]:
    """고정 에이전트 터미널 확인. 끝났거나 없거나 lost 면 잊고(로그 한 번), 그때 맡고 있던 태스크를 (태스크, Dispatch, 터미널,
    exited|lost) 로 돌려준다. 확인 불가는 처음 시각을 적고 LIVENESS_UNKNOWN_S 넘게 이어지면 decide 한 번. 확인되면 argv 를
    채우고(없을 때) idle·done·working 이면 두 표시를 지운다. 맡은 태스크 없이 blocked·error·보고 없음이 NO_STATUS_GRACE_S
    넘게 이어지면 decide 한 번."""
    p = d.p
    gone: list[tuple[str, str | None, str, str]] = []
    for name, raw in load(p).items():
        if not isinstance(raw, dict) or not raw.get("terminal"):
            continue
        e = {**blank(name), **raw}
        terminal = e["terminal"]
        verdict, info = probe(terminal, e["terminal_argv"])
        if verdict == "gone":
            forget(p, name, log=True)
            if e["task"]:
                kind = herdr.verdict(info, e["terminal_argv"]) if info is not None else "exited"
                gone.append((e["task"], e["dispatch"], terminal, kind))
            continue
        if verdict == "unknown":
            since = e["terminal_unknown_since"]
            if not since:
                _mark(p, name, terminal, terminal_unknown_since=local_now())
                continue
            age = local_age(since)
            if age is not None and age >= drive.LIVENESS_UNKNOWN_S and not e["terminal_unknown_asked"]:
                d.decide("escalation", None, UNKNOWN_TEXT.format(name=name, terminal=terminal, minutes=int(age // 60)))
                _mark(p, name, terminal, terminal_unknown_asked=True)
            continue
        fields: dict = {}
        if e["terminal_argv"] is None and info.get("argv") is not None:
            fields["terminal_argv"] = info["argv"]
        w = word(info)
        if w in (*READY, "working"):
            if e["terminal_unknown_since"] or e["terminal_unknown_asked"]:
                fields.update(terminal_unknown_since=None, terminal_unknown_asked=False)
        elif not e["task"] and not e["terminal_unknown_asked"]:
            ms = info.get("status_ms")
            age = time.time() - ms / 1000 if isinstance(ms, (int, float)) else local_age(e["launched_at"])
            if age is not None and age >= drive.NO_STATUS_GRACE_S:
                d.decide("escalation", None, STUCK_TEXT.format(name=name, word=w or "보고 없음"))
                fields["terminal_unknown_asked"] = True
        if fields:
            _mark(p, name, terminal, **fields)
    return gone


def _mark(p, name: str, terminal: str, **fields) -> None:
    """entry 의 터미널이 그대로일 때만 fields 를 쓴다."""
    with edit(p) as data:
        e = entry_of(data, name)
        if e["terminal"] == terminal:
            e.update(fields)


# --- status(8.3) ---
def status_rows(p, cfg) -> list[dict]:
    """설정 순서의 고정 에이전트. entry 가 없거나 비면 설정 값. hc 를 부르지 않는다."""
    data = load(p)
    rows = []
    for name, c in cfg.crew.items():
        e = {**blank(name), **(data.get(name) or {})}
        rows.append({"name": name, "title": c.title, "agent": e["agent"] or c.agent, "model": e["model"] or c.model,
                     "roles": list(c.roles), "terminal": e["terminal"], "task": e["task"], "queue": list(e["queue"]),
                     "reset_pending": e["reset_pending"], "resetting": e["resetting"], "since_reset": e["since_reset"]})
    return rows


# --- 리셋 표시(5.9.7 의 시점) ---
def _set(p, name: str, **fields) -> None:
    with edit(p) as data:
        entry_of(data, name).update(fields)


def mark_batch_reset(p) -> list[str]:
    """묶음 끝(5.9.7): since_reset ≥ 1 인 에이전트마다 reset_pending = True. 그 이름(crew.json 순서, 멱등). 묶음 처리가 후속
    태스크 만들기보다 먼저 부른다(후속 태스크는 배정이 기다리게 해 리셋 뒤 새 세션이 받는다)."""
    names: list[str] = []
    with edit(p) as data:
        for name, raw in data.items():
            if isinstance(raw, dict) and (raw.get("since_reset") or 0) >= 1:
                entry_of(data, name)["reset_pending"] = True
                names.append(name)
    return names


def _known(cfg, name: str) -> None:
    if name not in cfg.crew:
        raise HteamError("unknown_crew", f"고정 에이전트가 아니다: {name}. 가능한 이름: {', '.join(cfg.crew) or '없음'}", USAGE)


def agent_reset(p, cfg, name: str, *, request: str | None = None) -> dict:
    """`hteam agent reset <이름>`(5.9.7): reset_pending 만 쓴다(since_reset 조건 없음, entry 가 없으면 만든다). request 는
    큐 요청 id(재실행 막기의 기록, 7.1). 다시 해도 결과가 같다."""
    _known(cfg, name)
    with edit(p) as data:
        e = entry_of(data, name)
        e["reset_pending"] = True
        if request:
            e["reset_request"] = request
    return {"name": name, "reset_pending": True}


# --- 리셋 단계(5.9.7 의 순서, 관제 틱 7) ---
def _call(d, *args: str) -> tuple[int, dict]:
    """horch 결과(code, data). 의존 프로그램 없음(exit 12)은 관제를 끝내도록 올린다(8.5)."""
    code, data = d.horch().call(*args)
    if code == MISSING:
        raise failure(code, data, args)
    return code, data


def begin_reset(d, cfg, name: str) -> None:
    """에이전트 하나의 리셋 단계. resetting 의 단계(clear·starting·handoff)를 먼저 잇고, 아니면 reset_pending 이고 맡은 일이
    없을 때 작업 터미널을 보고 인수인계를 넣는다(일하는 중·확인 불가는 30분까지 미룬다)."""
    p = d.p
    raw = load(p).get(name)
    if not isinstance(raw, dict):
        return
    e = {**blank(name), **raw}
    step = (e["resetting"] or {}).get("step")
    if step == "clear":
        return _clear(d, name)
    if step == "starting":
        return _resume_start(d, cfg, name, e)
    if step == "handoff":
        return None  # 끝은 인수인계 Dispatch 의 메시지나 재확인이 본다
    if not e["reset_pending"] or e["task"] or e["queue"]:
        if e["reset_busy_since"] or e["reset_unknown_since"]:
            _set(p, name, reset_busy_since=None, reset_unknown_since=None)  # 연속 구간이 끊겼다
        return None
    if not e["terminal"]:
        return _skip(d, name)
    verdict, info = probe(e["terminal"], e["terminal_argv"])
    if verdict == "gone":
        return _skip(d, name)
    w = word(info) if verdict == "live" else None
    if w in READY:
        return _insert(d, cfg, name, e)
    busy = w in ("working", "blocked")  # 그 밖(hc 실패·판정 불가·error·보고 없음)은 확인 불가
    field, other, limit = (("reset_busy_since", "reset_unknown_since", drive.RESET_BUSY_S) if busy
                           else ("reset_unknown_since", "reset_busy_since", drive.RESET_UNKNOWN_S))
    since = e[field]
    if not since:
        _set(p, name, **{field: local_now(), other: None})
        if busy:
            d.log(f"{name} 리셋 미룸: 작업 세션이 일하는 중({w})")
        return None
    age = local_age(since)
    if age is None or age < limit:
        return None
    _set(p, name, reset_pending=False, reset_busy_since=None, reset_unknown_since=None)
    d.decide("escalation", None, (BUSY_CANCEL if busy else UNKNOWN_CANCEL).format(name=name, minutes=int(age // 60)))


def _skip(d, name: str) -> None:
    """비울 세션이 없다(터미널 없음·끝남·lost·terminal_gone): 리셋을 마친 것으로 둔다."""
    _set(d.p, name, reset_pending=False, since_reset=0, reset_tasks=[], terminal=None, terminal_argv=None,
         work_pane=None, resetting=None, reset_busy_since=None, reset_unknown_since=None)
    d.log(f"{name} 리셋 시작: skipped")


def _next_title(p, name: str) -> str:
    """처음 넣는 인수인계의 제목(실행 키): state/crew/<이름>-handoff-s*.md 의 가장 큰 번호 + 1(없으면 1)."""
    pattern = re.compile(re.escape(name) + r"-handoff-s(\d+)\.md")
    found = [int(m.group(1)) for f in (p.crew_dir.iterdir() if p.crew_dir.is_dir() else [])
             if (m := pattern.fullmatch(f.name))]
    return f"[handoff] {name} s{max(found, default=0) + 1}"


def _insert(d, cfg, name: str, e: dict, title: str | None = None) -> None:
    """인수인계 넣기(5.9.7 의 3): 사양을 쓰고 resetting = starting 을 먼저 쓴 뒤 같은 터미널에 넣는다. title 이 있으면(starting
    이어 붙이기) 그 번호를 그대로 쓴다."""
    p = d.p
    terminal = e["terminal"]
    if not terminal:
        return _skip(d, name)
    title = title or _next_title(p, name)
    spec = p.crew_dir / f"{name}-handoff-s{title.rsplit(' s', 1)[1]}.md"
    write_atomic(spec, fill(HANDOFF_TEMPLATE.read_text(encoding="utf-8"), agent=name, agent_title=cfg.crew[name].title,
                            path=handoff_rel(name)))
    _set(p, name, resetting={"step": "starting", "title": title, "at": local_now()}, reset_busy_since=None,
         reset_unknown_since=None)
    code, data = _call(d, "worker-start", "--terminal", terminal, "--title", title, "--spec-file", str(spec))
    if code == 0 and data.get("ok"):
        _set(p, name, resetting={"step": "handoff", "dispatch": data["dispatch"], "title": title, "at": local_now()},
             reset_failures=0)
        d.log(f"{name} 리셋 시작: handoff")
        return None
    err = data.get("error") or {}
    ecode, message = err.get("code") or f"exit_{code}", err.get("message") or ""
    if ecode == "terminal_gone":
        return _skip(d, name)
    n = entry(p, name)["reset_failures"] + 1
    d.log(f"{name} 리셋 시작: failed({n}/{drive.RESET_FAIL_LIMIT}): {ecode}: {message}")
    if n < drive.RESET_FAIL_LIMIT:
        return _set(p, name, resetting=None, reset_failures=n)  # 다음 틱에 다시 한다
    _set(p, name, resetting=None, reset_pending=False, reset_failures=0)
    d.decide("escalation", None, INSERT_CANCEL.format(name=name, n=n, code=ecode, message=message))


def _resume_start(d, cfg, name: str, e: dict) -> None:
    """starting 이어 붙이기(관제가 넣는 중에 죽었다): 그 제목의 launch_failed 가 아닌 Dispatch 가 있으면 handoff 로, 없으면
    같은 제목으로 다시 넣는다(5.4 의 실행 키와 같은 규칙)."""
    title = e["resetting"].get("title")
    rows = [r for r in d.horch().workers() if title and r.get("title") == title and r.get("state") != "launch_failed"]
    if not rows:
        return _insert(d, cfg, name, e, title)
    row = max(rows, key=lambda r: (r.get("created_at") or "", r["id"]))
    _set(d.p, name, resetting={"step": "handoff", "dispatch": row["id"], "title": title, "at": local_now()},
         reset_failures=0)
    d.log(f"{name} 리셋 시작: handoff")


def _reset_done(d, name: str, text: str, **fields) -> None:
    _set(d.p, name, resetting=None, reset_pending=False, since_reset=0, reset_tasks=[], last_reset_at=local_now(),
         reset_failures=0, close_failures=0, **fields)
    d.log(f"{name} 리셋: {text}")


def _clear(d, name: str) -> None:
    """비우기와 닫기 재시도(clear 단계, 어디서 죽어도 이어 한다). 비우기 신호가 없거나 실패하면 비웠다고 믿지 않고 터미널을
    닫는다(다음 태스크가 새 세션을 띄운다). 닫지 못하면 다음 틱에 닫기만 다시 하고, 세 번째면 decide 뒤 터미널을 잊는다."""
    p = d.p
    e = entry(p, name)
    res = e["resetting"] or {}
    reason, terminal = res.get("clear_error"), e["terminal"]
    if not terminal:  # 그 사이 재확인이 끝난 터미널을 잊었다: 비울 세션이 없다
        return _reset_done(d, name, f"new_terminal({reason or 'terminal_gone'})", terminal_argv=None, work_pane=None)
    if e["close_failures"] == 0 and reason is None:  # 아직 비우기를 하지 않았다
        args = ["terminal-reset", "--terminal", terminal]
        if e["agent"] == "codex":
            args += ["--name", name]  # /clear <이름> 이 Codex 대화 이름(제목)을 고정한다(X3b)
        timeout = os.environ.get("HTEAM_RESET_TIMEOUT_MS") or str(drive.RESET_CLEAR_TIMEOUT_MS)
        code, data = _call(d, *args, "--timeout-ms", timeout)
        if code == 0 and data.get("ok"):
            return _reset_done(d, name, f"reset(turn {data.get('turn')}, {data.get('seconds')}초)")
        reason = (data.get("error") or {}).get("code") or f"exit_{code}"
        _set(p, name, resetting={**res, "clear_error": reason})
    code, data = _call(d, "terminal-close", "--terminal", terminal)  # 진행 중 Dispatch 가 없으니 --abandon 없이
    if code == 0 and data.get("ok"):
        return _reset_done(d, name, f"new_terminal({reason})", terminal=None, terminal_argv=None, work_pane=None)
    n = e["close_failures"] + 1
    if n < CLOSE_LIMIT:
        return _set(p, name, close_failures=n)  # resetting 을 남겨 다음 틱에 닫기만 다시
    err = data.get("error") or {}
    d.decide("escalation", None, CLEAR_FAILED.format(name=name, code=err.get("code") or f"exit_{code}",
                                                     message=err.get("message") or ""))
    _set(p, name, resetting=None, reset_pending=False, close_failures=0, terminal=None, terminal_argv=None,
         work_pane=None)


# --- 인수인계 끝(5.9.7 의 4, 8.6 의 인수인계 줄, 8.7 의 3) ---
def _handoff_end(d, name: str, did: str, outcome, summary) -> None:
    """인수인계 Dispatch 가 끝났다: 성공이면 release 뒤 clear 단계를 먼저 쓰고 비운다. 실패면 정리하고 decide."""
    if outcome != "succeeded":
        return _handoff_failed(d, name, did, HANDOFF_FAILED.format(name=name, summary=str(summary or "")[:200]))
    dispatch.cleanup(d.horch(), did, kill=False)  # 고정 Dispatch 라 터미널은 남는다
    with edit(d.p) as data:
        e = entry_of(data, name)
        e["resetting"] = {**(e["resetting"] or {}), "step": "clear"}
    _clear(d, name)


def _handoff_failed(d, name: str, did: str, text: str) -> None:
    """인수인계 실패 정리: 아직 active 면 --keep-terminal 로 버린 뒤 release. 세션은 비우지 않는다(since_reset 그대로)."""
    dispatch.cleanup(d.horch(), did, kill=True)
    _set(d.p, name, resetting=None, reset_pending=False)
    d.decide("escalation", None, text, commands=[f"hteam agent reset {name}"])


def _handoff_holder(p, did: str | None) -> str | None:
    """resetting.dispatch 가 did 인 에이전트 이름."""
    if not did:
        return None
    return next((name for name, e in load(p).items()
                 if isinstance(e, dict) and (e.get("resetting") or {}).get("dispatch") == did), None)


def handoff_message(d, m: dict) -> bool:
    """인수인계 Dispatch 의 메시지면 처리하고 True(8.6). 아니면 False(태스크 메시지로 간다)."""
    from .coord import _body  # coord 가 이 모듈을 쓴다
    body = _body(m)
    did = m.get("dispatch") or body.get("dispatch")
    name = _handoff_holder(d.p, did)
    if name is None:
        return False
    kind, what = m.get("type"), body.get("kind")
    if kind == "worker_done":
        _handoff_end(d, name, did, body.get("outcome"), body.get("summary"))
    elif kind == "observed" and what == "idle":
        res = entry(d.p, name)["resetting"] or {}
        if res.get("idle_asked"):
            _handoff_failed(d, name, did, HANDOFF_FAILED.format(name=name, summary=IDLE_TWICE))
        else:
            d.horch().ok("send", "--to", f"dispatch:{did}", "--subject", drive.IDLE_SUBJECT,
                         f"--body={drive.IDLE_TEXT}")
            _set(d.p, name, resetting={**res, "idle_asked": True})
    elif kind == "observed" and what in ("blocked", "error"):
        d.decide("escalation", None, HANDOFF_PAUSED.format(name=name, word=what, msg=str(body.get("msg") or "")[:120]))
    elif kind == "observed" and what in ("exited", "lost"):
        forget(d.p, name)  # terminal-close --abandon 으로 남은 기록 정리. 다음 세션은 새로 뜬다
        _set(d.p, name, resetting=None, reset_pending=False, since_reset=0, reset_tasks=[])
        d.decide("escalation", None, HANDOFF_GONE.format(name=name))
    else:
        d.log(f"{name} 인수인계 Dispatch 의 {kind} 무시: {did}")
    return True


def handoff_check(d) -> None:
    """끝나지 않은 인수인계 정리(8.7 의 3): handoff 단계 entry 마다 그 Dispatch 행을 본다. 끝났으면 outcome 대로 끝내고,
    아직 active 인데 resetting.at 에서 RESET_STUCK_S 가 지났으면 버린 뒤 실패로 정리한다. 에이전트마다 reset:<이름> 격리."""
    pending = [(name, e["resetting"]) for name, e in load(d.p).items()
               if isinstance(e, dict) and (e.get("resetting") or {}).get("step") == "handoff"]
    if not pending:
        return
    rows = d.horch().workers()
    for name, res in pending:
        d.isolated(f"reset:{name}", lambda name=name, res=res: _check_handoff(d, name, res, rows))


def _check_handoff(d, name: str, res: dict, rows: list[dict]) -> None:
    did = res.get("dispatch")
    row = dispatch.row_by_id(rows, did)
    if row is None:
        return
    s = row["state"]
    if s in ("settled", "retained") or (s == "released" and row.get("outcome")):
        _handoff_end(d, name, did, row.get("outcome"), row.get("summary"))
    elif s in ("abandoned", "released", "launch_failed") or row.get("verdict") in ("exited", "lost"):
        _handoff_failed(d, name, did, HANDOFF_FAILED.format(name=name, summary=ENDED_NO_DONE))
    elif s == "active":
        age = local_age(res.get("at"))
        if age is not None and age >= drive.RESET_STUCK_S:
            _handoff_failed(d, name, did, HANDOFF_STUCK.format(name=name))


# --- 입력 유실 재투입(5.9.8) ---
def not_started(d, tid: str, did: str) -> None:
    """observed not_started(넣은 입력이 들어가지 않았다): 작업 터미널이 live 이고 idle·done 일 때만 같은 라운드를 같은 터미널에
    다시 넣는다. 재투입 예약 resend 를 먼저 쓰고, 새 Dispatch 를 기록하거나 실패 decide 를 올릴 때까지 지우지 않는다. 남은
    resend 는 이 처리(다시 온 메시지)와 재확인이 잇는다. 세 번째면 다시 넣지 않고 decide."""
    p = d.p
    st = state.require(p, tid)
    rd = state.current_round(st)
    if rd is None:
        return
    work = rd["work"]
    resend = work.get("resend")
    abandon = True
    if resend:  # 앞 재투입이 끝나기 전에 관제가 죽었거나 터미널을 확인하지 못했다
        row = dispatch.latest_for_task(d.horch().workers(), work.get("horch_task"))
        if row is not None and row["id"] != resend["from"]:
            if row["state"] == "launch_failed":
                d.procedure_failed(tid, HteamError("resend_failed", f"{tid} 에 다시 넣은 Dispatch {row['id']} 가 "
                                                                    "launch_failed 다", FAIL))
                return _drop_resend(p, tid)
            return _resent(d, tid, row, resend["n"])  # 새 Dispatch 를 띄운 뒤 기록 전에 죽었다: 이어 붙인다
        did, n = resend["from"], resend["n"]
        abandon = row is None or row["state"] != "abandoned"
    name = round_crew(rd)
    e = entry(p, name) if name else None
    if not e or not e["terminal"]:
        return
    verdict, info = probe(e["terminal"], e["terminal_argv"])
    if verdict != "live" or word(info) not in READY:
        return  # 일하는 중은 입력이 들어간 증거다. 확인 불가·보고 없음은 resend 를 두어 다음 재확인이 다시 본다
    if not resend:
        n = (st.get("unknown_starts") or 0) + 1
        if n >= drive.UNKNOWN_START_LIMIT:
            d.decide("escalation", tid, NOT_STARTED_LIMIT.format(n=n),
                     commands=[d._fix_cmd(st), d._fix_cmd(st, force=True), f"hteam drop {tid}"])
            return
        with state.edit(p, tid) as cur:
            state.current_round(cur)["work"]["resend"] = {"from": did, "n": n}
    try:
        if abandon:
            d.horch().ok("worker-abandon", "--dispatch", did, "--keep-terminal")
        die_at("resend_abandoned")  # 테스트: 앞 Dispatch 를 버린 뒤 새 Dispatch 를 띄우기 전에 죽는다
        res = d.horch().ok("worker-start", "--terminal", e["terminal"], "--task", work["horch_task"])
        die_at("resend_started")  # 테스트: 새 Dispatch 를 띄운 뒤 기록 전에 죽는다
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        d.procedure_failed(tid, exc)
        return _drop_resend(p, tid)
    _resent(d, tid, {"id": res["dispatch"], "start_turn": res.get("start_turn"), "delivery": res.get("delivery")}, n)


def _resent(d, tid: str, row: dict, n: int) -> None:
    """재투입한 Dispatch 를 기록한다: 한 상태 쓰기에서 작업 Dispatch·start_turn·delivery·unknown_starts, resend 를 지운다. 그
    다음 맡은 에이전트의 dispatch."""
    with state.edit(d.p, tid) as st:
        rd = state.current_round(st)
        rd["work"]["dispatch"] = row["id"]
        for key in ("start_turn", "delivery"):
            if row.get(key) is not None:
                rd[key] = row[key]
        rd["work"].pop("resend", None)
        st["unknown_starts"] = n
    name = round_crew(rd)
    if name:
        with edit(d.p) as data:
            e = entry_of(data, name)
            if e["task"] == tid:
                e["dispatch"] = row["id"]
    d.log(f"{tid} not_started: resent({n})")


def _drop_resend(p, tid: str) -> None:
    with state.edit(p, tid) as st:
        state.current_round(st)["work"].pop("resend", None)


# --- CLI ---
def _cmd_agent_reset(args) -> dict:
    """큐 명령(7.1): 관제(와 자식)에서는 바로, 메인에서는 이름 검사 뒤 요청 큐."""
    p = find_project(args.root)
    cfg = config.load(p)
    return queue.route(p, "agent reset", {"name": args.name}, lambda req: agent_reset(p, cfg, args.name),
                       check=lambda: _known(cfg, args.name))


def register(sub) -> None:
    agent = sub.add_parser("agent")
    asub = agent.add_subparsers(dest="agent_cmd", required=True, parser_class=agent.__class__)
    s = asub.add_parser("reset")
    s.add_argument("name")
    s.set_defaults(func=_cmd_agent_reset)
