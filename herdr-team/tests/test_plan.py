"""owns glob 겹침(설계 5.2), plan check 규칙, plan apply·--append."""
import errno
import fcntl
import json
import os
import pathlib
import subprocess
import unicodedata
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
    def test_covers_tree_needs_the_whole_subtree(self):
        # 변조 검사가 서브모듈 vendor 의 변경을 빼려면 그 아래 전체를 확실히 덮어야 한다(Codex 계획 r1 P1)
        for patterns in (["vendor/**"], ["vendor"], ["third/**"], ["**"]):
            with self.subTest(patterns=patterns):
                path = "third/vendor" if patterns == ["third/**"] else "vendor"
                self.assertTrue(globs.covers_tree(path, patterns))
        for patterns in (["vendor/docs/**"], ["vendor/*.md"], ["**/*.md"], ["vendor-x/**"], ["vend*/**"], []):
            with self.subTest(patterns=patterns):
                self.assertFalse(globs.covers_tree("vendor", patterns))

    def test_matches(self):
        self.assertTrue(matches("src/a/b.py", "src/**"))
        self.assertTrue(matches("src/a.py", "src/*.py"))
        self.assertFalse(matches("src/a/b.py", "src/*.py"))
        self.assertTrue(matches("a/x/b", "a/**/b"))
        self.assertTrue(matches("a/b", "a/**/b"))
        self.assertFalse(matches("src/ab", "src/?"))

    def test_matches_paths_with_newline(self):
        # git pathspec 의 `**`·`*`·`?` 는 줄바꿈도 맞춘다. 사전 검사·변조 검사가 owns 안 경로를 밖으로 보지 않게 한다
        self.assertTrue(matches("src/a\nb.py", "src/**"))
        self.assertTrue(matches("x/a\nb/c.py", "**/c.py"))
        self.assertTrue(matches("a/x\ny/b", "a/**/b"))
        self.assertTrue(matches("src/a\nb.py", "src/*.py"))
        self.assertTrue(matches("src/\n", "src/?"))
        self.assertFalse(matches("src/a\nb/c.py", "src/*.py"))  # `*` 는 여전히 한 마디 안이다

    def test_conservative_overlap(self):
        self.assertTrue(overlaps("src/**", "src/auth/**"))
        self.assertTrue(overlaps("src/a*", "src/ab/**"))  # 접두사 src/a 와 src/ab/
        self.assertFalse(overlaps("src/**", "tests/**"))
        self.assertTrue(overlaps("docs/design/**", "docs/design/screens/**"))
        self.assertFalse(overlaps("docs/a.md", "docs/b.md"))
        self.assertTrue(overlaps("docs/a.md", "docs/*.md"))
        self.assertFalse(overlaps("docs/a.md", "src/**"))
        self.assertEqual(any_overlap(["src/**", "x"], ["src/a/**"]), [("src/**", "src/a/**")])
        # 대소문자를 구분하지 않는 파일시스템에서는 같은 경로다(구분하는 곳에서는 병렬 시작만 막혀 안전하다)
        for a, b in (("src/Foo/**", "src/foo/**"), ("SRC/a.py", "src/A.py"), ("src/Foo", "src/foo/*.py"),
                     ("Docs/*.md", "docs/x/**")):
            self.assertTrue(overlaps(a, b) and overlaps(b, a), (a, b))
        self.assertEqual(any_overlap(["src/Foo/**"], ["src/foo/**"]), [("src/Foo/**", "src/foo/**")])
        # casefold 가 한 글자를 여럿으로 늘려도(ß → ss) 원래 판정이 겹치면 겹친다(`?` 는 한 글자다)
        self.assertTrue(overlaps("src/straße.py", "src/stra?e.py") and overlaps("src/stra?e.py", "src/straße.py"))
        # macOS 는 NFC·NFD 표기를 같은 디렉터리로 본다
        nfc, nfd = (unicodedata.normalize(form, "src/café/**") for form in ("NFC", "NFD"))
        self.assertNotEqual(nfc, nfd)
        self.assertTrue(overlaps(nfc, nfd) and overlaps(nfd, nfc))
        self.assertTrue(overlaps(unicodedata.normalize("NFD", "src/CAFÉ/a.py"), "src/café/**"))
        # NFD 결합 글자에 대소문자 차이까지: casefold 만 한 판정이 `??` 두 글자와 맞는다(Codex P2, db50c05 회귀)
        self.assertTrue(overlaps("src/CAFÉ.py", "src/caf??.py") and overlaps("src/caf??.py", "src/CAFÉ.py"))
        for a, b in (("src/café/**", "src/cafe/**"), ("src/Foo/**", "src/bar/**"), ("src/straße.py", "src/stra?e.txt")):
            self.assertFalse(overlaps(a, b) or overlaps(b, a), (a, b))

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

    def test_owns_overlap_ignores_case(self):
        errs = self.errors([task("a", owns=["src/Foo/**"]), task("b", owns=["src/foo/**"])])
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("a 와 b 의 owns 가 겹친다(src/Foo/** ↔ src/foo/**)", errs[0])

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

    def test_check_refuses_what_append_would_refuse(self):
        # 기획 승인 전에 막는다: 이미 적용한 key 를 바꾸거나 빼면 plan check(--file 도)가 apply --append 와 같이 거부한다
        base = [task("a"), task("b", "tester", ["tests/**"])]
        self.write_plan(base)
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        self.write_plan(base + [task("c", owns=["src/c/**"], deps=["a"])])
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual((code, out.get("tasks")), (0, 3), out)
        alt = self.proj / "alt.toml"
        for changed, needle in (([task("a", title="바뀜"), base[1]], "이미 적용한 a 의 내용이 바뀌었다"),
                                ([base[1]], "이미 적용한 a 가 tasks.toml 에서 빠졌다")):
            self.write_plan(changed)
            alt.write_text(toml(changed), encoding="utf-8")
            for args in ((), ("--file", "alt.toml")):
                code, out = self.hteam("plan", "check", *args, as_=None)
                self.assertEqual((code, out["error"]["code"]), (2, "plan_changed"), (args, out))
                self.assertIn(needle, out["error"]["message"])
            code, out = self.hteam("plan", "apply", "--append")
            self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                             (2, "plan_changed", needle), out)

    def test_check_skips_pending_that_recovery_rolls_back(self):
        # 커밋 전에 멈춘 apply 의 pending 은 다음 apply 가 되돌린다. 그 초안을 고쳐도 check 와 apply --append 가 같이 받는다
        base = [task("a")]
        self.write_plan(base)
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        self.write_plan(base + [task("b", "tester", ["tests/**"])])
        code, out = self.hteam("plan", "apply", "--append", env={"HTEAM_TEST_DIE_AT": "plan_before_commit"})
        self.assertEqual(code, 137, out)
        self.assertEqual([r["key"] for r in self.pending()], ["b"])
        edited = base + [task("b", "tester", ["tests/**"], title="고친 초안")]
        self.write_plan([task("a", title="바뀜")] + edited[1:])  # 적용한 항목은 여전히 비교한다
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_changed"), out)
        self.write_plan(edited)
        code, out = self.hteam("plan", "check", as_=None)
        self.assertEqual((code, out.get("tasks")), (0, 2), out)
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out.get("applied")), (0, [{"key": "b", "id": "T-002"}]), out)
        self.assertIn("title: 고친 초안", (self.proj / ".herdr-team/tasks/T-002.md").read_text())

    def test_check_refuses_partly_committed_pending_like_apply(self):
        # pending a·b 가운데 a 만 따로 커밋됐다. apply 는 되돌리지도 마저 끝내지도 않고 plan_incomplete 로 멈춘다
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        self.die("plan_before_commit")
        self.git("add", "--", ".herdr-team/tasks/T-001.md")
        self.git("commit", "-q", "-m", "a 만 커밋", "--", ".herdr-team/tasks/T-001.md")
        self.write_plan([task("a"), task("b", "tester", ["tests/**"], title="고친 초안")])
        for args in (("check",), ("apply", "--append")):
            code, out = self.hteam("plan", *args, as_=None if args == ("check",) else "coordinator")
            self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                             (3, "plan_incomplete", "앞선 plan apply 의 사양 일부만 커밋돼 있다: .herdr-team/tasks/T-001.md"),
                             (args, out))

    def test_check_compares_pending_committed_before_crash(self):
        # 커밋 뒤에 멈춘 apply 의 pending 은 다음 apply 가 마저 끝낸다. 고치면 check 도 apply 처럼 거부한다
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        self.die("plan_after_commit")
        self.assertEqual([r["key"] for r in self.pending()], ["a", "b"])
        self.write_plan([task("a"), task("b", "tester", ["tests/**"], title="바뀜")])
        for args in (("check",), ("apply", "--append")):
            code, out = self.hteam("plan", *args, as_=None if args == ("check",) else "coordinator")
            self.assertEqual((code, out["error"]["code"], out["error"]["message"]),
                             (2, "plan_changed", "이미 적용한 b 의 내용이 바뀌었다"), (args, out))

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
        code, out = self.hteam("plan", "apply", "--append")  # pending 이 남아 있어 그 apply 를 마저 끝낸다
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-001"}, {"key": "b", "id": "T-002"}]), out)
        self.assertEqual([self.task_state(t)["status"] for t in ("T-001", "T-002")], ["pending", "pending"])

    def die(self, point):
        code, out = self.hteam("plan", "apply", env={"HTEAM_TEST_DIE_AT": point})
        self.assertEqual(code, 137, out)

    def pending(self):
        return json.loads((self.state_dir / "plan.json").read_text()).get("pending")

    def test_pending_ids_are_reserved_for_task_new(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        self.die("plan_before_commit")
        (self.proj / ".herdr-team/tasks/T-002.md").unlink()  # T-002 를 쓰기 전에 죽은 것과 같다(pending 에만 있다)
        code, out = self.hteam("task", "new", "--role", "developer", "--title", "손으로")
        self.assertEqual((code, out.get("id")), (0, "T-003"), out)
        hand = (self.proj / ".herdr-team/tasks/T-003.md").read_text()
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-004"}, {"key": "b", "id": "T-005"}]), out)
        self.assertEqual((self.proj / ".herdr-team/tasks/T-003.md").read_text(), hand)

    def test_rollback_leaves_foreign_spec_alone(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        self.die("plan_before_commit")
        self.write_spec("T-002", commit=False)  # 같은 ID 를 다른 길로 쓴 사양(plan_key 없음)
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["error"]["code"]), (3, "plan_id_taken"), out)
        self.assertEqual(self.spec_files(), ["T-001.md", "T-002.md"])
        self.assertEqual([r["id"] for r in self.pending()], ["T-001", "T-002"])

    def test_resume_refuses_foreign_committed_spec(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        self.die("plan_after_commit")
        self.write_spec("T-002")  # 커밋된 T-002 를 plan_key 없는 사양으로 바꿔 커밋
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["error"]["code"]), (3, "plan_id_taken"), out)
        self.assertEqual([r["id"] for r in self.pending()], ["T-001", "T-002"])

    def test_git_read_error_during_recovery_keeps_everything(self):
        self.write_plan([task("a")])
        self.die("plan_after_commit")
        tree = self.git("rev-parse", "HEAD:.herdr-team/tasks").strip()
        obj = self.proj / ".git/objects" / tree[:2] / tree[2:]
        obj.chmod(0o000)  # 트리 객체를 읽지 못하게 한다
        try:
            code, out = self.hteam("plan", "apply")
        finally:
            obj.chmod(0o444)
        self.assertEqual((code, out["error"]["code"]), (1, "git_failed"), out)
        self.assertEqual(self.spec_files(), ["T-001.md"])
        self.assertEqual(self.git("status", "--porcelain", "--", ".herdr-team"), "")
        self.assertEqual([r["id"] for r in self.pending()], ["T-001"])
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-001"}]), out)

    def test_failed_spec_write_leaves_no_partial_spec(self):
        self.write_plan([task("a"), task("b", "tester", ["tests/**"])])
        p = Project(self.proj)
        real = pathlib.Path.write_text

        def disk_full(path, data, *args, **kwargs):  # T-002 사양을 쓰다가 디스크가 찬다
            if "T-002.md" in path.name:
                real(path, data[:10], *args, **kwargs)
                raise OSError(errno.ENOSPC, "No space left on device")
            return real(path, data, *args, **kwargs)

        with mock.patch.object(pathlib.Path, "write_text", disk_full), \
                mock.patch.dict(os.environ, self.env, clear=True), self.assertRaises(OSError):
            plan.apply(p, config.load(p), False)
        self.assertEqual(sorted(f.name for f in (self.proj / ".herdr-team/tasks").iterdir()), [])
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-001"}, {"key": "b", "id": "T-002"}]), out)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=all", "--", ".herdr-team"), "")

    def test_broken_head_ref_is_an_error_not_unborn(self):
        self.write_plan([task("a")])
        self.die("plan_after_commit")
        ref = self.proj / ".git/refs/heads/main"
        sha = ref.read_text()
        for broken in ("", "garbage\n"):  # 커밋 직후 전원이 나가 비거나 깨진 브랜치 ref
            ref.write_text(broken)
            code, out = self.hteam("plan", "apply")
            self.assertEqual((code, out["error"]["code"]), (1, "git_failed"), (broken, out))
            self.assertEqual(self.spec_files(), ["T-001.md"])
            self.assertEqual([r["id"] for r in self.pending()], ["T-001"])
        ref.write_text(sha)
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"], out["commit"]), (0, [{"key": "a", "id": "T-001"}], sha.strip()), out)

    def test_plain_apply_resumes_after_state_failure(self):
        self.write_plan([task("a")])
        tasks_dir = self.state_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        tasks_dir.chmod(0o555)  # 커밋 뒤 상태 파일을 만들지 못하게 한다
        try:
            code, out = self.hteam("plan", "apply")
        finally:
            tasks_dir.chmod(0o755)
        self.assertNotEqual(code, 0, out)
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"]), (0, [{"key": "a", "id": "T-001"}]), out)
        self.assertEqual(self.task_state("T-001")["status"], "pending")
        self.assertIsNone(self.pending())

    def test_apply_reads_tasks_once_under_project_lock(self):
        self.write_plan([task("a")])
        p = Project(self.proj)
        p.ensure_state()
        real, seen = plan.read_plan_data, []

        def spy(path):
            with open(p.lock, "a+") as fh:  # 다른 열린 파일로 잠금을 잡아 보면 지금 잠겨 있는지 안다
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    fcntl.flock(fh, fcntl.LOCK_UN)
                    seen.append(False)
                except BlockingIOError:
                    seen.append(True)
            return real(path)

        with mock.patch.object(plan, "read_plan_data", spy), mock.patch.dict(os.environ, self.env, clear=True):
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


