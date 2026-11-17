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
from datetime import datetime
from typing import Iterator

from . import config, dispatch, drive, herdr, outbox, queue, state
from .errors import FAIL, MISSING, USAGE, HteamError
from .horch import Horch, failure, version_confirmed
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
# 인수인계 중 대리 보고 쓰기 실패(설계 8.6 표·8.14 의 5, 12단계): 끝나지 않은 인수인계 정리의 실패 갈래(_handoff_failed)로 멈춘다
RELAY_HANDOFF = "{name} 에이전트 인수인계 중 상태를 Herdr 에 보낼 수 없어(대리 보고 쓰기 실패) 인수인계를 멈췄다"
# 보고 없는 세션 닫기·다시 묶기 앞당기기·옛 세션 바꾸기(설계 5.9.9 의 2–4 원문, 12단계). 닫기 실패 줄은 로그만이다
QUIET_CLOSED = "{name} 보고 없는 세션 닫음: 다음 태스크가 새 세션으로 뜬다"
CLOSE_QUIET_FAILED = "{name} 세션 닫기 실패({n}/{limit}): {code}: {message}"
REHOME_EARLY = "{name} 다시 묶기: 메인 {main} 아래가 아니다(parent {parent}). {what}"
RELAY_REPLACE = "{name} 옛 세션 바꾸기: 대리 보고·Stop 기록이 없는 세션이다. {what}"
SESSION_MARKS = ("relay_ready", "relay_upgrade")  # 그 작업 세션의 표시(5.9.1): terminal 을 비울 때 함께 지운다


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
        for e in data.values():  # 12단계(5.9.1): terminal 이 빈 entry 에는 세션 표시가 남지 않는다(비우는 곳 모두에 맞는다)
            if isinstance(e, dict) and not e.get("terminal"):
                for key in SESSION_MARKS:
                    e.pop(key, None)
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
    {"kind": "crew", "crew", "mode": "fresh"|"insert"(, "terminal", "entry")}·{"kind": "temp"}·{"kind": "wait", "reason"}.
    worktree 모드의 작업 공간 직무는 늘 임시 워커다(5.9.4 의 0. 설정을 다시 보지 않는다)."""
    if cfg.workspace.covers(role):
        return dict(TEMP)
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
        if unreported(p, e, info) or e["close_failures"]:
            # Codex 커밋 리뷰 6224f9b: 옛 세션 바꾸기·다시 묶기 앞당기기의 닫기가 실패해 close_failures 가 남은 세션도 보고 없는
            # 세션처럼 넣지 않는다. 같은 세션에 넣으면 after_launch 가 close_failures 를 0 으로 되돌려 닫기가 영영 다시
            # 되지 않는다(표시 relay_upgrade·rehome_main 은 한 번 규칙이라 남는다). 닫고 새 세션으로 띄운다(5.9.9 의 배정 길)
            # 12단계(5.9.9 의 2): 대리 보고도 없는 세션에는 넣지 않는다. 맡은 일이 없으니 인수인계 없이 닫고 이번 라운드는
            # 새 세션으로 띄운다. 닫지 못했으면 확인 불가와 같이 기다린다
            if close_unreported(p, c.name, e):
                return {"kind": "crew", "crew": c, "mode": "fresh"}
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
            e.update(task=tid, dispatch=res["dispatch"], close_failures=0)
            e["assigned_since_reset"] = (e.get("assigned_since_reset") or 0) + 1  # 5.9.9 의 3: 리셋 뒤 넣은 태스크
            again = bool(e["layout_error"]) and not e["layout_retried"]
            if again:
                e["layout_retried"] = True
        if again:
            layout(p, c.name)
        return
    space = outbox._run(p).get("team_space")
    tab = agent_tab(p.root, space, c.name)
    # 12단계(5.9.2 의 3, 설계 3.3): herdr-orch 0.5.0 이상을 확인한 때만 relay_ready(launch-guard 가 HORCH_HOME 을 넣어 띄운
    # 세션). 확인하지 못하면 적지 않아 옛 세션으로 다룬다(5.9.9 의 4). 잠금 밖에서 묻는다(horch 를 부를 수 있다)
    ready = version_confirmed(p.horch_home)
    with edit(p) as data:
        e = entry_of(data, c.name)
        e.update(
            terminal=terminal, agent=rd["agent"], model=rd["model"], effort=rd["effort"], space=space, tab=tab, task=tid,
            dispatch=res["dispatch"], launched_at=local_now(), since_reset=0, reset_tasks=[], terminal_argv=None,
            work_pane=None, layout_error=None, layout_retried=False, assigned_since_reset=1, close_failures=0)
        e.pop("relay_upgrade", None)
        if ready:
            e["relay_ready"] = True
        else:
            e.pop("relay_ready", None)
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


def view_pane_of(p, name: str, view: dict) -> str | None:
    """기록에 pane 이 없는 보기(설계 6.5 의 11단계: hc run 직후 앱이 아직 pane 을 붙이지 않았다)의 pane 을 herdr-app ls 에서
    찾는다. 찾으면 그 보기가 그대로일 때 crew.json 의 view.pane 을 채운다. 보기 터미널이 없거나 못 찾으면 None."""
    if not view.get("terminal"):
        return None
    pane = herdr.pane_of(view["terminal"])
    if pane:
        with edit(p) as data:
            cur = entry_of(data, name)
            if cur.get("view") == view:
                cur["view"] = {**view, "pane": pane}
    return pane


def layout(p, name: str) -> None:
    """배치(5.9.2 의 5·6): 작업 pane 을 찾고, 보기 pane 이 있으면 pane.swap 으로 작업 pane 을 왼쪽에 둔 뒤 doc.get 의 줄 순서로
    확인한다(읽지 못하면 확인을 건너뛴다). work_pane·layout_error 를 쓴다. 실패는 태스크를 막지 않고 로그 한 줄.
    11단계: 보기의 pane 이 기록에 없으면 view_pane_of 로 찾는다(리뷰 중 새로 뜬 작업 pane 이 보기 pane 오른쪽에 남지 않게)."""
    e = entry(p, name)
    terminal, view = e["terminal"], e["view"] or {}
    error = None
    pane = herdr.pane_of(terminal)
    view_pane = (view.get("pane") or view_pane_of(p, name, view)) if pane is not None else None
    if pane is None:
        error = "작업 pane 을 찾지 못했다"
    elif view_pane:
        try:
            herdr.swap(pane, view_pane)
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
    넘게 이어지면 decide 한 번.
    12단계(5.9.9 의 2, 8.7 의 2a): 맡은 태스크가 없을 때 대리 보고도 없는 세션(unreported. 쓰기 실패는 relay-status)을
    가른다. 리셋 중이 아니면 인수인계 없이 닫고(close_quiet), 리셋 중이면 두며 어느 쪽이든 위 decide 를 하지 않는다. 앞
    확인에서 닫지 못한 세션(close_failures)도 맡은 일이 없으면 여기서 다시 닫는다."""
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
        quiet = not e["task"] and unreported(p, e, info)  # 맡은 세션은 닫지도 escalation 하지도 않는다
        if (quiet or e["close_failures"]) and not e["task"] and not e["resetting"]:
            close_quiet(d, name, e, QUIET_CLOSED.format(name=name) if quiet else None)
            continue
        fields: dict = {}
        if e["terminal_argv"] is None and info.get("argv") is not None:
            fields["terminal_argv"] = info["argv"]
        w = word(info)
        if w in (*READY, "working"):
            if e["terminal_unknown_since"] or e["terminal_unknown_asked"]:
                fields.update(terminal_unknown_since=None, terminal_unknown_asked=False)
        elif not e["task"] and not e["terminal_unknown_asked"] and not quiet:
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


