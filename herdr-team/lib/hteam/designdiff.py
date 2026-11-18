"""디자인 diff 자동 검사(설계 11.6·11.13 의 2): 리뷰 대상 커밋의 지운 줄에서 줄어든 접근성·글자 신호, 지운 줄의 보존
신호(링크·입력란 이름·이벤트·시험 ID 값이 같은 변경의 추가한 줄에 없다), 추가한 줄의 확대 막기와 대체 없는 포커스 제거를
찾는다.

결과는 경고다(판정은 리뷰어가 디자인 기준 4번·6번으로 한다). git 은 gitio.diff_lines 로만 읽는다. 표준 라이브러리 정규식만
쓰고 hc·horch·codex 를 부르지 않는다. 상한은 없다(디자인 절이 내용 검사와 합친 뒤 자른다).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import gitio
from .globs import matches_any
from .lint import EXCLUDE, MAX_BYTES, read_source

# 내용 검사(lint.SUFFIXES)에서 .md 를 빼고(설명 글이 신호 낱말을 담는다) 앱 형식을 더한다
SUFFIXES = frozenset({".html", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".json", ".dart",
                      ".swift", ".kt", ".xml"})
SNIPPET = 60


def _attr(name: str) -> re.Pattern:
    """속성 값이 오는 꼴만: 앞이 낱말 글자·`.`·`$`·`-` 가 아니고 `이름 = ` 뒤에 따옴표나 `{`(`const role = user.role` 은 아니다)."""
    return re.compile(rf"(?<![\w.$-]){name}\s*=\s*[\"'{{]")


def _variant(name: str) -> re.Pattern:
    """Tailwind 변형: 앞이 낱말 글자·`-` 가 아니고 콜론 바로 뒤에 클래스(낱말 글자·`!`·`[`). JS 객체 `focus: {` 는 아니다."""
    return re.compile(rf"(?<![\w-]){re.escape(name)}:(?=[\w!\[])")


def _word(name: str) -> re.Pattern:
    return re.compile(rf"\b{re.escape(name)}\b")


def _text(name: str) -> re.Pattern:
    return re.compile(re.escape(name))


# (신호 이름, 정규식). 이 순서로 알린다. 줄마다 일치 개수를 센다
SIGNALS = (
    ("aria-label", re.compile(r"aria-label(?!ledby)")),
    ("aria-labelledby", _text("aria-labelledby")),
    ("aria-describedby", _text("aria-describedby")),
    ("aria-live", _text("aria-live")),
    ("aria-expanded", _text("aria-expanded")),  # 13단계 p13d: 토글 상태(web-rules §7 의 10)
    ("aria-pressed", _text("aria-pressed")),
    ("role", _attr("role")),
    ("alt", _attr("alt")),
    ("lang", _attr("lang")),
    ("<label", re.compile(r"<label\b")),
    ("htmlFor", _word("htmlFor")),
    ("<caption", re.compile(r"<caption\b")),  # 13단계 p13d: 표 머리(web-rules §7 의 3)
    # scope 는 표 머리의 값(row·col·rowgroup·colgroup)이 있을 때만 센다(따옴표·따옴표 없음·`{"col"}`). `const scope = view` 는 아니다
    ("scope", re.compile(r"""(?<![\w.$-])scope\s*=\s*(?:\{\s*)?["'`]?(?:row|col)(?:group)?\b""")),
    (":focus-visible", _text(":focus-visible")),
    (":focus", re.compile(r":focus(?!-)")),
    ("focus-visible:", _variant("focus-visible")),
    ("focus:", _variant("focus")),
    ("motion-reduce:", _variant("motion-reduce")),
    ("motion-safe:", _variant("motion-safe")),
    (".focus(", _text(".focus(")),
    ("tabindex", re.compile(r"\btab[iI]ndex\b")),
    ("prefers-reduced-motion", _text("prefers-reduced-motion")),
    ("prefers-contrast", _text("prefers-contrast")),
    ("useReducedMotion", _word("useReducedMotion")),
    ("keep-all", _text("keep-all")),
    ("break-keep", re.compile(r"(?<![\w-])break-keep(?![\w-])")),
    ("tabular-nums", _text("tabular-nums")),
    *((name, _word(name)) for name in ("semanticsLabel", "semanticLabel")),
    ("Semantics(", re.compile(r"\bSemantics\(")),
    *((name, _word(name)) for name in ("accessibilityLabel", "accessibilityHint", "contentDescription",
                                       "accessibilityReduceMotion", "isReduceMotionEnabled", "disableAnimations")),
)
ZOOM = (re.compile(r"user-scalable\s*=\s*[\"']?(?:no|0)(?![\w.])", re.I),
        re.compile(r"maximum-scale\s*=\s*[\"']?1(?:\.0*)?(?![\d.])", re.I),
        re.compile(r"userScalable\s*:\s*false", re.I),
        re.compile(r"maximumScale\s*:\s*1(?:\.0*)?(?![\d.])", re.I))
