import json
import time
import unittest

from tests.helpers import HorchCase


class RunCreateTest(HorchCase):
    def test_requires_terminal(self):
        code, out = self.horch("run-create", "--objective", "x")
        self.assertEqual(code, 5)
        self.assertEqual(out["error"]["code"], "no_terminal")

    def test_records_owner_labels_and_argv(self):
        run_id = self.make_owner("t100", "spA", "tbA")
        row = self.db().execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        self.assertEqual((row["owner_space"], row["owner_tab"]), ("spA", "tbA"))
        b = self.db().execute("SELECT * FROM bindings WHERE run_id=?", (run_id,)).fetchone()
        self.assertEqual(b["terminal"], "t100")
        self.assertEqual(json.loads(b["argv"]), ["claude"])

    def test_without_herdr_labels_placement_none(self):
        self.add_terminal("t101", argv=["claude"])
        code, out = self.horch("run-create", "--objective", "x", terminal="t101")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["placement"], "none")
        self.assertIsNone(out["run"]["owner_tab"])

    def test_hc_cannot_read_caller(self):
        code, out = self.horch("run-create", "--objective", "x", terminal="t404")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"]["code"], "hc_unavailable")

    def test_second_create_leaves_first_ownerless(self):
        first = self.make_owner("t100")
        code, out = self.horch("run-create", "--objective", "y", terminal="t100")
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.db().execute("SELECT 1 FROM bindings WHERE run_id=?", (first,)).fetchone())

    def test_worker_terminal_cannot_create(self):
        run_id = self.make_owner("t100")
        db = self.db()
        db.execute("INSERT INTO tasks(id, run_id, title, spec, status, created_at) VALUES ('task-00000001', ?, 't', 's', 'open', 'x')", (run_id,))
        db.execute("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, terminal, state, created_at) "
                   "VALUES ('dsp-00000001', 'task-00000001', ?, 1, 'claude', '/', 't9', 'active', 'x')", (run_id,))
        db.commit()
        self.add_terminal("t9", argv=["x"])
        code, out = self.horch("run-create", "--objective", "x", terminal="t9")
        self.assertEqual(code, 5)
        self.assertEqual(out["error"]["code"], "worker_terminal")


class RunUseTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100", "spA", "tbA")
        self.add_terminal("t200", argv=["claude"], labels={"herdr.space": "spB", "herdr.tab": "tbB"})

    def use(self, *extra, terminal="t200"):
        return self.horch("run-use", "--id", self.run_id, *extra, terminal=terminal)

    def owner(self):
        row = self.db().execute("SELECT terminal FROM bindings WHERE run_id=?", (self.run_id,)).fetchone()
        return row["terminal"] if row else None

    def test_self_is_noop(self):
        code, out = self.use(terminal="t100")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["previous_owner"], "t100")
        self.assertIsNone(out["previous_verdict"])

    def test_self_is_noop_without_hc(self):
        self.fail_hc("get", "timeout")
        code, out = self.use(terminal="t100")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["previous_owner"], "t100")
        self.assertEqual(self.owner(), "t100")

    def test_live_owner_refused(self):
        code, out = self.use()
        self.assertEqual(code, 3)
        self.assertEqual(out["error"]["code"], "owner_alive")
        self.assertEqual(self.owner(), "t100")

    def test_exited_owner_taken_over_and_tab_updated(self):
        self.update_terminal("t100", state="finished")
        code, out = self.use()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["previous_verdict"], "exited")
        self.assertEqual(self.owner(), "t200")
        self.assertEqual((out["run"]["owner_space"], out["run"]["owner_tab"]), ("spB", "tbB"))

    def test_lost_owner_taken_over(self):
        self.update_terminal("t100", argv=["/bin/zsh", "-l"])
        code, out = self.use()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["previous_verdict"], "lost")

    def test_restart_reason_is_lost(self):
        self.update_terminal("t100", reason="stopped_by_restart")
        code, out = self.use()
        self.assertEqual(code, 0, out)

    def test_unverifiable_needs_force(self):
        st = self.hc_state()
        del st["terminals"]["t100"]
        self.set_hc_state(st)
        code, out = self.use()
        self.assertEqual(code, 3)
        self.assertEqual(out["error"]["code"], "owner_unverifiable")
        code, out = self.use("--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.owner(), "t200")

    def test_rebind_during_judgement_is_blocked(self):
        """판정은 쓰기 트랜잭션 안에서 한다. 판정 중 t100 이 같은 terminal·argv 로 다시 묶으려는 쓰기는 잠금에 막힌다."""
        import os
        import sqlite3
        from unittest import mock
        from horch import runs
        from horch.store import Store
        seen = []
        with mock.patch.dict(os.environ, dict(self.env, HC_TERMINAL_ID="t200"), clear=True):
            store = Store(self.home)
            self.addCleanup(store.close)

            def rebind_attempt(*_a, **_k):
                other = sqlite3.connect(self.home / "orch.db", isolation_level=None, timeout=0.1)
                try:
                    other.execute("BEGIN IMMEDIATE")
                    other.execute("UPDATE bindings SET argv=argv WHERE run_id=?", (self.run_id,))
                    other.execute("COMMIT")
                    seen.append("written")
                except sqlite3.OperationalError as exc:
                    seen.append(str(exc))
                finally:
                    other.close()
                return "lost", None

            with mock.patch.object(runs.liveness, "probe", side_effect=rebind_attempt):
                out = runs.use(store, self.run_id, False)
        self.assertEqual(seen, ["database is locked"])
        self.assertEqual(out["previous_verdict"], "lost")
        self.assertEqual(self.owner(), "t200")

    # --- 설계 12장: 넘겨받기 표 전부 ---
    def test_ownerless_run_is_taken_without_probe(self):
        code, out = self.horch("run-create", "--objective", "other", terminal="t100")  # 첫 Run 은 소유자 없음
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.owner())
        before = len(self.hc_calls())
        code, out = self.use()
        self.assertEqual(code, 0, out)
        self.assertEqual((out["previous_owner"], out["previous_verdict"]), (None, None))
        self.assertEqual(self.owner(), "t200")
        self.assertNotIn(["get", "t100", "--json"], self.hc_calls()[before:])  # 판정할 소유자가 없다

    def test_live_owner_refused_even_with_force(self):
        code, out = self.use("--force")
        self.assertEqual(code, 3, out)
        self.assertEqual(out["error"]["code"], "owner_alive")
        self.assertEqual(self.owner(), "t100")

    def test_worker_terminal_cannot_use(self):
        self.update_terminal("t100", state="finished")
        self.add_dispatch(self.run_id, terminal="t9")
        code, out = self.use(terminal="t9")
        self.assertEqual(code, 5, out)
        self.assertEqual(out["error"]["code"], "worker_terminal")
        self.assertEqual(self.owner(), "t100")

    def test_caller_previous_binding_is_dropped(self):
        code, out = self.horch("run-create", "--objective", "mine", terminal="t200")
        self.assertEqual(code, 0, out)
        other = out["run"]["id"]
        self.update_terminal("t100", state="finished")
        code, out = self.use()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.owner(), "t200")
        self.assertIsNone(self.db().execute("SELECT 1 FROM bindings WHERE run_id=?", (other,)).fetchone())

    # --- 판정은 잠금 안에서 한다: 느린 hc 가 잠금을 오래 쥐지 않게 한다 ---
    def test_slow_owner_probe_is_unverifiable_quickly(self):
        self.delay_hc("get t100", 10)
        t0 = time.monotonic()
        code, out = self.use()
        self.assertLess(time.monotonic() - t0, 6)
        self.assertEqual(code, 3, out)
        self.assertEqual(out["error"]["code"], "owner_unverifiable")
        self.assertEqual(self.owner(), "t100")

    def test_readers_work_during_slow_run_use(self):
        self.delay_hc("get t100", 10)
        probe = ["get", "t100", "--json"]
        seen = self.hc_calls().count(probe)  # run-create 가 이미 t100 을 읽었다
        proc = self.horch_bg("run-use", "--id", self.run_id, terminal="t200")
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        limit = time.monotonic() + 10
        while self.hc_calls().count(probe) == seen:  # 판정(잠금 안의 hc get)이 시작될 때까지
            self.assertLess(time.monotonic(), limit, "run-use 가 판정을 시작하지 않았다")
            time.sleep(0.02)
        t0 = time.monotonic()
        code, out = self.horch("status", terminal="t100")
        self.assertEqual(code, 0, out)
        self.assertLess(time.monotonic() - t0, 2.0)  # 쓰기 잠금을 기다리지 않는다
        self.assertEqual(out["run"]["id"], self.run_id)
        code, out = self.finish(proc, timeout=20)
        self.assertEqual((code, out["error"]["code"]), (3, "owner_unverifiable"), out)

    def test_unknown_run(self):
        code, out = self.horch("run-use", "--id", "run-ffffffff", terminal="t200")
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "unknown_run")


if __name__ == "__main__":
    unittest.main()
