"""accept·fix·drop(설계 6.4)와 수정 라운드."""
import contextlib
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import dispatch, procs, state, tasks
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
        for needle in ("## 수정 라운드 r2", "`docs/reviews/T-001/r1.md` 의 지적을 모두", "코디네이터 메모: 리뷰 지적 반영"):
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
        self.write_spec("T-002", commit=False)
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


class FinishLockTest(LifeCase):
    def test_drop_waits_for_running_review_finish_without_blocking_others(self):
        """잠금 순서 프로젝트 → finish → 태스크. drop 은 진행 중인 review-finish 가 끝날 때까지 취소하지 않고 기다린다.
        기다리는 동안 프로젝트 잠금·태스크 잠금을 쥐지 않는다(다른 start 가 돌고, review-finish 가 교착하지 않는다)."""
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        work = self.hteam("start", "T-001")[1]["dispatch"]
        self.act_work("T-001")
        self.hteam("review", "T-001")
        self.act_review("T-001", "APPROVE")
        fin, go, wait = self.paused("before_verdict", "review-finish", "T-001")
        self.assertTrue(wait())
        drop = self.hteam_bg("drop", "T-001", "--force")
        self.write_spec("T-002", "tester")
        state.create(self.p, "T-002", "tester")
        code, out = self.hteam("start", "T-002")
        self.assertEqual(code, 0, out)
        time.sleep(0.5)
        self.assertIsNone(drop.poll())
        self.assertFalse(self.attempt("T-001")["canceled"])
        go()
        code, res = self.finish(fin)
        self.assertEqual((code, res["status"]), (0, "approved"), res)
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
