"""메시지 명령. send·check(Task 6), reply·ask·escalate·done(Task 9)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time

from . import auth, mailbox, workers
from .errors import CONFLICT, DENIED, TIMEOUT, USAGE, HorchError
from .ids import now


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

    tick = workers.Sweep(store, run_id) if wait else None
    return mailbox.check(store, f"run:{run_id}", wait=wait, timeout_ms=timeout_ms, ack_id=ack,
                         terminal=auth.caller(), guard=still_owner, on_tick=tick)


def reply(store, question_id: int, body: str) -> dict:
    run_id = auth.owner_run_id(store)
    q = store.one("SELECT * FROM messages WHERE id=? AND type='question'", (question_id,))
    if not q or q["run_id"] != run_id:
        raise HorchError("unknown_question", f"이 Run 에 질문 {question_id} 가 없다", USAGE)
    existing = None
    try:
        with store.tx():
            # 확인과 트랜잭션 사이에 run-use 로 소유가 옮겨졌을 수 있다. 쓰기 직전에 다시 확인한다.
            if auth.owner_run_id(store) != run_id:
                raise HorchError("not_owner", f"이 터미널은 더는 Run {run_id} 의 소유자가 아니다", DENIED,
                                 "run-create 또는 run-use 를 먼저 한다")
            existing = store.one("SELECT id, body FROM messages WHERE reply_to=? AND type='reply'", (question_id,))
            if existing is None:
                mid = mailbox.post(store, run_id=run_id, mailbox=f"dispatch:{q['dispatch_id']}", sender=f"run:{run_id}",
                                   type="reply", body=body, reply_to=question_id, dispatch_id=q["dispatch_id"])
                return {"message": mid, "duplicate": False}
    except sqlite3.IntegrityError:
        existing = store.one("SELECT id, body FROM messages WHERE reply_to=? AND type='reply'", (question_id,))
    if existing["body"] == body:
        return {"message": existing["id"], "duplicate": True}
    raise HorchError("reply_conflict", f"질문 {question_id} 에는 이미 다른 답이 있다", CONFLICT)


def _ask_key(question: str, key: str | None) -> str:
    return key or hashlib.sha256(question.encode("utf-8")).hexdigest()[:16]


def ask(store, dispatch_id: str, question: str | None, key: str | None, timeout_ms: int, resume: int | None) -> dict:
    row = auth.worker_dispatch(store, dispatch_id)
    run_id = row["run_id"]
    reused = True
    if resume is not None:
        q = store.one("SELECT * FROM messages WHERE id=? AND type='question' AND dispatch_id=?", (resume, dispatch_id))
        if not q:
            raise HorchError("unknown_question", f"이 Dispatch 의 질문 {resume} 가 없다", USAGE)
        if row["state"] != "active":
            raise HorchError("dispatch_not_active", f"Dispatch {dispatch_id} 는 {row['state']} 다", CONFLICT,
                             data={"question": q["id"]})
    else:
        auth.require_active(row)
        if not question:
            raise HorchError("usage", "--question 또는 --resume 이 필요하다", USAGE)
        ask_key = _ask_key(question, key)
        try:
            with store.tx():
                auth.require_active(store.one("SELECT id, state FROM dispatches WHERE id=?", (dispatch_id,)))
                q = store.one("SELECT * FROM messages WHERE dispatch_id=? AND ask_key=?", (dispatch_id, ask_key))
                if q is None:
                    mid = mailbox.post(store, run_id=run_id, mailbox=f"run:{run_id}", sender=f"dispatch:{dispatch_id}",
                                       type="question", subject=question.splitlines()[0][:80], body=question,
                                       dispatch_id=dispatch_id, ask_key=ask_key)
                    q = store.one("SELECT * FROM messages WHERE id=?", (mid,))
                    reused = False
        except sqlite3.IntegrityError:
            q = store.one("SELECT * FROM messages WHERE dispatch_id=? AND ask_key=?", (dispatch_id, ask_key))
        if q["body"] != question:
            raise HorchError("ask_key_conflict", f"key {ask_key} 의 질문 본문이 다르다", CONFLICT,
                             data={"question": q["id"]})
        if not reused:
            mailbox.wake(store, f"run:{run_id}")
    return _wait_answer(store, dispatch_id, run_id, q["id"], timeout_ms, reused)


def _wait_answer(store, dispatch_id: str, run_id: str, qid: int, timeout_ms: int, reused: bool) -> dict:
    deadline = time.monotonic() + timeout_ms / 1000
    next_wake = time.monotonic() + mailbox.rewake_interval()
    while True:
        # 설계 9장: Dispatch 가 active 가 아니면 답이 있어도 exit 3 으로 끝낸다. 상태를 먼저 본다.
        state = store.one("SELECT state FROM dispatches WHERE id=?", (dispatch_id,))["state"]
        if state != "active":
            raise HorchError("dispatch_not_active", f"Dispatch {dispatch_id} 가 {state} 가 됐다", CONFLICT,
                             data={"question": qid})
        answer = store.one("SELECT body FROM messages WHERE reply_to=? AND type='reply'", (qid,))
        if answer:
            return {"question": qid, "answer": answer["body"], "reused": reused}
        t = time.monotonic()
        if t >= deadline:
            raise HorchError("timeout", "답이 오지 않았다", TIMEOUT, f"--resume {qid} 로 다시 기다린다",
                             data={"question": qid})
        if t >= next_wake:
            mailbox.wake(store, f"run:{run_id}")
            next_wake = t + mailbox.rewake_interval()
        time.sleep(min(mailbox.poll_interval(), deadline - t))


def escalate(store, dispatch_id: str, body: str) -> dict:
    row = auth.worker_dispatch(store, dispatch_id)
    auth.require_active(row)
    run_id = row["run_id"]
    with store.tx():
        auth.require_active(store.one("SELECT id, state FROM dispatches WHERE id=?", (dispatch_id,)))
        mid = mailbox.post(store, run_id=run_id, mailbox=f"run:{run_id}", sender=f"dispatch:{dispatch_id}",
                           type="escalation", subject=body.splitlines()[0][:80] if body else None, body=body,
                           dispatch_id=dispatch_id)
    return {"message": mid, "wake": mailbox.wake(store, f"run:{run_id}")}


def done(store, dispatch_id: str, outcome: str, summary: str, report_path: str | None, files: list[str]) -> dict:
    row = auth.worker_dispatch(store, dispatch_id)
    run_id = row["run_id"]
    files = list(files or [])
    files_json = json.dumps(files, ensure_ascii=False)
    with store.tx():
        cur = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
        if cur["outcome"] is not None:
            same = (cur["outcome"], cur["summary"], cur["report_path"], cur["files_modified"]) == \
                   (outcome, summary, report_path, files_json)
            if not same:
                raise HorchError("done_conflict", "이미 다른 내용으로 done 했다", CONFLICT)
            duplicate = True
        else:
            if cur["state"] != "active":
                raise HorchError("dispatch_not_active", f"Dispatch {dispatch_id} 는 {cur['state']} 다", CONFLICT)
            ts = now()
            d_upd = store.run("UPDATE dispatches SET state='settled', outcome=?, summary=?, report_path=?, "
                              "files_modified=?, settled_at=? WHERE id=? AND state='active'",
                              (outcome, summary, report_path, files_json, ts, dispatch_id))
            t_upd = store.run("UPDATE tasks SET status='settled', outcome=?, settled_at=? WHERE id=? AND status='open'",
                              (outcome, ts, cur["task_id"]))
            if d_upd.rowcount != 1 or t_upd.rowcount != 1:
                raise HorchError("conflict", "Dispatch 또는 Task 상태가 바뀌어 done 을 반영하지 못했다", CONFLICT)
            body = json.dumps({"dispatch": dispatch_id, "task": cur["task_id"], "outcome": outcome, "summary": summary,
                               "report_path": report_path, "files_modified": files}, ensure_ascii=False)
            mailbox.post(store, run_id=run_id, mailbox=f"run:{run_id}", sender=f"dispatch:{dispatch_id}",
                         type="worker_done", subject=f"{outcome} {dispatch_id}", body=body, dispatch_id=dispatch_id)
            duplicate = False
    wake = None if duplicate else mailbox.wake(store, f"run:{run_id}")
    final = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    return {"dispatch": {"id": final["id"], "task": final["task_id"], "state": final["state"],
                         "outcome": final["outcome"], "summary": final["summary"], "report_path": final["report_path"],
                         "files_modified": json.loads(final["files_modified"] or "[]")},
            "duplicate": duplicate, "wake": wake}
