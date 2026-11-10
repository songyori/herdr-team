"""사용자 일괄 승인(설계 11.4): `hteam design-review`(관제), `hteam design-decide`(메인은 요청 큐, 설계 7.4).

승인 직무(user_approval_roles) 태스크는 리뷰 승인 뒤 accept 로 awaiting_user 가 된다. 진행 중(working·reviewing·
approved·changes·launch_failed)이거나 지금 바로 시작할 수 있는(사양 통과·의존 충족·잠금 비어 있음) 승인 직무 태스크가
없을 때, 그 순간 awaiting_user 인 승인 태스크 가운데 아직 묻지 않은 (태스크, 라운드) 전부를 outbox 의 approval 항목
하나로 묻는다. 결정이 만들고 띄운 적 없는 queued 수정 라운드(launch_failed)는 pending 처럼 지금 시작할 수 있을 때만
막는다(선행이 dropped 면 영영 시작하지 못하므로 다른 승인 태스크를 막지 않는다). 승인 → 비승인 → 승인 사슬의 뒤
태스크는 비승인 태스크가 done 이어야 시작할 수 있으므로 앞 묶음을 막지 않고 다음 묶음이 된다.

stale: 승인 태스크의 선행(직간접)이 이 태스크의 현재 라운드를 연 뒤에 새 라운드를 열었으면 이 태스크는 옛 선행을 보고
만든 것이다. 일괄 승인 결정(decide)은 의존 승인 태스크를 선행과 함께 고치므로 stale 은 결정 밖에서 선행을 고친 경우뿐이다.
읽기만 하는 검사다: stale 인 awaiting_user 태스크는 묻지 않고(approval_stale) accept 가 받지 않는다. 기준은 그 라운드의
워커를 새로 띄울 때 본 선행의 끝난 라운드(basis, tasks._finished_round: 선행이 done·awaiting_user·dropped 면
그 라운드, 아니면 앞 라운드. 같은 라운드 복구가 기존 Dispatch 를 이어 붙이면 그대로 둔다)다. basis 에 없는 선행은
라운드 0 을 본 것으로 본다. basis 가 없는 라운드(옛 기록)는 history 의 그 라운드 start·fix 시각으로 본다.

기록 `state/design-review.json` = {"batches": [{"batch": "dr-0001", "at", "id": "out-NNNN" | null, "render",
"tasks": [{"task", "round"}]}]}. 한 (태스크, 라운드)는 한 번만 묻는다(수정 라운드는 라운드가 달라 다시 묻는다).
쓰는 순서: 기록(id 없음) → outbox 항목(batch 를 붙인다) → 기록의 id. 모두 프로젝트 잠금 안에서 한다. 그 사이 죽으면
다음 호출이 새 묶음보다 먼저 outbox 에서 같은 batch 를 찾아 id 를 채우거나, 없으면 저장한 render 로 마저 쓴다(같은
묶음을 두 번 묻지 않는다). 기록을 읽지 못하거나 모양이 틀리면 덮어쓰지 않고 exit 1 이다.

결정(design-decide): 메인이 사용자 답과 태스크별 결정을 한 답 파일(`state/answers/<out-id>.json` 의 answer·decision)에 남기고
요청 큐로 관제에 넘긴다(record_answer). 관제는 결정 기록 → fix --round·accept --round → applied 를 한다(decide). 큐 제출이
거부되거나 메인이 죽어도 결정은 답 파일에 남고, 관제의 재확인이 결정 기록에 없거나 끝나지 않은 것을 마저 한다
(pending_answers, 설계 8.7).
"""
from __future__ import annotations

import json
import re
import sys

from . import config, dispatch, outbox, queue, roles, specs, state, tasks
from .errors import CONFLICT, FAIL, USAGE, HteamError
from .paths import SHIM, find_project, report_rel
from .util import bad_side_file, die_at, now, read_json_strict, write_json

PROGRESS = frozenset({"working", "reviewing", "approved", "changes", "launch_failed"})
# 아티팩트 링크. 괄호·따옴표·꺾쇠·공백·제어 문자는 URL 밖이다(context 에 그대로 들어가므로 render 검사를 지나야 한다)
URL_RE = re.compile(r"https://claude\.ai/[A-Za-z0-9._~:/?#@!$&*+,;=%-]+")
BATCH_RE = re.compile(r"dr-\d{4,}")
OUT_RE = re.compile(r"out-\d{4,}")
CONTEXT_MAX = 4000
TITLE_MAX = 60
HEADER = "승인"  # 기록의 render 에 header 가 없을 때만 쓰는 기본값(render 가 직무 이름으로 정한다)
AGENT_NAMES = {"claude": "Claude", "codex": "Codex"}
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
    if b.get("decision") is not None:
        return _decision_problem(b)
    return None


