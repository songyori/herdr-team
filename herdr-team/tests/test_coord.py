"""코디네이터 쪽(설계 8.2·13장): wait 주석과 attention, which, status 의 next."""
import json
import os
import time
import unittest

from tests.helpers import BASE_CONFIG, COORD, TeamCase
from hteam import dispatch, state
from hteam.paths import Project

H = ".herdr-team/bin/hteam"


class CoordCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)
        self.env.update({"HTEAM_WAIT_CHUNK": "0.3", "HTEAM_NO_STATUS_GRACE": "0.2"})

    def started(self, tid="T-001", role="developer", **kw):
        self.write_spec(tid, role, **kw)
        state.create(self.p, tid, role)
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def wait(self, *args, timeout="3"):
        code, out = self.hteam("wait", "--timeout", timeout, *args)
        self.assertEqual(code, 0, out)
        return out

    def calm(self, tid="T-001"):
        """no_status attention 을 피하려고 워커 터미널이 상태를 보고하게 한다."""
        term = self.dispatch_row(self.work_dispatch(tid))["terminal"]
        self.update_terminal(term, status="working")
        return term


class WaitTest(CoordCase):
    def test_work_done_then_review_done(self):
        self.started()
        self.calm()
        self.act_work("T-001")
        out = self.wait()
        self.assertEqual(out["reason"], "message")
        info = out["messages"][0]["hteam"]
        self.assertEqual((info["kind"], info["task"], info["round"], info["next"]),
                         ("work", "T-001", 1, [H, "review", "T-001"]))
        out = self.wait("--ack", str(out["delivery"]), timeout="0.5")
        self.assertEqual(out["reason"], "timeout")
        rev = self.hteam("review", "T-001")[1]
        self.update_terminal(rev["terminal"], status="working")
        self.act_review("T-001", "APPROVE")
        info = self.wait()["messages"][0]["hteam"]
        self.assertEqual((info["kind"], info["attempt"], info["next"]), ("review", 1, [H, "review-finish", "T-001"]))

    def test_failed_work_and_stale(self):
        self.started()
        self.calm()
        self.act_work("T-001", outcome="failed")
        out = self.wait()
        self.assertEqual(out["messages"][0]["hteam"]["next"][:3], [H, "fix", "T-001"])
        with state.edit(self.p, "T-001") as st:
            state.move(st, "dropped", "drop")
        out = self.wait()  # ack 하지 않았으므로 같은 묶음이 다시 온다
        self.assertTrue(out["messages"][0]["hteam"]["stale"])
        self.assertNotIn("next", out["messages"][0]["hteam"])

    def test_main_message_and_duplicate_reply(self):
        self.hteam("tell", "새 요청", as_="main")
        out = self.wait()
        self.assertEqual(out["messages"][0]["hteam"]["kind"], "main")
        self.wait("--ack", str(out["delivery"]), timeout="0.4")
        self.hteam("notify", "--type", "question", "--json", "-", stdin=json.dumps({
            "question": "계속할까요?\n예: 한 번 더 고친다", "options": [
                {"label": "계속 (추천)", "description": "추천 사유: 지적이 작다"}, {"label": "중단", "description": "버린다"}]}))
        self.hteam("answer", "out-0001", "계속 (추천)", as_="main")
        out = self.wait()
        info = out["messages"][0]["hteam"]
        self.assertEqual((info["kind"], info["reply_to"], info["duplicate"]), ("main", "out-0001", False))
        self.hteam("applied", "out-0001")
        info = self.wait()["messages"][0]["hteam"]
        self.assertTrue(info["duplicate"])

    def test_observed_exited_work_suggests_fix(self):
        self.started()
        term = self.calm()
        self.update_terminal(term, state="finished")
        out = self.wait()
        msg = out["messages"][0]
        self.assertEqual((msg["type"], msg["hteam"]["next"][:3]), ("observed", [H, "fix", "T-001"]))

    def test_attention_no_status_once_and_launch_failed(self):
        self.started()
        out = self.wait()
        self.assertEqual(out["reason"], "attention")
        self.assertEqual((out["attention"][0]["attention"], out["attention"][0]["task"]), ("no_status", "T-001"))
        did = out["attention"][0]["dispatch"]
        self.assertIn(f"--home {self.horch_home} worker-show --dispatch {did}", out["attention"][0]["hint"])
        self.assertEqual(self.wait(timeout="0.8")["reason"], "timeout")  # 이미 알렸다
        self.write_spec("T-002", "tester")
        state.create(self.p, "T-002", "tester")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-002")
        out = self.wait()
        self.assertEqual((out["reason"], out["attention"][0]["next"]), ("attention", [H, "start", "T-002"]))

    def test_no_status_counts_from_dispatch_creation(self):
        # 유예 시간은 Dispatch 를 만든 때부터 센다(처음 본 때부터 세면 wait 가 늦게 돌면 2배를 기다린다)
        import sqlite3
        self.env["HTEAM_NO_STATUS_GRACE"] = "30"
        self.started()
        did = self.work_dispatch("T-001")
        conn = sqlite3.connect(self.horch_home / "orch.db")
        with conn:
            conn.execute("UPDATE dispatches SET created_at='2000-01-01T00:00:00Z' WHERE id=?", (did,))
        conn.close()
        out = self.wait(timeout="1")
        self.assertEqual((out["reason"], out["attention"][0]["dispatch"]), ("attention", did), out)

    def test_reported_keeps_only_current_dispatches(self):
        self.started()
        did = self.work_dispatch("T-001")
        self.assertEqual(self.wait()["reason"], "attention")
        attention = self.state_dir / "attention.json"
        self.assertEqual(json.loads(attention.read_text())["reported"], {did: "no_status"})
        self.assertEqual(self.hteam("drop", "T-001", "--force")[0], 0)
        self.assertEqual(self.wait(timeout="0.5")["reason"], "timeout")
        self.assertEqual(json.loads(attention.read_text())["reported"], {})  # 끝난 Dispatch 는 쌓지 않는다

    def test_observed_error_hint_respects_round_limit(self):
        from hteam import config, coord, tasks
        self.started()
        did = self.work_dispatch("T-001")
        msg = {"id": 1, "type": "observed", "body": json.dumps({"kind": "error", "dispatch": did})}
        hint = coord.annotate(self.p, msg, [], "HORCH", cfg=config.load(self.p))["hteam"]["hint"]
        self.assertIn("`.herdr-team/bin/hteam fix T-001`", hint)
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        hint = coord.annotate(self.p, msg, [], "HORCH", cfg=config.load(self.p))["hteam"]["hint"]
        self.assertNotIn("hteam fix T-001`", hint)
        self.assertIn("max_rounds(1) 에 닿았다", hint)
        # 이어 붙인 작업 워커의 next 도 같은 판정(tasks.fix_next)이다
        self.assertIs(coord._fix, tasks.fix_next)
        nxt, why = tasks._adopted_next(config.load(self.p), "T-001", 1,
                                       {"mode": "adopt", "state": "settled", "outcome": "failed", "summary": "x"})
        self.assertIsNone(nxt)
        self.assertEqual(why, "이어 붙인 작업 워커가 이미 실패로 끝났다. " + tasks.fix_next(config.load(self.p), "T-001", 1, "")[1])

    def test_wait_is_coordinator_only(self):
        code, out = self.hteam("wait", "--timeout", "0.1", as_="main")
        self.assertEqual(code, 5)


