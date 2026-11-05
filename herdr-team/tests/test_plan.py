"""owns glob 겹침(설계 5.2), plan check 규칙, plan apply·--append."""
import fcntl
import json
import os
import subprocess
import unittest
from unittest import mock

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import config, gitio, globs, plan
from hteam.errors import HteamError
from hteam.globs import any_overlap, matches, overlaps, within
from hteam.paths import Project

APPROVAL = BASE_CONFIG.replace("user_approval_roles = []", 'user_approval_roles = ["designer"]') + """
[roles.director]
title = "디자인 디렉터"
owns = ["docs/design/**"]

[roles.designer]
title = "디자인"
owns = ["docs/design/screens/**", "assets/**"]
"""


def task(key, role="developer", owns=("src/**",), deps=(), **extra):
    t = {"key": key, "role": role, "title": f"{key} 제목", "owns": list(owns), "depends_on": list(deps),
         "target": "대상", "change": "바꿀 것", "constraints": "제약", "acceptance": ["확인 1"]}
    t.update(extra)
    return t


def toml(tasks):
    out = []
    for t in tasks:
        out.append("[[task]]")
        for k, v in t.items():
            out.append(f"{k} = {json.dumps(v, ensure_ascii=False)}")
        out.append("")
    return "\n".join(out)


class GlobTest(unittest.TestCase):
    def test_matches(self):
        self.assertTrue(matches("src/a/b.py", "src/**"))
        self.assertTrue(matches("src/a.py", "src/*.py"))
        self.assertFalse(matches("src/a/b.py", "src/*.py"))
        self.assertTrue(matches("a/x/b", "a/**/b"))
        self.assertTrue(matches("a/b", "a/**/b"))
        self.assertFalse(matches("src/ab", "src/?"))

    def test_conservative_overlap(self):
        self.assertTrue(overlaps("src/**", "src/auth/**"))
        self.assertTrue(overlaps("src/a*", "src/ab/**"))  # 접두사 src/a 와 src/ab/
        self.assertFalse(overlaps("src/**", "tests/**"))
        self.assertTrue(overlaps("docs/design/**", "docs/design/screens/**"))
        self.assertFalse(overlaps("docs/a.md", "docs/b.md"))
        self.assertTrue(overlaps("docs/a.md", "docs/*.md"))
        self.assertFalse(overlaps("docs/a.md", "src/**"))
        self.assertEqual(any_overlap(["src/**", "x"], ["src/a/**"]), [("src/**", "src/a/**")])

    def test_owns_problem(self):
        for good in ("src/**", "src/*.py", "a/**/b", "src/?.py", "docs/a.md", "**"):
            self.assertIsNone(globs.owns_problem(good), good)
        # git `:(glob)` 와 matches() 가 다르게 읽거나 front matter 에서 갈라지는 owns
        for bad in ("src/[ab].py", "src/{a,b}/**", "src/a,b", "src/", "/src/**", "src//a/**", "src/../x/**",
                    "./src/**", "src/./a", "src/a**", "src/a\\*", "src/a\nb"):
            self.assertIsNotNone(globs.owns_problem(bad), bad)

    def test_literal_pattern_covers_its_directory(self):
        # git 의 `:(glob)src/a` 는 src/a/x.py 도 덮는다. 와일드카드 없는 owns 는 그 아래도 owns 다.
        self.assertTrue(matches("src/a/x.py", "src/a"))
        self.assertFalse(matches("src/ab", "src/a"))
        self.assertTrue(overlaps("src/a", "src/a/**"))
        self.assertTrue(overlaps("src/a", "src/a/b.py"))
        self.assertTrue(overlaps("src", "src/*.py"))
        self.assertTrue(overlaps("src/foo", "src/*/x.py"))
        self.assertFalse(overlaps("src/x.py", "src/*.txt"))
        self.assertFalse(overlaps("src/a", "src/ab/**"))

    def test_within_refuses_unnormalized_owns(self):
        for inner in ("src/", "src/../x/**", "src//a/**", "src/[ab]/**"):
            self.assertFalse(within(inner, "src/**"), inner)


class PlanCheckTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project(config=APPROVAL, commit=False)
        self.cfg = config.load(Project(self.proj))

    def errors(self, tasks):
        return plan.validate(self.cfg, tasks)[0]

    def test_valid_graph_and_groups(self):
        tasks = [task("plan-a", "planner", ["docs/planning/**"]), task("dev", deps=["plan-a"]),
                 task("qa", "tester", ["tests/**"], deps=["plan-a"]), task("dev2", deps=["dev"])]
        errors, groups = plan.validate(self.cfg, tasks)
        self.assertEqual(errors, [])
        self.assertEqual(groups, [["plan-a"], ["dev", "qa"], ["dev2"]])

    def test_field_rules(self):
        bad = task("Bad_Key")
        del bad["target"]
        errs = self.errors([bad, task("dup"), task("dup", owns=["tests/**"]), task("x", role="nope", owns=["a/**"]),
                            task("y", owns=[], change="", acceptance=[]), task("z", owns=["b/**"], change="a\n## 절")])
        joined = "\n".join(errs)
        for needle in ("Bad_Key: target 가 없다", "Bad_Key: key 는", "dup: key 가 중복", "x: 직무 'nope'",
                       "y: owns 는", "y: acceptance 는", "y: change 는", "z: 텍스트 필드에 '## '"):
            self.assertIn(needle, joined)

    def test_values_survive_spec_roundtrip(self):
        # 검사한 값과 사양으로 쓴 뒤 다시 읽은 값이 같아야 한다
        cases = {"t2": task("t2", title="첫 줄\n둘째 줄"),
                 "inj": task("inj", title="제목\nrole: tester"),
                 "fence": task("fence", change="```py\n열고 닫지 않았다"),
                 "brace": task("brace", owns=["src/{a,b}/**"]),
                 "comma": task("comma", owns=["src/foo/**, tests/**"])}
        for key, t in cases.items():
            errs = self.errors([t])
            self.assertTrue(errs and all(e.startswith(f"{key}: ") for e in errs), (key, errs))
        self.assertIn("## Constraints 절이 없다", "\n".join(self.errors([cases["fence"]])))

    def test_role_type_unknown_fields_duplicate_deps(self):
        errs = "\n".join(self.errors([task("a", role=["developer"]), task("b", owns=["src/b/**"], depends=["a"]),
                                      task("c", owns=["src/c/**"], deps=["a", "a"])]))
        for needle in ("a: role 은 문자열이다", "b: 모르는 필드 depends", "c: depends_on 에 같은 key 가 두 번"):
            self.assertIn(needle, errs)

    def test_owns_character_rules(self):
        for owns in ("src/[ab]/**", "src/../x/**", "src/", "src//a/**"):
            errs = self.errors([task("a", owns=[owns])])
            self.assertTrue(any(e.startswith(f"a: owns {owns!r}") for e in errs), (owns, errs))

    def test_unknown_dep_and_cycle(self):
        self.assertEqual(self.errors([task("a", deps=["ghost"])]), ["a: 모르는 의존 'ghost'"])
        errs = self.errors([task("a", deps=["b"]), task("b", owns=["tests/**"], role="tester", deps=["a"])])
        self.assertEqual(len(errs), 1)
        self.assertTrue(errs[0].startswith("순환 의존: a -> b -> a"), errs)

    def test_owns_overlap_only_between_unrelated(self):
        errs = self.errors([task("a"), task("b", owns=["src/auth/**"])])
        self.assertEqual(len(errs), 1)
        self.assertIn("a 와 b 의 owns 가 겹친다", errs[0])
        self.assertEqual(self.errors([task("a"), task("b", owns=["src/auth/**"], deps=["a"])]), [])

    def test_approval_chain_with_overlap_is_refused(self):
        tasks = [task("dir", "director", ["docs/design/system/**"]),
                 task("s1", "designer", ["docs/design/screens/a/**"], deps=["dir"]),
                 task("s2", "designer", ["docs/design/screens/**"], deps=["s1"])]
        errs = self.errors(tasks)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("승인 직무 태스크 s1·s2", errs[0])

    def test_director_rule(self):
        screens = [task("s1", "designer", ["docs/design/screens/a/**"]),
                   task("icons", "designer", ["assets/icons/**"])]
        errs = self.errors(screens)
        self.assertEqual(errs, ["designer 태스크가 있으면 director 태스크가 정확히 하나여야 한다(지금 0개)"])
        tasks = [task("dir", "director", ["docs/design/system/**"])] + screens
        errs = self.errors(tasks)
        self.assertEqual(errs, ["s1: 에셋 전용이 아닌 designer 태스크는 director 태스크 dir 에 직간접으로 의존해야 한다"])
        tasks[1]["depends_on"] = ["dir"]
        self.assertEqual(self.errors(tasks), [])

    def test_plan_check_command(self):
        self.init_project(config=APPROVAL)
        (self.proj / "docs/planning").mkdir(parents=True)
        (self.proj / "docs/planning/tasks.toml").write_text(toml([task("a"), task("b", owns=["src/x/**"])]))
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertEqual(len(out["errors"]), 1)
        alt = self.proj / "alt.toml"
        alt.write_text(toml([task("a")]))
        code, out = self.hteam("plan", "check", "--file", "alt.toml", as_=None)
        self.assertEqual((code, out["tasks"], out["groups"]), (0, 1, [["a"]]), out)
        alt.write_text(toml([task("a", role=["developer"])]))
        code, out = self.hteam("plan", "check", "--file", "alt.toml", as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)