def _decision_problem(b: dict) -> str | None:
    """결정 기록의 모양 문제(없으면 None). 틀린 결정으로 accept·fix 를 하지 않는다."""
    d, name = b["decision"], b["batch"]
    if b.get("id") is None:
        return f"{name}: 묻지 않은 묶음에 결정이 있다"
    if not isinstance(d, dict) or not isinstance(d.get("at"), str) or not isinstance(d.get("input"), dict):
        return f"{name}: decision 이 객체가 아니거나 at·input 이 없다"
    if not all(isinstance(d.get(k), list) for k in ("fix", "accept", "skipped")):
        return f"{name}: decision 의 fix·accept·skipped 가 목록이 아니다"
    if not all(_task_ok(e) and isinstance(e.get("note"), str) and e["note"].strip()
               and isinstance(e.get("because"), list) for e in d["fix"]):
        return f"{name}: decision.fix 가 [{{task, round, note, because}}] 가 아니다"
    if not all(_task_ok(e) for e in d["accept"]):
        return f"{name}: decision.accept 가 [{{task, round}}] 가 아니다"
    if not all(isinstance(e, dict) and isinstance(e.get("task"), str) and state.ID_RE.fullmatch(e["task"])
               and isinstance(e.get("why"), str) for e in d["skipped"]):
        return f"{name}: decision.skipped 가 [{{task, why}}] 가 아니다"
    if d.get("done") is not None and not isinstance(d["done"], str):
        return f"{name}: decision.done 이 시각이나 null 이 아니다"
    return None


def _open_decision(data: dict, but: dict | None = None) -> dict | None:
    """끝나지 않은 결정이 있는 묶음(but 은 뺀다)."""
    return next((b for b in data["batches"] if b is not but and b.get("decision") and not b["decision"].get("done")),
                None)


def _decision_pending(b: dict) -> HteamError:
    return HteamError("decision_pending", f"{b['id']} 의 일괄 승인 결정을 아직 다 하지 않았다", CONFLICT,
                      f"관제가 재확인마다 결정 {b['id']} 을 기록대로 마저 한다", data={"pending": b["id"]})


def _unfinished(data: dict, states: list[dict]) -> dict[str, str]:
    """끝나지 않은 결정의 항목 가운데 아직 하지 않은 것(태스크가 기록한 라운드 그대로) → 그 out-id."""
    by_id = {s["id"]: s for s in states}
    found: dict[str, str] = {}
    for b in data["batches"]:
        d = b.get("decision")
        if not d or d.get("done"):
            continue
        for e in [*d["fix"], *d["accept"]]:
            st = by_id.get(e["task"])
            if st is not None and st["status"] not in state.CLOSED and st["round"] == e["round"]:
                found[e["task"]] = b["id"]
    return found


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
        self._specs: dict[str, object] = {}

    def spec(self, tid: str):
        """사양(한 번만 읽는다). 읽지 못하면 None."""
        if tid not in self._specs:
            try:
                self._specs[tid] = specs.load(self.p, tid)
            except HteamError:
                self._specs[tid] = None
        return self._specs[tid]

    def deps(self, tid: str) -> list[str]:
        spec = self.spec(tid)
        return list(spec.depends_on) if spec is not None else []

    def role(self, tid: str) -> str | None:
        spec = self.spec(tid)
        return spec.role if spec is not None else None

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
    done·awaiting_user·dropped 면 그 라운드, 아니면 앞 라운드)다: 선행의 지금 라운드가 그보다 크면 stale 이다.
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


def unlaunched(st: dict) -> bool:
    """일괄 승인 결정이 만들고 아직 띄운 적 없는 queued 수정 라운드다(launch_failed, 시작 장벽 자식·horch Task 기록 없음).
    start T 는 의존을 보지 않으므로 start-ready 가 선행이 다시 승인된 뒤 띄운다."""
    rd = state.current_round(st) or {}
    slot = rd.get("work") or {}
    return (st["status"] == "launch_failed" and bool(rd.get("queued")) and not slot.get("launched")
            and not slot.get("horch_task"))


_SUBSECTION = "### 시스템 추가 제안"
_NONE = re.compile(r"[-*\s]*없음[.。]?\s*")


def proposals(p, st: dict) -> str | None:
    """designer 보고서의 지금 라운드 절(`## rN`)에 있는 시스템 추가 제안(설계 11.2·11.4). `### 시스템 추가 제안` 소절,
    없으면 2단계 형식의 `- 시스템 추가 제안: …` 줄. 비었거나 "없음" 이면 None. 보고서가 없으면 None 이고, 있는데 읽지
    못하면 exit 1 `unreadable_report` 다(읽지 못한 것을 제안 없음으로 보고 묻지 않는다: fail-closed)."""
    path = p.root / report_rel(st["id"])
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise HteamError("unreadable_report", f"{st['id']} 보고서 `{report_rel(st['id'])}` 를 읽지 못했다: {exc}", FAIL,
                         "보고서를 고치거나 메인에 알린다. 제안이 있는지 알 수 없어 묻지 않는다") from None
    lines = text.splitlines()
    head = re.compile(rf"## r{st['round']}(?!\d)", re.I)
    start = next((i for i, line in enumerate(lines) if head.match(line)), None)
    if start is None:
        return None
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    found = None
    for i, line in enumerate(body):
        if line.strip().startswith(_SUBSECTION):
            rest = []
            for more in body[i + 1:]:
                if more.startswith(("## ", "### ")):
                    break
                rest.append(more)
            found = "\n".join(rest).strip()
            break
        hit = re.match(r"\s*[-*]\s*시스템 추가 제안\s*:\s*(.*)", line)
        if hit and found is None:
            found = hit.group(1).strip()
    return None if not found or _NONE.fullmatch(found) else found


