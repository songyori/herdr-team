# herdr-team 9단계(질문 보기 렌더) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 설계 15.3 의 9번을 만든다. "질문 보기" pane(`hteam question-pager`)이 `render.context` 마크다운을 글 그대로 출력하던 것(kakao out-0024: 표 열이 맞지 않고 `##`·코드 펜스·백틱이 그대로)을 터미널 글로 그려 보인다. herdr-team 0.6.0 → 0.6.1, herdr-orch 그대로.

**Architecture:** 새 모듈 `herdr-team/lib/hteam/mdrender.py` 가 마크다운 일부(제목·목록·표·펜스 코드·인라인 코드·굵게·링크·인용·가로줄)를 정한 폭의 터미널 글로 바꾸는 순수 함수 `render(text, width, color)` 를 낸다. `questions.pager` 는 pane 폭을 읽어 그것으로 그리고, 2초마다 답·질문 닫힘을 볼 때 폭이 바뀌었으면 화면을 지우고 다시 그린다. 렌더가 예외를 내면 글 그대로 출력한다.

**Tech Stack:** Python 3.11+ 표준 라이브러리(re, unicodedata, os, shutil, unittest). 외부 렌더러(glow·mdcat·bat·rich)는 쓰지 않는다.

**설계 문서:** `docs/superpowers/specs/2026-11-05-herdr-team-design.md`(이하 "설계"). 9단계 범위는 설계 15.3 의 9번이다. 함께 볼 절: 1장(9단계 사용자 결정 표), 7.4a(`question-pager` 줄, "렌더 규칙", 한계 줄), 15.1(9단계 시험), 15.2(9단계 실환경).

**코드가 기준이다.** 수정은 모두 지금 HEAD(브랜치 `fix/herdr-team-0.6.1-question-render`. 코드는 main 7eb6c1e 와 같고 설계 문서만 다르다)의 코드에 대한 부분 수정이다. 새 모듈은 `mdrender.py` 하나다.

**계획 방식(6–8단계와 같다):** 시험은 전부, 구현은 규칙·인터페이스. 태스크마다 시험 코드는 전부 블록으로 쓴다. 구현은 `**Interfaces:**` 와 `**Rules:**` 로 적고 코드는 구현자가 쓴다. 렌더 규칙의 원문은 설계 7.4a 의 "렌더 규칙" 이다(이 계획은 그 규칙을 되풀이하지 않고 결정만 더한다).

**편집 표기:** `**Edit** \`경로\`` 다음 두 코드 블록은 "찾을 내용"과 "바꿀 내용"이다. 찾을 내용은 적용하는 그 시점의 파일에서 정확히 한 번 나온다. `**Create** \`경로\`` 는 새 파일이다.

## Global Constraints

