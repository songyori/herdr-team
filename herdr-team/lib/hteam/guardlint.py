"""검사 약화 의심(설계 6.6 의 1): 리뷰 대상 커밋이 더한 억제 주석·시험 건너뛰기·빈 catch, 지운 시험 파일·시험 정의, 줄어든 단언.

결과는 경고다(자동 불합격은 없다). 판정은 리뷰어가 보고서의 이유와 함께 한다(리뷰 프롬프트의 P1 정의). 언어는 설정이 모르므로
패턴은 고정 목록이고 줄 단위 정규식이라 문자열 안의 낱말도 잡는다. 추가한 줄은 문구 검사(textlint)처럼 "지금 파일에서 내용이
대상 커밋의 추가한 줄에 있는 줄" 이다. git 은 gitio.diff_lines·parents·tree_entry 로만 읽고 hc·horch·codex 를 부르지 않는다.
"""
from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

from . import gitio
from .globs import matches_any
from .lint import cap, read_source

# 줄 단위로 보지 않는 파일: 보고서·리뷰·hteam 파일과 글 문서(억제 주석을 설명하는 글이 경고가 되지 않게). 시험 파일 판정과
# 지운 시험·단언 세기는 이 제외와 상관없다
EXCLUDE = ("docs/tasks/**", "docs/reviews/**", ".herdr-team/**")
PROSE = frozenset({".md", ".mdx", ".txt", ".rst"})
TEST_DIRS = frozenset({"test", "tests", "spec", "__tests__"})
TEST_NAMES = ("*_test.*", "*.test.*", "*.spec.*", "test_*")
SNIPPET = 60
NAMES_SHOWN = 5
# (분류 이름, 정규식). 이름이 출력에 그대로 나온다. 낱말처럼 생긴 것(xit·t.Skip)은 앞에 낱말 글자·점이 붙으면 보지 않는다
# (sys.exit( 의 xit( 같은 것). .skip(·.only( 는 시험 함수 이름(it·test·describe…) 바로 뒤에서만 본다
# (qs.only("a")·stream.skip(3) 같은 일반 코드 제외. 점부터 맞추려고 낱말마다 고정 길이 lookbehind 로 건다)
LINE_CHECKS = (
    ("억제 주석", re.compile(r"@ts-ignore|@ts-expect-error|@ts-nocheck|eslint-disable|#\s*noqa\b|#\s*type:\s*ignore"
                         r"|#\s*pyright:\s*ignore|istanbul ignore|c8 ignore|pragma: no cover|//\s*nolint\b"
                         r"|@SuppressWarnings\b")),
    ("시험 건너뛰기", re.compile(r"(?:(?<=\bit)|(?<=\btest)|(?<=\bdescribe)|(?<=\bcontext)|(?<=\bsuite)|(?<=\bspecify))\.(?:skip|only)\("
                           r"|(?<![\w$.])(?:xit|xdescribe|xtest)\(|@pytest\.mark\.(?:skip|xfail)"
                           r"|@unittest\.skip|(?<![\w$.])t\.Skip\w*\(|#\[ignore\]|@Ignore\b|@Disabled")),
    ("빈 catch", re.compile(r"\bcatch\s*(?:\([^()]*\))?\s*\{\s*\}")),
)
_EXCEPT = re.compile(r"^\s*except\b[^:]*:\s*(?:#.*)?$")
_EXCEPT_PASS = re.compile(r"^\s*except\b[^:]*:\s*pass\s*(?:#.*)?$")
_PASS = re.compile(r"^\s*pass\s*(?:#.*)?$")
_SKIP_LINE = re.compile(r"^\s*(?:#.*)?$")  # 빈 줄·주석 줄(except 블록의 문장을 셀 때 건너뛴다)
_PY_GO_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)|^\s*func\s+(Test\w*)")
_JS_TEST = re.compile(r"^\s*(?:it|test)\(\s*(?:([\"'`])(.*?)\1)?")
_ANNOTATION = re.compile(r"^\s*@Test\b")
_CALL_NAME = re.compile(r"(`[^`]+`|[A-Za-z_]\w*)\s*\(")
# 단언 호출: assert 로 시작하는 호출(assertEqual(, assert.Equal(, assert_eq!(, Python 의 `assert x`), expect(, XCTAssert…(
_ASSERT = re.compile(r"(?<![\w$])(?:assert\w*(?:\.\w+)?!?\s*\(|assert\s+(?=\S)|expect\s*\(|XCTAssert\w*\s*\()")


