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


class SevenKeysTest(unittest.TestCase):
    """[test] 의 tester_paths·full_if(설계 5.7, 7단계): 형식, 기본값, 식별값에 들지 않음, 확정 질문 절."""

    BASE = {"quick": "a {files}", "full": "b"}
    PATHS_RULE = "[test]: tester_paths 는 {key} 를 한 번씩 담은 경로 목록이다"
    GLOB_RULE = "[test]: full_if 는 glob 목록이다"

    def test_parse_and_defaults(self):
        cfg = testgate.parse_config(dict(self.BASE))
        self.assertEqual((cfg.tester_paths, cfg.full_if), (None, ()))
        cfg = testgate.parse_config({**self.BASE, "tester_paths": ["tests/{key}/**", "e2e/{key}/**"],
                                     "full_if": ["db/migrations/**", "package.json"]})
        self.assertEqual((cfg.tester_paths, cfg.full_if),
                         (("tests/{key}/**", "e2e/{key}/**"), ("db/migrations/**", "package.json")))
        self.assertEqual(testgate.parse_config({**self.BASE, "full_if": []}).full_if, ())
        # 다섯 인자로 만드는 GateConfig 는 그대로 된다(새 필드는 뒤에 기본값으로 붙는다)
        old = testgate.GateConfig("a {files}", "b", 30, (0,), False)
        self.assertEqual((old.tester_paths, old.full_if), (None, ()))

    def test_problems(self):
        for bad in ("tests/{key}/**", [], ["tests/**"], ["tests/{key}/{key}/**"], ["tests/{key}/**", 3], [" "]):
            with self.subTest(tester_paths=bad):
                self.assertEqual(testgate.config_problems({**self.BASE, "tester_paths": bad}), [self.PATHS_RULE])
        self.assertEqual(testgate.config_problems({**self.BASE, "tester_paths": ["tests/{key}/[a]/**", "/e2e/{key}/**"]}),
                         ["[test]: tester_paths 'tests/{key}/[a]/**': [] 를 쓸 수 없다",
                          "[test]: tester_paths '/e2e/{key}/**': / 로 시작하거나 끝날 수 없다"])
        for bad in ("db/**", ["db/**", 3], [""], [" "]):
            with self.subTest(full_if=bad):
                self.assertEqual(testgate.config_problems({**self.BASE, "full_if": bad}), [self.GLOB_RULE])
        self.assertEqual(testgate.config_problems({**self.BASE, "full_if": ["db/[x]", "src//a"]}),
                         ["[test]: full_if 'db/[x]': [] 를 쓸 수 없다",
                          "[test]: full_if 'src//a': 빈 마디나 . · .. 마디를 쓸 수 없다"])
        good = {**self.BASE, "tester_paths": ["tests/{key}/**", "e2e/x{key}/**"],
                "full_if": ["db/migrations/**", "package.json", "**/*.sql"]}
        self.assertEqual(testgate.config_problems(good), [])
        # 다른 문제와 함께 모으고 새 키 문제는 뒤에 온다
        self.assertEqual(testgate.config_problems({"quick": "a", "full": "b", "tester_paths": "x", "full_if": 1}),
                         ["[test]: quick 은 {files} 를 정확히 한 번 담는다", self.PATHS_RULE, self.GLOB_RULE])

    def test_digest_ignores_new_keys(self):
        plain = testgate.parse_config(dict(self.BASE))
        more = testgate.parse_config({**self.BASE, "tester_paths": ["tests/{key}/**"], "full_if": ["db/**"]})
        self.assertEqual(testgate.digest(more), testgate.digest(plain))
        self.assertEqual(testgate.normalized(more), testgate.normalized(plain))

    def test_confirm_section_shows_new_keys_when_present(self):
        cfg = testgate.parse_config({**self.BASE, "tester_paths": ["tests/{key}/**", "e2e/{key}/**"],
                                     "full_if": ["db/**"]})
        self.assertEqual(testgate.confirm_section(cfg),
                         "## 테스트 명령\n" + testgate.CONFIRM_LINE + "\n```toml\nquick = \"a {files}\"\nfull = \"b\"\n"
                         "timeout_min = 30\nok_exit = [0]\nexclusive = false\n"
                         "tester_paths = [\"tests/{key}/**\", \"e2e/{key}/**\"]\nfull_if = [\"db/**\"]\n```")
        only = testgate.parse_config({**self.BASE, "full_if": ["db/**"]})
        self.assertTrue(testgate.confirm_section(only).endswith("exclusive = false\nfull_if = [\"db/**\"]\n```"))
        self.assertTrue(testgate.confirm_section(testgate.parse_config(dict(self.BASE))).endswith(
            "exclusive = false\n```"))