def supplement_needed(p, cfg, sts: list[dict]) -> list[dict]:
    """일괄 승인에 넣을 designer 태스크 가운데 디렉터 보강이 먼저인 것(설계 11.4): 지금 라운드가 보강 라운드
    (`fix --supplement`)가 아니고 보고서 그 라운드 절에 시스템 추가 제안이 있다. `[roles.director]` 가 없으면 빈 목록."""
    if "director" not in cfg.roles:
        return []
    found = []
    for st in sts:
        rd = state.current_round(st) or {}
        if st.get("role") != "designer" or rd.get("supplement"):
            continue
        try:
            text = proposals(p, st)
        except HteamError as exc:  # 읽지 못한 보고서는 제안이 있을 수 있다. design-review 가 exit 1 로 멈춘다
            found.append({"task": st["id"], "round": st["round"], "proposal": None, "error": exc.message})
            continue
        if text:
            found.append({"task": st["id"], "round": st["round"], "proposal": text})
    return found


def _startable(p, cfg, st: dict) -> bool:
    """승인 직무 태스크를 지금 바로 시작할 수 있나: 사양 검사·의존 충족·잠금 비어 있음(설계 11.4). pending 의 직무는
    저장된 직무가 아니라 지금 사양의 직무다(첫 시작이 저장된 직무를 사양에 맞춘다). 띄운 적 없는 queued 라운드
    (launch_failed)는 같은 라운드 복구로 띄우므로 시작 경로처럼 저장된 직무·owns 로 본다. 잠금은 시작 경로와 같은 검사
    (tasks._check_locks: owns 잠금과 기획 하나 규칙)다. 사양이 틀렸거나 owns 를 판단할 수 없으면 시작할 수 없다
    (start-ready 도 띄우지 않는다)."""
    try:
        spec = specs.check(p, cfg, st["id"])
        stored = st["status"] == "launch_failed"
        if not cfg.is_approval(st.get("role") if stored else spec.role) or not tasks.deps_met(p, cfg, spec):
            return False
        owns = (list(st.get("owns") or []) if stored else []) or tasks.checked_owns(cfg, spec)
        tasks._check_locks(p, cfg, spec, owns)
        return True
    except HteamError:
        return False


def view(p, cfg, states: list[dict] | None = None, data: dict | None = None) -> dict:
    """지금의 승인 상황. waiting: awaiting_user 승인 태스크, blockers: 진행 중이거나 지금 시작할 수 있는 승인 태스크,
    stale: waiting 가운데 선행이 그 뒤에 고쳐진 것({task, round, because}), fresh: waiting 가운데 stale 이 아니고 아직 묻지
    않은 것, asked: 물은 (태스크, 라운드) → out-id, answered: waiting 의 지금 라운드를 물은 out-id 가운데 답이 온 것,
    unreadable_answers: 그 가운데 답 파일이 있는데 읽지 못한 것, supplement: fresh 가운데 디렉터 보강이 먼저인 것
    (supplement_needed), directors: 끝나지 않은 director 태스크(보강 중일 수 있다).
    띄운 적 없는 queued 라운드는 pending 처럼 지금 시작할 수 있을 때만 blocker 다(띄우는 중이면 진행 중). 상태는 읽기만
    한다."""
    states = state.all_states(p) if states is None else states
    data = load(p) if data is None else data
    done = asked(data)
    behind = stale(p, cfg, states)
    replay = _unfinished(data, states)
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
        elif unlaunched(st) and not dispatch.busy(st, st["rounds"][-1]["work"]):
            if _startable(p, cfg, st):
                blockers.append({"task": st["id"], "status": st["status"], "why": "지금 시작할 수 있다"})
        elif st["status"] in PROGRESS:
            blockers.append({"task": st["id"], "status": st["status"], "why": "진행 중"})
    late = [{"task": st["id"], "round": st["round"], "because": behind[st["id"]]} for st in waiting if st["id"] in behind]
    fresh = [st for st in waiting if st["id"] not in behind and (st["id"], st["round"]) not in done]
    answered, unreadable = set(), set()
    for oid in {oid for st in waiting if (oid := done.get((st["id"], st["round"])))}:
        try:
            if outbox.answer_strict(p, oid) is not None:
                answered.add(oid)
        except HteamError:  # 답 파일이 손상됐다. 답이 없다고 하지 않는다
            unreadable.add(oid)
    directors = [{"task": st["id"], "status": st["status"]} for st in states
                 if st.get("role") == "director" and st["status"] not in state.CLOSED]
    return {"waiting": waiting, "blockers": blockers, "stale": late, "fresh": fresh, "asked": done, "replay": replay,
            "answered": answered, "unreadable_answers": unreadable, "supplement": supplement_needed(p, cfg, fresh),
            "directors": directors}


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


def reviewer(st: dict) -> str:
    """그 태스크를 승인한 리뷰어 에이전트: 판정이 APPROVE 인 마지막 리뷰 시도의 에이전트. 기록이 없으면 지금 라운드
    작업 에이전트의 반대쪽(리뷰는 늘 반대쪽이다)."""
    for rd in reversed(st.get("rounds") or []):
        for att in reversed(rd.get("reviews") or []):
            if att.get("result") == "APPROVE" and att.get("agent"):
                return att["agent"]
    return config.other((state.current_round(st) or {}).get("agent") or "claude")


def _words(cfg, sts: list[dict]) -> tuple[str, str, str]:
    """질문 문구의 (무엇, 누가, header). 무엇은 묶음 직무의 title(여럿이면 "결과"), 누가는 승인한 리뷰어들, header 는
    `<무엇> 승인`(12자를 넘으면 "승인")."""
    titles = list(dict.fromkeys(cfg.role_title(st["role"]) for st in sts))
    what = titles[0] if len(titles) == 1 else "결과"
    who = "·".join(dict.fromkeys(AGENT_NAMES.get(r, r) for r in map(reviewer, sts)))
    header = f"{what} 승인"
    return what, who, header if len(header) <= 12 else HEADER


