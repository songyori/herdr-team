"""교차 리뷰(설계 6.1–6.3): 사전 검사, 기준점, 리뷰어 실행·복구, 변조 검사, 판정, 자동 재시도, --retry."""
import json
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import gitio, state
from hteam.paths import Project


class ReviewCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)

    def started(self, tid="T-001", role="developer", **kw):
        self.write_spec(tid, role, **kw)
        state.create(self.p, tid, role)
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def worked(self, tid="T-001", **kw):
        self.started(tid, **kw)
        code, out = self.act_work(tid)
        self.assertEqual(code, 0, out)

    def reviewing(self, tid="T-001", **kw):
        self.worked(tid, **kw)
        code, out = self.hteam("review", tid)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        return out


class ReviewTest(ReviewCase):
    def test_approve_flow(self):
        out = self.reviewing()
        st = self.task_state("T-001")
        att = st["rounds"][0]["reviews"][0]
        self.assertEqual((att["attempt"], att["title"], att["agent"], att["model"]),
                         (1, "T-001 r1 리뷰 a1", "codex", "gpt-6.1-sol"))
        self.assertEqual(att["file"], "docs/reviews/T-001/r1-a1.md")
        self.assertEqual([c["subject"] for c in att["inputs"]["commits"]], ["[T-001] r1 작업"])
        self.assertEqual(att["inputs"]["files"], ["docs/tasks/T-001/report.md", "src/app.py"])
        self.assertEqual(att["baseline"]["head"], self.head())
        self.assertEqual(self.dispatch_row(self.work_dispatch("T-001"))["state"], "retained")
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["agent"], row["title"]), ("codex", "T-001 r1 리뷰 a1"))
        self.assertEqual(json.loads(row["agent_args"]), ["--disable=hooks"])
        prompt = (self.state_dir / "tasks/T-001/r1-review-a1.md").read_text()
        for needle in ("REVIEW_FILE: docs/reviews/T-001/r1-a1.md", "[T-001] r1 작업", "`src/app.py`",
                       "VERDICT: REQUEST_CHANGES", "--report-path docs/reviews/T-001/r1-a1.md", "이전 리뷰: 없음"):
            self.assertIn(needle, prompt)
        code, res = self.act_review("T-001", "APPROVE")
        self.assertEqual(code, 0, res)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["verdict"], out["status"], out["file"]), ("APPROVE", "approved", "docs/reviews/T-001/r1.md"))
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "[T-001] review r1: APPROVE")
        self.assertEqual(self.git("show", "--name-only", "--format=", "HEAD").split(), ["docs/reviews/T-001/r1.md"])
        self.assertFalse((self.proj / "docs/reviews/T-001/r1-a1.md").exists())
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["verdict"]), ("approved", "APPROVE"))
        self.assertEqual(self.dispatch_row(out_dispatch := st["rounds"][0]["reviews"][0]["dispatch"])["state"], "released")
        self.assertTrue(out_dispatch)

    def test_request_changes(self):
        self.reviewing()
        self.act_review("T-001", "REQUEST_CHANGES", text="## 지적 사항\n- [P1] src/app.py:1 — 틀림. 고친다.\n")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "changes"), out)

    def test_codex_worker_gets_claude_reviewer(self):
        self.write_spec("T-001", front={"worker": "codex"})
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["reviewer"]), (0, "claude"), out)
        self.assertEqual(self.dispatch_row(out["dispatch"])["model"], "opus")  # [roles.developer].claude_model

    def test_review_needs_working_and_single_review(self):
        self.started()
        self.act_work("T-001")
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "review_in_progress"))
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "reviewer_running"))
        with state.edit(self.p, "T-001") as st:
            state.move(st, "dropped", "drop")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "task_closed"))

    def test_canceled_round_is_not_reviewed(self):
        self.worked()
        with state.edit(self.p, "T-001") as st:  # fix·drop 이 취소를 저장한 뒤 멈췄다
            st["rounds"][-1]["work"]["canceled"] = True
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "round_canceled"), out)
        self.assertEqual(self.task_state("T-001")["rounds"][0]["reviews"], [])


