"""테스트 관문(설계 5.7): [test] 형식·HEAD 읽기·식별값, 확정 기록, hteam test 의 대상·실행·기록·exit 코드."""
import fcntl
import json
import os
import signal
import subprocess
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TeamCase
from hteam import gitio, plan, state, testgate
from hteam.errors import HteamError
from hteam.paths import Project


class ConfigTest(unittest.TestCase):
    def test_plan_file_matches_plan_module(self):
        self.assertEqual(testgate.PLAN_FILE, plan.PLAN_FILE)

    def test_defaults(self):
        cfg = testgate.parse_config({"quick": " a {files} ", "full": "b"})
        self.assertEqual((cfg.quick, cfg.full, cfg.timeout_min, cfg.ok_exit, cfg.exclusive),
                         ("a {files}", "b", 30, (0,), False))

    def test_problems(self):
        self.assertEqual(testgate.config_problems(["x"]), ["[test] 는 표여야 한다"])
        self.assertEqual(testgate.config_problems({"quick": "a {files}", "full": "b", "timeout_min": 240,
                                                   "ok_exit": [0, 5], "exclusive": True}), [])
        self.assertEqual(testgate.config_problems({"quick": "a", "full": "b {files}", "timeout_min": 0,
                                                   "ok_exit": [], "exclusive": "yes", "zz": 1, "aa": 2}),
                         ["[test]: 모르는 키 aa, zz", "[test]: quick 은 {files} 를 정확히 한 번 담는다",
                          "[test]: full 은 {files} 를 담지 않는다", "[test]: timeout_min 은 1–240 정수",
                          "[test]: ok_exit 는 정수 목록", "[test]: exclusive 는 true 또는 false"])
        self.assertEqual(testgate.config_problems({"quick": " ", "full": 3, "timeout_min": True, "ok_exit": [True]}),
                         ["[test]: quick 는 비지 않은 명령 문자열이어야 한다",
                          "[test]: full 는 비지 않은 명령 문자열이어야 한다", "[test]: timeout_min 은 1–240 정수",
                          "[test]: ok_exit 는 정수 목록"])
        self.assertEqual(testgate.config_problems({"quick": "a {files} {files}", "full": "b", "timeout_min": 241})[0],
                         "[test]: quick 은 {files} 를 정확히 한 번 담는다")
        quoted = "[test]: quick 의 {files} 는 따옴표 밖에 둔다(hteam 이 파일을 따로 인자로 넘긴다)"
        for bad in ('fake-test "{files}"', "fake-test '{files}'", 'x "a $(b)" "{files}"', "x 'a' \"p {files} q\"",
                    'x "$(echo "{files}")"', "pytest \\{files}", 'pytest "\\{files}"', "x '$( {files}", "pytest a#b' {files}"):
            self.assertEqual(testgate.config_problems({"quick": bad, "full": "b"}), [quoted], bad)
        for good in ('fake-test "a b" {files}', "fake-test 'a b' \\' {files}", 'x "{" {files}',
                     "# project's tests\npytest {files}", 'out="$(pytest {files})"', 'x "`y {files}`"',
                     "x '$(' {files}", 'x "a\\q" {files}', "x $(y 'z)' ) {files}"):
            self.assertEqual(testgate.config_problems({"quick": good, "full": "b"}), [], good)
        with self.assertRaises(HteamError) as cm:
            testgate.parse_config({"quick": "a"})
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("bad_test_config", 2))
        self.assertIn("docs/planning/tasks.toml [test] 검증 실패: [test]: full 는", cm.exception.message)

    def test_digest_normalizes_and_changes_with_values(self):
        base = testgate.digest(testgate.parse_config({"quick": "a {files}", "full": "b"}))
        same = testgate.parse_config({"quick": "  a {files}\n", "full": "b ", "timeout_min": 30, "ok_exit": [0],
                                      "exclusive": False})
        self.assertEqual(testgate.digest(same), base)
        self.assertEqual(len(base), 64)
        for changed in ({"quick": "c {files}", "full": "b"}, {"quick": "a {files}", "full": "b", "ok_exit": [0, 5]}):
            self.assertNotEqual(testgate.digest(testgate.parse_config(changed)), base)

    def test_describe_shows_non_utf8_names(self):
        # Codex 계획 리뷰 r1: quick 파일 이름은 os.fsdecode 로 보존해 서로게이트를 담을 수 있다. 보이는 줄은 UTF-8 로 써진다
        entry = {"status": "failed", "seconds": 0.1, "exit": 1, "command": "true src/a\udcff.py", "log": "x.log",
                 "dirty": ["lib/b\udcfe.py"]}
        lines = testgate.describe(entry, "quick")
        self.assertEqual(lines[1], 'quick 명령: "true src/a\\udcff.py"')
        self.assertEqual(lines[-1], "실행 때 커밋 안 된 다른 파일: lib/b\\xfe.py")
        "\n".join(lines).encode("utf-8")

    def test_fence_is_longer_than_backticks_inside(self):
        self.assertEqual(testgate.fence("plain"), "```")
        self.assertEqual(testgate.fence("a ```` b ``"), "`````")
        section = testgate.confirm_section(testgate.parse_config({"quick": "t \"x\" {files}", "full": "f"}))
        self.assertEqual(section, "## 테스트 명령\n" + testgate.CONFIRM_LINE + "\n```toml\nquick = \"t \\\"x\\\" {files}\"\n"
                         "full = \"f\"\ntimeout_min = 30\nok_exit = [0]\nexclusive = false\n```")


