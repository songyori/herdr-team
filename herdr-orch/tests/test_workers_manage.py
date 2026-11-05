import json
import os
import subprocess
import unittest
from unittest import mock

from tests.helpers import HorchCase
from horch import liveness
from horch.store import Store


class ObserveTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id, status="working")
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(self.home)
        self.addCleanup(self.store.close)

    def kinds(self):
        rows = self.store.all("SELECT body FROM messages WHERE type='observed' ORDER BY id")
        return [(json.loads(r["body"])["kind"], json.loads(r["body"])["key"]) for r in rows]

    def test_blocked_and_error_once_per_turn(self):
        self.update_terminal("t9", status="blocked", turn=3)
        liveness.observe(self.store, self.run_id)
        liveness.observe(self.store, self.run_id)
        self.update_terminal("t9", status="error", turn=4)
        liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [("blocked", "3"), ("error", "4")])

    def test_exited_and_lost(self):
        self.update_terminal("t9", reason="stopped_by_restart")
        liveness.observe(self.store, self.run_id)
        self.update_terminal("t9", state="finished", reason=None)
        liveness.observe(self.store, self.run_id)
        liveness.observe(self.store, self.run_id)
        self.assertEqual(self.kinds(), [("lost", "lost"), ("exited", "exited")])


class ManageTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id, status="working")

    def o(self, *args):
        return self.horch(*args, terminal="t100")

    def state(self, did=None):
        return self.db().execute("SELECT state FROM dispatches WHERE id=?", (did or self.did,)).fetchone()["state"]

    def set_state(self, state, did=None):
        db = self.db()
        db.execute("UPDATE dispatches SET state=? WHERE id=?", (state, did or self.did))
        db.commit()

    def test_owner_wait_reports_exit(self):
        self.update_terminal("t9", state="finished")
        code, out = self.o("check", "--wait", "--timeout-ms", "3000")
        self.assertEqual((code, out["reason"]), (0, "message"))
        msg = out["messages"][0]
        self.assertEqual((msg["type"], json.loads(msg["body"])["kind"]), ("observed", "exited"))

    def test_owner_wait_reconciles_launching(self):
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal=None, state="launching")
        self.o("check", "--wait", "--timeout-ms", "300")
        self.assertEqual(self.state(did2), "launch_failed")

    def test_list_attention_and_filter(self):
        self.update_terminal("t9", state="finished")
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal="t10", state="settled")
        did3 = self.add_dispatch(self.run_id, did="dsp-00000003", terminal=None, state="launch_failed")
        code, out = self.o("worker-list")
        self.assertEqual(code, 0, out)
        by = {w["id"]: w for w in out["workers"]}
        self.assertEqual(by[self.did]["attention"], "exited_without_done")
        self.assertIn("worker-abandon", by[self.did]["next"])
        self.assertEqual(by[did2]["attention"], "settled")
        self.assertIn("worker-release", by[did2]["next"])
        self.assertEqual(by[did3]["attention"], "launch_failed")
        self.assertIn("--retry", by[did3]["next"])
        retry = subprocess.run(by[did3]["next"], capture_output=True, text=True, env=self._env("t100", None), timeout=30)
        self.assertEqual(retry.returncode, 0, retry.stdout)
        _, only = self.o("worker-list", "--state", "settled")
        self.assertEqual([w["id"] for w in only["workers"]], [did2])

    def test_list_no_status_for_live_worker_without_report(self):
        self.update_terminal("t9", status=None)
        _, out = self.o("worker-list")
        row = {w["id"]: w for w in out["workers"]}[self.did]
        self.assertEqual((row["verdict"], row["status"], row["attention"]), ("live", None, "no_status"))
        self.assertEqual(row["next"][-4:], ["--dispatch", self.did, "--lines", "40"])
        self.update_terminal("t9", status="working")
        _, out = self.o("worker-list")
        self.assertIsNone({w["id"]: w for w in out["workers"]}[self.did]["attention"])

    def test_show_with_screen(self):
        st = self.hc_state()
        st["screens"]["t9"] = "화면 내용"
        self.set_hc_state(st)
        code, out = self.o("worker-show", "--dispatch", self.did, "--lines", "20")
        self.assertEqual(code, 0, out)
        self.assertIn("화면 내용", out["worker"]["screen"])
        self.assertEqual(out["worker"]["hc"]["state"], "live")
        _, none = self.o("worker-show", "--dispatch", self.did, "--lines", "0")
        self.assertIsNone(none["worker"]["screen"])

    def test_release_kills_removes_and_is_idempotent(self):
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual(code, 3)
        self.set_state("settled")
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["dispatch"]["state"]), (0, "released"))
        self.assertNotIn("t9", self.hc_state()["terminals"])
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual(code, 0)

    def test_release_when_terminal_gone(self):
        self.set_state("abandoned")
        st = self.hc_state()
        del st["terminals"]["t9"]
        self.set_hc_state(st)
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["dispatch"]["state"]), (0, "released"))

    def test_release_hc_failure_keeps_state(self):
        self.set_state("settled")
        self.fail_hc("get", "timeout")
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"))
        self.assertEqual(self.state(), "settled")

    def test_retain_then_release(self):
        self.set_state("settled")
        code, out = self.o("worker-retain", "--dispatch", self.did)
        self.assertEqual((code, out["dispatch"]["state"]), (0, "retained"))
        code, out = self.o("worker-release", "--dispatch", self.did)
        self.assertEqual(out["dispatch"]["state"], "released")

    def test_abandon_rules(self):
        code, out = self.o("worker-abandon", "--dispatch", self.did)
        self.assertEqual((code, out["error"]["code"]), (3, "worker_alive"))
        code, out = self.o("worker-abandon", "--dispatch", self.did, "--kill")
        self.assertEqual((code, out["dispatch"]["state"], out["verdict"]), (0, "abandoned", "live"))
        self.assertEqual(self.hc_state()["terminals"]["t9"]["state"], "finished")
        did2 = self.add_dispatch(self.run_id, did="dsp-00000002", terminal="t10")
        st = self.hc_state()
        del st["terminals"]["t10"]
        self.set_hc_state(st)
        code, out = self.o("worker-abandon", "--dispatch", did2)
        self.assertEqual((code, out["error"]["code"]), (1, "unverifiable"))

    def test_abandon_exited_without_kill(self):
        self.update_terminal("t9", state="finished")
        code, out = self.o("worker-abandon", "--dispatch", self.did)
        self.assertEqual((code, out["verdict"]), (0, "exited"))

    def test_not_owner(self):
        code, out = self.horch("worker-list", terminal="t9")
        self.assertEqual(code, 5)


if __name__ == "__main__":
    unittest.main()
