"""프로젝트 규칙 파일(설계 5.11 의 1, 13단계): .herdr-team/project-rules/<직무>.md 를 워커 사양이 직무 문서 뒤에 붙이고, 리뷰
프롬프트가 가리키고, 메인 규칙이 그 파일에 쓰라고 한다. upgrade 옮기기는 test_setup.UpgradeTest(9.7 의 1)."""
from __future__ import annotations

import unittest

from tests.helpers import ROOT, TeamCase
from hteam import compose, config, specs, state
from hteam.errors import HteamError
from hteam.paths import Project

NOTE = ("아래는 이 프로젝트가 더한 developer 규칙이다(.herdr-team/project-rules/developer.md). 이 사양의 작업 규칙"
        "(소유 경로, 커밋, 보고서, done)은 바꾸지 않는다.")


class ProjectRulesSpecTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)
        self.write_spec("T-001")
        self.rules = self.team / "project-rules" / "developer.md"

    def spec_text(self):
        cfg = config.load(self.p)
        return compose.work_spec(self.p, cfg, specs.load(self.p, "T-001"), {"round": 1}, ["src/**"])

    def test_rules_follow_the_role_doc(self):
        self.assertEqual(self.p.project_rules("developer"), self.rules)
        self.assertNotIn("이 프로젝트가 더한", self.spec_text())  # 없으면 지금 그대로
        self.rules.parent.mkdir()
        self.rules.write_text("  \n\n", encoding="utf-8")
        self.assertNotIn("이 프로젝트가 더한", self.spec_text())  # 공백뿐이면 붙이지 않는다
        self.rules.write_text("## 이 프로젝트 규칙\n- 제품 책임자의 개인 폰은 쓰지 않는다.\n", encoding="utf-8")
        text = self.spec_text()
        self.assertLess(text.index("# developer 직무 문서"), text.index(NOTE))
        self.assertLess(text.index(NOTE), text.index("- 제품 책임자의 개인 폰은 쓰지 않는다."))
        self.assertLess(text.index("- 제품 책임자의 개인 폰은 쓰지 않는다."), text.index("---\n\n# 태스크 T-001"))
        self.assertEqual(text.count(NOTE), 1)

    def test_other_roles_do_not_get_the_file(self):
        self.rules.parent.mkdir()
        (self.team / "project-rules" / "tester.md").write_text("- 테스터만의 규칙\n", encoding="utf-8")
        self.assertNotIn("테스터만의 규칙", self.spec_text())

    def test_unreadable_rules_stop_the_spec(self):
        self.rules.mkdir(parents=True)  # 디렉터리라 읽지 못한다
        with self.assertRaises(HteamError) as ctx:
            self.spec_text()
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("project_rules_unreadable", 1))
        self.rules.rmdir()
        self.rules.write_bytes(b"\xff\xfe\x00")  # UTF-8 아님
        with self.assertRaises(HteamError) as ctx:
            self.spec_text()
        self.assertEqual(ctx.exception.code, "project_rules_unreadable")
        self.rules.unlink()
        self.rules.symlink_to(self.tmp / "없는-규칙.md")  # 끊어진 링크는 "없음" 이 아니다
        with self.assertRaises(HteamError) as ctx:
            self.spec_text()
        self.assertEqual(ctx.exception.code, "project_rules_unreadable")
        self.assertIn("끊어진 심볼릭 링크", ctx.exception.message)


class ProjectRulesReviewTest(TeamCase):
    """태스크 하나씩(두 developer 태스크를 함께 띄우면 owns 잠금이 겹친다)."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)

    def prompt(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.assertEqual(self.act_work("T-001")[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        return (self.state_dir / "tasks" / "T-001" / "r1-review-a1.md").read_text(encoding="utf-8")

    def test_no_rules_line_without_file(self):
        text = self.prompt()
        self.assertIn("- 직무 문서: `.herdr-team/roles/developer.md`\n- 워커 보고서:", text)
        self.assertIn("2. 직무 문서와 프로젝트 규칙(위에 있으면)의 규칙과 품질 기준을 지키는가.", text)

    def test_rules_line_with_file(self):
        self.commit(".herdr-team/project-rules/developer.md", "- 개인 폰은 쓰지 않는다.\n", "프로젝트 규칙")
        text = self.prompt()
        self.assertIn("- 직무 문서: `.herdr-team/roles/developer.md`\n"
                      "- 프로젝트 규칙: `.herdr-team/project-rules/developer.md`\n- 워커 보고서:", text)


class MainRuleTest(unittest.TestCase):
    def test_main_rule_says_where_project_rules_go(self):
        main = (ROOT / "templates" / "CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("직무 문서(`.herdr-team/roles/<직무>.md`)가 아니라 `.herdr-team/project-rules/<직무>.md` 에 쓰고 "
                      "커밋한다", main)