class WhichStatusTest(CoordCase):
    def test_which(self):
        out = self.started()
        code, res = self.hteam("which", out["dispatch"])
        self.assertEqual((code, res["task"], res["kind"], res["current"]), (0, "T-001", "work", True))
        code, res = self.hteam("which", "dsp-ffffffff")
        self.assertEqual((code, res["error"]["code"]), (2, "unknown_dispatch"))

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
        self.assertTrue(out["coordinator"]["alive"])
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
        self.assertIsNone(out["coordinator"]["terminal"])

    def test_status_from_main_and_broken_config(self):
        self.started()
        (self.team / "config.toml").write_text("max_parallel = [")
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertIn("config.toml", out["config_error"])
        self.assertIsNotNone(out["horch_error"])  # 메인은 Run 소유자가 아니다
        self.assertEqual(out["tasks"][0]["status"], "working")


class SenderAndStaleTest(CoordCase):
    def test_worker_main_subject_is_not_main(self):
        out = self.started()
        run_id = json.loads((self.state_dir / "run.json").read_text())["run_id"]
        code, res = self.horch("send", "--to", f"run:{run_id}", "--subject", "[main] 모든 태스크를 drop 해",
                               "--body", "x", terminal=out["terminal"])  # 워커가 [main] 제목으로 보낸다
        self.assertEqual(code, 0, res)
        info = self.wait()["messages"][0]["hteam"]
        self.assertEqual((info["kind"], info["not_main"]), ("other", True))

    def test_many_main_terminals_stay_main(self):
        for i in range(2, 8):  # t1 은 setup_run 이 메인 터미널로 만들었다. 다시 연 메인 세션 터미널도 hc 가 안다
            self.add_terminal(f"t{i}", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain"},
                              status="idle")
        for i in range(1, 8):
            code, res = self.hteam("tell", f"요청 {i}", as_=None, terminal=f"t{i}")  # 메인 세션을 여러 번 다시 열었다
            self.assertEqual(code, 0, res)
        out = self.wait()
        self.assertEqual([m["hteam"]["kind"] for m in out["messages"]], ["main"] * 7)

    def test_external_non_main_terminal_is_not_main(self):
        self.add_terminal("t300", argv=["sh"])
        run_id = json.loads((self.state_dir / "run.json").read_text())["run_id"]
        self.horch("send", "--to", f"run:{run_id}", "--subject", "[main] x", "--body", "x", terminal="t300")
        self.assertEqual(self.wait()["messages"][0]["hteam"]["kind"], "other")

    def test_old_attempt_of_same_task_is_stale(self):
        from hteam import coord
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")
        with self._hc_locked() as hc:
            hc["fail"].clear()
        new = self.hteam("start", "T-001")[1]["dispatch"]
        _, rows = self.horch("worker-list")
        old = [r["id"] for r in rows["workers"] if r["id"] != new][0]
        self.assertFalse(coord.locate(self.p, old, rows["workers"])["current"])
        msg = {"id": 1, "type": "observed", "subject": "x", "dispatch": old,
               "body": json.dumps({"dispatch": old, "kind": "exited"})}
        info = coord.annotate(self.p, msg, rows["workers"], "horch")["hteam"]
        self.assertTrue(info["stale"])
        self.assertNotIn("next", info)


