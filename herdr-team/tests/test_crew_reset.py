"""고정 에이전트 2(설계 5.9.7, 5.9.8, 8.6 의 인수인계 줄·not_started 줄, 8.5 의 7 단계): 리셋·인수인계, agent reset, 리셋 단계
이어 하기, 인수인계 Dispatch 이벤트, 끝나지 않은 인수인계 정리, 입력 유실 재투입, 묶음 끝 리셋 표시."""
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

from tests.helpers import CREW_CONFIG, MAIN, ROOT
from tests.test_crew import CrewCase, ago
from hteam import crew

HANDOFF_TITLE = "[handoff] production s1"
# 관제의 메시지 처리를 따로 띄운 프로세스에서 한다. HTEAM_TEST_DIE_AT 의 os._exit 가 시험 프로세스를 죽이지 않게
HANDLE_RUNNER = ("import json, sys; sys.path.insert(0, sys.argv[1]); from hteam import drive; from hteam.paths import Project; "
                 "drive.Drive(Project(sys.argv[2])).handle(json.loads(sys.argv[3]))")
CODEX_TEST = CREW_CONFIG.replace('roles = ["tester"]\nagent = "claude"\nmodel = "sonnet"',
                                 'roles = ["tester"]\nagent = "codex"\nmodel = "gpt-6.1-sol"').replace(
    '[roles.tester]\ntitle = "테스트"', '[roles.tester]\ntitle = "테스트"\nworker = "codex"')


class ResetCase(CrewCase):
    def setUp(self):
        super().setUp()
        self.env["HTEAM_RESET_TIMEOUT_MS"] = "400"  # /clear 뒤 turn 사건 마감(설계 10초)을 시험에서 줄인다
        self.t = self.first("T-001")  # 생산 에이전트: T-001 을 마쳤다(since_reset 1), 세션은 done 으로 쉰다

    def drive(self):
        return self.make_drive()

    def step(self, n=1):
        with self.in_drive():
            d = self.drive()
            for _ in range(n):
                d.reset_step()

    def handle(self, type_, did, body, sender=None):
        with self.in_drive():
            self.drive().handle(self.message(type_, did, body, sender=sender))

    def handoff_did(self) -> str:
        return self.entry()["resetting"]["dispatch"]

    def write_handoff(self, outcome="succeeded", summary="인수인계를 썼다"):
        """인수인계 워커가 docs/handoff/production.md 를 커밋하고 done 한다(템플릿의 끝내기)."""
        action = {"write": {"docs/handoff/production.md": "# 결정\n"}, "commit": "[handoff] production: 인수인계",
                  "done": {"outcome": outcome, "summary": summary}}
        code, out = self.act(self.handoff_did(), action)
        self.assertEqual(code, 0, out)
        return out

    def done_body(self, did, outcome="succeeded", summary="인수인계를 썼다"):
        return {"dispatch": did, "task": self.dispatch_row(did)["task_id"], "outcome": outcome, "summary": summary,
                "report_path": None, "files_modified": []}

    def observed(self, did, kind, key="1", status=None):
        return {"dispatch": did, "kind": kind, "key": key, "terminal": self.t, "status": status}

    def keys(self) -> list[list[str]]:
        return [k["keys"] for k in self.hc_state().get("keys", []) if k["terminal"] == self.t]

    def on_clear(self, mode):
        with self._hc_locked() as st:
            st.setdefault("on_clear", {})[self.t] = mode

    def mark(self):
        self.set_entry(reset_pending=True)


class MarkTest(ResetCase):
    def test_batch_mark_only_agents_with_work(self):
        with self.in_drive():
            self.assertEqual(crew.mark_batch_reset(self.p), ["production"])
            self.assertEqual(crew.mark_batch_reset(self.p), ["production"])  # 멱등
        self.assertTrue(self.entry()["reset_pending"])
        self.assertNotIn("test", self.crew_json())  # 일한 적 없는 에이전트는 표시하지 않는다

    def test_agent_reset_command(self):
        code, out = self.hteam("agent", "reset", "test")  # 관제에서 부르면 바로 한다(entry 가 없으면 만든다)
        self.assertEqual((code, out), (0, {"ok": True, "name": "test", "reset_pending": True}))
        self.assertTrue(self.entry("test")["reset_pending"])
        code, out = self.hteam("agent", "reset", "nope")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                         (2, "unknown_crew", "고정 에이전트가 아니다: nope. 가능한 이름: production, test"), out)
        code, out = self.hteam("agent", "reset", "nope", as_="main")  # 메인 쪽 검사도 큐에 넣기 전에 거부한다
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_crew"), out)

    def test_agent_reset_without_crew(self):
        self.set_config(CREW_CONFIG.split("[crew.production]")[0])
        code, out = self.hteam("agent", "reset", "production")
        self.assertEqual((code, out["error"]["message"]), (2, "고정 에이전트가 아니다: production. 가능한 이름: 없음"), out)


