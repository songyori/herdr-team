"""13단계 코드 품질 규칙(설계 5.11 의 2–4): 작업 규칙 7번·3번, developer 의 재현 시험, planner·메인 규칙의 표시 줄, 표시 줄 읽기."""
import unittest

from tests.helpers import ROOT, VALID_BODY
from hteam import specs

REPRO_LINE = "- 재현 시험: 고치기 전에 실패하는 시험을 먼저 쓴다(보고서 ### 재현 시험)"
GUARD_RULE = ("7. 검사를 통과시키려고 다음을 더하지 않는다: 억제 주석(`@ts-ignore`, `eslint-disable`, `# noqa`, `# type: ignore` "
              "같은 것), 시험 건너뛰기·골라 돌리기(`.skip`, `.only`, `xit`, skip 표시), 시험·단언 지우기나 약하게 바꾸기, 빈 "
              "catch·`except: pass`, 기준값 낮추기, 동작하지 않는 자리 채움(`Not implemented`). 꼭 필요하면 보고서에 이유를 적는다.")
UNTOUCHED = ("그 절 안 `### 건드리지 않고 본 것` 소절에 범위 밖에서 본 문제를 고치지 않고 `파일:줄 — 무엇` 으로 적는다"
             "(없으면 \"없음\").")


def read(rel):
    return (ROOT / "templates" / rel).read_text(encoding="utf-8")


def section(text, title):
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class WorkerRulesTest(unittest.TestCase):
    def test_guard_rule_is_seventh_and_untouched_list_in_third(self):
        rules = read("worker-rules.md")
        self.assertIn("수정 라운드로 돌려보낸다).\n" + GUARD_RULE + "\n", rules)
        self.assertTrue(rules.rstrip().endswith(GUARD_RULE))
        self.assertIn("남은 위험, 가정. " + UNTOUCHED + " 이슈 트래커의", rules)
        # tester 의 같은 뜻 한 줄은 그대로 둔다(설계 5.11 의 2)
        self.assertIn("테스트를 통과시키려고 테스트를 약하게 만들거나 건너뛰거나 지우지 않는다.", read("roles/tester.md"))


class ReproDocTest(unittest.TestCase):
    def test_developer_repro_section(self):
        text = section(read("roles/developer.md"), "재현 시험")
        for needle in ("`- 재현 시험:`", "먼저 쓰고 돌려 실패를 확인한 뒤 고친다", "`### 재현 시험`", "고치기 전 실패 출력 원문",
                       "고친 뒤 통과 출력 원문", "이미 실패하는 시험이 있으면", "그 이유와 대신 확인한 방법", "수정 라운드도"):
            self.assertIn(needle, text)

    def test_marker_line_is_the_same_everywhere(self):
        planner = section(read("roles/planner.md"), "tasks.toml 형식")
        main = read("CLAUDE.section.md")
        rules = main[main.index("### 메인 규칙\n"):main.index("### decide 처리 기준\n")]
        for text in (planner, rules):
            self.assertIn(f"`{REPRO_LINE}`", text)
        self.assertIn("묶음 정리 태스크와 수정 라운드", rules)
        self.assertEqual(specs.REPRO_LINE, REPRO_LINE)
        # 메인 규칙 줄은 decide 처리 줄 앞이다(그 줄 뒤에는 7단계 index.lock 줄이 붙어 있다)
        self.assertLess(rules.index(REPRO_LINE), rules.index("- decide 를 처리하며 만든 태스크"))
        table = main[main.index("### decide 처리 기준\n"):main.index("### 질문 표시 규칙\n")]
        row = next(line for line in table.splitlines() if line.startswith("| `unknown_regression` |"))
        self.assertIn("재현 시험 줄", row)


class PlanWarningDocTest(unittest.TestCase):
    def test_planner_reads_warnings_before_the_confirm_question(self):
        text = read("roles/planner.md")
        confirm = section(text, "확정 질문")
        for needle in ("`plan check` 출력의 `warnings`", "나누지 않은 경고는 그 이유를 확정 질문 `context` 에 적는다"):
            self.assertIn(needle, confirm)
        tasks = section(text, "tasks.toml 형식")
        for needle in ("`acceptance` 를 5개 이하로", "`title` 에 \"및\"·\"그리고\" 를 쓰지 않는다", "`warnings`"):
            self.assertIn(needle, tasks)


class ReproTaskTest(unittest.TestCase):
    def spec(self, constraints):
        body = VALID_BODY.replace("표준 라이브러리만.", constraints)
        return specs.parse(f"---\nid: T-001\nrole: developer\ntitle: 고치기\n---\n{body}")

    def test_marker_line_head(self):
        self.assertTrue(specs.repro_task(self.spec(f"표준 라이브러리만.\n{REPRO_LINE}")))
        self.assertTrue(specs.repro_task(self.spec("  - 재현 시험: 손으로 쓴 뒤쪽 글은 보지 않는다")))
        for text in ("표준 라이브러리만.", "재현 시험: 글머리가 없다", "표준 라이브러리만. - 재현 시험: 줄 머리가 아니다",
                     "- 재현 시험 줄이 없다"):
            self.assertFalse(specs.repro_task(self.spec(text)), text)
        self.assertFalse(specs.repro_task(specs.parse("---\nid: T-001\nrole: developer\ntitle: x\n---\n## Target\nx\n")))


if __name__ == "__main__":
    unittest.main()