class GateCase(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.p = Project(self.proj)

    def started(self, tid: str = "T-001", owns=("src/**",), role: str = "developer", base: str | None = None) -> None:
        """시작한 태스크의 상태(base·round·owns)를 쓴다."""
        with mock.patch.dict(os.environ, self.env, clear=True):
            state.create(self.p, tid, role)
            with state.edit(self.p, tid) as st:
                st.update(round=1, base=base or self.head(), owns=list(owns), status="working")

    def run_test(self, *args: str, **kw):
        return self.hteam("test", *args, as_=None, **kw)

    def record(self, tid: str = "T-001") -> dict:
        path = self.state_dir / "tests" / f"{tid}.json"
        return json.loads(path.read_text()) if path.exists() else {}


class HeadConfigTest(GateCase):
    def test_no_test_table_and_arguments(self):
        self.started()
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "no_test_config"), out)
        self.assertEqual(out["error"]["message"], testgate.NO_CONFIG)
        code, out = self.run_test()
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                         (2, "usage", "태스크 ID 또는 --full 이 필요하다"))
        self.use_gate()
        code, out = self.run_test("../x")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_task_id"))
        code, out = self.run_test("T-009")
        self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                         (2, "not_started", "T-009 는 아직 시작하지 않은 태스크다(hteam start)"))

    def test_uncommitted_table_keeps_the_gate_off(self):
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        self.use_gate(commit=False, approve=False)
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "no_test_config"), out)
        self.assertEqual(self.gate_calls(), [])

    def test_repo_without_commits_is_off(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(fresh)], check=True, env=self.env)
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertIsNone(testgate.load_config(Project(fresh)))

    def test_committed_broken_toml_and_worktree_edits(self):
        self.started()
        self.commit("docs/planning/tasks.toml", "[test\n", "plan: 깨짐")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_unreadable"), out)
        self.assertIn("docs/planning/tasks.toml 읽기 실패", out["error"]["message"])
        self.use_gate()
        self.commit("src/a.py", "a\n", "[T-001] a")
        (self.proj / "docs/planning/tasks.toml").write_text("깨짐 [", encoding="utf-8")  # 작업 트리만 깬다
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"]), (0, "passed"), out)

    def test_bad_format_is_exit_2(self):
        self.started()
        self.commit("docs/planning/tasks.toml", '[test]\nquick = "x"\nfull = "y"\n', "plan: [test]")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_test_config"), out)


