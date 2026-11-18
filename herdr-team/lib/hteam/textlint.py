"""문구 자동 검사(설계 11.7): 리뷰 대상 커밋이 추가한 줄에서 `.herdr-team/text-rules.md` 의 의심 위치를 찾는다.

결과는 경고다. 판정은 리뷰어가 text-rules §5 심각도로 한다. 표준 라이브러리 정규식만 쓴다. git 은 gitio.diff_lines 로만
읽고 hc·horch·codex 를 부르지 않는다. 이모지는 디자인 검사(lint)가 잡으므로 보지 않는다. 정책 문서의 "할 수 있다" 같은
권한·가능성 표현은 검사하지 않는다(hedging 은 메타 표현만).
"""
from __future__ import annotations

import bisect
import re
from pathlib import Path

from . import gitio
from .globs import matches_any
from .lint import cap, read_source
from .specs import code_lines

# 문구 대상 확장자(설계 11.7). 코드 확장자는 주석 줄을, HTML·XML 은 주석 줄을, Markdown 은 코드 블록과 인라인 코드를 뺀다
SUFFIXES = frozenset({".md", ".mdx", ".txt", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".json",
                      ".yaml", ".yml", ".po", ".arb", ".dart", ".strings", ".xcstrings", ".xml", ".kt", ".swift"})
