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
                 "저장하고, 보낸다": '쉼표 "고,"',
                 # 13단계(설계 11.14 의 2)
                 "잠시 뒤 문제가 발생했습니다": '상용구 오류 "문제가 발생했습니다"', "오류가 발생했습니다": '상용구 오류 "오류가 발생했습니다"',
                 "문제가 생겼습니다": '상용구 오류 "문제가 생겼습니다"', "당신의 계정": '2인칭 "당신의"', "당신이 고른": '2인칭 "당신"',
                 "성공적으로 저장했어요": '상투어 "성공적으로"', "다양한 기능": '상투어 "다양한"', "효율적인 관리": '상투어 "효율적"',
                 "원활한 결제": '상투어 "원활"', "한눈에 보는 요약": '상투어 "한눈에"', "손쉽게 시작": '상투어 "손쉽게"',
                 "간편하게 결제": '상투어 "간편하게"', "올인원 앱": '상투어 "올인원"', "차원이 다른 속도": '상투어 "차원이 다른"',
                 "정보를 가지고 있어요": '번역투 "가지고 있"', "관리자에 의해 지워졌어요": '번역투 "에 의해"',
                 "화면에서의 동작": '번역투 "에서의"', "앱으로의 이동": '번역투 "으로의"', "시사하는 바가 크다": '번역투 "시사하는 바"',
                 "주목할 만하다": '번역투 "주목할 만하"'}
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

    def test_nested_fence_example_is_code(self):
        # 펜스 문자와 길이를 따른다: 네 백틱 펜스 안의 세 백틱 줄은 펜스를 닫지 않는다(Codex 계획 리뷰 p13c r1)
        text = "설명 됬다\n````markdown\n```\n예시 됬다\n```\n````\n뒤 됬다\n  ~~~\n  들여 쓴 예시 됬다\n  ~~~\n"
        self.assertEqual([x.split(":", 2)[1] for x in self.found(text, "docs/user/a.md")], ["1", "7"])
        self.assertEqual([n for n, _, _ in visible_lines("docs/user/a.md", text)], [1, 7])

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

    def test_excerpt_is_around_the_match(self):
        # 설계 11.14 의 2: 줄 앞 60자 대신 일치 위치 앞뒤 30자(시안 HTML 의 수천 자 줄에서 위치를 찾게)
        text = 'const a = "' + "가" * 80 + '됬";'
        self.assertEqual(self.found(text), ['src/app.tsx:1: 오탈자 "됬"(…' + "가" * 30 + '됬";)'])
        text = 'x = "' + "가" * 40 + "됬" + "나" * 40 + '"'
        self.assertEqual(self.found(text)[0].split("(", 1)[1], "…" + "가" * 30 + "됬" + "나" * 30 + "…)")
        # Markdown 의 인라인 코드는 같은 길이의 공백으로 바꿔 보므로 발췌 위치가 맞다
        self.assertEqual(self.found("앞 `코드` 됬다\n", "docs/user/a.md"), ['docs/user/a.md:1: 오탈자 "됬"(앞 `코드` 됬다)'])

    def test_repeat_counts_per_file(self):
        text = ('a = "A가 아니라 B예요";\nb = "C가 아니라 D예요";\n' + 'c = "카드를 통해 결제해요";\n' * 2
                + 'd = "앱을 통해 받아요";\n' + 'e = "결제에 대해 알려요";\n' * 2)
        self.assertEqual(self.found(text), ['src/app.tsx:1: 반복 "아니라" 2번(줄: 1, 2)',
                                            'src/app.tsx:3: 반복 "을 통해·를 통해" 3번(줄: 3, 4, 5)'])
        self.assertEqual(self.found('a = "이것이다 저것이다";\nb = "그것입니다";\n'),
                         ['src/app.tsx:1: 반복 "것이다·것입니다" 3번(줄: 1, 2)'])
        self.assertEqual(self.found('a = "에 대해 에 대해";\nb = "아니라";\n'), [])  # 문턱 아래

    def test_data_sample_content_is_not_checked(self):
        text = ('<li data-sample>사용자 댓글: 완료됬어요\n여러 줄 됬어요</li>\n<li>저장됬어요</li>\n'
                '<div data-sample="1"><div>안쪽됬</div>바깥됬</div>\n<p data-sample />자기 닫음됬\n'
                '<p data-sample-id="x">표시 아님됬</p>\n')
        found = self.found(text, "docs/design/screens/home/index.html")
        self.assertEqual([x.split(":", 2)[1] for x in found], ["3", "4", "5", "6"])
        self.assertIn('오탈자 "됬"(…ta-sample="1"><div>안쪽됬</div>바깥됬</div>)', found[1])  # 발췌는 줄 원문이다
        self.assertEqual(len(self.found("<p data-sample>됬</p>\n", "docs/user/a.md")), 1)  # Markdown 은 보지 않는다
        self.assertEqual(textlint.mask_samples("<b data-sample>가\n나</b>끝"), "<b data-sample> \n </b>끝")
        self.assertEqual(textlint.mask_samples("<b data-sample>닫지 않음"), "<b data-sample>닫지 않음")
        # 속성 이름이 정확히 data-sample 일 때만이다. 속성 값 안의 글자는 이름이 아니다(Codex 계획 리뷰 p13c r2)
        real = ('<p class="data-sample">저장됬어요</p>\n<p title=\'data-sample 예시\'>저장됬어요</p>\n'
                '<p data-sample-id="x">저장됬어요</p>\n<Item onClick={() => a > b} data-sample>가짜됬</Item>\n'
                '<img data-sample src="a.png">이미지 뒤됬\n<li {...props} DATA-SAMPLE>가짜됬</li>\n')
        found = self.found(real, "src/app.tsx")
        self.assertEqual([x.split(":", 2)[1] for x in found], ["1", "2", "3", "5"])

    def test_sample_mark_ignores_tags_in_comments_and_attribute_values(self):
        # 주석·속성 값 안의 태그 모양 글은 사람 글 표시가 아니다(Codex p13c Task 5 리뷰)
        rel = "docs/design/screens/home/index.html"
        self.assertEqual(self.found("<!-- <p data-sample> 예시 -->\n<p>저장됬어요</p>\n", rel),
                         [f'{rel}:2: 오탈자 "됬"(<p>저장됬어요</p>)'])
        self.assertEqual(len(self.found("{/* <p data-sample> 예시 */}\n<p>저장됬어요</p>\n", "src/app.tsx")), 1)
        attr = '<a title="<p data-sample>">x</a><p>저장됬어요</p>\n'
        self.assertEqual(len(self.found(attr, "src/app.tsx")), 1)
        self.assertEqual(len(self.found(attr, "a.html")), 1)
        self.assertEqual(len(self.found("<!-- 닫지 않음 <p data-sample>\n<p>저장됬어요</p>\n", "a.html")), 1)
        self.assertEqual(self.found("<!-- 메모 --><p data-sample>가짜됬</p>\n", "a.html"), [])  # 주석 뒤 진짜 표시는 지운다

    def test_comment_end_whitespace_and_void_attribute_values(self):
        # JSX 주석은 `*/` 와 `}` 사이 공백·줄바꿈이 있어도 닫힌다. 빈 요소 속성 값 안의 `<!--` 는 주석이 아니다(Codex 회귀)
        for comment in ("{/* c */ }", "{/* c */\n}"):
            self.assertEqual(self.found(comment + "\n<p data-sample>가짜됬</p>\n", "src/app.tsx"), [])
        self.assertEqual(self.found('<input value="<!--">\n<p data-sample>가짜됬</p>\n', "a.html"), [])
        self.assertEqual(len(self.found("{/* c */ }\n<p>저장됬어요</p>\n", "src/app.tsx")), 1)

    def test_component_names_are_case_sensitive(self):
        self.assertEqual(self.found('<Link href="/profile" data-sample>댓글이 등록됬어요</Link>\n', "src/app.tsx"), [])
        self.assertEqual(self.found("<Input data-sample>가짜됬</Input>\n", "src/app.tsx"), [])
        self.assertEqual(len(self.found('<link rel="x" data-sample>저장됬어요\n', "a.html")), 1)  # .html 은 빈 요소 link
        self.assertEqual(self.found("<P data-sample>가짜됬</p>\n", "a.html"), [])  # .html 은 대소문자를 가리지 않는다
        self.assertEqual(len(self.found("<Item data-sample>가짜됬</item>\n", "src/app.tsx")), 1)  # 컴포넌트는 가린다
        self.assertEqual(len(self.found('<link rel="x" data-sample>저장됬어요\n', "src/app.tsx")), 1)  # 소문자는 빈 요소

    def test_excerpt_stays_linear_on_long_lines_with_many_hits(self):
        import time
        line = "<p>가 됬 아니라 </p>" * 100000
        start = time.monotonic()
        rows = textlint.added_rows("src/app.tsx", line, {line})
        found = textlint.scan_rows("src/app.tsx", rows, [])
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(len(found), 100001)  # 오탈자 10만 + 반복 집계 한 줄
        self.assertEqual(textlint.excerpt("  ab cd  ", 3, 4), "ab cd")
        self.assertEqual(textlint.excerpt("x" * 40 + "됬" + "y" * 40, 40, 41), "…" + "x" * 30 + "됬" + "y" * 30 + "…")

    def test_sample_scan_stays_linear(self):
        # 빈 요소와 닫히지 않은 요소가 많아도 닫는 태그를 찾으려 파일 끝까지 다시 훑지 않는다(Codex 계획 리뷰 p13c r2)
        import time
        voids = '<img data-sample src="avatar.png"><p>저장했어요</p>\n' * 25000
        unclosed = "<div data-sample><p>저장했어요</p>\n" * 25000
        for text in (voids, unclosed):
            start = time.monotonic()
            rows = textlint.visible_lines("docs/design/screens/home/index.html", text)
            self.assertLess(time.monotonic() - start, 1.5, text[:20])
            self.assertEqual(len(rows), 25000)  # 빈 요소·닫히지 않은 요소는 아무것도 지우지 않는다

    def test_long_lines_stay_linear(self):
        # 마침표 없는 긴 줄에서 복붙 문장 찾기와 종결 낱말 찾기가 제곱 시간이 되지 않는다(Codex 계획 리뷰 p13c r1)
        import time
        spaced = "a = '" + "가나다 라마바 " * 25000 + "'"  # 글자 20만(약 200 KB 이상), 마침표 없음
        solid = "b = '" + "가" * 200000 + "x"  # 띄어 쓰지 않은 한글, 따옴표로 닫지 않음
        for line in (spaced, solid):
            start = time.monotonic()
            rows = textlint.added_rows("src/app.tsx", line, {line})
            textlint.scan_rows("src/app.tsx", rows, [])
            self.assertEqual(textlint.copies([("src/app.tsx", rows)]), [])
            self.assertEqual(textlint.labels([("src/app.tsx", rows)]), [])
            self.assertLess(time.monotonic() - start, 1.5, line[:10])


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
            "docs/design/system/README.md", "docs/design/screens/home/notes.md",
            "docs/design/screens/home/artifact/project/Home.dc.html",  # 10단계: 화면 아티팩트 파일(설계 11.7)
            "docs/design/screens/home/artifact/project/canvas.json", "tests/a.md", ".herdr-team/x.md",
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

    def test_copied_sentences_and_label_forms_across_files(self):
        same = "변경 내용은 저장하면 바로 적용됩니다."
        a = self.commit("src/a.tsx", "".join(f'a{n} = "{same}";\n' for n in range(3)) + "<button>저장</button>\n",
                        "[T-001] a")
        b = self.commit("src/b.tsx", "".join(f'b{n} = "{same}";\n' for n in range(2)) + "<button>저장하기</button>\n",
                        "[T-001] b")
        self.assertEqual(text_lint(self.proj, ["src/a.tsx", "src/b.tsx"], [a, b]),
                         [f'src/a.tsx:1: 복붙 "{same}" 5번',
                          'src/b.tsx:3: 라벨 형태 혼용 "저장"·"저장하기"(처음 "저장": src/a.tsx:4)'])
        self.assertEqual(text_lint(self.proj, ["src/a.tsx"], [a]), [])  # 한 파일에 세 번, 라벨은 한 형태
        self.assertEqual(textlint.copies([("x.md", [(1, "", "짧다. 아주 짧은 문장.")] * 6)]), [])  # 10자 미만

    def test_one_megabyte_changed_file(self):
        import time
        line = "<p>저장하면 바로 적용돼요. 다음 화면으로 가요</p>\n"
        n = 1_000_000 // len(line.encode("utf-8"))
        sha = self.commit("src/big.html", line * n, "[T-001] 큰 화면")
        start = time.monotonic()
        found = text_lint(self.proj, ["src/big.html"], [sha])
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(found, [f'src/big.html:1: 복붙 "저장하면 바로 적용돼요." {n}번'])

    def test_comment_and_component_samples_for_targets(self):
        sha = self.commit("src/a.tsx", "{/* <p data-sample> 예시 */}\n<p>저장됬어요</p>\n", "[T-001] 주석")
        self.assertEqual(textlint.targets(self.proj, ["src/a.tsx"]), ["src/a.tsx"])
        self.assertEqual(textlint.added_text_files(self.proj, ["src/a.tsx"], [sha]), ["src/a.tsx"])
        sha = self.commit("src/b.tsx", '<Link href="/p" data-sample>가짜 댓글</Link>\n', "[T-001] 링크")
        self.assertEqual(textlint.targets(self.proj, ["src/b.tsx"]), [])
        self.assertEqual(textlint.added_text_files(self.proj, ["src/b.tsx"], [sha]), [])

    def test_precheck_ignores_end_of_line_comments(self):
        # 줄 끝 주석의 한글은 문구 점검 소절을 요구하지 않는다(최종 리뷰 1). 문자열·마크업 글 안의 한글은 요구한다
        ts = textlint.added_text_files
        sha = self.commit("src/server.ts", "export const b = 2; // 재시도 횟수\nconst c = 3; /* 설명 */ run();\n", "[T-001] 주석")
        self.assertEqual(ts(self.proj, ["src/server.ts"], [sha]), [])
        sha = self.commit("src/msg.ts", 'const msg = "다시 시도해 주세요"\n', "[T-001] 문구")
        self.assertEqual(ts(self.proj, ["src/msg.ts"], [sha]), ["src/msg.ts"])
        sha = self.commit("ci.yml", "run: make # 빌드\n", "[T-001] 워크플로")
        self.assertEqual(ts(self.proj, ["ci.yml"], [sha]), [])
        sha = self.commit("src/url.ts", 'const u = "http://x" // 주석\n', "[T-001] 주소")
        self.assertEqual(ts(self.proj, ["src/url.ts"], [sha]), [])
        self.assertEqual(textlint.strip_eol_comment("src/url.ts", 'const u = "http://x" // 주석'), 'const u = "http://x" ')
        self.assertEqual(textlint.strip_eol_comment("a.html", "<p>저장</p> <!-- 메모 -->"), "<p>저장</p>  ")
        self.assertEqual(textlint.strip_eol_comment("a.py", 'x = "a \\" # 안"  # 끝'), 'x = "a \\" # 안"  ')
        sha = self.commit("src/page.html", "<p>저장</p> <!-- 메모 -->\n", "[T-001] 마크업")
        self.assertEqual(ts(self.proj, ["src/page.html"], [sha]), ["src/page.html"])

    def test_precheck_follows_multiline_comments_and_templates(self):
        # 파일 전체를 한 번 훑어 여러 줄 주석은 뺀다. 템플릿 문자열·마크업 본문의 주석 모양 글은 남긴다(최종 리뷰 2 라운드)
        ts = textlint.added_text_files
        sha = self.commit("src/c.ts", "const a = 1;\n/*\n  사용자 정보\n*/\nrun();\n", "[T-001] 여러 줄 주석")
        self.assertEqual(ts(self.proj, ["src/c.ts"], [sha]), [])
        sha = self.commit("src/c.vue", "<template><p>x</p></template>\n<!--\n  설명 주석\n-->\n", "[T-001] 마크업 주석")
        self.assertEqual(ts(self.proj, ["src/c.vue"], [sha]), [])
        sha = self.commit("src/t.tsx", "const faq = `\nFAQ // 저장 방법\n`;\n", "[T-001] 템플릿")
        self.assertEqual(ts(self.proj, ["src/t.tsx"], [sha]), ["src/t.tsx"])
        sha = self.commit("src/n.tsx", "const s = `a ${x /* 설명 */} b`;\n", "[T-001] 식 안 주석")
        self.assertEqual(ts(self.proj, ["src/n.tsx"], [sha]), [])
        sha = self.commit("src/m.html", "<p>/* 저장 */</p>\n", "[T-001] 본문")
        self.assertEqual(ts(self.proj, ["src/m.html"], [sha]), ["src/m.html"])
        sha = self.commit("src/m2.html", "<p>a // 저장</p>\n", "[T-001] 본문 2")
        self.assertEqual(ts(self.proj, ["src/m2.html"], [sha]), ["src/m2.html"])
        sha = self.commit("src/s.vue", "<script>\n// 한글 주석\nrun();\n</script>\n<p>x</p>\n", "[T-001] 스크립트")
        self.assertEqual(ts(self.proj, ["src/s.vue"], [sha]), [])
        sha = self.commit("src/s2.vue", "<script>\nrun(); /* 설명\n여러 줄 */\n</script>\n<p>/* 저장 */</p>\n", "[T-001] 혼합")
        self.assertEqual(ts(self.proj, ["src/s2.vue"], [sha]), ["src/s2.vue"])

    def test_comment_scan_keeps_one_entry_per_line(self):
        ts = textlint.added_text_files
        samples = [
            "<script\n lang=\"ts\">\nrun();\n</script>\n<p>저장</p>\n",
            "<script\n  lang=\"ts\"\n  setup>\nrun();\n</script>\n<p>저장</p>\n",
            "<style\n scoped>\na{}\n</style>\n<p>저장</p>\n",
            "<script\n lang=\"ts\"\n",
            "<div\nclass=\"a\n b\"\n>x</div>\n",
            "<!-- a\nb\nc --><p>저장</p>\n",
            "<p>a</p><!-- 끝나지 않는\n\n",
            "<input placeholder=\"<!-- 저장\n -->\">\n<p>저장</p>",
            "<script \n<script \n",
        ]
        for rel in ("a.html", "a.vue", "a.svelte"):
            for text in samples:
                lines = textlint.comment_free_lines(rel, text)
                self.assertEqual(len(lines), text.count("\n") + 1, (rel, text))
        lines = textlint.comment_free_lines("a.vue", samples[0])
        self.assertEqual(lines[4], "<p>저장</p>")
        sha = self.commit("src/ml.vue", samples[0], "[T-001] 여러 줄 태그")
        self.assertEqual(ts(self.proj, ["src/ml.vue"], [sha]), ["src/ml.vue"])
        three = "<script\n  lang=\"ts\"\n  setup>\nrun();\n</script>\n<p>저장</p>\n"
        sha = self.commit("src/ml3.vue", three, "[T-001] 세 줄 태그")
        self.assertEqual(ts(self.proj, ["src/ml3.vue"], [sha]), ["src/ml3.vue"])

    def test_comment_marks_inside_attribute_values_are_text(self):
        ts = textlint.added_text_files
        sha = self.commit("src/a.html", '<input placeholder="<!-- 저장 -->">\n', "[T-001] 속성")
        self.assertEqual(ts(self.proj, ["src/a.html"], [sha]), ["src/a.html"])
        sha = self.commit("src/b.html", '<a title="<!--">x</a>\n<p>저장</p>\n', "[T-001] 홀로 연")
        self.assertEqual(ts(self.proj, ["src/b.html"], [sha]), ["src/b.html"])
        sha = self.commit("src/c.html", '<p title="<script>">저장</p>\n<p>저장 방법</p>\n', "[T-001] 속성 안 script")
        self.assertEqual(ts(self.proj, ["src/c.html"], [sha]), ["src/c.html"])
        lines = textlint.comment_free_lines("a.html", "<a title='<!--'>x</a>\n<p>저장</p>")
        self.assertEqual(lines[1], "<p>저장</p>")
        # 본문의 아포스트로피는 따옴표가 아니다
        lines = textlint.comment_free_lines("a.html", "<p>it's</p><!-- 주석 --><p>저장</p>")
        self.assertEqual(lines[0], "<p>it's</p> <p>저장</p>")

    def test_unclosed_block_tags_are_linear(self):
        import time
        for rel in ("a.html", "a.vue"):
            for unit in ("<script ", "<style ", "<a \"", "<div "):
                text = unit * (1_000_000 // len(unit))
                start = time.monotonic()
                lines = textlint.comment_free_lines(rel, text)
                self.assertLess(time.monotonic() - start, 1.5, (rel, unit))
                self.assertEqual(len(lines), text.count("\n") + 1)
        # 긴 태그 이름 뒤의 닫히지 않은 따옴표(Codex commit-c1b249b: 이름과 속성이 같은 글자를 두고 되짚어 20초)
        text = ("<" + "a" * 1800 + "\">") * 550 + "\n<p>저장</p>"
        start = time.monotonic()
        lines = textlint.comment_free_lines("a.html", text)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertEqual(lines[-1], "<p>저장</p>")

    def test_comment_scan_is_linear(self):
        import time
        text = "'\"`/*//<!--#${}\\\n" * (1_000_000 // 16)
        for rel in ("a.tsx", "a.vue", "a.yml", "a.html"):
            start = time.monotonic()
            lines = textlint.comment_free_lines(rel, text)
            self.assertLess(time.monotonic() - start, 1.5, rel)
            self.assertEqual(len(lines), text.count("\n") + 1)

    def test_added_text_files_for_the_precheck(self):
        sha = self.commit("src/a.tsx", '// 한글 주석\nconst a = 1;\n', "[T-001] 주석")
        other = self.commit("src/b.tsx", '<p data-sample>가짜 댓글</p>\n<p>저장</p>\n', "[T-001] 화면")
        self.assertEqual(textlint.added_text_files(self.proj, ["src/a.tsx", "src/b.tsx"], [sha, other]), ["src/b.tsx"])
        self.commit("src/c.tsx", '<p data-sample>가짜 댓글</p>\n', "[T-001] 표본만")
        self.assertEqual(textlint.added_text_files(self.proj, ["src/c.tsx"], [self.head()]), [])

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
