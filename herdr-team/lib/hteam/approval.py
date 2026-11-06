"""사용자 일괄 승인(설계 11.4): `hteam design-review`.

승인 직무(user_approval_roles) 태스크는 리뷰 승인 뒤 accept 로 awaiting_user 가 된다. 진행 중(working·reviewing·
approved·changes·launch_failed)이거나 지금 바로 시작할 수 있는(사양 통과·의존 충족·잠금 비어 있음) 승인 직무 태스크가
없을 때, 그 순간 awaiting_user 인 승인 태스크 가운데 아직 묻지 않은 (태스크, 라운드) 전부를 outbox 의 approval 항목
하나로 묻는다. 승인 → 비승인 → 승인 사슬의 뒤 태스크는 비승인 태스크가 done 이어야 시작할 수 있으므로 앞 묶음을 막지
않고 다음 묶음이 된다.

stale: 승인 태스크의 선행(직간접)이 이 태스크의 현재 라운드를 연 뒤에 새 라운드를 열었으면 이 태스크는 옛 선행을 보고
만든 것이다. 일괄 승인 결정(decide)은 의존 승인 태스크를 선행과 함께 고치므로 stale 은 결정 밖에서 선행을 고친 경우뿐이다.
읽기만 하는 검사다: stale 인 awaiting_user 태스크는 묻지 않고(approval_stale) accept 가 받지 않는다. 기준은 그 라운드의
워커를 새로 띄울 때 본 선행의 끝난 라운드(basis, tasks._finished_round: 선행이 done·awaiting_user·approved·dropped 면
그 라운드, 아니면 앞 라운드. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이면 그대로 둔다)다. basis 에 없는 선행은
라운드 0 을 본 것으로 본다. basis 가 없는 라운드(옛 기록)는 history 의 그 라운드 start·fix 시각으로 본다.

기록 `state/design-review.json` = {"batches": [{"batch": "dr-0001", "at", "id": "out-NNNN" | null, "render",
"tasks": [{"task", "round"}]}]}. 한 (태스크, 라운드)는 한 번만 묻는다(수정 라운드는 라운드가 달라 다시 묻는다).
쓰는 순서: 기록(id 없음) → outbox 항목(batch 를 붙인다) → 기록의 id. 모두 프로젝트 잠금 안에서 한다. 그 사이 죽으면
다음 호출이 새 묶음보다 먼저 outbox 에서 같은 batch 를 찾아 id 를 채우거나, 없으면 저장한 render 로 마저 쓴다(같은
묶음을 두 번 묻지 않는다). 기록을 읽지 못하거나 모양이 틀리면 덮어쓰지 않고 exit 1 이다.
"""
from __future__ import annotations

import re

from . import config, outbox, roles, specs, state, tasks
from .errors import CONFLICT, USAGE, HteamError
from .paths import find_project, report_rel
from .util import bad_side_file, die_at, now, read_json_strict, write_json

PROGRESS = frozenset({"working", "reviewing", "approved", "changes", "launch_failed"})
# 아티팩트 링크. 괄호·따옴표·꺾쇠·공백·제어 문자는 URL 밖이다(context 에 그대로 들어가므로 render 검사를 지나야 한다)
URL_RE = re.compile(r"https://claude\.ai/[A-Za-z0-9._~:/?#@!$&*+,;=%-]+")
BATCH_RE = re.compile(r"dr-\d{4,}")
OUT_RE = re.compile(r"out-\d{4,}")
CONTEXT_MAX = 4000
TITLE_MAX = 60
HEADER = "디자인 승인"
APPROVE = "모두 승인 (추천)"
REVISE = "수정 요청"


def _task_ok(t) -> bool:
    return (isinstance(t, dict) and isinstance(t.get("task"), str) and state.ID_RE.fullmatch(t["task"]) is not None
            and isinstance(t.get("round"), int) and not isinstance(t["round"], bool) and t["round"] >= 1)


