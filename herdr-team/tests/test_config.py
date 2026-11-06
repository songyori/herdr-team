"""설정 검사(설계 4.2)와 모델·에이전트 결정(4.1)."""
import os
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import config
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
        self.assertEqual(cfg.coordinator, {"model": "opus", "effort": "xhigh"})

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
                 "coordinator.model": BASE_CONFIG.replace('[coordinator]\nmodel = "opus"', '[coordinator]\nmodel = ["opus"]'),
                 "coordinator.effort": BASE_CONFIG.replace('effort = "xhigh"\n\n[review]', "effort = true\n\n[review]"),
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

    def test_image_choice(self):
        cfg = self.load(FULL)
        self.assertEqual(cfg.image_choice(), ("img-model", "high"))
        cfg = self.load(BASE_CONFIG)
        self.assertEqual(cfg.image_choice(), ("gpt-6.1-sol", "high"))


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


if __name__ == "__main__":
    unittest.main()
