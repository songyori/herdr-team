import json
import subprocess
import sys
import unittest

from tests.helpers import BIN, REPO, ROOT, TeamCase


class CliTest(TeamCase):
    def test_version_envelope(self):
        code, out = self.hteam("version", as_=None)
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.1.0"))

    def test_unknown_command_is_usage_json(self):
        code, out = self.hteam("nope", as_=None)
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "usage")

    def test_stdout_is_single_json_line(self):
        proc = subprocess.run([sys.executable, str(BIN), "version"], capture_output=True, text=True, env=self.env)
        self.assertEqual(len(proc.stdout.strip().splitlines()), 1)
        json.loads(proc.stdout)

    def test_versions_match(self):
        from hteam.paths import VERSION
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        entry = [p for p in market["plugins"] if p["name"] == "herdr-team"][0]
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.1.0"})
        self.assertEqual(entry["source"], "./herdr-team")


if __name__ == "__main__":
    unittest.main()
