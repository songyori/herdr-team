"""사용자 일괄 승인(설계 11.4): design-review 의 묶음·조건·stale·기록·링크·복구."""
import json
import time
import unittest
from pathlib import Path

from tests.helpers import BASE_CONFIG, ROOT, TeamCase
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
        import time  # 머리 import 는 뒤 태스크의 찾을 내용이라 그대로 둔다
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
    def test_proposals_do_not_block_without_director_role(self):
        # [roles.director] 가 없으면 보강할 디렉터가 없다. 시스템 추가 제안이 있어도 그대로 묻는다(설계 11.4)
        self.task("T-001", "awaiting_user")
        self.commit("docs/tasks/T-001/report.md", "## r1\n### 시스템 추가 제안\n- 배지 색\n", "[T-001] r1")
        self.assertEqual(self.review()[0], 0)

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

    def test_removed_record_does_not_reuse_an_old_batch(self):
        # bad_side_file 힌트대로 기록을 치웠다. 묶음 번호가 dr-0001 로 돌아가 옛 outbox 항목을 다시 쓰면 묻지 않게 된다
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        (self.state_dir / "design-review.json").unlink()
        self.task("T-002", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("batch"), out.get("resumed")), (0, "out-0002", "dr-0002", False),
                         out)
        self.assertEqual([(e["id"], e["batch"]) for e in self.outbox_items()],
                         [("out-0001", "dr-0001"), ("out-0002", "dr-0002")])

    def test_resume_reuses_only_the_same_question(self):
        # 손으로 고친 기록: 쓰다 멈춘 dr-0001 이 이미 outbox 에 있는 dr-0001 과 다른 질문이다. 옛 항목을 쓰지 않는다
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        self.task("T-002", "awaiting_user")
        cfg = config.load(self.p)
        other = approval.render(self.p, cfg, [state.load(self.p, "T-002")])
        (self.state_dir / "design-review.json").write_text(json.dumps({"batches": [
            {"batch": "dr-0001", "at": "2026-11-06T10:00:00Z", "id": None, "tasks": [{"task": "T-002", "round": 1}],
             "render": other}]}, ensure_ascii=False), encoding="utf-8")
        code, out = self.review()
        self.assertEqual((code, out.get("id"), out.get("resumed")), (0, "out-0002", True), out)
        self.assertEqual(self.outbox_items()[-1]["render"], other)

    def test_basis_counts_only_finished_predecessor_rounds(self):
        # T-001 r4 가 아직 일하는 중에 T-002 를 고쳤다. T-002 r2 는 T-001 r3 의 결과를 보고 만들었다
        self.task("T-001", "awaiting_user", rnd=3)
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", depends="T-001", commit=False)
        state.create(self.p, "T-002", "designer")
        self.assertEqual(self.hteam("start", "T-002")[0], 0)
        self.move("T-001", "working", rnd=4)
        code, out = self.hteam("fix", "T-002", "--note=선행이 바뀌었다")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 3})  # 끝난 선행 라운드
        self.move("T-001", "awaiting_user")  # T-001 r4 가 끝났다
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {"T-002": ["T-001"]})

    def test_predecessor_missing_from_basis_counts_as_round_zero(self):
        # 예약 때 상태가 없었거나 사양을 읽지 못해 basis 에 없는 선행은 아무것도 보지 않은 것이다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        with state.edit(self.p, "T-002") as st:
            st["rounds"][-1]["basis"] = {}
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {"T-002": ["T-001"]})

    def start_dependent(self):
        """T-001 에 의존하는 T-002 를 손으로 띄우고 그 라운드의 basis 를 돌려준다."""
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", depends="T-001", commit=False)
        state.create(self.p, "T-002", "designer")
        code, out = self.hteam("start", "T-002")
        self.assertEqual(code, 0, out)
        return self.task_state("T-002")["rounds"][-1]["basis"]

    def test_predecessor_dropped_after_approval_is_finished(self):
        # T-001 r1 을 awaiting_user 에서 버린 뒤 T-002 가 떴다. 버린 태스크는 새 라운드를 열지 않는다: stale 이 아니다
        self.task("T-001", "awaiting_user")
        self.move("T-001", "dropped")
        self.assertEqual(self.start_dependent(), {"T-001": 1})
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {})

    def test_fix_after_predecessor_dropped_mid_round_is_not_stale(self):
        # T-002 r1 이 T-001 r1 을 보고 뜬 뒤 T-001 r2 를 일하다 버렸다. T-002 r1 은 stale 이고, 힌트대로 fix 한 r2 는 아니다
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.start_dependent(), {"T-001": 1})
        self.move("T-001", "working", rnd=2)
        self.move("T-001", "dropped")
        self.move("T-002", "awaiting_user")
        cfg = config.load(self.p)
        self.assertEqual(approval.stale(self.p, cfg, state.all_states(self.p)), {"T-002": ["T-001"]})
        code, out = self.hteam("fix", "T-002", "--note=선행이 버려졌다")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 2})
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, cfg, state.all_states(self.p)), {})
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-002", "round": 2}]), out)

    def test_approved_predecessor_round_is_not_yet_finished(self):
        # approved 에는 작업 워커가 아직 살아 있을 수 있다(리뷰는 worker-retain 실패를 견딘다). 그 워커가 같은 라운드에서
        # 더 고치면 r2 결과가 바뀌므로 approved 는 끝난 라운드가 아니다(보수적: 승인 그대로면 stale 이 한 번 더 뜬다)
        self.task("T-001", "approved", rnd=2)
        self.assertEqual(self.start_dependent(), {"T-001": 1})
        self.move("T-002", "awaiting_user")
        self.move("T-001", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {"T-002": ["T-001"]})

    def test_planner_held_by_the_single_planner_rule_does_not_block(self):
        # 승인 직무가 기획이다. 기획은 한 번에 하나라 T-001 이 끝나기 전에는 T-002 를 시작할 수 없다(planner_busy)
        (self.team / "config.toml").write_text(
            APPROVAL.replace('user_approval_roles = ["designer"]', 'user_approval_roles = ["planner"]'), encoding="utf-8")
        for tid, owns in (("T-001", "docs/planning/a/**"), ("T-002", "docs/planning/b/**")):
            self.write_spec(tid, "planner", owns=owns, commit=False)
            state.create(self.p, tid, "planner")
        self.move("T-001", "awaiting_user", rnd=1)
        code, out = self.hteam("start-ready")
        self.assertEqual([w["reason"] for w in out.get("waiting", []) if w["task"] == "T-002"], ["lock"], out)
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}]), out)

    def test_pending_role_comes_from_the_current_spec(self):
        # 첫 시작 전에 사양의 직무를 바꿨다. 첫 시작이 저장된 직무를 사양에 맞추므로 pending 은 사양의 직무로 본다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "pending", role="developer")
        self.write_spec("T-002", "designer", owns="docs/design/screens/t-002/**", commit=False)  # 개발 → 디자인
        self.task("T-003", "pending")
        self.write_spec("T-003", "developer", owns="src/t-003/**", commit=False)  # 디자인 → 개발
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        self.assertEqual(out["blockers"], [{"task": "T-002", "status": "pending", "why": "지금 시작할 수 있다"}])


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


H = ".herdr-team/bin/hteam"


class DecisionCase(ApprovalCase):
    def answered(self, oid, text="모두 승인 (추천)"):
        """그 질문에 메인의 답이 온 것으로 둔다(답 파일과 보낸 기록). 이미 있으면 그대로 둔다."""
        path = self.state_dir / "answers" / f"{oid}.json"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"id": oid, "answer": text, "at": "2026-11-06T10:00:00Z",
                                        "sent_at": "2026-11-06T10:00:00Z"}, ensure_ascii=False), encoding="utf-8")

    def decide(self, oid, fix=None, answer=True, **kw):
        """design-review --decide. fix 가 None 이면 입력 없이(기록대로 다시 한다). 입력을 주면 먼저 답이 온 것으로 둔다
        (answer=False 면 두지 않는다. 결정은 답이 온 질문만 새로 계산한다)."""
        if fix is not None and answer:
            self.answered(oid, "모두 승인 (추천)" if not fix else "수정 요청")
        args = ["design-review", "--decide", oid] + ([] if fix is None else ["--json", "-"])
        stdin = None if fix is None else json.dumps({"fix": fix}, ensure_ascii=False)
        return self.hteam(*args, stdin=stdin, **kw)

    def rounds(self, *tids):
        return [(t, self.task_state(t)["status"], self.task_state(t)["round"]) for t in tids]


