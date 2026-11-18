"""검사 약화 의심(설계 6.6 의 1): 추가한 줄의 패턴, 시험 파일 판정, 시험 정의 이름, 지운 시험 파일·시험, `@Test` 표시·단언
줄어듦, 본문만 pass 로 바꾼 except, 상한."""
import unittest

from tests.helpers import TeamCase
from hteam import gitio
from hteam.guardlint import defined_tests, guard_lint, is_test_file, line_findings


def heads(rel, text):
    """`분류 "일치"` 부분만(파일 전체를 추가한 줄로 본다). 일치한 글에는 따옴표가 없다."""
    out = []
    for item in line_findings(rel, text, set(text.split("\n"))):
        rest = item.split(": ", 1)[1]
        out.append(rest[:rest.index('"(', rest.index('"') + 1) + 1])
    return out


class LineTest(unittest.TestCase):
    def test_each_pattern(self):
        cases = {
            "// @ts-ignore": '억제 주석 "@ts-ignore"', "// @ts-expect-error": '억제 주석 "@ts-expect-error"',
            "// @ts-nocheck": '억제 주석 "@ts-nocheck"', "/* eslint-disable no-console */": '억제 주석 "eslint-disable"',
            "x = 1  # noqa: E501": '억제 주석 "# noqa"', "y = f()  # type: ignore": '억제 주석 "# type: ignore"',
            "z = g()  # pyright: ignore": '억제 주석 "# pyright: ignore"',
            "/* istanbul ignore next */": '억제 주석 "istanbul ignore"', "/* c8 ignore next */": '억제 주석 "c8 ignore"',
            "if x:  # pragma: no cover": '억제 주석 "pragma: no cover"', "a := b //nolint": '억제 주석 "//nolint"',
            '@SuppressWarnings("unchecked")': '억제 주석 "@SuppressWarnings"',
            "it.skip('a', f)": '시험 건너뛰기 ".skip("', "describe.only('a', f)": '시험 건너뛰기 ".only("',
            "xit('a', f)": '시험 건너뛰기 "xit("', "xdescribe('a', f)": '시험 건너뛰기 "xdescribe("',
            "xtest('a', f)": '시험 건너뛰기 "xtest("',
            "@pytest.mark.skip(reason='x')": '시험 건너뛰기 "@pytest.mark.skip"',
            "@pytest.mark.xfail": '시험 건너뛰기 "@pytest.mark.xfail"', "@unittest.skip('x')": '시험 건너뛰기 "@unittest.skip"',
            '\tt.Skip("flaky")': '시험 건너뛰기 "t.Skip("', "#[ignore]": '시험 건너뛰기 "#[ignore]"',
            "@Ignore": '시험 건너뛰기 "@Ignore"', "@Disabled": '시험 건너뛰기 "@Disabled"',
            "try { a() } catch (e) {}": '빈 catch "catch (e) {}"', "} catch {}": '빈 catch "catch {}"',
            "except: pass": '빈 catch "except: pass"',
        }
        for line, want in cases.items():
            self.assertEqual(heads("src/a.ts", line), [want], line)

    def test_except_then_pass_and_lookalikes(self):
        text = "try:\n    a()\nexcept ValueError:\n    pass\nexcept KeyError:\n    log()\n"
        self.assertEqual(heads("src/a.py", text), ['빈 catch "except ValueError:"'])
        for line in ("sys.exit(1)", "context(x)", "stream.skipLast(2)", "@IgnoreExtraProperties", "@TestFactory",
                     "catch (e) { log(e) }", "except ValueError as e: log(e)"):
            self.assertEqual(heads("src/a.ts", line), [], line)

    def test_finding_format_and_only_added_lines(self):
        text = "a()\n// @ts-ignore\nb()\n"
        self.assertEqual(line_findings("src/a.ts", text, {"// @ts-ignore"}),
                         ['src/a.ts:2: 억제 주석 "@ts-ignore"(// @ts-ignore)'])
        self.assertEqual(line_findings("src/a.ts", text, {"a()"}), [])
        long = "x = 1  # noqa " + "가" * 80
        shown = line_findings("src/a.py", long, {long})[0].split("(", 1)[1][:-1]
        self.assertEqual((len(shown), shown[-1]), (60, "…"))

    def test_test_files(self):
        for rel in ("tests/a.py", "src/test/Foo.kt", "spec/a_spec.rb", "src/__tests__/a.js", "pkg/a_test.go",
                    "src/a.test.ts", "src/a.spec.tsx", "test_a.py", "src/test_util.py"):
            self.assertTrue(is_test_file(rel), rel)
        for rel in ("src/app.py", "src/testing/a.py", "src/contest.py", "src/latest.ts", "docs/spec.md", "src/tests.py"):
            self.assertFalse(is_test_file(rel), rel)

    def test_defined_tests(self):
        lines = ["def test_save(self):", "    async def test_load():", "func TestAdd(t *testing.T) {",
                 "it('저장한다', () => {", 'test("불러온다", async () => {', "  it(`템플릿`, f)", "@Test",
                 '@DisplayName("x")', "public void keepsOrder() {", "def helper():", "describe('묶음', () => {"]
        self.assertEqual(defined_tests(lines),
                         ["test_save", "test_load", "TestAdd", "저장한다", "불러온다", "템플릿", "keepsOrder"])