TEST_TABLE = '[test]\nquick = "npx vitest related --run --passWithNoTests {files}"\nfull = "npx vitest run"\n'
GROUP_CONFIG = BASE_CONFIG.replace('owns = ["src/**"]', 'owns = ["src/**", "README.md", "docs/user/**", "docs/policy/**"]')


class GroupRuleTest(TeamCase):
    """묶음 규칙(설계 5.2, orca-team GroupRuleTest)."""

    def setUp(self):
        super().setUp()
        self.init_project(config=GROUP_CONFIG)
        self.setup_run()
        self.path = self.proj / "docs/planning/tasks.toml"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def valid(self):
        return [task("store", owns=["src/store/**"]), task("ui", owns=["src/ui/**"], deps=["store"]),
                task("guide", owns=["docs/user/**"]),
                task("grp", "tester", ["tests/grp/**", "docs/qa/grp.md"], deps=["store", "ui"])]

    def check(self, tasks, table=TEST_TABLE):
        self.path.write_text(toml(tasks) + "\n" + table, encoding="utf-8")
        return self.hteam("plan", "check", as_=None)

    def test_valid_groups_pass_and_report_test(self):
        code, out = self.check(self.valid())
        self.assertEqual((code, out["test"]), (0, True), out)
        code, out = self.check(self.valid() + [task("extra", owns=["src/extra/**"])], table="")
        self.assertEqual((code, out["test"]), (0, False), out)

    def test_rule_messages(self):
        cases = [
            (self.valid() + [task("extra", owns=["src/extra/**"])],
             "extra: 문서 전용이 아닌 developer 태스크는 정확히 한 tester 태스크(묶음)의 depends_on 에 든다(지금: 없음)"),
            (self.valid() + [task("grp2", "tester", ["tests/grp2/**", "docs/qa/grp2.md"], deps=["store"])],
             "store: 문서 전용이 아닌 developer 태스크는 정확히 한 tester 태스크(묶음)의 depends_on 에 든다(지금: grp, grp2)"),
            ([*self.valid()[:3], task("grp", "tester", ["tests/**"], deps=["store", "ui"])],
             'grp: tester 태스크 owns 는 정확히 ["tests/grp/**", "docs/qa/grp.md"] 다'),
            ([task("plan-a", "planner", ["docs/planning/**"]), *self.valid()[:3],
              task("grp", "tester", ["tests/grp/**", "docs/qa/grp.md"], deps=["store", "ui", "plan-a"])],
             "grp: tester 태스크의 depends_on 에는 developer 태스크만 둔다(plan-a)"),
            (self.valid() + [task("next", owns=["src/next/**"], deps=["grp"]),
                             task("grp2", "tester", ["tests/grp2/**", "docs/qa/grp2.md"], deps=["next"])],
             "next: developer 태스크는 tester 태스크에 의존하지 않는다(grp). 다음 묶음 구현이 앞 묶음 테스트를 기다리지 않게 한다"),
        ]
        for tasks, needle in cases:
            code, out = self.check(tasks)
            self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), (needle, out))
            self.assertIn(needle, out["errors"])

    def test_test_table_format_errors_reported(self):
        code, out = self.check(self.valid(), table='[test]\nquick = "npx vitest"\nfull = "npx vitest run"\n')
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertIn("[test]: quick 은 {files} 를 정확히 한 번 담는다", out["errors"])

    def test_append_checks_only_new_tasks(self):
        old = [task("old", owns=["src/old/**"])]
        self.path.write_text(toml(old), encoding="utf-8")
        self.assertEqual(self.hteam("plan", "apply")[0], 0)
        tasks = old + [task("new1", owns=["src/new1/**"]),
                       task("grp", "tester", ["tests/grp/**", "docs/qa/grp.md"], deps=["new1"]),
                       task("new2", owns=["src/new2/**"])]
        code, out = self.check(tasks)
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.assertEqual([e for e in out["errors"] if "문서 전용이 아닌" in e],
                         ["new2: 문서 전용이 아닌 developer 태스크는 정확히 한 tester 태스크(묶음)의 depends_on 에 든다(지금: 없음)"])
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, out["error"]["code"]), (2, "plan_invalid"), out)
        self.path.write_text(toml(tasks[:3]) + "\n" + TEST_TABLE, encoding="utf-8")
        code, out = self.hteam("plan", "apply", "--append")
        self.assertEqual((code, [a["key"] for a in out["applied"]]), (0, ["new1", "grp"]), out)

    def test_planner_review_precheck_uses_group_rules(self):
        self.write_spec("T-001", role="planner", title="기획", owns="docs/planning/**")
        self.assertEqual(self.hteam("start", "T-001")[0], 0)
        did = self.task_state("T-001")["rounds"][-1]["work"]["dispatch"]
        text = toml(self.valid() + [task("extra", owns=["src/extra/**"])]) + "\n" + TEST_TABLE
        self.act(did, {"write": {"docs/planning/tasks.toml": text}, "commit": "[T-001] r1 기획",
                       "done": {"outcome": "succeeded", "summary": "끝"}})
        code, out = self.hteam("review", "T-001")
        self.assertEqual((code, out["status"], out["source"]), (0, "changes", "hteam"), out)
        self.assertIn("extra: 문서 전용이 아닌 developer 태스크", out["problems"][0])