class ApprovalTest(GateCase):
    def test_unapproved_then_approved(self):
        self.started()
        self.use_gate(approve=False)
        self.commit("src/a.py", "a\n", "[T-001] a")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "test_unapproved"), out)
        self.assertIn("hteam status 의 test_gate", out["error"]["message"])
        self.assertEqual(self.gate_calls(), [])
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(testgate.gate_state(self.p)["state"], "unapproved")
            self.assertEqual(testgate.read_approvals(self.p), [])
        self.approve_gate()
        self.approve_gate()  # 두 번 더해도 하나다
        with mock.patch.dict(os.environ, self.env, clear=True):
            path = testgate.approvals_path(self.p)
            items = testgate.read_approvals(self.p)
            self.assertEqual(testgate.gate_state(self.p)["state"], "approved")
        self.assertEqual(len(items), 1)
        self.assertEqual(sorted(items[0]), ["at", "digest", "full", "out_id", "quick"])
        self.assertTrue(str(path).startswith(str(self.tmp / "home" / ".local" / "state" / "herdr-team" / "projects")))
        self.assertFalse(str(path).startswith(str(self.proj)))
        self.assertEqual(self.run_test("T-001")[0], 0)
        # 확정 뒤 [test] 를 바꿔 커밋하면 다시 확정하지 않은 [test] 다
        self.commit("docs/planning/tasks.toml", '[test]\nquick = "fake-test -v {files}"\nfull = "fake-test --all"\n',
                    "plan: [test] 바꿈")
        self.assertEqual(self.run_test("T-001")[1]["error"]["code"], "test_unapproved")

    def test_xdg_state_home_and_broken_record(self):
        self.started()
        self.use_gate(approve=False)
        self.env["XDG_STATE_HOME"] = str(self.tmp / "xdg")
        self.approve_gate()
        with mock.patch.dict(os.environ, self.env, clear=True):
            path = testgate.approvals_path(self.p)
        self.assertTrue(path.is_file() and str(path).startswith(str(self.tmp / "xdg" / "herdr-team")))
        path.write_text("{깨짐", encoding="utf-8")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (1, "bad_test_approvals"), out)
        self.assertIn(str(path), out["error"]["message"])
        self.assertEqual(path.read_text(encoding="utf-8"), "{깨짐")
        with mock.patch.dict(os.environ, self.env, clear=True):
            gate = testgate.gate_state(self.p)
        self.assertEqual(gate["state"], "error")
        self.assertIn(str(path), gate["error"])


