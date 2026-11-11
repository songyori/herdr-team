"""관제 뼈대(설계 8.1–8.3, 8.5 의 루프·격리·시간 상수, 8.10 decide 쓰기, 8.11 drive.log): 시작 순서, 단일 인스턴스, Run 연결,
heartbeat, 생존 판정, 관제 판별, status 의 drive."""
import json
import os
import re
import signal
import subprocess
import sys
import time
import unittest
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

from tests.helpers import BIN, DRIVE, DRIVE_ARGV, HORCH_BIN, MAIN, NONCE, TeamCase, _parse
from hteam import drive, state, util
from hteam.errors import HteamError
from hteam.paths import Project

LOCAL_ISO = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d"
DRIVE_ONLY = ("이 명령은 관제(hteam drive)가 스스로 한다. 메인이 관제 큐로 넣는 명령은 start, start-ready, fix, accept, drop, "
              "review --retry, design-decide, scope, agent reset, test-confirm 이다")

# run-use·run-create 를 처음 FLAKY_FAILS 번 일시 실패로 돌려주고 나머지는 진짜 horch 로 넘기는 감싸개(Run 연결 재시도, 설계 8.2 의 4)
FLAKY_HORCH = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
count = Path(os.environ["FLAKY_COUNT"])
args = sys.argv[1:]
if any(a in ("run-use", "run-create") for a in args):
    n = int(count.read_text()) if count.exists() else 0
    count.write_text(str(n + 1))
    if n < int(os.environ["FLAKY_FAILS"]):
        print(json.dumps({"ok": False, "error": {"code": "db_busy", "message": "잠시 바쁘다", "hint": ""}}))
        sys.exit(1)
