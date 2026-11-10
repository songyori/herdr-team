"""코디네이터 자동 부활(설계 9.5): 판정, 안내 문구, 간격·반복 줄이기, 분리 실행, 시간 예산과 마감, 상태 파일."""
import json
import os
import subprocess
import time
import unittest
from unittest import mock

from tests.helpers import BASE_CONFIG, COORD, MAIN, TeamCase
from hteam import autoup, coord, procs
from hteam.autoup import DISABLED, FAILED, NO_HANDLE, REVIVED, UNKNOWN, check, decide
from hteam.paths import Project
from hteam.util import now


def ago(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - seconds))


class AutoUpCase(TeamCase):
    """메인 터미널(MAIN)의 훅처럼 이 프로세스에서 부른다. hc 는 가짜다(환경 변수를 이 프로세스에 옮긴다)."""

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

    def gets(self) -> int:
        return sum(1 for c in self.hc_calls() if c[:1] == ["get"])

    def dead(self) -> None:
        self.update_terminal(COORD, state="finished")

    def check(self, force=False, started=None):
        return check(self.p, force=force, started=time.monotonic() if started is None else started)

    def wait_spawned(self) -> None:
        """분리 실행한 hteam up 이 끝날 때까지 기다린다(임시 폴더를 지우기 전에)."""
        rec = json.loads((self.state_dir / "auto-up.pid").read_text())
        deadline = time.monotonic() + 30
        while procs.record_alive(rec) and rec.get("started"):
            self.assertLess(time.monotonic(), deadline, "자동 실행한 hteam up 이 끝나지 않았다")
            time.sleep(0.05)
        while "launched" not in (self.state_dir / "auto-up.log").read_text() and time.monotonic() < deadline:
            time.sleep(0.05)


