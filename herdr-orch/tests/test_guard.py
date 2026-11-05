import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from tests.helpers import BIN, HorchCase
from horch import agents, guard, preamble
from horch.errors import HorchError


class AgentsTest(unittest.TestCase):
    def test_claude(self):
        argv = agents.build("claude", model="opus", effort="high", extra=["--x"], preamble="P", home=Path("/h"))
        self.assertEqual(argv, ["claude", "--model", "opus", "--effort", "high", "--x", "--", "P"])
        self.assertEqual(agents.build("claude", model=None, effort=None, extra=[], preamble="P", home=Path("/h")),
                         ["claude", "--", "P"])

    def test_variadic_extra_cannot_swallow_preamble(self):
        argv = agents.build("claude", model=None, effort=None, extra=["--add-dir", "/x"], preamble="P",
                            home=Path("/h"))
        self.assertEqual(argv[-4:], ["--add-dir", "/x", "--", "P"])

    def test_codex(self):
        argv = agents.build("codex", model="gpt-5.5", effort="high", extra=[], preamble="P", home=Path("/h"))
        self.assertEqual(argv, ["codex", "--no-daemon", "-s", "workspace-write", "-a", "never", "--add-dir", "/h",
                                "-m", "gpt-5.5", "-c", "model_reasoning_effort=high", "--", "P"])

    def _codex(self, extra):
        return agents.build("codex", model=None, effort=None, extra=extra, preamble="P", home=Path("/h"))

    def test_codex_caller_sandbox_omits_default_sandbox(self):
        for opt in (["-s", "read-only"], ["--sandbox", "read-only"], ["--sandbox=read-only"], ["--full-auto"]):
            with self.subTest(opt=opt):
                self.assertNotIn("workspace-write", self._codex(opt))

    def test_codex_exact_argv_per_conflict(self):
        base = ["codex", "--no-daemon"]
        tail = ["--add-dir", "/h"]
        self.assertEqual(self._codex(["-s", "read-only"]),
                         base + ["-a", "never"] + tail + ["-s", "read-only", "--", "P"])
        self.assertEqual(self._codex(["--sandbox=read-only"]),
                         base + ["-a", "never"] + tail + ["--sandbox=read-only", "--", "P"])
        self.assertEqual(self._codex(["-a", "on-request"]),
                         base + ["-s", "workspace-write"] + tail + ["-a", "on-request", "--", "P"])
        self.assertEqual(self._codex(["--ask-for-approval=on-request"]),
                         base + ["-s", "workspace-write"] + tail + ["--ask-for-approval=on-request", "--", "P"])
        for flag in ("--dangerously-bypass-approvals-and-sandbox", "--yolo", "--full-auto"):
            self.assertEqual(self._codex([flag]), base + tail + [flag, "--", "P"])
        self.assertEqual(self._codex(["-s", "read-only", "-a", "never"]),
                         base + tail + ["-s", "read-only", "-a", "never", "--", "P"])
        self.assertEqual(self._codex(["--x"]),
                         base + ["-s", "workspace-write", "-a", "never"] + tail + ["--x", "--", "P"])

    def test_codex_attached_short_forms_and_approve_for_me(self):
        base = ["codex", "--no-daemon"]
        tail = ["--add-dir", "/h"]
        cases = [
            (["-sread-only"], ["-a", "never"]),
            (["-s=read-only"], ["-a", "never"]),
            (["-anever"], ["-s", "workspace-write"]),
            (["-a=on-request"], ["-s", "workspace-write"]),
            (["--approve-for-me"], []),
        ]
        for extra, defaults in cases:
            with self.subTest(extra=extra):
                self.assertEqual(self._codex(extra), base + defaults + tail + extra + ["--", "P"])

    def test_codex_non_conflicting_dash_s_a_prefixes_keep_defaults(self):
        for extra in (["--search"], ["--add-dir", "/x"], ["-C", "/x"], ["--sandbox-x"]):
            with self.subTest(extra=extra):
                argv = self._codex(extra)
                self.assertEqual(argv[2:6], ["-s", "workspace-write", "-a", "never"])

    def test_unknown(self):
        with self.assertRaises(HorchError) as cm:
            agents.executable("gemini")
        self.assertEqual(cm.exception.exit_code, 2)


