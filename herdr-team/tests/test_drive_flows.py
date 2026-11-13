"""관제 자동화(설계 8.4 묶음 처리·마무리·확정 질문, 8.9 기획 적용·디자인 단계·관제가 만드는 태스크·중복 방지, 8.7 의 6·7,
7.4 의 답 파일에만 있는 결정): 관제 객체의 함수를 이 프로세스에서 바로 부른다(관제 환경, setup_run 의 Run).

start-ready·자식 프로세스 띄우기는 가짜로 바꾼다(그 동작은 Task 6 의 시험이 본다). 상태 파일은 시험이 직접 쓴다."""
import json
import re
import unittest
from unittest import mock

from tests.helpers import BASE_CONFIG, CREW_CONFIG, TeamCase
from hteam import approval, outbox, specs, state, tasks, testgate
from hteam.errors import HteamError
from hteam.paths import Project

LOCAL_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
CONSTRAINTS = "다른 태스크의 소유 경로와 이 태스크 범위 밖은 건드리지 않는다"
REGRESSION_ACCEPT_RUN = "- 이 항목의 실패한 테스트(항목에 적힌 이름)를 직접 돌리는 명령이 통과하고 그 명령과 출력 원문이 보고서에 있다"
CLEANUP_ACCEPT = "- 항목마다 고쳤거나 고치지 않은 이유를 보고서에 적었다"
SUPPLEMENT_CHANGE = ("화면 디자이너의 시스템 추가 제안이다. 제안마다 받아들일지 정해 디자인 시스템에 더하고, 결정과 이유를 출처(태스크 "
                     "ID·라운드)와 함께 docs/design/direction.md 에 적는다.")
SUPPLEMENT_ACCEPT = "- 제안마다 반영 여부와 이유가 출처와 함께 `docs/design/direction.md` 에 있다"
CONFIRM_QUESTION = ("커밋된 [test] 명령을 리뷰 전에 자동으로 돌려도 되는가\n"
                    "예: 확정하면 다음 리뷰부터 quick 이 돌고 묶음 리뷰와 마무리가 full 을 돈다")

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

DESIGN_CONFIG = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["designer"]') + """
[roles.director]
title = "디자인 디렉터"
owns = ["docs/design/**", "assets/**"]

[roles.designer]
title = "디자인"
owns = ["docs/design/**", "assets/**"]
"""

PLAN_TWO = """[[task]]
key = "store"
role = "developer"
title = "저장 모듈"
owns = ["src/store/**"]
target = "src/store/"
change = "할 일을 저장한다"
constraints = "표준 라이브러리만"
acceptance = ["저장한 할 일을 다시 읽는다"]

