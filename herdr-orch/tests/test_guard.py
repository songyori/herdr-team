import json
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
        self.assertEqual(argv, ["claude", "--model", "opus", "--effort", "high", "--x", "P"])
        self.assertEqual(agents.build("claude", model=None, effort=None, extra=[], preamble="P", home=Path("/h")),
                         ["claude", "P"])

    def test_codex(self):
        argv = agents.build("codex", model="gpt-5.5", effort="high", extra=[], preamble="P", home=Path("/h"))
        self.assertEqual(argv, ["codex", "--no-daemon", "-s", "workspace-write", "-a", "never", "--add-dir", "/h",
                                "-m", "gpt-5.5", "-c", "model_reasoning_effort=high", "P"])

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
                       "H --home /h done --dispatch dsp-1 --outcome", "AskUserQuestion", "다른 워커를 띄우지 않는다"):
            self.assertIn(needle, text)


class InjectTest(unittest.TestCase):
    def test_codex_gets_terminal(self):
        self.assertEqual(guard.inject_codex_env(["/usr/bin/codex", "--no-daemon"], "t7"),
                         ["/usr/bin/codex", "-c", 'shell_environment_policy.set.HC_TERMINAL_ID="t7"', "--no-daemon"])

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

    def state(self):
        row = self.db().execute("SELECT state, terminal FROM dispatches WHERE id=?", (self.did,)).fetchone()
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

    def test_needs_terminal(self):
        code, out = self.guard("claude", terminal=None)
        self.assertEqual(code, 3)
        self.assertEqual(self.state(), ("launching", None))

    def test_codex_injection_end_to_end(self):
        code, out = self.guard("codex", "--no-daemon", "P")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["argv"],
                         ["-c", 'shell_environment_policy.set.HC_TERMINAL_ID="t42"', "--no-daemon", "P"])

    def test_missing_executable(self):
        code, out = self.guard("no-such-agent-xyz")
        self.assertEqual(code, 12)

    def test_usage_without_separator(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "launch-guard", "--dispatch", self.did],
                              capture_output=True, text=True, env=self._env("t42", None), timeout=30)
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