class OwnsWithinTest(TeamCase):
    def test_within_is_conservative(self):
        from hteam.globs import within
        self.assertTrue(within("src/auth/**", "src/**"))
        self.assertTrue(within("src/*.py", "src/**"))
        # 와일드카드 없는 owns 는 그 아래 전체(git·matches)다. outer 가 그 전체를 덮어야(`**`, `<접두사>/**`) 안이다
        self.assertFalse(within("src/a.py", "src/*.py"))
        self.assertFalse(within("src/auth", "src/*"))
        self.assertTrue(within("src/auth", "src/**"))
        self.assertTrue(within("src/a/b", "src/a"))
        self.assertTrue(within("package.json", "package.json"))
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


class SubdirPlanTest(TeamCase):
    """프로젝트가 git 저장소의 하위 디렉터리에 있다. 사양 경로는 프로젝트 기준, HEAD 의 경로는 git 최상위 기준이다."""

    def setUp(self):
        super().setUp()
        self.proj = self.proj / "sub"
        self.proj.mkdir()
        self.init_project()
        self.setup_run()

    def test_resume_after_commit_in_subdir_project(self):
        path = self.proj / "docs/planning/tasks.toml"
        path.parent.mkdir(parents=True)
        path.write_text(toml([task("a")]), encoding="utf-8")
        code, out = self.hteam("plan", "apply", env={"HTEAM_TEST_DIE_AT": "plan_after_commit"})
        self.assertEqual(code, 137, out)
        sha = self.head()
        code, out = self.hteam("plan", "apply")
        self.assertEqual((code, out["applied"], out["commit"]), (0, [{"key": "a", "id": "T-001"}], sha), out)
        self.assertTrue((self.proj / ".herdr-team/tasks/T-001.md").exists())
        self.assertEqual(self.git("status", "--porcelain", "--", ".herdr-team"), "")
        self.assertEqual(self.task_state("T-001")["status"], "pending")