CODE = frozenset({".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".yaml", ".yml", ".dart", ".kt", ".swift", ".strings"})
MARKUP = frozenset({".html", ".htm", ".xml"})
MARKDOWN = frozenset({".md", ".mdx"})
# 기획·보고서·리뷰·QA·디자인 설계 문서(디렉터 산출물, designer 의 notes.md)·테스트·hteam 파일은 대상이 아니다.
# 화면 원본(docs/design/screens/<화면>/index.html)은 대상이다. 그 화면의 아티팩트 파일(artifact/)은 같은 문구라 뺀다(11.7 10단계)
EXCLUDE = ("docs/planning/**", "docs/tasks/**", "docs/reviews/**", "docs/qa/**", "docs/design/*.md",
           "docs/design/board/**", "docs/design/pilots/**", "docs/design/system/**", "docs/design/screens/*/notes.md",
           "docs/design/screens/*/artifact/**",
           "tests/**", ".herdr-team/**", "**/*.test.*", "**/*.spec.*", "**/__tests__/**", "e2e/**")
VOICE = "docs/planning/voice.md"
SIDE = 30  # 발췌: 일치 위치 앞뒤 글자 수(설계 11.14 의 2. 시안 HTML 의 긴 줄에서 위치를 찾게)
HANGUL = re.compile("[가-힣]")
# 사람 글 표시(설계 11.14 의 2): 이 확장자에서 속성 이름이 정확히 `data-sample` 인 요소의 내용(같은 이름의 처음 닫는 태그
# 앞까지)은 모든 검사에서 뺀다. 시안 속 가짜 사용자 댓글 같은 글이다. 여는 태그는 속성 단위로 읽어 따옴표·중괄호 값 안의 글을
# 속성 이름으로 보지 않는다. 내용이 없는 빈 요소와 스스로 닫는 태그는 건너뛴다(Codex 계획 리뷰 p13c r2)
SAMPLE_SUFFIXES = frozenset({".html", ".jsx", ".tsx", ".vue", ".svelte"})
SAMPLE_ATTR = "data-sample"
VOID_TAGS = frozenset({"area", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"})
TAG_WINDOW = 2000  # 여는 태그 하나를 읽는 최대 글자 수(닫히지 않은 따옴표에서 파일 끝까지 읽지 않게)
_SCAN = re.compile(r"<!--|<([A-Za-z][\w.:-]*)(?=[\s/>])")  # 주석 시작 또는 여는 태그(이름은 묶음 1)
_HTML_COMMENT_END = re.compile(r"-->")
_JSX_COMMENT_END = re.compile(r"\*/\s*\}")
_SCAN_JSX = re.compile(r"<!--|\{/\*|<([A-Za-z][\w.:-]*)(?=[\s/>])")
_CLOSE_TAG = re.compile(r"</([A-Za-z][\w.:-]*)\s*>")
_TAG_SPACE = re.compile(r"\s*")
_ATTR_NAME = re.compile(r"[^\s\"'=<>/`{}]+")
_ATTR_VALUE = re.compile(r"\s*=\s*(?:\"[^\"]*\"|'[^']*'|\{[^{}]*\}|[^\s\"'=<>`{}]+)")
_SPREAD = re.compile(r"\{[^{}]*\}")  # JSX 의 {...props}
COMMENTS = ("//", "/*", "*", "#", "<!--")
_INLINE = re.compile(r"`[^`]*`")

TYPOS = ("됬", "몇일", "어떻해", "금새", "왠만", "오랫만", "역활", "희안", "설겆이", "할께", "일일히", "깨끗히", "틈틈히",
         "안되요", "되요")
# (분류 이름, 정규식). 이름이 출력에 그대로 나온다. 오탈자는 긴 것부터 대안으로 묶어 "안되요" 를 "되요" 로 다시 세지 않는다
CATEGORIES = (
    ("오탈자", re.compile("|".join(sorted(TYPOS, key=len, reverse=True)))),
    ("이중피동", re.compile("(?:되어|보여|쓰여|불려)(?:지|진|짐|져|졌)")),
    ("번역투", re.compile(r"에 있어서|에 있어(?=\s)|가지고 있|에 의해|에서의|으로의|시사하는 바|주목할 만하")),
    # 영문은 낱말 경계(영문·숫자·_ 가 붙지 않음)만. unlock·elevate 는 코드 식별자·i18n 키와 겹쳐 넣지 않는다
    ("상투어", re.compile("혁신적|획기적|최적의|극대화|차세대|시너지|패러다임|게임 체인저|성공적으로|다양한|효율적|원활|한눈에"
                       "|손쉽게|간편하게|올인원|차원이 다른"
                       "|(?<![A-Za-z0-9_])(?:seamlessly|seamless|empower)(?![A-Za-z0-9_])", re.I)),
    ("상용구 오류", re.compile("문제가 발생했습니다|오류가 발생했습니다|문제가 생겼습니다")),  # 무엇이 잘못됐는지 없는 오류 문구
    ("2인칭", re.compile("당신의?")),
    ("hedging", re.compile("라고 할 수 있|다고 볼 수 있|것으로 보여지|것으로 보인다고")),
    ("챗봇 잔재", re.compile("도움이 되셨길|도움이 되었길|도움이 되셨으면|궁금한 점이 있으시면 언제든|물론입니다")),
    # (1) 문두 접속어 뒤 (2) 한글 음절 뒤 연결어미 뒤 (3) 용언 어간·선어말 어미 뒤 "고,"("신고,"·"참고," 같은 명사는 아니다).
    # 한 정규식이라 "하지만," 을 (1) 이 먼저 차지하고 (2) 가 "지만," 으로 다시 세지 않는다
    ("쉼표", re.compile("(?<![가-힣])(?:그리고|또한|그러나|따라서|하지만),"
                      "|(?<=[가-힣])(?:며|지만|면서|아서|어서|여서|해서),"
                      "|(?<=[하되있없않이었았했겠])고,")),
)
# 종결로 보는 낱말: 한글 낱말 + 선택적 문장 부호 + 공백 + (따옴표·백틱·`<`·`|` 또는 줄 끝). 낱말 머리에서만 시작한다(앞이 한글이면
# 같은 낱말의 뒷부분이라 결과가 같다). 띄어 쓰지 않은 긴 한글 줄에서 시작점마다 다시 훑지 않게 한다
_ENDING = re.compile(r"(?<![가-힣])([가-힣]+)[.!?…~]?\s*(?=[\"'`<|]|$)")
HASIPSIO = ("니다", "니까", "십시오")
NOT_HAEYO = ("필요", "중요", "개요", "주요", "수요", "아니요", "좋아요")
_CELL_SPLIT = re.compile("[,，]")
_RULE_ROW = re.compile(r":?-+:?")
# 반복 집계(설계 11.14 의 2): 파일마다 추가한 줄 전체에서 (이름, 정규식, 문턱) 이상이면 범주마다 한 줄
REPEATS = (("아니라", re.compile("아니라"), 2), ("을 통해·를 통해", re.compile("[을를] 통해"), 3),
           ("에 대해", re.compile("에 대해"), 3), ("것이다·것입니다", re.compile("것이다|것입니다"), 3))
LINES_SHOWN = 5
# 복붙(설계 11.14 의 2): 따옴표·태그·중괄호·`|` 로 나눈 조각을 다시 마침표로 나눈, 마침표로 끝나는 10자 이상의 문장이 바뀐
# 파일들 전체에서 5번 이상. 긴 줄에서도 한 번 훑고 끝나게 정규식 검색이 아니라 나누기로 찾는다(Codex 계획 리뷰 p13c r1)
_SENTENCE_BREAK = re.compile(r"[\"'`<>{}|]")
COPY_MIN_CHARS = 10
COPY_MIN_TIMES = 5
COPY_SHOWN = 40
# 라벨 형태 혼용(설계 11.14 의 2): 따옴표 안 값과 태그 사이 글 가운데 10자 이하
_LABEL = re.compile(r"\"([^\"\n]{1,10})\"|'([^'\n]{1,10})'|>([^<>\n]{1,10})<")
LABEL_MAX = 10


def excerpt(line: str, start: int, end: int, bounds: tuple[int, int] | None = None) -> str:
    """발췌: 줄의 일치 위치(start–end) 앞뒤 SIDE 자. 잘린 쪽에 `…` 를 붙이고 공백을 하나로 줄인다. 잘린 쪽에 공백 아닌 글이
    남는지는 줄의 첫·마지막 공백 아닌 글자 위치(bounds, 없으면 한 번 구한다)와 견줘 정하므로 줄 나머지를 복사하지 않는다."""
    first, last = bounds if bounds else (len(line) - len(line.lstrip()), len(line.rstrip()))
    a, b = max(0, start - SIDE), min(len(line), end + SIDE)
    text = " ".join(line[a:b].split())
    return ("…" if first < a else "") + text + ("…" if last > b else "")


def open_tag(text: str, name_end: int, limit: int) -> tuple[int, bool, bool] | None:
    """여는 태그(이름 뒤 name_end 부터, limit 앞까지)를 속성 단위로 읽는다: (태그 끝 다음 위치, 스스로 닫는가, 이름이 정확히
    SAMPLE_ATTR 인 속성이 있는가). 따옴표·중괄호 값과 `{...props}` 는 통째로 건너뛴다. limit 안에서 `>` 를 찾지 못하거나 읽을
    수 없는 글(겹친 중괄호 값 등)이 나오면 None."""
    i, sample = name_end, False
    while True:
        i = _TAG_SPACE.match(text, i, limit).end()
        if i >= limit:
            return None
        if text[i] == ">":
            return i + 1, False, sample
        if text.startswith("/>", i):
            return i + 2, True, sample
        spread = _SPREAD.match(text, i, limit) if text[i] == "{" else None
        if spread:
            i = spread.end()
            continue
        name = _ATTR_NAME.match(text, i, limit)
        if name is None:
            return None
        sample = sample or name.group(0).lower() == SAMPLE_ATTR
        value = _ATTR_VALUE.match(text, name.end(), limit)
        i = value.end() if value else name.end()


def mask_samples(text: str, suffix: str = ".html") -> str:
    """사람 글 표시: 속성 이름이 정확히 `data-sample` 인 요소의 내용(여는 태그 끝부터 같은 이름의 처음 닫는 태그 앞까지. 같은
    태그가 안에 겹쳐도 처음 닫는 태그까지)을 공백으로 바꾼다. 줄바꿈과 길이는 그대로다. 빈 요소(VOID_TAGS)·스스로 닫는 태그·
    닫는 태그가 없는 요소는 그대로 둔다. 닫는 태그 위치는 이름마다 한 번 모아 이분 탐색하므로 닫히지 않은 요소가 많아도 파일을
    다시 훑지 않는다(줄 길이에 비례). 글을 앞에서부터 차례로 읽는다: `<!-- -->` 주석(.jsx·.tsx 는 `{/* */}` 도)은 건너뛰고,
    여는 태그를 읽은 뒤에는 그 태그 끝부터 이어 읽어 다른 태그의 따옴표·중괄호 값 안의 `<` 를 태그로 보지 않는다. .html 은 태그
    이름의 대소문자를 가리지 않고, 컴포넌트 확장자는 가린다(`Link` 는 빈 요소 link 가 아니고 `<Item>` 은 `</Item>` 과 짝이다)."""
    html = suffix == ".html"
    rx = _SCAN_JSX if suffix in (".jsx", ".tsx") else _SCAN
    closes: dict[str, list[int]] = {}
    for m in _CLOSE_TAG.finditer(text):
        closes.setdefault(m.group(1).lower() if html else m.group(1), []).append(m.start())
    out: list[str] = []
    pos = i = 0
    while True:
        m = rx.search(text, i)
        if m is None:
            break
        if m.group(1) is None:  # 주석
            # JSX 주석은 `*/` 뒤에 공백·줄바꿈이 있어도 `}` 로 닫힌다
            end = _JSX_COMMENT_END.search(text, m.end()) if m.group(0) == "{/*" else _HTML_COMMENT_END.search(text, m.end())
            if end is None:  # 닫히지 않은 주석은 브라우저처럼 파일 끝까지다
                break
            i = end.end()
            continue
        name = m.group(1).lower() if html else m.group(1)
        i = m.end()
        # 빈 요소도 먼저 읽어 속성 값 안의 `<!--` 를 주석으로 보지 않는다
        tag = open_tag(text, m.end(), min(len(text), m.start() + TAG_WINDOW))
        if tag is None:
            continue
        i = tag[0]
        if name in VOID_TAGS or tag[1] or not tag[2]:  # 빈 요소(컴포넌트 확장자에서는 소문자 이름만)·스스로 닫는 태그·표시 없음
            continue
        starts = closes.get(name, [])
        k = bisect.bisect_left(starts, tag[0])
        if k == len(starts):
            continue
        out += [text[pos:tag[0]], re.sub(r"[^\n]", " ", text[tag[0]:starts[k]])]
        pos = i = starts[k]
    out.append(text[pos:])
    return "".join(out)


def visible_lines(rel: str, text: str) -> list[tuple[int, str, str]]:
    """검사할 줄 (줄 번호, 줄 원문, 검사할 글). `.html .jsx .tsx .vue .svelte` 는 먼저 사람 글 표시 요소의 내용을 지운다
    (mask_samples). 코드 확장자는 주석으로 시작하는 줄, HTML·XML 은 `<!--` 로 시작하는 줄, Markdown 은 펜스 코드 블록
    (specs.code_lines: 펜스 문자와 길이를 따르고 앞 공백은 보지 않는다. 네 백틱 펜스 안의 세 백틱 예시도 코드다)을 빼고 인라인
    코드를 같은 길이의 공백으로 바꾼 글을 본다(`* 글머리` 는 남는다). 검사할 글은 줄 원문과 길이가 같다(발췌가 일치 위치를
    쓴다). 한글이 없는 줄은 뺀다."""
    suffix = Path(rel).suffix.lower()
    lines = text.split("\n")
    shown = mask_samples(text, suffix).split("\n") if suffix in SAMPLE_SUFFIXES else lines
    code = code_lines(lines, any_indent=True) if suffix in MARKDOWN else [False] * len(lines)
    out: list[tuple[int, str, str]] = []
    for number, (line, body, fenced) in enumerate(zip(lines, shown, code), 1):
        head = body.lstrip()
        if fenced:
            continue
        if suffix in MARKDOWN:
            body = _INLINE.sub(lambda m: " " * len(m.group(0)), body)
        elif suffix in CODE and head.startswith(COMMENTS):
            continue
        elif suffix in MARKUP and head.startswith("<!--"):
            continue
        if HANGUL.search(body):
            out.append((number, line, body))
    return out


def ending_styles(line: str) -> set[str]:
    """줄의 종결 문체: "하십시오체"(니다·니까·십시오), "해요체"(요, 필요·중요 같은 명사와 아니요·좋아요는 뺀다)."""
    found: set[str] = set()
    for m in _ENDING.finditer(line):
        word = m.group(1)
        if word.endswith(HASIPSIO):
            found.add("하십시오체")
        elif word.endswith("요") and not word.endswith(NOT_HAEYO):
            found.add("해요체")
    return found


def load_glossary(root: Path) -> list[tuple[str, list[str]]]:
    """voice.md 용어집 [(쓰는 표기, [쓰지 않는 표기, …])]. `## 용어집` 줄 뒤의 첫 표만 읽고 다음 `## ` 나 표 끝에서 멈춘다.
    머리 첫 두 칸이 `쓰는 표기`·`쓰지 않는 표기` 가 아니면, 파일이 없거나 UTF-8 이 아니면 빈 목록이다. 칸의 백틱을 벗기고,
    금지 칸이 빈 행과 괄호 조건(ASCII·전각)이 붙은 표기는 버린다(조건부 금지가 전역 금지가 되지 않게)."""
    text = read_source(root, VOICE)
    if text is None:
        return []
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip() == "## 용어집"), None)
    if start is None:
        return []
    rows: list[list[str]] = []
    for line in lines[start + 1:]:
        stripped = line.strip()
        if stripped.startswith("|"):
            rows.append([c.replace("`", "").strip() for c in stripped.strip("|").split("|")])
        elif rows or stripped.startswith("## "):
            break
    if not rows or rows[0][:2] != ["쓰는 표기", "쓰지 않는 표기"]:
        return []
    out: list[tuple[str, list[str]]] = []
    for cells in rows[1:]:
        if len(cells) < 2 or all(_RULE_ROW.fullmatch(c) for c in cells if c) or not cells[0] or not cells[1]:
            continue
        banned = [t.strip() for t in _CELL_SPLIT.split(cells[1])]
        out.append((cells[0], [t for t in banned if t and "(" not in t and "（" not in t]))
    return out


def _banned(body: str, glossary: list[tuple[str, list[str]]]) -> list[tuple[int, int, str]]:
    """금지 표기 (시작, 끝, 지적). 어느 행이든 쓰는 표기의 일치 구간이 그 자리를 다 덮으면 건너뛴다(회원가입 안의 가입)."""
    covers = [(m.start(), m.end()) for pref, _ in glossary for m in re.finditer(re.escape(pref), body)]
    found = []
    for pref, banned in glossary:
        for term in banned:
            for m in re.finditer(re.escape(term), body):
                if not any(a <= m.start() and m.end() <= b for a, b in covers):
                    found.append((m.start(), m.end(), f'금지 표기 "{term}"→"{pref}"'))
    return found


def _mixed(rel: str, rows: list[tuple[int, set[str]]]) -> tuple[int, str] | None:
    """해요체 줄과 하십시오체 줄이 모두 있으면 (적은 쪽 첫 줄, 지적). 수가 같으면 하십시오체 쪽을 적는다."""
    yo = [n for n, styles in rows if "해요체" in styles]
    sip = [n for n, styles in rows if "하십시오체" in styles]
    if not yo or not sip:
        return None
    name, minor = ("해요체", yo) if len(yo) < len(sip) else ("하십시오체", sip)
    shown = ", ".join(map(str, minor[:5])) + (", …" if len(minor) > 5 else "")
    return minor[0], f"{rel}:{minor[0]}: 높임법 섞임(해요체 {len(yo)}줄, 하십시오체 {len(sip)}줄. {name} 줄: {shown})"


def _repeats(rel: str, rows: list[tuple[int, str, str]]) -> list[tuple[int, str]]:
    """반복 집계(REPEATS): 문턱 이상이면 (첫 줄, `<파일>:<첫 줄>: 반복 "<이름>" N번(줄: a, b, …)`). 줄 번호는 5개까지."""
    out = []
    for name, rx, limit in REPEATS:
        at = [n for n, _, body in rows for _ in rx.finditer(body)]
        if len(at) >= limit:
            nums = list(dict.fromkeys(at))
            shown = ", ".join(map(str, nums[:LINES_SHOWN])) + (", …" if len(nums) > LINES_SHOWN else "")
            out.append((at[0], f'{rel}:{at[0]}: 반복 "{name}" {len(at)}번(줄: {shown})'))
    return out


def added_rows(rel: str, text: str, added: set[str]) -> list[tuple[int, str, str]]:
    """검사할 줄 가운데 내용이 added(이 태스크가 추가한 줄)에 있는 줄(지금 줄 번호)."""
    return [(n, line, body) for n, line, body in visible_lines(rel, text) if line in added]


def scan_rows(rel: str, rows: list[tuple[int, str, str]], glossary: list[tuple[str, list[str]]]) -> list[str]:
    """한 파일의 지적(상한 없음). 순서는 (줄 번호, 줄 안 위치)이고, 파일 단위 지적(반복 집계, 높임법 섞임)은 그 첫 줄의 다른
    지적들 뒤다. 발췌는 일치 위치 앞뒤(excerpt)."""
    found: list[tuple[int, float, int, str]] = []
    for number, line, body in rows:
        bounds = (len(line) - len(line.lstrip()), len(line.rstrip()))
        hits = [(m.start(), m.end(), f'{name} "{m.group(0)}"') for name, rx in CATEGORIES for m in rx.finditer(body)]
        hits += _banned(body, glossary)
        found += [(number, start, 0, f"{rel}:{number}: {what}({excerpt(line, start, end, bounds)})")
                  for start, end, what in sorted(hits, key=lambda h: h[0])]
    tail = _repeats(rel, rows)
    mixed = _mixed(rel, [(n, ending_styles(body)) for n, _, body in rows])
    if mixed:
        tail.append(mixed)
    found += [(first, float("inf"), k, item) for k, (first, item) in enumerate(tail)]
    return [item for *_, item in sorted(found, key=lambda f: (f[0], f[1], f[2]))]


def scan(rel: str, text: str, added: set[str], glossary: list[tuple[str, list[str]]]) -> list[str]:
    """한 파일의 지적(scan_rows(added_rows(…)))."""
    return scan_rows(rel, added_rows(rel, text, added), glossary)


def sentences(body: str) -> list[str]:
    """검사할 글의 문장 후보: 따옴표·태그·중괄호·`|` 로 나눈 조각마다 마침표로 나눠 마침표로 끝나는 것(마침표를 붙여서). 나누기만
    하므로 줄 길이에 비례한다."""
    out = []
    for segment in _SENTENCE_BREAK.split(body):
        parts = segment.split(".")
        out += [part + "." for part in parts[:-1] if part]
    return out


def copies(files_rows: list[tuple[str, list[tuple[int, str, str]]]]) -> list[str]:
    """복붙: 추가한 줄의 문장(sentences, 공백을 하나로 줄여 10자 이상, 한글 포함)이 바뀐 파일들 전체에서 5번 이상 같으면 문장마다
    한 줄 `<처음 파일>:<줄>: 복붙 "<문장 40자>" N번`(처음 나온 차례)."""
    seen: dict[str, list] = {}
    for rel, rows in files_rows:
        for n, _, body in rows:
            for piece in sentences(body):
                sentence = " ".join(piece.split())
                if len(sentence) >= COPY_MIN_CHARS and HANGUL.search(sentence):
                    seen.setdefault(sentence, [f"{rel}:{n}", 0])[1] += 1
    out = []
    for sentence, (where, times) in seen.items():
        if times >= COPY_MIN_TIMES:
            shown = sentence if len(sentence) <= COPY_SHOWN else sentence[:COPY_SHOWN - 1] + "…"
            out.append(f'{where}: 복붙 "{shown}" {times}번')
    return out


def labels(files_rows: list[tuple[str, list[tuple[int, str, str]]]]) -> list[str]:
    """라벨 형태 혼용: 추가한 줄의 따옴표 안 값과 태그 사이 글 가운데 10자 이하(한글 포함)를 모아 `X` 와 `X하기` 가 함께
    있으면 한 줄 `<X하기 의 처음 위치>: 라벨 형태 혼용 "X"·"X하기"(처음 "X": <위치>)`."""
    first: dict[str, str] = {}
    for rel, rows in files_rows:
        for n, _, body in rows:
            for m in _LABEL.finditer(body):
                value = next(g for g in m.groups() if g is not None).strip()
                if value and len(value) <= LABEL_MAX and HANGUL.search(value):
                    first.setdefault(value, f"{rel}:{n}")
    out = []
    for value, where in first.items():
        base = value[:-2].strip()
        if value.endswith("하기") and base and base in first:
            out.append(f'{where}: 라벨 형태 혼용 "{base}"·"{value}"(처음 "{base}": {first[base]})')
    return out


def _candidate(rel: str) -> bool:
    return not rel.startswith("../") and Path(rel).suffix.lower() in SUFFIXES and not matches_any(rel, EXCLUDE)


def targets(root: Path, files: list[str]) -> list[str]:
    """files(프로젝트 기준 경로) 가운데 문구 대상: 대상 확장자, 제외 경로 밖, 프로젝트 안, read_source 로 읽히고 검사할 줄에
    한글이 있다(주석에만 한글이 있으면 대상이 아니다)."""
    out = []
    for rel in files:
        text = read_source(root, rel) if _candidate(rel) else None
        if text is not None and visible_lines(rel, text):
            out.append(rel)
    return out


_SLASH_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".swift", ".kt", ".dart", ".java", ".go",
                             ".scss", ".less", ".css"})
