"""메인 → 관제 요청 큐(설계 7.1, 8.3 의 큐 명령·drive_only, 8.5 의 finish 잠금 비차단): 메인 쪽 검사, 관제 생존, 번호, 결과
대기·queued·outbox result, 신호, 관제의 실행·재실행 막기·review_busy 미루기, scope 의 key, test-confirm 의 메인 쪽 검사."""
import fcntl
import json
import re
import signal
import subprocess
import sys
import time
import unittest

from tests.helpers import ROOT, TeamCase
from hteam import state
from hteam.paths import Project

QUEUED = "관제가 처리 중이다. 결과는 hteam watch 의 result 메시지로 온다"
DRIVE_DOWN = "관제(hteam drive)가 꺼져 있다. 메인에서 /herdr-team:up 으로 살린 뒤 다시 한다"
DRIVE_HUNG = ("관제가 멈춘 것 같다(프로세스는 살아 있는데 heartbeat 가 끊겼다). 긴 작업 중일 수 있으니 잠시 뒤 다시 한다. 계속되면 "
              "사용자에게 관제 탭을 확인해 달라고 한다(관제를 다시 띄우는 명령은 이 상태를 고치지 않는다)")
DRIVE_ONLY = ("이 명령은 관제(hteam drive)가 스스로 한다. 메인이 관제 큐로 넣는 명령은 start, start-ready, fix, accept, drop, "
              "review --retry, design-decide, scope, agent reset, slot reset, test-confirm 이다")
NOT_WORKING = "T-002: 일하는 중(working)인 태스크에만 범위를 더한다(status=pending). 시작 전이면 사양을 고쳐 커밋한다"

# 관제의 큐 실행(Drive.run_queue)을 따로 띄운 프로세스에서 한다. HTEAM_TEST_DIE_AT 의 os._exit 가 시험 프로세스를 죽이지 않게
RUNNER = ("import json, sys; sys.path.insert(0, sys.argv[1]); from hteam import drive; from hteam.paths import Project; "
          "print(json.dumps(drive.Drive(Project(sys.argv[2])).run_queue()))")
NAME_RE = re.compile(r"^(\d{6})\.json$")


class QueueCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()
        self.p = Project(self.proj)
        self.env["HTEAM_QUEUE_POLL_S"] = "0.05"

    # --- 큐 파일 ---
    @property
    def queue_dir(self):
        return self.drive_dir / "queue"

    def requests(self) -> list[str]:
        """남은 요청 파일 번호(결과·그만둔 표시는 뺀다)."""
        if not self.queue_dir.exists():
            return []
        return sorted(m.group(1) for f in self.queue_dir.iterdir() if (m := NAME_RE.match(f.name)))

    def request(self, num: str = "000001") -> dict:
        return json.loads((self.queue_dir / f"{num}.json").read_text(encoding="utf-8"))

    def wait_until(self, cond, what: str, limit: float = 20.0) -> None:
        deadline = time.monotonic() + limit
        while not cond():
            self.assertLess(time.monotonic(), deadline, what)
            time.sleep(0.05)

    # --- 메인 ---
    def main(self, *args, wait: str = "0.3", **env):
        return self.hteam(*args, as_="main", env={"HTEAM_QUEUE_WAIT_S": wait, **env})

    def main_bg(self, *args, wait: str = "30", **env):
        """메인이 큐에 넣고 결과를 기다린다. 요청 파일이 생길 때까지 기다린 뒤 돌려준다."""
        before = len(self.requests())
        proc = self.hteam_bg(*args, as_="main", env={"HTEAM_QUEUE_WAIT_S": wait, **env})
        self.wait_until(lambda: len(self.requests()) > before or proc.poll() is not None, "요청 파일")
        self.assertIsNone(proc.poll(), "메인이 큐에 넣기 전에 끝났다")
        return proc

    # --- 관제 ---
    def run_queue(self) -> list:
        with self.in_drive():
            return self.make_drive().run_queue()

    def run_queue_proc(self, die_at: str | None = None) -> int:
        extra = {"HTEAM_TEST_DIE_AT": die_at} if die_at else None
        proc = subprocess.run([sys.executable, "-c", RUNNER, str(ROOT / "lib"), str(self.proj)], capture_output=True,
                              text=True, env=self._env("drive", None, extra), timeout=60)
        return proc.returncode

    def log_lines(self) -> list[str]:
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def results(self) -> list[dict]:
        return [e for e in self.outbox_items() if e["type"] == "result"]

    # --- 태스크 ---
    def failed_work(self, tid: str = "T-001") -> None:
        """작업 워커가 실패로 끝난 working 태스크(fix 가 새 라운드를 연다)."""
        self.write_spec(tid)
        state.create(self.p, tid, "developer")
        self.assertEqual(self.hteam("start", tid)[0], 0)
        self.assertEqual(self.act_work(tid, outcome="failed", commit=False, files={})[0], 0)

    def pending(self, tid: str, role: str = "developer", **kw) -> None:
        self.write_spec(tid, role, **kw)
        state.create(self.p, tid, role)

    def history(self, tid: str) -> list[dict]:
        return self.task_state(tid)["history"]


