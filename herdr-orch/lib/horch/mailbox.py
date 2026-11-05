"""메일함: 쓰기, Delivery, ack, 대기, 깨우기(설계 9장)."""
from __future__ import annotations

import os
import sqlite3
import time

from . import hcio, procs
from .errors import USAGE, HorchError
from .ids import now
from .liveness import status_word
from .paths import horch_cmd

BATCH = 50


def poll_interval() -> float:
    return float(os.environ.get("HORCH_POLL", "1.0"))


def sweep_interval() -> float:
    return float(os.environ.get("HORCH_SWEEP_INTERVAL", "5.0"))


def rewake_interval() -> float:
    return float(os.environ.get("HORCH_REWAKE_INTERVAL", "60.0"))


def post(store, *, run_id: str, mailbox: str, sender: str, type: str, body: str, subject: str | None = None,
         reply_to: int | None = None, dispatch_id: str | None = None, ask_key: str | None = None) -> int:
    """메시지 한 건을 쓴다. 호출자가 트랜잭션을 연다."""
    cur = store.run(
        "INSERT INTO messages(run_id, mailbox, sender, type, subject, body, reply_to, dispatch_id, ask_key, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (run_id, mailbox, sender, type, subject, body, reply_to, dispatch_id, ask_key, now()))
    return int(cur.lastrowid)


def message_json(row) -> dict:
    return {"id": row["id"], "type": row["type"], "sender": row["sender"], "subject": row["subject"],
            "body": row["body"], "reply_to": row["reply_to"], "dispatch": row["dispatch_id"],
            "created_at": row["created_at"]}


def take(store, mailbox: str) -> dict:
    """ack 안 된 Delivery 가 있으면 그대로, 없으면 새 묶음(reply 제외, 최대 50건)."""
    with store.tx():
        open_row = store.one("SELECT id FROM deliveries WHERE mailbox=? AND acked_at IS NULL ORDER BY id LIMIT 1",
                             (mailbox,))
        if open_row:
            delivery = open_row["id"]
        else:
            ids = [r["id"] for r in store.all(
                "SELECT id FROM messages WHERE mailbox=? AND delivery_id IS NULL AND type != 'reply' "
                "ORDER BY id LIMIT ?", (mailbox, BATCH))]
            if not ids:
                return {"delivery": None, "messages": [], "count": 0}
            delivery = store.run("INSERT INTO deliveries(mailbox, created_at) VALUES (?,?)", (mailbox, now())).lastrowid
            store.run(f"UPDATE messages SET delivery_id=? WHERE id IN ({','.join('?' * len(ids))})", (delivery, *ids))
        rows = store.all("SELECT * FROM messages WHERE delivery_id=? ORDER BY id", (delivery,))
    messages = [message_json(r) for r in rows]
    return {"delivery": delivery, "messages": messages, "count": len(messages)}


def ack(store, mailbox: str, delivery: int) -> None:
    with store.tx():
        if not store.one("SELECT id FROM deliveries WHERE id=? AND mailbox=?", (delivery, mailbox)):
            raise HorchError("unknown_delivery", f"이 메일함에 Delivery {delivery} 가 없다", USAGE)
        store.run("UPDATE deliveries SET acked_at=? WHERE id=? AND acked_at IS NULL", (now(), delivery))


def _register_waiter(store, mailbox: str, terminal: str | None) -> int:
    pid, started = procs.me()
    with store.tx():
        store.run("INSERT OR REPLACE INTO waiters(mailbox, pid, pid_started, terminal, started_at) VALUES (?,?,?,?,?)",
                  (mailbox, pid, started, terminal, now()))
    return pid


def _unregister_waiter(store, mailbox: str, pid: int) -> None:
    with store.tx():
        store.run("DELETE FROM waiters WHERE mailbox=? AND pid=?", (mailbox, pid))


def has_live_waiter(store, mailbox: str) -> bool:
    """살아 있고 지금 이 메일함의 수신자 터미널이 등록한 waiter 만 센다.
    소유권이 옮겨간 뒤 남은 옛 소유자의 waiter 는 깨우기를 막지 못한다."""
    target = _target(store, mailbox)
    live, dead = False, []
    for row in store.all("SELECT pid, pid_started, terminal FROM waiters WHERE mailbox=?", (mailbox,)):
        if procs.alive(row["pid"], row["pid_started"]):
            if target and row["terminal"] == target:
                live = True
        else:
            dead.append((row["pid"], row["pid_started"]))
    if dead:
        with store.tx():
            for pid, started in dead:
                # pid 가 재사용돼 새 waiter 가 등록됐다면 pid_started 가 달라 지워지지 않는다.
                store.run("DELETE FROM waiters WHERE mailbox=? AND pid=? AND pid_started=?", (mailbox, pid, started))
    return live


def check(store, mailbox: str, *, wait: bool = False, timeout_ms: int = 900000, ack_id: int | None = None,
          terminal: str | None = None, on_tick=None, guard=None) -> dict:
    """guard: 대기 중 매 틱과 묶음을 돌려주기 전에 부른다. 호출자가 더는 이 메일함의 수신자가 아니면 예외를 낸다."""
    if ack_id is not None:
        ack(store, mailbox, ack_id)
    res = take(store, mailbox)
    if res["count"] or not wait:
        return {**res, "reason": "message" if res["count"] else "empty"}
    pid = _register_waiter(store, mailbox, terminal)
    try:
        deadline = time.monotonic() + timeout_ms / 1000
        next_tick = time.monotonic()
        while True:
            if on_tick is not None and time.monotonic() >= next_tick:
                on_tick()
                next_tick = time.monotonic() + sweep_interval()
            if guard is not None:
                guard()
            res = take(store, mailbox)
            if res["count"]:
                return {**res, "reason": "message"}
            left = deadline - time.monotonic()
            if left <= 0:
                return {"delivery": None, "messages": [], "count": 0, "reason": "timeout"}
            time.sleep(min(poll_interval(), left))
    finally:
        _unregister_waiter(store, mailbox, pid)


def _target(store, mailbox: str) -> str | None:
    kind, _, ident = mailbox.partition(":")
    if kind == "run":
        row = store.one("SELECT terminal FROM bindings WHERE run_id=?", (ident,))
    else:
        row = store.one("SELECT terminal FROM dispatches WHERE id=?", (ident,))
    return row["terminal"] if row else None


def wake_text(home, mailbox: str) -> str:
    cmd = horch_cmd(home) + " check"
    if mailbox.startswith("dispatch:"):
        cmd += " --dispatch " + mailbox.split(":", 1)[1]
    return f"[horch] 새 메시지가 있다. 확인: {cmd}"


def wake(store, mailbox: str) -> str:
    """보조 깨우기. 트랜잭션 밖에서 부른다. 실패해도 예외를 내지 않는다(DB 오류 포함: 메시지는 이미 커밋됐다)."""
    if os.environ.get("CODEX_SANDBOX"):
        return "skipped_sandbox"
    try:
        if has_live_waiter(store, mailbox):
            return "skipped_waiter"
        terminal = _target(store, mailbox)
        if not terminal:
            return "no_target"
        word = status_word(hcio.get(terminal))
        text = wake_text(store.home, mailbox)
        if word == "idle":
            hcio.send(terminal, text, if_status="idle")
            return "sent"
        if word in ("done", "error"):
            # done: 턴을 마쳤지만 아무도 안 본 Claude 는 done 에 머문다(설계 9장, 사전 검증 S3).
            # hc send --if 는 done 을 받지 않으므로 조건 없이 보낸다.
            hcio.send(terminal, text)
            return "sent"
        return f"skipped_{word or 'unknown'}"
    except sqlite3.Error:
        return "failed_db"
    except hcio.HcFailure as exc:
        return f"failed_{exc.kind}"
    except HorchError as exc:
        return f"failed_{exc.code}"
