"""accept·fix·drop(설계 6.4)와 수정 라운드."""
import contextlib
import fcntl
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import dispatch, horch, procs, review, state, tasks
from hteam.errors import HteamError
from hteam.paths import Project

FILES = {"developer": {"src/app.py": "print(1)\n"}, "tester": {"tests/t.py": "assert True\n"}}


class LifeCase(TeamCase):
    config = BASE_CONFIG

    def setUp(self):
        super().setUp()
        self.init_project(config=self.config)
        self.setup_run()
        self.p = Project(self.proj)

    def to_verdict(self, tid="T-001", role="developer", verdict="APPROVE"):
        self.write_spec(tid, role)
        state.create(self.p, tid, role)
        self.assertEqual(self.hteam("start", tid)[0], 0)
        self.act_work(tid, FILES[role])
        self.assertEqual(self.hteam("review", tid)[1]["status"], "reviewing")
        self.act_review(tid, verdict)
        code, out = self.hteam("review-finish", tid)
        self.assertEqual(code, 0, out)
        return out

    def active_rows(self):
        _, rows = self.horch("worker-list")
        return [r["id"] for r in rows["workers"] if r["state"] == "active"]

    @contextlib.contextmanager
    def in_process(self):
        """hteam 을 이 프로세스에서 부른다(경합 지점에 끼어들려고). horch 는 테스트 환경을 물려받는다."""
        with mock.patch.dict(os.environ, self._env("coordinator", None, None), clear=True):
            yield

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

    def lock_file(self, which: str, tid: str = "T-001") -> Path:
        return {"project": self.state_dir / "lock", "finish": self.state_dir / "tasks" / f"{tid}.finish.lock",
                "task": self.state_dir / "tasks" / f"{tid}.lock"}[which]

    def held(self, which: str, tid: str = "T-001") -> bool:
        """다른 프로세스가 그 잠금을 쥐고 있나(LOCK_NB 로 잡아 본다. 잡히면 바로 놓는다). 시간에 기대지 않는다."""
        with open(self.lock_file(which, tid), "a+") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(fh, fcntl.LOCK_UN)
            return False

    def first_call_then(self, name: str, hook):
        """tasks.<name> 의 첫 호출이 끝난 직후 hook() 을 한 번 부르는 대역(경합 지점에 끼어든다)."""
        real = getattr(tasks, name)
        calls = []

        def wrapper(*a, **kw):
            res = real(*a, **kw)
            if not calls:
                calls.append(1)
                hook()
            return res
        return mock.patch.object(tasks, name, wrapper)