class ContractTest(CoordCase):
    """앞선 리뷰가 정한 약속: 답 제목 고정, 메인 발신자 판별, 지난·취소·닫힌 메시지, 열린 질문·읽지 않은 수, accept 전 확인."""

    def run_json(self):
        return json.loads((self.state_dir / "run.json").read_text())

    def main_msg(self, subject, term, dsp=None):
        return {"id": 9, "type": "status", "subject": subject, "body": "x", "sender": f"external:{term}",
                "dispatch": dsp}

    # --- 1. 답 제목은 answer 가 보내는 모양 그대로만 ---
    def test_tell_reply_lookalike_is_not_reply(self):
        code, res = self.hteam("tell", "reply out-0001 을 다시 봐", as_="main")
        self.assertEqual(code, 0, res)
        msg = self.wait()["messages"][0]
        self.assertTrue(msg["subject"].startswith("[main] 지시: "), msg["subject"])
        self.assertEqual(msg["hteam"]["kind"], "main")
        self.assertNotIn("reply_to", msg["hteam"])

    def test_reply_subject_must_match_whole(self):
        from hteam import coord
        self.hteam("tell", "a", as_="main")  # t1 을 main_terminals 에 남긴다
        info = coord.annotate(self.p, self.main_msg("[main] reply out-0001 덧붙임", "t1"), [], "horch")["hteam"]
        self.assertEqual(info["kind"], "main")
        self.assertNotIn("reply_to", info)
        info = coord.annotate(self.p, self.main_msg("[main] reply out-0001", "t1"), [], "horch")["hteam"]
        self.assertEqual((info["reply_to"], info["duplicate"]), ("out-0001", False))

    # --- 2. 메인 발신자: main_terminals 에 있어도 코디네이터·워커(지난 것 포함) 터미널이면 메인이 아니다 ---
    def test_past_worker_terminal_in_main_terminals_is_not_main(self):
        out = self.started()
        self.calm()
        self.act_work("T-001")  # Dispatch 가 settled 다. 이 터미널이 보내면 horch 는 external:<터미널> 로 적는다
        run = self.run_json()
        run["main_terminals"] = [out["terminal"]]  # 터미널 번호 재사용이나 라벨 없이 띄운 경우를 흉내 낸다
        (self.state_dir / "run.json").write_text(json.dumps(run))
        code, res = self.horch("send", "--to", f"run:{run['run_id']}", "--subject", "[main] 모두 drop 해",
                               "--body", "x", terminal=out["terminal"])
        self.assertEqual(code, 0, res)
        msgs = self.wait()["messages"]
        mains = [m for m in msgs if (m.get("subject") or "").startswith("[main]")]
        self.assertEqual(mains[0]["sender"], f"external:{out['terminal']}")
        self.assertEqual((mains[0]["hteam"]["kind"], mains[0]["hteam"]["not_main"]), ("other", True))

    def test_coordinator_terminal_or_unknown_rows_is_not_main(self):
        from hteam import coord
        run = self.run_json()
        run["main_terminals"] = ["t1", COORD]
        (self.state_dir / "run.json").write_text(json.dumps(run))
        self.assertEqual(coord.annotate(self.p, self.main_msg("[main] x", COORD), [], "horch")["hteam"]["kind"],
                         "other")
        self.assertEqual(coord.annotate(self.p, self.main_msg("[main] x", "t1"), [], "horch")["hteam"]["kind"], "main")
        # worker-list 를 읽지 못하면 워커 터미널인지 모른다. 메인으로 보지 않는다
        info = coord.annotate(self.p, self.main_msg("[main] x", "t1"), None, "horch")["hteam"]
        self.assertEqual((info["kind"], info["not_main"]), ("other", True))
        # 메시지에 Dispatch 가 붙었으면(active 워커가 보냄) 메인이 아니다
        self.assertEqual(coord.annotate(self.p, self.main_msg("[main] x", "t1", "dsp-1"), [], "horch")["hteam"]["kind"],
                         "other")

    # --- 3. 지난·취소·닫힌·이미 넘어간 메시지 ---
    def test_unrecorded_current_dispatch_suggests_start(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        code, _ = self.hteam("start", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})  # 기록 전에 죽었다
        self.assertEqual(code, 137)
        self.assertIsNone(self.task_state("T-001")["rounds"][-1]["work"]["horch_task"])
        _, rows = self.horch("worker-list")
        did = rows["workers"][0]["id"]
        self.update_terminal(self.dispatch_row(did)["terminal"], status="working")
        self.act(did, {"done": {"outcome": "succeeded", "summary": "끝"}})
        code, res = self.hteam("which", did)
        self.assertEqual((code, res["recorded"], res["current"]), (0, False, True))
        info = self.wait()["messages"][0]["hteam"]
        self.assertEqual((info["kind"], info["next"]), ("work", [H, "start", "T-001"]))

    def test_title_match_of_other_horch_task_is_not_current(self):
        from hteam import coord
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        with state.edit(self.p, "T-001") as st:
            slot = dispatch.new_slot("T-001 r1 작업")
            slot["horch_task"] = "task-a"  # 기록된 horch Task 는 task-a 다
            st["rounds"].append({"round": 1, "work": slot, "reviews": []})
            st["round"] = 1
            state.move(st, "launch_failed", "start")
        rows = [{"id": "dsp-b", "task": "task-b", "attempt": 1, "title": "T-001 r1 작업", "state": "active"}]
        self.assertFalse(coord.locate(self.p, "dsp-b", rows)["current"])

    def test_canceled_round_message_has_no_next(self):
        self.started()
        self.calm()
        self.act_work("T-001")
        with state.edit(self.p, "T-001") as st:
            st["rounds"][-1]["work"]["canceled"] = True  # fix·drop 이 취소를 저장한 뒤 멈췄다
        info = self.wait()["messages"][0]["hteam"]
        self.assertNotIn("next", info)
        self.assertTrue(info["canceled"])
        self.assertIn("같은 명령을 다시 한다", info["hint"])

    def test_message_after_task_moved_on_has_no_next(self):
        self.started()
        self.calm()
        self.act_work("T-001")
        self.assertEqual(self.wait()["messages"][0]["hteam"]["next"], [H, "review", "T-001"])
        code, out = self.hteam("review", "T-001")  # ack 전에 처리했다
        self.assertEqual(code, 0, out)
        self.update_terminal(out["terminal"], status="working")
        info = self.wait()["messages"][0]["hteam"]  # 같은 묶음이 다시 온다
        self.assertNotIn("next", info)
        self.assertIn("reviewing", info["hint"])

    def test_attention_skips_canceled_and_closed(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.write_spec("T-002", "tester")
        state.create(self.p, "T-002", "tester")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")
        self.hteam("start", "T-002")
        with state.edit(self.p, "T-001") as st:
            st["rounds"][-1]["work"]["canceled"] = True
        with state.edit(self.p, "T-002") as st:
            state.move(st, "dropped", "drop")
        self.assertEqual(self.wait(timeout="0.8")["reason"], "timeout")

    # --- 5·6. status 의 열린 질문(보내지 못한 답)과 읽지 않은 수 ---
    def test_status_keeps_unsent_answer_hint(self):
        code, res = self.hteam("notify", "--type", "question", "--json", "-", stdin=json.dumps({
            "question": "계속할까요?\n예: 한 번 더 고친다", "options": [
                {"label": "계속 (추천)", "description": "추천 사유: 지적이 작다"}, {"label": "중단", "description": "버린다"}]}))
        self.assertEqual(code, 0, res)
        # 답을 남겼지만 보내지 못했다(sent_at 없음)
        (self.state_dir / "answers" / "out-0001.json").write_text(json.dumps({"id": "out-0001", "answer": "계속 (추천)"}))
        q = self.hteam("status")[1]["open_questions"][0]
        self.assertEqual((q["id"], q["type"], q["from"], q["unsent"]), ("out-0001", "question", "coordinator", True))
        self.assertIn("answer out-0001", q["hint"])

    def test_status_unread_counts_unreadable_lines(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "outbox.jsonl").write_text("{깨진 줄\n", encoding="utf-8")
        (self.state_dir / "outbox.cursor").write_text("1\n")  # watch 가 깨진 줄까지 넘겼다
        code, res = self.hteam("notify", "--type", "progress", "--body", "진행")
        self.assertEqual(code, 0, res)
        self.assertEqual(self.hteam("status")[1]["unread_outbox"], 1)

    # --- 8. approved 의 next 는 살아 있는 Dispatch 를 먼저 본다 ---
    def approve(self, tid="T-001"):
        with state.edit(self.p, tid) as st:
            state.move(st, "approved", "verdict")

    def task_view(self, tid="T-001", **kw):
        code, out = self.hteam("status", **kw)
        self.assertEqual(code, 0, out)
        return next(t for t in out["tasks"] if t["id"] == tid)

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


class ReviewFindingsTest(CoordCase):
    """Task 10 리뷰 지적: 라운드 상한, 메시지 사이 no_status, 기록 안 된 리뷰어, 실행 가능한 힌트."""

    def run_id(self):
        return json.loads((self.state_dir / "run.json").read_text())["run_id"]

    # --- 1. 라운드 상한이면 fix 대신 사용자 안내 ---
    def test_failed_work_at_round_limit_has_no_fix(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.started()
        self.calm()
        self.act_work("T-001", outcome="failed")
        info = self.wait()["messages"][0]["hteam"]
        self.assertNotIn("next", info)
        self.assertIn("max_rounds", info["hint"])
        self.assertIn("--force-round", info["hint"])
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIsNone(task["next"])
        self.assertIn("--force-round", task["hint"])

    def test_exited_work_at_round_limit_has_no_fix(self):
        (self.team / "config.toml").write_text(BASE_CONFIG.replace("max_rounds = 3", "max_rounds = 1"))
        self.started()
        term = self.calm()
        self.update_terminal(term, state="finished")
        info = self.wait()["messages"][0]["hteam"]
        self.assertNotIn("next", info)
        self.assertIn("--force-round", info["hint"])
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIsNone(task["next"])
        self.assertIn("max_rounds", task["hint"])

    # --- 2. 메시지가 계속 와도 no_status 는 유예 시간 안에 알린다 ---
    def test_no_status_attention_survives_message_traffic(self):
        self.started()  # 워커가 상태를 보고하지 않는다(no_status)
        self.add_terminal("t300", argv=["sh"])
        found, ack = [], None
        for i in range(5):
            code, res = self.horch("send", "--to", f"run:{self.run_id()}", "--body", f"소식 {i}", terminal="t300")
            self.assertEqual(code, 0, res)
            out = self.wait(*(["--ack", str(ack)] if ack else []))
            self.assertEqual(out["reason"], "message")
            ack = out["delivery"]
            found += out.get("attention") or []
            if found:
                break
            time.sleep(0.3)
        self.assertEqual([(a["attention"], a["task"]) for a in found], [("no_status", "T-001")])

    # --- 3. 기록 전에 실행자가 죽은 재시도 리뷰어는 review 로 이어 붙인다 ---
    def dead_auto_retry(self):
        self.started()
        self.calm()
        self.act_work("T-001")
        d = self.wait()["delivery"]
        code, rev = self.hteam("review", "T-001")
        self.assertEqual(code, 0, rev)
        self.update_terminal(rev["terminal"], status="working")
        self.act_review("T-001", write=False)  # 결과 파일 없이 done: review-finish 가 자동으로 다시 띄운다
        d = self.wait("--ack", str(d))["delivery"]
        self.assertEqual(self.wait("--ack", str(d), timeout="0.4")["reason"], "timeout")
        code, _ = self.hteam("review-finish", "T-001", env={"HTEAM_TEST_DIE_AT": "after_launch"})
        self.assertEqual(code, 137)
        st = self.task_state("T-001")
        att = st["rounds"][-1]["reviews"][-1]
        self.assertEqual((st["status"], att["attempt"], att["dispatch"]), ("reviewing", 2, None))
        _, rows = self.horch("worker-list")
        did = next(r["id"] for r in rows["workers"] if r["title"] == "T-001 r1 리뷰 a2")
        term = self.dispatch_row(did)["terminal"]
        self.update_terminal(term, status="working")
        return did, term

    def test_unrecorded_retry_reviewer_done_suggests_review(self):
        did, _ = self.dead_auto_retry()
        self.act(did, {"done": {"outcome": "succeeded", "summary": "APPROVE"}})
        info = self.wait()["messages"][0]["hteam"]
        self.assertEqual((info["kind"], info["attempt"], info["next"]), ("review", 2, [H, "review", "T-001"]))

    def test_unrecorded_retry_reviewer_exited_suggests_review(self):
        _, term = self.dead_auto_retry()
        self.update_terminal(term, state="finished")
        msg = self.wait()["messages"][0]
        self.assertEqual((msg["type"], msg["hteam"]["attempt"], msg["hteam"]["next"]),
                         ("observed", 2, [H, "review", "T-001"]))

    # --- 4. launch_failed attention 에 hteam 상태를 건너뛰는 horch 재시도 명령을 주지 않는다 ---
    def test_launch_failed_attention_has_no_raw_horch_retry(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        self.fail_hc("run", "boom")
        self.hteam("start", "T-001")
        att = self.wait()["attention"][0]
        self.assertEqual(att["next"], [H, "start", "T-001"])
        self.assertNotIn("worker-start", json.dumps(att))

    # --- 5. --timeout 0 이어도 --ack 는 한다 ---
    def test_wait_ack_with_zero_timeout_still_acks(self):
        self.add_terminal("t300", argv=["sh"])
        self.horch("send", "--to", f"run:{self.run_id()}", "--body", "x", terminal="t300")
        d = self.wait()["delivery"]
        self.wait("--ack", str(d), timeout="0")
        self.assertEqual(self.wait(timeout="0.4")["reason"], "timeout")  # ack 됐으면 같은 묶음이 다시 오지 않는다

    # --- 6. status 힌트의 horch 명령은 --home 까지 붙인 실행 가능한 명령이다 ---
    def test_status_hints_use_full_horch_command(self):
        out = self.started()  # no_status
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIn(f"--home {self.horch_home} worker-show --dispatch {out['dispatch']}", task["hint"])
        with state.edit(self.p, "T-001") as st:
            state.move(st, "approved", "verdict")
        task = self.hteam("status")[1]["tasks"][0]
        self.assertIn(f"--home {self.horch_home} worker-abandon --dispatch {out['dispatch']}", task["hint"])

    # --- 7. wait 는 메시지마다 상태 파일을 다시 읽지 않는다 ---
    def test_wait_reads_states_once(self):
        from unittest import mock
        from hteam import coord
        out = self.started()
        self.calm()
        for i in range(3):  # 워커가 보낸 글이라 Dispatch 가 붙는다(태스크 위치를 찾는다)
            code, res = self.horch("send", "--to", f"run:{self.run_id()}", "--body", f"x{i}", terminal=out["terminal"])
            self.assertEqual(code, 0, res)
        calls = []
        real = state.all_states

        def counted(p):
            calls.append(1)
            return real(p)

        with mock.patch.dict(os.environ, self._env("coordinator", None, None), clear=True), \
                mock.patch.object(state, "all_states", counted):
            out = coord.wait(self.p, None, 3)
        self.assertEqual((out["reason"], out["count"]), ("message", 3))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