_BLOCK_ONLY = frozenset({".css"})  # 한 줄 주석 `//` 가 없는 문법
_HASH_SUFFIXES = frozenset({".py", ".sh", ".rb", ".yml", ".yaml", ".toml"})
_ANGLE_SUFFIXES = MARKUP | frozenset({".vue", ".svelte"})


_HTML_LIKE = frozenset({".html", ".htm", ".vue", ".svelte"})  # <script>·<style> 블록이 있는 마크업
_SPECIAL = re.compile(r"[\"'`/\\#<{}$\n]")
_TAG_LIMIT = 2000  # 여는 태그 하나를 읽는 최대 글자 수(속성 값 안의 따옴표를 따라 `>` 를 찾는다)
_OPEN_TAG = re.compile(r"""<([A-Za-z][\w.:-]*+)((?:[^>"']++|"[^"]*+"|'[^']*+')*+)>""")  # 소유 한정자: 실패해도 되짚지 않는다(선형)
_SCSS_LANG = re.compile(r"""lang\s*=\s*["']?(scss|less|sass)""", re.I)


def comment_free_lines(rel: str, text: str) -> list[str] | None:
    """파일 전체를 한 번 훑어 줄마다 주석을 뺀 글(문구 사전 검사용, 선형). 상태를 줄을 넘어 따른다: 여러 줄 `/* … */`·`<!-- … -->`,
    줄을 넘는 백틱 템플릿 문자열(`${…}` 안은 코드로 읽고 중첩한다). `'`·`\"` 는 줄 끝에서 닫힌다. 줄 주석은 `//`(앞이 `:` 면 주소라
    아니다)와 `#`(`.py .sh .rb .yml .yaml .toml`, 줄 머리나 공백 뒤). `.html .htm .vue .svelte` 는 `<script>`·`<style>` 밖(마크업
    본문)에서 `<!-- -->` 만 주석이고 그 안은 JS·CSS 규칙이다. `.jsx .tsx` 는 JSX 글을 가려내지 못한다(알려진 한계). 지운 주석은 공백
    하나로 바꾸고 줄 수는 그대로다(여러 줄 태그의 줄바꿈도 모두 남긴다. 마크업의 여는 태그는 따옴표 속성 값까지 통째로 읽어 그 안의 `<!--` 는 글이다. 줄 i 의 글은 반환값 [i-1]). 대상이 아닌 확장자는 None."""
    suffix = Path(rel).suffix.lower()
    if suffix in _HASH_SUFFIXES:
        region = "hash"
    elif suffix in _ANGLE_SUFFIXES:
        region = "markup"
    elif suffix in _SLASH_SUFFIXES:
        region = "code"
    else:
        return None
    detect_tags = suffix in _HTML_LIKE
    line_ok = suffix not in _BLOCK_ONLY  # style 블록은 lang 으로 바뀐다
    out: list[str] = []
    buf: list[str] = []
    quote = ""
    stack: list[list] = []  # ["T"] 템플릿 문자열, ["E", 깊이] 그 안의 ${ … }
    i, n = 0, len(text)

    def emit(piece: str) -> None:
        """piece 를 그대로 쓰되 안의 줄바꿈마다 줄을 닫는다(태그가 여러 줄이어도 줄 수가 맞는다)."""
        parts = piece.split("\n")
        buf.append(parts[0])
        for part in parts[1:]:
            out.append("".join(buf))
            buf.clear()
            buf.append(part)

    gt = -1  # 다음 `>` 위치의 기억(없으면 n): 닫는 `>` 가 멀면 태그를 읽지 않는다
    fail_budget = 4 * n + _TAG_LIMIT  # 닫히지 않은 태그를 읽다 만 글자 합계의 상한

    def drop(end: int) -> int:
        """i 부터 end 까지가 주석이다: 공백 하나를 남기고 안의 줄바꿈마다 줄을 닫는다."""
        buf.append(" ")
        for _ in range(text.count("\n", i, end)):
            out.append("".join(buf))
            buf.clear()
        return end

    while i < n:
        m = _SPECIAL.search(text, i)
        if m is None:
            buf.append(text[i:])
            break
        j = m.start()
        if j > i:
            buf.append(text[i:j])
        c = text[j]
        i = j + 1
        if c == "\n":
            out.append("".join(buf))
            buf.clear()
            quote = ""
            continue
        top = stack[-1] if stack else None
        if top is not None and top[0] == "T":  # 템플릿 문자열 안: 주석 모양도 글이다
            buf.append(c)
            if c == "\\" and i < n and text[i] != "\n":
                buf.append(text[i])
                i += 1
            elif c == "`":
                stack.pop()
            elif c == "$" and text.startswith("{", i):
                buf.append("{")
                stack.append(["E", 1])
                i += 1
            continue
        if region == "markup":
            if c == "<" and text.startswith("<!--", j):
                end = text.find("-->", j + 4)
                i = drop(n if end < 0 else end + 3)
                continue
            tag = None
            if c == "<" and text[i:i + 1].isalpha():
                if gt < j:
                    gt = text.find(">", j)
                    gt = n if gt < 0 else gt
                if gt - j <= _TAG_LIMIT and fail_budget > 0:
                    tag = _OPEN_TAG.match(text, j, min(n, j + _TAG_LIMIT))
                    if tag is None:
                        fail_budget -= _TAG_LIMIT
            if tag is None:
                buf.append(c)
                continue
            name = tag.group(1).lower()
            if detect_tags and name in ("script", "style") and not tag.group(0).endswith("/>"):
                region = name
                line_ok = name == "script" or bool(_SCSS_LANG.search(tag.group(2)))
            emit(tag.group(0))
            i = tag.end()
            continue
        if region in ("script", "style") and c == "<" and text[j + 2:j + 2 + len(region)].lower() == region \
                and text.startswith("</", j):  # HTML 은 따옴표 안이어도 </script 에서 블록이 끝난다
            region, quote = "markup", ""
            stack.clear()
            buf.append(c)
            continue
        buf.append(c)
        if quote:
            if c == "\\" and i < n and text[i] != "\n":
                buf.append(text[i])
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "`" and region != "hash" and region != "style":
            stack.append(["T"])
        elif c == "{" and top is not None:
            top[1] += 1
        elif c == "}" and top is not None:
            top[1] -= 1
            if top[1] == 0:
                stack.pop()
        elif c == "/" and region != "hash":
            if text.startswith("*", i):
                buf.pop()
                end = text.find("*/", i + 1)
                i = drop(n if end < 0 else end + 2)
            elif line_ok and text.startswith("/", i) and (j == 0 or text[j - 1] != ":"):
                buf.pop()
                nl = text.find("\n", i)
                i = n if nl < 0 else nl
        elif c == "#" and region == "hash" and (j == 0 or text[j - 1] in " \t\n"):
            buf.pop()
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
    out.append("".join(buf))
    return out