class ApprovalReplyTest(DecisionCase):
    def test_unreadable_task_state_is_not_treated_as_done(self):
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        (self.state_dir / "tasks" / "T-001.json").write_text("{", encoding="utf-8")
        view = approval.reply_view(self.p, "out-0001", "모두 승인 (추천)")
        self.assertEqual((view["unknown"], view["tasks"][0]["pending"], view["decision"]), (["T-001"], False, None))
        hint = approval.reply_hint(view, "out-0001")
        self.assertIn("결정하지 않는다", hint)
        self.assertIsNone(approval.reply_view(self.p, "out-0009", "x"))  # 일괄 승인 질문이 아니다
        code, out = self.decide("out-0001", {})  # 결정도 상태를 읽지 못하면 하지 않는다
        self.assertEqual((code, out["error"]["code"]), (1, "bad_state_file"), out)
        self.assertNotIn("decision", self.record()["batches"][0])


class ApprovalDecisionTest(DecisionCase):
    """일괄 승인 결정: 한 번 기록하고 기록대로 다시 한다(설계 11.4)."""

    def cross_batches(self):
        """첫 묶음 T-001·T-002, 둘째 묶음 T-003(T-001 에 의존). 첫 답이 T-001 을 고치면 T-003 도 함께 고친다."""
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        self.task("T-003", "awaiting_user", depends="T-001")  # T-001 의 답을 기다리는 동안 따로 둘째 묶음에 들어갔다
        self.assertEqual(self.review()[1].get("id"), "out-0002")
        self.task("T-004", "pending", depends="T-001")  # 아직 시작하지 않았다: 선행이 다시 승인된 뒤에 시작한다
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual(code, 0, out)
        return out

    def test_decision_fixes_named_tasks_and_their_dependents_in_other_batches(self):
        d = self.cross_batches()["decision"]
        self.assertEqual([(e["task"], e["round"], e["note"]) for e in d["fix"]],
                         [("T-001", 1, "버튼을 크게"), ("T-003", 1, "선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게")])
        self.assertEqual(d["accept"], [{"task": "T-002", "round": 1}])
        self.assertEqual([s["task"] for s in d["skipped"]], ["T-004"])
        self.assertEqual(self.rounds("T-001", "T-002", "T-003"),
                         [("T-001", "launch_failed", 2), ("T-002", "done", 1), ("T-003", "launch_failed", 2)])
        self.assertTrue(self.task_state("T-003")["rounds"][-1]["queued"])
        work = (self.state_dir / "tasks/T-003/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("사용자 요청: 선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", work)
        self.assertIn("out-0001", json.loads((self.state_dir / "applied.json").read_text(encoding="utf-8")))
        tasks_ = {t["id"]: t for t in self.hteam("status")[1]["tasks"]}
        self.assertEqual(tasks_["T-003"]["next"], [H, "start-ready"])  # start T 는 의존을 보지 않으므로 권하지 않는다
        # 둘째 묶음의 답(모두 승인)이 와도 이미 고친 T-003 을 승인하지 않는다
        code, out = self.decide("out-0002", {})
        self.assertEqual((code, out["decision"]["accept"]), (0, []), out)
        # 첫 답이 다시 와도 기록한 라운드가 지나 아무것도 다시 하지 않는다(T-003 은 r3 가 되지 않는다)
        code, out = self.decide("out-0001")
        self.assertEqual((code, out["replayed"]), (0, True), out)
        self.assertEqual(self.rounds("T-001", "T-003"), [("T-001", "launch_failed", 2), ("T-003", "launch_failed", 2)])

    def test_separate_request_for_a_task_another_decision_reopened_is_kept(self):
        # 둘째 묶음의 답이 T-003 에 따로 수정을 요청했다. T-003 은 첫 결정이 이미 r2 로 만들었지만 이 요청을 버리지 않는다
        self.cross_batches()
        code, out = self.decide("out-0002", {"T-003": "글꼴을 바꾼다"})
        self.assertEqual(code, 0, out)
        [entry] = out["decision"]["fix"]
        self.assertEqual((entry["task"], entry["round"]), ("T-003", 2))
        self.assertEqual(entry["note"], "글꼴을 바꾼다 / 이전 요청도 그대로 반영한다: 선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게")
        self.assertEqual(self.rounds("T-003"), [("T-003", "launch_failed", 3)])
        work = (self.state_dir / "tasks/T-003/r3-work.md").read_text(encoding="utf-8")
        self.assertIn("글꼴을 바꾼다", work)
        self.assertIn("버튼을 크게", work)
        self.assertIn("out-0002", json.loads((self.state_dir / "applied.json").read_text(encoding="utf-8")))
        for oid in ("out-0001", "out-0002"):  # 어느 답이 다시 와도 r4 가 열리지 않는다
            self.assertEqual(self.decide(oid)[0], 0)
        self.assertEqual(self.rounds("T-003"), [("T-003", "launch_failed", 3)])

    def test_request_for_a_finished_task_is_a_conflict(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.move("T-001", "dropped")
        code, out = self.decide("out-0001", {"T-001": "x"})
        self.assertEqual((code, out["error"]["code"], out.get("closed")), (3, "decision_conflict", ["T-001"]), out)
        self.assertNotIn("decision", self.record()["batches"][0])
        self.assertFalse((self.state_dir / "applied.json").exists())

    def test_crash_and_replay_keep_every_request(self):
        # T-002 는 T-001 에 의존한다. 사용자는 둘 다 고치라고 했다(T-001 버튼, T-002 글꼴)
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.review()
        want = {"T-001": "버튼을 크게", "T-002": "글꼴을 바꾼다"}
        code, _ = self.decide("out-0001", want, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "awaiting_user", 1), ("T-002", "awaiting_user", 1)])
        tasks_ = {t["id"]: t for t in self.hteam("status")[1]["tasks"]}
        self.assertEqual(tasks_["T-002"]["next"], [H, "design-review", "--decide", "out-0001"])  # 일반 fix 를 권하지 않는다
        code, _ = self.decide("out-0001", env={"HTEAM_TEST_DIE_AT": "decision_after_fix"})  # 첫 fix 뒤 죽었다
        self.assertEqual(code, 137)
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "launch_failed", 2), ("T-002", "awaiting_user", 1)])
        code, out = self.decide("out-0001", {"T-001": "다른 해석"})  # 다시 온 답을 다르게 읽어도 기록대로 한다
        self.assertEqual((code, out["replayed"], out["passed"]), (0, True, ["T-001"]), out)
        self.assertTrue(out["warnings"])
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "launch_failed", 2), ("T-002", "launch_failed", 2)])
        second = (self.state_dir / "tasks/T-002/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("글꼴을 바꾼다", second)
        self.assertIn("선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", second)
        self.assertNotIn("다른 해석", (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8"))

    def test_start_ready_rechecks_deps_after_a_decision_lands(self):
        # start-ready 가 T-002 의 의존(T-001 awaiting_user)을 본 직후 결정이 T-001 을 고쳤다. 시작 예약에서 다시 보고 띄우지 않는다
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "pending", depends="T-001")
        gate = self.tmp / "gate-start"
        proc = self.hteam_bg("start-ready", env={"HTEAM_TEST_PAUSE_AT": "start_ready_checked",
                                                 "HTEAM_TEST_PAUSE_FILE": str(gate)})
        reached = Path(str(gate) + ".reached")
        deadline = time.monotonic() + 30
        while not reached.exists():
            self.assertIsNone(proc.poll())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual((code, [s["task"] for s in out.get("decision", {}).get("skipped", [])]), (0, ["T-002"]), out)
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual((code, out.get("started")), (0, []), out)
        self.assertEqual([w["reason"] for w in out["waiting"] if w["task"] == "T-002"], ["deps"])
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_unfinished_decision_holds_its_dependents(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "pending", depends="T-001")
        code, _ = self.decide("out-0001", {"T-001": "x"}, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)  # 기록만 했다. 선행은 아직 awaiting_user 라 의존 검사만 보면 T-002 를 띄운다
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out.get("started")), (0, []), out)
        self.assertEqual([w["reason"] for w in out["waiting"] if w["task"] == "T-002"], ["decision"])
        code, out = self.hteam("start", "T-002")  # 손으로 띄워도 막는다
        self.assertEqual((code, out["error"]["code"], out.get("pending")), (3, "decision_pending", "out-0001"), out)
        self.assertEqual(self.decide("out-0001")[0], 0)  # 결정을 마저 한다
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"], out)  # 선행의 수정 라운드만
        self.assertEqual([w["reason"] for w in out["waiting"] if w["task"] == "T-002"], ["deps"])

    def test_queued_dependent_started_after_predecessor_refix_is_not_stale(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.review()
        self.assertEqual(self.decide("out-0001", {"T-001": "x", "T-002": "y"})[0], 0)  # 둘 다 queued r2
        self.assertNotIn("basis", self.task_state("T-002")["rounds"][-1])  # 아직 띄우지 않았다
        # T-001 r2 가 리뷰에서 한 번 더 고쳐져 r3 에서 승인됐다(T-002 의 queued 라운드보다 나중에 열렸다)
        self.move("T-001", "awaiting_user", rnd=3)
        self.opened("T-001", 3, "2099-01-01T00:00:00Z")
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-002"], out)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["basis"], {"T-001": 3})  # 실제로 띄울 때 본 선행
        self.move("T-002", "awaiting_user")
        self.assertEqual(approval.stale(self.p, config.load(self.p), state.all_states(self.p)), {})

    def test_crash_between_done_and_applied_is_recovered(self):
        self.task("T-001", "awaiting_user")
        self.review()
        code, _ = self.decide("out-0001", {}, env={"HTEAM_TEST_DIE_AT": "decision_done"})
        self.assertEqual(code, 137)
        self.assertEqual(self.task_state("T-001")["status"], "done")
        self.assertFalse((self.state_dir / "applied.json").exists())
        view = approval.reply_view(self.p, "out-0001", "모두 승인 (추천)")
        self.assertEqual((view["decision"], view["applied"]), ("done", False))
        self.assertIn("--decide out-0001", approval.reply_hint(view, "out-0001"))  # ack 만 하라고 하지 않는다
        self.assertEqual(self.decide("out-0001")[0], 0)
        self.assertIn("out-0001", json.loads((self.state_dir / "applied.json").read_text(encoding="utf-8")))
        view = approval.reply_view(self.p, "out-0001", "모두 승인 (추천)")
        self.assertIn("ack 만", approval.reply_hint(view, "out-0001"))

    def test_unfinished_decision_comes_first(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "awaiting_user")
        self.review()
        code, _ = self.decide("out-0001", {"T-001": "x"}, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)
        code, out = self.decide("out-0002", {})
        self.assertEqual((code, out["error"]["code"], out.get("pending")), (3, "decision_pending", "out-0001"), out)
        self.task("T-003", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "decision_pending"), out)

    def test_decision_input_is_checked_before_anything(self):
        self.task("T-001", "awaiting_user")
        self.review()
        for fix in ({"T-009": "x"}, {"T-001": " "}):
            code, out = self.decide("out-0001", fix)
            self.assertEqual((code, out["error"]["code"]), (2, "bad_decision"), out)
        code, out = self.decide("out-0001")  # 결정이 아직 없는데 입력이 없다
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        code, out = self.decide("out-0009", {})
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_batch"), out)
        code, out = self.decide("out-0001", {}, as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "not_coordinator"), out)
        self.assertNotIn("decision", self.record()["batches"][0])

    def test_corrupt_applied_record_stops_before_deciding(self):
        # 적용 기록을 읽지 못하면 결정을 기록하거나 fix·accept 하기 전에 멈춘다(끝의 mark_applied 에서야 멈추면 결정만 해 버린다)
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        path = self.state_dir / "applied.json"
        path.write_text("{broken", encoding="utf-8")
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertNotIn("decision", self.record()["batches"][0])
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "awaiting_user", 1), ("T-002", "awaiting_user", 1)])
        self.assertEqual(path.read_text(encoding="utf-8"), "{broken")

    def test_corrupt_decision_record_is_kept(self):
        self.task("T-001", "awaiting_user")
        self.review()
        data = self.record()
        data["batches"][0]["decision"] = {"at": "2026-11-06T10:00:00Z", "fix": [{"task": "T-001", "round": 1}],
                                          "accept": [], "skipped": [], "done": None}  # note 가 없다
        path = self.state_dir / "design-review.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        code, out = self.decide("out-0001")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_accept_rechecks_predecessor_at_the_final_transition(self):
        # accept 의 사전 처리(Dispatch 정리) 동안 선행이 새 라운드를 열었다. 마지막 전이에서 다시 보고 승인하지 않는다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.opened("T-001", 1, "2026-11-06T09:00:00Z")
        self.opened("T-002", 1, "2026-11-06T10:00:00Z")
        gate = self.tmp / "gate-accept"
        proc = self.hteam_bg("accept", "T-002", "--round", "1",
                             env={"HTEAM_TEST_PAUSE_AT": "accept_before_final", "HTEAM_TEST_PAUSE_FILE": str(gate)})
        reached = Path(str(gate) + ".reached")
        deadline = time.monotonic() + 30
        while not reached.exists():
            self.assertIsNone(proc.poll())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.opened("T-001", 2, "2026-11-06T10:05:00Z")
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"], out.get("because")), (3, "approval_stale", ["T-001"]), out)
        self.assertEqual(self.task_state("T-002")["status"], "awaiting_user")

    def test_accept_refuses_result_adopted_after_predecessor_refix(self):
        # 같은 라운드 복구가 T-001 r3 을 보고 만든 옛 Dispatch 를 이어 붙였다. 그 결과를 최신 선행을 본 것으로 승인하지 않는다
        code, out = self.restart_after_predecessor_refix("after_launch")
        self.assertEqual((code, out.get("mode")), (0, "adopt"), out)
        self.move("T-002", "awaiting_user")
        code, out = self.hteam("accept", "T-002", "--round", "1")
        self.assertEqual((code, out["error"]["code"], out.get("because")), (3, "approval_stale", ["T-001"]), out)
        self.assertEqual(self.task_state("T-002")["status"], "awaiting_user")