class AcceptTest(LifeCase):
    config = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["tester"]')

    def test_accept_done_and_release(self):
        self.to_verdict()
        did = self.work_dispatch("T-001")
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"], out["warnings"]), (0, "done", []), out)
        self.assertEqual(self.dispatch_row(did)["state"], "released")
        self.assertTrue(self.task_state("T-001")["rounds"][0]["work"]["cleaned"])
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "task_closed"))

    def test_approval_role_waits_for_user(self):
        self.to_verdict("T-001", "tester")
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"]), (0, "awaiting_user"))
        self.assertIn("T-001", [s["id"] for s in state.all_states(self.p) if s["status"] in state.LOCKING])
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"]), (0, "done"))

    def test_accept_needs_approved(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "bad_state"))

    def test_accept_releases_older_attempts_of_work_task(self):
        """같은 horch Task 를 다시 띄웠으면 버려진 이전 시도도 정리한다(기록된 Dispatch 만이 아니다)."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        first = self.active_rows()[0]
        self.assertEqual(self.horch("worker-abandon", "--dispatch", first, "--kill")[0], 0)
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"]), (0, "retry"), out)
        self.act_work("T-001")
        self.hteam("review", "T-001")
        self.act_review("T-001", "APPROVE")
        self.assertEqual(self.hteam("review-finish", "T-001")[0], 0)
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"], out["warnings"]), (0, "done", []), out)
        self.assertEqual((self.dispatch_row(first)["state"], self.dispatch_row(out_d := self.work_dispatch("T-001"))
                          ["state"]), ("released", "released"))
        self.assertNotEqual(first, out_d)

    def test_accept_refuses_live_work_worker(self):
        """retain 실패를 견딘 review 로 작업 워커가 active 인 채 approved 가 됐다. accept 는 owns 잠금을 풀지 않고
        exit 3 이다. 워커를 정리한 뒤에는 된다."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        did = self.hteam("start", "T-001")[1]["dispatch"]
        rel = "docs/tasks/T-001/report.md"
        code, out = self.act(did, {"write": FILES["developer"], "report": "## r1\n", "report_path": rel,
                                   "commit": "[T-001] r1 작업"})  # done 없이 커밋만 했다: 워커는 active
        self.assertEqual(code, 0, out)
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)
        self.assertTrue(out["warnings"])  # worker-retain 실패
        self.act_review("T-001", "APPROVE")
        self.assertEqual(self.hteam("review-finish", "T-001")[1]["status"], "approved")
        before = self.task_state("T-001")
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"], out.get("dispatch")), (3, "worker_active", did), out)
        hint = out["error"]["hint"]  # 그대로 실행할 수 있는 horch 명령(절대 경로와 --home)
        self.assertIn(f"--home {self.horch_home} worker-abandon --dispatch {did} --kill", hint)
        self.assertIn(f"--home {self.horch_home} worker-release --dispatch {did}", hint)
        self.assertEqual(self.task_state("T-001"), before)  # 아무것도 바꾸지 않았다
        self.assertEqual(self.dispatch_row(did)["state"], "active")
        self.assertEqual(self.horch("worker-abandon", "--dispatch", did, "--kill")[0], 0)
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["status"], out["warnings"]), (0, "done", []), out)
        self.assertEqual(self.dispatch_row(did)["state"], "released")

    def test_accept_refuses_if_round_changed(self):
        """멈춘 accept 가 r1 을 본 뒤 그 사이 r2 가 같은 상태에 닿았으면 r2 를 닫지 않는다."""
        self.to_verdict()

        def next_round():
            with state.edit(self.p, "T-001") as st:
                st["rounds"].append({**st["rounds"][0], "round": 2, "work": dispatch.new_slot("T-001 r2 작업"),
                                     "reviews": []})
                st["round"] = 2

        real = horch.Horch.workers
        calls = []

        def workers(h, states=None):
            rows = real(h, states)
            if not calls:
                calls.append(1)
                next_round()
            return rows

        with self.in_process(), mock.patch.object(horch.Horch, "workers", workers):
            with self.assertRaises(HteamError) as cm:
                tasks.accept(self.p, "T-001")
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("state_changed", 3))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"][1]["work"]["cleaned"]), ("approved", 2, False))