class PlanApplyTest(TeamCase):
    def setUp(self):
        super().setUp()
        self.init_project()
        self.setup_run()

    def write_plan(self, tasks):
        path = self.proj / "docs/planning/tasks.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(toml(tasks), encoding="utf-8")

    def test_apply_creates_specs_commit_and_states(self):
        self.write_plan([task("plan-a", "planner", ["docs/planning/**"]), task("dev", deps=["plan-a"])])
        code, out = self.hteam("plan", "apply")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["applied"], [{"key": "plan-a", "id": "T-001"}, {"key": "dev", "id": "T-002"}])
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "[plan] apply: 2 tasks")
        self.assertEqual(sorted(self.git("show", "--name-only", "--format=", "HEAD").split()),
                         [".herdr-team/tasks/T-001.md", ".herdr-team/tasks/T-002.md"])
        text = (self.proj / ".herdr-team/tasks/T-002.md").read_text()
        for needle in ("depends_on: T-001", "plan_key: dev", "owns: src/**", "## Acceptance\n- 확인 1"):
            self.assertIn(needle, text)
        saved = json.loads((self.state_dir / "plan.json").read_text())
        self.assertEqual(saved["tasks"]["dev"]["id"], "T-002")
        self.assertEqual(len(saved["tasks"]["dev"]["digest"]), 40)
        self.assertEqual(self.task_state("T-002")["status"], "pending")
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["error"]["code"]), (3, "plan_applied"))

    def test_append_adds_new_keys_and_refuses_changes(self):
        base = [task("a"), task("b", "tester", ["tests/**"])]
        self.write_plan(base)
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        self.write_plan(base + [task("c", owns=["src/c/**"], deps=["a"])])
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["applied"]), (0, [{"key": "c", "id": "T-003"}]), out)
        self.assertIn("depends_on: T-001", (self.proj / ".herdr-team/tasks/T-003.md").read_text())
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["applied"], out["commit"]), (0, [], None))
        changed = [task("a", title="바뀜"), base[1], task("c", owns=["src/c/**"], deps=["a"])]
        self.write_plan(changed)
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_changed"))
        self.write_plan([base[1], task("c", owns=["src/c/**"])])
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_changed"))

    def test_missing_plan_json_with_planned_tasks(self):
        self.write_plan([task("a")])
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        (self.state_dir / "plan.json").unlink()
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_state_missing"))

    def test_invalid_plan_is_not_applied(self):
        self.write_plan([task("a"), task("b")])
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"))
        self.assertFalse((self.state_dir / "plan.json").exists())
        code, out = self.hteam("plan", "apply", as_="main")
        self.assertEqual(code, 5)

    def fail_commits(self):
        """pre-commit 훅으로 커밋을 막는다. 돌려준 훅 파일을 지우면 다시 커밋된다."""
        hooks = self.tmp / "hooks"
        hooks.mkdir(exist_ok=True)
        hook = hooks / "pre-commit"
        hook.write_text("#!/bin/sh\necho 막힘 >&2\nexit 1\n")
        hook.chmod(0o755)
        self.git("config", "core.hooksPath", str(hooks))
        return hook

    def spec_files(self):
        return sorted(f.name for f in (self.proj / ".herdr-team/tasks").glob("T-*.md"))

    def plan_commits(self):
        return [s for s in self.git("log", "--format=%s").splitlines() if s.startswith("[plan]")]

    def test_commit_failure_rolls_back_and_retry_succeeds(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        hook = self.fail_commits()
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["error"]["code"]), (1, "git_failed"), out)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all", "--", ".herdr-team"), "")
        self.assertEqual(self.spec_files(), [])
        self.assertFalse((self.state_dir / "plan.json").exists())
        hook.unlink()
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-001"}, {"key": "b", "id": "T-002"}]), out)
        self.assertEqual(self.plan_commits(), ["[plan] apply: 2 tasks"])

    def test_append_commit_failure_retry_has_no_duplicates(self):
        base = [task("a"), task("b", "tester", ["tests/**"])]
        self.write_plan(base)
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        self.write_plan(base + [task("c", owns=["src/c/**"], deps=["a"])])
        hook = self.fail_commits()
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["error"]["code"]), (1, "git_failed"), out)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all", "--", ".herdr-team"), "")
        hook.unlink()
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["applied"]), (0, [{"key": "c", "id": "T-003"}]), out)
        self.assertEqual(self.spec_files(), ["T-001.md", "T-002.md", "T-003.md"])
        saved = json.loads((self.state_dir / "plan.json").read_text())
        self.assertEqual({k: v["id"] for k, v in saved["tasks"].items()}, {"a": "T-001", "b": "T-002", "c": "T-003"})

    def test_non_json_values_are_refused_before_any_write(self):
        path = self.proj / "docs/planning/tasks.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        head = self.head()
        for extra in ("due = 2026-11-05\n", ""):
            text = toml([task("a")]) + extra
            if not extra:
                text = text.replace('title = "a 제목"', "title = 2026-11-05")
            path.write_text(text, encoding="utf-8")
            code, out = self.hteam("plan", "apply")
            self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
            self.assertEqual((self.head(), self.spec_files()), (head, []))
            self.assertFalse((self.state_dir / "plan.json").exists())

    def test_spec_that_would_not_load_is_not_applied(self):
        self.write_plan([task("a", change="```\n닫지 않은 코드 블록")])
        head = self.head()
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertEqual((self.head(), self.spec_files()), (head, []))

    def test_crash_after_commit_retry_completes(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        code, _ = self.hteam("plan", "apply", env={"HTEAM_TEST_DIE_AT": "plan_after_commit"})
        self.assertEqual(code, 137)
        sha = self.head()
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"], out["commit"]),
                         (0, [{"key": "a", "id": "T-001"}, {"key": "b", "id": "T-002"}], sha), out)
        self.assertEqual(self.plan_commits(), ["[plan] apply: 2 tasks"])
        saved = json.loads((self.state_dir / "plan.json").read_text())
        self.assertNotIn("pending", saved)
        self.assertEqual(self.task_state("T-002")["status"], "pending")

    def test_crash_before_commit_retry_starts_clean(self):
        self.write_plan([task("a")])
        code, _ = self.hteam("plan", "apply", env={"HTEAM_TEST_DIE_AT": "plan_before_commit"})
        self.assertEqual(code, 137)
        self.assertEqual(self.spec_files(), ["T-001.md"])
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-001"}]), out)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all", "--", ".herdr-team"), "")
        self.assertEqual(self.plan_commits(), ["[plan] apply: 1 tasks"])

    def test_uncommitted_planned_spec_is_not_a_plan(self):
        self.write_spec("T-001", front={"plan_key": "old"}, commit=False)
        self.write_plan([task("a")])
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-002"}]), out)

    def test_missing_pending_states_are_created_on_rerun(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        tasks_dir = self.state_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        tasks_dir.chmod(0o555)  # 상태 파일을 만들지 못하게 한다
        try:
            code, out = self.hteam("plan", "apply")
        finally:
            tasks_dir.chmod(0o755)
        self.assertNotEqual(code, 0, out)
        self.assertTrue((self.state_dir / "plan.json").exists())
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["applied"]), (0, []), out)
        self.assertEqual([self.task_state(t)["status"] for t in ("T-001", "T-002")], ["pending", "pending"])

    def test_apply_reads_tasks_once_under_project_lock(self):
        self.write_plan([task("a")])
        p = Project(self.proj)
        p.ensure_state()
        real, seen = plan.read_tasks, []

        def spy(path):
            with open(p.lock, "a+") as fh:  # 다른 열린 파일로 잠금을 잡아 보면 지금 잠겨 있는지 안다
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    seen.append(False)
                except BlockingIOError:
                    seen.append(True)
            return real(path)

        with mock.patch.object(plan, "read_tasks", spy), mock.patch.dict(os.environ, self.env, clear=True):
            out = plan.apply(p, config.load(p), False)
        self.assertEqual((seen, out["applied"]), ([True], [{"key": "a", "id": "T-001"}]))

    def test_order_follows_plan(self):
        self.write_spec("T-001", commit=False)
        self.write_plan([task("z", owns=["src/z/**"]), task("y", owns=["src/y/**"])])
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        from hteam import state
        state.create(Project(self.proj), "T-001", "developer")
        self.assertEqual(plan.order(Project(self.proj)), ["T-002", "T-003", "T-001"])
        self.assertTrue(gitio.is_repo(self.proj))