class SubmitTest(QueueCase):
    def test_main_start_goes_through_queue_and_gets_the_drive_result(self):
        self.pending("T-001")
        proc = self.main_bg("start", "T-001")
        req = self.request()
        self.assertEqual((req["id"], req["command"], req["args"]), ("q-000001", "start", {"task": "T-001"}), req)
        self.assertNotIn("expect_round", req)
        self.assertNotIn("started_at", req)
        self.assertEqual(self.task_state("T-001")["status"], "pending")  # 메인은 상태를 바꾸지 않았다
        self.assertEqual(self.run_queue(), ["q-000001"])
        code, out = self.finish(proc)
        self.assertEqual((code, out["status"], out["task"]), (0, "working", "T-001"), out)
        self.assertEqual(self.task_state("T-001")["status"], "working")
        self.assertEqual(self.requests(), [])
        self.assertEqual(list(self.queue_dir.iterdir()), [])  # 메인이 결과 파일을 읽고 지웠다
        self.assertIn("요청 q-000001 start: 완료", [line.split(" ", 1)[1] for line in self.log_lines()])
        start = [e for e in self.history("T-001") if e["event"] == "start"]
        self.assertEqual(start[0]["request"], "q-000001")  # 큐 요청이 바꾼 기록에 요청 id 를 남긴다

    def test_drive_refusal_becomes_the_main_exit(self):
        self.pending("T-001")
        proc = self.main_bg("accept", "T-001")
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"]), (3, "bad_state"), out)
        self.assertTrue(any(line.endswith(f"요청 q-000001 accept: bad_state: {out['error']['message']}")
                            for line in self.log_lines()), self.log_lines())

    def test_main_side_checks_fail_without_queueing(self):
        self.pending("T-002")
        cases = [(("start", "T-009"), (2, "unknown_task")),  # 사양 없음
                 (("fix", "T-009", "--note=x"), (2, "unknown_task")),
                 (("drop", "T-003"), (2, "unknown_task")),  # 상태 없음
                 (("accept", "T-003"), (2, "unknown_task")),
                 (("review", "T-003", "--retry"), (2, "unknown_task")),
                 (("scope", "T-002", ""), (2, "usage")),  # 내용이 비었다
                 (("test-confirm",), (2, "no_test_config"))]  # HEAD 에 [test] 가 없다
        self.write_spec("T-003")  # 사양만 있고 상태가 없다
        for args, want in cases:
            with self.subTest(args=args):
                code, out = self.main(*args)
                self.assertEqual((code, out["error"]["code"]), want, out)
        (self.team / "config.toml").write_text("max_parallel = [")
        for args in (("start-ready",), ("start", "T-002")):
            code, out = self.main(*args)
            self.assertEqual((code, out["error"]["code"]), (2, "bad_config"), out)
        self.assertEqual(self.requests(), [])
        self.assertFalse((self.drive_dir / "queue.seq").exists())

    def test_drive_down_or_hung_is_refused_before_queueing(self):
        self.pending("T-001")
        (self.drive_dir / "drive.pid").unlink()
        code, out = self.main("start", "T-001")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (1, "drive_down", DRIVE_DOWN), out)
        self.write_drive_pid()
        self.write_heartbeat(age_s=300)
        code, out = self.main("start", "T-001")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (1, "drive_hung", DRIVE_HUNG), out)
        self.assertEqual(self.requests(), [])

    def test_wait_timeout_is_queued_and_result_goes_to_outbox(self):
        self.pending("T-001")
        self.pending("T-002")
        code, out = self.main("start", "T-001")
        self.assertEqual(out, {"ok": True, "status": "queued", "request": "q-000001", "message": QUEUED})
        self.assertEqual(code, 0)
        self.assertTrue((self.queue_dir / "000001.abandoned").exists())
        code, out = self.main("accept", "T-002")  # 관제가 거부할 요청
        self.assertEqual((code, out["request"]), (0, "q-000002"), out)
        self.assertEqual(self.run_queue(), ["q-000001", "q-000002"])
        done, failed = self.results()
        self.assertEqual((done["request"], done["command"], done["from"], done["result"]["ok"], done["body"]),
                         ("q-000001", "start", "drive", True, "start T-001 — 완료"), done)
        self.assertEqual((failed["request"], failed["result"]["ok"], failed["result"]["exit"]), ("q-000002", False, 3))
        self.assertTrue(failed["body"].startswith("accept T-002 — 실패: bad_state: "), failed["body"])
        self.assertEqual(list(self.queue_dir.iterdir()), [])  # 표시·요청·결과 파일 모두 치웠다

    def test_numbers_continue_even_when_the_queue_is_empty(self):
        self.pending("T-001")
        self.pending("T-002")
        self.assertEqual(self.main("drop", "T-001")[1]["request"], "q-000001")
        self.assertEqual(self.main("drop", "T-002")[1]["request"], "q-000002")
        self.run_queue()
        self.assertEqual(list(self.queue_dir.iterdir()), [])
        self.assertEqual((self.drive_dir / "queue.seq").read_text().strip(), "3")
        self.pending("T-003")
        self.assertEqual(self.main("drop", "T-003")[1]["request"], "q-000003")  # 큐가 비어도 1 부터 다시 매기지 않는다
        (self.drive_dir / "queue.seq").write_text("2")
        (self.queue_dir / "000005.result.json").write_text("{}")  # 남은 파일의 가장 큰 번호 + 1
        self.pending("T-004")
        self.assertEqual(self.main("drop", "T-004")[1]["request"], "q-000006")
        self.assertEqual((self.drive_dir / "queue.seq").read_text().strip(), "7")

    def test_signal_while_waiting_leaves_an_abandoned_mark(self):
        self.pending("T-001")
        proc = self.main_bg("start", "T-001")
        proc.send_signal(signal.SIGTERM)
        code, _ = self.finish(proc)
        self.assertEqual(code, 143)
        self.assertTrue((self.queue_dir / "000001.abandoned").exists())
        self.run_queue()
        self.assertEqual([r["request"] for r in self.results()], ["q-000001"])

    def test_signal_after_the_result_arrived_moves_it_to_outbox(self):
        self.pending("T-001")
        proc = self.main_bg("start", "T-001", HTEAM_QUEUE_POLL_S="5")  # 첫 확인 뒤 5초 동안 잔다
        time.sleep(0.5)
        (self.queue_dir / "000001.result.json").write_text(json.dumps({"ok": True, "result": {"task": "T-001"}}))
        proc.send_signal(signal.SIGTERM)
        code, _ = self.finish(proc)
        self.assertEqual(code, 143)
        [res] = self.results()
        self.assertEqual((res["request"], res["command"], res["result"]), ("q-000001", "start",
                                                                           {"ok": True, "result": {"task": "T-001"}}))
        self.assertFalse((self.queue_dir / "000001.result.json").exists())
        self.assertFalse((self.queue_dir / "000001.abandoned").exists())

    def test_restarted_drive_runs_leftover_requests_in_order(self):
        self.pending("T-001")
        self.pending("T-002")
        self.main("drop", "T-002")
        self.main("start", "T-001")
        self.assertEqual(self.requests(), ["000001", "000002"])
        self.assertEqual(self.run_queue(), ["q-000001", "q-000002"])  # 새 관제 객체가 번호순으로
        lines = [line.split(" ", 1)[1] for line in self.log_lines()]
        self.assertLess(lines.index("요청 q-000001 drop: 완료"), lines.index("요청 q-000002 start: 완료"))
        self.assertEqual((self.task_state("T-002")["status"], self.task_state("T-001")["status"]),
                         ("dropped", "working"))

    def test_round_commands_carry_expect_round(self):
        self.failed_work("T-001")
        self.main("fix", "T-001", "--note=x")
        self.main("fix", "T-001", "--note=y", "--round", "5")
        self.main("accept", "T-001")
        self.main("drop", "T-001", "--force")
        self.main("scope", "T-001", "더한다")
        self.main("review", "T-001", "--retry")
        reqs = [self.request(n) for n in self.requests()]
        self.assertEqual([(r["command"], r.get("expect_round")) for r in reqs],
                         [("fix", 1), ("fix", 5), ("accept", 1), ("drop", 1), ("scope", 1), ("review", 1)])
        self.assertEqual(reqs[0]["args"], {"task": "T-001", "note": "x"})  # 준 옵션만 담는다
        self.assertEqual(reqs[2]["args"], {"task": "T-001"})
        self.assertEqual(reqs[3]["args"], {"task": "T-001", "force": True})
        self.assertEqual(reqs[4]["args"], {"task": "T-001", "body": "더한다"})
        self.assertEqual(reqs[5]["args"], {"task": "T-001", "retry": True})