class ApprovalFollowupTest(DecisionCase):
    """Task 4 리뷰 뒤: 앞선 사용자 요청 잇기, accept·fix 의 결정 차단과 라운드 우선, 리뷰 지적 유지, 기록 검사."""

    def work(self, tid):
        rnd = self.task_state(tid)["round"]
        return (self.state_dir / f"tasks/{tid}/r{rnd}-work.md").read_text(encoding="utf-8")

    def held(self, fix):
        """T-001 의 묶음(out-0001) 결정을 기록만 하고 멈췄다(적용 전)."""
        code, _ = self.decide("out-0001", fix, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)

    def test_dependent_refix_keeps_an_earlier_request_in_reverse_order(self):
        # 둘째 묶음의 답(T-003 글꼴)을 먼저 처리하고 첫 묶음의 답(T-001 버튼)이 뒤에 왔다. T-003 은 의존 태스크로 다시
        # 고쳐지지만 아직 띄우지 않은 앞 사용자 요청(글꼴)을 잃지 않는다
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        self.task("T-003", "awaiting_user", depends="T-001")
        self.assertEqual(self.review()[1].get("id"), "out-0002")
        self.assertEqual(self.decide("out-0002", {"T-003": "글꼴을 바꾼다"})[0], 0)
        self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.assertEqual(self.rounds("T-003"), [("T-003", "launch_failed", 3)])
        work = self.work("T-003")
        self.assertIn("글꼴을 바꾼다", work)
        self.assertIn("선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", work)

    def test_dependent_of_two_predecessors_in_different_batches_keeps_both_requests(self):
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        self.task("T-002", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0002")
        self.task("T-003", "awaiting_user", depends="T-001, T-002")  # 아직 묻지 않았다
        self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.assertEqual(self.decide("out-0002", {"T-002": "글꼴을 바꾼다"})[0], 0)
        self.assertEqual(self.rounds("T-003"), [("T-003", "launch_failed", 3)])
        work = self.work("T-003")
        self.assertIn("선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", work)
        self.assertIn("선행 T-002 의 사용자 요청을 반영한다: 글꼴을 바꾼다", work)

    def test_request_already_carried_is_not_written_twice(self):
        earlier = "버튼을 크게 / 이전 요청도 그대로 반영한다: 선행 T-001 의 사용자 요청을 반영한다: 색을 바꾼다"
        merged = approval._merge(["버튼을 크게"], earlier, ["선행 T-001 의 사용자 요청을 반영한다: 색을 바꾼다",
                                                         "선행 T-002 의 사용자 요청을 반영한다: 글꼴"])
        self.assertEqual(merged, f"이전 요청도 그대로 반영한다: {earlier} / 선행 T-002 의 사용자 요청을 반영한다: 글꼴")
        self.assertEqual(approval._merge(["글꼴"], None, ["선행 T-001 의 사용자 요청을 반영한다: 버튼"]),
                         "글꼴 / 선행 T-001 의 사용자 요청을 반영한다: 버튼")

    def test_replay_passes_an_accept_item_a_separate_fix_moved_on(self):
        # 결정(모두 승인)을 기록한 뒤 적용 전에 따로 한 fix 가 T-001 을 r2 로 옮겼다. 다시 하면 그 항목은 한 것으로 넘기고
        # 결정을 끝낸다(bad_state 로 멈춰 다른 묶음을 decision_pending 으로 막지 않는다)
        self.task("T-001", "awaiting_user")
        self.review()
        self.held({})
        code, out = self.hteam("fix", "T-001", "--note=따로 고친다")
        self.assertEqual((code, self.task_state("T-001")["round"]), (0, 2), out)
        code, out = self.decide("out-0001")
        self.assertEqual((code, out.get("passed"), out.get("accepted")), (0, ["T-001"], []), out)
        self.assertIsNotNone(self.record()["batches"][0]["decision"]["done"])

    def test_accept_round_mismatch_changes_nothing(self):
        self.task("T-001", "awaiting_user")
        code, out = self.hteam("accept", "T-001", "--round", "2")
        self.assertEqual((code, out["error"]["code"], out.get("round")), (3, "round_changed", 1), out)
        self.assertEqual(self.rounds("T-001"), [("T-001", "awaiting_user", 1)])

    def test_dependent_in_changes_keeps_the_review_findings(self):
        from hteam.paths import review_rel
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "changes", depends="T-001")
        with state.edit(self.p, "T-002") as st:
            st["rounds"][-1]["verdict"] = "REQUEST_CHANGES"
        prior = review_rel("T-002", 1)
        self.commit(prior, "# 리뷰\nREQUEST_CHANGES: 여백이 틀렸다\n", "[T-002] review r1: REQUEST_CHANGES")
        self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        work = self.work("T-002")
        self.assertIn(f"`{prior}` 의 지적을 모두 다룬다", work)
        self.assertIn("사용자 요청: 선행 T-001 의 사용자 요청을 반영한다: 버튼을 크게", work)
        self.assertNotIn("이전 리뷰는 승인이었다", work)

    def test_dependents_reviewing_or_approved_are_rebuilt(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "reviewing", depends="T-001")
        self.task("T-003", "approved", depends="T-001")
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual((code, [f["task"] for f in out["fixed"]]), (0, ["T-001", "T-002", "T-003"]), out)
        self.assertEqual(self.rounds("T-002", "T-003"), [("T-002", "launch_failed", 2), ("T-003", "launch_failed", 2)])

    def test_accept_of_a_held_target_is_refused(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.held({"T-001": "버튼을 크게"})
        code, out = self.hteam("accept", "T-001")
        self.assertEqual((code, out["error"]["code"], out.get("pending")), (3, "decision_pending", "out-0001"), out)
        self.assertEqual(self.rounds("T-001"), [("T-001", "awaiting_user", 1)])
        code, out = self.decide("out-0001")  # 사용자 수정 요청이 그대로 적용된다
        self.assertEqual((code, out.get("fixed")), (0, [{"task": "T-001", "round": 2}]), out)

    def test_plain_fix_of_a_held_task_is_refused_before_cancel(self):
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "working", depends="T-001")
        self.held({"T-001": "버튼을 크게"})
        code, out = self.hteam("fix", "T-002", "--note=따로 고친다")
        self.assertEqual((code, out["error"]["code"], out.get("pending")), (3, "decision_pending", "out-0001"), out)
        self.assertFalse(self.task_state("T-002")["rounds"][-1]["work"].get("canceled"))  # 라운드를 닫지 않았다
        self.assertEqual(self.rounds("T-002"), [("T-002", "working", 1)])

    def test_canceled_decision_item_points_at_decide(self):
        # 결정의 fix 가 취소를 저장한 뒤 멈췄다. status 는 닫는 중 안내가 아니라 결정을 마저 하라고 한다
        self.task("T-001", "awaiting_user")
        self.review()
        self.task("T-002", "working", depends="T-001")
        self.held({"T-001": "버튼을 크게"})
        with state.edit(self.p, "T-002") as st:
            st["rounds"][-1]["work"]["canceled"] = True
        task = {t["id"]: t for t in self.hteam("status")[1]["tasks"]}["T-002"]
        self.assertEqual(task["next"], [H, "design-review", "--decide", "out-0001"])

    def test_decision_with_bad_skipped_is_a_bad_record(self):
        self.task("T-001", "awaiting_user")
        self.review()
        data = self.record()
        data["batches"][0]["decision"] = {"at": "2026-11-06T10:00:00Z", "input": {}, "fix": [], "accept": [],
                                          "skipped": [{"task": "T-001"}], "done": None}  # why 가 없다
        path = self.state_dir / "design-review.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        code, out = self.decide("out-0001")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_supplement_fix_from_awaiting_user_is_not_a_user_request(self):
        self.task("T-001", "awaiting_user")
        self.task("T-009", "done", role="director")  # --supplement 는 끝난 디렉터 보강 태스크만 받는다
        code, out = self.hteam("fix", "T-001", "--supplement", "T-009", "--note=보강을 반영한다")
        self.assertEqual(code, 0, out)
        self.assertNotIn("from_user", self.task_state("T-001")["rounds"][-1])
        work = self.work("T-001")
        self.assertIn("코디네이터 메모: 보강을 반영한다", work)
        self.assertNotIn("사용자가 일괄 승인에서 수정을 요청했다", work)

    def test_status_hint_for_a_stale_approval_task(self):
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.opened("T-001", 1, "2026-11-06T09:00:00Z")
        self.opened("T-002", 1, "2026-11-06T10:00:00Z")
        self.opened("T-001", 2, "2026-11-06T10:05:00Z")  # 선행이 결정 밖에서 다시 고쳐졌다
        task = {t["id"]: t for t in self.hteam("status")[1]["tasks"]}["T-002"]
        self.assertIsNone(task["next"])
        self.assertIn("선행 T-001 가 이 라운드를 연 뒤에 결정 밖에서 고쳐졌다", task["hint"])

    def test_changes_dependent_refixed_twice_keeps_the_review_findings(self):
        # T-002(changes, r1 REQUEST_CHANGES)가 서로 다른 묶음의 T-001·T-005 에 의존한다. 두 결정이 차례로 고쳐 r2 는
        # 띄우지 않은 채 r3 이 된다. r3 도 r1 리뷰의 지적을 가리킨다
        from hteam.paths import review_rel
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        self.task("T-005", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0002")
        self.task("T-002", "changes", depends="T-001, T-005")
        with state.edit(self.p, "T-002") as st:
            st["rounds"][-1]["verdict"] = "REQUEST_CHANGES"
        prior = review_rel("T-002", 1)
        self.commit(prior, "# 리뷰\nREQUEST_CHANGES: 여백이 틀렸다\n", "[T-002] review r1: REQUEST_CHANGES")
        self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.assertEqual(self.decide("out-0002", {"T-005": "글꼴을 바꾼다"})[0], 0)
        self.assertEqual(self.rounds("T-002"), [("T-002", "launch_failed", 3)])
        rd = self.task_state("T-002")["rounds"][-1]
        self.assertEqual((rd.get("prior_verdict"), rd.get("prior_review_round")), ("REQUEST_CHANGES", 1))
        work = self.work("T-002")
        self.assertIn(f"`{prior}` 의 지적을 모두 다룬다", work)
        self.assertIn("버튼을 크게", work)
        self.assertIn("글꼴을 바꾼다", work)
        self.assertNotIn("이전 리뷰는 승인이었다", work)

    def test_plain_fix_after_a_failed_user_round_keeps_the_request(self):
        # 결정이 연 사용자 요청 라운드(r2)의 워커가 done 없이 끝났다(working). next 대로 일반 fix 를 해도 요청을 잃지 않는다
        self.task("T-001", "awaiting_user")
        self.review()
        self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.move("T-001", "working")
        code, out = self.hteam("fix", "T-001", "--note=이전 워커가 done 없이 끝남")
        self.assertEqual((code, self.task_state("T-001")["round"]), (0, 3), out)
        self.assertTrue(self.task_state("T-001")["rounds"][-1].get("from_user"))  # 다음 결정·fix 도 이 요청을 잇는다
        rd = self.task_state("T-001")["rounds"][-1]
        # 코디네이터 메모는 사용자 요청과 섞지 않고 따로 적는다(워커가 메모를 사용자 요구로 읽지 않게)
        self.assertEqual((rd["note"], rd["coord_note"]), ("버튼을 크게", "이전 워커가 done 없이 끝남"))
        work = self.work("T-001")
        self.assertIn("사용자 요청: 버튼을 크게\n", work)
        self.assertIn("코디네이터 메모: 이전 워커가 done 없이 끝남\n", work)
        self.assertNotIn("사용자 요청: 이전 워커", work)


DIRECTOR_CONFIG = APPROVAL + """
[roles.director]
title = "디자인 디렉터"
owns = ["docs/design/**", "assets/**"]
"""


class SupplementTest(DecisionCase):
    """디렉터 보강(설계 11.4 첫 항목): 시스템 추가 제안이 있으면 묻기 전에 보강한다."""

    config = DIRECTOR_CONFIG

    def work(self, tid):
        rnd = self.task_state(tid)["round"]
        return (self.state_dir / f"tasks/{tid}/r{rnd}-work.md").read_text(encoding="utf-8")

    def report(self, tid, text):
        self.commit(f"docs/tasks/{tid}/report.md", text, f"[{tid}] 보고서")

    def hints(self):
        return {t["id"]: t for t in self.hteam("status")[1]["tasks"]}

    def test_proposals_hold_the_batch_until_the_supplement_round(self):
        self.task("T-001", "awaiting_user", title="목록 화면")
        self.task("T-002", "awaiting_user", title="통계 화면")
        self.report("T-001", "## r1\n- 아티팩트: 없음\n\n### 시스템 추가 제안\n- 진한 강조색 단계(목록 배지): 대비가 모자라다\n\n"
                             "### 금지 목록 점검\n- 1–10 지켰다\n")
        self.report("T-002", "## r1\n### 시스템 추가 제안\n없음\n")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "supplement_needed"), out)
        self.assertEqual(out["proposals"], [{"task": "T-001", "round": 1,
                                             "proposal": "- 진한 강조색 단계(목록 배지): 대비가 모자라다"}])
        self.assertEqual((out["directors"], self.outbox_items()), ([], []))  # 묻지 않았다
        for tid in ("T-001", "T-002"):
            task = self.hints()[tid]
            self.assertIsNone(task["next"])
            self.assertIn("디렉터 보강 태스크를 만들고", task["hint"])
        self.task("T-005", "working", role="director")  # 보강 태스크가 도는 중이다
        self.assertEqual(self.review()[1]["directors"], [{"task": "T-005", "status": "working"}])
        self.assertIn("보강 중인 director 태스크 T-005(working)", self.hints()["T-001"]["hint"])
        code, out = self.hteam("fix", "T-001", "--supplement", "T-005", "--note=진한 강조색을 쓴다")
        self.assertEqual((code, out["error"]["code"]), (3, "supplement_not_done"), out)
        self.move("T-005", "done")
        code, out = self.hteam("fix", "T-001", "--supplement", "T-005", "--note=진한 강조색을 쓴다")
        self.assertEqual((code, out["round"]), (0, 2), out)
        work = self.work("T-001")
        for needle in ("디렉터 보강 태스크 T-005 의 결과(`docs/tasks/T-005/report.md`, `docs/design/system/`)를 반영한다",
                       "코디네이터 메모: 진한 강조색을 쓴다"):
            self.assertIn(needle, work)
        self.move("T-001", "awaiting_user")  # 보강 라운드가 리뷰를 거쳐 다시 승인됐다
        self.report("T-001", "## r1\n### 시스템 추가 제안\n- 진한 강조색\n\n## r2\n### 시스템 추가 제안\n- 더 진한 단계도\n")
        code, out = self.review()  # 보강 라운드는 제안을 다시 보지 않는다
        self.assertEqual(code, 0, out)
        self.assertEqual(out["tasks"], [{"task": "T-001", "round": 2}, {"task": "T-002", "round": 1}])

    def test_unfinished_supplement_round_keeps_its_supplement(self):
        # 보강 라운드가 리뷰 수정 요청(또는 작업 실패)으로 끝난 뒤의 일반 fix 도 보강을 잇는다: 보강 참조가 남고, 다시
        # 승인된 뒤 그 라운드의 제안을 다시 보강 대상으로 보지 않는다
        self.task("T-001", "awaiting_user")
        self.task("T-005", "done", role="director")
        self.report("T-001", "## r1\n### 시스템 추가 제안\n- 진한 강조색\n")
        code, out = self.hteam("fix", "T-001", "--supplement", "T-005", "--note=진한 강조색을 쓴다")
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.move("T-001", "changes")
        code, out = self.hteam("fix", "T-001", "--note=리뷰 지적: 배지 대비")
        self.assertEqual((code, out["round"]), (0, 3), out)
        self.assertEqual(self.task_state("T-001")["rounds"][-1]["supplement"], "T-005")
        self.assertIn("디렉터 보강 태스크 T-005 의 결과", self.work("T-001"))
        self.move("T-001", "awaiting_user")
        self.report("T-001", "## r1\n### 시스템 추가 제안\n- 진한 강조색\n\n## r3\n### 시스템 추가 제안\n- 더 진한 단계\n")
        code, out = self.review()
        self.assertEqual(code, 0, out)
        self.assertEqual(out["tasks"], [{"task": "T-001", "round": 3}])
        code, out = self.hteam("fix", "T-001", "--note=사용자와 다시 본다")  # awaiting_user 뒤의 새 수정은 잇지 않는다
        self.assertEqual((code, out["round"]), (0, 4), out)
        self.assertIsNone(self.task_state("T-001")["rounds"][-1]["supplement"])

    def test_supplement_must_be_a_director_task(self):
        self.task("T-001", "awaiting_user")
        self.task("T-003", "done")  # designer
        code, out = self.hteam("fix", "T-001", "--supplement", "T-003")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_supplement"), out)
        self.assertEqual(self.task_state("T-001")["round"], 1)

    def test_proposals_read_the_current_round_section(self):
        cases = [("## r1\n### 시스템 추가 제안\n- 없음\n", None),
                 ("## r1\n- 시스템 추가 제안: 배지 색 하나\n", "배지 색 하나"),  # 2단계 형식의 줄
                 ("## r1\n- 시스템 추가 제안: 없음\n", None),
                 ("## r10\n### 시스템 추가 제안\n- 다른 라운드\n", None),
                 ("## r1\n### 시스템 추가 제안\n- 간격 20px\n### 금지 목록 점검\n- 지켰다\n## r2\n### 시스템 추가 제안\n- r2\n",
                  "- 간격 20px"),
                 ("## r2\n### 시스템 추가 제안\n- r2 것\n", None)]
        path = self.proj / "docs/tasks/T-001/report.md"
        path.parent.mkdir(parents=True)
        for text, want in cases:
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                self.assertEqual(approval.proposals(self.p, {"id": "T-001", "round": 1}), want)
        self.assertIsNone(approval.proposals(self.p, {"id": "T-404", "round": 1}))  # 보고서가 없다


