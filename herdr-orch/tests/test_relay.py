"""Claude 상태 대리 보고와 Stop 기록(설계 16.3–16.7). relay 함수를 이 프로세스에서 바로 부른다.

가짜 hc 터미널 TERM 의 foreground 는 이 시험 프로세스다(relay 는 훅 프로세스 자신도 조상으로 본다). ps 는 표로 바꿔
끼운다(_ps_row): 이 프로세스의 tty 는 시험이 만든 pty 쌍의 slave 경로이고 master 에서 읽는다. 실제 터미널에는 쓰지 않는다.
확인기 띄우기(_spawn)는 부른 인자만 남긴다.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import select
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from tests.helpers import HorchCase
from horch import hcio, relay

TERM = "t60"
W = relay.osc("working")
D = relay.osc("done")
Q = relay.osc("blocked", "question")
P = relay.osc("blocked", "permission")
UTC_Z = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"


class RelayCase(HorchCase):
    def setUp(self):
        super().setUp()
        self.home.mkdir(mode=0o700)
        self.master, slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, slave)
        self.tty = os.ttyname(slave)
        self.me = os.getpid()
        self.start = (int(time.time()) - 10) * 1000  # Claude 가 10초 전에 떴다(판정 시각이 지났다)
        self.ps = {self.me: (os.getppid(), self.tty, self.start)}  # 그 위 조상은 표에 없다(조상이 아니다)
        self.spawned = []
        for patcher in (mock.patch.object(relay, "_ps_row", side_effect=lambda pid, deadline=None: self.ps.get(pid)),
                        mock.patch.object(relay, "_spawn", side_effect=lambda home, *args: self.spawned.append(args)),
                        mock.patch.dict(os.environ, self._env(TERM, None), clear=True)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.add_terminal(TERM, argv=["claude"], status="idle", turn=3)  # 가짜 hc 의 status_ms 는 기본 null(보고한 적 없다)
        self.update_terminal(TERM, foreground={"pid": self.me, "name": "claude", "argv": ["claude"],
                                               "cwd": str(self.tmp)})

    def decide_after(self, seconds: float) -> None:
        os.environ["HORCH_TEST_RELAY_DECIDE_S"] = str(seconds)

    def handle(self, event, payload=None, *, role="worker"):
        relay.handle(self.home, event, {"session_id": "s1", **(payload or {})}, role=role)

    def rec(self):
        return relay.record(self.home, TERM)

    def put(self, **fields):
        """기록을 바로 쓴다(기본: 이 프로세스, on, 아직 쓰지 않았다)."""
        rec = {"terminal": TERM, "pid": self.me, "tty": self.tty, "started_ms": self.start, "decided": "on",
               "pending": "idle", "last": None, "at": None, "blockers": {}, "perm_tools": {}, "write_failures": 0,
               "notified": False, **fields}
        (self.home / "relay").mkdir(mode=0o700, exist_ok=True)
        (self.home / "relay" / f"{TERM}.json").write_text(json.dumps(rec), encoding="utf-8")

    def read_tty(self) -> bytes:
        chunks = []
        while select.select([self.master], [], [], 0.05)[0]:
            chunks.append(os.read(self.master, 4096))
        return b"".join(chunks)

    def log_lines(self):
        path = self.home / "relay.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def set_status(self, **status):
        """가짜 hc 의 상태 기록(msg 기본 빈 글)."""
        with self._hc_locked() as st:
            st["terminals"][TERM]["status"] = {"app": "claude-code", "msg": "", **status}

    def hc_gets(self):
        return [c for c in self.hc_calls() if c[:2] == ["get", TERM]]

    def stops(self):
        return relay.stops(self.home, TERM)


class OscTest(unittest.TestCase):
    def test_bytes_constants_and_names(self):
        self.assertEqual(relay.osc("working"), b"\x1b]7501;state=working:app=claude-code\x07")
        self.assertEqual(relay.osc("blocked", "question"), b"\x1b]7501;state=blocked:app=claude-code:kind=question\x07")
        self.assertEqual(relay.osc("blocked", "permission"),
                         b"\x1b]7501;state=blocked:app=claude-code:kind=permission\x07")
        self.assertEqual(relay.osc("clear"), b"\x1b]7501;state=clear\x07")
        self.assertEqual((relay.DECIDE_S, relay.CHECK_BUDGET_S, relay.CHECK_EVERY_S, relay.FOREGROUND_FRESH_S,
                          relay.LOCK_WAIT_S, relay.WRITE_RETRIES, relay.WRITE_PAUSE_S, relay.FAIL_LIMIT, relay.STOPS_KEEP,
                          relay.DESC_MAX, relay.REVERIFY_SLACK_MS, relay.HC_TIMEOUT, relay.PS_TIMEOUT),
                         (3.0, 10.0, 1.0, 1.0, 10.0, 2, 0.1, 3, 20, 80, 1000, 3.0, 3.0))
        self.assertEqual(relay.ROLES, ("worker", "main"))
        self.assertEqual(relay.NOTICED, ("no_tty", "write_failed"))
        self.assertEqual(relay.NOTICE, 'herdr-orch: 이 세션은 Herdr 에 상태를 보고하지 않고 대신 보낼 수도 없다(Claude 시작 질의 '
                                       '실패, 대리 쓰기 실패). 질문이 Herdr "Needs you" 로 뜨지 않는다. 사용자에게 그대로 알린다: '
                                       '일이 덜 몰린 때 /exit 뒤 같은 터미널에서 claude --resume 으로 다시 열면 풀린다. 세션을 '
                                       '스스로 끝내지 않는다.')
        self.assertEqual(relay.HOOK_SCRIPT.parts[-2:], ("hooks", "horch_hook.py"))
        for good in ("t60", "t1f", "w-1.a_b:c", "x" * 64):
            self.assertTrue(relay.valid_terminal(good), good)
        for bad in ("", "x" * 65, "a/b", "a b", "가", None, 7):
            self.assertFalse(relay.valid_terminal(bad), bad)


class FakeHcGetTest(HorchCase):
    def test_get_reports_new_fields_with_defaults(self):
        """가짜 hc get(설계 16.11): status_ms·reported·created_ms·foreground 는 기본 null·false 이고 터미널 기록의 값이 앞선다."""
        self.add_terminal("t5", argv=["claude"], status="idle")
        with mock.patch.dict(os.environ, self.env, clear=True):
            got = hcio.get("t5")
            self.assertEqual((got["status_ms"], got["reported"], got["created_ms"], got["foreground"]),
                             (None, False, None, None))
            fg = {"pid": 7, "name": "claude", "argv": ["claude"], "cwd": "/"}
            self.update_terminal("t5", status_ms=5, reported=True, created_ms=3, foreground=fg)
            got = hcio.get("t5")
        self.assertEqual((got["status_ms"], got["reported"], got["created_ms"], got["foreground"]), (5, True, 3, fg))


class RecordTest(RelayCase):
    def test_session_start_creates_the_record_and_spawns_the_checker(self):
        self.decide_after(30)
        self.handle("SessionStart", {"source": "startup"})
        self.assertEqual(self.rec(), {"terminal": TERM, "pid": self.me, "tty": self.tty, "started_ms": self.start,
                                      "decided": None, "pending": "idle", "last": None, "at": None, "blockers": {},
                                      "perm_tools": {}, "write_failures": 0, "notified": False})
        self.assertEqual(self.spawned, [(TERM, self.me, self.start)])
        self.assertEqual(oct((self.home / "relay").stat().st_mode & 0o777), oct(0o700))
        self.handle("SessionStart", {"source": "clear"})  # 같은 프로세스(/clear): 기록을 그대로 쓴다
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(self.read_tty(), b"")

    def test_any_event_creates_the_record(self):
        self.decide_after(30)
        self.handle("PostToolUse", {"tool_name": "Read", "tool_use_id": "r1"})  # SessionStart 의 hc 가 실패했던 경우
        self.assertEqual(self.rec()["pending"], "working")
        self.assertEqual(self.spawned, [(TERM, self.me, self.start)])

    def test_no_record_unless_the_foreground_is_an_ancestor(self):
        for fg in ({"pid": 999999, "name": "claude"}, None):
            self.update_terminal(TERM, foreground=fg)
            self.handle("SessionStart", {"source": "startup"})
            self.assertIsNone(self.rec(), fg)
        self.update_terminal(TERM, foreground={"pid": self.me})
        self.fail_hc("get", "timeout")
        self.handle("PostToolUse", {"tool_name": "Read"})
        self.assertIsNone(self.rec())
        self.assertEqual(self.spawned, [])
        self.clear_hc_fail("get")
        self.handle("PostToolUse", {"tool_name": "Read"})  # 다음 사건에서 다시 한다
        self.assertEqual(self.rec()["pid"], self.me)

    def test_error_recovery_of_an_old_hook_leaves_the_new_record(self):
        """옛 Claude A(이 프로세스)의 Stop 이 쓰기 전에 예외로 끝나는 사이 새 Claude B 가 기록을 만들었다. 보완(_give_up)은 그
        훅의 Claude 기록일 때만 write_failed 로 바꾸므로 B 의 기록은 그대로다(Codex 계획 리뷰 r3)."""
        b_start = self.start + 5000
        self.ps[4242] = (1, self.tty, b_start)
        self.put(last="working")

        def swap(*args):
            self.put(pid=4242, started_ms=b_start, last="working")
            raise RuntimeError("깨짐")
        with mock.patch.object(relay, "_apply", side_effect=swap):
            with self.assertRaises(RuntimeError):
                self.handle("Stop", {}, role="main")
        self.assertEqual((self.rec()["pid"], self.rec()["decided"], self.read_tty()), (4242, "on", b""))
        relay._give_up(self.home, TERM, 4242, b_start)  # 그 기록의 Claude 의 보완이면 바꾼다
        self.assertEqual(self.rec()["decided"], "write_failed")

    def test_a_late_event_of_an_old_claude_leaves_the_new_record(self):
        """옛 Claude A(이 프로세스)의 훅이 잠금 밖에서 A 를 확인한 뒤 늦어진 사이 새 Claude B 가 기록을 만들었다. B 가 살면 A 의
        늦은 사건은 B 의 기록을 바꾸지도, Stop 기록을 남기지도, 쓰지도 않는다. B 도 끝났으면 기록을 새로 만든다(Codex 계획
        리뷰 r2)."""
        b_start = self.start + 5000
        self.ps[4242] = (1, self.tty, b_start)  # 새 Claude B. 이 훅의 조상이 아니다
        self.put(pid=4242, started_ms=b_start, last="working", blockers={"tool:q1": "question"})
        path = self.home / "relay" / f"{TERM}.json"
        before = path.read_text(encoding="utf-8")
        self.handle("Stop", {})
        self.assertEqual((path.read_text(encoding="utf-8"), self.read_tty(), self.spawned, self.stops()),
                         (before, b"", [], []))
        self.assertRegex(self.log_lines()[-1], rf"^{UTC_Z} {TERM} {self.me} 늦은 사건 버림\(Stop\): 기록은 4242 의 것이다$")
        del self.ps[4242]
        self.decide_after(30)
        self.handle("PostToolUse", {"tool_name": "Read"})
        self.assertEqual((self.rec()["pid"], self.rec()["decided"]), (self.me, None))
        self.assertEqual(self.spawned, [(TERM, self.me, self.start)])

    def test_a_claude_that_ends_while_the_hook_waits_gets_no_write(self):
        """잠금 밖에서 그 Claude 를 확인한 뒤 hc 조회나 잠금 대기 사이 그 Claude 가 끝났다. 기록의 주인이 그대로여도 쓰기 전에
        pid·시작 시각을 다시 보고 쓰지 않는다(설계 16.10, 계획 리뷰 plan2 r2 의 1)."""
        self.put(last="working")
        path = self.home / "relay" / f"{TERM}.json"
        before = path.read_text(encoding="utf-8")
        real_get = relay._hc_get

        def hc_get(term, deadline=None):
            info = real_get(term, deadline)
            self.ps.pop(self.me, None)  # hc 를 기다리는 사이 Claude 가 끝났다
            return info
        with mock.patch.object(relay, "_hc_get", side_effect=hc_get):
            self.handle("Stop", {})
        self.assertEqual((self.read_tty(), path.read_text(encoding="utf-8"), self.stops()), (b"", before, []))
        self.assertIn(f"{TERM} {self.me} 사건 버림(Stop): 그 Claude 가 끝났다(쓰기 없음)", self.log_lines()[-1])
        self.ps[self.me] = (os.getppid(), self.tty, self.start)
        self.put(last="idle")
        th = threading.Thread(target=self.handle, args=("UserPromptSubmit", {}))
        with relay._locked(self.home, TERM):  # 다른 훅이 잠금을 쥐었다
            th.start()
            time.sleep(0.3)  # 그 훅은 조상 확인을 마치고 잠금을 기다린다
            self.ps[self.me] = (os.getppid(), self.tty, self.start + 1000)  # 그 사이 Claude 가 끝나고 pid 가 다시 쓰였다
        th.join(10)
        self.assertEqual((self.read_tty(), self.rec()["last"]), (b"", "idle"))
        self.assertIn("사건 버림(UserPromptSubmit): 그 Claude 가 끝났다", self.log_lines()[-1])

    def test_same_pid_with_another_start_time_is_another_process(self):
        self.decide_after(30)
        self.put(decided="off", started_ms=self.start - 60_000)
        self.handle("PostToolUse", {"tool_name": "Read"})
        rec = self.rec()
        self.assertEqual((rec["started_ms"], rec["decided"]), (self.start, None))
        self.assertEqual(self.spawned, [(TERM, self.me, self.start)])

    def test_outside_the_target_does_nothing(self):
        """Herdr 밖, 서브에이전트 사건, 모르는 사건·역할, 상대 경로이거나 없는 홈은 아무것도 하지 않는다(설계 16.2)."""
        os.environ.pop("HC_TERMINAL_ID")
        self.handle("SessionStart")
        os.environ["HC_TERMINAL_ID"] = "a/b"  # 파일 이름으로 쓸 수 없는 주소
        self.handle("SessionStart")
        os.environ["HC_TERMINAL_ID"] = TERM
        self.handle("PostToolUse", {"tool_name": "Read", "agent_id": "a1"})
        self.handle("Notification", {})
        self.handle("PostToolUse", {"tool_name": "Read"}, role="unknown")
        relay.handle("relative/home", "PostToolUse", {"tool_name": "Read"}, role="worker")
        relay.handle(self.tmp / "no-such-home", "PostToolUse", {"tool_name": "Read"}, role="worker")
        relay.handle(self.home, "PostToolUse", ["not", "a", "dict"], role="worker")
        self.assertIsNone(self.rec())
        self.assertEqual(self.hc_gets(), [])
        self.assertFalse((self.tmp / "no-such-home").exists())  # 홈은 만들지 않는다

    def test_compact_never_creates_decides_or_writes(self):
        """자동 compact 는 턴 중간이다. 판정 전 기록에서도 판정하지 않고 쓰지 않는다(pending 도 그대로). 기록이 없으면(앞
        사건의 hc 가 실패했다) 만들지 않는다: 만들면 확인기가 기본 pending(idle)을 턴 중간에 쓴다."""
        self.handle("SessionStart", {"source": "compact"})
        self.assertIsNone(self.rec())
        self.assertEqual((self.spawned, self.hc_gets()), ([], []))
        self.put(decided=None, pending="working")
        self.handle("SessionStart", {"source": "compact"})
        rec = self.rec()
        self.assertEqual((rec["decided"], rec["pending"], self.read_tty()), (None, "working", b""))


class DecideTest(RelayCase):
    def test_waits_decide_s_and_never_decides_at_a_prompt(self):
        self.decide_after(30)
        self.handle("SessionStart", {"source": "startup"})
        self.handle("PreToolUse", {"tool_name": "Bash", "tool_use_id": "b1"})
        self.assertEqual((self.rec()["decided"], self.rec()["pending"]), (None, "working"))
        self.decide_after(0)
        self.handle("UserPromptSubmit", {"prompt": "x"})  # 그 턴의 Claude 보고보다 먼저 돌 수 있다
        self.assertIsNone(self.rec()["decided"])
        self.assertEqual(self.read_tty(), b"")
        self.handle("PostToolUse", {"tool_name": "Bash", "tool_use_id": "b1"})
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", W))
        self.assertEqual(len(self.log_lines()), 1)
        self.assertRegex(self.log_lines()[0], rf"^{UTC_Z} {TERM} {self.me} on$")

    def test_status_after_start_is_off_otherwise_on(self):
        for status_ms, want in ((self.start + 500, "off"), (self.start - 5000, "on"), (None, "on")):
            with self.subTest(status_ms=status_ms):
                self.put(decided=None)
                self.update_terminal(TERM, status_ms=status_ms)
                self.handle("PostToolUse", {"tool_name": "Bash"})
                self.assertEqual(self.rec()["decided"], want)
                self.assertEqual(self.read_tty(), b"" if want == "off" else W)

    def test_no_tty(self):
        self.ps[self.me] = (os.getppid(), None, self.start)  # ps 의 tty 가 `??`
        self.handle("PostToolUse", {"tool_name": "Bash"})
        self.assertEqual((self.rec()["tty"], self.rec()["decided"]), (None, "no_tty"))

    def test_hc_failure_does_not_decide(self):
        self.put(decided=None)
        self.fail_hc("get", "timeout")
        self.handle("PostToolUse", {"tool_name": "Bash"})
        self.assertEqual((self.rec()["decided"], self.rec()["pending"], self.read_tty()), (None, "working", b""))

    def test_first_question_of_the_main_is_written_at_the_decision(self):
        self.put(decided=None)
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"}, role="main")
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", Q))

    def test_checker_writes_the_pending_question(self):
        """첫 질문이 답을 기다리는 동안에는 다음 훅 사건이 없다: 확인기가 판정하고 blocked 를 쓴다."""
        self.decide_after(30)
        self.put(decided=None)
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"}, role="main")
        self.assertEqual((self.rec()["blockers"], self.read_tty()), ({"tool:q1": "question"}, b""))
        self.decide_after(0)
        relay.check(self.home, TERM, self.me, self.start)
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", Q))

    def test_checker_retries_after_an_hc_failure(self):
        self.put(decided=None, pending="idle")
        self.fail_hc("get", "timeout")
        with mock.patch.object(relay, "CHECK_EVERY_S", 0.2):
            th = threading.Thread(target=relay.check, args=(self.home, TERM, self.me, self.start))
            th.start()
            time.sleep(0.3)
            self.clear_hc_fail("get")
            th.join(10)
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", relay.osc("idle")))
        self.assertGreaterEqual(len(self.hc_gets()), 2)

    def test_checker_gives_up_after_its_budget_and_ignores_other_processes(self):
        self.put(decided=None)
        self.fail_hc("get", "timeout")
        t0 = time.monotonic()
        with mock.patch.object(relay, "CHECK_EVERY_S", 0.1), mock.patch.object(relay, "CHECK_BUDGET_S", 0.5):
            relay.check(self.home, TERM, self.me, self.start)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertIsNone(self.rec()["decided"])
        before = len(self.hc_calls())
        relay.check(self.home, TERM, 4242, self.start)  # 다른 프로세스의 확인기
        relay.check(self.home, TERM, self.me, self.start - 1000)  # 같은 pid 의 다른 프로세스
        relay.check(self.home, "a/b", self.me, self.start)  # 쓸 수 없는 주소
        relay.check(self.tmp / "no-such-home", TERM, self.me, self.start)  # 없는 홈
        self.assertEqual(len(self.hc_calls()), before)

    def test_checker_writes_only_to_the_foreground_claude(self):
        """확인기는 훅의 자손이 아니다. 판정에 쓴 hc get 의 foreground.pid 가 기록의 pid 이고 그 시작 시각(ps)이 기록과 같을
        때만 판정하고 쓴다. Claude 가 끝났거나(전경 없음·다른 프로그램) pid 가 다시 쓰였으면 아무것도 하지 않는다."""
        cases = (({"pid": 999999, "name": "zsh"}, self.start), (None, self.start),
                 ({"pid": self.me, "name": "claude"}, self.start - 60_000))
        for fg, ps_start in cases:
            with self.subTest(fg=fg, ps_start=ps_start):
                self.put(decided=None)
                self.update_terminal(TERM, foreground=fg)
                self.ps[self.me] = (os.getppid(), self.tty, ps_start)
                relay.check(self.home, TERM, self.me, self.start)
                self.assertEqual((self.rec()["decided"], self.read_tty()), (None, b""))
        self.assertIn("확인기: 전경이 그 Claude 가 아니다(판정·쓰기 없음)", self.log_lines()[-1])

    def test_checker_rechecks_after_waiting_for_the_lock(self):
        """확인기가 전경을 본 뒤 잠금을 기다리는 사이 Claude 가 끝나거나 전경이 바뀌면 쓰지 않는다(Codex 계획 리뷰 r2).
        잠금 안에서는 그 Claude 가 사는지(ps) 다시 보고, 1초 넘게 기다렸으면 잠금을 놓고 전경부터 다시 본다."""
        def run_while_locked(hold, change):
            before = len(self.hc_gets())
            th = threading.Thread(target=relay.check, args=(self.home, TERM, self.me, self.start))
            with relay._locked(self.home, TERM):  # 다른 훅이 잠금을 쥐었다
                th.start()
                deadline = time.monotonic() + 5
                while len(self.hc_gets()) == before and time.monotonic() < deadline:
                    time.sleep(0.02)
                time.sleep(0.2)  # 확인기는 전경을 봤고 잠금을 기다린다
                change()
                time.sleep(hold)
            th.join(15)
            return len(self.hc_gets()) - before
        self.put(decided=None)
        self.assertEqual(run_while_locked(0, lambda: self.ps.pop(self.me)), 1)  # 짧은 대기 중 그 Claude 가 끝났다
        self.assertEqual((self.rec()["decided"], self.read_tty()), (None, b""))
        self.assertIn("확인기: 그 Claude 가 끝났다(판정·쓰기 없음)", self.log_lines()[-1])
        self.ps[self.me] = (os.getppid(), self.tty, self.start)
        other = {"pid": 999999, "name": "zsh", "argv": ["zsh"], "cwd": str(self.tmp)}
        self.assertEqual(run_while_locked(1.0, lambda: self.update_terminal(TERM, foreground=other)), 2)  # 다시 봤다
        self.assertEqual((self.rec()["decided"], self.read_tty()), (None, b""))
        self.assertIn("확인기: 전경이 그 Claude 가 아니다", self.log_lines()[-1])
        self.update_terminal(TERM, foreground={"pid": self.me, "name": "claude", "argv": ["claude"],
                                               "cwd": str(self.tmp)})
        self.assertEqual(run_while_locked(1.0, lambda: None), 2)  # 바뀐 것이 없으면 다시 본 뒤 판정하고 쓴다
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", relay.osc("idle")))

    def test_two_hooks_deciding_together_give_one_result(self):
        """한 턴의 도구 호출이 함께 끝나 PostToolUse 둘이 함께 판정한다. 먼저 잠금을 잡은 쪽이 on 으로 정하고 쓰면 실제 hc
        의 status_ms 가 그 쓰기로 Claude 시작 뒤가 된다. 그 hc 를 본 다른 훅도 잠금 안에서 기록을 다시 읽어 on 을 따른다."""
        self.put(decided=None)
        written = threading.Event()
        real_get, real_write = relay._hc_get, relay._write_once

        def hc_get(term, deadline=None):
            info = real_get(term, deadline)
            if threading.current_thread().name == "late":
                written.wait(10)  # 앞 훅이 쓴 뒤의 hc: 그 쓰기가 status_ms 에 들었다
                info = {**info, "status_ms": relay._now_ms(),
                        "status": {"app": "claude-code", "state": "working", "msg": ""}}
            return info

        def write_once(tty, data):
            n = real_write(tty, data)
            written.set()
            return n

        with mock.patch.object(relay, "_hc_get", side_effect=hc_get), \
                mock.patch.object(relay, "_write_once", side_effect=write_once):
            late = threading.Thread(target=self.handle, name="late",
                                    args=("PostToolUse", {"tool_name": "Read", "tool_use_id": "r1"}))
            late.start()
            time.sleep(0.2)  # late 는 판정 전 기록을 읽고 hc 를 기다린다
            self.handle("PostToolUse", {"tool_name": "Grep", "tool_use_id": "g1"})
            late.join(10)
        self.assertEqual(self.rec()["decided"], "on")
        self.assertEqual(self.read_tty(), W)
        self.assertEqual([line.split()[-1] for line in self.log_lines()], ["on"])

    def test_lock_is_not_held_while_waiting_for_hc(self):
        self.delay_hc("get", 1.0)  # 느린 hc
        th = threading.Thread(target=self.handle, args=("SessionStart", {"source": "startup"}))
        th.start()
        time.sleep(0.3)  # 그 훅은 잠금 밖에서 hc 를 기다린다
        with relay._locked(self.home, TERM, wait=0.2):  # 다른 훅은 기다리지 않고 잡는다(못 잡으면 _Busy)
            pass
        th.join(10)
        self.assertEqual(self.rec()["pid"], self.me)


class WriteTest(RelayCase):
    def setUp(self):
        super().setUp()
        self.put()  # on, 아직 쓰지 않았다

    def test_event_table_bytes(self):
        bg = [{"id": "b1", "type": "shell", "status": "running", "description": "전체 시험"}]
        steps = (("UserPromptSubmit", {}, "worker", W),
                 ("PreToolUse", {"tool_name": "Bash", "tool_use_id": "b1"}, "worker", b""),  # last 와 같다
                 ("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "rm x"}}, "worker", P),
                 ("PostToolUse", {"tool_name": "Bash", "tool_use_id": "b1", "tool_input": {"command": "rm x"}},
                  "worker", W),
                 ("Stop", {"background_tasks": []}, "worker", D),
                 ("UserPromptSubmit", {}, "worker", W),
                 ("Stop", {"background_tasks": bg}, "worker", b""),  # 백그라운드 일이 돈다: working 그대로
                 ("Stop", {"background_tasks": bg}, "main", D),  # 메인은 늘 done
                 ("StopFailure", {"error": "rate_limit"}, "main", relay.osc("error")),
                 ("SessionStart", {"source": "clear"}, "main", W + relay.osc("idle")),
                 ("SessionStart", {"source": "clear"}, "main", W + relay.osc("idle")),  # 늘 쓴다(turn 이 오른다)
                 ("SessionStart", {"source": "compact"}, "main", b""),  # 턴 중간이다
                 ("SessionEnd", {"reason": "prompt_input_exit"}, "main", relay.osc("clear")),
                 ("SessionStart", {"source": "resume"}, "main", relay.osc("idle")))
        for event, payload, role, want in steps:
            with self.subTest(event=event, role=role):
                self.handle(event, payload, role=role)
                self.assertEqual(self.read_tty(), want)
        self.assertEqual(self.rec()["write_failures"], 0)

    def test_subagent_events_are_ignored(self):
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"}, role="main")
        self.assertEqual(self.read_tty(), Q)
        before = self.rec()
        self.handle("PostToolUse", {"tool_name": "Read", "tool_use_id": "x", "agent_id": "a1"}, role="main")
        self.handle("Stop", {"agent_id": "a1"})
        self.assertEqual((self.rec(), self.read_tty()), (before, b""))
        self.assertEqual(self.stops(), [])

    def test_question_with_a_parallel_read(self):
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"}, role="main")
        self.handle("PostToolUse", {"tool_name": "Read", "tool_use_id": "r1"}, role="main")  # 함께 돈 읽기가 끝났다
        self.assertEqual(self.read_tty(), Q)
        self.handle("PostToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"}, role="main")
        self.assertEqual(self.read_tty(), W)

    def test_question_key_without_a_tool_use_id(self):
        ask = {"tool_name": "AskUserQuestion", "tool_input": {"questions": [{"question": "어느 쪽?"}]}}
        self.handle("PreToolUse", ask, role="main")
        self.assertEqual(list(self.rec()["blockers"]), ["tool:" + relay._hash(json.dumps(
            ask["tool_input"], sort_keys=True, ensure_ascii=False))])

    def test_worker_question_is_not_a_blocker(self):
        """워커의 질문은 horch ask 메일함으로 간다. 다른 플러그인이 거부하면 PostToolUse 가 오지 않아 blocked 가 남으므로
        넣지 않는다(설계 16.2)."""
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"})
        self.assertEqual((self.rec()["blockers"], self.read_tty()), ({}, W))

    def test_permission_keys_and_the_same_tool_fallback(self):
        bash = {"tool_name": "Bash", "tool_input": {"command": "rm x"}}
        write = {"tool_name": "Write", "tool_input": {"file_path": "/x", "content": "y"}}
        self.handle("PermissionRequest", bash)
        self.handle("PermissionRequest", write)
        key = "perm:" + hashlib.sha1('Bash\n{"command": "rm x"}'.encode()).hexdigest()[:16]
        self.assertEqual(list(self.rec()["blockers"]), [key, relay._perm_key(write)])
        self.assertEqual(self.rec()["perm_tools"], {key: "Bash", relay._perm_key(write): "Write"})
        self.assertEqual(self.read_tty(), P)
        # 다른 플러그인이 입력을 바꿨다: 해시가 달라도 같은 도구의 가장 오래된 승인이 빠진다(Write 는 남는다)
        self.handle("PostToolUse", {"tool_name": "Bash", "tool_use_id": "b1", "tool_input": {"command": "rm -i x"}})
        self.assertEqual((list(self.rec()["blockers"]), self.read_tty()), ([relay._perm_key(write)], b""))
        self.handle("PermissionDenied", write)  # auto 모드의 거절
        self.assertEqual((self.rec()["blockers"], self.rec()["perm_tools"], self.read_tty()), ({}, {}, W))

    def test_elicitation(self):
        self.handle("Elicitation", {"mcp_server_name": "s", "elicitation_id": "e1", "message": "m"})
        self.assertEqual((list(self.rec()["blockers"]), self.read_tty()), (["elic:s:e1"], Q))
        self.handle("ElicitationResult", {"mcp_server_name": "s", "elicitation_id": "e1", "action": "accept"})
        self.assertEqual(self.read_tty(), W)
        # id 가 없으면 키는 message 의 해시이고, 결과는 그 서버의 가장 오래된 것을 뺀다
        self.handle("Elicitation", {"mcp_server_name": "s", "message": "m1"})
        self.handle("Elicitation", {"mcp_server_name": "s", "message": "m2"})
        self.assertEqual(self.read_tty(), Q)
        self.handle("ElicitationResult", {"mcp_server_name": "s"})
        self.assertEqual(list(self.rec()["blockers"]), [f"elic:s:{relay._hash('m2')}"])
        self.handle("ElicitationResult", {"mcp_server_name": "s"})
        self.assertEqual((self.rec()["blockers"], self.read_tty()), ({}, W))

    def test_stop_and_prompt_clear_the_list(self):
        self.handle("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "x"}})
        self.handle("Stop", {}, role="main")  # 사람이 거절하면 턴이 끝날 때 풀린다
        self.assertEqual((self.rec()["blockers"], self.read_tty()), ({}, P + D))
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q1"}, role="main")
        self.handle("UserPromptSubmit", {}, role="main")
        self.assertEqual((self.rec()["blockers"], self.read_tty()), ({}, Q + W))

    def test_quiet_decisions_write_nothing(self):
        for decided in relay.QUIET:
            with self.subTest(decided=decided):
                self.put(decided=decided)
                for event, payload in (("UserPromptSubmit", {}), ("PermissionRequest", {"tool_name": "Bash"}),
                                       ("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q"}),
                                       ("Stop", {}), ("SessionEnd", {})):
                    self.handle(event, payload, role="main")
                self.handle("Stop", {})  # 워커 Stop: Stop 기록만 남긴다
                self.assertEqual((self.rec()["decided"], self.read_tty()), (decided, b""))


class WriteFailTest(RelayCase):
    def setUp(self):
        super().setUp()
        self.gone = str(self.tmp / "gone-tty")  # 열 수 없는 tty
        self.put(tty=self.gone)
        self.tries = []
        real = relay._write_once

        def spy(tty, data):
            self.tries.append(data)
            return real(tty, data)
        patcher = mock.patch.object(relay, "_write_once", side_effect=spy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_two_retries_per_event_and_three_failures_in_a_row(self):
        for n, event in enumerate(("UserPromptSubmit", "PreToolUse", "PostToolUse"), 1):
            self.handle(event, {"tool_name": "Read"})
            self.assertEqual(len(self.tries), 3 * n)  # 첫 쓰기와 0.1초 간격으로 두 번 더
            want = "on" if n < 3 else "write_failed"
            self.assertEqual((self.rec()["write_failures"], self.rec()["decided"]), (n, want))
        self.assertEqual(sum("쓰기 실패(working)" in line for line in self.log_lines()), 3)
        self.assertRegex(self.log_lines()[-1], rf"^{UTC_Z} {TERM} {self.me} write_failed$")
        self.handle("UserPromptSubmit", {})
        self.assertEqual(len(self.tries), 9)  # write_failed 뒤에는 쓰지 않는다

    def test_success_resets_the_count(self):
        self.put(tty=self.tty, write_failures=2)
        self.handle("UserPromptSubmit", {})
        self.assertEqual((self.rec()["write_failures"], self.read_tty()), (0, W))

    def test_eagain_is_retried_in_the_same_event(self):
        busy = OSError(errno.EAGAIN, "Resource temporarily unavailable")
        self.put(tty=self.tty)
        with mock.patch.object(relay, "_write_once", side_effect=[busy, busy, len(W)]) as fake:
            self.handle("UserPromptSubmit", {})
        self.assertEqual(fake.call_count, 3)
        self.assertEqual((self.rec()["write_failures"], self.rec()["last"]), (0, "working"))

    def test_last_events_and_blocked_fail_at_once(self):
        cases = (("Stop", {}, "main"), ("Stop", {}, "worker"), ("StopFailure", {}, "worker"), ("SessionEnd", {}, "main"),
                 ("PermissionRequest", {"tool_name": "Bash"}, "worker"),
                 ("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q"}, "main"),
                 ("Elicitation", {"mcp_server_name": "s", "elicitation_id": "e"}, "worker"))
        for event, payload, role in cases:
            with self.subTest(event=event, role=role):
                self.put(tty=self.gone, last="working")
                self.handle(event, payload, role=role)
                self.assertEqual((self.rec()["decided"], self.rec()["write_failures"]), ("write_failed", 1))

    def test_a_worker_question_is_not_a_last_event(self):
        """워커의 AskUserQuestion 은 blocked 를 쓰지 않는다(working). 그 쓰기 실패는 이어진 실패로만 센다."""
        self.put(tty=self.gone, last="idle")
        self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q"})
        self.assertEqual((self.rec()["decided"], self.rec()["write_failures"]), ("on", 1))

    def test_an_error_before_the_tty_write_of_a_last_event_is_write_failed(self):
        """턴의 마지막 사건이 쓰기 전에 예외로 끝나면 hc 에 앞 상태가 남는다: write_failed 로 둔다. 다른 사건은 그대로다."""
        self.put(tty=self.tty, last="working")
        with mock.patch.object(relay, "_apply", side_effect=RuntimeError("깨짐")):
            with self.assertRaises(RuntimeError):
                self.handle("PostToolUse", {"tool_name": "Read"})
            self.assertEqual(self.rec()["decided"], "on")
            with self.assertRaises(RuntimeError):
                self.handle("Stop", {}, role="main")
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("write_failed", b""))
        self.assertIn("write_failed(예외 뒤 보완)", self.log_lines()[-1])

    def test_a_failed_save_of_write_failed_is_saved_again(self):
        """Stop 의 쓰기 전 저장은 됐고 tty 쓰기가 실패해 write_failed 로 정했는데 그것을 담은 마지막 저장이 실패했다. 보완
        저장(_give_up)이 한 번 더 해 write_failed 가 남는다(Codex 계획 리뷰 r3)."""
        self.put(tty=self.gone, last="working")
        real, saved = relay._save, []

        def flaky(home, rec):
            saved.append(rec["decided"])
            if len(saved) == 2:  # 1: 쓰기 전 저장, 2: write_failed 를 담은 마지막 저장, 3: 보완 저장
                raise OSError("디스크 가득")
            real(home, rec)
        with mock.patch.object(relay, "_save", side_effect=flaky):
            with self.assertRaises(OSError):
                self.handle("Stop", {}, role="main")
        self.assertEqual(saved, ["on", "write_failed", "write_failed"])
        self.assertEqual(self.rec()["decided"], "write_failed")

    def test_a_failed_save_of_write_failed_by_the_checker_is_saved_again(self):
        """확인기가 첫 질문의 blocked 를 쓰다 실패해 write_failed 로 정했는데 그것을 담은 마지막 저장이 실패했다. 질문을
        기다리는 동안 다음 사건이 없으므로 확인기도 잠금을 놓은 뒤 보완 저장한다(계획 리뷰 plan2 r1 의 3)."""
        self.put(decided=None, tty=self.gone, pending="working", blockers={"tool:q1": "question"})
        real, saved = relay._save, []

        def flaky(home, rec):
            saved.append(rec["decided"])
            if len(saved) == 2:  # 1: 쓰기 전 저장(on), 2: write_failed 를 담은 마지막 저장, 3: 보완 저장
                raise OSError("디스크 가득")
            real(home, rec)
        with mock.patch.object(relay, "_save", side_effect=flaky):
            with self.assertRaises(OSError):
                relay.check(self.home, TERM, self.me, self.start)
        self.assertEqual(saved, ["on", "write_failed", "write_failed"])
        self.assertEqual(self.rec()["decided"], "write_failed")
        self.assertIn("write_failed(예외 뒤 보완)", self.log_lines()[-1])

    def test_the_checker_recovery_keeps_another_claudes_record(self):
        """확인기의 보완도 그 Claude(pid·started_ms)의 on 기록만 바꾼다: 그 사이 새 Claude B 가 기록을 만들었으면 그대로다."""
        b_start = self.start + 5000
        self.put(decided=None, tty=self.gone, pending="working", blockers={"tool:q1": "question"})
        real = relay._save
        calls = []

        def swap_then_fail(home, rec):
            calls.append(rec["decided"])
            if len(calls) == 2:
                real(home, {**rec, "pid": 4242, "started_ms": b_start, "decided": "on"})  # B 의 기록이 들어왔다
                raise OSError("디스크 가득")
            real(home, rec)
        with mock.patch.object(relay, "_save", side_effect=swap_then_fail):
            with self.assertRaises(OSError):
                relay.check(self.home, TERM, self.me, self.start)
        self.assertEqual((self.rec()["pid"], self.rec()["decided"]), (4242, "on"))


class NoticeTest(RelayCase):
    """메인 알림(계획 리뷰 plan2 r1 의 1): 메인의 Stop 에서 그 Claude 의 기록이 처음 no_tty·write_failed 면 notified 를 저장한 뒤
    훅 출력으로 그 Stop 을 한 번 막는다."""
    BLOCK = {"decision": "block", "reason": relay.NOTICE}

    def stop(self, role="main", **payload):
        return relay.handle(self.home, "Stop", {"session_id": "s1", **payload}, role=role)

    def test_a_failed_write_of_the_same_stop_blocks_that_stop(self):
        self.put(tty=str(self.tmp / "gone-tty"), last="working")
        self.assertEqual(self.stop(), self.BLOCK)  # done 쓰기가 실패해 write_failed: 같은 Stop 이 알린다
        self.assertEqual((self.rec()["decided"], self.rec()["notified"]), ("write_failed", True))
        before = len(self.hc_calls())
        self.assertIsNone(self.stop())  # 두 번째 Stop 은 막지 않는다(빠른 길: hc 없음)
        self.assertEqual(len(self.hc_calls()), before)

    def test_a_decision_by_the_checker_is_noticed_at_the_next_main_stop(self):
        self.ps[self.me] = (os.getppid(), None, self.start)  # tty 가 없다
        self.put(decided=None, tty=None)
        relay.check(self.home, TERM, self.me, self.start)  # 확인기가 no_tty 로 정했다(확인기는 알리지 않는다)
        self.assertEqual((self.rec()["decided"], self.rec()["notified"]), ("no_tty", False))
        self.assertIsNone(relay.handle(self.home, "PostToolUse", {"tool_name": "Read"}, role="main"))
        self.assertEqual(self.stop(), self.BLOCK)
        self.assertIsNone(self.stop())

    def test_a_continued_turn_is_noticed_once(self):
        """다른 Stop 훅이 막아 이어진 턴(stop_hook_active)에서도 처음이면 한 번 알리고, 다음 Stop 은 막지 않는다(orch 16.11,
        계획 리뷰 plan2 r2 의 4)."""
        self.put(decided="write_failed")
        self.assertEqual(self.stop(stop_hook_active=True), self.BLOCK)
        self.assertTrue(self.rec()["notified"])
        self.assertIsNone(self.stop(stop_hook_active=True))
        self.assertIsNone(self.stop())

    def test_workers_and_reporting_sessions_are_never_blocked(self):
        self.put(tty=str(self.tmp / "gone-tty"), last="working")
        self.assertIsNone(self.stop(role="worker"))  # 워커는 막지 않는다(감독이 relay_failed 로 안다)
        self.assertEqual((self.rec()["decided"], self.rec()["notified"]), ("write_failed", False))
        for decided in ("on", "off", None):
            self.put(decided=decided)
            self.assertIsNone(self.stop(), decided)
        self.assertEqual(self.read_tty(), D + D)  # on 세션과 이 Stop 이 on 으로 정한 세션의 done

    def test_the_mark_is_saved_before_blocking(self):
        self.put(decided="no_tty", tty=None)
        with mock.patch.object(relay, "_save", side_effect=OSError("디스크 가득")):
            with self.assertRaises(OSError):
                self.stop()  # 표시를 저장하지 못하면 막지 않는다(훅은 오류를 남기고 출력하지 않는다)
        self.assertFalse(self.rec()["notified"])
        self.assertEqual(self.stop(), self.BLOCK)

    def test_a_new_claude_is_noticed_again(self):
        self.put(decided="write_failed", notified=True, started_ms=self.start - 60_000)  # 앞 Claude 의 기록
        self.ps[self.me] = (os.getppid(), None, self.start)  # 새 Claude 는 tty 가 없다
        self.assertEqual(self.stop(), self.BLOCK)  # 새 기록이 no_tty 로 정해졌다: 한 번 더 알린다
        self.assertEqual((self.rec()["started_ms"], self.rec()["decided"]), (self.start, "no_tty"))


class SaveTest(RelayCase):
    """기록 저장 실패(설계 16.5, Codex 계획 리뷰 r1). 판정과 쓸 상태는 tty 쓰기 전에 저장한다."""

    def test_first_decision_is_saved_before_the_write(self):
        self.put(decided=None)
        with mock.patch.object(relay, "_save", side_effect=OSError("디스크 가득")):
            with self.assertRaises(OSError):
                self.handle("PostToolUse", {"tool_name": "Bash"})
        self.assertEqual((self.rec()["decided"], self.read_tty()), (None, b""))  # 저장하지 못한 판정은 쓰지 않는다
        self.handle("PostToolUse", {"tool_name": "Bash"})  # hc 에 자기 쓰기가 없다: 다음 사건이 다시 on 으로 판정한다
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", W))

    def test_a_failed_save_after_the_write_is_not_taken_for_a_self_report(self):
        self.put(decided=None)
        real, saved = relay._save, []

        def flaky(home, rec):
            saved.append(rec["last"])
            if len(saved) == 2:  # 쓴 뒤의 저장(last)만 실패한다
                raise OSError("디스크 가득")
            real(home, rec)
        with mock.patch.object(relay, "_save", side_effect=flaky):
            with self.assertRaises(OSError):
                self.handle("PostToolUse", {"tool_name": "Bash"})
        self.assertEqual((saved, self.read_tty()), ([None, "working"], W))
        self.assertEqual((self.rec()["decided"], self.rec()["last"]), ("on", None))  # 판정은 쓰기 전에 남았다
        self.update_terminal(TERM, status="working", status_ms=relay._now_ms())  # 그 쓰기가 hc 에 들었다
        self.handle("Stop", {}, role="main")  # 다시 확인이 자기 쓰기를 Claude 의 보고로 보지 않는다
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", D))


class StopRecordTest(RelayCase):
    def test_turn_rule_background_and_hc_failure(self):
        self.put(decided="off")  # 스스로 보고하는 세션도 Stop 기록을 남긴다
        bg = [{"id": "b1", "type": "shell", "status": "running", "description": "x" * 100, "command": "make test"}]
        self.set_status(state="working")  # hc turn 3 이고 아직 working: 이 턴 끝의 idle 은 turn 4 다
        self.handle("Stop", {"background_tasks": bg})
        self.set_status(state="idle")  # Claude 가 먼저 보고했다: turn 은 이미 올랐다
        self.handle("Stop", {})
        self.fail_hc("get", "timeout")
        self.handle("Stop", {"background_tasks": "x"})
        got = self.stops()
        self.assertEqual([(s["pid"], s["turn"], s["background"]) for s in got],
                         [(self.me, 4, [{"type": "shell", "status": "running", "description": "x" * 80}]),
                          (self.me, 3, []), (self.me, None, [])])
        for s in got:
            self.assertRegex(s["at"], rf"^{UTC_Z}$")
        self.assertEqual(self.read_tty(), b"")  # off: 쓰지 않는다

    def test_an_unidentified_stop_leaves_no_record(self):
        """늦은 옛 훅이 살아 있는 새 Claude B 의 전경을 보면 지금 Claude 를 확인하지 못한다(B 는 이 훅의 조상이 아니다). 그
        Stop 은 B 의 turn 에 자기 백그라운드 목록을 덧붙이지 않는다. hc 가 실패해도 같다(계획 리뷰 plan2 r1 의 2)."""
        b_start = self.start + 5000
        self.ps[4242] = (1, self.tty, b_start)
        self.put(pid=4242, started_ms=b_start, last="working")
        self.update_terminal(TERM, foreground={"pid": 4242, "name": "claude", "argv": ["claude"], "cwd": str(self.tmp)})
        path = self.home / "relay" / f"{TERM}.json"
        before = path.read_text(encoding="utf-8")
        self.handle("Stop", {"background_tasks": []})
        self.fail_hc("get", "timeout")
        self.handle("Stop", {"background_tasks": [{"type": "shell", "status": "running"}]})
        self.assertEqual((self.stops(), self.read_tty(), path.read_text(encoding="utf-8"), self.spawned),
                         ([], b"", before, []))

    def test_main_writes_none_and_twenty_are_kept(self):
        self.put(decided="off")
        self.handle("Stop", {}, role="main")
        self.assertEqual(self.stops(), [])
        for i in range(25):
            self.update_terminal(TERM, turn=i)
            self.handle("Stop", {})
        self.assertEqual([s["turn"] for s in self.stops()], list(range(5, 25)))

    def test_record_comes_before_the_tty_write(self):
        seen = []
        real = relay._write_once

        def spy(tty, data):
            seen.append(len(self.stops()))
            return real(tty, data)
        self.put(last="working")
        with mock.patch.object(relay, "_write_once", side_effect=spy):
            self.handle("Stop", {})
        self.assertEqual((seen, self.read_tty()), ([1], D))  # 쓸 때 그 Stop 의 기록이 이미 있다

    def test_record_failure_still_writes_the_tty(self):
        self.put(last="working")
        (self.home / "relay" / f"{TERM}.stops.json").mkdir()  # Stop 기록 자리에 폴더
        self.handle("Stop", {})
        self.assertEqual(self.read_tty(), D)
        self.assertRegex(self.log_lines()[-1], rf"^{UTC_Z} 오류\(Stop 기록\): ")

    def test_reverify_msg_turns_off(self):
        self.put(last="working", at=relay._now_ms() - 5000)
        self.set_status(state="working", msg="파일을 읽는다")  # Claude 는 일하는 중 보고에 msg 를 붙인다
        self.handle("Stop", {}, role="main")
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("off", b""))
        self.assertIn("off(다시 확인: Claude 가 스스로 보고한다)", self.log_lines()[-1])

    def test_reverify_by_status_time(self):
        at = relay._now_ms() - 5000
        self.set_status(state="idle")
        self.put(last="working", at=at)
        self.update_terminal(TERM, status_ms=at + 500)  # 대리 쓰기 직후의 변화: 우리 쓰기다
        self.handle("Stop", {}, role="main")
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", D))
        self.put(last="working", at=at)
        self.update_terminal(TERM, status_ms=at + 2000)  # 1초 넘게 뒤에 다른 상태: Claude 가 스스로 보고했다
        self.handle("Stop", {}, role="main")
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("off", b""))
        self.put(last="working", at=at)
        self.fail_hc("get", "timeout")  # 다시 확인할 수 없으면 그대로 쓴다
        self.handle("Stop", {}, role="main")
        self.assertEqual((self.rec()["decided"], self.read_tty()), ("on", D))


class ReaderTest(RelayCase):
    def test_stops_and_stop_for_turn(self):
        stops = [{"pid": 1, "turn": 3, "at": "2026-11-16T01:00:00Z", "background": [{"type": "shell"}]},
                 {"pid": 1, "turn": 3, "at": "2026-11-16T01:00:05Z", "background": []},
                 {"pid": 1, "turn": 4, "at": "2026-11-16T01:01:00Z", "background": [{"type": "subagent"}]},
                 {"pid": 1, "turn": None, "at": "2026-11-16T01:02:00Z", "background": [{"type": "monitor"}]},
                 {"pid": 1, "turn": 5, "at": "2026-11-16T01:03:00Z", "background": "깨짐"}, "깨진 항목"]
        (self.home / "relay").mkdir(mode=0o700)
        (self.home / "relay" / f"{TERM}.stops.json").write_text(json.dumps({"stops": stops}), encoding="utf-8")
        self.assertEqual(self.stops(), stops[:5])  # 사전이 아닌 항목은 뺀다
        self.assertEqual(relay.stop_for_turn(self.home, TERM, 3)["at"], "2026-11-16T01:00:05Z")  # 같은 turn 의 마지막
        self.assertEqual(relay.stop_for_turn(self.home, TERM, 4)["background"], [{"type": "subagent"}])
        self.assertEqual(relay.stop_for_turn(self.home, TERM, 5)["background"], [])  # 목록이 아니면 빈 목록
        for turn in (6, None, "4", True):
            self.assertIsNone(relay.stop_for_turn(self.home, TERM, turn), turn)
        self.assertEqual(relay.stops(self.home, "t99"), [])
        self.assertEqual(relay.stops(self.home, "a/b"), [])
        (self.home / "relay" / f"{TERM}.stops.json").write_text("{깨짐", encoding="utf-8")
        self.assertEqual(self.stops(), [])

    def test_record_and_write_failed(self):
        self.assertIsNone(self.rec())
        self.assertFalse(relay.write_failed(self.home, TERM))
        for decided in (None, "on", "off", "no_tty", "write_failed"):
            self.put(decided=decided)
            self.assertEqual(relay.write_failed(self.home, TERM), decided == "write_failed", decided)
        self.put(decided="bogus", blockers=[1], pending=3, write_failures="x", tty="")
        rec = self.rec()
        self.assertEqual((rec["decided"], rec["blockers"], rec["pending"], rec["write_failures"], rec["tty"]),
                         (None, {}, "idle", 0, None))  # 틀린 필드는 기본값
        for bad in ({"pid": "x", "started_ms": 1}, {"pid": 0, "started_ms": 1}, {"pid": 7}, [1]):
            (self.home / "relay" / f"{TERM}.json").write_text(json.dumps(bad), encoding="utf-8")
            self.assertIsNone(self.rec(), bad)
        self.assertIsNone(relay.record(self.home, "a/b"))


class FastPathTest(RelayCase):
    def test_quiet_record_needs_no_hc_and_no_lock(self):
        self.put(decided="off")
        before = len(self.hc_calls())
        with relay._locked(self.home, TERM):  # 다른 훅이 잠금을 쥐어도 기다리지 않는다
            t0 = time.monotonic()
            self.handle("PostToolUse", {"tool_name": "Read"})
            self.handle("PreToolUse", {"tool_name": "AskUserQuestion", "tool_use_id": "q"}, role="main")
            self.handle("Stop", {}, role="main")
            self.assertLess(time.monotonic() - t0, 1.0)
        self.assertEqual(len(self.hc_calls()), before)

    def test_another_claude_takes_the_slow_path(self):
        self.put(decided="off", pid=999999)  # 기록의 Claude 가 이 훅의 조상이 아니다(Claude 가 바뀌었다)
        self.decide_after(30)
        self.handle("PostToolUse", {"tool_name": "Read"})
        self.assertEqual((self.rec()["pid"], self.rec()["decided"]), (self.me, None))
        self.assertEqual(self.spawned, [(TERM, self.me, self.start)])

    def test_no_hc_near_the_hook_deadline(self):
        """훅 마감까지 hc 조회 시간(3초)이 남지 않았으면 hc 를 부르지 않는다(15초 훅 제한, Codex 계획 리뷰 r1)."""
        soon = time.monotonic() + 1
        relay.handle(self.home, "SessionStart", {"source": "startup"}, role="main", deadline=soon)
        self.assertIsNone(self.rec())  # 지금 Claude 를 모른다: 다음 사건에서 다시 한다
        self.put(last="working")
        relay.handle(self.home, "Stop", {}, role="worker", deadline=soon)
        self.assertEqual(self.hc_gets(), [])
        self.assertEqual(self.read_tty(), D)  # 기록의 Claude 는 ps 로 안다: 다시 확인 없이 쓴다
        self.assertEqual([s["turn"] for s in self.stops()], [None])


class SlowPsTest(HorchCase):
    """ps 가 느려도 훅 마감을 넘지 않는다(Codex 계획 리뷰 r3). ps 한 번의 시간 상한은 min(3초, 마감까지 남은 시간)이고, 남은
    시간이 없으면 그 사건의 대리 보고를 건너뛴다(빠른 길도 같다). PATH 앞에 30초 자는 ps 를 둔다."""

    def setUp(self):
        super().setUp()
        self.home.mkdir(mode=0o700)
        slow = self.tmp / "slow-bin"
        slow.mkdir()
        (slow / "ps").write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
        (slow / "ps").chmod(0o755)
        patcher = mock.patch.dict(os.environ, self._env(TERM, {"PATH": f"{slow}{os.pathsep}{self.env['PATH']}"}),
                                  clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.home / "relay").mkdir(mode=0o700)
        (self.home / "relay" / f"{TERM}.json").write_text(json.dumps(
            {"terminal": TERM, "pid": os.getpid(), "tty": None, "started_ms": 0, "decided": "off"}), encoding="utf-8")

    def test_ps_and_the_whole_event_keep_the_deadline(self):
        t0 = time.monotonic()
        self.assertIsNone(relay._ps_row(os.getpid(), time.monotonic() + 0.5))  # 시간 초과는 실패와 같다
        self.assertLess(time.monotonic() - t0, 2.0)
        with self.assertRaises(relay._Late):
            relay._ps_row(os.getpid(), time.monotonic() - 1)
        t0 = time.monotonic()
        relay.handle(self.home, "PostToolUse", {"tool_name": "Read"}, role="main", deadline=time.monotonic() + 0.5)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual(relay.record(self.home, TERM)["decided"], "off")
        relay.handle(self.home, "PostToolUse", {"tool_name": "Read"}, role="main", deadline=time.monotonic() - 1)
        self.assertIn(f"{TERM} 훅 마감(PostToolUse): 이 사건은 대리 보고하지 않았다",
                      (self.home / "relay.log").read_text(encoding="utf-8"))


class ProcessTest(HorchCase):
    """실제 ps 와 확인기 띄우기(쓰지 않는다)."""

    def test_ps_row_and_ancestors(self):
        row = relay._ps_row(os.getpid())
        self.assertEqual(row[0], os.getppid())
        self.assertLess(abs(row[2] - relay._now_ms()), 7 * 24 * 3600 * 1000)
        self.assertIsNotNone(relay._ancestor(os.getpid()))  # 자기 자신
        self.assertEqual(relay._ancestor(os.getppid())[1], relay._ps_row(os.getppid())[2])
        child = subprocess.Popen(["sleep", "5"])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertIsNone(relay._ancestor(child.pid))  # 자식은 조상이 아니다

    def test_spawn_runs_the_hook_checker_detached(self):
        with mock.patch.object(relay.subprocess, "Popen") as popen:
            relay._spawn(self.home, TERM, 4242, 1700000000000)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [sys.executable, str(relay.HOOK_SCRIPT), "relay-check", str(self.home), TERM, "4242",
                                   "1700000000000"])
        self.assertTrue(relay.HOOK_SCRIPT.is_file())
        self.assertEqual((kwargs["stdin"], kwargs["stdout"], kwargs["stderr"], kwargs["start_new_session"],
                          kwargs["cwd"]),
                         (subprocess.DEVNULL, subprocess.DEVNULL, subprocess.DEVNULL, True, str(self.home)))


if __name__ == "__main__":
    unittest.main()