# --- 보고 없는 세션, 다시 묶기 앞당기기, 옛 세션 바꾸기(5.9.9 의 2–4, 12단계) ---
def _silent(info: dict) -> bool:
    """hc get 정보로 본 보고 없는 세션(설계 5.9.9 의 2): status_ms 키가 있고 그 값이 없거나 created_ms 앞이다(작업 터미널은
    claude 하나만 돈다). 키가 없으면(이 필드를 주지 않는 hc) 가르지 않는다."""
    if "status_ms" not in info:
        return False
    ms, created = info.get("status_ms"), info.get("created_ms")
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return True
    return isinstance(created, (int, float)) and not isinstance(created, bool) and ms < created


def _write_failed(p, terminal: str) -> bool:
    """그 터미널의 대리 보고 쓰기가 실패했다: horch relay-status 기록의 decided 가 write_failed(herdr-orch 16.8, 설계 8.14 의
    5 의 끝 줄). 기록이 없거나 horch 가 실패하면 False(지금처럼)."""
    rec = herdr.relay_status(p, terminal)
    return isinstance(rec, dict) and rec.get("decided") == "write_failed"


def unreported(p, e: dict, info: dict | None) -> bool:
    """entry e 의 작업 터미널이 대리 보고도 없는 세션(설계 5.9.9 의 2): hc get 정보로 보고가 없거나(_silent) 대리 보고 쓰기가
    실패했다(_write_failed. hc 에는 마지막 대리 상태가 남는다). Claude 고정 에이전트만 대상이다: Codex 는 False(설계 8.14 의 1.
    지금의 no_status 처리. horch relay-status 도 부르지 않는다, 최종 리뷰 M1). info 가 없으면(hc 실패) False 다(지금처럼 확인
    불가). hc 로 갈리면 horch 를 부르지 않는다."""
    if info is None or e["agent"] != "claude":
        return False
    return _silent(info) or _write_failed(p, e["terminal"])


