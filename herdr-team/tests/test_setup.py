"""doctor·scaffold·shim·up·bind·setup-done(설계 9.1–9.3)와 스킬·템플릿."""
import json
import os
import shutil
import subprocess
import sys
import unittest

from tests.helpers import COORD, HORCH_FAKES, MAIN, ROOT, TeamCase
from hteam import config
from hteam.paths import Project


class DoctorTest(TeamCase):
    def test_healthy_with_fakes(self):
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)
        checks = {c["name"]: c for c in out["checks"]}
        for name in ("python", "git", "horch", "horch_doctor", "herdr_terminal", "claude", "codex", "codex_login"):
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
        for rel in (".herdr-team/config.toml", ".herdr-team/coordinator.md", ".herdr-team/roles/planner.md",
                    ".herdr-team/roles/developer.md", ".herdr-team/roles/tester.md", ".herdr-team/bin/hteam",
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
        (self.team / "coordinator.md").write_text("바꿈\n")
        code, out = self.scaffold()
        self.assertEqual((code, out["created"]), (0, []), out)
        self.assertEqual((self.team / "coordinator.md").read_text(), "바꿈\n")
        self.assertEqual((self.proj / "CLAUDE.md").read_text().count("<!-- herdr-team -->"), 1)
        self.assertEqual((self.proj / ".gitignore").read_text().count(".herdr-team/state/"), 1)

    def test_shim_finds_plugin(self):
        self.scaffold()
        shim = str(self.proj / ".herdr-team/bin/hteam")
        env = dict(self.env, HERDR_TEAM_PLUGIN_ROOT=str(ROOT))
        out = subprocess.run([sys.executable, shim, "version"], capture_output=True, text=True, env=env)
        self.assertEqual(json.loads(out.stdout)["version"], "0.1.0")
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


class UpBindTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.add_terminal(MAIN, argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain"}, status="idle")

    def run_json(self):
        return json.loads((self.state_dir / "run.json").read_text())

    def test_up_launches_coordinator_then_bind(self):
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        run = self.run_json()
        nonce = run["pending_launch"]["nonce"]
        term = self.hc_state()["terminals"][out["terminal"]]
        self.assertEqual(term["argv"][:4], ["env", "HTEAM_ROLE=coordinator", f"HTEAM_LAUNCH={nonce}", "claude"])
        self.assertEqual(term["argv"][-2:], ["--", "`.herdr-team/bin/hteam bind` 를 실행하고 `.herdr-team/coordinator.md` 를 따른다."])
        self.assertIn("--keep", term["flags"])
        self.assertEqual(term["labels"]["hteam.role"], "coordinator")
        self.assertEqual(term["labels"]["herdr.tab"], run["team_tab"])
        self.assertTrue(run["team_tab"].startswith("tb") and len(run["team_tab"]) == 34)
        self.assertEqual((run["coordinator_terminal"], run["coordinator_argv"]), (out["terminal"], term["argv"]))
        self.assertIn(["do", "tab.rename", "--id", run["team_tab"], "--name", "팀"], self.herdr_calls())
        code, again = self.hteam("up", as_="main")
        self.assertEqual((code, again["status"], again["launched"]), (0, "starting", False))
        code, again = self.hteam("up", "--wait-run", "0.3", as_="main")
        self.assertEqual((code, again["error"]["code"]), (4, "timeout"))
        env = {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": nonce}
        code, bound = self.hteam("bind", as_=None, terminal=out["terminal"], env=env)
        self.assertEqual((code, bound["mode"], bound["owner_tab"]), (0, "create", run["team_tab"]), bound)
        self.assertIn("--home", bound["horch"])
        code, again = self.hteam("up", "--wait-run", "1", as_="main")
        self.assertEqual((code, again["status"], again["run_id"]), (0, "alive", bound["run_id"]))

    def test_bind_needs_nonce_and_takes_over_dead_owner(self):
        run_id = self.setup_run()
        code, out = self.hteam("bind", as_=None, terminal="t300", env={"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": "x"})
        self.assertEqual((code, out["error"]["code"]), (5, "not_coordinator"))
        self.add_terminal("t300", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbTeam"})
        code, out = self.hteam("bind", terminal="t300")
        self.assertEqual((code, out["error"]["code"]), (3, "horch_owner_alive"), out)
        self.update_terminal(COORD, state="finished")
        code, out = self.hteam("bind", terminal="t300")
        self.assertEqual((code, out["mode"], out["run_id"], out["previous_owner"]), (0, "use", run_id, COORD), out)
        self.assertEqual(self.run_json()["coordinator_terminal"], "t300")

    def test_up_relaunches_dead_coordinator_and_needs_terminal(self):
        self.setup_run()
        self.update_terminal(COORD, state="finished")
        code, out = self.hteam("up", as_=None)
        self.assertEqual((code, out["error"]["code"]), (5, "no_terminal"))
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        self.assertNotEqual(self.run_json()["pending_launch"]["nonce"], "nonce-test")


class SkillTemplateTest(unittest.TestCase):
    def test_skills_and_templates(self):
        for name in ("init", "up"):
            text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"name: {name}", text)
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        for needle in ("doctor", "scaffold --description-file", "up --wait-run 180", "watch", "setup-done",
                       "chore: herdr-team 세팅", "bypassPermissions"):
            self.assertIn(needle, init)
        coord = (ROOT / "templates/coordinator.md").read_text(encoding="utf-8")
        for needle in ("hteam bind", "hteam wait", "--ack <delivery>", "review-finish", "notify --type question",
                       "applied", "start-ready", "plan apply", "--force-round", "review T --retry"):
            self.assertIn(needle, coord)


class UnverifiableCoordinatorTest(TeamCase):
    def test_unverifiable_is_kept_then_force_and_bind_takes_over(self):
        self.init_project()
        run_id = self.setup_run()
        with self._hc_locked() as hc:
            del hc["terminals"][COORD]  # hc 가 터미널을 모른다: 끝났다고 단정할 수 없다(horch 와 같은 규칙)
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["error"]["code"]), (3, "coordinator_unverifiable"), out)
        run = json.loads((self.state_dir / "run.json").read_text())
        self.assertEqual((run["pending_launch"]["nonce"], run["coordinator_terminal"]), ("nonce-test", COORD))
        code, out = self.hteam("up", "--force", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        run = json.loads((self.state_dir / "run.json").read_text())
        self.assertTrue(run["pending_launch"]["force"])
        env = {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": run["pending_launch"]["nonce"]}
        code, bound = self.hteam("bind", as_=None, terminal=out["terminal"], env=env)
        self.assertEqual((code, bound["mode"], bound["run_id"]), (0, "use", run_id), bound)

    def test_force_is_carried_until_bind(self):
        self.init_project()
        run_id = self.setup_run()
        with self._hc_locked() as hc:
            del hc["terminals"][COORD]
        _, first = self.hteam("up", "--force", as_="main")
        self.update_terminal(first["terminal"], state="finished")  # bind 전에 끝났다
        code, out = self.hteam("up", as_="main")  # 이번 판정은 exited 지만 이전 소유자는 여전히 확인할 수 없다
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        run = json.loads((self.state_dir / "run.json").read_text())
        self.assertTrue(run["pending_launch"]["force"])
        env = {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": run["pending_launch"]["nonce"]}
        code, bound = self.hteam("bind", as_=None, terminal=out["terminal"], env=env)
        self.assertEqual((code, bound["mode"], bound["run_id"]), (0, "use", run_id), bound)
        self.assertEqual(self.hteam("up", as_="main")[1]["status"], "alive")
        self.assertFalse(self.hteam("up", as_="main")[1]["launched"])


# --- 아래는 계획 리뷰·앞 태스크 계약(코디네이터 생존·인계 승인·라벨·팀 탭·템플릿)을 더 좁게 확인한다 ---


class CoordinatorContractTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()

    def run_json(self):
        return json.loads((self.state_dir / "run.json").read_text())

    def test_every_unverifiable_form_keeps_records_and_nonce(self):
        """hc get 실패(not_found 포함)와 argv 없음은 모두 확인 불가다(horch liveness 와 같다). 기록·nonce 를 그대로 두고 exit 3."""
        before = self.run_json()
        cases = {
            "not_found": lambda hc: hc["terminals"].pop(COORD),
            "argv_missing": lambda hc: hc["terminals"][COORD].update(argv=None),
            "get_failed": lambda hc: hc["fail"].update({"get": {"kind": "server_down", "code": 1}}),
            "not_live": lambda hc: hc["terminals"][COORD].update(state="starting"),
        }
        for name, breaks in cases.items():
            with self.subTest(name):
                saved = self.hc_state()
                with self._hc_locked() as hc:
                    breaks(hc)
                code, out = self.hteam("up", as_="main")
                self.assertEqual((code, out["error"]["code"]), (3, "coordinator_unverifiable"), out)
                self.assertEqual(self.run_json(), before)
                self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])
                self.set_hc_state(saved)

    def test_alive_coordinator_is_never_relaunched_even_with_force(self):
        for args in ((), ("--force",)):
            code, out = self.hteam("up", *args, as_="main")
            self.assertEqual((code, out["status"], out["launched"], out["terminal"]), (0, "alive", False, COORD), out)
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["run"]])
        self.assertNotIn("force", self.run_json()["pending_launch"])

    def test_bind_without_force_refuses_unverifiable_owner(self):
        """pending_launch.force 가 없으면 bind 는 run-use 에 --force 를 붙이지 않는다."""
        with self._hc_locked() as hc:
            del hc["terminals"][COORD]
        self.add_terminal("t300", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbTeam"})
        code, out = self.hteam("bind", terminal="t300")
        self.assertEqual((code, out["error"]["code"]), (3, "horch_owner_unverifiable"), out)
        self.assertIn("up --force", out["error"]["hint"])
        self.assertEqual(self.run_json()["coordinator_terminal"], COORD)

    def test_force_is_not_reused_after_successful_bind(self):
        """bind 가 성공하면 인계 승인은 끝난다: 같은 nonce 의 다음 bind 는 --force 없이 run-use 한다."""
        with self._hc_locked() as hc:
            del hc["terminals"][COORD]
        code, first = self.hteam("up", "--force", as_="main")
        self.assertEqual(code, 0, first)
        nonce = self.run_json()["pending_launch"]["nonce"]
        env = {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": nonce}
        code, bound = self.hteam("bind", as_=None, terminal=first["terminal"], env=env)
        self.assertEqual((code, bound["mode"]), (0, "use"), bound)
        with self._hc_locked() as hc:
            del hc["terminals"][first["terminal"]]  # 새 소유자도 확인할 수 없게 된다
        self.add_terminal("t300", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbTeam"})
        code, out = self.hteam("bind", as_=None, terminal="t300", env=env)
        self.assertEqual((code, out["error"]["code"]), (3, "horch_owner_unverifiable"), out)
        code, out = self.hteam("up", as_="main")  # 다음 up 도 인계 승인을 이어 받지 않는다
        self.assertEqual((code, out["error"]["code"]), (3, "coordinator_unverifiable"), out)

    def test_relaunch_after_exit_is_not_forced(self):
        self.update_terminal(COORD, state="finished")
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)
        self.assertFalse(self.run_json()["pending_launch"]["force"])
        self.update_terminal(out["terminal"], reason="stopped_by_restart")  # lost 도 확인된 끝이다(띄운 지 180초 안이어도)
        code, again = self.hteam("up", as_="main")
        self.assertEqual((code, again["status"]), (0, "launched"), again)
        self.assertNotEqual(again["terminal"], out["terminal"])
        self.assertFalse(self.run_json()["pending_launch"]["force"])

    def test_launch_failure_restores_run_json(self):
        """hc run 이 실패하면 pending_launch 를 되돌린다(새 코디네이터가 없는데 starting 으로 보이지 않게)."""
        self.update_terminal(COORD, state="finished")
        before = self.run_json()
        self.fail_hc("run", "server_down")
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"), out)
        self.assertEqual(self.run_json(), before)
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("up", as_="main")
        self.assertEqual((code, out["status"]), (0, "launched"), out)

    def test_team_tab_label_and_hash(self):
        import hashlib
        from hteam import setup
        self.update_terminal(COORD, state="finished")
        code, out = self.hteam("up", as_="main")
        self.assertEqual(code, 0, out)
        run = self.run_json()
        root = str(Project(self.proj).root)
        expected = "tb" + hashlib.sha1(f"herdr-team\n{root}\nspA".encode("utf-8")).hexdigest()[:32]
        self.assertEqual((run["team_tab"], setup.team_tab(Project(self.proj).root, "spA")), (expected, expected))
        term = self.hc_state()["terminals"][out["terminal"]]
        self.assertEqual(term["labels"], {"herdr.space": "spA", "herdr.tab": expected, "hteam.role": "coordinator"})
        self.assertEqual(set(term["flags"]), {"--bg", "--no-parent", "--no-notify", "--keep"})
        # 띄운 코디네이터 터미널은 bind 전에도 메인 명령(tell)을 거부당한다(라벨 hteam.role)
        self.add_terminal("t400", argv=["sh"], labels={"hteam.role": "coordinator"})
        code, out = self.hteam("tell", "안녕", as_=None, terminal="t400")
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)


class TemplateContractTest(unittest.TestCase):
    def test_coordinator_doc_contract(self):
        coord = (ROOT / "templates/coordinator.md").read_text(encoding="utf-8")
        for needle in ("horch check", "[horch] 새 메시지가 있다", "데이터", ".herdr-team/bin/hteam", "`kind: main`",
                       "not_main", "stale", "next", "제목"):
            self.assertIn(needle, coord)

    def test_phase1_roles_only(self):
        import tomllib
        raw = tomllib.loads((ROOT / "templates/config.toml").read_text(encoding="utf-8"))
        self.assertEqual(set(raw["roles"]), {"planner", "developer", "tester"})
        self.assertEqual(raw["user_approval_roles"], [])
        self.assertEqual(config.validate(raw), [])
        self.assertEqual(sorted(p.name for p in (ROOT / "templates/roles").iterdir()),
                         ["developer.md", "planner.md", "tester.md"])

    def test_no_personal_paths_or_trust_all(self):
        import re
        private = re.compile(r"/[U]sers/|/private/[t]mp|~[/]Workspace|/[h]ome/")
        files = [*(ROOT / "templates").rglob("*"), *(ROOT / "skills").rglob("*")]
        for path in (f for f in files if f.is_file()):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(private.search(text), path)
        init = (ROOT / "skills/init/SKILL.md").read_text(encoding="utf-8")
        for needle in ("위험", "승인", "전역"):
            self.assertIn(needle, init)


if __name__ == "__main__":
    unittest.main()