NO_OUTLINE = (re.compile(r"outline(?:-style)?\s*:\s*[\"']?(?:none|0|0px)(?![\w.%-])", re.I),
              re.compile(r"(?<![\w-])outline-(?:none|hidden)(?![\w-])"))
# 대체 포커스가 아닌 Tailwind focus: 클래스(포커스 표시를 지우거나 보이지 않게 한다)
WEAK_FOCUS = frozenset({"outline-none", "outline-hidden", "ring-0", "shadow-none", "ring-transparent"})
_FOCUS_CLASS = re.compile(r"(?<![\w-])focus:!?([\w\[\]#%./:-]+)")


# 보존 신호(설계 11.13 의 2, 13단계). 값은 큰따옴표·작은따옴표, 또는 JSX `{"…"}`·`{'…'}`·`` {`…`} `` 안의 글이다.
_QUOTED = r"""(?:"([^"\n]*)"|'([^'\n]*)'|\{\s*["'`]([^"'`\n]*)["'`]\s*\})"""
_HREF = re.compile(rf"(?<![\w-])href\s*=\s*{_QUOTED}")
_LINK_TO = re.compile(rf"(?<![\w-])to\s*=\s*{_QUOTED}")  # 라우터 링크의 to: 남은 링크로만 본다
_TESTID = re.compile(rf"(?<![\w-])data-testid\s*=\s*{_QUOTED}")
_TEST_TAG = re.compile(r"""\btestTag\(\s*"([^"\n]*)"\s*\)""")
_A11Y_ID = re.compile(r'\baccessibilityIdentifier\s*(?:=\s*|\(\s*)"([^"\n]*)"')
_INPUT_TAG = re.compile(r"<(?:input|select|textarea)\b", re.I)
_INPUT_ATTR = re.compile(rf"(?<![\w-])(name|id)\s*=\s*{_QUOTED}")
_EVENT = re.compile(r"(?<![\w-])(onClick|onclick|@click(?:\.[\w-]+)*)\s*=\s*")
_LISTENER = re.compile(r"""\baddEventListener\(\s*["'`]([\w:-]+)["'`]""")
_LISTENER_KIND = "이벤트 addEventListener"


def _value(m: re.Match, first: int = 1) -> str:
    return " ".join(next((g for g in m.groups()[first - 1:] if g is not None), "").split())


SCAN_LIMIT = 2000  # 여러 줄 읽기의 창 크기(선형을 지킨다)
MAX_OPEN_SCANS = 200  # 한 줄·한 파일에서 닫히지 않은 `{…}` 읽기를 이만큼 하면 더 읽지 않는다


def _event_value(line: str, start: int, limit: int | None = None) -> str | None:
    """line[start] 에서 시작하는 이벤트 속성 값: 따옴표 글, 또는 같은 줄에서 짝이 맞는 `{…}` 의 안(중첩 중괄호 포함,
    `{() => { save(); }}`). 줄 안에서 닫히지 않으면 None. limit 이 있으면 `{…}` 를 줄 경계 없이 limit 글자 안에서 읽는다(최종 파일의 여러 줄 처리기)."""
    quote = line[start:start + 1]
    if quote in ('"', "'"):
        end = line.find(quote, start + 1, len(line) if limit is None else start + 1 + limit)
        return line[start + 1:end] if end >= 0 else None
    if quote != "{":
        return None
    depth = 0
    for i in range(start, len(line) if limit is None else min(len(line), start + limit)):
        if line[i] == "{":
            depth += 1
        elif line[i] == "}":
            depth -= 1
            if depth == 0:
                return line[start + 1:i]
    return None