class QuickTest(GateCase):
    def setUp(self):
        super().setUp()
        self.use_gate()
        self.started(owns=("src/**",))

    def test_quotes_paths_and_skips_deleted_outside_and_reports(self):
        self.commit("src/my file.py", "a\n", "[T-001] 공백 파일")
        self.commit("src/gone.py", "g\n", "[T-001] 지울 파일")
        self.git("rm", "-q", "src/gone.py")
        self.git("commit", "-q", "-m", "[T-001] 지움")
        code_sha = self.head()
        self.commit("docs/tasks/T-001/report.md", "## r1\n", "[T-001] 보고서")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"], out["kind"], out["task"]), (0, "passed", "quick", "T-001"), out)
        self.assertEqual(out["files"], ["src/my file.py"])
        self.assertEqual(out["command"], "fake-test 'src/my file.py'")
        self.assertEqual(out["head"], code_sha)
        self.assertEqual(self.gate_calls()[-1]["args"], ["src/my file.py"])
        self.assertTrue(out["log"].startswith(".herdr-team/state/tests/logs/T-001-r1-quick-a1-"), out["log"])
        self.assertEqual((self.proj / out["log"]).read_text().splitlines()[0], "$ fake-test 'src/my file.py'")
        saved = self.record()["quick"]
        self.assertEqual({k: saved[k] for k in ("round", "head", "status", "exit", "files")},
                         {"round": 1, "head": code_sha, "status": "passed", "exit": 0, "files": ["src/my file.py"]})
        self.assertEqual(saved["config"], out["config"])

    def test_only_report_commit_is_skipped(self):
        self.commit("docs/tasks/T-001/report.md", "## r1\n", "[T-001] 보고서")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"], out["head"], out["command"], out["log"], out["files"]),
                         (0, "skipped", None, None, None, []), out)
        self.assertEqual(self.gate_calls(), [])

    def test_two_failures_flaky_and_ok_exit(self):
        self.commit("src/a.py", "a\n", "[T-001] a")
        self.gate_modes("fail", "fail")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"], out["exit"]), (1, "failed", 1), out)
        self.assertIn("-quick-a2-", out["log"])
        self.assertIn("FAIL tests/a.test.ts > 더하기", out["tail"])
        self.assertNotIn("\n\n", out["tail"])
        self.assertFalse(any(not line.strip() for line in out["tail"].splitlines()))
        self.gate_modes("fail", "pass")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"], out["exit"], out["first"]["exit"]), (0, "flaky", 0, 1), out)
        self.assertIn("-quick-a1-", out["first"]["log"])

    def test_ok_exit_five_and_unrunnable(self):
        self.commit("docs/planning/tasks.toml", '[test]\nquick = "fake-test {files}"\nfull = "fake-test --all"\n'
                    "ok_exit = [0, 5]\n", "plan: pytest 식")
        self.approve_gate()
        self.commit("src/a.py", "a\n", "[T-001] a")
        self.gate_modes("five")
        self.assertEqual(self.run_test("T-001")[1]["status"], "passed")
        self.gate_modes("missing")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "test_unrunnable"), out)
        self.assertIn("exit 127", out["error"]["message"])
        self.assertEqual(self.record()["quick"]["status"], "passed")  # 실행 불가는 기록하지 않는다

    def test_dirty_lists_other_tracked_changes(self):
        self.commit("lib/other.py", "o\n", "다른 태스크")
        self.commit("src/a.py", "a\n", "[T-001] a")
        (self.proj / "lib/other.py").write_text("작업 중\n")
        (self.proj / "docs/tasks/T-001").mkdir(parents=True)
        (self.proj / "docs/tasks/T-001/report.md").write_text("초안\n")  # 보고서 초안은 막지 않는다
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["dirty"]), (0, ["lib/other.py"]), out)

    def test_refuses_before_commit_and_with_uncommitted_owned(self):
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "no_work_commit"), out)
        self.assertIn("아직 `[T-001]` 작업 커밋이 없다", out["error"]["message"])
        self.commit("src/a.py", "a\n", "[T-001] a")
        (self.proj / "src/a.py").write_text("고침\n")
        (self.proj / "src/new.py").write_text("새 파일\n")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "uncommitted_owned"), out)
        self.assertIn("src/a.py, src/new.py", out["error"]["message"])
        self.assertIn('hteam fix T-001 --note "커밋 안 된 파일을 커밋하거나 지운다"', out["error"]["message"])
        self.assertEqual(self.gate_calls(), [])
        code, out = self.run_test("T-001", "--full")  # full 은 이 검사를 하지 않는다
        self.assertEqual((code, out["kind"], out["status"]), (0, "full", "passed"), out)

    def test_tester_qa_report_keeps_head(self):
        self.started("T-002", owns=("tests/grp/**", "docs/qa/grp.md"), role="tester")
        self.commit("tests/grp/test_a.py", "t\n", "[T-002] 묶음 테스트")
        code_sha = self.head()
        (self.proj / "docs/qa").mkdir(parents=True)
        (self.proj / "docs/qa/grp.md").write_text("초안\n")
        code, out = self.run_test("T-002", "--full")
        self.assertEqual((code, out["head"], out["command"]), (0, code_sha, "fake-test --all"), out)
        self.assertTrue(out["log"].startswith(".herdr-team/state/tests/logs/T-002-r1-full-"))
        self.commit("docs/qa/grp.md", "QA\n", "[T-002] QA 보고서")
        code, out = self.run_test("T-002")
        self.assertEqual((code, out["head"], out["files"]), (0, code_sha, ["tests/grp/test_a.py"]), out)

    def test_command_substitution_in_file_name_is_not_run(self):
        self.commit("src/$(touch INJECTED).py", "a\n", "[T-001] 이름에 명령 치환")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"]), (0, "passed"), out)
        self.assertEqual(self.gate_calls()[-1]["args"], ["src/$(touch INJECTED).py"])
        self.assertFalse((self.proj / "INJECTED").exists())
        self.assertEqual(out["command"], "fake-test 'src/$(touch INJECTED).py'")

    def test_final_full_records_the_head_it_started_on(self):
        self.commit("docs/planning/tasks.toml", '[test]\nquick = "fake-test {files}"\n'
                    'full = "git commit -q --allow-empty -m moved"\n', "plan: full 이 커밋한다")
        self.approve_gate()
        start = self.head()
        code, out = self.run_test("--full")
        self.assertEqual((code, out["status"], out["head"], out["head_moved"]), (0, "passed", start, self.head()), out)
        self.assertNotEqual(start, self.head())
        self.assertEqual(json.loads((self.state_dir / "tests" / "final.json").read_text())["full"]["head"], start)

    def test_final_full(self):
        self.gate_modes("fail")
        code, out = self.run_test("--full")
        self.assertEqual((code, out["task"], out["kind"], out["status"], out["head"]),
                         (1, None, "full", "failed", self.head()), out)
        saved = json.loads((self.state_dir / "tests" / "final.json").read_text())
        self.assertEqual((saved["full"]["head"], saved["full"]["status"]), (self.head(), "failed"))
        self.assertIsNone(saved["full"]["head_moved"])
        self.assertTrue(out["log"].startswith(".herdr-team/state/tests/logs/final-full-"))

    def test_test_command_env_drops_role_variables(self):
        self.commit("src/a.py", "a\n", "[T-001] a")
        code, out = self.hteam("test", "T-001")  # 코디네이터 환경(HTEAM_ROLE·HTEAM_LAUNCH·HC_TERMINAL_ID)
        self.assertEqual(code, 0, out)
        call = self.gate_calls()[-1]
        self.assertEqual(call["env"], {"HTEAM_ROLE": False, "HTEAM_LAUNCH": False, "HC_TERMINAL_ID": False})
        self.assertEqual(Path(call["cwd"]).resolve(), self.proj.resolve())

    def test_dirty_check_leaves_the_index_alone(self):
        self.commit("src/a.py", "a\n", "[T-001] a")
        os.utime(self.proj / "src/a.py", (1_000_000_000, 1_000_000_000))  # 내용은 그대로, 상태 정보만 바뀐다
        index = self.proj / ".git" / "index"
        before = (index.stat().st_ino, index.stat().st_mtime_ns)
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertEqual(testgate.dirty_files(self.p, ["src/**"]), [])
        after = (index.stat().st_ino, index.stat().st_mtime_ns)
        self.assertEqual(before, after)

    def test_git_status_runs_without_optional_locks(self):
        self.commit("src/a.py", "a\n", "[T-001] a")
        seen, real = [], subprocess.run

        def spy(argv, **kw):
            if "status" in argv:
                seen.append((kw.get("env") or {}).get("GIT_OPTIONAL_LOCKS"))
            return real(argv, **kw)
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch("hteam.gitio.subprocess.run", spy):
            out = testgate.run_task(self.p, "T-001", "quick")
        self.assertEqual(out["status"], "passed")
        self.assertTrue(seen and set(seen) == {"0"}, seen)