def render(p, cfg, sts: list[dict]) -> dict:
    """approval 질문(설계 7.4 형식). context 는 태스크마다 한 줄과 링크다. 4000자를 넘으면 뒤 태스크는 ID 만 적는다
    (남은 ID 줄이 들어갈 자리를 늘 남긴다). 문구는 묶음의 직무 이름과 승인한 리뷰어로 쓴다(_words)."""
    what, who, header = _words(cfg, sts)
    head = f"리뷰({who})가 승인한 {what} {len(sts)}개다. 링크를 열어 보고 한 번에 답한다.\n"
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
    obj = {"header": header,
           "question": f"{what} {len(sts)}개를 승인할까요?\n예: 모두 승인이면 이 {what}에 의존하는 작업이 이어서 시작된다",
           "context": context,
           "options": [{"label": APPROVE, "description": f"추천 사유: 리뷰({who})가 모두 승인했다"},
                       {"label": REVISE, "description": "고칠 태스크와 내용을 이어서 알려 준다"}],
           "multiSelect": False}
    return outbox.validate_render(obj, header)


def _write(p, data: dict, b: dict) -> None:
    """기록한 묶음 b 를 outbox 에 쓰고 기록에 id 를 적는다. 같은 batch 항목이 이미 있으면(앞 호출이 쓰고 죽음) 그것을
    쓴다. 찾기와 쓰기는 outbox 잠금 안에서 한다(append 의 reuse). 묶음 id 와 질문(render)이 모두 같아야 같은 항목이다."""
    def mine(entries: list[dict]) -> dict | None:
        return next((e for e in entries if e.get("type") == "approval" and e.get("batch") == b["batch"]
                     and e.get("render") == b["render"]), None)

    entry = outbox.append(p, {"type": "approval", "render": b["render"], "from": "drive", "batch": b["batch"]},
                          reuse=mine)
    die_at("design_review_appended")
    b["id"] = entry["id"]
    write_json(p.design_review, data)


def _next_batch(p, data: dict) -> str:
    """다음 묶음 id: 기록과 batch 가 붙은 outbox approval 항목의 묶음 번호 가운데 가장 큰 것 다음. 기록을 치운 뒤에도
    옛 묶음 id 를 다시 쓰지 않는다(batch 가 붙은 approval 항목은 design-review 만 프로젝트 잠금 안에서 쓴다)."""
    names = [b["batch"] for b in data["batches"]]
    names += [e["batch"] for e in outbox.read_outbox(p) if e.get("type") == "approval" and isinstance(e.get("batch"), str)]
    return f"dr-{max([int(n[3:]) for n in names if BATCH_RE.fullmatch(n)], default=0) + 1:04d}"


def _result(b: dict, resumed: bool) -> dict:
    return {"id": b["id"], "batch": b["batch"], "tasks": b["tasks"], "resumed": resumed,
            "hint": f"메인이 사용자 답과 결정을 `hteam design-decide {b['id']} --json -` 으로 넘기기를 기다린다"}


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
        busy = _open_decision(data)
        if busy is not None:  # 끝나지 않은 결정이 태스크를 바꾸는 중이다. 그 태스크를 새 묶음에 넣지 않는다
            raise _decision_pending(busy)
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
                             "메인의 결정(`hteam design-decide out-NNNN --json -`)을 기다린다", data={"asked": ids})
        if v["blockers"]:
            names = ", ".join(f"{b['task']}({b['status']})" for b in v["blockers"])
            raise HteamError("approval_not_ready", f"진행 중이거나 지금 시작할 수 있는 승인 직무 태스크가 있다: {names}",
                             CONFLICT, "시작할 수 있으면 start-ready 를 먼저 한다. 그 태스크들이 accept 로 awaiting_user 가 "
                             "된 뒤 다시 부른다", data={"blockers": v["blockers"]})
        unreadable = [s for s in v["supplement"] if s.get("error")]
        if unreadable:  # 보고서를 읽지 못해 제안이 있는지 모른다(fail-closed)
            raise HteamError("unreadable_report", "; ".join(s["error"] for s in unreadable), FAIL,
                             "보고서를 고치거나 메인에 알린다. 제안이 있는지 알 수 없어 묻지 않는다",
                             data={"unreadable": unreadable})
        if v["supplement"]:  # 묻기 전에 디렉터 보강(설계 11.4). 보강 라운드가 다시 승인되면 그때 함께 묻는다
            names = ", ".join(f"{s['task']} r{s['round']}" for s in v["supplement"])
            raise HteamError("supplement_needed", f"시스템 추가 제안이 있어 디렉터 보강이 먼저다: {names}", CONFLICT,
                             "coordinator.md 의 \"디자인 시스템 보강\" 대로 보강 태스크(director)를 만들거나(끝나지 않은 "
                             "director 태스크가 있으면 끝나기를 기다린다) 끝난 뒤 제안한 태스크마다 fix --supplement",
                             data={"proposals": v["supplement"], "directors": v["directors"]})
        b = {"batch": _next_batch(p, data), "at": now(), "id": None,
             "tasks": [{"task": s["id"], "round": s["round"]} for s in v["fresh"]], "render": render(p, cfg, v["fresh"])}
        data["batches"].append(b)
        write_json(p.design_review, data)
        die_at("design_review_recorded")
        _write(p, data, b)
    return _result(b, resumed=False)


# 결정이 고치는 의존 태스크는 진행 중(리뷰 중·승인됨 포함)이어도 다시 만든다(옛 선행을 보고 만들었다)
DEPENDENT_FROM = ("reviewing", "approved")


