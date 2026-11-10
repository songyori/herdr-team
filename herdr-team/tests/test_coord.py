"""status 의 next·hint(설계 8.3·13장). 0.4.0 에서 wait·which 와 메시지 주석을 없앴다(관제가 안에서 처리한다, 8.6)."""
import os
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import outbox, state
from hteam.paths import Project

H = ".herdr-team/bin/hteam"


class CoordCase(TeamCase):
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

    def calm(self, tid="T-001"):
        """no_status attention 을 피하려고 워커 터미널이 상태를 보고하게 한다."""
        term = self.dispatch_row(self.work_dispatch(tid))["terminal"]
        self.update_terminal(term, status="working")
        return term

    def approve(self, tid="T-001"):
        with state.edit(self.p, tid) as st:
            state.move(st, "approved", "verdict")

    def task_view(self, tid="T-001", **kw):
        code, out = self.hteam("status", **kw)
        self.assertEqual(code, 0, out)
        return next(t for t in out["tasks"] if t["id"] == tid)


class StatusTest(CoordCase):
    def test_status_reads_each_spec_once(self):
        from unittest import mock
        from hteam import coord, specs
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        calls = []
        real = specs.load

        def load(p, tid):
            calls.append(tid)
            return real(p, tid)
        with mock.patch.dict(os.environ, self._env("drive", None, None), clear=True), \
                mock.patch.object(specs, "load", load):
            out = coord.status(self.p)
        self.assertEqual(out["tasks"][0]["title"], "앱 만들기")
        self.assertEqual(calls, ["T-001"])  # 제목과 dropped 선행 검사가 같은 사양을 다시 읽지 않는다

    def test_status_next_per_state(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.started("T-002", "tester")
        self.act_work("T-002", {"tests/t.py": "1\n"})
        self.started("T-003", "planner")
        code, out = self.hteam("status")
        self.assertEqual(code, 0, out)
        nxt = {t["id"]: t["next"] for t in out["tasks"]}
        self.assertEqual(nxt["T-001"], [H, "start-ready"])
        self.assertEqual(nxt["T-002"], [H, "review", "T-002"])
        self.assertIsNone(nxt["T-003"])
        self.assertTrue(out["drive"]["alive"])
        self.assertFalse(out["watch_alive"])
        self.assertIn("--home", out["horch"])
        self.hteam("review", "T-002")
        self.act_review("T-002", "REQUEST_CHANGES")
        nxt = {t["id"]: (t["next"], t["hint"]) for t in self.hteam("status")[1]["tasks"]}
        self.assertEqual(nxt["T-002"][0], [H, "review-finish", "T-002"])
        self.hteam("review-finish", "T-002")
        nxt = {t["id"]: (t["next"], t["hint"]) for t in self.hteam("status")[1]["tasks"]}
        self.assertIsNone(nxt["T-002"][0])
        self.assertIn("max_rounds", nxt["T-002"][1])

    def test_status_next_for_changes_has_no_note(self):
        # 리뷰 수정 요청 뒤 next 는 메모 없는 fix 다(설계 10장): 메모는 다음 라운드의 요청이 돼 리뷰어가 P2 까지 막는다
        self.started("T-002", "tester")
        self.act_work("T-002", {"tests/t.py": "1\n"})
        self.hteam("review", "T-002")
        self.act_review("T-002", "REQUEST_CHANGES")
        self.hteam("review-finish", "T-002")
        nxt = {t["id"]: t["next"] for t in self.hteam("status")[1]["tasks"]}
        self.assertEqual(nxt["T-002"], [H, "fix", "T-002"])

    def test_status_hint_for_round_being_closed(self):
        self.started()
        with state.edit(self.p, "T-001") as st:
            st["rounds"][0]["work"]["canceled"] = True  # fix·drop 이 취소를 저장한 뒤 멈췄다
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIsNone(task["next"])
        self.assertIn("같은 명령을 다시 한다", task["hint"])

    def test_status_reports_corrupt_run_file(self):
        (self.state_dir / "run.json").write_text("{broken")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertIn("run.json", out["run_error"])
        self.assertIsNone(out["drive"]["terminal"])

    def test_status_from_main_and_broken_config(self):
        self.started()
        (self.team / "config.toml").write_text("max_parallel = [")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertIn("config.toml", out["config_error"])
        self.assertIsNotNone(out["horch_error"])  # 메인은 Run 소유자가 아니다
        self.assertEqual(out["tasks"][0]["status"], "working")

    def test_approved_with_live_worker_points_to_cleanup(self):
        out = self.started()
        self.calm()
        self.approve()  # review 는 retain 실패를 견디므로 approved 에도 작업 워커가 살아 있을 수 있다
        task = self.task_view()
        self.assertIsNone(task["next"])
        self.assertIn(out["dispatch"], task["hint"])
        self.assertIn("worker-abandon", task["hint"])

    def test_approved_without_live_worker_suggests_accept(self):
        self.started()
        self.calm()
        self.act_work("T-001")
        self.approve()
        self.assertEqual(self.task_view()["next"], [H, "accept", "T-001"])
        task = self.task_view(as_="main")  # 메인은 worker-list 를 못 본다. accept 를 권하되 경고한다
        self.assertEqual(task["next"], [H, "accept", "T-001"])
        self.assertIn("exit 3", task["hint"])

    def test_every_next_starts_with_shim(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.started("T-002", "tester")
        for task in self.hteam("status")[1]["tasks"]:
            if task["next"] is not None:
                self.assertEqual(task["next"][0], H)

    def test_status_hints_use_full_horch_command(self):
        out = self.started()  # no_status
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIn(f"--home {self.horch_home} worker-show --dispatch {out['dispatch']}", task["hint"])
        with state.edit(self.p, "T-001") as st:
            state.move(st, "approved", "verdict")
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIn(f"--home {self.horch_home} worker-abandon --dispatch {out['dispatch']}", task["hint"])

    def test_status_unread_counts_unreadable_lines(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "outbox.jsonl").write_text("{깨진 줄\n", encoding="utf-8")
        (self.state_dir / "outbox.cursor").write_text("1\n")  # watch 가 깨진 줄까지 넘겼다
        outbox.append(self.p, {"type": "progress", "from": "drive", "body": "진행"})
        self.assertEqual(self.hteam("status")[1]["unread_outbox"], 1)

    def test_failed_work_at_round_limit_has_no_fix(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.started()
        self.calm()
        self.act_work("T-001", outcome="failed")
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIsNone(task["next"])
        self.assertIn("--force-round", task["hint"])

    def test_exited_work_at_round_limit_has_no_fix(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.started()
        term = self.calm()
        self.update_terminal(term, state="finished")
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIsNone(task["next"])
        self.assertIn("max_rounds", task["hint"])


if __name__ == "__main__":
    unittest.main()