- Python 3.11 이상, 표준 라이브러리만. 외부 패키지 금지. 커밋 전에 바꾼 `.py` 를 `python3 -m py_compile` 로 확인한다.
- `mdrender` 는 순수 함수만 둔다(파일·환경·터미널을 읽지 않는다). 폭·색 판단은 `questions` 가 한다.
- 설계의 9단계 값(그대로 쓴다): SGR 굵게 `1`, 흐리게 `2`, 인라인 코드 `33`, 2단계 제목 `36`(굵게와 함께 `1;36`), 리셋 `\x1b[0m`. 표 열 최소 폭 `min(본래 폭, 4)`. 펜스 코드 들여쓰기 2칸. 화면 지우기 `\x1b[H\x1b[2J\x1b[3J`. 폭을 못 읽을 때 `shutil.get_terminal_size((80, 24))`. 상자 선 `┌─┬┐ │ ├┼┤ └┴┘`. 목록 표시 `•`. 인용 머리 `│ `. 가로줄 `─`.
- pager 의 다른 동작(끝 줄 `(답하면 이 pane 은 닫힌다)`, 2초 간격, 2시간 상한, 답 파일·열린 질문 확인, SystemExit(0), 파일이 없을 때의 글)은 그대로다.
- 문서·메시지·주석은 한국어. 명령·코드 식별자는 원문.
- 저장소는 공개돼 있다. 커밋 전에 `git grep -n -I -P '/[U]sers/|/private/[t]mp|~[/]Workspace' -- . ':!.codex-reviews'` 가 아무것도 찾지 않아야 한다.
- 버전: Task 3 이 herdr-team 을 `0.6.1` 로 올린다(`herdr-team/lib/hteam/paths.py` 의 `VERSION`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` 의 herdr-team 항목). herdr-orch 는 바꾸지 않는다.
- 작업 브랜치 `fix/herdr-team-0.6.1-question-render` 에서 한다. main 에 직접 커밋하지 않는다. 커밋은 늘 경로 지정, 메시지 끝에 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- 테스트: 모듈을 `(cd herdr-team && python3 -m unittest tests.test_a tests.test_b)` 로 고른다. 전체는 저장소 루트에서 `bash herdr-team/tests/run.sh`(10–20분, 전체 시험 둘을 함께 돌리지 않는다).
- **Codex 교차 검증(CLAUDE.md):** 이 계획은 실행 전에 `scripts/codex-review.sh doc` 로 검토받는다. 각 태스크의 마지막 단계는 커밋이다. 그 뒤 `scripts/codex-review.sh commit <sha>` 를 돌리고(`hc wait <주소> --timeout 3600` 백그라운드), 지적을 코드로 확인해 고치거나 고치지 않는 이유를 적는다. 리뷰 수정 범위는 P0·P1, 기본 경로의 P2, 회귀다.

## File Structure

| 파일 | 바뀌는 것 | 태스크 |
|---|---|---|
| `herdr-team/lib/hteam/mdrender.py` | 새 모듈: `cells`, `render`, `RESET` | 1 |
| `herdr-team/tests/test_mdrender.py` | 새 시험 | 1 |
| `herdr-team/lib/hteam/questions.py` | `_width`, `CLEAR`, `_draw`, `pager` 의 그리기·다시 그리기, 모듈 머리말 | 2 |
| `herdr-team/tests/test_questions.py` | pager 시험 고침·더함 | 2 |
| `README.md` | 질문 보기 줄, 버전 표, "0.6.0 → 0.6.1" | 3 |
| `herdr-team/lib/hteam/paths.py`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | 0.6.1 | 3 |
| `herdr-team/tests/test_cli.py`, `herdr-team/tests/test_setup.py` | 버전·README 시험 | 3 |
| `docs/superpowers/specs/2026-11-05-herdr-team-design.md` | 15.4 의 9단계 실환경 결과 | 4 |

---

### Task 1: 마크다운 렌더러 `mdrender` (설계 7.4a 렌더 규칙)

**Files:**
- Create: `herdr-team/lib/hteam/mdrender.py`
- Create: `herdr-team/tests/test_mdrender.py`

**Interfaces:**
- Produces:
  - `cells(text: str) -> int`: 화면 칸 수. `unicodedata.combining(ch)` 이면 0, `east_asian_width` 가 W·F 면 2, 나머지 1.
  - `render(text: str, width: int, color: bool = False) -> str`: 줄을 `"\n"` 으로 이은 글(끝에 줄바꿈 없음). `width` 는 1 보다 작으면 1 로 본다. 빈 글은 `""`.
  - `RESET = "\x1b[0m"`.

**Rules:** 설계 7.4a "렌더 규칙" 그대로다. 그 위에 정한 것:
- 입력은 `"\n"` 으로 나누고, 펜스 밖 줄(펜스 판정·표·문단 등)은 `expandtabs(4)` 한 줄로 본다. 펜스 안 줄은 원래 줄 그대로(탭 포함) 2칸 들여 쓴다(Codex 계획 리뷰 r2). 블록은 설계에 적은 순서(펜스 → 표 → 빈 줄 → 제목 → 가로줄 → 인용 → 목록 → 문단)로 가른다. 가로줄을 목록보다 먼저 보므로 `- - -`·`* * *` 는 가로줄이다.
- 펜스를 닫는 줄: 여는 펜스 글자와 같은 글자가 여는 개수 이상이고 뒤가 공백뿐(앞 공백 3칸까지). 펜스 안의 빈 줄은 빈 줄로(들여쓰기·색 없이) 둔다.
- 표 판정은 설계대로 "`|` 가 든 줄 + 다음 줄이 같은 칸 수의 구분 줄" 이다. 구분 줄 칸은 `^:?-+:?$`. 행은 빈 줄이 아니고 `|` 가 든 줄이 이어지는 동안이다.
- 표 열 폭: 칸 글(인라인 서식을 적용한 글)의 화면 폭 최댓값이다(모두 빈 열은 0칸, 설계 그대로. Codex 계획 리뷰 r1). 줄이기는 "최소 폭보다 넓은 열 가운데 가장 넓은 열(같으면 왼쪽)을 1칸 줄이기" 를 넘친 칸 수만큼 되풀이한다. 머리 줄은 굵게(`1`), 선은 흐리게(`2`). 행 사이 가로선은 접힌 칸이 하나라도 있을 때만 행과 행 사이(머리 줄 아래 선과 마지막 행 아래는 원래 있다)에 넣는다.
- 제목: 끝의 `#` 들은 앞에 공백이 있거나 본문 전체가 `#` 일 때만 뺀다(`C#` 은 그대로). 1·3–6단계는 굵게(`1`), 2단계는 `1;36`.
- 인라인 짝 찾기: 하나의 정규식으로 왼쪽부터 가장 먼저 시작하는 짝을 쓴다. 같은 자리에서는 코드 → 굵게 → 링크 순이다. 코드: 앞뒤에 백틱이 더 붙지 않은 같은 개수의 백틱 짝(``(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)``). 굵게: `\*\*(.+?)\*\*`. 링크: `\[([^\]\n]+)\]\(([^)\s]+)\)`. 인라인 서식의 SGR 은 감싼 블록의 SGR 뒤에 붙인다(예: 2단계 제목 안의 코드는 `1;36;33`).
- 색: 조각마다 `\x1b[<번호들>m<글>\x1b[0m`. SGR 이 없는 조각은 글 그대로. 색이 켜져 있어도 SGR 을 지운 글은 색이 꺼진 결과와 같다.
- 문단 줄의 앞 공백은 줄 머리(첫 줄과 접은 줄 모두)다(Codex 계획 리뷰 r2).
- 접기의 낱말은 공백(`' '`) 하나 이상으로 나눈 조각이다. 공백만 있는 조각이 줄 앞에 오면 버리고, 넘치면 줄을 바꾸고 버린다. 줄 끝의 공백은 지운다.

- [ ] **Step 1: 시험 쓰기**

**Create** `herdr-team/tests/test_mdrender.py`

```python
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
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_mdrender)`
Expected: `ModuleNotFoundError: No module named 'hteam.mdrender'`(또는 ImportError)

- [ ] **Step 3: 구현**: `herdr-team/lib/hteam/mdrender.py` 를 위 Interfaces·Rules 와 설계 7.4a 렌더 규칙대로 쓴다. 모듈 머리말에 설계 7.4a 9단계와 "전체 마크다운이 아니다, 모르는 문법은 글 그대로" 를 적는다.

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_mdrender)`
Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
python3 -m py_compile herdr-team/lib/hteam/mdrender.py
git add -- herdr-team/lib/hteam/mdrender.py herdr-team/tests/test_mdrender.py
git commit -m "feat(herdr-team): 질문 보기 마크다운 렌더러 mdrender(설계 7.4a 렌더 규칙)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/mdrender.py herdr-team/tests/test_mdrender.py
```

