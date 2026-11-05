import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import BIN, FAKES, ROOT, HorchCase
from horch import guard, hcio, procs, workers
from horch.errors import HorchError
from horch.store import Store


class WorkerStartCliTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100", "spA", "tbA")

    def dispatch(self, did):
        return self.db().execute("SELECT * FROM dispatches WHERE id=?", (did,)).fetchone()

    def test_claude_happy_path(self):
        out = self.start_worker(spec="스펙 본문", extra=("--model", "opus", "--effort", "high", "--agent-arg=--permission-mode=bypassPermissions"))
        did, term = out["dispatch"], out["terminal"]
        self.assertEqual((out["state"], out["placement"], out["warning"]), ("active", "pane", None))
        row = self.dispatch(did)
        self.assertEqual((row["state"], row["terminal"], row["attempt"]), ("active", term, 1))
        t = self.hc_state()["terminals"][term]
        self.assertEqual(t["name"], did)
        self.assertEqual(t["labels"], {"herdr.space": "spA", "herdr.tab": "tbA", "horch.run": self.run_id, "horch.dispatch": did})
        self.assertEqual(sorted(t["flags"]), ["--bg", "--no-notify", "--no-parent"])
        argv = t["argv"]
        self.assertEqual(json.loads(row["launch_argv"]), argv)
        self.assertEqual(argv[:4], [sys.executable, str(BIN), "--home", str(self.home)])
        sep = argv.index("--")
        self.assertEqual(argv[4:sep], ["launch-guard", "--dispatch", did])
        self.assertEqual(argv[sep + 1:sep + 6], ["claude", "--model", "opus", "--effort", "high"])
        self.assertEqual(argv[sep + 6], "--permission-mode=bypassPermissions")
        ddir = self.home / "runs" / self.run_id / "dispatches" / did
        self.assertEqual((ddir / "spec.md").read_text(encoding="utf-8"), "스펙 본문")
        self.assertEqual(argv[-1], (ddir / "preamble.md").read_text(encoding="utf-8"))
        self.assertIn(str(ddir / "spec.md"), argv[-1])
        self.assertEqual(json.loads((ddir / "receipt.json").read_text())["result"]["address"], term)

    def test_codex_command(self):
        out = self.start_worker(agent="codex", extra=("--model", "gpt-5.5"))
        argv = self.hc_state()["terminals"][out["terminal"]]["argv"]
        sep = argv.index("--")
        self.assertEqual(argv[sep + 1:sep + 9], ["codex", "--no-daemon", "-s", "workspace-write", "-a", "never",
                                                 "--add-dir", str(self.home)])

    def test_placement_none_without_owner_tab(self):
        self.make_owner("t101", None, None)
        out = self.start_worker(owner="t101")
        self.assertEqual(out["placement"], "none")
        self.assertTrue(out["warning"])
        labels = self.hc_state()["terminals"][out["terminal"]]["labels"]
        self.assertEqual(set(labels), {"horch.run", "horch.dispatch"})

    def test_validation(self):
        code, out = self.horch("worker-start", "--agent", "claude", "--title", "t", "--spec", "s", terminal="t555")
        self.assertEqual(code, 5)
        code, out = self.horch("worker-start", "--agent", "claude", "--spec", "s", terminal="t100")
        self.assertEqual(code, 2)
        code, out = self.horch("worker-start", "--agent", "claude", "--title", "t", "--spec", "s",
                               "--cwd", str(self.tmp / "nope"), terminal="t100")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_cwd"))
        spec_file = self.tmp / "spec.md"
        spec_file.write_text("파일 스펙", encoding="utf-8")
        code, out = self.horch("worker-start", "--agent", "claude", "--title", "t", "--spec-file", str(spec_file),
                               "--cwd", str(self.tmp), terminal="t100")
        self.assertEqual(code, 0, out)
        code, out2 = self.horch("worker-start", "--agent", "claude", "--task", out["task"], "--spec", "x", terminal="t100")
        self.assertEqual(code, 2)

    def test_agent_missing(self):
        only = self.tmp / "only-hc"
        only.mkdir()
        os.symlink(FAKES / "hc", only / "hc")
        os.symlink(sys.executable, only / "python3")
        code, out = self.horch("worker-start", "--agent", "claude", "--title", "t", "--spec", "s",
                               "--cwd", str(self.tmp), terminal="t100", env={"PATH": str(only)})
        self.assertEqual((code, out["error"]["code"]), (12, "agent_missing"))
        self.assertEqual(self.dispatch(out["dispatch"])["state"], "launch_failed")

    def test_hc_run_failure(self):
        self.fail_hc("run", "spawn_failed")
        code, out = self.horch("worker-start", "--agent", "claude", "--title", "t", "--spec", "s",
                               "--cwd", str(self.tmp), terminal="t100")
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"))
        self.assertEqual(self.dispatch(out["dispatch"])["state"], "launch_failed")
        receipt = self.home / "runs" / self.run_id / "dispatches" / out["dispatch"] / "receipt.json"
        self.assertEqual(json.loads(receipt.read_text())["error"]["kind"], "spawn_failed")

    def test_retry_rules(self):
        out = self.start_worker()
        task, did = out["task"], out["dispatch"]
        code, res = self.horch("worker-start", "--agent", "claude", "--task", task, terminal="t100")
        self.assertEqual((code, res["error"]["code"]), (3, "task_busy"))
        db = self.db()
        db.execute("UPDATE dispatches SET state='launch_failed' WHERE id=?", (did,))
        db.commit()
        code, res = self.horch("worker-start", "--agent", "claude", "--task", task, terminal="t100")
        self.assertEqual((code, res["error"]["code"]), (3, "retry_required"))
        code, res = self.horch("worker-start", "--agent", "claude", "--task", task, "--retry",
                               "--cwd", str(self.tmp), terminal="t100")
        self.assertEqual(code, 0, res)
        self.assertEqual(self.dispatch(res["dispatch"])["attempt"], 2)
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (res["dispatch"],))
        db.commit()
        code, res3 = self.horch("worker-start", "--agent", "claude", "--task", task, "--cwd", str(self.tmp), terminal="t100")
        self.assertEqual(code, 0, res3)
        db.execute("UPDATE tasks SET status='settled' WHERE id=?", (task,))
        db.execute("UPDATE dispatches SET state='abandoned' WHERE id=?", (res3["dispatch"],))
        db.commit()
        code, res4 = self.horch("worker-start", "--agent", "claude", "--task", task, terminal="t100")
        self.assertEqual((code, res4["error"]["code"]), (3, "task_settled"))

    def test_executor_death_points(self):
        for point in ("after_create", "after_run", "before_record"):
            with self.subTest(point=point):
                code, _ = self.horch("worker-start", "--agent", "claude", "--title", "t", "--spec", "s",
                                     "--cwd", str(self.tmp), terminal="t100", env={"HORCH_TEST_DIE_AT": point})
                self.assertEqual(code, 137)
                did = self.db().execute("SELECT id FROM dispatches WHERE state='launching'").fetchone()["id"]
                store = Store(self.home)
                try:
                    self.assertEqual(workers.reconcile_launching(store, self.run_id), [did])
                finally:
                    store.close()
                self.assertEqual(self.dispatch(did)["state"], "launch_failed")
                late = [t for t in self.hc_state()["terminals"].values() if t["name"] == did]
                self.assertEqual(len(late), 0 if point == "after_create" else 1)
                if late:
                    rc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "launch-guard",
                                         "--dispatch", did, "--", "claude"], capture_output=True, text=True,
                                        env=self._env(late[0]["address"], None), timeout=30).returncode
                    self.assertEqual(rc, 3)

    def test_concurrent_retry_creates_one(self):
        out = self.start_worker()
        db = self.db()
        db.execute("UPDATE dispatches SET state='launch_failed' WHERE id=?", (out["dispatch"],))
        db.commit()
        args = ("worker-start", "--agent", "claude", "--task", out["task"], "--retry", "--cwd", str(self.tmp))
        procs_ = [self.horch_bg(*args, terminal="t100") for _ in range(2)]
        codes = sorted(self.finish(p)[0] for p in procs_)
        self.assertEqual(codes, [0, 3])
        n = db.execute("SELECT COUNT(*) FROM dispatches WHERE task_id=? AND state IN ('launching','active')",
                       (out["task"],)).fetchone()[0]
        self.assertEqual(n, 1)