def is_test_file(rel: str) -> bool:
    """시험 파일(설계 6.6 의 1): 경로의 폴더 조각에 test·tests·spec·__tests__ 가 있거나 이름이 `*_test.*`·`*.test.*`·
    `*.spec.*`·`test_*` 다."""
    parts = rel.split("/")
    return any(p in TEST_DIRS for p in parts[:-1]) or any(fnmatch(parts[-1], pat) for pat in TEST_NAMES)


def _shown(line: str) -> str:
    """발췌: 공백을 하나로 줄인 줄 전체를 60자까지(넘으면 59자 + `…`)."""
    text = " ".join(line.split())
    return text if len(text) <= SNIPPET else text[:SNIPPET - 1] + "…"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def empty_excepts(lines: list[str]) -> list[tuple[int, int]]:
    """지금 파일의 빈 except 블록 (머리 줄, pass 줄)(0 부터 센 줄 번호): `except …:` 머리 다음의 첫 문장 줄(빈 줄·주석 줄은
    건너뛴다)이 머리보다 들여 쓴 `pass` 이고, 그다음 문장 줄이 머리보다 들여 쓰지 않았거나 없다(블록의 문장이 `pass` 하나)."""
    def statement(i: int) -> int:
        while i < len(lines) and _SKIP_LINE.match(lines[i]):
            i += 1
        return i
    out = []
    for i, line in enumerate(lines):
        if not _EXCEPT.match(line):
            continue
        j = statement(i + 1)
        if j == len(lines) or not _PASS.match(lines[j]) or _indent(lines[j]) <= _indent(line):
            continue
        k = statement(j + 1)
        if k == len(lines) or _indent(lines[k]) <= _indent(line):
            out.append((i, j))
    return out


def line_findings(rel: str, text: str, added: set[str]) -> list[str]:
    """추가한 줄(내용이 added 에 있는 지금 줄)의 억제 주석·시험 건너뛰기·빈 catch. 빈 catch 는 한 줄 `catch (…) {}`,
    추가한 `except …: pass` 한 줄, 그리고 머리나 `pass` 줄 가운데 하나라도 추가한 줄인 빈 except 블록(empty_excepts. 그대로 둔
    머리 아래 본문만 `pass` 로 바꾼 것도 잡는다)이다. 빈 except 블록은 머리 줄 번호로 낸다. 차례는 (줄 번호, 줄 안 위치)."""
    lines = text.split("\n")
    hits: list[tuple[int, int, str, str]] = []
    for n, line in enumerate(lines):
        if line not in added:
            continue
        hits += [(n, m.start(), name, m.group(0)) for name, rx in LINE_CHECKS for m in rx.finditer(line)]
        if _EXCEPT_PASS.match(line):
            hits.append((n, line.index("except"), "빈 catch", line.strip()))
    for head, body in empty_excepts(lines):
        if lines[head] in added or lines[body] in added:
            hits.append((head, lines[head].index("except"), "빈 catch", lines[head].strip()))
    return [f'{rel}:{n + 1}: {name} "{what}"({_shown(lines[n])})' for n, _, name, what in sorted(hits)]