class PreambleTest(unittest.TestCase):
    def test_contents(self):
        text = preamble.render(task_id="task-1", dispatch_id="dsp-1", spec_path="/h/spec.md", horch="H --home /h")
        for needle in ("task-1", "dsp-1", "/h/spec.md",
                       "H --home /h ask --dispatch dsp-1", "--resume",
                       "H --home /h check --dispatch dsp-1", "--ack",
                       "H --home /h escalate --dispatch dsp-1",
                       "H --home /h done --dispatch dsp-1 --outcome", "AskUserQuestion", "다른 워커를 띄우지 않는다",
                       "horch 는 셸 명령으로 실행한다",
                       "도구 시간 초과 등으로 horch 출력을 못 받았으면 같은 명령을 그대로 다시 실행한다(ask·check·done 은 재호출 안전. escalate 는 다시 보내면 같은 보고가 한 번 더 간다)",
                       "같은 질문을 새로 하려면 다른 `--key` 를 준다(같은 key·같은 본문은 이전 답을 돌려준다)"):
            self.assertIn(needle, text)


class InjectTest(unittest.TestCase):
    def test_codex_gets_terminal(self):
        self.assertEqual(guard.inject_codex_env(["/usr/bin/codex", "--no-daemon"], "t7"),
                         ["/usr/bin/codex", "-c", 'shell_environment_policy.set.HC_TERMINAL_ID="t7"', "--no-daemon"])

    def test_terminal_is_json_quoted(self):
        self.assertEqual(guard.inject_codex_env(["codex"], 'a"b')[2], 'shell_environment_policy.set.HC_TERMINAL_ID="a\\"b"')

    def test_claude_unchanged(self):
        self.assertEqual(guard.inject_codex_env(["claude", "x"], "t7"), ["claude", "x"])


class GuardCliTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.did = self.add_dispatch(self.run_id, terminal=None, state="launching")

    def guard(self, *agent, terminal="t42", dispatch=None):
        args = ["launch-guard", "--dispatch", dispatch or self.did, "--", *agent]
        env = dict(self._env(terminal, None))
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), *args],
                              capture_output=True, text=True, env=env, timeout=30)
        return proc.returncode, proc.stdout

    def state(self, did=None):
        row = self.db().execute("SELECT state, terminal FROM dispatches WHERE id=?", (did or self.did,)).fetchone()
        return row["state"], row["terminal"]

    def test_claims_and_execs(self):
        code, out = self.guard("claude", "--x")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out), {"fake": "claude", "argv": ["--x"], "terminal": "t42"})
        self.assertEqual(self.state(), ("active", "t42"))

    def test_active_same_terminal_proceeds(self):
        self.db().execute("UPDATE dispatches SET state='active', terminal='t42' WHERE id=?", (self.did,)).connection.commit()
        code, out = self.guard("claude")
        self.assertEqual(code, 0, out)

    def test_refuses_failed_abandoned_and_other_terminal(self):
        for state, term in (("launch_failed", None), ("abandoned", "t42"), ("active", "t77")):
            with self.subTest(state=state):
                db = self.db()
                db.execute("UPDATE dispatches SET state=?, terminal=? WHERE id=?", (state, term, self.did))
                db.commit()
                code, out = self.guard("claude")
                self.assertEqual(code, 3)
                self.assertIn("[horch] launch-guard", out)
                self.assertNotIn('"fake"', out)
                self.assertEqual(self.state(), (state, term))

    def test_unknown_dispatch_refused(self):
        code, out = self.guard("claude", dispatch="dsp-nope")
        self.assertEqual(code, 3)
        self.assertNotIn('"fake"', out)
        self.assertEqual(self.state(), ("launching", None))

    def test_needs_terminal(self):
        code, out = self.guard("claude", terminal=None)
        self.assertEqual(code, 3)
        self.assertEqual(self.state(), ("launching", None))

    def test_codex_injection_end_to_end(self):
        code, out = self.guard("codex", "--no-daemon", "P")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["argv"],
                         ["-c", 'shell_environment_policy.set.HC_TERMINAL_ID="t42"', "--no-daemon", "P"])

    def test_double_dash_before_preamble_reaches_agent(self):
        code, out = self.guard("claude", "--add-dir", "/x", "--", "P")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["argv"], ["--add-dir", "/x", "--", "P"])
        self.tearDown()  # 첫 임시 폴더를 지운 뒤 새로 준비한다(그냥 setUp 하면 ResourceWarning)
        self.setUp()
        code, out = self.guard("codex", "--add-dir", "/x", "--", "P")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["argv"][-4:], ["--add-dir", "/x", "--", "P"])

    @unittest.skipUnless(shutil.which("perl"), "perl 필요")
    def test_sigpipe_restored_before_exec(self):
        code, out = self.guard("perl", "-e", 'print defined $SIG{PIPE} ? $SIG{PIPE} : "default"')
        self.assertEqual((code, out), (0, "default"))

    def test_missing_executable(self):
        code, out = self.guard("no-such-agent-xyz")
        self.assertEqual(code, 12)
        self.assertEqual(self.state(), ("active", "t42"))

    def test_usage_without_separator(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "launch-guard", "--dispatch", self.did],
                              capture_output=True, text=True, env=self._env("t42", None), timeout=30)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
