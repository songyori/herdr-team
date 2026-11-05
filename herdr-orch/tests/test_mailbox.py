import time
import unittest

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


if __name__ == "__main__":
    unittest.main()
