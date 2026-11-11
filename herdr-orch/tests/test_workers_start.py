import json
import os
import sqlite3
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import BIN, FAKES, ROOT, HorchCase
from horch import guard, hcio, procs, workers
from horch.errors import MISSING, HorchError
from horch.store import Store


def _reap(proc: subprocess.Popen) -> None:
    """타임아웃 등으로 테스트가 중단돼도 자식 프로세스를 남기지 않는다."""
    if proc.poll() is None:
        proc.kill()
    proc.wait()
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()


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
        trust = "projects=" + "{" + json.dumps(os.path.realpath(self.tmp)) + '={trust_level="trusted"}}'
        self.assertIn(trust, argv)  # --cwd 의 실경로를 그 실행에만 신뢰한다(6단계 실환경)
        self.assertIn("check_for_update_on_startup=false", argv)

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

    def test_unknown_task(self):
        code, out = self.horch("worker-start", "--agent", "claude", "--task", "task-zzzzzzzz", terminal="t100")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_task"))
        self.assertEqual(self.db().execute("SELECT COUNT(*) FROM dispatches").fetchone()[0], 0)

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
        for p in procs_:
            self.addCleanup(_reap, p)
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
        patcher = mock.patch.dict(os.environ, {**self.env, "HC_TERMINAL_ID": "t100"}, clear=True)
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

    # --- 생성 뒤 오류: task·dispatch 를 항상 돌려준다 ---
    def test_spec_write_oserror_marks_failed_with_ids(self):
        real = workers.write_atomic

        def boom(path, text, *a, **k):
            if str(path).endswith("spec.md"):
                raise OSError("disk full")
            return real(path, text, *a, **k)
        with mock.patch.object(workers, "write_atomic", side_effect=boom):
            with self.assertRaises(HorchError) as cm:
                self.start()
        exc = cm.exception
        self.assertEqual(exc.exit_code, 1)
        self.assertEqual(exc.code, "launch_failed")
        row = self.store.one("SELECT id, task_id, state FROM dispatches")
        self.assertEqual((exc.data["task"], exc.data["dispatch"]), (row["task_id"], row["id"]))
        self.assertEqual(row["state"], "launch_failed")

    def test_receipt_write_oserror_after_run_is_warning(self):
        real = workers.write_atomic

        def boom(path, text, *a, **k):
            if str(path).endswith("receipt.json"):
                raise OSError("disk full")
            return real(path, text, *a, **k)
        with mock.patch.object(workers.hcio, "run_bg", return_value={"address": "t9"}), \
                mock.patch.object(workers, "write_atomic", side_effect=boom):
            out = self.start()
        self.assertEqual((out["state"], out["terminal"]), ("active", "t9"))
        self.assertTrue(out["task"] and out["dispatch"])
        self.assertTrue(any("receipt" in w for w in out["warnings"]), out)
        self.assertEqual(self.store.one("SELECT state FROM dispatches WHERE id=?", (out["dispatch"],))["state"], "active")

    def test_record_failure_after_run_keeps_launching_and_returns_ids(self):
        with mock.patch.object(workers.hcio, "run_bg", return_value={"address": "t9"}), \
                mock.patch.object(workers, "_record_active", side_effect=sqlite3.OperationalError("locked")):
            with self.assertRaises(HorchError) as cm:
                self.start()
        data = cm.exception.data
        self.assertEqual(data["terminal"], "t9")
        row = self.store.one("SELECT id, state FROM dispatches")
        self.assertEqual((data["dispatch"], row["state"]), (row["id"], "launching"))

    def test_hc_missing_is_launch_failed_exit_12(self):
        err = HorchError("hc_missing", "hc 실행 파일을 찾지 못했다", MISSING)
        with mock.patch.object(workers.hcio, "run_bg", side_effect=err):
            with self.assertRaises(HorchError) as cm:
                self.start()
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_failed", 12))
        row = self.store.one("SELECT id, state FROM dispatches")
        self.assertEqual((cm.exception.data["dispatch"], row["state"]), (row["id"], "launch_failed"))

    def test_launch_failed_at_record_time(self):
        def fake_run(*_a, **_k):
            self.store.run("UPDATE dispatches SET state='launch_failed' WHERE id=?", (self.launching_id(),))
            return {"address": "t9"}
        with mock.patch.object(workers.hcio, "run_bg", side_effect=fake_run):
            with self.assertRaises(HorchError) as cm:
                self.start()
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_failed", 1))
        self.assertIn("dispatch", cm.exception.data)

    def test_binding_moved_before_create_tx_is_not_owner(self):
        # worker-start 의 첫 소유 확인 뒤 run-use 로 바인딩이 옮겨지면 옛 Run 에 아무것도 만들지 않는다
        other = self.make_owner("t200")
        real_tx = self.store.tx
        state = {"moved": False}

        def moving_tx():
            if not state["moved"]:
                state["moved"] = True
                self.store.run("DELETE FROM bindings WHERE terminal='t200'")  # run_id 는 UNIQUE
                self.store.run("UPDATE bindings SET run_id=? WHERE terminal='t100'", (other,))
            return real_tx()
        with mock.patch.object(self.store, "tx", side_effect=moving_tx), \
                mock.patch.object(workers.hcio, "run_bg") as run_bg:
            with self.assertRaises(HorchError) as cm:
                self.start()
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("not_owner", 5))
        run_bg.assert_not_called()
        self.assertEqual(self.store.one("SELECT COUNT(*) AS n FROM tasks WHERE run_id=?", (self.run_id,))["n"], 0)
        self.assertEqual(self.store.one("SELECT COUNT(*) AS n FROM dispatches WHERE run_id=?", (self.run_id,))["n"], 0)

    def test_other_integrity_error_not_task_busy(self):
        self.add_dispatch(self.run_id)  # dsp-00000001 이 이미 있다
        real = workers.new_id
        with mock.patch.object(workers, "new_id", side_effect=lambda p: "dsp-00000001" if p == "dsp" else real(p)):
            with self.assertRaises(sqlite3.IntegrityError):
                self.start()


class ReconcileAndFenceTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.did = self.add_dispatch(self.run_id, terminal=None, state="launching")
        patcher = mock.patch.dict(os.environ, {**self.env, "HC_TERMINAL_ID": "t100"}, clear=True)
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
            self.addCleanup(_reap, g)
            r = subprocess.Popen([sys.executable, "-c", script, str(ROOT / "lib"), str(self.home), self.run_id],
                                 env=self.env)
            self.addCleanup(_reap, r)
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

    def test_cleanup_requires_label_for_this_dispatch(self):
        self.dead_launcher()
        workers.reconcile_launching(self.store, self.run_id)
        other = self.add_dispatch(self.run_id, did="dsp-00000002", terminal=None, state="launch_failed")
        # 이름은 self.did 인데 horch.dispatch 라벨은 다른(실패한) Dispatch 를 가리킨다 -> 지우지 않는다
        self.add_terminal("t63", name=self.did, state="finished",
                          labels={"horch.run": self.run_id, "horch.dispatch": other})
        self.assertEqual(workers.cleanup_refused(self.store, self.run_id), [])
        self.assertIn("t63", self.hc_state()["terminals"])


if __name__ == "__main__":
    unittest.main()
