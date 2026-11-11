"""설정 검사(설계 4.2)와 모델·에이전트 결정(4.1)."""
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path as FsPath
from unittest import mock

from tests.helpers import BASE_CONFIG, CREW_CONFIG, ROOT, TeamCase
from hteam import config, herdr, procs
from hteam.errors import HteamError
from hteam.paths import Project

FULL = BASE_CONFIG + """
[image]
codex_model = "img-model"

[roles.director]
title = "디자인 디렉터"
owns = ["docs/design/**"]

[roles.designer]
title = "디자인"
owns = ["docs/design/screens/**"]
"""


class ConfigTest(TeamCase):
    def load(self, text: str):
        self.init_project(config=text, commit=False)
        return config.load(Project(self.proj))

    def errors(self, text: str) -> list[str]:
        with self.assertRaises(HteamError) as ctx:
            self.load(text)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_config", 2))
        return ctx.exception.data["errors"]

    def test_base_config_loads_with_defaults(self):
        cfg = self.load(BASE_CONFIG)
        self.assertEqual((cfg.max_parallel, cfg.max_rounds), (4, 3))
        self.assertEqual(cfg.args("codex"), ["--disable=hooks"])
        self.assertEqual(cfg.args("claude"), [])
        self.assertEqual(cfg.owns("developer"), ["src/**"])
        self.assertEqual(cfg.role_title("developer"), "개발")
        self.assertEqual((cfg.crew, cfg.overflow, cfg.drive, cfg.auto_up), ({}, True, {}, True))
        self.assertFalse(hasattr(cfg, "coordinator"))

    def test_missing_and_broken_file(self):
        self.init_project(commit=False)
        (self.proj / ".herdr-team" / "config.toml").write_text("max_parallel = [", encoding="utf-8")
        with self.assertRaises(HteamError) as ctx:
            config.load(Project(self.proj))
        self.assertEqual(ctx.exception.exit_code, 2)
        (self.proj / ".herdr-team" / "config.toml").unlink()
        with self.assertRaises(HteamError) as ctx:
            config.load(Project(self.proj))
        self.assertEqual(ctx.exception.code, "no_config")

    def test_rule_violations(self):
        bad = BASE_CONFIG.replace("max_parallel = 4", "max_parallel = 0").replace("max_rounds = 3", "max_rounds = 0")
        bad = bad.replace('worker = "claude"', 'worker = "gpt"').replace('owns = ["src/**"]', "owns = []")
        bad = bad.replace("user_approval_roles = []", 'user_approval_roles = ["designer"]')
        bad += '\n[agents.gemini]\nargs = []\n'
        errs = "\n".join(self.errors(bad))
        for needle in ("max_parallel", "max_rounds", "defaults.worker", "roles.developer.owns",
                       "user_approval_roles 의 designer", "agents.gemini"):
            self.assertIn(needle, errs)

    def test_role_owns_rules(self):
        errs = "\n".join(self.errors(BASE_CONFIG.replace('"docs/qa/**"', '"docs/qa/"')))
        self.assertIn("roles.tester.owns 'docs/qa/'", errs)

    def test_director_designer_claude_only(self):
        errs = self.errors(FULL.replace('title = "디자인"', 'title = "디자인"\nworker = "codex"'))
        self.assertTrue(any("roles.designer" in e and "claude" in e for e in errs), errs)
        errs = self.errors(FULL.replace('[defaults]\nworker = "claude"', '[defaults]\nworker = "codex"'))
        self.assertEqual(len([e for e in errs if "Claude Design" in e]), 2, errs)

    def test_agents_args_must_be_strings(self):
        errs = self.errors(BASE_CONFIG.replace('args = ["--disable=hooks"]', "args = [1]"))
        self.assertIn("agents.codex.args 는 문자열 목록이다", errs)

    def test_model_and_effort_must_be_nonempty_strings(self):
        # 숫자 등을 받으면 start 가 launch_failed 를 쓴 뒤 Popen 에서 TypeError 로 죽고(복구도 같은 값을 다시 쓴다)
        # up 은 pending_launch 를 쓴 뒤 죽는다. 설정을 읽을 때 막는다
        cases = {"defaults.claude_effort": BASE_CONFIG.replace('claude_effort = "xhigh"', "claude_effort = 3"),
                 "defaults.codex_model": BASE_CONFIG.replace('codex_model = "gpt-6.1-sol"', 'codex_model = ""'),
                 "roles.developer.claude_model": BASE_CONFIG.replace('claude_model = "opus"', "claude_model = 1"),
                 "image.codex_effort": BASE_CONFIG + "\n[image]\ncodex_effort = 2\n"}
        for key, text in cases.items():
            self.assertEqual(self.errors(text), [f"{key} 는 비지 않은 문자열이다"], key)

    def test_bad_effort_refuses_start_before_any_write(self):
        self.init_project(commit=False)
        self.setup_run()
        self.write_spec("T-001")
        from hteam import state
        state.create(Project(self.proj), "T-001", "developer")
        (self.team / "config.toml").write_text(BASE_CONFIG.replace('claude_effort = "xhigh"', "claude_effort = 3"))
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_config"), out)
        self.assertEqual(self.task_state("T-001")["status"], "pending")

    def test_unreadable_config_is_bad_config(self):
        self.init_project(commit=False)
        path = self.proj / ".herdr-team" / "config.toml"
        path.unlink()
        path.mkdir()  # 디렉터리·읽을 수 없는 파일은 OSError 다(internal 이 아니다)
        with self.assertRaises(HteamError) as ctx:
            config.load(Project(self.proj))
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_config", 2))
        path.rmdir()
        path.write_text(BASE_CONFIG, encoding="utf-8")
        path.chmod(0)
        if os.access(path, os.R_OK):
            self.skipTest("root 는 권한 없이도 읽는다")
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "bad_config"), out)

    def test_drive_and_overflow_switches(self):
        # 설계 4.1·4.2(6단계): [drive] auto_up·[overflow] enabled 는 키가 없으면 켜진다. 있으면 불리언이다
        cfg = self.load(BASE_CONFIG)
        self.assertEqual((cfg.auto_up, cfg.overflow), (True, True))
        off = self.load(BASE_CONFIG + "\n[drive]\nauto_up = false\n\n[overflow]\nenabled = false\n")
        self.assertEqual((off.auto_up, off.overflow, off.drive), (False, False, {"auto_up": False}))
        errs = self.errors(BASE_CONFIG + '\n[drive]\nauto_up = "yes"\n\n[overflow]\nenabled = 1\n')
        self.assertEqual(sorted(errs), sorted(["drive.auto_up 은 true·false 다", "overflow.enabled 은 true·false 다"]))
        errs = self.errors('drive = 1\noverflow = "x"\n' + BASE_CONFIG)
        self.assertIn("[drive] 는 표여야 한다", errs)
        self.assertIn("[overflow] 는 표여야 한다", errs)

    def test_old_coordinator_table_is_bad_config(self):
        # 설계 4.2(6단계): 0.3.0 의 [coordinator] 가 남은 설정은 오류로 알리고 다시 세팅하라고 한다(이전 명령은 없다)
        self.assertEqual(config.OLD_CONFIG_MESSAGE,
                         "config.toml 에 [coordinator] 가 있다. 0.4.0 은 코디네이터 대신 관제(hteam drive)를 쓴다. "
                         "[coordinator] 를 지우고 템플릿의 [drive]·[overflow]·[crew.*] 를 옮긴다. 또는 config.toml 을 "
                         "지운 뒤 다시 세팅한다(/herdr-team:init. 있는 파일은 덮어쓰지 않으므로 config.toml 만 새로 "
                         "생긴다)")
        for extra in ('\n[coordinator]\nmodel = "opus"\neffort = "xhigh"\nauto_up = true\n', "\n[coordinator]\n"):
            with self.subTest(extra=extra):
                self.assertEqual(self.errors(BASE_CONFIG + extra), [config.OLD_CONFIG_MESSAGE])

    def test_image_choice(self):
        cfg = self.load(FULL)
        self.assertEqual(cfg.image_choice(), ("img-model", "high"))
        cfg = self.load(BASE_CONFIG)
        self.assertEqual(cfg.image_choice(), ("gpt-6.1-sol", "high"))


