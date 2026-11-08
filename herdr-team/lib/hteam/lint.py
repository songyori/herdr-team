"""디자인 자동 검사(설계 11.6): `hteam lint --task T`.

리뷰 대상 커밋이 바꾼 파일에서 AI 티 금지 목록(`.herdr-team/design-rules.md`)의 1(이모지), 2(왼쪽 강조 테두리),
3(파랑·보라 그라디언트) 의심 위치를 찾는다. 결과는 경고다(블록 인용처럼 정당한 쓰임이 있다). 판정은 리뷰어가 한다.
리뷰 프롬프트의 디자인 절(compose.review_prompt)이 시도 기록의 바뀐 파일로 부른다. 표준 라이브러리 정규식만 쓰고
git·hc·horch·codex 를 부르지 않는다(명령 `lint --task` 만 review 의 대상 커밋 계산과 compose 의 절 목록을 거친다).
read_source·cap 은 문구 검사(textlint)도 함께 쓴다.
"""
from __future__ import annotations

import bisect
import colorsys
import re
from pathlib import Path

from .globs import matches_any
from .paths import find_project

DESIGN_ROLES = ("director", "designer", "developer")  # 리뷰 프롬프트에 디자인 절을 넣는 직무(설계 6.2)
SUFFIXES = frozenset({".html", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".md", ".json"})
EXCLUDE = ("docs/design/references.md", "docs/planning/**", "docs/tasks/**", "docs/reviews/**")
MAX_BYTES = 1 << 20  # 이보다 큰 파일(번들·데이터)은 보지 않는다
MAX_FINDINGS = 50  # 리뷰 프롬프트가 커지지 않게 이만큼만 싣는다
SNIPPET = 60

# BMP 에서 기본으로 이모지로 보이는(Emoji_Presentation) 글자. ✓ ★ ❯ ➜ ⬆ ▶ 같은 글자 기호는 넣지 않는다.
_BMP = ("⌚-⌛⏩-⏬⏰⏳◽-◾☔-☕♈-♓♿⚓⚡"
        "⚪-⚫⚽-⚾⛄-⛅⛎⛔⛪⛲-⛳⛵⛺⛽✅"
        "✊-✋✨❌❎❓-❕❗➕-➗➰➿⬛-⬜⭐⭕")
# U+FE0F(이모지 표시 선택자)가 붙은 공백 아닌 글자(▶️ ☀️), U+1F000–U+1FAFF, BMP 이모지. 공백 뒤에 홀로 남은 FE0F 는
# 보이는 것이 없어 잡지 않는다.
EMOJI_RE = re.compile(f"[^\\s]️|[\U0001F000-\U0001FAFF{_BMP}]")

_LEFT_CSS = re.compile(r"\bborder-(?:left|inline-start)\s*:\s*([^;{}\n]+)", re.I)
_LEFT_JS = re.compile(r"\bborder(?:Left|InlineStart)\s*:\s*[\"'`]([^\"'`\n]+)[\"'`]")
_WIDTH_CSS = re.compile(r"\bborder-(?:left|inline-start)-width\s*:\s*([^;{}\n]+)", re.I)
_WIDTH_JS = re.compile(r"\bborder(?:Left|InlineStart)Width\s*:\s*(?:(\d*\.?\d+)(?![\w.])|[\"'`]([^\"'`\n]+)[\"'`])")
_LENGTH = re.compile(r"(?<![\w.#-])(\d*\.?\d+)(px|rem|em)\b", re.I)
# 너비 낱말. 앞뒤가 낱말 글자·하이픈이면(var(--thick) 같은 사용자 정의 속성 이름) 낱말이 아니다.
_WIDTH_WORD = re.compile(r"(?<![\w-])(thin|medium|thick)(?![\w-])", re.I)
_WORD_PX = {"thin": 1.0, "medium": 3.0, "thick": 5.0}
_VISIBLE = re.compile(r"\b(?:solid|dashed|dotted|double|groove|ridge|inset|outset)\b|#[0-9a-f]{3,8}\b"
                      r"|\b(?:rgba?|hsla?|oklch|oklab|lab|lch|color-mix|var)\(", re.I)