def strip_eol_comment(rel: str, line: str) -> str:
    """한 줄만 보고 주석을 뺀 글(comment_free_lines 의 한 줄 판). 줄이 대상 확장자가 아니면 그대로다."""
    lines = comment_free_lines(rel, line)
    return line if lines is None else lines[0]


def added_text_files(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """문구 대상(targets) 가운데 대상 커밋(shas)이 검사할 줄(주석이 아니고 한글이 보이는 줄)을 더한 파일(설계 6.6 의 3,
    `### 문구 점검` 사전 검사). 파일 전체를 한 번 훑어 여러 줄 주석·줄 끝 주석을 뺀 글(comment_free_lines)에 한글이 남아야
    센다(코드만 바꾼 변경을 돌려보내지 않는다). diff 를 읽지 못한 파일은 세지 않는다(그 파일 때문에 돌려보내지 않는다)."""
    out = []
    for rel in targets(root, files):
        added = gitio.added_lines(root, shas, rel)
        text = read_source(root, rel)
        if not added or text is None:
            continue
        suffix = Path(rel).suffix.lower()
        clean = comment_free_lines(rel, mask_samples(text, suffix) if suffix in SAMPLE_SUFFIXES else text)
        if any(line in added and HANGUL.search(body if clean is None else clean[number - 1])
               for number, line, body in visible_lines(rel, text)):
            out.append(rel)
    return out


def text_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """문구 대상마다 리뷰 대상 커밋(shas)이 추가한 줄의 지적(파일 차례), 그 뒤에 파일들 전체의 복붙(copies)과 라벨 형태
    혼용(labels). 용어집은 한 번 읽는다. diff 를 읽지 못한 파일(None)은 건너뛴다. MAX_FINDINGS(50)를 넘으면 마지막 항목이
    `… 외 N건`."""
    glossary = load_glossary(root)
    found: list[str] = []
    files_rows: list[tuple[str, list[tuple[int, str, str]]]] = []
    for rel in targets(root, files):
        added = gitio.added_lines(root, shas, rel)
        text = read_source(root, rel)
        if added is not None and text is not None:
            rows = added_rows(rel, text, added)
            found += scan_rows(rel, rows, glossary)
            files_rows.append((rel, rows))
    return cap(found + copies(files_rows) + labels(files_rows))