class PrecheckTest(ReviewCase):
    def assert_changes(self, needle):
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["source"]), (0, "changes", "hteam"), out)
        self.assertTrue(any(needle in x for x in out["problems"]), out["problems"])
        text = (self.proj / "docs/reviews/T-001/r1.md").read_text()
        self.assertTrue(text.rstrip().endswith("VERDICT: REQUEST_CHANGES"))
        self.assertIn("출처: hteam", text)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "[T-001] review r1: REQUEST_CHANGES")
        self.assertEqual(self.task_state("T-001")["rounds"][0]["reviews"], [])
        return out

    def test_no_commits_and_uncommitted(self):
        self.started()
        self.act_work("T-001", commit=False)
        out = self.assert_changes("리뷰 대상 커밋이 없다")
        self.assertTrue(any("커밋하지 않은 변경" in x for x in out["problems"]))

    def test_outside_owns_unless_reverted(self):
        self.started()
        self.act_work("T-001", files={"src/app.py": "x\n", "README.md": "바꿈\n"})
        self.assert_changes("owns 밖 경로의 내용이 base 와 다르다: README.md")

    def test_reverted_outside_change_passes(self):
        self.started()
        self.act(self.work_dispatch("T-001"), {"write": {"README.md": "바꿈\n"}, "commit": "[T-001] 실수"})
        self.act_work("T-001", files={"src/app.py": "x\n", "README.md": "# proj\n"})
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)

    def test_planner_plan_check(self):
        self.started("T-001", "planner")
        bad = '[[task]]\nkey = "a"\nrole = "developer"\n'
        self.act_work("T-001", files={"docs/planning/tasks.toml": bad})
        self.assert_changes("plan check 를 통과하지 못한다")

    def test_resume_after_precheck_commit(self):
        self.started()
        self.act_work("T-001", commit=False)
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_precheck_commit"})
        self.assertEqual(code, 137)
        sha = self.head()
        self.assertEqual(self.task_state("T-001")["status"], "working")
        code, out = self.hteam("review", "T-001")  # 같은 내용은 다시 커밋하지 않는다(빈 커밋 실패 없음)
        self.assertEqual((code, out["status"], out["commit"]), (0, "changes", sha), out)
        self.assertEqual(self.head(), sha)


class TamperTest(ReviewCase):
    def finish(self):
        return self.hteam("review-finish", "T-001")

    def test_reviewer_product_edit_is_tamper_then_retry(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE", extra={"write": {"src/app.py": "리뷰어가 고침\n"}})
        code, out = self.finish()
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["reviews"][0]["result"]), ("reviewing", "tampered"))
        self.git("checkout", "--", "src/app.py")  # 사용자가 정리했다
        code, out = self.hteam("review", "T-001", "--retry")
        self.assertEqual((code, out["attempt"]), (0, 2), out)
        self.assertTrue(self.task_state("T-001")["rounds"][0]["reviews"][1]["extra"])

    def test_reviewer_commit_moves_head(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE", extra={"write": {"src/b.py": "x\n"}, "commit": "리뷰어 커밋"})
        code, out = self.finish()
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"))
        self.assertEqual(out["tamper"]["paths"], ["src/b.py"])

    def test_other_tasks_work_is_excluded(self):
        self.write_spec("T-002", "tester")
        state.create(self.p, "T-002", "tester")
        self.assertEqual(self.hteam("start", "T-002")[0], 0)  # 기준점에 진행 중
        self.act(self.work_dispatch("T-002"), {"write": {"tests/t.py": "1\n"}})  # 커밋 안 된 변경
        self.reviewing()
        self.write_spec("T-003", "planner")
        state.create(self.p, "T-003", "planner")
        self.assertEqual(self.hteam("start", "T-003")[0], 0)  # 리뷰 중 시작
        self.act(self.work_dispatch("T-003"), {"write": {"docs/planning/spec.md": "x\n"}, "commit": "[T-003] 기획"})
        self.act(self.work_dispatch("T-002"), {"write": {"tests/t.py": "2\n"}, "commit": "[T-002] 테스트"})
        self.act_review("T-001", "APPROVE", extra={"write": {"scratch.log": "x\n"}})
        code, out = self.finish()
        self.assertEqual((code, out["status"], out["warnings"]), (0, "approved", ["scratch.log"]), out)
        body = self.git("log", "-1", "--format=%b")
        self.assertIn("scratch.log", body)


class AttemptTest(ReviewCase):
    def test_failed_attempt_retries_once_then_review_failed(self):
        self.reviewing()
        self.act_review("T-001", write=False)  # 파일 없이 done
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["retried"], out["attempt"], out["failed_attempt"]), (0, True, 2, 1), out)
        self.act_review("T-001", "APPROVE", outcome="failed")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_failed"), out)
        st = self.task_state("T-001")
        self.assertEqual([a["result"] for a in st["rounds"][0]["reviews"]], ["failed", "failed"])
        self.assertEqual(st["status"], "reviewing")
        code, out = self.hteam("review", "T-001", "--retry")
        self.assertEqual((code, out["attempt"]), (0, 3), out)
        self.act_review("T-001", "APPROVE")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["verdict"], out["attempt"]), (0, "APPROVE", 3), out)
        self.assertFalse(list((self.proj / "docs/reviews/T-001").glob("r1-a*.md")))

    def test_reviewer_exited_without_done(self):
        out = self.reviewing()
        self.update_terminal(out["terminal"], state="finished")
        code, res = self.hteam("review-finish", "T-001")
        self.assertEqual((code, res["retried"]), (0, True), res)
        first = self.task_state("T-001")["rounds"][0]["reviews"][0]
        self.assertEqual((first["dispatch_end"]["abandoned"], first["reason"]), (True, "리뷰어가 done 없이 끝났다"))
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")

    def test_missing_verdict_line(self):
        self.reviewing()
        self.act_review("T-001", None)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["reason"]), (0, "VERDICT 줄이 없다"), out)

    def test_retry_requires_failed_review(self):
        self.reviewing()
        code, out = self.hteam("review", "T-001", "--retry")
        self.assertEqual((code, out["error"]["code"]), (3, "no_failed_review"))