def defined_tests(lines: list[str]) -> list[str]:
    """줄 목록의 시험 정의 이름: `def test_…`, `func Test…`, 줄 머리의 `it(`·`test(`(첫 인자 글자. 글자가 아니면 그 줄),
    `@Test` 다음 줄(사이의 다른 `@` 줄은 건너뛴다)의 함수 이름."""
    names = []
    for i, line in enumerate(lines):
        m = _PY_GO_TEST.match(line)
        if m:
            names.append(m.group(1) or m.group(2))
            continue
        m = _JS_TEST.match(line)
        if m:
            names.append(m.group(2) if m.group(2) is not None else line.strip())
            continue
        if _ANNOTATION.match(line):
            j = i + 1
            while j < len(lines) and j <= i + 3 and lines[j].strip().startswith("@"):
                j += 1
            call = _CALL_NAME.search(lines[j]) if j < len(lines) else None
            if call:
                names.append(call.group(1))
    return names


def _asserts(lines: list[str]) -> int:
    return sum(len(_ASSERT.findall(line)) for line in lines)


def _marks(lines: list[str]) -> int:
    """`@Test` 표시 줄 수(`@TestFactory` 같은 다른 표시는 세지 않는다)."""
    return sum(1 for line in lines if _ANNOTATION.match(line))


def _deleted(root: Path, shas: list[str], top: str) -> bool:
    """대상 커밋이 그 파일(최상위 기준 top)을 지웠는가: 마지막 대상 커밋에 없고 첫 대상 커밋의 첫 부모에는 있었다."""
    if gitio.tree_entry(root, shas[-1], top) is not None:
        return False
    ups = gitio.parents(root, shas[0])
    return bool(ups) and gitio.tree_entry(root, ups[0], top) is not None


def guard_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """files(프로젝트 기준 경로, 시도 기록의 바뀐 파일)에서 대상 커밋(shas)의 검사 약화 의심. 줄 경고(파일 차례) 뒤에 시험 파일의
    지운 파일·지운 시험·`@Test` 표시 줄어듦·단언 줄어듦(파일 차례). 프로젝트 밖(`../`)·보고서·리뷰·hteam 파일은 보지 않고, 글 문서는 줄 경고만
    보지 않는다. diff 를 읽지 못한 파일(None)은 건너뛴다. 지운 시험은 같은 이름이 바뀐 시험 파일 어디의 추가한 줄에도 없을 때다.
    MAX_FINDINGS(50)를 넘으면 마지막 항목이 `… 외 N건`."""
    root = Path(root)
    if not shas:
        return []
    found: list[str] = []
    tests: list[tuple[str, list[str], list[str]]] = []
    for rel in files:
        if rel.startswith("../") or matches_any(rel, EXCLUDE):
            continue
        lines = gitio.diff_lines(root, shas, rel)
        if lines is None:
            continue
        added, removed = lines
        text = read_source(root, rel)
        if text is not None and Path(rel).suffix.lower() not in PROSE:
            found += line_findings(rel, text, set(added))
        if is_test_file(rel):
            tests.append((rel, added, removed))
    prefix = gitio.top_prefix(root)
    added_names = {name for _, added, _ in tests for name in defined_tests(added)}
    for rel, added, removed in tests:
        if _deleted(root, shas, gitio.to_top(prefix, rel)):
            found.append(f"{rel}: 시험 파일을 지웠다")
            continue
        gone = [name for name in dict.fromkeys(defined_tests(removed)) if name not in added_names]
        if gone:
            shown = ", ".join(gone[:NAMES_SHOWN]) + (", …" if len(gone) > NAMES_SHOWN else "")
            found.append(f"{rel}: 지운 시험 {len(gone)}개({shown}) — 같은 이름을 추가한 줄이 없다")
        marks_cut, marks_put = _marks(removed), _marks(added)
        if marks_cut > marks_put:  # 함수는 두고 `@Test` 만 지우면 그 시험은 돌지 않는다
            found.append(f"{rel}: @Test 표시 {marks_cut}개 지움, {marks_put}개 더함")
        cut, put = _asserts(removed), _asserts(added)
        if cut > put:
            found.append(f"{rel}: 단언 {cut}개 지움, {put}개 더함")
    return cap(found)
