"""관제 이벤트·재확인·자식(설계 8.6–8.8, 8.10, 5.4 의 start-ready): 임시 워커 경로. 고정 에이전트 줄은 test_crew·
test_crew_reset, 묶음·마무리·디자인 단계는 test_drive_flows 가 본다(여기서는 그 자리를 부르는지만 본다)."""
import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from tests.helpers import BASE_CONFIG, DRIVE, HORCH_BIN, ROOT, TeamCase
from hteam import dispatch, outbox, procs, review, state, testgate
from hteam.errors import HteamError
from hteam.paths import Project

LOCAL_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
IDLE_TEXT = "턴을 마쳤는데 done 이 없다. 일이 끝났으면 프리앰블의 done 명령을 부른다. 남았으면 이어서 하고 끝나면 done 을 부른다."
GONE_NOTE = "이전 작업자가 중간에 끝났다. 보고서와 [T-001] 커밋을 확인하고 남은 일을 이어서 한다"
FIX = 'hteam fix T-001 --note "<지시>"'
FIX_FORCE_ROUND = 'hteam fix T-001 --force-round --note "<지시>"'
BLOCKED_TAIL = (". 사용자에게 그 탭(고정 에이전트면 에이전트 탭, 아니면 관제 탭)을 보고 승인하거나 거절해 달라고 한다. "
                "그 뒤 작업자가 이어 가면 worker_done 이 와서 리뷰로 간다")
