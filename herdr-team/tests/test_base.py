"""paths·util·procs·horch 클라이언트·roles 의 기본 동작."""
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import DRIVE, HORCH_BIN, TeamCase
from hteam import horch as horch_mod
from hteam import paths, procs, roles, util
from hteam.errors import HteamError


class PathsTest(TeamCase):
    def test_find_project_walks_up_and_root_flag(self):
        self.init_project(commit=False)
        sub = self.proj / "src" / "deep"
        sub.mkdir(parents=True)
        cwd = os.getcwd()
        os.chdir(sub)
        try:
            self.assertEqual(paths.find_project(None).root, self.proj)
        finally:
            os.chdir(cwd)
        self.assertEqual(paths.find_project(str(self.proj)).root, self.proj)
        with self.assertRaises(HteamError) as ctx:
            paths.find_project(str(self.tmp))
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("no_project", 2))

    def test_relative_paths(self):
        self.assertEqual(paths.report_rel("T-001"), "docs/tasks/T-001/report.md")
        self.assertEqual(paths.review_rel("T-001", 2), "docs/reviews/T-001/r2.md")
        self.assertEqual(paths.review_rel("T-001", 2, 1), "docs/reviews/T-001/r2-a1.md")


class UtilTest(unittest.TestCase):
    def test_fill_and_missing_slot(self):
        self.assertEqual(util.fill("a {{x}} {b}", x="1"), "a 1 {b}")
        with self.assertRaises(KeyError):
            util.fill("{{y}}")

    def test_write_atomic_and_json(self):
        with __import__("tempfile").TemporaryDirectory() as d:
            path = Path(d) / "a" / "b.json"
            util.write_json(path, {"k": "값"})
            self.assertEqual(util.read_json(path, None), {"k": "값"})
            self.assertEqual(util.read_json(Path(d) / "none.json", 7), 7)
            self.assertEqual([p.name for p in path.parent.iterdir()], ["b.json"])

    def test_flock_serializes(self):
        with __import__("tempfile").TemporaryDirectory() as d:
            lock = Path(d) / "lock"
            order = []

            def other():
                with util.flock(lock):
                    order.append("other")

            with util.flock(lock):
                th = threading.Thread(target=other)
                th.start()
                th.join(0.2)
                order.append("first")
            th.join()
            self.assertEqual(order, ["first", "other"])

    def test_age_seconds(self):
        self.assertLess(util.age_seconds(util.now()), 5)
        self.assertIsNone(util.age_seconds("bad"))


class ProcsTest(unittest.TestCase):
    def test_alive_and_reuse(self):
        me = procs.me()
        self.assertTrue(procs.record_alive(me))
        self.assertFalse(procs.alive(me["pid"], "Thu Jan  1 00:00:00 1970"))
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(procs.alive(child.pid, None))
        self.assertFalse(procs.record_alive(None))