class FixTest(LifeCase):
    def test_fix_after_changes_starts_round_two(self):
        self.to_verdict(verdict="REQUEST_CHANGES")
        old = self.work_dispatch("T-001")
        base = self.task_state("T-001")["base"]
        head = self.head()
        code, out = self.hteam("fix", "T-001", "--note", "리뷰 지적 반영")
        self.assertEqual((code, out["round"], out["status"]), (0, 2, "working"), out)
        st = self.task_state("T-001")
        self.assertEqual((st["base"], st["rounds"][1]["round_base"], st["rounds"][1]["note"]), (base, head, "리뷰 지적 반영"))
        self.assertEqual(st["rounds"][1]["work"]["title"], "T-001 r2 작업")
        self.assertEqual(self.dispatch_row(old)["state"], "released")
        spec = (self.state_dir / "tasks/T-001/r2-work.md").read_text()
        for needle in ("## 수정 라운드 r2", "`docs/reviews/T-001/r1.md` 리뷰를 읽고 막는 지적", "코디네이터 메모: 리뷰 지적 반영"):
            self.assertIn(needle, spec)
        self.act_work("T-001")
        code, out = self.hteam("review", "T-001")
        self.assertEqual(code, 0, out)
        subjects = [c["subject"] for c in self.attempt("T-001")["inputs"]["commits"]]
        self.assertEqual(subjects, ["[T-001] r1 작업", "[T-001] r2 작업"])  # review 커밋은 빠진다
        self.assertEqual(self.attempt("T-001")["title"], "T-001 r2 리뷰 a1")

    def test_max_rounds_and_force_round(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.to_verdict(verdict="REQUEST_CHANGES")
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["error"]["code"], out["max_rounds"]), (3, "max_rounds", 1))
        code, out = self.hteam("fix", "T-001", "--force-round", "--note", "사용자가 계속")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertTrue(self.task_state("T-001")["history"][-2]["force_round"])

    def test_fix_after_failed_worker_and_active_worker(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001", outcome="failed")
        old = self.work_dispatch("T-001")
        code, out = self.hteam("fix", "T-001", "--note", "실패 원인")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertEqual(self.dispatch_row(old)["state"], "released")
        active = self.work_dispatch("T-001")
        code, out = self.hteam("fix", "T-001", "--model", "haiku")  # 일하는 중인 워커는 abandon --kill 뒤 release
        self.assertEqual((code, out["round"], out["model"]), (0, 3, "haiku"), out)
        self.assertEqual(self.dispatch_row(active)["state"], "released")

    def test_fix_from_awaiting_user_ignores_limit_and_supplement(self):
        (self.team / "config.toml").write_text(
            BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1").replace("user_approval_roles = []",
                                                                           'user_approval_roles = ["tester"]'))
        self.to_verdict("T-001", "tester")
        self.hteam("accept", "T-001")
        code, out = self.hteam("fix", "T-001", "--supplement", "T-404")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_task"))
        code, out = self.hteam("fix", "T-001", "--supplement", "../x")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_task_id"))
        self.write_spec("T-002", "director", commit=False)  # --supplement 는 끝난 디렉터 보강 태스크만 받는다
        state.create(self.p, "T-002", "director")
        code, out = self.hteam("fix", "T-001", "--supplement", "T-002")
        self.assertEqual((code, out["error"]["code"]), (3, "supplement_not_done"), out)
        with state.edit(self.p, "T-002") as st:
            state.move(st, "done", "test")
        code, out = self.hteam("fix", "T-001", "--supplement", "T-002", "--note", "사용자 수정 요청")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertEqual(self.task_state("T-001")["rounds"][1]["supplement"], "T-002")
        self.assertIn("디렉터 보강 태스크 T-002", (self.state_dir / "tasks/T-001/r2-work.md").read_text())

    def test_fix_refused_while_reviewing(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001")
        self.hteam("review", "T-001")
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "bad_state"))

    def test_fix_aligns_role_with_spec(self):
        """사양의 직무가 바뀌었으면 새 라운드를 쓸 때 저장된 직무도 맞춘다(planner 하나 검사가 저장된 직무를 본다)."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001", outcome="failed")
        self.write_spec("T-001", "planner", owns="docs/planning/a/**")
        code, out = self.hteam("fix", "T-001", "--note", "기획으로")
        self.assertEqual((code, out["round"]), (0, 2), out)
        st = self.task_state("T-001")
        self.assertEqual((st["role"], st["owns"]), ("planner", ["docs/planning/a/**"]))
        self.write_spec("T-002", "planner", owns="docs/planning/b/**")
        state.create(self.p, "T-002", "planner")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"]), (3, "planner_busy"), out)


class DropTest(LifeCase):
    def started(self, tid="T-001"):
        self.write_spec(tid)
        state.create(self.p, tid, "developer")
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def test_drop_pending_and_closed(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"))
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "task_closed"))

    def test_active_worker_needs_force(self):
        out = self.started()
        code, res = self.hteam("drop", "T-001")
        self.assertEqual((code, res["error"]["code"]), (3, "worker_active"))
        self.assertEqual(self.task_state("T-001")["status"], "working")
        code, res = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")
        self.assertTrue(self.task_state("T-001")["rounds"][0]["work"]["canceled"])

    def test_launch_failed_is_left_to_horch(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")
        horch_task = self.task_state("T-001")["rounds"][0]["work"]["horch_task"]
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["released"]), (0, []), out)
        _, rows = self.horch("worker-list")
        self.assertEqual([r["state"] for r in rows["workers"] if r["task"] == horch_task], ["launch_failed"])

    def test_drop_while_reviewing_releases_both(self):
        out = self.started()
        self.act_work("T-001")
        rev = self.hteam("review", "T-001")[1]
        code, res = self.hteam("drop", "T-001", "--force")
        self.assertEqual(code, 0, res)
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "released")
        self.assertEqual(self.dispatch_row(rev["dispatch"])["state"], "released")
        self.assertTrue(self.attempt("T-001")["canceled"])
        code, res = self.hteam("review", "T-001")
        self.assertEqual((code, res["error"]["code"]), (3, "task_closed"))

    def test_unrecorded_launch_found_by_title(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "worker_active"))
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["released"][0]["state"]), (0, "released"), out)


class DropRerunTest(LifeCase):
    def reviewing(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        work = self.hteam("start", "T-001")[1]["dispatch"]
        self.act_work("T-001")
        rev = self.hteam("review", "T-001")[1]["dispatch"]  # 작업 retained, 리뷰어 active
        return work, rev

    def assert_dropped_and_clean(self, work, rev):
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.assertEqual((self.dispatch_row(work)["state"], self.dispatch_row(rev)["state"]), ("released", "released"))
        rd = self.task_state("T-001")["rounds"][0]
        self.assertTrue(rd["work"]["cleaned"] and rd["reviews"][0]["cleaned"])

    def test_rerun_after_dying_right_after_cancel(self):
        work, rev = self.reviewing()
        code, _ = self.hteam("drop", "T-001", "--force", env={"HTEAM_TEST_DIE_AT": "after_cancel"})
        self.assertEqual(code, 137)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["reviews"][0]["canceled"]), ("reviewing", True))
        self.assert_dropped_and_clean(work, rev)  # 취소된 시도의 리뷰어도 정리한다

    def test_rerun_after_release_failure(self):
        work, rev = self.reviewing()
        self.fail_hc("get", "boom")  # 작업 Dispatch release 가 hc get 에서 실패한다
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual(code, 1, out)
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")  # 정리를 확인하기 전에는 dropped 가 아니다
        self.assertEqual(self.dispatch_row(rev)["state"], "active")
        with self._hc_locked() as hc:
            hc["fail"].clear()
        self.assert_dropped_and_clean(work, rev)

    def test_rerun_after_dying_between_release_and_cleaned_record(self):
        """release 뒤 cleaned 를 쓰기 전에 죽었다. 다시 부르면 그 Dispatch 는 대상이 아니지만 기록에는 cleaned 를 쓴다."""
        work, rev = self.reviewing()
        code, _ = self.hteam("drop", "T-001", "--force", env={"HTEAM_TEST_DIE_AT": "after_release"})
        self.assertEqual(code, 137)
        self.assertEqual(self.dispatch_row(work)["state"], "released")  # 첫 대상(작업)은 release 했다
        self.assertFalse(self.task_state("T-001")["rounds"][0]["work"]["cleaned"])
        self.assert_dropped_and_clean(work, rev)


class CloseOrderTest(LifeCase):
    """fix·drop 의 순서 규칙: 취소 저장 → 정리 → 마지막 전이. 어디서 멈춰도 복구가 되살리지 않고 다시 부르면 끝난다."""

    def test_fix_failing_after_cleanup_blocks_recovery_then_rerun_finishes(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})  # 기록되지 않은 워커
        old = self.active_rows()[0]
        doc = self.team / "roles" / "developer.md"
        doc.rename(self.tmp / "developer.md")
        code, out = self.hteam("fix", "T-001", "--note", "x")  # 정리 뒤 새 라운드 작성이 실패한다
        self.assertEqual((code, out["error"]["code"]), (2, "no_role_doc"), out)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"][0]["work"]["canceled"]), ("launch_failed", 1, True))
        self.assertEqual(self.dispatch_row(old)["state"], "released")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "launch_canceled"))  # 취소된 실행 키는 되살리지 않는다
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "round_canceled"))
        self.assertEqual(self.active_rows(), [])
        (self.tmp / "developer.md").rename(doc)
        code, out = self.hteam("fix", "T-001", "--note", "x")
        self.assertEqual((code, out["round"], self.active_rows()), (0, 2, [out["dispatch"]]), out)

    def test_fix_failing_in_working_then_drop_finishes(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        did = self.hteam("start", "T-001")[1]["dispatch"]
        (self.team / "roles" / "developer.md").unlink()
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "no_role_doc"))
        self.assertEqual(self.dispatch_row(did)["state"], "released")
        code, out = self.hteam("drop", "T-001")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)

    def test_close_releases_older_attempts_of_same_task(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        first = self.active_rows()[0]
        self.assertEqual(self.horch("worker-abandon", "--dispatch", first, "--kill")[0], 0)  # 코디네이터가 버렸다
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"]), (0, "retry"), out)  # 같은 Task 를 다시 띄웠다
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(r["dispatch"] for r in out["released"]), sorted([first, out_d := self.work_dispatch("T-001")]))
        self.assertEqual((self.dispatch_row(first)["state"], self.dispatch_row(out_d)["state"]), ("released", "released"))

    def test_failed_drop_blocks_review_retry(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001")
        self.hteam("review", "T-001")
        self.act_review("T-001", write=False)
        self.assertTrue(self.hteam("review-finish", "T-001")[1]["retried"])  # a1 실패, a2 진행 중
        self.fail_hc("get", "boom")
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 1)  # 취소를 저장한 뒤 정리 중 실패
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("review", "T-001", "--retry")
        self.assertEqual((code, out["error"]["code"]), (3, "round_canceled"))
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.assertEqual(self.active_rows(), [])

    def test_failed_drop_after_review_failed_blocks_review_retry(self):
        """끝나지 않은 시도가 없는 reviewing(review_failed 뒤)에서도 라운드에 취소를 남긴다. 그래서 정리 중 실패한 drop 뒤
        review --retry 가 새 리뷰어를 띄우지 않는다."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001")
        self.hteam("review", "T-001")
        self.act_review("T-001", write=False)
        self.assertTrue(self.hteam("review-finish", "T-001")[1]["retried"])
        self.act_review("T-001", write=False)
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_failed"), out)
        self.fail_hc("get", "boom")
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 1)
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("review", "T-001", "--retry")
        self.assertEqual((code, out["error"]["code"]), (3, "round_canceled"), out)
        self.assertEqual(len(self.task_state("T-001")["rounds"][0]["reviews"]), 2)
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual((code, out["status"]), (0, "dropped"), out)
        self.assertEqual(self.active_rows(), [])