class ResetFlowTest(ResetCase):
    def test_handoff_then_clear_resets_in_place(self):
        self.mark()
        self.step()
        e = self.entry()
        self.assertEqual(e["resetting"]["step"], "handoff")
        did = e["resetting"]["dispatch"]
        row = self.dispatch_row(did)
        self.assertEqual((row["title"], row["terminal"], row["persistent"]), (HANDOFF_TITLE, self.t, 1))
        spec = (self.state_dir / "crew/production-handoff-s1.md").read_text(encoding="utf-8")
        self.assertIn('너는 herdr-team 의 고정 에이전트 "생산"(production) 다.', spec)
        self.assertIn("`docs/handoff/production.md`", spec)
        self.assertIn('git commit -m "[handoff] production: 인수인계" -- docs/handoff/production.md', spec)
        self.assertNotIn("{{", spec)
        self.assertTrue(any("production 리셋 시작: handoff" in x for x in self.log_lines()), self.log_lines())
        self.write_handoff()
        turn = self.terminals()[self.t]["turn"]
        self.handle("worker_done", did, self.done_body(did))
        self.assertEqual(self.keys()[-1], ["/", "c", "l", "e", "a", "r", "enter"])  # Claude 는 이름 없이(--name 제목이 남는다)
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["since_reset"], e["reset_tasks"], e["terminal"]),
                         (None, False, 0, [], self.t))  # 같은 터미널 주소(제자리 비우기)
        self.assertRegex(e["last_reset_at"], r"[+-]\d\d:\d\d$")
        self.assertEqual(self.dispatch_row(did)["state"], "released")
        self.assertTrue(any(f"production 리셋: reset(turn {turn + 1}, " in x for x in self.log_lines()), self.log_lines())
        self.assertTrue((self.proj / "docs/handoff/production.md").is_file())

    def test_next_task_after_reset_reads_handoff_and_uses_new_turn(self):
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.handle("worker_done", did, self.done_body(did))
        turn = self.terminals()[self.t]["turn"]
        out = self.started("T-002")
        self.assertEqual((out["terminal"], out["start_turn"]), (self.t, turn))  # 비우기가 올린 turn 이 다음 기준이다
        spec = (self.state_dir / "tasks/T-002/r1-work.md").read_text(encoding="utf-8")
        self.assertIn("먼저 `docs/handoff/production.md` 를 읽는다.", spec)

    def test_codex_clear_gets_agent_name(self):
        self.set_config(CODEX_TEST)
        out = self.started("T-005", "tester")
        t = out["terminal"]
        self.work("T-005")
        self.free("T-005")
        self.ready(t)
        self.set_entry("test", reset_pending=True)
        self.step()
        did = self.entry("test")["resetting"]["dispatch"]
        self.assertEqual(self.dispatch_row(did)["title"], "[handoff] test s1")
        self.act(did, {"write": {"docs/handoff/test.md": "x\n"}, "commit": "[handoff] test: 인수인계",
                       "done": {"outcome": "succeeded", "summary": "썼다"}})
        self.handle("worker_done", did, self.done_body(did))
        keys = [k["keys"] for k in self.hc_state()["keys"] if k["terminal"] == t][-1]
        self.assertEqual(keys, ["/", "c", "l", "e", "a", "r", "space", "t", "e", "s", "t", "enter"])  # /clear test
        self.assertIsNone(self.entry("test")["resetting"])

    def test_done_mid_turn_waits_then_clears_in_place(self):
        """실제 에이전트는 done 명령을 턴 안에서 부른다: worker_done 이 올 때 작업 세션은 아직 working 이다(6단계 실환경).
        terminal-reset 이 terminal_not_ready 로 아무것도 치지 않았으면 세션을 닫지 않고 clear 단계로 남아 다음 틱에 다시 한다."""
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        turn = self.terminals()[self.t]["turn"]
        self.ready(self.t, status="working", turn=turn)  # done 을 부른 턴이 아직 끝나지 않았다
        self.handle("worker_done", did, self.done_body(did))
        e = self.entry()
        self.assertEqual((e["terminal"], (e["resetting"] or {}).get("step"), (e["resetting"] or {}).get("clear_error")),
                         (self.t, "clear", None))
        self.assertIn(self.t, self.terminals())  # 닫지 않았다
        self.assertEqual(self.keys(), [])
        self.step(2)  # 아직 일하는 중: 다시 미루고 로그는 한 줄
        lines = [x for x in self.log_lines() if "production 리셋 미룸: 작업 세션이 일하는 중(working)" in x]
        self.assertEqual(len(lines), 1, self.log_lines())
        self.assertRegex(self.entry()["reset_busy_since"], r"[+-]\d\d:\d\d$")
        self.ready(self.t, status="done", turn=turn)  # 턴이 끝났다
        self.step()
        e = self.entry()
        self.assertEqual(self.keys()[-1], ["/", "c", "l", "e", "a", "r", "enter"])
        self.assertEqual((e["resetting"], e["reset_pending"], e["terminal"], e["reset_busy_since"]),
                         (None, False, self.t, None))  # 같은 터미널 주소(제자리 비우기)
        self.assertTrue(any(f"production 리셋: reset(turn {turn + 1}, " in x for x in self.log_lines()), self.log_lines())

    def test_done_mid_turn_busy_too_long_goes_to_new_terminal(self):
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.ready(self.t, status="working", turn=self.terminals()[self.t]["turn"])
        self.handle("worker_done", did, self.done_body(did))
        self.set_entry(reset_busy_since=ago(31 * 60 + 5))
        self.step()
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"], e["reset_busy_since"]),
                         (None, None, False, None))
        self.assertNotIn(self.t, self.terminals())  # terminal-close 가 끄고 지웠다
        self.assertTrue(any("production 리셋: new_terminal(terminal_not_ready)" in x for x in self.log_lines()),
                        self.log_lines())

    def test_late_handoff_observation_in_clear_step_is_ignored(self):
        """clear 단계(인수인계 Dispatch 가 이미 끝났다)에서 그 Dispatch 의 늦은 observed 는 무시한다. 관제 재시작 뒤 재확인이
        메일보다 먼저 clear 로 넘기면 지난 두 번째 idle 이 남아 있다(Codex 커밋 리뷰 558d54d). 리셋을 취소하지 않는다."""
        self.mark()
        self.step()
        did = self.handoff_did()
        self.handle("observed", did, self.observed(did, "idle", "2", "done"), sender="horch")  # 첫 idle: done 요청
        self.assertTrue(self.entry()["resetting"]["idle_asked"])
        self.write_handoff()
        turn = self.terminals()[self.t]["turn"]
        self.ready(self.t, status="working", turn=turn)
        self.handle("worker_done", did, self.done_body(did))
        self.assertEqual(self.entry()["resetting"]["step"], "clear")
        self.handle("observed", did, self.observed(did, "idle", "3", "done"), sender="horch")  # 늦게 처리된 두 번째 idle
        e = self.entry()
        self.assertEqual(((e["resetting"] or {}).get("step"), e["reset_pending"], e["terminal"]), ("clear", True, self.t))
        self.assertEqual(self.decides(), [])
        self.assertTrue(any(f"production 인수인계 Dispatch 의 observed 무시(clear 단계): {did}" in x
                            for x in self.log_lines()), self.log_lines())
        self.ready(self.t, status="done", turn=turn)  # 턴이 끝났다
        self.step()
        e = self.entry()
        self.assertEqual(self.keys()[-1], ["/", "c", "l", "e", "a", "r", "enter"])
        self.assertEqual((e["resetting"], e["reset_pending"], e["terminal"]), (None, False, self.t))

    def test_reset_timeout_goes_to_new_terminal(self):
        self.on_clear("none")  # /clear 뒤 turn 사건이 오지 않는다
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.handle("worker_done", did, self.done_body(did))
        e = self.entry()
        self.assertEqual((e["terminal"], e["work_pane"], e["resetting"], e["reset_pending"], e["since_reset"]),
                         (None, None, None, False, 0))
        self.assertNotIn(self.t, self.terminals())  # terminal-close 가 끄고 지웠다
        self.assertTrue(any("production 리셋: new_terminal(reset_timeout)" in x for x in self.log_lines()), self.log_lines())
        out = self.started("T-002")  # 다음 태스크가 새 세션을 띄운다
        self.assertNotEqual(out["terminal"], self.t)

    def test_close_failure_retries_then_decides_on_third(self):
        self.on_clear("none")
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.fail_hc("kill", "timeout")
        self.handle("worker_done", did, self.done_body(did))
        e = self.entry()
        self.assertEqual((e["resetting"]["step"], e["close_failures"], e["terminal"]), ("clear", 1, self.t))
        clears = len(self.keys())
        self.step()  # 닫기만 다시 한다(비우기를 다시 하지 않는다)
        self.assertEqual((self.entry()["close_failures"], len(self.keys())), (2, clears))
        self.assertEqual(self.decides(), [])
        self.step()
        e = self.entry()
        self.assertEqual((e["resetting"], e["terminal"]), (None, None))  # 세 번째: decide 를 올리고 터미널을 잊는다
        d = self.decides()
        self.assertEqual(len(d), 1, d)
        self.assertTrue(d[0]["summary"].startswith("production 에이전트 세션을 비우지도 닫지도 못했다: "), d[0])
        self.assertTrue(d[0]["summary"].endswith(". 사용자에게 그 에이전트 탭의 작업 pane 을 닫아 달라고 한다"), d[0])

    def test_failed_handoff_keeps_session(self):
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff(outcome="failed", summary="쓸 것이 없다")
        self.handle("worker_done", did, self.done_body(did, "failed", "쓸 것이 없다"))
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["since_reset"], e["terminal"]), (None, False, 1, self.t))
        self.assertEqual(self.keys(), [])  # 비우지 않는다
        self.assertEqual(self.dispatch_row(did)["state"], "released")
        d = self.decides()
        self.assertEqual((len(d), d[0]["kind"], d[0]["summary"], d[0]["commands"]),
                         (1, "escalation", "production 에이전트가 인수인계를 쓰지 못했다: 쓸 것이 없다",
                          ["hteam agent reset production"]))

    def test_waits_while_agent_has_work(self):
        self.mark()
        self.set_entry(task="T-009", dispatch="dsp-x")
        self.step()
        self.assertIsNone(self.entry()["resetting"])
        self.set_entry(task=None, dispatch=None, queue=["T-001"])
        self.step()
        self.assertIsNone(self.entry()["resetting"])

    def test_no_terminal_is_skipped(self):
        self.set_entry(terminal=None, reset_pending=True)
        self.step()
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["since_reset"], e["reset_tasks"], e["resetting"]), (False, 0, [], None))
        self.assertTrue(any("production 리셋 시작: skipped" in x for x in self.log_lines()), self.log_lines())

    def test_dead_terminal_is_skipped(self):
        self.update_terminal(self.t, state="finished")
        self.mark()
        self.step()
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["terminal"], e["since_reset"]), (False, None, 0))


class ResetDeferTest(ResetCase):
    def test_busy_session_defers_with_one_log_then_cancels_after_30_minutes(self):
        self.mark()
        self.ready(self.t, status="working")  # 자동 압축 중이거나 사람이 친 글
        self.step(2)
        lines = [x for x in self.log_lines() if "production 리셋 미룸: 작업 세션이 일하는 중(working)" in x]
        self.assertEqual(len(lines), 1, self.log_lines())
        self.assertRegex(self.entry()["reset_busy_since"], r"[+-]\d\d:\d\d$")
        self.assertIsNone(self.entry()["resetting"])
        self.set_entry(reset_busy_since=ago(31 * 60 + 5))
        self.step()
        e = self.entry()
        self.assertEqual(e["reset_pending"], False)
        d = self.decides()
        self.assertEqual(len(d), 1, d)
        self.assertEqual(d[0]["summary"], "production 에이전트의 작업 세션이 31분 넘게 일하는 중이라 리셋(인수인계)을 취소했다. "
                                          "그 탭을 확인한 뒤 필요하면 다시 요청한다")

    def test_unknown_terminal_cancels_after_30_minutes(self):
        self.mark()
        self.delay_get(self.t)
        self.step()
        self.assertRegex(self.entry()["reset_unknown_since"], r"[+-]\d\d:\d\d$")
        self.assertEqual(self.decides(), [])
        self.set_entry(reset_unknown_since=ago(31 * 60 + 5))
        self.step()
        self.assertEqual(self.entry()["reset_pending"], False)
        d = self.decides()
        self.assertEqual(d[0]["summary"], "production 에이전트의 작업 터미널 상태를 31분 넘게 알 수 없어 리셋(인수인계)을 "
                                          "취소했다. 터미널을 확인한 뒤 필요하면 다시 요청한다")

    def test_no_status_or_error_counts_as_unknown(self):
        self.mark()
        for word in ("error", None):
            self.ready(self.t, status=word)
            self.step()
            self.assertIsNone(self.entry()["resetting"])
            self.assertTrue(self.entry()["reset_unknown_since"])

    def test_streak_resets_when_reset_not_needed(self):
        self.mark()
        self.ready(self.t, status="working")
        self.step()
        self.set_entry(task="T-009", dispatch="dsp-x")  # 그 사이 태스크를 받았다: 연속 구간이 끊겼다
        self.step()
        e = self.entry()
        self.assertEqual((e["reset_busy_since"], e["reset_unknown_since"]), (None, None))

    def test_insert_failures_decide_only_on_third_with_cause(self):
        self.mark()
        with self._hc_locked() as st:
            st["on_send"] = {self.t: "mismatch"}  # 보내기 직전 일을 시작했다(terminal_not_ready)
        self.step()
        self.step()
        self.assertEqual((self.entry()["reset_failures"], self.decides()), (2, []))
        self.assertTrue(any("production 리셋 시작: failed(2/3): terminal_not_ready: " in x for x in self.log_lines()),
                        self.log_lines())
        self.assertIsNone(self.entry()["resetting"])
        self.step()
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["resetting"]), (False, None))
        d = self.decides()
        self.assertEqual(len(d), 1, d)
        self.assertTrue(d[0]["summary"].startswith("production 에이전트에 인수인계 태스크를 3번 넣지 못해 리셋을 취소했다: "
                                                   "terminal_not_ready: "), d[0])
        self.assertTrue(d[0]["summary"].endswith(". 작업 세션이 자동 압축 중이거나 다른 일을 하면 실패한다. 화면을 본 뒤 다시 "
                                                 "요청한다"), d[0])
        titles = [r["title"] for r in self.horch("worker-list")[1]["workers"] if r["title"].startswith("[handoff]")]
        self.assertTrue(all(r["state"] == "launch_failed" for r in self.horch("worker-list")[1]["workers"]
                            if r["title"].startswith("[handoff]")), titles)  # horch 가 실패한 넣기를 닫는다(고아 Task 없음)