# 선을 보이지 않게 하는 낱말. 괄호 밖에 홀로 선 것만 본다(사용자 정의 속성 이름·함수 인자는 뺀다).
_INVISIBLE = re.compile(r"(?<![\w-])(?:transparent|none|hidden)(?![\w-])", re.I)
# Tailwind 왼쪽(border-l)·논리 시작(border-s) 너비: 2~8 또는 임의 값([3px]·[0.25rem], 2px 이상만)
_TW_WIDTH = re.compile(r"(?<![\w-])border-[ls]-(?:[2-8]|\[([^\]\s]+)\])(?![\w-])")
_TW_COLOR = re.compile(r"(?<![\w-])border-(?:[ls]-)?(?:[a-z]+-\d{2,3}|black|white|\[#[0-9a-fA-F]{3,8}\])(?![\w-])")
_TW_BLUE = re.compile(r"(?<![\w-])(?:from|via|to)-(?:blue|indigo|sky)-\d{2,3}(?![\w-])")
_TW_PURPLE = re.compile(r"(?<![\w-])(?:from|via|to)-(?:purple|violet|fuchsia)-\d{2,3}(?![\w-])")
_GRADIENT = re.compile(r"\b(?:repeating-)?(?:linear|radial|conic)-gradient\(", re.I)
_COLOR = re.compile(r"#[0-9a-f]{3,8}\b|\b(?:rgba?|hsla?|oklch)\([^()]*\)|\b[a-z]+\b", re.I)
# Tailwind 클래스 목록: 직접 인용한 class·className 속성 값(여러 줄 가능), `@apply` 문, 그 밖의 JS 문자열 리터럴
# (`{"…"}`·`cn("…")`). 앞의 것이 차지한 자리는 뒤의 것이 다시 보지 않는다.
# 속성 값(HTML·JSX)은 백슬래시가 따옴표를 이스케이프하지 않으니 첫 같은 따옴표에서 끝난다.
_CLASS_ATTR = re.compile(r"\b(?:class|className)\s*=\s*([\"'])(.*?)\1", re.S)
_APPLY = re.compile(r"@apply\b([^;}]*)")
# JS 문자열 리터럴만 `\"` 같은 이스케이프(백슬래시+줄바꿈 줄 이음 포함)를 닫는 따옴표로 보지 않는다.
_LITERAL = re.compile(r"\"((?:\\[\s\S]|[^\"\\\n])*)\"|'((?:\\[\s\S]|[^'\\\n])*)'|`((?:\\[\s\S]|[^`\\])*)`")
# oklch(L C H [/ alpha]). L 은 % 또는 0~1, C 는 숫자(또는 %: 100% = 0.4), H 는 도(deg 생략 가능).
_OKLCH = re.compile(r"oklch\(\s*(\d*\.?\d+)(%?)\s+(\d*\.?\d+)(%?)\s+(\d*\.?\d+)(?:deg)?\s*(?:/\s*\d*\.?\d+%?\s*)?\)")
_BLUE_NAMES = frozenset({"blue", "royalblue", "dodgerblue", "deepskyblue", "cornflowerblue", "steelblue", "navy",
                         "mediumblue", "darkblue", "midnightblue"})
_PURPLE_NAMES = frozenset({"purple", "violet", "indigo", "blueviolet", "darkviolet", "mediumpurple", "rebeccapurple",
                           "darkorchid", "mediumorchid", "orchid", "plum", "magenta", "fuchsia", "slateblue",
                           "mediumslateblue", "darkslateblue"})


def _short(text: str) -> str:
    return " ".join(text.split())[:SNIPPET]


def _px(value: str) -> float:
    """값에 적힌 길이(px·rem·em, rem·em 은 16px)와 너비 낱말(thin 1, medium 3, thick 5) 가운데 가장 큰 px. 없으면 0."""
    found = [float(n) * (16 if unit.lower() in ("rem", "em") else 1) for n, unit in _LENGTH.findall(value)]
    found += [_WORD_PX[w.lower()] for w in _WIDTH_WORD.findall(value)]
    return max(found, default=0.0)


def _invisible(value: str) -> bool:
    """괄호 밖에 transparent·none·hidden 이 홀로 선 낱말로 있나. var(--none), var(--accent, transparent) 는 아니다."""
    depth, outside = 0, []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif depth == 0:
            outside.append(ch)
    return bool(_INVISIBLE.search("".join(outside)))


def left_border(line: str) -> bool:
    """2px 이상의 보이는 왼쪽(시작 쪽) 강조 테두리가 있나: border-left·border-inline-start 선언(CSS, JSX 인라인
    스타일)에 2px 이상과 보이는 선(선 모양·색, 홀로 선 transparent·none·hidden 이 없다), 너비만 준 2px 이상의
    border-left-width 류(JSX 는 숫자 2 이상도). 한 줄만 본다. Tailwind 는 tailwind_left_border."""
    for m in (*_LEFT_CSS.finditer(line), *_LEFT_JS.finditer(line)):
        value = m.group(1)
        if _px(value) >= 2 and _VISIBLE.search(value) and not _invisible(value):
            return True
    if any(_px(m.group(1)) >= 2 for m in _WIDTH_CSS.finditer(line)):
        return True
    for m in _WIDTH_JS.finditer(line):
        number, text = m.groups()
        if (float(number) if number is not None else _px(text)) >= 2:
            return True
    return False