class ProbeTimeoutTest(TeamCase):
    """자동 부활이 쓰는 시간 제한(설계 9.5): herdr.probe 의 timeout, hc 출력이 UTF-8 이 아닐 때, procs 의 timeout."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.add_terminal("t100", argv=["claude"])

    def test_probe_timeout(self):
        self.assertEqual(herdr.probe("t100", ["claude"], timeout=3), "live")
        with self._hc_locked() as st:
            st["delay"] = {"get": 4}
        start = time.monotonic()
        self.assertEqual(herdr.probe("t100", ["claude"], timeout=1), "unverifiable")
        self.assertLess(time.monotonic() - start, 3)

    def test_non_utf8_hc_output_is_unverifiable(self):
        fake = FsPath(tempfile.mkdtemp(prefix="hteam-hc-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(fake, True))
        script = fake / "hc"
        script.write_bytes(b"#!/bin/sh\nprintf '{\"state\": \"live\", \"x\": \"\\377\"}\\n'\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        with mock.patch.dict(os.environ, {"PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}):
            self.assertEqual(herdr.probe("t100", None), "unverifiable")
            with self.assertRaises(HteamError) as ctx:
                herdr.get("t100")
        self.assertEqual((ctx.exception.code, ctx.exception.data), ("hc_failed", {"kind": "bad_output"}))

    def test_procs_timeout_is_passed_to_ps(self):
        seen = []
        real = procs.subprocess.run

        def run(argv, *args, **kw):
            seen.append(kw.get("timeout"))
            return real(argv, *args, **kw)
        me = procs.me()
        with mock.patch.object(procs.subprocess, "run", side_effect=run):
            self.assertTrue(procs.record_alive(me, timeout=1.5))
            self.assertIsNotNone(procs.start_time(os.getpid(), timeout=2.5))
            self.assertTrue(procs.alive(os.getpid(), me["started"]))
        self.assertEqual(seen, [1.5, 2.5, 5])


class ResolveTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project(config=FULL, commit=False)
        self.cfg = config.load(Project(self.proj))

    def test_precedence_per_value(self):
        c = config.resolve(self.cfg, "developer")
        self.assertEqual((c.worker, c.model, c.effort), ("claude", "opus", "xhigh"))
        self.assertEqual((c.reviewer, c.review_model, c.review_effort), ("codex", "gpt-6.1-sol", "high"))
        c = config.resolve(self.cfg, "developer", {"claude_model": "haiku"})
        self.assertEqual((c.model, c.effort), ("haiku", "xhigh"))
        c = config.resolve(self.cfg, "developer", {"claude_model": "haiku"}, {"model": "cli-m", "effort": "low"})
        self.assertEqual((c.model, c.effort), ("cli-m", "low"))
        self.assertEqual(c.review_model, "gpt-6.1-sol")  # CLI 는 작업 모델에만

    def test_worker_switch_flips_reviewer(self):
        c = config.resolve(self.cfg, "tester", {"worker": "codex", "codex_model": "fm"})
        self.assertEqual((c.worker, c.model, c.reviewer, c.review_model), ("codex", "fm", "claude", "sonnet"))
        c = config.resolve(self.cfg, "tester", {"worker": "codex"}, {"worker": "claude"})
        self.assertEqual(c.worker, "claude")

    def test_claude_only_roles_refuse_override(self):
        for front, cli in (({"worker": "codex"}, {}), ({}, {"worker": "codex"})):
            with self.assertRaises(HteamError) as ctx:
                config.resolve(self.cfg, "designer", front, cli)
            self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("claude_only_role", 2))

    def test_bad_worker_and_unknown_role(self):
        with self.assertRaises(HteamError) as ctx:
            config.resolve(self.cfg, "developer", {}, {"worker": "gpt"})
        self.assertEqual(ctx.exception.code, "bad_worker")
        with self.assertRaises(HteamError) as ctx:
            config.resolve(self.cfg, "nope")
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("unknown_role", 2))
        self.assertEqual(config.other("claude"), "codex")


class CrewConfigTest(TeamCase):
    """고정 에이전트 설정 `[crew.<이름>]`(설계 4.1·4.2, 6단계)."""

    def load(self, text: str):
        self.init_project(config=text, commit=False)
        return config.load(Project(self.proj))

    def errors(self, text: str) -> list[str]:
        with self.assertRaises(HteamError) as ctx:
            self.load(text)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_config", 2))
        return ctx.exception.data["errors"]

    def test_crew_values_and_defaults(self):
        cfg = self.load(CREW_CONFIG)
        self.assertEqual(list(cfg.crew), ["production", "test"])  # 설정 순서
        prod = cfg.crew["production"]
        self.assertEqual((prod.name, prod.title, prod.roles, prod.agent, prod.model, prod.effort),
                         ("production", "생산", ("planner", "developer"), "claude", "opus", "xhigh"))
        self.assertIs(cfg.crew_of("developer"), prod)
        self.assertEqual(cfg.crew_of("tester").name, "test")
        self.assertIsNone(cfg.crew_of("nope"))
        with self.assertRaises(Exception):
            prod.agent = "codex"  # 고정 값이다(frozen)
        # title·agent·model·effort 가 없으면 이름, [defaults] worker, [defaults] 의 <agent>_model·<agent>_effort
        solo = self.load(BASE_CONFIG + '\n[crew.solo]\nroles = ["tester"]\n').crew["solo"]
        self.assertEqual((solo.title, solo.agent, solo.model, solo.effort), ("solo", "claude", "sonnet", "xhigh"))
        solo = self.load(BASE_CONFIG + '\n[crew.solo]\nroles = ["tester"]\nagent = "codex"\n').crew["solo"]
        self.assertEqual((solo.agent, solo.model, solo.effort), ("codex", "gpt-6.1-sol", "high"))

    def test_no_crew_means_all_temporary_workers(self):
        for text in (BASE_CONFIG, BASE_CONFIG + "\n[crew]\n"):
            with self.subTest(text=text[-8:]):
                cfg = self.load(text)
                self.assertEqual(cfg.crew, {})
                self.assertIsNone(cfg.crew_of("developer"))

    def test_crew_errors_are_collected(self):
        text = BASE_CONFIG + """