class ApprovalCloseTest(DecisionCase):
    """2단계 마감 리뷰: 띄운 적 없는 queued 라운드와 dropped 선행, 답이 온 질문의 안내, 답 없는 결정, skipped 겹침."""

    def statuses(self):
        return {t["id"]: t for t in self.hteam("status")[1]["tasks"]}

    def queued_pair(self):
        """T-002 → T-001(둘 다 designer). 결정이 T-001 을 고쳐 두 태스크가 띄운 적 없는 queued r2 가 된다."""
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.assertEqual(self.rounds("T-001", "T-002"), [("T-001", "launch_failed", 2), ("T-002", "launch_failed", 2)])

    def test_queued_round_behind_a_dropped_predecessor_does_not_block(self):
        # 최종 리뷰 I1: 선행을 버리면 queued T-002 는 영영 시작하지 못한다. 그것이 다른 승인 태스크를 막으면 안 된다
        self.queued_pair()
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 0)
        self.task("T-003", "awaiting_user")  # 독립 designer
        code, out = self.review()
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-003", "round": 1}]), out)
        task = self.statuses()["T-002"]
        self.assertIsNone(task["next"])  # start-ready 가 띄우지 않으므로 권하지 않는다
        for needle in ("선행 T-001 가 dropped 다", f"{H} drop T-002", "depends_on"):
            self.assertIn(needle, task["hint"])
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out.get("started")), (0, []), out)
        [w] = [w for w in out["waiting"] if w["task"] == "T-002"]
        self.assertEqual((w["reason"], w["detail"], w.get("dropped")), ("deps", "T-001(dropped)", ["T-001"]), w)
        self.assertIn(f"{H} drop T-002", w["hint"])

    def test_pending_task_behind_a_dropped_predecessor_says_so(self):
        self.task("T-001", "working", role="developer")
        self.task("T-002", "pending", role="developer", depends="T-001")
        self.task("T-004", "done", role="developer")
        self.task("T-003", "pending", role="developer", depends="T-004, T-001")
        self.assertEqual(self.statuses()["T-002"]["next"], [H, "start-ready"])  # 선행이 아직 일한다
        code, out = self.hteam("start-ready")
        [w] = [w for w in out["waiting"] if w["task"] == "T-003"]
        self.assertEqual((w["detail"], w.get("dropped"), w.get("hint")), ("T-001(working)", None, None), w)  # 끝난 T-004 는 빼고
        self.move("T-001", "dropped")
        task = self.statuses()["T-002"]
        self.assertIsNone(task["next"])
        self.assertIn("선행 T-001 가 dropped 다", task["hint"])
        code, out = self.hteam("start-ready")
        [w] = [w for w in out["waiting"] if w["task"] == "T-003"]
        self.assertEqual((w["detail"], w.get("dropped")), ("T-001(dropped)", ["T-001"]), w)

    def test_unreadable_answer_file_is_not_read_as_no_answer(self):
        # 답 파일이 있는데 손상됐다. 답이 왔으므로 "답을 기다린다"·no_answer 는 틀린 안내다
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        (self.state_dir / "answers").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "answers" / "out-0001.json").write_text("{broken", encoding="utf-8")
        code, out = self.decide("out-0001", {}, answer=False)
        self.assertEqual((code, out["error"]["code"]), (1, "bad_side_file"), out)
        self.assertIn(".herdr-team/state/answers/out-0001.json", out["error"]["hint"])
        self.assertNotIn("decision", self.record()["batches"][0])
        task = self.statuses()["T-001"]
        self.assertIsNone(task["next"])
        self.assertIn("`.herdr-team/state/answers/out-0001.json`", task["hint"])
        self.assertIn("읽지 못했다", task["hint"])

    def test_task_behind_an_indirect_dropped_predecessor_says_so(self):
        # T-003 → T-002(pending) → T-001(dropped): T-002 가 영영 시작하지 못하므로 T-003 도 그렇다
        self.task("T-001", "working", role="developer")
        self.task("T-002", "pending", role="developer", depends="T-001")
        self.task("T-003", "pending", role="developer", depends="T-002")
        # 이미 띄운 선행(T-005)은 제 선행을 기다리지 않는다. 그 너머의 dropped 는 T-006 을 막지 않는다
        self.task("T-004", "working", role="developer")
        self.task("T-005", "working", role="developer", depends="T-004")
        self.task("T-006", "pending", role="developer", depends="T-005")
        self.move("T-001", "dropped")
        self.move("T-004", "dropped")
        tasks = self.statuses()
        self.assertIsNone(tasks["T-003"]["next"])
        for needle in ("선행 T-001", "T-002", f"{H} drop T-003", "`.herdr-team/tasks/T-002.md`"):
            self.assertIn(needle, tasks["T-003"]["hint"])
        self.assertEqual((tasks["T-006"]["next"], tasks["T-006"]["hint"]), ([H, "start-ready"], None))
        code, out = self.hteam("start-ready")
        [w] = [w for w in out["waiting"] if w["task"] == "T-003"]
        self.assertEqual((w["detail"], w.get("dropped")), ("T-002(pending)", ["T-001"]), w)
        self.assertIn(f"{H} drop T-003", w["hint"])
        [w] = [w for w in out["waiting"] if w["task"] == "T-006"]
        self.assertEqual((w["detail"], w.get("dropped"), w.get("hint")), ("T-005(working)", None, None), w)

    def test_queued_round_behind_a_predecessor_in_revision_leaves_the_blocker_on_the_predecessor(self):
        self.queued_pair()
        self.task("T-003", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        # T-001 r2 는 지금 시작할 수 있다. T-002 는 T-001 을 기다리므로 막지 않는다(pending 과 같다)
        self.assertEqual(out["blockers"], [{"task": "T-001", "status": "launch_failed", "why": "지금 시작할 수 있다"}])
        self.assertEqual(self.statuses()["T-002"]["next"], [H, "start-ready"])
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"], out)
        [w] = [w for w in out["waiting"] if w["task"] == "T-002"]
        self.assertEqual((w["reason"], w["detail"]), ("deps", "T-001(working)"), w)
        code, out = self.review()
        self.assertEqual((code, out["blockers"]), (3, [{"task": "T-001", "status": "working", "why": "진행 중"}]), out)

    def test_launched_queued_round_still_blocks(self):
        # 한 번이라도 띄운(horch Task 가 있는) launch_failed 는 진행 중이다
        self.queued_pair()
        with state.edit(self.p, "T-002") as st:
            st["rounds"][-1]["work"]["horch_task"] = "tsk-x"
        self.task("T-003", "awaiting_user")
        code, out = self.review()
        self.assertEqual((code, [b["task"] for b in out["blockers"]]), (3, ["T-001", "T-002"]), out)

    def test_awaiting_hint_says_the_answer_is_in(self):
        # 최종 리뷰 M1: --decide 가 아무것도 기록하지 못한 채 답 메시지를 ack 했다. 답이 와 있다고 알린다
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[1].get("id"), "out-0001")
        hint = self.statuses()["T-001"]["hint"]
        self.assertIn("out-0001 의 사용자 답을 기다린다", hint)
        self.answered("out-0001", "수정 요청")
        task = self.statuses()["T-001"]
        self.assertIsNone(task["next"])  # 답 해석은 코디네이터가 한다
        self.assertIn("out-0001 의 답이 와 있다", task["hint"])
        self.assertIn("design-review --decide out-0001 --json -", task["hint"])

    def test_awaiting_hint_without_approval_role(self):
        # 최종 리뷰 M2: 승인 직무가 아니면 일괄 승인 기록을 탓하지 않는다
        self.task("T-001", "awaiting_user")
        cfg = self.team / "config.toml"
        cfg.write_text(cfg.read_text().replace('user_approval_roles = ["designer"]', "user_approval_roles = []"))
        task = self.statuses()["T-001"]
        self.assertIsNone(task["next"])
        self.assertIn(f"{H} accept T-001", task["hint"])
        self.assertNotIn("일괄 승인 기록을 읽지 못했다", task["hint"])
        cfg.write_text("[broken")  # 설정을 읽지 못하면 config_error 를 가리킨다
        code, out = self.hteam("status")
        self.assertTrue(out["config_error"], out)
        task = {t["id"]: t for t in out["tasks"]}["T-001"]
        self.assertIn("config_error", task["hint"])

    def test_decision_needs_the_answer(self):
        # 최종 리뷰 M3: 답이 오기 전의 결정은 사용자의 실제 답을 버린다
        self.task("T-001", "awaiting_user")
        self.review()
        code, out = self.decide("out-0001", {}, answer=False)
        self.assertEqual((code, out["error"]["code"]), (3, "no_answer"), out)
        self.assertIn("답이 온 뒤", out["error"]["hint"])
        self.assertNotIn("decision", self.record()["batches"][0])
        self.assertEqual(self.task_state("T-001")["status"], "awaiting_user")
        self.assertFalse((self.state_dir / "applied.json").exists())
        code, _ = self.decide("out-0001", {"T-001": "x"}, env={"HTEAM_TEST_DIE_AT": "decision_recorded"})
        self.assertEqual(code, 137)
        (self.state_dir / "answers" / "out-0001.json").unlink()  # 기록한 결정의 재실행은 답을 보지 않는다
        code, out = self.decide("out-0001")
        self.assertEqual((code, out["replayed"]), (0, True), out)

    def test_skipped_does_not_repeat_a_fixed_task(self):
        # 최종 리뷰 M4: T-002 는 다른 결정이 이미 고친 묶음 태스크이고 이번 지목 태스크 T-001 의 의존이다
        self.task("T-001", "awaiting_user")
        self.task("T-002", "awaiting_user", depends="T-001")
        self.review()  # out-0001: T-001, T-002
        self.task("T-005", "awaiting_user")
        self.review()  # out-0002: T-005
        with state.edit(self.p, "T-002") as st:  # 다른 결정(또는 fix)이 T-002 를 이미 r2 로 고쳤다
            st["round"] = 2
            st["rounds"].append({**st["rounds"][-1], "round": 2})
            state.move(st, "launch_failed", "test")
        code, out = self.decide("out-0001", {"T-001": "버튼을 크게"})
        self.assertEqual(code, 0, out)
        d = out["decision"]
        self.assertEqual([e["task"] for e in d["fix"]], ["T-001", "T-002"])
        self.assertNotIn("T-002", [s["task"] for s in d["skipped"]])


