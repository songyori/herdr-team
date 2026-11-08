"""묶음 후속(설계 8.4): hteam followups 의 대상·마지막 리뷰·절 추출·빈 항목·후속 처리 태스크·인자."""
import json
import os
import unittest
from unittest import mock

from tests.helpers import TeamCase
from hteam import followups, state
from hteam.paths import Project


class SectionItemsTest(unittest.TestCase):
    def test_id_item_is_never_empty(self):
        for item in ("r1-F2 해당 없음 문구 — 고친다", "r2-F1 없음"):
            self.assertFalse(followups.is_empty(item), item)
        self.assertFalse(followups.is_empty("없음표 정리 — 표 머리를 맞춘다"))

    def test_none_with_reason_is_empty(self):
        for item in ("없음", "없음.", "(없음)", "해당 없음", "해당없음", "**없음**", "해당 없음(묶음 리뷰 아님)",
                     "해당 없음 — 묶음 리뷰가 아니다"):
            self.assertTrue(followups.is_empty(item), item)

    def test_items_join_continuations_and_skip_other_bullets(self):
        text = ("## 후속\n- r1-F2 [P2] a.py:1 — 길다.\n  다음 줄로 잇는다.\n* 별표 글머리\n1. 번호 글머리\n- 없음\n"
                "## 회귀\n- 해당 없음\nVERDICT: APPROVE\n")
        self.assertEqual(followups.section_items(text, "후속"), ["r1-F2 [P2] a.py:1 — 길다. 다음 줄로 잇는다."])
        self.assertEqual(followups.section_items(text, "회귀"), [])
        self.assertEqual(followups.section_items(text, "기획 누락"), [])


REVIEW = """# {tid} r{n} 리뷰
## 판정 근거
- 근거
## 이전 지적 확인
- 해당 없음
## 지적 사항
- 없음
## 후속
{followups}
## 기획 누락
{gaps}
## 회귀
{regressions}
## 직접 확인한 것
- 실행했다

VERDICT: APPROVE
"""


class FollowupsTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)

    def task(self, tid, role="developer", status="done", rounds=(1,), depends=None, change="바꿀 것", owns=None):
        body = f"## Target\n대상\n\n## Change\n{change}\n\n## Constraints\n제약\n\n## Acceptance\n- 확인\n"
        self.write_spec(tid, role, depends=depends, body=body, owns=owns)
        with mock.patch.dict(os.environ, self.env, clear=True):
            state.create(self.p, tid, role)
            with state.edit(self.p, tid) as st:
                st.update(status=status, round=max(rounds), base=self.head(),
                          rounds=[{"round": n, "reviews": [], "work": {}} for n in rounds])

    def review(self, tid, n, followups="- 없음", gaps="- 없음", regressions="- 해당 없음(묶음 리뷰 아님)"):
        self.commit(f"docs/reviews/{tid}/r{n}.md",
                    REVIEW.format(tid=tid, n=n, followups=followups, gaps=gaps, regressions=regressions),
                    f"[{tid}] review r{n}: APPROVE")

    def followups(self, *args):
        return self.hteam("followups", *args, as_=None)

    def test_group_collects_latest_round_of_members(self):
        self.task("T-001", rounds=(1, 2))
        self.review("T-001", 1, followups="- r1-F9 [P2] src/a.py:1 — 옛 라운드.")
        self.review("T-001", 2, followups="- r2-F2 [P2] src/a.py:3 — 중복.\n  두 함수가 같다.")
        self.task("T-002")
        self.review("T-002", 1, gaps="- 비밀번호 규칙이 사양에 없다. 정해야 한다.")
        self.task("T-009", role="designer")
        self.task("T-003", role="tester", depends="T-001, T-002, T-009")
        self.review("T-003", 1, followups="- r1-F3 [P3] tests/grp/test_a.py:5 — 도우미 중복.",
                    regressions="- r1-F4 test_flow — 원인 T-001. 경계 버그.\n- 작업 중 파일 의심: lib/x.py")
        code, out = self.followups("T-003")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["tasks"], ["T-001", "T-002", "T-003"])
        self.assertEqual(out["regressions"], [
            {"task": "T-003", "round": 1, "id": "r1-F4", "text": "r1-F4 test_flow — 원인 T-001. 경계 버그."},
            {"task": "T-003", "round": 1, "id": None, "text": "작업 중 파일 의심: lib/x.py"}])
        self.assertEqual(out["followups"], [
            {"task": "T-001", "round": 2, "id": "r2-F2", "text": "r2-F2 [P2] src/a.py:3 — 중복. 두 함수가 같다."},
            {"task": "T-003", "round": 1, "id": "r1-F3", "text": "r1-F3 [P3] tests/grp/test_a.py:5 — 도우미 중복."}])
        self.assertEqual(out["planning_gaps"], [
            {"task": "T-002", "round": 1, "id": None, "text": "비밀번호 규칙이 사양에 없다. 정해야 한다."}])
        self.assertEqual(list(out), ["ok", "tasks", "regressions", "followups", "planning_gaps"])
        self.assertEqual(self.followups("T-003"), (code, out))  # 두 번 불러도 같다

    def test_non_tester_task_is_alone(self):
        self.task("T-001", role="planner")
        self.review("T-001", 1, followups="- r1-F1 [P2] docs/planning/spec.md:1 — 다듬기.")
        code, out = self.followups("T-001")
        self.assertEqual((code, out["tasks"], len(out["followups"])), (0, ["T-001"], 1), out)

    def test_rest_only_done_ungrouped_developers(self):
        self.task("T-001")
        self.task("T-002", status="working")
        self.task("T-003", role="designer")
        self.task("T-004")
        self.task("T-005", role="tester", status="dropped", depends="T-004")
        self.task("T-006")
        self.review("T-006", 1, followups="- r1-F1 [P2] src/b.py:1 — 이름.")
        code, out = self.followups("--rest")
        self.assertEqual((code, out["tasks"]), (0, ["T-001", "T-006"]), out)
        self.assertEqual([x["id"] for x in out["followups"]], ["r1-F1"])

    def test_followup_derived_task_skips_followups(self):
        self.task("T-004", change="출처: T-003 followups\nr1-F3 [P3] 도우미 중복")
        self.review("T-004", 1, followups="- r1-F1 [P2] src/a.py:1 — 또 다듬기.", gaps="- 정책이 없다.")
        code, out = self.followups("T-004")
        self.assertEqual((code, out["followups"], len(out["planning_gaps"])), (0, [], 1), out)

    def test_unreadable_spec_is_not_derived(self):
        self.task("T-004", change="출처: rest followups")
        self.review("T-004", 1, followups="- r1-F1 [P2] src/a.py:1 — 다듬기.")
        (self.proj / ".herdr-team/tasks/T-004.md").write_bytes(b"\xff\xfe")
        code, out = self.followups("T-004")
        self.assertEqual((code, len(out["followups"])), (0, 1), out)

    def test_old_format_and_hteam_rejection_give_nothing(self):
        self.task("T-001")
        self.commit("docs/reviews/T-001/r1.md", "# T-001 r1 리뷰\n## 지적 사항\n- [P2] a.py:1 — 옛 형식.\n\nVERDICT: APPROVE\n",
                    "[T-001] review r1: APPROVE")
        self.task("T-002")
        self.commit("docs/reviews/T-002/r1.md", "# T-002 r1 리뷰 (출처: hteam 테스트 관문)\n\n## 지적 사항\n- [P1] hteam 테스트 "
                    "관문: quick 이 통과하지 못했다.\n\nVERDICT: REQUEST_CHANGES\n", "[T-002] review r1: REQUEST_CHANGES")
        self.task("T-003")  # 리뷰 파일이 없다
        for tid in ("T-001", "T-002", "T-003"):
            code, out = self.followups(tid)
            self.assertEqual((code, out["regressions"], out["followups"], out["planning_gaps"]), (0, [], [], []), out)

    def test_argument_rules(self):
        for args in ((), ("T-001", "--rest")):
            code, out = self.followups(*args)
            self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                             (2, "usage", "태스크 ID 와 --rest 중 하나만 준다"), args)
        code, out = self.followups("T-009")
        self.assertEqual((code, out["error"]["code"]), (2, "not_started"))
        code, out = self.followups("x")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_task_id"))
        self.assertEqual(json.loads(json.dumps(out))["ok"], False)


if __name__ == "__main__":
    unittest.main()
