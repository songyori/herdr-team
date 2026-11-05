"""Claude Code 훅(설계 9.4): 역할 판별과 캐시, PreToolUse 가드, Stop, SessionStart."""
import json
import os
import subprocess
import sys
import unittest

from tests.helpers import COORD, MAIN, NONCE, ROOT, TeamCase
from hteam import state
from hteam.paths import Project

HOOK = ROOT / "hooks" / "hteam_hook.py"


class HookCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)

    def hook(self, event, payload=None, *, terminal=None, coordinator=False, env=None):
        e = dict(self.env, CLAUDE_PROJECT_DIR=str(self.proj))
        if terminal:
            e["HC_TERMINAL_ID"] = terminal
        if coordinator:
            e.update({"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": NONCE, "HC_TERMINAL_ID": COORD})
        e.update(env or {})
        body = {"session_id": "s1", "cwd": str(self.proj), **(payload or {})}
        proc = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(body), capture_output=True,
                              text=True, env=e, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def edit(self, path, **kw):
        return self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": str(self.proj / path)}}, **kw)

    def decision(self, out):
        return out and out["hookSpecificOutput"]["permissionDecision"]

    def worker_terminal(self, tid, role):
        self.write_spec(tid, role)
        state.create(self.p, tid, role)
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out["terminal"]

    def cached(self, sid):
        path = self.state_dir / "sessions" / sid
        return path.read_text().strip() if path.exists() else None

    def hook_log(self):
        path = self.state_dir / "hook-errors.log"
        return path.read_text() if path.exists() else ""