def held_by_decision(p, tid: str) -> str | None:
    """끝나지 않은 결정이 고치는 태스크이거나 그것에 직간접으로 의존하는 태스크면 그 결정의 out-id(시작 예약이 본다)."""
    data = load(p)
    graph = None
    for b in data["batches"]:
        d = b.get("decision")
        if not d or d.get("done"):
            continue
        targets = {e["task"] for e in d["fix"]}
        if tid in targets:
            return b["id"]
        graph = graph or Graph(p)
        if targets & graph.ancestors(tid):
            return b["id"]
    return None


def _decision_input(text: str | None, b: dict) -> dict[str, str]:
    """관제가 실행할 결정: {"fix": {태스크: 사용자 요청}} 또는 메인 입력 그대로 {"answer", "fix"}(answer 는 쓰지 않는다).
    태스크는 그 묶음의 것이어야 한다. 틀리면 exit 2."""
    if text is None:
        raise HteamError("usage", f"{b['id']} 에는 아직 결정이 없다. --json - 으로 {{\"fix\": {{태스크: 사용자 요청}}}} 을 "
                         "준다(모두 승인이면 {\"fix\": {}})", USAGE)
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise HteamError("bad_decision", f"결정 JSON 을 읽지 못했다: {exc}", USAGE) from None
    fix = obj.get("fix") if isinstance(obj, dict) else None
    if not isinstance(obj, dict) or set(obj) not in ({"fix"}, {"answer", "fix"}) or not isinstance(fix, dict):
        raise HteamError("bad_decision", "결정은 {\"fix\": {태스크: 사용자 요청}} 이다", USAGE)
    mine = {t["task"] for t in b["tasks"]}
    errors = [f"{k}: 이 묶음({b['id']})의 태스크가 아니다" for k in fix if k not in mine]
    errors += [f"{k}: 사용자 요청이 비었다" for k, v in fix.items() if not isinstance(v, str) or not v.strip()]
    if errors:
        raise HteamError("bad_decision", "결정 입력이 틀렸다: " + "; ".join(errors), USAGE, data={"errors": errors})
    return {k: v.strip() for k, v in fix.items()}


CARRY = "이전 요청도 그대로 반영한다: "


def _pending_request(st: dict) -> str | None:
    """지금 라운드가 결정이 연 사용자 요청 라운드이고 아직 사용자에게 다시 보이지 않았으면(queued·진행 중·리뷰 중, 즉
    awaiting_user 가 아니면) 그 요청. 그 라운드를 닫고 새로 열 때 이어 적는다."""
    rd = state.current_round(st) or {}
    if rd.get("from_user") and rd.get("note") and st["status"] != "awaiting_user":
        return rd["note"]
    return None


def _merge(own: list[str], earlier: str | None, ups: list[str]) -> str:
    """고칠 태스크의 요청 = 이번 사용자 요청 → 아직 반영하지 않은 앞 요청(그 라운드의 note) → 선행의 사용자 요청.
    앞 요청에 이미 든 요청(" / " 로 나뉜 한 조각)은 다시 적지 않는다."""
    def has(part: str) -> bool:
        pat = f"(?:^| / |{re.escape(CARRY)}){re.escape(part)}(?: / |$)"
        return earlier is not None and re.search(pat, earlier) is not None

    parts = [x for x in own if not has(x)]
    if earlier:
        parts.append(f"{CARRY}{earlier}")
    parts += [x for x in ups if not has(x)]
    return " / ".join(parts)


