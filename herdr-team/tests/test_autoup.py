"""관제 자동 부활(설계 9.5, 6단계에 대상을 관제로): pid·heartbeat 판정, 안내 문구, 간격·반복 줄이기, 분리 실행, 시간 예산과
마감, 상태 파일. hc 를 부르지 않는다."""
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests.helpers import BASE_CONFIG, DRIVE, MAIN, TeamCase
from hteam import autoup, drive, procs
from hteam.autoup import DISABLED, FAILED, FAILED_SPAWN, HUNG, OLD_CONFIG, REVIVED, check, decide
from hteam.paths import Project
from hteam.util import now

DEAD = {"alive": False, "hung": False, "pid": None, "started": None, "heartbeat_age": None}


def ago(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds))


class AutoUpCase(TeamCase):
    """메인 터미널(MAIN)의 훅처럼 이 프로세스에서 부른다. setup_run 이 관제 생존 파일(이 시험 프로세스)을 쓴다."""

    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()
        self.p = Project(self.proj)
        patcher = mock.patch.dict(os.environ, {**self.env, "HC_TERMINAL_ID": MAIN}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

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

    def record(self) -> dict:
        path = self.state_dir / "auto-up.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def set_record(self, **rec) -> None:
        (self.state_dir / "auto-up.json").write_text(json.dumps(rec))

    def dead(self) -> None:
        (self.drive_dir / "drive.pid").unlink(missing_ok=True)

    def hung(self) -> None:
        self.write_heartbeat(age_s=200)

    def check(self, force=False, started=None):
        return check(self.p, force=force, started=time.monotonic() if started is None else started)

    def wait_spawned(self) -> None:
        """분리 실행한 hteam up 이 끝날 때까지 기다린다(임시 폴더를 지우기 전에)."""
        rec = json.loads((self.state_dir / "auto-up.pid").read_text())
        deadline = time.monotonic() + 30
        while procs.record_alive(rec) and rec.get("started"):
            self.assertLess(time.monotonic(), deadline, "자동 실행한 hteam up 이 끝나지 않았다")
            time.sleep(0.05)
        while '"ok"' not in (self.state_dir / "auto-up.log").read_text() and time.monotonic() < deadline:
            time.sleep(0.05)


class DecideTest(AutoUpCase):
    def test_constants_and_texts(self):
        self.assertEqual((autoup.CHECK_INTERVAL_S, autoup.RETRY_WINDOW_S, autoup.PID_STALE_S, autoup.SPAWN_WAIT_S,
                          autoup.PS_TIMEOUT_S, autoup.HOOK_START_BUDGET_S, autoup.HOOK_DEADLINE_S, autoup.STARTING_S,
                          autoup.DRIVE_STALE_S), (60, 600, 60, 5, 5, 4, 12, 180, 120))
        self.assertEqual((autoup.STARTING_S, autoup.DRIVE_STALE_S), (drive.LAUNCH_GRACE_S, drive.DRIVE_STALE_S))
        for gone in ("PROBE_TIMEOUT_S", "UNKNOWN", "NO_HANDLE"):
            self.assertFalse(hasattr(autoup, gone), gone)
        self.assertEqual(REVIVED, "herdr-team: 관제(hteam drive)가 꺼져 있어 자동으로 다시 띄우는 중이다. 답변 첫 줄에 사용자에게 "
                                  "이 사실을 한 줄로 알린다. 관제가 뜨기 전에 낸 큐 명령은 '관제가 꺼져 있다' 로 거부되므로 잠시 "
                                  "뒤 다시 한다. watch 가 꺼져 있으면 띄우고, 답하지 않은 질문이 있으면 hteam reask 로 다시 보여 "
                                  "준다.")
        self.assertEqual(HUNG, "herdr-team: 관제 프로세스는 살아 있지만 2분 넘게 응답이 없다. 답변 첫 줄에 사용자에게 한 줄로 "
                               "알리고 관제 탭(herdr-team 관제)의 출력을 확인하게 한다.")
        self.assertEqual(DISABLED, "herdr-team: 관제가 꺼져 있다(config.toml 의 [drive] auto_up = false). 답변 첫 줄에 "
                                   "사용자에게 한 줄로 알리고 /herdr-team:up 을 안내한다.")
        self.assertEqual(FAILED, "herdr-team: 자동으로 다시 띄운 관제가 10분 안에 다시 꺼졌거나 뜨지 못했다(기록: "
                                 ".herdr-team/state/auto-up.log, .herdr-team/state/drive/drive.log). 답변 첫 줄에 사용자에게 "
                                 "한 줄로 알리고, 그 기록으로 원인을 확인한 뒤 /herdr-team:up 을 실행하도록 안내한다. 10분 "
                                 "동안은 자동으로 다시 띄우지 않는다.")
        self.assertEqual(FAILED_SPAWN, "herdr-team: 관제를 자동으로 다시 띄우지 못했다(hteam up 실행 실패, 기록: "
                                       ".herdr-team/state/auto-up.log). 답변 첫 줄에 사용자에게 한 줄로 알리고 "
                                       "/herdr-team:up 을 안내한다.")
        self.assertEqual(OLD_CONFIG, "herdr-team: config.toml 에 0.3.0 의 [coordinator] 가 남아 있다. 0.4.0 은 "
                                     "관제(hteam drive)를 쓴다. 답변 첫 줄에 사용자에게 한 줄로 알리고, [coordinator] 를 지우고 "
                                     "템플릿의 [drive]·[overflow]·[crew.*] 를 옮기거나, config.toml 을 지운 뒤 "
                                     "/herdr-team:init 으로 다시 세팅하도록 안내한다(있는 파일은 덮어쓰지 않는다).")

    def test_verdicts_by_pid_and_heartbeat_without_hc(self):
        far = time.monotonic() + 12
        before = len(self.hc_calls())
        self.assertEqual(decide(self.p, far), (None, None))  # 살아 있다
        self.hung()
        self.assertEqual(decide(self.p, far), (None, HUNG))  # pid 는 살고 heartbeat 가 멈췄다: 띄우지 않는다
        (self.drive_dir / "heartbeat").unlink()
        self.assertEqual(decide(self.p, far), (None, HUNG))
        self.write_heartbeat()
        self.write_drive_pid(os.getpid(), "Thu Jan  1 00:00:00 2026")  # pid 가 다른 프로세스에 다시 쓰였다
        self.assertEqual(decide(self.p, far), ("spawn", REVIVED))
        self.dead()
        self.assertEqual(decide(self.p, far), ("spawn", REVIVED))
        self.set_run(drive_terminal=None, drive_argv=None)  # 터미널 기록이 없어도 pid 로 판정한다(NO_HANDLE 없음)
        self.assertEqual(decide(self.p, far), ("spawn", REVIVED))
        self.assertEqual(len(self.hc_calls()), before)  # hc 를 부르지 않는다

    def test_auto_up_false_only_informs(self):
        self.commit(".herdr-team/config.toml", BASE_CONFIG + "\n[drive]\nauto_up = false\n", "chore: 자동 부활 끔")
        self.dead()
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, DISABLED))

    def test_old_config_is_announced_other_config_errors_are_silent(self):
        self.dead()
        (self.team / "config.toml").write_text(BASE_CONFIG + '\n[coordinator]\nmodel = "opus"\n', encoding="utf-8")
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, OLD_CONFIG))
        (self.team / "config.toml").write_text("max_parallel = 0\n", encoding="utf-8")
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))

    def test_starting_and_running_auto_up_are_skipped(self):
        self.dead()
        self.set_run(launched_at=now())
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))
        self.set_run(launched_at=None, pending_launch={"nonce": "n", "at": ago(30)})
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))
        self.set_run(pending_launch={"nonce": "n", "at": ago(400)})
        (self.state_dir / "auto-up.pid").write_text(json.dumps(procs.me()))
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))  # 자동 실행이 진행 중이다

    def test_stale_or_reused_auto_up_pid_is_ignored(self):
        self.dead()
        pid = self.state_dir / "auto-up.pid"
        pid.write_text(json.dumps(procs.me()))
        os.utime(pid, (time.time() - 70, time.time() - 70))  # 60초 지난 기록은 ps 없이 진행 중이 아니다
        self.assertEqual(decide(self.p, time.monotonic() + 12), ("spawn", REVIVED))
        pid.write_text(json.dumps({"pid": os.getpid(), "started": "Thu Jan  1 00:00:00 2026"}))  # 다른 프로세스
        self.assertEqual(decide(self.p, time.monotonic() + 12), ("spawn", REVIVED))

    def test_redeath_within_ten_minutes_is_failed(self):
        self.dead()
        self.set_record(spawned_at=ago(100))
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, FAILED))
        self.set_record(spawned_at=ago(700))
        self.assertEqual(decide(self.p, time.monotonic() + 12), ("spawn", REVIVED))