class RecoveryTest(ReviewCase):
    def test_dead_before_byte_relaunches_same_attempt(self):
        self.worked()
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_child"})
        self.assertEqual(code, 137)
        st = self.task_state("T-001")
        att = st["rounds"][0]["reviews"][0]
        self.assertEqual((st["status"], att["result"], att["dispatch"]), ("working", None, None))
        self.commit("other.txt", "x\n", "다른 커밋")  # 새 기준점을 만들지 않는다
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["attempt"], out["mode"]), (0, 1, "fresh"), out)
        self.assertEqual(self.task_state("T-001")["rounds"][0]["reviews"][0]["baseline"], att["baseline"])

    def test_dead_after_launch_adopts(self):
        self.worked()
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        self.assertEqual(code, 137)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["mode"], out["status"]), (0, "adopt", "reviewing"), out)
        self.act_review("T-001", "APPROVE")
        self.assertEqual(self.hteam("review-finish", "T-001")[1]["status"], "approved")


class CrashResumeTest(ReviewCase):
    def approve_and_die(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        code, _ = self.hteam("review-finish", "T-001", env={"HTEAM_TEST_DIE_AT": "after_verdict"})
        self.assertEqual(code, 137)
        att = self.attempt("T-001")
        self.assertEqual((att["verdict_read"], att["result"]), ("APPROVE", None))

    def test_resume_after_verdict_finishes(self):
        self.approve_and_die()
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)

    def test_resume_after_verdict_rechecks_tamper(self):
        self.approve_and_die()
        (self.proj / "src/app.py").write_text("그 사이 바뀜\n")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)

    def test_resume_without_evidence_is_failed_attempt(self):
        self.approve_and_die()
        (self.proj / "docs/reviews/T-001/r1-a1.md").unlink()
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["retried"], out["reason"]), (0, True, "기록한 판정의 리뷰 파일이 없거나 바뀌었다"), out)

    def die_after_move(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        code, _ = self.hteam("review-finish", "T-001", env={"HTEAM_TEST_DIE_AT": "after_move"})
        self.assertEqual(code, 137)
        self.assertFalse((self.proj / "docs/reviews/T-001/r1-a1.md").exists())

    def test_resume_after_move_finalizes_moved_file(self):
        self.die_after_move()
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"]), (0, "approved"), out)
        self.assertTrue(self.git("show", "HEAD:docs/reviews/T-001/r1.md").rstrip().endswith("VERDICT: APPROVE"))

    def test_recreated_attempt_file_after_move_is_not_finalized(self):
        self.die_after_move()
        (self.proj / "docs/reviews/T-001/r1-a1.md").write_text("VERDICT: REQUEST_CHANGES\n")  # 검증하지 않은 내용
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["retried"]), (0, True), out)  # 시도 실패로 다시 한다
        self.assertNotIn("review r1", self.git("log", "--format=%s"))
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_end_evidence_kept_when_dying_before_release(self):
        out = self.reviewing()
        self.update_terminal(out["terminal"], state="finished")
        code, _ = self.hteam("review-finish", "T-001", env={"HTEAM_TEST_DIE_AT": "after_end"})
        self.assertEqual(code, 137)
        att = self.attempt("T-001")
        self.assertEqual((att["dispatch_end"]["state"], att["dispatch_end"]["verdict"], att["dispatch_end"]["abandoned"],
                          att["cleaned"]), ("active", "exited", True, False))
        code, res = self.hteam("review-finish", "T-001")
        self.assertEqual((code, res["retried"]), (0, True), res)
        first = self.task_state("T-001")["rounds"][0]["reviews"][0]
        self.assertEqual((first["dispatch_end"]["state"], first["cleaned"]), ("active", True))
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")

    def test_stale_result_file_removed_on_recovery(self):
        self.worked()
        stale = self.proj / "docs/reviews/T-001/r1-a1.md"
        stale.parent.mkdir(parents=True)
        stale.write_text("VERDICT: APPROVE\n")
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_attempt"})
        self.assertEqual(code, 137)
        self.assertTrue(stale.exists())
        self.assertEqual(self.hteam("review", "T-001")[1]["status"], "reviewing")
        self.assertFalse(stale.exists())  # 리뷰어를 띄우기 전에 초기화했다
        self.act_review("T-001", write=False)  # 파일 없이 성공 보고
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["retried"]), (0, True), out)  # 이전 APPROVE 를 읽지 않는다


