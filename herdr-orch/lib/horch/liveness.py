"""생존 판정(설계 10장)과 observed 감시(설계 9장)."""
from __future__ import annotations

import json

from . import hcio


def status_word(info: dict | None) -> str | None:
    """hc 가 보고한 에이전트 상태 낱말. get 은 {"state": ...}, ls 는 문자열을 준다."""
    if not info:
        return None
    status = info.get("status")
    if isinstance(status, dict):
        return status.get("state")
    if isinstance(status, str):
        return status
    return None


def verdict(info: dict | None, expected_argv: list[str] | None) -> str:
    if info is None:
        return "unverifiable"
    state = info.get("state")
    if state == "finished":
        return "exited"
    if state != "live":
        return "unverifiable"
    if info.get("reason") == "stopped_by_restart":
        return "lost"
    if expected_argv is not None:
        argv = info.get("argv")
        if argv is None:
            # argv 를 알 수 없으면 터미널이 끝났다고 단정하지 못한다(10장): 모름.
            return "unverifiable"
        if argv != expected_argv:
            return "lost"
    return "live"


def probe(terminal: str | None, expected_argv: list[str] | None,
          timeout: float | None = None) -> tuple[str, dict | None]:
    """timeout 은 hc get 하나의 시간 제한(초, None 이면 hcio 기본). 넘기면 모름(unverifiable)."""
    if not terminal:
        return "unverifiable", None
    try:
        info = hcio.get(terminal, timeout=timeout)
    except hcio.HcFailure:
        return "unverifiable", None
    return verdict(info, expected_argv), info


def loads_argv(text: str | None) -> list[str] | None:
    return json.loads(text) if text else None


def observe_one(store, run_id: str, dispatch_id: str, timeout: float | None = None) -> list[int]:
    """active Dispatch 하나를 판정해 새 사건이면 observed 메시지를 Run 메일함에 쓴다(설계 9장)."""
    from . import mailbox  # mailbox 가 이 모듈을 import 하므로 여기서 가져온다
    from .ids import now
    row = store.one("SELECT id, state, terminal, launch_argv FROM dispatches WHERE id=?", (dispatch_id,))
    if not row or row["state"] != "active":
        return []
    verdict_, info = probe(row["terminal"], loads_argv(row["launch_argv"]), timeout)
    word = status_word(info)
    events = []
    if verdict_ == "live" and word in ("blocked", "error"):
        turn = info.get("turn")
        if turn is not None:  # turn 이 없으면 같은 사건을 가를 key 가 없다. 모름이므로 보내지 않는다
            events.append((word, str(turn)))
    if verdict_ in ("exited", "lost"):
        events.append((verdict_, verdict_))
    created: list[int] = []
    for kind, key in events:
        with store.tx():
            # hc 판정은 트랜잭션 밖에서 했다. 그 사이 done·abandon 으로 바뀌었으면 옛 판정을 쓰지 않는다(10장 원칙)
            cur = store.one("SELECT state, terminal FROM dispatches WHERE id=?", (dispatch_id,))
            if cur["state"] != "active" or cur["terminal"] != row["terminal"]:
                return created
            ins = store.run("INSERT OR IGNORE INTO observations(dispatch_id, kind, key, created_at) VALUES (?,?,?,?)",
                            (dispatch_id, kind, key, now()))
            if ins.rowcount:
                body = json.dumps({"dispatch": dispatch_id, "kind": kind, "key": key, "terminal": row["terminal"],
                                   "status": word}, ensure_ascii=False)
                created.append(mailbox.post(store, run_id=run_id, mailbox=f"run:{run_id}", sender="horch",
                                            type="observed", subject=f"{kind} {dispatch_id}", body=body,
                                            dispatch_id=dispatch_id))
    return created


def observe(store, run_id: str) -> list[int]:
    """Run 의 active Dispatch 를 모두 판정한다. 소유자의 대기는 시간 예산이 있는 workers.Sweep 을 쓴다."""
    created: list[int] = []
    for row in store.all("SELECT id FROM dispatches WHERE run_id=? AND state='active' ORDER BY created_at, id",
                         (run_id,)):
        created += observe_one(store, run_id, row["id"])
    return created
