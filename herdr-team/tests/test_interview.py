"""기획 인터뷰(설계 10장): planner 직무 문서의 체크리스트·확정 질문·리뷰 기준, 수정 라운드의 열린 질문."""
import json
import re
import unittest

from tests.helpers import ROOT, TeamCase
from hteam import outbox, state
from hteam.paths import Project

PLANNER = ROOT / "templates" / "roles" / "planner.md"
# 설계 10장의 체크리스트 순서 그대로
CHECKLIST = ["목적과 성공 기준", "사용자와 상황", "범위", "사용자 흐름", "화면 목록", "데이터와 상태", "오류",
             "비기능 요구", "기술 스택과 실행 환경", "인터페이스 계약", "브랜드 자산과 아는 레퍼런스", "범위 밖"]
HEREDOC = re.compile(r"ask-user --task T-xxx --json - <<'EOF'\n(.*?)\nEOF", re.S)


def section(text: str, title: str) -> str:
    start = text.index(f"## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class PlannerDocTest(unittest.TestCase):
    def setUp(self):
        self.text = PLANNER.read_text(encoding="utf-8")

    def test_checklist_is_the_design_list(self):
        items = re.findall(r"(?m)^(\d+)\. (.+)$", section(self.text, "인터뷰 체크리스트"))
        self.assertEqual([int(n) for n, _ in items], list(range(1, 13)))
        self.assertEqual([t for _, t in items], CHECKLIST)
        for word in ("`미정`", "`결정`", "`자동 결정`", "`범위 밖`"):
            self.assertIn(word, section(self.text, "인터뷰 체크리스트"))

    def test_examples_are_valid_questions(self):
        found = [json.loads(x) for x in HEREDOC.findall(self.text)]
        self.assertEqual(len(found), 2)  # 보통 질문 하나, 확정 질문 하나
        for obj in found:
            outbox.validate_render(obj, "기획")  # ask-user 가 받는 형식 그대로다(어기면 exit 2)
        confirm = found[-1]
        self.assertEqual([o["label"] for o in confirm["options"]], ["확정 (추천)", "수정할 부분 있음"])
        for part in ("계획 핵심", "자동 결정", "태스크 그래프"):
            self.assertIn(part, confirm["context"])

    def test_confirmation_resume_and_review_rules(self):
        confirm = section(self.text, "확정 질문")
        for needle in ("마지막 질문은 늘 확정 질문이다", "`plan check` 가 통과한 뒤", "확정 질문을 다시 한다"):
            self.assertIn(needle, confirm)
        review = section(self.text, "리뷰 기준(리뷰어가 본다)")
        for needle in ("ask-user --task <이 태스크> --history", "답이 `확정 (추천)` 이다", "12항목", "`render.context`"):
            self.assertIn(needle, review)
        self.assertIn("--wait <id>", section(self.text, "사용자에게 묻기"))
        self.assertIn("designer 태스크", section(self.text, "tasks.toml 형식"))
        # plan.py 의 디렉터 규칙: director 직무가 있으면 director 태스크 하나, 에셋 전용이 아닌 designer 는 그것에 의존
        self.assertIn("director 태스크를 정확히 하나", section(self.text, "tasks.toml 형식"))

    def test_designer_task_names_the_designer_outputs(self):
        # 실환경(2단계): planner 문서가 designer 산출물 이름을 말하지 않아 기획자가 design.md·mockup.html 을 지어
        # 사양에 적었고 designer 는 직무 문서(index.html·notes.md) 대신 사양을 따랐다. 기획자는 직무 문서의 이름을 쓴다.
        designer = (ROOT / "templates" / "roles" / "designer.md").read_text(encoding="utf-8")
        outputs = re.findall(r"(?m)^- `(docs/design/screens/<화면>/[^`]+)`", section(designer, "산출물"))
        self.assertEqual(outputs, ["docs/design/screens/<화면>/index.html", "docs/design/screens/<화면>/notes.md"])
        fmt = section(self.text, "tasks.toml 형식")
        for path in outputs:
            self.assertIn(f"`{path}`", fmt)


class FixRoundQuestionTest(TeamCase):
    """수정 라운드의 기획자는 앞 라운드의 열린 질문을 새로 묻지 않고 기다린다(설계 10장)."""

    QUESTION = {"question": "저장 위치는?\n예: 파일이면 서버가 필요 없다", "context": "앞선 답: 웹 앱이다",
                "options": [{"label": "파일 (추천)", "description": "추천 사유: 서버가 없다"},
                            {"label": "DB", "description": "서버가 필요하다"}]}

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)
        self.env["HTEAM_ASK_TIMEOUT"] = "0.3"

    def ask(self):
        term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]
        return self.hteam("ask-user", "--task", "T-001", "--json", "-", as_=None, terminal=term,
                          stdin=json.dumps(self.QUESTION))

    def test_open_question_carries_into_fix_round(self):
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        code, out = self.ask()
        self.assertEqual((code, out.get("id")), (4, "out-0001"), out)  # 답을 받기 전에 r1 이 끝났다
        self.act_work("T-001", {"docs/planning/spec.md": "초안\n"}, outcome="failed")
        code, out = self.hteam("fix", "T-001", "--note=인터뷰를 이어 한다")
        self.assertEqual((code, out.get("round")), (0, 2), out)
        work = (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("`.herdr-team/bin/hteam ask-user --task T-001 --wait <id>` 로 그 답을 기다린다", work)
        code, out = self.hteam("ask-user", "--task", "T-001", "--history", as_=None)
        self.assertEqual([(i["id"], i["answer"]) for i in out["history"]], [("out-0001", None)])
        shown = out["history"][0]["render"]  # 리뷰어가 사용자에게 보인 그대로 본다(context·선택지)
        self.assertEqual((shown["context"], [o["label"] for o in shown["options"]]), ("앞선 답: 웹 앱이다", ["파일 (추천)", "DB"]))
        self.assertEqual([q["id"] for q in outbox.open_questions(self.p)], ["out-0001"])  # r2 도 working 이다
        code, out = self.ask()  # r2 워커가 같은 질문을 새로 하면 열린 질문 때문에 거부된다
        self.assertEqual((code, out["error"]["code"], out.get("id")), (3, "question_open", "out-0001"), out)
        self.assertEqual(self.hteam("answer", "out-0001", "파일 (추천)", as_="main")[0], 0)
        code, out = self.hteam("ask-user", "--task", "T-001", "--wait", "out-0001", as_=None)
        self.assertEqual((code, out.get("answer")), (0, "파일 (추천)"), out)


    def test_confirmed_answer_before_ack_is_pending_in_the_next_round(self):
        # 확정 질문의 답을 받은 뒤 ack 전에 r1 워커가 끝났다. r2 의 기획자는 --pending 으로 그 답을 보고 반영한다(다시 묻지 않는다)
        confirm = {"header": "기획 확정", "question": "이 계획으로 확정할까요?\n예: 확정하면 디자인이 시작된다",
                   "context": "## 계획 핵심\n- 할 일 앱",
                   "options": [{"label": "확정 (추천)", "description": "추천 사유: 빠진 항목이 없다"},
                               {"label": "수정할 부분 있음", "description": "고칠 곳을 알려 준다"}]}
        self.write_spec("T-001", "planner")
        state.create(self.p, "T-001", "planner")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]
        code, out = self.hteam("ask-user", "--task", "T-001", "--json", "-", as_=None, terminal=term,
                               stdin=json.dumps(confirm))
        self.assertEqual((code, out.get("id")), (4, "out-0001"), out)
        self.assertEqual(self.hteam("answer", "out-0001", "확정 (추천)", as_="main")[0], 0)
        self.act_work("T-001", {"docs/planning/spec.md": "초안\n"}, outcome="failed")  # ack 전에 끝났다
        self.assertEqual(self.hteam("fix", "T-001", "--note=확정 답을 반영한다")[0], 0)
        work = (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("`.herdr-team/bin/hteam ask-user --task T-001 --pending`", work)
        code, out = self.hteam("ask-user", "--task", "T-001", "--pending", as_=None)
        self.assertEqual([(i["id"], i["answer"], i["round"]) for i in out["pending"]], [("out-0001", "확정 (추천)", 1)])
        code, out = self.hteam("ask-user", "--task", "T-001", "--history", as_=None)
        self.assertEqual([o["label"] for o in out["history"][0]["render"]["options"]], ["확정 (추천)", "수정할 부분 있음"])
        self.assertEqual(outbox.open_questions(self.p), [])  # 답이 왔으므로 열린 질문이 아니다
        term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]
        self.assertEqual(self.hteam("ask-user", "--task", "T-001", "--ack", "out-0001", as_=None, terminal=term)[0], 0)
        self.assertEqual(self.hteam("ask-user", "--task", "T-001", "--pending", as_=None)[1]["pending"], [])


if __name__ == "__main__":
    unittest.main()