class RoleTest(HookCase):
    def test_no_project_does_nothing(self):
        e = dict(self.env)
        proc = subprocess.run([sys.executable, str(HOOK), "guard"], input=json.dumps(
            {"session_id": "s", "cwd": str(self.tmp), "tool_name": "Write", "tool_input": {"file_path": "/x"}}),
            capture_output=True, text=True, env=e, cwd=str(self.tmp))
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_main_session_start_caches_and_guides(self):
        self.hteam("notify", "--type", "question", "--json", "-", stdin=json.dumps({
            "question": "q?\n예: e", "options": [{"label": "a (추천)", "description": "추천 사유: x"},
                                                 {"label": "b", "description": "y"}]}))
        out = self.hook("session-start", terminal=MAIN)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("/herdr-team:up", ctx)
        self.assertIn("답하지 않은 질문이 1건", ctx)
        self.assertEqual((self.state_dir / "sessions" / "s1").read_text().strip(), "main")
        self.assertEqual((self.state_dir / "plugin-root").read_text().strip(), str(ROOT))

    def test_worker_and_reviewer_detection(self):
        term = self.worker_terminal("T-001", "planner")
        self.assertIsNone(self.hook("session-start", {"session_id": "w1"}, terminal=term))
        self.assertEqual((self.state_dir / "sessions" / "w1").read_text().strip(), "worker:planner")
        self.worker_terminal("T-002", "developer")
        self.act_work("T-002")
        rev = self.hteam("review", "T-002")[1]
        self.hook("role-mark", {"session_id": "r1"}, terminal=rev["terminal"])
        self.assertEqual((self.state_dir / "sessions" / "r1").read_text().strip(), "reviewer")

    def test_unsure_is_not_cached(self):
        out = self.hook("role-mark", {"session_id": "u1"}, terminal="t9",
                        env={"HERDR_ORCH_BIN": str(self.tmp / "none")})
        self.assertIsNone(out)
        self.assertFalse((self.state_dir / "sessions" / "u1").exists())

    def test_labeled_terminals_are_never_main(self):
        """끝난 Dispatch 의 워커 터미널은 horch status 에 없고 hc 라벨(horch.dispatch)만 남는다. 메인으로 보지 않는다."""
        self.add_terminal("t50", labels={"horch.dispatch": "dsp-old"})
        self.add_terminal("t51")
        self.update_terminal("t51", parent="t50")  # 워커 터미널 아래에서 띄운 터미널
        for sid, term in (("w1", "t50"), ("w2", "t51")):
            self.assertIsNone(self.hook("session-start", {"session_id": sid}, terminal=term), term)
            self.assertEqual(self.cached(sid), "worker", term)
            self.assertIsNone(self.hook("stop", {"session_id": sid}, terminal=term), term)
        # bind 전 코디네이터(라벨 hteam.role)와 그 아래 터미널, Run 소유자, nonce 가 맞지 않는 코디네이터 환경: 모름(캐시 안 함)
        self.add_terminal("t52", labels={"hteam.role": "coordinator"})
        self.add_terminal("t53")
        self.update_terminal("t53", parent="t52")
        cases = (("c1", "t52", None), ("c2", "t53", None), ("c3", COORD, None),
                 ("c4", COORD, {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": "old-nonce"}))
        for sid, term, env in cases:
            self.assertIsNone(self.hook("session-start", {"session_id": sid}, terminal=term, env=env), sid)
            self.assertIsNone(self.cached(sid), sid)
            self.assertIsNone(self.hook("stop", {"session_id": sid}, terminal=term, env=env), sid)
            out = self.hook("guard", {"session_id": sid, "tool_name": "Write",
                                      "tool_input": {"file_path": str(self.proj / "src/app.py")}}, terminal=term, env=env)
            self.assertIsNone(out, sid)  # 메인 가드(제품 파일 거부)가 걸리지 않는다
        # run.json 이 다른 터미널을 가리켜도 horch Run 소유자는 메인이 아니다
        run = json.loads((self.state_dir / "run.json").read_text())
        (self.state_dir / "run.json").write_text(json.dumps({**run, "coordinator_terminal": "t999"}))
        self.assertIsNone(self.hook("session-start", {"session_id": "c5"}, terminal=COORD))
        self.assertIsNone(self.cached("c5"))

    def test_hc_failure_is_not_cached(self):
        self.fail_hc("get", "timeout")
        self.assertIsNone(self.hook("session-start", terminal=MAIN))
        self.assertIsNone(self.cached("s1"))

    def test_session_start_redetects_stale_cache(self):
        """`claude --continue` 등으로 다른 터미널의 session id 를 이어 쓰면 캐시가 그 터미널의 역할이다. 다시 판별한다."""
        (self.state_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "sessions" / "s1").write_text("worker:developer\n")
        out = self.hook("session-start", terminal=MAIN)
        self.assertIn("/herdr-team:up", out["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self.cached("s1"), "main")
        # 확실하지 않으면 지난 캐시를 지운다
        self.assertIsNone(self.hook("session-start", terminal="t9", env={"HERDR_ORCH_BIN": str(self.tmp / "none")}))
        self.assertIsNone(self.cached("s1"))

    def test_unknown_cache_value_is_not_trusted(self):
        (self.state_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "sessions" / "s1").write_text("coordinator\n")  # 코디네이터는 캐시하지 않는다(늘 환경으로 본다)
        self.assertEqual(self.decision(self.edit("src/app.py", terminal=MAIN)), "deny")
        self.assertEqual(self.cached("s1"), "main")

    def test_corrupt_run_file_is_logged_and_role_unknown(self):
        (self.state_dir / "run.json").write_text("{")
        self.assertIsNone(self.edit("src/app.py", coordinator=True))  # 코디네이터인지 모른다: 코디네이터 가드를 걸지 않는다
        self.assertEqual(self.decision(self.edit(".herdr-team/state/run.json", coordinator=True)), "deny")
        self.assertIsNone(self.hook("session-start", {"session_id": "c"}, coordinator=True))
        self.assertIsNone(self.cached("c"))
        self.assertIn("bad_run_file", self.hook_log())


class GuardTest(HookCase):
    def test_state_dir_denied_for_everyone(self):
        for kw in ({"terminal": MAIN}, {"coordinator": True}):
            self.assertEqual(self.decision(self.edit(".herdr-team/state/tasks/T-001.json", **kw)), "deny")

    def test_coordinator_edits(self):
        self.assertEqual(self.decision(self.edit("src/app.py", coordinator=True)), "deny")
        self.assertIsNone(self.edit(".herdr-team/tasks/T-001.md", coordinator=True))
        out = self.hook("guard", {"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}, coordinator=True)
        self.assertIn("notify --type question", out["hookSpecificOutput"]["permissionDecisionReason"])

    def test_main_edits_and_setup_mode(self):
        self.assertEqual(self.decision(self.edit("src/app.py", terminal=MAIN)), "deny")
        for ok in ("CLAUDE.md", ".herdr-team/roles/developer.md", "docs/superpowers/x.md", ".claude/settings.json"):
            self.assertIsNone(self.edit(ok, terminal=MAIN), ok)
        (self.state_dir / "setup-mode").write_text("x")
        self.assertIsNone(self.edit("src/app.py", terminal=MAIN))

    def test_main_bash_horch_denied(self):
        for cmd in ("herdr-orch/bin/horch status", "python3 /x/bin/horch --home h check", "horch send"):
            out = self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": cmd}}, terminal=MAIN)
            self.assertEqual(self.decision(out), "deny", cmd)
        for cmd in (".herdr-team/bin/hteam tell hi", "ls herdr-orch/", "echo horchestra"):
            out = self.hook("guard", {"tool_name": "Bash", "tool_input": {"command": cmd}}, terminal=MAIN)
            self.assertIsNone(out, cmd)

    def test_worker_ask_hints(self):
        planner = self.worker_terminal("T-001", "planner")
        dev = self.worker_terminal("T-002", "developer")
        ask = {"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}
        out = self.hook("guard", {**ask, "session_id": "p"}, terminal=planner)
        self.assertIn("ask-user", out["hookSpecificOutput"]["permissionDecisionReason"])
        out = self.hook("guard", {**ask, "session_id": "d"}, terminal=dev)
        self.assertIn("horch ask", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.edit("src/app.py", terminal=dev))  # 워커의 owns 는 리뷰가 본다

    def test_main_context_guard_once(self):
        ctx = "## 계획 요약\n- 화면 셋과 저장소는 localStorage 로 정한다. 표는 아래와 같다. " * 2
        self.hteam("notify", "--type", "question", "--json", "-", stdin=json.dumps({
            "question": "이대로 확정할까요?\n예: 확정이면 개발을 시작한다", "context": ctx,
            "options": [{"label": "확정 (추천)", "description": "추천 사유: 빠진 항목이 없다"},
                        {"label": "수정", "description": "고칠 곳을 말한다"}]}))
        transcript = self.tmp / "t.jsonl"
        transcript.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "안녕"}]}}) + "\n")
        payload = {"tool_name": "AskUserQuestion", "transcript_path": str(transcript),
                   "tool_input": {"questions": [{"question": "이대로 확정할까요?\n예: 확정이면 개발을 시작한다"}]}}
        out = self.hook("guard", payload, terminal=MAIN)
        self.assertEqual(self.decision(out), "deny")
        self.assertIn("계획 요약", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIsNone(self.hook("guard", payload, terminal=MAIN))  # 같은 질문은 한 번만 거부


class StopTest(HookCase):
    def test_main_without_watch_is_blocked(self):
        out = self.hook("stop", terminal=MAIN)
        self.assertEqual(out["decision"], "block")
        self.assertIn("watch", out["reason"])
        self.assertIsNone(self.hook("stop", {"stop_hook_active": True}, terminal=MAIN))
        self.assertIsNone(self.hook("stop", {"session_id": "c"}, coordinator=True))

    def test_live_watch_or_dead_coordinator_passes(self):
        proc = self.hteam_bg("watch", as_="main")
        deadline = __import__("time").monotonic() + 10
        while not (self.state_dir / "watch.pid").exists():
            self.assertLess(__import__("time").monotonic(), deadline)
            __import__("time").sleep(0.05)
        self.assertIsNone(self.hook("stop", terminal=MAIN))
        proc.kill()
        proc.communicate()
        self.update_terminal(COORD, state="finished")
        self.assertIsNone(self.hook("stop", {"session_id": "s2"}, terminal=MAIN))

    def test_stale_watch_pid_is_not_a_watch(self):
        """watch.pid 는 기록일 뿐이다. 죽은 pid, 다른 프로세스(시작 시각이 다름)를 가리키는 pid 는 watch 가 아니다."""
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        for pid in (dead.pid, os.getpid()):
            (self.state_dir / "watch.pid").write_text(json.dumps({"pid": pid, "started": "Thu Jan  1 00:00:00 2026"}))
            out = self.hook("stop", terminal=MAIN)
            self.assertEqual(out and out["decision"], "block", pid)

    def test_corrupt_run_file_does_not_block_stop(self):
        (self.state_dir / "run.json").write_text("[]")
        self.assertIsNone(self.hook("stop", terminal=MAIN))
        log = self.hook_log()
        self.assertIn("stop", log)
        self.assertIn("bad_run_file", log)

    def test_hook_errors_are_logged_not_raised(self):
        (self.state_dir / "sessions").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "sessions" / "bad").mkdir()  # 캐시 파일 자리에 폴더: 읽기가 실패한다
        out = self.hook("guard", {"session_id": "bad", "tool_name": "Write",
                                  "tool_input": {"file_path": str(self.proj / "src/a.py")}}, terminal=MAIN)
        self.assertIsNone(out)
        self.assertIn("guard", (self.state_dir / "hook-errors.log").read_text())


class PathGuardTest(HookCase):
    def test_coordinator_outside_project_and_traversal(self):
        sibling = self.tmp / "sibling"
        sibling.mkdir()
        for raw in (str(sibling / "a.py"), str(self.proj / ".herdr-team/../../sibling/a.py"), "../sibling/a.py"):
            out = self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": raw}}, coordinator=True)
            self.assertEqual(self.decision(out), "deny", raw)
        link = self.proj / ".herdr-team" / "out"
        link.symlink_to(sibling)
        out = self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": str(link / "a.py")}},
                        coordinator=True)
        self.assertEqual(self.decision(out), "deny")

    def test_main_traversal_into_product_and_outside_scratch(self):
        out = self.hook("guard", {"tool_name": "Write",
                                  "tool_input": {"file_path": str(self.proj / ".herdr-team/../src/a.py")}}, terminal=MAIN)
        self.assertEqual(self.decision(out), "deny")
        out = self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": str(self.tmp / "scratch.txt")}},
                        terminal=MAIN)
        self.assertIsNone(out)  # 프로젝트 밖은 제품 파일이 아니다
        out = self.hook("guard", {"tool_name": "Write", "tool_input": {}}, terminal=MAIN)
        self.assertEqual(self.decision(out), "deny")

    def test_symlink_into_state_or_product(self):
        (self.proj / "src").mkdir()
        (self.team / "st").symlink_to(self.state_dir)
        (self.proj / ".claude").mkdir()
        (self.proj / ".claude" / "src").symlink_to(self.proj / "src")
        for kw in ({"terminal": MAIN}, {"coordinator": True}):
            self.assertEqual(self.decision(self.edit(".herdr-team/st/run.json", **kw)), "deny", kw)
            self.assertEqual(self.decision(self.edit(".herdr-team/State/run.json", **kw)), "deny", kw)  # 대소문자
        self.assertEqual(self.decision(self.edit(".claude/src/a.py", terminal=MAIN)), "deny")

    def test_unresolvable_path_denied_for_coordinator_and_main(self):
        loop = self.team / "loop"
        loop.symlink_to(loop)  # 자기 자신을 가리키는 링크: 풀 수 없다
        for raw in ("", str(loop / "a.md"), str(self.team / "a\0b.md"), ["x"]):
            for kw in ({"terminal": MAIN}, {"coordinator": True}):
                out = self.hook("guard", {"tool_name": "Write", "tool_input": {"file_path": raw}}, **kw)
                self.assertEqual(self.decision(out), "deny", (raw, kw))
        self.assertEqual(self.hook_log(), "")  # 훅 오류가 아니라 판단이다


if __name__ == "__main__":
    unittest.main()