class HorchClientTest(TeamCase):
    def test_find_order(self):
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(HORCH_BIN)}):
            self.assertEqual(horch_mod.find_horch(), HORCH_BIN.resolve())
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(self.tmp / "none")}):
            with self.assertRaises(HteamError) as ctx:
                horch_mod.find_horch()
            self.assertEqual(ctx.exception.exit_code, 12)
        env = {k: v for k, v in os.environ.items() if k != "HERDR_ORCH_BIN"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(horch_mod.find_horch(), HORCH_BIN.resolve())  # 형제 폴더
            registry = self.tmp / "installed.json"
            registry.write_text(json.dumps({"plugins": {"herdr-orch@herdr-team": [
                {"installPath": str(HORCH_BIN.parent.parent)}]}}))
            os.environ["HTEAM_PLUGINS_JSON"] = str(registry)
            with mock.patch.object(horch_mod, "PLUGIN_ROOT", self.tmp / "x" / "herdr-team"):
                self.assertEqual(horch_mod.find_horch(), HORCH_BIN.resolve())
                os.environ["HTEAM_PLUGINS_JSON"] = str(self.tmp / "none.json")
                with self.assertRaises(HteamError):
                    horch_mod.find_horch()

    def install(self, name, version):
        """가짜 herdr-orch 설치 폴더(bin/horch 와 plugin.json)."""
        root = self.tmp / "cache" / name
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "horch").write_text("")
        (root / ".claude-plugin").mkdir()
        (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
        return root

    def registry(self, entries, key="herdr-orch@herdr-team"):
        path = self.tmp / "installed.json"
        path.write_text(json.dumps({"version": 2, "plugins": {key: entries}}))
        return path

    def test_registry_picks_scope_project_and_version(self):
        old = self.install("old", "0.4.0")  # 12단계: HORCH_MIN 0.5.0 아래(대리 보고·relay-status 가 없다)
        user = self.install("user", "0.5.0")
        other = self.install("other", "0.5.9")
        mine = self.install("mine", "0.5.0")
        local = self.install("local", "0.5.1")
        env = {k: v for k, v in os.environ.items() if k != "HERDR_ORCH_BIN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(horch_mod, "PLUGIN_ROOT", self.tmp / "x" / "herdr-team"):
            entries = [{"scope": "user", "installPath": str(old), "version": "0.4.0"},
                       {"scope": "project", "projectPath": str(self.tmp / "elsewhere"), "installPath": str(other)},
                       {"scope": "user", "installPath": str(user)}]
            os.environ["HTEAM_PLUGINS_JSON"] = str(self.registry(entries))
            self.assertEqual(horch_mod.find_horch(self.proj), (user / "bin/horch").resolve())  # 다른 프로젝트 것은 쓰지 않는다
            entries.append({"scope": "project", "projectPath": str(self.proj), "installPath": str(mine)})
            self.registry(entries)
            self.assertEqual(horch_mod.find_horch(self.proj / "sub"), (mine / "bin/horch").resolve())  # 하위 폴더도 그 프로젝트
            self.assertEqual(horch_mod.find_horch(None), (user / "bin/horch").resolve())  # 프로젝트를 모르면 user 범위만
            entries.append({"scope": "local", "projectPath": str(self.proj), "installPath": str(local)})
            self.registry(entries)
            self.assertEqual(horch_mod.find_horch(self.proj), (local / "bin/horch").resolve())  # local 이 project 보다 앞선다
            h = horch_mod.Horch(self.proj / ".herdr-team" / "state" / "horch")  # 홈에서 프로젝트를 찾는다
            self.assertEqual(h.bin, (local / "bin/horch").resolve())
            self.registry([{"scope": "user", "installPath": str(old)}])
            with self.assertRaises(HteamError) as ctx:
                horch_mod.find_horch(self.proj)
            self.assertEqual(ctx.exception.exit_code, 12)
            self.assertIn("쓰지 않은 설치: herdr-orch@herdr-team user 0.4.0(0.5.0 보다 낮다)", ctx.exception.message)

    def test_corrupt_registry_entries_are_skipped(self):
        # 손상된 설치 기록 하나(자료형이 틀린 scope·projectPath·version·installPath)가 TypeError 로 고르기를 멈추지 않는다.
        # 그 항목만 이유와 함께 빼고 뒤의 정상 후보를 고른다
        good = self.install("good", "0.5.0")
        env = {k: v for k, v in os.environ.items() if k != "HERDR_ORCH_BIN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(horch_mod, "PLUGIN_ROOT", self.tmp / "x" / "herdr-team"):
            entries = [{"scope": [], "installPath": str(good)},
                       {"scope": "project", "projectPath": ["x"], "installPath": str(good)},
                       {"scope": "user", "installPath": str(good), "version": [0, 1, 2]},
                       {"scope": "user", "installPath": 7},
                       {"scope": "user", "installPath": str(good)}]
            os.environ["HTEAM_PLUGINS_JSON"] = str(self.registry(entries))
            self.assertEqual(horch_mod.find_horch(self.proj), (good / "bin/horch").resolve())
            path, skipped = horch_mod._from_registry(self.proj)
            self.assertEqual(len([s for s in skipped if "손상된 설치 기록" in s]), 4, skipped)
            self.registry(entries[:4])
            with self.assertRaises(HteamError) as ctx:
                horch_mod.find_horch(self.proj)
            self.assertEqual(ctx.exception.exit_code, 12)
            self.assertIn("손상된 설치 기록(scope)", ctx.exception.message)

    def test_bad_values_in_registry_entries_are_skipped(self):
        # Codex 계획 r2: 자료형은 맞지만 값이 손상된 항목("1.2.²" 는 isdigit 가 참이라 int() 가 실패, 없는 사용자의 ~경로는
        # expanduser 가 RuntimeError)도 그 항목만 까닭과 함께 빼고 뒤의 정상 후보를 고른다
        good = self.install("good", "0.5.0")
        odd = self.install("odd", "1.2.²")
        env = {k: v for k, v in os.environ.items() if k != "HERDR_ORCH_BIN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(horch_mod, "PLUGIN_ROOT", self.tmp / "x" / "herdr-team"):
            entries = [{"scope": "user", "installPath": str(odd), "version": "1.2.²"},
                       {"scope": "user", "installPath": "~hteam-no-such-user-x/plugin"},
                       {"scope": "project", "projectPath": "~hteam-no-such-user-y/proj", "installPath": str(good)},
                       {"scope": "user", "installPath": str(good)}]
            os.environ["HTEAM_PLUGINS_JSON"] = str(self.registry(entries))
            self.assertEqual(horch_mod.find_horch(self.proj), (good / "bin/horch").resolve())
            path, skipped = horch_mod._from_registry(self.proj)
            self.assertIn("herdr-orch@herdr-team user 버전 모름", skipped)
            self.assertEqual(len([s for s in skipped if "경로를 해석하지 못했다" in s]), 2, skipped)
        # Codex 계획 r3: 아주 긴 숫자(int 변환 상한을 넘는다)도 그 항목만 빼고 뒤의 정상 후보를 고른다
        huge = "9" * 4301 + ".0.0"
        long = self.install("long", huge)
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(horch_mod, "PLUGIN_ROOT", self.tmp / "x" / "herdr-team"):
            os.environ["HTEAM_PLUGINS_JSON"] = str(self.registry([{"scope": "user", "installPath": str(long), "version": huge},
                                                                 {"scope": "user", "installPath": str(good)}]))
            self.assertEqual(horch_mod.find_horch(self.proj), (good / "bin/horch").resolve())
        self.assertIsNone(horch_mod.version_tuple(huge))
        self.assertIsNone(horch_mod.version_tuple("1234567.0.0"))  # 숫자 조각은 6자리까지
        self.assertEqual(horch_mod.version_tuple("123456.0.0"), (123456, 0, 0))
        self.assertIsNone(horch_mod.version_tuple("1.2.²"))
        self.assertIsNone(horch_mod.version_tuple("０.1.2"))  # 전각 숫자
        self.assertEqual(horch_mod.version_tuple(" 0.1.12 "), (0, 1, 12))

    def test_env_and_sibling_horch_below_min_stop(self):
        # 12단계(설계 3.3): HERDR_ORCH_BIN·형제 경로로 고른 horch 도 같은 플러그인의 plugin.json 버전을 본다. HORCH_MIN 아래면
        # exit 12(0.4.0 horch 로 새 세션에 relay_ready 를 적지 않게, Codex 설계 리뷰 r2)
        self.assertEqual(horch_mod.HORCH_MIN, "0.5.0")
        low, good = self.install("low", "0.4.0"), self.install("good", "0.5.0")
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(low / "bin/horch")}):
            with self.assertRaises(HteamError) as ctx:
                horch_mod.find_horch()
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("horch_missing", 12))
        self.assertIn("0.4.0(0.5.0 보다 낮다)", ctx.exception.message)
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(good / "bin/horch")}):
            self.assertEqual(horch_mod.find_horch(), (good / "bin/horch").resolve())
        env = {k: v for k, v in os.environ.items() if k != "HERDR_ORCH_BIN"}
        for version, fine in (("0.4.0", False), ("0.5.0", True)):
            orch = self.tmp / f"sib-{version}" / "herdr-orch"
            (orch / "bin").mkdir(parents=True)
            (orch / "bin" / "horch").write_text("")
            (orch / ".claude-plugin").mkdir()
            (orch / ".claude-plugin" / "plugin.json").write_text(json.dumps({"version": version}))
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(horch_mod, "PLUGIN_ROOT", orch.parent / "herdr-team"):
                if fine:
                    self.assertEqual(horch_mod.find_horch(), (orch / "bin/horch").resolve())
                else:
                    with self.assertRaises(HteamError) as ctx:
                        horch_mod.find_horch()
                    self.assertEqual(ctx.exception.exit_code, 12)

    def solo(self, name: str, answer: str, delay: float = 0) -> Path:
        """plugin.json 이 곁에 없는 대역 horch. `version` 에는 delay 초 뒤 answer 를 답하고(부른 횟수를 <이름>.n 에 센다),
        다른 명령에는 {"ok": true, "seen": 1} 을 답한다."""
        script = self.tmp / name
        script.write_text("import sys, time\nfrom pathlib import Path\n"
                          "if sys.argv[-1] == 'version':\n"
                          f"    n = Path({str(script) + '.n'!r})\n"
                          "    n.write_text(str(int(n.read_text()) + 1) if n.exists() else '1')\n"
                          f"    time.sleep({delay})\n"
                          f"    print({answer!r})\n"
                          "else:\n"
                          "    print('{\"ok\": true, \"seen\": 1}')\n")
        return script

    def probes(self, script: Path) -> int:
        n = Path(str(script) + ".n")
        return int(n.read_text()) if n.exists() else 0

    def test_horch_without_plugin_json_is_checked_before_the_first_call(self):
        # plugin.json 이 곁에 없는 horch(감싼 스크립트 등)는 첫 호출 전에 `horch version` 으로 본다(생성자는 부르지 않는다).
        # 낮으면 그 호출이 exit 12 오류 모양으로 끝난다. 확인한 버전은 이 프로세스 동안 기억한다(다시 묻지 않는다)
        home = self.proj / ".herdr-team" / "state" / "horch"
        low = self.solo("solo-low", '{"ok": true, "version": "0.4.0"}')
        good = self.solo("solo-good", '{"ok": true, "version": "0.5.0"}')
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(low)}):
            h = horch_mod.Horch(home)
            self.assertEqual(self.probes(low), 0)
            code, data = h.call("status")
            self.assertEqual((code, data["error"]["code"]), (12, "horch_missing"), data)
            self.assertIn("0.4.0(0.5.0 보다 낮다)", data["error"]["message"])
            with self.assertRaises(HteamError) as ctx:
                h.ok("status")
            self.assertEqual(ctx.exception.exit_code, 12)
            self.assertFalse(horch_mod.version_confirmed(home))
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(good)}):
            h = horch_mod.Horch(home)
            self.assertEqual(h.call("status"), (0, {"ok": True, "seen": 1}))
            self.assertEqual(h.call("status"), (0, {"ok": True, "seen": 1}))
            self.assertTrue(horch_mod.version_confirmed(home))
        self.assertEqual((self.probes(low), self.probes(good)), (1, 1))

    def test_unconfirmed_version_is_not_remembered(self):
        # 계획 리뷰 plan2-r1 의 8: 버전을 확인하지 못하면(잘못된 출력) 통과로 기억하지 않는다. 그 호출은 지금처럼 하고 다음
        # 호출이 다시 본다. 고정 에이전트의 relay_ready 는 version_confirmed 가 참일 때만 쓴다(Task 5)
        home = self.proj / ".herdr-team" / "state" / "horch"
        bad = self.solo("solo-bad", '{"ok": true}')
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(bad)}):
            h = horch_mod.Horch(home)
            self.assertEqual(h.call("status"), (0, {"ok": True, "seen": 1}))
            self.assertEqual(h.call("status"), (0, {"ok": True, "seen": 1}))
            self.assertFalse(horch_mod.version_confirmed(home))
        self.assertEqual(self.probes(bad), 3)  # 호출마다, version_confirmed 도 한 번 더 묻는다
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(self.tmp / "none")}):
            self.assertFalse(horch_mod.version_confirmed(home))  # horch 를 찾지 못했다
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(HORCH_BIN)}):
            self.assertTrue(horch_mod.version_confirmed(home))  # 함께 배포하는 herdr-orch: plugin.json 으로 안다

    def test_version_probe_stays_within_the_call_budget(self):
        # 계획 리뷰 plan2-r1 의 6: 버전 조회도 그 호출의 timeout 안이다(상한 min(10, timeout), 걸린 시간은 본 명령에서 뺀다).
        # 시간 초과는 기억하지 않는다
        home = self.proj / ".herdr-team" / "state" / "horch"
        slow = self.solo("solo-slow", '{"ok": true, "version": "0.5.0"}', delay=2)
        with mock.patch.dict(os.environ, {"HERDR_ORCH_BIN": str(slow)}):
            h = horch_mod.Horch(home)
            t0 = time.monotonic()
            code, data = h.call("status", timeout=0.5)
            self.assertLess(time.monotonic() - t0, 1.5)
            self.assertEqual((code, data["error"]["code"]), (1, "horch_timeout"), data)
            self.assertEqual(data["error"]["message"], "horch status 가 0.5초 안에 끝나지 않았다")
            self.assertEqual(h.call("status", timeout=8), (0, {"ok": True, "seen": 1}))  # 다시 묻고 기억한다
            t0 = time.monotonic()
            self.assertEqual(h.call("status", timeout=8), (0, {"ok": True, "seen": 1}))
            self.assertLess(time.monotonic() - t0, 1.5)  # 확인한 뒤에는 묻지 않는다
        self.assertEqual(self.probes(slow), 2)

    def test_call_ok_and_failure(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            h = horch_mod.Horch(self.horch_home)
            self.assertEqual(h.ok("version")["version"][:4], "0.5.")  # 함께 배포하는 herdr-orch 0.5.0
            code, data = h.call("worker-list")
            self.assertEqual(code, 5)
            with self.assertRaises(HteamError) as ctx:
                h.ok("worker-list")
            self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("horch_failed", 1))
            self.assertEqual(ctx.exception.data["horch"]["error"]["code"], "not_owner")
            self.assertIn("--home", h.cmd())

    def test_parse_and_agent_args(self):
        self.assertEqual(horch_mod.parse('noise\n{"ok": true}\n')["ok"], True)
        self.assertEqual(horch_mod.parse("garbage")["error"]["code"], "bad_output")
        self.assertEqual(horch_mod.agent_args(["--disable=hooks", "-x"]),
                         ["--agent-arg=--disable=hooks", "--agent-arg=-x"])