os.execv(sys.executable, [sys.executable, os.environ["FLAKY_REAL"], *args])
"""


class DriveCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.run_id = self.setup_run()
        self.p = Project(self.proj)

    def run_json(self) -> dict:
        return json.loads((self.state_dir / "run.json").read_text())

    def set_run(self, **changes) -> None:
        run = self.run_json()
        for key, value in changes.items():
            if value is None:
                run.pop(key, None)
            else:
                run[key] = value
        (self.state_dir / "run.json").write_text(json.dumps(run))

    def log_lines(self) -> list[str]:
        path = self.drive_dir / "drive.log"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []

    def decides(self) -> list[dict]:
        return [e for e in self.outbox_items() if e["type"] == "decide"]

    def dead_pid(self) -> int:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        return proc.pid


class ConstantsTest(unittest.TestCase):
    def test_time_constants_and_kinds(self):
        # 설계 8.5 의 시간 상수 표(orca-team 코드 값)와 8.10 의 decide 종류
        self.assertEqual((drive.WAIT_MS, drive.IDLE_S, drive.IDLE_FAIL_S, drive.RECONCILE_S, drive.DRIVE_STALE_S,
                          drive.LAUNCH_GRACE_S, drive.QUEUE_WAIT_S, drive.QUEUE_POLL_S, drive.NOT_STARTED_S,
                          drive.LIVENESS_UNKNOWN_S, drive.RESET_STUCK_S, drive.RESET_BUSY_S, drive.RESET_UNKNOWN_S,
                          drive.RESET_FAIL_LIMIT, drive.RESET_CLEAR_TIMEOUT_MS, drive.UNKNOWN_START_LIMIT,
                          drive.NO_STATUS_GRACE_S, drive.BIND_TRIES, drive.BIND_RETRY_S),
                         (10000, 1.0, 5.0, 60, 120, 180, 90, 0.2, 60, 1800, 1800, 1800, 1800, 3, 10000, 3, 60, 3, 5.0))
        self.assertEqual(drive.DECIDE_KINDS, ("worker_failed", "worker_question", "escalation", "max_rounds",
                                              "repeat_test_failure", "test_config", "planning_gaps",
                                              "unknown_regression", "token_update", "workspace_failed"))


class LivenessTest(DriveCase):
    """drive_alive(설계 8.2): pid 파일의 {pid, started} 가 살아 있는 같은 프로세스이고 heartbeat 가 0 이상 120초 미만 전."""

    def view(self) -> dict:
        return drive.liveness(self.p)

    def test_alive_and_hung(self):
        v = self.view()
        self.assertEqual(set(v), {"alive", "hung", "pid", "started", "heartbeat_age"})
        self.assertEqual((v["alive"], v["hung"], v["pid"]), (True, False, os.getpid()))
        self.assertLess(v["heartbeat_age"], 60)
        self.write_heartbeat(age_s=130)
        v = self.view()
        self.assertEqual((v["alive"], v["hung"]), (False, True))
        self.assertGreaterEqual(v["heartbeat_age"], 129)
        hb = self.drive_dir / "heartbeat"
        future = (datetime.now().astimezone() + timedelta(seconds=300)).isoformat(timespec="seconds")
        no_offset = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        for text in ("", "nonsense", no_offset, future):  # 해석 실패·오프셋 없는 시각·미래 시각은 살아 있지 않다
            with self.subTest(text=text):
                hb.write_text(text)
                v = self.view()
                self.assertEqual((v["alive"], v["hung"]), (False, True))
        hb.unlink()  # pid 만 살아 있으면 멈춤이다
        v = self.view()
        self.assertEqual((v["alive"], v["hung"], v["heartbeat_age"]), (False, True, None))

    def test_dead_or_unknown_pid(self):
        self.write_drive_pid(self.dead_pid(), "Thu Jan  1 00:00:00 2026")
        v = self.view()
        self.assertEqual((v["alive"], v["hung"]), (False, False))
        self.write_drive_pid(os.getpid(), "Thu Jan  1 00:00:00 2026")  # 같은 pid, 다른 시작 시각: pid 가 다시 쓰였다
        self.assertEqual((self.view()["alive"], self.view()["hung"]), (False, False))
        (self.drive_dir / "drive.pid").write_text("[")
        v = self.view()
        self.assertEqual((v["alive"], v["hung"], v["pid"]), (False, False, None))
        (self.drive_dir / "drive.pid").unlink()
        v = self.view()
        self.assertEqual((v["alive"], v["hung"], v["pid"]), (False, False, None))

    def test_liveness_calls_no_hc(self):
        before = len(self.hc_calls())
        self.view()
        self.assertEqual(len(self.hc_calls()), before)


class DriveStartTest(DriveCase):
    """hteam drive 의 시작 순서(설계 8.2 의 1–7). HTEAM_DRIVE_TICKS 로 몇 틱 뒤 끝낸다."""

    def setUp(self):
        super().setUp()
        (self.drive_dir / "drive.pid").unlink()  # setup_run 이 쓴 생존 파일(이 시험 프로세스)을 치운다
        self.env.update({"HTEAM_DRIVE_TICKS": "1", "HTEAM_DRIVE_WAIT_MS": "50", "HTEAM_DRIVE_IDLE_S": "0.01"})

    def drive(self, *, as_="drive", env=None, terminal=None) -> tuple[int, dict, str]:
        proc = subprocess.run([sys.executable, str(BIN), "drive"], capture_output=True, text=True,
                              env=self._env(as_, terminal, env), cwd=str(self.proj), timeout=120)
        return proc.returncode, _parse(proc.stdout, proc.stderr), proc.stdout

    def flaky(self, fails: int) -> dict:
        wrap = self.tmp / "flaky-horch"
        wrap.write_text(FLAKY_HORCH)
        wrap.chmod(0o755)
        return {"HERDR_ORCH_BIN": str(wrap), "FLAKY_REAL": str(HORCH_BIN), "FLAKY_FAILS": str(fails),
                "FLAKY_COUNT": str(self.tmp / "flaky-count"), "HTEAM_BIND_RETRY_S": "0.05"}

    def test_refusals_before_start(self):
        code, out, _ = self.drive(env={"CLAUDECODE": "1"})
        self.assertEqual((code, out["error"]["code"]), (2, "drive_in_claude"), out)
        self.assertEqual(out["error"]["message"],
                         "hteam drive 는 관제 탭에서만 돈다. Claude 세션 안에서는 띄우지 않는다(메인은 /herdr-team:up)")
        code, out, _ = self.drive(as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "no_terminal"), out)
        self.assertEqual(out["error"]["message"], "HC_TERMINAL_ID 가 없다. hteam drive 는 Herdr 터미널(관제 탭)에서 돈다")
        for env in ({"HTEAM_LAUNCH": "other-nonce"}, {"HTEAM_ROLE": "coordinator"}):
            with self.subTest(env=env):
                code, out, _ = self.drive(env=env)
                self.assertEqual((code, out["error"]["code"]), (5, "not_drive"), out)
        (self.team / "config.toml").write_text("max_parallel = 0\n")
        code, out, _ = self.drive()
        self.assertEqual((code, out["error"]["code"]), (2, "bad_config"), out)
        self.assertFalse((self.drive_dir / "drive.pid").exists())
        self.assertEqual(self.log_lines(), [])  # pid 파일을 잡기 전의 거부는 기록하지 않는다

    def test_single_instance(self):
        self.write_drive_pid()  # 살아 있는 같은 프로세스(이 시험 프로세스)의 파일
        code, out, _ = self.drive()
        self.assertEqual((code, out["error"]["code"]), (3, "drive_running"), out)
        self.assertEqual(out["error"]["message"], f"hteam drive 가 이미 실행 중이다(pid {os.getpid()})")
        self.assertEqual(json.loads((self.drive_dir / "drive.pid").read_text())["pid"], os.getpid())  # 남의 파일은 그대로
        self.write_drive_pid(self.dead_pid(), "Thu Jan  1 00:00:00 2026")  # 죽은 프로세스의 파일은 지우고 다시 만든다
        code, out, _ = self.drive()
        self.assertEqual(code, 0, out)
        self.assertFalse((self.drive_dir / "drive.pid").exists())  # 끝날 때 자기 pid 일 때만 지운다

    def test_rebinds_existing_run_and_records(self):
        self.set_run(launched_at="2026-11-10T00:00:00Z")
        code, out, stdout = self.drive()
        self.assertEqual((code, out["mode"], out["run_id"], out["ticks"]), (0, "rebound", self.run_id, 1), out)
        run = self.run_json()
        self.assertEqual((run["run_id"], run["drive_terminal"], run["drive_argv"], run["bound_nonce"]),
                         (self.run_id, DRIVE, DRIVE_ARGV, NONCE))
        self.assertNotIn("launched_at", run)
        self.assertRegex(run["bound_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn(["do", "tab.rename", "--id", "tbTeam", "--name", "herdr-team 관제"], self.herdr_calls())
        self.assertIn("\x1b]2;herdr-team 관제\x07", stdout)  # 관제 pane 제목(OSC 2)
        lines = self.log_lines()
        self.assertRegex(lines[0], rf"^{LOCAL_ISO} 관제 시작\(t100\): rebound$")
        self.assertRegex(lines[-1], rf"^{LOCAL_ISO} 관제 종료: ")
        self.assertIn("관제 시작(t100): rebound", stdout)  # 관제 탭 화면에도 같은 줄
        self.assertRegex((self.drive_dir / "heartbeat").read_text().strip(), rf"^{LOCAL_ISO}$")

    def test_creates_run_when_none(self):
        self.set_run(run_id=None, bound_nonce=None, bound_at=None)
        code, out, _ = self.drive()
        self.assertEqual((code, out["mode"]), (0, "created"), out)
        self.assertNotEqual(out["run_id"], self.run_id)
        self.assertEqual(self.run_json()["run_id"], out["run_id"])
        code, st = self.horch("status", terminal=DRIVE)
        self.assertEqual((code, st["run"]["id"], st["run"]["objective"]), (0, out["run_id"], "테스트 프로젝트"), st)
        self.assertRegex(self.log_lines()[0], rf"^{LOCAL_ISO} 관제 시작\(t100\): created$")

    def test_takes_over_unverifiable_owner_with_force(self):
        # 사용자 결정(2026-11-10): 이전 소유자가 owner_unverifiable 이면 pid 잠금을 믿고 --force 로 넘겨받는다
        self.add_terminal("t300", argv=["hteam-drive"], labels={"herdr.space": "spA", "herdr.tab": "tbTeam"})
        code, made = self.horch("run-create", "--objective", "old", terminal="t300")
        self.assertEqual(code, 0, made)
        with self._hc_locked() as hc:
            del hc["terminals"]["t300"]  # hc rm 된 이전 관제 터미널: 생존을 확인할 수 없다
        self.set_run(run_id=made["run"]["id"])
        code, out, _ = self.drive()
        self.assertEqual((code, out["mode"], out["run_id"]), (0, "rebound", made["run"]["id"]), out)
        code, st = self.horch("status", terminal=DRIVE)
        self.assertEqual(st["run"]["id"], made["run"]["id"])

    def test_live_other_owner_is_refused(self):
        self.add_terminal("t300", argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbTeam"}, status="idle")
        code, made = self.horch("run-create", "--objective", "old", terminal="t300")
        self.set_run(run_id=made["run"]["id"])
        code, out, _ = self.drive()
        self.assertEqual((code, out["error"]["code"]), (3, "horch_owner_alive"), out)
        self.assertFalse((self.drive_dir / "drive.pid").exists())
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: HteamError: ")

    def test_run_connect_retries_then_succeeds(self):
        code, out, _ = self.drive(env=self.flaky(2))
        self.assertEqual((code, out["mode"]), (0, "rebound"), out)
        lines = self.log_lines()
        for n in (1, 2):
            self.assertTrue(any(re.search(rf"^{LOCAL_ISO} Run 연결 실패\({n}/3\): .*db_busy.*\. .*초 뒤 다시 한다$", line)
                                for line in lines), lines)
        self.assertEqual((self.tmp / "flaky-count").read_text(), "3")

    def test_run_connect_gives_up_after_three_tries(self):
        code, out, _ = self.drive(env=self.flaky(9))
        self.assertEqual((code, out["error"]["code"]), (1, "horch_db_busy"), out)
        self.assertEqual((self.tmp / "flaky-count").read_text(), "3")
        lines = self.log_lines()
        self.assertEqual(len([line for line in lines if "Run 연결 실패" in line]), 2)
        self.assertRegex(lines[-1], rf"^{LOCAL_ISO} 관제 종료: HteamError: ")
        self.assertFalse((self.drive_dir / "drive.pid").exists())

    def test_missing_horch_ends_drive_with_12(self):
        code, out, _ = self.drive(env={"HERDR_ORCH_BIN": str(self.tmp / "no-horch")})
        self.assertEqual((code, out["error"]["code"]), (12, "horch_missing"), out)
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: HteamError: ")
        self.assertFalse((self.drive_dir / "drive.pid").exists())

    def test_signals_end_drive_with_143_and_129(self):
        for sig, code in ((signal.SIGTERM, 143), (signal.SIGHUP, 129)):
            with self.subTest(sig=sig):
                started = len([line for line in self.log_lines() if "관제 시작" in line])
                proc = self.hteam_bg("drive", env={"HTEAM_DRIVE_TICKS": "0"})
                deadline = time.monotonic() + 30
                while len([line for line in self.log_lines() if "관제 시작" in line]) == started:
                    self.assertIsNone(proc.poll(), "관제가 일찍 끝났다")
                    self.assertLess(time.monotonic(), deadline, "관제가 시작하지 않았다")
                    time.sleep(0.05)
                rec = json.loads((self.drive_dir / "drive.pid").read_text())
                self.assertEqual((rec["pid"], set(rec)), (proc.pid, {"pid", "started"}))
                proc.send_signal(sig)
                proc.communicate(timeout=30)
                self.assertEqual(proc.returncode, code)
                self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 관제 종료: SystemExit: {code}$")
                self.assertFalse((self.drive_dir / "drive.pid").exists())


class TickTest(DriveCase):
    """틱 순서와 격리(설계 8.5). 단계 몸통은 뒤 태스크가 채운다. 여기서는 순서·heartbeat·격리·check 를 본다."""

    STEPS = ("heartbeat", "check_mail", "run_queue", "start_ready", "reap_jobs", "reset_step", "view_step", "reconcile")

    def setUp(self):
        super().setUp()
        self.env.update({"HTEAM_DRIVE_WAIT_MS": "50"})
        patcher = self.in_drive()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.d = self.make_drive()

    def stub(self, *names, queue=()) -> list[str]:
        """names 단계를 이름만 남기는 가짜로 바꾼다(run_queue 는 queue 를 돌려준다)."""
        calls: list[str] = []
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name in names:
            result = list(queue) if name == "run_queue" else None
            stack.enter_context(mock.patch.object(self.d, name, side_effect=lambda n=name, r=result: calls.append(n) or r))
        return calls

    def test_tick_order_and_reconcile_interval(self):
        calls = self.stub(*self.STEPS)
        self.d.tick()
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "heartbeat", "reset_step",
                                 "view_step", "reconcile"])
        calls.clear()
        self.d.tick()  # 마지막 재확인 뒤 60초 안: 재확인하지 않는다
        self.assertEqual(calls, ["heartbeat", "check_mail", "run_queue", "reap_jobs", "heartbeat", "reset_step",
                                 "view_step"])
        calls.clear()
        self.d.last_reconcile -= 61
        self.d.tick()
        self.assertEqual(calls[-1], "reconcile")

    def test_start_ready_only_after_executed_requests(self):
        calls = self.stub(*self.STEPS, queue=[{"id": "q-000001"}])
        self.d.tick()
        self.assertEqual(calls[:5], ["heartbeat", "check_mail", "run_queue", "start_ready", "reap_jobs"])

    def test_step_failure_is_logged_and_raised_once(self):
        self.stub("check_mail", "reap_jobs", "reset_step", "view_step", "reconcile", "start_ready")
        with mock.patch.object(self.d, "run_queue", side_effect=RuntimeError("터졌다")):
            self.d.tick()
            self.d.tick()
        lines = [line for line in self.log_lines() if re.search(rf"^{LOCAL_ISO} queue 실패: ", line)]
        self.assertEqual(len(lines), 2, self.log_lines())  # 실패마다 로그, decide 는 한 번
        self.assertRegex(lines[0], rf"^{LOCAL_ISO} queue 실패: RuntimeError: 터졌다$")
        decides = self.decides()
        self.assertEqual(len(decides), 1)
        self.assertEqual((decides[0]["kind"], decides[0]["task"], decides[0]["summary"], decides[0]["from"]),
                         ("escalation", None, "queue 실패: RuntimeError: 터졌다", "drive"))
        with mock.patch.object(self.d, "run_queue", side_effect=RuntimeError("다른 문구")):
            self.d.tick()
        self.assertEqual(len(self.decides()), 2)

    def test_failed_raise_is_only_logged_and_retried(self):
        self.stub("check_mail", "reap_jobs", "reset_step", "view_step", "reconcile", "start_ready")
        with mock.patch.object(self.d, "run_queue", side_effect=RuntimeError("x")), \
                mock.patch.object(self.d, "decide", side_effect=OSError("디스크가 찼다")):
            self.d.tick()
        self.assertTrue(any(re.search(rf"^{LOCAL_ISO} queue 실패를 올리지 못했다: OSError: 디스크가 찼다$", line)
                            for line in self.log_lines()), self.log_lines())
        self.assertEqual(self.decides(), [])
        with mock.patch.object(self.d, "run_queue", side_effect=RuntimeError("x")):
            self.d.tick()  # 다음 실패가 다시 올린다
        self.assertEqual(len(self.decides()), 1)

    def test_missing_dependency_is_not_isolated(self):
        self.stub("check_mail", "reap_jobs", "reset_step", "view_step", "reconcile", "start_ready")
        with mock.patch.object(self.d, "run_queue", side_effect=HteamError("horch_missing", "horch 가 없다", 12)):
            with self.assertRaises(HteamError) as ctx:
                self.d.tick()
        self.assertEqual(ctx.exception.exit_code, 12)

    def test_message_failure_raises_original_and_is_acked(self):
        self.stub("run_queue", "reap_jobs", "reset_step", "view_step", "reconcile", "start_ready")
        body = "가" * 250
        code, sent = self.horch("send", "--to", f"run:{self.run_id}", "--subject", "s", f"--body={body}", terminal=MAIN)
        self.assertEqual(code, 0, sent)
        mid = sent["message"]
        with mock.patch.object(self.d, "handle", side_effect=RuntimeError("처리 오류")) as handle:
            self.d.tick()
            self.d.tick()  # 처리한 묶음은 다음 check --ack 로 확인돼 다시 오지 않는다
        self.assertEqual(handle.call_count, 1)
        self.assertEqual(handle.call_args[0][0]["id"], mid)
        decides = self.decides()
        self.assertEqual(len(decides), 1)
        self.assertEqual(decides[0]["summary"],
                         f"메시지 {mid} 처리 실패: RuntimeError: 처리 오류 [type=status dispatch=-] " + "가" * 200)
        self.assertTrue(any(re.search(rf"^{LOCAL_ISO} msg:{mid} 실패: RuntimeError: 처리 오류$", line)
                            for line in self.log_lines()))

    def test_question_failure_keeps_message_id(self):
        self.stub("run_queue", "reap_jobs", "reset_step", "view_step", "reconcile", "start_ready")
        code, w = self.horch("worker-start", "--agent", "claude", "--title", "x", "--spec", "s", "--cwd", str(self.proj),
                             terminal=DRIVE)
        self.assertEqual(code, 0, w)
        code, asked = self.horch("ask", "--dispatch", w["dispatch"], "--question", "어느 쪽인가", "--timeout-ms", "100",
                                 terminal=w["terminal"])
        self.assertEqual(code, 4, asked)
        with mock.patch.object(self.d, "handle", side_effect=RuntimeError("처리 오류")):
            self.d.tick()
        entry = self.decides()[-1]
        self.assertEqual((entry["question"], entry["message_id"]), ("어느 쪽인가", asked["question"]))
        self.assertTrue(entry["summary"].startswith(f"메시지 {asked['question']} 처리 실패: RuntimeError: 처리 오류 "
                                                    f"[type=question dispatch={w['dispatch']}] "))

    def test_check_failure_is_raised_once_and_slows_the_loop(self):
        self.stub("run_queue", "reap_jobs", "reset_step", "view_step", "reconcile", "start_ready")
        self.assertEqual(self.d.idle_seconds(), 1.0)
        with mock.patch.dict(os.environ, {"HC_TERMINAL_ID": "t999"}):  # Run 소유자가 아니다: horch check 가 거부한다
            self.d.tick()
            self.d.tick()
        self.assertEqual(self.d.idle_seconds(), 5.0)
        lines = [line for line in self.log_lines() if re.search(rf"^{LOCAL_ISO} check 실패: ", line)]
        self.assertEqual(len(lines), 2, self.log_lines())
        decides = self.decides()
        self.assertEqual(len(decides), 1)
        self.assertTrue(decides[0]["summary"].startswith("check 실패: "), decides[0])
        self.d.tick()  # 다시 된다
        self.assertEqual(self.d.idle_seconds(), 1.0)

    def test_heartbeat_and_log(self):
        self.d.heartbeat()
        self.assertRegex((self.drive_dir / "heartbeat").read_text().strip(), rf"^{LOCAL_ISO}$")
        self.assertTrue(drive.liveness(self.p)["alive"])
        buf = StringIO()
        with redirect_stdout(buf):
            self.d.log("한 줄")
        self.assertRegex(buf.getvalue(), rf"^{LOCAL_ISO} 한 줄\n$")
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} 한 줄$")
        (self.drive_dir / "drive.log").unlink()
        (self.drive_dir / "drive.log").mkdir()
        with redirect_stdout(StringIO()):
            self.d.log("또 한 줄")  # 쓰기 실패는 무시한다


class DecideTest(DriveCase):
    """decide 쓰기(설계 8.10): outbox decide 줄, 태스크의 decide·decide_round, drive.log."""

    def setUp(self):
        super().setUp()
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        patcher = self.in_drive()
        patcher.start()
        self.addCleanup(patcher.stop)
        self.d = self.make_drive()

    def test_decide_line_and_task_marks(self):
        oid = self.d.decide("escalation", "T-001", "요약 글", files=["docs/tasks/T-001/report.md"],
                            commands=["hteam drop T-001"], detail="원문", message_id=7)
        entry = self.outbox_items()[-1]
        self.assertEqual(entry["id"], oid)
        self.assertRegex(oid, r"^out-\d{4}$")
        self.assertEqual({k: entry[k] for k in ("type", "from", "kind", "task", "summary", "files", "commands", "body",
                                                 "answered", "detail", "message_id")},
                         {"type": "decide", "from": "drive", "kind": "escalation", "task": "T-001", "summary": "요약 글",
                          "files": ["docs/tasks/T-001/report.md"], "commands": ["hteam drop T-001"],
                          "body": "[escalation] T-001: 요약 글", "answered": False, "detail": "원문", "message_id": 7})
        st = self.task_state("T-001")
        self.assertEqual((st["decide"], st["decide_round"]), (oid, 0))
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} decide {oid} escalation T-001: 요약 글$")

    def test_empty_summary_no_task_and_long_log(self):
        oid = self.d.decide("worker_failed", None, "")
        entry = self.outbox_items()[-1]
        self.assertEqual((entry["summary"], entry["body"], entry["files"], entry["commands"]),
                         ("(요약 없음)", "[worker_failed] -: (요약 없음)", [], []))
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} decide {oid} worker_failed -: \(요약 없음\)$")
        oid = self.d.decide("max_rounds", "T-001", "가" * 100)
        self.assertRegex(self.log_lines()[-1], rf"^{LOCAL_ISO} decide {oid} max_rounds T-001: {'가' * 80}$")
        self.assertEqual(self.outbox_items()[-1]["summary"], "가" * 100)

    def test_unknown_kind_is_internal_error(self):
        with self.assertRaises(HteamError) as ctx:
            self.d.decide("nope", "T-001", "x")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(self.outbox_items(), [])
        self.assertNotIn("decide", self.task_state("T-001"))


class StatusDriveTest(DriveCase):
    """status 의 drive(설계 8.3 6단계): coordinator 칸을 지우고 관제 생존을 pid·heartbeat 로 보인다."""

    def drive_view(self) -> dict:
        code, out = self.hteam("status", as_="main")
        self.assertEqual(code, 0, out)
        self.assertNotIn("coordinator", out)
        return out["drive"]

    def test_drive_view(self):
        view = self.drive_view()
        self.assertEqual(set(view), {"terminal", "alive", "hung", "starting", "pid", "heartbeat_age"})
        self.assertEqual((view["terminal"], view["alive"], view["hung"], view["starting"], view["pid"]),
                         (DRIVE, True, False, False, os.getpid()))
        self.write_heartbeat(age_s=200)
        view = self.drive_view()
        self.assertEqual((view["alive"], view["hung"]), (False, True))
        (self.drive_dir / "drive.pid").unlink()
        view = self.drive_view()
        self.assertEqual((view["alive"], view["hung"], view["pid"]), (False, False, None))
        # 띄운 지 180초 안이고 아직 Run 에 묶이지 않았다(bound_nonce 가 새 nonce 가 아니다)
        self.set_run(launched_at=util.now(), pending_launch={"nonce": "n2", "at": util.now()})
        self.assertTrue(self.drive_view()["starting"])


class DriveRoleTest(DriveCase):
    """관제 판별(설계 8.2): HTEAM_ROLE=drive 이고 $HC_TERMINAL_ID 가 run.json 의 drive_terminal. 아니면 exit 5 drive_only."""

    def test_drive_only_commands(self):
        self.write_spec("T-001")
        state.create(self.p, "T-001", "developer")
        for kwargs in ({"as_": "main"}, {"terminal": "t999"}, {"env": {"HTEAM_ROLE": "coordinator"}}):
            with self.subTest(kwargs=kwargs):
                code, out = self.hteam("review-finish", "T-001", **kwargs)
                self.assertEqual((code, out["error"]["code"], out["error"]["message"]), (5, "drive_only", DRIVE_ONLY), out)

    def test_removed_commands(self):
        code, out = self.hteam("bind")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)
        code, out = self.hteam("up", "--force", as_="main")
        self.assertEqual((code, out["error"]["code"]), (2, "usage"), out)


if __name__ == "__main__":
    unittest.main()