class DecideTest(AutoUpCase):
    def test_constants_match(self):
        self.assertEqual(autoup.STARTING_S, coord.STARTING_S)
        self.assertEqual((autoup.CHECK_INTERVAL_S, autoup.RETRY_WINDOW_S, autoup.PID_STALE_S, autoup.PROBE_TIMEOUT_S,
                          autoup.SPAWN_WAIT_S, autoup.PS_TIMEOUT_S, autoup.HOOK_START_BUDGET_S, autoup.HOOK_DEADLINE_S),
                         (60, 600, 60, 3, 5, 5, 4, 12))
        for text in (REVIVED, UNKNOWN, NO_HANDLE, DISABLED, FAILED):
            self.assertTrue(text.startswith("herdr-team: "))
            self.assertIn("답변 첫 줄에 사용자에게", text)

    def test_verdicts(self):
        far = time.monotonic() + 12
        self.assertEqual(decide(self.p, far), (None, None))  # live
        self.update_terminal(COORD, argv=["zsh"])  # --keep 이 셸로 바꿨다: lost
        self.assertEqual(decide(self.p, far), ("spawn", REVIVED))
        self.dead()
        self.assertEqual(decide(self.p, far), ("spawn", REVIVED))
        with self._hc_locked() as st:  # hc rm 으로 지운 터미널(not_found)은 확인 불가다
            del st["terminals"][COORD]
        self.assertEqual(decide(self.p, far), (None, UNKNOWN))

    def test_auto_up_false_only_informs(self):
        self.commit(".herdr-team/config.toml", BASE_CONFIG + "\n[drive]\nauto_up = false\n", "chore: 자동 부활 끔")
        self.dead()
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, DISABLED))

    def test_no_terminal_is_no_handle_without_hc(self):
        self.set_run(coordinator_terminal=None)
        before = self.gets()
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, NO_HANDLE))
        self.assertEqual(self.gets(), before)

    def test_starting_and_running_auto_up_are_skipped(self):
        self.dead()
        self.set_run(launched_at=now())
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))
        self.set_run(launched_at=None, pending_launch={"nonce": "n", "at": ago(30)})
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))
        self.set_run(pending_launch={"nonce": "n", "at": ago(400)})
        me = procs.me()
        (self.state_dir / "auto-up.pid").write_text(json.dumps(me))
        self.assertEqual(decide(self.p, time.monotonic() + 12), (None, None))  # 자동 실행이 진행 중이다

    def test_stale_or_reused_pid_file_is_ignored(self):
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
    def test_not_eligible_calls_no_hc_and_writes_nothing(self):
        self.dead()
        cases = (lambda: self.set_run(run_id=None), lambda: (self.state_dir / "setup-mode").write_text("x"),
                 lambda: (self.state_dir / "run.json").write_text("{"))
        for make in cases:
            self.setup_run()
            (self.state_dir / "setup-mode").unlink(missing_ok=True)
            self.dead()
            make()
            before = self.gets()
            self.assertIsNone(self.check(force=True))
            self.assertEqual(self.gets(), before)
            self.assertFalse((self.state_dir / "auto-up.json").exists())

    def test_bad_config_is_skipped(self):
        (self.team / "config.toml").write_text("max_parallel = 0\n")
        self.dead()
        before = self.gets()
        self.assertIsNone(self.check(force=True))
        self.assertEqual(self.gets(), before)

    def test_interval_and_force(self):
        before = self.gets()
        self.assertIsNone(self.check())
        self.assertEqual(self.gets(), before + 1)
        self.assertIn("checked_at", self.record())
        self.assertIsNone(self.check())  # 60초 안: hc 를 부르지 않는다
        self.assertEqual(self.gets(), before + 1)
        self.assertIsNone(self.check(force=True))  # 세션 시작은 간격과 관계없다
        self.assertEqual(self.gets(), before + 2)

    def test_same_notice_is_repeated_only_when_changed_or_forced(self):
        self.fail_hc("get", "timeout")
        self.assertEqual(self.check(), UNKNOWN)
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertIsNone(self.check())  # 같은 문구
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(force=True), UNKNOWN)
        with self._hc_locked() as st:
            st["fail"] = {}
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertIsNone(self.check())  # live: notice 를 지운다
        self.assertNotIn("notice", self.record())
        self.fail_hc("get", "timeout")
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(), UNKNOWN)  # 다음 문제는 다시 알린다

    def test_real_spawn_is_always_announced(self):
        self.dead()
        self.set_record(notice=REVIVED, spawned_at=ago(700), checked_at=ago(70))
        with mock.patch.object(autoup, "spawn_up", return_value=True):
            self.assertEqual(self.check(), REVIVED)
        rec = self.record()
        self.assertEqual((rec["notice"], rec["spawned_at"]), (REVIVED, rec["checked_at"]))

    def test_corrupt_record_is_due(self):
        (self.state_dir / "auto-up.json").write_text("[1]")
        before = self.gets()
        self.assertIsNone(self.check())
        self.assertEqual(self.gets(), before + 1)

    def test_spawn_failure_is_unknown_without_spawned_at(self):
        self.dead()
        real = subprocess.run

        def run(argv, *args, **kw):
            if argv[0] == "/bin/sh":
                raise OSError("sh 없음")
            return real(argv, *args, **kw)
        with mock.patch.object(autoup.subprocess, "run", side_effect=run):
            self.assertEqual(self.check(), UNKNOWN)
        self.assertNotIn("spawned_at", self.record())
        self.assertFalse((self.state_dir / "auto-up.pid").exists())

    def test_exception_leaves_only_checked_at(self):
        self.dead()
        old = {"notice": UNKNOWN, "spawned_at": ago(900), "checked_at": ago(70)}
        self.set_record(**old)
        with mock.patch.object(autoup.herdr, "probe", side_effect=RuntimeError("터졌다")):
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
        self.assertNotEqual(run["coordinator_terminal"], COORD)  # 가짜 hc 가 새 코디네이터 터미널을 만들었다
        self.assertEqual(self.hc_state()["terminals"][run["coordinator_terminal"]]["labels"]["herdr.space"], "spA")
        self.assertIn(["get", MAIN, "--json"], self.hc_calls())  # 메인 터미널($HC_TERMINAL_ID)을 물려받았다
        log = (self.state_dir / "auto-up.log").read_text()
        self.assertRegex(log, r"--- \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ hteam up \(자동\)\n")
        self.assertIn('"launched"', log)
        rec, pid = self.record(), json.loads((self.state_dir / "auto-up.pid").read_text())
        self.assertEqual(rec["spawned_at"], rec["checked_at"])
        self.assertEqual(set(pid), {"pid", "started"})
        # 다시 확인하면 새 코디네이터는 시작 중이다(launched_at 뒤 180초)
        self.set_record(**{**rec, "checked_at": ago(70)})
        self.assertIsNone(self.check())

    def test_up_failing_before_launch_gives_failed_next(self):
        # (가) hc run 이 거부해 up 이 바꾼 키를 되돌렸다: 코디네이터 주소가 그대로 남고 다음 확인은 FAILED
        self.dead()
        self.fail_hc("run", "denied")
        self.assertEqual(self.check(), REVIVED)
        self.wait_failed_up()
        self.assertEqual(self.run_json()["coordinator_terminal"], COORD)
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(), FAILED)

    def test_uncertain_launch_is_starting_then_no_handle(self):
        # (나) hc run 결과를 알 수 없다(launch_uncertain): 주소를 지우고 pending_launch 를 남긴다
        self.dead()
        self.fail_hc("run", "bad_output")
        self.assertEqual(self.check(), REVIVED)
        self.wait_failed_up()
        run = self.run_json()
        self.assertNotIn("coordinator_terminal", run)
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertIsNone(self.check())  # 시작 유예
        self.set_run(launched_at=ago(200), pending_launch={**run["pending_launch"], "at": ago(200)})
        self.set_record(**{**self.record(), "checked_at": ago(70)})
        self.assertEqual(self.check(), NO_HANDLE)

    def wait_failed_up(self) -> None:
        rec = json.loads((self.state_dir / "auto-up.pid").read_text())
        deadline = time.monotonic() + 30
        while procs.record_alive(rec):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        self.assertIn('"ok": false', (self.state_dir / "auto-up.log").read_text())