def _compute(p, cfg, b: dict, wanted: dict[str, str]) -> dict:
    """결정을 한 번 계산한다(프로젝트 잠금 안). 고칠 태스크 = 지목된 묶음 태스크 + 그것에 직간접으로 의존하는 승인 태스크
    전부(다른 묶음 포함). 각자 지금 라운드와 사용자 요청을 적는다. 지목된 태스크의 라운드가 다른 결정 때문에 이미 바뀌었어도
    (의존 태스크로 함께 고쳐졌다) 이 새 요청을 버리지 않고 지금 라운드에서 다시 고친다(그 라운드가 사용자 요청 라운드면 그
    요청도 이어 적는다). 지목된 태스크가 끝났으면 decision_conflict(아무것도 쓰지 않는다). 시작하지 않은 의존 태스크
    (pending)는 선행이 다시 승인된 뒤 시작하므로 고칠 것이 없고, 끝난 의존 태스크는 고칠 수 없어 skipped 다. 승인할 태스크 =
    묶음의 나머지(아직 그 라운드의 awaiting_user). 상태를 읽지 못하면, 승인할 태스크가 stale 이면 아무것도 쓰지 않는다."""
    bad = state.unreadable_ids(p)
    if bad:
        raise tasks._unreadable(p, bad)
    states = state.all_states(p)
    by_id = {s["id"]: s for s in states}
    missing = [t["task"] for t in b["tasks"] if t["task"] not in by_id]
    if missing:
        raise HteamError("bad_state_file", f"묶음 태스크의 상태 파일이 없다: {', '.join(missing)}", FAIL,
                         "메인에 알린다", data={"missing": missing})
    graph = Graph(p)
    live = {t["task"] for t in b["tasks"]
            if by_id[t["task"]]["status"] == "awaiting_user" and by_id[t["task"]]["round"] == t["round"]}
    closed = [t for t in sorted(wanted, key=state.id_number) if by_id[t]["status"] in state.CLOSED]
    if closed:  # 사용자 요청을 반영할 수 없다. 처리한 것으로 넘기지 않는다
        raise HteamError("decision_conflict", f"고치라는 태스크가 이미 끝났다: {', '.join(closed)}", CONFLICT,
                         "메인에 알린다. 사용자가 정한 대로(새 태스크 등) 그 태스크를 뺀 결정을 다시 준다",
                         data={"closed": closed})
    direct = sorted(wanted, key=state.id_number)
    skipped: list[dict] = []
    fix: dict[str, dict] = {}
    for tid in sorted(set(by_id) | set(specs.list_ids(p)), key=state.id_number):
        ups = [d for d in direct if d != tid and d in graph.ancestors(tid)]
        if tid not in direct and not ups:
            continue
        st = by_id.get(tid)
        if tid not in direct:
            if not cfg.is_approval((st or {}).get("role") or graph.role(tid)):
                continue
            if st is None or st["status"] == "pending":
                skipped.append({"task": tid, "why": "pending: 선행이 다시 승인된 뒤에 시작한다(고칠 것이 없다)"})
                continue
            if st["status"] in state.CLOSED:
                skipped.append({"task": tid, "why": f"{st['status']}: 끝난 태스크라 고칠 수 없다(메인에 알린다)"})
                continue
        # 지목된 태스크든 의존 태스크든, 지금 라운드가 아직 반영하지 않은 사용자 요청 라운드면 그 요청을 잇는다
        # (다른 결정이 연 라운드를 이 결정이 닫는다. 답이 온 순서·선행이 여럿인 경우에도 요청을 잃지 않는다)
        fix[tid] = {"task": tid, "round": st["round"],
                    "note": _merge([wanted[tid]] if tid in direct else [], _pending_request(st),
                                   [f"선행 {d} 의 사용자 요청을 반영한다: {wanted[d]}" for d in ups]),
                    "because": ups}
    # 선행부터(결정 안의 선행 수가 적은 것부터). 라운드를 연 시각이 선행 → 의존 순서가 된다
    order = sorted(fix.values(), key=lambda e: (len([x for x in fix if x in graph.ancestors(e["task"])]),
                                                state.id_number(e["task"])))
    accept = [{"task": t["task"], "round": t["round"]} for t in b["tasks"] if t["task"] in live and t["task"] not in fix]
    skipped += [{"task": t["task"], "why": "이미 처리됐다"} for t in b["tasks"]
                if t["task"] not in live and t["task"] not in wanted and t["task"] not in fix]  # 의존으로 고치면 fix 에만
    behind = stale(p, cfg, states, graph)
    late = [a["task"] for a in accept if a["task"] in behind]
    if late:
        raise HteamError("approval_stale", f"승인할 태스크의 선행이 그 뒤에 고쳐졌다: {', '.join(late)}", CONFLICT,
                         "메인에 알린다. 사용자가 정하면 그 태스크도 결정의 fix 에 넣는다", data={"stale": late})
    return {"at": now(), "input": wanted, "fix": order, "accept": accept, "skipped": skipped, "done": None}


def _stopped(exc: HteamError, oid: str) -> HteamError:
    exc.hint = f"{exc.hint} 결정은 기록돼 있다. 관제가 재확인마다 결정 {oid} 을 기록대로 마저 한다".strip()
    return exc


def _apply(p, oid: str, d: dict, nowait: bool = False) -> dict:
    """기록한 결정을 그대로 한다. 기록한 라운드가 이미 지났거나 닫힌 항목은 한 것으로 본다(다시 하지 않는다). 다른 오류는
    거기서 멈춘다(다시 부르면 이어 한다). 다 하면 결정에 done 을 적고 그 답을 applied 로 적는다. nowait(관제 안)면 fix·accept
    가 finish 잠금을 기다리지 않는다(review_busy 로 멈추고 다음에 이어 한다, 설계 8.5)."""
    fixed: list[dict] = []
    accepted: list[str] = []
    passed: list[str] = []
    for e in d["fix"]:
        try:
            res = tasks.fix(p, e["task"], note=e["note"], supplement=None, force_round=True, cli={},
                            expect_round=e["round"], queue=True, from_user=True, extra_from=DEPENDENT_FROM, nowait=nowait)
            fixed.append({"task": e["task"], "round": res["round"]})
        except HteamError as exc:
            if exc.code not in ("round_changed", "task_closed"):
                raise _stopped(exc, oid)
            passed.append(e["task"])
        die_at("decision_after_fix")
    for e in d["accept"]:
        try:
            tasks.accept(p, e["task"], expect_round=e["round"], decision=oid, nowait=nowait)
            accepted.append(e["task"])
        except HteamError as exc:
            if exc.code not in ("round_changed", "task_closed"):
                raise _stopped(exc, oid)
            passed.append(e["task"])
    _notify_stale_questions(p, oid, d)
    die_at("decision_notified")  # 테스트: 알린 뒤 done 전에 죽고 다시 해도 한 번만 알린다
    with state.project_lock(p):
        data = load(p)
        b = next(x for x in data["batches"] if x.get("id") == oid)
        b["decision"]["done"] = now()
        write_json(p.design_review, data)
    die_at("decision_done")  # 여기서 죽으면 다음 결정 실행이 applied 만 적는다
    outbox.mark_applied(p, oid)
    return {"fixed": fixed, "accepted": accepted, "passed": passed}


