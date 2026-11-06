"""사용자 일괄 승인(설계 11.4): design-review 의 묶음·조건·stale·기록·링크·복구."""
import json
import time
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import approval, config, dispatch, outbox, procs, roles, state
from hteam.paths import Project

APPROVAL = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["designer"]') + """
[roles.designer]
title = "디자인"
owns = ["docs/design/**", "assets/**"]
"""


class ApprovalCase(TeamCase):
    config = APPROVAL

    def setUp(self):
        super().setUp()
        self.init_project(config=self.config, roles=("planner", "designer", "developer", "tester"))
        self.setup_run()
        self.p = Project(self.proj)

    def task(self, tid, status, role="designer", rnd=1, depends=None, title="화면 디자인"):
        """상태만 만든다(워커는 띄우지 않는다). designer 는 화면마다, developer 는 태스크마다 owns 를 나눈다. 시작한
        태스크에는 띄운 적 없는 라운드 기록 하나를 둔다(accept·fix 가 라운드 기록을 본다)."""
        owns = f"docs/design/screens/{tid.lower()}/**" if role == "designer" else f"src/{tid.lower()}/**"
        self.write_spec(tid, role, title=title, owns=owns, depends=depends, commit=False)
        state.create(self.p, tid, role)
        if status != "pending":
            with state.edit(self.p, tid) as st:
                rd = {"round": rnd, "round_base": None, "agent": "claude", "model": None, "effort": None, "note": None,
                      "supplement": None, "work": dispatch.new_slot(roles.work_title(tid, rnd)), "reviews": [],
                      "verdict": None}
                st.update(round=rnd, owns=[owns], rounds=[rd])
                state.move(st, status, "test")

    def move(self, tid, status, rnd=None):
        with state.edit(self.p, tid) as st:
            if rnd is not None:
                st["round"] = rnd
            state.move(st, status, "test")

    def opened(self, tid, rnd, at):
        """그 라운드를 연 기록(fix)을 남기고 라운드를 바꾼다. stale 판정이 이 시각을 본다."""
        with state.edit(self.p, tid) as st:
            st["round"] = rnd
            st["history"].append({"at": at, "from": st["status"], "to": st["status"], "event": "fix", "round": rnd})

    def wait_gone(self, rec, limit=10.0):
        """시작 장벽 자식이 끝날 때까지 기다린다. 실행자가 시작 바이트 전에 죽으면 자식은 stdin 의 EOF 를 보고 스스로
        끝나지만 그 시점은 정해져 있지 않다. 살아 있는 동안의 복구는 launching(exit 3)이라 기다린 뒤에 복구한다."""
        deadline = time.monotonic() + limit
        while procs.record_alive(rec):
            if time.monotonic() >= deadline:
                self.fail(f"{limit}초 안에 시작 장벽 자식(pid {rec.get('pid')})이 끝나지 않았다")
            time.sleep(0.05)

    def restart_after_predecessor_refix(self, die_at):
        """T-002 가 T-001 r3 을 보고 뜨다가 die_at 에서 실행자가 죽었다. 그 사이 T-001 이 결정 밖에서 r4 로 고쳐져 다시
        승인됐다. T-002 를 다시 start 한 (exit, 출력). after_launch 면 그 전에 워커가 이미 성공으로 끝났다."""
        self.task("T-001", "awaiting_user", rnd=3)
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", depends="T-001", commit=False)
        state.create(self.p, "T-002", "designer")
        self.assertEqual(self.hteam("start", "T-002", env={"HTEAM_TEST_DIE_AT": die_at})[0], 137)
        rd = self.task_state("T-002")["rounds"][-1]
        self.assertIsNotNone(rd["work"]["launched"])
        self.assertEqual(rd["basis"], {"T-001": 3})  # launched 와 같은 저장에 썼다
        self.wait_gone(rd["work"]["launched"])  # 복구가 시작 장벽 자식의 종료 시점에 기대지 않게 한다
        if die_at == "after_launch":
            code, out = self.horch("worker-list")
            self.assertEqual(code, 0, out)
            [row] = out["workers"]
            code, out = self.act(row["id"], {"done": {"outcome": "succeeded", "summary": "r3 을 보고 만들었다"}})
            self.assertEqual(code, 0, out)
        self.move("T-001", "awaiting_user", rnd=4)
        return self.hteam("start", "T-002")

    def review(self, **kw):
        return self.hteam("design-review", **kw)

    def outbox_items(self):
        return outbox.read_outbox(self.p)

    def record(self):
        return json.loads((self.state_dir / "design-review.json").read_text(encoding="utf-8"))


class DesignReviewTest(ApprovalCase):
    def test_batches_every_waiting_task(self):
        self.task("T-001", "awaiting_user", title="로그인 화면")
        self.task("T-002", "awaiting_user", title="목록 화면")
        self.task("T-003", "working", role="developer")  # 비승인 직무는 묶음을 막지 않는다
        self.commit("docs/tasks/T-001/report.md", "## r1\n- 아티팩트: https://claude.ai/artifact/abc-1\n", "[T-001] r1")
        code, out = self.review()
        self.assertEqual(code, 0, out)
        self.assertEqual((out["id"], out["batch"], out["resumed"]), ("out-0001", "dr-0001", False))
        self.assertEqual(out["tasks"], [{"task": "T-001", "round": 1}, {"task": "T-002", "round": 1}])
        [entry] = self.outbox_items()
        self.assertEqual((entry["type"], entry["from"], entry["batch"]), ("approval", "coordinator", "dr-0001"))
        render = entry["render"]
        self.assertEqual([o["label"] for o in render["options"]], ["모두 승인 (추천)", "수정 요청"])
        self.assertIn("- T-001 r1 [디자인] 로그인 화면: https://claude.ai/artifact/abc-1", render["context"])
        self.assertIn("- T-002 r1 [디자인] 목록 화면: docs/tasks/T-002/report.md", render["context"])  # 링크가 없다
        outbox.validate_render(render, "디자인 승인")
        self.assertEqual([(b["batch"], b["id"]) for b in self.record()["batches"]], [("dr-0001", "out-0001")])
        self.assertIn("out-0001", [q["id"] for q in outbox.open_questions(self.p)])

    def test_waits_for_approval_tasks_in_progress(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "working")
        for status in ("working", "reviewing", "approved", "changes", "launch_failed"):
            with self.subTest(status):
                self.move("T-002", status)
                code, out = self.review()
                self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
                self.assertEqual([b["task"] for b in out["blockers"]], ["T-002"])
        self.assertEqual(self.outbox_items(), [])

    def test_startable_pending_blocks_but_waiting_on_deps_does_not(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "pending", role="developer")
        self.task("T-003", "pending", depends="T-002")  # 승인 → 비승인 → 승인: 다음 묶음이 된다
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}]), out)
        self.task("T-004", "awaiting_user")
        self.task("T-005", "pending")  # 의존 없음, 잠금 비어 있음: 지금 시작할 수 있다
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        self.assertEqual(out["blockers"], [{"task": "T-005", "status": "pending", "why": "지금 시작할 수 있다"}])

    def test_locked_pending_does_not_block(self):
        self.task("T-001", "awaiting_user")
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-001/**", commit=False)  # T-001 의 잠금과 겹친다
        state.create(self.p, "T-002", "designer")
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}]), out)

    def test_task_round_is_asked_once(self):
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"], out.get("asked")), (3, "already_asked", ["out-0001"]), out)
        self.task("T-002", "awaiting_user")  # T-001 의 답을 기다리는 동안 새로 기다리는 태스크만 묻는다
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("tasks")), (0, "out-0002", [{"task": "T-002", "round": 1}]), out)
        self.move("T-001", "awaiting_user", rnd=2)  # 사용자 수정 요청 뒤 r2 가 다시 승인됐다
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("tasks")), (0, "out-0003", [{"task": "T-001", "round": 2}]), out)

    def test_task_built_on_an_older_predecessor_is_not_asked(self):
        # T-002 r1 은 T-001 r1 을 보고 만들었다. 그 뒤 사용자 요청으로 T-001 r2 가 열렸다: T-002 도 고쳐야 한다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.opened("T-001", 1, "2026-11-06T09:00:00Z")
        self.opened("T-002", 1, "2026-11-06T10:00:00Z")
        self.opened("T-001", 2, "2026-11-06T10:05:00Z")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_stale"), out)
        self.assertEqual(out["stale"], [{"task": "T-002", "round": 1, "because": ["T-001"]}])
        self.assertIn("메인에 알린다", out["error"]["hint"])
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {"T-002": ["T-001"]})
        self.opened("T-002", 2, "2026-11-06T10:05:00Z")  # 선행과 함께(같은 초에) 고쳤다: stale 이 아니다
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 2}, {"task": "T-002", "round": 2}]),
                         out)

    def test_stale_uses_rounds_seen_at_launch(self):
        self.task("T-001", "awaiting_user", rnd=3)
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", depends="T-001", commit=False)
        state.create(self.p, "T-002", "designer")
        self.assertEqual(self.hteam("start", "T-002")[0], 0)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 3})  # 띄울 때 본 선행 라운드
        self.move("T-002", "awaiting_user")
        self.opened("T-001", 3, "2099-01-01T00:00:00Z")  # 시각만 보면 stale 로 보인다(선행 라운드를 나중에 열었다)
        cfg = config.load(self.p)
        self.assertEqual(approval.stale(self.p, cfg, state.all_states(self.p)), {})
        self.move("T-001", "awaiting_user", rnd=4)  # 띄운 뒤에 선행이 새 라운드를 열었다
        self.assertEqual(approval.stale(self.p, cfg, state.all_states(self.p)), {"T-002": ["T-001"]})

    def test_recovery_that_adopts_keeps_the_launch_basis(self):
        # 같은 라운드 복구가 옛 Dispatch(T-001 r3 을 보고 만든 결과)를 이어 붙인다. 복구가 basis 를 r4 로 덮으면 옛
        # 결과를 최신 선행을 본 것으로 승인하게 된다
        code, out = self.restart_after_predecessor_refix("after_launch")
        self.assertEqual((code, out.get("mode")), (0, "adopt"), out)
        rd = self.task_state("T-002")["rounds"][-1]
        self.assertEqual(rd["basis"], {"T-001": 3})  # 처음 띄울 때 본 선행 그대로다
        self.assertEqual(rd["work"]["pred_rounds"], {"T-001": 4})  # 복구의 시작 예약은 본 것을 적어 두기만 한다
        self.move("T-002", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_stale"), out)
        self.assertEqual(out["stale"], [{"task": "T-002", "round": 1, "because": ["T-001"]}])

    def test_recovery_that_launches_again_records_a_new_basis(self):
        # 시작 바이트를 보내기 전에 죽어 워커가 뜨지 않았다. 다시 띄우는 워커는 T-001 r4 를 본다
        code, out = self.restart_after_predecessor_refix("after_child")
        self.assertEqual((code, out.get("mode")), (0, "fresh"), out)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 4})
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {})

    def test_nothing_to_approve_and_permissions(self):
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "nothing_to_approve"), out)
        code, out = self.review(as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "not_coordinator"), out)
        (self.team / "config.toml").write_text(BASE_CONFIG, encoding="utf-8")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (2, "no_approval_roles"), out)

    def test_crash_between_record_and_outbox_asks_once(self):
        self.task("T-001", "awaiting_user")
        code, _ = self.review(env={"HTEAM_TEST_DIE_AT": "design_review_recorded"})
        self.assertEqual(code, 137)
        self.assertEqual(self.outbox_items(), [])
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("resumed")), (0, "out-0001", True), out)
        self.task("T-002", "awaiting_user")
        code, _ = self.review(env={"HTEAM_TEST_DIE_AT": "design_review_appended"})
        self.assertEqual(code, 137)
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("batch"), out.get("resumed")), (0, "out-0002", "dr-0002", True),
                         out)
        self.assertEqual([e["id"] for e in self.outbox_items()], ["out-0001", "out-0002"])  # 두 번 묻지 않았다
        self.assertEqual([b["id"] for b in self.record()["batches"]], ["out-0001", "out-0002"])

    def test_resume_finds_entry_missing_only_its_last_lf(self):
        # 항목 JSON 은 다 썼는데 마지막 LF 만 못 쓰고 죽었다. 다음 호출은 그 항목을 완결해 쓰고 새로 쓰지 않는다
        self.task("T-001", "awaiting_user")
        code, _ = self.review(env={"HTEAM_TEST_DIE_AT": "design_review_appended"})
        self.assertEqual(code, 137)
        path = self.state_dir / "outbox.jsonl"
        path.write_bytes(path.read_bytes().rstrip(b"\n"))
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("resumed")), (0, "out-0001", True), out)
        self.assertEqual([(e["id"], e["batch"]) for e in self.outbox_items()], [("out-0001", "dr-0001")])
        self.assertEqual(self.record()["batches"][0]["id"], "out-0001")

    def test_corrupt_record_is_kept(self):
        self.task("T-001", "awaiting_user")
        path = self.state_dir / "design-review.json"
        good = {"batch": "dr-0001", "at": "2026-11-06T10:00:00Z", "id": "out-0001",
                "tasks": [{"task": "T-009", "round": 1}], "render": approval.render(self.p, config.load(self.p), [])}
        for broken in ("{broken", {"batches": [{"batch": 1}]}, {"batches": [{**good, "id": None, "render": 42}]},
                       {"batches": [{**good, "id": 7}]}, {"batches": [good, {**good, "batch": "dr-0002", "id": "out-0002"}]},
                       {"batches": [good, {**good, "tasks": [{"task": "T-008", "round": 1}]}]},
                       {"batches": [{**good, "tasks": [{"task": "T-009", "round": 0}]}]}):
            with self.subTest(broken):
                text = broken if isinstance(broken, str) else json.dumps(broken, ensure_ascii=False)
                path.write_text(text, encoding="utf-8")
                code, out = self.review()
                self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
                self.assertEqual(path.read_text(encoding="utf-8"), text)  # 덮어쓰지 않았다
        self.assertEqual(self.outbox_items(), [])

    def test_unreadable_state_refuses(self):
        self.task("T-001", "awaiting_user")
        (self.state_dir / "tasks" / "T-002.json").write_text("{", encoding="utf-8")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (1, "bad_state_file"), out)
        self.assertEqual(self.outbox_items(), [])


class LinkTest(ApprovalCase):
    def test_last_claude_url_without_design_system(self):
        report = ("## r1\n- 아티팩트: https://claude.ai/artifact/old\n## r2\n- 아티팩트: https://claude.ai/artifact/new).\n"
                  "- design_system_url: https://claude.ai/artifact/sys\n- 시스템 URL: https://claude.ai/artifact/sys2\n")
        self.commit("docs/tasks/T-001/report.md", report, "[T-001] r2")
        self.commit("docs/design/direction.md", "design_system_url: https://claude.ai/artifact/sys2\n", "dir")
        self.assertEqual(approval.link(self.p, "T-001"), "https://claude.ai/artifact/new")
        self.assertEqual(approval.link(self.p, "T-009"), "docs/tasks/T-009/report.md")

    def test_context_stays_within_limit(self):
        ids = [f"T-{i:03d}" for i in range(1, 81)]
        for tid in ids:
            self.task(tid, "awaiting_user", title="아주 긴 화면 이름 " * 8)
        render = approval.render(self.p, config.load(self.p), [state.load(self.p, t) for t in ids])
        self.assertLessEqual(len(render["context"]), 4000)
        self.assertIn("그 밖", render["context"])
        self.assertIn("T-080", render["context"])  # 줄이 넘친 태스크도 ID 는 남는다


if __name__ == "__main__":
    unittest.main()
