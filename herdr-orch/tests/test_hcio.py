import json
import os
import subprocess
import sys
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
        self.assertEqual(self.hc_sent(), [{"terminal": "t3", "text": "hi", "if": "idle", "tagged": False}])

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

    def test_non_object_json_is_bad_output(self):
        proc = mock.Mock(returncode=0, stdout="[1]", stderr="")
        with mock.patch.object(hcio.subprocess, "run", return_value=proc):
            with self.assertRaises(hcio.HcFailure) as cm:
                hcio.get("t1")
        self.assertEqual(cm.exception.kind, "bad_output")

    def test_exec_oserror_is_exec_failed(self):
        with mock.patch.object(hcio.subprocess, "run", side_effect=PermissionError("denied")):
            with self.assertRaises(hcio.HcFailure) as cm:
                hcio.get("t1")
        self.assertEqual(cm.exception.kind, "exec_failed")

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
        self.assertEqual(v({"state": "live"}, ["a"]), "unverifiable")
        self.assertEqual(v({"state": "live", "argv": None}, ["a"]), "unverifiable")
        self.assertEqual(v({"state": "live"}, None), "live")

    def test_status_word(self):
        sw = liveness.status_word
        self.assertEqual(sw({"status": {"state": "blocked"}}), "blocked")
        self.assertEqual(sw({"status": "idle"}), "idle")
        self.assertIsNone(sw({"status": None}))
        self.assertIsNone(sw(None))

    def test_loads_argv(self):
        self.assertEqual(liveness.loads_argv('["a", "b"]'), ["a", "b"])
        self.assertIsNone(liveness.loads_argv(None))