class ResetResumeTest(ResetCase):
    def test_starting_resumes_by_title(self):
        """인수인계를 넣는 중(starting) 관제가 죽었다. 그 제목의 Dispatch 가 있으면 이어 붙인다."""
        spec = self.state_dir / "crew/production-handoff-s1.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text("인수인계\n", encoding="utf-8")
        code, out = self.horch("worker-start", "--terminal", self.t, "--title", HANDOFF_TITLE, "--spec-file", str(spec))
        self.assertEqual(code, 0, out)
        self.set_entry(reset_pending=True, resetting={"step": "starting", "title": HANDOFF_TITLE, "at": ago(5)})
        self.step()
        e = self.entry()
        self.assertEqual((e["resetting"]["step"], e["resetting"]["dispatch"]), ("handoff", out["dispatch"]))
        handoffs = [r for r in self.horch("worker-list")[1]["workers"] if r["title"] == HANDOFF_TITLE]
        self.assertEqual(len(handoffs), 1)  # 다시 넣지 않았다

    def test_starting_without_dispatch_inserts_again(self):
        self.set_entry(reset_pending=True, resetting={"step": "starting", "title": HANDOFF_TITLE, "at": ago(5)})
        self.step()
        e = self.entry()
        self.assertEqual(e["resetting"]["step"], "handoff")
        self.assertEqual(self.dispatch_row(e["resetting"]["dispatch"])["title"], HANDOFF_TITLE)

    def test_clear_step_resumes(self):
        """비우기(clear) 단계에서 관제가 죽었다. 다시 뜬 관제가 비우기를 이어 한다."""
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.assertEqual(self.horch("worker-release", "--dispatch", did)[0], 0)
        self.set_entry(resetting={"step": "clear", "dispatch": did, "at": ago(5)})
        self.step()
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["since_reset"]), (None, False, 0))
        self.assertEqual(len(self.keys()), 1)

    def test_handoff_step_waits(self):
        self.mark()
        self.step()
        did = self.handoff_did()
        self.step()  # handoff 단계는 넘어간다(끝은 worker_done 이나 재확인)
        self.assertEqual(self.entry()["resetting"]["dispatch"], did)
        self.assertEqual(len([r for r in self.horch("worker-list")[1]["workers"] if r["title"].startswith("[handoff]")]), 1)


class HandoffEventTest(ResetCase):
    def setUp(self):
        super().setUp()
        self.mark()
        self.step()
        self.did = self.handoff_did()

    def dispatch_messages(self) -> list[dict]:
        conn = sqlite3.connect(self.horch_home / "orch.db")
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT subject, body FROM messages WHERE mailbox=?",
                                                   (f"dispatch:{self.did}",))]
        finally:
            conn.close()

    def test_idle_twice_asks_then_abandons_and_releases(self):
        self.handle("observed", self.did, self.observed(self.did, "idle", "2", "done"), sender="horch")
        msgs = self.dispatch_messages()
        self.assertEqual([m["subject"] for m in msgs], ["done 요청"])
        self.assertEqual(msgs[0]["body"], "턴을 마쳤는데 done 이 없다. 일이 끝났으면 프리앰블의 done 명령을 부른다. 남았으면 "
                                          "이어서 하고 끝나면 done 을 부른다.")
        self.assertEqual(self.decides(), [])
        self.handle("observed", self.did, self.observed(self.did, "idle", "3", "done"), sender="horch")
        self.assertEqual(self.dispatch_row(self.did)["state"], "released")  # abandon --keep-terminal 뒤 release
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["terminal"]), (None, False, self.t))
        self.assertEqual(self.terminals()[self.t]["state"], "live")
        d = self.decides()
        self.assertEqual(len(d), 1)
        self.assertTrue(d[0]["summary"].startswith("production 에이전트가 인수인계를 쓰지 못했다"), d[0])

    def test_blocked_decides(self):
        self.handle("observed", self.did, self.observed(self.did, "blocked", "2", "blocked"), sender="horch")
        d = self.decides()
        self.assertEqual(len(d), 1)
        self.assertTrue(d[0]["summary"].startswith("production 에이전트가 인수인계 중 blocked 로 멈췄다("), d[0])
        self.assertTrue(d[0]["summary"].endswith("). 사용자에게 그 탭을 보게 한다"), d[0])
        self.assertEqual(self.entry()["resetting"]["dispatch"], self.did)  # 정리는 30분 뒤 재확인이 한다

    def test_exited_forgets_terminal(self):
        self.update_terminal(self.t, state="finished")
        self.handle("observed", self.did, self.observed(self.did, "exited", "exited"), sender="horch")
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"], e["since_reset"]), (None, None, False, 0))
        d = self.decides()
        self.assertEqual((len(d), d[0]["summary"]), (1, "production 에이전트가 인수인계 중 끝났다"))

    def test_handoff_message_is_not_a_task_message(self):
        with self.in_drive():
            d = self.drive()
            self.assertTrue(d.handoff_message(self.message("observed", self.did, self.observed(self.did, "blocked", "5"),
                                                           sender="horch")))
            self.assertFalse(d.handoff_message(self.message("observed", "dsp-other", {"kind": "idle"}, sender="horch")))


class HandoffCheckTest(ResetCase):
    def setUp(self):
        super().setUp()
        self.mark()
        self.step()
        self.did = self.handoff_did()

    def check(self):
        with self.in_drive():
            self.drive().handoff_check()

    def test_missed_worker_done_is_found(self):
        self.write_handoff()  # done 은 했지만 메시지를 놓쳤다
        self.check()
        e = self.entry()
        self.assertEqual((e["resetting"], e["since_reset"]), (None, 0))
        self.assertEqual(len(self.keys()), 1)

    def test_stuck_handoff_is_abandoned_after_30_minutes(self):
        self.check()
        self.assertEqual(self.entry()["resetting"]["dispatch"], self.did)  # 30분 전에는 둔다
        res = dict(self.entry()["resetting"], at=ago(31 * 60))
        self.set_entry(resetting=res)
        self.check()
        self.assertEqual(self.dispatch_row(self.did)["state"], "released")
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["terminal"]), (None, False, self.t))
        d = self.decides()
        self.assertEqual((len(d), d[0]["summary"]), (1, "production 에이전트 인수인계가 끝나지 않았다"))


class NotStartedTest(CrewCase):
    def setUp(self):
        super().setUp()
        self.t = self.first("T-001")
        self.out = self.started("T-002")

    def not_started_msg(self, did, status="done"):
        self.update_terminal(self.t, status=status)
        body = {"dispatch": did, "kind": "not_started", "key": "1", "terminal": self.t, "status": status,
                "start_turn": 1, "turn": 1, "delivery": {"attempted": True}}
        return self.message("observed", did, body, sender="horch")

    def not_started(self, did, status="done"):
        msg = self.not_started_msg(did, status)
        with self.in_drive():
            self.make_drive().handle(msg)

    def task_dispatches(self, horch_task) -> list[dict]:
        conn = sqlite3.connect(self.horch_home / "orch.db")
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT id, state FROM dispatches WHERE task_id=? ORDER BY rowid",
                                                  (horch_task,))]
        finally:
            conn.close()

    def test_death_after_resend_attaches_the_new_dispatch(self):
        """재투입이 새 Dispatch 를 띄운 뒤 기록 전에 관제가 죽었다(설계 5.9.8 의 resend). ack 전이라 다시 온 not_started 는
        다시 넣지 않고 그 Dispatch 를 이어 붙인다(그 Dispatch 의 메시지가 지난 것으로 버려지지 않게)."""
        first = self.out["dispatch"]
        horch_task = self.dispatch_row(first)["task_id"]
        msg = self.not_started_msg(first)
        proc = subprocess.run([sys.executable, "-c", HANDLE_RUNNER, str(ROOT / "lib"), str(self.proj), json.dumps(msg)],
                              capture_output=True, text=True, timeout=60,
                              env=self._env("drive", None, {"HTEAM_TEST_DIE_AT": "resend_started"}))
        self.assertEqual(proc.returncode, 137, proc.stderr)
        self.assertEqual(self.work_dispatch("T-002"), first)  # 새 Dispatch 를 띄웠지만 기록하지 못했다
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["work"]["resend"], {"from": first, "n": 1})
        rows = self.task_dispatches(horch_task)
        self.assertEqual([r["state"] for r in rows], ["abandoned", "active"])
        with self.in_drive():
            self.make_drive().handle(msg)  # 같은 메시지가 다시 온다
        st = self.task_state("T-002")
        self.assertEqual((self.work_dispatch("T-002"), self.entry()["dispatch"]), (rows[1]["id"], rows[1]["id"]))
        self.assertEqual(st["unknown_starts"], 1)
        self.assertNotIn("resend", st["rounds"][-1]["work"])
        self.assertEqual(len(self.task_dispatches(horch_task)), 2)  # 다시 넣지 않았다
        self.assertEqual(sum("T-002 not_started: resent(1)" in x for x in self.log_lines()), 1)

    def test_death_after_abandon_and_unknown_terminal_is_resumed_by_reconcile(self):
        """재투입이 앞 Dispatch 를 abandon 한 뒤 새 Dispatch 를 띄우기 전에 관제가 죽었다. 다시 온 not_started 를 처리할 때
        작업 터미널 상태를 알 수 없으면 resend 를 남기고, 그 메시지가 ack 된 뒤에도 재확인이 이어서 다시 넣는다(설계 5.9.8,
        8.7)."""
        first = self.out["dispatch"]
        horch_task = self.dispatch_row(first)["task_id"]
        msg = self.not_started_msg(first)
        proc = subprocess.run([sys.executable, "-c", HANDLE_RUNNER, str(ROOT / "lib"), str(self.proj), json.dumps(msg)],
                              capture_output=True, text=True, timeout=60,
                              env=self._env("drive", None, {"HTEAM_TEST_DIE_AT": "resend_abandoned"}))
        self.assertEqual(proc.returncode, 137, proc.stderr)
        self.assertEqual([r["state"] for r in self.task_dispatches(horch_task)], ["abandoned"])
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["work"]["resend"], {"from": first, "n": 1})
        self.delay_get(self.t, 4.0)  # 작업 터미널의 hc get 이 3초 확인을 넘긴다: 상태를 알 수 없다
        with self.in_drive():
            self.make_drive().handle(msg)  # 같은 메시지가 다시 온다(이 처리 뒤 ack 된다)
        self.assertEqual(self.task_state("T-002")["rounds"][-1]["work"]["resend"], {"from": first, "n": 1})  # 남긴다
        self.assertEqual(len(self.task_dispatches(horch_task)), 1)
        self.undelay()
        with self.in_drive():
            d = self.make_drive()
            d.write_workers()
            d.reconcile_task(self.task_state("T-002"))  # 메시지 없이 재확인이 잇는다
        rows = self.task_dispatches(horch_task)
        self.assertEqual([r["state"] for r in rows], ["abandoned", "active"])
        st = self.task_state("T-002")
        self.assertEqual((self.work_dispatch("T-002"), self.entry()["dispatch"], st["unknown_starts"]),
                         (rows[1]["id"], rows[1]["id"], 1))
        self.assertNotIn("resend", st["rounds"][-1]["work"])
        self.assertEqual(sum("T-002 not_started: resent(1)" in x for x in self.log_lines()), 1)
        self.assertEqual([x for x in self.decides() if x["task"] == "T-002"], [])

    def test_resend_same_round_then_decide_on_third(self):
        first = self.out["dispatch"]
        horch_task = self.dispatch_row(first)["task_id"]
        self.not_started(first)
        did2 = self.work_dispatch("T-002")
        self.assertNotEqual(did2, first)
        self.assertEqual(self.dispatch_row(first)["state"], "abandoned")  # worker-abandon --keep-terminal
        row = self.dispatch_row(did2)
        self.assertEqual((row["task_id"], row["terminal"], row["persistent"]), (horch_task, self.t, 1))  # 같은 Task, 같은 터미널
        st = self.task_state("T-002")
        self.assertEqual((st["round"], st["unknown_starts"], self.entry()["dispatch"]), (1, 1, did2))
        self.assertTrue(any("T-002 not_started: resent(1)" in x for x in self.log_lines()), self.log_lines())
        self.not_started(did2)
        did3 = self.work_dispatch("T-002")
        self.assertEqual(self.task_state("T-002")["unknown_starts"], 2)
        self.not_started(did3)
        self.assertEqual(self.work_dispatch("T-002"), did3)  # 세 번째는 다시 넣지 않는다
        d = [x for x in self.decides() if x["task"] == "T-002"]
        self.assertEqual(len(d), 1, d)
        self.assertEqual((d[0]["kind"], d[0]["summary"]), ("escalation", "작업자 시작을 3번 확인하지 못했다"))
        self.assertEqual(len(d[0]["commands"]), 3)
        self.assertTrue(any("--force" in c for c in d[0]["commands"]), d[0]["commands"])

    def test_working_session_is_not_resent(self):
        first = self.out["dispatch"]
        self.not_started(first, status="working")
        self.assertEqual(self.work_dispatch("T-002"), first)
        self.assertEqual(self.dispatch_row(first)["state"], "active")
        self.assertNotIn("unknown_starts", self.task_state("T-002"))