def _notify_stale_questions(p, oid: str, d: dict) -> None:
    """이 결정이 다시 고치는 태스크가 아직 답이 오지 않은 다른 묶음 질문에도 있으면 메인에 알린다(progress). 그 질문을
    물을 때 사용자가 이미 바뀐 디자인을 승인하지 않게 한다. 묶음 질문마다 한 번만 쓴다(다시 해도 같은 항목을 찾는다).
    문구는 그 질문의 답을 _compute 가 처리하는 대로 지금 상태 전체로 쓴다(앞선 결정이 고친 것도 든다): `모두 승인` 은
    물은 라운드 그대로 awaiting_user 인 태스크만 승인하고, 다시 고친 태스크를 지목한 수정 요청은 그 태스크의 지금 라운드에
    더해진다. 끝난 태스크는 바꿀 수 없다."""
    fixed = {e["task"] for e in d["fix"]}
    by_id = {s["id"]: s for s in state.all_states(p)}
    for b in load(p)["batches"]:
        if b.get("id") in (None, oid) or b.get("decision") or outbox.answer_of(p, b["id"]) is not None:
            continue
        hit = [t["task"] for t in b["tasks"] if t["task"] in fixed]
        if not hit:
            continue
        live, again, closed = [], [], []
        for t in b["tasks"]:
            st = by_id.get(t["task"]) or {}
            if st.get("status") == "awaiting_user" and st.get("round") == t["round"]:
                live.append(t["task"])
            elif st.get("status") in state.CLOSED:
                closed.append(t["task"])
            else:
                again.append(t["task"])
        body = (f"일괄 승인 질문 {b['id']} 의 {', '.join(hit)} 는 {oid} 의 수정 요청으로 다시 고친다. 그 질문을 물을 때(이미 "
                "물었으면 지금) 사용자에게 함께 알린다: "
                + (f"`{APPROVE}` 은 그대로인 {', '.join(live)} 만 승인한다. " if live else
                   f"`{APPROVE}` 은 아무 태스크도 승인하지 않는다. ")
                + (f"다시 고친 {', '.join(again)} 는 다시 승인된 뒤 새로 묻는다. 그 태스크를 지목한 `{REVISE}` 은 그 태스크의 "
                   "지금 라운드에 더해진다." if again else "")
                + (f" {', '.join(closed)} 는 이미 끝나 바꿀 수 없다." if closed else ""))
        fields = {"type": "progress", "from": "drive", "body": body, "stale_question": b["id"], "by": oid}
        outbox.append(p, fields, reuse=lambda entries, q=b["id"]: next(
            (e for e in entries if e.get("stale_question") == q and e.get("by") == oid), None))


def decide(p, oid: str, text: str | None, request: str | None = None, nowait: bool = False) -> dict:
    """일괄 승인 답의 결정(설계 11.4, 관제). 결정이 없으면 계산해 묶음 기록에 먼저 쓰고, 있으면 그대로 쓴다. 그다음 기록대로
    fix(queued)·accept 를 한다. 다른 묶음의 결정이 끝나지 않았으면 exit 3 decision_pending. 결정은 답이 온 질문만 새로
    계산한다. 기록한 결정의 재실행은 답을 보지 않는다.

    text 가 None 이고 기록한 결정이 없으면 답 파일의 decision(메인의 design-decide 가 남겼다, 설계 7.4)을 입력으로 쓴다.
    결정을 새로 계산하면 결정 기록에 request(큐 요청 id)를 남긴다. nowait 는 결정 안의 fix·accept 에 잇는다."""
    cfg = config.load(p)
    warnings: list[str] = []
    with state.project_lock(p):
        data = load(p)
        b = next((x for x in data["batches"] if x.get("id") == oid), None)
        if b is None:
            raise HteamError("unknown_batch", f"{oid} 는 design-review 가 쓴 일괄 승인 질문이 아니다", USAGE)
        other = _open_decision(data, but=b)
        if other is not None:
            raise _decision_pending(other)
        # 적용 기록을 먼저 엄격히 읽는다. 손상이면 결정을 기록하거나 fix·accept 하기 전에 bad_side_file 로 멈춘다
        # (끝의 mark_applied 에서야 멈추면 결정만 하고 applied 를 적지 못한다)
        outbox.applied_ids(p)
        replayed = b.get("decision") is not None
        if not replayed:
            ans = outbox.answer_strict(p, oid)  # 손상된 답 파일은 bad_side_file(답이 없다고 하지 않는다)
            if ans is None:
                raise HteamError("no_answer", f"{oid} 에 아직 사용자 답이 없다. 결정하지 않았다", CONFLICT,
                                 f"답이 온 뒤(메인의 `hteam design-decide {oid} --json -`) 부른다")
            if text is None and isinstance(ans.get("decision"), dict):  # 메인이 답 파일에 남긴 결정
                text = json.dumps(ans["decision"], ensure_ascii=False)
            b["decision"] = _compute(p, cfg, b, _decision_input(text, b))
            if request:
                b["decision"]["request"] = request
            write_json(p.design_review, data)
        elif text is not None:
            warnings.append("결정이 이미 기록돼 있어 새 입력은 쓰지 않았다(기록대로 한다)")
        d = b["decision"]
    die_at("decision_recorded")
    out = {"id": oid, "batch": b["batch"], "decision": d, "replayed": replayed, "skipped": d["skipped"]}
    if d.get("done"):
        outbox.mark_applied(p, oid)  # 다 한 뒤 applied 전에 죽었을 수 있다(두 번 적어도 같다)
        res = {"fixed": [], "accepted": [], "passed": [e["task"] for e in [*d["fix"], *d["accept"]]]}
    else:
        res = _apply(p, oid, d, nowait)
    closed = [s["task"] for s in d["skipped"] if s["why"].startswith(("done", "dropped"))]
    if closed:
        warnings.append(f"끝난 의존 태스크({', '.join(closed)})는 고치지 못했다. 메인에 알린다")
    return {**out, **res, "warnings": warnings, "next": [SHIM, "start-ready"],
            "hint": "고칠 태스크는 수정 라운드를 만들어 두었다(queued). start-ready 가 선행이 다시 승인된 뒤 띄운다"}


