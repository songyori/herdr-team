import os
import unittest
from unittest import mock

from tests.helpers import HorchCase
from horch import hcio, liveness
from horch.errors import HorchError


class HcioTest(HorchCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_and_not_found(self):
        self.add_terminal("t5", argv=["claude"], status="idle")
        self.assertEqual(hcio.get("t5")["argv"], ["claude"])
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.get("t404")
        self.assertEqual(cm.exception.kind, "not_found")

    def test_ls_all_includes_finished(self):
        self.add_terminal("t1")
        self.add_terminal("t2", state="finished")
        self.assertEqual({t["address"] for t in hcio.ls_all()}, {"t1", "t2"})
        self.assertIn(["ls", "--all", "--json"], self.hc_calls())

    def test_run_bg_flags_labels_and_argv(self):
        res = hcio.run_bg("dsp-00000001", "/w", {"a": "b", "c": "d=e"}, ["prog", "--x", "y"])
        self.assertEqual(res["address"], "t1")
        self.assertEqual(self.hc_calls()[-1], [
            "run", "--bg", "--no-parent", "--no-notify", "--name", "dsp-00000001", "--cwd", "/w",
            "--label", "a=b", "--label", "c=d=e", "--json", "--", "prog", "--x", "y"])
        t = self.hc_state()["terminals"]["t1"]
        self.assertEqual(t["labels"], {"a": "b", "c": "d=e"})
        self.assertEqual(t["argv"], ["prog", "--x", "y"])

    def test_run_failure_kind(self):
        self.fail_hc("run", "spawn_failed", 1)
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.run_bg("dsp-00000001", "/w", {}, ["prog"])
        self.assertEqual(cm.exception.kind, "spawn_failed")

    def test_send_if_idle(self):
        self.add_terminal("t3", status="working")
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.send("t3", "hi", if_status="idle")
        self.assertEqual(cm.exception.kind, "status_mismatch")
        self.update_terminal("t3", status="idle")
        hcio.send("t3", "hi", if_status="idle")
        self.assertEqual(self.hc_sent(), [{"terminal": "t3", "text": "hi", "if": "idle"}])

    def test_kill_rm(self):
        self.add_terminal("t4")
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.rm("t4")
        self.assertEqual(cm.exception.kind, "live")
        hcio.kill("t4")
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.kill("t4")
        self.assertEqual(cm.exception.kind, "finished")
        hcio.rm("t4")
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.rm("t4")
        self.assertEqual(cm.exception.kind, "not_found")

    def test_read(self):
        self.add_terminal("t6")
        st = self.hc_state()
        st["screens"]["t6"] = "hello screen"
        self.set_hc_state(st)
        self.assertIn("hello screen", hcio.read("t6", 10))

    def test_missing_hc(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            with self.assertRaises(HorchError) as cm:
                hcio.get("t1")
        self.assertEqual(cm.exception.code, "hc_missing")
        self.assertEqual(cm.exception.exit_code, 12)

    def test_probe(self):
        self.add_terminal("t7", argv=["a"])
        self.assertEqual(liveness.probe("t7", ["a"])[0], "live")
        self.assertEqual(liveness.probe("t7", ["b"])[0], "lost")
        self.assertEqual(liveness.probe("t404", ["a"]), ("unverifiable", None))
        self.assertEqual(liveness.probe(None, None), ("unverifiable", None))


class VerdictTest(unittest.TestCase):
    def test_table(self):
        v = liveness.verdict
        self.assertEqual(v(None, None), "unverifiable")
        self.assertEqual(v({"state": "finished"}, ["a"]), "exited")
        self.assertEqual(v({"state": "live", "reason": "stopped_by_restart", "argv": ["a"]}, ["a"]), "lost")
        self.assertEqual(v({"state": "live", "argv": ["/bin/zsh", "-l"]}, ["a"]), "lost")
        self.assertEqual(v({"state": "live", "argv": ["a"]}, ["a"]), "live")
        self.assertEqual(v({"state": "live", "argv": ["x"]}, None), "live")
        self.assertEqual(v({"state": "weird"}, None), "unverifiable")

    def test_status_word(self):
        sw = liveness.status_word
        self.assertEqual(sw({"status": {"state": "blocked"}}), "blocked")
        self.assertEqual(sw({"status": "idle"}), "idle")
        self.assertIsNone(sw({"status": None}))
        self.assertIsNone(sw(None))

    def test_loads_argv(self):
        self.assertEqual(liveness.loads_argv('["a", "b"]'), ["a", "b"])
        self.assertIsNone(liveness.loads_argv(None))


if __name__ == "__main__":
    unittest.main()