---

### Task 2: pager 가 마크다운을 그리고 폭이 바뀌면 다시 그린다 (설계 7.4a `question-pager`)

**Files:**
- Modify: `herdr-team/lib/hteam/questions.py`
- Modify: `herdr-team/tests/test_questions.py`

**Interfaces:**
- Consumes: `mdrender.render(text, width, color)`(Task 1). 모듈 속성으로 부른다(`from . import mdrender` 뒤 `mdrender.render(...)`. 시험이 바꿔 끼운다).
- Produces(모듈 `questions`):
  - `CLEAR = "\x1b[H\x1b[2J\x1b[3J"`.
  - `_width() -> int`: `os.get_terminal_size(sys.stdout.fileno()).columns`. `OSError`·`ValueError`(파일 번호가 없거나 터미널이 아니다)면 `shutil.get_terminal_size((80, 24)).columns`.
  - `_draw(text: str, width: int, clear: bool) -> None`: `color = sys.stdout.isatty()`. `mdrender.render(text, width, color)` 가 예외(`Exception`)를 내면 `text` 를 그대로 쓴다. `clear` 면 `CLEAR` 를 먼저 쓴다. 그다음 `<글>` + `"\n\n"` + `PAGER_END` + `"\n"` 을 쓰고 flush 한다.
  - `pager(p, oid)`: 시그니처·종료 방식 그대로.