class HandoffTemplateTest(CrewCase):
    def test_template_text(self):
        text = (ROOT / "templates/handoff.md").read_text(encoding="utf-8")
        for needle in ('너는 herdr-team 의 고정 에이전트 "{{agent_title}}"({{agent}}) 다. 이번 태스크는 인수인계 하나만 한다. '
                       "리뷰하지 않는다.", "## 쓸 내용 (200줄 이하)", "## 하지 않는 것", "## 끝내기",
                       '1. `git add -- {{path}} && git commit -m "[handoff] {{agent}}: 인수인계" -- {{path}}`',
                       '2. 프리앰블의 done 명령을 `--outcome succeeded --summary "<한 줄>"` 로 한 번 부른다. 쓰지 못했으면 '
                       "`--outcome failed` 와 이유를 보낸다."):
            self.assertIn(needle, text)
        self.assertEqual(sorted(set(__import__("re").findall(r"\{\{(\w+)\}\}", text))), ["agent", "agent_title", "path"])


class ReviewFixTest(ResetCase):
    """Task 8 리뷰 고치기(Codex 커밋 리뷰 fe8770f, 태스크 리뷰 Minor 1)."""

    def not_started_msg(self, did, status="done"):
        return NotStartedTest.not_started_msg(self, did, status)

    def test_unknown_terminal_on_first_not_started_keeps_resend_for_reconcile(self):
        """첫 not_started 처리에서 작업 터미널을 확인하지 못해도 재투입 예약을 남겨 재확인이 잇는다(설계 5.9.8, 8.7)."""
        first = self.started("T-002")["dispatch"]
        msg = self.not_started_msg(first)
        self.delay_get(self.t, 4.0)  # hc get 이 3초 확인을 넘긴다
        with self.in_drive():
            self.make_drive().handle(msg)  # 이 처리 뒤 메시지는 ack 되고 horch 는 같은 관찰을 다시 내지 않는다
        self.assertEqual(self.rnd("T-002")["work"]["resend"], {"from": first, "n": 1})
        self.assertEqual(self.dispatch_row(first)["state"], "active")  # 아직 버리지 않았다
        self.undelay()
        with self.in_drive():
            d = self.make_drive()
            d.write_workers()
            d.reconcile_task(self.task_state("T-002"))
        did2 = self.work_dispatch("T-002")
        self.assertNotEqual(did2, first)
        self.assertEqual(self.dispatch_row(first)["state"], "abandoned")
        st = self.task_state("T-002")
        self.assertEqual((st["unknown_starts"], self.entry()["dispatch"]), (1, did2))
        self.assertNotIn("resend", st["rounds"][-1]["work"])

    def test_not_started_after_turn_rose_is_not_resent(self):
        """not_started 가 기다리는 사이 워커가 시작해 done 없이 턴을 마쳤다(turn 이 올랐다): 다시 넣지 않는다(orch 13.6)."""
        first = self.started("T-002")["dispatch"]
        msg = self.not_started_msg(first)
        self.update_terminal(self.t, turn=self.terminals()[self.t]["turn"] + 1)
        with self.in_drive():
            self.make_drive().handle(msg)
        st = self.task_state("T-002")
        self.assertEqual((self.work_dispatch("T-002"), self.dispatch_row(first)["state"]), (first, "active"))
        self.assertNotIn("unknown_starts", st)
        self.assertNotIn("resend", st["rounds"][-1]["work"])
        self.assertTrue(any(f"T-002 not_started 지난 관찰 무시: {first}" in x for x in self.log_lines()), self.log_lines())

    def test_handoff_blocked_reads_hc_status_msg(self):
        """horch 의 observed blocked 본문에는 status 만 있다. 원인 글은 worker-show 의 hc 상태 msg 에서 읽는다(8.6)."""
        self.mark()
        self.step()
        did = self.handoff_did()
        with self._hc_locked() as st:
            st["terminals"][self.t]["status"] = {"app": "claude-code", "state": "blocked", "msg": "Bash 실행을 허락할까?"}
        self.handle("observed", did, self.observed(did, "blocked", "2", "blocked"), sender="horch")
        d = self.decides()
        self.assertEqual(len(d), 1, d)
        self.assertEqual(d[0]["summary"], "production 에이전트가 인수인계 중 blocked 로 멈췄다(Bash 실행을 허락할까?). "
                                          "사용자에게 그 탭을 보게 한다")

    def test_reset_failures_cleared_when_reset_ends(self):
        """넣기 실패 수는 한 리셋 안의 횟수다. 리셋이 어떻게 끝나든 지운다(태스크 리뷰 Minor 1)."""
        self.mark()
        with self._hc_locked() as st:
            st["on_send"] = {self.t: "mismatch"}
        self.step(2)
        self.assertEqual(self.entry()["reset_failures"], 2)
        self.update_terminal(self.t, state="finished")
        self.step()  # 터미널이 끝나 skipped 로 끝난다
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["reset_failures"]), (False, 0))


from unittest import mock  # noqa: E402  (리뷰 고치기 둘째의 시험 도구)

from hteam.errors import HteamError  # noqa: E402


