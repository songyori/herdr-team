"""owns glob(설계 5.2). `**` 는 디렉터리를 넘고, `*`·`?` 는 한 마디 안이다. 겹침 판정은 보수적이다.

git `:(glob)` pathspec 과 같게 읽히도록 와일드카드 없는 경로는 그 아래도 덮는다(디렉터리). git 과 다르게 읽히는
문자(`[]{},\\`)와 정규화되지 않은 경로(`.`·`..`·빈 마디, 앞뒤 `/`), 마디 일부인 `**` 는 owns_problem 이 막는다."""
from __future__ import annotations

import re
from functools import lru_cache

GLOB_CHARS = "*?["
BAD_CHARS = "[]{},\\"


@lru_cache(maxsize=512)
def _regex(pattern: str) -> re.Pattern:
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches(path: str, pattern: str) -> bool:
    if literal_prefix(pattern) == pattern:  # git 처럼 고정 경로는 그 아래 경로도 덮는다
        return path == pattern or path.startswith(pattern + "/")
    return bool(_regex(pattern).match(path))


def matches_any(path: str, patterns) -> bool:
    return any(matches(path, p) for p in patterns)


def literal_prefix(pattern: str) -> str:
    cut = min((pattern.index(c) for c in GLOB_CHARS if c in pattern), default=len(pattern))
    return pattern[:cut]


def owns_problem(pattern: str) -> str | None:
    """owns 로 쓸 수 없으면 까닭, 쓸 수 있으면 None. git `:(glob)` 과 matches() 가 다르게 읽거나 사양 front matter
    (쉼표로 나눈 한 줄)에서 갈라지는 값을 막는다."""
    if pattern.splitlines() != [pattern]:
        return "한 줄이어야 한다"
    bad = "".join(c for c in BAD_CHARS if c in pattern)
    if bad:
        return f"{bad} 를 쓸 수 없다"
    if pattern.startswith("/") or pattern.endswith("/"):
        return "/ 로 시작하거나 끝날 수 없다"
    parts = pattern.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "빈 마디나 . · .. 마디를 쓸 수 없다"
    if any("**" in part and part != "**" for part in parts):
        return "** 는 마디 전체로만 쓴다"
    return None


def _under(a: str, b: str) -> bool:
    """고정 경로 a 아래(a/…)의 경로를 glob b 가 덮을 수 있는가(보수적)."""
    head, pb = a + "/", literal_prefix(b)
    if not (head.startswith(pb) or pb.startswith(head)):
        return False
    # `**` 가 없으면 b 는 마디 수가 b 와 같은 경로만 덮는다. a 아래 경로는 a 보다 마디가 많다.
    return "**" in b or b.count("/") > a.count("/")


def overlaps(a: str, b: str) -> bool:
    """두 glob 의 고정 접두사 중 하나가 다른 하나의 접두사면 겹친다고 본다. 고정 경로는 그 아래까지 덮는다.

    대소문자는 구분하지 않는다: 대소문자를 무시하는 파일시스템(macOS 기본)에서 `src/Foo` 와 `src/foo` 는 같은
    디렉터리다. 구분하는 파일시스템에서는 병렬 시작만 막혀 안전한 쪽이다. matches·within 은 그대로 구분한다
    (owns 안·밖 판정을 넓히면 사전 검사·변조 검사가 놓친다)."""
    a, b = a.casefold(), b.casefold()
    pa, pb = literal_prefix(a), literal_prefix(b)
    if pa == a and pb == b:
        return matches(a, b) or matches(b, a)
    if pa == a:
        return matches(a, b) or _under(a, b)
    if pb == b:
        return matches(b, a) or _under(b, a)
    return pa.startswith(pb) or pb.startswith(pa)


def any_overlap(xs, ys) -> list[tuple[str, str]]:
    return [(x, y) for x in xs for y in ys if overlaps(x, y)]


def within(inner: str, outer: str) -> bool:
    """inner 가 outer 안에 있다고 확실할 때만 True(보수적). 판단할 수 없으면 False.

    같은 glob, 둘 다 고정 경로이고 inner 가 outer 와 같거나 그 아래일 때, outer 가 `<고정 접두사>**` 이고 inner 의
    고정 접두사가 그 접두사로 시작할 때만 안이다(설계 4.1: front matter owns 는 직무 owns 를 좁힌다). 고정 경로 inner 는
    그 아래 전체(git·matches)라 outer 가 그 전체를 덮어야 한다: `src/a.py` 는 `src/*.py` 안이 아니다.
    owns_problem 에 걸리면 안이 아니다."""
    if owns_problem(inner) or owns_problem(outer):
        return False
    if inner == outer:
        return True
    if literal_prefix(inner) == inner and literal_prefix(outer) == outer:
        return matches(inner, outer)
    head = outer[:-2]
    return outer.endswith("**") and literal_prefix(outer) == head and literal_prefix(inner).startswith(head)
