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
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.3.0"))

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
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.3.0"})
        self.assertEqual(entry["source"], "./herdr-team")
        # hteam 이 설치 기록에서 받는 가장 낮은 herdr-orch 는 함께 배포하는 herdr-orch 와 같다(성공 봉투 고침, 0.1.2)
        from hteam.horch import HORCH_MIN
        orch = [p for p in market["plugins"] if p["name"] == "herdr-orch"][0]
        self.assertEqual(HORCH_MIN, orch["version"])


class CompileWarningTest(unittest.TestCase):
    """경고를 오류로 바꿔 Python 소스를 compile 한다(정규식 문자열의 잘못된 이스케이프 등, orca-team 0576df2)."""

    def test_python_sources_compile_without_warnings(self):
        import warnings
        files = [f for folder in ("lib", "hooks", "templates", "tests") for f in sorted((ROOT / folder).rglob("*.py"))]
        files += [f for f in sorted((ROOT / "tests" / "fakes").iterdir())
                  if f.is_file() and f.suffix != ".py" and "python" in f.read_text(encoding="utf-8").split("\n", 1)[0]]
        files.append(ROOT / "bin" / "hteam")
        self.assertIn(ROOT / "tests" / "fakes" / "fake-test", files)
        for f in files:
            with self.subTest(str(f.relative_to(ROOT))), warnings.catch_warnings():
                warnings.simplefilter("error")
                compile(f.read_text(encoding="utf-8"), str(f), "exec")


if __name__ == "__main__":
    unittest.main()
