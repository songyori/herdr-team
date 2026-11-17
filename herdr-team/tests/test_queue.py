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
from unittest import mock

from tests.helpers import ROOT, TeamCase
from hteam import queue, state
from hteam.errors import HteamError
from hteam.paths import Project

QUEUED = "관제가 처리 중이다. 결과는 hteam watch 의 result 메시지로 온다"
DRIVE_DOWN = "관제(hteam drive)가 꺼져 있다. 메인에서 /herdr-team:up 으로 살린 뒤 다시 한다"
DRIVE_HUNG = ("관제가 멈춘 것 같다(프로세스는 살아 있는데 heartbeat 가 끊겼다). 긴 작업 중일 수 있으니 잠시 뒤 다시 한다. 계속되면 "
              "사용자에게 관제 탭을 확인해 달라고 한다(관제를 다시 띄우는 명령은 이 상태를 고치지 않는다)")
DRIVE_ONLY = ("이 명령은 관제(hteam drive)가 스스로 한다. 메인이 관제 큐로 넣는 명령은 start, start-ready, fix, accept, drop, "
              "review --retry, design-decide, scope, agent reset, slot reset, test-confirm 이다")
NOT_WORKING = "T-002: 일하는 중(working)인 태스크에만 범위를 더한다(status=pending). 시작 전이면 사양을 고쳐 커밋한다"
# 12단계 미룬 fix(설계 7.1 원문)
DEFERRED = "T-002 가 done 이 되면 관제가 실행한다. 결과는 hteam watch 의 result 메시지로 온다"
CYCLE = "T-001: {after} 는 T-001 가 끝나야 진행한다. 서로 기다려 멈춘다"
AFTER_CLOSED = "T-001: 선행 T-004 가 병합 없이 끝났다(dropped). 기다릴 것이 없다. 지금 fix 하거나 다시 판단한다"
AFTER_FAILED = "{after} 가 병합 없이 끝났다({status}). T-001 의 fix 를 하지 않았다. 다시 판단한다"

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


