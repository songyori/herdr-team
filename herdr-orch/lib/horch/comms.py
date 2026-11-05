"""메시지 명령. send·check(Task 6), reply·ask·escalate·done(Task 9)."""
from __future__ import annotations

from . import auth, mailbox
from .errors import CONFLICT, DENIED, USAGE, HorchError


def send(store, to: str, subject: str | None, body: str) -> dict:
    kind, _, ident = to.partition(":")
    term = auth.caller()
    if kind == "run":
        if not store.one("SELECT 1 FROM runs WHERE id=?", (ident,)):
            raise HorchError("unknown_run", f"Run {ident} 가 없다", USAGE)
        owner = store.one("SELECT terminal FROM bindings WHERE run_id=?", (ident,))
        if owner and term and owner["terminal"] == term:
            raise HorchError("owner_to_self", "소유자는 자기 Run 메일함에 send 하지 않는다", DENIED)
        dsp = store.one("SELECT id FROM dispatches WHERE terminal=? AND state='active'", (term,)) if term else None
        run_id, box = ident, f"run:{ident}"
        sender = f"dispatch:{dsp['id']}" if dsp else f"external:{term or 'none'}"
        dispatch_id = dsp["id"] if dsp else None
    elif kind == "dispatch":
        run_id = auth.owner_run_id(store)
        try:
            row = auth.owned_dispatch(store, run_id, ident)
        except HorchError as exc:
            # 설계 7장: 소유자의 Run 에 속한 active Dispatch 만 받는다. 아니면 exit 3.
            raise HorchError(exc.code, exc.message, CONFLICT, exc.hint) from exc
        if row["state"] != "active":
            raise HorchError("dispatch_not_active", f"Dispatch {ident} 는 {row['state']} 다", CONFLICT)
        box, sender, dispatch_id = f"dispatch:{ident}", f"run:{run_id}", ident
    else:
        raise HorchError("usage", "--to 는 run:<id> 또는 dispatch:<id> 다", USAGE)
    with store.tx():
        if kind == "dispatch":
            auth.require_active(store.one("SELECT id, state FROM dispatches WHERE id=?", (ident,)))
        mid = mailbox.post(store, run_id=run_id, mailbox=box, sender=sender, type="status", subject=subject,
                           body=body, dispatch_id=dispatch_id)
    return {"message": mid, "wake": mailbox.wake(store, box)}


def check(store, *, dispatch: str | None, wait: bool, timeout_ms: int, ack: int | None) -> dict:
    if dispatch:
        row = auth.worker_dispatch(store, dispatch)
        auth.require_active(row)
        return mailbox.check(store, f"dispatch:{dispatch}", wait=wait, timeout_ms=timeout_ms, ack_id=ack,
                             terminal=auth.caller())
    run_id = auth.owner_run_id(store)

    def still_owner() -> None:
        if auth.owner_run_id(store) != run_id:
            raise HorchError("binding_moved", f"이 터미널은 더는 Run {run_id} 의 소유자가 아니다", DENIED,
                             "대기를 끝낸다. 새 Run 의 메일함은 다시 check 한다")

    return mailbox.check(store, f"run:{run_id}", wait=wait, timeout_ms=timeout_ms, ack_id=ack,
                         terminal=auth.caller(), guard=still_owner)