class HcioPersistTest(HorchCase):
    """0.2.0 hcio: 감싸지 않은 send 와 결과, label(herdr-orch 설계 13.7)."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, {**self.env, "HC_TERMINAL_ID": "t9"}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_send_untagged_and_result(self):
        self.add_terminal("t3", status="done", turn=4)
        res = hcio.send("t3", "hi")
        self.assertEqual((res["sent"], res["started"], res["status"], res["turn"]), (True, True, "done", 4))
        hcio.send("t3", "plain", untagged=True)
        self.assertEqual([(s["text"], s["tagged"]) for s in self.hc_sent()], [("hi", True), ("plain", False)])
        self.assertEqual(os.environ["HC_TERMINAL_ID"], "t9")  # 호출자 환경은 그대로다

    def test_send_modes(self):
        self.add_terminal("t3", status="idle", turn=2)
        with self._hc_locked() as st:
            st["on_send"] = {"t3": "working"}
        res = hcio.send("t3", "go", if_status="idle")
        self.assertEqual(res["status"], "working")
        with self._hc_locked() as st:
            st["on_send"] = {"t3": "mismatch"}
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.send("t3", "go")
        self.assertEqual(cm.exception.kind, "status_mismatch")

    def test_label_sets_and_removes(self):
        self.add_terminal("t5", labels={"a": "1", "b": "2"})
        hcio.label("t5", {"b": "3", "a": ""})
        self.assertEqual(self.hc_state()["terminals"]["t5"]["labels"], {"b": "3"})
        call = self.hc_calls()[-1]
        self.assertEqual(call[:2], ["label", "t5"])
        self.assertIn("b=3", call)
        self.assertIn("a=", call)
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.label("t404", {"x": "1"})
        self.assertEqual(cm.exception.kind, "not_found")


class HcioKeysEventsTest(HorchCase):
    """0.2.0 hcio: keys·events·kill 시간 제한(herdr-orch 설계 13.7)과 herdr-team 이 쓰는 가짜 hc connect."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_keys_clear_moves_turn_without_send(self):
        self.add_terminal("t3", status="done", turn=2)
        hcio.keys("t3", ["/", "c", "l", "e", "a", "r", "enter"])
        st = self.hc_state()
        self.assertEqual(st["keys"], [{"terminal": "t3", "keys": ["/", "c", "l", "e", "a", "r", "enter"]}])
        self.assertEqual((st["terminals"]["t3"]["turn"], st["terminals"]["t3"]["status"]["state"]), (3, "idle"))
        self.assertEqual(st.get("sent", []), [])
        call = self.hc_calls()[-1]
        self.assertEqual(call[0], "keys")
        self.assertIn("--json", call)
        self.assertEqual(hcio.get("t3")["title"], "")

    def test_keys_other_and_no_turn_scenario(self):
        self.add_terminal("t3", status="done", turn=2)
        hcio.keys("t3", ["down"])
        with self._hc_locked() as st:
            st["on_clear"] = {"t3": "none"}
        hcio.keys("t3", ["/", "c", "l", "e", "a", "r", "enter"])
        self.assertEqual(self.hc_state()["terminals"]["t3"]["turn"], 2)
        with self.assertRaises(hcio.HcFailure) as cm:
            hcio.keys("t404", ["enter"])
        self.assertEqual(cm.exception.kind, "not_found")

    def test_events_stream_and_close(self):
        # 가짜 hc events 는 실제 꼴(스냅숏 한 줄 + JSON-RPC 알림)을 내고, EventStream 이 평평한 사건으로 바꾼다
        self.add_terminal("t3", status="done", turn=2)
        stream = hcio.events("t3")
        try:
            first = stream.read(5)
            self.assertEqual((first["type"], first["terminal"], liveness.status_word(first), first["turn"]),
                             ("snapshot", "t3", "done", 2))
            self.update_terminal("t3", status="idle", turn=3)
            got = [stream.read(5), stream.read(5)]
            self.assertEqual([(e["type"], e["terminal"], liveness.status_word(e), e.get("turn")) for e in got],
                             [("status", "t3", "idle", None), ("turn", "t3", "idle", 3)])
            self.assertIsNone(stream.read(0.2))  # 바뀐 것이 없으면 마감까지 None
        finally:
            stream.close()
        self.assertTrue(stream.closed)
        self.assertIn(["events", "--json", "--terminal", "t3"], self.hc_calls())

    def test_events_failure_ends_stream(self):
        self.add_terminal("t3", status="done", turn=2)
        self.fail_hc("events", "unavailable")
        stream = hcio.events("t3")
        try:
            self.assertIsNone(stream.read(2))
            self.assertTrue(stream.closed)
        finally:
            stream.close()

    def test_kill_passes_timeout(self):
        proc = mock.Mock(returncode=0, stdout='{"killed": true}', stderr="")
        with mock.patch.object(hcio.subprocess, "run", return_value=proc) as run:
            hcio.kill("t4", timeout=7)
        self.assertEqual(run.call_args.kwargs["timeout"], 7)

    def test_fake_connect_doc_get(self):
        # herdr-team(설계 5.9.2 배치 확인)이 쓰는 가짜 hc connect 의 계약: doc.get herdr-app 은 탭마다 root row 의 터미널 순서
        self.add_terminal("t1", labels={"herdr.space": "spA", "herdr.tab": "tbA"})
        self.add_terminal("t2", labels={"herdr.space": "spA", "herdr.tab": "tbA"})
        self.add_terminal("t3")
        with self._hc_locked() as st:
            st["layout"] = {"tbA": ["t2", "t1"]}
        req = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "doc.get", "params": {"name": "herdr-app"}})
        proc = subprocess.run(["hc", "connect"], input=req + "\n", capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        res = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(res["id"], 7)
        # 실제 꼴: result 는 {"value": 문서, "version"}, 자식은 {"type": "block", "id": <pane>, "content": {"terminal"}}
        space = res["result"]["value"]["spaces"][0]
        tab = space["tabs"][0]
        self.assertEqual((space["id"], tab["id"], tab["root"]["type"]), ("spA", "tbA", "row"))
        self.assertIn("version", res["result"])
        self.assertEqual([c["content"]["terminal"] for c in tab["root"]["children"]], ["t2", "t1"])
        self.assertEqual((tab["root"]["children"][0]["type"], tab["root"]["children"][0]["id"]), ("block", "pt2"))

    def test_event_lines_real_shape(self):
        """실제 hc events --json 줄(2026-11-10 확인한 꼴)을 평평한 사건으로 바꾸고 나머지는 건너뛴다."""
        def note(kind, data, term="t12w"):
            return {"jsonrpc": "2.0", "method": "event", "params": {"type": kind, "terminal": term, "seq": 5, "data": data}}
        lines = [
            {"channel": None, "seq": 1, "terminals": [
                {"address": "t9", "status": {"app": "codex", "state": "working"}, "turn": 7, "title": "x"},
                {"address": "t12w", "status": {"app": "codex", "state": "done"}, "turn": 1, "title": "⠙ codexproj"}]},
            note("heartbeat", {}),
            note("status", {"records": {}, "reported": True, "status": {"app": "codex", "state": "idle"}}),
            "not json",
            [1, 2],
            note("labels", {"labels": {"a": "b"}}),
            note("turn", {"state": "done", "turn": 2}),
            note("title", {"title": "test-a1 | proj"}),
            {"jsonrpc": "2.0", "method": "missed", "params": {"terminal": "t12w"}},
        ]
        text = "\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines)  # 마지막 줄은 줄바꿈 없이 끝난다
        proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", text],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        stream = hcio.EventStream(proc, "t12w")
        try:
            got = []
            while not stream.closed:
                event = stream.read(5)
                if event is not None:
                    got.append(event)
        finally:
            stream.close()
        self.assertEqual([(e["type"], e["terminal"], liveness.status_word(e), e.get("turn"), e.get("title")) for e in got],
                         [("snapshot", "t12w", "done", 1, "⠙ codexproj"), ("status", "t12w", "idle", None, None),
                          ("turn", "t12w", "done", 2, None), ("title", "t12w", None, None, "test-a1 | proj")])


if __name__ == "__main__":
    unittest.main()
