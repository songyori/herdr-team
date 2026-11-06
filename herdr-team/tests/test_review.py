"""교차 리뷰(설계 6.1–6.3): 사전 검사, 기준점, 리뷰어 실행·복구, 변조 검사, 판정, 자동 재시도, --retry."""
import json
import os
import time
import unittest
from pathlib import Path

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

    def paused(self, point: str, *args: str):
        """hteam 을 백그라운드로 띄워 point 에서 멈춘다. (프로세스, 풀어 주는 함수, 도착했는지 기다리는 함수)."""
        gate = self.tmp / f"gate-{point}-{len(args)}-{time.monotonic_ns()}"
        proc = self.hteam_bg(*args, env={"HTEAM_TEST_PAUSE_AT": point, "HTEAM_TEST_PAUSE_FILE": str(gate)})
        reached = Path(str(gate) + ".reached")

        def wait(timeout: float = 30) -> bool:
            end = time.monotonic() + timeout
            while time.monotonic() < end:
                if reached.exists():
                    return True
                if proc.poll() is not None:
                    return False
                time.sleep(0.05)
            return False
        return proc, gate.touch, wait


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
                       "VERDICT: REQUEST_CHANGES", "--report-path docs/reviews/T-001/r1-a1.md", "이전 리뷰: 없음",
                       # 실환경(1단계): 병렬 커밋으로 HEAD 가 움직일 때마다 리뷰어가 멈추고 물었다
                       "네가 추적 파일 내용을 바꾸거나 HEAD 를 움직이면 판정이 무효가 된다",
                       "리뷰 동안 다른 워커와 코디네이터의 커밋으로 HEAD 가 움직이는 것은 정상이다"):
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

    def test_merge_commit_changes_are_checked(self):
        self.started()
        self.act_work("T-001")
        self.git("checkout", "-q", "-b", "side")
        self.commit("README.md", "옆 가지\n", "옆 가지 커밋")  # 접두사 없는 커밋을 [T-001] 병합으로 들여온다
        self.git("checkout", "-q", "main")
        self.git("merge", "--no-ff", "-q", "-m", "[T-001] 병합", "side")
        self.assert_changes("owns 밖 경로의 내용이 base 와 다르다: README.md")

    def test_planner_plan_check(self):
        self.started("T-001", "planner")
        bad = '[[task]]\nkey = "a"\nrole = "developer"\n'
        self.act_work("T-001", files={"docs/planning/tasks.toml": bad})
        self.assert_changes("plan check 를 통과하지 못한다")

    def applied_then_planner(self, rewritten) -> tuple[int, dict]:
        """key a 를 plan apply 한 뒤(T-001) 기획 태스크 T-002 가 tasks.toml 을 rewritten(처음 내용)으로 바꾸고 review 한다."""
        first = '[[task]]\nkey = "a"\nrole = "developer"\ntitle = "a 제목"\nowns = ["src/**"]\n' \
                'target = "대상"\nchange = "바꿀 것"\nconstraints = "제약"\nacceptance = ["확인 1"]\n'
        self.commit("docs/planning/tasks.toml", first, "기획 초안")
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out.get("applied")), (0, [{"key": "a", "id": "T-001"}]), out)
        self.started("T-002", "planner")
        self.act_work("T-002", files={"docs/planning/tasks.toml": rewritten(first)})
        return self.hteam("review", "T-002")

    def test_planner_changing_applied_task_fails_precheck(self):
        # 승인 뒤에는 plan apply --append 가 plan_changed 로 실패하고 fix 도 task_closed 라 승인 전에 막는다
        code, out = self.applied_then_planner(lambda first: first.replace("a 제목", "바뀐 제목"))
        self.assertEqual((code, out.get("status"), out.get("source")), (0, "changes", "hteam"), out)
        self.assertTrue(any("plan check 를 통과하지 못한다: 이미 적용한 a 의 내용이 바뀌었다" in x
                            for x in out["problems"]), out["problems"])

    def test_planner_appending_tasks_passes_precheck(self):
        more = '\n[[task]]\nkey = "b"\nrole = "tester"\ntitle = "b 제목"\nowns = ["tests/**"]\n' \
               'depends_on = ["a"]\ntarget = "대상"\nchange = "바꿀 것"\nconstraints = "제약"\nacceptance = ["확인 1"]\n'
        code, out = self.applied_then_planner(lambda first: first + more)
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)

    def test_partial_plan_apply_is_not_sent_back_to_the_planner(self):
        # 앞선 plan apply 가 사양 일부만 커밋하고 멈췄다(plan_incomplete). 기획자가 고칠 수 없으므로 수정 라운드로 보내지
        # 않고 코디네이터에게 exit 3 으로 알린다
        two = ('[[task]]\nkey = "a"\nrole = "developer"\ntitle = "a 제목"\nowns = ["src/**"]\n'
               'target = "대상"\nchange = "바꿀 것"\nconstraints = "제약"\nacceptance = ["확인 1"]\n\n'
               '[[task]]\nkey = "b"\nrole = "tester"\ntitle = "b 제목"\nowns = ["tests/**"]\n'
               'target = "대상"\nchange = "바꿀 것"\nconstraints = "제약"\nacceptance = ["확인 1"]\n')
        self.commit("docs/planning/tasks.toml", two, "기획 초안")
        code, _ = self.hteam("plan", "apply", env={"HTEAM_TEST_DIE_AT": "plan_before_commit"})
        self.assertEqual(code, 137)
        self.git("add", "--", ".herdr-team/tasks/T-001.md")
        self.git("commit", "-q", "-m", "a 만 커밋", "--", ".herdr-team/tasks/T-001.md")
        self.started("T-003", "planner")
        self.act_work("T-003", files={"docs/planning/spec.md": "기획\n"})
        code, out = self.hteam("review", "T-003")
        self.assertEqual((code, out["error"]["code"]), (3, "plan_incomplete"), out)
        self.assertIn("같은 review 를 다시 한다", out["error"]["hint"])
        self.assertEqual(self.task_state("T-003")["status"], "working")
        self.assertFalse((self.proj / "docs/reviews/T-003").exists())

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

    def test_staged_rename_out_of_product_is_tamper(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        self.git("mv", "src/app.py", "docs/reviews/T-001/hidden.py")  # 리뷰어가 제품 파일을 제외 경로로 옮겼다
        code, out = self.finish()
        self.assertEqual((code, out.get("error", {}).get("code")), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])

    def stage_then_restore(self, rel: str, text: str) -> None:
        """rel 을 text 로 고쳐 스테이징한 뒤 작업 트리만 되돌린다. `git diff HEAD` 에는 나오지 않고 인덱스에만 남는다."""
        path = self.proj / rel
        original = path.read_text(encoding="utf-8")
        path.write_text(text, encoding="utf-8")
        self.git("add", "--", rel)
        path.write_text(original, encoding="utf-8")
        self.assertEqual(self.git("diff", "--name-only", "HEAD", "--", rel), "")
        self.assertEqual(self.git("diff", "--cached", "--name-only", "--", rel).split(), [rel])

    def test_staged_then_restored_product_edit_is_tamper(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        self.stage_then_restore("src/app.py", "리뷰어가 고침\n")
        code, out = self.finish()
        self.assertEqual((code, out.get("error", {}).get("code")), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])

    def test_index_only_change_kept_from_baseline_is_not_tamper(self):
        self.worked()
        self.stage_then_restore("README.md", "리뷰 전에 스테이징\n")  # owns 밖이라 사전 검사는 보지 않는다
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertIn("README.md", self.attempt("T-001")["baseline"]["index"])
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def test_non_utf8_name_elsewhere_in_index_does_not_break_review(self):
        # 기준점·변조 검사는 인덱스 전체를 읽는다. 무관한 비 UTF-8 파일명 하나가 디코딩 오류로 리뷰를 막지 않아야 한다.
        # macOS(APFS) 는 그런 파일을 만들지 못하므로 git plumbing 으로 인덱스에만 넣고 skip-worktree(sparse 처럼)로 둔다
        import subprocess
        name = os.fsencode("bad-") + b"\xff.txt"
        git = ["git", "-C", str(self.proj)]
        made = subprocess.run(git + ["hash-object", "-w", "--stdin"], input=b"x\n", capture_output=True, env=self.env)
        sha = made.stdout.strip()
        for args in (["update-index", "--add", "--cacheinfo", b"100644," + sha + b"," + name],
                     ["update-index", "--skip-worktree", name], ["commit", "-q", "-m", "비 UTF-8 이름"]):
            done = subprocess.run(git + args, capture_output=True, env=self.env)
            if done.returncode:
                self.skipTest(f"git 이 비 UTF-8 이름을 받지 않는다: {done.stderr!r}")
        self.assertIn(name, subprocess.run(git + ["ls-files", "-z"], capture_output=True, env=self.env).stdout)
        self.worked()
        (self.proj / "README.md").write_text("owns 밖, 커밋 안 함\n")  # 바뀐 추적 파일이 있어야 인덱스를 읽는다
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertIn("README.md", self.attempt("T-001")["baseline"]["index"])
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def test_committed_rename_out_of_product_is_tamper(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        self.git("mv", "src/app.py", "docs/reviews/T-001/hidden.py")
        self.git("commit", "-q", "-m", "리뷰어 커밋")
        code, out = self.finish()
        self.assertEqual((code, out.get("error", {}).get("code")), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])

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