class OwnsWithinTest(TeamCase):
    def test_within_is_conservative(self):
        from hteam.globs import within
        self.assertTrue(within("src/auth/**", "src/**"))
        self.assertTrue(within("src/*.py", "src/**"))
        self.assertTrue(within("src/a.py", "src/*.py"))
        self.assertTrue(within("src/**", "src/**"))
        self.assertFalse(within("**", "src/**"))
        self.assertFalse(within("srcx/**", "src/**"))
        self.assertFalse(within("src/a*.py", "src/*.py"))  # 판단할 수 없으면 안이 아니다
        self.assertFalse(within("docs/a.md", "src/**"))

    def test_plan_check_refuses_wider_owns(self):
        self.init_project(config=APPROVAL, commit=False)
        cfg = config.load(Project(self.proj))
        errs = plan.validate(cfg, [task("a", owns=["**"])])[0]
        self.assertEqual(errs, ["a: owns 가 직무 developer 의 owns 를 넘거나 판단할 수 없다: **"])


class GitioTest(TeamCase):
    def test_git_errors_are_not_answers(self):
        first = self.head()
        second = self.commit("x.txt", "x\n", "x")
        self.assertTrue(gitio.differs(self.proj, first, second, "x.txt"))
        self.assertFalse(gitio.differs(self.proj, first, second, "README.md"))
        self.assertTrue(gitio.is_ancestor(self.proj, first, second))
        self.assertFalse(gitio.is_ancestor(self.proj, second, first))
        for call in (lambda: gitio.differs(self.proj, first, "no-such-rev", "x.txt"),
                     lambda: gitio.is_ancestor(self.proj, first, "no-such-rev")):
            with self.assertRaises(HteamError) as cm:
                call()
            self.assertEqual((cm.exception.code, cm.exception.exit_code), ("git_failed", 1))

    def test_commit_paths_names_literal_paths(self):
        (self.proj / "a[1].txt").write_text("x\n")
        (self.proj / "a1.txt").write_text("y\n")
        with mock.patch.dict(os.environ, self.env, clear=True):
            sha = gitio.commit_paths(self.proj, ["a[1].txt"], "s")
        self.assertEqual(gitio.commit_files(self.proj, sha), ["a[1].txt"])
        self.assertEqual(gitio.untracked(self.proj), ["a1.txt"])

    def test_git_timeout_is_json_error(self):
        with mock.patch("hteam.gitio.subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 120)):
            with self.assertRaises(HteamError) as cm:
                gitio.head(self.proj)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("git_timeout", 1))


if __name__ == "__main__":
    unittest.main()
