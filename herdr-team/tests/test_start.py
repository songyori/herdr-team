"""start·start-ready(설계 5.4), 워커 사양 조립(5.5), 시작 장벽과 복구."""
import json
import subprocess
import sys
import unittest

from tests.helpers import BASE_CONFIG, COORD, TeamCase
from hteam import compose, config, dispatch, launch, procs, specs, state, tasks
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
    def test_go_sends_byte_without_closing_stdin_first(self):
        """Python 3.11 의 communicate() 는 닫힌 stdin 을 flush 하다 ValueError 를 낸다. 장벽은 input= 으로 보낸다."""
        b = launch.Barrier([sys.executable, "-c", "print('ran')"])
        seen = []
        real = b.proc.communicate

        def strict(input=None, timeout=None):
            seen.append((b.proc.stdin.closed, input))
            return real(input=input, timeout=timeout)

        b.proc.communicate = strict
        code, out, _ = b.go(timeout=30)
        self.assertEqual((code, out.strip(), seen), (0, "ran", [(False, b"x")]))

    def test_abort_never_runs_child(self):
        with __import__("tempfile").TemporaryDirectory() as d:
            marker = f"{d}/ran"
            b = launch.Barrier([sys.executable, "-c", f"open({marker!r}, 'w')"])
            b.abort()
            self.assertEqual(b.proc.returncode, launch.NOT_RUN)
            self.assertFalse(__import__("os").path.exists(marker))


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
