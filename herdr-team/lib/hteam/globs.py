"""owns glob(설계 5.2). `**` 는 디렉터리를 넘고, `*`·`?` 는 한 마디 안이다. 겹침 판정은 보수적이다."""
from __future__ import annotations

import re
from functools import lru_cache

GLOB_CHARS = "*?["


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
    return bool(_regex(pattern).match(path))


def matches_any(path: str, patterns) -> bool:
    return any(matches(path, p) for p in patterns)


def literal_prefix(pattern: str) -> str:
    cut = min((pattern.index(c) for c in GLOB_CHARS if c in pattern), default=len(pattern))
    return pattern[:cut]


def overlaps(a: str, b: str) -> bool:
    """두 glob 의 고정 접두사 중 하나가 다른 하나의 접두사면 겹친다고 본다. 둘 다 글자 그대로면 같을 때만."""
    pa, pb = literal_prefix(a), literal_prefix(b)
    if pa == a and pb == b:
        return a == b
    if pa == a:
        return matches(a, b)
    if pb == b:
        return matches(b, a)
    return pa.startswith(pb) or pb.startswith(pa)


def any_overlap(xs, ys) -> list[tuple[str, str]]:
    return [(x, y) for x in xs for y in ys if overlaps(x, y)]


def within(inner: str, outer: str) -> bool:
    """inner 가 outer 안에 있다고 확실할 때만 True(보수적). 판단할 수 없으면 False.

    같은 glob, 와일드카드 없는 경로가 outer 에 맞을 때, outer 가 `<고정 접두사>**` 이고 inner 의 고정 접두사가
    그 접두사로 시작할 때만 안이다(설계 4.1: front matter owns 는 직무 owns 를 좁힌다)."""
    if inner == outer:
        return True
    if literal_prefix(inner) == inner:
        return matches(inner, outer)
    head = outer[:-2]
    return outer.endswith("**") and literal_prefix(outer) == head and literal_prefix(inner).startswith(head)