class CloseRaceTest(LifeCase):
    """마지막 전이는 프로젝트 잠금 아래에서 취소 때 본 상태·라운드 그대로이고 살아 있는 실행자가 없을 때만 쓴다."""

    def test_drop_pending_racing_start_neither_drops_nor_kills(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        proc, go, wait = self.paused("after_cancel", "drop", "T-001", "--force")
        self.assertTrue(wait())  # pending 을 보고 (취소할 라운드 없이) 멈췄다
        code, out = self.hteam("start", "T-001")  # 그 사이 start 가 워커를 띄운다
        self.assertEqual(code, 0, out)
        go()
        code, res = self.finish(proc)
        self.assertEqual((code, res["error"]["code"]), (3, "state_changed"), res)
        self.assertEqual(self.task_state("T-001")["status"], "working")  # dropped 위에 워커가 남지 않는다
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "active")  # --force 여도 그 워커를 죽이지 않는다

    def test_final_write_refuses_new_round_or_live_launcher(self):
        """정리와 마지막 전이 사이에 다른 fix 가 새 라운드를 쓰고 그 워커를 띄우는 중이면 dropped 를 쓰지 않는다."""
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))

        def new_round(st):  # 상태는 그대로 launch_failed, 라운드만 바뀌었다(실행자는 끝났다)
            st["rounds"].append({**st["rounds"][-1], "round": 2, "work": dispatch.new_slot(f"{st['id']} r2 작업")})
            st["round"] = 2

        def live_launcher(st):  # 상태·라운드는 그대로, 살아 있는 실행자가 나타났다
            st["launcher"] = {"key": st["rounds"][-1]["work"]["title"], "pid": sleeper.pid,
                              "started": procs.start_time(sleeper.pid)}

        self.fail_hc("run", "boom")  # launch_failed 로 둔다
        for tid, owns, hook, code in (("T-001", "src/a/**", new_round, "state_changed"),
                                      ("T-002", "src/b/**", live_launcher, "launching")):
            with self.subTest(tid=tid):
                self.write_spec(tid, owns=owns)
                state.create(self.p, tid, "developer")
                self.hteam("start", tid)
                real = tasks._release

                def release(*a, _tid=tid, _hook=hook, **kw):
                    res = real(*a, **kw)
                    with state.edit(self.p, _tid) as st:
                        _hook(st)
                    return res

                with self.in_process(), mock.patch.object(tasks, "_release", release):
                    with self.assertRaises(HteamError) as cm:
                        tasks.drop(self.p, tid, True)
                self.assertEqual((cm.exception.code, cm.exception.exit_code), (code, 3))
                self.assertEqual(self.task_state(tid)["status"], "launch_failed")