class ReviewFix2Test(ResetCase):
    """Task 8 리뷰 고치기 둘째(Codex 커밋 리뷰 ad508b6)."""

    def not_started_msg(self, did, status="done"):
        return NotStartedTest.not_started_msg(self, did, status)

    def test_worker_list_failure_on_first_not_started_keeps_resend(self):
        """첫 not_started 처리의 worker-list 가 실패해도 재투입 예약은 이미 남았다. 메시지는 처리 실패로 ack 되고 재확인이 잇는다."""
        first = self.started("T-002")["dispatch"]
        msg = self.not_started_msg(first)
        with self.in_drive():
            d = self.make_drive()
            fail = HteamError("horch_failed", "worker-list 시간 초과", 1)
            with mock.patch.object(d.horch(), "workers", side_effect=fail), self.assertRaises(HteamError):
                d.handle(msg)
        self.assertEqual(self.rnd("T-002")["work"]["resend"], {"from": first, "n": 1})
        self.assertEqual(self.dispatch_row(first)["state"], "active")
        with self.in_drive():
            d = self.make_drive()
            d.write_workers()
            d.reconcile_task(self.task_state("T-002"))
        did2 = self.work_dispatch("T-002")
        self.assertNotEqual(did2, first)
        self.assertEqual((self.dispatch_row(first)["state"], self.task_state("T-002")["unknown_starts"]),
                         ("abandoned", 1))
        self.assertNotIn("resend", self.rnd("T-002")["work"])

    def test_finished_dispatch_clears_resend_without_hc_and_goes_to_review(self):
        """예약이 남은 뒤 hc 확인이 계속 실패해도, 워커가 끝낸 Dispatch(settled·seen_at)를 보면 예약을 지우고 보통 재확인
        (놓친 worker_done → 리뷰)으로 간다."""
        first = self.started("T-002")["dispatch"]
        msg = self.not_started_msg(first)
        self.delay_get(self.t, 4.0)
        with self.in_drive():
            self.make_drive().handle(msg)
        self.assertEqual(self.rnd("T-002")["work"]["resend"], {"from": first, "n": 1})
        code, out = self.act_work("T-002", {"src/t-002/a.py": "T-002\n"})  # 입력은 들어갔고 워커가 끝냈다(worker_done 은 놓쳤다)
        self.assertEqual(code, 0, out)
        row = self.dispatch_row(first)
        self.assertEqual(row["state"], "settled")
        self.assertTrue(row["seen_at"])
        with self.in_drive():
            d = self.make_drive()
            d.write_workers()
            with mock.patch.object(d, "start_review") as review:
                d.reconcile_task(self.task_state("T-002"))  # hc get 은 여전히 3초를 넘긴다
        review.assert_called_once_with("T-002")
        self.assertNotIn("resend", self.rnd("T-002")["work"])
        self.assertEqual(self.work_dispatch("T-002"), first)
        self.assertTrue(any(f"T-002 not_started 지난 관찰 무시: {first}" in x for x in self.log_lines()), self.log_lines())


class SameSessionNoParentTest(ResetCase):
    """11단계 회귀(설계 3.2·15.1): 인수인계와 입력 유실 재투입은 crew.py 가 horch 를 바로 불러 같은 세션에 넣는다(worker-start
    --terminal, dispatch.launch 를 거치지 않는다). run.json 에 main_terminal 이 있어도 --parent 를 주지 않는다(horch 는
    --terminal 과 --parent 를 usage 로 거부한다)."""

    def setUp(self):
        super().setUp()
        self.set_run(main_terminal=MAIN)

    def worker_starts(self, run) -> list[list[str]]:
        """관제 객체로 run(d) 를 하고 그동안 horch 에 넘긴 worker-start 인자를 돌려준다."""
        seen = []
        with self.in_drive():
            d = self.make_drive()
            real = d.horch().call

            def spy(*args, **kw):
                seen.append(list(args))
                return real(*args, **kw)

            with mock.patch.object(d.horch(), "call", side_effect=spy):
                run(d)
        return [a for a in seen if a[:1] == ["worker-start"]]

    def test_handoff_has_no_parent(self):
        self.mark()
        (argv,) = self.worker_starts(lambda d: d.reset_step())
        self.assertEqual(argv[:3], ["worker-start", "--terminal", self.t])
        self.assertNotIn("--parent", argv)
        self.assertEqual(self.entry()["resetting"]["step"], "handoff")  # horch 가 받았다

    def test_resend_has_no_parent(self):
        first = self.started("T-002")["dispatch"]
        horch_task = self.dispatch_row(first)["task_id"]
        msg = NotStartedTest.not_started_msg(self, first)
        (argv,) = self.worker_starts(lambda d: d.handle(msg))
        self.assertEqual(argv, ["worker-start", "--terminal", self.t, "--task", horch_task])
        self.assertNotEqual(self.work_dispatch("T-002"), first)  # 다시 넣었다


import contextlib  # noqa: E402  (11단계 보강의 시험 도구)
import re  # noqa: E402
import time  # noqa: E402

from tests.test_crew import HANDOFF_LINE  # noqa: E402
from hteam import herdr  # noqa: E402


class RehomeResetTest(ResetCase):
    """11단계 보강(설계 5.9.7 의 4, 15.1): 메인이 바뀌었으면(작업 터미널 parent ≠ main_terminal M, M 은 같은 space 의 산
    터미널) 리셋의 clear 단계가 같은 터미널을 비우지 않고 닫는다. 다음 태스크가 새 메인 아래 새 세션으로 띄우고 인수인계
    파일을 읽는다. self.t 는 main_terminal 없이 띄운 세션(parent 없음, 0.7.0 에서 띄운 세션과 같다)이다."""

    def setUp(self):
        super().setUp()
        self.set_run(main_terminal=MAIN)

    def horch_args(self, run) -> list[list[str]]:
        """관제 객체로 run(d) 를 하고 그동안 horch 에 넘긴 인자를 돌려준다."""
        seen = []
        with self.in_drive():
            d = self.make_drive()
            real = d.horch().call

            def spy(*args, **kw):
                seen.append(list(args))
                return real(*args, **kw)

            with mock.patch.object(d.horch(), "call", side_effect=spy):
                run(d)
        return seen

    def finish_handoff(self, n=1, get=None) -> list[list[str]]:
        """리셋 표시 → 인수인계 → 워커가 인수인계 n 을 커밋하고 done → 관제가 worker_done 을 처리한다(clear 단계). get 이
        있으면 worker_done 처리 동안 hteam 의 hc get(herdr.get)을 그것으로 바꾼다(horch 는 그대로). horch 인자를 돌려준다."""
        self.mark()
        self.step()
        did = self.handoff_did()
        code, out = self.act(did, {"write": {"docs/handoff/production.md": f"# 결정 {n}\n"},
                                   "commit": "[handoff] production: 인수인계",
                                   "done": {"outcome": "succeeded", "summary": "썼다"}})
        self.assertEqual(code, 0, out)
        msg = self.message("worker_done", did, self.done_body(did))
        with mock.patch.object(herdr, "get", side_effect=get) if get else contextlib.nullcontext():
            return self.horch_args(lambda d: d.handle(msg))

    @staticmethod
    def calls_of(args, word) -> list[list[str]]:
        return [a for a in args if a[:1] == [word]]

    def test_parent_changed_closes_and_next_task_opens_under_main(self):
        args = self.finish_handoff()
        self.assertEqual(self.calls_of(args, "terminal-close"), [["terminal-close", "--terminal", self.t]])  # --abandon 없이
        self.assertEqual(self.calls_of(args, "terminal-reset"), [])
        self.assertEqual(self.keys(), [])  # /clear 를 치지 않았다
        e = self.entry()
        self.assertEqual((e["terminal"], e["terminal_argv"], e["work_pane"], e["resetting"], e["reset_pending"],
                          e["since_reset"], e["reset_tasks"]), (None, None, None, None, False, 0, []))
        self.assertRegex(e["last_reset_at"], r"[+-]\d\d:\d\d$")
        self.assertNotIn(self.t, self.terminals())  # terminal-close 가 끄고 지웠다
        self.assertTrue(any("production 리셋: new_terminal(parent_changed)" in x for x in self.log_lines()),
                        self.log_lines())
        out = self.started("T-002")  # 다음 태스크가 5.9.2 로 새 세션을 띄운다
        new = out["terminal"]
        self.assertNotEqual(new, self.t)
        info = self.terminals()[new]
        self.assertEqual((info["parent"], "--outlive-parent" in info["flags"], info["labels"]["herdr.tab"]),
                         (MAIN, True, self.tab()))
        self.assertIn(HANDOFF_LINE, (self.state_dir / "tasks/T-002/r1-work.md").read_text(encoding="utf-8"))  # 5.5 의 7
        self.assertEqual(self.entry()["terminal"], new)
        # 메인이 또 옮겼다: parent 가 있는 세션도 다음 리셋이 새 터미널로 띄운다
        self.work("T-002")
        self.free("T-002")
        self.ready(new)
        self.add_terminal("t5", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain5"}, status="idle")
        self.set_run(main_terminal="t5")
        args = self.finish_handoff(2)
        self.assertEqual(self.calls_of(args, "terminal-close"), [["terminal-close", "--terminal", new]])
        self.assertIsNone(self.entry()["terminal"])
        self.assertEqual(len([x for x in self.log_lines() if "production 리셋: new_terminal(parent_changed)" in x]), 2)

    def test_same_parent_or_unverifiable_main_clears_in_place(self):
        real = herdr.get

        def work_get_fails(terminal, timeout=10):
            if terminal == self.t:
                raise HteamError("hc_timeout", "hc get 가 3초 안에 끝나지 않았다", 1)
            return real(terminal, timeout=timeout)

        self.add_terminal("t50", argv=["claude"], state="finished", labels={"herdr.space": "spA", "herdr.tab": "tbM"})
        self.add_terminal("t51", argv=["claude"], labels={"herdr.space": "spB", "herdr.tab": "tbM"}, status="idle")
        self.add_terminal("t52", argv=["claude"], labels={"herdr.tab": "tbM"}, status="idle")
        self.add_terminal("t53", name="main-b", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbM"},
                          status="idle")
        cases = (("같은 parent", MAIN, MAIN, None), ("작업 터미널 hc get 실패", MAIN, None, work_get_fails),
                 ("끝난 메인", "t50", None, None), ("지운 메인", "t404", None, None), ("다른 space", "t51", None, None),
                 ("space 라벨 없음", "t52", None, None), ("같은 터미널의 다른 이름", "main-b", "t53", None))
        for n, (why, main, parent, get) in enumerate(cases, start=1):
            with self.subTest(why=why):
                self.set_run(main_terminal=main)
                self.update_terminal(self.t, parent=parent)
                before = len(self.keys())
                args = self.finish_handoff(n, get)
                self.assertEqual(len(self.keys()), before + 1)  # /clear 로 같은 터미널을 비웠다(지금 그대로)
                self.assertEqual(self.calls_of(args, "terminal-close"), [])
                e = self.entry()
                self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"]), (self.t, None, False))
        self.assertFalse(any("parent_changed" in x for x in self.log_lines()), self.log_lines())

    def test_close_failure_clears_the_same_terminal_in_the_same_tick(self):
        # 인수인계 worker_done 을 틱 2 의 메일 확인이 처리한다. 닫기가 실패해 rehome = failed 를 두면 같은 틱의 리셋 단계
        # (틱 7)가 parent 를 다시 보지 않고 같은 터미널을 비운다(실패한 틱을 건너뛰지 않는다. 리셋 단계나 재확인에서 실패했으면
        # 다음 틱이다). 틱 하나로 terminal-close 실패 → 같은 터미널 terminal-reset 순서를 본다
        self.env["HTEAM_DRIVE_WAIT_MS"] = "50"  # 빈 메일 확인을 짧게
        self.mark()
        self.step()
        self.fail_hc("kill", "timeout")  # terminal-close 가 실패한다
        gets, real = [], herdr.get

        def spy_get(terminal, timeout=10):
            gets.append(terminal)
            return real(terminal, timeout=timeout)

        def one_tick(d):
            with mock.patch.object(d, "handle"):  # 앞 단계의 메시지(T-001 의 worker_done 등)는 처리하지 않고 확인한다
                d.check_mail()
                d.check_mail()
            self.write_handoff()  # 인수인계 워커가 커밋하고 done 한다(Run 메일함에 worker_done)
            d.last_reconcile = time.monotonic()  # 이 틱에는 재확인이 돌지 않는다(worker_done 은 메일 확인이 처리한다)
            with mock.patch.object(herdr, "get", side_effect=spy_get):
                self.assertFalse(d.tick())

        args = self.horch_args(one_tick)
        self.assertEqual([a[:3] for a in args if a[:1] in (["terminal-close"], ["terminal-reset"])],
                         [["terminal-close", "--terminal", self.t], ["terminal-reset", "--terminal", self.t]])
        self.assertEqual(gets.count(self.t), 1)  # 작업 터미널 parent 는 첫 시도에서 한 번만 봤다
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"], e["close_failures"]),
                         (self.t, None, False, 0))
        self.assertEqual(self.keys(), [["/", "c", "l", "e", "a", "r", "enter"]])
        lines = self.log_lines()
        fail = next(i for i, x in enumerate(lines)
                    if re.search(r"production 리셋: 다시 묶기 닫기 실패\(.+\), 같은 터미널을 비운다$", x))
        self.assertTrue(any("production 리셋: reset(turn " in x for x in lines[fail + 1:]), lines)
        self.assertEqual(self.decides(), [])

    def test_reset_failure_after_the_close_failure_follows_the_close_rule(self):
        self.fail_hc("kill", "timeout")
        self.finish_handoff()
        self.on_clear("none")  # 같은 터미널 비우기도 turn 사건이 없다
        self.step()
        e = self.entry()
        self.assertEqual((e["resetting"]["clear_error"], e["resetting"]["rehome"], e["close_failures"], e["terminal"]),
                         ("reset_timeout", "failed", 1, self.t))  # 지금의 exit 4 갈래(닫기 세 번 뒤 decide)

    def test_resumed_parent_changed_closes_first(self):
        # clear_error = "parent_changed" 를 쓴 뒤 닫기 전에 관제가 죽었다. 다시 뜬 관제는 parent 를 다시 보지 않고 닫기부터
        # 한다(지금 규칙 그대로)
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.assertEqual(self.horch("worker-release", "--dispatch", did)[0], 0)
        self.set_entry(resetting={"step": "clear", "dispatch": did, "at": ago(5), "clear_error": "parent_changed"})
        with mock.patch.object(herdr, "get", wraps=herdr.get) as get:
            self.step()
        get.assert_not_called()
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"]), (None, None, False))
        self.assertEqual(self.keys(), [])
        self.assertTrue(any("production 리셋: new_terminal(parent_changed)" in x for x in self.log_lines()),
                        self.log_lines())


