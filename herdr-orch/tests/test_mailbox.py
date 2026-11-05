import os
import sqlite3
import threading
import time
import unittest
from unittest import mock

from tests.helpers import HorchCase


class MailboxTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")

    def owner_check(self, *extra):
        return self.horch("check", *extra, terminal="t100")

    def test_external_send_then_owner_check_and_replay(self):
        code, out = self.horch("send", "--to", f"run:{self.run_id}", "--subject", "hi", "--body", "hello")
        self.assertEqual(code, 0, out)
        code, first = self.owner_check()
        self.assertEqual(code, 0, first)
        self.assertEqual((first["count"], first["reason"]), (1, "message"))
        msg = first["messages"][0]
        self.assertEqual((msg["type"], msg["sender"], msg["body"]), ("status", "external:none", "hello"))
        _, again = self.owner_check()
        self.assertEqual(again["delivery"], first["delivery"])
        _, after = self.owner_check("--ack", str(first["delivery"]))
        self.assertEqual((after["count"], after["delivery"], after["reason"]), (0, None, "empty"))
        code, twice = self.owner_check("--ack", str(first["delivery"]))
        self.assertEqual(code, 0, twice)

    def test_unknown_ack_is_usage(self):
        code, out = self.owner_check("--ack", "999")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "unknown_delivery")

    def test_batches_of_50_in_order(self):
        db = self.db()
        for i in range(60):
            db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, created_at) VALUES (?, ?, 'x', 'status', ?, 'x')",
                       (self.run_id, f"run:{self.run_id}", str(i)))
        db.commit()
        _, first = self.owner_check()
        self.assertEqual([m["body"] for m in first["messages"]], [str(i) for i in range(50)])
        _, second = self.owner_check("--ack", str(first["delivery"]))
        self.assertEqual([m["body"] for m in second["messages"]], [str(i) for i in range(50, 60)])

    def test_owner_cannot_send_to_own_run(self):
        code, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x", terminal="t100")
        self.assertEqual(code, 5)
        self.assertEqual(out["error"]["code"], "owner_to_self")

    def test_worker_send_to_run_is_from_dispatch(self):
        did = self.add_dispatch(self.run_id)
        self.horch("send", "--to", f"run:{self.run_id}", "--body", "x", terminal="t9")
        _, out = self.owner_check()
        self.assertEqual(out["messages"][0]["sender"], f"dispatch:{did}")

    def test_send_to_dispatch_rules(self):
        did = self.add_dispatch(self.run_id)
        code, out = self.horch("send", "--to", f"dispatch:{did}", "--body", "x", terminal="t9")
        self.assertEqual(code, 5)
        code, out = self.horch("send", "--to", f"dispatch:{did}", "--body", "go", terminal="t100")
        self.assertEqual(code, 0, out)
        code, wout = self.horch("check", "--dispatch", did, terminal="t9")
        self.assertEqual((wout["count"], wout["messages"][0]["body"]), (1, "go"))
        self.db().execute("UPDATE dispatches SET state='settled' WHERE id=?", (did,)).connection.commit()
        code, out = self.horch("send", "--to", f"dispatch:{did}", "--body", "x", terminal="t100")
        self.assertEqual(code, 3)

    def test_worker_check_identity_and_state(self):
        did = self.add_dispatch(self.run_id)
        self.add_terminal("t50")
        code, out = self.horch("check", "--dispatch", did, terminal="t50")
        self.assertEqual(code, 5)
        db = self.db()
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (did,))
        db.commit()
        code, out = self.horch("check", "--dispatch", did, terminal="t9")
        self.assertEqual(code, 3)

    def test_replies_not_in_check(self):
        did = self.add_dispatch(self.run_id)
        db = self.db()
        db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, reply_to, created_at) VALUES (?, ?, 'x', 'reply', 'a', 1, 'x')",
                   (self.run_id, f"dispatch:{did}"))
        db.commit()
        _, out = self.horch("check", "--dispatch", did, terminal="t9")
        self.assertEqual(out["count"], 0)

    def _wait_for_waiter(self):
        for _ in range(100):
            if self.db().execute("SELECT 1 FROM waiters").fetchone():
                return
            time.sleep(0.05)
        self.fail("waiter 가 등록되지 않았다")

    def test_wait_returns_on_message_and_skips_wake(self):
        proc = self.horch_bg("check", "--wait", "--timeout-ms", "10000", terminal="t100")
        self._wait_for_waiter()
        code, sent = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        self.assertIn(sent["wake"], ("skipped_waiter", "skipped_working"))
        code, out = self.finish(proc)
        self.assertEqual((code, out["count"], out["reason"]), (0, 1, "message"))
        self.assertIsNone(self.db().execute("SELECT 1 FROM waiters").fetchone())

    def test_live_waiter_suppresses_wake(self):
        from horch import procs
        self.update_terminal("t100", status="idle")
        pid, started = procs.me()
        db = self.db()
        db.execute("INSERT INTO waiters(mailbox, pid, pid_started, terminal, started_at) VALUES (?, ?, ?, 't100', 'x')",
                   (f"run:{self.run_id}", pid, started))
        db.commit()
        _, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        self.assertEqual(out["wake"], "skipped_waiter")
        self.assertEqual(self.hc_sent(), [])

    def test_concurrent_checks_share_delivery(self):
        self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        procs_ = [self.horch_bg("check", terminal="t100") for _ in range(3)]
        deliveries = {self.finish(p)[1]["delivery"] for p in procs_}
        self.assertEqual(len(deliveries), 1)
        self.assertIsNotNone(deliveries.pop())

    def test_wait_timeout(self):
        code, out = self.owner_check("--wait", "--timeout-ms", "300")
        self.assertEqual((code, out["count"], out["reason"], out["delivery"]), (0, 0, "timeout", None))

    def test_wake_by_status(self):
        cases = [("idle", "sent", "idle"), ("done", "sent", None), ("error", "sent", None),
                 ("working", "skipped_working", None), ("blocked", "skipped_blocked", None)]
        for word, expect, if_ in cases:
            with self.subTest(word=word):
                st = self.hc_state()
                st["sent"] = []
                self.set_hc_state(st)
                self.update_terminal("t100", status=word)
                _, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
                self.assertEqual(out["wake"], expect)
                if expect == "sent":
                    sent = self.hc_sent()[-1]
                    self.assertEqual((sent["terminal"], sent["if"]), ("t100", if_))
                    self.assertIn("check", sent["text"])
                    self.assertIn("--home", sent["text"])

    def test_wake_skipped_in_codex_sandbox(self):
        self.update_terminal("t100", status="idle")
        _, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x", env={"CODEX_SANDBOX": "seatbelt"})
        self.assertEqual(out["wake"], "skipped_sandbox")
        self.assertEqual(self.hc_sent(), [])

    def test_dead_waiter_is_cleaned(self):
        self.update_terminal("t100", status="idle")
        db = self.db()
        db.execute("INSERT INTO waiters(mailbox, pid, pid_started, terminal, started_at) VALUES (?, 999999, 'never', 't100', 'x')",
                   (f"run:{self.run_id}",))
        db.commit()
        _, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        self.assertEqual(out["wake"], "sent")
        self.assertIsNone(self.db().execute("SELECT 1 FROM waiters").fetchone())

    def test_wake_db_error_is_failed_db_not_exception(self):
        import sqlite3
        from horch import mailbox
        from horch.store import Store
        self.update_terminal("t100", status="idle")
        box = f"run:{self.run_id}"
        db = self.db()
        db.execute("INSERT INTO waiters(mailbox, pid, pid_started, terminal, started_at) VALUES (?, 999999, 'never', 't100', 'x')", (box,))
        db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, created_at) VALUES (?, ?, 'x', 'status', 'm', 'x')",
                   (self.run_id, box))
        db.commit()
        store = Store(self.home)
        self.addCleanup(store.conn.close)
        store.conn.execute("PRAGMA busy_timeout=50")
        locker = sqlite3.connect(self.home / "orch.db", isolation_level=None)
        self.addCleanup(locker.close)
        locker.execute("BEGIN IMMEDIATE")
        # wake 은 os.environ 의 CODEX_SANDBOX 를 읽는다. 샌드박스 안에서도 실제 DB 경로를 타도록 비운다.
        with mock.patch.dict(os.environ):
            os.environ.pop("CODEX_SANDBOX", None)
            try:
                self.assertEqual(mailbox.wake(store, box), "failed_db")
            finally:
                locker.execute("ROLLBACK")
        self.assertIsNotNone(self.db().execute("SELECT 1 FROM messages WHERE body='m'").fetchone())

    def test_dead_waiter_cleanup_keeps_reused_pid_row(self):
        from horch import mailbox
        from horch.store import Store
        box = f"run:{self.run_id}"
        db = self.db()
        db.execute("INSERT INTO waiters(mailbox, pid, pid_started, terminal, started_at) VALUES (?, 999999, 'never', 't100', 'x')", (box,))
        db.commit()
        store = Store(self.home)
        self.addCleanup(store.conn.close)
        real = store.all

        def racing_all(sql, params=()):
            rows = real(sql, params)
            if "FROM waiters" in sql:  # 읽은 뒤 같은 pid 로 새 waiter 가 등록된 상황
                db.execute("UPDATE waiters SET pid_started='fresh' WHERE pid=999999")
                db.commit()
            return rows
        store.all = racing_all
        mailbox.has_live_waiter(store, box)
        row = self.db().execute("SELECT pid_started FROM waiters WHERE pid=999999").fetchone()
        self.assertIsNotNone(row)

    def test_owner_change_ends_run_wait_and_wake_not_suppressed(self):
        proc = self.horch_bg("check", "--wait", "--timeout-ms", "20000", terminal="t100")
        self._wait_for_waiter()
        code, out = self.horch("run-create", "--objective", "other", terminal="t100")
        self.assertEqual(code, 0, out)
        self.add_terminal("t200", argv=["claude"], labels={"herdr.space": "spB", "herdr.tab": "tbB"}, status="working")
        code, out = self.horch("run-use", "--id", self.run_id, terminal="t200")
        self.assertEqual(code, 0, out)
        code, sent = self.horch("send", "--to", f"run:{self.run_id}", "--body", "late")
        self.assertEqual(code, 0, sent)
        self.assertNotEqual(sent["wake"], "skipped_waiter")
        code, out = self.finish(proc, timeout=10)
        self.assertEqual(code, 5, out)
        self.assertNotIn("messages", out)
        self.assertIsNone(self.db().execute("SELECT 1 FROM waiters").fetchone())

    def test_waiter_of_old_owner_does_not_suppress_wake(self):
        from horch import procs
        pid, started = procs.me()
        db = self.db()
        db.execute("INSERT INTO waiters(mailbox, pid, pid_started, terminal, started_at) VALUES (?, ?, ?, 't999', 'x')",
                   (f"run:{self.run_id}", pid, started))
        db.commit()
        _, out = self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        self.assertEqual(out["wake"], "skipped_working")

    def test_send_to_other_runs_or_unknown_dispatch_is_conflict(self):
        did = self.add_dispatch(self.run_id)
        self.make_owner("t300")
        code, out = self.horch("send", "--to", f"dispatch:{did}", "--body", "x", terminal="t300")
        self.assertEqual(code, 3, out)
        code, out = self.horch("send", "--to", "dispatch:dsp-ffffffff", "--body", "x", terminal="t100")
        self.assertEqual(code, 3, out)

    def test_status(self):
        self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        code, out = self.horch("status", terminal="t100")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["run"]["id"], out["run"]["unread"]), (self.run_id, 1))
        did = self.add_dispatch(self.run_id)
        _, wout = self.horch("status", terminal="t9")
        self.assertEqual(wout["dispatch"], {"id": did, "state": "active"})
        _, none = self.horch("status")
        self.assertEqual((none["terminal"], none["run"]), (None, None))

    def test_status_unanswered_only_for_running_dispatches(self):
        # 버리거나 끝난 Dispatch 의 질문은 답할 필요가 없다. 남겨 두면 check --wait 를 띄울 이유가 끝나지 않는다
        live = self.add_dispatch(self.run_id, did="dsp-00000001", terminal="t9")
        gone = self.add_dispatch(self.run_id, did="dsp-00000002", terminal="t8", state="abandoned")
        done = self.add_dispatch(self.run_id, did="dsp-00000003", terminal="t7", state="settled")
        db = self.db()
        for did in (live, gone, done):
            db.execute("INSERT INTO messages(run_id, mailbox, sender, type, subject, body, dispatch_id, ask_key, created_at) "
                       "VALUES (?, ?, ?, 'question', 'q', ?, ?, 'k', 'x')",
                       (self.run_id, f"run:{self.run_id}", f"dispatch:{did}", f"q {did}", did))
        db.commit()
        code, out = self.horch("status", terminal="t100")
        self.assertEqual(code, 0, out)
        self.assertEqual([q["dispatch"] for q in out["run"]["unanswered"]], [live])

    # --- 소유권은 첫 ack·take 트랜잭션 안에서도 확인한다 ---
    def _store_as(self, terminal: str):
        from horch.store import Store
        patcher = mock.patch.dict(os.environ, dict(self.env, HC_TERMINAL_ID=terminal), clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        store = Store(self.home)
        self.addCleanup(store.close)
        return store

    def _move_binding_after_lookup(self):
        """comms.check 의 소유자 조회 바로 뒤(ack·take 트랜잭션 전)에 binding 을 t200 으로 옮긴다."""
        from horch import auth
        real = auth.owner_run_id
        moved = []

        def lookup(store):
            rid = real(store)
            if not moved:
                moved.append(rid)
                db = sqlite3.connect(self.home / "orch.db")
                db.execute("UPDATE bindings SET terminal='t200' WHERE run_id=?", (rid,))
                db.commit()
                db.close()
            return rid
        return mock.patch.object(auth, "owner_run_id", side_effect=lookup)

    def test_old_owner_cannot_ack_after_binding_moves(self):
        from horch import comms
        from horch.errors import DENIED, HorchError
        self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        _, first = self.owner_check()
        store = self._store_as("t100")
        with self._move_binding_after_lookup(), self.assertRaises(HorchError) as cm:
            comms.check(store, dispatch=None, wait=False, timeout_ms=1000, ack=first["delivery"])
        self.assertEqual(cm.exception.exit_code, DENIED)
        row = self.db().execute("SELECT acked_at FROM deliveries WHERE id=?", (first["delivery"],)).fetchone()
        self.assertIsNone(row["acked_at"])

    def test_old_owner_cannot_take_after_binding_moves(self):
        from horch import comms
        from horch.errors import DENIED, HorchError
        self.horch("send", "--to", f"run:{self.run_id}", "--body", "x")
        store = self._store_as("t100")
        with self._move_binding_after_lookup(), self.assertRaises(HorchError) as cm:
            comms.check(store, dispatch=None, wait=False, timeout_ms=1000, ack=None)
        self.assertEqual(cm.exception.exit_code, DENIED)
        self.assertIsNone(self.db().execute("SELECT 1 FROM deliveries").fetchone())
        self.assertIsNone(self.db().execute("SELECT 1 FROM messages WHERE delivery_id IS NOT NULL").fetchone())

    def test_send_to_dispatch_rechecks_ownership_inside_tx(self):
        """소유권 확인과 트랜잭션 사이에 binding 이 옮겨지면 옛 소유자의 send 는 exit 5 이고 기록되지 않는다."""
        from horch import comms
        from horch.errors import HorchError
        did = self.add_dispatch(self.run_id)
        store = self._store_as("t100")
        real_tx = store.tx

        def moving_tx():
            store.run("UPDATE bindings SET terminal='t200' WHERE run_id=?", (self.run_id,))
            return real_tx()

        with mock.patch.object(store, "tx", moving_tx), self.assertRaises(HorchError) as cm:
            comms.send(store, f"dispatch:{did}", None, "옛 소유자")
        self.assertEqual((cm.exception.exit_code, cm.exception.code), (5, "not_owner"))
        self.assertIsNone(self.db().execute("SELECT 1 FROM messages WHERE mailbox=?", (f"dispatch:{did}",)).fetchone())

    def test_wait_survives_brief_lock(self):
        # 대기 중 다른 쓰기가 잠금을 busy_timeout 보다 오래 쥐어도 그 폴링만 건너뛰고 계속 기다린다
        from horch import mailbox
        store = self._store_as("t100")
        store.conn.execute("PRAGMA busy_timeout=100")
        box = f"run:{self.run_id}"
        errors = []

        def holder():
            db = sqlite3.connect(self.home / "orch.db", isolation_level=None)
            try:
                limit = time.monotonic() + 5
                while not db.execute("SELECT 1 FROM waiters").fetchone() and time.monotonic() < limit:
                    time.sleep(0.01)
                db.execute("BEGIN IMMEDIATE")
                time.sleep(0.6)
                db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, created_at) "
                           "VALUES (?, ?, 'external:none', 'status', 'late', 'x')", (self.run_id, box))
                db.execute("COMMIT")
            except Exception as exc:  # 스레드 오류를 본 테스트에 드러낸다
                errors.append(exc)
            finally:
                db.close()

        th = threading.Thread(target=holder)
        th.start()
        self.addCleanup(th.join)
        res = mailbox.check(store, box, wait=True, timeout_ms=5000, terminal="t100")
        th.join()
        self.assertEqual(errors, [])
        self.assertEqual((res["reason"], res["count"]), ("message", 1))
        self.assertEqual(res["messages"][0]["body"], "late")


if __name__ == "__main__":
    unittest.main()
