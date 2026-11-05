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


def probe(terminal: str | None, expected_argv: list[str] | None) -> tuple[str, dict | None]:
    if not terminal:
        return "unverifiable", None
    try:
        info = hcio.get(terminal)
    except hcio.HcFailure:
        return "unverifiable", None
    return verdict(info, expected_argv), info


def loads_argv(text: str | None) -> list[str] | None:
    return json.loads(text) if text else None


def observe(store, run_id: str) -> list[int]:
    """active Dispatch 를 판정해 새 사건이면 observed 메시지를 Run 메일함에 쓴다(설계 9장)."""
    from . import mailbox  # mailbox 가 이 모듈을 import 하므로 여기서 가져온다
    from .ids import now
    created: list[int] = []
    for row in store.all("SELECT id, terminal, launch_argv FROM dispatches WHERE run_id=? AND state='active'", (run_id,)):
        verdict_, info = probe(row["terminal"], loads_argv(row["launch_argv"]))
        word = status_word(info)
        events = []
        if verdict_ == "live" and word in ("blocked", "error"):
            events.append((word, str(info.get("turn"))))
        if verdict_ in ("exited", "lost"):
            events.append((verdict_, verdict_))
        for kind, key in events:
            with store.tx():
                cur = store.run("INSERT OR IGNORE INTO observations(dispatch_id, kind, key, created_at) VALUES (?,?,?,?)",
                                (row["id"], kind, key, now()))
                if cur.rowcount:
                    body = json.dumps({"dispatch": row["id"], "kind": kind, "key": key, "terminal": row["terminal"],
                                       "status": word}, ensure_ascii=False)
                    created.append(mailbox.post(store, run_id=run_id, mailbox=f"run:{run_id}", sender="horch",
                                                type="observed", subject=f"{kind} {row['id']}", body=body,
                                                dispatch_id=row["id"]))
    return created
