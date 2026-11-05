"""상태 파일(설계 5.3), 사양 검사(5.1), task new."""
import threading
import unittest

from tests.helpers import VALID_BODY, TeamCase
from hteam import config, specs, state
from hteam.errors import HteamError
from hteam.paths import Project


class StateTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project(commit=False)
        self.p = Project(self.proj)

    def test_create_edit_move_history(self):
        st = state.create(self.p, "T-001", "developer")
        self.assertEqual((st["status"], st["round"], st["history"][0]["event"]), ("pending", 0, "create"))
        self.assertEqual(state.create(self.p, "T-001", "tester")["role"], "developer")  # 있으면 그대로
        with state.edit(self.p, "T-001", expect={"pending"}) as st:
            state.move(st, "launch_failed", "start", key="T-001 r1 작업")
        st = state.require(self.p, "T-001")
        self.assertEqual(st["status"], "launch_failed")
        self.assertEqual(st["history"][-1]["from"], "pending")
        self.assertEqual(st["history"][-1]["key"], "T-001 r1 작업")

    def test_expect_checks_previous_state(self):
        state.create(self.p, "T-001", "developer")
        with self.assertRaises(HteamError) as ctx:
            with state.edit(self.p, "T-001", expect={"working"}):
                pass
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_state", 3))
        with state.edit(self.p, "T-001") as st:
            state.move(st, "done", "accept")
        with self.assertRaises(HteamError) as ctx:
            with state.edit(self.p, "T-001", expect={"working"}):
                pass
        self.assertEqual(ctx.exception.code, "task_closed")

    def test_exception_in_block_does_not_write(self):
        state.create(self.p, "T-001", "developer")
        with self.assertRaises(RuntimeError):
            with state.edit(self.p, "T-001") as st:
                st["status"] = "working"
                raise RuntimeError("x")
        self.assertEqual(state.require(self.p, "T-001")["status"], "pending")

    def test_concurrent_edits_do_not_lose_updates(self):
        state.create(self.p, "T-001", "developer")

        def bump():
            for _ in range(20):
                with state.edit(self.p, "T-001") as st:
                    st["round"] += 1

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(state.require(self.p, "T-001")["round"], 80)

    def test_all_states_sorted_and_helpers(self):
        for tid in ("T-010", "T-002", "T-1000"):
            state.create(self.p, tid, "developer")
        self.assertEqual([s["id"] for s in state.all_states(self.p)], ["T-002", "T-010", "T-1000"])
        rd = {"reviews": [{"attempt": 1, "result": "failed"}, {"attempt": 2, "result": None},
                          {"attempt": 3, "result": None, "canceled": True}]}
        self.assertEqual(state.open_attempt(rd)["attempt"], 2)
        self.assertEqual(state.latest_attempt(rd)["attempt"], 2)
        self.assertIsNone(state.open_attempt(None))
        with self.assertRaises(HteamError) as ctx:
            state.require(self.p, "T-999")
        self.assertEqual(ctx.exception.code, "unknown_task")

    def _write_state(self, tid, text):
        self.p.ensure_state()
        self.p.state_path(tid).write_text(text, encoding="utf-8")

    def test_corrupt_state_file_is_its_own_error(self):
        for text in ("{ not json", "[]", "\"x\"", "\xff"):
            self._write_state("T-001", text)
            for fn in (state.load, state.require):
                with self.assertRaises(HteamError) as ctx:
                    fn(self.p, "T-001")
                self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_state_file", 1), text)
        self.assertIsNone(state.load(self.p, "T-002"))  # 없는 파일은 None

    def test_create_refuses_existing_corrupt_file(self):
        self._write_state("T-001", "{ not json")
        with self.assertRaises(HteamError) as ctx:
            state.create(self.p, "T-001", "developer")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(self.p.state_path("T-001").read_text(), "{ not json")

    def test_corrupt_state_number_not_reused(self):
        self._write_state("T-005", "{ not json")
        self._write_state("T-006", "[]")
        self.assertEqual(state.all_states(self.p), [])
        self.assertEqual(specs.next_id(self.p), "T-007")

    def test_all_states_without_id_do_not_crash(self):
        state.create(self.p, "T-001", "developer")
        self._write_state("T-002", "{}")
        self.assertEqual([s["id"] for s in state.all_states(self.p)], ["T-001"])
        self.assertEqual(specs.next_id(self.p), "T-003")

    def test_bad_task_id_rejected(self):
        for bad in ("../run", "T-1", "X-001", "T-001/x"):
            for call in (lambda t: state.load(self.p, t), lambda t: state.require(self.p, t),
                         lambda t: state.create(self.p, t, "developer"),
                         lambda t: state.edit(self.p, t).__enter__()):
                with self.assertRaises(HteamError) as ctx:
                    call(bad)
                self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_task_id", 2), bad)


class SpecTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project(commit=False)
        self.p = Project(self.proj)
        self.cfg = config.load(self.p)

    def test_parse_valid_spec(self):
        self.write_spec("T-003", owns="src/auth/**, src/ui/**", depends="T-001, T-002",
                        front={"worker": "codex", "claude_model": "opus"}, commit=False)
        spec = specs.check(self.p, self.cfg, "T-003")
        self.assertEqual((spec.id, spec.role, spec.title), ("T-003", "developer", "앱 만들기"))
        self.assertEqual(spec.owns, ["src/auth/**", "src/ui/**"])
        self.assertEqual(spec.depends_on, ["T-001", "T-002"])
        self.assertEqual(spec.front["worker"], "codex")
        self.assertEqual(spec.sections["Change"], "hello 를 출력한다.")
        self.assertEqual(specs.owns_of(self.cfg, spec), ["src/auth/**", "src/ui/**"])

    def test_placeholders_and_missing_sections(self):
        body = VALID_BODY.replace("hello 를 출력한다.", "<만들 결과>").replace("## Constraints\n표준 라이브러리만.\n", "")
        self.write_spec("T-001", body=body, commit=False)
        with self.assertRaises(HteamError) as ctx:
            specs.check(self.p, self.cfg, "T-001")
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_spec", 2))
        self.assertEqual(ctx.exception.data["problems"],
                         ["## Change 절이 비었거나 <…> 자리표시뿐이다", "## Constraints 절이 없다"])

    def test_bad_front_matter(self):
        path = self.proj / ".herdr-team" / "tasks" / "T-001.md"
        for text in ("no front", "---\nid: T-001\n", "---\nid: T-001\nrole: developer\n---\n", "---\nbad line\n---\n"):
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(HteamError) as ctx:
                specs.load(self.p, "T-001")
            self.assertEqual(ctx.exception.code, "bad_spec", text)
        self.write_spec("T-002", commit=False)
        path.write_text((self.proj / ".herdr-team/tasks/T-002.md").read_text(), encoding="utf-8")
        with self.assertRaises(HteamError):
            specs.load(self.p, "T-001")  # id 가 파일 이름과 다르다

    def test_unknown_role_and_task(self):
        self.write_spec("T-001", role="nope", commit=False)
        with self.assertRaises(HteamError) as ctx:
            specs.check(self.p, self.cfg, "T-001")
        self.assertEqual(ctx.exception.code, "unknown_role")
        with self.assertRaises(HteamError) as ctx:
            specs.load(self.p, "T-404")
        self.assertEqual(ctx.exception.code, "unknown_task")
        with self.assertRaises(HteamError) as ctx:
            specs.load(self.p, "X-1")
        self.assertEqual(ctx.exception.code, "bad_task_id")

    def test_code_fence_headers_are_not_sections(self):
        body = VALID_BODY.replace("- python3 src/app.py 가 hello 를 출력한다.",
                                  "템플릿:\n```markdown\n## Target\n<x>\n\n## Change\n<y>\n```\n- 통과")
        self.write_spec("T-001", body=body, commit=False)
        spec = specs.check(self.p, self.cfg, "T-001")
        self.assertEqual(spec.sections["Target"], "src/app.py")
        self.assertIn("## Change", spec.sections["Acceptance"])

    def test_markup_only_placeholder_is_empty(self):
        for ph in ("- <완료를 증명할 테스트>", "* **<x>**", "1. <x>", "> <x>", "- _<x>_ -"):
            body = VALID_BODY.replace("- python3 src/app.py 가 hello 를 출력한다.", ph)
            self.write_spec("T-001", body=body, commit=False)
            with self.assertRaises(HteamError, msg=ph) as ctx:
                specs.check(self.p, self.cfg, "T-001")
            self.assertEqual(ctx.exception.data["problems"], ["## Acceptance 절이 비었거나 <…> 자리표시뿐이다"], ph)

    def test_load_unreadable_spec_is_bad_spec(self):
        path = self.proj / ".herdr-team" / "tasks" / "T-001.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"---\xff\xfe\n")
        with self.assertRaises(HteamError) as ctx:
            specs.load(self.p, "T-001")
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_spec", 2))
        path.unlink()
        path.mkdir()
        with self.assertRaises(HteamError) as ctx:
            specs.load(self.p, "T-001")
        self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_spec", 2))
        path.rmdir()
        path.write_text("---\n", encoding="utf-8")
        path.chmod(0)
        try:
            with self.assertRaises(HteamError) as ctx:
                specs.load(self.p, "T-001")
            self.assertEqual((ctx.exception.code, ctx.exception.exit_code), ("bad_spec", 2))
        finally:
            path.chmod(0o644)

    def test_new_rejects_any_line_break_in_title_and_owns(self):
        for sep in ("\r", "\x0b", "\x0c", "\x1c", "\x85", "\u2028", "\n"):
            with self.assertRaises(HteamError, msg=repr(sep)) as ctx:
                specs.new(self.p, self.cfg, "developer", f"a{sep}role: nope")
            self.assertEqual(ctx.exception.exit_code, 2)
            with self.assertRaises(HteamError, msg=repr(sep)) as ctx:
                specs.new(self.p, self.cfg, "developer", "ok", owns=[f"src/**{sep}role: nope"])
            self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(specs.list_ids(self.p), [])


class TaskNewTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()

    def test_task_new_numbers_and_state(self):
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "첫 일")
        self.assertEqual((code, out["id"], out["path"]), (0, "T-001", ".herdr-team/tasks/T-001.md"), out)
        self.write_spec("T-007", commit=False)
        code, out = self.hteam("task", "new", "--role", "tester", "--title", "둘", "--owns", "tests/a/**",
                               "--depends-on", "T-001")
        self.assertEqual((code, out["id"]), (0, "T-008"), out)
        text = (self.proj / ".herdr-team/tasks/T-008.md").read_text()
        self.assertIn("owns: tests/a/**", text)
        self.assertIn("depends_on: T-001", text)
        self.assertEqual(self.task_state("T-008")["status"], "pending")
        p = Project(self.proj)
        self.assertIn("## Target 절이 비었거나 <…> 자리표시뿐이다", specs.problems(specs.load(p, "T-008")))

    def test_task_new_errors(self):
        code, out = self.hteam("task", "new", "--role", "nope", "--title", "x")
        self.assertEqual((code, out["error"]["code"]), (2, "unknown_role"))
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "x", as_="main")
        self.assertEqual((code, out["error"]["code"]), (5, "not_coordinator"))
        (self.proj / ".herdr-team" / "config.toml").write_text("max_parallel = 0\n")
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "x")
        self.assertEqual((code, out["error"]["code"]), (2, "bad_config"))


if __name__ == "__main__":
    unittest.main()
