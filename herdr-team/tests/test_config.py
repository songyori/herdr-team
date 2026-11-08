"""설정 검사(설계 4.2)와 모델·에이전트 결정(4.1)."""
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path as FsPath
from unittest import mock

from tests.helpers import BASE_CONFIG, TeamCase
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

    def test_coordinator_auto_up(self):
        # 설계 4.1·4.2: 키가 없으면 켜진다(0.1.x 프로젝트도). 있으면 불리언이다
        self.assertIs(self.load(BASE_CONFIG).auto_up, True)
        off = BASE_CONFIG.replace('effort = "xhigh"\n', 'effort = "xhigh"\nauto_up = false\n', 1)
        self.assertIs(self.load(off).auto_up, False)
        bad = BASE_CONFIG.replace('effort = "xhigh"\n', 'effort = "xhigh"\nauto_up = "yes"\n', 1)
        self.assertIn("coordinator.auto_up 은 true·false 다", self.errors(bad))

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


if __name__ == "__main__":
    unittest.main()