def pending_answers(p) -> list[str]:
    """결정(decision)이 적힌 일괄 승인 답 가운데 결정 기록이 없거나 끝나지 않은 out id(정렬). 관제의 재확인이 마저 한다
    (approval.decide(p, oid, None), 설계 8.7 의 7). 기록·답 파일을 읽지 못하면 bad_side_file."""
    found = []
    for b in load(p)["batches"]:
        if not b.get("id") or (b.get("decision") or {}).get("done"):
            continue
        ans = outbox.answer_strict(p, b["id"])
        if isinstance(ans, dict) and isinstance(ans.get("decision"), dict):
            found.append(b["id"])
    return sorted(found, key=lambda oid: int(oid[4:]))


SHAPE = '결정은 {"answer": "<사용자 답 원문>", "fix": {태스크: 사용자 요청}} 이다'
NEED_JSON = '--json - 으로 {"answer": "<사용자 답 원문>", "fix": {"T-xxx": "<사용자 요청 원문>"}} 을 준다'


def record_answer(p, oid: str, text: str) -> dict:
    """메인의 design-decide(설계 7.4): 입력을 검사하고 사용자 답과 결정을 한 답 파일에 원자적으로 쓴다. 검사 순서는 JSON →
    항목 → approval → answer → 묶음 → 묻지 않은 태스크 → 빈 요청. 이미 같은 답·결정이면 그대로, 다르면 already_answered.
    값은 앞뒤 공백을 뗀다. 답 파일 기록을 돌려준다."""
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise HteamError("bad_decision", f"결정 JSON 을 읽지 못했다: {exc}", USAGE) from None
    if not (isinstance(obj, dict) and set(obj) == {"answer", "fix"} and isinstance(obj["answer"], str)
            and isinstance(obj["fix"], dict) and all(isinstance(v, str) for v in obj["fix"].values())):
        raise HteamError("bad_decision", SHAPE, USAGE)
    entry = outbox._entry(p, oid)
    if entry["type"] != "approval":
        raise HteamError("not_approval", f"{oid} 는 일괄 승인 질문(approval)이 아니다", USAGE)
    answer = obj["answer"].strip()
    if not answer:
        raise HteamError("empty_answer", "answer(사용자 답 원문)가 비었다", USAGE)
    b = next((x for x in load(p)["batches"] if x.get("id") == oid), None)
    if b is None:
        raise HteamError("unknown_batch", f"{oid} 는 design-review 가 쓴 일괄 승인 질문이 아니다", USAGE)
    mine = {t["task"] for t in b["tasks"]}
    extra = sorted(k for k in obj["fix"] if k not in mine)
    if extra:
        raise HteamError("not_asked", f"묻지 않은 태스크: {', '.join(extra)}", USAGE)
    empty = sorted(k for k, v in obj["fix"].items() if not v.strip())
    if empty:
        raise HteamError("empty_request", f"사용자 요청이 빈 태스크: {', '.join(empty)}", USAGE)
    decision = {"fix": {k: v.strip() for k, v in obj["fix"].items()}}
    if not outbox._link_answer(p, oid, answer, decision=decision):
        prev = outbox.answer_strict(p, oid) or {}
        if prev.get("answer") != answer or prev.get("decision") != decision:
            raise HteamError("already_answered", f"{oid} 에는 이미 다른 답·결정을 남겼다", CONFLICT)
    return outbox.answer_strict(p, oid)


def _cmd(args) -> dict:
    p = find_project(args.root)
    roles.require_drive(p)
    return design_review(p)


def _cmd_decide(args) -> dict:
    """관제(그 자식)면 바로 결정한다(입력이 없으면 기록이나 답 파일의 결정으로). 메인이면 답 파일을 쓴 뒤 요청 큐로 넘긴다."""
    p = find_project(args.root)
    text = sys.stdin.read() if args.json == "-" else args.json

    def check() -> None:
        if text is None:
            raise HteamError("usage", NEED_JSON, USAGE)
        config.load(p)
        record_answer(p, args.id, text)

    try:
        return queue.route(p, "design-decide", {"id": args.id}, lambda req: decide(p, args.id, text, nowait=True),
                           check=check)
    except HteamError as exc:
        if exc.code in queue.SUBMIT_ERRORS:  # 큐에 넣지 못했다. 결정은 답 파일에 있으니 다시 뜬 관제의 재확인이 한다
            exc.hint = f"{exc.hint} 결정은 답 파일에 남았다. 관제가 살아나면 이어 한다".strip()
        raise


def register(sub) -> None:
    sub.add_parser("design-review").set_defaults(func=_cmd)
    s = sub.add_parser("design-decide")
    s.add_argument("id", metavar="OUT_ID")
    s.add_argument("--json", help="'-' 면 표준 입력. 메인: {\"answer\": 사용자 답, \"fix\": {태스크: 사용자 요청}}")
    s.set_defaults(func=_cmd_decide)