def _problem(b) -> str | None:
    """묶음 기록 하나의 모양 문제(없으면 None)."""
    if not isinstance(b, dict):
        return "묶음이 객체가 아니다"
    if not isinstance(b.get("batch"), str) or not BATCH_RE.fullmatch(b["batch"]):
        return f"batch 가 dr-NNNN 이 아니다: {b.get('batch')!r}"
    if not isinstance(b.get("at"), str):
        return f"{b['batch']}: at 이 없다"
    if b.get("id") is not None and not (isinstance(b["id"], str) and OUT_RE.fullmatch(b["id"])):
        return f"{b['batch']}: id 가 out-NNNN 이나 null 이 아니다: {b['id']!r}"
    if not isinstance(b.get("tasks"), list) or not b["tasks"] or not all(_task_ok(t) for t in b["tasks"]):
        return f"{b['batch']}: tasks 가 [{{task, round}}] 가 아니다"
    try:
        outbox.validate_render(b.get("render"), HEADER)
    except HteamError as exc:
        return f"{b['batch']}: render 가 질문 형식이 아니다({exc.message})"
    return None


def load(p) -> dict:
    """design-review.json. 없으면 빈 기록. 읽지 못하거나 모양이 틀리면(필수 필드·타입, 묶음·out-id·태스크 라운드 중복)
    bad_side_file 이다(덮어쓰지 않는다. 그 기록으로 outbox 에 쓰지도 않는다)."""
    data = read_json_strict(p.design_review, {"batches": []})
    if not isinstance(data, dict) or not isinstance(data.get("batches"), list):
        raise bad_side_file(p.design_review, "batches 목록이 아니다")
    batches, ids, keys = set(), set(), set()
    for b in data["batches"]:
        why = _problem(b)
        if why is None:
            mine = {(t["task"], t["round"]) for t in b["tasks"]}
            if b["batch"] in batches:
                why = f"{b['batch']} 가 두 번 나온다"
            elif b.get("id") is not None and b["id"] in ids:
                why = f"{b['id']} 가 두 묶음에 있다"
            elif len(mine) != len(b["tasks"]) or mine & keys:
                why = f"{b['batch']}: 같은 태스크·라운드를 두 번 물었다"
            keys |= mine
        if why:
            raise bad_side_file(p.design_review, why)
        batches.add(b["batch"])
        if b.get("id") is not None:
            ids.add(b["id"])
    return data


def asked(data: dict) -> dict[tuple[str, int], str | None]:
    """이미 물은 (태스크, 라운드) → 그 묶음의 out-id(쓰다 멈췄으면 None)."""
    return {(t["task"], t["round"]): b.get("id") for b in data["batches"] for t in b["tasks"]}


class Graph:
    """사양의 depends_on 으로 본 태스크 그래프(읽기만). 사양을 읽지 못하는 태스크는 의존이 없고 직무를 모르는 것으로 본다."""

    def __init__(self, p):
        self.p = p
        self._deps: dict[str, list[str]] = {}
        self._roles: dict[str, str | None] = {}

    def deps(self, tid: str) -> list[str]:
        if tid not in self._deps:
            try:
                spec = specs.load(self.p, tid)
                self._deps[tid], self._roles[tid] = list(spec.depends_on), spec.role
            except HteamError:
                self._deps[tid], self._roles[tid] = [], None
        return self._deps[tid]

    def role(self, tid: str) -> str | None:
        self.deps(tid)
        return self._roles[tid]

    def ancestors(self, tid: str) -> set[str]:
        """직간접 선행(순환이 있어도 끝난다)."""
        seen: set[str] = set()
        todo = list(self.deps(tid))
        while todo:
            d = todo.pop()
            if d != tid and d not in seen:
                seen.add(d)
                todo += self.deps(d)
        return seen


def opened(st: dict) -> str | None:
    """현재 라운드를 연 시각(그 라운드의 가장 이른 start·fix 기록). 없으면 None(stale 을 판단하지 않는다)."""
    times = [h["at"] for h in st.get("history") or [] if isinstance(h, dict) and h.get("event") in ("start", "fix")
             and h.get("round") == st.get("round") and isinstance(h.get("at"), str)]
    return min(times) if times else None


def _seen(basis: dict, tid: str) -> int:
    """basis 에 적힌 선행 라운드. 없으면(예약 때 상태가 없었거나 사양을 읽지 못한 선행) 0: 아무것도 보지 않은 것으로 본다."""
    n = basis.get(tid)
    return n if isinstance(n, int) and not isinstance(n, bool) else 0


