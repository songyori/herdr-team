"""문구 자동 검사(설계 11.7): 분류, 출력 형식, 대상 파일, 검사할 줄, 추가한 줄만, 용어집, 높임법, 상한, gitio.diff_lines."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import TeamCase
from hteam import gitio, textlint
from hteam.textlint import ending_styles, load_glossary, scan, targets, text_lint, visible_lines

VOICE = """# 문구 기준

## 문체
- 서비스 문구: 해요체

## 용어집
| 쓰는 표기 | 쓰지 않는 표기 | 메모 |
|---|---|---|
| 로그인 | 로그 인, `로긴` | |
| 회원가입 | 가입 | |
| 오늘할일 | | 서비스 이름 |
| 할 일 | 할일 | |
| 약관 | 이용 약관(제목), 약관서（링크） | 제목·링크에서만 |
"""


def lines(text):
    """scan 에 줄 파일 내용 전체를 추가한 줄로 준다(git 없이)."""
    return set(text.split("\n"))


class ScanTest(unittest.TestCase):
    def found(self, text, rel="src/app.tsx", glossary=()):
        return scan(rel, text, lines(text), list(glossary))

    def heads(self, text, rel="src/app.tsx", glossary=()):
        """`분류 "일치"` 부분만."""
        return [item.split(": ", 1)[1].split("(", 1)[0] for item in self.found(text, rel, glossary)]

    def test_each_category(self):
        cases = {"결제가 완료됬어요": '오탈자 "됬"', "저장이 안되요": '오탈자 "안되요"', "주문이 되어진다": '이중피동 "되어진"',
                 "처리가 되어졌다": '이중피동 "되어졌"', "결제에 있어서 중요한 점": '번역투 "에 있어서"',
                 "혁신적인 기능": '상투어 "혁신적"', "Seamless 결제 경험": '상투어 "Seamless"',
                 "편리하다라고 할 수 있다": 'hedging "라고 할 수 있"', "물론입니다 바로 해요": '챗봇 잔재 "물론입니다"',
                 "그리고, 저장한다": '쉼표 "그리고,"', "저장하며, 보낸다": '쉼표 "며,"', "확인해서, 보낸다": '쉼표 "해서,"',
                 "저장하고, 보낸다": '쉼표 "고,"'}
        for text, want in cases.items():
            self.assertIn(want, self.heads(f'const a = "{text}";'), text)
        self.assertEqual(self.heads('const a = "저장이 안되요";'), ['오탈자 "안되요"'])  # "되요" 로 다시 세지 않는다
        self.assertEqual(self.heads('const a = "하지만, 저장한다";'), ['쉼표 "하지만,"'])  # "지만," 으로 다시 세지 않는다

    def test_finding_format(self):
        self.assertEqual(self.found('const a = "결제가 완료됬어요";'),
                         ['src/app.tsx:1: 오탈자 "됬"(const a = "결제가 완료됬어요";)'])

    def test_normal_text_has_no_findings(self):
        for text in ("회원님은 언제든지 탈퇴할 수 있습니다", "결제는 카드를 통해 진행해요", "unlock()", "로그인이 필요",
                     "신고, 차단, 숨기기", "경고, 오류, 정보", "참고, 아래 표"):
            self.assertEqual(self.found(f'const a = "{text}";'), [], text)
        self.assertEqual(self.found('{"lock.unlock": "잠금 해제"}', "src/i18n/ko.json"), [])

    def test_mobile_formats_and_comment_lines(self):
        cases = {"ios/Localizable.strings": '/* 됬 주석 */\n"save" = "저장됬어요";\n',
                 "ios/View.swift": '// 됬 주석\nText("저장됬어요")\n',
                 "android/strings.xml": '<!-- 됬 주석 -->\n<string name="save">저장됬어요</string>\n',
                 "lib/app.dart": "# 됬 주석\nText('저장됬어요');\n",
                 "config/ko.yaml": "# 됬 주석\nsave: 저장됬어요\n",
                 "web/index.html": "<!-- 됬 주석 -->\n<p>저장됬어요</p>\n"}
        for rel, text in cases.items():
            self.assertEqual([x.split(":", 2)[1] for x in self.found(text, rel)], ["2"], rel)

    def test_markdown_skips_code_but_not_bullets(self):
        text = "```\n완료됬다\n```\n~~~js\n완료됬다\n~~~\n인라인 `완료됬다` 는 빼고 본다\n* 저장됬다\n"
        self.assertEqual([x.split(":", 2)[1] for x in self.found(text, "docs/user/guide.md")], ["8"])
        self.assertEqual([n for n, _, _ in visible_lines("docs/user/guide.md", text)], [7, 8])

    def test_only_added_lines(self):
        text = 'const a = "저장됬어요";\nconst b = "삭제됬어요";\n'
        self.assertEqual(scan("src/app.tsx", text, {'const b = "삭제됬어요";'}, []),
                         ['src/app.tsx:2: 오탈자 "됬"(const b = "삭제됬어요";)'])

    def test_glossary_terms_and_cover(self):
        glossary = [("로그인", ["로긴"]), ("회원가입", ["가입"]), ("오늘할일", ["오늘 할일"]), ("할 일", ["할일"])]
        text = 'a = "로긴 해 주세요";\nb = "회원가입 하세요";\nc = "오늘할일 앱";\nd = "할일 추가";\n'
        self.assertEqual(self.found(text, glossary=glossary),
                         ['src/app.tsx:1: 금지 표기 "로긴"→"로그인"(a = "로긴 해 주세요";)',
                          'src/app.tsx:4: 금지 표기 "할일"→"할 일"(d = "할일 추가";)'])

    def test_mixed_endings_reported_once_with_minor_lines(self):
        text = 'a = "저장했어요";\nb = "삭제했어요";\nc = "완료했습니다";\nd = "다음 단계로 가요. 저장합니다."\n'
        found = self.found(text)
        self.assertEqual(found, ["src/app.tsx:3: 높임법 섞임(해요체 2줄, 하십시오체 2줄. 하십시오체 줄: 3, 4)"])
        text = 'a = "저장했어요";\nb = "완료됬습니다";\n'
        self.assertEqual(self.found(text), ['src/app.tsx:2: 오탈자 "됬"(b = "완료됬습니다";)',
                                            "src/app.tsx:2: 높임법 섞임(해요체 1줄, 하십시오체 1줄. 하십시오체 줄: 2)"])
        many = "".join(f'x{n} = "저장했어요";\n' for n in range(7)) + "".join(f'y{n} = "저장합니다";\n' for n in range(6))
        self.assertEqual(self.found(many)[-1],
                         "src/app.tsx:8: 높임법 섞임(해요체 7줄, 하십시오체 6줄. 하십시오체 줄: 8, 9, 10, 11, 12, …)")

    def test_ending_styles(self):
        self.assertEqual(ending_styles('"다음 단계로 가요. 저장합니다."'), {"하십시오체"})
        self.assertEqual(ending_styles("<p>저장할까요?</p>"), {"해요체"})
        self.assertEqual(ending_styles("| 확인하십시오 |"), {"하십시오체"})
        for word in ("필요", "중요", "개요", "주요", "수요", "아니요", "좋아요"):
            self.assertEqual(ending_styles(f'"{word}"'), set(), word)

    def test_long_line_excerpt_is_cut(self):
        text = 'const a = "' + "가" * 80 + '됬";'
        item = self.found(text)[0]
        snippet = item.split("(", 1)[1][:-1]
        self.assertEqual(len(snippet), 60)
        self.assertTrue(snippet.endswith("…"))


class GlossaryTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="hteam-text-")).resolve()
        self.addCleanup(shutil.rmtree, self.root, True)
        (self.root / "docs/planning").mkdir(parents=True)
        self.voice = self.root / "docs/planning/voice.md"

    def test_load_glossary(self):
        self.voice.write_text(VOICE, encoding="utf-8")
        self.assertEqual(load_glossary(self.root),
                         [("로그인", ["로그 인", "로긴"]), ("회원가입", ["가입"]), ("할 일", ["할일"]), ("약관", [])])

    def test_bad_or_missing_glossary_is_empty(self):
        self.assertEqual(load_glossary(self.root), [])
        for text in (VOICE.replace("| 쓰는 표기 | 쓰지 않는 표기 |", "| 표기 | 금지 |"), VOICE.replace("## 용어집", "## 용어"),
                     "# 문구 기준\n\n## 용어집\n\n## 다음\n| 쓰는 표기 | 쓰지 않는 표기 |\n|---|---|\n| a | b |\n"):
            self.voice.write_text(text, encoding="utf-8")
            self.assertEqual(load_glossary(self.root), [], text[:40])
        self.voice.write_bytes(b"\xff\xfe" + VOICE.encode("utf-8"))
        self.assertEqual(load_glossary(self.root), [])

    def test_targets(self):
        def put(rel, text):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return rel
        yes = [put("src/app.tsx", 'a = "저장"\n'), put("docs/design/screens/home/index.html", "<p>홈</p>\n"),
               put("README.md", "# 할 일\n"), put("docs/policy/terms.md", "이용약관\n"), put("app/ko.arb", '{"a": "저장"}\n')]
        no = [put(rel, "저장\n") for rel in (
            "docs/planning/spec.md", "docs/tasks/T-001/report.md", "docs/reviews/T-001/r1.md", "docs/qa/plan.md",
            "docs/design/direction.md", "docs/design/board/a.html", "docs/design/pilots/a.html",
            "docs/design/system/README.md", "docs/design/screens/home/notes.md", "tests/a.md", ".herdr-team/x.md",
            "src/a.test.ts", "src/a.spec.ts", "src/__tests__/a.ts", "e2e/a.ts", "src/app.py")]
        no += [put("src/comment.js", "// 한글 주석만 있다\nconst a = 1;\n"), put("src/none.tsx", "const a = 1;\n"),
               "src/deleted.tsx", "../outside.md"]
        put("src/big.md", "저장\n" + "a" * (1 << 20))
        (self.root / "src/bad.md").write_bytes(b"\xff \xea\xb0\x80\n")
        self.assertEqual(targets(self.root, [*yes, *no, "src/big.md", "src/bad.md"]), yes)


class GitTextLintTest(TeamCase):
    """git 이 필요한 것: 추가한 줄만, 다른 커밋, 경로, UTF-8 아닌 diff, 상한, 하위 폴더 프로젝트, 병합 커밋, diff_lines."""

    def test_only_lines_added_by_the_given_commits(self):
        mine = self.commit("src/app.tsx", 'a = "저장됬어요";\n', "[T-001] 작업")
        self.commit("src/app.tsx", 'a = "저장됬어요";\nb = "삭제됬어요";\n', "[T-002] 다른 태스크")
        self.assertEqual(text_lint(self.proj, ["src/app.tsx"], [mine]),
                         ['src/app.tsx:1: 오탈자 "됬"(a = "저장됬어요";)'])

    def test_literal_pathspec_and_git_error_skip_only_that_file(self):
        sha = self.commit("src/[id]/page.tsx", 'a = "저장됬어요";\n', "[T-001] 동적 경로")
        self.commit("src/b.tsx", 'b = "삭제됬어요";\n', "[T-001] b")
        shas = [sha, self.head()]
        self.assertEqual([x.split(":", 1)[0] for x in text_lint(self.proj, ["src/[id]/page.tsx", "src/b.tsx"], shas)],
                         ["src/[id]/page.tsx", "src/b.tsx"])
        real = gitio.added_lines
        with mock.patch.object(textlint.gitio, "added_lines",
                               side_effect=lambda root, s, rel: None if rel == "src/b.tsx" else real(root, s, rel)):
            self.assertEqual([x.split(":", 1)[0] for x in text_lint(self.proj, ["src/[id]/page.tsx", "src/b.tsx"], shas)],
                             ["src/[id]/page.tsx"])

    def test_non_utf8_diff_skips_only_that_file(self):
        path = self.proj / "src/a.md"
        path.parent.mkdir(parents=True)
        path.write_bytes("저장됬다\n".encode("utf-8") + b"\xff\n")
        self.git("add", "--", "src/a.md")
        self.git("commit", "-q", "-m", "[T-001] 깨진 글자", "--", "src/a.md")
        bad = self.head()
        self.commit("src/a.md", "저장됬다\n", "[T-001] 고침")
        self.commit("src/b.md", "삭제됬다\n", "[T-001] b")
        shas = [bad, *self.git("rev-list", f"{bad}..HEAD").split()]
        self.assertIsNone(gitio.diff_lines(self.proj, shas, "src/a.md"))
        self.assertEqual([x.split(":", 1)[0] for x in text_lint(self.proj, ["src/a.md", "src/b.md"], shas)], ["src/b.md"])

    def test_cap(self):
        sha = self.commit("src/app.tsx", "".join(f'a{n} = "저장됬"\n' for n in range(53)), "[T-001] 많다")
        found = text_lint(self.proj, ["src/app.tsx"], [sha])
        self.assertEqual(len(found), 51)
        self.assertEqual(found[-1], "… 외 3건")

    def test_subdir_project(self):
        sha = self.commit("app/src/a.md", "저장됬다\n", "[T-001] 하위 폴더")
        self.assertEqual(text_lint(self.proj / "app", ["src/a.md"], [sha]), ['src/a.md:1: 오탈자 "됬"(저장됬다)'])

    def test_merge_commit_is_compared_with_first_parent(self):
        self.git("checkout", "-q", "-b", "side")
        self.commit("src/a.md", "저장됬다\n", "옆 가지")
        self.git("checkout", "-q", "main")
        self.commit("src/b.md", "b\n", "main 가지")
        self.git("merge", "--no-ff", "-q", "-m", "[T-001] 병합", "side")
        self.assertEqual(text_lint(self.proj, ["src/a.md"], [self.head()]), ['src/a.md:1: 오탈자 "됬"(저장됬다)'])

    def test_diff_lines(self):
        first = self.commit("src/a.txt", "하나\n++둘\n셋\n", "[T-001] 1")
        second = self.commit("src/a.txt", "하나\n++둘\n넷\n", "[T-001] 2")
        self.assertEqual(gitio.diff_lines(self.proj, [first], "src/a.txt"), (["하나", "++둘", "셋"], []))
        # 커밋을 걸쳐 합친다. `+++`·`---` 머리는 빠지고 내용이 `++` 로 시작하는 줄은 남는다
        self.assertEqual(gitio.diff_lines(self.proj, [first, second], "src/a.txt"), (["하나", "++둘", "셋", "넷"], ["셋"]))
        self.assertEqual(gitio.added_lines(self.proj, [second], "src/a.txt"), {"넷"})
        self.assertIsNone(gitio.diff_lines(self.proj, ["0" * 40], "src/a.txt"))


if __name__ == "__main__":
    unittest.main()