class AfterTest(QueueCase):
    """미룬 fix(12단계, 설계 7.1 `hteam fix T --after <A>`): 메인 쪽 검사, 미룬 요청, 관제의 건너뛰기·실행·실패, 취소와의
    배제, 대상 태스크 붙잡기, 한가함·status."""

    def move(self, tid: str, to: str) -> None:
        with state.edit(self.p, tid) as st:
            state.move(st, to, "test")

    def rounds(self, tid: str = "T-001") -> int:
        return len(self.task_state(tid)["rounds"])

    def defer(self, *args: str) -> dict:
        code, out = self.main("fix", *args)
        self.assertEqual((code, out.get("status")), (0, "deferred"), out)
        return out

    def test_main_side_refusals(self):
        self.failed_work()  # T-001
        self.pending("T-002", depends="T-001")  # 사양으로 T-001 을 기다린다
        self.pending("T-003", depends="T-002")  # 이어서 기다린다
        self.pending("T-004")
        self.assertEqual(self.hteam("drop", "T-004")[0], 0)
        self.pending("T-005")
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "새 태스크", "--depends-on", "T-001",
                               as_="main")  # tasks.toml 없이 task new 로 만든 사양(커밋 전)
        self.assertEqual(code, 0, out)
        made = out["id"]
        cases = [(("T-001", "--after", "T-001"), (2, "usage"), None),
                 (("T-001", "--after", "T-009"), (2, "unknown_task"), None),
                 (("T-001", "--after", "T-004"), (3, "after_closed"), AFTER_CLOSED),
                 (("T-001", "--after", "T-002"), (3, "after_cycle"), CYCLE.format(after="T-002")),
                 (("T-001", "--after", "T-003"), (3, "after_cycle"), CYCLE.format(after="T-003")),
                 (("T-001", "--after", made), (3, "after_cycle"), CYCLE.format(after=made))]
        for args, want, message in cases:
            with self.subTest(args=args):
                code, out = self.main("fix", *args)
                self.assertEqual((code, out["error"]["code"]), want, out)
                if message:
                    self.assertEqual(out["error"]["message"], message)
        self.assertEqual(self.requests(), [])
        self.assertFalse((self.drive_dir / "queue.seq").exists())
        self.defer("T-005", "--after", "T-001")  # 남은 미룬 요청: T-005 가 T-001 을 기다린다
        code, out = self.main("fix", "T-001", "--after", "T-005")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                         (3, "after_cycle", CYCLE.format(after="T-005")), out)
        self.assertEqual(self.requests(), ["000001"])
        code, out = self.hteam("fix", "T-001", "--after", "T-005")  # 관제 안에서는 받지 않는다
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)

    def test_deferred_request_is_written_and_returns_at_once(self):
        self.failed_work()
        self.pending("T-002")
        started = time.monotonic()
        code, out = self.main("fix", "T-001", "--note=다시", "--after", "T-002", wait="30")
        self.assertLess(time.monotonic() - started, 20)  # 결과를 기다리지 않는다
        self.assertEqual((code, out), (0, {"ok": True, "status": "deferred", "request": "q-000001", "after": "T-002",
                                           "message": DEFERRED}))
        req = self.request()
        self.assertEqual((req["command"], req["args"], req["after"], req["expect_round"]),
                         ("fix", {"task": "T-001", "note": "다시"}, "T-002", 1))
        self.assertNotIn("started_at", req)
        self.assertTrue((self.queue_dir / "000001.abandoned").exists())
        self.assertEqual(queue.held_tasks(self.p), {"T-001"})
        self.assertEqual([r["id"] for r in queue.deferred(self.p)], ["q-000001"])
        self.assertFalse(queue.waiting(self.p))  # 다시 묶기의 한가함에서 세지 않는다(설계 8.13)
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["deferred"], [{"request": "q-000001", "command": "fix", "task": "T-001", "after": "T-002",
                                            "at": req["at"]}])
        self.pending("T-003")
        self.main("drop", "T-003")  # 미루지 않은 요청은 센다
        self.assertTrue(queue.waiting(self.p))
        self.assertEqual([r["id"] for r in queue.deferred(self.p)], ["q-000001"])

    def test_done_prerequisite_runs_now(self):
        self.failed_work()
        self.pending("T-002")
        self.move("T-002", "done")
        proc = self.main_bg("fix", "T-001", "--note=다시", "--after", "T-002")
        self.assertNotIn("after", self.request())  # --after 를 떼고 지금 fix 로 보냈다
        self.assertFalse((self.queue_dir / "000001.abandoned").exists())
        self.assertEqual(self.run_queue(), ["q-000001"])
        code, out = self.finish(proc)
        self.assertEqual((code, out["round"], out["after"]), (0, 2, "already_done"), out)

    def test_drive_skips_until_done_then_runs_and_posts_the_result(self):
        self.failed_work()
        self.pending("T-002")
        self.pending("T-003")
        self.defer("T-001", "--note=다시", "--after", "T-002")
        self.main("drop", "T-003")  # 뒤 요청 q-000002
        with self.in_drive():
            d = self.make_drive()
            self.assertEqual(d.run_queue(), ["q-000002"])  # 선행 pending: 건너뛰고 뒤 요청을 실행한다
            for status in ("working", "changes"):
                self.move("T-002", status)
                self.assertEqual(d.run_queue(), [])
        lines = [line.split(" ", 1)[1] for line in self.log_lines()]
        self.assertEqual(lines.count("요청 q-000001 fix: T-002 를 기다린다"), 1)  # 처음 미룰 때만
        self.assertEqual(self.task_state("T-003")["status"], "dropped")
        self.assertEqual((self.requests(), self.rounds()), (["000001"], 1))
        self.assertNotIn("started_at", self.request())
        self.assertEqual(self.run_queue_proc(), 0)  # 다시 뜬 관제(다른 프로세스)도 그대로 둔다
        self.assertEqual(self.requests(), ["000001"])
        self.move("T-002", "done")
        self.assertEqual(self.run_queue(), ["q-000001"])  # 또 다른 관제 객체가 이어 간다
        [res] = [r for r in self.results() if r["request"] == "q-000001"]
        self.assertEqual((res["command"], res["result"]["ok"], res["result"]["result"]["round"], res["body"]),
                         ("fix", True, 2, "fix T-001 — 완료"), res)
        self.assertEqual(self.rounds(), 2)
        self.assertEqual(list(self.queue_dir.iterdir()), [])

    def test_dropped_or_missing_prerequisite_closes_with_after_failed(self):
        self.failed_work()
        self.pending("T-002")
        self.pending("T-003")
        self.defer("T-001", "--note=다시", "--after", "T-002")
        self.defer("T-001", "--note=또", "--after", "T-003")
        self.assertEqual(self.hteam("drop", "T-002")[0], 0)  # 선행이 병합 없이 끝났다
        (self.state_dir / "tasks" / "T-003.json").unlink()  # 선행의 상태 파일이 없어졌다
        self.assertEqual(self.run_queue(), ["q-000001", "q-000002"])
        first, second = self.results()
        for res, after, status in ((first, "T-002", "dropped"), (second, "T-003", "상태 없음")):
            message = AFTER_FAILED.format(after=after, status=status)
            self.assertEqual(res["result"], {"ok": False, "error": {"code": "after_failed", "message": message, "hint": ""},
                                             "exit": 3})
            self.assertEqual(res["body"], f"fix T-001 — 실패: after_failed: {message}")
        lines = [line.split(" ", 1)[1] for line in self.log_lines()]
        self.assertIn("요청 q-000001 fix: after_failed: " + AFTER_FAILED.format(after="T-002", status="dropped"), lines)
        self.assertEqual(self.rounds(), 1)  # 실행하지 않았다
        self.assertEqual(list(self.queue_dir.iterdir()), [])

    def test_round_changed_while_waiting_is_a_failed_result(self):
        self.failed_work()
        self.pending("T-002")
        self.defer("T-001", "--note=다시", "--after", "T-002")
        self.assertEqual(self.hteam("fix", "T-001", "--note=관제가 먼저")[0], 0)  # 그 사이 라운드가 바뀌었다
        self.move("T-002", "done")
        self.assertEqual(self.run_queue(), ["q-000001"])
        [res] = self.results()
        self.assertEqual((res["result"]["error"]["code"], res["result"]["exit"]), ("round_changed", 3), res)
        self.assertEqual(self.rounds(), 2)

    def test_cancel(self):
        self.failed_work()
        self.pending("T-002")
        self.defer("T-001", "--note=다시", "--after", "T-002")  # q-000001
        self.main("start-ready")  # q-000002: 미루지 않은 요청
        self.defer("T-001", "--note=또", "--after", "T-002")  # q-000003
        started = self.queue_dir / "000003.json"
        started.write_text(json.dumps({**self.request("000003"), "started_at": "2026-01-01T00:00:00Z"}))  # 관제가 시작했다
        (self.queue_dir / "000009.result.json").write_text("{}")  # 결과만 남았다
        code, out = self.hteam("cancel", "q-000001")  # 관제 환경
        self.assertEqual((code, out["error"]["code"]), (5, "not_main"), out)
        code, out = self.main("cancel", "q-000001")
        self.assertEqual((code, out), (0, {"ok": True, "request": "q-000001", "cancelled": True}))
        self.assertFalse((self.queue_dir / "000001.json").exists())
        self.assertFalse((self.queue_dir / "000001.abandoned").exists())
        for rid, want in (("q-000001", (2, "unknown_request")), ("q-000008", (2, "unknown_request")),
                          ("1", (2, "unknown_request")), ("q-000002", (3, "not_deferred")),
                          ("q-000003", (3, "not_deferred")), ("q-000009", (3, "not_deferred"))):
            with self.subTest(rid=rid):
                code, out = self.main("cancel", rid)
                self.assertEqual((code, out["error"]["code"]), want, out)
        self.assertEqual(self.requests(), ["000002", "000003"])
        self.assertEqual(queue.held_tasks(self.p), set())

    def test_cancel_after_the_drive_read_the_request_wins(self):
        # 관제가 잠금 없이 요청을 읽은 뒤 취소가 끼어도 실행하지 않는다(잠금 안에서 다시 읽는다, Codex 설계 리뷰 r1)
        self.failed_work()
        self.pending("T-002")
        self.defer("T-001", "--note=다시", "--after", "T-002")
        self.move("T-002", "done")
        real, seen, cancelled = queue.read_json, [], []

        def racing(path, default):
            got = real(path, default)
            if path.name == "000001.json" and not seen:
                seen.append(path)
                cancelled.append(queue.cancel(self.p, "q-000001"))
            return got

        with mock.patch.object(queue, "read_json", side_effect=racing):
            self.assertEqual(self.run_queue(), [])
        self.assertEqual(cancelled, [{"request": "q-000001", "cancelled": True}])
        self.assertEqual(self.rounds(), 1)
        self.assertEqual((self.results(), list(self.queue_dir.iterdir())), ([], []))

    def test_cancel_before_the_first_read_leaves_no_result(self):
        # 목록을 만든 뒤 첫 읽기 전에 취소돼도 결과 파일·outbox 결과·절차 실패가 없고 뒤 요청은 실행된다(Codex 계획 리뷰 r1)
        self.failed_work()
        self.pending("T-002")
        self.pending("T-003")
        self.defer("T-001", "--note=다시", "--after", "T-002")  # q-000001
        self.main("drop", "T-003")  # 뒤 요청 q-000002
        self.move("T-002", "done")
        real, cancelled = queue._request_files, []

        def listed(p):
            files = real(p)
            if not cancelled:
                cancelled.append(queue.cancel(self.p, "q-000001"))
            return files

        with mock.patch.object(queue, "_request_files", side_effect=listed):
            self.assertEqual(self.run_queue(), ["q-000002"])
        self.assertEqual(cancelled, [{"request": "q-000001", "cancelled": True}])
        self.assertEqual([r["request"] for r in self.results()], ["q-000002"])
        self.assertEqual([e for e in self.outbox_items() if e["type"] == "decide"], [])
        self.assertEqual(list(self.queue_dir.iterdir()), [])  # 000001.result.json 을 만들지 않았다
        self.assertEqual((self.rounds(), self.task_state("T-003")["status"]), (1, "dropped"))

    def test_mutual_after_at_once_lets_only_one_in(self):
        # 두 메인이 서로를 --after 로 거의 함께 넣으면 뒤의 것이 queue.lock 안 다시 검사에서 after_cycle(Codex 설계 리뷰 r4)
        self.pending("T-001")
        self.pending("T-002")
        fh = open(self.drive_dir / "queue.lock", "a+")
        self.addCleanup(fh.close)
        fcntl.flock(fh, fcntl.LOCK_EX)
        mains = [self.hteam_bg("fix", "T-001", "--after", "T-002", as_="main"),
                 self.hteam_bg("fix", "T-002", "--after", "T-001", as_="main")]
        time.sleep(2)  # 둘 다 잠금 밖 검사를 지나 queue.lock 을 기다린다
        fcntl.flock(fh, fcntl.LOCK_UN)
        outs = sorted((self.finish(proc) for proc in mains), key=lambda r: r[0])
        self.assertEqual([(code, out.get("status") or out["error"]["code"]) for code, out in outs],
                         [(0, "deferred"), (3, "after_cycle")], outs)
        self.assertEqual(self.requests(), ["000001"])

    def test_lock_recheck_sees_a_request_written_after_the_main_check(self):
        # 잠금 안 다시 검사만 본다: 메인 쪽 검사(route)를 지난 뒤 다른 메인이 fix T-002 --after T-001 을 넣었다
        self.pending("T-001")
        self.pending("T-002")
        self.defer("T-002", "--after", "T-001")
        with self.assertRaises(HteamError) as cm:
            queue.submit(self.p, "fix", {"task": "T-001"}, expect_round=0, after="T-002")
        self.assertEqual((cm.exception.code, cm.exception.exit_code, cm.exception.message),
                         ("after_cycle", 3, CYCLE.format(after="T-002")))
        self.assertEqual(self.requests(), ["000001"])
        self.assertEqual((self.drive_dir / "queue.seq").read_text().strip(), "2")  # 번호를 쓰지 않았다
        self.assertTrue(queue.after_cycle(self.p, "T-001", "T-003", extra=[("T-003", "T-002")]))  # 아직 쓰지 않은 간선
        self.assertFalse(queue.after_cycle(self.p, "T-001", "T-003"))

    def test_held_task_is_not_handled_by_reconcile_until_the_request_goes(self):
        # 대상 태스크 붙잡기(설계 7.1, 8.7): changes 의 자동 fix 를 하지 않는다. 요청이 없어지면 다음 재확인부터 다룬다
        self.pending("T-001")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        self.act_work("T-001")
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
        self.act_review("T-001", "REQUEST_CHANGES")
        self.assertEqual(self.hteam("review-finish", "T-001")[1].get("status"), "changes")
        self.pending("T-002")
        self.defer("T-001", "--note=선행 뒤 고친다", "--after", "T-002")
        with self.in_drive():
            self.make_drive().reconcile_task(self.task_state("T-001"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("changes", 1))
        self.assertEqual(self.main("cancel", "q-000001")[0], 0)
        with self.in_drive():
            self.make_drive().reconcile_task(self.task_state("T-001"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("working", 2))


class TaskNewTest(QueueCase):
    def test_main_and_drive_make_specs_directly(self):
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "메인이 만든다", as_="main")
        self.assertEqual((code, out["id"]), (0, "T-001"), out)
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "관제가 만든다")
        self.assertEqual((code, out["id"]), (0, "T-002"), out)
        self.assertEqual(self.requests(), [])  # 큐 명령이 아니다(설계 7.1)


if __name__ == "__main__":
    unittest.main()
