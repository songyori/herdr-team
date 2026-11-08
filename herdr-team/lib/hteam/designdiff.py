"""디자인 diff 자동 검사(설계 11.6): 리뷰 대상 커밋의 지운 줄에서 줄어든 접근성·글자 신호와, 추가한 줄의 확대 막기와
대체 없는 포커스 제거를 찾는다.

결과는 경고다(판정은 리뷰어가 디자인 기준 4번·6번으로 한다). git 은 gitio.diff_lines 로만 읽는다. 표준 라이브러리 정규식만
쓰고 hc·horch·codex 를 부르지 않는다. 상한은 없다(디자인 절이 내용 검사와 합친 뒤 자른다).
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from . import gitio
from .globs import matches_any
from .lint import EXCLUDE, read_source

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
    ("role", _attr("role")),
    ("alt", _attr("alt")),
    ("lang", _attr("lang")),
    ("<label", re.compile(r"<label\b")),
    ("htmlFor", _word("htmlFor")),
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


def _short(text: str) -> str:
    """공백을 하나로 줄이고 앞 60자(내용 검사 발췌와 같다)."""
    return " ".join(text.split())[:SNIPPET]


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
    추가한 줄(줄 번호 순).

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
    found: list[str] = []
    for rel, (added, _) in diffs.items():
        for name, _ in SIGNALS:
            lost = gone[rel][name] - came[rel][name]
            if lost > 0 and net[name] > 0:
                found.append(f"{rel}: 지운 줄에서 {name} {lost}개가 줄었다(대체가 있는지 확인)")
        text = read_source(root, rel)
        if text is not None:
            found += _added_findings(rel, text, set(added) - removed_anywhere)
    return found
