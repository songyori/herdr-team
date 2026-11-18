"""디자인 자동 검사(설계 11.6·11.13): `hteam lint --task T`.

리뷰 대상 커밋이 바꾼 파일에서 디자인 규칙(`.herdr-team/design-rules.md`) §1 의 1(이모지), 2(왼쪽 강조 테두리),
3(파랑·보라 그라디언트) 의심 위치를 찾는다(design_findings). 13단계 색·글꼴 검사(style_findings)는 과용 색·Tailwind
기본 램프(파일당 한 줄), 이름에 primary·accent·brand 가 든 토큰의 파랑·남색·보라 강조, 과용 글꼴을 찾는다. 카탈로그는
palette.load_overused 이고 깨지면 그 검사만 실패한다(compose 가 따로 감싼다). 결과는 경고다(블록 인용처럼 정당한 쓰임이
있다). 판정은 리뷰어가 한다.
리뷰 프롬프트의 디자인 절(compose.review_prompt)이 시도 기록의 바뀐 파일로 부른다. 표준 라이브러리 정규식만 쓰고
git·hc·horch·codex 를 부르지 않는다(명령 `lint --task` 만 review 의 대상 커밋 계산과 compose 의 절 목록을 거친다).
read_source·cap 은 문구 검사(textlint)도 함께 쓴다.
"""
from __future__ import annotations

import bisect
import colorsys
import json
import re
from pathlib import Path

from . import color
from .globs import matches_any
from .paths import find_project

DESIGN_ROLES = ("director", "designer", "developer")  # 리뷰 프롬프트에 디자인 절을 넣는 직무(설계 6.2)
SUFFIXES = frozenset({".html", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".md", ".json"})
# 화면 아티팩트 파일(docs/design/screens/<화면>/artifact/)은 index.html 을 아티팩트 꼴로 바꾼 것이다(설계 11.6·11.8 10단계)
EXCLUDE = ("docs/design/references.md", "docs/planning/**", "docs/tasks/**", "docs/reviews/**",
           "docs/design/screens/*/artifact/**")
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


# 13단계 색·글꼴 검사(설계 11.13 의 1). hex 는 앞이 `&`·낱말 글자가 아니고(HTML 숫자 문자 참조 `&#123;` 는 뺀다) 뒤가 낱말
# 글자·하이픈이 아닌 3·4·6·8자리다. 4·8자리의 알파는 버리고 견준다.
_HEX = re.compile(r"(?<![&\w])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})(?![\w-])")
# 이름 붙은 값: CSS 변수(`--x:`)·Sass 변수(`$x:`)·따옴표 키(`"x":`, tokens.json·JS 객체). 값의 끝은 다음 이름 앞이다
# (`value`·`$value` 키는 값을 감싸는 껍데기라 끝으로 보지 않는다).
_NAME = re.compile(r"""(?:(?<![\w$-])(--[\w-]+|\$[\w-]+)|(["'])([^"'\n]{1,80})\2)\s*:""")
_ROLE = re.compile(r"primary|accent|brand", re.I)
_COLOR_LITERAL = re.compile(r"(?<![&\w])#[0-9a-fA-F]{3,8}(?![\w-])|\b(?:rgba?|hsla?|oklch)\([^()\n]*\)", re.I)
# 글꼴 선언의 머리(`font-family:`·`fontFamily:`·`"fontFamily":`). 값은 _font_values 가 여러 줄까지 읽는다.
_FONT_HEAD = re.compile(r"""(?:font-family|fontFamily)["']?\s*:\s*""", re.I)
_FONT_LIST = re.compile(r""":\s*(\[[^\]]*\]|"[^"\n]*"|'[^'\n]*'|`[^`\n]*`)""")
# 객체 안을 토큰으로 읽는다: 따옴표 글(뒤에 `:` 가 오면 키), 따옴표 없는 키, 괄호. 글 안의 내용은 한 덩어리로 건너뛴다.
_OBJ_TOKEN = re.compile(r"""(?P<s>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')(?P<c>\s*:\s*)?|(?P<i>[A-Za-z_$][\w$]*)(?P<ic>\s*:\s*)|(?P<b>[{}\[\]])""")
SCAN_WINDOW = 4000  # 닫히지 않은 `{`·`[`·끝나지 않는 값을 앞으로 찾는 최대 글자 수(병적인 입력에서도 선형으로 끝낸다)
BLUE_HUE = (240, 300)  # 주 강조로 근거가 필요한 OKLCH h(파랑·남색·보라, 설계 11.12 의 1 §1 의 11)
BLUE_MIN_C = 0.08
# 프로젝트의 design-rules.md 가 13단계 판인지 가르는 줄(Task 3 이 쓰는 §1 의 11 의 머리). 색·글꼴 경고가 인용하는 규칙이다
STYLE_RULES_MARKER = "11. 근거 없이 프레임워크 기본 팔레트 값"