NO_STATUS = "T-001 작업자가 상태를 보고하지 않는다(시작 확인 창일 수 있다). 사용자에게 그 탭을 보고 넘겨 달라고 한다"
# horch 를 부를 때마다 인자를 한 줄씩 남기고 진짜 horch 로 넘기는 감싸개(status 가 horch 를 부르지 않는지 본다, 설계 8.3)
RECORD_HORCH = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["HORCH_CALLS"], "a") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
os.execv(sys.executable, [sys.executable, os.environ["HORCH_REAL"], *sys.argv[1:]])
"""
# 관제 fix 를 따로 띄운 프로세스에서 한다. HTEAM_TEST_DIE_AT 의 os._exit 가 시험 프로세스를 죽이지 않게(설계 8.7 의 drive_fix)
FIX_RUNNER = ("import sys; sys.path.insert(0, sys.argv[1]); from hteam import drive; from hteam.paths import Project; "
              "drive.Drive(Project(sys.argv[2])).fix_task(sys.argv[3], sys.argv[4])")
# 다른 리뷰 실행자가 finish 잠금을 쥔 것처럼 쥔다(설계 8.5). 시간으로 풀리지 않고 시험이 표준 입력을 닫을 때 놓는다
HOLD_FINISH = ("import fcntl, sys; fh = open(sys.argv[1], 'a+'); fcntl.flock(fh, fcntl.LOCK_EX); "
               "print('held', flush=True); sys.stdin.read()")


def ago(seconds: float) -> str:
    """seconds 초 전 UTC 시각(util.now 꼴)."""
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record(errors: list, call) -> None:
    """다른 스레드에서 부른 call 의 예외를 errors 에 남긴다(스레드의 예외는 시험에 오르지 않는다)."""
    try:
        call()
    except BaseException as exc:  # noqa: BLE001 — 시험이 그대로 보인다
        errors.append(f"{type(exc).__name__}: {exc}")


class EventCase(TeamCase):
    """관제를 이 프로세스 안에서 만든다(make_drive). 리뷰·전체 테스트 자식은 실제 hteam 하위 프로세스다(설계 8.8)."""

    config = BASE_CONFIG

    def setUp(self):
        super().setUp()
        self.init_project(self.config)
        self.run_id = self.setup_run()
        self.p = Project(self.proj)
        self.write_spec("T-001")
        self._patcher = None
        self.rearm()

    def tearDown(self):
        for job in list(self.d.jobs.values()):  # 남은 리뷰 자식을 끝낸 뒤 시험 폴더를 지운다
            if job["proc"].poll() is None:
                job["proc"].kill()
            job["proc"].wait(timeout=30)
        super().tearDown()

    def rearm(self) -> None:
        """self.env 를 바꾼 뒤(use_gate 의 FAKE_DIR 등) 관제 환경을 다시 건다. 관제가 띄우는 자식은 이 환경을 물려받는다."""
        if self._patcher is not None:
            self._patcher.stop()
        else:
            self.addCleanup(lambda: self._patcher.stop())
        self._patcher = self.in_drive()
        self._patcher.start()
        self.d = self.make_drive()

    # --- 준비 ---
    def start(self, tid: str = "T-001") -> dict:
        code, out = self.hteam("start", tid)
        self.assertEqual(code, 0, out)
        return out

    def work_terminal(self, tid: str = "T-001") -> str:
        return self.dispatch_row(self.work_dispatch(tid))["terminal"]

    def done_msg(self, did: str, outcome: str = "succeeded", summary: str = "끝", mid: int = 1) -> dict:
        row = self.dispatch_row(did)
        return self.message("worker_done", did, {"dispatch": did, "task": row["task_id"], "outcome": outcome,
                                                 "summary": summary, "report_path": row["report_path"],
                                                 "files_modified": []}, mid=mid)

    def observed(self, did: str, kind: str, key: str = "1", status: str | None = None, mid: int = 1) -> dict:
        row = self.dispatch_row(did)
        return self.message("observed", did, {"dispatch": did, "kind": kind, "key": key, "terminal": row["terminal"],
                                              "status": status}, mid=mid, sender="horch")

    def text_msg(self, type_: str, did: str, body: str, mid: int = 1) -> dict:
        m = self.message(type_, did, {}, mid=mid)
        m["body"] = body  # question·escalation 본문은 JSON 이 아니다(horch ask·escalate)
        return m

    def wait_jobs(self, limit: float = 60.0) -> None:
        deadline = time.monotonic() + limit
        while True:
            self.d.reap_jobs()
            if not self.d.jobs:
                return
            if time.monotonic() > deadline:
                self.fail(f"자식이 끝나지 않았다: {sorted(self.d.jobs)}")
            time.sleep(0.05)

    def worked(self, tid: str = "T-001", **kw) -> None:
        """작업 워커가 커밋·보고서·done 을 하고, 관제가 그 worker_done 을 처리해 리뷰 자식이 끝날 때까지 기다린다."""
        did = self.work_dispatch(tid)
        code, out = self.act_work(tid, **kw)
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, kw.get("outcome", "succeeded")))
        self.wait_jobs()

    def reviewed(self, tid: str = "T-001", verdict: str | None = "APPROVE", **kw) -> None:
        """현재 리뷰 시도의 리뷰어가 파일을 쓰고 done 하고, 관제가 그 worker_done 을 처리한다."""
        did = self.attempt(tid)["dispatch"]
        code, out = self.act_review(tid, verdict, **kw)
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, kw.get("outcome", "succeeded")))
        self.wait_jobs()

    def set_state(self, tid: str, **fields) -> None:
        with state.edit(self.p, tid) as st:
            st.update(fields)

    def answer(self, oid: str, text: str = "처리했다") -> None:
        (self.state_dir / "answers").mkdir(parents=True, exist_ok=True)
        (self.state_dir / "answers" / f"{oid}.json").write_text(
            json.dumps({"id": oid, "answer": text, "at": "2026-01-01T00:00:00Z"}), encoding="utf-8")

    # --- 확인 ---
    def decides(self) -> list[dict]:
        return [e for e in self.outbox_items() if e["type"] == "decide"]

    def progress(self) -> list[str]:
        return [e["body"] for e in self.outbox_items() if e["type"] == "progress"]

    def log_lines(self) -> list[str]:
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def logged(self, text: str) -> int:
        """시각을 뗀 drive.log 줄이 text 와 같은 수."""
        return sum(1 for line in self.log_lines() if re.fullmatch(rf"{LOCAL_ISO} (.*)", line).group(1) == text)

    def dispatch_messages(self, did: str) -> list[dict]:
        conn = sqlite3.connect(self.horch_home / "orch.db")
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute("SELECT subject, body FROM messages WHERE mailbox=? ORDER BY id",
                                (f"dispatch:{did}",)).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]

    def sleeper(self) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (proc.kill(), proc.wait()))
        return proc

    def hold_finish(self, tid: str = "T-001"):
        """다른 프로세스가 그 태스크의 finish 잠금을 쥔다(죽은 관제가 남긴 리뷰 자식처럼). 보유자는 시험이 돌려받은 release()
        를 부를 때(표준 입력을 닫을 때)까지 쥔다. 시험이 그 전에 끝나면 정리가 놓는다. (보유자 프로세스, release) 를 돌려준다."""
        path = self.state_dir / "tasks" / f"{tid}.finish.lock"
        proc = subprocess.Popen([sys.executable, "-c", HOLD_FINISH, str(path)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, text=True)

        def release() -> None:
            if not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=30)
            if not proc.stdout.closed:
                proc.stdout.close()

        self.addCleanup(release)
        self.assertEqual(proc.stdout.readline().strip(), "held")
        return proc, release

    def main_bg(self, *args: str) -> subprocess.Popen:
        """메인이 큐 명령을 넣고 결과를 기다린다(설계 7.1). 요청 파일이 생길 때까지 기다린 뒤 돌려준다."""
        proc = self.hteam_bg(*args, as_="main", env={"HTEAM_QUEUE_WAIT_S": "30", "HTEAM_QUEUE_POLL_S": "0.05"})
        deadline = time.monotonic() + 20
        while not list((self.drive_dir / "queue").glob("[0-9][0-9][0-9][0-9][0-9][0-9].json")):
            self.assertIsNone(proc.poll(), "메인이 큐에 넣기 전에 끝났다")
            self.assertLess(time.monotonic(), deadline, "요청 파일이 생기지 않았다")
            time.sleep(0.05)
        return proc


def _with_rounds(config: str, n: int) -> str:
    return config.replace("max_rounds = 3", f"max_rounds = {n}")


class WorkDoneTest(EventCase):
    """작업 worker_done(설계 8.6 표 첫 줄들)."""

    def test_success_starts_review_child_once(self):
        self.start()
        did = self.work_dispatch("T-001")
        code, out = self.act_work("T-001")
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did))
        self.assertEqual(sorted(self.d.jobs), ["review:T-001"])
        self.d.handle(self.done_msg(did, mid=2))  # 같은 worker_done 이 다시 와도 리뷰 자식은 하나다
        self.assertFalse(self.d.start_review("T-001"))
        self.assertFalse(self.d.spawn("review:T-001", ["review", "T-001"]))
        self.assertEqual(sorted(self.d.jobs), ["review:T-001"])
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")
        self.assertTrue((self.drive_dir / "jobs" / "review-T-001.out").is_file())
        self.assertTrue((self.drive_dir / "jobs" / "review-T-001.err").is_file())
        self.assertEqual(self.logged("T-001 리뷰 시작"), 1)
        self.assertEqual(self.decides(), [])

    def test_success_clears_liveness_unknown(self):
        self.start()
        self.set_state("T-001", liveness_unknown_since=ago(60), liveness_escalated=True)
        self.worked()
        st = self.task_state("T-001")
        self.assertNotIn("liveness_unknown_since", st)
        self.assertNotIn("liveness_escalated", st)

    def test_failed_raises_worker_failed(self):
        self.start()
        did = self.work_dispatch("T-001")
        code, out = self.act_work("T-001", outcome="failed")
        self.assertEqual(code, 0, out)
        self.d.handle(self.done_msg(did, "failed", summary="빌드가 안 된다"))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["task"], e["summary"]), ("worker_failed", "T-001", "빌드가 안 된다"))
        self.assertEqual(e["files"], [".herdr-team/tasks/T-001.md", "docs/tasks/T-001/report.md"])
        self.assertEqual(e["commands"], ['hteam fix T-001 --note "<원인과 지시>"', "hteam drop T-001"])
        self.assertEqual(self.d.jobs, {})
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["decide"], st["decide_round"]), ("working", e["id"], 1))

    def test_failed_without_summary_uses_default_text(self):
        self.start()
        did = self.work_dispatch("T-001")
        self.act_work("T-001", outcome="failed")
        self.d.handle(self.done_msg(did, "failed", summary=""))
        self.assertEqual(self.decides()[0]["summary"], "워커가 실패를 보고했다")


class WorkDoneMaxRoundTest(EventCase):
    config = _with_rounds(BASE_CONFIG, 1)

    def test_failed_at_max_round_offers_force_round(self):
        self.start()
        did = self.work_dispatch("T-001")
        self.act_work("T-001", outcome="failed")
        self.d.handle(self.done_msg(did, "failed", summary="x"))
        self.assertEqual(self.decides()[0]["commands"],
                         ['hteam fix T-001 --force-round --note "<원인과 지시>"', "hteam drop T-001"])

    def test_exited_at_max_round_raises_max_rounds(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        self.d.handle(self.observed(did, "exited", key="exited"))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]), ("max_rounds", "작업자가 worker_done 없이 끝났고 최대 라운드다"))
        self.assertEqual(e["commands"], [FIX_FORCE_ROUND, "hteam drop T-001"])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("working", 1))
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 0)


class QuestionEscalationTest(EventCase):
    def test_question_raises_worker_question_with_grounds(self):
        for name in ("spec.md", "contracts.md"):  # interview.md·voice.md 는 없다(있는 것만 넣는다)
            path = self.proj / "docs" / "planning" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# 문서\n", encoding="utf-8")
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        code, asked = self.horch("ask", "--dispatch", did, "--question", "어느 쪽인가", "--timeout-ms", "100",
                                 terminal=term)
        self.assertEqual(code, 4, asked)
        self.d.handle(self.text_msg("question", did, "어느 쪽인가", mid=asked["question"]))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["task"], e["summary"], e["question"], e["message_id"]),
                         ("worker_question", "T-001", "어느 쪽인가", "어느 쪽인가", asked["question"]))
        self.assertEqual(e["files"], [".herdr-team/tasks/T-001.md", "docs/planning/spec.md", "docs/planning/contracts.md",
                                      ".herdr-team/roles/developer.md", ".herdr-team/project.md"])
        self.assertEqual(e["commands"], [f'hteam answer {e["id"]} "<답>"'])

    def test_escalation_summary_and_files(self):
        self.start()
        did = self.work_dispatch("T-001")
        self.act_work("T-001", outcome="failed")  # 보고서가 있다
        self.d.handle(self.text_msg("escalation", did, "막혔다" * 150))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]), ("escalation", ("막혔다" * 150)[:300]))
        self.assertEqual(e["files"], [".herdr-team/tasks/T-001.md", "docs/tasks/T-001/report.md"])
        self.assertEqual(e["commands"], [])

    def test_empty_escalation_uses_default_text(self):
        self.start()
        self.d.handle(self.text_msg("escalation", self.work_dispatch("T-001"), ""))
        self.assertEqual(self.decides()[0]["summary"], "워커가 done 없이 멈췄다")
        self.assertEqual(self.decides()[0]["files"], [".herdr-team/tasks/T-001.md"])


class IdleTest(EventCase):
    def test_work_idle_nudges_once_then_escalates_once(self):
        self.start()
        did = self.work_dispatch("T-001")
        self.d.handle(self.observed(did, "idle", key="1", status="idle"))
        self.assertEqual(self.dispatch_messages(did), [{"subject": "done 요청", "body": IDLE_TEXT}])
        self.assertEqual(self.decides(), [])
        self.d.handle(self.observed(did, "idle", key="2", status="done", mid=2))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]), ("escalation", "T-001 작업자가 done 없이 턴을 두 번 마쳤다"))
        self.assertEqual(e["commands"], [FIX, "hteam drop T-001"])
        self.d.handle(self.observed(did, "idle", key="3", status="done", mid=3))
        self.assertEqual(len(self.decides()), 1)
        self.assertEqual(len(self.dispatch_messages(did)), 1)

    def test_review_idle_nudges_then_abandons_and_retries(self):
        self.start()
        self.worked()
        first = self.attempt("T-001")
        self.d.handle(self.observed(first["dispatch"], "idle", key="1", status="idle"))
        self.assertEqual(self.dispatch_messages(first["dispatch"]), [{"subject": "done 요청", "body": IDLE_TEXT}])
        self.d.handle(self.observed(first["dispatch"], "idle", key="2", status="done", mid=2))
        self.assertEqual(self.dispatch_row(first["dispatch"])["state"], "released")  # --kill 뒤 review-finish 가 정리
        st = self.task_state("T-001")
        self.assertEqual((st["status"], self.attempt("T-001")["attempt"]), ("reviewing", 2))  # 시도 실패, 자동 재시도
        self.assertEqual(self.decides(), [])


class BlockedErrorTest(EventCase):
    def set_status(self, term: str, **status) -> None:
        with self._hc_locked() as st:
            st["terminals"][term]["status"] = {"app": "claude-code", **status}

    def test_blocked_raises_korean_summary_and_lifts_on_done(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        msg = "Bash 명령을 허용할까?" + "가" * 200
        self.set_status(term, state="blocked", kind="permission", msg=msg)
        self.d.handle(self.observed(did, "blocked", key="1", status="blocked"))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]),
                         ("escalation", f"T-001 작업자가 확인 창에서 멈췄다(permission: {msg[:120]})" + BLOCKED_TAIL))
        self.assertEqual(e["commands"], ['hteam fix T-001 --force --note "<지시>"', "hteam drop T-001 --force"])
        self.assertEqual(e["detail"], msg)
        st = self.task_state("T-001")
        self.assertEqual((st["blocked_decide"], st["decide"]), ({"id": e["id"], "dispatch": did}, e["id"]))
        self.set_status(term, state="idle", msg="")  # 사람이 넘겼고 작업자가 이어 가 done 했다
        self.act_work("T-001")
        self.d.handle(self.done_msg(did, mid=2))
        st = self.task_state("T-001")
        self.assertIsNone(st.get("blocked_decide"))
        self.assertIsNone(st.get("decide"))  # 그 decide 의 라운드 표시도 지워 리뷰로 간다
        self.assertEqual(self.progress(),
                         [f"T-001: {e['id']} 은 작업자가 이어 가서 닫아도 된다(worker_done 이 와서 리뷰로 간다)"])
        self.assertIn("review:T-001", self.d.jobs)
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_lift_without_progress_when_already_answered(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.set_status(term, state="blocked", kind="question", msg="계속할까?")
        self.d.handle(self.observed(did, "blocked", key="1", status="blocked"))
        self.answer(self.decides()[0]["id"])
        self.act_work("T-001")
        self.d.handle(self.done_msg(did, mid=2))
        self.assertEqual(self.progress(), [])
        self.assertIsNone(self.task_state("T-001").get("blocked_decide"))

    def test_error_raises_escalation(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.set_status(term, state="error", msg="API 오류: 과부하")
        self.d.handle(self.observed(did, "error", key="1", status="error"))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]), ("escalation", "T-001 작업자가 오류 상태다(API 오류: 과부하)"))


class GoneTest(EventCase):
    def test_exited_work_starts_fix_with_note(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        self.d.handle(self.observed(did, "exited", key="exited"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"][-1]["note"]), ("working", 2, GONE_NOTE))
        self.assertEqual(self.dispatch_row(did)["state"], "released")
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 1)
        self.assertEqual(self.decides(), [])

    def test_lost_work_is_the_same(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, reason="stopped_by_restart")
        self.d.handle(self.observed(did, "lost", key="lost"))
        self.assertEqual(self.task_state("T-001")["round"], 2)
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 1)

    def test_procedure_failure_carries_undelivered_note(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        from hteam import tasks
        with mock.patch.object(tasks, "fix", side_effect=HteamError("owns_locked", "겹친다", 3)):
            self.d.handle(self.observed(did, "exited", key="exited"))
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]),
                         ("escalation", f"관제 절차 실패: owns_locked: 겹친다 (아직 전하지 못한 지시: {GONE_NOTE})"))

    def test_review_busy_is_left_for_next_reconcile(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        from hteam import tasks
        with mock.patch.object(tasks, "fix", side_effect=HteamError("review_busy", "리뷰 관문이 돈다", 3)):
            self.d.handle(self.observed(did, "exited", key="exited"))
        self.assertEqual((self.decides(), self.task_state("T-001")["round"]), ([], 1))

    def test_fix_launch_failure_is_left_to_launch_failed_decide(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        self.fail_hc("run", "boom")
        self.d.handle(self.observed(did, "exited", key="exited"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], self.decides()), ("launch_failed", 2, []))
        self.d.reconcile()
        (e,) = self.decides()
        self.assertTrue(e["summary"].startswith("T-001 r2 실행이 실패했거나 도중에 끊겼다(launch_failed)."), e["summary"])

    def test_exited_reviewer_fails_attempt_and_retries(self):
        self.start()
        self.worked()
        first = self.attempt("T-001")
        self.update_terminal(self.dispatch_row(first["dispatch"])["terminal"], state="finished")
        self.d.handle(self.observed(first["dispatch"], "exited", key="exited"))
        st = self.task_state("T-001")
        self.assertEqual((st["status"], self.attempt("T-001")["attempt"]), ("reviewing", 2))
        self.assertEqual(self.decides(), [])


class NoWaitTest(EventCase):
    """관제 객체는 함수를 바로 부르므로 nowait 를 직접 넘긴다(설계 8.5, Task 5 Rules 7). 다른 리뷰 실행자가 finish 잠금을
    쥔 동안 fix·accept·review-finish 는 기다리지 않고 아무것도 바꾸지 않은 채 돌아온다(decide 도 없다)."""

    def test_drive_calls_do_not_wait_for_the_finish_lock(self):
        self.start()
        self.update_terminal(self.work_terminal(), state="finished")
        holder, release = self.hold_finish()
        for name, call in (("fix_task", lambda: self.d.fix_task("T-001", GONE_NOTE)),
                           ("accept_task", lambda: self.d.accept_task("T-001")),
                           ("finish_review", lambda: self.d.finish_review("T-001"))):
            errors = []
            worker = threading.Thread(target=lambda: _record(errors, call), daemon=True)
            worker.start()
            worker.join(10)  # 호출마다 따로 제한 시간을 둔다. 보유자는 시험이 놓기 전에는 풀리지 않는다
            if worker.is_alive():  # 기다리는 구현: 잠금을 놓아 그 호출을 끝내고 실패로 본다
                release()
                worker.join(60)
                self.fail(f"{name} 가 finish 잠금을 기다렸다")
            self.assertEqual(errors, [], name)
        self.assertIsNone(holder.poll())  # 세 호출 내내 보유자가 잠금을 쥐고 있었다
        release()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], self.decides()), ("working", 1, []))
        self.assertFalse(st["rounds"][0]["work"].get("canceled"))
        self.assertEqual(st["drive_fix"]["note"], GONE_NOTE)  # review_busy: 표시를 두고 다음 재확인이 잇는다


class DriveFixResumeTest(EventCase):
    """관제 fix 가 이전 Dispatch 를 정리한 뒤 새 라운드를 쓰기 전에 죽으면 재확인이 같은 지시로 잇는다(설계 8.7 의 drive_fix)."""

    def test_fix_interrupted_after_cleanup_resumes_with_the_same_note(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        proc = subprocess.run([sys.executable, "-c", FIX_RUNNER, str(ROOT / "lib"), str(self.proj), "T-001", GONE_NOTE],
                              capture_output=True, text=True, timeout=60,
                              env=self._env("drive", None, {"HTEAM_TEST_DIE_AT": "fix_closed"}))
        self.assertEqual(proc.returncode, 137, proc.stderr)
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["drive_fix"]["note"]), ("working", 1, GONE_NOTE))
        self.assertTrue(st["rounds"][0]["work"]["canceled"])
        self.assertEqual(self.dispatch_row(did)["state"], "released")  # 정리는 끝났고 새 라운드가 없다
        self.d.reconcile()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"][-1]["note"]), ("working", 2, GONE_NOTE))
        self.assertNotIn("drive_fix", st)
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 1)
        self.assertEqual(self.decides(), [])
        self.d.reconcile()
        self.assertEqual(self.task_state("T-001")["round"], 2)  # 한 번만 잇는다


class IgnoreTest(EventCase):
    def test_status_message_is_only_acked(self):
        self.start()
        self.d.handle(self.message("status", self.work_dispatch("T-001"), {"x": 1}))
        self.assertEqual((self.decides(), self.log_lines()), ([], []))

    def test_old_dispatch_message_is_logged_and_ignored(self):
        self.start()
        old, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, state="finished")
        self.d.handle(self.observed(old, "exited", key="exited"))
        self.d.handle(self.done_msg(old, mid=2))
        self.assertEqual(self.logged(f"T-001 지난 디스패치의 worker_done 무시: {old}"), 1)
        self.assertEqual((self.task_state("T-001")["round"], self.d.jobs), (2, {}))

    def test_closed_task_message_is_logged_and_ignored(self):
        self.start()
        did = self.work_dispatch("T-001")
        code, out = self.hteam("drop", "T-001", "--force")
        self.assertEqual(code, 0, out)
        self.d.handle(self.observed(did, "idle", key="1", status="idle"))
        self.assertEqual(self.logged(f"T-001 이미 끝난 태스크(dropped)의 observed 무시: {did}"), 1)
        self.assertEqual(self.decides(), [])

    def test_unknown_dispatch_is_logged(self):
        self.d.handle(self.message("worker_done", "dsp-ffffffff", {"dispatch": "dsp-ffffffff", "outcome": "succeeded"}))
        self.assertEqual(self.logged("모르는 Dispatch 의 worker_done 무시: dsp-ffffffff"), 1)
        self.assertEqual(self.decides(), [])


class ReviewFinishResultTest(EventCase):
    """리뷰어 worker_done → review-finish 결과 표(설계 8.6)."""

    def test_approved_accepts_and_starts_ready(self):
        self.write_spec("T-002", title="둘", depends="T-001")
        state.create(self.p, "T-002", "developer")
        self.start()
        self.worked()
        self.reviewed()
        self.assertEqual(self.task_state("T-001")["status"], "done")
        self.assertEqual(self.task_state("T-002")["status"], "working")  # accept 뒤 start-ready
        self.assertEqual(self.logged("T-001 r1 APPROVE"), 1)

    def test_changes_fixes_without_note(self):
        self.start()
        self.worked()
        self.reviewed(verdict="REQUEST_CHANGES")
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"], st["rounds"][-1]["note"]), ("working", 2, None))
        self.assertEqual(self.logged("T-001 r1 REQUEST_CHANGES"), 1)
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 1)

    def test_changes_with_untracked_owned_files_adds_note(self):
        self.start()
        self.worked()
        (self.proj / "src" / "scratch.txt").write_text("x\n")  # 리뷰 중 소유 경로 안의 추적 안 된 새 파일
        (self.proj / "notes.log").write_text("x\n")  # 소유 경로 밖은 지시에 넣지 않는다
        self.reviewed(verdict="REQUEST_CHANGES")
        self.assertEqual(self.task_state("T-001")["rounds"][-1]["note"],
                         "리뷰 중 소유 경로에 추적 안 된 파일이 생겼다. 커밋하거나 지운다: src/scratch.txt")

    def test_reviewer_still_running_waits(self):
        self.start()
        self.worked()
        self.d.finish_review("T-001")
        self.assertEqual((self.task_state("T-001")["status"], self.decides()), ("reviewing", []))

    def test_review_failed_twice_raises_escalation(self):
        self.start()
        self.worked()
        self.reviewed(verdict=None, write=False)  # 파일 없음: 시도 실패, 자동 재시도
        self.assertEqual(self.attempt("T-001")["attempt"], 2)
        self.reviewed(verdict=None, write=False)
        (e,) = self.decides()
        self.assertEqual(e["kind"], "escalation")
        self.assertTrue(e["summary"].startswith("리뷰 실패(review_failed): "), e["summary"])
        self.assertEqual(e["commands"], ["hteam review T-001 --retry", "hteam drop T-001"])

    def test_tampered_raises_escalation(self):
        self.start()
        self.worked()
        self.commit("README.md", "# 바뀜\n", "리뷰 중 다른 커밋")  # 제외 경로 밖 추적 파일을 바꾼다
        self.reviewed()
        (e,) = self.decides()
        self.assertTrue(e["summary"].startswith("리뷰 실패(review_tampered): "), e["summary"])
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_other_error_raises_procedure_failure(self):
        self.start()
        self.worked()
        with mock.patch.object(review, "review_finish", side_effect=HteamError("boom", "예상 밖", 1)):
            self.d.finish_review("T-001")
        self.assertEqual(self.decides()[0]["summary"], "관제 절차 실패: boom: 예상 밖")


class ReviewFinishMaxRoundTest(EventCase):
    config = _with_rounds(BASE_CONFIG, 1)

    def test_changes_at_max_round_raises_max_rounds(self):
        self.start()
        self.worked()
        self.reviewed(verdict="REQUEST_CHANGES")
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]), ("max_rounds", "최대 1 라운드에도 승인되지 않았다"))
        self.assertEqual(e["files"], ["docs/reviews/T-001/r1.md"])
        self.assertEqual(e["commands"], [FIX_FORCE_ROUND, "hteam drop T-001"])
        self.assertEqual(self.task_state("T-001")["status"], "changes")


class ReviewChildResultTest(EventCase):
    """`hteam review T` 자식 결과 표(설계 8.6)."""

    def test_precheck_changes_fixes_with_reason(self):
        self.start()
        self.worked(files={"src/app.py": "print(1)\n", "README.md": "# 밖\n"})  # owns 밖 커밋: 사전 검사 반려
        st = self.task_state("T-001")
        problems = st["rounds"][0]["prechecks"]
        self.assertEqual((st["status"], st["round"]), ("working", 2))
        self.assertEqual(st["rounds"][-1]["note"], ("사전 검사 반려: " + "; ".join(problems))[:300])
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 1)

    def test_gate_rejection_fixes_then_repeat_raises_decide(self):
        self.use_gate()
        self.gate_modes("fail", "fail", "fail", "fail")  # 라운드마다 quick 1차·2차
        self.rearm()
        self.start()
        self.worked()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("working", 2))
        self.assertEqual(st["rounds"][-1]["note"],
                         "테스트 관문 반려: quick 이 통과하지 못했다(docs/reviews/T-001/r1.md 의 출력 끝을 본다)")
        self.worked()
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]),
                         ("repeat_test_failure", "같은 quick 테스트 실패로 hteam 사전 검사가 두 라운드 연속 반려했다"))
        self.assertEqual(e["files"], ["docs/reviews/T-001/r2.md"])
        self.assertEqual(e["commands"], [FIX, "hteam drop T-001"])
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["round"]), ("changes", 2))

    def test_unrunnable_test_raises_test_config(self):
        self.use_gate()
        self.gate_modes("missing")  # exit 127: test_unrunnable(exit 2), 리뷰는 아무것도 쓰지 않는다
        self.rearm()
        self.start()
        self.worked()
        (e,) = self.decides()
        self.assertEqual(e["kind"], "test_config")
        self.assertEqual(e["files"], ["docs/planning/tasks.toml"])
        self.assertEqual(e["commands"], ['hteam task new --role planner --title "[test] 고치기"'])
        self.assertEqual(self.task_state("T-001")["status"], "working")

    def test_bad_test_approvals_raises_escalation_with_path(self):
        self.use_gate()
        self.rearm()
        path = testgate.approvals_path(self.p)
        path.write_text("{깨짐", encoding="utf-8")
        self.start()
        self.worked()
        (e,) = self.decides()
        self.assertEqual(e["kind"], "escalation")
        self.assertIn(str(path), e["summary"])

    def test_tests_skipped_asks_test_confirm(self):
        self.use_gate(approve=False)  # 확정하지 않은 [test]: 관문 없이 리뷰어를 띄우고 tests_skipped
        self.rearm()
        self.start()
        with mock.patch.object(self.d, "confirm_test") as hook:
            self.worked()
        hook.assert_called_once_with()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_uncommitted_owned_fixes_with_note(self):
        self.start()
        self.d.on_review_result("T-001", 2, {"ok": False, "error": {"code": "uncommitted_owned",
                                                                    "message": "소유 경로에 커밋 안 된 변경", "hint": ""}})
        st = self.task_state("T-001")
        self.assertEqual((st["round"], st["rounds"][-1]["note"]), (2, "커밋 안 된 파일을 커밋하거나 지운다"))

    def test_lock_timeout_retries_at_reconcile(self):
        self.start()
        self.act_work("T-001")
        self.d.on_review_result("T-001", 4, {"ok": False, "error": {"code": "test_lock_timeout", "message": "대기 초과",
                                                                    "hint": ""}})
        self.assertEqual((self.d.retry_reviews, self.decides()), ({"T-001"}, []))
        self.d.reconcile()
        self.assertIn("review:T-001", self.d.jobs)
        self.assertEqual(self.d.retry_reviews, set())
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_conflict_does_nothing(self):
        self.start()
        self.d.on_review_result("T-001", 3, {"ok": False, "error": {"code": "review_in_progress", "message": "진행 중",
                                                                    "hint": ""}})
        self.assertEqual((self.decides(), self.task_state("T-001")["round"]), ([], 1))

    def test_other_failure_raises_escalation(self):
        self.start()
        self.d.on_review_result("T-001", 1, {"ok": False, "error": {"code": "plan_incomplete", "message": "앞선 plan apply",
                                                                    "hint": ""}})
        self.assertEqual(self.decides()[0]["summary"], "리뷰를 시작하지 못했다(exit 1): plan_incomplete: 앞선 plan apply")

    def test_child_without_json_raises_escalation(self):
        self.start()
        self.d.on_review_result("T-001", -9, None)
        self.assertEqual(self.decides()[0]["summary"], "리뷰를 시작하지 못했다(exit -9): 출력이 없다")


class ReviewChildMaxRoundTest(EventCase):
    config = _with_rounds(BASE_CONFIG, 1)

    def test_precheck_changes_at_max_round_raises_max_rounds(self):
        self.start()
        self.worked(files={"README.md": "# 밖\n"})
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["summary"]), ("max_rounds", "최대 1 라운드에도 승인되지 않았다"))
        self.assertEqual(e["commands"], [FIX_FORCE_ROUND, "hteam drop T-001"])


class ReviewRetryChildTest(EventCase):
    """큐 review --retry 는 리뷰 자식으로 돈다(설계 8.8, Task 5 의 spawn_review): 자식은 숨은 --round·--request 를 받는다."""

    def failed_review(self) -> None:
        self.start()
        self.worked()
        self.reviewed(verdict=None, write=False)
        self.reviewed(verdict=None, write=False)  # 두 번 실패: review_failed decide
        self.assertEqual(self.attempt("T-001")["result"], "failed")

    def test_queue_retry_runs_as_child_with_round_and_request(self):
        self.failed_review()
        proc = self.main_bg("review", "T-001", "--retry")
        self.assertEqual(self.d.run_queue(), ["q-000001"])
        code, out = self.finish(proc)
        self.assertEqual((code, out["task"], out["spawned"]), (0, "T-001", True), out)
        self.assertEqual(self.d.jobs["review:T-001"]["args"],
                         ["review", "T-001", "--retry", "--round", "1", "--request", "q-000001"])
        self.wait_jobs()
        att = self.attempt("T-001")
        self.assertEqual((att["attempt"], att.get("result")), (3, None))
        self.assertTrue(any(e.get("request") == "q-000001" for e in self.task_state("T-001")["history"]))

    def test_hidden_flags_are_drive_only_and_round_is_checked(self):
        self.failed_review()
        code, out = self.hteam("review", "T-001", "--retry", "--round", "2")  # 관제 안: 라운드가 바뀌었으면 거부
        self.assertEqual((code, out["error"]["code"]), (3, "round_changed"), out)
        self.assertEqual(self.attempt("T-001")["attempt"], 2)
        code, out = self.hteam("review", "T-001", "--retry", "--request", "q-000009", as_="main")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)

    def test_lock_timeout_retry_keeps_retry_args(self):
        """큐 review --retry 자식이 관문 잠금 대기 초과(exit 4)로 끝나면 재확인이 같은 인자로 다시 띄운다(인자 없이 띄우면
        reviewing 의 실패 시도에 bad_state 로 끝난다. Codex 커밋 리뷰 75a6612)."""
        self.failed_review()
        args = ["review", "T-001", "--retry", "--round", "1", "--request", "q-000001"]
        out, err = self.tmp / "timeout.out", self.tmp / "timeout.err"
        line = json.dumps({"ok": False, "error": {"code": "test_lock_timeout", "message": "대기 초과", "hint": ""}})
        with open(out, "w", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
            proc = subprocess.Popen([sys.executable, "-c", f"print({line!r}); raise SystemExit(4)"], stdout=fo, stderr=fe)
        self.d.jobs["review:T-001"] = {"proc": proc, "args": args, "out": out, "err": err}  # 그 자식이 도는 중이었다
        self.wait_jobs()
        self.assertEqual(self.d.retry_reviews, {"T-001"})
        self.d.reconcile()
        self.assertEqual(self.d.jobs["review:T-001"]["args"], args)
        self.wait_jobs()
        att = self.attempt("T-001")
        self.assertEqual((att["attempt"], att.get("result")), (3, None))


class AcceptAfterTest(EventCase):
    """accept 뒤(설계 8.6): 직무·결과별 다음 자리, release 실패 progress, 끝에 start-ready."""

    def approved(self, tid: str, role: str) -> None:
        """리뷰가 승인한 상태를 바로 만든다(작업·리뷰 Dispatch 없음)."""
        owns = {"planner": "docs/planning/**", "tester": "tests/**"}.get(role)
        self.write_spec(tid, role=role, title=f"{role} 일", owns=owns)
        state.create(self.p, tid, role)
        with state.edit(self.p, tid) as st:
            st.update(status="approved", round=1, base=self.head(), owns=[owns or "src/**"],
                      rounds=[{"round": 1, "round_base": self.head(), "agent": "claude", "model": None,
                               "effort": None, "note": None, "supplement": None,
                               "work": dispatch.new_slot(f"{tid} r1 작업"), "reviews": [], "verdict": "APPROVE"}])

    def test_planner_done_goes_to_apply_plan(self):
        self.approved("T-003", "planner")
        with mock.patch.object(self.d, "apply_plan") as plan, mock.patch.object(self.d, "start_ready") as ready:
            self.d.accept_task("T-003")
        plan.assert_called_once_with("T-003")
        ready.assert_called_once_with()
        self.assertEqual(self.task_state("T-003")["status"], "done")

    def test_tester_done_goes_to_batch_done(self):
        self.approved("T-004", "tester")
        with mock.patch.object(self.d, "batch_done") as batch, mock.patch.object(self.d, "apply_plan") as plan:
            self.d.accept_task("T-004")
        batch.assert_called_once_with("T-004")
        plan.assert_not_called()

    def test_queue_accept_goes_through_the_same_after_accept(self):
        """메인의 큐 accept 도 accept 뒤 처리를 거친다(설계 8.6 "관제 판정 경로와 큐 accept 모두")."""
        self.approved("T-004", "tester")
        proc = self.main_bg("accept", "T-004")
        with mock.patch.object(self.d, "batch_done") as batch, mock.patch.object(self.d, "start_ready") as ready:
            self.assertEqual(self.d.run_queue(), ["q-000001"])
        code, out = self.finish(proc)
        self.assertEqual((code, out["status"]), (0, "done"), out)
        batch.assert_called_once_with("T-004")
        ready.assert_called_once_with()

    def test_release_failure_is_progress(self):
        self.start()
        self.act_work("T-001")
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
        self.act_review("T-001", "APPROVE")
        self.assertEqual(self.hteam("review-finish", "T-001")[1].get("status"), "approved")
        self.fail_hc("rm", "busy")
        self.d.accept_task("T-001")
        self.assertEqual(self.task_state("T-001")["status"], "done")
        (body,) = self.progress()
        self.assertTrue(body.startswith("T-001 워커 해제 실패: "), body)
        self.assertLessEqual(len(body), len("T-001 워커 해제 실패: ") + 200)


class AwaitingUserTest(AcceptAfterTest):
    config = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["developer"]')

    def test_awaiting_user_goes_to_design_step(self):
        self.approved("T-005", "developer")
        with mock.patch.object(self.d, "design_step") as design:
            self.d.accept_task("T-005")
        design.assert_called_once_with()
        self.assertEqual(self.task_state("T-005")["status"], "awaiting_user")

    test_planner_done_goes_to_apply_plan = None
    test_tester_done_goes_to_batch_done = None
    test_queue_accept_goes_through_the_same_after_accept = None
    test_release_failure_is_progress = None


class ReconcileTest(EventCase):
    """재확인(설계 8.7): 워커 목록 사본과 reconcile_task 의 상태별 표."""

    def test_writes_worker_copy(self):
        self.start()
        self.d.reconcile()
        copy = json.loads((self.drive_dir / "workers.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(copy), ["at", "rows"])
        self.assertRegex(copy["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual([r["id"] for r in copy["rows"]], [self.work_dispatch("T-001")])

    def test_open_decide_is_left_alone_until_answered(self):
        self.start()
        self.act_work("T-001")  # 작업자는 끝났다(settled). worker_done 을 놓쳤다
        oid = self.d.decide("escalation", "T-001", "메인이 정한다")
        self.d.reconcile()
        self.assertEqual(self.d.jobs, {})
        self.answer(oid)
        self.d.reconcile()
        self.assertIn("review:T-001", self.d.jobs)

    def test_queued_fix_is_left_alone(self):
        self.start()
        self.act_work("T-001")
        self.set_state("T-001", queued_fix={"note": "메인 지시", "supplement": None, "force_round": False,
                                            "at": "2026-01-01T00:00:00Z", "request": None})
        self.d.reconcile()
        self.assertEqual(self.d.jobs, {})

    def test_settled_worker_without_message_goes_to_review(self):
        self.start()
        self.act_work("T-001")
        self.d.reconcile()
        self.assertIn("review:T-001", self.d.jobs)
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_retained_resumes_review_unless_another_executor_holds_finish_lock(self):
        self.start()
        did = self.work_dispatch("T-001")
        self.act_work("T-001")
        code, out = self.horch("worker-retain", "--dispatch", did)
        self.assertEqual(code, 0, out)
        with state.finish_lock(self.p, "T-001"):  # 죽은 관제가 남긴 리뷰 자식이 관문을 도는 중
            self.d.reconcile()
            self.assertEqual(self.d.jobs, {})
        self.d.reconcile()
        self.assertIn("review:T-001", self.d.jobs)
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")

    def test_unlaunched_attempt_record_resumes_review(self):
        self.start()
        self.act_work("T-001")
        code, _ = self.hteam("review", "T-001", env={"HTEAM_TEST_DIE_AT": "after_attempt"})
        self.assertEqual(code, 137)
        att = self.attempt("T-001")
        self.assertEqual((self.task_state("T-001")["status"], att["dispatch"]), ("working", None))
        self.d.reconcile()
        self.wait_jobs()
        self.assertEqual(self.task_state("T-001")["status"], "reviewing")
        self.assertEqual(self.attempt("T-001")["attempt"], att["attempt"])  # 같은 시도를 잇는다(6.1 0)

    def test_live_worker_clears_unknown_mark(self):
        self.start()
        self.set_state("T-001", liveness_unknown_since=ago(120))
        self.d.reconcile()
        self.assertNotIn("liveness_unknown_since", self.task_state("T-001"))
        self.assertEqual(self.decides(), [])

    def test_no_status_over_a_minute_raises_once(self):
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.update_terminal(term, status=None)
        conn = sqlite3.connect(self.horch_home / "orch.db")
        conn.execute("UPDATE dispatches SET created_at=? WHERE id=?", (ago(120), did))
        conn.commit()
        conn.close()
        self.d.reconcile()
        self.d.reconcile()
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["task"], e["summary"]), ("escalation", "T-001", NO_STATUS))

    def test_exited_worker_starts_fix(self):
        self.start()
        self.update_terminal(self.work_terminal(), state="finished")
        self.d.reconcile()
        st = self.task_state("T-001")
        self.assertEqual((st["round"], st["rounds"][-1]["note"]), (2, GONE_NOTE))
        self.assertEqual(self.logged("T-001 r2 수정 시작"), 1)

    def test_unverifiable_over_thirty_minutes_raises_once_and_does_not_kill(self):
        self.start()
        self.update_terminal(self.work_terminal(), state="restarting")  # live·finished 가 아니다: 판정 unverifiable
        self.d.reconcile()
        self.assertIn("liveness_unknown_since", self.task_state("T-001"))
        self.assertEqual(self.decides(), [])
        self.set_state("T-001", liveness_unknown_since=ago(31 * 60))
        self.d.reconcile()
        self.d.reconcile()
        (e,) = self.decides()
        self.assertTrue(e["summary"].startswith("작업자 생존을 31분 넘게 확인하지 못했다("), e["summary"])
        self.assertTrue(e["summary"].endswith("). 끝났는지 알 수 없어 그대로 둔다. 작업자 탭이 멈췄으면 다시 보내거나 중단한다"))
        self.assertEqual(e["commands"], ['hteam fix T-001 --force --note "<지시>"', "hteam drop T-001 --force"])
        self.assertTrue(self.task_state("T-001")["liveness_escalated"])
        self.assertFalse([c for c in self.hc_calls() if c[:1] == ["kill"]])

    def test_reviewing_finishes_ended_reviewer_and_waits_for_live_one(self):
        self.start()
        self.worked()
        self.d.reconcile()
        self.assertEqual((self.task_state("T-001")["status"], self.decides()), ("reviewing", []))
        self.act_review("T-001", "APPROVE")  # 리뷰어가 끝났다. 그 worker_done 을 놓쳤다
        self.d.reconcile()
        self.assertEqual(self.task_state("T-001")["status"], "done")

    def test_review_failure_saved_before_decide_is_raised_once(self):
        """review-finish 가 시도 실패를 쓴 뒤 관제가 decide 전에 죽었다(설계 8.7 의 reviewing 줄)."""
        self.start()
        self.worked()
        self.reviewed(verdict=None, write=False)  # 첫 시도 실패: 자동 재시도
        self.act_review("T-001", None, write=False)
        code, out = self.hteam("review-finish", "T-001")  # 결과를 쓰고 decide 없이 끝난 실행자
        self.assertEqual((code, out["error"]["code"]), (1, "review_failed"), out)
        self.assertEqual(self.decides(), [])
        self.d.reconcile()
        (e,) = self.decides()
        self.assertTrue(e["summary"].startswith("리뷰 실패(review_failed): T-001 r1 리뷰 시도가 실패했다: "), e["summary"])
        self.assertEqual(e["commands"], ["hteam review T-001 --retry", "hteam drop T-001"])
        self.assertEqual(self.task_state("T-001")["review_failure_asked"], [1, 2])
        self.answer(e["id"])
        self.d.reconcile()
        self.assertEqual(len(self.decides()), 1)  # 같은 시도로는 다시 올리지 않는다

    def test_tamper_saved_before_decide_is_raised_once(self):
        self.start()
        self.worked()
        self.commit("README.md", "# 바뀜\n", "리뷰 중 다른 커밋")
        self.act_review("T-001", "APPROVE")
        code, out = self.hteam("review-finish", "T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "review_tampered"), out)
        self.d.reconcile()
        (e,) = self.decides()
        self.assertTrue(e["summary"].startswith("리뷰 실패(review_tampered): T-001 r1 리뷰 중 제품이 바뀌었다: README.md"),
                        e["summary"])
        self.answer(e["id"])
        self.d.reconcile()
        self.assertEqual(len(self.decides()), 1)

    def test_handled_review_failure_is_not_raised_again(self):
        self.start()
        self.worked()
        self.reviewed(verdict=None, write=False)
        self.reviewed(verdict=None, write=False)  # 관제가 review-finish 결과로 decide 를 올렸다
        (e,) = self.decides()
        self.answer(e["id"])
        self.d.reconcile()
        self.assertEqual(len(self.decides()), 1)

    def test_approved_is_accepted(self):
        self.start()
        self.act_work("T-001")
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
        self.act_review("T-001", "APPROVE")
        self.assertEqual(self.hteam("review-finish", "T-001")[1].get("status"), "approved")
        self.d.reconcile()
        self.assertEqual(self.task_state("T-001")["status"], "done")

    def test_changes_from_reviewer_and_from_hteam(self):
        self.start()
        self.act_work("T-001")
        self.assertEqual(self.hteam("review", "T-001")[0], 0)
        self.act_review("T-001", "REQUEST_CHANGES")
        self.assertEqual(self.hteam("review-finish", "T-001")[1].get("status"), "changes")
        self.d.reconcile()
        st = self.task_state("T-001")
        self.assertEqual((st["round"], st["rounds"][-1]["note"]), (2, None))
        self.act_work("T-001", files={"README.md": "# 밖\n"})
        self.assertEqual(self.hteam("review", "T-001")[1].get("source"), "hteam")
        self.d.reconcile()
        st = self.task_state("T-001")
        self.assertEqual(st["round"], 3)
        self.assertTrue(st["rounds"][-1]["note"].startswith("사전 검사 반려: "), st["rounds"][-1]["note"])
        self.assertEqual((self.logged("T-001 r2 수정 시작"), self.logged("T-001 r3 수정 시작")), (1, 1))

    def test_pending_with_dropped_dependency_raises_once(self):
        state.create(self.p, "T-001", "developer")
        self.assertEqual(self.hteam("drop", "T-001")[0], 0)
        self.write_spec("T-002", title="둘", depends="T-001")
        state.create(self.p, "T-002", "developer")
        self.d.reconcile()
        self.d.reconcile()
        (e,) = self.decides()
        self.assertEqual((e["kind"], e["task"]), ("escalation", "T-002"))
        self.assertEqual(e["summary"], "선행 태스크 T-001 가 중단(dropped)돼 T-002 를 시작할 수 없다. 진행하지 않으면 drop "
                                       "하고, 이어 가려면 depends_on 을 고친다")
        self.assertEqual(e["files"], [".herdr-team/tasks/T-002.md"])
        self.assertEqual(e["commands"], ["hteam drop T-002", "depends_on 을 고쳐 커밋한 뒤 hteam start T-002"])

    def test_launch_failed_raises_once_with_left_workers_and_error(self):
        self.fail_hc("run", "boom")
        code, out = self.hteam("start", "T-001")
        self.assertEqual(code, 1, out)
        self.d.reconcile()
        self.d.reconcile()
        (e,) = self.decides()
        self.assertTrue(e["summary"].startswith("T-001 r1 실행이 실패했거나 도중에 끊겼다(launch_failed). 남은 워커 없음. "
                                                "오류: launch_failed: "), e["summary"])
        self.assertEqual(e["commands"], ["hteam start T-001", "hteam drop T-001"])

    def test_launch_failed_not_raised_while_launcher_lives_or_when_transient(self):
        self.fail_hc("run", "boom")
        self.assertEqual(self.hteam("start", "T-001")[0], 1)
        proc = self.sleeper()
        with state.edit(self.p, "T-001") as st:
            st["rounds"][-1]["work"]["launched"] = {"pid": proc.pid, "started": procs.start_time(proc.pid)}
        self.d.reconcile()
        self.assertEqual(self.decides(), [])
        with state.edit(self.p, "T-001") as st:
            st["rounds"][-1]["work"]["launched"] = None
            st["rounds"][-1]["work"]["transient"] = True  # 고정 에이전트가 바빠 넣지 않았다(Task 7 이 쓴다)
        with mock.patch.object(self.d, "start_ready"):  # 재확인의 start-ready 가 다시 넣지 않게(여기서는 decide 만 본다)
            self.d.reconcile()
        self.assertEqual(self.decides(), [])

    def test_done_planner_without_plan_applied_goes_to_apply_plan(self):
        self.write_spec("T-003", role="planner", title="기획", owns="docs/planning/**")
        state.create(self.p, "T-003", "planner")
        self.set_state("T-003", status="done")
        with mock.patch.object(self.d, "apply_plan") as plan:
            self.d.reconcile()
        plan.assert_called_once_with("T-003")
        self.set_state("T-003", plan_applied=True)
        with mock.patch.object(self.d, "apply_plan") as plan:
            self.d.reconcile()
        plan.assert_not_called()

    def test_running_child_task_is_left_alone(self):
        self.start()
        self.act_work("T-001")
        self.d.jobs["review:T-001"] = {"proc": self.sleeper(), "args": ["review", "T-001"]}
        self.assertTrue(self.d.running("review:T-001"))
        self.d.reconcile()
        self.assertEqual(sorted(self.d.jobs), ["review:T-001"])  # 다시 띄우지 않는다
        del self.d.jobs["review:T-001"]

    def test_reconcile_order_and_hooks(self):
        calls = []
        names = ("write_workers", "crew_check", "handoff_check", "unbatched", "start_ready", "design_step",
                 "resume_decisions", "finish_step")
        with mock.patch.multiple(self.d, **{n: mock.DEFAULT for n in names}) as mocks:
            for n in names:
                mocks[n].side_effect = (lambda n=n: calls.append(n) or ([] if n == "write_workers" else None))
            self.d.reconcile()
        self.assertEqual(calls, list(names))

    def test_one_task_failure_does_not_stop_others(self):
        self.start()
        self.act_work("T-001")
        self.write_spec("T-002", title="둘", owns="src/b/**")
        state.create(self.p, "T-002", "developer")
        real = self.d.reconcile_task

        def boom(st):
            if st["id"] == "T-002":
                raise RuntimeError("깨짐")
            return real(st)

        with mock.patch.object(self.d, "reconcile_task", side_effect=boom), mock.patch.object(self.d, "start_ready"):
            self.d.reconcile()
        self.assertIn("review:T-001", self.d.jobs)
        self.assertEqual(self.logged("reconcile:T-002 실패: RuntimeError: 깨짐"), 1)


class FinalJobTest(EventCase):
    def test_final_child_result_goes_to_final_done(self):
        """마무리 전체 테스트 자식(키 final)의 결과는 final_done(code, 마지막 JSON 객체 dict, stderr) 이 받는다(Task 10 이
        채운다. Task 10 은 out.get("error") 부터 읽는다)."""
        self.assertTrue(self.d.spawn("final", ["version"]))
        self.assertTrue(self.d.running("final"))
        with mock.patch.object(self.d, "final_done") as done:
            self.wait_jobs()
        (code, out, err), _ = done.call_args
        self.assertEqual(code, 0)
        self.assertIsInstance(out, dict)
        self.assertIn("version", out)
        self.assertEqual(err, "")
        self.assertFalse(self.d.running("final"))


class DecideMarkTest(EventCase):
    """리뷰 자식이 도는 동안 decide 표시를 미룬다(설계 8.8, 8.10)."""

    def test_marks_wait_for_review_child(self):
        self.start()
        did = self.work_dispatch("T-001")
        self.act_work("T-001")
        gate = self.tmp / "pause"
        with mock.patch.dict("os.environ", {"HTEAM_TEST_PAUSE_AT": "after_attempt", "HTEAM_TEST_PAUSE_FILE": str(gate)}):
            self.d.handle(self.done_msg(did))
        deadline = time.monotonic() + 30
        while not gate.with_name("pause.reached").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        oid = self.d.decide("escalation", "T-001", "자식이 도는 동안 올린 판단")
        self.assertIsNone(self.task_state("T-001").get("decide"))
        gate.touch()
        self.wait_jobs()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st["decide"], st["decide_round"]), ("reviewing", oid, 1))

    def test_lift_drops_deferred_mark(self):
        """리뷰 자식이 도는 동안 올린 확인 창 decide 를 worker_done 이 풀면 미룬 표시도 지운다. 자식을 거둘 때 풀린 decide 가
        다시 써져 재확인이 그 태스크를 건드리지 않는 일이 없다(Codex 커밋 리뷰 75a6612)."""
        self.start()
        did, term = self.work_dispatch("T-001"), self.work_terminal()
        self.act_work("T-001")
        gate = self.tmp / "pause"
        with mock.patch.dict("os.environ", {"HTEAM_TEST_PAUSE_AT": "after_attempt", "HTEAM_TEST_PAUSE_FILE": str(gate)}):
            self.d.handle(self.done_msg(did))
        deadline = time.monotonic() + 30
        while not gate.with_name("pause.reached").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        with self._hc_locked() as hc:
            hc["terminals"][term]["status"] = {"app": "claude-code", "state": "blocked", "kind": "permission",
                                               "msg": "허용할까?"}
        self.d.handle(self.observed(did, "blocked", key="1", status="blocked", mid=2))
        (e,) = self.decides()
        self.assertEqual(self.d.pending_marks, {"T-001": (e["id"], 1)})
        self.d.handle(self.done_msg(did, mid=3))  # 사람이 넘겼고 작업자가 이어 가 done 했다
        self.assertEqual(self.d.pending_marks, {})
        gate.touch()
        self.wait_jobs()
        st = self.task_state("T-001")
        self.assertEqual((st["status"], st.get("decide"), st.get("blocked_decide")), ("reviewing", None, None))


class UnrecordedDispatchTest(EventCase):
    """상태 파일에 아직 기록되지 않은 Dispatch 의 메시지(설계 8.6 "모르는 Dispatch", Codex 커밋 리뷰 75a6612): 워커 목록을
    새로 받아 이 Run 의 진행 중 워커면 ack 하지 않고 미뤘다가 상태가 기록된 다음 틱에 처리한다."""

    def acked(self, mid: int) -> bool:
        conn = sqlite3.connect(self.horch_home / "orch.db")
        try:
            row = conn.execute("SELECT d.acked_at FROM messages m JOIN deliveries d ON d.id = m.delivery_id WHERE m.id=?",
                               (mid,)).fetchone()
        finally:
            conn.close()
        return bool(row and row[0])

    def reviewer(self) -> tuple[str, str]:
        conn = sqlite3.connect(self.horch_home / "orch.db")
        try:
            row = conn.execute("SELECT d.id, d.terminal FROM dispatches d JOIN tasks t ON t.id = d.task_id WHERE t.title=?",
                               ("T-001 r1 리뷰 a1",)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        return row[0], row[1]

    def test_question_from_unrecorded_reviewer_waits_for_state(self):
        self.start()
        self.act_work("T-001")
        gate = self.tmp / "pause"
        with mock.patch.dict("os.environ", {"HTEAM_DRIVE_WAIT_MS": "200"}):
            with mock.patch.dict("os.environ", {"HTEAM_TEST_PAUSE_AT": "after_launch",
                                                "HTEAM_TEST_PAUSE_FILE": str(gate)}):
                self.d.check_mail()  # 작업 worker_done → 리뷰 자식. 리뷰어를 띄운 뒤 상태에 기록하기 전에 멈춘다
            self.assertIn("review:T-001", self.d.jobs)
            deadline = time.monotonic() + 30
            while not gate.with_name("pause.reached").exists():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
            self.assertIsNone(self.attempt("T-001")["dispatch"])
            did, term = self.reviewer()
            code, asked = self.horch("ask", "--dispatch", did, "--question", "어느 쪽인가", "--timeout-ms", "100",
                                     terminal=term)
            self.assertEqual(code, 4, asked)
            self.d.check_mail()
            self.d.check_mail()  # 미룬 묶음이 다시 온다
            self.assertEqual(self.decides(), [])
            self.assertFalse(self.acked(asked["question"]))
            self.assertEqual(self.logged(f"모르는 Dispatch 의 question 무시: {did}"), 0)
            gate.touch()
            self.wait_jobs()
            self.assertEqual(self.attempt("T-001")["dispatch"], did)
            self.d.check_mail()  # 상태가 기록됐다: 이번에는 처리한다
            (e,) = self.decides()
            self.assertEqual((e["kind"], e["question"], e["message_id"]), ("worker_question", "어느 쪽인가", asked["question"]))
            self.d.check_mail()  # 이번에는 ack 한다. 같은 질문을 다시 올리지 않는다
            self.assertTrue(self.acked(asked["question"]))
            self.assertEqual(len(self.decides()), 1)


class StartReadyDecideTest(EventCase):
    """start-ready 는 지금 라운드의 열린 decide 가 있는 태스크를 띄우지 않는다(설계 5.4)."""

    def failed_start(self) -> None:
        self.fail_hc("run", "boom")
        self.assertEqual(self.hteam("start", "T-001")[0], 1)
        with self._hc_locked() as st:
            st["fail"].pop("run")

    def test_launch_failed_with_open_decide_is_skipped_but_named_start_runs(self):
        self.failed_start()
        self.d.reconcile()  # launch_failed decide
        (e,) = self.decides()
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["started"], [])
        self.assertEqual(out["waiting"], [{"task": "T-001", "reason": "decide",
                                           "detail": f"메인이 답하지 않은 decide {e['id']} 가 있다"}])
        code, out = self.hteam("start", "T-001")  # 메인이 이름으로 고른 복구(큐의 start T)는 그대로 실행한다
        self.assertEqual((code, self.task_state("T-001")["status"]), (0, "working"), out)

    def test_launch_failed_without_decide_is_restarted(self):
        self.failed_start()
        code, out = self.hteam("start-ready")
        self.assertEqual(code, 0, out)
        self.assertEqual([s["task"] for s in out["started"]], ["T-001"])

    def test_answered_decide_no_longer_blocks(self):
        state.create(self.p, "T-001", "developer")
        oid = self.d.decide("escalation", "T-001", "pending 에 올린 판단")
        self.assertEqual(self.hteam("start-ready")[1]["waiting"][0]["reason"], "decide")
        self.answer(oid)
        self.assertEqual([s["task"] for s in self.hteam("start-ready")[1]["started"]], ["T-001"])

    def test_decide_raised_after_candidate_check_is_seen_in_reservation(self):
        state.create(self.p, "T-001", "developer")
        gate = self.tmp / "gate"
        proc = self.hteam_bg("start-ready", env={"HTEAM_TEST_PAUSE_AT": "start_ready_checked",
                                                 "HTEAM_TEST_PAUSE_FILE": str(gate)})
        deadline = time.monotonic() + 30
        while not gate.with_name("gate.reached").exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.d.decide("escalation", "T-001", "검사 뒤 올린 판단")
        gate.touch()
        code, out = self.finish(proc)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["started"], [])
        self.assertEqual(out["waiting"][0]["reason"], "decide")
        self.assertEqual(self.task_state("T-001")["status"], "pending")


class StatusCopyTest(EventCase):
    """status 는 horch 를 부르지 않고 관제의 워커 목록 사본을 읽는다(설계 8.3)."""

    def recording(self) -> dict:
        wrap = self.tmp / "record-horch"
        wrap.write_text(RECORD_HORCH, encoding="utf-8")
        wrap.chmod(0o755)
        self.calls = self.tmp / "horch-calls.jsonl"
        return {"HERDR_ORCH_BIN": str(wrap), "HORCH_REAL": str(HORCH_BIN), "HORCH_CALLS": str(self.calls)}

    def test_status_reads_copy_and_calls_no_horch(self):
        self.start()
        self.act_work("T-001")
        self.d.write_workers()
        copy = json.loads((self.drive_dir / "workers.json").read_text(encoding="utf-8"))
        code, out = self.hteam("status", as_="main", env=self.recording())
        self.assertEqual(code, 0, out)
        self.assertFalse(self.calls.exists())
        self.assertEqual(out["workers_at"], copy["at"])
        (task,) = out["tasks"]
        self.assertEqual((task["next"], task["hint"]), (None, "관제가 한다(hteam review T-001)"))

    def test_status_without_copy_says_so(self):
        self.start()
        (self.drive_dir / "workers.json").unlink(missing_ok=True)
        code, out = self.hteam("status", as_="main", env=self.recording())
        self.assertEqual(code, 0, out)
        self.assertFalse(self.calls.exists())
        self.assertIsNone(out["workers_at"])
        self.assertEqual(out["tasks"][0]["hint"], "관제의 워커 목록 사본이 없다(관제가 재확인마다 쓴다)")


if __name__ == "__main__":
    unittest.main()
