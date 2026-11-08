"""문구 자동 검사(설계 11.7): 리뷰 대상 커밋이 추가한 줄에서 `.herdr-team/text-rules.md` 의 의심 위치를 찾는다.

결과는 경고다. 판정은 리뷰어가 text-rules §5 심각도로 한다. 표준 라이브러리 정규식만 쓴다. git 은 gitio.diff_lines 로만
읽고 hc·horch·codex 를 부르지 않는다. 이모지는 디자인 검사(lint)가 잡으므로 보지 않는다. 정책 문서의 "할 수 있다" 같은
권한·가능성 표현은 검사하지 않는다(hedging 은 메타 표현만).
"""
from __future__ import annotations

import re
from pathlib import Path

from . import gitio
from .globs import matches_any
from .lint import cap, read_source

# 문구 대상 확장자(설계 11.7). 코드 확장자는 주석 줄을, HTML·XML 은 주석 줄을, Markdown 은 코드 블록과 인라인 코드를 뺀다
SUFFIXES = frozenset({".md", ".mdx", ".txt", ".html", ".htm", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".json",
                      ".yaml", ".yml", ".po", ".arb", ".dart", ".strings", ".xcstrings", ".xml", ".kt", ".swift"})
CODE = frozenset({".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".yaml", ".yml", ".dart", ".kt", ".swift", ".strings"})
MARKUP = frozenset({".html", ".htm", ".xml"})
MARKDOWN = frozenset({".md", ".mdx"})
# 기획·보고서·리뷰·QA·디자인 설계 문서(디렉터 산출물, designer 의 notes.md)·테스트·hteam 파일은 대상이 아니다.
# 화면 원본(docs/design/screens/<화면>/index.html)은 대상이다
EXCLUDE = ("docs/planning/**", "docs/tasks/**", "docs/reviews/**", "docs/qa/**", "docs/design/*.md",
           "docs/design/board/**", "docs/design/pilots/**", "docs/design/system/**", "docs/design/screens/*/notes.md",
           "tests/**", ".herdr-team/**", "**/*.test.*", "**/*.spec.*", "**/__tests__/**", "e2e/**")
VOICE = "docs/planning/voice.md"
SNIPPET = 60
HANGUL = re.compile("[가-힣]")
COMMENTS = ("//", "/*", "*", "#", "<!--")
_INLINE = re.compile(r"`[^`]*`")

TYPOS = ("됬", "몇일", "어떻해", "금새", "왠만", "오랫만", "역활", "희안", "설겆이", "할께", "일일히", "깨끗히", "틈틈히",
         "안되요", "되요")
# (분류 이름, 정규식). 이름이 출력에 그대로 나온다. 오탈자는 긴 것부터 대안으로 묶어 "안되요" 를 "되요" 로 다시 세지 않는다
CATEGORIES = (
    ("오탈자", re.compile("|".join(sorted(TYPOS, key=len, reverse=True)))),
    ("이중피동", re.compile("(?:되어|보여|쓰여|불려)(?:지|진|짐|져|졌)")),
    ("번역투", re.compile(r"에 있어서|에 있어(?=\s)")),
    # 영문은 낱말 경계(영문·숫자·_ 가 붙지 않음)만. unlock·elevate 는 코드 식별자·i18n 키와 겹쳐 넣지 않는다
    ("상투어", re.compile("혁신적|획기적|최적의|극대화|차세대|시너지|패러다임|게임 체인저"
                       "|(?<![A-Za-z0-9_])(?:seamlessly|seamless|empower)(?![A-Za-z0-9_])", re.I)),
    ("hedging", re.compile("라고 할 수 있|다고 볼 수 있|것으로 보여지|것으로 보인다고")),
    ("챗봇 잔재", re.compile("도움이 되셨길|도움이 되었길|도움이 되셨으면|궁금한 점이 있으시면 언제든|물론입니다")),
    # (1) 문두 접속어 뒤 (2) 한글 음절 뒤 연결어미 뒤 (3) 용언 어간·선어말 어미 뒤 "고,"("신고,"·"참고," 같은 명사는 아니다).
    # 한 정규식이라 "하지만," 을 (1) 이 먼저 차지하고 (2) 가 "지만," 으로 다시 세지 않는다
    ("쉼표", re.compile("(?<![가-힣])(?:그리고|또한|그러나|따라서|하지만),"
                      "|(?<=[가-힣])(?:며|지만|면서|아서|어서|여서|해서),"
                      "|(?<=[하되있없않이었았했겠])고,")),
)
# 종결로 보는 낱말: 한글 낱말 + 선택적 문장 부호 + 공백 + (따옴표·백틱·`<`·`|` 또는 줄 끝)
_ENDING = re.compile(r"([가-힣]+)[.!?…~]?\s*(?=[\"'`<|]|$)")
HASIPSIO = ("니다", "니까", "십시오")
NOT_HAEYO = ("필요", "중요", "개요", "주요", "수요", "아니요", "좋아요")
_CELL_SPLIT = re.compile("[,，]")
_RULE_ROW = re.compile(r":?-+:?")


def excerpt(line: str) -> str:
    """공백을 하나로 줄인 줄 전체를 60자까지(넘으면 59자 + `…`)."""
    text = " ".join(line.split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1] + "…"


def visible_lines(rel: str, text: str) -> list[tuple[int, str, str]]:
    """검사할 줄 (줄 번호, 줄 원문, 검사할 글). 코드 확장자는 주석으로 시작하는 줄, HTML·XML 은 `<!--` 로 시작하는 줄,
    Markdown 은 펜스(``` · ~~~) 블록을 빼고 인라인 코드를 지운 글을 본다(`* 글머리` 는 남는다). 한글이 없는 줄은 뺀다."""
    suffix = Path(rel).suffix.lower()
    out: list[tuple[int, str, str]] = []
    fenced = False
    for number, line in enumerate(text.split("\n"), 1):
        head, body = line.lstrip(), line
        if suffix in MARKDOWN:
            if head.startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            body = _INLINE.sub(" ", line)
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


def _banned(body: str, glossary: list[tuple[str, list[str]]]) -> list[tuple[int, str]]:
    """금지 표기 (위치, 지적). 어느 행이든 쓰는 표기의 일치 구간이 그 자리를 다 덮으면 건너뛴다(회원가입 안의 가입)."""
    covers = [(m.start(), m.end()) for pref, _ in glossary for m in re.finditer(re.escape(pref), body)]
    found = []
    for pref, banned in glossary:
        for term in banned:
            for m in re.finditer(re.escape(term), body):
                if not any(a <= m.start() and m.end() <= b for a, b in covers):
                    found.append((m.start(), f'금지 표기 "{term}"→"{pref}"'))
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


def scan(rel: str, text: str, added: set[str], glossary: list[tuple[str, list[str]]]) -> list[str]:
    """한 파일의 지적(상한 없음). 검사할 줄 가운데 내용이 added(이 태스크가 추가한 줄)에 있는 줄만 지금 줄 번호로 본다.
    순서는 (줄 번호, 줄 안 위치)이고 높임법 섞임은 그 줄의 다른 지적들 뒤다."""
    rows = [(n, line, body) for n, line, body in visible_lines(rel, text) if line in added]
    found: list[tuple[int, float, str]] = []
    for number, line, body in rows:
        hits = [(m.start(), f'{name} "{m.group(0)}"') for name, rx in CATEGORIES for m in rx.finditer(body)]
        hits += _banned(body, glossary)
        found += [(number, pos, f"{rel}:{number}: {what}({excerpt(line)})")
                  for pos, what in sorted(hits, key=lambda h: h[0])]
    mixed = _mixed(rel, [(n, ending_styles(body)) for n, _, body in rows])
    if mixed:
        found.append((mixed[0], float("inf"), mixed[1]))
    return [item for _, _, item in sorted(found, key=lambda f: (f[0], f[1]))]


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


def text_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """문구 대상마다 리뷰 대상 커밋(shas)이 추가한 줄의 지적. 용어집은 한 번 읽는다. diff 를 읽지 못한 파일(None)은
    건너뛴다. MAX_FINDINGS(50)를 넘으면 마지막 항목이 `… 외 N건`."""
    glossary = load_glossary(root)
    found: list[str] = []
    for rel in targets(root, files):
        added = gitio.added_lines(root, shas, rel)
        text = read_source(root, rel)
        if added is not None and text is not None:
            found += scan(rel, text, added, glossary)
    return cap(found)