class CheckTest(AutoUpCase):
    def liveness_calls(self):
        return mock.patch.object(autoup.drive, "liveness", wraps=drive.liveness)

    def test_not_eligible_writes_nothing(self):
        cases = (lambda: self.set_run(run_id=None), lambda: (self.state_dir / "setup-mode").write_text("x"),
                 lambda: (self.state_dir / "run.json").write_text("{"))
        for make in cases:
            self.setup_run()
            (self.state_dir / "setup-mode").unlink(missing_ok=True)
            self.dead()
            make()
            with self.liveness_calls() as live:
                self.assertIsNone(self.check(force=True))
            live.assert_not_called()
            self.assertFalse((self.state_dir / "auto-up.json").exists())

    def test_bad_config_is_skipped(self):
        (self.team / "config.toml").write_text("max_parallel = 0\n")
        self.dead()
        with self.liveness_calls() as live:
            self.assertIsNone(self.check(force=True))
        live.assert_not_called()

    def test_interval_and_force(self):
        with self.liveness_calls() as live:
            self.assertIsNone(self.check())
            self.assertEqual(live.call_count, 1)
            self.assertIn("checked_at", self.record())
            self.assertIsNone(self.check())  # 60초 안: 판정하지 않는다
            self.assertEqual(live.call_count, 1)
            self.assertIsNone(self.check(force=True))  # 세션 시작은 간격과 관계없다
            self.assertEqual(live.call_count, 2)

    def test_same_notice_is_repeated_only_when_changed_or_forced(self):
        self.hung()
        self.assertEqual(self.check(), HUNG)
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertIsNone(self.check())  # 같은 문구
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(force=True), HUNG)
        self.write_heartbeat()
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertIsNone(self.check())  # 살아 있다: notice 를 지운다
        self.assertNotIn("notice", self.record())
        self.hung()
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(), HUNG)  # 다음 문제는 다시 알린다

    def test_real_spawn_is_always_announced(self):
        self.dead()
        self.set_record(notice=REVIVED, spawned_at=ago(700), checked_at=ago(70))
        with mock.patch.object(autoup, "spawn_up", return_value=True):
            self.assertEqual(self.check(), REVIVED)
        rec = self.record()
        self.assertEqual((rec["notice"], rec["spawned_at"]), (REVIVED, rec["checked_at"]))

    def test_corrupt_record_is_due(self):
        (self.state_dir / "auto-up.json").write_text("[1]")
        with self.liveness_calls() as live:
            self.assertIsNone(self.check())
        self.assertEqual(live.call_count, 1)

    def test_spawn_failure_is_failed_spawn_without_spawned_at(self):
        self.dead()
        real = subprocess.run

        def run(argv, *args, **kw):
            if argv[0] == "/bin/sh":
                raise OSError("sh 없음")
            return real(argv, *args, **kw)
        with mock.patch.object(autoup.subprocess, "run", side_effect=run):
            self.assertEqual(self.check(), FAILED_SPAWN)
        self.assertNotIn("spawned_at", self.record())
        self.assertFalse((self.state_dir / "auto-up.pid").exists())

    def test_exception_leaves_only_checked_at(self):
        old = {"notice": HUNG, "spawned_at": ago(900), "checked_at": ago(70)}
        self.set_record(**old)
        with mock.patch.object(autoup.drive, "liveness", side_effect=RuntimeError("터졌다")):
            with self.assertRaises(RuntimeError):
                self.check()
        rec = self.record()
        self.assertEqual((rec["notice"], rec["spawned_at"]), (old["notice"], old["spawned_at"]))
        self.assertNotEqual(rec["checked_at"], old["checked_at"])