class GuardLintGitTest(TeamCase):
    """git 이 필요한 것: 지운 시험 파일·시험 정의, 단언 줄어듦, 옮긴 시험, 실제 diff 의 except 본문·`@Test` 표시, 상한, 보지 않는
    경로, 하위 폴더 프로젝트."""

    def test_existing_except_body_changed_to_pass(self):
        # 그대로 둔 except 머리 아래 본문만 pass 로 바꿨다(실제 diff: 추가한 줄은 본문뿐이다. Codex 계획 리뷰 p13c r1)
        base = ("try:\n    a()\nexcept ValueError:\n    log()\n\nclass B:\n    def f(self):\n        try:\n            b()\n"
                "        except KeyError:\n            pass\n")
        self.commit("src/a.py", base, "기존")
        sha = self.commit("src/a.py", base.replace("    log()\n", "    # 무시한다\n    pass\n"), "[T-001] 본문만 바꿈")
        self.assertEqual(gitio.added_lines(self.proj, [sha], "src/a.py"), {"    # 무시한다", "    pass"})
        self.assertEqual(guard_lint(self.proj, ["src/a.py"], [sha]),
                         ['src/a.py:3: 빈 catch "except ValueError:"(except ValueError:)'])  # 그대로 둔 KeyError 블록은 아니다
        more = self.commit("src/b.py", "try:\n    a()\nexcept ValueError:\n    pass\n    log()\n", "[T-001] 문장이 더 있다")
        self.assertEqual(guard_lint(self.proj, ["src/b.py"], [more]), [])

    def test_removed_test_annotation_only(self):
        # 함수는 두고 `@Test` 만 지우면 그 시험은 돌지 않는다. 지운 줄에는 표시만 있어 이름을 찾지 못한다(r1)
        rel = "src/test/java/a/FooTest.java"
        body = ("class FooTest {\n    @Test\n    void saves() {\n        assertEquals(1, f());\n    }\n\n    @Test\n"
                "    void loads() {\n        assertEquals(2, g());\n    }\n}\n")
        self.commit(rel, body, "기존 시험")
        sha = self.commit(rel, body.replace("    @Test\n    void loads", "    void loads"), "[T-001] 표시만 지움")
        self.assertEqual(gitio.diff_lines(self.proj, [sha], rel), ([], ["    @Test"]))
        self.assertEqual(guard_lint(self.proj, [rel], [sha]), [f"{rel}: @Test 표시 1개 지움, 0개 더함"])

    def test_deleted_test_file_tests_and_asserts(self):
        self.commit("tests/test_a.py", "def test_save():\n    assert f() == 1\n    assert g()\n\ndef test_load():\n"
                    "    assert h()\n", "기존 시험")
        self.commit("tests/test_b.py", "def test_x():\n    assert 1\n", "기존 시험 b")
        self.commit("src/a.py", "assert x\n", "제품 코드")
        first = self.commit("tests/test_a.py", "def test_save():\n    assert f() == 1\n\ndef test_renamed():\n    pass\n",
                            "[T-001] 시험 고침")
        self.git("rm", "-q", "--", "tests/test_b.py")
        self.git("commit", "-q", "-m", "[T-001] 시험 지움")
        second = self.head()
        third = self.commit("src/a.py", "", "[T-001] 단언 지움")  # 제품 코드의 단언은 세지 않는다
        found = guard_lint(self.proj, ["src/a.py", "tests/test_a.py", "tests/test_b.py"], [first, second, third])
        self.assertEqual(found, ["tests/test_a.py: 지운 시험 1개(test_load) — 같은 이름을 추가한 줄이 없다",
                                 "tests/test_a.py: 단언 2개 지움, 0개 더함",
                                 "tests/test_b.py: 시험 파일을 지웠다"])

    def test_moved_test_is_not_a_deleted_test(self):
        # 같은 이름이 다른 시험 파일의 추가한 줄에 있으면 지운 시험이 아니다. 단언은 파일마다 센다(설계 6.6 의 1)
        self.commit("tests/test_a.py", "def test_save():\n    assert 1\n", "기존")
        a = self.commit("tests/test_a.py", "", "[T-001] 옮김")
        b = self.commit("tests/test_c.py", "def test_save():\n    assert 1\n", "[T-001] 새 파일")
        self.assertEqual(guard_lint(self.proj, ["tests/test_a.py", "tests/test_c.py"], [a, b]),
                         ["tests/test_a.py: 단언 1개 지움, 0개 더함"])

    def test_added_test_file_is_not_deleted(self):
        a = self.commit("tests/test_n.py", "def test_n():\n    assert 1\n", "[T-001] 새 시험")
        self.git("rm", "-q", "--", "tests/test_n.py")
        self.git("commit", "-q", "-m", "[T-001] 다시 지움")
        found = guard_lint(self.proj, ["tests/test_n.py"], [a, self.head()])
        self.assertNotIn("tests/test_n.py: 시험 파일을 지웠다", found)  # 이 태스크 전에는 없던 파일이다

    def test_cap_and_excluded_paths(self):
        sha = self.commit("src/a.ts", "".join(f"// @ts-ignore {n}\n" for n in range(53)), "[T-001] 많다")
        found = guard_lint(self.proj, ["src/a.ts"], [sha])
        self.assertEqual((len(found), found[-1]), (51, "… 외 3건"))
        docs = self.commit("docs/tasks/T-001/report.md", "`@ts-ignore` 를 더한 이유\n", "[T-001] 보고서")
        readme = self.commit("README.md", "eslint-disable 을 쓰지 않는다\n", "[T-001] 문서")
        self.assertEqual(guard_lint(self.proj, ["docs/tasks/T-001/report.md", "README.md", "../x.ts"], [docs, readme]), [])
        self.assertEqual(guard_lint(self.proj, ["src/a.ts"], []), [])

    def test_subdir_project(self):
        self.commit("app/README.md", "앱\n", "하위 폴더 프로젝트")
        self.commit("app/tests/test_a.py", "def test_a():\n    assert 1\n", "기존")
        self.git("rm", "-q", "--", "app/tests/test_a.py")
        self.git("commit", "-q", "-m", "[T-001] 지움")
        self.assertEqual(guard_lint(self.proj / "app", ["tests/test_a.py"], [self.head()]),
                         ["tests/test_a.py: 시험 파일을 지웠다"])


if __name__ == "__main__":
    unittest.main()