class SevenKeysApprovalTest(GateCase):
    """tester_paths·full_if 를 더해도 사용자 확정은 그대로 맞는다(설계 5.7 "이미 한 확정이 그대로 맞는다")."""

    def test_adding_new_keys_keeps_the_confirmation(self):
        self.use_gate()
        self.commit("docs/planning/tasks.toml", '[test]\nquick = "fake-test {files}"\nfull = "fake-test --all"\n'
                    'tester_paths = ["tests/{key}/**"]\nfull_if = ["db/**"]\n', "plan: [test] 7단계 키")
        with mock.patch.dict(os.environ, self.env, clear=True):
            gate = testgate.gate_state(self.p)
            cfg = testgate.load_config(self.p)
        self.assertEqual(gate["state"], "approved", gate)
        self.assertEqual((cfg.tester_paths, cfg.full_if), (("tests/{key}/**",), ("db/**",)))


from tests.helpers import BASE_CONFIG, WS_CONFIG
from hteam import config  # noqa: E402

# [redmine] 표(설계 4.1). 이 태스크의 시험은 key_env 만 쓴다(주소는 쓰지 않는 닫힌 포트)
REDMINE_TABLE = """
[redmine]
url = "http://127.0.0.1:9"
key_env = "REDMINE_API_KEY"
status = { start = 2, done = 3, changes = 4, closed = 5 }
"""
# full 이 받은 두 변수를 FAKE_DIR/env.txt 에 남긴다(없으면 "없음")
ENV_FULL = 'mkdir -p "$FAKE_DIR" && printf "%s|%s" "${REDMINE_API_KEY-없음}" "${HT_KEEP-없음}" > "$FAKE_DIR/env.txt"'