def stale(p, cfg, states: list[dict], graph: Graph | None = None) -> dict[str, list[str]]:
    """{승인 태스크: [이 태스크의 현재 라운드를 띄운 뒤에 새 라운드를 연 선행]}. 끝난 태스크는 보지 않는다.

    기준은 그 라운드의 워커를 새로 띄울 때 본 선행의 끝난 라운드(`basis`, tasks._launch_basis·_finished_round: 선행이
    done·awaiting_user·approved·dropped 면 그 라운드, 아니면 앞 라운드)다: 선행의 지금 라운드가 그보다 크면 stale 이다.
    basis 에 없는 선행은 0 으로 본다(_seen). 미리 만들어 둔(queued) 라운드는 실제로 띄울 때 기록하므로, 기다리는 동안
    선행이 리뷰에서 한 번 더 고쳐져도 그 최신 선행을 보고 만든 결과는 stale 이 아니다. 같은 라운드 복구가 옛 Dispatch 를
    이어 붙이면 basis 는 처음 것 그대로라 그 사이 고쳐진 선행을 놓치지 않는다. basis 가 없는 라운드(옛 기록)는 라운드를
    연 시각으로 본다(시각이 같으면 함께 고친 것이라 stale 이 아니다)."""
    graph = graph or Graph(p)
    by_id = {s["id"]: s for s in states}
    found: dict[str, list[str]] = {}
    for st in states:
        if st["status"] in state.CLOSED or not cfg.is_approval(st.get("role")):
            continue
        basis = (state.current_round(st) or {}).get("basis")
        if isinstance(basis, dict):
            newer = sorted(a for a in graph.ancestors(st["id"]) if a in by_id and by_id[a]["round"] > _seen(basis, a))
        else:
            mine = opened(st)
            if mine is None:
                continue
            newer = sorted(a for a in graph.ancestors(st["id"])
                           if a in by_id and (o := opened(by_id[a])) is not None and o > mine)
        if newer:
            found[st["id"]] = newer
    return found


def _startable(p, cfg, st: dict) -> bool:
    """pending 태스크가 승인 직무이고 지금 바로 시작할 수 있나: 사양 검사·의존 충족·잠금 비어 있음(설계 11.4). 직무는
    저장된 직무가 아니라 지금 사양의 직무다(첫 시작이 저장된 직무를 사양에 맞춘다). 잠금은 시작 경로와 같은 검사
    (tasks._check_locks: owns 잠금과 기획 하나 규칙)다. 사양이 틀렸거나 owns 를 판단할 수 없으면 시작할 수 없다
    (start-ready 도 띄우지 않는다)."""
    try:
        spec = specs.check(p, cfg, st["id"])
        if not cfg.is_approval(spec.role) or not tasks.deps_met(p, cfg, spec):
            return False
        tasks._check_locks(p, cfg, spec, tasks.checked_owns(cfg, spec))
        return True
    except HteamError:
        return False


def view(p, cfg, states: list[dict] | None = None, data: dict | None = None) -> dict:
    """지금의 승인 상황. waiting: awaiting_user 승인 태스크, blockers: 진행 중이거나 지금 시작할 수 있는 승인 태스크,
    stale: waiting 가운데 선행이 그 뒤에 고쳐진 것({task, round, because}), fresh: waiting 가운데 stale 이 아니고 아직 묻지
    않은 것, asked: 물은 (태스크, 라운드) → out-id. 상태는 읽기만 한다."""
    states = state.all_states(p) if states is None else states
    data = load(p) if data is None else data
    done = asked(data)
    behind = stale(p, cfg, states)
    waiting, blockers = [], []
    for st in states:
        if st["status"] == "pending":  # 직무는 지금 사양으로 본다(_startable)
            if _startable(p, cfg, st):
                blockers.append({"task": st["id"], "status": "pending", "why": "지금 시작할 수 있다"})
            continue
        if not cfg.is_approval(st.get("role")):
            continue
        if st["status"] == "awaiting_user":
            waiting.append(st)
        elif st["status"] in PROGRESS:
            blockers.append({"task": st["id"], "status": st["status"], "why": "진행 중"})
    late = [{"task": st["id"], "round": st["round"], "because": behind[st["id"]]} for st in waiting if st["id"] in behind]
    fresh = [st for st in waiting if st["id"] not in behind and (st["id"], st["round"]) not in done]
    return {"waiting": waiting, "blockers": blockers, "stale": late, "fresh": fresh, "asked": done}


