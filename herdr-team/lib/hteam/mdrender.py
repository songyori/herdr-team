"""질문 보기 pane 의 마크다운 그리기(설계 7.4a 렌더 규칙, 9단계).

`render(text, width, color)` 는 render.context 에 나오는 꼴(제목·목록·표·펜스 코드·인라인 코드·굵게·링크·인용·가로줄)을
터미널 글로 바꾼다. 전체 마크다운이 아니다. 모르는 문법은 글 그대로 둔다. 표준 라이브러리만 쓰는 순수 함수다.
"""
from __future__ import annotations

import re
import unicodedata

BOLD, DIM, CODE, H2 = "1", "2", "33", "36"  # SGR 번호. 칸마다 RESET 으로 끝낸다
RESET = "\x1b[0m"
MIN_COL = 4  # 표 열을 줄일 때 아래 한도(본래 폭이 더 작으면 본래 폭)

FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.*)$")
HR_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
QUOTE_RE = re.compile(r"^ {0,3}> ?(.*)$")
BULLET_RE = re.compile(r"^([ \t]*)([-*+])[ \t]+(.*)$")
NUMBER_RE = re.compile(r"^([ \t]*)(\d{1,9}[.)])[ \t]+(.*)$")
SEP_CELL_RE = re.compile(r"^:?-+:?$")
PIPE_RE = re.compile(r"(?<!\\)\|")
INLINE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)"  # 코드: 같은 개수 백틱 짝
                       r"|\*\*(.+?)\*\*"  # 굵게: 안이 비지 않은 짝
                       r"|\[([^\]\n]+)\]\(([^)\s]+)\)")  # 링크

Span = tuple[str, tuple[str, ...]]  # (글, SGR 번호들)


def cells(text: str) -> int:
    """화면 칸 수: 동아시아 넓은 글자(W·F) 2칸, 결합 문자 0칸, 나머지 1칸(모호 폭 A 는 1칸)."""
    return sum(0 if unicodedata.combining(ch) else 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def inline(text: str, base: tuple[str, ...] = ()) -> list[Span]:
    """인라인 서식을 조각으로 가른다. 왼쪽부터 가장 먼저 시작하는 짝(같은 자리면 코드·굵게·링크 순)을 쓴다."""
    out: list[Span] = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            out.append((text[pos:m.start()], base))
        if m.group(1) is not None:
            code = m.group(2)
            if len(code) >= 2 and code[0] == " " and code[-1] == " " and code.strip():
                code = code[1:-1]
            out.append((code, base + (CODE,)))
        elif m.group(3) is not None:
            out.append((m.group(3), base + (BOLD,)))
        else:
            out.append((m.group(4), base))
            out.append((f" ({m.group(5)})", base + (DIM,)))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], base))
    return [s for s in out if s[0]]


def _tokens(spans: list[Span]) -> list[tuple[bool, list[Span]]]:
    """조각을 (공백인가, 조각들) 덩어리로 가른다. 낱말은 서식 경계를 가로지른다(`**회원**입니다` 는 한 낱말)."""
    out: list[tuple[bool, list[Span]]] = []
    for text, st in spans:
        for part in re.split(r"( +)", text):
            if not part:
                continue
            space = part.startswith(" ")
            if out and out[-1][0] == space:
                out[-1][1].append((part, st))
            else:
                out.append((space, [(part, st)]))
    return out


def wrap(spans: list[Span], avail: int) -> list[list[Span]]:
    """조각을 avail 칸 줄들로 접는다. 공백에서 끊고, 줄 끝·줄 앞 공백은 뺀다. 한 줄보다 긴 낱말은 글자에서 자른다."""
    avail = max(1, avail)
    lines: list[list[Span]] = [[]]
    used = 0

    def put(t: str, st: tuple[str, ...]) -> None:
        line = lines[-1]
        if line and line[-1][1] == st:
            line[-1] = (line[-1][0] + t, st)
        else:
            line.append((t, st))

    def newline() -> None:
        nonlocal used
        lines.append([])
        used = 0

    for space, pieces in _tokens(spans):
        w = sum(cells(t) for t, _ in pieces)
        if space:
            if used == 0:
                continue  # 줄 앞 공백은 뺀다
            if used + w <= avail:
                for t, st in pieces:
                    put(t, st)
                used += w
            else:
                newline()
            continue
        if used and used + w > avail and w <= avail:
            newline()  # 낱말이 다음 줄에는 들어간다
        if used + w <= avail:
            for t, st in pieces:
                put(t, st)
            used += w
            continue
        for t, st in pieces:  # 한 줄보다 긴 낱말: 글자에서 자른다
            for ch in t:
                cw = cells(ch)
                if used and used + cw > avail:
                    newline()
                put(ch, st)
                used += cw
    return [_rstrip(line) for line in lines]


def _rstrip(line: list[Span]) -> list[Span]:
    while line and not line[-1][0].strip():
        line = line[:-1]
    if line:
        t, st = line[-1]
        line = line[:-1] + [(t.rstrip(" "), st)]
    return line


def _plain(line: list[Span]) -> str:
    return "".join(t for t, _ in line)


def _paint(line: list[Span], color: bool) -> str:
    if not color:
        return _plain(line)
    return "".join(f"\x1b[{';'.join(st)}m{t}{RESET}" if st else t for t, st in line)


