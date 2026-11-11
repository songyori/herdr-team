"""6단계 문구(설계 5.5·7.7·9.4·9.6·15.1 템플릿): 코디네이터가 없는 템플릿·스킬·워커 사양·테스트 관문 문구, 메인 규칙,
README, 없앤 코디네이터 문서."""
import json
import re
import unittest

from tests.helpers import REPO, ROOT, TeamCase
from hteam import compose, config, setup, specs, testgate
from hteam.paths import Project

TEMPLATE_DOCS = sorted([*(ROOT / "templates").rglob("*.md"), *(ROOT / "skills").rglob("*.md")])
REMOVED = re.compile(r"hteam (tell|notify|wait|which|bind|applied)\b|design-review --decide|up --force")
DECIDE_KINDS = ("worker_failed", "worker_question", "escalation", "max_rounds", "repeat_test_failure", "test_config",
                "planning_gaps", "unknown_regression", "token_update")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class TemplateWordingTest(unittest.TestCase):
    def test_no_coordinator_in_templates_and_skills(self):
        self.assertTrue(TEMPLATE_DOCS)
        for path in TEMPLATE_DOCS:
            with self.subTest(str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("코디네이터", text)
                self.assertIsNone(REMOVED.search(text))

    def test_coordinator_doc_is_gone(self):
        self.assertFalse((ROOT / "templates/coordinator.md").exists())
        self.assertNotIn("coordinator.md", setup.FILES)
        self.assertNotIn("coordinator.md", setup.UPGRADE)
        self.assertFalse(hasattr(Project(ROOT), "coordinator_md"))
        self.assertFalse(hasattr(setup, "COORD_PROMPT"))
        plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        entry = [x for x in market["plugins"] if x["name"] == "herdr-team"][0]
        for text in (plugin["description"], entry["description"]):
            self.assertNotIn("코디네이터", text)
            self.assertIn("관제", text)

    def test_ask_wording_in_rules_and_agents(self):
        self.assertIn("그 밖의 파일을 고쳐야 하면 멈추고 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답하거나 "
                      "새 태스크로 나눈다).", read("templates/worker-rules.md"))
        agents = read("templates/AGENTS.section.md")
        self.assertIn("- 대화형으로 사용자에게 묻지 않는다. 막히면 프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 "
                      "답한다).", agents)
        self.assertIn("- 리뷰 동안 다른 워커·관제·메인의 커밋으로 HEAD 가 움직이는 것은 정상이다. 그 때문에 멈추거나 묻지 않는다.", agents)
        self.assertIn("리뷰 동안 다른 워커·관제·메인의 커밋으로 HEAD 가 움직이는 것은 정상이다. 그 때문에 멈추거나 묻지 않고 아래 리뷰 "
                      "대상 커밋을 리뷰한다.", read("templates/review-prompt.md"))
        self.assertIn("관제가 메인에 확정 질문을 올린다.", read("templates/roles/developer.md"))
        tester = read("templates/roles/tester.md")
        self.assertIn("관제가 메인에 확정 질문을 올린다.", tester)
        self.assertIn("- `src/` 고치기. 버그는 보고서에 적는다. 리뷰의 `## 회귀` 를 거쳐 관제가 회귀 수정 태스크로 만든다.", tester)
        self.assertIn("관제 환경에서 자동으로 돈다", read("templates/roles/planner.md"))
        self.assertIn("관제가 제안을 모아 디렉터 보강 태스크로", read("templates/roles/designer.md"))
        self.assertIn("관제가 화면 디자이너들의", read("templates/roles/director.md"))


class MainRulesTest(unittest.TestCase):
    """메인 규칙과 decide 처리 기준(설계 7.7, templates/CLAUDE.section.md)."""

    def setUp(self):
        self.main = read("templates/CLAUDE.section.md")

    def section(self, title: str) -> str:
        start = self.main.index(f"### {title}\n")
        nxt = self.main.find("\n### ", start + 1)
        return self.main[start:nxt if nxt != -1 else len(self.main)]

    def test_role_table_has_no_coordinator_row(self):
        table = self.main[self.main.index("| 판별 |"):self.main.index("### 메인 규칙")]
        rows = [ln for ln in table.splitlines() if ln.startswith("| ") and not ln.startswith("| 판별")]
        self.assertEqual(rows, [
            '| 첫 프롬프트가 "너는 herdr-orch 워커다" 로 시작 | 직무 워커·리뷰어(고정 에이전트 또는 임시 워커) | 프리앰블과 그 사양 |',
            '| 그 밖 | 메인 | 아래 "메인 규칙" |'])
        self.assertIn("관제(`hteam drive`)는 관제 탭에서 도는 프로그램이다. 완료 대기, 리뷰, accept·fix, 다음 태스크 시작, 묶음 후속, "
                      "세션 리셋, 복구를 정해진 절차대로 하고 판단이 필요한 일만 decide 로 메인에 올린다.", self.main)
        self.assertNotIn("HTEAM_ROLE", self.main)

    def test_main_rules_lines(self):
        rules = self.section("메인 규칙")
        for needle in (
                "- 메인은 사용자와 대화하고 판단한다. 기획·디자인·코드·테스트 산출물을 직접 만들지 않는다(훅이 막는다). "
                "서브에이전트로 대신 시키지도 않는다.",
                '  1. `.herdr-team/bin/hteam task new --role planner --title "<요약>"`.',
                '  3. 경로 지정 커밋: `git add -- .herdr-team/tasks/T-xxx.md && git commit -m "spec: T-xxx" -- '
                ".herdr-team/tasks/T-xxx.md`. 경로 없는 커밋은 하지 않는다.",
                '{"status": "waiting"}',
                "front matter 에 `plan: append`",
                '`.herdr-team/bin/hteam scope T-xxx "<내용>"`',
                "- 큐 명령(`start`, `start-ready`, `fix`, `accept`, `drop`, `review --retry`, `design-decide`, `scope`, "
                "`agent reset`, `test-confirm`)은 관제 큐를 거친다.",
                "- `horch` 와 `hteam drive` 를 직접 부르지 않는다(훅이 막는다).",
                "`status: orphaned` 면 `/herdr-team:up` 을 한다.",
                '`decide`: 아래 "decide 처리 기준"대로 처리하고 `.herdr-team/bin/hteam answer <id> "<처리 내용>"` 으로 닫는다.',
                "`result`",
                "- decide 가 열린 동안 관제는 그 태스크를 자동으로 다루지 않는다. 처리했으면 명령이 적히지 않은 escalation 도 "
                '반드시 `hteam answer <id> "<처리 내용>"` 으로 닫는다.',
                "`.herdr-team/bin/hteam design-decide <id> --json -`"):
            self.assertIn(needle, rules)
        self.assertNotIn("tell", rules)

    def test_decide_table_has_the_nine_kinds(self):
        table = self.section("decide 처리 기준")
        self.assertIn("decide 에 적힌 `files` 만 읽고 `commands` 가운데 하나로 처리한다. 사용자에게 물을 때는 AskUserQuestion 을 "
                      "직접 쓴다(질문 하나, 선택지 2–4개, 추천 하나).", table)
        kinds = re.findall(r"^\| `(\w+)` \|", table, re.M)
        self.assertEqual(tuple(kinds), DECIDE_KINDS)
        for needle in ('`hteam fix T-xxx --force-round --note "<지시>"`', "`plan: append`",
                       "`hteam test T-yyy` 가 통과한다", "`출처: T-xxx followups`"):
            self.assertIn(needle, table)
        self.assertNotIn("--extra-round", table)

    def test_question_rules_and_locations(self):
        rules = self.section("질문 표시 규칙")
        self.assertIn("- `approval`(승인 직무 일괄 승인, 보통 디자인): 사용자 답을 태스크별로 정리해 "
                      "`hteam design-decide <id> --json -` 으로 넘긴다", rules)
        self.assertIn("사용자가 `수정 요청` 을 고르면 어느 태스크를 어떻게 고칠지 대화로 물은 뒤 넘긴다.", rules)
        self.assertNotIn("수정 요청: <태스크 ID 와 고칠 내용>", rules)
        where = self.section("위치")
        for needle in ("`[crew.*]`", "`[overflow]`", "`[drive]`", "`.herdr-team/state/drive/drive.log`",
                       "`.herdr-team/state/crew.json`", "`docs/handoff/<이름>.md`",
                       "- 상태 `hteam status`(태스크별 상태·next, 관제·고정 에이전트·watch 생사, 열린 질문)."):
            self.assertIn(needle, where)


class SkillWordingTest(unittest.TestCase):
    def test_up_skill(self):
        up = read("skills/up/SKILL.md")
        head = up.split("---")[1]
        self.assertIn("수동 복구. 관제는 보통 메인 세션 훅이 자동으로 살린다(config.toml `[drive] auto_up`).", head)
        for needle in ("`drive.hung`", "`drive.alive`·`drive.hung`·`drive.starting`", "`running`", "`launched`",
                       "decide 처리 기준", "`hteam design-decide <id> --json -`", "고정 에이전트(`crew`"):
            self.assertIn(needle, up)
        self.assertNotIn("--force", up)
        self.assertNotIn("coordinator_unverifiable", up)
        self.assertIn("`[coordinator]` 가 있으면 0.3.0 설정이다", up)  # 다시 세팅을 안내한다(설계 4.2)
        # 관제를 띄우지 못했으면 watch 를 띄우지 않는다(최종 리뷰 I1: watch → orphaned → up 실패가 되풀이되지 않게)
        self.assertIn("3 이 관제를 띄우지 못했으면(exit 4·1, 그 밖의 오류) 사용자에게 알리고, `unread_outbox` 가 0 이면 watch 를 "
                      "띄우지 않는다", up)
        # 관제가 꺼졌어도 미전달 항목은 watch 가 준다(Codex 커밋 리뷰 81c2c30)
        self.assertIn("`unread_outbox` 가 0 보다 크면(관제가 꺼졌어도) Bash `run_in_background: true` 로 `hteam watch` 를 "
                      "띄운다", up)

    def test_init_skill(self):
        init = read("skills/init/SKILL.md")
        self.assertIn("herdr-team(메인·관제·고정 에이전트, Claude ↔ Codex 교차 리뷰)", init)
        self.assertIn("## 5. 관제\n", init)
        for needle in ("고정 에이전트 구성(`[crew.<이름>]`, `[overflow]`)", "`production`(planner·designer·developer)",
                       '`worker = "codex"`', "director·designer 를 가진 에이전트는 claude 만 된다",
                       "`[agents.claude].args` 는 Claude 워커·리뷰어(고정 에이전트 포함)를 띄울 때마다 붙는다",
                       "`horch` 와 `hteam drive` 직접 호출"):
            self.assertIn(needle, init)
        self.assertNotIn("--force", init)


class ComposeWordingTest(TeamCase):
    """워커 사양의 6단계 문구(설계 5.5): 메인에게 묻는다, 관제가 따로 만든다, 지시, 이어 받은 세션."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)

    def spec(self, role, rd):
        self.write_spec("T-001", role, commit=False)
        cfg = config.load(self.p)
        return compose.work_spec(self.p, cfg, specs.load(self.p, "T-001"), rd, cfg.owns(role))

    def test_first_round_asks_main(self):
        text = self.spec("developer", {"round": 1})
        self.assertIn("4. 막히면 프리앰블의 ask 명령으로 메인에게 묻고 답을 기다린다.", text)
        self.assertIn("프리앰블의 ask 명령으로 메인에게 묻는다(관제가 메인에 올리고, 메인이 답하거나 새 태스크로 나눈다).", text)
        self.assertNotIn("코디네이터", text)
        text = self.spec("planner", {"round": 1})
        self.assertIn("메인에게 물을 것은 프리앰블의 ask 명령을 쓴다.", text)
        self.assertNotIn("코디네이터", text)

    def test_fix_block(self):
        self.commit("docs/reviews/T-001/r1.md", "VERDICT: REQUEST_CHANGES\n", "[T-001] review r1: REQUEST_CHANGES")
        text = self.spec("developer", {"round": 2, "note": "버튼 색을 바꾼다"})
        for needle in ("이전 대화가 없을 수 있다(고정 에이전트면 같은 세션일 수 있다). 먼저 `docs/tasks/T-001/report.md` 와",
                       "`## 후속`·`## 기획 누락`·`## 회귀` 는 고치지 않는다(관제가 따로 태스크나 decide 로 만든다).",
                       "지시: 버튼 색을 바꾼다\n"):
            self.assertIn(needle, text)
        self.assertNotIn("코디네이터", text)
        self.assertNotIn("이전 대화는 없다", text)
        text = self.spec("developer", {"round": 2, "from_user": True, "note": "글꼴", "coord_note": "이전 워커가 끝남"})
        self.assertIn("사용자 요청: 글꼴\n", text)
        self.assertIn("지시: 이전 워커가 끝남\n", text)
        self.assertEqual(compose.round_requests(self.p, {"note": "a"}), [("지시", "a")])
        self.assertEqual(compose.round_requests(self.p, {"from_user": True, "note": "a", "coord_note": "b"}),
                         [("사용자 요청", "a"), ("지시", "b")])

    def test_tester_test_block(self):
        self.assertIn("제품 회귀는 리뷰가 `## 회귀` 로 넘기고 관제가 회귀 수정 태스크로 만든다(원인을 정하지 못하면 메인이 정한다).",
                      compose.TESTER_TEST_BLOCK)
        for block in (compose.TESTER_TEST_BLOCK, compose.DEVELOPER_TEST_BLOCK, compose.PENDING_TEST_BLOCK):
            self.assertNotIn("코디네이터", block)


class GateWordingTest(TeamCase):
    """테스트 관문 문구(설계 5.7): 관제 환경, 관제가 확정 질문을 올린다, test-confirm."""

    def test_constants(self):
        self.assertEqual(testgate.CONFIRM_LINE, "이 명령은 리뷰 전에 관제 환경에서 자동으로 돈다(Codex 샌드박스 밖, 사용자 권한). "
                                                "워커도 자기 환경에서 돌린다.")
        self.assertEqual(testgate.CONFIRM_HINT, "커밋된 `[test]` 를 사용자가 확정하지 않았다. 관제가 확정 질문을 올린다. 확정 "
                                                "기록이 빠졌으면 `.herdr-team/bin/hteam test-confirm`")

    def test_unapproved_message(self):
        self.init_project()
        self.use_gate(approve=False)
        code, out = self.hteam("test", "--full", as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "test_unapproved"), out)
        self.assertEqual(out["error"]["message"],
                         "커밋된 [test] 를 사용자가 확정하지 않았다. 관제가 메인에 확정 질문을 올린다(hteam status 의 test_gate)")


class ReadmeTest(unittest.TestCase):
    def test_readme_describes_drive_crew_and_upgrade(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        for needle in ("### 관제와 고정 에이전트", "### 리뷰 보기 pane", "그 pane 에서 친 키는 리뷰어에 들어간다", "`ctrl+\\`",
                       "### 관제 복구", "`[drive] auto_up = false`", "herdr-orch 0.2.0 이상", "#### 0.3.0 → 0.4.0",
                       "이전하지 않는다", "`config.toml` 을 지운 뒤 `/herdr-team:init`", "`drive_down`", "`drive_hung`"):
            self.assertIn(needle, text)
        head = text[:text.index("### 이미 세팅한 프로젝트 업그레이드")]
        self.assertNotIn("코디네이터", head)  # 옛 버전 업그레이드 기록 밖에는 코디네이터가 없다
        self.assertLess(text.index("#### 0.3.0 → 0.4.0"), text.index("#### 0.2.0 → 0.3.0"))


if __name__ == "__main__":
    unittest.main()


from tests.helpers import BASE_CONFIG, CREW_CONFIG  # noqa: E402  (Append 블록, 7단계)

P7_REDMINE = ('\n[redmine]\nurl = "https://redmine.example.com"\nkey_env = "REDMINE_API_KEY"\n'
              'status = { start = 2, done = 3, changes = 4, closed = 5 }\n')
WORK_PRIORITY = ("보고서 경로, 커밋 형식, done 방법은 이 사양이 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 규칙보다 앞선다"
                 "(Orca 시절 문서의 다른 보고서 경로·이슈 트래커 갱신 규칙과 부딪칠 때).")
REVIEW_PRIORITY = ("- 이 프롬프트의 리뷰 파일 경로·형식·판정 표기와 git 쓰기 금지는 프로젝트 문서(AGENTS.md, CLAUDE.md 등)의 다른 "
                   "규칙보다 앞선다. 코드·문구·디자인 기준은 프로젝트 문서도 따른다.")
ROUND_TWO = ("2. 새 커밋이 새 P1 을 만들었는지. 고친 함수·데이터를 읽는 다른 호출처와 출력 경로(다른 화면, 내보내기, 다른 "
             "API·작업)도 본다. 고친 방법이 만든 새 경계 조건(잠금 대기의 누적, 시각·순서, 늦은 응답)도 본다.")
RULES_HEAD = "## 소유 경로와 작업 규칙\n"


class PromptTemplateP7Test(unittest.TestCase):
    """7단계 템플릿 문구(설계 6.2·5.5): 리뷰 프롬프트 우선순위 줄과 자리, 라운드 절 2, 작업 규칙의 우선순위 줄."""

    def test_review_prompt_priority_line_and_slots(self):
        text = read("templates/review-prompt.md")
        self.assertIn("<execution_policy>\n- 리뷰만 한다. 쓰는 파일은 REVIEW_FILE 하나다. 다른 파일을 만들거나 고치거나 지우지 "
                      "않는다.\n" + REVIEW_PRIORITY + "\n- git 쓰기", text)
        self.assertIn("— [{{role}}] {{title}}{{issue}}\n- 사양: `{{spec_path}}`\n", text)
        self.assertIn("{{request_rule}}\n\n{{extra}}## 등급과 판정\n", text)

    def test_round_item_two(self):
        text = read("templates/review-round.md")
        self.assertIn("\n" + ROUND_TWO + "\n3. r{{prev}} 이후 바뀌지 않은 코드에서", text)
        self.assertNotIn("2. 새 커밋이 새 P1 을 만들었는지.\n", text)
        self.assertIn("이번 라운드는 세 가지만 본다.", text)

    def test_worker_rules_priority_paragraph(self):
        text = read("templates/worker-rules.md")
        self.assertIn("새 태스크로 나눈다).\n\n" + WORK_PRIORITY + "\n\n1. 같은 작업 폴더에서", text)
        self.assertTrue(text.rstrip().endswith("(리뷰 사전 검사가 수정 라운드로 돌려보낸다)."))


class WorkSpecP7Test(TeamCase):
    """워커 사양의 7단계 줄(설계 5.5 의 8·작업 규칙, 8.12): 작업 규칙의 우선순위 줄, 작업 규칙 바로 앞의 이슈 줄."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)

    def spec(self, front=None, config_text=None) -> str:
        if config_text is not None:
            (self.team / "config.toml").write_text(config_text, encoding="utf-8")
        self.write_spec("T-001", "developer", front=front, commit=False)
        cfg = config.load(self.p)
        return compose.work_spec(self.p, cfg, specs.load(self.p, "T-001"), {"round": 1}, cfg.owns("developer"))

    def test_defaults_add_only_the_priority_paragraph(self):
        # 회귀: issue 가 없으면 선행 태스크 절 바로 뒤가 작업 규칙이다
        text = self.spec()
        self.assertIn("## 선행 태스크\n없음.\n\n" + RULES_HEAD, text)
        self.assertNotIn("이슈 #", text)
        self.assertEqual(text.count(WORK_PRIORITY), 1)
        self.assertNotIn("\n\n\n", text)

    def test_issue_line_right_before_the_rules(self):
        text = self.spec(front={"issue": "5712"})
        self.assertIn("## 선행 태스크\n없음.\n\n이 태스크는 이슈 #5712 이다.\n\n" + RULES_HEAD, text)
        self.assertEqual(text.count("이슈 #5712"), 1)
        self.assertNotIn("\n\n\n", text)

    def test_issue_hash_is_dropped(self):
        text = self.spec(front={"issue": "#5712"})
        self.assertIn("\n\n이 태스크는 이슈 #5712 이다.\n\n" + RULES_HEAD, text)
        self.assertNotIn("##5712", text)

    def test_redmine_issue_line(self):
        text = self.spec(front={"issue": "5712"}, config_text=BASE_CONFIG + P7_REDMINE)
        self.assertIn("\n\n이 태스크는 Redmine 이슈 #5712 이다. 이슈 상태와 노트는 관제가 바꾼다. 워커·리뷰어는 Redmine 을 바꾸지 "
                      "않는다(프로젝트 문서에 다른 규칙이 있어도).\n\n" + RULES_HEAD, text)

    def test_redmine_without_issue_adds_nothing(self):
        text = self.spec(config_text=BASE_CONFIG + P7_REDMINE)
        self.assertIn("## 선행 태스크\n없음.\n\n" + RULES_HEAD, text)
        self.assertNotIn("Redmine", text)

    def test_issue_line_comes_after_the_handoff_line(self):
        (self.proj / "docs/handoff").mkdir(parents=True)
        (self.proj / "docs/handoff/production.md").write_text("# 인수인계\n", encoding="utf-8")
        text = self.spec(front={"issue": "5712"}, config_text=CREW_CONFIG)
        self.assertIn("남은 일이 적혀 있다.\n\n이 태스크는 이슈 #5712 이다.\n\n" + RULES_HEAD, text)