**Rules:**
- `pager`: 파일을 읽어 끝 줄바꿈을 뗀 글을 둔다(파일이 없을 때는 지금 그대로). `width = _width()` 로 `_draw(글, width, False)`. 반복(지금 순서 그대로: 대기 → 답 파일 → 열린 질문)의 끝에 `_width()` 를 다시 읽어 `width` 와 다르면 `width` 를 바꾸고 `_draw(글, width, True)`. 열린 질문을 읽지 못한 `OSError` 는 지금처럼 `continue`(그 회차는 폭을 보지 않는다).
- 파일 글은 처음 한 번만 읽는다(다시 그릴 때도 같은 글).
- 모듈 머리말의 `question-pager` 줄을 "전문을 마크다운으로 그려(mdrender, 설계 7.4a 9단계) 출력하고, 폭이 바뀌면 다시 그린다" 로 고친다.

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/test_questions.py`(가져오기)

```python
import fcntl
import json
import subprocess
import sys
import time
import unittest

from tests.helpers import BIN, MAIN, TeamCase
from hteam import outbox, state
from hteam.paths import Project
```

```python
import contextlib
import fcntl
import io
import json
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests.helpers import BIN, MAIN, TeamCase
from hteam import mdrender, outbox, questions, state
from hteam.paths import Project
```

**Edit** `herdr-team/tests/test_questions.py`(pager 를 띄울 때 폭을 정한다)

```python
    def pager_bg(self, oid):
        """pager 를 띄우고 출력을 파일로 받는다(끝 줄이 나온 것을 보고 상태를 바꾼다, Codex 계획 리뷰 r1)."""
        out = self.tmp / f"pager-{oid}.txt"
        fh = open(out, "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(BIN), "question-pager", oid], stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT, env=self._env("main", None, None), cwd=str(self.proj))
```

```python
    def pager_bg(self, oid, columns="40"):
        """pager 를 띄우고 출력을 파일로 받는다(끝 줄이 나온 것을 보고 상태를 바꾼다, Codex 계획 리뷰 r1)."""
        out = self.tmp / f"pager-{oid}.txt"
        fh = open(out, "w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, str(BIN), "question-pager", oid], stdin=subprocess.DEVNULL, stdout=fh,
                                stderr=subprocess.STDOUT, env=self._env("main", None, {"COLUMNS": columns}),
                                cwd=str(self.proj))
```

**Edit** `herdr-team/tests/test_questions.py`(8단계의 글 그대로 시험을 그린 결과 시험으로 바꾼다)

```python
    def test_prints_the_table_and_ends_when_answered(self):
        oid = self.question(ctx="## 표\n| 가 | 1 |")
        proc, out = self.pager_bg(oid)
        self.wait_ready(out)
        self.assertIsNone(proc.poll())
        self.write_answer(oid)
        self.assertEqual(proc.wait(timeout=30), 0)
        text = out.read_text(encoding="utf-8")
        self.assertIn(f"# 질문 보기 {oid}: 시험\n\n## 표\n| 가 | 1 |", text)
        self.assertTrue(text.rstrip().endswith("(답하면 이 pane 은 닫힌다)"), text)
        self.assertNotIn('"ok"', text)  # JSON 봉투를 쓰지 않는다
```

```python
    def test_draws_the_markdown_and_ends_when_answered(self):
        # 설계 7.4a 9단계: 표준 출력이 터미널이 아니면 COLUMNS 폭(30 에서만 접히는 목록 줄로 본다), 색 없음
        oid = self.question(ctx="## 표\n| 가 | 1 |\n|---|---|\n| 나 | 2 |\n- 가나다 라마바 사아자 차카타 파하\n```\n**코드**\n```")
        proc, out = self.pager_bg(oid, columns="30")
        self.wait_ready(out)
        self.assertIsNone(proc.poll())
        self.write_answer(oid)
        self.assertEqual(proc.wait(timeout=30), 0)
        self.assertEqual(out.read_text(encoding="utf-8").split("\n"), [
            f"질문 보기 {oid}: 시험", "", "표",
            "┌────┬───┐", "│ 가 │ 1 │", "├────┼───┤", "│ 나 │ 2 │", "└────┴───┘",
            "• 가나다 라마바 사아자 차카타", "  파하",
            "  **코드**", "", "(답하면 이 pane 은 닫힌다)", ""])  # JSON 봉투도 색도 없다
```

**Edit** `herdr-team/tests/test_questions.py`(파일 끝 앞에 더한다)

```python
if __name__ == "__main__":
    unittest.main()
```

```python
class PagerLoopTest(QuestionCase):
    """pager 반복문(설계 7.4a 9단계, Codex 설계 리뷰 r1): 같은 프로세스에서 부르고 폭 읽기·대기·렌더를 바꿔 끼운다."""

    def run_pager(self, oid, widths, on_sleep):
        out = io.StringIO()
        count = []

        def fake_sleep(_seconds):
            count.append(1)
            on_sleep(len(count))

        with mock.patch.object(questions, "_width", side_effect=lambda: next(widths)), \
                mock.patch.object(questions.time, "sleep", fake_sleep), contextlib.redirect_stdout(out), \
                self.assertRaises(SystemExit) as end:
            questions.pager(self.p, oid)
        self.assertEqual(end.exception.code, 0)
        return out.getvalue(), len(count)

    def test_redraws_on_width_change_and_falls_back_on_render_error(self):
        oid = self.question(ctx="| 가 | 1 |\n|---|---|")
        real = mdrender.render

        def flaky(text, width, color=False):
            if width == 30:
                raise RuntimeError("시험")
            return real(text, width, color)

        def on_sleep(n):
            if n == 3:
                self.write_answer(oid)

        with mock.patch.object(questions.mdrender, "render", flaky):
            text, sleeps = self.run_pager(oid, iter([60, 60, 30, 30]), on_sleep)
        self.assertEqual(sleeps, 3)  # 다시 그린 뒤에도 기다렸고, 셋째 대기에 쓴 답으로 끝났다(Codex 계획 리뷰 r1)
        first, cleared, second = text.partition(questions.CLEAR)
        self.assertEqual(cleared, questions.CLEAR)  # 폭이 같은 회차는 다시 그리지 않고, 바뀐 회차에 한 번 지웠다
        self.assertNotIn(questions.CLEAR, second)
        self.assertEqual(first, "\n".join([f"질문 보기 {oid}: 시험", "", "┌────┬───┐", "│ 가 │ 1 │", "├────┼───┤",
                                           "└────┴───┘", "", questions.PAGER_END, ""]))
        self.assertEqual(second, f"# 질문 보기 {oid}: 시험\n\n| 가 | 1 |\n|---|---|\n\n{questions.PAGER_END}\n")

    def test_ends_when_closed_after_a_redraw(self):
        oid = self.question(ctx="가나다 라마바 사아자 차카타")
        opened = iter([[{"id": oid}], []])
        with mock.patch.object(questions.outbox, "open_questions", side_effect=lambda p: next(opened)) as seen:
            text, sleeps = self.run_pager(oid, iter([60, 20, 20]), lambda n: None)
        self.assertEqual((sleeps, seen.call_count), (2, 2))  # 다시 그린 뒤 둘째 조회에서 닫힘을 보고 끝났다
        body = (self.qdir / f"{oid}.md").read_text(encoding="utf-8").rstrip("\n")
        self.assertNotEqual(mdrender.render(body, 60), mdrender.render(body, 20))  # 두 폭에서 접기가 다르다
        first, cleared, second = text.partition(questions.CLEAR)
        self.assertEqual(cleared, questions.CLEAR)
        self.assertEqual(first, mdrender.render(body, 60) + "\n\n" + questions.PAGER_END + "\n")
        self.assertEqual(second, mdrender.render(body, 20) + "\n\n" + questions.PAGER_END + "\n")


class PagerWidthTest(unittest.TestCase):
    def test_terminal_size_first_then_columns(self):
        # 설계 7.4a 9단계: COLUMNS 가 있어도 터미널 크기가 먼저다(Codex 설계 리뷰 r1)
        class Tty:
            def fileno(self):
                return 1

        with mock.patch.dict(os.environ, {"COLUMNS": "37"}), mock.patch.object(questions.sys, "stdout", Tty()), \
                mock.patch.object(questions.os, "get_terminal_size", return_value=os.terminal_size((91, 30))):
            self.assertEqual(questions._width(), 91)
        with mock.patch.dict(os.environ, {"COLUMNS": "37"}), mock.patch.object(questions.sys, "stdout", io.StringIO()):
            self.assertEqual(questions._width(), 37)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_questions)`
Expected: `test_draws_the_markdown_and_ends_when_answered` 가 글 그대로 출력이라 FAIL, `PagerLoopTest`·`PagerWidthTest` 가 `AttributeError`(`_width`·`CLEAR`·`mdrender` 없음).

- [ ] **Step 3: 구현**: `herdr-team/lib/hteam/questions.py` 를 위 Interfaces·Rules 대로 고친다(`import os`·`shutil`, `from . import herdr, mdrender, outbox`).

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_questions tests.test_mdrender tests.test_hooks)`
Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
python3 -m py_compile herdr-team/lib/hteam/questions.py
git add -- herdr-team/lib/hteam/questions.py herdr-team/tests/test_questions.py
git commit -m "feat(herdr-team): 질문 보기 pane 이 마크다운을 그리고 폭이 바뀌면 다시 그린다(설계 7.4a 9단계)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- herdr-team/lib/hteam/questions.py herdr-team/tests/test_questions.py
```

---

### Task 3: README 와 0.6.1 (설계 15.3 의 9번 2)

**Files:**
- Modify: `README.md`, `herdr-team/lib/hteam/paths.py`, `herdr-team/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Modify: `herdr-team/tests/test_cli.py`, `herdr-team/tests/test_setup.py`