def _closed_fields() -> dict:
    """인수인계 없이 닫은 세션의 entry 필드(5.9.9 의 2): 터미널을 잊고 리셋을 마친 것으로 둔다(세션 표시는 edit 가 지운다)."""
    return {"terminal": None, "terminal_argv": None, "work_pane": None, "reset_pending": False, "since_reset": 0,
            "reset_tasks": [], "assigned_since_reset": 0, "reset_failures": 0, "close_failures": 0,
            "reset_busy_since": None, "reset_unknown_since": None, "terminal_unknown_since": None,
            "terminal_unknown_asked": False}


def _forget_closed(p, name: str, terminal: str, **extra) -> None:
    """entry 의 터미널이 그대로일 때만 닫은 세션의 필드를 쓴다."""
    with edit(p) as data:
        e = entry_of(data, name)
        if e["terminal"] == terminal:
            e.update(_closed_fields(), **extra)


def close_quiet(d, name: str, e: dict, done: str | None) -> None:
    """맡은 일 없는 세션을 인수인계 없이 닫는다(5.9.9 의 2, 3·4 의 닫기). 진행 중 Dispatch 가 없으니 --abandon 없이
    terminal-close. 성공하면 터미널을 잊고 리셋을 마친 것으로 두고(last_reset_at) done 로그. 실패하면 로그와 close_failures
    (다음 터미널 확인이 다시 한다). 세 번째 실패면 5.9.7 의 4 와 같은 decide 를 올리고 터미널을 잊는다."""
    p, terminal = d.p, e["terminal"]
    code, data = _call(d, "terminal-close", "--terminal", terminal)
    if code == 0 and data.get("ok"):
        _forget_closed(p, name, terminal, last_reset_at=local_now())
        if done:
            d.log(done)
        return
    err = data.get("error") or {}
    ecode, message = err.get("code") or f"exit_{code}", err.get("message") or ""
    n = (e["close_failures"] or 0) + 1
    d.log(CLOSE_QUIET_FAILED.format(name=name, n=n, limit=CLOSE_LIMIT, code=ecode, message=message))
    if n < CLOSE_LIMIT:
        return _mark(p, name, terminal, close_failures=n)
    d.decide("escalation", None, CLEAR_FAILED.format(name=name, code=ecode, message=message))
    _forget_closed(p, name, terminal)


def close_unreported(p, name: str, e: dict) -> bool:
    """넣기 전 확인(5.9.3 의 2: 배정 place·fix 의 _crew_fix·대기열 drain)이 대리 보고도 없는 세션을 만났고 그 에이전트가 맡은
    태스크가 없다(5.9.9 의 2): 그 자리에서 인수인계 없이 닫는다(close_quiet). 터미널을 잊었으면(닫았거나 세 번째 실패) True:
    이번 라운드는 5.9.2 로 새 세션에 띄운다. 닫지 못했으면 False: 넣지 않고 기다린다(확인 불가와 같다)."""
    close_quiet(drive.Drive(p), name, e, QUIET_CLOSED.format(name=name))
    return entry(p, name)["terminal"] != e["terminal"]


