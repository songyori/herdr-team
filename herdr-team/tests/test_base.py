"""paths·util·procs·horch 클라이언트·roles 의 기본 동작."""
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import HORCH_BIN, NONCE, TeamCase
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
        old = self.install("old", "0.1.1")
        user = self.install("user", "0.1.2")
        other = self.install("other", "0.1.9")
        mine = self.install("mine", "0.1.2")
        local = self.install("local", "0.1.3")
        env = {k: v for k, v in os.environ.items() if k != "HERDR_ORCH_BIN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(horch_mod, "PLUGIN_ROOT", self.tmp / "x" / "herdr-team"):
            entries = [{"scope": "user", "installPath": str(old), "version": "0.1.1"},
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
            self.assertIn("쓰지 않은 설치: herdr-orch@herdr-team user 0.1.1(0.1.2 보다 낮다)", ctx.exception.message)

    def test_corrupt_registry_entries_are_skipped(self):
        # 손상된 설치 기록 하나(자료형이 틀린 scope·projectPath·version·installPath)가 TypeError 로 고르기를 멈추지 않는다.
        # 그 항목만 이유와 함께 빼고 뒤의 정상 후보를 고른다
        good = self.install("good", "0.1.2")
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
        good = self.install("good", "0.1.2")
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

    def test_call_ok_and_failure(self):
        with mock.patch.dict(os.environ, self.env, clear=True):
            h = horch_mod.Horch(self.horch_home)
            self.assertEqual(h.ok("version")["version"][:4], "0.1.")
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

    def test_coordinator_env_needs_nonce(self):
        self.init_project(commit=False)
        self.setup_run()
        p = paths.Project(self.proj)
        with mock.patch.dict(os.environ, {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": NONCE}):
            self.assertTrue(roles.coordinator_env(p))
            roles.require_coordinator(p)
        with mock.patch.dict(os.environ, {"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": "other"}):
            self.assertFalse(roles.coordinator_env(p))
            with self.assertRaises(HteamError) as ctx:
                roles.require_coordinator(p)
            self.assertEqual(ctx.exception.exit_code, 5)


if __name__ == "__main__":
    unittest.main()