**Rules:**
- 버전 셋을 `0.6.1` 로. README 첫 표의 herdr-team 버전도 `0.6.1`.
- README herdr-team 절의 질문 표시 줄(`  - 관제·기획자 질문의 표(\`render.context\`)는 훅이 선택 창 오른쪽 미리보기에 넣는다.` 로 시작하는 줄) 끝에 문장을 더한다: ` "질문 보기" pane 은 마크다운(제목·목록·표·코드)을 그 pane 폭에 맞춰 그리고, pane 폭이 바뀌면 다시 그린다.`
- README "이미 세팅한 프로젝트 업그레이드" 의 `#### 0.5.0 → 0.6.0` 바로 앞에 `#### 0.6.0 → 0.6.1` 절을 더한다(아래 원문).

**Edit** `README.md`

```markdown
#### 0.5.0 → 0.6.0

herdr-orch 는 그대로(0.3.0)다.
```

```markdown
#### 0.6.0 → 0.6.1

herdr-orch 는 그대로(0.3.0)다. "질문 보기" pane 이 마크다운을 글 그대로 보이던 것을 고쳤다(제목·목록·표·코드를 pane 폭에 맞춰 그리고, 폭이 바뀌면 다시 그린다).

1. 플러그인을 올린다(`claude plugin marketplace update herdr-team`, `claude plugin update herdr-team@herdr-team`).
2. 메인 세션을 새로 연다(`/exit` 뒤 같은 폴더에서 다시 연다). 질문 보기는 메인 세션 훅의 플러그인 경로로 뜬다.

`hteam upgrade`·`CLAUDE.md` 수정·관제 다시 띄우기는 필요 없다(관제는 질문 보기를 쓰지 않는다). 이미 떠 있는 질문 보기 pane 은 0.6.0 그대로다: 같은 터미널에서 메인 세션만 새로 열면 그 질문을 다시 물어도 같은 pane 이 남는다. 그 질문에 답하면 닫히고 다음 질문부터 새로 그린다. 바로 바꾸려면 그 pane 을 닫고 다시 묻는다.

#### 0.5.0 → 0.6.0

herdr-orch 는 그대로(0.3.0)다.
```