class FullIfTest(GateCase):
    """`[test] full_if`(설계 5.7 7단계): developer 가 바꾼 경로가 맞으면 `hteam test T` 가 quick 대신 full 을 한 번 돈다."""

    def setUp(self):
        super().setUp()
        self.use_gate(extra='full_if = ["src/db/**", "migrations/*.sql"]\n')

    def test_quick_until_a_full_if_path_changes(self):
        self.started()
        self.commit("src/app.py", "a\n", "[T-001] app")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["status"], out.get("reason")), (0, "quick", "passed", None), out)
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        code_sha = self.head()
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["status"], out["reason"], out["matched"]),
                         (0, "full", "passed", "full_if", ["src/db/schema.py"]), out)
        self.assertEqual((out["command"], out["head"], out["round"]), ("fake-test --all", code_sha, 1), out)
        self.assertEqual([c["args"] for c in self.gate_calls()], [["src/app.py"], ["--all"]])
        self.assertTrue(out["log"].startswith(".herdr-team/state/tests/logs/T-001-r1-full-"), out["log"])
        saved = self.record()
        self.assertEqual({k: saved["full"][k] for k in ("round", "head", "status", "reason", "matched")},
                         {"round": 1, "head": code_sha, "status": "passed", "reason": "full_if",
                          "matched": ["src/db/schema.py"]})
        self.assertEqual(saved["quick"]["status"], "passed")  # 앞 quick 기록은 그대로 남는다

    def test_deleted_and_moved_paths_count(self):
        # 지운 파일·옮긴 파일의 옛 경로도 바꾼 경로다(quick 파일은 지금 있는 파일만이라 판정에 쓰지 않는다, Codex 설계 리뷰 r1)
        self.commit("src/db/a.py", "a\n", "chore: a")
        self.commit("src/db/b.py", "b\n", "chore: b")
        self.started()
        self.git("rm", "-q", "src/db/a.py")
        self.git("mv", "src/db/b.py", "src/b.py")
        self.git("commit", "-q", "-m", "[T-001] 지우고 옮김")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["matched"]), (0, "full", ["src/db/a.py", "src/db/b.py"]), out)
        self.commit("migrations/001.sql", "create\n", "[T-001] 마이그레이션")
        code, out = self.run_test("T-001")
        self.assertEqual(out["matched"], ["migrations/001.sql", "src/db/a.py", "src/db/b.py"], out)

    def test_report_paths_do_not_count(self):
        self.use_gate(extra='full_if = ["docs/**"]\n')
        self.started()
        self.commit("src/app.py", "a\n", "[T-001] app")
        self.commit("docs/tasks/T-001/report.md", "## r1\n", "[T-001] 보고서")
        self.commit("docs/qa/x.md", "qa\n", "[T-001] QA")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out.get("matched")), (0, "quick", None), out)

    def test_full_if_refuses_uncommitted_owned_like_quick(self):
        self.started()
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        (self.proj / "src/db/schema.py").write_text("고침\n")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["error"]["code"]), (2, "uncommitted_owned"), out)
        self.assertIn("src/db/schema.py", out["error"]["message"])
        self.assertEqual((self.gate_calls(), self.record()), ([], {}))

    def test_failed_full_if_runs_once_and_exits_1(self):
        self.started()
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        self.gate_modes("fail", "pass")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["status"], out["exit"]), (1, "full", "failed", 1), out)
        self.assertEqual(len(self.gate_calls()), 1)  # full 은 한 번만 돈다(quick 처럼 다시 돌리지 않는다)
        self.assertEqual(self.record()["full"]["status"], "failed")

    def test_only_developer_and_only_without_full_flag(self):
        self.use_gate(extra='full_if = ["src/**", "tests/**"]\n')
        self.started("T-002", owns=("tests/grp/**", "docs/qa/grp.md"), role="tester")
        self.commit("tests/grp/test_a.py", "t\n", "[T-002] 묶음 테스트")
        code, out = self.run_test("T-002")
        self.assertEqual((code, out["kind"], out.get("reason")), (0, "quick", None), out)
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        code, out = self.run_test("T-001", "--full")  # 직접 돌린 full 은 지금 그대로(사전 거부 없음, reason 없음)
        self.assertEqual((code, out["kind"], out.get("reason"), out.get("matched")), (0, "full", None, None), out)
        self.assertNotIn("reason", self.record("T-001")["full"])


class FullIfOffTest(GateCase):
    """회귀: [test] 에 full_if 가 없으면 developer 의 `hteam test T` 는 바꾼 경로와 관계없이 지금처럼 quick 이다."""

    def setUp(self):
        super().setUp()
        self.use_gate()

    def test_without_full_if_nothing_changes(self):
        self.started()
        self.commit("src/db/schema.py", "s\n", "[T-001] 스키마")
        code, out = self.run_test("T-001")
        self.assertEqual((code, out["kind"], out["files"]), (0, "quick", ["src/db/schema.py"]), out)
        self.assertNotIn("reason", out)
        self.assertNotIn("full", self.record())