def _block(spans: list[Span], width: int, first: list[Span], rest: list[Span], color: bool) -> list[str]:
    """줄 머리(first, 둘째 줄부터 rest)를 붙여 접은 줄들."""
    head = cells(_plain(first))
    out = []
    for i, line in enumerate(wrap(spans, width - head)):
        out.append(_paint((first if i == 0 else rest) + line, color))
    return out


def split_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in PIPE_RE.split(s)]


def _separator(line: str, n: int) -> list[str] | None:
    """표 구분 줄이면 열마다 정렬(left·center·right), 아니면 None."""
    if "|" not in line:
        return None
    parts = split_cells(line)
    if len(parts) != n or not all(SEP_CELL_RE.match(p) for p in parts):
        return None
    return ["center" if p.startswith(":") and p.endswith(":") else "right" if p.endswith(":") else "left"
            for p in parts]


def table(header: list[str], aligns: list[str], rows: list[list[str]], width: int, color: bool) -> list[str]:
    n = len(header)
    grid = [[inline(c, (BOLD,)) for c in header]] + [[inline(c) for c in (r + [""] * n)[:n]] for r in rows]
    natural = [max(cells(_plain(row[j])) for row in grid) for j in range(n)]
    widths = natural[:]
    floor = [min(w, MIN_COL) for w in natural]
    over = sum(widths) + 3 * n + 1 - width
    while over > 0:
        j = max((j for j in range(n) if widths[j] > floor[j]), key=lambda j: widths[j], default=None)
        if j is None:
            break  # 최소 폭으로도 넘는다: 그대로 그린다(터미널이 접는다)
        widths[j] -= 1
        over -= 1
    wrapped = [[wrap(cell, widths[j]) for j, cell in enumerate(row)] for row in grid]
    ruled = any(len(c) > 1 for row in wrapped for c in row)

    def rule(left: str, mid: str, right: str) -> str:
        return _paint([(left + mid.join("─" * (w + 2) for w in widths) + right, (DIM,))], color)

    def lines_of(row: list[list[list[Span]]]) -> list[str]:
        out = []
        for k in range(max(len(c) for c in row)):
            parts: list[Span] = [("│", (DIM,))]
            for j, c in enumerate(row):
                line = c[k] if k < len(c) else []
                pad = widths[j] - cells(_plain(line))
                left = pad // 2 if aligns[j] == "center" else pad if aligns[j] == "right" else 0
                parts += [(" " + " " * left, ())] + line + [(" " * (pad - left) + " ", ()), ("│", (DIM,))]
            out.append(_paint(parts, color))
        return out

    out = [rule("┌", "┬", "┐")] + lines_of(wrapped[0]) + [rule("├", "┼", "┤")]
    for i, row in enumerate(wrapped[1:]):
        if i and ruled:
            out.append(rule("├", "┼", "┤"))
        out += lines_of(row)
    return out + [rule("└", "┴", "┘")]


def render(text: str, width: int, color: bool = False) -> str:
    """마크다운 글을 width 칸 터미널 글로 그린다(설계 7.4a 렌더 규칙). color 면 ANSI SGR 을 쓴다."""
    width = max(1, int(width))
    raw = text.split("\n")
    lines = [line.expandtabs(4) for line in raw]  # 펜스 밖은 탭을 공백으로. 펜스 안은 raw 그대로 쓴다
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = FENCE_RE.match(line)
        if m:
            mark = m.group(1)
            close = re.compile(r"^ {0,3}" + re.escape(mark[0]) + "{" + str(len(mark)) + r",}[ \t]*$")
            i += 1
            while i < len(lines) and not close.match(lines[i]):
                out.append(_paint([("  " + raw[i], (DIM,))], color) if raw[i] else "")
                i += 1
            i += 1  # 닫는 펜스(없으면 끝)
            continue
        if "|" in line and i + 1 < len(lines):
            header = split_cells(line)
            aligns = _separator(lines[i + 1], len(header))
            if aligns is not None:
                j = i + 2
                rows = []
                while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                    rows.append(split_cells(lines[j]))
                    j += 1
                out += table(header, aligns, rows, width, color)
                i = j
                continue
        if not line.strip():
            out.append("")
        elif (m := HEADING_RE.match(line)):
            body = re.sub(r"(^|[ \t]+)#+[ \t]*$", "", m.group(2)).strip()
            style = (BOLD, H2) if len(m.group(1)) == 2 else (BOLD,)
            out += _block(inline(body, style), width, [], [], color)
        elif HR_RE.match(line):
            out.append(_paint([("─" * width, (DIM,))], color))
        elif (m := QUOTE_RE.match(line)):
            bar = [("│ ", (DIM,))]
            out += _block(inline(m.group(1)), width, bar, bar, color)
        elif (m := BULLET_RE.match(line)) or (m := NUMBER_RE.match(line)):
            mark = "•" if m.group(2) in "-*+" else m.group(2)
            first = m.group(1) + mark + " "
            out += _block(inline(m.group(3)), width, [(first, ())], [(" " * cells(first), ())], color)
        else:
            body = line.lstrip(" ")
            head = [(line[:len(line) - len(body)], ())] if body != line else []  # 들여쓰기는 줄 머리(접은 줄도)
            out += _block(inline(body.rstrip()), width, head, head, color)
        i += 1
    return "\n".join(out)
