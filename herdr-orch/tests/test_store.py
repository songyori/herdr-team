import os
import sqlite3
import stat
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests.helpers import ROOT, HorchCase
from horch import procs
from horch.errors import HorchError
from horch.store import SCHEMA_VERSION, Store, write_atomic


class StoreTest(HorchCase):
    def open(self) -> Store:
        s = Store(self.home)
        self.addCleanup(s.close)
        return s

    def test_creates_schema_and_private_home(self):
        s = self.open()
        self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"], str(SCHEMA_VERSION))
        tables = {r["name"] for r in s.all("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in ("runs", "bindings", "tasks", "dispatches", "messages", "deliveries", "waiters", "observations"):
            self.assertIn(t, tables)
        self.assertEqual(stat.S_IMODE(os.stat(self.home).st_mode), 0o700)
        self.assertEqual(s.one("PRAGMA journal_mode")[0], "wal")

    def test_migrates_v1_to_v2(self):
        s = self.open()
        # v1 (agent_args 열도, task·attempt 인덱스도 없던 시절) 로 되돌린다
        s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-1','o','t','t')")
        s.run("INSERT INTO tasks(id, run_id, title, spec, created_at) VALUES ('tsk-1','run-1','T','S','t')")
        s.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, state, created_at) "
              "VALUES ('dsp-1','tsk-1','run-1',1,'claude','/x','settled','t')")
        s.run("DROP INDEX dispatch_task_attempt")
        s.run("ALTER TABLE dispatches DROP COLUMN agent_args")
        s.run("UPDATE meta SET value='1' WHERE key='schema_version'")
        s.close()
        s2 = self.open()
        cols = {r["name"] for r in s2.all("PRAGMA table_info(dispatches)")}
        self.assertIn("agent_args", cols)
        self.assertEqual(s2.one("SELECT value FROM meta WHERE key='schema_version'")["value"], "2")
        self.assertEqual(s2.one("SELECT id, agent_args FROM dispatches")["id"], "dsp-1")
        idx = {r["name"] for r in s2.all("PRAGMA index_list(dispatches)")}
        self.assertIn("dispatch_task_attempt", idx)

    def test_refuses_newer_schema(self):
        self.open().run("UPDATE meta SET value='99' WHERE key='schema_version'")
        with self.assertRaises(HorchError) as cm:
            Store(self.home)
        self.assertEqual(cm.exception.code, "schema_too_new")

    def test_reopen_keeps_data(self):
        s = self.open()
        with s.tx():
            s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-00000001','o','x','x')")
        s.close()
        self.assertIsNotNone(self.open().one("SELECT id FROM runs WHERE id='run-00000001'"))

    def test_tx_rolls_back_on_error(self):
        s = self.open()
        with self.assertRaises(RuntimeError):
            with s.tx():
                s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-00000002','o','x','x')")
                raise RuntimeError("boom")
        self.assertIsNone(s.one("SELECT id FROM runs WHERE id='run-00000002'"))

    def test_concurrent_writers(self):
        self.open().close()
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from horch.store import Store;"
            "s = Store(Path(sys.argv[2]));"
            "\nfor i in range(50):\n"
            "    with s.tx():\n"
            "        s.run(\"INSERT INTO runs(id, objective, created_at, updated_at) VALUES (?, 'o', 'x', 'x')\", (f'run-{sys.argv[3]}{i:06x}',))\n"
        )
        procs_ = [subprocess.Popen([sys.executable, "-c", script, str(ROOT / "lib"), str(self.home), f"{n:02x}"])
                  for n in range(4)]
        for p in procs_:
            self.assertEqual(p.wait(timeout=60), 0)
        self.assertEqual(self.open().one("SELECT COUNT(*) AS n FROM runs")["n"], 200)

    def test_concurrent_first_creation(self):
        # 아직 없는 home 을 여러 프로세스가 동시에 처음 만든다
        home = self.tmp / "fresh-home"
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from horch.store import Store;"
            "s = Store(Path(sys.argv[2]));"
            "\nwith s.tx():\n"
            "    s.run(\"INSERT INTO runs(id, objective, created_at, updated_at) VALUES (?, 'o', 'x', 'x')\", (f'run-{sys.argv[3]}',))\n"
        )
        ps = [subprocess.Popen([sys.executable, "-c", script, str(ROOT / "lib"), str(home), f"{n:08x}"])
              for n in range(4)]
        for p in ps:
            self.assertEqual(p.wait(timeout=60), 0)
        s = Store(home)
        self.addCleanup(s.close)
        self.assertEqual(s.one("SELECT COUNT(*) AS n FROM runs")["n"], 4)

    def test_open_needs_no_write_lock_when_schema_is_current(self):
        # 다른 프로세스가 쓰기 잠금을 오래 쥐어도(예: run-use 판정 중) 마이그레이션이 필요 없으면 열고 읽는다
        self.open().close()
        other = sqlite3.connect(self.home / "orch.db", isolation_level=None)
        self.addCleanup(other.close)
        other.execute("BEGIN IMMEDIATE")
        try:
            t0 = time.monotonic()
            s = Store(self.home)
            try:
                self.assertEqual(s.one("SELECT value FROM meta WHERE key='schema_version'")["value"],
                                 str(SCHEMA_VERSION))
            finally:
                s.close()
            self.assertLess(time.monotonic() - t0, 1.0)
        finally:
            other.execute("ROLLBACK")

    def test_migrate_failure_closes_connection(self):
        made = []
        real_connect = sqlite3.connect

        def connect(*a, **k):
            conn = mock.Mock(wraps=real_connect(*a, **k))
            made.append(conn)
            return conn

        with mock.patch.object(Store, "_migrate", side_effect=RuntimeError("boom")), \
                mock.patch("sqlite3.connect", side_effect=connect):
            with self.assertRaises(RuntimeError):
                Store(self.home)
        made[0].close.assert_called_once()

    def test_rollback_failure_does_not_mask_original(self):
        s = self.open()
        real = s.conn

        class Conn:
            def execute(self, sql, *a):
                if sql == "ROLLBACK":
                    raise sqlite3.OperationalError("rollback failed")
                return real.execute(sql, *a)

        s.conn = Conn()
        try:
            with self.assertRaises(RuntimeError):
                with s.tx():
                    raise RuntimeError("boom")
        finally:
            s.conn = real
            real.execute("ROLLBACK")

    def _run_task(self, s):
        with s.tx():
            s.run("INSERT INTO runs(id, objective, created_at, updated_at) VALUES ('run-0000000a','o','x','x')")
            s.run("INSERT INTO tasks(id, run_id, title, spec, status, created_at) VALUES ('task-0000000a','run-0000000a','t','s','open','x')")

    def _dispatch(self, s, did, state):
        with s.tx():
            s.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, cwd, state, created_at) "
                  "VALUES (?, 'task-0000000a', 'run-0000000a', 1, 'claude', '/', ?, 'x')", (did, state))

    def test_one_binding_per_run(self):
        s = self.open()
        self._run_task(s)
        with s.tx():
            s.run("INSERT INTO bindings(terminal, run_id) VALUES ('t1','run-0000000a')")
        with self.assertRaises(sqlite3.IntegrityError):
            with s.tx():
                s.run("INSERT INTO bindings(terminal, run_id) VALUES ('t2','run-0000000a')")

    def test_one_running_dispatch_per_task(self):
        s = self.open()
        self._run_task(s)
        self._dispatch(s, "dsp-00000001", "launch_failed")
        self._dispatch(s, "dsp-00000002", "launching")
        with self.assertRaises(sqlite3.IntegrityError):
            self._dispatch(s, "dsp-00000003", "active")

    def test_question_key_and_single_reply(self):
        s = self.open()
        self._run_task(s)
        ins = ("INSERT INTO messages(run_id, mailbox, sender, type, body, dispatch_id, ask_key, reply_to, created_at) "
               "VALUES ('run-0000000a', ?, 'x', ?, 'b', 'dsp-00000001', ?, ?, 'x')")
        with s.tx():
            s.run(ins, ("run:run-0000000a", "question", "k1", None))
        with self.assertRaises(sqlite3.IntegrityError):
            with s.tx():
                s.run(ins, ("run:run-0000000a", "question", "k1", None))
        with s.tx():
            s.run(ins, ("dispatch:dsp-00000001", "reply", None, 1))
        with self.assertRaises(sqlite3.IntegrityError):
            with s.tx():
                s.run(ins, ("dispatch:dsp-00000001", "reply", None, 1))

    def test_write_atomic(self):
        path = self.tmp / "a" / "b.txt"
        write_atomic(path, "안녕")
        self.assertEqual(path.read_text(encoding="utf-8"), "안녕")
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["b.txt"])