- [ ] **Step 1: 시험 쓰기**

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.6.0"))
```

```python
        self.assertEqual((code, out["ok"], out["version"]), (0, True, "0.6.1"))
```

**Edit** `herdr-team/tests/test_cli.py`

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.6.0"})
```

```python
        self.assertEqual({VERSION, plugin["version"], entry["version"]}, {"0.6.1"})
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.assertEqual(json.loads(out.stdout)["version"], "0.6.0")
```

```python
        self.assertEqual(json.loads(out.stdout)["version"], "0.6.1")
```

**Edit** `herdr-team/tests/test_setup.py`

```python
        self.assertIn("#### 0.5.0 → 0.6.0", readme)
        self.assertLess(readme.index("#### 0.5.0 → 0.6.0"), readme.index("#### 0.4.0 → 0.5.0"))
```

```python
        self.assertIn("#### 0.5.0 → 0.6.0", readme)
        self.assertLess(readme.index("#### 0.5.0 → 0.6.0"), readme.index("#### 0.4.0 → 0.5.0"))
        # 9단계(0.6.1): 플러그인과 새 메인 세션만. 떠 있는 0.6.0 보기 안내(Codex 설계 리뷰 r1)
        self.assertLess(readme.index("#### 0.6.0 → 0.6.1"), readme.index("#### 0.5.0 → 0.6.0"))
        patch = readme[readme.index("#### 0.6.0 → 0.6.1"):readme.index("#### 0.5.0 → 0.6.0")]
        self.assertIn("메인 세션을 새로 연다", patch)
        self.assertIn("관제 다시 띄우기는 필요 없다", patch)
        self.assertIn("이미 떠 있는 질문 보기 pane 은 0.6.0 그대로다", patch)
        self.assertIn("pane 폭이 바뀌면 다시 그린다", readme)
```