RELAY_HANDOFF = "production 에이전트 인수인계 중 상태를 Herdr 에 보낼 수 없어(대리 보고 쓰기 실패) 인수인계를 멈췄다"


class RelayHandoffTest(ResetCase):
    """12단계 인수인계 Dispatch 의 대리 보고 쓰기 실패(설계 8.6 표·8.7 의 2a·8.14 의 5): observed relay_failed 메시지나
    재확인의 attention relay_failed 로 그 자리에서 끝나지 않은 인수인계 정리(5.9.7 의 4 의 실패 갈래)와 decide 를 한다.
    정리한 Dispatch 는 진행 중이 아니므로 한 번이다. horch 신호는 흉내 낸다."""

    def setUp(self):
        super().setUp()
        self.mark()
        self.step()
        self.did = self.handoff_did()

    def stopped(self) -> None:
        self.assertEqual(self.dispatch_row(self.did)["state"], "released")  # abandon --keep-terminal 뒤 release
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["terminal"]), (None, False, self.t))
        (x,) = self.decides()
        self.assertEqual((x["kind"], x["task"], x["summary"], x["commands"]),
                         ("escalation", None, RELAY_HANDOFF, ["hteam agent reset production"]))

    def test_message_stops_the_handoff(self):
        self.handle("observed", self.did, self.observed(self.did, "relay_failed", "4242"), sender="horch")
        self.stopped()

    def test_late_relay_failed_after_the_dispatch_settled_is_ignored(self):
        # Codex 커밋 리뷰 2efd085: 끝난 인수인계 Dispatch 에 relay_failed 가 worker_done 보다 먼저 읽혀도 리셋을 취소하지 않는다
        self.write_handoff()
        self.handle("observed", self.did, self.observed(self.did, "relay_failed", "4242"), sender="horch")
        self.assertEqual(self.entry()["resetting"]["step"], "handoff")
        self.assertEqual(self.decides(), [])
        self.handle("worker_done", self.did, self.done_body(self.did), sender="horch")
        e = self.entry()  # 리셋이 이어져 끝났다(취소도 실패 decide 도 아니다)
        self.assertEqual((e["resetting"], e["reset_pending"], e["since_reset"]), (None, False, 0))
        self.assertEqual(self.decides(), [])

    def test_reconcile_stops_it_from_the_attention(self):
        with self.in_drive():
            d = self.make_drive()
            for _ in range(2):  # 정리한 Dispatch 는 진행 중이 아니다: 다시 하지 않는다
                d.relay_failed([dict(r, attention="relay_failed") if r["id"] == self.did else r
                                for r in d.write_workers()])
        self.stopped()


from datetime import timezone  # noqa: E402  (12단계 시험 도구)

from tests.test_crew import LOCAL_ISO, relay_failed_on  # noqa: E402
from hteam import tasks  # noqa: E402


class QuietResendTest(CrewCase):
    """입력 유실 재투입(5.9.8)도 넣기 전 확인을 한다(12단계, 5.9.9 의 2): 쓰기 실패 세션은 넣었는지 알 수 없어 다시 넣지
    않고 resend 를 남긴다(재확인이 다시 본다. 진행 중 작업 Dispatch 의 쓰기 실패는 8.14 의 5 의 escalation 이 알린다)."""

    def test_write_failed_session_is_not_resent(self):
        t = self.first("T-001")
        out = self.started("T-002")
        did = out["dispatch"]
        body = {"dispatch": did, "kind": "not_started", "key": "1", "terminal": t, "status": "done",
                "start_turn": 1, "turn": 1, "delivery": {"attempted": True}}
        with self.in_drive(), relay_failed_on(t):
            self.make_drive().handle(self.message("observed", did, body, sender="horch"))
        self.assertEqual(self.work_dispatch("T-002"), did)
        self.assertEqual(self.dispatch_row(did)["state"], "active")  # 버리지도 다시 넣지도 않았다
        self.assertEqual(self.rnd("T-002")["work"]["resend"], {"from": did, "n": 1})