class _KeyEnvCase(GateCase):
    redmine = ""

    def setUp(self):
        TeamCase.setUp(self)
        self.init_project(BASE_CONFIG + self.redmine)
        self.p = Project(self.proj)
        self.use_gate(full=ENV_FULL)

    def full_saw(self) -> str:
        code, out = self.run_test("--full", env={"REDMINE_API_KEY": "k-secret", "HT_KEEP": "keep"})
        self.assertEqual((code, out["status"]), (0, "passed"), out)
        return (self.tmp / "fake" / "env.txt").read_text(encoding="utf-8")


class KeyEnvTest(_KeyEnvCase):
    """테스트 명령 환경에서 [redmine] key_env 를 뺀다(설계 5.7 끝, 8.12). 다른 변수는 그대로 넘어간다."""
    redmine = REDMINE_TABLE

    def test_test_command_does_not_get_the_redmine_key(self):
        self.assertEqual(self.full_saw(), "없음|keep")


class KeyEnvSharedTest(_KeyEnvCase):
    """회귀: [redmine] 이 없으면 그 이름의 변수도 지금처럼 넘어간다."""

    def test_without_redmine_the_variable_passes(self):
        self.assertEqual(self.full_saw(), "k-secret|keep")


class KeyEnvBrokenConfigTest(_KeyEnvCase):
    """설정이 깨져도(여기서는 [redmine] 의 url) hteam test 는 돌고 key_env 이름은 뺀다(Task 2 Rules 11, Codex 계획 리뷰 r1)."""
    redmine = REDMINE_TABLE.replace('url = "http://127.0.0.1:9"', 'url = "ftp://127.0.0.1:9"')

    def test_broken_config_still_drops_the_key(self):
        with self.assertRaises(HteamError):
            config.load(self.p)  # 전체 검사는 실패한다
        self.assertEqual(self.full_saw(), "없음|keep")


class BrokenConfigGateTest(GateCase):
    """회귀: hteam test 는 config.toml 을 검사하지 않는다(설계 4.2·5.7 의 5단계 규칙, Codex 계획 리뷰 r1). 새 표가 없는
    프로젝트에서 다른 키가 틀렸거나 TOML 이 깨져도 확정된 quick·full 이 지금처럼 돈다(bad_config 가 아니다)."""

    def check(self, text: str) -> None:
        self.use_gate()
        self.started()
        self.commit("src/a.py", "a\n", "[T-001] a")
        (self.team / "config.toml").write_text(text, encoding="utf-8")
        for args in (("T-001",), ("--full",)):
            with self.subTest(args=args):
                code, out = self.run_test(*args)
                self.assertEqual((code, out.get("status")), (0, "passed"), out)

    def test_other_key_broken(self):
        self.check(BASE_CONFIG.replace("max_parallel = 4", "max_parallel = 0"))

    def test_toml_broken(self):
        self.check("max_parallel = [\n")


class KeyEnvSetupTest(TeamCase):
    """작업 공간 setup 도 같은 환경 규칙이다(설계 5.10.3 의 4, 8.12): key_env 는 빠지고 슬롯 번호는 들어간다."""

    def test_setup_does_not_get_the_redmine_key(self):
        setup = ('printf "%s|%s" "${REDMINE_API_KEY-없음}" "${HTEAM_SLOT-없음}" '
                 '> "$HTEAM_MAIN_ROOT/.herdr-team/state/setup-env.txt"')
        self.init_project(WS_CONFIG.replace("slots = 2\n", f"slots = 2\nsetup = {json.dumps(setup)}\n") + REDMINE_TABLE)
        self.setup_run()
        self.write_spec("T-001")
        env = {"REDMINE_API_KEY": "k-secret"}
        code, out = self.hteam("start", "T-001", env=env)
        self.assertEqual((code, out.get("status"), out.get("reason")), (0, "waiting", "slot_setup"), out)
        code, out = self.hteam("slot", "prepare", "T-001", env=env)
        self.assertEqual(code, 0, out)
        self.assertEqual((self.state_dir / "setup-env.txt").read_text(encoding="utf-8"), "없음|1")