class SubdirReviewTest(ReviewCase):
    """프로젝트가 git 저장소의 하위 디렉터리에 있다. owns·리뷰 입력·변조 경로는 프로젝트 기준이고(프로젝트 밖은 `../`),
    git 출력과 blob 은 최상위 기준이다. `**/*.md` owns 는 `../README.md` 에도 글자로는 맞지만 프로젝트 밖이라 owns 밖이다."""

    def setUp(self):
        TeamCase.setUp(self)
        self.proj = self.proj / "sub"
        self.proj.mkdir()
        self.init_project(BASE_CONFIG.replace('owns = ["src/**"]', 'owns = ["src/**", "**/*.md"]'))
        self.setup_run()
        self.p = Project(self.proj)

    def test_review_in_subdir_project(self):
        self.worked()
        (self.proj.parent / "README.md").write_text("프로젝트 밖, 커밋 안 함\n")  # 기준점에 있고 리뷰 동안 그대로다
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        att = self.attempt("T-001")
        self.assertEqual(att["inputs"]["files"], ["docs/tasks/T-001/report.md", "src/app.py"])
        self.assertEqual(list(att["baseline"]["dirty"]), ["../README.md"])
        self.assertIsNotNone(att["baseline"]["dirty"]["../README.md"])
        self.assertIn("`src/app.py`", (self.state_dir / "tasks/T-001/r1-review-a1.md").read_text())
        self.act_review("T-001", "APPROVE", extra={"write": {"scratch.log": "x\n", "../top.log": "x\n"}})
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"], out["file"], out["warnings"]),
                         (0, "approved", "docs/reviews/T-001/r1.md", ["../top.log", "scratch.log"]), out)
        self.assertEqual(self.git("show", "--name-only", "--format=", "HEAD").split(), ["sub/docs/reviews/T-001/r1.md"])

    def test_precheck_flags_paths_outside_project(self):
        self.started()
        self.act_work("T-001", files={"src/app.py": "x\n", "../README.md": "바꿈\n"})
        (self.proj / "src/app.py").write_text("커밋 안 함\n")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["source"]), (0, "changes", "hteam"), out)
        self.assertIn("owns 밖 경로의 내용이 base 와 다르다: ../README.md", out["problems"])
        self.assertIn("owns 안에 커밋하지 않은 변경이 있다: src/app.py", out["problems"])
        self.assertEqual(self.git("show", "--name-only", "--format=", "HEAD").split(), ["sub/docs/reviews/T-001/r1.md"])

    def test_tamper_inside_and_outside_project(self):
        self.reviewing()
        # 프로젝트 안 추적 파일을 지우고(기준 blob 을 최상위 경로로 읽어야 잡힌다) 프로젝트 밖 추적 파일을 바꾼다
        self.act_review("T-001", "APPROVE", extra={"delete": ["src/app.py"], "write": {"../README.md": "리뷰어\n"}})
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["../README.md", "src/app.py"])


class GitPathTest(unittest.TestCase):
    def test_from_top_and_back(self):
        for prefix, top, rel in (("", "src/a.py", "src/a.py"), ("sub/", "sub/src/a.py", "src/a.py"),
                                 ("sub/", "README.md", "../README.md"), ("a/b/", "a/c.py", "../c.py"),
                                 ("sub/", "subx/y", "../subx/y")):
            self.assertEqual(gitio.from_top(prefix, top), rel)
            self.assertEqual(gitio.to_top(prefix, rel), top)


if __name__ == "__main__":
    unittest.main()