[crew.Bad_Name]
roles = ["developer"]

[crew.empty]
title = ""
roles = []

[crew.ghost]
roles = ["planner", "nope", "gone"]
agent = "gpt"
colour = "red"
alpha = 1

[crew.dup]
roles = ["planner", "tester"]
model = ""
"""
        errs = self.errors(text)
        for expected in ("crew.Bad_Name: 이름은 소문자로 시작하는 소문자·숫자·- 1–32자다",
                         "crew.empty.title 은 비지 않은 문자열이다",
                         "crew.empty.roles 는 비지 않은 직무 이름 목록이다",
                         "crew.ghost.roles 에 정의되지 않은 직무가 있다: nope, gone",
                         "crew.ghost.agent 는 claude·codex 다",
                         "crew.ghost: 모르는 키 alpha, colour",
                         "직무 planner 가 crew.ghost 와 crew.dup 에 함께 있다",
                         "crew.dup.model 는 비지 않은 문자열이다"):
            self.assertIn(expected, errs)

    def test_crew_shapes_and_name_length(self):
        self.assertIn("crew 는 표여야 한다", self.errors("crew = 1\n" + BASE_CONFIG))
        self.assertIn("crew.x 는 표여야 한다", self.errors(BASE_CONFIG + "\n[crew]\nx = 1\n"))
        self.assertIn("crew.x.roles 는 비지 않은 직무 이름 목록이다",
                      self.errors(BASE_CONFIG + '\n[crew.x]\nroles = "tester"\n'))
        long = "a" + "b" * 32  # 33자
        self.assertIn(f"crew.{long}: 이름은 소문자로 시작하는 소문자·숫자·- 1–32자다",
                      self.errors(BASE_CONFIG + f'\n[crew.{long}]\nroles = ["tester"]\n'))
        self.assertIn("crew.9a: 이름은 소문자로 시작하는 소문자·숫자·- 1–32자다",
                      self.errors(BASE_CONFIG + '\n[crew.9a]\nroles = ["tester"]\n'))
        cfg = self.load(BASE_CONFIG + f'\n[crew.{long[:32]}]\nroles = ["tester"]\n')  # 32자는 된다
        self.assertEqual(list(cfg.crew), [long[:32]])

    def test_codex_crew_cannot_hold_claude_only_roles(self):
        # 1장 6단계 결정: director·designer(config.CLAUDE_ONLY)를 가진 고정 에이전트는 claude 여야 한다
        errs = self.errors(FULL + '\n[crew.art]\nroles = ["designer", "director", "developer"]\nagent = "codex"\n')
        self.assertIn('crew.art: designer 는 claude 만 된다(agent = "codex")', errs)
        self.assertIn('crew.art: director 는 claude 만 된다(agent = "codex")', errs)
        cfg = self.load(FULL + '\n[crew.art]\nroles = ["designer", "director"]\nagent = "claude"\n')
        self.assertEqual(cfg.crew_of("director").name, "art")

    def test_model_and_effort_must_resolve(self):
        text = BASE_CONFIG.replace('codex_model = "gpt-6.1-sol"\n', "").replace('codex_effort = "high"\n', "")
        errs = self.errors(text + '\n[crew.cx]\nroles = ["tester"]\nagent = "codex"\n')
        self.assertIn("crew.cx.model 을 정하지 못했다([crew.cx].model 또는 [defaults].codex_model)", errs)
        self.assertIn("crew.cx.effort 을 정하지 못했다([crew.cx].effort 또는 [defaults].codex_effort)", errs)
        cfg = self.load(text + '\n[crew.cx]\nroles = ["tester"]\nagent = "codex"\nmodel = "m"\neffort = "e"\n')
        self.assertEqual((cfg.crew["cx"].model, cfg.crew["cx"].effort), ("m", "e"))


class CrewChoiceTest(TeamCase):
    """고정 에이전트 태스크의 모델 우선순위(설계 4.1 6단계): [crew] > [defaults]. 덮어쓰기는 무시하고 model_ignored."""

    def setUp(self):
        super().setUp()
        self.init_project(config=CREW_CONFIG, commit=False)
        self.cfg = config.load(Project(self.proj))
        self.prod = self.cfg.crew["production"]

    def test_crew_model_wins_and_reviewer_follows_role(self):
        c, ignored = config.crew_choice(self.cfg, self.prod, "developer", {}, {})
        self.assertEqual((c.worker, c.model, c.effort), ("claude", "opus", "xhigh"))
        self.assertEqual((c.reviewer, c.review_model, c.review_effort), ("codex", "gpt-6.1-sol", "high"))
        self.assertFalse(ignored)
        c, _ = config.crew_choice(self.cfg, self.cfg.crew["test"], "tester", {}, {})
        self.assertEqual((c.model, c.effort), ("sonnet", "xhigh"))  # [roles.tester] 가 아니라 crew 값

    def test_overrides_are_ignored_and_marked(self):
        for front, cli in (({}, {"model": "haiku"}), ({}, {"effort": "low"}), ({"claude_model": "haiku"}, {}),
                           ({"claude_effort": "low"}, {})):
            with self.subTest(front=front, cli=cli):
                c, ignored = config.crew_choice(self.cfg, self.prod, "developer", front, cli)
                self.assertEqual((c.model, c.effort, ignored), ("opus", "xhigh", True))
        # 리뷰어 쪽 front 는 직무 규칙대로 쓴다(덮어쓰기 무시가 아니다)
        c, ignored = config.crew_choice(self.cfg, self.prod, "developer", {"codex_model": "rv", "codex_effort": "low"}, {})
        self.assertEqual((c.review_model, c.review_effort, ignored), ("rv", "low", False))

    def test_codex_crew(self):
        text = CREW_CONFIG.replace('[roles.tester]\ntitle = "테스트"\n', '[roles.tester]\ntitle = "테스트"\nworker = "codex"\n')
        text = text.replace('roles = ["tester"]\nagent = "claude"\nmodel = "sonnet"',
                            'roles = ["tester"]\nagent = "codex"\nmodel = "gpt-crew"')
        self.init_project(config=text, commit=False)
        cfg = config.load(Project(self.proj))
        c, ignored = config.crew_choice(cfg, cfg.crew["test"], "tester", {"codex_model": "x"}, {})
        self.assertEqual((c.worker, c.model, c.effort, c.reviewer, c.review_model), ("codex", "gpt-crew", "xhigh",
                                                                                      "claude", "sonnet"))
        self.assertTrue(ignored)
        _, ignored = config.crew_choice(cfg, cfg.crew["test"], "tester", {"claude_model": "x"}, {})
        self.assertFalse(ignored)  # 리뷰어(claude) 쪽 값이다

    def test_unknown_role(self):
        with self.assertRaises(HteamError) as ctx:
            config.crew_choice(self.cfg, self.prod, "nope", {}, {})
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("unknown_role", 2))


class CrewWarningTest(TeamCase):
    """경고(설계 4.2): 고정 에이전트의 agent 가 그 직무들의 작업 에이전트 어느 것과도 같지 않다."""

    MESSAGE = ("crew.test: 어느 직무의 작업 에이전트도 codex 가 아니다. 이 에이전트는 태스크를 받지 않는다(태스크 front matter "
               "의 worker 로만 받는다)")

    def test_warning_in_status_and_doctor(self):
        text = CREW_CONFIG.replace('roles = ["tester"]\nagent = "claude"', 'roles = ["tester"]\nagent = "codex"')
        self.init_project(config=text)
        cfg = config.load(Project(self.proj))
        self.assertEqual(config.crew_warnings(cfg), [self.MESSAGE])
        code, out = self.hteam("status")
        self.assertEqual(code, 0, out)
        self.assertIn(self.MESSAGE, out["warnings"])
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual(code, 0, out)  # 경고는 healthy 를 바꾸지 않는다
        self.assertIn(self.MESSAGE, out["warnings"])
        fixed = text.replace('[roles.tester]\ntitle = "테스트"\n', '[roles.tester]\ntitle = "테스트"\nworker = "codex"\n')
        (self.team / "config.toml").write_text(fixed, encoding="utf-8")
        self.assertEqual(config.crew_warnings(config.load(Project(self.proj))), [])
        self.assertEqual(self.hteam("doctor", as_="main")[1]["warnings"], [])

    def test_doctor_without_config_has_empty_warnings(self):
        code, out = self.hteam("doctor", as_="main")
        self.assertEqual((code, out["warnings"]), (0, []), out)


class TemplateConfigTest(unittest.TestCase):
    """템플릿 config.toml(설계 4장 6단계): 표, 고정 에이전트, 모든 codex_effort xhigh, 머리 주석."""

    def setUp(self):
        import tomllib
        self.text = (ROOT / "templates" / "config.toml").read_text(encoding="utf-8")
        self.raw = tomllib.loads(self.text)

    def test_tables_and_crew(self):
        raw = self.raw
        self.assertEqual(config.validate(raw), [])
        self.assertNotIn("coordinator", raw)
        self.assertEqual((raw["drive"], raw["overflow"], raw["review"]),
                         ({"auto_up": True}, {"enabled": True}, {"max_rounds": 3}))
        self.assertEqual(list(raw["crew"]), ["production", "research", "test"])
        self.assertEqual({n: (c["title"], c["roles"], c["agent"], c["model"], c["effort"]) for n, c in raw["crew"].items()},
                         {"production": ("생산", ["planner", "designer", "developer"], "claude", "opus", "xhigh"),
                          "research": ("조사", ["director"], "claude", "opus", "xhigh"),
                          "test": ("테스트", ["tester"], "codex", "gpt-6.1-sol", "xhigh")})
        # 테스트는 생산(Claude)과 다른 모델이 수용 기준으로 짠다(사용자 결정 2026-11-11). 리뷰는 반대쪽인 Claude
        self.assertEqual(raw["roles"]["tester"]["worker"], "codex")
        cfg = config.build(raw)
        self.assertEqual(config.crew_warnings(cfg), [])
        self.assertEqual(cfg.crew_of("designer").name, "production")

    def test_every_codex_effort_is_xhigh(self):
        efforts = {"defaults": self.raw["defaults"]["codex_effort"]}
        efforts.update({f"roles.{n}": r["codex_effort"] for n, r in self.raw["roles"].items()})
        self.assertEqual(len(efforts), 6, efforts)
        self.assertEqual(set(efforts.values()), {"xhigh"}, efforts)

    def test_head_comments(self):
        for line in ("# auto_up: [drive] 표에 둔다. 메인 세션 훅이 관제(hteam drive)가 확실히 죽은 것을 보면 자동으로 다시 "
                     "띄운다(기본 true). false 면 안내만 한다.",
                     "# crew: 고정 에이전트. roles 의 직무 태스크를 한 세션이 이어 맡는다. 한 직무는 한 에이전트에만 둔다. agent 가 "
                     "태스크의 작업 에이전트와 다르면 그 태스크는 임시 워커로 돈다.",
                     "# overflow: 고정 에이전트가 바쁠 때 준비된 독립 태스크를 임시 워커로 돌린다(기본 true)."):
            self.assertIn(line + "\n", self.text)
        self.assertIn('claude_model = "sonnet"   # 임시 워커로 돌 때만 쓴다. 생산 에이전트에서는 그 에이전트 모델(6단계)\n',
                      self.text)


if __name__ == "__main__":
    unittest.main()