class ApprovalFlowTest(DecisionCase):
    """실제 워커로: accept → awaiting_user → design-review → 메인 답 → wait 주석 → 결정 → start-ready(설계 11.4)."""

    def setUp(self):
        super().setUp()
        self.env.update({"HTEAM_WAIT_CHUNK": "0.3", "HTEAM_NO_STATUS_GRACE": "60"})

    def decide(self, oid, fix=None, answer=False, **kw):
        """흐름 테스트는 실제 `hteam answer` 가 답 파일을 남긴다. helper 가 대신 두지 않는다(그 경로의 회귀를 숨긴다)."""
        return super().decide(oid, fix, answer=answer, **kw)

    def start_design(self, tid, screen, depends=None):
        self.write_spec(tid, "designer", title=f"{screen} 화면", owns=f"docs/design/screens/{screen}/**",
                        depends=depends)
        state.create(self.p, tid, "designer")
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)

    def finish_design(self, tid, screen):
        """현재 라운드의 작업 → Codex 리뷰 APPROVE → accept(awaiting_user)."""
        rnd = self.task_state(tid)["round"]
        report = f"## r{rnd}\n- 아티팩트: https://claude.ai/artifact/{screen}-r{rnd}\n"
        code, out = self.act_work(tid, {f"docs/design/screens/{screen}/index.html": f"<p>{screen} r{rnd}</p>\n"},
                                  report=report)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.hteam("review", tid)[1].get("status"), "reviewing")
        self.act_review(tid, "APPROVE")
        self.assertEqual(self.hteam("review-finish", tid)[1].get("status"), "approved")
        code, out = self.hteam("accept", tid)
        self.assertEqual((code, out["status"], out.get("next")), (0, "awaiting_user", [H, "design-review"]), out)

    def statuses(self):
        code, out = self.hteam("status")
        self.assertEqual(code, 0, out)
        return {t["id"]: t for t in out["tasks"]}

    def wait_mains(self):
        """메인 답이 올 때까지 wait 하고 묶음마다 ack 한다. 메인 답이 든 묶음의 메인 메시지 hteam 주석들을 돌려준다."""
        for _ in range(10):
            code, out = self.hteam("wait", "--timeout", "5")
            self.assertEqual(code, 0, out)
            if out.get("delivery") is not None:
                self.assertEqual(self.hteam("wait", "--ack", str(out["delivery"]), "--timeout", "0")[0], 0)
            found = [m["hteam"] for m in out["messages"] if m["hteam"].get("kind") == "main"]
            if found:
                return found
        self.fail("메인 답이 오지 않았다")

    def test_approve_all_then_dependent_development_starts(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.write_spec("T-002", "developer", owns="src/**", depends="T-001")
        state.create(self.p, "T-002", "developer")
        self.assertEqual(self.statuses()["T-001"]["next"], [H, "design-review"])
        code, out = self.hteam("start-ready")
        self.assertEqual((code, out.get("started")), (0, []), out)  # T-002 는 T-001 이 done 이 되기를 기다린다
        code, out = self.hteam("design-review")
        self.assertEqual((code, out.get("id")), (0, "out-0001"), out)
        task = self.statuses()["T-001"]
        self.assertIsNone(task["next"])
        self.assertIn("out-0001", task["hint"])
        self.assertIn("https://claude.ai/artifact/login-r1", self.outbox_items()[0]["render"]["context"])
        self.assertEqual(self.hteam("answer", "out-0001", "모두 승인 (추천)", as_="main")[0], 0)
        [info] = self.wait_mains()
        self.assertEqual((info["reply_to"], info["duplicate"]), ("out-0001", False))
        self.assertEqual(info["design_review"], {"batch": "dr-0001", "approve_all": True, "decision": None,
                                                 "applied": False, "unknown": [], "tasks": [{"task": "T-001", "round": 1,
                                                                           "status": "awaiting_user", "round_now": 1,
                                                                           "pending": True}]})
        self.assertIn("--decide out-0001", info["hint"])
        code, out = self.decide("out-0001", {})
        self.assertEqual((code, out["accepted"], self.task_state("T-001")["status"]), (0, ["T-001"], "done"), out)
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out.get("started", [])], ["T-002"], out)

    def test_same_answer_twice_in_one_delivery_is_handled_once(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.assertEqual(self.hteam("design-review")[0], 0)
        for _ in range(2):  # 메인이 답을 다시 보냈다(보내기가 끊긴 줄 알았다)
            self.assertEqual(self.hteam("answer", "out-0001", "수정 요청: 버튼을 크게", as_="main")[0], 0)
        first, second = self.wait_mains()
        self.assertEqual((first["duplicate"], second["duplicate"]), (False, True))
        self.assertIn("design_review", first)
        self.assertNotIn("design_review", second)
        for _ in range(2):  # 두 번 처리해도 라운드는 하나만 열린다
            self.assertEqual(self.decide("out-0001", {"T-001": "버튼을 크게"})[0], 0)
        self.assertEqual(self.rounds("T-001"), [("T-001", "launch_failed", 2)])
        code, out = self.hteam("fix", "T-001", "--round", "1", "--note=버튼을 크게")
        self.assertEqual((code, out["error"]["code"], out.get("round")), (3, "round_changed", 2), out)

    def test_dependent_fix_waits_for_predecessor_and_keeps_both_requests(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        self.start_design("T-002", "list", depends="T-001")
        self.assertIn("T-002", self.statuses()["T-001"]["hint"])  # 진행 중인 승인 태스크가 끝나면 함께 묻는다
        code, out = self.hteam("design-review")
        self.assertEqual((code, out["error"]["code"]), (3, "approval_not_ready"), out)
        self.finish_design("T-002", "list")
        code, out = self.hteam("design-review")
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 1}, {"task": "T-002", "round": 1}]),
                         out)
        self.assertEqual(self.hteam("answer", "out-0001", "수정 요청: T-001 버튼, T-002 글꼴", as_="main")[0], 0)
        [info] = self.wait_mains()
        self.assertFalse(info["design_review"]["approve_all"])
        code, out = self.decide("out-0001", {"T-001": "버튼을 더 크게", "T-002": "글꼴을 바꾼다"})
        self.assertEqual((code, [f["task"] for f in out["fixed"]]), (0, ["T-001", "T-002"]), out)
        self.assertTrue(self.task_state("T-001")["rounds"][1]["from_user"])
        first = (self.state_dir / "tasks/T-001/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("사용자가 일괄 승인에서 수정을 요청했다", first)
        self.assertIn("사용자 요청: 버튼을 더 크게", first)
        self.assertNotIn("의 지적을 모두 다룬다", first)
        second = (self.state_dir / "tasks/T-002/r2-work.md").read_text(encoding="utf-8")
        self.assertIn("글꼴을 바꾼다", second)
        self.assertIn("선행 T-001 의 사용자 요청을 반영한다: 버튼을 더 크게", second)
        code, out = self.hteam("start-ready")  # 선행의 수정 라운드가 다시 승인되기 전에는 의존 태스크를 띄우지 않는다
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"], out)
        self.assertIn({"task": "T-002", "reason": "deps", "detail": "T-001(working)"}, out["waiting"])  # 남은 선행과 상태
        self.assertEqual(self.task_state("T-002")["status"], "launch_failed")
        self.finish_design("T-001", "login")
        self.assertEqual(self.task_state("T-001")["status"], "awaiting_user")  # 이제 의존이 풀렸다
        code, out = self.hteam("start-ready")
        self.assertEqual([s["task"] for s in out["started"]], ["T-002"], out)
        self.finish_design("T-002", "list")
        code, out = self.hteam("design-review")  # 다시 승인된 r2 둘을 함께 묻는다
        self.assertEqual((code, out.get("tasks")), (0, [{"task": "T-001", "round": 2}, {"task": "T-002", "round": 2}]),
                         out)

    def test_unreadable_record_is_a_warning_not_a_crash(self):
        self.start_design("T-001", "login")
        self.finish_design("T-001", "login")
        (self.state_dir / "design-review.json").write_text("{broken", encoding="utf-8")
        code, out = self.hteam("status")
        self.assertEqual(code, 0, out)
        self.assertTrue(any("design-review.json" in w for w in out.get("warnings", [])), out)
        task = {t["id"]: t for t in out["tasks"]}["T-001"]
        self.assertIsNone(task["next"])

    def test_unreadable_record_hint_does_not_say_applied(self):
        self.task("T-001", "awaiting_user")
        self.assertEqual(self.review()[0], 0)
        self.assertEqual(self.hteam("answer", "out-0001", "모두 승인 (추천)", as_="main")[0], 0)
        (self.state_dir / "design-review.json").write_text("{broken", encoding="utf-8")
        [info] = self.wait_mains()
        self.assertIn("warning", info)
        self.assertNotIn(f"{H} applied", info["hint"])  # 일괄 승인 답인지 모르면 손으로 applied 하라고 하지 않는다


class ApprovalDocsTest(unittest.TestCase):
    def test_coordinator_and_main_docs(self):
        coord = (ROOT / "templates" / "coordinator.md").read_text(encoding="utf-8")
        for needle in ("`hteam design-review`", "exit 3 `approval_not_ready`", "`already_asked`", "## 일괄 승인 답",
                       "`hteam design-review --decide out-NNNN --json -`", '{"fix": {"T-xxx": "<사용자 요청 원문>"}}',
                       "`decision_pending`", "`decision_conflict`", "`approval_stale`", "`queued`",
                       "같은 `reply_to` 가 둘 이상이면",
                       "- designer:"):
            self.assertIn(needle, coord)
        main = (ROOT / "templates" / "CLAUDE.section.md").read_text(encoding="utf-8")
        self.assertIn("`수정 요청: <태스크 ID 와 고칠 내용>`", main)
        self.assertIn("디자인 `docs/design/`", main)

    def test_design_review_answer_is_applied_by_decide(self):
        coord = (ROOT / "templates" / "coordinator.md").read_text(encoding="utf-8")
        self.assertIn("일괄 승인 답은 `hteam design-review --decide` 가 applied 를 적는다. 그 답에는 `hteam applied` 를 하지 "
                      "않는다", coord)

    def test_supplement_flow_in_coordinator_doc(self):
        coord = (ROOT / "templates" / "coordinator.md").read_text(encoding="utf-8")
        for needle in ("## 디자인 시스템 보강", "exit 3 `supplement_needed`", "--role director", "--supplement <보강 태스크>",
                       "`plan_key: ui-foundation`", "토큰 갱신", "`directors`"):
            self.assertIn(needle, coord)
        # 보강된 토큰이 화면 구현보다 먼저 들어간다: UI 기반이 시작 전이면 보강에 의존하게, 시작했으면 토큰 갱신 태스크를
        # 만들어 화면 구현 태스크가 그것에 의존하게 한다(시작한 화면 구현이 있으면 멈춘다)
        sup = coord[coord.index("## 디자인 시스템 보강"):coord.index("## 요청 처리")]
        for needle in ("`pending`(아직 시작하지 않았다): 그 사양의 `depends_on` 에 보강 태스크를 더한다",
                       "--depends-on <보강 태스크>,<UI 기반 태스크>",
                       "UI 기반 태스크에 의존하는(사양 `depends_on` 에 그 ID 가 있는) 태스크마다 사양 `depends_on` 에 토큰 갱신 태스크를 더한다",
                       "(토큰 갱신 태스크 자신은 빼고)",
                       "시작한 것이 있으면 사양을 고치지 않고 멈춰 메인에 알린다", "`dropped`: 메인에 알린다",
                       "아직 시작하지 않는다(3 을 먼저 한다)", "(보강 ID 를 잇는다)"):
            self.assertIn(needle, sup)
        self.assertNotIn("아직 `done` 이 아니면", sup)

    def test_fix_and_accept_are_held_by_an_unfinished_decision(self):
        coord = (ROOT / "templates" / "coordinator.md").read_text(encoding="utf-8")
        self.assertIn("결정 밖의 `fix`·`accept` 도 exit 3 `decision_pending` 으로 거부한다", coord)


if __name__ == "__main__":
    unittest.main()