class PrecheckRaceTest(LifeCase):
    """사전 검사(대상 미리 고르기)와 취소 저장 사이에 다른 명령이 실행 기록을 바꿨으면 아무것도 바꾸지 않고 exit 3."""

    def test_drop_refuses_if_start_lands_before_cancel(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        drop, go, wait = self.paused("before_cancel", "drop", "T-001")
        self.assertTrue(wait())  # pending 을 사전 검사했다
        code, out = self.hteam("start", "T-001")  # 그 사이 start 가 워커를 띄운다
        self.assertEqual(code, 0, out)
        go()
        code, res = self.finish(drop)
        self.assertEqual((code, res["error"]["code"]), (3, "state_changed"), res)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["work"]["canceled"]), ("working", False))
        self.act_work("T-001")
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"]), (0, "reviewing"), out)  # 실패한 drop 이 라운드를 막지 않는다

    def test_drop_refuses_if_recovery_lands_before_cancel(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")  # launch_failed
        with self._hc_locked() as hc:
            hc["fail"].clear()
        drop, go, wait = self.paused("before_cancel", "drop", "T-001")
        self.assertTrue(wait())
        code, out = self.hteam("start", "T-001")  # 그 사이 같은 Task 를 다시 띄워 working
        self.assertEqual((code, out["mode"]), (0, "retry"), out)
        go()
        code, res = self.finish(drop)
        self.assertEqual((code, res["error"]["code"]), (3, "state_changed"), res)
        self.assertFalse(self.task_state("T-001")["rounds"][0]["work"]["canceled"])
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "active")

    def test_launch_record_change_with_same_status_refuses(self):
        """상태·라운드가 같아도 실행 기록(horch Task·Dispatch·장벽 자식)이 바뀌었으면 취소하지 않는다."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")

        def recorded():  # 같은 Task 를 다시 띄운 실행자가 working 전이 전에 Dispatch 를 기록했다
            with state.edit(self.p, "T-001") as st:
                st["rounds"][0]["work"]["dispatch"] = "dsp-new"

        with self.in_process(), self.first_call_then("_round_targets", recorded):
            with self.assertRaises(HteamError) as cm:
                tasks.drop(self.p, "T-001", False)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("state_changed", 3))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["work"]["canceled"]), ("launch_failed", False))

    def test_fix_check_refusal_leaves_state_untouched(self):
        """사전 검사 뒤 상태가 reviewing 이 됐다. fix 의 check= 가 거부하고 아무것도 바꾸지 않는다(정리도 안 한다)."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        did = self.hteam("start", "T-001")[1]["dispatch"]
        self.act_work("T-001", outcome="failed")

        def reviewing():
            with state.edit(self.p, "T-001") as st:
                state.move(st, "reviewing", "review")

        with self.in_process(), self.first_call_then("_round_targets", reviewing):
            with self.assertRaises(HteamError) as cm:
                tasks.fix(self.p, "T-001", note=None, supplement=None, force_round=False, cli={})
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("bad_state", 3))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"][0]["work"]["canceled"]), ("reviewing", 1, False))
        self.assertEqual(self.dispatch_row(did)["state"], "settled")