class Clock:
    """가상 단조 시계(autoup._clock 자리). 패치한 단계가 부르면 그 단계가 걸린 만큼 앞으로 간다."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class BudgetTest(AutoUpCase):
    """훅 시작 4초 규칙과 마감(설계 9.5). 남은 시간은 가상 시계와 단계별 소요로 정해 실행 속도에 기대지 않는다."""

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
        before = self.gets()
        self.assertIsNone(check(self.p, force=True, started=self.clock.now - 4.5))
        self.assertEqual((self.gets(), self.record()), (before, {}))
        with mock.patch.object(autoup, "spawn_up", return_value=True):  # 다음 확인은 간격과 관계없이 바로 한다
            self.assertEqual(check(self.p, force=False, started=self.clock.now), REVIVED)
        self.assertEqual(self.gets(), before + 1)

    def test_deadline_stops_before_ps_hc_and_sh(self):
        self.fresh_pid()
        with mock.patch.object(autoup.procs, "record_alive") as alive:
            self.assertIsNone(decide(self.p, self.clock.now + 0.5))  # 진행 중 확인(ps) 앞에서 멈춘다
        alive.assert_not_called()
        before = self.gets()
        (self.state_dir / "auto-up.pid").unlink()
        self.assertIsNone(decide(self.p, self.clock.now + 0.5))  # hc 앞에서 멈춘다
        self.assertEqual(self.gets(), before)
        self.fresh_pid()  # ps 가 11.2초 걸렸다: hc 앞에서 멈추고 아무것도 쓰지 않는다
        with mock.patch.object(autoup.procs, "record_alive", side_effect=self.step("ps", 11.2, False)), \
                mock.patch.object(autoup.herdr, "probe") as probe:
            self.assertIsNone(check(self.p, force=True, started=self.clock.now))
        probe.assert_not_called()
        self.assertEqual(self.record(), {})
        (self.state_dir / "auto-up.pid").unlink()  # hc 가 11.5초 걸렸다: sh 앞에서 멈추고 아무것도 쓰지 않는다
        with mock.patch.object(autoup.herdr, "probe", side_effect=self.step("probe", 11.5, "exited")), \
                mock.patch.object(autoup.subprocess, "run") as run:
            self.assertIsNone(check(self.p, force=True, started=self.clock.now))
        run.assert_not_called()
        self.assertEqual(self.record(), {})
        self.assertFalse((self.state_dir / "auto-up.pid").exists())

    def test_each_step_gets_the_remaining_time(self):
        def run(ps, probe, sh):
            self.fresh_pid()
            self.set_record()
            with mock.patch.object(autoup.procs, "record_alive", side_effect=self.step("ps", ps, False)), \
                    mock.patch.object(autoup.herdr, "probe", side_effect=self.step("probe", probe, "exited")), \
                    mock.patch.object(autoup.subprocess, "run", side_effect=self.sh(sh)), \
                    mock.patch.object(autoup.procs, "start_time", side_effect=self.step("start", 0, "Sun Nov  8 00:00:00 2026")):
                self.assertEqual(check(self.p, force=True, started=self.clock.now), REVIVED)
            return tuple(self.seen[k] for k in ("ps", "probe", "sh", "start"))
        self.assertEqual(run(0, 0, 0), (5, 3, 5, 5))  # 남은 시간이 넉넉하면 자기 제한
        self.assertEqual(run(9, 1, 0.5), (5, 3, 2, 1.5))  # ps 9초 뒤 남은 3초, hc 1초 뒤 2초, sh 0.5초 뒤 1.5초

    def test_started_is_null_when_time_is_short_after_spawn(self):
        with mock.patch.object(autoup.herdr, "probe", side_effect=self.step("probe", 0, "exited")), \
                mock.patch.object(autoup.subprocess, "run", side_effect=self.sh(11.5)), \
                mock.patch.object(autoup.procs, "start_time") as start_time:
            self.assertEqual(check(self.p, force=True, started=self.clock.now), REVIVED)
        start_time.assert_not_called()
        self.assertEqual(json.loads((self.state_dir / "auto-up.pid").read_text()), {"pid": 4242, "started": None})
        self.assertIn("spawned_at", self.record())


if __name__ == "__main__":
    unittest.main()
