"""묶음 후속(설계 8.4): `hteam followups T-xxx | --rest`. 리뷰 파일의 막지 않는 항목(`## 회귀`, `## 후속`, `## 기획 누락`)을
모아 관제가 회귀 수정 태스크, 묶음 정리 태스크, decide 를 만들게 한다.

읽기 전용이다(아무것도 쓰지 않는다). 같은 대상을 다시 부르면 같은 결과다. 중복 제거는 하지 않는다. 역할을 확인하지 않고
config.toml 을 읽지 않는다.
"""
from __future__ import annotations

import re

from . import specs, state
from .errors import USAGE, HteamError
from .paths import find_project, review_rel
from .testgate import DEVELOPER_ROLE, TESTER_ROLE

SECTIONS = (("regressions", "회귀"), ("followups", "후속"), ("planning_gaps", "기획 누락"))
ITEM_ID_RE = re.compile(r"^(r\d+-F\d+)\b")
EMPTY_RE = re.compile(r"^\(?\*{0,2}(?:해당 ?없음|없음)\*{0,2}\)?(?:$|[\s(（).,;:!?·—–-])")
SOURCE_RE = re.compile(r"^출처: (T-\d{3,}|rest|final) followups\s*$")


def _section(text: str, title: str) -> str | None:
    found = re.search(rf"^## {re.escape(title)}[ \t]*\n(.*?)(?=^## |^VERDICT:|\Z)", text, re.M | re.S)
    return found.group(1) if found else None


def section_items(text: str, title: str) -> list[str]:
    """절의 항목: 정확히 `- ` 로 시작하는 줄이 새 항목이고 공백·탭으로 들여 쓴 비지 않은 다음 줄은 앞 항목에 공백 하나로
    잇는다. `* `·`1.` 글머리는 항목이 아니다. 빈 항목(`없음`·`해당 없음` 등)은 뺀다."""
    body = _section(text, title)
    if body is None:
        return []
    items: list[str] = []
    for line in body.splitlines():
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif items and line[:1] in (" ", "\t") and line.strip():
            items[-1] += " " + line.strip()
    return [x for x in items if not is_empty(x)]


def is_empty(item: str) -> bool:
    """`rN-Fk` 로 시작하는 항목은 빈 항목이 아니다(EMPTY_RE 가 `^` 로 시작해 실제로는 겹치지 않는다)."""
    return not ITEM_ID_RE.match(item) and bool(EMPTY_RE.match(item))


def source_of(p, tid: str) -> str | None:
    """후속 처리로 만든 태스크의 출처: 사양의 `## Change` 절 첫 비지 않은 줄이 `출처: T-xxx|rest|final followups` 면 그
    그룹(`T-xxx`·`rest`·`final`). 아니거나 사양을 읽지 못하면 None(관제의 중복 방지, 설계 8.9)."""
    try:
        body = specs.load(p, tid).body
    except (HteamError, OSError, UnicodeDecodeError):
        return None
    change = _section(body, "Change") or ""
    first = next((line for line in change.splitlines() if line.strip()), "")
    found = SOURCE_RE.match(first)
    return found.group(1) if found else None


def _from_followups(p, tid: str) -> bool:
    """후속 처리로 만든 태스크(source_of 가 있다). 사양을 읽지 못하면 아니다."""
    return source_of(p, tid) is not None


def latest_review(p, st: dict) -> tuple[int, str] | None:
    """상태 rounds 를 큰 라운드부터 보며 `docs/reviews/T-xxx/rN.md` 가 있는 첫 라운드의 (라운드, 내용). 없으면 None."""
    for rd in sorted(st.get("rounds") or [], key=lambda r: r.get("round", 0), reverse=True):
        path = p.root / review_rel(st["id"], rd["round"])
        try:
            return rd["round"], path.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            continue
    return None


def group_members(p, tid: str) -> list[str]:
    """tester 면 사양 depends_on 가운데 상태의 직무가 developer 인 것(순서 그대로) + tester 자신. 아니면 그 태스크 하나."""
    st = state.load(p, tid)  # ID 형식이 아니면 bad_task_id(exit 2)
    if st is None:
        raise HteamError("not_started", f"{tid} 는 아직 시작하지 않은 태스크다(hteam start)", USAGE)
    if st.get("role") != TESTER_ROLE:
        return [tid]
    members = []
    for dep in specs.load(p, tid).depends_on:
        dst = state.load(p, dep) if state.ID_RE.fullmatch(dep) else None
        if dst is not None and dst.get("role") == DEVELOPER_ROLE:
            members.append(dep)
    return [*members, tid]


def rest_members(p) -> list[str]:
    """모든 상태 가운데 직무 developer, 상태 done, 어떤 tester 태스크 사양의 depends_on 에도 없는 것(ID 순). tester 의 상태는
    보지 않는다(dropped tester 의 묶음도 묶음에 든 것으로 친다, 한계)."""
    states = state.all_states(p)
    grouped: set[str] = set()
    for st in states:
        if st.get("role") == TESTER_ROLE:
            try:
                grouped.update(specs.load(p, st["id"]).depends_on)
            except HteamError:
                continue
    return [st["id"] for st in states
            if st.get("role") == DEVELOPER_ROLE and st["status"] == "done" and st["id"] not in grouped]


def collect(p, tids: list[str]) -> dict:
    out: dict = {"tasks": tids, **{key: [] for key, _ in SECTIONS}}
    for tid in tids:
        st = state.load(p, tid)
        found = latest_review(p, st) if st else None
        if found is None:
            continue
        rnd, text = found
        derived = _from_followups(p, tid)
        for key, title in SECTIONS:
            if key == "followups" and derived:  # 정리 태스크가 다시 정리 태스크를 낳지 않게 한다
                continue
            for item in section_items(text, title):
                m = ITEM_ID_RE.match(item)
                out[key].append({"task": tid, "round": rnd, "id": m.group(1) if m else None, "text": item})
    return out


def _cmd(args) -> dict:
    p = find_project(args.root)
    if bool(args.task) == bool(args.rest):
        raise HteamError("usage", "태스크 ID 와 --rest 중 하나만 준다", USAGE)
    return collect(p, rest_members(p) if args.rest else group_members(p, args.task))


def register(sub) -> None:
    s = sub.add_parser("followups")
    s.add_argument("task", nargs="?")
    s.add_argument("--rest", action="store_true")
    s.set_defaults(func=_cmd)
