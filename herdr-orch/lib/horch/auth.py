"""호출자 확인(설계 6장). 보안 경계가 아니라 협조적인 에이전트의 실수를 막는다."""
from __future__ import annotations

import json
import os
import sqlite3

from .errors import CONFLICT, DENIED, USAGE, HorchError
from .ids import now


def caller() -> str | None:
    value = os.environ.get("HC_TERMINAL_ID", "").strip()
    return value or None


def require_terminal() -> str:
    term = caller()
    if not term:
        raise HorchError("no_terminal", "hc 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
    return term


def refuse_worker(store, terminal: str) -> None:
    if store.one("SELECT id FROM dispatches WHERE terminal=? AND state IN ('launching','active')", (terminal,)):
        raise HorchError("worker_terminal", "워커 터미널은 Run 을 만들거나 넘겨받을 수 없다(중첩 금지)", DENIED)


def owner_run_id(store) -> str:
    term = caller()
    row = store.one("SELECT run_id FROM bindings WHERE terminal=?", (term,)) if term else None
    if not row:
        raise HorchError("not_owner", "이 터미널에 묶인 Run 이 없다", DENIED, "run-create 또는 run-use 를 먼저 한다")
    return row["run_id"]


def owned_dispatch(store, run_id: str, dispatch_id: str) -> sqlite3.Row:
    row = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    if not row or row["run_id"] != run_id:
        raise HorchError("unknown_dispatch", f"이 Run 에 Dispatch {dispatch_id} 가 없다", USAGE)
    return row


def worker_dispatch(store, dispatch_id: str) -> sqlite3.Row:
    """신원 확인만 한다(상태와 상관없이). 상태 검사는 명령마다 한다."""
    row = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    if not row:
        raise HorchError("unknown_dispatch", f"Dispatch {dispatch_id} 가 없다", USAGE)
    term = caller()
    if not row["terminal"] or row["terminal"] != term:
        raise HorchError("not_this_worker", f"Dispatch {dispatch_id} 는 이 터미널({term or '없음'})의 것이 아니다", DENIED,
                         "이 명령은 그 Dispatch 의 워커 터미널에서만 한다. Codex 는 셸 명령으로 부른다"
                         "(node_repl 등 다른 도구에는 HC_TERMINAL_ID 가 없다)")
    if (row["state"] == "launching" and row["persistent"] and row["launch_argv"] is None
            and json.loads(row["delivery"] or "{}").get("attempted")):
        # 같은 터미널 넣기(--terminal)의 보내기 표시 뒤 결과 기록 전에 워커가 먼저 왔다. 입력이 들어갔다는 증거다.
        # 새 터미널의 가드 등록처럼 launching 을 active 로 넘긴다(조건부 쓰기, 설계 13.4 의 7 뒤)
        with store.tx():
            store.run("UPDATE dispatches SET state='active' WHERE id=? AND state='launching'", (dispatch_id,))
        row = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    if row["seen_at"] is None:
        mark_seen(store, dispatch_id)
    return row


def mark_seen(store, dispatch_id: str) -> None:
    """이 Dispatch 로 워커 명령이 처음 신원 확인을 통과한 시각(설계 13.6). 비어 있을 때만 쓴다."""
    with store.tx():
        store.run("UPDATE dispatches SET seen_at=? WHERE id=? AND seen_at IS NULL", (now(), dispatch_id))


def require_active(row) -> None:
    if row["state"] != "active":
        raise HorchError("dispatch_not_active", f"Dispatch {row['id']} 는 {row['state']} 다", CONFLICT)
