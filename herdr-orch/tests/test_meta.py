import json
import os
import shutil
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import BIN, FAKES, ROOT, HorchCase

REPO = ROOT.parent


class MetaTest(HorchCase):
    def test_versions_match(self):
        from horch.paths import VERSION
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
        entry = [p for p in market["plugins"] if p["name"] == "herdr-orch"][0]
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {VERSION})
        self.assertEqual(VERSION, "0.2.0")  # 고정 터미널(herdr-orch 설계 13장)

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
            "worker-show --dispatch <d> --lines 0",
            "--cwd <cwd> [--model <model>] [--effort <effort>] [--agent-arg=<각 인자>]...",
            "`skill` 을 뺀 모든 명령은 JSON 한 개를 출력한다",
            "사용자의 자격 증명(git, 클라우드 인증, 셸 환경)",
            'attention: "no_status"',
            # 실환경 확인 뒤 보강: done 없이 멈춘 워커, abandon 뒤 release, Codex hook
            "- `idle`: 워커가 done 없이 턴을 끝냈다. `horch worker-show --dispatch <d> --lines 40` 으로 화면을 보고",
            "(깨우기가 입력을 보낸다)",
            "일을 끝냈는데 done 을 잊었으면 done 하라고 보내고, 막혔으면 사용자에게 알린다.",
            "`abandoned` 도 `worker-release` 해야 정리된 것이다.",
            "사용자가 허락하면 `--agent-arg=--disable=hooks`",
            "`--dangerously-bypass-hook-trust` 는 검토하지 않은 hook 을 실행해, 깨진 hook(예: Node 버전이 맞지 않는 hook)이 "
            "워커의 셸 명령을 모두 막을 수 있다.",
            "`--disable=hooks` 는 hook 을 끄고 확인 창도 없앤다",
            "horch 는 셸 명령으로 실행한다",
            # 최종 리뷰 뒤 보강: 재시도와 새 Task 구분, 여러 줄 spec
            "`--task <id> --retry` 는 `launch_failed` 를 다시 띄울 때만 쓴다",
            "`outcome=failed` 로 끝난 Task 는 다시 열리지 않는다",
            "`--task` 없이 새 Task 로 띄운다",
            "--spec-file <경로>",
        ):
            self.assertIn(needle, proc.stdout)
        self.assertEqual(proc.stdout.count("`--agent-arg` 로 권한·샌드박스 우회를 넘기면"), 1)  # 같은 항목이 두 번 없다
        self.assertNotIn("--agent-arg=--dangerously-bypass-hook-trust", proc.stdout)
        # abandon 은 abandoned 표시일 뿐이다. abandon 을 "정리" 라 부르면 release 없이 끝낸다(실환경 확인)
        for line in proc.stdout.splitlines():
            if "worker-abandon" in line:
                self.assertNotIn("정리", line, line)

    def test_skill_covers_persistent_terminal(self):
        proc = subprocess.run([sys.executable, str(BIN), "--home", str(self.home), "skill"],
                              capture_output=True, text=True, env=self.env, timeout=30)
        for needle in ("## 고정 터미널(0.2.0)", "worker-start --keep-open", "worker-start --terminal <t>",
                       "observed `not_started`", "--keep-terminal", "terminal-reset --terminal <t>",
                       "terminal-close --terminal <t> [--abandon]", "--key <요청 id>", "`duplicate: true`",
                       "`reset_timeout`", "고정 Dispatch 는 `--kill` 대신 `terminal-close --terminal <t> --abandon`"):
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
        # 가짜 herdr-app status 는 실제처럼 여러 줄 JSON 을 낸다. 첫 글자 "{" 가 아니라 한 줄 요약을 보인다
        detail = {c["name"]: c["detail"] for c in out["checks"]}["herdr_app"]
        self.assertEqual(detail, "running true, version 0.9.0, spaces 2개")

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

    def test_doctor_survives_non_executable_herdr_app(self):
        bin_dir = self.tmp / "bin2"
        bin_dir.mkdir()
        shutil.copy(FAKES / "herdr-app", bin_dir / "herdr-app")
        os.chmod(bin_dir / "herdr-app", 0o644)
        os.symlink(FAKES / "hc", bin_dir / "hc")
        os.symlink(sys.executable, bin_dir / "python3")
        os.symlink(shutil.which("ps"), bin_dir / "ps")
        code, out = self.horch("doctor", env={"PATH": str(bin_dir)})
        self.assertEqual((code, out["error"]["code"]), (1, "unhealthy"))
        names = {c["name"]: c["ok"] for c in out["checks"]}
        self.assertFalse(names["herdr_app"])
        for name in ("python", "hc", "home_writable", "ps"):
            self.assertIn(name, names)


class HerdrStatusTest(unittest.TestCase):
    def status(self, stdout: str, stderr: str = "", code: int = 0):
        from horch import herdr
        done = subprocess.CompletedProcess(["herdr-app", "status"], code, stdout, stderr)
        with mock.patch.object(herdr.subprocess, "run", return_value=done):
            return herdr.app_status()

    def test_multiline_json_is_summarized(self):
        text = json.dumps({"running": True, "spaces": [{"id": "a"}], "app": {"x": 1}, "pid": 7}, indent=2)
        self.assertEqual(self.status(text), (True, "running true, spaces 1개, pid 7"))

    def test_json_without_scalars_is_ok(self):
        self.assertEqual(self.status(json.dumps({"app": {"x": 1}}, indent=2)), (True, "ok"))

    def test_json_error_shows_message(self):
        err = json.dumps({"error": {"kind": "no_app", "message": "앱이 떠 있지 않다"}}, indent=2)
        self.assertEqual(self.status("", err, 1), (False, "앱이 떠 있지 않다"))

    def test_plain_text_keeps_first_line(self):
        self.assertEqual(self.status("layout: main\nspaces: 2\n"), (True, "layout: main"))
        self.assertEqual(self.status("", "", 3), (False, "exit 3"))


if __name__ == "__main__":
    unittest.main()