def _urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?") for u in URL_RE.findall(text)]


def _system_urls(p) -> set[str]:
    """`docs/design/direction.md` 의 `design_system_url:` 줄 URL(디자인 시스템, 3단계 디렉터가 남긴다)."""
    try:
        text = (p.root / "docs" / "design" / "direction.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return set()
    return {u for line in text.splitlines() if "design_system_url" in line for u in _urls(line)}


def link(p, tid: str) -> str:
    """태스크 보고서의 마지막 claude.ai URL. `design_system_url` 줄과 디자인 시스템 URL 은 뺀다. 없으면 보고서 경로."""
    try:
        text = (p.root / report_rel(tid)).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return report_rel(tid)
    skip = _system_urls(p)
    found = [u for line in text.splitlines() if "design_system_url" not in line for u in _urls(line) if u not in skip]
    return found[-1] if found else report_rel(tid)


def _line(p, cfg, st: dict) -> str:
    try:
        title = specs.load(p, st["id"]).title
    except HteamError:
        title = "(사양을 읽지 못했다)"
    if len(title) > TITLE_MAX:
        title = title[:TITLE_MAX - 1] + "…"
    return f"- {st['id']} r{st['round']} [{cfg.role_title(st['role'])}] {title}: {link(p, st['id'])}"


def _tail(rest: list[str]) -> str:
    return f"\n- 그 밖 {len(rest)}개(링크는 각 보고서): " + ", ".join(rest) if rest else ""


def render(p, cfg, sts: list[dict]) -> dict:
    """approval 질문(설계 7.4 형식). context 는 태스크마다 한 줄과 링크다. 4000자를 넘으면 뒤 태스크는 ID 만 적는다
    (남은 ID 줄이 들어갈 자리를 늘 남긴다)."""
    head = f"리뷰(Codex)가 승인한 디자인 {len(sts)}개다. 링크를 열어 보고 한 번에 답한다.\n"
    ids = [st["id"] for st in sts]
    lines: list[str] = []
    for i, st in enumerate(sts):
        line = _line(p, cfg, st)
        if len(head + "\n".join(lines + [line]) + _tail(ids[i + 1:])) > CONTEXT_MAX:
            break
        lines.append(line)
    context = head + "\n".join(lines) + _tail(ids[len(lines):])
    if len(context) > CONTEXT_MAX:  # ID 만으로도 넘친다(태스크가 수백 개)
        context = context[:CONTEXT_MAX - 1] + "…"
    obj = {"header": HEADER,
           "question": f"디자인 {len(sts)}개를 승인할까요?\n예: 모두 승인이면 이 디자인에 의존하는 개발이 이어서 시작된다",
           "context": context,
           "options": [{"label": APPROVE, "description": "추천 사유: 리뷰(Codex)가 모두 승인했다"},
                       {"label": REVISE, "description": "고칠 태스크와 내용을 이어서 알려 준다"}],
           "multiSelect": False}
    return outbox.validate_render(obj, HEADER)


def _write(p, data: dict, b: dict) -> None:
    """기록한 묶음 b 를 outbox 에 쓰고 기록에 id 를 적는다. 같은 batch 항목이 이미 있으면(앞 호출이 쓰고 죽음) 그것을
    쓴다. 찾기와 쓰기는 outbox 잠금 안에서 한다(append 의 reuse). 묶음 id 와 질문(render)이 모두 같아야 같은 항목이다."""
    def mine(entries: list[dict]) -> dict | None:
        return next((e for e in entries if e.get("type") == "approval" and e.get("batch") == b["batch"]
                     and e.get("render") == b["render"]), None)

    entry = outbox.append(p, {"type": "approval", "render": b["render"], "from": "coordinator", "batch": b["batch"]},
                          reuse=mine)
    die_at("design_review_appended")
    b["id"] = entry["id"]
    write_json(p.design_review, data)


def _next_batch(p, data: dict) -> str:
    """다음 묶음 id: 기록과 batch 가 붙은 outbox approval 항목의 묶음 번호 가운데 가장 큰 것 다음. 기록을 치운 뒤에도
    옛 묶음 id 를 다시 쓰지 않는다(batch 가 붙은 approval 항목은 design-review 만 프로젝트 잠금 안에서 쓴다. `notify
    --type approval` 의 항목에는 batch 가 없다)."""
    names = [b["batch"] for b in data["batches"]]
    names += [e["batch"] for e in outbox.read_outbox(p) if e.get("type") == "approval" and isinstance(e.get("batch"), str)]
    return f"dr-{max([int(n[3:]) for n in names if BATCH_RE.fullmatch(n)], default=0) + 1:04d}"


def _result(b: dict, resumed: bool) -> dict:
    return {"id": b["id"], "batch": b["batch"], "tasks": b["tasks"], "resumed": resumed,
            "hint": f"메인의 답(`[main] reply {b['id']}`)을 기다린다. hteam wait 가 그 답에 design_review 필드를 붙인다"}


def design_review(p) -> dict:
    cfg = config.load(p)
    if not cfg.user_approval_roles:
        raise HteamError("no_approval_roles", "user_approval_roles 가 비었다(승인 직무가 없다)", USAGE,
                         "`.herdr-team/config.toml` 의 user_approval_roles 에 직무를 넣는다")
    with state.project_lock(p):
        data = load(p)
        stuck = next((b for b in data["batches"] if b.get("id") is None), None)
        if stuck is not None:  # 앞 호출이 기록 뒤 죽었다. 새 묶음보다 먼저 마저 쓴다
            _write(p, data, stuck)
            return _result(stuck, resumed=True)
        bad = state.unreadable_ids(p)
        if bad:  # 그 태스크가 진행 중인 승인 태스크인지 알 수 없다. 묶음을 잘못 나누지 않게 묻지 않는다
            raise tasks._unreadable(p, bad)
        v = view(p, cfg, data=data)
        if not v["waiting"]:
            raise HteamError("nothing_to_approve", "awaiting_user 인 승인 직무 태스크가 없다", CONFLICT)
        if v["stale"]:  # 읽기만 한다. 일괄 승인 결정은 의존 태스크를 함께 고치므로 이것은 결정 밖에서 선행을 고친 경우다
            names = ", ".join(f"{s['task']} r{s['round']}(선행 {', '.join(s['because'])})" for s in v["stale"])
            raise HteamError("approval_stale", f"선행이 그 뒤에 고쳐져 옛 선행을 보고 만든 승인 태스크는 묻지 않는다: {names}",
                             CONFLICT, "메인에 알린다. 사용자가 정하면 그 태스크를 `hteam fix T --note=…` 로 다시 만든 뒤 "
                             "design-review 를 다시 부른다", data={"stale": v["stale"]})
        if not v["fresh"]:
            ids = sorted({v["asked"][(s["id"], s["round"])] for s in v["waiting"]})
            raise HteamError("already_asked", f"awaiting_user 승인 태스크는 이미 물었다: {', '.join(ids)}", CONFLICT,
                             "메인의 답(`[main] reply out-NNNN`)을 기다린다", data={"asked": ids})
        if v["blockers"]:
            names = ", ".join(f"{b['task']}({b['status']})" for b in v["blockers"])
            raise HteamError("approval_not_ready", f"진행 중이거나 지금 시작할 수 있는 승인 직무 태스크가 있다: {names}",
                             CONFLICT, "시작할 수 있으면 start-ready 를 먼저 한다. 그 태스크들이 accept 로 awaiting_user 가 "
                             "된 뒤 다시 부른다", data={"blockers": v["blockers"]})
        b = {"batch": _next_batch(p, data), "at": now(), "id": None,
             "tasks": [{"task": s["id"], "round": s["round"]} for s in v["fresh"]], "render": render(p, cfg, v["fresh"])}
        data["batches"].append(b)
        write_json(p.design_review, data)
        die_at("design_review_recorded")
        _write(p, data, b)
    return _result(b, resumed=False)


def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return design_review(p)


def register(sub) -> None:
    sub.add_parser("design-review").set_defaults(func=_cmd)