def kept_values(line: str) -> list[tuple[str, str]]:
    """한 줄의 보존 신호 (종류, 값). 값은 공백을 하나로 줄인 속성 값 전체다. 빈 값과 `href="#"` 는 뺀다. 입력란 name·id 는
    `<input`·`<select`·`<textarea` 가 든 줄에서만 본다(여러 줄에 걸친 태그는 놓친다)."""
    out = [("링크 href", _value(m)) for m in _HREF.finditer(line)]
    out += [("링크 href", _value(m)) for m in _LINK_TO.finditer(line)]  # 라우터 링크의 to 도 링크다
    if _INPUT_TAG.search(line):
        out += [(f"입력란 {m.group(1)}", _value(m, 2)) for m in _INPUT_ATTR.finditer(line)]
    open_scans = 0  # 닫히지 않아 창을 다 쓴 읽기 횟수(되풀이되는 병적인 줄에서도 선형으로 끝낸다)
    for m in _EVENT.finditer(line):
        value = _event_value(line, m.end(), SCAN_LIMIT)  # 값마다 창 안에서 끝난다
        if value is not None:
            out.append((f"이벤트 {m.group(1)}", " ".join(value.split())))
        elif line.startswith("{", m.end()):
            open_scans += 1
            if open_scans > MAX_OPEN_SCANS:
                break
    out += [(_LISTENER_KIND, m.group(1)) for m in _LISTENER.finditer(line)]
    out += [("data-testid", _value(m)) for m in _TESTID.finditer(line)]
    out += [("testTag", m.group(1)) for m in _TEST_TAG.finditer(line)]
    out += [("accessibilityIdentifier", m.group(1)) for m in _A11Y_ID.finditer(line)]
    return [(kind, v) for kind, v in out if v and not (kind == "링크 href" and v == "#")]


def _key(kind: str) -> str:
    """같은 것으로 보는 종류: 링크(href·라우터 to), 이벤트 처리 값(onClick·onclick·@click), 그 밖은 종류 그대로."""
    if kind == "링크 href":
        return "링크"
    if kind.startswith("이벤트 ") and kind != _LISTENER_KIND:
        return "이벤트"
    return kind


def final_values(text: str) -> set[tuple[str, str]]:
    """파일 글(마지막 리뷰 대상 커밋의 내용)에 있는 보존 신호 (_key 종류, 값 전체). 줄 단위로 읽은 것에 더해, 여러 줄로
    나뉜 입력 태그의 name·id 와 여러 줄 `{…}` 처리기도 읽는다(Prettier 줄바꿈. 창은 SCAN_LIMIT 글자)."""
    out: set[tuple[str, str]] = set()
    for line in text.split("\n"):
        out |= {(_key(kind), value) for kind, value in kept_values(line)}
    for tag in _INPUT_TAG.finditer(text):
        window = text[tag.start():tag.start() + SCAN_LIMIT]
        close = re.search(r"(?<!=)>", window)  # 화살표 `=>` 는 태그 끝이 아니다
        if close:
            window = window[:close.start()]
        out |= {(f"입력란 {m.group(1)}", _value(m, 2)) for m in _INPUT_ATTR.finditer(window)}
    open_scans = 0
    for m in _EVENT.finditer(text):
        if text[m.end():m.end() + 1] == "{":
            value = _event_value(text, m.end(), SCAN_LIMIT)
            if value is not None and " ".join(value.split()):
                out.add(("이벤트", " ".join(value.split())))
            elif value is None:
                open_scans += 1
                if open_scans > MAX_OPEN_SCANS:
                    break
    return out


def _short(text: str) -> str:
    """공백을 하나로 줄이고 앞 60자(내용 검사 발췌와 같다)."""
    return " ".join(text.split())[:SNIPPET]


def _kept_findings(rel: str, removed: list[str], final: set[tuple[str, str]]) -> list[str]:
    """지운 줄의 보존 신호 가운데 마지막 커밋의 대상 파일 어디에도 같은 종류·값 전체로 남지 않은 것(지운 줄 차례, (종류,
    값)마다 한 번). 중간 커밋이 더했다가 지운 줄은 남은 것이 아니다."""
    seen: set[tuple[str, str]] = set()
    found = []
    for line in removed:
        for kind, value in kept_values(line):
            if (kind, value) in seen:
                continue
            seen.add((kind, value))
            if (_key(kind), value) not in final:
                found.append(f'{rel}: 보존 신호 — 지운 {kind} "{_short(value)}"(같은 변경에 대신하는 것이 없다)')
    return found


def _counts(lines: list[str]) -> Counter:
    found: Counter = Counter()
    for line in lines:
        for name, rx in SIGNALS:
            found[name] += len(rx.findall(line))
    return found


def has_focus_alternative(text: str) -> bool:
    """파일 어디든 대체 포커스가 있나: `focus-visible` 글자, 또는 지우는 클래스가 아닌 Tailwind `focus:` 클래스
    (`dark:focus:ring-2`·`focus:!ring-2` 도). `:focus` 셀렉터는 대체가 아니다."""
    if "focus-visible" in text:
        return True
    return any(m.group(1) not in WEAK_FOCUS for m in _FOCUS_CLASS.finditer(text))


