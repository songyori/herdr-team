"""0.5.0 의 idle 넘기기·relay_failed·relay-status(설계 16.7·16.8). 세션 기록과 Stop 기록은 시험이 홈 아래에 바로 쓴다."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from tests.helpers import HorchCase
from horch import liveness
from horch.store import Store

CREATED = "2026-11-17T00:00:00Z"  # 시험 Dispatch 의 created_at
AFTER = "2026-11-17T00:00:10Z"  # 그 뒤의 Stop
BG = [{"type": "shell", "status": "running", "description": "전체 시험"}]
DONE = [{"type": "shell", "status": "completed"}, {"type": "shell", "status": "failed"},
        {"type": "subagent", "status": "killed"}]  # 끝난 백그라운드 일


class RelayFiles:
    """홈 아래 대리 보고 파일을 쓰는 도우미(HorchCase 와 함께 쓴다. 터미널 기본 t9)."""

    def session(self, terminal="t9", **fields):
        rec = {"terminal": terminal, "pid": 4242, "tty": None, "started_ms": 1, "decided": "on", "pending": "idle",
               "last": "working", "at": None, "blockers": {}, "perm_tools": {}, "write_failures": 0, **fields}
        (self.home / "relay").mkdir(mode=0o700, exist_ok=True)
        (self.home / "relay" / f"{terminal}.json").write_text(json.dumps(rec), encoding="utf-8")

    def stop(self, turn, background=(), at=AFTER, terminal="t9"):
        path = self.home / "relay" / f"{terminal}.stops.json"
        path.parent.mkdir(mode=0o700, exist_ok=True)
        items = json.loads(path.read_text(encoding="utf-8"))["stops"] if path.exists() else []
        items.append({"pid": 4242, "turn": turn, "at": at, "background": list(background)})
        path.write_text(json.dumps({"stops": items}), encoding="utf-8")

    def created(self, did, stamp=CREATED):
        db = self.db()
        db.execute("UPDATE dispatches SET created_at=? WHERE id=?", (stamp, did))
        db.commit()


class ObserveRelayTest(RelayFiles, HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id, status="working")
        self.created(self.did)
        patcher = mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store = Store(self.home)
        self.addCleanup(self.store.close)

    def observe(self, did=None):
        liveness.observe_one(self.store, self.run_id, did or self.did)

    def kinds(self):
        rows = self.store.all("SELECT body FROM messages WHERE type='observed' ORDER BY id")
        return [(json.loads(r["body"])["kind"], json.loads(r["body"])["key"]) for r in rows]

    def waits(self):
        return [r["key"] for r in self.store.all("SELECT key FROM observations WHERE kind='idle_wait' ORDER BY key")]

    def test_background_turn_gives_no_idle_until_an_empty_record(self):
        self.stop(3, BG)
        self.update_terminal("t9", status="idle", turn=3)
        self.observe()
        self.observe()
        self.assertEqual(self.kinds(), [])
        self.assertEqual(self.store.all("SELECT * FROM observations"), [])  # 넘긴 turn 은 observations 에 넣지 않는다
        self.stop(3, [], at="2026-11-17T00:01:00Z")  # 같은 turn 의 마지막 기록이 빈 목록이 됐다(백그라운드 뒤 시스템 턴)
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])

    def test_finished_background_does_not_hold_and_mixed_does(self):
        """끝난 백그라운드 일(completed·failed·killed 등)만 남은 기록은 idle 을 붙잡지 않는다. 끝나지 않은 일이 섞이면
        붙잡는다(최종 리뷰 I1)."""
        self.stop(3, DONE + [{"type": "monitor", "status": "Running"}])
        self.update_terminal("t9", status="idle", turn=3)
        self.observe()
        self.assertEqual(self.kinds(), [])
        self.stop(3, DONE, at="2026-11-17T00:01:00Z")  # 남은 일이 모두 끝났다
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])

    def test_records_of_other_turns_or_before_the_dispatch_do_not_hold(self):
        self.stop(2, BG)
        self.stop(3, BG, at="2026-11-16T23:59:59Z")  # 앞 Dispatch 의 기록(고정 터미널)
        self.update_terminal("t9", status="done", turn=3)
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])  # 세션 기록이 없는 워커: 기다리지 않는다

    def test_waits_for_the_stop_record_of_a_relay_worker(self):
        self.session(decided="off")  # 스스로 보고하는 세션도 Stop 기록을 남긴다: Claude 의 보고가 Stop 훅보다 먼저 왔다
        self.update_terminal("t9", status="idle", turn=3)
        self.observe()
        self.assertEqual((self.kinds(), self.waits()), ([], ["3"]))
        self.stop(3, BG)  # 기다리는 사이 백그라운드가 든 기록이 왔다
        self.observe()
        self.assertEqual(self.kinds(), [])
        self.stop(3, [], at="2026-11-17T00:01:00Z")
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])

    def test_an_empty_record_after_waiting_gives_idle(self):
        self.session()
        self.update_terminal("t9", status="done", turn=5)
        self.observe()
        self.assertEqual((self.kinds(), self.waits()), ([], ["5"]))
        self.stop(5, [])
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "5")])

    def test_gives_up_after_the_grace(self):
        self.session()
        self.stop(None, BG)  # Stop 훅의 hc 가 실패했다: 어느 turn 에도 맞지 않는다
        self.update_terminal("t9", status="idle", turn=3)
        os.environ["HORCH_TEST_IDLE_RECORD_GRACE_S"] = "0"
        self.observe()
        self.assertEqual((self.kinds(), self.waits()), ([], ["3"]))  # 첫 판정은 늘 기다린다
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])

    def test_grace_is_ten_seconds(self):
        self.assertEqual((liveness.IDLE_RECORD_GRACE_S, liveness.idle_record_grace_s()), (10, 10.0))
        self.session()
        self.update_terminal("t9", status="idle", turn=3)
        self.observe()
        self.observe()
        self.assertEqual(self.kinds(), [])
        self.store.run("UPDATE observations SET created_at='2000-01-01T00:00:00Z' WHERE kind='idle_wait'")  # 오래전에 처음 봤다
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])

    def test_codex_and_workers_without_a_session_record_are_not_held(self):
        self.update_terminal("t9", status="idle", turn=3)
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3")])  # 0.5.0 전 Claude, 훅이 돌지 않은 세션
        db = self.db()
        db.execute("UPDATE dispatches SET agent='codex' WHERE id=?", (self.did,))
        db.commit()
        self.session()  # Codex 는 Claude 훅이 없어 Stop 기록이 생기지 않는다
        self.update_terminal("t9", status="idle", turn=4)
        self.observe()
        self.assertEqual(self.kinds(), [("idle", "3"), ("idle", "4")])

    def test_relay_failed_once_and_stale_words_are_held(self):
        self.session(decided="write_failed", last="working", write_failures=3)
        self.update_terminal("t9", status="done", turn=3)
        self.observe()
        self.observe()
        self.update_terminal("t9", status="blocked", turn=4)
        self.observe()
        self.assertEqual(self.kinds(), [("relay_failed", "4242")])
        self.assertEqual(self.waits(), [])
        body = json.loads(self.store.one("SELECT body FROM messages WHERE type='observed'")["body"])
        self.assertEqual(body, {"dispatch": self.did, "kind": "relay_failed", "key": "4242", "terminal": "t9",
                                "status": "done", "pid": 4242, "last": "working", "write_failures": 3})
        self.update_terminal("t9", state="finished")  # exited·lost 는 그대로 낸다
        self.observe()
        self.assertEqual(self.kinds(), [("relay_failed", "4242"), ("exited", "exited")])

    def test_relay_failed_again_for_the_next_dispatch_on_the_terminal(self):
        self.session(decided="write_failed")
        self.update_terminal("t9", status="working", turn=3)
        self.observe()
        db = self.db()
        db.execute("UPDATE dispatches SET state='settled' WHERE id=?", (self.did,))
        db.commit()
        nxt = self.add_dispatch(self.run_id, "dsp-00000002", terminal="t9", status="working")
        self.observe(nxt)
        self.observe(nxt)
        rows = self.store.all("SELECT dispatch_id, key FROM observations WHERE kind='relay_failed' ORDER BY dispatch_id")
        self.assertEqual([tuple(r) for r in rows], [(self.did, "4242"), (nxt, "4242")])

    def test_other_decisions_keep_the_current_events(self):
        for turn, decided in enumerate(("on", "off", "no_tty", None), 1):
            self.session(decided=decided)
            self.update_terminal("t9", status="blocked", turn=turn)
            self.observe()
        self.assertEqual(self.kinds(), [("blocked", "1"), ("blocked", "2"), ("blocked", "3"), ("blocked", "4")])


class AttentionRelayTest(RelayFiles, HorchCase):
    def setUp(self):
        super().setUp()
        self.run_id = self.make_owner("t100")
        self.update_terminal("t100", status="working")
        self.did = self.add_dispatch(self.run_id, status="working")
        self.created(self.did)

    def row(self):
        code, out = self.horch("worker-list", terminal="t100")
        self.assertEqual(code, 0, out)
        r = {w["id"]: w for w in out["workers"]}[self.did]
        return r["attention"], r["next"]

    def test_relay_failed_attention(self):
        self.session(decided="write_failed")
        for word in ("blocked", "idle", None, "working"):
            self.update_terminal("t9", status=word, turn=2)
            attention, nxt = self.row()
            self.assertEqual(attention, "relay_failed", word)
            self.assertEqual(nxt[-5:], ["worker-show", "--dispatch", self.did, "--lines", "40"])
        code, shown = self.horch("worker-show", "--dispatch", self.did, "--lines", "0", terminal="t100")
        self.assertEqual((code, shown["worker"]["attention"]), (0, "relay_failed"))
        self.update_terminal("t9", state="finished")  # exited·lost 가 먼저다
        self.assertEqual(self.row()[0], "exited_without_done")

    def test_other_decisions_keep_the_attention(self):
        for decided in ("on", "off", "no_tty"):
            self.session(decided=decided)
            self.update_terminal("t9", status="blocked", turn=2)
            self.assertEqual(self.row()[0], "blocked", decided)
            self.update_terminal("t9", status=None)
            self.assertEqual(self.row()[0], "no_status", decided)

    def test_idle_attention_is_hidden_while_background_work_runs(self):
        self.session()
        self.update_terminal("t9", status="idle", turn=2)
        self.assertEqual(self.row()[0], "idle")  # Stop 기록이 아직 없다: 목록은 기다리지 않는다
        self.stop(2, BG)
        self.assertEqual(self.row(), (None, None))
        self.stop(2, [], at="2026-11-17T00:01:00Z")
        self.assertEqual(self.row()[0], "idle")

    def test_finished_background_does_not_hide_idle(self):
        self.session()
        self.update_terminal("t9", status="idle", turn=2)
        self.stop(2, DONE + [{"type": "shell", "status": "pending"}])
        self.assertEqual(self.row(), (None, None))
        self.stop(2, DONE, at="2026-11-17T00:01:00Z")  # 끝난 일만 남았다(최종 리뷰 I1)
        self.assertEqual(self.row()[0], "idle")


class RelayStatusTest(RelayFiles, HorchCase):
    def test_record_null_and_usage_without_a_run(self):
        code, out = self.horch("relay-status", "--terminal", "t9")
        self.assertEqual((code, out), (0, {"ok": True, "terminal": "t9", "record": None}))
        self.assertFalse(self.home.exists())  # 읽기만 한다: 홈·DB 를 만들지 않는다(Run 이 없어도 된다)
        self.home.mkdir()
        self.session(decided="write_failed", write_failures=3, blockers={"tool:q1": "question"})
        code, out = self.horch("relay-status", "--terminal", "t9")
        self.assertEqual(code, 0, out)
        rec = out["record"]
        self.assertEqual((rec["terminal"], rec["pid"], rec["decided"], rec["write_failures"], rec["blockers"]),
                         ("t9", 4242, "write_failed", 3, {"tool:q1": "question"}))
        (self.home / "relay" / "t9.json").write_text("{깨짐", encoding="utf-8")
        self.assertEqual(self.horch("relay-status", "--terminal", "t9"), (0, {"ok": True, "terminal": "t9",
                                                                              "record": None}))
        for bad in ("t/9", "", "x" * 65, "t 9"):
            code, out = self.horch("relay-status", f"--terminal={bad}")
            self.assertEqual((code, out["error"]["code"]), (2, "usage"), bad)
        code, out = self.horch("relay-status")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"))


if __name__ == "__main__":
    unittest.main()
