import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

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

    def test_unserializable_result_is_internal_json(self):
        # 명령이 JSON 으로 못 바꾸는 값을 돌려줘도 stdout 에는 오류 봉투 하나만 나오고 exit 1 이다.
        from hteam import cli
        for bad in ({"path": Path("/x")}, ["not", "a", "dict"], None):
            parser = cli.Parser(prog="hteam")
            parser.set_defaults(func=lambda args, bad=bad: bad)
            buf = io.StringIO()
            with mock.patch.object(cli, "build_parser", return_value=parser), contextlib.redirect_stdout(buf):
                code = cli.main([])
            lines = buf.getvalue().strip().splitlines()
            self.assertEqual(len(lines), 1, bad)
            out = json.loads(lines[0])
            self.assertEqual((code, out["ok"], out["error"]["code"]), (1, False, "internal"), bad)

    def test_versions_match(self):
        from hteam.paths import VERSION
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        entry = [p for p in market["plugins"] if p["name"] == "herdr-team"][0]
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.1.0"})
        self.assertEqual(entry["source"], "./herdr-team")
        # hteam 이 설치 기록에서 받는 가장 낮은 herdr-orch 는 함께 배포하는 herdr-orch 와 같다(성공 봉투 고침, 0.1.2)
        from hteam.horch import HORCH_MIN
        orch = [p for p in market["plugins"] if p["name"] == "herdr-orch"][0]
        self.assertEqual(HORCH_MIN, orch["version"])


if __name__ == "__main__":
    unittest.main()