class SpawnTest(AutoUpCase):
    def test_spawn_runs_real_up_with_the_main_terminal(self):
        self.dead()
        self.assertEqual(self.check(), REVIVED)
        self.wait_spawned()
        run = self.run_json()
        self.assertNotEqual(run["drive_terminal"], DRIVE)  # 가짜 hc 가 새 관제 터미널을 만들었다
        term = self.hc_state()["terminals"][run["drive_terminal"]]
        self.assertEqual((term["labels"]["herdr.space"], term["labels"]["hteam.role"]), ("spA", "drive"))
        self.assertIn(["get", MAIN, "--json"], self.hc_calls())  # 메인 터미널($HC_TERMINAL_ID)을 물려받았다
        log = (self.state_dir / "auto-up.log").read_text()
        self.assertRegex(log, r"--- \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ hteam up \(자동\)\n")
        self.assertIn('"launched"', log)
        rec, pid = self.record(), json.loads((self.state_dir / "auto-up.pid").read_text())
        self.assertEqual(rec["spawned_at"], rec["checked_at"])
        self.assertEqual(set(pid), {"pid", "started"})
        # 다시 확인하면 새 관제는 시작 중이다(launched_at 뒤 180초)
        self.set_record(**{**rec, "checked_at": ago(70)})
        self.assertIsNone(self.check())

    def test_up_failing_before_launch_gives_failed_next(self):
        # hc run 이 거부해 up 이 바꾼 키를 되돌렸다: 관제 기록이 그대로 남고 다음 확인은 FAILED(10분 안 재사망)
        self.dead()
        self.fail_hc("run", "denied")
        self.assertEqual(self.check(), REVIVED)
        self.wait_spawned()
        self.assertIn('"ok": false', (self.state_dir / "auto-up.log").read_text())
        self.assertEqual(self.run_json()["drive_terminal"], DRIVE)
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(), FAILED)


