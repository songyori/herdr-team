"""고정 터미널 닫기와 비우기(herdr-orch 설계 13.5 terminal-close, 13.8 terminal-reset)."""
import json
import subprocess
import time
import unittest

from tests.test_persist import PersistCase
from horch import procs

CLEAR = ["/", "c", "l", "e", "a", "r"]


class TerminalCloseTest(PersistCase):
    def state(self, did) -> str:
        return self.row(did)["state"]

    def test_close_idle_terminal(self):
        d1, term = self.first()
        code, out = self.o("terminal-close", "--terminal", term)
        self.assertEqual(code, 0, out)
        self.assertEqual((out["terminal"], out["closed"], out["abandoned"], out["released"]), (term, True, None, [d1]))
        self.assertNotIn(term, self.hc_state()["terminals"])
        names = [c[0] for c in self.hc_calls()]
        self.assertIn("kill", names)
        self.assertIn("rm", names)
        self.assertEqual(self.state(d1), "released")
        self.assertTrue(self.row(d1)["closed_at"])

    def test_running_dispatch_needs_abandon(self):
        _, term = self.first()
        _, out = self.put(term)
        d2 = out["dispatch"]
        calls = len(self.hc_calls())
        code, res = self.o("terminal-close", "--terminal", term)
        self.assertEqual((code, res["error"]["code"], res["dispatch"]), (3, "terminal_busy", d2))
        self.assertEqual([c for c in self.hc_calls()[calls:] if c[0] in ("kill", "rm")], [])
        self.assertEqual(self.state(d2), "active")
        code, res = self.o("terminal-close", "--terminal", term, "--abandon")
        self.assertEqual(code, 0, res)
        self.assertEqual((res["closed"], res["abandoned"]), (True, d2))
        self.assertIn(d2, res["released"])
        self.assertEqual(self.state(d2), "released")
        self.assertNotIn(term, self.hc_state()["terminals"])

    def test_not_found_cleans_records(self):
        d1, term = self.first()
        _, out = self.put(term)
        d2 = out["dispatch"]
        st = self.hc_state()
        del st["terminals"][term]
        self.set_hc_state(st)
        code, res = self.o("terminal-close", "--terminal", term)
        self.assertEqual(code, 0, res)
        self.assertEqual((res["closed"], res["reason"], res["abandoned"]), (False, "not_found", d2))
        self.assertEqual(sorted(res["released"]), sorted([d1, d2]))
        self.assertEqual((self.state(d1), self.state(d2)), ("released", "released"))

    def test_not_persistent_terminal(self):
        plain = self.start_worker(owner="t100")
        code, res = self.o("terminal-close", "--terminal", plain["terminal"])
        self.assertEqual((code, res["error"]["code"]), (3, "not_persistent_terminal"))
        self.assertEqual(self.hc_state()["terminals"][plain["terminal"]]["state"], "live")
        _, term = self.first()
        labels = dict(self.hc_state()["terminals"][term]["labels"], **{"horch.run": "run-other"})
        self.update_terminal(term, labels=labels)
        code, res = self.o("terminal-close", "--terminal", term)
        self.assertEqual((code, res["error"]["code"]), (3, "not_persistent_terminal"))

    def test_kill_failure_keeps_state_then_retry(self):
        _, term = self.first()
        _, out = self.put(term)
        d2 = out["dispatch"]
        self.fail_hc("kill", "timeout")
        code, res = self.o("terminal-close", "--terminal", term, "--abandon")
        self.assertEqual((code, res["error"]["code"]), (1, "hc_failed"))
        self.assertEqual(self.state(d2), "active")
        self.assertEqual(self.hc_state()["terminals"][term]["state"], "live")
        self.clear_hc_fail("kill")
        code, res = self.o("terminal-close", "--terminal", term, "--abandon")
        self.assertEqual((code, res["closed"], res["abandoned"]), (0, True, d2))
        self.assertEqual(self.state(d2), "released")

    def test_rm_failure_after_kill_retries(self):
        d1, term = self.first()
        self.fail_hc("rm", "timeout")
        code, res = self.o("terminal-close", "--terminal", term)
        self.assertEqual((code, res["error"]["code"]), (1, "hc_failed"))
        self.assertEqual(self.state(d1), "settled")
        self.clear_hc_fail("rm")
        code, res = self.o("terminal-close", "--terminal", term)  # 이미 끝난 터미널: kill 없이 rm 만
        self.assertEqual((code, res["closed"], res["released"]), (0, True, [d1]))

    def test_close_holds_reservation_against_put_and_reset(self):
        """닫기는 kill 전에 터미널 예약(종류 close)을 잡아 끝날 때까지 쥔다. 그동안 --terminal 넣기·terminal-reset 은
        terminal_busy 이고, 닫기가 끝나면 예약은 지워진다(Codex 커밋 리뷰 c6d82d2)."""
        d1, term = self.first()
        self.delay_hc("kill", 3.0)
        bg = self.horch_bg("terminal-close", "--terminal", term, terminal="t100")
        self.addCleanup(lambda: bg.poll() is None and bg.kill())
        deadline = time.monotonic() + 10
        while (row := self.db().execute("SELECT value FROM meta WHERE key=?", (f"reset:{term}",)).fetchone()) is None:
            self.assertLess(time.monotonic(), deadline, "닫기 예약이 생기지 않았다")
            time.sleep(0.05)
        self.assertTrue(row["value"].endswith("|close"), row["value"])
        dispatches = self.count("dispatches")
        code, res = self.put(term)
        self.assertEqual((code, res["error"]["code"], res["dispatch"]), (3, "terminal_busy", None), res)
        self.assertIn("terminal-close", res["error"]["message"])
        code, res = self.o("terminal-reset", "--terminal", term)
        self.assertEqual((code, res["error"]["code"]), (3, "terminal_busy"), res)
        self.assertEqual(self.count("dispatches"), dispatches)
        self.assertIsNone(bg.poll())  # 두 거부를 본 동안 닫기는 아직 kill 을 기다린다
        code, res = self.finish(bg)
        self.assertEqual((code, res["closed"], res["abandoned"], res["released"]), (0, True, None, [d1]), res)
        self.assertIsNone(self.db().execute("SELECT 1 FROM meta WHERE key=?", (f"reset:{term}",)).fetchone())

    def test_close_refused_while_other_reservation_lives(self):
        _, term = self.first()
        pid, started = procs.me()  # 이 시험 프로세스는 살아 있다(리셋 중인 것으로 본다)
        self.reserve(term, pid, started)
        calls = len(self.hc_calls())
        code, res = self.o("terminal-close", "--terminal", term, "--abandon")
        self.assertEqual((code, res["error"]["code"], res["dispatch"]), (3, "terminal_busy", None), res)
        self.assertIn("terminal-reset", res["error"]["message"])
        self.assertEqual([c for c in self.hc_calls()[calls:] if c[0] in ("kill", "rm")], [])
        self.assertEqual(self.hc_state()["terminals"][term]["state"], "live")
        self.assertIsNotNone(self.db().execute("SELECT 1 FROM meta WHERE key=?", (f"reset:{term}",)).fetchone())

    def test_hc_failure_and_owner(self):
        _, term = self.first()
        self.fail_hc("get", "timeout")
        code, res = self.o("terminal-close", "--terminal", term)
        self.assertEqual((code, res["error"]["code"]), (1, "hc_failed"))
        self.clear_hc_fail("get")
        code, res = self.horch("terminal-close", "--terminal", term, terminal=term)
        self.assertEqual(code, 5)


