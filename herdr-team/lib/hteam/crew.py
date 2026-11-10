"""고정 에이전트(설계 5.9, 6단계): state/crew.json, 배정(5.9.4), 처음 띄운 뒤 기록·탭 이름·배치(5.9.2), 같은 터미널에 넣은 뒤
기록(5.9.3), 작업 터미널 확인과 잊기, fix·drop --force 의 세션 닫기(5.9.6), 수정 대기열과 큐 맞추기(5.9.5), 관제의 worker_done
정리와 재확인의 터미널 확인(8.6·8.7 의 2), status 의 crew(8.3).

crew.json 을 쓰는 것은 관제와 그 자식뿐이다(5.9.1). 쓰기는 늘 edit(crew.json.lock flock → 다시 읽기 → 고치기 → 원자 쓰기)다.
태스크 잠금 안에서 edit 를 잡아도 되고, edit 안에서 다른 hteam 잠금을 잡지 않는다. 리셋·인수인계(5.9.7)는 뒤 단계가 더한다."""
from __future__ import annotations

import contextlib
import hashlib
import time
from typing import Iterator

from . import drive, herdr, outbox, state
from .errors import FAIL, HteamError
from .horch import Horch
from .util import bad_side_file, die_at, dumps, flock, local_age, local_now, now, read_json_strict, write_json

READY = ("idle", "done")  # 같은 터미널에 넣을 수 있는 세션 상태(herdr-orch 13.4)
FORGOT_LOG = "{name} 작업 터미널이 닫혀 잊음"
STUCK_TEXT = ("{name} 에이전트 작업 세션이 태스크 없이 {word} 로 멈춰 있다. 사용자에게 그 탭을 보고 넘기거나 작업 pane 을 닫아 "
              "달라고 한다(닫으면 관제가 다음 태스크 때 새 세션을 띄운다)")
UNKNOWN_TEXT = ("{name} 에이전트 작업 터미널({terminal}) 상태를 {minutes}분 넘게 확인하지 못했다. 새 세션을 띄우지 않고 기다린다. "
                "사용자에게 그 탭을 확인해 달라고 한다")
STOP_FAILED = ("{tid}: 일하는 중일 수 있는 이전 세션을 닫지 못했다({error}). 다시 띄우지 않았다. 사용자에게 그 에이전트 탭의 "
               "작업 pane 을 닫아 달라고 한 뒤 다시 한다")


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
def enqueue(p, tid: str, name: str, *, note: str | None, supplement: str | None, force_round: bool,
            request: str | None) -> dict:
    """태스크의 queued_fix(기준 기록)를 먼저 쓰고 그다음 에이전트 queue 끝에 넣는다(이미 있으면 끝으로 옮긴다). 두 번째 fix 는
    note 를 줄마다 앞 note 뒤에 잇고(같은 줄은 한 번), supplement 는 이번 값(없으면 앞 값), force_round 는 OR, at 은 지금,
    request 는 처음 값이다. 같은 쓰기에서 관제 fix 이어 하기 표시(drive_fix)를 지운다(줄을 섰으면 이어 할 것이 없다)."""
    with state.edit(p, tid) as st:
        old = st.get("queued_fix") or None
        lines = (old or {}).get("note", "").split("\n") if (old or {}).get("note") else []
        for line in (note or "").split("\n"):
            if line and line not in lines:
                lines.append(line)
        st["queued_fix"] = {"note": "\n".join(lines) or None,
                            "supplement": supplement if supplement is not None else (old or {}).get("supplement"),
                            "force_round": bool((old or {}).get("force_round")) or bool(force_round),
                            "at": now(), "request": old.get("request") if old else request}
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
