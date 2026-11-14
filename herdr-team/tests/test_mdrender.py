"""9단계 질문 보기 렌더(설계 7.4a 렌더 규칙): mdrender.render 의 블록·인라인·표·접기·색."""
import re
import unittest

from tests import helpers  # noqa: F401  lib 를 sys.path 에 넣는다(다른 시험과 같다)
from hteam import mdrender
from hteam.mdrender import cells, render

SGR = re.compile(r"\x1b\[[0-9;]*m")

KAKAO = """# 질문 보기 out-0024: 기획 확정

## 계획 핵심
- 공용 등록 파일을 기능 폴더별 등록으로 나눈다(#5764). 동작은 그대로다.
- 시험 순차 목록: 순차 시험은 *.serial.test.ts 이름으로 가린다.

## 용어집
| 쓰는 표기 | 쓰지 않는 표기 | 메모 |
|---|---|---|
| 이용 정지 | 이용정지, 사용 정지 | 제재 종류 이름(#5550 AC 5) |
| Lot 번호 | 로트 번호 | |
| 회원 코드 | | `XXXX-XXXX` 꼴. C-11 머리, C-12 |
| 다운로드 | | 화면·버튼 이름. 기획 문서 본문의 「내려받기」는 그대로 둔다 |

## 테스트 명령
이 명령은 리뷰 전에 관제 환경에서 자동으로 돈다(Codex 샌드박스 밖, 사용자 권한).
```toml
quick = "pnpm exec vitest related --run --passWithNoTests {files}"
timeout_min = 40
```"""


def lines(text, width=60, **kw):
    return render(text, width, **kw).split("\n")


class BlockTest(unittest.TestCase):
    def test_headings_drop_marks(self):
        self.assertEqual(lines("# 하나\n## 둘 ##\n###### 여섯\n#붙음\n## C#"), ["하나", "둘", "여섯", "#붙음", "C#"])

    def test_lists(self):
        self.assertEqual(lines("- 가\n* 나\n+ 다\n  - 안\n1. 하나\n2) 둘"),
                         ["• 가", "• 나", "• 다", "  • 안", "1. 하나", "2) 둘"])

    def test_list_wraps_under_the_text(self):
        self.assertEqual(lines("- 가나다 라마바 사아자", width=12), ["• 가나다", "  라마바", "  사아자"])
        self.assertEqual(lines("10. 가나다 라마바", width=12), ["10. 가나다", "    라마바"])

    def test_single_star_and_underscore_stay(self):
        self.assertEqual(lines("순차 시험은 *.serial.test.ts 이름, snake_case_name"),
                         ["순차 시험은 *.serial.test.ts 이름, snake_case_name"])

    def test_rule_and_quote(self):
        self.assertEqual(lines("---\n* * *\n> 인용 글", width=10), ["─" * 10, "─" * 10, "│ 인용 글"])
        self.assertEqual(lines("> 가나다 라마바", width=10), ["│ 가나다", "│ 라마바"])

    def test_fences(self):
        self.assertEqual(lines("```toml\na = \"**x**\"\n\n````\n뒤"), ['  a = "**x**"', "", "뒤"])
        self.assertEqual(lines("~~~\n코드\n```\n~~~~\n뒤"), ["  코드", "  ```", "뒤"])
        self.assertEqual(lines("```\n닫지 않음\n# 제목 아님"), ["  닫지 않음", "  # 제목 아님"])
        self.assertEqual(lines("```\n\ta\tb\n```"), ["  \ta\tb"])  # 펜스 안의 탭은 그대로(Codex 계획 리뷰 r2)

    def test_code_lines_are_not_folded(self):
        long = "x" * 80
        self.assertEqual(lines(f"```\n{long}\n```", width=20), ["  " + long])

    def test_paragraph_lines_are_kept_and_folded(self):
        self.assertEqual(lines("첫 줄\n둘째 줄"), ["첫 줄", "둘째 줄"])
        self.assertEqual(lines("가나다 라마바 사아자", width=13), ["가나다 라마바", "사아자"])
        self.assertEqual(lines("- 항목\n  이어지는 설명 글", width=10), ["• 항목", "  이어지는", "  설명 글"])

    def test_long_word_is_cut_at_characters(self):
        self.assertEqual(lines("abcdefghij", width=4), ["abcd", "efgh", "ij"])
        self.assertEqual(lines("가나다", width=5), ["가나", "다"])  # 넓은 글자는 남은 1칸에 넣지 않는다

    def test_very_narrow_width_still_ends(self):
        self.assertEqual(lines("- 가나다", width=2), ["• 가", "  나", "  다"])  # 본문 폭 1칸: 줄마다 한 글자
        self.assertEqual(lines("> ab", width=1), ["│ a", "│ b"])
        self.assertEqual(lines("가나", width=1), ["가", "나"])
        self.assertEqual(lines("가", width=0), ["가"])

    def test_empty(self):
        self.assertEqual(render("", 40), "")


class InlineTest(unittest.TestCase):
    def test_code_bold_link(self):
        self.assertEqual(lines("`a|b` **굵게** [글](https://x.y/z) ``a`b`` ` 공백 `"),
                         ["a|b 굵게 글 (https://x.y/z) a`b 공백"])

    def test_code_is_literal_and_unpaired_marks_stay(self):
        self.assertEqual(lines("`**x**` **열림 `닫힘"), ["**x** **열림 `닫힘"])