class QuietResetTest(ResetCase):
    """12단계(설계 5.9.9 의 2·3, 15.1): 대리 보고도 없는 세션은 리셋의 30분 확인 불가 대기 없이 인수인계 없이 닫힌다.
    assigned_since_reset 은 띄우기·넣기가 올리고 리셋이 0 으로 둔다(인수인계는 세지 않는다)."""

    def test_unreported_session_is_closed_instead_of_waited_for(self):
        self.mark()
        self.update_terminal(self.t, status=None, status_ms=None, created_ms=int(time.time() * 1000) - 1000)
        self.step(2)
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_unknown_since"], e["reset_busy_since"], e["terminal"]),
                         (None, None, None, self.t))
        with self.in_drive():
            crew.check_terminals(self.make_drive())
        e = self.entry()
        self.assertEqual((e["terminal"], e["reset_pending"], e["since_reset"], e["reset_tasks"], e["resetting"]),
                         (None, False, 0, [], None))
        self.assertEqual(self.decides(), [])
        self.assertFalse(any("리셋 시작" in x for x in self.log_lines()), self.log_lines())

    def test_codex_unreported_session_keeps_the_unknown_wait(self):
        """Codex 고정 에이전트는 보고 없는 세션의 단축 경로를 타지 않는다(unreported 와 같다, Codex 브랜치 리뷰). 재확인이
        닫지 않으니 단축하면 reset_pending 이 영구히 남는다. 지금처럼 확인 불가로 30분을 기다린 뒤 리셋을 취소한다."""
        self.set_entry(agent="codex")
        self.mark()
        self.update_terminal(self.t, status=None, status_ms=None, created_ms=int(time.time() * 1000) - 1000)
        with mock.patch("hteam.herdr.relay_status", return_value=None) as relay_status:
            self.step()
            self.assertTrue(self.entry()["reset_unknown_since"])
            self.set_entry(reset_unknown_since=ago(31 * 60 + 5))
            self.step()
        self.assertEqual(relay_status.call_count, 0)
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["resetting"], e["terminal"]), (False, None, self.t))
        d = self.decides()
        self.assertEqual(len(d), 1, d)
        self.assertTrue(d[0]["summary"].startswith("production 에이전트의 작업 터미널 상태를 31분 넘게 알 수 없어"), d[0])

    def test_write_failed_ready_session_gets_no_handoff(self):
        self.mark()
        with relay_failed_on(self.t):
            self.step(2)  # hc 에는 옛 done 이 남아 넣기 준비로 보인다
        e = self.entry()
        self.assertEqual((e["resetting"], e["reset_pending"], e["terminal"]), (None, True, self.t))
        self.assertFalse(any("리셋 시작" in x for x in self.log_lines()), self.log_lines())

    def test_assigned_counter_rises_on_launch_and_insert_and_resets(self):
        self.assertEqual(self.entry()["assigned_since_reset"], 1)  # 5.9.2 의 띄우기
        self.started("T-002")  # 같은 세션에 넣었다(5.9.3)
        self.assertEqual(self.entry()["assigned_since_reset"], 2)
        self.work("T-002")
        self.free("T-002")
        self.ready(self.t, turn=2)
        self.mark()
        self.step()
        did = self.handoff_did()
        self.assertEqual(self.entry()["assigned_since_reset"], 2)  # 인수인계는 세지 않는다
        self.write_handoff()
        self.handle("worker_done", did, self.done_body(did))
        e = self.entry()
        self.assertEqual((e["assigned_since_reset"], e["since_reset"], e["terminal"]), (0, 0, self.t))  # 제자리 비우기
        self.assertTrue(e["relay_ready"])  # 같은 프로세스를 비웠다(/clear): 표시는 그대로다

    def test_write_failed_after_handoff_done_closes_without_the_busy_wait(self):
        # 인수인계 워커가 턴 안에서 done 을 보내 Dispatch 가 끝나고(clear 단계) 그 턴의 Stop 쓰기가 실패해 hc 에 옛 working 이
        # 남았다(Codex 계획 리뷰 r3). 바쁨으로 30분을 기다리지 않고 인수인계 파일은 둔 채 지금의 닫기 갈래로 간다
        self.mark()
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.ready(self.t, status="working", turn=self.terminals()[self.t]["turn"])
        with relay_failed_on(self.t):
            self.handle("worker_done", did, self.done_body(did))
        e = self.entry()
        self.assertEqual((e["terminal"], e["resetting"], e["reset_pending"], e["reset_busy_since"]),
                         (None, None, False, None))
        self.assertNotIn(self.t, self.terminals())  # terminal-close 가 끄고 지웠다
        self.assertTrue(any("production 리셋: new_terminal(terminal_not_ready)" in x for x in self.log_lines()),
                        self.log_lines())
        self.assertFalse(any("리셋 미룸" in x for x in self.log_lines()), self.log_lines())
        self.assertTrue((self.proj / "docs/handoff/production.md").is_file())  # 인수인계 파일은 그대로다
        self.assertEqual(self.keys(), [])  # /clear 를 치지 않았다

    def test_session_left_by_a_stopped_handoff_is_closed(self):
        # 인수인계 중 쓰기 실패(8.6 표의 인수인계 갈래)로 정리한 뒤 맡은 일 없이 남은 세션은 재확인이 relay-status 로 닫는다
        self.mark()
        self.step()
        did = self.handoff_did()
        self.handle("observed", did, self.observed(did, "relay_failed", "4242"), sender="horch")
        self.assertIsNone(self.entry()["resetting"])
        with self.in_drive(), relay_failed_on(self.t):
            crew.check_terminals(self.make_drive())
        e = self.entry()
        self.assertEqual((e["terminal"], e["reset_pending"]), (None, False))
        self.assertEqual(sum(x.endswith(" production 보고 없는 세션 닫음: 다음 태스크가 새 세션으로 뜬다")
                             for x in self.log_lines()), 1)
        self.assertEqual([x["summary"] for x in self.decides()], [RELAY_HANDOFF])