class WorkerStartInProcessTest(HorchCase):
    """실행자와 가드가 겹치는 순서를 한 프로세스에서 재현한다."""

    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(self.home)
        self.addCleanup(self.store.close)

    def start(self):
        return workers.start(self.store, self.run_id, spec="s", title="t", agent="claude", model=None, effort=None,
                             cwd=str(self.tmp), extra=[], task_id=None, retry=False)

    def launching_id(self):
        return self.store.one("SELECT id FROM dispatches WHERE state='launching'")["id"]

    def guard_claims(self, terminal):
        other = Store(self.home)
        try:
            guard.claim(other, self.launching_id(), terminal)
        finally:
            other.close()

    def test_hc_failure_after_guard_registered_is_success(self):
        def fake_run(*_a, **_k):
            self.guard_claims("t9")
            raise hcio.HcFailure("exit_1", "lost reply")
        with mock.patch.object(workers.hcio, "run_bg", side_effect=fake_run):
            out = self.start()
        self.assertEqual((out["state"], out["terminal"]), ("active", "t9"))

    def test_guard_and_done_before_executor_records(self):
        def fake_run(*_a, **_k):
            did = self.launching_id()
            self.guard_claims("t9")
            self.store.run("UPDATE dispatches SET state='settled', outcome='succeeded' WHERE id=?", (did,))
            return {"address": "t9"}
        with mock.patch.object(workers.hcio, "run_bg", side_effect=fake_run):
            out = self.start()
        self.assertEqual((out["state"], out["terminal"]), ("settled", "t9"))

    def test_abandon_before_executor_records(self):
        def fake_run(*_a, **_k):
            did = self.launching_id()
            self.guard_claims("t9")
            self.store.run("UPDATE dispatches SET state='abandoned' WHERE id=?", (did,))
            return {"address": "t9"}
        with mock.patch.object(workers.hcio, "run_bg", side_effect=fake_run):
            out = self.start()
        self.assertEqual((out["state"], out["terminal"]), ("abandoned", "t9"))

    def test_terminal_mismatch(self):
        def fake_run(*_a, **_k):
            self.guard_claims("t8")
            return {"address": "t9"}
        with mock.patch.object(workers.hcio, "run_bg", side_effect=fake_run):
            with self.assertRaises(HorchError) as cm:
                self.start()
        self.assertEqual(cm.exception.code, "terminal_mismatch")


class ReconcileAndFenceTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.did = self.add_dispatch(self.run_id, terminal=None, state="launching")
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(self.home)
        self.addCleanup(self.store.close)

    def set_launcher(self, pid, started):
        self.store.run("UPDATE dispatches SET launcher_pid=?, launcher_started=? WHERE id=?", (pid, started, self.did))

    def dead_launcher(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        started = procs.start_time(child.pid) or "x"
        child.wait()
        self.set_launcher(child.pid, started)

    def state(self):
        return self.store.one("SELECT state FROM dispatches WHERE id=?", (self.did,))["state"]

    def guard_cli(self):
        env = dict(self.env, HC_TERMINAL_ID="t42")
        return subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "launch-guard", "--dispatch",
                               self.did, "--", "claude"], capture_output=True, text=True, env=env, timeout=30).returncode

    def test_alive_launcher_kept(self):
        self.set_launcher(*procs.me())
        self.assertEqual(workers.reconcile_launching(self.store, self.run_id), [])
        self.assertEqual(self.state(), "launching")

    def test_dead_launcher_then_late_guard_refused(self):
        self.dead_launcher()
        self.assertEqual(workers.reconcile_launching(self.store, self.run_id), [self.did])
        self.assertEqual(self.state(), "launch_failed")
        self.assertEqual(self.guard_cli(), 3)

    def test_guard_first_then_reconcile_noop(self):
        self.dead_launcher()
        self.assertEqual(self.guard_cli(), 0)
        self.assertEqual(workers.reconcile_launching(self.store, self.run_id), [])
        self.assertEqual(self.state(), "active")

    def test_guard_and_reconcile_race_one_wins(self):
        script = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path;"
                  "from horch.store import Store; from horch import workers;"
                  "workers.reconcile_launching(Store(Path(sys.argv[2])), sys.argv[3])")
        for _ in range(5):
            self.store.run("UPDATE dispatches SET state='launching', terminal=NULL WHERE id=?", (self.did,))
            self.dead_launcher()
            g = subprocess.Popen([sys.executable, str(BIN), "--home", str(self.home), "launch-guard", "--dispatch",
                                  self.did, "--", "claude"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=dict(self.env, HC_TERMINAL_ID="t42"))
            r = subprocess.Popen([sys.executable, "-c", script, str(ROOT / "lib"), str(self.home), self.run_id],
                                 env=self.env)
            rc = g.wait(timeout=30)
            self.assertEqual(r.wait(timeout=30), 0)
            self.assertIn((rc, self.state()), ((0, "active"), (3, "launch_failed")))

    def test_old_guard_refused_after_retry(self):
        self.dead_launcher()
        workers.reconcile_launching(self.store, self.run_id)
        with mock.patch.object(workers.hcio, "run_bg", return_value={"address": "t77"}):
            new = workers.start(self.store, self.run_id, spec=None, title=None, agent="claude", model=None,
                                effort=None, cwd=str(self.tmp), extra=[], task_id="task-00000001", retry=True)
        self.assertEqual(new["state"], "active")
        self.assertEqual(self.guard_cli(), 3)
        self.assertEqual(self.store.one("SELECT state FROM dispatches WHERE id=?", (new["dispatch"],))["state"], "active")

    def test_cleanup_refused_terminals(self):
        self.dead_launcher()
        workers.reconcile_launching(self.store, self.run_id)
        labels = {"horch.run": self.run_id, "horch.dispatch": self.did}
        self.add_terminal("t60", name=self.did, state="finished", labels=labels)
        self.add_terminal("t61", name=self.did, state="live", labels=labels)
        self.add_terminal("t62", name=self.did, state="finished")
        self.assertEqual(workers.cleanup_refused(self.store, self.run_id), ["t60"])
        self.assertEqual(set(self.hc_state()["terminals"]) & {"t60", "t61", "t62"}, {"t61", "t62"})


if __name__ == "__main__":
    unittest.main()