class TableTest(unittest.TestCase):
    def test_korean_columns_line_up(self):
        out = lines("| 이름 | 값 |\n|---|---|\n| 가나 | 1 |\n| a | 바뀐 값 |")
        self.assertEqual(out, ["┌──────┬─────────┐",
                               "│ 이름 │ 값      │",
                               "├──────┼─────────┤",
                               "│ 가나 │ 1       │",
                               "│ a    │ 바뀐 값 │",
                               "└──────┴─────────┘"])

    def test_alignment_missing_extra_cells_and_escaped_pipe(self):
        out = lines("| 왼 | 가운데 | 오른 |\n|:--|:---:|--:|\n| a | b | c |\n| x\\|y |\n| 1 | 2 | 3 | 4 |")
        self.assertEqual(out[3:6], ["│ a   │   b    │    c │",
                                    "│ x|y │        │      │",
                                    "│ 1   │   2    │    3 │"])

    def test_escaped_pipe_at_the_end_of_a_row_without_outer_pipe(self):
        out = lines("| a | b |\n|---|---|\n| 1 | 값\\|")
        self.assertEqual(out[3], "│ 1 │ 값| │")

    def test_cell_inline_code(self):
        self.assertIn("│ XXXX-XXXX 꼴 │", lines("| 메모 |\n|---|\n| `XXXX-XXXX` 꼴 |"))

    def test_narrow_table_shrinks_widest_first_and_rules_rows(self):
        out = lines("| 짧음 | 긴 칸 |\n|---|---|\n| a | 가나다 라마바 사아자 |\n| b | c |", width=20)
        self.assertEqual(out, ["┌──────┬───────────┐",
                               "│ 짧음 │ 긴 칸     │",
                               "├──────┼───────────┤",
                               "│ a    │ 가나다    │",
                               "│      │ 라마바    │",
                               "│      │ 사아자    │",
                               "├──────┼───────────┤",
                               "│ b    │ c         │",
                               "└──────┴───────────┘"])
        self.assertTrue(all(cells(line) <= 20 for line in out))

    def test_too_many_columns_keep_the_floor(self):
        out = lines("| " + " | ".join("가나다라" for _ in range(6)) + " |\n|" + "---|" * 6, width=20)
        self.assertEqual(out[0], "┌" + "┬".join("─" * 6 for _ in range(6)) + "┐")  # 열마다 4칸 아래로 줄이지 않는다

    def test_empty_column_is_zero_wide(self):
        self.assertEqual(lines("| | x |\n|---|---|"), ["┌──┬───┐", "│  │ x │", "├──┼───┤", "└──┴───┘"])

    def test_header_only_table(self):
        self.assertEqual(lines("| 가 | 1 |\n|---|---|"), ["┌────┬───┐", "│ 가 │ 1 │", "├────┼───┤", "└────┴───┘"])

    def test_not_a_table(self):
        self.assertEqual(lines("a | b\n그냥 글"), ["a | b", "그냥 글"])
        self.assertEqual(lines("| a | b |\n|---|"), ["| a | b |", "|---|"])  # 칸 수가 다르다


class WholeTest(unittest.TestCase):
    def test_kakao_like_text(self):
        for width in (40, 64, 100):
            out = lines(KAKAO, width=width)
            text = "\n".join(out)
            self.assertNotIn("##", text)
            self.assertNotIn("```", text)
            self.assertNotIn("`XXXX", text)
            self.assertIn("*.serial.test.ts", text)
            code = {'  quick = "pnpm exec vitest related --run --passWithNoTests {files}"'}
            self.assertTrue(all(cells(line) <= width for line in out if line not in code), width)
            table = [line for line in out if line.startswith(("┌", "├", "└", "│"))]
            joints = {tuple(i for i, ch in enumerate(_cols(line)) if ch and ch in "┌┬┐├┼┤└┴┘│") for line in table}
            self.assertEqual(len(joints), 1, width)  # 표의 모든 줄에서 선 자리가 같다

    def test_color_keeps_the_layout(self):
        for width in (20, 64):
            plain = render(KAKAO, width)
            colored = render(KAKAO, width, color=True)
            self.assertIn("\x1b[", colored)
            self.assertEqual(SGR.sub("", colored), plain)
            for line in colored.split("\n"):
                if "\x1b[" in line:
                    self.assertTrue(line.endswith(mdrender.RESET), line)

    def test_color_codes(self):
        self.assertEqual(render("## 제목", 40, color=True), "\x1b[1;36m제목\x1b[0m")
        self.assertEqual(render("`x`", 40, color=True), "\x1b[33mx\x1b[0m")
        self.assertEqual(render("## `x`", 40, color=True), "\x1b[1;36;33mx\x1b[0m")
        self.assertEqual(render("| a |\n|---|", 40, color=True).split("\n"), [
            "\x1b[2m┌───┐\x1b[0m", "\x1b[2m│\x1b[0m \x1b[1ma\x1b[0m \x1b[2m│\x1b[0m", "\x1b[2m├───┤\x1b[0m",
            "\x1b[2m└───┘\x1b[0m"])  # 선은 흐리게, 머리 줄은 굵게


def _cols(line):
    """화면 칸 자리마다 글자(넓은 글자는 두 칸을 차지하고 둘째 칸은 빈 글이다)."""
    out = []
    for ch in line:
        out.append(ch)
        if cells(ch) == 2:
            out.append("")
    return out


if __name__ == "__main__":
    unittest.main()