class ReviewRoundTest(LifeCase):
    def test_old_review_cannot_judge_new_round(self):
        """r1 의 review 가 사전 검사 중이다. review 는 호출 내내 finish 잠금을 쥐므로 fix 는 취소·새 라운드를 쓰지 못하고
        기다린다. 그래서 r1 의 판정은 r1 에만 쓰이고, 그 뒤 fix 가 r2 를 띄운다(r2 는 판정 없이 working)."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001", commit=False)  # 대상 커밋이 없다: 사전 검사가 REQUEST_CHANGES
        rev, go, wait = self.paused("after_precheck_write", "review", "T-001")
        self.assertTrue(wait())
        self.assertTrue(self.held("finish"))
        self.assertFalse(self.held("project"))
        fix = self.hteam_bg("fix", "T-001", "--note", "다시")
        go()
        code, out = self.finish(rev)
        self.assertEqual((code, out["status"], out["round"]), (0, "changes", 1), out)
        code, out = self.finish(fix)
        self.assertEqual((code, out["round"], out["status"]), (0, 2, "working"), out)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["verdict"], st["rounds"][1]["verdict"]),
                         ("working", "REQUEST_CHANGES", None))
        self.assertEqual(self.dispatch_row(out["dispatch"])["state"], "active")


class FinishAfterCancelTest(LifeCase):
    def reviewed(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001")
        self.hteam("review", "T-001")
        self.act_review("T-001", "APPROVE")

    def test_review_finish_after_drop_cancel_changes_nothing(self):
        self.reviewed()
        code, _ = self.hteam("drop", "T-001", "--force", env={"HTEAM_TEST_DIE_AT": "after_cancel"})
        self.assertEqual(code, 137)
        before, head = self.task_state("T-001"), self.head()
        code, out = self.hteam("review-finish", "T-001")
        # 취소된 시도는 열린 시도가 아니다. no_open_review 의 `review --retry` 안내는 round_canceled 로 막히므로
        # 처음부터 round_canceled 로 앞선 fix·drop 을 다시 하라고 안내한다
        self.assertEqual((code, out["error"]["code"]), (3, "round_canceled"), out)
        self.assertIn("앞선 fix·drop 이 끝나지 않았다", out["error"]["hint"])
        self.assertEqual((self.task_state("T-001"), self.head()), (before, head))

    def test_cancel_landing_mid_finish_is_round_canceled(self):
        """finish 잠금이 막는 경로지만 방어를 확인한다: 판정을 쓰기 전에 취소가 끼면 exit 3 round_canceled."""
        self.reviewed()

        def tamper(p, tid, base, real=review.tamper_check):
            with state.edit(self.p, tid) as st:
                st["rounds"][-1]["reviews"][-1]["canceled"] = True
            return real(p, tid, base)

        with self.in_process(), mock.patch.object(review, "tamper_check", tamper):
            with self.assertRaises(HteamError) as cm:
                review.review_finish(self.p, "T-001")
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("round_canceled", 3))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["verdict"], self.attempt("T-001")["result"]),
                         ("reviewing", None, None))


class FinishLockTest(LifeCase):
    """잠금 순서 프로젝트 → finish → 태스크. gate 파일로 멈추고 flock 탐침으로 본다(시간에 기대지 않는다)."""

    def reviewing(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        work = self.hteam("start", "T-001")[1]["dispatch"]
        self.act_work("T-001")
        self.hteam("review", "T-001")
        return work

    def test_cancel_and_cleanup_hold_only_the_finish_lock(self):
        work = self.reviewing()
        drop, go, wait = self.paused("before_cancel", "drop", "T-001", "--force")
        self.assertTrue(wait())
        # finish 잠금을 쥐었으므로 review-finish·review 는 이 취소·정리가 끝난 뒤에 돈다. 프로젝트·태스크 잠금은 쥐지 않는다
        self.assertEqual((self.held("finish"), self.held("project"), self.held("task")), (True, False, False))
        go()
        code, res = self.finish(drop)
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertFalse(self.held("finish"))
        self.assertEqual(self.dispatch_row(work)["state"], "released")

    def test_drop_after_running_review_finish(self):
        work = self.reviewing()
        self.act_review("T-001", "APPROVE")
        fin, go, wait = self.paused("before_verdict", "review-finish", "T-001")
        self.assertTrue(wait())
        self.assertEqual((self.held("finish"), self.held("project"), self.held("task")), (True, False, False))
        drop = self.hteam_bg("drop", "T-001", "--force")  # finish 잠금을 기다린다
        self.write_spec("T-002", "tester")
        state.create(self.p, "T-002", "tester")
        code, out = self.hteam("start", "T-002")  # 기다리는 drop 은 프로젝트 잠금을 쥐지 않는다
        self.assertEqual(code, 0, out)
        go()
        code, res = self.finish(fin)
        self.assertEqual((code, res["status"]), (0, "approved"), res)  # drop 이 판정 전에 취소하지 않았다
        code, res = self.finish(drop)
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        self.assertEqual(self.dispatch_row(work)["state"], "released")


class FixOpenReviewTest(LifeCase):
    def test_fix_cleans_unrecorded_reviewer(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001")
        self.act_work("T-001")
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        self.assertEqual(code, 137)
        _, rows = self.horch("worker-list")
        reviewer = [r["id"] for r in rows["workers"] if r["title"] == "T-001 r1 리뷰 a1"][0]
        code, out = self.hteam("fix", "T-001", "--note", "다시")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertEqual(self.dispatch_row(reviewer)["state"], "released")
        old = self.task_state("T-001")["rounds"][0]["reviews"][0]
        self.assertTrue(old["canceled"] and old["cleaned"])


class FixInputFirstTest(LifeCase):
    def test_bad_owns_does_not_clean_up_previous_worker(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        did = self.hteam("start", "T-001")[1]["dispatch"]
        self.act_work("T-001", outcome="failed")  # fix 를 부를 수 있는 상태
        self.write_spec("T-001", owns="**")
        code, out = self.hteam("fix", "T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "owns_too_wide"))
        self.assertEqual(self.dispatch_row(did)["state"], "settled")  # 정리하지 않았다
        self.assertEqual(self.task_state("T-001")["round"], 1)


class FixUnrecordedTest(LifeCase):
    def test_fix_cleans_worker_launched_before_record(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        _, rows = self.horch("worker-list")
        old = rows["workers"][0]["id"]
        self.assertEqual(rows["workers"][0]["state"], "active")
        code, out = self.hteam("fix", "T-001", "--note", "다시")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertEqual(self.dispatch_row(old)["state"], "released")
        _, rows = self.horch("worker-list")
        self.assertEqual([r["id"] for r in rows["workers"] if r["state"] == "active"], [out["dispatch"]])


class SlotRowTest(unittest.TestCase):
    def test_slot_row_prefers_task_then_title_then_dispatch(self):
        rows = [{"id": "d1", "task": "t1", "attempt": 1, "title": "T-001 r1 작업", "created_at": "1"},
                {"id": "d2", "task": "t1", "attempt": 2, "title": "T-001 r1 작업", "created_at": "2"},
                {"id": "d3", "task": "t2", "attempt": 1, "title": "T-001 r1 리뷰 a1", "created_at": "3"}]
        slot = dispatch.new_slot("T-001 r1 작업")
        self.assertIsNone(dispatch.slot_row(rows, slot))
        self.assertEqual(dispatch.slot_row(rows, {**slot, "dispatch": "d1"})["id"], "d1")
        self.assertEqual(dispatch.slot_row(rows, {**slot, "launched": {"pid": 1}})["id"], "d2")
        self.assertEqual(dispatch.slot_row(rows, {**slot, "horch_task": "t1", "dispatch": "d1"})["id"], "d2")
        self.assertIsNone(dispatch.slot_row(rows, {**slot, "horch_task": "t9"}))


if __name__ == "__main__":
    unittest.main()
