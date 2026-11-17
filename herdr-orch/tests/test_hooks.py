"""herdr-orch 훅(설계 16.2): hooks.json 의 사건·matcher·셸 거르기, horch_hook.py 의 대상·역할, 훅 실행.

훅 실행 시험은 기록을 이 시험 프로세스(훅의 부모. 시작 시각은 실제 ps 로 읽는다)의 것으로 미리 쓰고 tty 는 pty 쌍의
slave 다. 가짜 hc 의 foreground 는 비워 두어 훅이 기록을 새로 만들지 않는다(실제 터미널에 쓰지 않는다). 확인기 시험만
foreground 를 이 시험 프로세스로 주고, 확인기는 미리 쓴 기록의 tty 에만 쓴다.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import select
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import ROOT, HorchCase
from horch import relay

HOOKS_JSON = ROOT / "hooks" / "hooks.json"
HOOK = ROOT / "hooks" / "horch_hook.py"
TERM = "t61"
UTC_Z = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"
# 사건과 matcher(설계 16.2). None 은 matcher 없음(모든 도구)
EVENTS = {"SessionStart": "startup|resume|clear|compact", "UserPromptSubmit": None, "PreToolUse": "AskUserQuestion",
          "PostToolUse": None, "PostToolUseFailure": None, "PermissionRequest": None, "PermissionDenied": None,
          "Elicitation": None, "ElicitationResult": None, "Stop": None, "StopFailure": None, "SessionEnd": None}
COMMAND = ('[ -n "$HC_TERMINAL_ID" ] && [ -n "$HORCH_HOME$HORCH_RELAY_HOME" ] || exit 0; '
           'exec python3 "${CLAUDE_PLUGIN_ROOT}/hooks/horch_hook.py" ')


def load_hook():
    spec = importlib.util.spec_from_file_location("horch_hook_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HooksJsonTest(HorchCase):
    def test_events_matchers_and_commands(self):
        hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(hooks), set(EVENTS))
        for event, matcher in EVENTS.items():
            with self.subTest(event=event):
                (entry,) = hooks[event]
                self.assertEqual(entry.get("matcher"), matcher)
                self.assertEqual(entry["hooks"], [{"type": "command", "timeout": 15, "command": COMMAND + event}])
        self.assertEqual(relay.EVENTS, frozenset(EVENTS))

    def test_shell_filter_starts_no_python_outside_the_target(self):
        """HC_TERMINAL_ID 가 없거나 두 홈 변수가 모두 비면 파이썬을 띄우지 않고 exit 0(설계 16.2). PATH 앞의 가짜 python3 가
        불린 인자를 남긴다."""
        fake = self.tmp / "fake-bin"
        fake.mkdir()
        mark = self.tmp / "python-calls"
        (fake / "python3").write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$MARK"\n', encoding="utf-8")
        (fake / "python3").chmod(0o755)
        base = {"PATH": f"{fake}{os.pathsep}/usr/bin{os.pathsep}/bin", "CLAUDE_PLUGIN_ROOT": str(ROOT), "MARK": str(mark)}
        skip = ({}, {"HC_TERMINAL_ID": "t1"}, {"HORCH_HOME": "/h"}, {"HORCH_RELAY_HOME": "/h"},
                {"HC_TERMINAL_ID": "t1", "HORCH_HOME": "", "HORCH_RELAY_HOME": ""},
                {"HC_TERMINAL_ID": "", "HORCH_HOME": "/h"})
        run = ({"HC_TERMINAL_ID": "t1", "HORCH_HOME": "/h"}, {"HC_TERMINAL_ID": "t1", "HORCH_RELAY_HOME": "/h"})
        for event in EVENTS:
            for extra in (*skip, *run):
                proc = subprocess.run(["/bin/sh", "-c", COMMAND + event], env={**base, **extra}, capture_output=True,
                                      text=True, timeout=30)
                self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""), (event, extra))
        calls = mark.read_text(encoding="utf-8").splitlines()
        self.assertEqual(calls, [f"{ROOT}/hooks/horch_hook.py {event}" for event in EVENTS for _ in run])


class TargetTest(unittest.TestCase):
    def test_roles_from_the_environment(self):
        """HORCH_HOME 이면 worker, HORCH_RELAY_HOME 만 있으면 main, 둘 다 있으면 HORCH_HOME 의 worker. 절대 경로가 아니면
        대상이 아니다(설계 16.2)."""
        hook = load_hook()
        cases = (({"HORCH_HOME": "/w"}, (Path("/w"), "worker")),
                 ({"HORCH_RELAY_HOME": "/m"}, (Path("/m"), "main")),
                 ({"HORCH_HOME": "/w", "HORCH_RELAY_HOME": "/m"}, (Path("/w"), "worker")),
                 ({"HORCH_HOME": "", "HORCH_RELAY_HOME": "/m"}, (Path("/m"), "main")),
                 ({"HORCH_HOME": "rel"}, None), ({"HORCH_HOME": "rel", "HORCH_RELAY_HOME": "/m"}, None),
                 ({"HORCH_RELAY_HOME": "rel"}, None), ({}, None))
        for env, want in cases:
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True):
                self.assertEqual(hook.target(), want)
        self.assertEqual(hook.HOOK_DEADLINE_S, 12)


class HookRunTest(HorchCase):
    def setUp(self):
        super().setUp()
        self.home.mkdir(mode=0o700)
        self.master, slave = os.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, slave)
        self.tty = os.ttyname(slave)
        self.me = os.getpid()
        self.start = relay._ps_row(self.me)[2]
        self.add_terminal(TERM, argv=["claude"], status="idle", turn=3)  # foreground 는 기본 null

    def put(self, **fields):
        rec = {"terminal": TERM, "pid": self.me, "tty": self.tty, "started_ms": self.start, "decided": "on",
               "pending": "idle", "last": None, "at": None, "blockers": {}, "perm_tools": {}, "write_failures": 0,
               "notified": False, **fields}
        (self.home / "relay").mkdir(mode=0o700, exist_ok=True)
        (self.home / "relay" / f"{TERM}.json").write_text(json.dumps(rec), encoding="utf-8")

    def rec(self):
        return relay.record(self.home, TERM)

    def read_tty(self) -> bytes:
        chunks = []
        while select.select([self.master], [], [], 0.05)[0]:
            chunks.append(os.read(self.master, 4096))
        return b"".join(chunks)

    def log(self) -> str:
        path = self.home / "relay.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def hook(self, event, payload=None, *, homes=None, terminal=TERM, expect=""):
        """훅을 실제 프로세스로 돌린다(이 시험 프로세스의 자식). 늘 exit 0 이고, stdout 은 expect(기본: 출력 없음)다."""
        env = self._env(terminal, {"HORCH_HOME": str(self.home)} if homes is None else homes)
        proc = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps({"session_id": "s1", **(payload or {})}),
                              capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, expect, ""))

    def test_main_notice_blocks_one_stop(self):
        """메인의 Stop 에서 그 Stop 의 대리 쓰기가 실패하면 그 Stop 의 훅 출력으로 한 번 막는다(계획 리뷰 plan2 r1 의 1). 두 번째
        Stop·워커는 막지 않는다. 다른 훅이 막아 이어진 턴(stop_hook_active)에서도 처음이면 알린다."""
        block = json.dumps({"decision": "block", "reason": relay.NOTICE}, ensure_ascii=False) + "\n"
        main = {"HORCH_RELAY_HOME": str(self.home)}
        gone = str(self.tmp / "gone-tty")
        self.put(tty=gone, last="working")
        self.hook("Stop", {}, homes=main, expect=block)  # 같은 Stop 의 쓰기 실패
        self.hook("Stop", {}, homes=main)
        self.put(tty=gone, last="working")
        self.hook("Stop", {"background_tasks": []})  # 워커
        self.assertEqual((self.rec()["decided"], self.rec()["notified"]), ("write_failed", False))
        self.put(decided="no_tty", tty=None)
        self.hook("Stop", {"stop_hook_active": True}, homes=main, expect=block)
        self.assertTrue(self.rec()["notified"])
        self.hook("Stop", {}, homes=main)

    def test_worker_events_and_stop_record(self):
        self.put(last="working")
        ls = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.hook("PermissionRequest", ls)
        self.hook("PostToolUse", {**ls, "tool_use_id": "b1"})
        self.hook("Stop", {"background_tasks": []})
        self.hook("StopFailure", {"error": "rate_limit"})
        self.hook("SessionEnd", {"reason": "other"})
        self.assertEqual(self.read_tty(), relay.osc("blocked", "permission") + relay.osc("working") + relay.osc("done")
                         + relay.osc("error") + relay.osc("clear"))
        self.assertEqual([(s["pid"], s["turn"], s["background"]) for s in relay.stops(self.home, TERM)],
                         [(self.me, 3, [])])
        self.assertEqual(self.log(), "")

    def test_relay_home_is_the_main_role(self):
        self.put(last="working")
        ask = {"tool_name": "AskUserQuestion", "tool_use_id": "q1", "tool_input": {"questions": []}}
        main = {"HORCH_RELAY_HOME": str(self.home)}
        self.hook("PreToolUse", ask, homes=main)
        self.assertEqual(self.rec()["blockers"], {"tool:q1": "question"})
        self.hook("PostToolUse", ask, homes=main)
        self.hook("Stop", {"background_tasks": [{"type": "shell"}]}, homes=main)  # 메인 Stop 은 늘 done, Stop 기록 없음
        self.assertEqual(self.read_tty(), relay.osc("blocked", "question") + relay.osc("working") + relay.osc("done"))
        self.assertEqual(relay.stops(self.home, TERM), [])

    def test_horch_home_wins_over_relay_home(self):
        self.put(last="idle")
        other = self.tmp / "other-home"
        other.mkdir()
        ask = {"tool_name": "AskUserQuestion", "tool_use_id": "q1", "tool_input": {"questions": []}}
        self.hook("PreToolUse", ask, homes={"HORCH_HOME": str(self.home), "HORCH_RELAY_HOME": str(other)})
        self.assertEqual((self.rec()["blockers"], self.read_tty()), ({}, relay.osc("working")))  # 워커: 질문은 넣지 않는다
        self.assertFalse((other / "relay").exists())

    def test_outside_the_target_does_nothing(self):
        self.put(last="idle")
        for homes, terminal in (({"HORCH_HOME": "relative/home"}, TERM), ({}, TERM),
                                ({"HORCH_HOME": str(self.home)}, None)):
            self.hook("UserPromptSubmit", {}, homes=homes, terminal=terminal)
        self.assertEqual((self.read_tty(), self.rec()["last"], self.log()), (b"", "idle", ""))
        self.assertEqual(self.hc_calls(), [])

    def test_errors_are_logged_and_never_block(self):
        self.put()
        (self.home / "relay" / f"{TERM}.lock").mkdir()  # 잠금 파일을 열 수 없다
        self.hook("PostToolUse", {"tool_name": "Read", "tool_use_id": "r1"})
        self.assertRegex(self.log(), rf"^{UTC_Z} 오류\(PostToolUse\): IsADirectoryError: ")
        self.assertEqual(self.read_tty(), b"")

    def test_relay_check_writes_only_while_its_claude_is_the_foreground(self):
        """확인기(relay-check <홈> <터미널> <pid> <started_ms>, 훅 입력 없음)는 판정에 쓴 hc get 의 foreground 가 기록의
        Claude(이 시험 프로세스, 시작 시각은 실제 ps)일 때만 판정하고 pending 을 쓴다."""
        self.put(decided=None)

        def check(*args):
            argv = args or (str(self.home), TERM, str(self.me), str(self.start))
            proc = subprocess.run([sys.executable, str(HOOK), "relay-check", *argv], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, timeout=30,
                                  env=self._env(None, {"HORCH_HOME": str(self.home), "HORCH_TEST_RELAY_DECIDE_S": "0"}))
            self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))
        for fg in (None, {"pid": 999999, "name": "zsh", "argv": ["zsh"], "cwd": str(self.tmp)}):
            self.update_terminal(TERM, foreground=fg)
            check()
            self.assertEqual((self.rec()["decided"], self.read_tty()), (None, b""), fg)
        self.update_terminal(TERM, foreground={"pid": self.me, "name": "claude", "argv": ["claude"], "cwd": str(self.tmp)})
        check("relative/home", TERM, str(self.me), str(self.start))  # 상대 경로 홈: 아무것도 하지 않는다
        check(str(self.home), TERM, "x", str(self.start))  # 숫자가 아닌 pid: 오류 한 줄
        self.assertIsNone(self.rec()["decided"])
        self.assertIn("오류(relay-check): ValueError", self.log())
        check()
        self.assertEqual(self.rec()["decided"], "on")
        self.assertEqual(self.read_tty(), relay.osc("idle"))
        self.assertIn(f" {TERM} {self.me} on\n", self.log())

    def test_quiet_post_tool_is_fast_and_calls_no_hc(self):
        self.put(decided="off")
        t0 = time.monotonic()
        self.hook("PostToolUse", {"tool_name": "Read", "tool_use_id": "r1"})
        took = time.monotonic() - t0
        self.assertEqual(self.hc_calls(), [])  # hc 를 부르지 않는다
        self.assertLess(took, 1.0)  # 상한(설계 16.6). herdr-team 판에서 잰 값은 약 0.1초, on 세션의 느린 길은 약 0.2초

    def test_slow_ps_keeps_the_hook_within_its_deadline(self):
        """ps 가 느려도 훅은 마감(시작 + 12초)을 넘지 않는다(Codex 계획 리뷰 r3). 훅 모듈을 이 프로세스에 올려 main() 을
        부르고, 시작 시각을 11초 앞으로 당긴다(마감까지 1초)."""
        slow = self.tmp / "slow-bin"
        slow.mkdir()
        (slow / "ps").write_text("#!/bin/sh\nexec sleep 30\n", encoding="utf-8")
        (slow / "ps").chmod(0o755)
        self.put()  # 기록의 Claude 를 ps 로 확인해야 한다
        env = self._env(TERM, {"HORCH_HOME": str(self.home), "PATH": f"{slow}{os.pathsep}{self.env['PATH']}"})
        hook = load_hook()
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"tool_name": "Read"}))):
            hook.HOOK_START = time.monotonic() - 11
            self.assertEqual(hook.main(["PostToolUse"]), 0)
            done = time.monotonic()
        self.assertLess(done, hook.HOOK_START + hook.HOOK_DEADLINE_S + 0.5)
        self.assertEqual(self.read_tty(), b"")


if __name__ == "__main__":
    unittest.main()