class RouteTest(QueueCase):
    def test_drive_and_its_children_run_directly(self):
        self.pending("T-001")
        code, out = self.hteam("start", "T-001")  # 관제 환경(자식도 같은 환경을 물려받는다)
        self.assertEqual((code, out["status"]), (0, "working"), out)
        self.assertEqual(self.requests(), [])
        self.assertFalse((self.drive_dir / "queue.seq").exists())

    def test_drive_only_commands_from_main(self):
        self.pending("T-001")
        for args in (("review", "T-001"), ("review-finish", "T-001"), ("plan", "apply"), ("design-review",)):
            with self.subTest(args=args):
                code, out = self.main(*args)
                self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (5, "drive_only", DRIVE_ONLY),
                                 out)
        self.assertEqual(self.requests(), [])

    def test_worker_terminal_cannot_queue(self):
        self.pending("T-001")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        term = self.dispatch_row(self.work_dispatch("T-001"))["terminal"]
        self.pending("T-002")
        code, out = self.hteam("start", "T-002", as_=None, terminal=term, env={"HTEAM_QUEUE_WAIT_S": "0.3"})
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        self.assertEqual(self.requests(), [])


class RerunTest(QueueCase):
    """재실행 막기(설계 7.1): 실행 직전 started_at, 큐 요청이 바꾼 기록의 request, 다시 뜬 관제의 결과 복구."""

    def fix_rounds(self) -> int:
        return len(self.task_state("T-001")["rounds"])

    def test_death_after_execution_recovers_without_running_again(self):
        self.failed_work()
        proc = self.main_bg("fix", "T-001", "--note=다시")
        self.assertEqual(self.run_queue_proc("queue_executed"), 137)
        self.assertEqual(self.fix_rounds(), 2)
        self.assertIn("started_at", self.request())
        [fix] = [e for e in self.history("T-001") if e["event"] == "fix"]
        self.assertEqual(fix["request"], "q-000001")
        self.assertEqual(self.run_queue(), ["q-000001"])
        code, out = self.finish(proc)
        self.assertEqual((code, out["recovered"], out["task"], out["round"], out["status"]),
                         (0, True, "T-001", 2, "working"), out)
        self.assertEqual(self.fix_rounds(), 2)  # 다시 하지 않았다

    def test_death_before_any_record_runs_again(self):
        self.failed_work()
        proc = self.main_bg("fix", "T-001", "--note=다시")
        self.assertEqual(self.run_queue_proc("queue_started"), 137)
        self.assertEqual(self.fix_rounds(), 1)
        self.assertIn("started_at", self.request())
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertNotIn("recovered", out)
        self.assertEqual(self.fix_rounds(), 2)

    def test_death_after_the_result_file_does_not_run_again(self):
        self.failed_work()
        proc = self.main_bg("fix", "T-001", "--note=다시")
        self.assertEqual(self.run_queue_proc("queue_result_written"), 137)
        code, out = self.finish(proc)  # 메인은 이미 결과를 받았다
        self.assertEqual((code, out["round"]), (0, 2), out)
        self.assertEqual(self.requests(), ["000001"])  # 요청 파일을 지우기 전에 죽었다
        self.assertEqual(self.run_queue(), ["q-000001"])  # 기록이 있으니 결과만 다시 쓴다(실행하지 않는다)
        self.assertEqual(self.requests(), [])
        self.assertEqual(self.fix_rounds(), 2)

    def test_start_ready_without_record_simply_runs_again(self):
        self.pending("T-001")
        proc = self.main_bg("start-ready")
        self.assertEqual(self.run_queue_proc("queue_executed"), 137)
        self.assertEqual(self.task_state("T-001")["status"], "working")
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["started"], out["waiting"]), (0, [], []), out)  # 다시 해도 같은 결과
        self.assertEqual(len(self.task_state("T-001")["rounds"]), 1)

    def test_round_changed_since_submission_is_refused(self):
        self.failed_work()
        proc = self.main_bg("fix", "T-001", "--note=다시")
        self.assertEqual(self.hteam("fix", "T-001", "--note=관제가 먼저")[0], 0)  # 그 사이 다른 수정이 라운드를 열었다
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"], out.get("round")), (3, "round_changed", 2), out)
        self.assertEqual(self.fix_rounds(), 2)


