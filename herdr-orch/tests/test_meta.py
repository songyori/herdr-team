import json
import os
import shutil
import subprocess
import sys
import unittest

from tests.helpers import BIN, FAKES, ROOT, HorchCase

REPO = ROOT.parent


class MetaTest(HorchCase):
    def test_versions_match(self):
        from horch.paths import VERSION
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        entry = [p for p in market["plugins"] if p["name"] == "herdr-orch"][0]
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {VERSION})

    def test_skill_output(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "skill"],
                              capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(proc.returncode, 0)
        first = proc.stdout.splitlines()[0]
        self.assertTrue(first.startswith("HORCH: "))
        self.assertIn("--home", first)
        for needle in ("코디네이터 루프", "worker-start", "check --wait", "--ack", "worker-release", "워커 의무"):
            self.assertIn(needle, proc.stdout)
        self.assertFalse(self.home.exists())

    def test_skill_covers_later_behavior(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "skill"],
                              capture_output=True, text=True, env=self.env, timeout=30)
        for needle in (
            "stdout 의 JSON 한 개만 읽는다",
            "`warnings`(목록, 예: 영수증 기록 실패)",
            "exit 5(`binding_moved`·`not_owner`)",
            "`terminal_mismatch`",
            "--agent-arg=--dangerously-bypass-hook-trust",
            'attention: "no_status"',
        ):
            self.assertIn(needle, proc.stdout)

    def test_skill_stub(self):
        text = (ROOT / "skills" / "herdr-orchestration" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: herdr-orchestration", text)
        self.assertIn("bin/horch skill", text)

    def test_doctor_healthy_with_fakes(self):
        code, out = self.horch("doctor")
        self.assertEqual(code, 0, out)
        names = {c["name"]: c["ok"] for c in out["checks"]}
        for name in ("python", "hc", "hc_server", "herdr_app", "home_writable", "ps", "claude", "codex", "codex_no_daemon"):
            self.assertTrue(names[name], name)

    def test_doctor_unhealthy_without_herdr_app(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        os.symlink(FAKES / "hc", bin_dir / "hc")
        os.symlink(sys.executable, bin_dir / "python3")
        os.symlink(shutil.which("ps"), bin_dir / "ps")
        code, out = self.horch("doctor", env={"PATH": str(bin_dir)})
        self.assertEqual((code, out["error"]["code"]), (1, "unhealthy"))
        names = {c["name"]: c["ok"] for c in out["checks"]}
        self.assertFalse(names["herdr_app"])
        self.assertFalse(names["claude"])


if __name__ == "__main__":
    unittest.main()