class SubdirGateTest(GateCase):
    def setUp(self):
        TeamCase.setUp(self)
        self.proj = self.proj / "sub"
        self.proj.mkdir()
        self.init_project()
        self.p = Project(self.proj)

    def test_reads_head_table_of_subdir_project(self):
        self.use_gate()
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["status"], out["files"]), (0, "passed", ["src/a.py"]), out)


class ExecuteTest(GateCase):
    def run_execute(self, command: str, limit: float):
        with mock.patch.dict(os.environ, self.env, clear=True):
            return testgate.execute(self.p, command, self.state_dir / "tests" / "logs" / "x.log", limit, (0,))

    def test_timeout_ends_the_group(self):
        start = time.monotonic()
        out = self.run_execute("sleep 30 & sleep 30", 0.5)
        self.assertEqual((out["status"], out["exit"]), ("timeout", None))
        self.assertLess(time.monotonic() - start, 10)

    def test_file_names_are_arguments_not_shell_text(self):
        # 검사를 거치지 않는 경로: 따옴표·백틱 문맥의 {files} 라도 파일 이름은 셸 문법으로 다시 읽히지 않는다
        self.env["FAKE_DIR"] = str(self.tmp / "fake")
        files = ["src/$(touch INJECTED).py", "src/`touch INJECTED2`.py", "src/a[$(touch INJECTED3)].py"]
        for i, quick in enumerate(('fake-test "{files}"', 'out=`fake-test {files}`; true', "fake-test {files}")):
            cfg = testgate.GateConfig(quick, "fake-test --all", 30, (0,), False)
            with mock.patch.dict(os.environ, self.env, clear=True):
                out = testgate.run_quick(self.p, cfg, files, f"x{i}")
            self.assertEqual(out["status"], "passed", out)
            for name in ("INJECTED", "INJECTED2", "INJECTED3"):
                self.assertFalse((self.proj / name).exists(), (quick, name))
        self.assertEqual(self.gate_calls()[-1]["args"], files)
        self.assertEqual(out["command"], "fake-test 'src/$(touch INJECTED).py' 'src/`touch INJECTED2`.py' "
                         "'src/a[$(touch INJECTED3)].py'")
        shown = (self.proj / out["log"]).read_text().splitlines()[0]
        self.assertEqual(shown, "$ " + out["command"])

    def test_term_ignoring_child_is_killed(self):
        pid_file = self.tmp / "child.pid"
        out = self.run_execute(f"sh -c 'trap \"\" TERM; echo $$ > {pid_file}; sleep 30' & wait", 3.0)  # trap 이 걸릴 시간을 넉넉히
        self.assertEqual(out["status"], "timeout")
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            self.fail(f"SIGTERM 을 무시한 자식 {pid} 가 남았다")

    def test_exclusive_lock(self):
        exclusive = testgate.parse_config({"quick": "true {files}", "full": "true", "exclusive": True})
        shared = testgate.parse_config({"quick": "true {files}", "full": "true"})
        lock = self.state_dir / "tests" / ".lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a") as fh, mock.patch.dict(os.environ, self.env, clear=True):
            fcntl.flock(fh, fcntl.LOCK_EX)
            with self.assertRaises(HteamError) as cm:
                testgate.attempt(self.p, exclusive, "true", "lock", lock_wait=0.3)
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("test_lock_timeout", 4))
            self.assertIn("exclusive", cm.exception.message)
            self.assertEqual(testgate.attempt(self.p, shared, "true", "free")["status"], "passed")
            fcntl.flock(fh, fcntl.LOCK_UN)
            self.assertEqual(testgate.attempt(self.p, exclusive, "true", "after", lock_wait=0.3)["status"], "passed")

    def test_sigterm_to_hteam_ends_the_group_without_a_record(self):
        self.use_gate(quick='echo $$ > "$FAKE_DIR/pid"; sleep 30; true {files}')
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        (self.tmp / "fake").mkdir(exist_ok=True)
        proc = self.hteam_bg("test", "T-001", as_=None)
        pid_file = self.tmp / "fake" / "pid"
        deadline = time.monotonic() + 20
        while not (pid_file.exists() and pid_file.read_text().strip()):
            self.assertLess(time.monotonic(), deadline, "테스트 명령이 시작하지 않았다")
            time.sleep(0.05)
        proc.send_signal(signal.SIGTERM)
        code, _ = self.finish(proc, timeout=30)
        self.assertEqual(code, 143)
        pgid = int(pid_file.read_text())
        with self.assertRaises((ProcessLookupError, PermissionError)):
            os.killpg(pgid, 0)
        self.assertEqual(self.record(), {})


if __name__ == "__main__":
    unittest.main()