class ReviewBusyTest(QueueCase):
    """관제 안의 fix·accept·drop·review-finish 는 finish 잠금을 비차단으로 잡는다(설계 8.5). 못 잡으면 review_busy."""

    def hold_finish(self, tid: str = "T-001"):
        fh = open(self.state_dir / "tasks" / f"{tid}.finish.lock", "a+")
        fcntl.flock(fh, fcntl.LOCK_EX)
        self.addCleanup(fh.close)
        return fh

    def test_queued_fix_is_deferred_while_others_run(self):
        self.failed_work()
        self.pending("T-002")
        fh = self.hold_finish()  # 리뷰 관문이 돈다
        fix = self.main_bg("fix", "T-001", "--note=다시")
        drop = self.main_bg("drop", "T-002")
        (self.drive_dir / "heartbeat").unlink()
        self.assertEqual(self.run_queue(), ["q-000002"])  # 미룬 요청은 실행한 것으로 세지 않는다
        self.assertTrue((self.drive_dir / "heartbeat").exists())  # 요청마다 heartbeat
        self.assertEqual(self.finish(drop)[1]["status"], "dropped")
        self.assertEqual(self.requests(), ["000001"])
        self.assertNotIn("started_at", self.request())  # 다음 틱에 다시 한다
        self.assertEqual(len(self.task_state("T-001")["rounds"]), 1)
        self.assertIsNone(fix.poll())  # 메인은 아직 기다린다
        self.assertFalse(any("q-000001" in line for line in self.log_lines()), self.log_lines())
        fcntl.flock(fh, fcntl.LOCK_UN)
        self.assertEqual(self.run_queue(), ["q-000001"])
        code, out = self.finish(fix)
        self.assertEqual((code, out["round"]), (0, 2), out)

    def test_drive_commands_do_not_wait_for_the_finish_lock(self):
        self.failed_work()
        self.hold_finish()
        for args in (("fix", "T-001", "--note=x"), ("drop", "T-001", "--force"), ("accept", "T-001"),
                     ("review-finish", "T-001")):
            with self.subTest(args=args):
                started = time.monotonic()
                code, out = self.hteam(*args)
                self.assertEqual((code, out["error"]["code"]), (3, "review_busy"), out)
                self.assertLess(time.monotonic() - started, 10)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("working", 1))
        self.assertFalse(st["rounds"][0]["work"].get("canceled"))


