import json
import time
import unittest

from tests.helpers import HorchCase


class CommsTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id)

    def w(self, *args):
        return self.horch(*args, terminal="t9")

    def owner(self, *args):
        return self.horch(*args, terminal="t100")

    def wait_question(self):
        for _ in range(100):
            row = self.db().execute("SELECT id FROM messages WHERE type='question'").fetchone()
            if row:
                return row["id"]
            time.sleep(0.05)
        self.fail("질문이 생기지 않았다")

    def test_done_settles_and_reports(self):
        code, out = self.w("done", "--dispatch", self.did, "--outcome", "succeeded", "--summary", "끝",
                           "--report-path", "r.md", "--files-modified", "a.py", "--files-modified", "b.py")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["dispatch"]["state"], out["duplicate"]), ("settled", False))
        task = self.db().execute("SELECT status, outcome FROM tasks WHERE id='task-00000001'").fetchone()
        self.assertEqual((task["status"], task["outcome"]), ("settled", "succeeded"))
        _, box = self.owner("check")
        msg = box["messages"][0]
        self.assertEqual((msg["type"], msg["sender"]), ("worker_done", f"dispatch:{self.did}"))
        self.assertEqual(json.loads(msg["body"])["files_modified"], ["a.py", "b.py"])

    def test_done_is_idempotent_across_states(self):
        args = ("done", "--dispatch", self.did, "--outcome", "failed", "--summary", "s")
        self.w(*args)
        for state in ("settled", "retained", "released"):
            with self.subTest(state=state):
                db = self.db()
                db.execute("UPDATE dispatches SET state=? WHERE id=?", (state, self.did))
                db.commit()
                code, out = self.w(*args)
                self.assertEqual((code, out["duplicate"]), (0, True))
        code, out = self.w("done", "--dispatch", self.did, "--outcome", "failed", "--summary", "다름")
        self.assertEqual((code, out["error"]["code"]), (3, "done_conflict"))
        n = self.db().execute("SELECT COUNT(*) FROM messages WHERE type='worker_done'").fetchone()[0]
        self.assertEqual(n, 1)

    def test_done_rules(self):
        self.add_terminal("t50")
        code, out = self.horch("done", "--dispatch", self.did, "--outcome", "succeeded", "--summary", "s", terminal="t50")
        self.assertEqual((code, out["error"]["code"]), (5, "not_this_worker"))
        # $HC_TERMINAL_ID 가 없는 도구(Codex node_repl 등)에서 부른 경우도 같은 오류다. 힌트가 셸 명령을 알려 준다
        code, none = self.horch("done", "--dispatch", self.did, "--outcome", "succeeded", "--summary", "s")
        self.assertEqual((code, none["error"]["code"]), (5, "not_this_worker"))
        for err in (out["error"], none["error"]):
            self.assertIn("워커 터미널에서만", err["hint"])
            self.assertIn("셸 명령", err["hint"])
            self.assertIn("HC_TERMINAL_ID", err["hint"])
        db = self.db()
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (self.did,))
        db.commit()
        code, out = self.w("done", "--dispatch", self.did, "--outcome", "succeeded", "--summary", "s")
        self.assertEqual((code, out["error"]["code"]), (3, "dispatch_not_active"))

    def test_ask_reply_roundtrip_and_reuse(self):
        proc = self.horch_bg("ask", "--dispatch", self.did, "--question", "어느 DB?", "--timeout-ms", "10000", terminal="t9")
        qid = self.wait_question()
        _, box = self.owner("check")
        self.assertEqual((box["messages"][0]["type"], box["messages"][0]["body"]), ("question", "어느 DB?"))
        code, rep = self.owner("reply", "--id", str(qid), "--body", "SQLite")
        self.assertEqual((code, rep["duplicate"]), (0, False))
        code, out = self.finish(proc)
        self.assertEqual((code, out["answer"], out["reused"], out["question"]), (0, "SQLite", False, qid))
        code, again = self.w("ask", "--dispatch", self.did, "--question", "어느 DB?")
        self.assertEqual((code, again["answer"], again["reused"]), (0, "SQLite", True))
        code, dup = self.owner("reply", "--id", str(qid), "--body", "SQLite")
        self.assertEqual((code, dup["duplicate"]), (0, True))
        code, bad = self.owner("reply", "--id", str(qid), "--body", "Postgres")
        self.assertEqual((code, bad["error"]["code"]), (3, "reply_conflict"))
        _, wbox = self.w("check", "--dispatch", self.did)
        self.assertEqual(wbox["count"], 0)

    def test_ask_key_conflict_and_new_key(self):
        db = self.db()
        db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, dispatch_id, ask_key, created_at) "
                   "VALUES (?, ?, 'x', 'question', 'A', ?, 'k1', 'x')", (self.run_id, f"run:{self.run_id}", self.did))
        db.commit()
        code, out = self.w("ask", "--dispatch", self.did, "--key", "k1", "--question", "B", "--timeout-ms", "100")
        self.assertEqual((code, out["error"]["code"]), (3, "ask_key_conflict"))
        code, out = self.w("ask", "--dispatch", self.did, "--key", "k2", "--question", "A", "--timeout-ms", "100")
        self.assertEqual(code, 4)

    def test_ask_timeout_then_resume(self):
        code, out = self.w("ask", "--dispatch", self.did, "--question", "Q", "--timeout-ms", "300")
        self.assertEqual((code, out["error"]["code"]), (4, "timeout"))
        qid = out["question"]
        self.owner("reply", "--id", str(qid), "--body", "A")
        code, res = self.w("ask", "--dispatch", self.did, "--resume", str(qid), "--timeout-ms", "300")
        self.assertEqual((code, res["answer"]), (0, "A"))

    def test_ask_ends_when_abandoned(self):
        proc = self.horch_bg("ask", "--dispatch", self.did, "--question", "Q", "--timeout-ms", "10000", terminal="t9")
        self.wait_question()
        db = self.db()
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (self.did,))
        db.commit()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"]), (3, "dispatch_not_active"))

    def test_ask_rewakes_idle_owner(self):
        self.update_terminal("t100", status="idle")
        code, out = self.w("ask", "--dispatch", self.did, "--question", "Q", "--timeout-ms", "1500")
        self.assertEqual(code, 4)
        self.assertGreaterEqual(len([s for s in self.hc_sent() if s["terminal"] == "t100"]), 2)

    def test_escalate(self):
        code, out = self.w("escalate", "--dispatch", self.did, "--body", "범위 밖")
        self.assertEqual(code, 0, out)
        _, box = self.owner("check")
        self.assertEqual((box["messages"][0]["type"], box["messages"][0]["body"]), ("escalation", "범위 밖"))

    def test_reply_rules(self):
        code, out = self.owner("reply", "--id", "999", "--body", "x")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_question"))
        code, out = self.w("reply", "--id", "1", "--body", "x")
        self.assertEqual(code, 5)

    def test_reply_rechecks_ownership_inside_tx(self):
        """소유권 확인과 트랜잭션 사이에 binding 이 옮겨지면 옛 소유자의 답은 exit 5 이고 기록되지 않는다."""
        import os
        from unittest import mock
        from horch import comms
        from horch.errors import HorchError
        from horch.store import Store
        db = self.db()
        db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, dispatch_id, ask_key, created_at) "
                   "VALUES (?, ?, 'x', 'question', 'Q', ?, 'k', 'x')", (self.run_id, f"run:{self.run_id}", self.did))
        db.commit()
        qid = db.execute("SELECT id FROM messages WHERE type='question'").fetchone()["id"]
        store = Store(self.home)
        self.addCleanup(store.close)
        real_tx = store.tx

        def moving_tx():
            store.run("UPDATE bindings SET terminal='t200' WHERE run_id=?", (self.run_id,))
            return real_tx()

        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t100"}):
            with mock.patch.object(store, "tx", moving_tx):
                with self.assertRaises(HorchError) as cm:
                    comms.reply(store, qid, "옛 답")
        self.assertEqual((cm.exception.exit_code, cm.exception.code), (5, "not_owner"))
        n = self.db().execute("SELECT COUNT(*) FROM messages WHERE type='reply'").fetchone()[0]
        self.assertEqual(n, 0)
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t200"}):
            out = comms.reply(store, qid, "새 답")
        self.assertFalse(out["duplicate"])

    def test_ask_state_wins_over_answer(self):
        for state in ("abandoned", "settled"):
            with self.subTest(state=state):
                db = self.db()
                db.execute("DELETE FROM messages")
                db.execute("UPDATE dispatches SET state='active' WHERE id=?", (self.did,))
                db.commit()
                code, out = self.w("ask", "--dispatch", self.did, "--question", "Q", "--timeout-ms", "200")
                self.assertEqual(code, 4)
                qid = out["question"]
                self.owner("reply", "--id", str(qid), "--body", "A")
                db.execute("UPDATE dispatches SET state=? WHERE id=?", (state, self.did))
                db.commit()
                code, out = self.w("ask", "--dispatch", self.did, "--resume", str(qid), "--timeout-ms", "200")
                self.assertEqual((code, out["error"]["code"], out["question"]), (3, "dispatch_not_active", qid))

    def test_wait_answer_checks_state_before_answer(self):
        """대기 루프: 답이 이미 있어도 Dispatch 가 active 가 아니면 exit 3(question 포함)."""
        from horch import comms
        from horch.errors import HorchError
        from horch.store import Store
        db = self.db()
        db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, dispatch_id, ask_key, created_at) "
                   "VALUES (?, ?, 'x', 'question', 'Q', ?, 'k', 'x')", (self.run_id, f"run:{self.run_id}", self.did))
        qid = db.execute("SELECT id FROM messages WHERE type='question'").fetchone()["id"]
        db.execute("INSERT INTO messages(run_id, mailbox, sender, type, body, dispatch_id, reply_to, created_at) "
                   "VALUES (?, ?, 'x', 'reply', 'A', ?, ?, 'x')", (self.run_id, f"dispatch:{self.did}", self.did, qid))
        db.commit()
        store = Store(self.home)
        self.addCleanup(store.close)
        for state in ("abandoned", "settled"):
            with self.subTest(state=state):
                db.execute("UPDATE dispatches SET state=? WHERE id=?", (state, self.did))
                db.commit()
                with self.assertRaises(HorchError) as cm:
                    comms._wait_answer(store, self.did, self.run_id, qid, 200, True)
                self.assertEqual((cm.exception.exit_code, cm.exception.code, cm.exception.data),
                                 (3, "dispatch_not_active", {"question": qid}))

    def test_done_conflicts_when_task_not_open(self):
        db = self.db()
        db.execute("UPDATE tasks SET status='settled' WHERE id='task-00000001'")
        db.commit()
        code, out = self.w("done", "--dispatch", self.did, "--outcome", "succeeded", "--summary", "s")
        self.assertEqual((code, out["error"]["code"]), (3, "conflict"))
        row = self.db().execute("SELECT state FROM dispatches WHERE id=?", (self.did,)).fetchone()
        self.assertEqual(row["state"], "active")
        n = self.db().execute("SELECT COUNT(*) FROM messages WHERE type='worker_done'").fetchone()[0]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