class Clock:
    """가상 단조 시계(autoup._clock 자리). 패치한 단계가 부르면 그 단계가 걸린 만큼 앞으로 간다."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class BudgetTest(AutoUpCase):
    """훅 시작 4초 규칙과 마감(설계 9.5). 바깥 프로그램(ps, sh)은 마감까지 남은 시간을 시간 제한으로 받는다."""

    def setUp(self):
        super().setUp()
        self.clock = Clock()
        patcher = mock.patch.object(autoup, "_clock", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dead()
        self.seen = {}

    def step(self, name, seconds, value):
        """패치할 단계: 받은 시간 제한을 seen[name] 에 적고 시계를 seconds 만큼 옮긴 뒤 value 를 돌려준다."""
        def run(*args, timeout, **kw):
            self.seen[name] = timeout
            self.clock.now += seconds
            return value
        return run

    def sh(self, seconds):
        return self.step("sh", seconds, subprocess.CompletedProcess(["/bin/sh"], 0, "4242\n", ""))

    def fresh_pid(self):
        (self.state_dir / "auto-up.pid").write_text(json.dumps(procs.me()))

    def test_late_hook_start_skips_and_writes_nothing(self):
        with mock.patch.object(autoup.drive, "liveness") as live:
            self.assertIsNone(check(self.p, force=True, started=self.clock.now - 4.5))
        live.assert_not_called()
        self.assertEqual(self.record(), {})
        with mock.patch.object(autoup, "spawn_up", return_value=True):  # 다음 확인은 간격과 관계없이 바로 한다
            self.assertEqual(check(self.p, force=False, started=self.clock.now), REVIVED)

    def test_deadline_stops_before_ps_liveness_and_sh(self):
        self.fresh_pid()
        with mock.patch.object(autoup.procs, "record_alive") as alive:
            self.assertIsNone(decide(self.p, self.clock.now + 0.5))  # 진행 중 확인(ps) 앞에서 멈춘다
        alive.assert_not_called()
        (self.state_dir / "auto-up.pid").unlink()
        with mock.patch.object(autoup.drive, "liveness") as live:
            self.assertIsNone(decide(self.p, self.clock.now + 0.5))  # 관제 생존 확인(ps) 앞에서 멈춘다
        live.assert_not_called()
        self.fresh_pid()  # ps 가 11.2초 걸렸다: 생존 확인 앞에서 멈추고 아무것도 쓰지 않는다
        with mock.patch.object(autoup.procs, "record_alive", side_effect=self.step("ps", 11.2, False)), \
                mock.patch.object(autoup.drive, "liveness") as live:
            self.assertIsNone(check(self.p, force=True, started=self.clock.now))
        live.assert_not_called()
        self.assertEqual(self.record(), {})
        (self.state_dir / "auto-up.pid").unlink()  # 생존 확인이 11.5초 걸렸다: sh 앞에서 멈추고 아무것도 쓰지 않는다
        with mock.patch.object(autoup.drive, "liveness", side_effect=self.step("live", 11.5, DEAD)), \
                mock.patch.object(autoup.subprocess, "run") as run:
            self.assertIsNone(check(self.p, force=True, started=self.clock.now))
        run.assert_not_called()
        self.assertEqual(self.record(), {})
        self.assertFalse((self.state_dir / "auto-up.pid").exists())

    def test_each_step_gets_the_remaining_time(self):
        def run(ps, live, sh):
            self.fresh_pid()
            self.set_record()
            with mock.patch.object(autoup.procs, "record_alive", side_effect=self.step("ps", ps, False)), \
                    mock.patch.object(autoup.drive, "liveness", side_effect=self.step("live", live, DEAD)), \
                    mock.patch.object(autoup.subprocess, "run", side_effect=self.sh(sh)), \
                    mock.patch.object(autoup.procs, "start_time", side_effect=self.step("start", 0, "Sun Nov  8 00:00:00 2026")):
                self.assertEqual(check(self.p, force=True, started=self.clock.now), REVIVED)
            return tuple(self.seen[k] for k in ("ps", "live", "sh", "start"))
        self.assertEqual(run(0, 0, 0), (5, 5, 5, 5))  # 남은 시간이 넉넉하면 자기 제한
        self.assertEqual(run(9, 1, 0.5), (5, 3, 2, 1.5))  # ps 9초 뒤 남은 3초, 생존 확인 1초 뒤 2초, sh 0.5초 뒤 1.5초

    def test_started_is_null_when_time_is_short_after_spawn(self):
        with mock.patch.object(autoup.drive, "liveness", side_effect=self.step("live", 0, DEAD)), \
                mock.patch.object(autoup.subprocess, "run", side_effect=self.sh(11.5)), \
                mock.patch.object(autoup.procs, "start_time") as start_time:
            self.assertEqual(check(self.p, force=True, started=self.clock.now), REVIVED)
        start_time.assert_not_called()
        self.assertEqual(json.loads((self.state_dir / "auto-up.pid").read_text()), {"pid": 4242, "started": None})
        self.assertIn("spawned_at", self.record())


if __name__ == "__main__":
    unittest.main()