def tailwind_left_border(classes: str) -> bool:
    """한 클래스 목록에 Tailwind border-l·border-s 너비(2~8, 2px 이상 임의 값)와 테두리 색이 함께 있나."""
    wide = any(v is None or _px(v) >= 2 for v in (m.group(1) for m in _TW_WIDTH.finditer(classes)))
    return wide and bool(_TW_COLOR.search(classes))


def class_lists(text: str) -> list[tuple[int, str]]:
    """(시작 위치, 클래스 목록 글) 들. class·className 속성 값(여러 줄 가능), @apply 문, 문자열 리터럴 매치를 모두 담는다.
    서로 겹쳐도 버리지 않는다(후보마다 따로 검사하고 경고를 합친다)."""
    out: list[tuple[int, str]] = []
    for rx, grp in ((_CLASS_ATTR, 2), (_APPLY, 1)):
        out += [(m.start(grp), m.group(grp)) for m in rx.finditer(text)]
    for m in _LITERAL.finditer(text):
        g = next(i for i in (1, 2, 3) if m.group(i) is not None)
        out.append((m.start(g), m.group(g)))
    return out


def _rgb_hue(token: str) -> tuple[float, float, float] | None:
    """(색상각 0~360, 채도 0~1, 밝기 0~1). hex(3·4·6·8자리)·rgb()·hsl() 만 읽는다."""
    if token.startswith("#"):
        digits = token[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits[:3])
        elif len(digits) in (6, 8):
            digits = digits[:6]
        else:
            return None
        r, g, b = (int(digits[i:i + 2], 16) / 255 for i in (0, 2, 4))
    else:
        numbers = re.findall(r"\d*\.?\d+", token)
        if not token.startswith(("rgb", "hsl")) or len(numbers) < 3:
            return None
        if token.startswith("hsl"):
            return float(numbers[0]) % 360, min(float(numbers[1]), 100) / 100, min(float(numbers[2]), 100) / 100
        channels = re.findall(r"(\d*\.?\d+)(%?)", token)[:3]  # 채널마다 퍼센트는 /100, 숫자는 /255
        r, g, b = (min(float(n), 100 if pct else 255) / (100 if pct else 255) for n, pct in channels)
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    return hue * 360, sat, light


def _oklch_family(token: str) -> str | None:
    """oklch 색의 계열. 채도 C 가 0.05 보다 작으면(무채색에 가깝다) None. oklch 색상각은 HSL 과 자가 달라서 200~280°
    를 파랑, 280~330° 를 보라로 본다(Tailwind v4 의 sky·blue·indigo 와 violet·purple·fuchsia)."""
    m = _OKLCH.fullmatch(token)
    if not m:
        return None
    light, light_pct, chroma, chroma_pct, hue = m.groups()
    if float(light) > (100 if light_pct else 1) or float(chroma) * (0.004 if chroma_pct else 1) < 0.05:
        return None
    deg = float(hue) % 360
    return "blue" if 200 <= deg < 280 else "purple" if 280 <= deg < 330 else None


def hue_family(token: str) -> str | None:
    """색 하나가 파랑(190~245°)이면 "blue", 보라(245~300°)면 "purple"(설계 11.6, oklch 는 _oklch_family). 무채색에
    가깝거나 읽지 못하면 None."""
    low = token.lower()
    if low in _BLUE_NAMES:
        return "blue"
    if low in _PURPLE_NAMES:
        return "purple"
    if low.startswith("oklch("):
        return _oklch_family(low)
    color = _rgb_hue(low)
    if color is None:
        return None
    hue, sat, light = color
    if sat < 0.25 or not 0.12 < light < 0.92:
        return None
    return "blue" if 190 <= hue < 245 else "purple" if 245 <= hue < 300 else None


def _body(text: str, start: int) -> str:
    """start(여는 괄호 바로 뒤)부터 짝이 맞는 닫는 괄호 앞까지. 닫히지 않으면 500자에서 자른다."""
    depth, end = 1, min(len(text), start + 500)
    for i in range(start, end):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return text[start:end]