def has_style_rules(rules: Path) -> bool:
    """프로젝트의 design-rules.md(rules)에 13단계 색·글꼴 규칙이 있나: 줄 머리가 STYLE_RULES_MARKER 인 줄. 읽지 못하면(없음,
    UTF-8 아님) 없다고 본다."""
    try:
        text = rules.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return any(line.startswith(STYLE_RULES_MARKER) for line in text.split("\n"))


def _hex6(digits: str) -> str:
    d = digits.lower()
    return "#" + ("".join(c * 2 for c in d[:3]) if len(d) in (3, 4) else d[:6])


def font_stack(value: str) -> list[str]:
    """font-family 값(CSS 글, 따옴표 글, JSON·JS 배열)의 글꼴 이름들. `!important` 와 감싼 따옴표는 뗀다."""
    v = re.sub(r"\s*!important\s*$", "", value.strip().rstrip(",;").strip(), flags=re.I)
    if v.startswith("["):
        names = re.findall(r"""["'`]([^"'`]*)["'`]""", v)
    else:
        if len(v) >= 2 and v[0] in "\"'`" and v[-1] == v[0]:
            v = v[1:-1]
        names = v.split(",")
    return [n for n in (x.strip().strip("\"'`").strip() for x in names) if n]


def _value_end(line: str, start: int) -> int:
    """start 에서 시작하는 값의 끝 위치: 괄호 밖의 `;`·`}`·`,` 앞, 아니면 줄 끝. `rgb(1, 2, 3)` 안의 쉼표는 값 안이다."""
    depth = 0
    for i in range(start, len(line)):
        c = line[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and c in ";},":
            return i
    return len(line)


def _object_end(line: str, start: int) -> int:
    """line[start] == "{" 인 객체의 닫는 `}` 다음 위치. 줄 안에서 닫히지 않으면 줄 끝."""
    depth = 0
    for i in range(start, len(line)):
        if line[i] == "{":
            depth += 1
        elif line[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(line)


def _direct_value(inner: str) -> int | None:
    """객체 글(inner, 첫 글자 `{`)에서 그 객체 바로 아래의 `$value`·`value` 키 다음 위치. 안쪽 객체·배열(`$extensions` 등)과 글 안의
    내용은 건너뛴다. 없으면 None."""
    depth = 0
    for t in _OBJ_TOKEN.finditer(inner):
        if t.group("b"):
            depth += 1 if t.group("b") in "{[" else -1
            if depth <= 0:
                return None
        elif depth == 1:
            if t.group("c") and t.group("s")[1:-1].lower() in ("value", "$value"):
                return t.end("c")
            if t.group("ic") and t.group("i").lower() in ("value", "$value"):
                return t.end("ic")
    return None


def _role_colors(line: str) -> list[tuple[float, float, float]]:
    """이름에 primary·accent·brand 가 든 값마다 그 값의 첫 색(OKLCH)을 줄 안 차례로. 값은 그 선언의 끝(`;`·`}`·괄호 밖 `,`·줄 끝)
    까지만 본다. 값이 객체(DTCG `{"$type": …, "$value": …}`)면 `$` 로 시작하는 메타 키를 건너뛰고 `$value`·`value` 의 값을 읽는다.
    색을 읽지 못한 값은 뺀다."""
    out = []
    for m in _NAME.finditer(line):
        name = m.group(1) or m.group(3)
        if name in ("value", "$value") or not _ROLE.search(name):
            continue
        start = m.end()
        while start < len(line) and line[start] in " \t":
            start += 1
        if line.startswith("{", start):
            inner = line[start:_object_end(line, start)]
            key = _direct_value(inner)
            if key is None:
                continue
            base = start + key
        else:
            base = start
        found = _COLOR_LITERAL.search(line, base, _value_end(line, base))
        lch = color.parse(found.group(0)) if found else None
        if lch is not None:
            out.append(lch)
    return out


def _line_starts(text: str) -> list[int]:
    """각 줄이 시작하는 위치(0 번째 줄 = 0). 위치 → 줄 번호는 `bisect.bisect_right(starts, pos)`."""
    return [0] + [m.end() for m in re.finditer("\n", text)]


_BRACES = re.compile(r"[{}]")


def _font_values(text: str, starts: list[int] | None = None):
    """글꼴 선언마다 (선언이 시작하는 줄 번호, 글꼴 이름 목록)을 낸다. 값은 여러 줄에 걸칠 수 있다: 배열은 닫는 `]` 까지, CSS 값은
    `;`·`}` 까지(줄이 `,` 로 끝나면 다음 줄로 이어진다), Tailwind 중첩 `fontFamily: { sans: [...] }` 는 안의 목록마다.
    닫히지 않은 괄호·끝나지 않는 값은 SCAN_WINDOW 글자까지만 본다."""
    if starts is None:
        starts = _line_starts(text)
    n = len(text)
    for m in _FONT_HEAD.finditer(text):
        number = bisect.bisect_right(starts, m.start())
        i = m.end()
        head = text[i:i + 1]
        limit = min(n, i + SCAN_WINDOW)
        if head == "{":
            depth = 0
            j = limit - 1
            for b in _BRACES.finditer(text, i, limit):
                depth += 1 if b.group() == "{" else -1
                if depth == 0:
                    j = b.start()
                    break
            for item in _FONT_LIST.finditer(text[i:j + 1]):
                yield number, font_stack(item.group(1))
        elif head == "[":
            j = text.find("]", i, limit)
            end = text.find("\n", i, limit)
            yield number, font_stack(text[i:j + 1] if j >= 0 else text[i:end if end >= 0 else limit])
        elif head in ("\"", "'", "`"):
            j = text.find(head, i + 1, limit)
            end = text.find("\n", i, limit)
            yield number, font_stack(text[i:j + 1] if 0 <= j and (end < 0 or j < end) else text[i:end if end >= 0 else limit])
        else:
            value = ""
            while i <= n and len(value) < SCAN_WINDOW:
                end = text.find("\n", i)
                line = text[i:end if end >= 0 else n]
                stop = min((k for k in (line.find(";"), line.find("}")) if k >= 0), default=-1)
                if stop >= 0:
                    value += line[:stop]
                    break
                value += line
                if not line.rstrip().endswith(",") or end < 0:
                    break
                i = end + 1
            yield number, font_stack(value[:SCAN_WINDOW])


def _json_role_hues(text: str, starts: list[int] | None = None):
    """JSON 토큰 파일(text)에서 (주 강조 hue 경고 [(줄 번호, h)], DTCG 글꼴 토큰 [(줄 번호, 글꼴 이름 목록)])를 낸다. JSON 이 아니면
    None(줄 단위 검사로 되돌아간다). 키 경로(배열은 색인 포함)에 primary·accent·brand 가 든 문자열 값을 색으로 읽는다. `$value` 말고
    `$` 로 시작하는 키(`$extensions` 등)의 하위 트리는 깊이와 관계없이 메타데이터라 통째로 뺀다. 역할 객체(경로에서 처음 역할
    이름이 나온 키)마다 문서 순서의 첫 파랑·남색·보라 값 하나만, 그 값이 나온 줄에 단다. `$type` 이 fontFamily(s) 인 객체의 `$value`
    (글·배열)는 글꼴 목록으로 내며 `$value` 키의 줄에 단다."""
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return None
    if starts is None:
        starts = _line_starts(text)
    cursor = 0  # 문서 순서로 키·값을 찾아 나가는 위치(같은 값이 여러 번 나와도 차례대로 맞는다)

    def locate(needle_src: str) -> int | None:
        nonlocal cursor
        plain = json.dumps(needle_src, ensure_ascii=False)
        for needle in (plain, json.dumps(needle_src)) if plain != json.dumps(needle_src) else (plain,):
            at = text.find(needle, cursor)
            if at >= 0:
                cursor = at + len(needle)
                return at
        return None

    out: list[tuple[int, float]] = []
    fonts: list[tuple[int, list[str]]] = []
    done: set[tuple] = set()  # 이미 단 역할 객체(경로 접두)

    def line_of(at: int | None, fallback: int) -> int:
        return bisect.bisect_right(starts, at) if at is not None else fallback

    def walk(node, path: tuple, role: tuple | None, role_line: int, meta: bool) -> None:
        if isinstance(node, dict):
            font_obj = not meta and str(node.get("$type", "")).lower() in ("fontfamily", "fontfamilies")
            for key, child in node.items():
                at = locate(str(key))
                line = line_of(at, role_line)
                is_role = role is None and not meta and _ROLE.search(str(key))
                if font_obj and key == "$value" and isinstance(child, (str, list)):
                    stack = font_stack(child) if isinstance(child, str) else [str(x) for x in child if isinstance(x, str)]
                    fonts.append((line, stack))
                walk(child, path + (key,), path + (key,) if is_role else role, line if is_role else role_line,
                     meta or (str(key).startswith("$") and key != "$value"))
        elif isinstance(node, list):
            for idx, child in enumerate(node):
                walk(child, path + (idx,), role, role_line, meta)
        elif isinstance(node, str):
            at = locate(node)
            if meta or role is None or role in done:
                return
            lch = color.parse(node)
            if lch is not None and lch[1] >= BLUE_MIN_C and BLUE_HUE[0] <= lch[2] < BLUE_HUE[1]:
                done.add(role)
                out.append((line_of(at, role_line), lch[2]))

    walk(data, (), None, 1, False)
    return out, fonts


def style_scan(rel: str, text: str, overused: dict) -> list[str]:
    """한 파일의 색·글꼴 경고(설계 11.13 의 1)를 줄 순서로. 과용 색·램프는 파일당 한 줄이고 그 첫 줄에 단다."""
    from .palette import font_key, hangul_font  # palette 가 color 를 쓴다. 이 모듈을 가져오는 차례가 꼬이지 않게 여기서 가져온다
    named = {c["hex"]: c["name"] for c in overused["colors"]}
    ramp = set(overused["tailwind_ramp"]) - set(named)
    latin = {font_key(n) for n in overused["fonts_latin"]}
    korean = {font_key(n) for n in overused["fonts_ko"]}
    hits: dict[str, int] = {}  # 과용 색 → 첫 줄(나온 차례)
    ramp_hits: dict[str, int] = {}
    found: list[tuple[int, str]] = []
    starts = _line_starts(text)
    parsed = _json_role_hues(text, starts) if rel.lower().endswith(".json") else None
    json_hues = parsed[0] if parsed else None if parsed is None else []
    for number, what in ((n, f"주 강조가 파랑·남색·보라 계열(h {round(h)}°) — 근거를 적는다(§1 의 11)") for n, h in json_hues or []):
        found.append((number, what))
    for number, line in enumerate(text.split("\n"), 1):
        for m in _HEX.finditer(line):
            h = _hex6(m.group(1))
            if h in named:
                hits.setdefault(h, number)
            elif h in ramp:
                ramp_hits.setdefault(h, number)
        blue = next((lch for lch in _role_colors(line)
                     if lch[1] >= BLUE_MIN_C and BLUE_HUE[0] <= lch[2] < BLUE_HUE[1]), None) if json_hues is None else None  # 줄에 하나만 단다
        if blue is not None:
            found.append((number, f"주 강조가 파랑·남색·보라 계열(h {round(blue[2])}°) — 근거를 적는다(§1 의 11)"))
    seen_lines: set[int] = set()  # 한 줄에 글꼴 경고는 하나만 단다
    for number, stack in [*_font_values(text, starts), *(parsed[1] if parsed else [])]:
        if not stack or number in seen_lines:
            continue
        if font_key(stack[0]) in latin:
            found.append((number, f"과용 글꼴 {stack[0]} — §1 의 7"))
            seen_lines.add(number)
            continue
        hangul = hangul_font(stack, latin)
        if hangul is not None and font_key(hangul) in korean:
            found.append((number, f"과용 글꼴 {hangul} — §1 의 7"))
            seen_lines.add(number)
    if hits:
        shown = ", ".join(f"{h} {named[h]}" for h in list(hits)[:3]) + (", …" if len(hits) > 3 else "")
        found.append((min(hits.values()), f"과용 기본 색 {len(hits)}개({shown}) — design-rules §1 의 11"))
    if len(ramp_hits) >= 3:
        found.append((min(ramp_hits.values()), f"Tailwind 기본 램프 값 {len(ramp_hits)}개 — design-rules §3 의 11"))
    return [f"{rel}:{number}: {what}" for number, what in sorted(found, key=lambda x: x[0])]


def style_findings(root: Path, files: list[str]) -> list[str]:
    """files 가운데 검사 대상(design_findings 와 같은 확장자·제외)의 색·글꼴 경고(상한 없음). 카탈로그가 깨지면
    HteamError(catalog_invalid) 를 그대로 올린다(디자인 절이 이 검사만 실패로 적는다)."""
    from .palette import load_overused
    overused = None
    found: list[str] = []
    for rel in files:
        if rel.startswith("../") or Path(rel).suffix.lower() not in SUFFIXES or matches_any(rel, EXCLUDE):
            continue
        text = read_source(root, rel)
        if text is not None:
            overused = overused or load_overused()
            found += style_scan(rel, text, overused)
    return found


def design_lint(root: Path, files: list[str]) -> list[str]:
    """design_findings 를 MAX_FINDINGS 로 자른 것(넘으면 마지막 항목이 `… 외 N건`)."""
    return cap(design_findings(root, files))


def lint_task(p, tid: str) -> dict:
    """태스크의 리뷰 대상 커밋(review.target_commits)이 바꾼 파일을 리뷰 프롬프트와 같은 규칙으로 검사한다. 읽기만 한다.
    findings 는 디자인 절의 경고 목록(디렉터 직무 유무와 관계없이), text_findings 는 문구 절의 경고 목록
    (`.herdr-team/text-rules.md` 가 없으면 None), guard_findings 는 검사 약화 의심 절의 경고 목록(설계 6.6 의 1)."""
    from . import compose, review, state, workspace  # review·compose 가 이 모듈을 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    st = state.require(p, tid)
    p = workspace.view(p, st)  # 커밋·파일은 그 태스크의 작업 루트에서 본다(설계 5.10.2)
    commits = review.target_commits(p, st) if st.get("base") else []
    files = review.changed_files(p, commits, st.get("base"))
    shas = [c["sha"] for c in commits]
    return {"task": tid, "files": files, "findings": compose.design_findings(p, files, shas),
            "text_findings": compose.text_findings(p, files, shas), "guard_findings": compose.guard_findings(p, files, shas)}


def _cmd(args) -> dict:
    return lint_task(find_project(args.root), args.task)


def register(sub) -> None:
    s = sub.add_parser("lint")
    s.add_argument("--task", required=True)
    s.set_defaults(func=_cmd)