def _stamp(value) -> datetime | None:
    """저장된 시각 문자열(history·상태의 util.now() 꼴 UTC `Z`, crew.json 의 local_now() 꼴 오프셋 ISO)을 시각으로. 읽지
    못하거나 오프셋이 없으면 None. 지금 시각에서 뺀 나이가 아니라 저장된 시각끼리 견주려고 쓴다(같은 초를 놓치지 않게)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        then = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return then if then.tzinfo is not None and then.utcoffset() is not None else None


def assigned(p, name: str, raw: dict) -> int:
    """마지막 리셋·띄운 뒤 그 세션에 넣은 태스크 수(설계 5.9.9 의 3, assigned_since_reset). 0.7.2 전 entry(키 없음)는
    since_reset 으로 대신하고, 그것도 0 이면: 리셋 기록(last_reset_at)이 없거나 launched_at 이 그보다 늦거나 같으면 1(마지막
    리셋 뒤 새로 띄웠다. 5.9.2 의 띄우기는 늘 태스크를 넣는다), 아니면 그 에이전트 라운드의 작업 Dispatch 가 last_reset_at 과
    같은 초이거나 뒤에 working 이 된 history(launched)가 있으면 1, 없으면 0. 저장된 시각끼리 견준다(_stamp)."""
    value = raw.get("assigned_since_reset")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    since = raw.get("since_reset")
    if isinstance(since, int) and not isinstance(since, bool) and since > 0:
        return since
    reset, launched = _stamp(raw.get("last_reset_at")), _stamp(raw.get("launched_at"))
    if reset is None or (launched is not None and launched >= reset):
        return 1
    for st in state.all_states(p):
        mine = {rd["work"].get("dispatch") for rd in st["rounds"] if round_crew(rd) == name} - {None}
        for h in st.get("history") or []:
            at = _stamp(h.get("at"))
            if h.get("event") == "launched" and h.get("dispatch") in mine and at is not None and at >= reset:
                return 1
    return 0


def rehome_check(d) -> None:
    """다시 묶기 앞당기기와 옛 세션 바꾸기(설계 5.9.9 의 3·4): 관제의 다시 묶기 확인(8.5 의 10, 60초마다)이 부른다.
    에이전트마다 rehome:<이름> 격리."""
    for name in list(load(d.p)):
        d.isolated(f"rehome:{name}", lambda name=name: _rehome_one(d, name))


def _rehome_one(d, name: str) -> None:
    """작업 터미널이 있고 task·queue·resetting·reset_pending 이 비었을 때만 본다. 먼저 옛 세션 바꾸기(5.9.9 의 4): claude
    이고 relay_ready·relay_upgrade 가 없으면 바꾼다(hc 를 부르지 않는다. 다시 묶기 조건도 맞아도 새 세션이 둘을 함께 푸므로
    이것 하나만 한다). 아니면 다시 묶기 앞당기기(5.9.9 의 3): main_parent 가 주소 M 이고 entry 의 rehome_main 이 M 이 아니고,
    작업 터미널(hc get 3초, live)의 parent 로 outbox.moved_main 이 M 이면(parent 가 M 이 아님, M 은 같은 space 의 산 터미널,
    5.9.7 의 4 의 11단계 보강 세 조건) 바꾼다. 확인하지 못하면 둔다."""
    p = d.p
    raw = load(p).get(name)
    if not isinstance(raw, dict):
        return
    e = {**blank(name), **raw}
    if not e["terminal"] or e["task"] or e["queue"] or e["resetting"] or e["reset_pending"]:
        return
    if e["agent"] == "claude" and not raw.get("relay_ready") and not raw.get("relay_upgrade"):
        return _settle(d, name, raw, lambda what: RELAY_REPLACE.format(name=name, what=what), relay_upgrade=local_now())
    main = outbox.main_parent(p)
    if main is None or raw.get("rehome_main") == main:
        return
    try:
        info = herdr.get(e["terminal"], timeout=3)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return
    if info.get("state") != "live":
        return  # 끝난 터미널은 재확인의 터미널 확인이 잊는다
    parent = outbox._parent_ref(info.get("parent"))
    if outbox.moved_main(p, parent, e["space"]) != main:
        return
    _settle(d, name, raw, lambda what: REHOME_EARLY.format(name=name, main=main, parent=parent or "없음", what=what),
            rehome_main=main)


def _settle(d, name: str, raw: dict, line, **mark) -> None:
    """다시 묶기 앞당기기·옛 세션 바꾸기의 처리(5.9.9 의 3·4): 리셋 뒤 넣은 태스크가 있으면(assigned ≥ 1) reset_pending(지금
    리셋 흐름의 clear 단계가 parent_changed·relay_missing 으로 닫는다), 없으면 인수인계 없이 닫는다(새 대화가 없어 인수인계가
    앞 파일보다 나을 것이 없다). 표시(mark: rehome_main 또는 relay_upgrade)를 먼저 한 번 쓴다(리셋이 실패·취소돼도 되풀이하지
    않는다). 로그 line(what)."""
    p, terminal = d.p, raw["terminal"]
    close = assigned(p, name, raw) == 0
    _mark(p, name, terminal, **mark, **({} if close else {"reset_pending": True}))
    d.log(line("닫는다" if close else "리셋을 건다"))
    if close:
        close_quiet(d, name, entry(p, name), None)


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
    if (verdict == "live" and e["agent"] == "claude"
            and (_silent(info) or (w in READY and _write_failed(p, e["terminal"])))):
        # 12단계(5.9.9 의 2): 대리 보고도 없는 세션에는 인수인계를 넣을 수 없다. 30분 대기 없이 두면 맡은 일이 없으니 재확인의
        # 터미널 확인이 인수인계 없이 닫는다. 쓰기 실패는 넣기 직전(idle·done)에만 relay-status 로 본다(틱마다 horch 를
        # 부르지 않게. 일하는 중으로 남은 쓰기 실패 세션도 재확인이 닫는다). Claude 만이다: 재확인은 Codex 를 닫지 않으니
        # (unreported) Codex 는 아래의 확인 불가 대기로 간다(Codex 브랜치 리뷰)
        if e["reset_busy_since"] or e["reset_unknown_since"]:
            _set(p, name, reset_busy_since=None, reset_unknown_since=None)
        return None
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
    _set(p, name, reset_pending=False, reset_failures=0, reset_busy_since=None, reset_unknown_since=None)
    d.decide("escalation", None, (BUSY_CANCEL if busy else UNKNOWN_CANCEL).format(name=name, minutes=int(age // 60)))


def _skip(d, name: str) -> None:
    """비울 세션이 없다(터미널 없음·끝남·lost·terminal_gone): 리셋을 마친 것으로 둔다."""
    _set(d.p, name, reset_pending=False, reset_failures=0, since_reset=0, reset_tasks=[], terminal=None,
         terminal_argv=None, work_pane=None, resetting=None, reset_busy_since=None, reset_unknown_since=None,
         assigned_since_reset=0)
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
         reset_failures=0, close_failures=0, reset_busy_since=None, reset_unknown_since=None, assigned_since_reset=0,
         **fields)
    d.log(f"{name} 리셋: {text}")


def _unreported_now(p, e: dict) -> bool:
    """clear 단계의 바쁨 판정: entry e 의 작업 터미널이 대리 보고도 없는 세션(5.9.9 의 2)인가. Codex 는 False(unreported 와
    같다). 대리 보고 쓰기 실패면 hc 를 부르지 않고 True, 아니면 hc get(3초)의 _silent. hc 실패면 False(지금처럼 바쁨)."""
    if e["agent"] != "claude":
        return False
    terminal = e["terminal"]
    if _write_failed(p, terminal):
        return True
    try:
        info = herdr.get(terminal, timeout=3)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return False
    return _silent(info)


def _parent_changed(p, e: dict) -> bool:
    """리셋의 다시 묶기(설계 5.9.7 의 4, 11단계 보강): main_parent 가 주소 M 이고, 작업 터미널의 parent(hc get 3초, 없으면
    null)가 M 이 아니고, hc get M 이 entry 의 space 에 산 터미널이다(outbox.moved_main, 8.13 의 확인 4 와 같은 규칙). 하나라도
    아니거나 hc 로 확인하지 못하면 False(지금처럼 같은 터미널을 비운다. 묶음은 보기 위한 것이라 리셋을 막지 않는다)."""
    if outbox.main_parent(p) is None:
        return False
    try:
        info = herdr.get(e["terminal"], timeout=3)
    except HteamError as exc:
        if exc.exit_code == MISSING:
            raise
        return False
    return outbox.moved_main(p, outbox._parent_ref(info.get("parent")), e["space"]) is not None


def _clear(d, name: str) -> None:
    """비우기와 닫기 재시도(clear 단계, 어디서 죽어도 이어 한다). 비우기 신호가 없거나 실패하면 비웠다고 믿지 않고 터미널을
    닫는다(다음 태스크가 새 세션을 띄운다). 닫지 못하면 다음 틱에 닫기만 다시 하고, 세 번째면 decide 뒤 터미널을 잊는다.
    11단계 보강(5.9.7 의 4): 첫 시도에서 메인이 바뀌었으면(_parent_changed) 비우지 않고 닫는다(parent_changed). 그 닫기가
    실패하면 rehome = failed 로 두고, 그 뒤의 리셋 단계(같은 틱의 틱 7 이나 다음 틱)가 parent 를 보지 않고 같은 터미널을
    비운다."""
    p = d.p
    e = entry(p, name)
    res = e["resetting"] or {}
    reason, terminal = res.get("clear_error"), e["terminal"]
    if not terminal:  # 그 사이 재확인이 끝난 터미널을 잊었다: 비울 세션이 없다
        return _reset_done(d, name, f"new_terminal({reason or 'terminal_gone'})", terminal_argv=None, work_pane=None)
    if e["close_failures"] == 0 and reason is None and e["agent"] == "claude" and not e.get("relay_ready"):
        # 12단계(5.9.9 의 4): 대리 보고·Stop 기록이 없는 옛 세션은 비우지 않고 닫아 다음 태스크가 새 세션으로 뜬다. 닫기
        # 실패는 다른 clear_error 와 같은 세 번 규칙이다
        reason = "relay_missing"
        res = {**res, "clear_error": reason}
        _set(p, name, resetting=res)  # 닫기 전에 죽으면 다시 뜬 관제가 닫기부터 한다
    if e["close_failures"] == 0 and reason is None and not res.get("rehome") and _parent_changed(p, e):
        # 메인이 바뀌었다: 비우지 않고 닫아 다음 태스크가 새 메인 아래 새 세션으로 띄운다(인수인계 파일은 그대로 읽는다)
        reason = "parent_changed"
        res = {**res, "clear_error": reason}
        _set(p, name, resetting=res)  # 닫기 전에 죽으면 다시 뜬 관제가 닫기부터 한다
    if e["close_failures"] == 0 and reason is None:  # 아직 비우기를 하지 않았다
        args = ["terminal-reset", "--terminal", terminal]
        if e["agent"] == "codex":
            args += ["--name", name]  # /clear <이름> 이 Codex 대화 이름(제목)을 고정한다(X3b)
        timeout = os.environ.get("HTEAM_RESET_TIMEOUT_MS") or str(drive.RESET_CLEAR_TIMEOUT_MS)
        code, data = _call(d, *args, "--timeout-ms", timeout)
        if code == 0 and data.get("ok"):
            return _reset_done(d, name, f"reset(turn {data.get('turn')}, {data.get('seconds')}초)")
        reason = (data.get("error") or {}).get("code") or f"exit_{code}"
        w = data.get("status")
        if reason == "terminal_not_ready" and w in ("working", "blocked") and not _unreported_now(p, e):
            # 12단계: 대리 보고도 없는 세션(인수인계 done 뒤 Stop 쓰기 실패로 옛 working 이 남았다 등)은 상태가 바뀌지 않으므로
            # 바쁨으로 기다리지 않고 아래 닫기로 간다(인수인계 파일은 그대로다)
            # 에이전트는 done 명령을 턴 안에서 부른다(6단계 실환경): 아무것도 치지 않았으니 세션을 닫지 않고 2 의 바쁨처럼
            # 미룬다. clear 단계로 남아 다음 틱에 다시 하고, RESET_BUSY_S 가 지나면 아래 닫기로 간다
            since = e["reset_busy_since"]
            if not since:
                _set(p, name, reset_busy_since=local_now(), reset_unknown_since=None)
                d.log(f"{name} 리셋 미룸: 작업 세션이 일하는 중({w})")
                return None
            age = local_age(since)
            if age is None or age < drive.RESET_BUSY_S:
                return None
        _set(p, name, resetting={**res, "clear_error": reason})
    code, data = _call(d, "terminal-close", "--terminal", terminal)  # 진행 중 Dispatch 가 없으니 --abandon 없이
    if code == 0 and data.get("ok"):
        return _reset_done(d, name, f"new_terminal({reason})", terminal=None, terminal_argv=None, work_pane=None)
    if reason == "parent_changed":  # 다시 묶기의 닫기는 되풀이하지 않는다: 그 뒤의 리셋 단계가 parent 를 보지 않고 비운다
        err = data.get("error") or {}
        _set(p, name, resetting={**{k: v for k, v in res.items() if k != "clear_error"}, "rehome": "failed"})
        d.log(f"{name} 리셋: 다시 묶기 닫기 실패({err.get('code') or f'exit_{code}'}), 같은 터미널을 비운다")
        return None
    n = e["close_failures"] + 1
    if n < CLOSE_LIMIT:
        return _set(p, name, close_failures=n)  # resetting 을 남겨 다음 틱에 닫기만 다시
    err = data.get("error") or {}
    d.decide("escalation", None, CLEAR_FAILED.format(name=name, code=err.get("code") or f"exit_{code}",
                                                     message=err.get("message") or ""))
    _set(p, name, resetting=None, reset_pending=False, reset_failures=0, close_failures=0, terminal=None,
         terminal_argv=None, work_pane=None)


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
    _set(d.p, name, resetting=None, reset_pending=False, reset_failures=0)
    d.decide("escalation", None, text, commands=[f"hteam agent reset {name}"])


def _handoff_holder(p, did: str | None) -> str | None:
    """resetting.dispatch 가 did 인 에이전트 이름."""
    if not did:
        return None
    return next((name for name, e in load(p).items()
                 if isinstance(e, dict) and (e.get("resetting") or {}).get("dispatch") == did), None)


def handoff_relay_failed(d, did: str | None) -> bool:
    """재확인의 쓰기 실패 보조(설계 8.7 의 2a): did 가 인수인계 Dispatch 면 True(태스크 Dispatch 로 보지 않는다). handoff
    단계면 그 자리에서 끝나지 않은 인수인계 정리(5.9.7 의 4, RESET_STUCK_S 갈래와 같은 _handoff_failed: abandon
    --keep-terminal → release → 리셋 지우기 → decide)를 한다. 그 세션은 상태를 보낼 수 없어 인수인계 끝을 알 수 없고
    비우기 확인(turn·idle)도 오지 않는다. 메시지 길은 handoff_message 의 relay_failed 갈래다."""
    name = _handoff_holder(d.p, did)
    if name is None:
        return False
    if (entry(d.p, name)["resetting"] or {}).get("step") == "handoff":
        _handoff_failed(d, name, did, RELAY_HANDOFF.format(name=name))
    return True


def handoff_message(d, m: dict) -> bool:
    """인수인계 Dispatch 의 메시지면 처리하고 True(8.6). 아니면 False(태스크 메시지로 간다)."""
    from .coord import _body  # coord 가 이 모듈을 쓴다
    body = _body(m)
    did = m.get("dispatch") or body.get("dispatch")
    name = _handoff_holder(d.p, did)
    if name is None:
        return False
    kind, what = m.get("type"), body.get("kind")
    if (entry(d.p, name)["resetting"] or {}).get("step") == "clear":
        # 인수인계 Dispatch 는 이미 끝났다(clear 단계는 비우기만 남았다). 관제 재시작 뒤 재확인이 메일보다 먼저 clear 로
        # 넘기면 그 Dispatch 의 지난 observed 가 늦게 온다: 리셋을 취소하지 않게 무시한다(Codex 커밋 리뷰 558d54d)
        d.log(f"{name} 인수인계 Dispatch 의 {kind} 무시(clear 단계): {did}")
        return True
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
        msg = str(d.hc_status(did).get("msg") or "")  # observed 본문에는 상태 낱말만 있다(작업 _stuck 과 같다)
        d.decide("escalation", None, HANDOFF_PAUSED.format(name=name, word=what, msg=msg[:120]))
    elif kind == "observed" and what == "relay_failed":
        # 12단계(설계 8.6 표): 상태를 보낼 수 없어 인수인계 끝·비우기 확인을 알 수 없다. 그 자리에서 정리하고 decide.
        # 이미 끝난(진행 중 아닌) Dispatch 의 늦은 relay_failed 는 무시한다: 같은 묶음의 worker_done 이나 재확인이 결과대로
        # 끝낸다(Codex 커밋 리뷰 2efd085)
        row = dispatch.row_by_id(d.horch().workers(), did)
        if row is not None and row.get("state") not in drive.LIVE:
            d.log(f"{name} 인수인계 Dispatch 의 {kind} 무시(이미 끝남): {did}")
            return True
        _handoff_failed(d, name, did, RELAY_HANDOFF.format(name=name))
    elif kind == "observed" and what in ("exited", "lost"):
        forget(d.p, name)  # terminal-close --abandon 으로 남은 기록 정리. 다음 세션은 새로 뜬다
        _set(d.p, name, resetting=None, reset_pending=False, reset_failures=0, since_reset=0, reset_tasks=[])
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
def not_started(d, tid: str, did: str) -> bool:
    """observed not_started(넣은 입력이 들어가지 않았다): 작업 터미널이 live 이고 idle·done 일 때만 같은 라운드를 같은 터미널에
    다시 넣는다. 재투입 예약 resend 를 어떤 조회(horch·hc)보다 먼저 쓰고, 새 Dispatch 를 기록하거나 실패 decide 를 올리거나 입력이
    들어간 증거를 볼 때까지 지우지 않는다. 남은 resend 는 이 처리(다시 온 메시지)와 재확인이 잇는다. 세 번째면 다시 넣지 않고
    decide. 입력이 들어간 증거로 예약을 지웠으면 True(재확인은 보통 작업자 확인으로 돌아간다)."""
    p = d.p
    st = state.require(p, tid)
    rd = state.current_round(st)
    if rd is None:
        return False
    work = rd["work"]
    resend = work.get("resend")
    if resend:  # 앞 재투입이 끝나기 전에 관제가 죽었거나 조회가 실패했다
        did, n = resend["from"], resend["n"]
    else:  # 상태 파일의 값만으로 먼저 쓴다. 뒤 조회가 실패해도(그 메시지는 ack 된다) 재확인이 잇는다
        n = (st.get("unknown_starts") or 0) + 1
        with state.edit(p, tid) as cur:
            state.current_round(cur)["work"]["resend"] = {"from": did, "n": n}
    rows = d.horch().workers()
    if resend:
        latest = dispatch.latest_for_task(rows, work.get("horch_task"))
        if latest is not None and latest["id"] != did:
            if latest["state"] == "launch_failed":
                d.procedure_failed(tid, HteamError("resend_failed", f"{tid} 에 다시 넣은 Dispatch {latest['id']} 가 "
                                                                    "launch_failed 다", FAIL))
                _drop_resend(p, tid)
                return False
            _resent(d, tid, latest, n)  # 새 Dispatch 를 띄운 뒤 기록 전에 죽었다: 이어 붙인다
            return False
    row = dispatch.row_by_id(rows, did)
    abandon = row is None or row["state"] != "abandoned"
    # 이미 버린 앞 Dispatch 는 증거를 보지 않는다(재투입을 마쳐야 한다). hc 없이 아는 증거(워커 명령·메시지, 끝남)를 먼저 본다
    if abandon and row is not None and (row.get("seen_at") or row["state"] not in drive.LIVE):
        return _went_in(d, tid, did)
    name = round_crew(rd)
    e = entry(p, name) if name else None
    if not e or not e["terminal"]:
        return False
    verdict, info = probe(e["terminal"], e["terminal_argv"])
    if verdict != "live":
        return False  # 확인 불가는 resend 를 두어 다음 재확인이 다시 본다(끝났으면 재확인의 터미널 확인이 맡은 태스크를 처리한다)
    w = word(info)
    if abandon and _started(row, rd, info, w):
        return _went_in(d, tid, did)
    if w not in READY or unreported(p, e, info):
        # blocked·error·보고 없음은 resend 를 두어 다음 재확인이 다시 본다. 대리 보고도 없는 세션(5.9.9 의 2. 쓰기 실패면 hc 에
        # 옛 done 이 남는다)은 넣은 입력이 들어갔는지 알 수 없어 다시 넣지 않는다(이 태스크를 맡은 세션이라 닫지도 않는다)
        return False
    if n >= drive.UNKNOWN_START_LIMIT:
        d.decide("escalation", tid, NOT_STARTED_LIMIT.format(n=n),
                 commands=[d._fix_cmd(st), d._fix_cmd(st, force=True), f"hteam drop {tid}"])
        _drop_resend(p, tid)
        return False
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
        _drop_resend(p, tid)
        return False
    _resent(d, tid, {"id": res["dispatch"], "start_turn": res.get("start_turn"), "delivery": res.get("delivery")}, n)
    return False


def _went_in(d, tid: str, did: str) -> bool:
    """앞 Dispatch 에 넣은 입력이 들어간 증거를 봤다: 다시 넣지 않고 예약을 지운다."""
    d.log(f"{tid} not_started 지난 관찰 무시: {did}")
    _drop_resend(d.p, tid)
    return True


def _started(row: dict | None, rd: dict, info: dict, w: str | None) -> bool:
    """hc 로 아는, 앞 Dispatch 에 넣은 입력이 그새 들어간 증거(orch 13.6 의 전달 판정과 같은 기준, 5.9.8 의 working): turn 이
    그 Dispatch 의 start_turn(없으면 0)보다 크거나 세션이 일하는 중이다. hc 없이 아는 증거(seen_at: 워커 명령과 워커의 send,
    끝난 Dispatch)는 not_started 가 터미널 확인 전에 본다."""
    start = (row.get("start_turn") if row else rd.get("start_turn")) or 0
    turn = info.get("turn")
    return (isinstance(turn, int) and turn > start) or w == "working"


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
