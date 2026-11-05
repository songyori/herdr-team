"""owns glob 겹침(설계 5.2), plan check 규칙, plan apply·--append."""
import json
import unittest

from tests.helpers import BASE_CONFIG, TeamCase
from hteam import config, gitio, plan
from hteam.globs import any_overlap, matches, overlaps
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


if __name__ == "__main__":
    unittest.main()