def _take(lines: list[str], budget: Counter) -> list[str]:
    """budget(줄 → 남은 수)만큼 lines 에서 같은 줄을 앞에서부터 뺀다."""
    out = []
    for line in lines:
        if budget[line] > 0:
            budget[line] -= 1
        else:
            out.append(line)
    return out


def _added_findings(rel: str, text: str, added: set[str]) -> list[str]:
    """지금 파일에서 내용이 added 에 있는 줄의 확대 막기·포커스 제거(줄 번호 순)."""
    found = []
    alternative = None
    for number, line in enumerate(text.split("\n"), 1):
        if line not in added:
            continue
        zoom = [m.start() for rx in ZOOM for m in [rx.search(line)] if m]
        if zoom:
            found.append(f"{rel}:{number}: 확대 막기({_short(line[min(zoom):])})")
        if any(rx.search(line) for rx in NO_OUTLINE):
            if alternative is None:
                alternative = has_focus_alternative(text)
            if not alternative:
                found.append(f"{rel}:{number}: 포커스 표시 제거({_short(line)}, 파일에 focus-visible 없음)")
    return found


def design_diff_lint(root: Path, files: list[str], shas: list[str]) -> list[str]:
    """files(시도 기록의 바뀐 파일) 가운데 대상 파일의 diff 경고. 파일 순서, 파일 안에서 지운 줄 신호(SIGNALS 순서) →
    보존 신호(지운 줄 차례) → 추가한 줄(줄 번호 순).

    보존 신호: 그 파일의 지운 줄에 있는 링크·입력란 name·id·이벤트·시험 ID 값이, 마지막 리뷰 대상 커밋(shas 의 끝)의 대상 파일
    어디에도 같은 종류·값 전체로 없을 때 알린다(gitio.file_text. 옮긴 줄·다른 파일로 옮긴 컴포넌트는 걸러지고, 지운 파일은 아무
    것도 남기지 않는다. 커밋마다 합친 추가한 줄로 보면 중간 커밋이 고쳤다가 다음 커밋이 지운 링크를 남은 것으로 본다).

    지운 줄: 모든 대상 파일에 걸쳐 내용이 같은 지운 줄·추가한 줄(옮긴 줄)을 짝지어 뺀 나머지로 파일별 신호 수를 센다.
    태스크 전체 순감소(net)가 0 보다 크고 그 파일에서 줄었을 때만 알린다(줄 나누기·옮긴 파일·컴포넌트 추출은 걸러진다).
    추가한 줄: 그 파일 diff 의 추가한 줄 가운데 태스크가 어디서도 지우지 않은 내용을 지금 파일에서 본다."""
    diffs: dict[str, tuple[list[str], list[str]]] = {}
    for rel in files:
        if rel.startswith("../") or Path(rel).suffix.lower() not in SUFFIXES or matches_any(rel, EXCLUDE):
            continue
        lines = gitio.diff_lines(root, shas, rel)
        if lines is not None:
            diffs[rel] = lines
    all_added = Counter(line for added, _ in diffs.values() for line in added)
    all_removed = Counter(line for _, removed in diffs.values() for line in removed)
    moved = all_added & all_removed
    take_added, take_removed = Counter(moved), Counter(moved)
    gone, came = {}, {}
    for rel, (added, removed) in diffs.items():
        gone[rel] = _counts(_take(removed, take_removed))
        came[rel] = _counts(_take(added, take_added))
    net = Counter()
    for rel in diffs:
        for name, _ in SIGNALS:
            net[name] += gone[rel][name] - came[rel][name]
    removed_anywhere = set(all_removed)
    final: set[tuple[str, str]] = set()
    unread: set[str] = set()  # 1 MiB 를 넘어 최종 글을 읽지 않은 파일(그 파일의 지운 값은 남았는지 확인할 수 없어 알리지 않는다)
    for rel in diffs if shas else ():
        size = gitio.file_size(root, shas[-1], rel)
        if size is not None and size > MAX_BYTES:
            unread.add(rel)
            continue
        text = gitio.file_text(root, shas[-1], rel)
        if text is not None:
            final |= final_values(text)
    found: list[str] = []
    for rel, (added, removed) in diffs.items():
        for name, _ in SIGNALS:
            lost = gone[rel][name] - came[rel][name]
            if lost > 0 and net[name] > 0:
                found.append(f"{rel}: 지운 줄에서 {name} {lost}개가 줄었다(대체가 있는지 확인)")
        if rel not in unread:
            found += _kept_findings(rel, removed, final)
        text = read_source(root, rel)
        if text is not None:
            found += _added_findings(rel, text, set(added) - removed_anywhere)
    return found