class RehomeEarlyTest(ResetCase):
    """다시 묶기 앞당기기(설계 5.9.9 의 3, 15.1): 맡은 일 없는 고정 에이전트 세션이 지금 메인 M 아래가 아니면 리셋 뒤
    태스크를 넣었으면 리셋을 걸고(clear 단계가 parent_changed 로 닫는다), 아니면 인수인계 없이 닫는다. 같은 M 으로는 한
    번이다. self.t 는 main_terminal 없이 띄운 세션(parent 없음)이다."""

    def setUp(self):
        super().setUp()
        self.set_run(main_terminal=MAIN)

    def rehome(self) -> None:
        with self.in_drive():
            crew.rehome_check(self.make_drive())

    def said(self, what: str) -> int:
        text = f" production 다시 묶기: 메인 {MAIN} 아래가 아니다(parent 없음). {what}"
        return sum(x.endswith(text) for x in self.log_lines())

    def after_reset(self) -> None:
        """마지막 리셋 뒤 이 세션에 넣은 태스크가 없다."""
        self.set_entry(since_reset=0, reset_tasks=[], assigned_since_reset=0, last_reset_at=ago(5))

    def test_session_with_work_is_reset_then_closed_under_the_new_main(self):
        self.assertEqual(self.entry()["assigned_since_reset"], 1)  # 5.9.2 의 띄우기가 1 올렸다
        self.rehome()
        self.rehome()  # 같은 메인 주소로는 한 번만
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["rehome_main"], e["terminal"]), (True, MAIN, self.t))
        self.assertEqual(self.said("리셋을 건다"), 1)
        self.step()  # 지금의 리셋: 인수인계를 넣는다
        did = self.handoff_did()
        self.write_handoff()
        self.handle("worker_done", did, self.done_body(did))
        e = self.entry()
        self.assertEqual((e["terminal"], e["reset_pending"], e["since_reset"], e["assigned_since_reset"]),
                         (None, False, 0, 0))
        self.assertTrue(any("production 리셋: new_terminal(parent_changed)" in x for x in self.log_lines()),
                        self.log_lines())
        out = self.started("T-002")  # 다음 태스크가 메인 아래 새 세션으로 뜬다
        self.assertEqual(self.terminals()[out["terminal"]]["parent"], MAIN)

    def test_close_failure_then_assignment_still_rehomes_under_the_new_main(self):
        # Codex 커밋 리뷰 6224f9b: 닫기가 실패한 뒤 재확인 전에 태스크가 오면 같은 세션에 넣지 않고 닫아 새 메인 아래로 띄운다
        self.after_reset()
        self.fail_hc("kill", "timeout")
        self.rehome()
        e = self.entry()
        self.assertEqual((e["terminal"], e["close_failures"], e["rehome_main"]), (self.t, 1, MAIN))
        with self._hc_locked() as st:
            st["fail"].clear()
        out = self.started("T-002")
        self.assertNotEqual(out["terminal"], self.t)
        self.assertNotIn(self.t, self.terminals())
        self.assertEqual(self.terminals()[out["terminal"]]["parent"], MAIN)
        self.assertEqual((self.entry()["terminal"], self.entry()["close_failures"]), (out["terminal"], 0))

    def test_task_dropped_without_done_counts(self):
        self.after_reset()
        self.started("T-002")  # 같은 세션에 넣었다
        self.ready(self.t, status="idle", turn=2)
        code, res = self.hteam("drop", "T-002")
        self.assertEqual((code, res["status"]), (0, "dropped"), res)
        e = self.entry()
        self.assertEqual((e["task"], e["since_reset"], e["assigned_since_reset"]), (None, 0, 1))  # done 이 없었다
        self.rehome()
        self.assertEqual((self.entry()["reset_pending"], self.said("리셋을 건다")), (True, 1))

    def test_session_without_work_is_closed_without_handoff(self):
        self.after_reset()
        self.rehome()
        e = self.entry()
        self.assertEqual((e["terminal"], e["reset_pending"], e["resetting"], e["rehome_main"], e["assigned_since_reset"]),
                         (None, False, None, MAIN, 0))
        self.assertNotIn(self.t, self.terminals())
        self.assertEqual(self.said("닫는다"), 1)
        self.assertFalse(any("보고 없는 세션 닫음" in x or "리셋 시작" in x for x in self.log_lines()), self.log_lines())
        out = self.started("T-002")
        self.assertEqual(self.terminals()[out["terminal"]]["parent"], MAIN)

    def legacy(self, **fields) -> None:
        """0.7.2 전 entry 의 assigned_since_reset·rehome_main 이 없다(relay_ready 는 둔다: 옛 세션 바꾸기는 RelayUpgradeTest)."""
        data = self.crew_json()
        e = data["production"]
        e.pop("assigned_since_reset", None)
        e.pop("rehome_main", None)
        e.update(reset_pending=False, **fields)
        (self.state_dir / "crew.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_legacy_entry_uses_since_reset_then_round_records(self):
        cases = (("since_reset", {"since_reset": 1}, "리셋을 건다", 1),
                 ("리셋 없이 띄운 세션", {"since_reset": 0, "last_reset_at": None, "launched_at": ago(60)}, "리셋을 건다", 2),
                 ("리셋 뒤 넣은 라운드", {"since_reset": 0, "last_reset_at": ago(3600), "launched_at": ago(7200)},
                  "리셋을 건다", 3),
                 ("리셋 뒤 라운드 없음", {"since_reset": 0, "last_reset_at": ago(-60), "launched_at": ago(7200)}, "닫는다", 1))
        for why, fields, what, count in cases:
            with self.subTest(why=why):
                self.legacy(**fields)
                self.rehome()
                self.assertEqual(self.said(what), count)
        self.assertIsNone(self.entry()["terminal"])  # 마지막 경우는 닫았다

    def test_legacy_reset_in_the_same_second_as_the_round_counts(self):
        # 마지막 리셋과 그 뒤 넣은 라운드가 같은 초다(리셋 직후 넣고 done 없이 drop). 저장된 시각을 그대로 견준다
        launched = next(h["at"] for h in self.task_state("T-001")["history"] if h.get("event") == "launched")
        same = datetime.strptime(launched, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
        self.legacy(since_reset=0, last_reset_at=same.isoformat(timespec="seconds"), launched_at=ago(7200))
        self.rehome()
        self.assertEqual((self.said("리셋을 건다"), self.entry()["reset_pending"], self.entry()["terminal"]),
                         (1, True, self.t))

    def test_busy_resetting_or_already_done_sessions_are_left(self):
        cases = (("맡은 태스크", {"task": "T-009", "dispatch": "dsp-x"}), ("대기열", {"queue": ["T-009"]}),
                 ("리셋 중", {"resetting": {"step": "handoff", "dispatch": "dsp-x", "title": "[handoff] production s1",
                                          "at": ago(5)}}),
                 ("리셋 대기", {"reset_pending": True}), ("이미 한 메인", {"rehome_main": MAIN}))
        for why, fields in cases:
            with self.subTest(why=why):
                before = self.entry()
                self.set_entry(**fields)
                self.rehome()
                e = self.entry()
                self.assertEqual((e["terminal"], e["reset_pending"]), (self.t, fields.get("reset_pending", False)))
                self.set_entry(**{k: before.get(k) for k in fields})
        self.assertFalse(any("다시 묶기:" in x for x in self.log_lines()), self.log_lines())

    def test_main_elsewhere_or_already_parent_is_left(self):
        self.add_terminal("t50", argv=["claude"], state="finished", labels={"herdr.space": "spA", "herdr.tab": "tbM"})
        self.add_terminal("t51", argv=["claude"], labels={"herdr.space": "spB", "herdr.tab": "tbM"}, status="idle")
        for why, main, parent in (("끝난 메인", "t50", None), ("다른 space", "t51", None), ("이미 메인 아래", MAIN, MAIN)):
            with self.subTest(why=why):
                self.set_run(main_terminal=main)
                self.update_terminal(self.t, parent=parent)
                self.rehome()
                e = self.entry()
                self.assertEqual((e["terminal"], e["reset_pending"], e.get("rehome_main")), (self.t, False, None))


class RelayUpgradeTest(ResetCase):
    """옛 세션 바꾸기(설계 5.9.9 의 4, 15.1): relay_ready 가 없는 Claude 작업 세션(herdr-orch 0.5.0 전에 띄워 HORCH_HOME 이
    없다)은 쉬는 동안 리셋 뒤 넣은 태스크가 있으면 리셋을 걸고(clear 단계가 비우지 않고 닫는다, new_terminal(relay_missing)),
    없으면 인수인계 없이 닫는다. relay_upgrade 로 한 번이다. 묶음 끝·사용자 리셋의 clear 단계도 옛 세션을 닫는다."""

    def old(self, **fields) -> None:
        """0.7.2 전에 띄운 세션: entry 에 relay_ready 가 없다."""
        data = self.crew_json()
        data["production"].pop("relay_ready", None)
        data["production"].update(fields)
        (self.state_dir / "crew.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def rehome(self) -> None:
        with self.in_drive():
            crew.rehome_check(self.make_drive())

    def said(self, what: str) -> int:
        text = f" production 옛 세션 바꾸기: 대리 보고·Stop 기록이 없는 세션이다. {what}"
        return sum(x.endswith(text) for x in self.log_lines())

    def finish_reset(self) -> None:
        """리셋을 건 뒤의 지금 흐름: 인수인계를 넣고, 인수인계 워커가 쓰고 done 한다(clear 단계로 간다)."""
        self.step()
        did = self.handoff_did()
        self.write_handoff()
        self.handle("worker_done", did, self.done_body(did))

    def replaced(self) -> None:
        e = self.entry()
        self.assertEqual((e["terminal"], e["reset_pending"], e["resetting"]), (None, False, None))
        self.assertNotIn("relay_upgrade", e)
        self.assertNotIn(self.t, self.terminals())  # terminal-close 가 끄고 지웠다
        out = self.started("T-002")  # 다음 태스크는 새 세션으로 뜬다
        self.assertNotEqual(out["terminal"], self.t)
        self.assertTrue(self.entry()["relay_ready"])

    def test_new_session_is_left(self):
        self.assertTrue(self.entry()["relay_ready"])  # 5.9.2 의 띄우기
        self.rehome()
        self.assertEqual((self.entry()["reset_pending"], self.said("리셋을 건다") + self.said("닫는다")), (False, 0))

    def test_old_session_with_work_is_reset_then_closed_by_the_clear_stage(self):
        self.old()  # assigned_since_reset 1(띄운 뒤 T-001 을 넣었다)
        self.rehome()
        self.rehome()  # relay_upgrade·reset_pending 이 있어 한 번만
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["terminal"]), (True, self.t))
        self.assertRegex(e["relay_upgrade"], LOCAL_ISO)
        self.assertEqual(self.said("리셋을 건다"), 1)
        self.finish_reset()
        self.assertTrue(any("production 리셋: new_terminal(relay_missing)" in x for x in self.log_lines()),
                        self.log_lines())
        self.assertEqual(self.keys(), [])  # /clear 를 치지 않았다
        self.replaced()

    def test_old_session_without_work_is_closed_without_handoff(self):
        self.old(since_reset=0, reset_tasks=[], assigned_since_reset=0, last_reset_at=ago(5))
        self.rehome()
        self.assertEqual(self.said("닫는다"), 1)
        self.assertFalse(any("리셋 시작" in x or "보고 없는 세션 닫음" in x for x in self.log_lines()), self.log_lines())
        self.replaced()

    def test_close_failure_then_assignment_still_replaces_the_old_session(self):
        # Codex 커밋 리뷰 6224f9b: 닫기가 한 번 실패한 뒤 다음 재확인 전에 태스크가 오면 같은 옛 세션에 넣지 않고 닫아 새 세션으로 띄운다
        self.old(since_reset=0, reset_tasks=[], assigned_since_reset=0, last_reset_at=ago(5))
        self.fail_hc("kill", "timeout")
        self.rehome()
        e = self.entry()
        self.assertEqual((e["terminal"], e["close_failures"]), (self.t, 1))
        self.assertRegex(e["relay_upgrade"], LOCAL_ISO)
        with self._hc_locked() as st:
            st["fail"].clear()
        out = self.started("T-002")
        self.assertNotEqual(out["terminal"], self.t)
        self.assertNotIn(self.t, self.terminals())
        e = self.entry()
        self.assertEqual((e["terminal"], e["close_failures"], e["task"]), (out["terminal"], 0, "T-002"))
        self.assertTrue(e["relay_ready"])
        self.assertNotIn("relay_upgrade", e)

    def test_batch_reset_of_an_old_session_closes_it(self):
        self.old()
        self.mark()  # 묶음 끝·사용자 요청 리셋
        self.finish_reset()
        self.assertTrue(any("production 리셋: new_terminal(relay_missing)" in x for x in self.log_lines()),
                        self.log_lines())
        self.assertEqual(self.keys(), [])
        self.replaced()

    def test_with_the_rehome_conditions_it_acts_once(self):
        self.set_run(main_terminal=MAIN)  # self.t 는 메인 없이 띄웠다(parent 없음): 다시 묶기 앞당기기 조건도 맞는다
        self.old()
        self.rehome()
        self.rehome()
        e = self.entry()
        self.assertEqual((e["reset_pending"], e.get("rehome_main")), (True, None))
        self.assertEqual(self.said("리셋을 건다"), 1)
        self.assertFalse(any("다시 묶기:" in x for x in self.log_lines()), self.log_lines())

    def test_busy_codex_or_upgraded_sessions_are_left(self):
        cases = (("맡은 태스크", {"task": "T-009", "dispatch": "dsp-x"}), ("대기열", {"queue": ["T-009"]}),
                 ("리셋 중", {"resetting": {"step": "handoff", "dispatch": "dsp-x", "title": "[handoff] production s1",
                                          "at": ago(5)}}),
                 ("리셋 대기", {"reset_pending": True}), ("이미 건 바꾸기", {"relay_upgrade": ago(60)}),
                 ("Codex", {"agent": "codex"}))
        for why, fields in cases:
            with self.subTest(why=why):
                before = self.entry()
                self.old(**fields)
                self.rehome()
                e = self.entry()
                self.assertEqual((e["terminal"], e["reset_pending"]), (self.t, fields.get("reset_pending", False)))
                self.set_entry(**{k: before.get(k) for k in fields})
        self.assertFalse(any("옛 세션 바꾸기:" in x for x in self.log_lines()), self.log_lines())


class UnconfirmedHorchTest(CrewCase):
    """horch 버전을 확인하지 못한 채 띄운 새 세션(설계 3.3·5.9.2 의 3): relay_ready 를 적지 않아 옛 세션처럼 바뀐다(5.9.9
    의 4). 버전 확인(horch.version_confirmed, Task 3)만 바꾼다."""

    def test_session_launched_without_a_confirmed_horch_is_replaced(self):
        self.task("T-001")
        with self.in_drive(), mock.patch("hteam.crew.version_confirmed", return_value=False) as confirmed:
            out = tasks.start_command(self.p, "T-001", {})
        confirmed.assert_called_with(self.p.horch_home)
        t = out["terminal"]
        self.assertEqual(self.entry()["terminal"], t)
        self.assertNotIn("relay_ready", self.entry())
        self.work("T-001")
        self.free("T-001")
        self.ready(t)
        with self.in_drive():
            crew.rehome_check(self.make_drive())
        e = self.entry()
        self.assertEqual((e["reset_pending"], e["terminal"]), (True, t))
        self.assertTrue(any(x.endswith(" production 옛 세션 바꾸기: 대리 보고·Stop 기록이 없는 세션이다. 리셋을 건다")
                            for x in self.log_lines()), self.log_lines())

    def test_confirmed_horch_marks_the_new_session(self):
        self.task("T-001")
        with self.in_drive(), mock.patch("hteam.crew.version_confirmed", return_value=True):
            tasks.start_command(self.p, "T-001", {})
        self.assertTrue(self.entry()["relay_ready"])