def scan(rel: str, text: str) -> list[str]:
    """한 파일의 의심 위치를 줄 순서로 `파일:줄: 패턴(발췌)` 목록으로."""
    found: list[tuple[int, str]] = []
    starts = [0]  # 줄마다 시작 위치. 그라디언트의 줄 번호를 bisect 로 찾는다(매치마다 처음부터 세지 않는다)
    for number, line in enumerate(text.split("\n"), 1):
        starts.append(starts[-1] + len(line) + 1)
        emoji = EMOJI_RE.search(line)
        if emoji:
            found.append((number, f"이모지({emoji.group(0)})"))
        if left_border(line):
            found.append((number, f"왼쪽 강조 테두리({_short(line)})"))
    # Tailwind 조합은 한 클래스 목록과 물리적 한 줄 둘 다에서 따로 본다. 한 줄에 다른 요소가 섞이면 거짓 경고가 날 수 있다.
    lines = text.split("\n")
    candidates = [(starts[n], line) for n, line in enumerate(lines)] + class_lists(text)
    for pos, classes in candidates:
        if tailwind_left_border(classes):
            first = min(m.start() for m in _TW_WIDTH.finditer(classes))
            found.append((bisect.bisect_right(starts, pos + first), f"왼쪽 강조 테두리({_short(classes)})"))
        blue, purple = _TW_BLUE.search(classes), _TW_PURPLE.search(classes)
        if blue and purple:
            number = bisect.bisect_right(starts, pos + min(blue.start(), purple.start()))
            found.append((number, f"파랑·보라 그라디언트({_short(classes)})"))
    for m in _GRADIENT.finditer(text):
        body = _body(text, m.end())
        if {"blue", "purple"} <= {hue_family(t) for t in _COLOR.findall(body)}:
            number = bisect.bisect_right(starts, m.start())
            found.append((number, f"파랑·보라 그라디언트({_short(m.group(0) + body + ')')})"))
    seen: set[tuple[int, str]] = set()  # (줄, 패턴 이름) 하나에 경고 하나
    out = []
    for number, what in sorted(found, key=lambda x: x[0]):
        if (number, what.split("(", 1)[0]) not in seen:
            seen.add((number, what.split("(", 1)[0]))
            out.append(f"{rel}:{number}: {what}")
    return out


def read_source(root: Path, rel: str) -> str | None:
    """검사할 파일 내용(프로젝트 기준 경로). 파일이 아니거나(없음·삭제·폴더), 1 MiB 를 넘거나, UTF-8 이 아니면 None.
    내용·문구·diff 검사가 함께 쓴다."""
    path = Path(root) / rel
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def cap(items: list[str], limit: int = MAX_FINDINGS) -> list[str]:
    """limit 를 넘으면 앞 limit 건과 마지막 `… 외 N건`."""
    return items if len(items) <= limit else [*items[:limit], f"… 외 {len(items) - limit}건"]


def design_findings(root: Path, files: list[str]) -> list[str]:
    """files(프로젝트 기준 경로) 가운데 검사 대상의 의심 위치(상한 없음). 대상 확장자가 아니거나, 제외
    경로거나, 프로젝트 밖(`../`)이거나, read_source 가 읽지 못하면 보지 않는다."""
    found: list[str] = []
    for rel in files:
        if rel.startswith("../") or Path(rel).suffix.lower() not in SUFFIXES or matches_any(rel, EXCLUDE):
            continue
        text = read_source(root, rel)
        if text is not None:
            found += scan(rel, text)
    return found


def design_lint(root: Path, files: list[str]) -> list[str]:
    """design_findings 를 MAX_FINDINGS 로 자른 것(넘으면 마지막 항목이 `… 외 N건`)."""
    return cap(design_findings(root, files))


def lint_task(p, tid: str) -> dict:
    """태스크의 리뷰 대상 커밋(review.target_commits)이 바꾼 파일을 리뷰 프롬프트와 같은 규칙으로 검사한다. 읽기만 한다.
    findings 는 디자인 절의 경고 목록(디렉터 직무 유무와 관계없이), text_findings 는 문구 절의 경고 목록
    (`.herdr-team/text-rules.md` 가 없으면 None)."""
    from . import compose, review, state  # review·compose 가 이 모듈을 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    st = state.require(p, tid)
    commits = review.target_commits(p, st) if st.get("base") else []
    files = review.changed_files(p, commits)
    shas = [c["sha"] for c in commits]
    return {"task": tid, "files": files, "findings": compose.design_findings(p, files, shas),
            "text_findings": compose.text_findings(p, files, shas)}


def _cmd(args) -> dict:
    return lint_task(find_project(args.root), args.task)


def register(sub) -> None:
    s = sub.add_parser("lint")
    s.add_argument("--task", required=True)
    s.set_defaults(func=_cmd)
