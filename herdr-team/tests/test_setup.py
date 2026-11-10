"""doctor·scaffold·shim·up·bind·setup-done(설계 9.1–9.3)와 스킬·템플릿."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, DRIVE, HORCH_FAKES, MAIN, NONCE, ROOT, TeamCase
from hteam import config
from hteam.errors import HteamError
from hteam.paths import Project

# 가짜 hc 앞에 두는 감싸개. run 의 응답 유실·깨짐과 특정 터미널의 hc get 실패를 흉내 낸다(나머지는 가짜 hc 로 넘긴다).
WRAP_HC = """#!/usr/bin/env python3
import json, os, subprocess, sys
real = os.environ["WRAP_REAL_HC"]
args = sys.argv[1:]
mode = os.environ.get("WRAP_MODE", "")
if args[:1] == ["run"] and mode == "lost":
    print("garbage")
    sys.exit(1)
if args[:1] == ["run"] and mode == "created_garbled":
    subprocess.run([sys.executable, real, *args], capture_output=True)
    print("garbage")
    sys.exit(0)
if args[:2] == ["get", os.environ.get("WRAP_FAIL_GET")]:
    sys.stderr.write(json.dumps({"error": {"kind": "server_down"}}) + "\\n")
    sys.exit(1)
os.execv(sys.executable, [sys.executable, real, *args])
"""


class SetupCase(TeamCase):
    def run_json(self):
        return json.loads((self.state_dir / "run.json").read_text())

    def run_calls(self):
        return [c for c in self.hc_calls() if c[:1] == ["run"]]

    def wrap_env(self, **extra):
        wrap = self.tmp / "wrap"
        wrap.mkdir(exist_ok=True)
        (wrap / "hc").write_text(WRAP_HC)
        (wrap / "hc").chmod(0o755)
        return {"PATH": f"{wrap}{os.pathsep}{self.env['PATH']}", "WRAP_REAL_HC": str(HORCH_FAKES / "hc"), **extra}

    def pause_env(self, point: str, name: str):
        gate = self.tmp / f"gate-{name}"
        return gate, {"HTEAM_TEST_PAUSE_AT": point, "HTEAM_TEST_PAUSE_FILE": str(gate)}

    def wait_reached(self, gate: Path, proc=None, timeout: float = 30) -> None:
        reached = gate.with_name(gate.name + ".reached")
        deadline = time.monotonic() + timeout
        while not reached.exists():
            if proc is not None and proc.poll() is not None:
                self.fail(f"멈출 곳({gate.name})에 닿기 전에 끝났다: {self.finish(proc)}")
            self.assertLess(time.monotonic(), deadline, f"{gate.name} 에 닿지 않았다")
            time.sleep(0.02)


class DoctorTest(TeamCase):
    def test_healthy_with_fakes(self):
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)
        checks = {c["name"]: c for c in out["checks"]}
        for name in ("python", "git", "horch", "horch_doctor", "herdr_terminal", "claude", "codex", "codex_login",
                     "codex_wrapper"):
            self.assertTrue(checks[name]["ok"], checks[name])
        self.assertEqual(checks["codex_image_generation"]["level"], "warning")
        self.assertFalse(checks["chrome_devtools_mcp"]["ok"])
        (self.tmp / "home" / ".claude.json").write_text('{"mcpServers": {"chrome-devtools": {}}}')
        checks = {c["name"]: c for c in self.hteam("doctor", as_="main")[1]["checks"]}
        self.assertTrue(checks["chrome_devtools_mcp"]["ok"])

    def test_unhealthy_without_codex_or_terminal(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        for name in ("hc", "herdr-app", "claude"):
            os.symlink(HORCH_FAKES / name, bin_dir / name)
        for name in ("python3", "ps", "git"):
            os.symlink(shutil.which(name), bin_dir / name)
        code, out = self.hteam("doctor", as_=None, env={"PATH": str(bin_dir)})
        self.assertEqual((code, out["error"]["code"]), (1, "unhealthy"), out)
        bad = {c["name"] for c in out["checks"] if not c["ok"] and c["level"] == "error"}
        self.assertEqual(bad, {"codex", "herdr_terminal"})


class ScaffoldTest(TeamCase):
    def scaffold(self):
        desc = self.tmp / "desc.txt"
        desc.write_text("할 일 앱\n두 번째 줄\n")
        return self.hteam("scaffold", "--description-file", str(desc), as_="main")

    def test_creates_files_and_never_overwrites(self):
        (self.proj / "CLAUDE.md").write_text("# 기존 규칙\n")
        code, out = self.scaffold()
        self.assertEqual(code, 0, out)
        self.assertNotIn(".herdr-team/coordinator.md", out["created"])  # 0.4.0 은 코디네이터 문서가 없다(설계 9.6)
        for rel in (".herdr-team/config.toml", ".herdr-team/roles/planner.md",
                    ".herdr-team/roles/director.md", ".herdr-team/roles/designer.md", ".herdr-team/roles/developer.md",
                    ".herdr-team/roles/tester.md", ".herdr-team/design-rules.md", ".herdr-team/text-rules.md",
                    ".herdr-team/bin/hteam",
                    ".herdr-team/project.md", "CLAUDE.md", "AGENTS.md", ".gitignore"):
            self.assertIn(rel, out["created"])
        claude = (self.proj / "CLAUDE.md").read_text()
        self.assertTrue(claude.startswith("# 기존 규칙\n"))
        self.assertIn("<!-- herdr-team -->", claude)
        self.assertTrue(os.access(self.proj / ".herdr-team/bin/hteam", os.X_OK))
        self.assertTrue((self.state_dir / "setup-mode").exists())
        self.assertEqual((self.state_dir / "plugin-root").read_text().strip(), str(ROOT))
        p = Project(self.proj)
        cfg = config.load(p)
        for role in cfg.roles:
            self.assertTrue(p.role_doc(role).is_file(), role)
        self.assertEqual((self.team / "text-rules.md").read_text(encoding="utf-8"),
                         (ROOT / "templates/text-rules.md").read_text(encoding="utf-8"))
        # 정책·사용자 문서를 맡는 직무가 없어 developer 가 맡는다(설계 4.1·11.7)
        self.assertEqual(cfg.owns("developer"), ["src/**", "README.md", "docs/user/**", "docs/policy/**"])
        (self.team / "roles/planner.md").write_text("바꿈\n")
        code, out = self.scaffold()
        self.assertEqual((code, out["created"]), (0, []), out)
        self.assertEqual((self.team / "roles/planner.md").read_text(), "바꿈\n")
        self.assertFalse((self.team / "coordinator.md").exists())
        self.assertEqual((self.proj / "CLAUDE.md").read_text().count("<!-- herdr-team -->"), 1)
        self.assertEqual((self.proj / ".gitignore").read_text().count(".herdr-team/state/"), 1)

    def test_agents_section_says_parallel_head_moves_are_normal(self):
        # 실환경(1단계): "HEAD 가 움직이면 판정이 무효" 를 다른 워커의 커밋까지로 읽은 Codex 리뷰어가 병렬 커밋마다
        # 코디네이터에게 묻고 escalate 했다. 무효는 리뷰어 자신의 쓰기만이고 남의 커밋은 정상이라고 적어야 한다.
        self.scaffold()
        agents = (self.proj / "AGENTS.md").read_text()
        self.assertIn("네가 추적 파일 내용을 바꾸거나 HEAD 를 움직이면 판정이 무효가 된다", agents)
        self.assertIn("리뷰 동안 다른 워커·관제·메인의 커밋으로 HEAD 가 움직이는 것은 정상이다", agents)
        self.assertNotIn("추적 파일 내용이 바뀌거나 HEAD 가 움직이면", agents)

    def test_shim_finds_plugin(self):
        self.scaffold()
        shim = str(self.proj / ".herdr-team/bin/hteam")
        env = dict(self.env, HERDR_TEAM_PLUGIN_ROOT=str(ROOT))
        out = subprocess.run([sys.executable, shim, "version"], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(out.stdout)["version"], "0.4.0")
        registry = self.tmp / "installed.json"
        registry.write_text(json.dumps({"plugins": {"herdr-team@herdr-team": [{"installPath": str(ROOT)}]}}))
        env = dict(self.env, HTEAM_PLUGINS_JSON=str(registry))
        out = subprocess.run([sys.executable, shim, "version"], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stdout)
        fake = self.tmp / "evil"
        (fake / "bin").mkdir(parents=True)
        (fake / "bin" / "hteam").write_text("print('evil')\n")
        (self.state_dir / "plugin-root").write_text(str(fake))
        out = subprocess.run([sys.executable, shim, "version"], capture_output=True, text=True, env=self.env)
        self.assertEqual(out.returncode, 12)  # 등록되지 않은 plugin-root 는 믿지 않는다

    def test_setup_done(self):
        self.scaffold()
        self.assertEqual(self.hteam("setup-done", as_="main")[0], 0)
        self.assertFalse((self.state_dir / "setup-mode").exists())


class UpgradeTest(TeamCase):
    """hteam upgrade(설계 9.6): 커밋돼 있고 깨끗한 규칙 파일만 템플릿으로 바꾼다."""

    def setUp(self):
        super().setUp()
        self.scaffolded()

    def scaffolded(self):
        desc = self.tmp / "desc.txt"
        desc.write_text("할 일 앱\n")
        code, out = self.hteam("scaffold", "--description-file", str(desc), as_="main")
        self.assertEqual(code, 0, out)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "chore: herdr-team 세팅")

    def upgrade(self):
        return self.hteam("upgrade", as_=None)

    def edit_commit(self, rel, text):
        self.commit(rel, text, f"사용자: {rel}")

    def template(self, name):
        return (ROOT / "templates" / name).read_text(encoding="utf-8")

    def test_same_files_change_nothing(self):
        code, out = self.upgrade()
        self.assertEqual((code, out["updated"], out["created"], out["skipped"], out["manual"], out["diff_stat"]),
                         (0, [], [], [], [], ""), out)
        # 설계 9.6(6단계): 코디네이터를 다시 띄우라는 줄이 없다. 직무 문서는 워커 사양에 라운드마다 들어간다
        self.assertEqual(out["next"], "바뀐 파일을 확인하고(git diff -- .herdr-team) 커밋한다. manual 의 절은 템플릿과 견줘 직접 "
                         "고친다. 직무 문서는 워커 사양에 라운드마다 들어가므로 커밋하면 다음 라운드부터 적용된다. 테스트 관문을 "
                         "쓰려면 docs/planning/tasks.toml 에 [test] 를 넣고 커밋한다(README \"묶음 검증\").")

    def test_overwrites_committed_copies_and_skips_the_rest(self):
        self.edit_commit(".herdr-team/coordinator.md", "옛 코디네이터 사본\n")  # 0.3.0 이 복사한 옛 파일: 건드리지 않는다
        self.edit_commit(".herdr-team/roles/planner.md", "옛 기획 문서 사본\n")
        self.edit_commit(".herdr-team/roles/developer.md", "사용자가 커밋한 수정\n")
        (self.team / "roles/designer.md").write_text("커밋 안 한 수정\n", encoding="utf-8")
        self.git("rm", "-q", "--", ".herdr-team/design-rules.md")
        self.git("commit", "-q", "-m", "디자인 규칙 지움")
        self.git("rm", "-q", "--cached", "--", ".herdr-team/text-rules.md")
        self.git("commit", "-q", "-m", "문구 규칙 추적 해제")
        config = (self.team / "config.toml").read_text(encoding="utf-8") + "# 사용자 메모\n"
        self.edit_commit(".herdr-team/config.toml", config)
        (self.team / "bin/hteam").chmod(0o644)
        self.git("add", "--", ".herdr-team/bin/hteam")
        self.git("commit", "-q", "-m", "실행 비트 잃음")
        head = self.head()
        code, out = self.upgrade()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["updated"], [".herdr-team/roles/planner.md", ".herdr-team/roles/developer.md"])
        self.assertEqual(out["created"], [".herdr-team/design-rules.md"])
        self.assertEqual(out["skipped"], [
            {"path": ".herdr-team/text-rules.md", "reason": "git 에 추적되지 않는다. 템플릿과 직접 비교해 바꾼다"},
            {"path": ".herdr-team/roles/designer.md",
             "reason": "커밋 안 된 변경이 있다(지운 것 포함). 커밋하거나 되돌린 뒤 다시 한다"}])
        for rel, name in ((".herdr-team/roles/planner.md", "roles/planner.md"), (".herdr-team/roles/developer.md",
                          "roles/developer.md"), (".herdr-team/design-rules.md", "design-rules.md")):
            self.assertEqual((self.proj / rel).read_text(encoding="utf-8"), self.template(name), rel)
        self.assertEqual((self.team / "roles/designer.md").read_text(encoding="utf-8"), "커밋 안 한 수정\n")
        self.assertEqual((self.team / "config.toml").read_text(encoding="utf-8"), config)
        self.assertNotIn("config.toml", json.dumps(out, ensure_ascii=False))
        self.assertEqual(self.head(), head)  # 커밋하지 않는다
        self.assertIn("planner.md", out["diff_stat"])
        self.assertEqual((self.team / "coordinator.md").read_text(encoding="utf-8"), "옛 코디네이터 사본\n")
        self.assertNotIn("coordinator.md", json.dumps(out, ensure_ascii=False))
        self.assertNotIn("designer.md", out["diff_stat"])
        self.assertEqual((self.team / "bin/hteam").stat().st_mode & 0o777, 0o755)
        code, again = self.upgrade()
        self.assertEqual((code, again["updated"], again["created"]), (0, [], []), again)

    def test_uncommitted_deletions_are_not_restored(self):
        (self.team / "roles/planner.md").unlink()  # 작업 트리 삭제( D)
        self.git("rm", "-q", "--", ".herdr-team/roles/tester.md")  # 스테이징한 삭제(D )
        code, out = self.upgrade()
        self.assertEqual((code, out["created"], [s["path"] for s in out["skipped"]]),
                         (0, [], [".herdr-team/roles/planner.md", ".herdr-team/roles/tester.md"]), out)
        self.assertTrue(all("지운 것 포함" in s["reason"] for s in out["skipped"]))
        self.assertFalse((self.team / "roles/planner.md").exists() or (self.team / "roles/tester.md").exists())

    def test_old_sections_are_manual_and_kept(self):
        claude = (self.proj / "CLAUDE.md").read_text(encoding="utf-8").replace("### 질문 표시 규칙", "### 옛 질문 규칙")
        self.edit_commit("CLAUDE.md", claude)
        self.git("rm", "-q", "--", "AGENTS.md")
        self.git("commit", "-q", "-m", "AGENTS.md 지움")
        code, out = self.upgrade()
        self.assertEqual(out["manual"], [
            {"path": "CLAUDE.md", "reason": "덧붙인 herdr-team 절이 템플릿과 다르다. templates/CLAUDE.section.md 과 견줘 직접 바꾼다"},
            {"path": "AGENTS.md", "reason": "herdr-team 절이 없다. scaffold 를 다시 하면 덧붙인다"}])
        self.assertEqual((self.proj / "CLAUDE.md").read_text(encoding="utf-8"), claude)


    def test_hidden_index_flags_are_skipped(self):
        for flag, rel in (("--assume-unchanged", "roles/planner.md"), ("--skip-worktree", "roles/tester.md")):
            self.git("update-index", flag, "--", f".herdr-team/{rel}")
            (self.team / rel).write_text("커밋 안 한 수정\n", encoding="utf-8")
        code, out = self.upgrade()
        self.assertEqual(code, 0, out)
        reason = ("git 숨김 플래그(assume-unchanged·skip-worktree)가 있다. 플래그를 풀고"
                  "(git update-index --no-assume-unchanged --no-skip-worktree) 다시 한다")
        self.assertEqual(out["skipped"], [{"path": ".herdr-team/roles/planner.md", "reason": reason},
                                          {"path": ".herdr-team/roles/tester.md", "reason": reason}])
        for rel in ("roles/planner.md", "roles/tester.md"):
            self.assertEqual((self.team / rel).read_text(encoding="utf-8"), "커밋 안 한 수정\n")

    def test_symlinked_folder_is_not_followed(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        self.git("rm", "-r", "-q", "--", ".herdr-team/roles")
        (self.team / "roles").symlink_to(outside)
        self.git("add", "--", ".herdr-team/roles")
        self.git("commit", "-q", "-m", "roles 를 링크로")
        code, out = self.upgrade()
        self.assertEqual(code, 0, out)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(out["created"], [])
        paths = {s["path"]: s["reason"] for s in out["skipped"]}
        self.assertEqual(paths[".herdr-team/roles/planner.md"], "경로에 심볼릭 링크가 있다. 템플릿과 직접 비교해 바꾼다")
        self.assertEqual(len(paths), 5)

    def test_tracked_broken_file_link_is_kept(self):
        link = self.team / "text-rules.md"
        self.git("rm", "-q", "--", ".herdr-team/text-rules.md")
        link.symlink_to(self.tmp / "nowhere")
        self.git("add", "--", ".herdr-team/text-rules.md")
        self.git("commit", "-q", "-m", "끊어진 링크")
        code, out = self.upgrade()
        self.assertEqual(code, 0, out)
        self.assertTrue(link.is_symlink() and not link.exists())
        self.assertEqual(out["skipped"], [{"path": ".herdr-team/text-rules.md",
                                           "reason": "경로에 심볼릭 링크가 있다. 템플릿과 직접 비교해 바꾼다"}])

    def test_shim_link_does_not_chmod_outside(self):
        target = self.tmp / "outside-file"
        shim = self.template("shim.py")
        target.write_text(shim)  # 템플릿과 같은 바이트라 덮어쓰기 없이 chmod 만 남는 경우
        target.chmod(0o600)
        self.git("rm", "-q", "--", ".herdr-team/bin/hteam")
        (self.team / "bin").mkdir(exist_ok=True)
        (self.team / "bin/hteam").symlink_to(target)
        self.git("add", "--", ".herdr-team/bin/hteam")
        self.git("commit", "-q", "-m", "shim 링크")
        code, out = self.upgrade()
        self.assertEqual(code, 0, out)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.read_text(), shim)
        self.assertEqual([s["path"] for s in out["skipped"]], [".herdr-team/bin/hteam"])


class SubdirUpgradeTest(UpgradeTest):
    def setUp(self):
        TeamCase.setUp(self)
        self.proj = self.proj / "sub"
        self.proj.mkdir()
        self.scaffolded()


class SkillTemplateTest(unittest.TestCase):
    def test_skills_and_templates(self):
        for name in ("init", "up"):
            text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", text)
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        for needle in ("doctor", "scaffold --description-file", "up --wait-run 180", "watch", "setup-done",
                       "chore: herdr-team 세팅", "bypassPermissions"):
            self.assertIn(needle, init)
        up = (ROOT / "skills/up/SKILL.md").read_text(encoding="utf-8")
        for needle in ("hteam status", "up --wait-run 180", "hteam watch", "hteam reask", "hteam answer"):
            self.assertIn(needle, up)
        self.assertFalse((ROOT / "templates/coordinator.md").exists())  # 6단계에 지웠다(설계 3.1)


class TemplateContractTest(unittest.TestCase):
    def test_batch_rules_in_main(self):
        # 설계 8.4·7.7: 메인의 done·upgrade·위치 줄(묶음 후속·마무리는 관제 코드가 한다, test_drive_flows)
        main = (ROOT / "templates/CLAUDE.section.md").read_text(encoding="utf-8")
        for needle in ("`done`: 결과, 태스크별 리뷰 판정과 라운드 수, 마지막 전체 테스트(full) 결과를 요약해 전한다.",
                       "`.herdr-team/bin/hteam upgrade` 를 실행해 바꾼 것·건너뛴 것·`manual` 을 보여 주고",
                       "테스트 명령 `docs/planning/tasks.toml` 의 `[test]`, QA 보고서 `docs/qa/`."):
            self.assertIn(needle, main)

    def test_skill_recovery_contract(self):
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        up = (ROOT / "skills/up/SKILL.md").read_text(encoding="utf-8")
        for text in (init, up):
            for needle in ("exit 3 `launch_raced`", "exit 1 `launch_uncertain`", "`hung`", "up --wait-run 180"):
                self.assertIn(needle, text)
            self.assertNotIn("coordinator_unverifiable", text)
            self.assertNotIn("up --force", text)
        self.assertIn("5단계가 어떻게 끝나도(exit 1·3·4 포함) 6단계로 간다. setup-mode 를 켠 채 두지 않는다.", init)
        self.assertIn("`[agents.claude].args` 는 Claude 워커·리뷰어(고정 에이전트 포함)를 띄울 때마다 붙는다", init)

    def test_template_roles(self):
        import tomllib
        from hteam import plan
        raw = tomllib.loads((ROOT / "templates/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(raw["roles"]), {"planner", "director", "designer", "developer", "tester"})
        self.assertEqual(raw["user_approval_roles"], ["designer"])  # director 는 승인 직무가 아니다(설계 11.1)
        self.assertEqual(raw["roles"]["designer"]["owns"], ["docs/design/**", "assets/**"])
        self.assertEqual(raw["roles"]["director"]["owns"], ["docs/design/**", "assets/**"])
        self.assertEqual(config.validate(raw), [])
        self.assertEqual(sorted(p.name for p in (ROOT / "templates/roles").iterdir()),
                         ["designer.md", "developer.md", "director.md", "planner.md", "tester.md"])
        designer = (ROOT / "templates/roles/designer.md").read_text(encoding="utf-8")
        for needle in ("docs/design/screens/<화면>/index.html", "- 아티팩트: <claude.ai URL 또는 없음>",
                       "사용자 일괄 승인", "코드(`src/`)"):
            self.assertIn(needle, designer)
        developer = (ROOT / "templates/roles/developer.md").read_text(encoding="utf-8")
        self.assertIn("패키지는 임시 venv(또는 프로젝트의 격리 환경) 안에서만 설치한다. 전역·시스템 Python 에 설치하지 않고 "
                      "`--user` 도 쓰지 않는다.", developer)

        def task(key, role, owns, deps=()):
            return {"key": key, "role": role, "title": f"{key} 제목", "owns": list(owns), "depends_on": list(deps),
                    "target": "대상", "change": "바꿀 것", "constraints": "제약", "acceptance": ["확인 1"]}
        # 템플릿 설정으로 디렉터 태스크 하나, 그것에 의존하는 화면마다 designer 태스크, 개발이 그것에 의존하는 그래프가
        # plan check 를 통과한다(디렉터 owns 는 설계 11.1 대로 좁힌다)
        cfg = config.build(raw)
        direction = task("design-direction", "director",
                         ["docs/design/direction.md", "docs/design/references.md", "docs/design/board/**",
                          "docs/design/pilots/**", "docs/design/system/**"])
        screens = [task("login-screen", "designer", ["docs/design/screens/login/**", "assets/login/**"],
                        ["design-direction"]),
                   task("list-screen", "designer", ["docs/design/screens/list/**", "assets/list/**"],
                        ["design-direction"])]
        app = task("app", "developer", ["src/**"], ["login-screen", "list-screen"])
        self.assertEqual(plan.validate(cfg, [direction, *screens, app]),
                         ([], [["design-direction"], ["login-screen", "list-screen"], ["app"]]))
        alone = [{**t, "depends_on": []} for t in screens]  # 디렉터 태스크가 없으면 plan check 가 거부한다
        self.assertIn("designer 태스크가 있으면 director 태스크가 정확히 하나여야 한다(지금 0개)",
                      plan.validate(cfg, [*alone, app])[0])
        chained = [direction, screens[0],
                   task("login-more", "designer", ["docs/design/screens/login/**"], ["login-screen"])]
        self.assertTrue(any("승인 직무 태스크" in e for e in plan.validate(cfg, chained)[0]))

    def test_codex_reviewer_browser_in_template(self):
        # Codex 리뷰어가 화면을 렌더하도록 chrome-devtools 서버를 헤드리스·격리·버전 고정으로 정의한다. 우회 플래그는
        # 기본에 넣지 않는다(init 이 승인받는다). horch 는 그대로 -s workspace-write -a never 를 붙이고, 우회를 더하면 뺀다
        import tomllib
        raw = tomllib.loads((ROOT / "templates/config.toml").read_text(encoding="utf-8"))
        args = raw["agents"]["codex"]["args"]
        # 서버 이름은 herdr-team 전용(hteam-browser): 사용자·플러그인의 chrome-devtools 를 -c 로 덮으면 기존 정의와 합쳐져
        # url 정의면 "url is not supported for stdio" 로 Codex 가 시작하지 못한다(codex-cli 0.166, Codex 계획 r2)
        self.assertEqual(args, ["--disable=hooks",
                                "-c", 'mcp_servers.hteam-browser={command="npx",args=["-y","chrome-devtools-mcp@1.10.1",'
                                      '"--headless=true","--isolated=true"],startup_timeout_sec=60}'])
        self.assertFalse([a for a in args if "chrome-devtools=" in a or "chrome-devtools." in a])
        self.assertFalse(any("bypass" in a or a in ("--yolo", "--full-auto") for a in args))
        sys.path.insert(0, str(ROOT.parent / "herdr-orch" / "lib"))
        self.addCleanup(sys.path.remove, str(ROOT.parent / "herdr-orch" / "lib"))
        from horch import agents
        self.assertEqual(set(config.CODEX_BYPASS), agents._BYPASS)  # doctor·image 가 보는 우회 플래그가 horch 와 같다
        argv = agents.build("codex", model=None, effort=None, extra=args, preamble="P", home=Path("/h"))
        self.assertEqual(argv[:6], ["codex", "--no-daemon", "-s", "workspace-write", "-a", "never"])
        argv = agents.build("codex", model=None, effort=None, extra=args + ["--dangerously-bypass-approvals-and-sandbox"],
                            preamble="P", home=Path("/h"))
        self.assertNotIn("-s", argv[:4])
        self.assertNotIn("never", argv)
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        for needle in ("Codex 권한(샌드박스 우회)", "`--dangerously-bypass-approvals-and-sandbox`", "코드로만 본다",
                       "변조 검사가 잡지 못한다", "`codex_browser`", "다른 MCP 서버도 승인 없이 쓸 수 있다"):
            self.assertIn(needle, init)

    def test_auto_up_in_templates(self):
        # 설계 4.1·9.3·9.5: 템플릿 설정의 auto_up, 메인 규칙의 자동 부활 줄, up 스킬은 수동 복구
        import tomllib
        text = (ROOT / "templates/config.toml").read_text(encoding="utf-8")
        self.assertIs(tomllib.loads(text)["drive"]["auto_up"], True)
        self.assertIn("# auto_up: [drive] 표에 둔다. 메인 세션 훅이 관제(hteam drive)가 확실히 죽은 것을 보면 자동으로 다시 "
                      "띄운다(기본 true). false 면 안내만 한다.\n", text)
        main = (ROOT / "templates/CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("- 관제는 훅이 확인하고 꺼져 있으면 자동으로 다시 띄운다(config.toml `[drive] auto_up`). 훅 안내가 없는데 "
                      "관제 상태가 의심되면 `/herdr-team:up` 을 실행한다. 메인을 다시 열었는데 답하지 않은 질문이 있으면 "
                      "`/herdr-team:up` 이 다시 묻는다.\n", main)
        self.assertNotIn("먼저 실행한다", main)
        head = (ROOT / "skills/up/SKILL.md").read_text(encoding="utf-8").split("---")[1]
        for needle in ("수동 복구", "메인 세션 훅이", "[drive] auto_up", "자동 부활이 꺼져 있거나 훅이 안내했을 때",
                       "열린 질문을 다시 물을 때"):
            self.assertIn(needle, head)

    def test_cleanup_rules_in_docs(self):
        up =(ROOT / "skills/up/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("`run_error`", up)

    def test_no_personal_paths_or_trust_all(self):
        import re
        private = re.compile(r"/[U]sers/|/private/[t]mp|~[/]Workspace|/[h]ome/")
        files = [*(ROOT / "templates").rglob("*"), *(ROOT / "skills").rglob("*")]
        for path in (f for f in files if f.is_file()):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(private.search(text), path)
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        for sentence in ("사용자 전역 설정(`~/.claude/`, `~/.claude.json`, `~/.codex/`)을 고치지 않는다.",
                         "Codex 의 폴더 신뢰를 한꺼번에 허용하는 설정(\"Trust all\" 류)이나 전역 샌드박스·승인 우회 설정을 쓰지 않는다(우회는 이 프로젝트의 `[agents.codex].args` 에, 위 표로 승인받았을 때만).",
                         "사용자가 승인했을 때만 넣는다."):
            self.assertIn(sentence, init)


# --- 리뷰 지적(commit-2b52d76) 재현 ---


class ReviewFixScaffoldTest(SetupCase):
    def scaffold(self):
        desc = self.tmp / "desc.txt"
        desc.write_text("할 일 앱\n")
        return self.hteam("scaffold", "--description-file", str(desc), as_="main")

    def test_appends_and_keeps_existing_bytes(self):
        ignore = b"node_modules/\r\ndist/"
        agents = "# 기존 Codex 규칙\r\n".encode("utf-8")
        (self.proj / ".gitignore").write_bytes(ignore)
        (self.proj / "AGENTS.md").write_bytes(agents)
        code, out = self.scaffold()
        self.assertEqual(code, 0, out)
        self.assertEqual((self.proj / ".gitignore").read_bytes(), ignore + b"\r\n.herdr-team/state/\r\n")
        after = (self.proj / "AGENTS.md").read_bytes()
        self.assertTrue(after.startswith(agents + b"\r\n<!-- herdr-team -->\r\n"), after[:80])
        self.assertNotIn(b"\n", after.replace(b"\r\n", b""))  # 기존 줄 끝(CRLF)을 따른다

    def test_refuses_undecodable_files_without_changes(self):
        (self.proj / "CLAUDE.md").write_bytes(b"\xff\xfe bad")
        code, out = self.scaffold()
        self.assertEqual((code, out["error"]["code"]), (2, "unreadable_file"), out)
        self.assertIn("CLAUDE.md", out["error"]["message"])
        self.assertFalse(self.team.exists())
        self.assertFalse((self.proj / "AGENTS.md").exists())

    def test_setup_mode_not_reopened_after_done(self):
        self.assertTrue(self.scaffold()[1]["setup_mode"])
        self.assertEqual(self.hteam("setup-done", as_="main")[0], 0)
        code, out = self.scaffold()
        self.assertEqual((code, out["setup_mode"]), (0, False), out)
        self.assertFalse((self.state_dir / "setup-mode").exists())

    def test_shim_rejects_bad_override(self):
        self.scaffold()
        shim = str(self.proj / ".herdr-team/bin/hteam")
        for root in (self.tmp / "nowhere", self.tmp):
            with self.subTest(str(root)):
                env = dict(self.env, HERDR_TEAM_PLUGIN_ROOT=str(root))
                out = subprocess.run([sys.executable, shim, "version"], capture_output=True, text=True, env=env)
                self.assertEqual(out.returncode, 12, out.stderr)
                self.assertEqual(json.loads(out.stdout)["error"]["code"], "plugin_missing")


class ReviewFixDoctorTest(unittest.TestCase):
    """doctor 를 프로세스 안에서 부른다(진짜 codex·horch 를 부르지 않게 바꿔 끼운다)."""

    def doctor(self, run, call=None):
        from hteam import setup

        class FakeHorch:
            bin = "horch"

            def __init__(self, home, project=None):
                pass

            def call(self, *args):
                return call() if call else (0, {"ok": True, "checks": []})

        which = {"git": "/fake/git", "claude": "/fake/claude", "codex": "/fake/codex"}.get
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(setup, "Horch", FakeHorch), \
                mock.patch.object(setup.shutil, "which", which), mock.patch.object(setup.subprocess, "run", run), \
                mock.patch.object(setup.gitio, "is_repo", lambda root: True), \
                mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t1", "HOME": tmp}):
            try:
                return setup.doctor(Path(tmp))
            except HteamError as exc:
                return {"error": exc.code, **exc.data}

    @staticmethod
    def ok_run(argv, **kwargs):
        out = "image_generation  stable  true\n" if argv[1:] == ["features", "list"] else "Logged in\n"
        return subprocess.CompletedProcess(argv, 0, out, "")

    def test_features_failure_is_only_a_warning(self):
        def run(argv, **kwargs):
            if argv[1:] == ["features", "list"]:
                raise subprocess.TimeoutExpired(argv, 30)
            return self.ok_run(argv)

        out = self.doctor(run)
        checks = {c["name"]: c for c in out["checks"]}
        self.assertTrue(out.get("healthy"), out)
        self.assertTrue(checks["codex_login"]["ok"])
        self.assertEqual((checks["codex_image_generation"]["ok"], checks["codex_image_generation"]["level"]),
                         (False, "warning"))

    def test_login_failure_is_an_error(self):
        def run(argv, **kwargs):
            if argv[1:] == ["login", "status"]:
                raise subprocess.TimeoutExpired(argv, 30)
            return self.ok_run(argv)

        out = self.doctor(run)
        self.assertEqual(out.get("error"), "unhealthy", out)
        checks = {c["name"]: c for c in out["checks"]}
        self.assertFalse(checks["codex_login"]["ok"])
        self.assertTrue(checks["codex_image_generation"]["ok"])

    def test_one_horch_entry_when_horch_call_raises(self):
        def call():
            raise HteamError("horch_failed", "boom")

        out = self.doctor(self.ok_run, call)
        horch = [c for c in out["checks"] if c["name"] == "horch"]
        self.assertEqual(len(horch), 1, out["checks"])
        self.assertFalse(horch[0]["ok"])
        self.assertEqual(out.get("error"), "unhealthy")

    def test_missing_codex_wrapper_is_an_error(self):
        from hteam import setup
        checks = {c["name"]: c for c in self.doctor(self.ok_run)["checks"]}
        self.assertEqual((checks["codex_wrapper"]["ok"], checks["codex_wrapper"]["level"]), (True, "error"))
        with mock.patch.object(setup.image, "WRAPPER", Path("/nonexistent/codex-run.sh")):
            out = self.doctor(self.ok_run)
        checks = {c["name"]: c for c in out["checks"]}
        self.assertEqual((out.get("error"), checks["codex_wrapper"]["ok"]), ("unhealthy", False))


class CodexBrowserDoctorTest(TeamCase):
    """doctor 의 codex_browser(경고만): chrome-devtools 정의·npx·샌드박스 우회."""

    def check(self, args, npx="/usr/bin/npx"):
        from hteam import setup
        if args is not None:
            self.init_project(config=BASE_CONFIG.replace('args = ["--disable=hooks"]', f"args = {json.dumps(args)}"),
                              commit=False)
        with mock.patch.object(setup.shutil, "which", lambda name: npx if name == "npx" else None):
            return setup._codex_browser(self.proj)

    def test_cases(self):
        define = ["-c", 'mcp_servers.hteam-browser={command="npx",args=["-y","chrome-devtools-mcp@1.10.1"]}']
        out = self.check(None)  # scaffold 전
        self.assertEqual((out["ok"], out["level"]), (True, "warning"))
        self.assertIn("코드로만", self.check(["--disable=hooks"])["detail"])
        out = self.check(define, npx=None)
        self.assertEqual(out["ok"], False)
        self.assertIn("npx", out["detail"])
        out = self.check(define)
        self.assertEqual(out["ok"], False)
        self.assertIn("승인 정책으로 거부된다", out["detail"])
        out = self.check(define + ["--dangerously-bypass-approvals-and-sandbox"])
        self.assertEqual((out["ok"], out["level"]), (True, "warning"))
        out = self.check(["-c", 'mcp_servers.chrome-devtools={command="npx"}', "--yolo"])  # 다른 이름은 리뷰어의 것이 아니다
        self.assertIn("코드로만", out["detail"])
        out = self.check(["-c", 'mcp_servers.hteam-browser.command="npx"', "--yolo"])  # 점 꼴도 정의로 본다
        self.assertEqual(out["ok"], True)


# --- 두 번째 리뷰(commit-f18dffe) 재현 ---


class ReviewFix2Test(SetupCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()

    def scaffold(self):
        desc = self.tmp / "desc.txt"
        desc.write_text("할 일 앱\n")
        return self.hteam("scaffold", "--description-file", str(desc), as_="main")

    def test_gitignore_leading_space_is_another_pattern(self):
        """git 은 앞 공백을 패턴의 일부로 본다: ` .herdr-team/state/` 는 state 를 빼지 않으므로 덧붙여야 한다."""
        (self.proj / ".gitignore").write_text(" .herdr-team/state/\n")
        code, out = self.scaffold()
        self.assertEqual(code, 0, out)
        self.assertIn(".gitignore", out["created"])
        self.assertEqual((self.proj / ".gitignore").read_text(), " .herdr-team/state/\n.herdr-team/state/\n")
        self.git("check-ignore", "-q", ".herdr-team/state/setup-mode")

    def test_gitignore_trailing_spaces_follow_git(self):
        """끝 공백은 git 이 무시한다(같은 패턴). 백슬래시로 막은 끝 공백은 다른 패턴이다."""
        for text, appended in ((".herdr-team/state/   \n", False), (".herdr-team/state/\\ \n", True)):
            with self.subTest(text):
                (self.proj / ".gitignore").write_text(text)
                code, out = self.scaffold()
                self.assertEqual((code, ".gitignore" in out["created"]), (0, appended), out)
                self.git("check-ignore", "-q", ".herdr-team/state/plugin-root")

    def test_watch_reports_bad_run_file(self):
        proc = self.hteam_bg("watch", as_="main", env={"HTEAM_ORPHAN_CHECK": "0.1"})
        deadline = time.monotonic() + 30
        while not (self.state_dir / "watch.pid").exists():
            self.assertIsNone(proc.poll(), "watch 가 일찍 끝났다")
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        (self.state_dir / "run.json").write_text("[]")
        code, out = self.finish(proc, timeout=30)
        self.assertEqual((code, out["error"]["code"]), (1, "bad_run_file"), out)

    def test_init_skill_setup_mode_guidance(self):
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        for sentence in ("출력의 `setup_mode` 가 false 면 이 프로젝트는 이미 세팅을 마쳤다(`setup-done`).",
                         "`.herdr-team/state/setup-done` 을 지우고 scaffold 를 다시 실행한다.",
                         "그대로 두면 4단계에서 제품 파일(`.mcp.json` 등)을 고치는 것을 훅이 막는다."):
            self.assertIn(sentence, init)


if __name__ == "__main__":
    unittest.main()


from tests.helpers import DRIVE_ARGV  # noqa: E402  (6단계 관제 실행 시험, 설계 9.3)


class UpDriveTest(SetupCase):
    """hteam up 이 관제(hteam drive)를 띄운다(설계 9.3, 6단계). 관제 생존은 drive.pid·heartbeat 로 본다(8.2)."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()

    def kill_drive(self):
        (self.drive_dir / "drive.pid").unlink()

    def bind(self, nonce: str, terminal: str | None = None) -> None:
        """띄운 관제가 Run 에 묶인 것처럼 run.json 을 쓰고 생존 파일을 남긴다(관제 시작 순서 4, 설계 8.2)."""
        run = self.run_json()
        run.update(run_id=self.run_id, bound_nonce=nonce, bound_at="2026-11-10T00:00:00Z")
        if terminal:
            run.update(drive_terminal=terminal, drive_argv=DRIVE_ARGV)
        run.pop("launched_at", None)
        (self.state_dir / "run.json").write_text(json.dumps(run))
        self.write_drive_pid()
        self.write_heartbeat()

    def test_running_drive_is_left_alone(self):
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out["launched"], out["terminal"]), (0, "running", False, DRIVE), out)
        code, out = self.hteam("up", "--wait-run", "1", as_="main")
        self.assertEqual((code, out["status"], out["run_id"]), (0, "running", self.run_id), out)
        self.assertEqual(self.run_calls(), [])

    def test_hung_drive_is_not_relaunched(self):
        self.write_heartbeat(age_s=200)
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out["launched"]), (0, "hung", False), out)
        self.assertEqual(out["message"], "관제 프로세스가 살아 있지만 응답이 없다. 관제 탭을 확인한다")
        self.assertEqual(self.run_calls(), [])

    def test_up_launches_drive_then_starting_then_running(self):
        import hashlib
        self.kill_drive()
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out["launched"]), (0, "launched", True), out)
        run = self.run_json()
        nonce = run["pending_launch"]["nonce"]
        self.assertNotEqual(nonce, NONCE)
        self.assertNotIn("force", run["pending_launch"])
        term = self.hc_state()["terminals"][out["terminal"]]
        root = str(Project(self.proj).root)
        tab = "tb" + hashlib.sha1(f"herdr-team\n{root}\nspA".encode("utf-8")).hexdigest()[:32]
        self.assertEqual(term["argv"], ["env", "HTEAM_ROLE=drive", f"HTEAM_LAUNCH={nonce}", sys.executable,
                                        str(ROOT / "bin" / "hteam"), "--root", root, "drive"])
        self.assertEqual(set(term["flags"]), {"--bg", "--no-parent", "--no-notify", "--keep"})
        self.assertEqual(term["labels"], {"herdr.space": "spA", "herdr.tab": tab, "hteam.role": "drive"})
        self.assertRegex(term["name"], r"^hteam-drive-[0-9a-f]{6}$")
        self.assertEqual((run["drive_terminal"], run["drive_argv"], run["team_tab"], run["team_space"]),
                         (out["terminal"], term["argv"], tab, "spA"))
        self.assertEqual((out["team_tab"], out["terminal"]), (tab, run["drive_terminal"]))
        self.assertIn("launched_at", run)
        self.assertFalse([c for c in self.herdr_calls() if c[:2] == ["do", "tab.rename"]])  # 탭 이름은 관제가 붙인다(8.2 의 5)
        code, again = self.hteam("up", as_="main")
        self.assertEqual((code, again["status"], again["launched"]), (0, "starting", False), again)
        self.assertEqual(again["message"], "관제가 아직 시작 중이다(180초 안에 다시 띄우지 않는다). hteam status 로 확인한다")
        code, again = self.hteam("up", "--wait-run", "0.3", as_="main")
        self.assertEqual((code, again["error"]["code"]), (4, "timeout"), again)
        self.assertEqual(again["error"]["message"], "관제가 0.3초 안에 Run 을 만들지 않았다. 관제 탭(herdr-team 관제)을 확인한다")
        self.bind(nonce)
        code, again = self.hteam("up", "--wait-run", "1", as_="main")
        self.assertEqual((code, again["status"], again["run_id"]), (0, "running", self.run_id), again)
        self.assertEqual(len(self.run_calls()), 1)

    def test_bound_drive_that_died_is_relaunched_at_once(self):
        # Run 에 묶인 뒤 죽은 관제는 시작 유예 없이 다시 띄운다(띄운 지 180초 안이어도). 새로 띄운 관제가 아직 묶이지
        # 않았으면 180초 동안 starting
        run = self.run_json()
        run["pending_launch"]["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (self.state_dir / "run.json").write_text(json.dumps(run))
        self.kill_drive()
        self.assertEqual(self.hteam("up", as_="main")[1]["status"], "launched")
        self.assertEqual(self.hteam("up", as_="main")[1]["status"], "starting")
        self.assertEqual(len(self.run_calls()), 1)

    def test_old_config_refuses_up(self):
        (self.team / "config.toml").write_text(BASE_CONFIG + '\n[coordinator]\nmodel = "opus"\n', encoding="utf-8")
        self.kill_drive()
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["error"]["code"], out["errors"]), (2, "bad_config", [config.OLD_CONFIG_MESSAGE]), out)
        self.assertEqual(self.run_calls(), [])

    def test_up_refuses_non_main_callers_and_bad_run_file(self):
        self.kill_drive()
        before = (self.state_dir / "run.json").read_text()
        self.add_terminal("t500", argv=["codex"], labels={"horch.dispatch": "dsp-x"})
        for kwargs in ({"as_": "drive"}, {"as_": None, "terminal": "t500"}, {"as_": None, "terminal": DRIVE}):
            with self.subTest(kwargs=kwargs):
                code, out = self.hteam("up", **kwargs)
                self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertEqual((self.state_dir / "run.json").read_text(), before)
        for text in ("{broken", "[]"):
            with self.subTest(text=text):
                (self.state_dir / "run.json").write_text(text)
                code, out = self.hteam("up", as_="main")
                self.assertEqual((code, out["error"]["code"]), (1, "bad_run_file"), out)
                self.assertEqual((self.state_dir / "run.json").read_text(), text)
        self.assertEqual(self.run_calls(), [])

    def test_launch_failure_restores_run_json(self):
        self.kill_drive()
        before = self.run_json()
        self.fail_hc("run", "server_down")
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"), out)
        self.assertEqual(self.run_json(), before)
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)

    def test_launch_created_despite_error_or_garbled_response_is_recorded(self):
        self.kill_drive()
        with self._hc_locked() as hc:
            hc["fail"]["run"] = {"kind": "server_down", "code": 1, "create": True}
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"], out.get("recovered")), (0, "launched", True), out)
        run = self.run_json()
        term = self.hc_state()["terminals"][out["terminal"]]
        self.assertEqual((run["drive_terminal"], run["drive_argv"]), (out["terminal"], term["argv"]))
        self.assertEqual(term["argv"][2], f"HTEAM_LAUNCH={run['pending_launch']['nonce']}")
        with self._hc_locked() as hc:
            hc["fail"].clear()
        self.set_run_old_launch()
        code, out = self.hteam("up", as_="main", env=self.wrap_env(WRAP_MODE="created_garbled"))
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        run = self.run_json()
        self.assertEqual(self.hc_state()["terminals"][out["terminal"]]["argv"], run["drive_argv"])

    def set_run_old_launch(self) -> None:
        """앞서 띄운 관제가 시작 유예(180초)를 넘기고도 묶이지 않고 죽었다."""
        run = self.run_json()
        run["launched_at"] = "2026-01-01T00:00:00Z"
        run["pending_launch"]["at"] = "2026-01-01T00:00:00Z"
        (self.state_dir / "run.json").write_text(json.dumps(run))

    def test_uncertain_launch_keeps_pending_nonce(self):
        self.kill_drive()
        before = self.run_json()
        terms = set(self.hc_state()["terminals"])
        code, out = self.hteam("up", as_="main", env=self.wrap_env(WRAP_MODE="lost"))
        self.assertEqual((code, out["error"]["code"]), (1, "launch_uncertain"), out)
        self.assertRegex(out["name"], r"^hteam-drive-[0-9a-f]{6}$")
        run = self.run_json()
        self.assertNotEqual(run["pending_launch"]["nonce"], before["pending_launch"]["nonce"])
        self.assertNotIn("drive_terminal", run)
        self.assertEqual((run["run_id"], run["bound_nonce"]), (before["run_id"], before["bound_nonce"]))
        code, again = self.hteam("up", as_="main")
        self.assertEqual((code, again["status"], again["launched"]), (0, "starting", False), again)
        self.assertEqual(set(self.hc_state()["terminals"]), terms)

    def test_uncertain_launch_waits_for_the_drive_to_bind(self):
        self.kill_drive()
        old = self.run_json()["pending_launch"]["nonce"]
        proc = self.hteam_bg("up", "--wait-run", "20", as_="main", env=self.wrap_env(WRAP_MODE="lost"))
        deadline = time.monotonic() + 30
        while self.run_json()["pending_launch"]["nonce"] == old:
            self.assertIsNone(proc.poll(), "up 이 pending_launch 를 쓰기 전에 끝났다")
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.02)
        self.add_terminal("t300", argv=DRIVE_ARGV, labels={"herdr.space": "spA", "herdr.tab": "tbTeam"})
        self.bind(self.run_json()["pending_launch"]["nonce"], terminal="t300")
        code, out = self.finish(proc)
        self.assertEqual((code, out.get("status"), out.get("terminal"), out.get("run_id"), out.get("recovered")),
                         (0, "launched", "t300", self.run_id, True), out)
        self.assertEqual((self.run_json()["drive_terminal"], self.run_json()["drive_argv"]), ("t300", DRIVE_ARGV))

    def test_concurrent_up_is_raced(self):
        self.kill_drive()
        gate, env = self.pause_env("up_before_pending", "first")
        first = self.hteam_bg("up", as_="main", env=env)
        self.wait_reached(gate, first)
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        gate.touch()
        code, raced = self.finish(first)
        self.assertEqual((code, raced["error"]["code"]), (3, "launch_raced"), raced)
        self.assertEqual(len(self.run_calls()), 1)
        self.assertEqual(self.run_json()["drive_terminal"], out["terminal"])
