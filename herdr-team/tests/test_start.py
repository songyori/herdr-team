"""start·start-ready(설계 5.4), 워커 사양 조립(5.5), 시작 장벽과 복구."""
import contextlib
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import compose, config, dispatch, launch, procs, specs, state, tasks
from hteam.errors import HteamError
from hteam.paths import Project


class StartCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()
        self.p = Project(self.proj)

    def make_task(self, tid, role="developer", **kw):
        self.write_spec(tid, role, **kw)
        state.create(self.p, tid, role)

    def horch_tasks(self):
        code, out = self.horch("worker-list")
        self.assertEqual(code, 0, out)
        return out["workers"]

    @contextlib.contextmanager
    def in_process(self):
        """hteam 을 이 프로세스에서 부른다(경합 지점에 끼어들려고). horch·장벽 자식은 테스트 환경을 물려받는다."""
        with mock.patch.dict(os.environ, self._env("coordinator", None, None), clear=True):
            yield

    @staticmethod
    def dead_record():
        """죽은 프로세스 기록: 띄우고 거둔 pid 에 맞지 않는 시작 시각(pid 가 재사용돼도 죽은 것으로 본다)."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return {"pid": proc.pid, "started": "Thu Jan  1 00:00:00 1970"}

    def set_max_parallel(self, n):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_parallel = 4", f"max_parallel = {n}"))


class StartTest(StartCase):
    def test_start_launches_worker_in_team_tab(self):
        self.make_task("T-001")
        head = self.head()
        code, out = self.hteam("start", "T-001")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["round"], out["agent"], out["model"], out["mode"]),
                         ("working", 1, "claude", "opus", "fresh"))
        st = self.task_state("T-001")
        rd = st["rounds"][0]
        self.assertEqual((st["status"], st["base"], rd["round_base"]), ("working", head, head))
        self.assertEqual(rd["work"]["title"], "T-001 r1 작업")
        self.assertEqual(rd["work"]["dispatch"], out["dispatch"])
        self.assertEqual(st["launcher"]["key"], "T-001 r1 작업")
        self.assertEqual([h["event"] for h in st["history"]], ["create", "start", "launched"])
        self.assertEqual(st["owns"], ["src/**"])
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["title"], row["agent"], row["model"], row["effort"], row["cwd"]),
                         ("T-001 r1 작업", "claude", "opus", "xhigh", str(self.proj)))
        term = self.hc_state()["terminals"][row["terminal"]]
        self.assertEqual(term["labels"]["herdr.tab"], "tbTeam")
        self.assertIn("launch-guard", term["argv"])
        spec = (self.state_dir / "tasks/T-001/r1-work.md").read_text()
        for needle in ("# developer 직무 문서", "# 태스크 T-001 · 라운드 1 — [개발] 앱 만들기", "## Acceptance",
                       "## 선행 태스크\n없음.", "- `src/**`", "docs/tasks/T-001/report.md", "[T-001] <요약>",
                       "--report-path docs/tasks/T-001/report.md", "프리앰블의 ask 명령"):
            self.assertIn(needle, spec)
        self.assertNotIn("## 수정 라운드", spec)

    def test_overrides_and_agent_args(self):
        self.make_task("T-001")
        code, out = self.hteam("start", "T-001", "--worker", "codex", "--model", "m1", "--effort", "low")
        self.assertEqual(code, 0, out)
        row = self.dispatch_row(out["dispatch"])
        self.assertEqual((row["agent"], row["model"], row["effort"]), ("codex", "m1", "low"))
        self.assertEqual(json.loads(row["agent_args"]), ["--disable=hooks"])

    def test_state_and_spec_errors(self):
        self.make_task("T-001", body="## Target\n<x>\n")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_spec"))
        self.make_task("T-002")
        self.assertEqual(self.hteam("start", "T-002")[0], 0)
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"]), (3, "bad_state"))
        with state.edit(self.p, "T-002") as st:
            state.move(st, "done", "accept")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"]), (3, "task_closed"))
        code, out = self.hteam("start", "T-009")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_task"))
        code, out = self.hteam("start", "T-002", as_="main")
        self.assertEqual(code, 5)

    def test_owns_lock_and_single_planner(self):
        self.make_task("T-001")
        self.make_task("T-002", owns="src/auth/**")
        self.make_task("T-003", "tester")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"]), (3, "owns_locked"), out)
        self.assertEqual(out["conflicts"][0]["task"], "T-001")
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        self.assertEqual(self.hteam("start", "T-003")[0], 0)
        self.make_task("T-004", "planner", owns="docs/planning/a/**")
        self.make_task("T-005", "planner", owns="docs/planning/b/**")
        self.assertEqual(self.hteam("start", "T-004")[0], 0)
        code, out = self.hteam("start", "T-005")
        self.assertEqual((code, out["error"]["code"]), (3, "planner_busy"))

    def test_launch_failure_then_retry_same_horch_task(self):
        self.make_task("T-001")
        self.fail_hc("run", "boom")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "launch_failed"), out)
        st = self.task_state("T-001")
        work = st["rounds"][0]["work"]
        self.assertEqual(st["status"], "launch_failed")
        self.assertEqual(work["error"]["code"], "launch_failed")
        self.assertIsNotNone(work["horch_task"])
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"]), (0, "retry"), out)
        self.assertEqual(out["horch_task"], work["horch_task"])
        attempts = sorted(r["attempt"] for r in self.horch_tasks() if r["task"] == work["horch_task"])
        self.assertEqual(attempts, [1, 2])
        self.assertEqual(self.task_state("T-001")["rounds"][0]["round_base"], st["rounds"][0]["round_base"])

    def test_dead_before_byte_relaunches_fresh(self):
        self.make_task("T-001")
        code, _ = self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_child"})
        self.assertEqual(code, 137)
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "launch_failed")
        self.assertIsNotNone(st["rounds"][0]["work"]["launched"])
        self.assertEqual(self.horch_tasks(), [])  # 자식은 바이트를 못 받아 horch 를 실행하지 않았다
        self.commit("src/other.py", "x\n", "other")  # 그 사이 HEAD 가 움직여도 base 는 그대로다
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"]), (0, "fresh"), out)
        self.assertEqual(len(self.horch_tasks()), 1)
        self.assertEqual(self.task_state("T-001")["base"], st["base"])

    def test_dead_after_launch_adopts_by_title(self):
        self.make_task("T-001")
        code, _ = self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        self.assertEqual(code, 137)
        rows = self.horch_tasks()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(self.task_state("T-001")["rounds"][0]["work"]["horch_task"])
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"], out["dispatch"]), (0, "adopt", rows[0]["id"]), out)
        self.assertEqual(len(self.horch_tasks()), 1)
        self.assertEqual(self.task_state("T-001")["status"], "working")

    def test_live_launcher_is_launching_and_canceled_key(self):
        self.make_task("T-001")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_child"})
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        with state.edit(self.p, "T-001") as st:
            st["launcher"].update(pid=sleeper.pid, started=procs.start_time(sleeper.pid))
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "launching"))
        with state.edit(self.p, "T-001") as st:
            st["launcher"] = None
            st["rounds"][0]["work"]["canceled"] = True
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (3, "launch_canceled"))

    def test_first_launch_aligns_role_with_spec(self):
        """task new --role developer 뒤 사양을 planner 로 바꿨다. 워커는 planner 로 뜨므로 저장된 직무도 planner 다."""
        self.make_task("T-001")
        self.write_spec("T-001", "planner", owns="docs/planning/a/**")
        self.assertEqual(self.task_state("T-001")["role"], "developer")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.assertEqual(self.task_state("T-001")["role"], "planner")
        self.make_task("T-002", "planner", owns="docs/planning/b/**")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"]), (3, "planner_busy"), out)

    def test_corrupt_state_file_blocks_new_starts(self):
        """잠금을 가진 태스크의 상태 파일이 손상되면 그 잠금을 알 수 없다. 새 작업을 띄우지 않는다(exit 1)."""
        self.make_task("T-001")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        (self.state_dir / "tasks/T-001.json").write_text("{", encoding="utf-8")
        self.make_task("T-002", owns="src/auth/**")
        code, out = self.hteam("start", "T-002")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_state_file"), out)
        self.assertIn("T-001.json", out["error"]["message"])
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        self.assertEqual(len(self.horch_tasks()), 1)


class LaunchRaceTest(StartCase):
    """시작 검사와 장벽 기록·working 전이 사이에 fix·drop(Task 8)의 취소나 상태 변경이 끼어든다."""

    def hooked_barrier(self, tid, hook, made):
        """장벽 자식을 만든 직후, 기록하기 전에 hook(st) 를 상태에 적용하는 Barrier."""
        test = self

        class Hooked(launch.Barrier):
            def __init__(self, argv):
                super().__init__(argv)
                made.append(self)
                with state.edit(test.p, tid) as st:
                    hook(st)
        return Hooked

    def test_cancel_or_status_change_before_barrier_record_never_launches(self):
        def cancel(st):
            st["rounds"][-1]["work"]["canceled"] = True

        def drop(st):
            state.move(st, "dropped", "drop")

        def replace(st):
            st["launcher"]["pid"] = 1

        cases = [("T-001", "src/a/**", cancel, "launch_canceled", "launch_failed"),
                 ("T-002", "src/b/**", drop, "task_closed", "dropped"),
                 ("T-003", "src/c/**", replace, "launch_canceled", "launch_failed")]
        for tid, owns, hook, code, status in cases:
            with self.subTest(tid=tid):
                self.make_task(tid, owns=owns)
                made = []
                with self.in_process(), mock.patch.object(dispatch, "Barrier", self.hooked_barrier(tid, hook, made)):
                    with self.assertRaises(HteamError) as cm:
                        tasks.start(self.p, tid, {})
                self.assertEqual((cm.exception.code, cm.exception.exit_code), (code, 3))
                self.assertEqual(made[0].proc.returncode, launch.NOT_RUN)  # 바이트 없이 끝났다
                st = self.task_state(tid)
                self.assertEqual(st["status"], status)
                self.assertIsNone(st["rounds"][-1]["work"]["launched"])
        self.assertEqual(self.horch_tasks(), [])

    def test_cancel_after_horch_started_is_not_working(self):
        """horch 가 이미 떴다면 working 으로 두지 않고 exit 3. 정리는 fix·drop 이 horch 상태로 한다."""
        real_go = launch.Barrier.go

        def go(barrier, timeout=600):
            res = real_go(barrier, timeout)
            with state.edit(self.p, "T-001") as st:
                st["rounds"][-1]["work"]["canceled"] = True
            return res

        self.make_task("T-001", owns="src/a/**")
        with self.in_process(), mock.patch.object(launch.Barrier, "go", go):
            with self.assertRaises(HteamError) as cm:
                tasks.start(self.p, "T-001", {})
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_canceled", 3))
        self.assertIn("fix", cm.exception.hint)
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "launch_failed")
        self.assertIsNotNone(st["rounds"][0]["work"]["launched"])  # fix·drop 이 실행 키(제목)로 찾는다
        self.assertEqual(len(self.horch_tasks()), 1)

        real_launch = dispatch.launch

        def launched_then_canceled(*a, **kw):
            res = real_launch(*a, **kw)
            with state.edit(self.p, "T-002") as st:
                st["rounds"][-1]["work"]["canceled"] = True
            return res

        self.make_task("T-002", owns="src/b/**")
        with self.in_process(), mock.patch.object(dispatch, "launch", launched_then_canceled):
            with self.assertRaises(HteamError) as cm:
                tasks.start(self.p, "T-002", {})
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_canceled", 3))
        st = self.task_state("T-002")
        self.assertEqual(st["status"], "launch_failed")
        self.assertIsNotNone(st["rounds"][0]["work"]["dispatch"])
        self.assertEqual(cm.exception.data["horch"]["dispatch"], st["rounds"][0]["work"]["dispatch"])

    def test_cancel_before_adopt_record(self):
        self.make_task("T-001")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        real = dispatch.existing

        def existing(h, slot):
            res = real(h, slot)
            with state.edit(self.p, "T-001") as st:
                st["rounds"][-1]["work"]["canceled"] = True
            return res

        with self.in_process(), mock.patch.object(dispatch, "existing", existing):
            with self.assertRaises(HteamError) as cm:
                tasks.start(self.p, "T-001", {})
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_canceled", 3))
        st = self.task_state("T-001")
        self.assertEqual(st["status"], "launch_failed")
        self.assertIsNone(st["rounds"][0]["work"]["horch_task"])

    def test_cancel_cannot_land_between_record_and_byte(self):
        """기록 직후 시도한 취소는 시작 바이트 뒤에야 저장된다(기록·바이트가 한 태스크 잠금 안). 그러면 horch 는 이미
        떴으므로 working 으로 두지 않고 exit 3. 기록 전에 저장된 취소는 위 테스트대로 horch 를 띄우지 않는다."""
        self.make_task("T-001")
        threads, byte_sent_at_cancel = [], []
        real_record, real_go = launch.Barrier.record, launch.Barrier.go

        def record(barrier):  # 태스크 잠금 안: 다른 실행자(fix·drop)의 취소가 기록 직후 잠금을 기다린다
            def cancel():
                with state.edit(self.p, "T-001") as st:
                    st["rounds"][-1]["work"]["canceled"] = True
                byte_sent_at_cancel.append(barrier.proc.stdin is None or barrier.proc.stdin.closed)
            t = __import__("threading").Thread(target=cancel)
            t.start()
            threads.append(t)
            return real_record(barrier)

        def go(barrier, timeout=600):
            threads[0].join(10)  # 취소가 저장된 뒤에 이어 간다
            return real_go(barrier, timeout)

        with self.in_process(), mock.patch.object(launch.Barrier, "record", record), \
                mock.patch.object(launch.Barrier, "go", go):
            with self.assertRaises(HteamError) as cm:
                tasks.start(self.p, "T-001", {})
        self.assertEqual(byte_sent_at_cancel, [True])
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_canceled", 3))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["rounds"][0]["work"]["canceled"]), ("launch_failed", True))

    def test_barrier_timeout_kills_horch_and_recovers_by_title(self):
        """horch 가 멈추면(hc run 이 끝나지 않음) 자식과 그 프로세스 그룹을 죽이고 거둔 뒤 exit 1 launch_timeout.
        horch 가 이미 만든 Task·Dispatch 는 제목으로 찾아 같은 Task 를 다시 띄운다."""
        self.make_task("T-001")
        with self._hc_locked() as hc:
            hc["delay"] = {"run": 30}
        held = []
        real_go = launch.Barrier.go

        def go(barrier, timeout=600):
            held.append(barrier)
            self.addCleanup(lambda: barrier.proc.poll() is None and (barrier.proc.kill(), barrier.proc.wait()))
            for _ in range(400):  # horch 가 Dispatch 를 만들고 hc run 에서 멈출 때까지
                if any(c[:1] == ["run"] for c in self.hc_calls()):
                    break
                __import__("time").sleep(0.05)
            return real_go(barrier, 0.5)

        with self.in_process(), mock.patch.object(launch.Barrier, "go", go):
            with self.assertRaises(HteamError) as cm:
                tasks.start(self.p, "T-001", {})
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("launch_timeout", 1))
        self.assertIsNotNone(held[0].proc.returncode)  # 거뒀다
        for _ in range(100):  # 그룹(hc run 포함)도 남지 않는다(고아 좀비는 init 이 곧 거둔다)
            try:
                os.killpg(held[0].pid, 0)
            except ProcessLookupError:
                break
            __import__("time").sleep(0.02)
        else:
            self.fail("horch 프로세스 그룹이 남았다")
        self.assertEqual(self.task_state("T-001")["status"], "launch_failed")
        with self._hc_locked() as hc:
            hc["delay"] = {}
        with self.in_process():  # 실행자(이 프로세스)는 제외된다. 자식이 없으니 바로 복구한다
            out = tasks.start(self.p, "T-001", {})
        self.assertEqual((out["mode"], out["status"]), ("retry", "working"), out)
        self.assertEqual(len({r["task"] for r in self.horch_tasks()}), 1)


class FindTest(unittest.TestCase):
    def test_find_by_title_latest_and_warn(self):
        rows = [{"id": "d1", "task": "a", "attempt": 1, "title": "T", "created_at": "1", "state": "abandoned"},
                {"id": "d2", "task": "a", "attempt": 2, "title": "T", "created_at": "2", "state": "active"},
                {"id": "d3", "task": "b", "attempt": 1, "title": "T", "created_at": "3", "state": "launch_failed"},
                {"id": "d4", "task": "c", "attempt": 1, "title": "U", "created_at": "4", "state": "active"}]
        row, warns = dispatch.find_by_title(rows, "T")
        self.assertEqual(row["id"], "d3")
        self.assertEqual(len(warns), 1)
        self.assertEqual(dispatch.latest_for_task(rows, "a")["id"], "d2")
        self.assertEqual(dispatch.classify(row), "retry")
        self.assertEqual(dispatch.classify(rows[1]), "adopt")
        self.assertEqual(dispatch.classify({"state": "released", "outcome": "succeeded"}), "adopt")
        self.assertEqual(dispatch.classify({"state": "released", "outcome": None}), "retry")
        self.assertEqual(dispatch.find_by_title(rows, "none"), (None, []))

    def test_recorded_horch_task_without_rows_is_error(self):
        """기록된 horch Task 가 worker-list 에 없으면 같은 제목의 Task 를 새로 만들지 않는다."""
        h = mock.Mock()
        h.workers.return_value = [{"id": "d1", "task": "other", "attempt": 1, "title": "T", "state": "active"}]
        slot = {**dispatch.new_slot("T"), "horch_task": "gone", "launched": {"pid": 1, "started": ""}}
        with self.assertRaises(HteamError) as cm:
            dispatch.existing(h, slot)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("horch_task_missing", 1))
        self.assertTrue(cm.exception.hint)


class StartReadyTest(StartCase):
    def test_reasons_and_order(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_parallel = 4", "max_parallel = 2"))
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", "tester", depends="T-001")
        self.make_task("T-003", owns="src/a/x/**")
        self.make_task("T-004", owns="src/b/**")
        self.make_task("T-005", owns="src/c/**")
        self.make_task("T-006", owns="src/d/**", body="## Target\n<…>\n")
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual([s["task"] for s in out["started"]], ["T-001", "T-004"])
        self.assertEqual({w["task"]: w["reason"] for w in out["waiting"]},
                         {"T-002": "deps", "T-003": "lock", "T-005": "limit", "T-006": "spec"})

    def test_failure_continues_and_exit_1(self):
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        self.fail_hc("run", "boom")
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out["error"]["code"]), (1, "start_failed"), out)
        self.assertEqual([f["task"] for f in out["failed"]], ["T-001", "T-002"])
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("start-ready")
        self.assertEqual((code, len(out["started"])), (0, 2), out)

    def test_deps_with_approval_roles(self):
        cfg_text = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["designer"]') + \
            '\n[roles.designer]\ntitle = "디자인"\nowns = ["docs/design/**"]\n'
        (self.team / "config.toml").write_text(cfg_text)
        cfg = config.load(self.p)
        self.make_task("T-001", "designer", owns="docs/design/a/**")
        with state.edit(self.p, "T-001") as st:
            state.move(st, "awaiting_user", "accept")
        self.write_spec("T-002", "designer", owns="docs/design/b/**", depends="T-001", commit=False)
        self.write_spec("T-003", "developer", depends="T-001", commit=False)
        self.assertTrue(tasks.deps_met(self.p, cfg, specs.load(self.p, "T-002")))
        self.assertFalse(tasks.deps_met(self.p, cfg, specs.load(self.p, "T-003")))

    def test_launching_task_counts_toward_limit(self):
        """다른 start·start-ready 가 띄우는 중인 태스크(launch_failed, 실행자 살아 있음)도 동시 수에 든다."""
        self.set_max_parallel(1)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_child"})
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        with state.edit(self.p, "T-001") as st:
            st["launcher"].update(pid=sleeper.pid, started=procs.start_time(sleeper.pid))
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["started"], [])
        self.assertEqual({w["task"]: w["reason"] for w in out["waiting"]}, {"T-001": "launching", "T-002": "limit"})
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_overlapping_start_ready_respects_limit(self):
        self.set_max_parallel(1)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        procs_ = [self.hteam_bg("start-ready") for _ in range(2)]
        results = [self.finish(proc) for proc in procs_]
        for code, out in results:
            self.assertEqual(code, 0, out)
        started = [s["task"] for _, out in results for s in out["started"]]
        self.assertEqual(len(started), 1, results)
        working = [t for t in ("T-001", "T-002") if self.task_state(t)["status"] == "working"]
        self.assertEqual(working, started)

    def test_recovery_candidate_uses_stored_owns(self):
        """launch_failed 복구는 저장된 owns 로 잠근다. 사양을 고쳐 다른 태스크와 겹쳐도 lock 대기가 아니다."""
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        self.fail_hc("run", "boom")
        self.assertEqual(self.hteam("start", "T-001")[1]["error"]["code"], "launch_failed")
        with self._hc_locked() as hc:
            hc["fail"].clear()
        self.assertEqual(self.hteam("start", "T-002")[0], 0)
        self.write_spec("T-001", owns="src/b/**")
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"], out)
        self.assertEqual(self.task_state("T-001")["owns"], ["src/a/**"])

    def test_too_wide_fresh_spec_is_failure_not_lock(self):
        self.make_task("T-001")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.make_task("T-002", owns="**")  # 직무 owns 를 넘고 T-001 과도 겹친다
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out["error"]["code"]), (1, "start_failed"), out)
        self.assertEqual([(f["task"], f["error"]["code"]) for f in out["failed"]], [("T-002", "owns_too_wide")])

    def test_bad_state_file_is_one_failure(self):
        """손상된 상태 파일이 있으면 start-ready 는 멈추지 않고 끝까지 돌며 모두 실패로 알린다: 손상된 태스크 자신,
        그것에 의존하는 태스크(의존 검사), 나머지(잠금 검사가 실패로 닫힌다). 아무것도 띄우지 않는다."""
        self.make_task("T-001", owns="src/a/**")
        (self.state_dir / "tasks/T-001.json").write_text("{", encoding="utf-8")
        self.make_task("T-002", owns="src/b/**", depends="T-001")
        self.make_task("T-003", owns="src/c/**")
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out["error"]["code"]), (1, "start_failed"), out)
        self.assertEqual([(f["task"], f["error"]["code"]) for f in out["failed"]],
                         [("T-001", "bad_state_file"), ("T-002", "bad_state_file"), ("T-003", "bad_state_file")])
        self.assertEqual(out["started"], [])

    def test_only_candidate_corrupt_is_reported(self):
        """plan.json 이 없고 유일한 태스크의 상태 파일이 손상됐다. 조용히 exit 0 이 아니라 실패로 알린다."""
        self.make_task("T-001")
        (self.state_dir / "tasks/T-001.json").write_text("{", encoding="utf-8")
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out["error"]["code"]), (1, "start_failed"), out)
        self.assertEqual([(f["task"], f["error"]["code"]) for f in out["failed"]], [("T-001", "bad_state_file")])
        self.assertIn("T-001.json", out["failed"][0]["error"]["message"])

    def _start_ready_with_go(self, tid, after_go):
        """tid 의 장벽은 horch 를 끝까지 돌린 뒤 after_go() 를 부른다(시작 바이트 뒤 오류 흉내)."""
        real_go = launch.Barrier.go

        def go(barrier, timeout=600):
            res = real_go(barrier, timeout)
            if f"{tid} r1 작업" in barrier.proc.args:
                after_go()
            return res

        with self.in_process(), mock.patch.object(launch.Barrier, "go", go):
            with self.assertRaises(HteamError) as cm:
                tasks.start_ready(self.p)
        self.assertEqual(cm.exception.code, "start_failed")
        return cm.exception.data

    def test_launch_timeout_is_one_failure(self):
        """시작 장벽 시간 초과(launch_timeout)도 그 태스크만 실패로 두고 started 를 잃지 않는다."""
        for tid, owns in (("T-001", "src/a/**"), ("T-002", "src/b/**"), ("T-003", "src/c/**")):
            self.make_task(tid, owns=owns)

        def timeout():
            raise subprocess.TimeoutExpired("horch", 600)

        data = self._start_ready_with_go("T-002", timeout)
        self.assertEqual([s["task"] for s in data["started"]], ["T-001", "T-003"])
        self.assertEqual([(f["task"], f["error"]["code"]) for f in data["failed"]], [("T-002", "launch_timeout")])

    def test_unexpected_error_is_one_failure(self):
        """HteamError 가 아닌 예상 밖 오류(버그)도 internal 실패 한 건으로 두고 계속한다."""
        for tid, owns in (("T-001", "src/a/**"), ("T-002", "src/b/**"), ("T-003", "src/c/**")):
            self.make_task(tid, owns=owns)

        def bug():
            raise RuntimeError("boom")

        data = self._start_ready_with_go("T-002", bug)
        self.assertEqual([s["task"] for s in data["started"]], ["T-001", "T-003"])
        self.assertEqual([(f["task"], f["error"]["code"], f["error"]["message"]) for f in data["failed"]],
                         [("T-002", "internal", "RuntimeError: boom")])

    def test_uncertain_launch_holds_slot_within_call(self):
        """시작 바이트 뒤 기록 저장이 실패했다(워커는 떴다). 그 워커는 새 worker-list 에서 제목으로 보여 자리를 차지한다."""
        self.set_max_parallel(1)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        real_save = state.save

        def save(p, st):
            if st["id"] == "T-001" and st["status"] == "launch_failed" and st["rounds"][-1]["work"]["dispatch"]:
                raise OSError(28, "No space left on device")
            return real_save(p, st)

        with self.in_process(), mock.patch.object(state, "save", save):
            with self.assertRaises(HteamError) as cm:
                tasks.start_ready(self.p)
        data = cm.exception.data
        self.assertEqual(data["started"], [])
        self.assertEqual([(f["task"], f["error"]["code"]) for f in data["failed"]], [("T-001", "internal")])
        self.assertEqual({w["task"]: w["reason"] for w in data["waiting"]}, {"T-002": "limit"})
        self.assertEqual(len(self.horch_tasks()), 1)

    def test_running_dispatch_of_launch_failed_task_counts_across_calls(self):
        """앞선 실행자가 워커를 띄운 뒤 죽었다(launch_failed, 실행자·자식 없음). horch 에서 그 실행 키가 active 면 센다."""
        self.set_max_parallel(1)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        self.assertEqual(self.hteam("start", "T-002", env={"HTEAM_TEST_DIE_AT": "after_launch"})[0], 137)
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual([s["task"] for s in out["started"]], ["T-002"], out)  # 이어 붙였다(새 워커 아님)
        self.assertEqual({w["task"]: w["reason"] for w in out["waiting"]}, {"T-001": "limit"})
        self.assertEqual(len(self.horch_tasks()), 1)


    def test_nonok_horch_with_active_dispatch_holds_slot(self):
        """horch 가 non-ok(record_failed 등)로 끝났지만 Dispatch 는 active 다. 앞서 worker-list 를 이미 본 뒤여도
        그 태스크는 자리를 차지한다(launched 는 바이트 전에 저장되고, 점유 검사마다 worker-list 를 새로 본다)."""
        self.set_max_parallel(1)
        for tid, owns in (("T-000", "src/z/**"), ("T-001", "src/a/**"), ("T-002", "src/b/**")):
            self.make_task(tid, owns=owns)
        with state.edit(self.p, "T-000") as st:  # 취소된 launch_failed(기록된 자식): T-001 의 점유 검사가 worker-list 를 본다
            slot = {**dispatch.new_slot("T-000 r1 작업"), "launched": self.dead_record(), "canceled": True}
            st["rounds"] = [{"round": 1, "round_base": None, "agent": "claude", "model": None, "effort": None,
                             "note": None, "supplement": None, "work": slot, "reviews": [], "verdict": None}]
            st.update(round=1, status="launch_failed")
        real_go = launch.Barrier.go

        def go(barrier, timeout=600):
            code, out, err = real_go(barrier, timeout)
            if "T-001 r1 작업" in barrier.proc.args:  # 워커는 떴는데 horch 가 non-ok 로 끝났다
                d = json.loads(out.strip().splitlines()[-1])
                return 1, json.dumps({"ok": False, "error": {"code": "record_failed", "message": "x", "hint": ""},
                                      "task": d["task"], "dispatch": d["dispatch"]}), err
            return code, out, err

        with self.in_process(), mock.patch.object(launch.Barrier, "go", go):
            with self.assertRaises(HteamError) as cm:
                tasks.start_ready(self.p)
        data = cm.exception.data
        self.assertEqual(data["started"], [])
        self.assertEqual([(f["task"], f["error"]["code"]) for f in data["failed"]],
                         [("T-000", "launch_canceled"), ("T-001", "launch_failed")])
        self.assertEqual({w["task"]: w["reason"] for w in data["waiting"]}, {"T-002": "limit"})
        live = [r["title"] for r in self.horch_tasks() if r["state"] in ("launching", "active")]
        self.assertEqual(live, ["T-001 r1 작업"])

    def test_worker_settled_mid_call_frees_slot(self):
        """호출 도중 끝난(settled) 워커는 더 세지 않는다. 다음 태스크는 limit 대기가 아니라 뜬다."""
        self.set_max_parallel(2)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        self.make_task("T-003", owns="src/c/**", depends="T-001")  # start-ready 는 deps 로 건너뛴다
        self.assertEqual(self.hteam("start", "T-003", env={"HTEAM_TEST_DIE_AT": "after_launch"})[0], 137)
        did = next(r["id"] for r in self.horch_tasks() if r["title"] == "T-003 r1 작업")
        self.assertEqual(self.dispatch_row(did)["state"], "active")
        real_go = launch.Barrier.go

        def go(barrier, timeout=600):
            res = real_go(barrier, timeout)
            if "T-001 r1 작업" in barrier.proc.args:  # T-001 을 띄우는 사이 T-003 워커가 끝났다
                code, out = self.act(did, {"done": {"outcome": "succeeded", "summary": "끝"}})
                self.assertEqual(code, 0, out)
            return res

        with self.in_process(), mock.patch.object(launch.Barrier, "go", go):
            out = tasks.start_ready(self.p)
        self.assertEqual(self.dispatch_row(did)["state"], "settled")
        self.assertEqual([s["task"] for s in out["started"]], ["T-001", "T-002"], out)
        self.assertEqual({w["task"]: w["reason"] for w in out["waiting"]}, {"T-003": "deps"})


    def _go_failing_for(self, title):
        """title 의 장벽만 hc run 실패로 horch 가 깨끗이 실패하게 하는 go(Dispatch launch_failed, 산 워커 없음)."""
        real_go = launch.Barrier.go

        def go(barrier, timeout=600):
            if title not in barrier.proc.args and "--retry" not in barrier.proc.args:
                return real_go(barrier, timeout)
            self.fail_hc("run", "boom")
            try:
                return real_go(barrier, timeout)
            finally:
                with self._hc_locked() as hc:
                    hc["fail"].clear()
        return go

    def test_clean_horch_failure_leaves_slot_free(self):
        """horch 가 깨끗이 실패한(산 워커 없는) 태스크는 자리를 잡지 않는다. 같은 호출의 다음 태스크가 뜬다."""
        self.set_max_parallel(1)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        with self.in_process(), mock.patch.object(launch.Barrier, "go", self._go_failing_for("T-001 r1 작업")):
            with self.assertRaises(HteamError) as cm:
                tasks.start_ready(self.p)
        data = cm.exception.data
        self.assertEqual([(f["task"], f["error"]["code"]) for f in data["failed"]], [("T-001", "launch_failed")])
        self.assertEqual([s["task"] for s in data["started"]], ["T-002"])

    def test_clean_horch_failure_never_starves_across_calls(self):
        """호출을 거듭해도 깨끗이 실패하는 태스크가 뒤 태스크를 굶기지 않는다. 대기 사유는 실제로 뜬 T-002 다."""
        self.set_max_parallel(1)
        self.make_task("T-001", owns="src/a/**")
        self.make_task("T-002", owns="src/b/**")
        go = self._go_failing_for("T-001 r1 작업")
        for call in range(3):
            with self.subTest(call=call), self.in_process(), mock.patch.object(launch.Barrier, "go", go):
                try:
                    data = tasks.start_ready(self.p)
                except HteamError as exc:
                    data = exc.data
                self.assertEqual(self.task_state("T-002")["status"], "working")
                live = [r["title"] for r in self.horch_tasks() if r["state"] in ("launching", "active")]
                self.assertEqual(live, ["T-002 r1 작업"])
                if call:
                    self.assertEqual([(w["task"], w["reason"]) for w in data["waiting"]], [("T-001", "limit")])
                    self.assertIn("T-002", data["waiting"][0]["detail"])
                    self.assertNotIn("T-001", data["waiting"][0]["detail"].split(":")[-1])

    def test_occupancy_asks_only_launching_and_active(self):
        """점유 검사는 worker-list --state launching --state active 만 묻는다(잠금 안에서 hc 호출을 줄인다)."""
        self.make_task("T-001", owns="src/a/**")
        with state.edit(self.p, "T-001") as st:
            slot = {**dispatch.new_slot("T-001 r1 작업"), "launched": self.dead_record()}
            st["rounds"] = [{"round": 1, "round_base": None, "agent": "claude", "model": None, "effort": None,
                             "note": None, "supplement": None, "work": slot, "reviews": [], "verdict": None}]
            st.update(round=1, status="launch_failed")
        h = mock.Mock()
        h.workers.return_value = []
        self.assertEqual(tasks.occupied(self.p, "T-002", tasks.Capacity(h, 1)), [])
        h.workers.assert_called_once_with(states=("launching", "active"))
        with self.in_process():
            real = __import__("hteam.horch", fromlist=["Horch"]).Horch(self.p.horch_home)
        with mock.patch.object(real, "ok", return_value={"ok": True, "workers": []}) as ok:
            self.assertEqual(real.workers(states=("launching", "active")), [])
            real.workers()
        self.assertEqual([c.args for c in ok.call_args_list],
                         [("worker-list", "--state", "launching", "--state", "active"), ("worker-list",)])


class ComposeTest(StartCase):
    def test_fix_round_block_and_ask_rule(self):
        self.write_spec("T-001", "planner", depends="T-000", commit=False)
        self.commit("docs/reviews/T-001/r1.md", "VERDICT: REQUEST_CHANGES\n", "[T-001] review r1: REQUEST_CHANGES")
        cfg = config.load(self.p)
        spec = specs.load(self.p, "T-001")
        rd = {"round": 2, "note": "표를 고친다", "supplement": "T-009"}
        text = compose.work_spec(self.p, cfg, spec, rd, ["docs/planning/**"])
        for needle in ("## 수정 라운드 r2", "git log --grep '^\\[T-001\\]'", "`docs/reviews/T-001/r1.md` 의 지적을 모두",
                       "코디네이터 메모: 표를 고친다", "디렉터 보강 태스크 T-009", "ask-user --task T-001 --json -",
                       "ask-user --task T-001 --pending", "- T-000: `docs/tasks/T-000/report.md`"):
            self.assertIn(needle, text)


class BarrierTest(unittest.TestCase):
    def test_go_never_communicates_with_closed_stdin(self):
        """Python 3.11 의 communicate() 는 닫힌 stdin 을 flush 하다 ValueError 를 낸다. 장벽은 바이트를 직접 쓰고
        stdin 을 닫은 뒤 떼어(None) 둔다. communicate() 는 출력만 읽는다."""
        for send_first in (False, True):
            with self.subTest(send_first=send_first):
                b = launch.Barrier([sys.executable, "-c", "print('ran')"])
                seen = []
                real = b.proc.communicate

                def strict(input=None, timeout=None, b=b, real=real, seen=seen):
                    seen.append((b.proc.stdin, input))
                    return real(input=input, timeout=timeout)

                b.proc.communicate = strict
                if send_first:
                    b.send()  # hteam 은 기록을 저장한 직후 태스크 잠금 안에서 보낸다
                code, out, _ = b.go(timeout=30)
                self.assertEqual((code, out.strip(), seen), (0, "ran", [(None, None)]))

    def test_abort_never_runs_child(self):
        with __import__("tempfile").TemporaryDirectory() as d:
            marker = f"{d}/ran"
            b = launch.Barrier([sys.executable, "-c", f"open({marker!r}, 'w')"])
            b.abort()
            self.assertEqual(b.proc.returncode, launch.NOT_RUN)
            self.assertFalse(__import__("os").path.exists(marker))

    def test_abort_kills_on_wait_timeout_and_never_raises(self):
        """abort 는 원래 오류를 가리지 않는다: 기다리다 시간이 넘으면 죽이고, 예외를 내지 않는다."""
        b = launch.Barrier([sys.executable, "-c", "pass"])
        real_wait = b.proc.wait
        calls = []

        def wait(timeout=None):
            calls.append(timeout)
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(b.proc.args, timeout)
            return real_wait(timeout=timeout)

        b.proc.wait = wait
        with mock.patch.object(b.proc, "kill", wraps=b.proc.kill) as kill:
            b.abort()
        kill.assert_called_once()
        self.assertIsNotNone(b.proc.returncode)
        self.assertTrue(b.proc.stdout.closed and b.proc.stderr.closed)


    def test_kill_after_reap_is_noop(self):
        """거둔 뒤에는 pgid 가 재사용될 수 있다. kill 은 아무것도 하지 않는다."""
        b = launch.Barrier([sys.executable, "-c", "pass"])
        b.go(timeout=30)
        self.assertIsNotNone(b.proc.returncode)
        with mock.patch.object(launch.os, "killpg") as killpg, mock.patch.object(b.proc, "kill") as kill:
            b.kill()
        killpg.assert_not_called()
        kill.assert_not_called()

    def test_kill_reaches_group_of_zombie_leader(self):
        """자식(그룹 리더)이 거두기 전 좀비가 되고 자손만 남았다. macOS 의 getpgid 는 좀비에 ESRCH 를 내지만
        killpg 는 그룹에 닿는다. kill 은 그룹을 늘 죽인다."""
        prog = ("import subprocess, sys\n"
                "c = subprocess.Popen(['sleep', '30'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                "print(c.pid, flush=True)\n")
        b = launch.Barrier([sys.executable, "-c", prog])
        b.send()
        gpid = int(b.proc.stdout.readline())
        gstarted = procs.start_time(gpid)
        self.assertTrue(gstarted)
        self.addCleanup(lambda: procs.alive(gpid, gstarted) and os.kill(gpid, 9))  # 같은 시작 시각일 때만(우리 것)
        for _ in range(250):  # 자식이 끝나 좀비가 될 때까지(거두지 않는다)
            state_ = procs._ps_state(b.pid)
            if state_ and state_[0].startswith("Z"):
                break
            __import__("time").sleep(0.02)
        else:
            self.fail("5초 안에 자식이 좀비가 되지 않았다")
        b.kill()
        self.assertIsNotNone(b.proc.returncode)
        for _ in range(100):
            if not procs.alive(gpid, None):
                break
            __import__("time").sleep(0.02)
        self.assertFalse(procs.alive(gpid, None), "자손이 살아 남았다")


class SameRoundTest(StartCase):
    def test_recovery_keeps_stored_spec_and_owns(self):
        self.make_task("T-001")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")
        spec_file = self.state_dir / "tasks/T-001/r1-work.md"
        before = spec_file.read_text()
        self.write_spec("T-001", owns="src/x/**", title="바뀐 제목")  # 사양을 고쳐도
        with self._hc_locked() as hc:
            hc["fail"].clear()
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"]), (0, "retry"), out)
        st = self.task_state("T-001")
        self.assertEqual(st["owns"], ["src/**"])  # horch 가 저장된 사양으로 띄우므로 잠금도 저장된 owns
        self.assertEqual(spec_file.read_text(), before)

    def test_recovery_rejects_overrides(self):
        self.make_task("T-001")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")
        code, out = self.hteam("start", "T-001", "--worker", "codex")
        self.assertEqual((code, out["error"]["code"]), (2, "recovery_overrides"))
        self.assertEqual(self.task_state("T-001")["rounds"][0]["agent"], "claude")

    def test_adopt_aligns_round_with_real_dispatch(self):
        self.make_task("T-001")
        self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        with state.edit(self.p, "T-001") as st:
            st["rounds"][0].update(agent="codex", model="wrong")  # 기록이 실제 워커와 어긋났다
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["mode"]), (0, "adopt"), out)
        rd = self.task_state("T-001")["rounds"][0]
        self.assertEqual((rd["agent"], rd["model"]), ("claude", "opus"))

    def test_front_matter_owns_cannot_widen(self):
        self.make_task("T-001", owns="**")
        code, out = self.hteam("start", "T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "owns_too_wide"))
        self.make_task("T-002", owns="src/auth/**")
        self.assertEqual(self.hteam("start", "T-002")[0], 0)


if __name__ == "__main__":
    unittest.main()