class TerminalResetTest(PersistCase):
    def keys_to(self, term) -> list[list[str]]:
        return [k["keys"] for k in self.hc_state().get("keys", []) if k["terminal"] == term]

    def reservation_row(self, term):
        return self.db().execute("SELECT value FROM meta WHERE key=?", (f"reset:{term}",)).fetchone()

    def test_claude_clear_waits_for_turn(self):
        _, term = self.first()
        code, out = self.o("terminal-reset", "--terminal", term)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.keys_to(term), [CLEAR + ["enter"]])
        self.assertEqual((out["terminal"], out["agent"], out["turn"], out["status"]), (term, "claude", 4, "idle"))
        self.assertIn(out["signal"], ("event", "poll"))
        self.assertIsInstance(out["seconds"], float)
        self.assertIn("title", out)
        self.assertEqual(out["warnings"], [])
        self.assertEqual(self.sent_to(term), [])  # 감싼 send 는 쓰지 않는다
        self.assertIsNone(self.reservation_row(term))
        self.assertEqual(self.hc_state()["terminals"][term]["state"], "live")  # 같은 터미널·주소

    def test_codex_name_keys_and_title(self):
        _, term = self.first(agent="codex")
        code, out = self.o("terminal-reset", "--terminal", term, "--name", "test-a1")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.keys_to(term), [CLEAR + ["space", "t", "e", "s", "t", "-", "a", "1", "enter"]])
        self.assertEqual(out["agent"], "codex")
        self.assertTrue(out["title"].startswith("test-a1 | "))

    def test_claude_ignores_name(self):
        _, term = self.first()
        code, out = self.o("terminal-reset", "--terminal", term, "--name", "prod")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["warnings"], ["name_ignored"])
        self.assertEqual(self.keys_to(term), [CLEAR + ["enter"]])

    def test_bad_name_is_usage(self):
        _, term = self.first(agent="codex")
        for name in ("Prod", "1st", "a b", "x" * 33):
            with self.subTest(name=name):
                code, out = self.o("terminal-reset", "--terminal", term, "--name", name)
                self.assertEqual((code, out["error"]["code"]), (2, "usage"))
        self.assertEqual(self.keys_to(term), [])

    def test_timeout_is_exit_4_and_frees_reservation(self):
        _, term = self.first()
        with self._hc_locked() as st:
            st["on_clear"] = {term: "none"}
        code, out = self.o("terminal-reset", "--terminal", term, "--timeout-ms", "400")
        self.assertEqual((code, out["error"]["code"]), (4, "reset_timeout"))
        self.assertEqual(out["turn_before"], 3)
        self.assertEqual((out["last"]["status"], out["last"]["turn"]), ("done", 3))
        self.assertIn("title", out["last"])
        self.assertIsNone(self.reservation_row(term))

    def test_poll_fallback_without_events(self):
        _, term = self.first()
        self.fail_hc("events", "unavailable")
        code, out = self.o("terminal-reset", "--terminal", term)
        self.assertEqual(code, 0, out)
        self.assertEqual((out["signal"], out["turn"]), ("poll", 4))

    def test_turn_event_needs_subscription_before_keys(self):
        """turn 사건으로만 비웠다는 신호가 온다(hc get 은 옛 turn 그대로). 사건은 0.3초 늦게, keys 를 받을 때 이미 붙은
        구독에만 온다(herdr-orch 설계 13.7 의 가짜 시나리오, 13.8 의 4: 구독을 먼저 붙인다)."""
        _, term = self.first()
        with self._hc_locked() as st:
            st["on_clear"] = {term: "event"}
        code, out = self.o("terminal-reset", "--terminal", term)
        self.assertEqual(code, 0, out)
        self.assertEqual((out["signal"], out["turn"], out["status"]), ("event", 4, "idle"))
        self.assertEqual(self.hc_state()["keys"][-1]["subscribed"], True)
        self.assertEqual(self.hc_state()["terminals"][term]["turn"], 3)  # 폴링으로는 알 수 없었다
        self.assertIsNone(self.reservation_row(term))

    def test_slow_poll_still_sees_arrived_event(self):
        """느린 폴링 hc get 이 마감을 넘겨도, 그 사이 이미 온 turn 사건을 시간 초과 전에 읽어 성공한다
        (Codex 커밋 리뷰 c6d82d2 의 재현: on_clear event, get 지연 0.7초, --timeout-ms 500)."""
        _, term = self.first()
        with self._hc_locked() as st:
            st["on_clear"] = {term: "event"}
            st.setdefault("delay", {})["get"] = 0.7
        code, out = self.o("terminal-reset", "--terminal", term, "--timeout-ms", "500")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["signal"], out["turn"], out["status"]), ("event", 4, "idle"))
        self.assertIsNone(self.reservation_row(term))

    def test_drain_finds_turn_after_skipped_burst(self):
        """마감 전 비우기는 지금 와 있는 알림을 다 읽는다: 완료 turn 사건이 읽기 한 조각을 넘는 건너뛸 알림 뒤에 와 있어도
        찾는다(Codex 커밋 리뷰 2cd720c. on_clear event, burst 3000줄, get 지연 0.7초, --timeout-ms 500)."""
        _, term = self.first()
        with self._hc_locked() as st:
            st["on_clear"] = {term: "event"}
            st["burst"] = {term: 3000}
            st.setdefault("delay", {})["get"] = 0.7
        code, out = self.o("terminal-reset", "--terminal", term, "--timeout-ms", "500")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["signal"], out["turn"], out["status"]), ("event", 4, "idle"))
        self.assertIsNone(self.reservation_row(term))

    def reset_then(self, term, *, status, turn, timeout_ms):
        """on_clear none 으로 리셋을 띄우고 keys 가 온 뒤(turn_before 를 읽은 뒤) 터미널을 status·turn 으로 바꾼다.
        가짜 events 는 그 변화를 turn 알림(data.state = status)으로, hc get 은 같은 값으로 준다."""
        with self._hc_locked() as st:
            st["on_clear"] = {term: "none"}
        bg = self.horch_bg("terminal-reset", "--terminal", term, "--timeout-ms", str(timeout_ms), terminal="t100")
        self.addCleanup(lambda: bg.poll() is None and bg.kill())
        deadline = time.monotonic() + 10
        while not self.keys_to(term):
            self.assertLess(time.monotonic(), deadline, "keys 가 오지 않았다")
            time.sleep(0.05)
        self.update_terminal(term, status=status, turn=turn)
        return self.finish(bg)

    def test_idle_after_clear_counts_for_codex(self):
        """Codex 도 /clear 뒤 idle·turn+1 이면 비운 것이다(X3b)."""
        _, term = self.first(agent="codex")
        code, res = self.reset_then(term, status="idle", turn=4, timeout_ms=20000)
        self.assertEqual((code, res["turn"], res["status"]), (0, 4, "idle"), res)

    def test_done_turn_is_not_cleared(self):
        """turn 이 올라도 done 이면 비운 것으로 보지 않는다. 보통 턴은 done 으로 끝나고, 보통 글로 처리된 /clear
        (X3 의 감싼 /clear)도 그렇다. 사건·폴링 모두 받지 않고 마감까지 기다려 reset_timeout 이다."""
        _, term = self.first(agent="codex")
        code, res = self.reset_then(term, status="done", turn=4, timeout_ms=1500)
        self.assertEqual((code, res["error"]["code"]), (4, "reset_timeout"), res)
        self.assertEqual((res["turn_before"], res["last"]["status"], res["last"]["turn"]), (3, "done", 4))
        self.assertIsNone(self.reservation_row(term))

    def test_keys_failure_is_hc_failed(self):
        _, term = self.first()
        self.fail_hc("keys", "timeout")
        code, out = self.o("terminal-reset", "--terminal", term)
        self.assertEqual((code, out["error"]["code"]), (1, "hc_failed"))
        self.assertIsNone(self.reservation_row(term))

    def test_refuses_busy_not_ready_and_gone(self):
        out = self.keep_open()
        term = out["terminal"]
        self.ready(term)
        code, res = self.o("terminal-reset", "--terminal", term)
        self.assertEqual((code, res["error"]["code"], res["dispatch"]), (3, "terminal_busy", out["dispatch"]))
        self.settle(out["dispatch"], term)
        self.ready(term, status="working")
        code, res = self.o("terminal-reset", "--terminal", term)
        self.assertEqual((code, res["error"]["code"]), (3, "terminal_not_ready"))
        self.update_terminal(term, state="finished")
        code, res = self.o("terminal-reset", "--terminal", term)
        self.assertEqual((code, res["error"]["code"]), (3, "terminal_gone"))
        self.assertEqual(self.keys_to(term), [])

    def test_reset_excludes_put_and_other_reset(self):
        _, term = self.first()
        with self._hc_locked() as st:
            st["on_clear"] = {term: "none"}  # 비운 신호가 오지 않는다: 시험이 장벽을 풀 때까지 리셋이 예약을 쥔다
        bg = self.horch_bg("terminal-reset", "--terminal", term, "--timeout-ms", "60000", terminal="t100")
        self.addCleanup(lambda: bg.poll() is None and bg.kill())
        deadline = time.monotonic() + 10
        while self.reservation_row(term) is None:
            self.assertLess(time.monotonic(), deadline, "리셋 예약이 생기지 않았다")
            time.sleep(0.05)
        dispatches = self.count("dispatches")
        code, res = self.put(term)
        self.assertEqual((code, res["error"]["code"], res["dispatch"]), (3, "terminal_busy", None))
        self.assertEqual(self.count("dispatches"), dispatches)
        code, res = self.o("terminal-reset", "--terminal", term, "--timeout-ms", "200")
        self.assertEqual((code, res["error"]["code"]), (3, "terminal_busy"))
        self.assertIsNone(bg.poll())  # 두 거부를 본 동안 앞 리셋은 아직 예약을 쥐고 기다린다
        self.update_terminal(term, status="idle", turn=4)  # 장벽을 푼다: 앞 리셋이 비운 신호를 받는다
        code, res = self.finish(bg)
        self.assertEqual((code, res["turn"]), (0, 4), res)
        self.assertIsNone(self.reservation_row(term))
        code, res = self.put(term)
        self.assertEqual(code, 0, res)

    def test_put_after_reset_uses_new_turn(self):
        _, term = self.first()
        code, out = self.o("terminal-reset", "--terminal", term)
        self.assertEqual(code, 0, out)
        code, res = self.put(term)
        self.assertEqual(code, 0, res)
        self.assertEqual(res["start_turn"], out["turn"])  # 비우기 자체가 turn 을 하나 올린다(13.8 의 7)
        self.assertEqual(self.sent_to(term)[-1]["if"], "idle")


if __name__ == "__main__":
    unittest.main()