class RolesTest(TeamCase):
    def test_titles(self):
        self.assertEqual(roles.work_title("T-003", 2), "T-003 r2 작업")
        self.assertEqual(roles.review_title("T-003", 2, 1), "T-003 r2 리뷰 a1")
        self.assertEqual(roles.parse_title("T-003 r2 작업"), {"task": "T-003", "round": 2, "kind": "work", "attempt": None})
        self.assertEqual(roles.parse_title("T-1234 r1 리뷰 a3")["attempt"], 3)
        self.assertIsNone(roles.parse_title("e2e"))

    def test_drive_env_is_role_and_terminal(self):
        # 설계 8.2 관제 판별: HTEAM_ROLE=drive 이고 $HC_TERMINAL_ID 가 run.json 의 drive_terminal 이다(nonce 는 시작 때만 본다)
        self.init_project(commit=False)
        self.setup_run()
        p = paths.Project(self.proj)
        with mock.patch.dict(os.environ, {"HTEAM_ROLE": "drive", "HC_TERMINAL_ID": DRIVE, "HTEAM_LAUNCH": "any"}):
            self.assertTrue(roles.drive_env(p))
            roles.require_drive(p)
        for env in ({"HTEAM_ROLE": "drive", "HC_TERMINAL_ID": "t999"}, {"HTEAM_ROLE": "coordinator", "HC_TERMINAL_ID": DRIVE}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                self.assertFalse(roles.drive_env(p))
                with self.assertRaises(HteamError) as ctx:
                    roles.require_drive(p)
                self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("drive_only", 5))
        (p.run_file).write_text("[]")
        with mock.patch.dict(os.environ, {"HTEAM_ROLE": "drive", "HC_TERMINAL_ID": DRIVE}):
            with self.assertRaises(HteamError) as ctx:
                roles.drive_env(p)
            self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_run_file", 1))
        for gone in ("coordinator_env", "require_coordinator"):
            self.assertFalse(hasattr(roles, gone), gone)


if __name__ == "__main__":
    unittest.main()