- [ ] **Step 2: 시험이 실패하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_cli tests.test_setup)`
Expected: 버전 셋과 README 시험이 FAIL.

- [ ] **Step 3: 구현**: 위 Rules 대로 README·버전 셋을 고친다.

- [ ] **Step 4: 시험이 통과하는지 본다**

Run: `(cd herdr-team && python3 -m unittest tests.test_cli tests.test_setup tests.test_wording)`
Expected: `OK`

- [ ] **Step 5: 커밋**

```bash
git add -- README.md herdr-team/lib/hteam/paths.py herdr-team/.claude-plugin/plugin.json .claude-plugin/marketplace.json herdr-team/tests/test_cli.py herdr-team/tests/test_setup.py
git commit -m "docs(herdr-team): 0.6.1 — README 질문 보기 렌더 줄과 0.6.0 → 0.6.1

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -- README.md herdr-team/lib/hteam/paths.py herdr-team/.claude-plugin/plugin.json .claude-plugin/marketplace.json herdr-team/tests/test_cli.py herdr-team/tests/test_setup.py
```

---

### Task 4: 실환경 확인과 기록 (설계 15.2 의 9단계, 컨트롤러가 한다)

운영 규칙은 8단계와 같다: 사용자 hc core 를 멈추거나 다시 띄우지 않는다(`hc server stop|restart`, `hc update` 금지), 새 `HC_SESSION`·XDG 상태 경로를 만들지 않는다, 시험이 띄운 space·터미널만 끝내고 지운다, `hc run` 은 늘 `--no-notify`, 사용자 터미널에 보내지 않는다, 플러그인을 설치·업데이트하지 않는다.

- [ ] **Step 1: 질문 보기 렌더(15.2 9단계 1)**: 버리는 시험 프로젝트(빈 git 저장소에 `hteam scaffold`)에 kakao out-0024 와 같은 꼴의 열린 outbox `question`(시험의 `question` 과 같이 `outbox.append`)과 질문 보기 파일(`# 질문 보기 <id>: <header>` 와 빈 줄, 그 글)을 만든다. 시험 space 의 셸 터미널(`hc run --bg --no-notify`)에서 그 터미널을 메인으로 `hteam --root <시험> question-view <id>` 를 부른다(`HC_TERMINAL_ID` 는 그 터미널). 그 오른쪽에 pager pane 이 뜨는지, `herdr-app shot` 으로 표 선이 열마다 맞고 `##`·펜스·백틱이 보이지 않으며 색이 있는지 본다. `pane.zoom` 으로 pager pane 을 키웠다 되돌려 2초 안에 새 폭으로 다시 그려지고 앞 화면이 남지 않는지 본다. 답 파일을 쓰면 pane 이 닫히고 터미널이 지워지는지 본다.
- [ ] **Step 2: 회귀(15.2 9단계 2)**: 전체 시험(`bash herdr-team/tests/run.sh`, `bash herdr-orch/tests/run.sh`, 하나씩 백그라운드).
- [ ] **Step 3: 기록**: 설계 15.4 에 "9단계 (2026-11-…)" 절을 더한다(환경, 본 것, 결과, 발견한 문제와 처리). 경로 지정 커밋 `docs: herdr-team 9단계 실환경 확인 결과`.
- [ ] **Step 4: 브랜치 리뷰**: 최종 코드 리뷰(서브에이전트)와 `scripts/codex-review.sh base main`(최대 3라운드, P0·P1 이 남지 않을 때까지). 그 뒤 main 병합은 사용자에게 묻는다.