class ProcsTest(unittest.TestCase):
    def test_me_is_alive(self):
        pid, started = procs.me()
        self.assertTrue(started)
        self.assertTrue(procs.alive(pid, started))

    def test_wrong_start_time_is_dead(self):
        pid, _ = procs.me()
        self.assertFalse(procs.alive(pid, "Thu Jan  1 00:00:00 1970"))

    def test_exited_process_is_dead(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        started = procs.start_time(child.pid)
        child.wait()
        self.assertFalse(procs.alive(child.pid, started))

    def test_start_time_independent_of_tz(self):
        pid, _ = procs.me()
        with mock.patch.dict(os.environ, {"TZ": "UTC"}):
            recorded = procs.start_time(pid)
        with mock.patch.dict(os.environ, {"TZ": "Asia/Seoul"}):
            self.assertTrue(procs.alive(pid, recorded))

    def test_zombie_is_dead(self):
        child = subprocess.Popen(["sleep", "30"])
        try:
            recorded = procs.start_time(child.pid)
            child.kill()
            deadline = time.time() + 5
            while time.time() < deadline:
                out = subprocess.run(["ps", "-o", "stat=", "-p", str(child.pid)],
                                     capture_output=True, text=True).stdout.strip()
                if out.startswith("Z"):
                    break
                time.sleep(0.02)
            self.assertTrue(out.startswith("Z"))
            self.assertFalse(procs.alive(child.pid, recorded))
        finally:
            child.wait()

    def test_ps_failure_means_unknown_alive(self):
        pid, started = procs.me()
        with mock.patch("subprocess.run", side_effect=OSError("no ps")):
            self.assertTrue(procs.alive(pid, started))

    def test_empty_started_live_pid_is_alive(self):
        pid, _ = procs.me()
        self.assertTrue(procs.alive(pid, ""))
        self.assertTrue(procs.alive(pid, None))

    def test_missing_values_are_dead(self):
        self.assertFalse(procs.alive(None, None))


if __name__ == "__main__":
    unittest.main()