class TamperEntryTest(ReviewCase):
    """변조 검사는 git 이 보는 항목(모드와 객체 ID)으로 견준다: 심볼릭 링크, 실행 비트, 링크 폴더, 손실 없는 경로."""

    def finish(self):
        return self.hteam("review-finish", "T-001")

    def assert_tamper(self, path):
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertIn(path, out["tamper"]["paths"])
        return out

    def test_file_swapped_for_symlink_with_same_content_is_tamper(self):
        self.reviewing()
        outside = self.tmp / "outside.md"
        outside.write_text("# proj\n")  # README.md 와 같은 내용
        readme = self.proj / "README.md"
        readme.unlink()
        readme.symlink_to(outside)
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_folder_swapped_for_symlink_is_tamper(self):
        self.commit("lib/x.txt", "x\n", "lib")
        self.reviewing()
        (self.proj / "lib").rename(self.tmp / "lib-real")
        (self.proj / "lib").symlink_to(self.tmp / "lib-real")  # lib/x.txt 의 내용은 그대로 읽힌다
        self.assert_tamper("lib/x.txt")

    def test_exec_bit_change_is_tamper(self):
        self.reviewing()
        os.chmod(self.proj / "README.md", 0o755)
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_exec_bit_is_ignored_when_git_ignores_modes(self):
        self.git("config", "core.fileMode", "false")
        self.reviewing()
        os.chmod(self.proj / "README.md", 0o755)
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def test_staged_exec_bit_is_tamper_even_when_git_ignores_modes(self):
        # core.fileMode=false 는 작업 트리의 실행 비트만 믿지 않는다. 인덱스에 올린 모드 변경은 실제 변경이다
        self.git("config", "core.fileMode", "false")
        self.reviewing()
        self.git("update-index", "--chmod=+x", "README.md")
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_file_mode_flipped_during_review_does_not_hide_chmod(self):
        self.reviewing()
        os.chmod(self.proj / "README.md", 0o755)
        self.git("config", "core.fileMode", "false")  # 리뷰어가 설정을 바꿔 숨기려 했다
        self.assert_tamper("README.md")

    def test_carriage_return_in_path_is_read_losslessly(self):
        name = "a\rb.txt"
        try:
            self.commit(name, "x\n", "cr")
        except (OSError, AssertionError) as exc:
            self.skipTest(f"이 파일 시스템은 \\r 이 든 이름을 만들지 못한다: {exc}")
        self.reviewing()
        (self.proj / name).write_text("리뷰어가 고침\n")
        self.assertEqual(self.assert_tamper(name)["tamper"]["paths"], [name])

    def test_non_utf8_changed_path_is_kept_losslessly(self):
        # 기준점의 바뀐 경로에 UTF-8 이 아닌 이름이 있어도 리뷰가 멈추지 않고 그 이름 그대로 견준다. macOS(APFS) 는 그런
        # 파일을 만들지 못하므로 인덱스에만 넣고(skip-worktree) 스테이징만 바꾼다
        import subprocess
        name = os.fsencode("bad-") + b"\xff.txt"
        git = ["git", "-C", str(self.proj)]

        def plumb(*args, data=None):
            done = subprocess.run(git + list(args), input=data, capture_output=True, env=self.env)
            if done.returncode:
                self.skipTest(f"git 이 비 UTF-8 이름을 받지 않는다: {done.stderr!r}")
            return done.stdout.strip()
        one = plumb("hash-object", "-w", "--stdin", data=b"1\n")
        two = plumb("hash-object", "-w", "--stdin", data=b"2\n")
        plumb("update-index", "--add", "--cacheinfo", b"100644," + one + b"," + name)
        plumb("update-index", "--skip-worktree", name)
        plumb("commit", "-q", "-m", "비 UTF-8 이름")
        plumb("update-index", "--cacheinfo", b"100644," + two + b"," + name)  # 스테이징만 바뀌었다(기준점에 남는다)
        self.worked()
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "reviewing"), out)
        self.assertIn(os.fsdecode(name), self.attempt("T-001")["baseline"]["index"])
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def test_non_utf8_tamper_path_is_printed_losslessly(self):
        # 리뷰 동안 UTF-8 이 아닌 이름의 스테이징이 바뀌면 변조다. stdout JSON 은 올바른 UTF-8 이고 경로는 같은 바이트로
        # 되돌아가며, 메시지에는 show 꼴(\xff)로 보인다
        import subprocess
        import sys
        from tests.helpers import BIN
        name = os.fsencode("bad-") + b"\xff.txt"
        git = ["git", "-C", str(self.proj)]

        def plumb(*args, data=None):
            done = subprocess.run(git + list(args), input=data, capture_output=True, env=self.env)
            if done.returncode:
                self.skipTest(f"git 이 비 UTF-8 이름을 받지 않는다: {done.stderr!r}")
            return done.stdout.strip()
        one = plumb("hash-object", "-w", "--stdin", data=b"1\n")
        two = plumb("hash-object", "-w", "--stdin", data=b"2\n")
        plumb("update-index", "--add", "--cacheinfo", b"100644," + one + b"," + name)
        plumb("update-index", "--skip-worktree", name)
        plumb("commit", "-q", "-m", "비 UTF-8 이름")
        self.reviewing()
        plumb("update-index", "--cacheinfo", b"100644," + two + b"," + name)  # 리뷰어가 스테이징을 바꿨다
        self.act_review("T-001", "APPROVE")
        proc = subprocess.run([sys.executable, str(BIN), "review-finish", "T-001"], capture_output=True,
                              env=self._env("coordinator", None, None), cwd=str(self.proj), timeout=60)
        out = json.loads(proc.stdout.decode("utf-8").strip().split("\n")[-1])  # 엄격한 UTF-8 디코딩
        self.assertEqual((proc.returncode, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertEqual([os.fsencode(x) for x in out["tamper"]["paths"]], [name])
        self.assertIn("bad-\\xff.txt", out["error"]["message"])

    def test_symlink_replaced_by_regular_file_is_tamper(self):
        os.symlink("README.md", self.proj / "lnk")
        self.git("add", "--", "lnk")
        self.git("commit", "-q", "-m", "링크", "--", "lnk")
        self.reviewing()
        (self.proj / "lnk").unlink()
        (self.proj / "lnk").write_text("README.md")  # 링크 글자와 같은 내용(같은 blob)의 일반 파일
        self.assertEqual(self.assert_tamper("lnk")["tamper"]["paths"], ["lnk"])

    def test_assume_unchanged_edit_is_tamper(self):
        self.reviewing()
        (self.proj / "README.md").write_text("리뷰어가 고침\n")
        self.git("update-index", "--assume-unchanged", "README.md")  # git diff·status 가 보지 않게 숨겼다
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_skip_worktree_edit_is_tamper(self):
        self.reviewing()
        (self.proj / "README.md").write_text("리뷰어가 고침\n")
        self.git("update-index", "--skip-worktree", "README.md")
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_ignore_stat_set_during_review_is_tamper(self):
        self.reviewing()
        self.git("config", "core.ignoreStat", "true")
        self.git("update-index", "--really-refresh")  # 모든 항목에 assume-unchanged 가 붙는다
        (self.proj / "README.md").write_text("리뷰어가 고침\n")
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_fake_fsmonitor_does_not_hide_edit(self):
        # 가짜 fsmonitor 훅이 "바뀐 것 없음"(토큰만, 경로 없음)을 답하면 git diff·status 가 stat 을 건너뛰어 변경을 놓친다
        # (아무것도 내지 않는 훅은 git 이 경고하고 다시 훑으므로 숨기지 못한다)
        self.reviewing()
        hook = self.tmp / "fsmonitor-hook"
        hook.write_text('#!/bin/sh\nprintf "tok\\0"\n')
        os.chmod(hook, 0o755)
        self.git("config", "core.fsmonitor", str(hook))
        self.git("update-index", "--fsmonitor")
        self.git("status", "--porcelain")
        (self.proj / "README.md").write_text("리뷰어가 고침\n")
        self.assertEqual(self.git("diff", "--name-only", "HEAD"), "")  # git 은 정말 보지 못한다
        self.assertEqual(self.assert_tamper("README.md")["tamper"]["paths"], ["README.md"])

    def test_clean_submodule_is_not_tamper(self):
        self.submodule()
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        code, out = self.finish()
        self.assertEqual((code, out.get("status")), (0, "approved"), out)

    def test_dirty_submodule_content_is_tamper(self):
        # 서브모듈 HEAD 는 그대로지만 안의 추적 파일을 고쳤다(커밋하지 않음)
        self.submodule()
        self.reviewing()
        (self.proj / "sub" / "a.txt").write_text("evil\n")
        self.assertEqual(self.assert_tamper("sub")["tamper"]["paths"], ["sub"])

    def test_staged_submodule_content_is_tamper(self):
        self.submodule()
        self.reviewing()
        (self.proj / "sub" / "a.txt").write_text("evil\n")
        self.git("-C", "sub", "add", "a.txt")
        self.assertEqual(self.assert_tamper("sub")["tamper"]["paths"], ["sub"])

    def test_submodule_dirty_at_baseline_changed_again_is_tamper(self):
        self.submodule()
        (self.proj / "sub" / "a.txt").write_text("before\n")  # 기준점 때 이미 고쳐져 있었다
        self.reviewing()
        (self.proj / "sub" / "a.txt").write_text("evil\n")
        self.assertEqual(self.assert_tamper("sub")["tamper"]["paths"], ["sub"])

    def test_newline_in_path_is_shown_escaped_in_commit_body(self):
        # 경로의 줄바꿈이 목록 한 줄을 둘로 나누지 않는다. JSON 값은 그대로다
        self.reviewing()
        self.act_review("T-001", "APPROVE", extra={"write": {"x\ny.log": "x\n"}})
        code, out = self.finish()
        self.assertEqual((code, out.get("status"), out.get("warnings")), (0, "approved", ["x\ny.log"]), out)
        self.assertIn("- x\\ny.log\n", self.git("log", "-1", "--format=%b"))


class LosslessJsonTest(unittest.TestCase):
    def test_surrogates_round_trip_as_valid_utf8(self):
        from hteam.util import dumps, show
        value = {"bad-\udcff.txt": ["a\rb", "정상"]}
        text = dumps(value, indent=2)
        text.encode("utf-8")  # 올바른 UTF-8 이다(짝 없는 서로게이트는 이스케이프됐다)
        self.assertIn("\\udcff", text)
        self.assertEqual(json.loads(text), value)
        self.assertEqual(show("bad-\udcff.txt"), "bad-\\xff.txt")
        self.assertEqual(show("정상 a\rb"), "정상 a\rb")
        self.assertEqual(show("a\nb.txt"), "a\\nb.txt")  # 줄바꿈은 보이게(목록 한 줄이 나뉘지 않게)


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

    def test_auto_retry_survives_crash_after_failed_record(self):
        self.reviewing()
        self.act_review("T-001", write=False)
        code, _ = self.hteam("review-finish", "T-001", env={"HTEAM_TEST_DIE_AT": "after_fail"})
        self.assertEqual(code, 137)
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")
        code, out = self.hteam("review-finish", "T-001")  # 자동 재시도가 남아 있다. 띄우기는 review 가 이어 한다
        self.assertEqual((code, out.get("error", {}).get("code")), (3, "review_not_launched"), out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("attempt"), out.get("status")), (0, 2, "reviewing"), out)
        self.act_review("T-001", "APPROVE")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("status"), out.get("attempt")), (0, "approved", 2), out)

    def test_undecodable_review_file_is_failed_attempt(self):
        self.reviewing()
        self.act_review("T-001", write=False)
        path = self.proj / self.attempt("T-001")["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\nVERDICT: APPROVE\n")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("retried"), out.get("failed_attempt")), (0, True, 1), out)
        self.assertIn("UTF-8", out["reason"])

    @unittest.skipIf(os.geteuid() == 0, "root 는 권한과 무관하게 읽는다")
    def test_unreadable_review_file_is_failed_attempt(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        (self.proj / self.attempt("T-001")["file"]).chmod(0)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("retried"), out.get("failed_attempt")), (0, True, 1), out)
        self.assertIn("읽지 못했다", out["reason"])

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

    def test_recorded_recovery_repicks_attempt_under_lock(self):
        self.reviewing()
        with state.edit(self.p, "T-001") as st:  # 리뷰 Dispatch 를 기록한 뒤 reviewing 전이 전에 죽었다
            state.move(st, "working", "test")
        proc, release, wait = self.paused("recover_recorded", "review", "T-001")
        self.assertTrue(wait())
        with state.edit(self.p, "T-001") as st:  # 그 사이 fix 가 취소를 저장하고 새 라운드를 썼다
            st["rounds"][-1]["reviews"][0]["canceled"] = True
            st["rounds"].append({"round": 2, "work": {"title": "T-001 r2 작업", "canceled": False}, "reviews": [],
                                 "verdict": None})
        release()
        code, out = self.finish(proc)
        self.assertEqual((code, out.get("error", {}).get("code")), (3, "attempt_missing"), out)
        self.assertEqual(self.task_state("T-001")["status"], "working")

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

    def test_file_changed_after_verdict_record_is_not_finalized(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        proc, release, wait = self.paused("after_verdict", "review-finish", "T-001")
        self.assertTrue(wait())
        (self.proj / "docs/reviews/T-001/r1-a1.md").write_text("VERDICT: REQUEST_CHANGES\n")
        release()
        code, out = self.finish(proc)
        self.assertEqual((code, out.get("retried")), (0, True), out)  # 읽은 바이트와 다른 파일은 최종화하지 않는다
        self.assertNotIn("review r1", self.git("log", "--format=%s"))

    def test_cancel_during_finish_is_not_undone(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        proc, release, wait = self.paused("after_verdict", "review-finish", "T-001")
        self.assertTrue(wait())
        with state.edit(self.p, "T-001") as st:  # drop 이 끝나지 않은 시도에 취소를 저장했다
            st["rounds"][-1]["reviews"][0]["canceled"] = True
        release()
        code, out = self.finish(proc)
        self.assertEqual((code, out.get("error", {}).get("code")), (3, "round_canceled"), out)
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")
        self.assertNotIn("review r1", self.git("log", "--format=%s"))

    def test_resume_after_commit_reports_commit(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        code, _ = self.hteam("review-finish", "T-001", env={"HTEAM_TEST_DIE_AT": "after_commit"})
        self.assertEqual(code, 137)
        sha = self.head()
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("status"), out.get("commit")), (0, "approved", sha), out)
        self.assertEqual(self.head(), sha)

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


class OverlapTest(ReviewCase):
    def test_overlapping_finishes_are_serialized(self):
        """첫 호출이 판정을 읽기 전에 멈춘 사이 둘째 호출이 판정을 기록하고 파일을 옮기면, 옛 시도 정보를 쥔 첫 호출이
        파일 없음으로 a2 를 띄우고 둘째가 approved 로 옮겨 승인된 태스크에 리뷰어가 남는다."""
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        first, release_first, wait_first = self.paused("before_verdict", "review-finish", "T-001")
        self.assertTrue(wait_first())
        second, release_second, wait_second = self.paused("after_move", "review-finish", "T-001")
        reached = wait_second(timeout=3)  # 직렬화되면 첫 호출이 끝날 때까지 여기 오지 못한다
        release_first()
        code1, out1 = self.finish(first)
        release_second()
        code2, out2 = self.finish(second)
        st = self.task_state("T-001")
        self.assertEqual(len(st["rounds"][0]["reviews"]), 1, (out1, out2))  # a2 를 띄우지 않았다
        self.assertEqual((st["status"], sorted([code1, code2])), ("approved", [0, 3]), (out1, out2))
        self.assertFalse(reached)


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
        # 프로젝트 밖의 추적하지 않는 새 파일은 보지 않는다(설계 6.3 3)
        self.act_review("T-001", "APPROVE", extra={"write": {"scratch.log": "x\n", "../top.log": "x\n"}})
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"], out["file"], out["warnings"]),
                         (0, "approved", "docs/reviews/T-001/r1.md", ["scratch.log"]), out)
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

    def test_tamper_is_scoped_to_project(self):
        self.reviewing()
        # 프로젝트 안 추적 파일을 지우고(기준 blob 을 최상위 경로로 읽어야 잡힌다) 프로젝트 밖 추적 파일을 바꾼다
        self.act_review("T-001", "APPROVE", extra={"delete": ["src/app.py"], "write": {"../README.md": "리뷰어\n"}})
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])  # 프로젝트 밖은 경고다
        self.assertEqual(self.attempt("T-001")["warnings"], ["../README.md"])

    def test_index_only_tamper_is_scoped_to_project(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE")
        for rel, text in (("src/app.py", "리뷰어가 고침\n"), ("../README.md", "리뷰어\n")):
            path = self.proj / rel  # 스테이징한 뒤 작업 트리만 되돌린다(인덱스에만 남는다)
            original = path.read_text(encoding="utf-8")
            path.write_text(text, encoding="utf-8")
            self.git("add", "--", rel)
            path.write_text(original, encoding="utf-8")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("error", {}).get("code")), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])  # 프로젝트 밖은 경고다
        self.assertEqual(self.attempt("T-001")["warnings"], ["../README.md"])

    def test_outside_changes_during_review_are_warnings(self):
        self.reviewing()
        self.commit("../other/x.txt", "x\n", "형제 프로젝트 커밋")  # 리뷰 중 저장소의 다른 곳에서 커밋했다
        self.act_review("T-001", "APPROVE", extra={"write": {"../README.md": "다른 사람\n", "scratch.log": "x\n"}})
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["status"], out["warnings"]),
                         (0, "approved", ["../README.md", "../other/x.txt", "scratch.log"]), out)
        body = self.git("log", "-1", "--format=%b")
        for needle in ("../README.md", "../other/x.txt", "scratch.log"):
            self.assertIn(needle, body)

    def test_task_commit_only_outside_project_fails_precheck(self):
        """사전 검사는 태스크 커밋을 경로로 거르지 않는다: 프로젝트 밖만 고친 `[T-001]` 커밋도 owns 밖으로 지적한다
        (같은 저장소의 여러 herdr-team 프로젝트가 ID 를 겹쳐 쓰는 구성은 지원하지 않는다, 설계 6.3 3)."""
        self.started()
        self.commit("../outside.txt", "x\n", "[T-001] 프로젝트 밖만 고침")
        self.act_work("T-001")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status"), out.get("source")), (0, "changes", "hteam"), out)
        self.assertIn("owns 밖 경로의 내용이 base 와 다르다: ../outside.txt", out["problems"])

    def test_diff_relative_config_does_not_hide_changes(self):
        self.git("config", "diff.relative", "true")  # 리뷰어도 .git/config 에 쓸 수 있다
        self.started()
        self.act_work("T-001", files={"src/app.py": "x\n", "../README.md": "바꿈\n"})
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out.get("status")), (0, "changes"), out)
        self.assertIn("owns 밖 경로의 내용이 base 와 다르다: ../README.md", out["problems"])

    def test_diff_relative_config_does_not_hide_tamper(self):
        self.reviewing()
        self.act_review("T-001", "APPROVE", extra={"write": {"src/app.py": "리뷰어가 고침\n"}})
        self.git("config", "diff.relative", "true")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out.get("error", {}).get("code")), (1, "review_tampered"), out)
        self.assertEqual(out["tamper"]["paths"], ["src/app.py"])

    def test_precheck_crash_before_commit_keeps_problems(self):
        """owns 가 `**/*.md` 라 커밋 전에 죽으면 남은 rN.md 가 owns 안 미커밋 변경으로 보일 수 있다."""
        self.started()
        self.act_work("T-001")
        (self.proj / "src/app.py").write_text("커밋 안 함\n")
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_precheck_write"})
        self.assertEqual(code, 137)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "changes"), out)
        self.assertEqual(out["problems"], ["owns 안에 커밋하지 않은 변경이 있다: src/app.py"])


class GitPathTest(unittest.TestCase):
    def test_from_top_and_back(self):
        for prefix, top, rel in (("", "src/a.py", "src/a.py"), ("sub/", "sub/src/a.py", "src/a.py"),
                                 ("sub/", "README.md", "../README.md"), ("a/b/", "a/c.py", "../c.py"),
                                 ("sub/", "subx/y", "../subx/y")):
            self.assertEqual(gitio.from_top(prefix, top), rel)
            self.assertEqual(gitio.to_top(prefix, rel), top)


if __name__ == "__main__":
    unittest.main()