[[task]]
key = "screen"
role = "developer"
title = "할 일 화면"
owns = ["src/ui/**"]
depends_on = ["store"]
target = "src/ui/"
change = "할 일 목록을 그린다"
constraints = "표준 라이브러리만"
acceptance = ["목록이 보인다"]
"""

PLAN_THIRD = PLAN_TWO + """
[[task]]
key = "settings"
role = "developer"
title = "설정"
owns = ["src/settings/**"]
depends_on = ["screen"]
target = "src/settings/"
change = "설정을 읽는다"
constraints = "표준 라이브러리만"
acceptance = ["설정이 읽힌다"]
"""


def body(target="대상", change="바꿀 것"):
    return f"## Target\n{target}\n\n## Change\n{change}\n\n## Constraints\n제약\n\n## Acceptance\n- 확인\n"


class FlowCase(TeamCase):
    config = BASE_CONFIG
    roles = ("planner", "developer", "tester")

    def setUp(self):
        super().setUp()
        self.init_project(config=self.config, roles=self.roles)
        self.setup_run()
        self.p = Project(self.proj)
        patcher = self.in_drive()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.d = self.make_drive()
        # start-ready·자식 프로세스는 이 시험의 대상이 아니다(Task 6). 불렸는지만 본다
        for name, value in (("start_ready", None), ("spawn", None), ("running", False)):
            stub = mock.patch.object(self.d, name, return_value=value)
            setattr(self, name, stub.start())
            self.addCleanup(stub.stop)

    # --- 상태 준비 ---
    def task(self, tid, role="developer", status="done", rounds=(1,), *, depends=None, owns=None, title=None,
             front=None, verdict="APPROVE", base=None, change="바꿀 것", started="2026-01-01T00:00:00Z"):
        """사양(커밋)과 상태를 바로 쓴다(워커는 띄우지 않는다). owns 는 직무마다 겹치지 않게 태스크 이름으로 나눈다."""
        if owns is None:
            owns = {"developer": [f"src/{tid.lower()}/**"], "planner": ["docs/planning/**"],
                    "designer": [f"docs/design/screens/{tid.lower()}/**"], "director": ["docs/design/**"],
                    "tester": [f"tests/{tid.lower()}/**", f"docs/qa/{tid.lower()}.md"]}[role]
        self.write_spec(tid, role, title=title or f"{tid} 일", owns=", ".join(owns), depends=depends, front=front,
                        body=body(change=change))
        state.create(self.p, tid, role)
        with state.edit(self.p, tid) as st:
            last = max(rounds) if rounds else 0
            st.update(round=last, base=base, owns=list(owns),
                      rounds=[{"round": n, "round_base": base, "agent": "claude", "model": None, "effort": None,
                               "note": None, "supplement": None,
                               "work": {"title": f"{tid} r{n} 작업", "horch_task": None, "dispatch": None,
                                        "launched": None, "error": None, "canceled": False, "cleaned": True},
                               "reviews": [], "verdict": verdict if n == last else "REQUEST_CHANGES"}
                              for n in rounds])
            if rounds:
                st["history"].append({"at": started, "from": "pending", "to": "launch_failed", "event": "start",
                                      "round": 1})
            if status != "pending":
                state.move(st, status, "test")

    def set_state(self, tid, **fields):
        with state.edit(self.p, tid) as st:
            st.update(fields)

    def review(self, tid, n, followups="- 없음", gaps="- 없음", regressions="- 해당 없음(묶음 리뷰 아님)"):
        self.commit(f"docs/reviews/{tid}/r{n}.md",
                    REVIEW.format(tid=tid, n=n, followups=followups, gaps=gaps, regressions=regressions),
                    f"[{tid}] review r{n}: APPROVE")

    def batch(self, *, key="calc-test", tester_status="done", rounds1=(1,)):
        """묶음: developer T-001·T-002 와 tester T-003(plan_key)."""
        self.task("T-001", rounds=rounds1)
        self.task("T-002")
        self.task("T-003", "tester", tester_status, depends="T-001, T-002", front={"plan_key": key},
                  owns=[f"tests/{key}/**", f"docs/qa/{key}.md"])

    def crew(self, **since):
        """crew.json 의 고정 에이전트(설계 5.9.1). since 는 이름 → since_reset."""
        data = {name: {"terminal": None, "terminal_argv": None, "agent": "claude", "model": "opus", "effort": "xhigh",
                       "space": "spA", "tab": None, "work_pane": None, "view": None, "task": None, "dispatch": None,
                       "queue": [], "since_reset": n, "reset_tasks": [f"T-{i:03d}" for i in range(1, n + 1)],
                       "reset_pending": False, "resetting": None}
                for name, n in since.items()}
        (self.state_dir / "crew.json").write_text(json.dumps(data), encoding="utf-8")

    def answer(self, oid, text="처리했다", **extra):
        path = self.state_dir / "answers" / f"{oid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"id": oid, "answer": text, "at": "2026-01-01T00:00:00Z", **extra},
                                   ensure_ascii=False), encoding="utf-8")

    # --- 읽기 ---
    def spec(self, tid):
        return specs.load(self.p, tid)

    def subject(self, rev="HEAD"):
        return self.git("log", "-1", "--format=%s", rev).strip()

    def tracked_clean(self, rel):
        return bool(self.git("ls-files", "--", rel).strip()) and not self.git("status", "--porcelain", "--", rel).strip()

    def items(self, type_):
        return [e for e in self.outbox_items() if e["type"] == type_]

    def decides(self, kind=None):
        return [e for e in self.items("decide") if kind is None or e["kind"] == kind]

    def progress(self):
        return [e["body"] for e in self.items("progress")]

    def finish(self):
        path = self.drive_dir / "finish.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def log_lines(self):
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def ids(self):
        return [s["id"] for s in state.all_states(self.p)]

    def from_source(self, source):
        """사양 `## Change` 첫 줄이 `출처: <source> followups` 인 태스크(설계 8.4 SOURCE_RE)."""
        found = []
        for tid in specs.list_ids(self.p):
            first = self.spec(tid).sections.get("Change", "").splitlines()[:1]
            if first == [f"출처: {source} followups"]:
                found.append(tid)
        return found


class BatchTest(FlowCase):
    """묶음 처리 batch_done(설계 8.4): 리셋 표시 → 후속 → finish.json batches·progress."""

    config = CREW_CONFIG

    def test_regression_with_one_cause_makes_fix_task(self):
        self.use_gate()  # 확정한 [test]: Acceptance 가 둘이다
        self.batch()
        item = "r1-F4 [P1] tests/calc-test/test_flow.py::test_add 가 실패한다 — 원인은 T-001 의 add 부호다(T-003 묶음)"
        self.review("T-003", 1, regressions=f"- {item}")
        self.d.batch_done("T-003")
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003", "T-004"])
        sp = self.spec("T-004")
        self.assertEqual((sp.role, sp.title, sp.owns), ("developer", "회귀 수정: " + item[:40], ["src/t-001/**"]))
        self.assertEqual(sp.sections["Target"], "src/t-001/**")
        self.assertEqual(sp.sections["Change"], f"출처: T-003 followups\n{item}")
        self.assertEqual(sp.sections["Constraints"], CONSTRAINTS)
        self.assertEqual(sp.sections["Acceptance"], f"{REGRESSION_ACCEPT_RUN}\n- `hteam test T-004` 가 통과한다")
        self.assertEqual(self.subject(), "spec: T-004")
        self.assertTrue(self.tracked_clean(".herdr-team/tasks/T-004.md"))
        self.assertEqual(self.task_state("T-004")["status"], "pending")
        self.assertTrue(any(re.fullmatch(rf"{LOCAL_ISO} T-004 생성 \[developer\] 회귀 수정: .+", line)
                            for line in self.log_lines()), self.log_lines())
        self.assertEqual(self.decides(), [])
        self.assertEqual(self.finish()["batches"], ["T-003"])
        self.assertEqual(self.progress(), ["묶음 완료: T-003"])
        self.start_ready.assert_called_once_with()

    def test_regression_acceptance_is_one_line_before_confirm(self):
        self.use_gate(approve=False)  # 확정하지 않은 [test]: hteam test 가 돌지 않는다
        self.batch()
        self.review("T-003", 1, regressions="- r1-F1 [P1] test_x 실패 — T-002 탓")
        self.d.batch_done("T-003")
        self.assertEqual(self.spec("T-004").sections["Acceptance"], REGRESSION_ACCEPT_RUN)
        self.assertEqual(self.spec("T-004").owns, ["src/t-002/**"])

    def test_regression_without_one_cause_is_decide(self):
        self.batch()
        none = "r1-F1 [P1] test_a 실패 — 원인을 모르겠다(T-003 의 테스트만 본다)"  # 자기 태스크는 원인이 아니다
        many = "r1-F2 [P1] test_b 실패 — T-001 과 T-002 가 같이 바꿨다"
        outside = "r1-F3 [P1] test_c 실패 — T-009 탓"  # 묶음 밖 태스크는 원인으로 보지 않는다
        self.review("T-003", 1, regressions=f"- {none}\n- {many}\n- {outside}")
        self.d.batch_done("T-003")
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003"])
        found = self.decides("unknown_regression")
        self.assertEqual([d["summary"] for d in found], [none, many, outside])
        for d in found:
            self.assertEqual((d["task"], d["files"], d["source"]),
                             ("T-003", ["docs/reviews/T-003/r1.md"], "출처: T-003 followups"))
            self.assertEqual(d["commands"], ['hteam task new --role <원인 태스크 직무> --title "회귀 수정: <요약>"'])
        self.assertEqual(self.finish()["batches"], ["T-003"])
        self.start_ready.assert_not_called()  # 만든 태스크가 없다

    def test_regression_summary_is_cut_to_300(self):
        self.batch()
        long = "r1-F1 [P1] " + "가" * 400
        self.review("T-003", 1, regressions=f"- {long}")
        self.d.batch_done("T-003")
        self.assertEqual(self.decides("unknown_regression")[0]["summary"], long[:300])

    def test_followups_become_one_cleanup_task_per_role(self):
        self.batch(rounds1=(1, 2))
        a = "r2-F2 [P2] src/t-001/a.py:3 — 중복."
        b = "r1-F1 [P3] src/t-002/b.py:1 — 이름이 길다."
        c = "r1-F3 [P2] tests/calc-test/test_flow.py:9 — 준비 코드 중복."
        no_id = "QA 보고서 재현 절차가 짧다."
        self.review("T-001", 2, followups=f"- {a}")
        self.review("T-002", 1, followups=f"- {b}")
        self.review("T-003", 1, followups=f"- {c}\n- {no_id}")
        self.d.batch_done("T-003")
        dev, test = self.spec("T-004"), self.spec("T-005")
        self.assertEqual((dev.role, dev.title, dev.owns), ("developer", "묶음 정리: calc-test",
                                                           ["src/t-001/**", "src/t-002/**"]))
        self.assertEqual(dev.sections["Change"], f"출처: T-003 followups\n- r2-F2: {a}\n- r1-F1: {b}")
        self.assertEqual(dev.sections["Target"], "src/t-001/**, src/t-002/**")
        self.assertEqual(dev.sections["Acceptance"], CLEANUP_ACCEPT)
        self.assertEqual((test.role, test.title, test.owns), ("tester", "묶음 정리: calc-test",
                                                              ["docs/qa/calc-test.md", "tests/calc-test/**"]))
        self.assertEqual(test.sections["Change"], f"출처: T-003 followups\n- r1-F3: {c}\n- -: {no_id}")
        self.assertEqual(self.from_source("T-003"), ["T-004", "T-005"])
        self.start_ready.assert_called_once_with()

    def test_cleanup_owns_beyond_role_is_decide(self):
        self.batch()
        self.set_state("T-002", owns=["lib/**"])  # 설정을 바꿔 직무 owns(src/**) 밖이 된 태스크
        a = "r1-F1 [P2] src/t-001/a.py:1 — 중복."
        b = "r1-F2 [P2] lib/b.py:1 — 이름."
        self.review("T-001", 1, followups=f"- {a}")
        self.review("T-002", 1, followups=f"- {b}")
        self.d.batch_done("T-003")
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003"])
        self.assertFalse((self.team / "tasks" / "T-004.md").exists())
        [d] = self.decides("escalation")
        self.assertEqual(d["task"], "T-003")
        self.assertTrue(d["summary"].startswith("묶음 정리 태스크(developer)를 만들지 못했다: owns_too_wide: "), d)
        self.assertEqual([i["text"] for i in d["items"]], [a, b])

    def test_planning_gaps_are_one_decide(self):
        self.batch()
        g1 = "비밀번호 규칙이 사양에 없다. 길이와 문자 종류를 정해야 한다. " * 2
        g2 = "빈 목록일 때 무엇을 보일지 정하지 않았다."
        self.review("T-002", 1, gaps=f"- {g1.strip()}")
        self.review("T-003", 1, gaps=f"- {g2}")
        self.d.batch_done("T-003")
        [d] = self.decides("planning_gaps")
        self.assertEqual(d["task"], "T-003")
        self.assertEqual(d["summary"], f"기획 누락 2건: {g1.strip()[:60]}; {g2[:60]}")
        self.assertEqual(d["files"], ["docs/reviews/T-002/r1.md", "docs/reviews/T-003/r1.md"])
        self.assertEqual(d["commands"], ['hteam scope T-xxx "<추가 범위>"',
                                         'hteam task new --role planner --title "<증분 기획>"'])
        self.assertEqual([i["text"] for i in d["items"]], [g1.strip(), g2])
        self.assertEqual(d["source"], "출처: T-003 followups")

    def test_reset_marks_come_first_and_only_once(self):
        self.crew(production=2, test=0)
        self.batch()
        self.review("T-003", 1, followups="- r1-F1 [P2] tests/calc-test/x.py:1 — 정리.")
        self.d.batch_done("T-003")
        crew = json.loads((self.state_dir / "crew.json").read_text())
        self.assertEqual((crew["production"]["reset_pending"], crew["test"]["reset_pending"]), (True, False))
        self.assertEqual(self.progress(), ["묶음 완료: T-003. 리셋할 에이전트: production"])
        self.d.batch_done("T-003")  # 같은 묶음은 다시 처리하지 않는다(batches)
        self.assertEqual(self.progress(), ["묶음 완료: T-003. 리셋할 에이전트: production"])
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003", "T-004"])

    def test_followup_task_starts_after_reset_in_new_session(self):
        # 리셋 표시가 후속 태스크보다 먼저다. 그래서 후속 태스크는 리셋을 기다린다(배정 5.9.4 의 4, orca §17 P2-4)
        self.crew(production=1)
        self.batch()
        self.review("T-002", 1, followups="- r1-F1 [P2] src/t-002/a.py:1 — 정리.")
        self.d.batch_done("T-003")
        code, out = self.hteam("start", "T-004")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["reason"]), ("waiting", "agent"))
        self.assertEqual(self.task_state("T-004")["status"], "pending")

    def test_death_during_marks_is_redone_without_duplicates(self):
        self.crew(production=1)
        self.batch()
        self.review("T-002", 1, followups="- r1-F1 [P2] src/t-002/a.py:1 — 정리.")
        with mock.patch.object(self.d, "create_task", side_effect=RuntimeError("관제가 죽었다")):
            with self.assertRaises(RuntimeError):
                self.d.batch_done("T-003")
        self.assertTrue(json.loads((self.state_dir / "crew.json").read_text())["production"]["reset_pending"])
        self.assertNotIn("T-003", self.finish().get("batches", []))  # 다음 재확인이 다시 한다
        self.assertEqual(self.progress(), [])
        self.d.batch_done("T-003")
        self.assertEqual(self.from_source("T-003"), ["T-004"])
        self.assertEqual(self.finish()["batches"], ["T-003"])
        self.assertEqual(self.progress(), ["묶음 완료: T-003. 리셋할 에이전트: production"])

    def test_source_line_keeps_tasks_from_being_made_twice(self):
        self.batch()
        self.review("T-002", 1, followups="- r1-F1 [P2] src/t-002/a.py:1 — 정리.")
        self.d.batch_done("T-003")
        (self.drive_dir / "finish.json").unlink()  # 기록을 잃어도 `출처: T-003 followups` 태스크가 있으면 만들지 않는다
        self.d.batch_done("T-003")
        self.assertEqual(self.from_source("T-003"), ["T-004"])
        self.assertEqual(self.finish()["batches"], ["T-003"])

    def test_corrupt_finish_record_is_empty(self):
        self.batch()
        self.drive_dir.mkdir(parents=True, exist_ok=True)
        (self.drive_dir / "finish.json").write_text("{깨짐", encoding="utf-8")
        self.d.batch_done("T-003")
        self.assertEqual(self.finish()["batches"], ["T-003"])

    def test_unbatched_done_testers_are_processed(self):
        # 재확인(설계 8.7 의 6): finish.json batches 에 없는 done tester 만 묶음 처리한다
        self.batch()
        self.task("T-004", "developer")
        self.task("T-005", "tester", depends="T-004", front={"plan_key": "second"},
                  owns=["tests/second/**", "docs/qa/second.md"])
        self.task("T-006", "tester", "working", front={"plan_key": "third"},
                  owns=["tests/third/**", "docs/qa/third.md"])
        self.drive_dir.mkdir(parents=True, exist_ok=True)
        (self.drive_dir / "finish.json").write_text(json.dumps({"batches": ["T-003"]}), encoding="utf-8")
        self.d.unbatched()
        self.assertEqual(self.finish()["batches"], ["T-003", "T-005"])
        self.assertEqual(self.progress(), ["묶음 완료: T-005"])


class FinishTest(FlowCase):
    """마무리 finish_step(설계 8.4 의 1–7)."""

    def all_done(self):
        self.task("T-001", rounds=(1, 2), title="계산", base=self.head(), started="2026-01-01T00:00:00Z")
        self.commit("src/app.py", "print(1)\n", "[T-001] r1")
        self.commit("README.md", "# proj\n바꿨다\n", "[T-001] r2")
        self.task("T-002", status="dropped", rounds=(1,), title="버린 것", verdict=None,
                  base=self.head(), started="2026-01-02T00:00:00Z")

    def done_items(self):
        return self.items("done")

    def test_waits_while_any_task_is_open(self):
        self.all_done()
        self.task("T-003", status="working")
        self.d.finish_step()
        self.assertEqual(self.done_items(), [])
        self.spawn.assert_not_called()

    def test_waits_for_open_judgment_decides(self):
        self.all_done()
        for kind in ("planning_gaps", "unknown_regression", "token_update"):
            oid = self.d.decide(kind, None, "판단을 기다린다")
            self.d.finish_step()
            self.assertEqual(self.done_items(), [], kind)
            self.answer(oid)
        self.d.decide("escalation", None, "다른 종류는 막지 않는다")
        self.d.finish_step()
        self.assertEqual(len(self.done_items()), 1)

    def test_done_once_with_tasks_and_changed_files(self):
        self.all_done()
        self.d.finish_step()
        [done] = self.done_items()
        self.assertEqual(done["from"], "drive")
        self.assertEqual(done["body"], "모든 태스크가 끝났다.\n"
                                       "- T-001 [developer] 계산: done, r2 APPROVE\n"
                                       "- T-002 [developer] 버린 것: dropped, r1 -\n"
                                       "바뀐 주요 파일: README.md, src/app.py")
        self.assertEqual(self.finish()["reported"], ["T-001", "T-002"])
        self.d.finish_step()
        self.assertEqual(len(self.done_items()), 1)  # 같은 태스크 묶음으로는 한 번만
        self.task("T-003")
        self.d.finish_step()
        self.assertEqual(len(self.done_items()), 2)  # 태스크가 늘었으면 다시 알린다

    def test_changed_files_start_at_the_first_round_even_if_base_moved(self):
        # 8단계(설계 8.4 의 7): 기준 병합(5.10.6)이 base 를 옮겨도 첫 라운드 이후의 앞 변경이 빠지지 않는다
        first = self.head()
        self.task("T-001", base=first)
        self.commit("src/early.py", "x\n", "[T-001] 앞 변경")
        moved = self.commit("src/late.py", "y\n", "[T-001] 뒤 변경")
        with state.edit(self.p, "T-001") as st:
            st["base"] = moved
        self.d.finish_step()
        lines = self.done_items()[0]["body"].splitlines()
        self.assertEqual(lines[-1], "바뀐 주요 파일: src/early.py, src/late.py")

    def test_changed_files_fall_back_to_base_without_round_base(self):
        # round_base 가 없는 옛 상태는 base 부터 센다(task 도우미는 round_base 를 늘 넣으므로 지워서 본다)
        first = self.head()
        self.task("T-001", base=first)
        with state.edit(self.p, "T-001") as st:
            st["rounds"][0].pop("round_base")
        self.commit("src/early.py", "x\n", "[T-001] 앞 변경")
        self.d.finish_step()
        lines = self.done_items()[0]["body"].splitlines()
        self.assertEqual(lines[-1], "바뀐 주요 파일: src/early.py")

    def test_changed_files_skip_team_folder_and_stop_at_15(self):
        self.task("T-001", base=self.head())
        for i in range(17):
            self.commit(f"src/f{i:02d}.py", "x\n", f"[T-001] f{i}")
        self.commit(".herdr-team/tasks/T-009.md", "사양\n", "spec: T-009")  # 사양 파일은 빼고 센다(orca §17 P3-12)
        self.d.finish_step()
        lines = self.done_items()[0]["body"].splitlines()
        self.assertEqual(lines[-1], "바뀐 주요 파일: " + ", ".join(f"src/f{i:02d}.py" for i in range(15)) + " …")

    def test_no_changed_files_line_when_nothing_changed(self):
        self.task("T-001", base=self.head())
        self.d.finish_step()
        self.assertEqual(self.done_items()[0]["body"], "모든 태스크가 끝났다.\n- T-001 [developer] T-001 일: done, r1 APPROVE")

    def test_rest_followups_once_before_done(self):
        self.task("T-001", base=self.head())
        self.review("T-001", 1, followups="- r1-F1 [P2] src/t-001/a.py:1 — 정리.",
                    gaps="- 오류 문구가 사양에 없다.")
        self.d.finish_step()
        [rest] = self.from_source("rest")
        self.assertEqual(self.spec(rest).title, "묶음 정리: rest")
        self.assertTrue(self.finish()["rest_done"])
        [gap] = self.decides("planning_gaps")
        self.assertEqual((gap["task"], gap["source"]), ("rest", "출처: rest followups"))
        self.assertEqual(self.done_items(), [])  # 새 태스크가 생겼으면 끝(그것들이 끝난 뒤 다시 온다)
        self.start_ready.assert_called_once_with()
        self.answer(gap["id"])
        self.set_state(rest, status="done", rounds=[{"round": 1, "reviews": [], "work": {}, "verdict": "APPROVE"}],
                       round=1)
        self.d.finish_step()
        self.assertEqual(self.from_source("rest"), [rest])  # 전역 한 번
        self.assertEqual(len(self.done_items()), 1)

    def test_runs_last_full_test_as_child_once(self):
        self.use_gate()
        self.all_done()
        self.d.finish_step()
        self.spawn.assert_called_once_with("final", ["test", "--full"])
        self.assertEqual(self.done_items(), [])
        self.running.return_value = True  # 자식이 도는 동안은 다시 띄우지 않는다
        self.d.finish_step()
        self.assertEqual(self.spawn.call_count, 1)

    def test_passed_full_test_writes_done_with_result(self):
        self.use_gate()
        self.all_done()
        self.d.final_done(0, {"ok": True, "task": None, "kind": "full", "status": "passed", "exit": 0,
                              "seconds": 12.5, "tail": "", "log": ".herdr-team/state/tests/logs/final-full-x.log"}, "")
        [done] = self.done_items()
        self.assertEqual(done["body"].splitlines()[-1], "마지막 전체 테스트: passed (12.5초)")
        self.assertEqual(self.finish()["reported"], ["T-001", "T-002"])

    def test_full_result_is_dropped_when_tasks_changed_during_the_run(self):
        """마지막 전체 테스트가 도는 동안 새 태스크가 생기면 그 결과로 done 을 쓰지 않는다(설계 8.4 의 6, final_ids)."""
        self.use_gate()
        self.all_done()
        self.d.finish_step()
        self.assertEqual(self.finish()["final_ids"], ["T-001", "T-002"])
        self.task("T-003", status="working")  # 테스트 중 메인이 새 태스크를 만들어 시작했다
        passed = {"ok": True, "task": None, "kind": "full", "status": "passed", "exit": 0, "seconds": 1.0, "tail": "",
                  "log": ".herdr-team/state/tests/logs/final-full-x.log"}
        self.d.final_done(0, passed, "")
        self.assertEqual((self.done_items(), self.decides()), ([], []))
        self.assertFalse(self.finish().get("reported"))
        self.assertNotIn("final_ids", self.finish())
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 마지막 전체 테스트 결과를 버린다\(그 사이 태스크가 바뀌었다\)$")
        self.set_state("T-003", status="done")  # 새 태스크도 끝났다: 늘어난 묶음으로 다시 돈다
        self.d.finish_step()
        self.assertEqual(self.spawn.call_count, 2)
        self.assertEqual(self.finish()["final_ids"], ["T-001", "T-002", "T-003"])
        self.d.final_done(0, passed, "")
        [done] = self.done_items()
        self.assertIn("- T-003 [developer] T-003 일: done, r1 APPROVE", done["body"])
        self.assertEqual(self.finish()["reported"], ["T-001", "T-002", "T-003"])

    def test_full_result_is_dropped_when_a_task_was_added_and_finished_during_the_run(self):
        self.use_gate()
        self.all_done()
        self.d.finish_step()
        self.task("T-003")  # 테스트 중 생겨서 이미 끝났다(목록만 다르다)
        self.d.final_done(1, {"ok": True, "task": None, "kind": "full", "status": "failed", "exit": 1, "seconds": 3.0,
                              "tail": "AssertionError", "log": ".herdr-team/state/tests/logs/final-full-x.log"}, "")
        self.assertEqual((self.decides(), self.done_items()), ([], []))
        self.assertNotIn("final_failed", self.finish())

    def test_failed_full_test_is_decide_then_runs_again_after_answer(self):
        self.use_gate()
        self.all_done()
        self.d.final_done(1, {"ok": True, "task": None, "kind": "full", "status": "failed", "exit": 1, "seconds": 3.0,
                              "tail": "AssertionError: 2 != 3", "log": ".herdr-team/state/tests/logs/final-full-x.log"},
                          "")
        [d] = self.decides("unknown_regression")
        self.assertEqual((d["task"], d["summary"], d["files"], d["tail"], d["source"]),
                         (None, "마지막 전체 테스트가 실패했다. 원인 태스크를 정해 회귀 수정 태스크를 만든다",
                          [".herdr-team/state/tests/logs/final-full-x.log"], "AssertionError: 2 != 3",
                          "출처: final followups"))
        self.assertEqual((self.finish()["final_failed"], self.finish()["final_decide"]), (["T-001", "T-002"], d["id"]))
        self.d.finish_step()
        self.spawn.assert_not_called()  # 답하기 전에는 다시 돌리지 않는다
        self.answer(d["id"])
        self.d.finish_step()
        self.spawn.assert_called_once_with("final", ["test", "--full"])
        self.assertNotIn("final_failed", self.finish())
        self.assertNotIn("final_decide", self.finish())

    def test_lock_timeout_is_only_logged(self):
        self.use_gate()
        self.all_done()
        self.d.final_done(4, {"ok": False, "error": {"code": "test_lock_timeout", "message": "잠금", "hint": ""}}, "")
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 전체 테스트 잠금 대기 초과. 다음 확인 때 다시 한다$")
        self.assertEqual((self.decides(), self.done_items(), self.finish()), ([], [], {}))

    def test_unapproved_full_test_asks_to_confirm(self):
        self.use_gate(approve=False)
        self.all_done()
        self.d.final_done(2, {"ok": False, "error": {"code": "test_unapproved", "message": "확정 전", "hint": ""}}, "")
        [q] = self.items("question")
        self.assertEqual(q["render"]["header"], "테스트 확정")
        self.assertEqual(self.decides(), [])

    def test_other_usage_error_is_test_config_decide(self):
        self.use_gate()
        self.all_done()
        self.d.final_done(2, {"ok": False, "error": {"code": "bad_test_config", "message": "형식", "hint": ""}},
                          "x" * 350 + "끝")
        [d] = self.decides("test_config")
        self.assertEqual(d["summary"], "전체 테스트를 돌리지 못했다(exit 2): " + ("x" * 350 + "끝")[-300:])
        self.assertEqual((d["files"], d["commands"]),
                         (["docs/planning/tasks.toml"], ['hteam task new --role planner --title "[test] 고치기"']))
        self.assertEqual(self.finish()["final_decide"], d["id"])
        self.d.final_done(2, {"ok": False, "error": {"code": "plan_unreadable", "message": "TOML 오류", "hint": ""}}, "")
        self.assertEqual(self.decides("test_config")[-1]["summary"], "전체 테스트를 돌리지 못했다(exit 2): TOML 오류")

    def test_bad_approvals_from_full_test_is_escalation(self):
        self.use_gate()
        self.all_done()
        self.d.final_done(1, {"ok": False, "error": {"code": "bad_test_approvals",
                                                     "message": "확정 기록이 손상됐다: /x/test-approvals.json",
                                                     "hint": ""}}, "")
        [d] = self.decides("escalation")
        self.assertIn("/x/test-approvals.json", d["summary"])
        self.assertEqual(self.decides("unknown_regression"), [])

    def test_unapproved_gate_asks_instead_of_running(self):
        self.use_gate(approve=False)
        self.all_done()
        self.d.finish_step()
        self.spawn.assert_not_called()
        self.assertEqual(len(self.items("question")), 1)
        self.d.finish_step()
        self.assertEqual(len(self.items("question")), 1)  # 같은 식별값은 한 번
        self.assertEqual(self.done_items(), [])

    def corrupt_state(self, tid):
        """읽지 못하는 상태 파일(진행 중이었을 수 있는 태스크). all_states 는 건너뛴다."""
        (self.state_dir / "tasks" / f"{tid}.json").write_text("{깨짐", encoding="utf-8")

    def test_unreadable_state_holds_finish(self):
        """손상된 상태 파일을 없는 태스크로 보지 않는다(엄격 읽기): 끝났는지 모르므로 done·전체 테스트를 하지 않는다."""
        self.use_gate()
        self.all_done()
        self.corrupt_state("T-003")
        self.d.finish_step()
        self.assertEqual(self.done_items(), [])
        self.spawn.assert_not_called()
        self.assertFalse(self.finish().get("reported"))
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 마무리 보류: 상태 파일을 읽을 수 없다: T-003\.json$")

    def test_full_result_is_dropped_when_a_state_file_became_unreadable(self):
        self.use_gate()
        self.all_done()
        self.d.finish_step()
        self.assertEqual(self.finish()["final_ids"], ["T-001", "T-002"])
        self.corrupt_state("T-003")  # 테스트 중 생긴 태스크의 상태 파일을 읽지 못한다
        self.d.final_done(0, {"ok": True, "task": None, "kind": "full", "status": "passed", "exit": 0, "seconds": 1.0,
                              "tail": "", "log": ".herdr-team/state/tests/logs/final-full-x.log"}, "")
        self.assertEqual((self.done_items(), self.decides()), ([], []))
        self.assertFalse(self.finish().get("reported"))
        self.assertNotIn("final_ids", self.finish())


class ConfirmTest(FlowCase):
    """[test] 확정 질문(설계 8.4 끝 문단, 5.7, 7.1 의 test-confirm)."""

    def test_question_render_and_once_per_digest(self):
        self.use_gate(approve=False)
        out = self.d.confirm_test()
        [q] = self.items("question")
        self.assertEqual(out["asked"], q["id"])
        self.assertEqual(q["from"], "drive")
        render = q["render"]
        self.assertEqual((render["header"], render["question"]), ("테스트 확정", CONFIRM_QUESTION))
        self.assertEqual(render["options"], [
            {"label": "확정한다 (추천)", "description": "추천 사유: 기획자가 쓴 명령이고 아래에 그대로 보인다"},
            {"label": "고친다", "description": "[test] 를 고치는 기획 태스크를 만든다"}])
        cfg = testgate.load_config(self.p)
        self.assertTrue(render["context"].endswith(testgate.confirm_section(cfg)))
        self.assertEqual(q["test_digest"], testgate.digest(cfg))
        outbox.validate_render(render, "질문")
        rec = json.loads((self.drive_dir / "test-confirm.json").read_text())
        self.assertEqual([a["digest"] for a in rec["asked"]], [testgate.digest(cfg)])
        self.assertEqual(rec["asked"][0]["out_id"], q["id"])
        self.answer(q["id"], "고친다")
        self.assertIsNone(self.d.confirm_test()["asked"])  # 같은 식별값은 다시 묻지 않는다
        self.assertEqual(len(self.items("question")), 1)

    def test_request_asks_again_but_not_over_an_open_one(self):
        self.use_gate(approve=False)
        first = self.d.confirm_test()["asked"]
        again = self.d.confirm_test(force=True)  # 열려 있는 같은 질문이 있으면 새로 올리지 않는다
        self.assertEqual((again["asked"], len(self.items("question"))), (first, 1))
        self.answer(first, "고친다")
        second = self.d.confirm_test(force=True)["asked"]  # hteam test-confirm: 이미 물었어도 다시 올린다
        self.assertNotEqual(second, first)
        self.assertEqual(len(self.items("question")), 2)

    def test_new_digest_asks_again(self):
        self.use_gate(approve=False)
        self.d.confirm_test()
        self.use_gate(full="fake-test --all --slow", approve=False)
        self.d.confirm_test()
        self.assertEqual(len({q["test_digest"] for q in self.items("question")}), 2)

    def test_main_rule_turns_fix_answer_into_planning_task(self):
        """`고친다` 답은 답 파일만 남고 관제는 같은 식별값을 다시 묻지 않는다. 메인 규칙이 그 답을 `[test]` 고치기 기획
        태스크로 잇는다(설계 7.4, Codex 브랜치 리뷰 p6r3: 없으면 마무리 full 이 멈춘다). 새 식별값은 위 시험대로 다시 묻는다."""
        from tests.helpers import ROOT
        main = (ROOT / "templates" / "CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("`question` 의 답이 `확정한다 (추천)` 이 아니면 답을 돌려준 뒤 사용자가 정한 대로 한다. `고친다` 면 "
                      "`[test]` 를 고치는 기획 태스크(`plan: append`)를 위 순서대로 만들어 시작한다", main)

    def test_approved_or_no_gate_asks_nothing(self):
        self.assertIsNone(self.d.confirm_test()["asked"])
        self.use_gate()
        self.assertIsNone(self.d.confirm_test()["asked"])
        self.assertEqual(self.items("question"), [])

    def test_request_without_gate_is_usage(self):
        with self.assertRaises(HteamError) as ctx:
            self.d.confirm_test(force=True)
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("no_test_config", 2))

    def test_corrupt_approvals_is_one_decide(self):
        self.use_gate(approve=False)
        path = testgate.approvals_path(self.p)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{깨짐", encoding="utf-8")
        self.assertIsNone(self.d.confirm_test()["asked"])
        self.d.confirm_test()
        [d] = self.decides("escalation")
        self.assertIn(str(path), d["summary"])
        self.assertEqual(self.items("question"), [])

    def test_corrupt_record_is_empty(self):
        self.use_gate(approve=False)
        self.drive_dir.mkdir(parents=True, exist_ok=True)
        (self.drive_dir / "test-confirm.json").write_text("[]", encoding="utf-8")
        self.assertIsNotNone(self.d.confirm_test()["asked"])


class PlanApplyTest(FlowCase):
    """기획 적용(설계 8.9): append 판정, 새 key 없음, 기획 수정 태스크, plan_applied."""

    def planner(self, tid, front=None):
        self.task(tid, "planner", front=front)

    def test_apply_writes_tasks_and_progress(self):
        self.commit("docs/planning/tasks.toml", PLAN_TWO, "[T-001] 기획")
        self.planner("T-001")
        self.d.apply_plan("T-001")
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003"])
        self.assertTrue(self.task_state("T-001")["plan_applied"])
        self.assertEqual(self.progress(), ["기획 적용: T-002 [developer] 저장 모듈; T-003 [developer] 할 일 화면 ← T-002"])
        self.start_ready.assert_called_once_with()
        self.d.apply_plan("T-001")  # 이미 적용한 기획 태스크는 다시 하지 않는다
        self.assertEqual(len(self.progress()), 1)

    def test_append_when_plan_already_applied_even_without_front_matter(self):
        self.commit("docs/planning/tasks.toml", PLAN_TWO, "[T-001] 기획")
        self.planner("T-001")
        self.d.apply_plan("T-001")
        self.commit("docs/planning/tasks.toml", PLAN_THIRD, "[T-004] 증분 기획")
        self.planner("T-004")  # front matter `plan: append` 가 없어도 이미 적용한 계획이 있으면 append(orca f4ebe86)
        self.d.apply_plan("T-004")
        self.assertEqual(self.ids()[-1], "T-005")
        self.assertEqual(self.progress()[-1], "기획 적용: T-005 [developer] 설정 ← T-003")

    def test_no_new_keys_is_progress_and_applied(self):
        self.commit("docs/planning/tasks.toml", PLAN_TWO, "[T-001] 기획")
        self.planner("T-001")
        self.d.apply_plan("T-001")
        self.planner("T-004")
        self.d.apply_plan("T-004")
        self.assertEqual(self.progress()[-1], "기획 적용: T-004 가 새 태스크를 더하지 않았다")
        self.assertTrue(self.task_state("T-004")["plan_applied"])
        self.assertEqual(self.ids(), ["T-001", "T-002", "T-003", "T-004"])

    def test_refused_plan_makes_fix_task(self):
        self.commit("docs/planning/tasks.toml", PLAN_TWO.replace('role = "developer"\ntitle = "할 일 화면"',
                                                                 'role = "painter"\ntitle = "할 일 화면"'),
                    "[T-001] 기획")
        self.planner("T-001")
        self.d.apply_plan("T-001")
        self.assertTrue(self.task_state("T-001")["plan_applied"])
        sp = self.spec("T-002")
        self.assertEqual((sp.role, sp.title, sp.front.get("plan")), ("planner", "tasks.toml 고치기", None))
        self.assertEqual(sp.sections["Target"], "docs/planning/tasks.toml")
        change = sp.sections["Change"].splitlines()
        self.assertEqual(change[0], "hteam plan apply 가 거부했다. 오류 원문:")
        self.assertTrue(change[1].startswith("plan_invalid: "), change)
        self.assertTrue(any("painter" in line for line in change[2:-1]), change)
        self.assertEqual(change[-1], "기존 docs/planning/ 을 읽고 이 오류만 고친다.")
        self.assertEqual(sp.sections["Acceptance"], "- `hteam plan check` 가 통과한다")
        self.assertEqual(self.subject(), "spec: T-002")
        self.start_ready.assert_called_once_with()

    def test_refused_append_fix_task_keeps_append(self):
        self.commit("docs/planning/tasks.toml", PLAN_TWO, "[T-001] 기획")
        self.planner("T-001")
        self.d.apply_plan("T-001")
        self.commit("docs/planning/tasks.toml", PLAN_THIRD.replace('title = "저장 모듈"', 'title = "저장"'),
                    "[T-004] 증분 기획")  # 이미 적용한 key 의 내용이 바뀌었다: append 가 거부한다
        self.planner("T-004", front={"plan": "append"})
        self.d.apply_plan("T-004")
        sp = self.spec("T-005")
        self.assertEqual((sp.title, sp.front.get("plan")), ("tasks.toml 고치기", "append"))
        self.assertEqual(sp.sections["Change"].splitlines()[0], "hteam plan apply --append 가 거부했다. 오류 원문:")


class CreateTaskTest(FlowCase):
    """관제가 만드는 태스크 create_task(설계 8.9 의 1–5)."""

    def test_fills_sections_commits_and_logs(self):
        self.task("T-001")
        tid = self.d.create_task(role="developer", title="토큰 반영", target="src/ui/**", change="바꿀 것\n둘째 줄",
                                 acceptance=["하나", "둘"], owns=["src/ui/**"], depends=["T-001"], plan_append=False)
        self.assertEqual(tid, "T-002")
        sp = self.spec(tid)
        self.assertEqual((sp.role, sp.title, sp.owns, sp.depends_on), ("developer", "토큰 반영", ["src/ui/**"],
                                                                        ["T-001"]))
        self.assertEqual({k: sp.sections[k] for k in specs.SECTIONS},
                         {"Target": "src/ui/**", "Change": "바꿀 것\n둘째 줄", "Constraints": CONSTRAINTS,
                          "Acceptance": "- 하나\n- 둘"})
        self.assertEqual(self.subject(), f"spec: {tid}")
        self.assertTrue(self.tracked_clean(f".herdr-team/tasks/{tid}.md"))
        self.assertEqual(self.task_state(tid)["status"], "pending")
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} T-002 생성 \[developer\] 토큰 반영$")
        tid = self.d.create_task(role="planner", title="증분", target="docs/planning/", change="더한다",
                                 acceptance=["된다"], plan_append=True)
        self.assertEqual(self.spec(tid).front.get("plan"), "append")

    def test_spec_check_failure_is_not_committed(self):
        head = self.head()
        self.assertIsNone(self.d.create_task(role="developer", title="빈 것", target="src/x/**", change="",
                                             acceptance=["된다"], owns=["src/x/**"]))
        self.assertEqual(self.head(), head)
        [d] = self.decides("escalation")
        self.assertTrue(d["summary"].startswith("T-001 사양 검사 실패로 커밋하지 않았다: "), d)
        self.assertTrue((self.team / "tasks" / "T-001.md").exists())  # 덮어쓴 파일은 커밋 안 된 채 남는다

    def test_input_errors_are_raised(self):
        with self.assertRaises(HteamError) as ctx:
            self.d.create_task(role="developer", title="넓다", target="lib/**", change="x", acceptance=["y"],
                               owns=["lib/**"])
        self.assertEqual(ctx.exception.code, "owns_too_wide")
        with self.assertRaises(HteamError) as ctx:
            self.d.create_task(role="painter", title="모름", target="x", change="x", acceptance=["y"])
        self.assertEqual(ctx.exception.code, "unknown_role")
        self.assertEqual(specs.list_ids(self.p), [])


class DesignStepTest(FlowCase):
    """디자인 단계 design_step 과 보강(설계 8.9, 11.4)."""

    config = DESIGN_CONFIG
    roles = ("planner", "director", "designer", "developer", "tester")

    def setUp(self):
        super().setUp()
        self.task("T-001", "director", owns=["docs/design/**"])

    def screen(self, tid, status="awaiting_user", rnd=1, proposal=None, title=None):
        self.task(tid, "designer", status, rounds=tuple(range(1, rnd + 1)), title=title or f"{tid} 화면",
                  depends="T-001")
        if proposal is not None:
            self.commit(f"docs/tasks/{tid}/report.md", f"## r{rnd}\n### 시스템 추가 제안\n{proposal}\n", f"[{tid}] r{rnd}")

    def supplement_record(self):
        return json.loads((self.drive_dir / "supplement.json").read_text(encoding="utf-8"))

    def write_supplement(self, records):
        self.drive_dir.mkdir(parents=True, exist_ok=True)
        (self.drive_dir / "supplement.json").write_text(json.dumps({"supplements": records}), encoding="utf-8")

    def test_nothing_without_waiting_or_with_blockers(self):
        self.screen("T-002", "working")
        with mock.patch.object(approval, "design_review") as review:
            self.d.design_step()
            self.screen("T-003")
            self.d.design_step()  # T-002 가 진행 중이다
            review.assert_not_called()
        self.assertEqual(specs.list_ids(self.p), ["T-001", "T-002", "T-003"])

    def test_queued_fix_blocks(self):
        self.screen("T-002")
        self.screen("T-003")
        self.set_state("T-003", queued_fix={"note": "고친다", "supplement": None, "force_round": False,
                                            "at": "2026-01-01T00:00:00Z", "request": None})
        with mock.patch.object(approval, "design_review") as review:
            self.d.design_step()
            review.assert_not_called()

    def test_asks_when_nothing_to_supplement(self):
        self.screen("T-002", proposal="- 없음")
        self.screen("T-003", proposal="- 해당 없음(기존 토큰으로 충분하다)")  # followups 의 빈 항목 규칙
        self.d.design_step()
        [ask] = self.items("approval")
        self.assertEqual([t["task"] for t in approval.load(self.p)["batches"][0]["tasks"]], ["T-002", "T-003"])
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 디자인 승인 질문 {ask['id']}: T-002, T-003$")

    def test_quiet_refusals(self):
        self.screen("T-002")
        for code in ("approval_not_ready", "already_asked", "nothing_to_approve", "supplement_needed",
                     "decision_pending", "approval_stale"):
            with mock.patch.object(approval, "design_review", side_effect=HteamError(code, "x", 3)):
                self.d.design_step()
        self.assertEqual(self.decides(), [])

    def test_proposals_make_one_supplement_task(self):
        self.screen("T-002", proposal="- 버튼 그림자 토큰\n- 강조 색 하나")
        self.screen("T-003", proposal="- 없음")
        self.screen("T-004", proposal="- 배지 모양")
        self.d.design_step()
        sp = self.spec("T-005")
        self.assertEqual((sp.role, sp.title, sp.owns),
                         ("director", "디자인 시스템 보강: T-002, T-004 제안",
                          ["docs/design/system/**", "docs/design/direction.md"]))
        self.assertEqual(sp.sections["Change"], f"{SUPPLEMENT_CHANGE}\n- T-002 r1: - 버튼 그림자 토큰 - 강조 색 하나\n"
                                                f"- T-004 r1: - 배지 모양")
        self.assertEqual(sp.sections["Acceptance"], SUPPLEMENT_ACCEPT)
        self.assertEqual(self.supplement_record()["supplements"],
                         [{"task": "T-005", "from": {"T-002": 1, "T-004": 1}, "handled": False, "token_update": None}])
        self.assertEqual(self.items("approval"), [])  # 보강이 먼저다
        self.start_ready.assert_called_once_with()
        self.d.design_step()  # 보강 태스크가 끝나기를 기다린다
        self.assertEqual(specs.list_ids(self.p), ["T-001", "T-002", "T-003", "T-004", "T-005"])

    def test_recorded_proposal_in_direction_is_skipped(self):
        self.commit("docs/design/direction.md", "## 결정 기록\n- T-002 r1: 그림자 토큰을 더했다\n", "[T-001] 결정")
        self.screen("T-002", proposal="- 버튼 그림자 토큰")
        self.d.design_step()
        self.assertEqual(specs.list_ids(self.p), ["T-001", "T-002"])
        self.assertEqual(len(self.items("approval")), 1)  # 기록된 제안은 승인 질문을 막지 않는다

    def test_pending_ui_foundation_waits_for_supplement(self):
        self.task("T-003", "developer", "pending", rounds=(), owns=["src/ui/**"], front={"plan_key": "ui-foundation"})
        self.screen("T-002", proposal="- 버튼 그림자 토큰")
        self.d.design_step()
        self.assertEqual(self.spec("T-003").depends_on, ["T-004"])
        self.assertEqual(self.subject(), "spec: T-003")
        self.assertTrue(self.tracked_clean(".herdr-team/tasks/T-003.md"))

    def test_started_ui_foundation_gets_token_task(self):
        self.task("T-003", "developer", "working", owns=["src/ui/**"], front={"plan_key": "ui-foundation"})
        self.task("T-004", "developer", "pending", rounds=(), depends="T-003, T-002", owns=["src/screen/**"])
        self.task("T-005", "developer", "pending", rounds=(), depends="T-002", owns=["src/other/**"])  # UI 기반 아님
        self.screen("T-002", proposal="- 버튼 그림자 토큰")
        self.d.design_step()
        sup, token = "T-006", "T-007"
        self.assertEqual(self.spec(sup).role, "director")
        tk = self.spec(token)
        self.assertEqual((tk.role, tk.title, tk.owns, tk.depends_on),
                         ("developer", "토큰 갱신: T-006 반영", ["src/ui/**"], ["T-006", "T-003"]))
        self.assertEqual(self.spec("T-004").depends_on, ["T-003", "T-002", "T-007"])
        self.assertEqual(self.spec("T-005").depends_on, ["T-002"])
        self.assertTrue(self.tracked_clean(".herdr-team/tasks/T-004.md"))
        self.assertEqual(self.decides(), [])

    def test_started_screen_is_token_update_decide_once(self):
        self.task("T-003", "developer", "done", owns=["src/ui/**"], front={"plan_key": "ui-foundation"})
        self.task("T-004", "developer", "working", depends="T-003", owns=["src/screen/**"])
        self.screen("T-002", proposal="- 버튼 그림자 토큰")
        self.d.design_step()
        [d] = self.decides("token_update")
        self.assertEqual((d["task"], d["summary"], d["files"]),
                         ("T-003", "디자인 시스템 보강 T-005 을 시작한다. UI 기반 개발 태스크에 바뀔 토큰을 반영할지 정한다",
                          ["docs/design/direction.md"]))
        self.assertEqual(d["commands"], ['hteam task new --role developer --title "토큰 갱신 반영: <요약>"',
                                         'hteam scope T-003 "<바뀐 토큰>"'])
        self.assertEqual(self.spec("T-004").depends_on, ["T-003"])  # 사양을 바꾸지 않는다
        self.assertEqual(self.supplement_record()["supplements"][0]["token_update"], d["id"])
        self.assertEqual(specs.list_ids(self.p), ["T-001", "T-002", "T-003", "T-004", "T-005"])
        self.d.design_step()
        self.assertEqual(len(self.decides("token_update")), 1)
        self.assertEqual(self.task_state("T-005")["status"], "pending")  # 보강 태스크는 decide 와 상관없이 시작한다
        self.assertNotIn("decide", self.task_state("T-005"))

    def test_dropped_ui_foundation_is_decide(self):
        self.task("T-003", "developer", "dropped", owns=["src/ui/**"], front={"plan_key": "ui-foundation"})
        self.screen("T-002", proposal="- 버튼 그림자 토큰")
        self.d.design_step()
        self.assertEqual(len(self.decides("token_update")), 1)

    def add_round(self, tid, n, status):
        st = self.task_state(tid)
        rd = {**st["rounds"][-1], "round": n, "supplement": "T-005", "verdict": None}
        self.set_state(tid, round=n, rounds=[*st["rounds"], rd])
        with state.edit(self.p, tid) as cur:
            state.move(cur, status, "test")

    def test_done_supplement_fixes_waiting_screens_once(self):
        self.screen("T-002", proposal="- 그림자")
        self.screen("T-003", proposal="- 배지")
        self.screen("T-004", rnd=2)  # 기록은 r1 인데 지금은 r2: 다른 라운드의 화면은 고치지 않는다
        self.task("T-005", "director", "done", owns=["docs/design/system/**", "docs/design/direction.md"])
        self.write_supplement([{"task": "T-005", "from": {"T-002": 1, "T-003": 1, "T-004": 1}, "handled": False,
                                "token_update": None}])
        calls = []

        def fake_fix(p, tid, **kw):
            calls.append((tid, kw.get("supplement")))
            if tid == "T-002":
                self.add_round("T-002", 2, "launch_failed")  # 화면을 고쳤다(보강 라운드)
            elif len(calls) == 2:
                raise RuntimeError("관제가 죽었다")  # 다음 화면을 고치다 관제가 죽었다
            return {"task": tid, "round": 2}

        with mock.patch.object(tasks, "fix", side_effect=fake_fix), mock.patch.object(approval, "design_review"):
            with self.assertRaises(RuntimeError):
                self.d.design_step()
            self.assertFalse(self.supplement_record()["supplements"][0]["handled"])  # 화면을 먼저, 기록은 나중
            self.d.design_step()  # 고친 화면(T-002)이 진행 중이다(단계 2 에서 끝)
            self.assertEqual(len(calls), 2)
            with state.edit(self.p, "T-002") as cur:
                state.move(cur, "awaiting_user", "test")  # T-002 의 보강 라운드가 다시 승인을 기다린다
            self.d.design_step()  # 이미 고친 T-002(지금 r2)는 다시 고치지 않는다
        self.assertEqual(calls, [("T-002", "T-005"), ("T-003", "T-005"), ("T-003", "T-005")])
        self.assertTrue(self.supplement_record()["supplements"][0]["handled"])
        self.start_ready.assert_called()

    def test_dropped_supplement_is_not_made_again(self):
        self.screen("T-002", proposal="- 그림자")
        self.task("T-003", "director", "dropped", owns=["docs/design/system/**", "docs/design/direction.md"])
        self.write_supplement([{"task": "T-003", "from": {"T-002": 1}, "handled": False, "token_update": None}])
        self.d.design_step()
        self.assertTrue(self.supplement_record()["supplements"][0]["handled"])
        self.assertEqual(specs.list_ids(self.p), ["T-001", "T-002", "T-003"])
        self.assertEqual(len(self.items("approval")), 1)  # 승인 질문으로 간다


class DecisionResumeTest(FlowCase):
    """답 파일에만 있는 일괄 승인 결정의 실행(설계 7.4)과 끝나지 않은 결정 이어 하기(11.4, 8.7 의 7)."""

    config = DESIGN_CONFIG
    roles = DesignStepTest.roles

    def setUp(self):
        super().setUp()
        self.task("T-001", "designer", "awaiting_user", title="로그인 화면")
        self.task("T-002", "designer", "awaiting_user", title="목록 화면")
        self.oid = approval.design_review(self.p)["id"]

    def test_decision_only_in_answer_file_is_executed_once(self):
        self.answer(self.oid, "수정 요청", decision={"fix": {"T-001": "버튼을 키운다"}})
        self.d.resume_decisions()
        self.assertEqual([(t, self.task_state(t)["status"], self.task_state(t)["round"]) for t in ("T-001", "T-002")],
                         [("T-001", "launch_failed", 2), ("T-002", "done", 1)])
        self.assertTrue(approval.load(self.p)["batches"][0]["decision"]["done"])
        self.d.resume_decisions()  # 다 한 결정은 다시 하지 않는다
        self.assertEqual(self.task_state("T-001")["round"], 2)

    def test_unfinished_decision_is_resumed(self):
        self.answer(self.oid, "모두 승인 (추천)", decision={"fix": {}})
        with mock.patch.object(approval, "_apply", side_effect=RuntimeError("멈춤")):
            with self.assertRaises(RuntimeError):
                approval.decide(self.p, self.oid, json.dumps({"fix": {}}))
        self.assertIsNone(approval.load(self.p)["batches"][0]["decision"].get("done"))
        self.d.resume_decisions()
        self.assertEqual([self.task_state(t)["status"] for t in ("T-001", "T-002")], ["done", "done"])

    def test_answer_without_decision_is_left(self):
        self.answer(self.oid, "모두 승인 (추천)")  # 결정 없는 답(메인이 design-decide 를 아직 부르지 않았다)
        self.d.resume_decisions()
        self.assertEqual([self.task_state(t)["status"] for t in ("T-001", "T-002")], ["awaiting_user", "awaiting_user"])
        self.assertIsNone(approval.load(self.p)["batches"][0].get("decision"))

    def test_waiting_refusals_are_quiet(self):
        self.answer(self.oid, "모두 승인 (추천)", decision={"fix": {}})
        with mock.patch.object(approval, "decide", side_effect=HteamError("decision_pending", "x", 3)):
            self.d.resume_decisions()
        self.assertEqual(self.decides(), [])


class ReconcileOrderTest(FlowCase):
    """재확인(설계 8.7)의 6·7: 묶음 처리 안 된 done tester → start-ready → 디자인 단계 → 결정 → 마무리."""

    def test_flow_steps_run_in_order_after_tasks(self):
        calls = []
        for name in ("unbatched", "design_step", "resume_decisions", "finish_step"):
            stub = mock.patch.object(self.d, name, side_effect=lambda n=name: calls.append(n))
            stub.start()
            self.addCleanup(stub.stop)
        self.start_ready.side_effect = lambda: calls.append("start_ready")
        self.d.reconcile()
        self.assertEqual(calls, ["unbatched", "start_ready", "design_step", "resume_decisions", "finish_step"])


if __name__ == "__main__":
    unittest.main()


class PlanIssueProgressTest(FlowCase):
    """기획 적용 progress 의 태스크 줄 이슈 번호(설계 8.12, 7단계). tasks.toml 의 issue 는 Task 2 가 사양으로 옮긴다."""

    def test_progress_line_shows_issue(self):
        plan = PLAN_TWO.replace('title = "저장 모듈"\n', 'title = "저장 모듈"\nissue = 5712\n')
        self.commit("docs/planning/tasks.toml", plan, "[T-001] 기획")
        self.task("T-001", "planner")
        self.d.apply_plan("T-001")
        self.assertEqual(self.progress(),
                         ["기획 적용: T-002 #5712 [developer] 저장 모듈; T-003 [developer] 할 일 화면 ← T-002"])