class ScopeTest(QueueCase):
    """`hteam scope T "<내용>"`(설계 7.1): target_dispatch 를 먼저 남기고 요청 id 를 key 로 한 번만 보낸다."""

    def setUp(self):
        super().setUp()
        self.pending("T-001")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.did = self.work_dispatch("T-001")
        self.term = self.dispatch_row(self.did)["terminal"]

    def mailbox(self) -> list[dict]:
        """작업 워커 메일함(워커 터미널의 check). 읽기만 한다."""
        code, out = self.horch("check", "--dispatch", self.did, terminal=self.term)
        self.assertEqual(code, 0, out)
        return out["messages"]

    def scope_events(self) -> list[dict]:
        return [e for e in self.history("T-001") if e["event"] == "scope"]

    def test_scope_sends_once_and_records_history(self):
        proc = self.main_bg("scope", "T-001", "로그인 오류 문구도 바꾼다")
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["id"], out["sent"]), (0, "T-001", True), out)
        [msg] = self.mailbox()
        self.assertEqual((msg["subject"], msg["body"]), ("추가 범위", "로그인 오류 문구도 바꾼다"))
        [ev] = self.scope_events()
        self.assertEqual((ev["round"], ev["body"], ev["request"]), (1, "로그인 오류 문구도 바꾼다", "q-000001"))
        self.assertIn("at", ev)

    def test_rerun_after_send_recovers_even_if_the_task_moved_on(self):
        proc = self.main_bg("scope", "T-001", "-x 옵션도 받는다")  # - 로 시작해도 본문이다
        self.assertEqual(self.run_queue_proc("scope_sent"), 137)
        self.assertEqual(self.request()["target_dispatch"], self.did)
        self.assertEqual(self.scope_events(), [])
        self.assertEqual(self.act_work("T-001")[0], 0)  # 그 사이 작업자가 끝냈다(Dispatch settled)
        with state.edit(self.p, "T-001") as st:
            state.move(st, "reviewing", "review")
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["sent"]), (0, True), out)  # key 조회로 이미 간 전송을 찾았다
        [ev] = self.scope_events()
        self.assertEqual((ev["body"], ev["request"]), ("-x 옵션도 받는다", "q-000001"))
        conn = __import__("sqlite3").connect(self.horch_home / "orch.db")
        try:
            rows = conn.execute("SELECT body FROM messages WHERE mailbox=? AND send_key=?",
                                (f"dispatch:{self.did}", "q-000001")).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows, [("-x 옵션도 받는다",)])  # 한 번만 갔다

    def test_scope_of_a_task_that_is_not_working(self):
        self.pending("T-002")
        proc = self.main_bg("scope", "T-002", "더한다")
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (3, "not_working", NOT_WORKING), out)
        self.assertEqual([e for e in self.history("T-002") if e["event"] == "scope"], [])

    def test_round_changed_scope_is_refused(self):
        proc = self.main_bg("scope", "T-001", "더한다")
        self.assertEqual(self.act_work("T-001", outcome="failed", commit=False, files={})[0], 0)
        self.assertEqual(self.hteam("fix", "T-001", "--note=관제")[0], 0)
        self.run_queue()
        code, out = self.finish(proc)
        self.assertEqual((code, out["error"]["code"]), (3, "round_changed"), out)


class TestConfirmQueueTest(QueueCase):
    def test_needs_committed_test_config_then_queues(self):
        code, out = self.main("test-confirm")
        self.assertEqual((code, out["error"]["code"]), (2, "no_test_config"), out)
        self.use_gate(approve=False)
        code, out = self.main("test-confirm")
        self.assertEqual((code, out["status"]), (0, "queued"), out)
        self.assertEqual((self.request()["command"], self.request()["args"]), ("test-confirm", {}))


class TaskNewTest(QueueCase):
    def test_main_and_drive_make_specs_directly(self):
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "메인이 만든다", as_="main")
        self.assertEqual((code, out["id"]), (0, "T-001"), out)
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "관제가 만든다")
        self.assertEqual((code, out["id"]), (0, "T-002"), out)
        self.assertEqual(self.requests(), [])  # 큐 명령이 아니다(설계 7.1)


if __name__ == "__main__":
    unittest.main()