class GitioTest(TeamCase):
    def test_index_entries_read_index_once_without_path_argv(self):
        # 리뷰 기준점은 저장소 전체 변경을 거르기 전에 묻는다. 경로마다 argv 를 늘리면 대량 변경에서 ARG_MAX 를 넘는다
        self.commit("src/a.py", "a\n", "a")
        want = "100644:" + self.git("rev-parse", ":src/a.py").strip()
        paths = ["src/a.py", "README.md"] + [f"bulk/{i:05d}/" + "x" * 80 for i in range(20000)]
        calls, real = [], gitio.run

        def spy(root, *args, **kw):
            calls.append(args)
            return real(root, *args, **kw)
        with mock.patch.object(gitio, "run", spy):
            got = gitio.index_entries(self.proj, paths)
        self.assertEqual(len(calls), 1)
        self.assertLess(sum(len(a) for a in calls[0]), 200)
        self.assertEqual((got["src/a.py"], len(got)), (want, len(paths)))
        self.assertIsNotNone(got["README.md"])
        self.assertIsNone(got[paths[-1]])

    def test_worktree_entries_see_what_git_sees(self):
        self.commit("x.txt", "x\n", "x")
        blob = self.git("rev-parse", "HEAD:x.txt").strip()
        (self.tmp / "out.txt").write_text("x\n")
        (self.proj / "link.txt").symlink_to(self.tmp / "out.txt")
        os.chmod(self.proj / "x.txt", 0o755)
        got = gitio.worktree_entries(self.proj, ["x.txt", "link.txt", "nope.txt"])
        self.assertEqual(got["x.txt"], f"100755:{blob}")
        self.assertTrue(got["link.txt"].startswith("120000:"))
        self.assertNotEqual(got["link.txt"], f"120000:{blob}")  # 링크 대상의 내용이 아니라 링크 글자다
        self.assertIsNone(got["nope.txt"])
        # 실행 비트를 믿지 않으면(core.fileMode=false) git 처럼 인덱스의 모드를 쓴다
        self.assertEqual(gitio.worktree_entries(self.proj, ["x.txt"], exec_bit=False)["x.txt"], f"100644:{blob}")
        self.assertEqual(gitio.worktree_entries(self.proj, ["x.txt"], exec_bit=False,
                                                index={"x.txt": f"100755:{blob}"})["x.txt"], f"100755:{blob}")
        self.assertEqual(gitio.tree_entry(self.proj, "HEAD", "x.txt"), f"100644:{blob}")
        self.assertEqual(gitio.blob(self.proj, "HEAD", "x.txt"), blob)

    def test_top_prefix_keeps_carriage_return_in_folder_name(self):
        # 하위 프로젝트 폴더 이름의 \r 이 text 모드로 \n 이 되면 그 안 변경을 프로젝트 밖(`../`)으로 잘못 나눈다
        sub = self.proj / "app\r"
        try:
            sub.mkdir()
        except OSError as exc:
            self.skipTest(f"이 파일 시스템은 \\r 이 든 이름을 만들지 못한다: {exc}")
        prefix = gitio.top_prefix(sub)
        self.assertEqual(prefix, "app\r/")
        self.assertEqual(gitio.from_top(prefix, "app\r/README.md"), "README.md")
        self.assertEqual(gitio.toplevel(sub), os.path.realpath(self.proj))

    def test_git_path_keeps_carriage_return(self):
        # 링크된 작업 트리에서 --git-path 는 주 저장소의 절대 경로를 낸다. 그 경로의 \r 이 text 모드로 \n 이 되면 깨진 ref
        # 파일(for-each-ref 가 내지 않는다)을 없는 것으로 잘못 본다
        main = self.tmp / "m\r"
        try:
            main.mkdir()
        except OSError as exc:
            self.skipTest(f"이 파일 시스템은 \\r 이 든 이름을 만들지 못한다: {exc}")

        def git(root, *args):
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, env=self.env)
        (main / "f").write_text("f\n")
        for args in (("init", "-q", "-b", "main"), ("add", "f"), ("commit", "-q", "-m", "f")):
            git(main, *args)
        wt = self.tmp / "wt"
        git(main, "worktree", "add", "-q", str(wt))
        (main / ".git" / "refs" / "heads" / "broken").write_text("")  # 비었거나 깨진 ref 파일
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertTrue(gitio._ref_present(wt, "refs/heads/broken"))

    def test_ref_present_reads_packed_refs(self):
        # 느슨한 ref 파일이 없어도 packed-refs 에 있으면 있는 것이다(git 2.43 미만의 has_head 가 기대는 경로)
        self.git("pack-refs", "--all")
        self.assertFalse((self.proj / ".git/refs/heads/main").exists())
        with mock.patch.dict(os.environ, self.env, clear=True):
            self.assertTrue(gitio._ref_present(self.proj, "refs/heads/main"))
            self.assertFalse(gitio._ref_present(self.proj, "refs/heads/nope"))

    def test_worktree_entries_see_submodule_content(self):
        # 서브모듈은 HEAD 와 안의 커밋하지 않은 변경(작업 트리·인덱스)으로 본다. HEAD 가 같아도 안에서 바뀌면 값이 다르다
        head = self.submodule()
        tree = gitio.tree_entry(self.proj, "HEAD", "sub")
        self.assertEqual(tree, f"160000:{head}")
        self.assertEqual(gitio.worktree_entries(self.proj, ["sub"])["sub"], tree)  # 깨끗하면 트리 항목과 같다
        (self.proj / "sub" / "a.txt").write_text("b\n")
        dirty = gitio.worktree_entries(self.proj, ["sub"])["sub"]
        self.assertTrue(dirty.startswith(f"160000:{head}+"), dirty)
        self.assertEqual(gitio.worktree_entries(self.proj, ["sub"])["sub"], dirty)  # 그대로면 같은 값
        (self.proj / "sub" / "a.txt").write_text("c\n")
        again = gitio.worktree_entries(self.proj, ["sub"])["sub"]
        self.assertNotIn(again, (tree, dirty))
        self.git("-C", "sub", "add", "a.txt")  # 스테이징만 해도 다르다
        self.assertNotIn(gitio.worktree_entries(self.proj, ["sub"])["sub"], (tree, dirty, again))

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

    def test_blob_tells_absent_from_error(self):
        head = self.head()
        self.assertIsNotNone(gitio.blob(self.proj, head, "README.md"))
        self.assertIsNone(gitio.blob(self.proj, head, "nope.md"))
        self.assertIsNone(gitio.blob(self.proj, head, "README.m?"))  # 경로는 글자 그대로다
        with self.assertRaises(HteamError) as cm:
            gitio.blob(self.proj, "no-such-rev", "README.md")
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("git_failed", 1))

    def test_has_head_unborn_only_when_branch_ref_is_missing(self):
        self.assertTrue(gitio.has_head(self.proj))
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(fresh)], check=True, env=self.env)
        self.assertFalse(gitio.has_head(fresh))
        (fresh / ".git/refs/heads/main").write_text("garbage\n")
        with self.assertRaises(HteamError) as cm:
            gitio.has_head(fresh)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("git_failed", 1))

    def test_has_head_without_show_ref_exists(self):
        """git 2.43 미만은 `show-ref --exists` 를 몰라 exit 129 를 낸다. 그래도 unborn 과 손상 ref 를 가른다."""
        real = gitio.run

        def old_git(root, *args, **kw):
            if args[:2] == ("show-ref", "--exists"):
                return subprocess.CompletedProcess(args, 129, "", "error: unknown option `exists'")
            return real(root, *args, **kw)

        fresh = self.tmp / "fresh_old"
        fresh.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(fresh)], check=True, env=self.env)
        with mock.patch.object(gitio, "run", old_git):
            self.assertTrue(gitio.has_head(self.proj))
            self.assertFalse(gitio.has_head(fresh))
            for junk in ("", "garbage\n"):
                (fresh / ".git/refs/heads/main").write_text(junk)
                with self.assertRaises(HteamError) as cm:
                    gitio.has_head(fresh)
                self.assertEqual((cm.exception.code, cm.exception.exit_code), ("git_failed", 1))

    def test_commit_paths_names_literal_paths(self):
        (self.proj / "a[1].txt").write_text("x\n")
        (self.proj / "a1.txt").write_text("y\n")
        with mock.patch.dict(os.environ, self.env, clear=True):
            sha = gitio.commit_paths(self.proj, ["a[1].txt"], "s")
        self.assertEqual(gitio.commit_files(self.proj, sha), ["a[1].txt"])
        self.assertEqual(gitio.untracked(self.proj), ["a1.txt"])

    class FakeTime:
        """gitio 의 시계·잠을 시험이 쥔다: 잘 때만 시간이 간다(실행 속도와 상관없이 재시도 횟수가 정해진다. Codex 계획 r2)."""

        def __init__(self, on_sleep=None):
            self.now, self.sleeps, self.on_sleep = 0.0, [], on_sleep

        def monotonic(self):
            return self.now

        def sleep(self, secs):
            self.sleeps.append(secs)
            self.now += secs
            if self.on_sleep:
                self.on_sleep(len(self.sleeps))

    def counted_adds(self):
        real, adds = subprocess.run, []

        def git(argv, **kw):
            if "add" in argv:
                adds.append(argv)
            return real(argv, **kw)
        return git, adds

    def test_commit_paths_waits_for_index_lock(self):
        # 같은 폴더의 워커 커밋이 index.lock 을 쥔 순간이면 잠깐 기다렸다 다시 한다. 잠금은 두 번째 잠 뒤에 풀린다
        lock = self.proj / ".git" / "index.lock"
        (self.proj / "a.txt").write_text("a\n")
        lock.write_text("")
        clock = self.FakeTime(on_sleep=lambda n: n == 2 and lock.unlink())
        git, adds = self.counted_adds()
        with mock.patch.dict(os.environ, {**self.env, "HTEAM_GIT_LOCK_WAIT": "10"}, clear=True), \
                mock.patch("hteam.gitio.subprocess.run", side_effect=git), mock.patch.object(gitio, "time", clock):
            sha = gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual(gitio.commit_files(self.proj, sha), ["a.txt"])
        self.assertEqual((len(adds), clock.sleeps), (3, [0.2, 0.2]))  # 잠금이 풀릴 때까지 0.2초마다 다시 했다

    def test_commit_paths_gives_up_on_stale_index_lock(self):
        # 마감 0.3초: 0초·0.2초에 다시 하고 0.4초에 멈춘다(시계는 시험이 쥔다)
        (self.proj / "a.txt").write_text("a\n")
        lock = self.proj / ".git" / "index.lock"
        lock.write_text("")
        clock = self.FakeTime()
        git, adds = self.counted_adds()
        with mock.patch.dict(os.environ, {**self.env, "HTEAM_GIT_LOCK_WAIT": "0.3"}, clear=True), \
                mock.patch("hteam.gitio.subprocess.run", side_effect=git), mock.patch.object(gitio, "time", clock):
            with self.assertRaises(HteamError) as cm:
                gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual((cm.exception.code, cm.exception.data.get("index_lock")), ("git_failed", True))
        self.assertIn("index.lock", cm.exception.hint)
        self.assertIn("직접 지우지 않는다", cm.exception.hint)
        self.assertEqual((len(adds), clock.sleeps), (3, [0.2, 0.2]))
        self.assertTrue(lock.exists())  # 남의 잠금 파일은 지우지 않는다

    def test_index_lock_permission_error_is_not_retried(self):
        # git 의 index.lock 메시지가 File exists(다른 git 이 쥐고 있다)일 때만 기다린다. 권한 오류는 기다려도 풀리지 않는다
        calls = []

        def git(argv, **kw):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 128, "", "fatal: Unable to create '/x/.git/index.lock': "
                                                             "Permission denied\n")

        with mock.patch.dict(os.environ, {"HTEAM_GIT_LOCK_WAIT": "5"}), \
                mock.patch("hteam.gitio.subprocess.run", side_effect=git):
            with self.assertRaises(HteamError) as cm:
                gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual(len([c for c in calls if "add" in c]), 1)  # 잠금 파일 조회(rev-parse)도 실패해 영어 문구만 본다
        self.assertFalse((cm.exception.data or {}).get("index_lock"))
        self.assertNotIn("다른 git 명령", cm.exception.hint)

    def test_translated_index_lock_message_is_retried_while_the_lock_file_exists(self):
        # gettext 를 켠 git 은 로캘에 따라 `File exists` 를 번역한다. 실패 직후 잠금 파일이 있으면 그래도 기다린다
        real, adds = subprocess.run, []
        lock = self.proj / ".git" / "index.lock"

        def german(argv, **kw):
            if "add" in argv:
                adds.append(argv)
                if len(adds) == 3:  # 두 번 실패한 뒤 다른 git 이 잠금을 풀었다(확인 뒤라 경쟁이 없다)
                    lock.unlink()
            proc = real(argv, **kw)
            if proc.returncode != 0 and "File exists" in (proc.stderr or ""):
                proc.stderr = (f"fatal: Konnte '{lock}' nicht erstellen: Die Datei existiert bereits.\n\n"
                               "Ein anderer Git-Prozess scheint in diesem Repository ausgeführt zu werden.\n")
            return proc

        (self.proj / "a.txt").write_text("a\n")
        lock.write_text("")
        with mock.patch.dict(os.environ, {**self.env, "HTEAM_GIT_LOCK_WAIT": "10"}, clear=True), \
                mock.patch("hteam.gitio.subprocess.run", side_effect=german):
            sha = gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual(len(adds), 3)
        self.assertEqual(gitio.commit_files(self.proj, sha), ["a.txt"])

    def test_index_lock_error_without_the_lock_file_is_not_retried(self):
        # 번역됐든 아니든 `File exists` 가 없고 실패 직후 잠금 파일도 없으면(권한 오류 등) 기다리지 않는다
        real, adds, queries = subprocess.run, [], []

        def git(argv, **kw):
            if "add" in argv:
                adds.append(argv)
                return subprocess.CompletedProcess(argv, 128, "", "fatal: Unable to create '/x/.git/index.lock': "
                                                                 "Permission denied\n")
            proc = real(argv, **kw)  # 잠금 파일 조회는 실제 git 이 한다
            if "--git-path" in argv:
                queries.append(proc.returncode)
            return proc

        (self.proj / "a.txt").write_text("a\n")
        with mock.patch.dict(os.environ, {**self.env, "HTEAM_GIT_LOCK_WAIT": "5"}, clear=True), \
                mock.patch("hteam.gitio.subprocess.run", side_effect=git):
            with self.assertRaises(HteamError) as cm:
                gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertEqual(len(adds), 1)
        self.assertFalse((cm.exception.data or {}).get("index_lock"))
        self.assertEqual(queries, [0])  # 잠금 파일 조회를 실제로 했고 성공했다(조회 실패로 False 가 된 것이 아니다)

    def test_commit_paths_shares_one_lock_deadline(self):
        # add 와 commit 이 마감 하나를 나눠 쓴다. 따로 쓰면 add 가 쓴 시간 뒤로 HTEAM_GIT_LOCK_WAIT 를 다시 기다린다
        clock = [0.0]
        fake = mock.Mock(monotonic=lambda: clock[0], sleep=lambda s: clock.__setitem__(0, clock[0] + s))

        def git(root, *args, **kw):
            if args[0] == "add" and clock[0] >= 0.4:
                return None
            raise HteamError("git_failed", "git 실패: index.lock", data={"index_lock": True})

        with mock.patch.dict(os.environ, {"HTEAM_GIT_LOCK_WAIT": "1"}), mock.patch.object(gitio, "time", fake), \
                mock.patch.object(gitio, "run", side_effect=git):
            with self.assertRaises(HteamError) as cm:
                gitio.commit_paths(self.proj, ["a.txt"], "a")
        self.assertTrue(cm.exception.data.get("index_lock"))
        self.assertLess(clock[0], 1.3)  # 마감을 따로 쓰면 0.4 + 1 = 1.4 까지 기다린다

    def test_git_timeout_is_json_error(self):
        with mock.patch("hteam.gitio.subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 120)):
            with self.assertRaises(HteamError) as cm:
                gitio.head(self.proj)
        self.assertEqual((cm.exception.code, cm.exception.exit_code), ("git_timeout", 1))


if __name__ == "__main__":
    unittest.main()
