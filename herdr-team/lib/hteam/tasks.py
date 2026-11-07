"""작업 라운드(설계 5.4·6.4): start, start-ready, fix, accept, drop."""
from __future__ import annotations

import contextlib
import os
from typing import Iterator

from . import compose, config, dispatch, gitio, plan, procs, roles, specs, state
from .errors import CONFLICT, FAIL, USAGE, HteamError
from .globs import any_overlap, within
from .horch import Horch
from .paths import SHIM, find_project
from .util import die_at, write_atomic


def work_slot(st: dict) -> dict:
    return st["rounds"][-1]["work"]


def lock_conflicts(p, tid: str, owns: list[str]) -> list[dict]:
    """잠금을 가진 다른 태스크 가운데 owns 가 겹치는 것."""
    found = []
    for other in state.all_states(p):
        if other["id"] == tid or other["status"] not in state.LOCKING:
            continue
        pairs = any_overlap(owns, other.get("owns") or [])
        if pairs:
            found.append({"task": other["id"], "status": other["status"], "pairs": [list(x) for x in pairs]})
    return found


def _unreadable(p, bad: list[str]) -> HteamError:
    files = [p.state_path(t).name for t in bad]
    return HteamError("bad_state_file", f"상태 파일을 읽을 수 없어 잠금을 확인할 수 없다: {', '.join(files)}", FAIL,
                      "파일을 직접 고치거나 치운 뒤 다시 시도한다", data={"files": files})


def _check_locks(p, cfg, spec, owns: list[str]) -> None:
    bad = state.unreadable_ids(p)
    if bad:  # 그 태스크의 잠금(owns·직무)을 알 수 없다. 겹칠 수 있으니 새 작업을 띄우지 않는다
        raise _unreadable(p, bad)
    if spec.role == "planner":
        busy = [s["id"] for s in state.all_states(p)
                if s["id"] != spec.id and s.get("role") == "planner" and s["status"] in state.LOCKING]
        if busy:
            raise HteamError("planner_busy", f"진행 중인 기획 태스크가 있다: {', '.join(busy)}", CONFLICT,
                             "기획 인터뷰는 프로젝트마다 한 번에 하나다(설계 10장)")
    conflicts = lock_conflicts(p, spec.id, owns)
    if conflicts:
        names = ", ".join(c["task"] for c in conflicts)
        raise HteamError("owns_locked", f"{spec.id} 의 owns 가 잠금을 가진 태스크({names})와 겹친다", CONFLICT,
                         data={"conflicts": conflicts})


def checked_owns(cfg, spec) -> list[str]:
    """태스크 owns. front matter owns 는 직무 owns 를 좁히기만 한다(설계 4.1). 넘거나 판단할 수 없으면 exit 2."""
    owns = specs.owns_of(cfg, spec)
    role_owns = cfg.owns(spec.role)
    wide = [o for o in owns if not any(within(o, r) for r in role_owns)]
    if wide:
        raise HteamError("owns_too_wide", f"{spec.id} 의 owns 가 직무 {spec.role} 의 owns({', '.join(role_owns)}) 를 넘거나 "
                         f"판단할 수 없다: {', '.join(wide)}", USAGE,
                         "front matter owns 는 직무 owns 안의 하위 경로(예: src/auth/**)로 좁힌다")
    return owns


def _spec_file(p, tid: str, n: int):
    return p.work_file(tid, n)


FINISHED = frozenset({"done", "awaiting_user", "dropped"})


def _finished_round(st: dict) -> int:
    """이 선행에서 지금 볼 수 있는 마지막 끝난 라운드. done·awaiting_user·dropped 면 지금 라운드, 아니면(일하는 중·리뷰
    중·승인됨·고치는 중·띄우지 않은 라운드) 그 앞 라운드다(0 은 끝난 결과가 없다). approved 는 리뷰가 worker-retain 실패를
    견디므로 작업 워커가 아직 살아 같은 라운드를 더 고칠 수 있어 끝난 것으로 보지 않는다(승인 그대로면 stale 이 한 번 더
    뜰 뿐이다). dropped 는 새 라운드를 열지 않으므로 앞 라운드로 적으면 의존 태스크가 영영 stale 이 된다."""
    return st["round"] if st["status"] in FINISHED else max(st["round"] - 1, 0)


def _basis(p, tid: str) -> dict[str, int]:
    """선행(직간접)마다 끝난 라운드(_finished_round). 승인 태스크의 stale 판단 기준이다(설계 11.4, approval.stale).
    지금 라운드가 끝나지 않은 선행이면 이 태스크는 그 앞 결과를 보고 만든다. 그 라운드를 적으면 선행이 끝난 뒤에도
    stale 로 잡지 못한다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    by_id = {s["id"]: s for s in state.all_states(p)}
    return {a: _finished_round(by_id[a]) for a in sorted(approval.Graph(p).ancestors(tid), key=state.id_number)
            if a in by_id}


def _launch_basis(st: dict) -> None:
    """dispatch.launch 가 워커를 새로 띄울 때(fresh)만 launched 와 같은 저장에서 부른다(on_fresh). 시작 예약에서 본
    선행 라운드가 이 라운드의 basis 다. 기존 Dispatch 를 이어 붙이거나(adopt) 같은 horch Task 를 다시 띄우면(retry)
    부르지 않아 처음 띄울 때 것이 남는다(adopt 한 Dispatch 는 그 선행을 보고 만들었다. retry 는 그 사이 선행이
    바뀌었으면 stale 로 보는 쪽이 안전하다: 놓치지 않고, 잘못 잡으면 fix 로 다시 만든다)."""
    rd = st["rounds"][-1]
    if isinstance(rd["work"].get("pred_rounds"), dict):
        rd["basis"] = rd["work"]["pred_rounds"]


def _begin(p, st: dict, rd: dict, text: str, event: str, **info) -> None:
    """실행 키·실행자·라운드를 launch_failed 와 함께 먼저 쓴다(설계 5.4 3). 사양 파일도 쓴다. 선행의 끝난 라운드를
    실행 기록 pred_rounds 에 둔다(start·fix 모두 프로젝트 잠금 안에서 부른다. 손으로 한 start·같은 라운드 복구·결정 밖
    fix 는 의존을 보지 않으므로 선행 라운드가 아직 끝나지 않았을 수 있다. 그래서 끝난 라운드만 적는다, _basis). 라운드의
    basis 는 워커를 새로 띄울 때만 그것으로 정한다(_launch_basis). 같은 라운드 복구는 여기를 다시 지나도 basis 를
    바꾸지 않는다."""
    rd["work"]["pred_rounds"] = _basis(p, st["id"])
    st["launcher"] = {"key": rd["work"]["title"], **procs.me()}
    state.move(st, "launch_failed", event, key=rd["work"]["title"], round=rd["round"], **info)
    write_atomic(_spec_file(p, st["id"], rd["round"]), text)


def _new_round(st: dict, n: int, head: str, choice, note=None, supplement=None, coord_note=None) -> dict:
    """note 는 사용자 요청 라운드(from_user)면 사용자 요청, 아니면 코디네이터 메모다. coord_note 는 사용자 요청 라운드를
    잇는 일반 fix 의 코디네이터 메모다(사용자 요청과 섞지 않는다)."""
    rd = {"round": n, "round_base": head, "agent": choice.worker, "model": choice.model, "effort": choice.effort,
          "note": note, "supplement": supplement, "work": dispatch.new_slot(roles.work_title(st["id"], n)),
          "reviews": [], "verdict": None}
    if coord_note:
        rd["coord_note"] = coord_note
    return rd


LIVE = ("launching", "active")


class Capacity:
    """start-ready 한 호출의 동시 수 상한(설계 5.4). h 는 점유 검사의 worker-list 에 쓴다."""

    def __init__(self, h, limit: int):
        self.h = h
        self.limit = limit


def _may_run(st: dict, cap: Capacity, rows) -> bool:
    """launch_failed 태스크의 현재 라운드 워커가 떠 있을 수 있나: 실행자·장벽 자식이 살아 있다, 또는 기록된 horch
    Task 나 실행 키의 Dispatch 가 launching·active 다. launched 는 시작 바이트 전에 저장되므로, 바이트 뒤 무슨 오류가
    났든(horch non-ok·시간 초과·기록 실패) 산 Dispatch 는 새 worker-list 에서 제목으로 보인다."""
    rd = state.current_round(st)
    if not rd:
        return False
    slot = rd["work"]
    if dispatch.busy(st, slot):
        return True
    if not (slot.get("launched") or slot.get("horch_task")):
        return False  # 장벽 자식을 기록한 적이 없다: horch 를 실행하지 않았다
    return any(r.get("state") in LIVE and (r.get("title") == slot["title"] or
                                           (slot.get("horch_task") and r.get("task") == slot["horch_task"]))
               for r in rows())


def occupied(p, tid: str, cap: Capacity) -> list[str]:
    """동시 수 상한이 세는 다른 태스크: working, 그리고 워커가 떠 있을 수 있는 launch_failed(_may_run).
    프로젝트 잠금 안에서 부른다. worker-list 는 이 검사마다 새로 묻는다(필요할 때 한 번). 호출 도중 끝나거나 새로 뜬
    워커를 옛 목록으로 세지 않게."""
    seen: list[list[dict]] = []

    def rows() -> list[dict]:
        if not seen:
            seen.append(cap.h.workers(states=LIVE))  # 상태로 거른 뒤에만 horch 가 hc 로 행을 살핀다
        return seen[0]

    return [s["id"] for s in state.all_states(p) if s["id"] != tid and
            (s["status"] == "working" or (s["status"] == "launch_failed" and _may_run(s, cap, rows)))]


def _prepare_start(p, cfg, spec, choice, cli: dict, cap: Capacity | None = None) -> None:
    tid = spec.id
    with state.project_lock(p):
        state.create(p, tid, spec.role)  # 사양만 있고 상태가 없으면 pending 으로 만든다
        with state.edit(p, tid) as st:
            if st["status"] in state.CLOSED:
                raise state.closed_error(st)
            if st["status"] not in ("pending", "launch_failed"):
                raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(start 는 pending·launch_failed 에서)", CONFLICT,
                                 data={"status": st["status"]})
            recovering = st["status"] == "launch_failed" and bool(st["rounds"])
            if recovering:
                # 같은 라운드 복구: horch --task --retry 는 DB 에 저장된 사양으로 띄운다. 그래서 저장된 사양 파일·owns·
                # 에이전트·모델을 그대로 쓴다(설계 5.4). 바꾸려면 fix 로 새 라운드를 띄운다
                rd = st["rounds"][-1]
                slot = rd["work"]
                if slot.get("canceled"):
                    raise HteamError("launch_canceled", f"{slot['title']} 실행 키가 취소됐다", CONFLICT,
                                     "앞선 fix·drop 이 끝나지 않았다. 같은 명령을 다시 한다")
                if dispatch.busy(st, slot):
                    raise HteamError("launching", f"{slot['title']} 를 띄우는 실행자가 아직 살아 있다", CONFLICT,
                                     "끝날 때까지 기다린 뒤 다시 한다")
                if cli.get("worker") or cli.get("model") or cli.get("effort"):
                    raise HteamError("recovery_overrides", f"{slot['title']} 복구는 저장된 에이전트·모델을 쓴다", USAGE,
                                     f"바꾸려면 hteam fix {tid} --model … 로 새 라운드를 띄운다")
                owns = list(st.get("owns") or []) or checked_owns(cfg, spec)
            else:
                owns = checked_owns(cfg, spec)
            _check_locks(p, cfg, spec, owns)
            _start_gate(p, cfg, spec, check_deps=cap is not None)
            if cap is not None:
                # 상한 검사와 예약(아래 _begin 의 launch_failed·실행자)을 한 프로젝트 잠금 안에서 한다(start-ready 만)
                busy = occupied(p, tid, cap)
                if len(busy) >= cap.limit:
                    raise HteamError("parallel_limit", f"동시 수 상한 {cap.limit} 에 닿았다: {', '.join(busy)}",
                                     CONFLICT, data={"occupied": busy})
            if not recovering:
                st["role"] = spec.role  # 워커는 이 사양의 직무로 뜬다. planner 하나 검사가 저장된 직무를 본다
                head = gitio.head(p.root)
                rd = _new_round(st, st["round"] + 1, head, choice)
                text = compose.work_spec(p, cfg, spec, rd, owns)
                if st["base"] is None:
                    st["base"] = head  # 태스크를 처음 띄울 때 한 번만
                st["rounds"].append(rd)
                st["round"] = rd["round"]
            else:
                stored = _spec_file(p, tid, rd["round"])  # base·round_base·사양은 그대로
                text = stored.read_text(encoding="utf-8") if stored.is_file() else \
                    compose.work_spec(p, cfg, spec, rd, owns)
            st["owns"] = owns
            _begin(p, st, rd, text, "start")


def run_work(p, cfg, h, tid: str) -> dict:
    """현재 라운드 작업 워커를 띄운다(설계 5.4 5–6). 실패하면 launch_failed 그대로 exit 1(horch 의 12 는 12)."""
    rd = state.require(p, tid)["rounds"][-1]
    res = dispatch.launch(p, h, tid, work_slot, agent=rd["agent"], model=rd["model"], effort=rd["effort"],
                          args=cfg.args(rd["agent"]), spec_file=_spec_file(p, tid, rd["round"]),
                          expect={"launch_failed"}, on_fresh=_launch_basis)
    try:
        # fix·drop 의 취소·전이가 그 사이 끼었으면 working 으로 두지 않는다(정리는 그쪽이 horch 상태로 한다)
        with dispatch.owned(p, tid, work_slot, {"launch_failed"}) as st:
            if res["mode"] == "adopt":  # 실제로 도는 워커에 맞춘다(리뷰어는 이 agent 의 반대쪽)
                st["rounds"][-1].update(agent=res["agent"], model=res["model"], effort=res["effort"])
            state.move(st, "working", "launched", dispatch=res["dispatch"])
            rd = st["rounds"][-1]
    except HteamError as exc:
        dispatch.left_running(exc, res, h)
        raise
    out = {"task": tid, "round": rd["round"], "status": "working", "agent": rd["agent"], "model": rd["model"],
           "effort": rd["effort"], **res}
    nxt, hint = _adopted_next(cfg, tid, rd["round"], res)
    if nxt is not None:
        out["next"] = nxt
    if hint:
        out["hint"] = hint
    return out


def _adopted_next(cfg, tid: str, rnd: int, res: dict) -> tuple[list[str] | None, str | None]:
    """이어 붙인 작업 Dispatch 가 이미 끝났으면(done 뒤 settled·retained·released) 다음 명령. 그 worker_done 은 태스크가
    launch_failed 일 때 와서(그때 next 는 start) 다시 오지 않으므로 여기서 준다(아니면 wait 가 시간 초과까지 기다린다)."""
    if res.get("mode") != "adopt" or res.get("state") not in ("settled", "retained", "released"):
        return None, None
    if res.get("outcome") == "succeeded":
        return [SHIM, "review", tid], "이어 붙인 작업 워커가 이미 성공으로 끝났다"
    if rnd >= cfg.max_rounds:
        return None, (f"이어 붙인 작업 워커가 실패로 끝났고 max_rounds({cfg.max_rounds}) 에 닿았다. 메인에 묻고, 사용자가 "
                      f"계속하라고 하면 {SHIM} fix {tid} --force-round --note …")
    return ([SHIM, "fix", tid, "--note", f"작업 실패: {(res.get('summary') or '')[:200]}"],
            "이어 붙인 작업 워커가 이미 실패로 끝났다")


def start(p, tid: str, cli: dict, cfg=None, h=None, cap: Capacity | None = None) -> dict:
    """cap 은 start-ready 만 준다(max_parallel 은 start-ready 만 본다, 설계 5.4)."""
    cfg = cfg or config.load(p)
    spec = specs.check(p, cfg, tid)
    choice = config.resolve(cfg, spec.role, spec.front, cli)
    h = h or Horch(p.horch_home)
    _prepare_start(p, cfg, spec, choice, cli, cap)
    return run_work(p, cfg, h, tid)


def _dep_done(cfg, spec, ds: dict) -> bool:
    return ds["status"] == "done" or (ds["status"] == "awaiting_user" and cfg.is_approval(spec.role)
                                      and cfg.is_approval(ds.get("role")))


def deps_met(p, cfg, spec) -> bool:
    """선행이 done 이거나, 선행·후행이 모두 승인 직무이고 선행이 awaiting_user(설계 5.3)."""
    for dep in spec.depends_on:
        ds = state.load(p, dep)
        if ds is None or not _dep_done(cfg, spec, ds):
            return False
    return True


def unmet_deps(p, cfg, spec) -> list[tuple[str, str]]:
    """끝나지 않은 선행과 그 상태(대기 사유에 적는다). 상태가 없으면 "상태 없음", 읽지 못하면 "읽지 못함"."""
    found = []
    for dep in spec.depends_on:
        try:
            ds = state.load(p, dep)
        except HteamError:
            found.append((dep, "읽지 못함"))
            continue
        if ds is None:
            found.append((dep, "상태 없음"))
        elif not _dep_done(cfg, spec, ds):
            found.append((dep, ds["status"]))
    return found


def _load_quiet(p, tid: str) -> dict | None:
    """상태. 없거나 읽지 못하면 None(dropped 선행을 찾을 때만 쓴다. 읽지 못한 선행은 unmet_deps 가 알린다)."""
    try:
        return state.load(p, tid)
    except HteamError:
        return None


def _unmet_text(unmet: list[tuple[str, str]], spec) -> str:
    return ", ".join(f"{d}({s})" for d, s in unmet) or ", ".join(spec.depends_on)


def dropped_blockers(graph, tid: str, load) -> dict[str, list[str]]:
    """tid 를 영영 시작하지 못하게 하는 dropped 선행(직간접) → 그것을 depends_on 에 둔 태스크(tid 이거나 사이의 선행).
    직접 선행이 dropped 이거나, start-ready 가 띄울 선행(pending, 띄운 적 없는 queued 라운드)을 거쳐 닿는 선행이 dropped
    인 것이다. 이미 띄운 선행은 제 선행을 기다리지 않으므로 그 너머는 보지 않는다(그래서 Graph.ancestors 를 그대로 쓰지
    않는다). graph 는 approval.Graph, load 는 태스크 → 상태(없거나 읽지 못하면 None). 순환이 있어도 끝난다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    found: dict[str, set[str]] = {}
    seen, todo = {tid}, [tid]
    while todo:
        cur = todo.pop()
        for d in graph.deps(cur):
            ds = load(d)
            if ds is None:
                continue
            if ds["status"] == "dropped":
                found.setdefault(d, set()).add(cur)
            elif d not in seen and (ds["status"] == "pending" or approval.unlaunched(ds)):
                seen.add(d)
                todo.append(d)
    return {d: sorted(found[d], key=state.id_number) for d in sorted(found, key=state.id_number)}


def dropped_hint(tid: str, gone: dict[str, list[str]]) -> str:
    """선행이 dropped 라 영영 시작하지 못하는 태스크(start-ready 가 띄우지 않는다)의 할 일. gone 은 dropped_blockers 다.
    버린 태스크는 다시 시작하지 않으므로(설계 6.4) 사람이 정한다. 간접 선행이면 그것을 depends_on 에 둔 사양을 적는다."""
    names = ", ".join(d if tid in held else f"{d}({', '.join(held)} 의 선행)" for d, held in gone.items())
    where = "·".join(f"`.herdr-team/tasks/{t}.md`"
                     for t in sorted({t for held in gone.values() for t in held}, key=state.id_number))
    return (f"선행 {names} 가 dropped 다. 이 태스크는 시작할 수 없다(start-ready 가 띄우지 않는다). 메인에 알려 "
            f"사용자가 정한다: 버리려면 {SHIM} drop {tid}, 계속하려면 사양 {where} 의 depends_on 에서 "
            "그 선행을 빼거나 바꾼다")


WAIT_CODES = {"owns_locked": "lock", "planner_busy": "lock", "launching": "launching", "parallel_limit": "limit",
              "deps_unmet": "deps", "decision_pending": "decision"}


def start_ready(p) -> dict:
    """tasks.toml 순서로 사양 → 의존 → 잠금 → 동시 수 상한을 보고 통과한 것을 start 한다(설계 5.4).

    잠금·상한은 start 가 프로젝트 잠금 안에서 본다(복구는 저장된 owns, 상한 검사와 예약은 원자적).
    한 태스크의 오류(예상 밖 오류 포함)는 그 태스크만 실패로 두고 계속한다."""
    cfg = config.load(p)
    h = Horch(p.horch_home)
    cap = Capacity(h, cfg.max_parallel)
    started, waiting, failed = [], [], []
    graph = None  # dropped 선행을 볼 때 만든다
    order = plan.order(p)
    for tid in state.unreadable_ids(p):  # plan.order 는 읽히는 상태만 본다. 손상된 상태 파일도 실패로 알린다
        if tid not in order:
            failed.append({"task": tid, "error": _unreadable(p, [tid]).to_json()["error"]})
    for tid in order:
        try:
            st = state.load(p, tid)
            if not st or st["status"] not in ("pending", "launch_failed"):
                continue
            try:
                spec = specs.check(p, cfg, tid)
            except HteamError as exc:
                waiting.append({"task": tid, "reason": "spec", "detail": exc.message})
                continue
            if not deps_met(p, cfg, spec):
                unmet = unmet_deps(p, cfg, spec)  # 끝나지 않은 선행만 상태와 함께 적는다
                item = {"task": tid, "reason": "deps", "detail": _unmet_text(unmet, spec)}
                if graph is None:
                    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
                    graph = approval.Graph(p)
                gone = dropped_blockers(graph, tid, lambda d: _load_quiet(p, d))  # 직간접 선행
                if gone:
                    item.update(dropped=list(gone), hint=dropped_hint(tid, gone))
                waiting.append(item)
                continue
            die_at("start_ready_checked")  # 테스트: 의존을 본 뒤 시작 전에 결정이 끼는 순서를 재현한다
            res = start(p, tid, {}, cfg=cfg, h=h, cap=cap)
            started.append({"task": tid, "round": res["round"], "dispatch": res["dispatch"],
                            "warnings": res["warnings"], **{k: res[k] for k in ("next", "hint") if res.get(k)}})
        except Exception as exc:
            if not isinstance(exc, HteamError):  # 버그·예상 밖 오류도 이 태스크만 실패로 둔다(cli 의 internal 모양)
                failed.append({"task": tid, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}",
                                                      "hint": ""}})
            elif exc.code in WAIT_CODES:
                waiting.append({"task": tid, "reason": WAIT_CODES[exc.code], "detail": exc.message})
            else:
                failed.append({"task": tid, "error": exc.to_json()["error"]})
    if failed:
        raise HteamError("start_failed", f"{len(failed)}개 태스크를 띄우지 못했다", FAIL,
                         "실패한 태스크는 hteam status 의 next 를 따른다",
                         data={"started": started, "waiting": waiting, "failed": failed})
    return {"started": started, "waiting": waiting}


FIX_FROM = ("changes", "launch_failed", "working", "awaiting_user")
# 판정 전 라운드: 이 라운드로 Dispatch 를 띄울 수 있다(start 복구, review, review-finish 자동 재시도, review --retry)
IN_FLIGHT = frozenset({"launch_failed", "working", "reviewing"})


def _slots(st: dict) -> list[dict]:
    """모든 라운드의 실행 기록(작업, 리뷰 시도)."""
    return [s for rd in st.get("rounds", []) for s in (rd["work"], *rd["reviews"])]


def _round_targets(h, st: dict, *, kill: bool, rows: list[dict] | None = None) -> dict[str, list[str]]:
    """정리할 Dispatch: {실행 키: [Dispatch, …]}. 모든 라운드의 모든 실행 기록(작업·리뷰 시도)을 본다.

    고르는 기준은 horch 의 실제 상태다(cleaned 표시가 아니다): 기록된 horch Task 의 모든 시도, Task 가 기록되지 않았으면
    그 실행 키(제목)의 모든 Task 의 시도(dispatch.slot_rows) 가운데 active·settled·retained·abandoned. 그래서 앞선
    fix·drop 이 멈춘 뒤 다시 불러도, 같은 Task 를 다시 띄워 남은 이전 시도가 있어도 빠짐없이 정리한다.
    launch_failed 는 건드리지 않는다. 실행자가 살아 있거나 launching 이면 exit 3 launching, kill 없는 active 는
    exit 3 worker_active. rows 를 주면 worker-list 를 다시 묻지 않는다."""
    slots = _slots(st)
    if rows is None:
        rows = h.workers() if slots else []
    targets: dict[str, list[str]] = {}
    for slot in slots:
        if dispatch.busy(st, slot):
            raise HteamError("launching", f"{slot['title']} 를 띄우는 실행자가 아직 살아 있다", CONFLICT, "나중에 다시 한다")
        for row in dispatch.slot_rows(rows, slot):
            did = row["id"]
            if row["state"] == "launching":
                raise HteamError("launching", f"Dispatch {did} 가 아직 launching 이다", CONFLICT, "나중에 다시 한다",
                                 data={"dispatch": did})
            if row["state"] == "active" and not kill:
                raise HteamError("worker_active", f"Dispatch {did}({slot['title']}) 가 아직 active 다", CONFLICT,
                                 "워커를 끝내고 버리려면 --force", data={"dispatch": did})
            if row["state"] in dispatch.CLEANABLE:
                targets.setdefault(slot["title"], []).append(did)
    return targets


def _release(p, h, tid: str, targets: dict[str, list[str]], *, kill: bool) -> list[dict]:
    """대상을 정리한다. 한 실행 기록의 Dispatch 를 모두 정리하면 그 기록에 cleaned 를 쓴다(기록일 뿐 대상 선택에는
    쓰지 않는다). 실패하면 예외(다시 부르면 horch 상태로 남은 것을 다시 고른다)."""
    released = []
    for title, dids in targets.items():
        released += [dispatch.cleanup(h, did, kill=kill) for did in dids]
        die_at("after_release")
        with state.edit(p, tid) as cur:
            for slot in _slots(cur):
                if slot["title"] == title:
                    slot["cleaned"] = True
    return released


def _record_cleaned(p, tid: str, st: dict, rows: list[dict], targets: dict[str, list[str]]) -> None:
    """앞 호출이 release 한 뒤 cleaned 를 쓰기 전에 멈췄으면 그 실행 기록은 다시 고를 대상이 없다. 그런 기록에 cleaned 를
    쓴다(기록만 바꾼다). horch 에 그 기록의 Dispatch 가 있고 모두 released·launch_failed 이며 released 가 하나라도
    있어야 한다. 그래서 살아 있는 Dispatch 가 있는 기록이나 launch_failed 뿐인 기록(horch 에 맡김)에는 쓰지 않는다."""
    done = set()
    for slot in _slots(st):
        mine = dispatch.slot_rows(rows, slot)
        if slot["title"] in targets or slot.get("cleaned") or not mine:
            continue
        if all(r["state"] in ("released", "launch_failed") for r in mine) and \
                any(r["state"] == "released" for r in mine):
            done.add(slot["title"])
    if done:
        with state.edit(p, tid) as cur:
            for slot in _slots(cur):
                if slot["title"] in done:
                    slot["cleaned"] = True


def _launch_view(st: dict) -> tuple:
    """사전 검사가 본 것: 상태·라운드·실행자, 실행 기록마다 horch Task·Dispatch·장벽 자식·결과·취소."""
    return (st["status"], st["round"], st.get("launcher"),
            [(s["title"], s.get("horch_task"), s.get("dispatch"), s.get("launched"), s.get("result"), s.get("canceled"))
             for s in _slots(st)])


def _cancel_open(st: dict) -> None:
    """현재 라운드의 끝나지 않은 실행 키와 리뷰 시도를 canceled 로(이후 start·review 가 복구하지 않는다).

    판정 전 라운드(launch_failed·working·reviewing)면 작업 실행 키도 취소한다. reviewing 은 끝나지 않은 시도가 없어도
    (review_failed·review_tampered 뒤) 라운드에 취소를 남겨, 정리 중 멈춘 drop 뒤 review --retry 가 새 리뷰어를 띄우지
    않게 한다(review 는 취소가 있는 라운드에 exit 3 round_canceled)."""
    rd = state.current_round(st)
    if not rd:
        return
    if st["status"] in IN_FLIGHT:
        rd["work"]["canceled"] = True
    for att in rd["reviews"]:
        if att.get("result") is None:
            att["canceled"] = True


def _changed(tid: str, seen: dict, cur: dict) -> HteamError:
    if cur["status"] in state.CLOSED:
        return state.closed_error(cur)
    what = f"{seen['status']} r{seen['round']} → {cur['status']} r{cur['round']}"
    if (seen["status"], seen["round"]) == (cur["status"], cur["round"]):
        what = f"{cur['status']} r{cur['round']} 의 실행 기록"
    return HteamError("state_changed", f"{tid} 가 이 명령이 본 뒤 바뀌었다({what})", CONFLICT,
                      "다른 명령이 이 태스크를 바꿨다. hteam status 로 확인한 뒤 다시 한다", data={"status": cur["status"]})


def _launcher_alive(st: dict) -> bool:
    """이 프로세스가 아닌 실행자(start·fix·review 가 Dispatch 를 띄우는 중)가 아직 살아 있나."""
    launcher = st.get("launcher") or {}
    return launcher.get("pid") != os.getpid() and procs.record_alive(launcher)


def _close_round(p, h, tid: str, *, kill: bool, check=None, seen: dict | None = None) -> list[dict]:
    """fix·drop 이 공유하는 순서 규칙(설계 6.4):
    1) 바꾸기 전에 거부할 것을 확인한다(대상 미리 고르기: launching, kill 없는 active. check).
    2) 끝나지 않은 실행 키·리뷰 시도의 취소를 먼저 저장한다(이후 start·review 가 그 기록으로 Dispatch 를 띄우지 않는다).
       저장하는 태스크 잠금 안에서 1) 이 본 상태·라운드·실행 기록(_launch_view)이 그대로인지 본다. 그 사이 start 등이
       워커를 띄웠으면 1) 의 판단이 맞지 않으므로 아무것도 바꾸지 않고 exit 3 state_changed.
    3) 취소 뒤 대상을 다시 골라 정리한다. 그 사이 상태·라운드가 바뀌었으면(다른 명령) 정리하지 않고 exit 3.
    호출자는 이것이 끝난 뒤에만 _closing 으로 마지막 전이(dropped 또는 새 라운드)를 쓴다. 어디서 멈춰도 같은 명령을 다시
    부르면 이어 한다.

    check(st) 는 취소를 저장하는 태스크 잠금 안에서 먼저 부른다(거부하면 아무것도 바꾸지 않는다). seen 에 취소 때 본
    상태·라운드를 채운다. review·review-finish 와 겹치지 않게 finish 잠금 안에서 한다. 잠금 순서(프로젝트 → finish →
    태스크)를 지키려고 프로젝트 잠금은 쥐지 않는다."""
    seen = {} if seen is None else seen
    with state.finish_lock(p, tid):
        before = state.require(p, tid)
        _round_targets(h, before, kill=kill)
        die_at("before_cancel")
        with state.edit(p, tid) as cur:
            if cur["status"] in state.CLOSED:
                raise state.closed_error(cur)
            if check is not None:
                check(cur)
            if _launch_view(cur) != _launch_view(before):
                raise _changed(tid, before, cur)
            _cancel_open(cur)
            seen.update(status=cur["status"], round=cur["round"])
        die_at("after_cancel")
        cur = state.require(p, tid)
        if (cur["status"], cur["round"]) != (seen["status"], seen["round"]):
            raise _changed(tid, seen, cur)  # 취소 전에 다른 명령이 라운드를 쓰고 띄운 워커는 이 명령의 대상이 아니다
        rows = h.workers() if _slots(cur) else []
        targets = _round_targets(h, cur, kill=kill, rows=rows)
        released = _release(p, h, tid, targets, kill=kill)
        _record_cleaned(p, tid, cur, rows, targets)
        return released


@contextlib.contextmanager
def _closing(p, tid: str, seen: dict) -> Iterator[dict]:
    """마지막 전이(새 라운드·dropped, 설계 6.4 4)를 쓸 상태를 내준다. 프로젝트 잠금 → 태스크 잠금 아래에서 취소 때 본
    상태·라운드 그대로이고 살아 있는 실행자가 없는지 다시 본다(아니면 exit 3). 그래서 그 사이 start·fix 가 라운드를 쓰고
    워커를 띄우는 중이면, 정리 대상으로 고른 적 없는 그 워커 위에 dropped·새 라운드를 쓰지 않는다."""
    with state.project_lock(p):
        with state.edit(p, tid) as st:
            if (st["status"], st["round"]) != (seen["status"], seen["round"]):
                raise _changed(tid, seen, st)
            if _launcher_alive(st):
                raise HteamError("launching", f"{tid} 의 Dispatch 를 띄우는 실행자({st['launcher'].get('key')})가 아직 "
                                 "살아 있다", CONFLICT, "끝난 뒤 같은 명령을 다시 한다")
            yield st


def fix(p, tid: str, *, note: str | None, supplement: str | None, force_round: bool, cli: dict,
        expect_round: int | None = None, queue: bool = False, from_user: bool = False,
        extra_from: tuple[str, ...] = ()) -> dict:
    """새 라운드(설계 6.4). 입력(사양·owns·잠금)을 먼저 검사하고, 이전 라운드들의 작업·리뷰 Dispatch 를 모두 정리한
    뒤에만 새 라운드를 쓰고 띄운다(이전 워커와 새 워커가 같은 폴더에서 함께 일하지 않게). 일하는 중인 워커는
    abandon --kill 뒤 release.

    일괄 승인 결정(설계 11.4)이 부를 때: queue 면 새 라운드를 쓰고 띄우지 않는다(launch_failed, queued. start-ready 가
    의존이 풀린 뒤 띄운다). from_user 면 사용자 요청 라운드다(결정만 준다. awaiting_user 에서의 다른 fix, 예를 들어
    --supplement 는 사용자 요청이 아니다). 다만 일반 fix 가 아직 사용자에게 다시 보이지 않은 사용자 요청 라운드(워커 실패
    등)를 닫으면 그 요청을 --note 와 합쳐 잇고 사용자 요청 라운드로 둔다(요청을 잃지 않는다). 보강 라운드(--supplement)가
    다시 승인되지 못한 채 닫히면 --supplement 없는 fix 도 그 보강 ID 를 잇는다(awaiting_user 에서 연 fix 는 잇지 않는다). extra_from 은 FIX_FROM 밖에서 더 받을 상태다(결정이 고치는 의존 태스크는
    리뷰 중·승인됨이어도 다시 만든다)."""
    cfg = config.load(p)
    spec = specs.check(p, cfg, tid)
    choice = config.resolve(cfg, spec.role, spec.front, cli)
    if supplement is not None:
        _check_supplement(p, supplement)
    h = Horch(p.horch_home)

    allowed_from = FIX_FROM + tuple(extra_from)

    def allowed(st: dict) -> None:
        if st["status"] in state.CLOSED:
            raise state.closed_error(st)
        _expect_round(tid, st, expect_round)  # 미리 보고, 취소를 저장하는 잠금 안에서 다시 본다(_close_round 의 check)
        if st["status"] not in allowed_from:
            raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(fix 는 {', '.join(allowed_from)} 에서)", CONFLICT,
                             data={"status": st["status"]})
        if st["status"] != "awaiting_user" and st["round"] >= cfg.max_rounds and not force_round:
            raise HteamError("max_rounds", f"{tid} 는 이미 {st['round']} 라운드다(상한 {cfg.max_rounds})", CONFLICT,
                             "사용자가 계속하라고 하면 --force-round(한 라운드만 넘긴다)",
                             data={"round": st["round"], "max_rounds": cfg.max_rounds})

    allowed(state.require(p, tid))
    owns = checked_owns(cfg, spec)  # 입력 검사(owns·잠금)는 이전 워커를 정리하기 전에 한다
    _check_locks(p, cfg, spec, owns)
    if not queue:  # 끝나지 않은 결정이 고치는 태스크면 워커를 죽이거나 라운드를 닫기 전에 거부한다(_closing 에서 다시 본다)
        _start_gate(p, cfg, spec, check_deps=False)
    seen: dict = {}
    _close_round(p, h, tid, kill=True, check=allowed, seen=seen)
    with _closing(p, tid, seen) as st:
        _check_locks(p, cfg, spec, owns)
        if not queue:  # 결정 밖의 fix 는 끝나지 않은 결정이 고치는 태스크를 띄우지 않는다(결정 자신의 fix 는 queue 다)
            _start_gate(p, cfg, spec, check_deps=False)
        old = st["status"]
        prior = state.current_round(st) or {}
        coord_note = None
        if not from_user and prior.get("from_user") and prior.get("note") and old != "awaiting_user":
            # 결정이 연 사용자 요청 라운드가 사용자에게 다시 보이지 못한 채 닫힌다(워커 실패, 리뷰 수정 요청 뒤 changes 등).
            # 그 요청을 그대로 잇고 코디네이터 메모는 따로 적는다(워커·리뷰어가 메모를 사용자 요청으로 읽지 않게)
            note, coord_note, from_user = prior["note"], note, True
        if supplement is None and prior.get("supplement") and old != "awaiting_user":
            # 보강 라운드가 다시 승인되지 못한 채 닫힌다(작업 실패, 리뷰 수정 요청 등). 끝나지 않은 보강을 잇는다
            # (수정 블록이 보강 결과를 계속 보이고, 다시 승인된 뒤 그 라운드의 제안을 보강 대상으로 보지 않는다)
            supplement = prior["supplement"]
        st["role"] = spec.role  # 첫 실행과 같이 워커가 뜨는 사양의 직무로 맞춘다. planner 하나 검사가 저장된 직무를 본다
        rd = _new_round(st, st["round"] + 1, gitio.head(p.root), choice, note=note, supplement=supplement,
                        coord_note=coord_note)
        if from_user:
            rd["from_user"] = True  # 사용자 일괄 승인의 수정 요청(설계 11.4). 수정 블록이 사용자 요청으로 적는다
            # 마지막으로 실제 리뷰된 라운드의 판정(그 뒤 라운드는 띄우지 않았거나 판정 전에 닫혔다). 수정 요청이면 그 지적도
            # 다루게 한다
            rd["prior_verdict"], rd["prior_review_round"] = _last_review(st)
        if queue:
            rd["queued"] = True
        text = compose.work_spec(p, cfg, spec, rd, owns)
        st["rounds"].append(rd)
        st["round"] = rd["round"]
        st["owns"] = owns
        st["note"] = note
        _begin(p, st, rd, text, "fix", previous=old, force_round=force_round)
    if queue:  # 띄우지 않는다. start-ready 의 의존 검사가 선행이 다시 승인된 뒤에 띄운다(설계 11.4)
        return {"task": tid, "round": rd["round"], "status": "launch_failed", "queued": True,
                "next": [SHIM, "start-ready"],
                "hint": "수정 라운드를 만들었다. start-ready 가 선행이 끝난(승인 직무는 awaiting_user) 뒤에 띄운다"}
    return run_work(p, cfg, h, tid)


def _check_supplement(p, sup: str) -> None:
    """--supplement 는 끝난(done) 디렉터 보강 태스크만 받는다(설계 11.4: 보강이 끝나면 제안한 화면을 고친다)."""
    state.check_id(sup)
    if not p.spec_path(sup).is_file():
        raise HteamError("unknown_task", f"--supplement {sup} 사양이 없다", USAGE)
    role = specs.load(p, sup).role
    if role != "director":
        raise HteamError("bad_supplement", f"--supplement {sup} 는 {role} 태스크다(디렉터 보강 태스크만 준다)", USAGE)
    st = state.load(p, sup)
    if st is None or st["status"] != "done":
        raise HteamError("supplement_not_done", f"보강 태스크 {sup} 가 아직 끝나지 않았다({(st or {}).get('status', '상태 없음')})",
                         CONFLICT, "보강 태스크를 accept 해 done 이 된 뒤 fix --supplement 한다")


def _last_review(st: dict) -> tuple[str | None, int | None]:
    """판정이 있는 마지막 라운드의 (판정, 라운드). 없으면 (None, None)."""
    for r in reversed(st["rounds"]):
        if r.get("verdict"):
            return r["verdict"], r["round"]
    return None, None


def _expect_round(tid: str, st: dict, want: int | None) -> None:
    """--round N: 명령을 정한 때의 라운드와 지금 라운드가 같아야 한다. 다시 하는 결정(일괄 승인)이 이미 한 항목을
    다음 라운드에 다시 적용하지 않게 한다(설계 6.4)."""
    if want is not None and st["round"] != want:
        raise HteamError("round_changed", f"{tid} 는 지금 r{st['round']} 다(--round {want}). 그 라운드는 이미 처리됐다",
                         CONFLICT, "다시 하지 않는다. hteam status 로 지금 상태를 본다", data={"round": st["round"]})


def _start_gate(p, cfg, spec, check_deps: bool) -> None:
    """시작 예약(프로젝트 잠금 안)에서 다시 본다(설계 11.4). 끝나지 않은 일괄 승인 결정이 고치는 태스크와 그것에
    의존하는 태스크는 띄우지 않는다(결정을 기록한 뒤 선행을 고치기 전 구간 포함). check_deps(start-ready)면 의존도 다시
    본다: 잠금 밖에서 의존을 본 뒤 결정이 선행을 고쳤을 수 있다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    held = approval.held_by_decision(p, spec.id)
    if held:
        raise HteamError("decision_pending", f"{spec.id} 는 끝나지 않은 일괄 승인 결정 {held} 이 고치는 태스크이거나 그 "
                         "의존 태스크다", CONFLICT, f"`{SHIM} design-review --decide {held}` 로 결정을 마저 한 뒤 start-ready",
                         data={"pending": held})
    if check_deps and not deps_met(p, cfg, spec):
        raise HteamError("deps_unmet", f"{spec.id} 의 선행이 아직 끝나지 않았다: "
                         f"{_unmet_text(unmet_deps(p, cfg, spec), spec)}", CONFLICT)


def _refuse_stale(p, cfg, tid: str) -> None:
    """awaiting_user 승인 태스크의 선행이 이 라운드를 연 뒤에 고쳐졌으면 승인하지 않는다(설계 11.4, 읽기만 하는 검사).
    프로젝트 잠금 안에서 부른다(선행의 새 라운드는 fix 가 같은 잠금 안에서 쓴다)."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    behind = approval.stale(p, cfg, state.all_states(p)).get(tid)
    if behind:
        names = ", ".join(behind)
        raise HteamError("approval_stale", f"{tid} 의 선행 {names} 가 이 라운드를 연 뒤에 고쳐졌다. 옛 선행을 보고 만든 "
                         "결과를 승인하지 않는다", CONFLICT,
                         "메인에 알린다. 사용자가 정하면 일괄 승인 결정의 fix 에 넣거나 hteam fix T --note=… 로 다시 만든다",
                         data={"because": behind})


def _live_error(tid: str, slot: dict, row: dict, horch_cmd: str) -> HteamError:
    """살아 있는 워커 때문에 accept 하지 않는다. 힌트의 horch 명령은 그대로 실행할 수 있다(horch_cmd = Horch.cmd())."""
    did = row["id"]
    if row["state"] == "launching":
        return HteamError("launching", f"{tid} 의 Dispatch {did}({slot['title']})가 아직 launching 이다", CONFLICT,
                          "끝난 뒤 다시 한다", data={"dispatch": did})
    return HteamError("worker_active", f"{tid} 의 Dispatch {did}({slot['title']})가 아직 active 다. 살아 있는 워커가 "
                      "파일을 고칠 수 있어 owns 잠금을 풀지 않는다", CONFLICT,
                      f"워커를 끝낸 뒤 다시 한다: {horch_cmd} worker-abandon --dispatch {did} --kill 뒤 {horch_cmd} "
                      f"worker-release --dispatch {did}. 태스크를 버리려면 {SHIM} drop {tid} --force", data={"dispatch": did})


def _held_for_accept(p, tid: str, decision: str | None) -> None:
    """끝나지 않은 일괄 승인 결정이 고치는 태스크(또는 그 의존 태스크)는 손으로 accept 하지 않는다. 사용자 수정 요청이
    결정을 다시 할 때 round_changed 로 조용히 사라진다(설계 11.4). decision 은 그 결정 자신의 accept 항목(_apply)이다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    held = approval.held_by_decision(p, tid)
    if held and held != decision:
        raise HteamError("decision_pending", f"{tid} 는 끝나지 않은 일괄 승인 결정 {held} 이 고치는 태스크이거나 그 "
                         "의존 태스크다", CONFLICT, f"`{SHIM} design-review --decide {held}` 로 결정을 마저 한다",
                         data={"pending": held})


def accept(p, tid: str, expect_round: int | None = None, decision: str | None = None) -> dict:
    """approved → done(승인 직무면 awaiting_user), awaiting_user → done(설계 6.4). 작업 Dispatch 를 release 한다
    (같은 horch Task 의 이전 시도도).

    태스크의 작업·리뷰 Dispatch 가 하나라도 launching·active 면(review 는 retain 실패를 견디므로 approved 에도 작업
    워커가 살아 있을 수 있다) 아무것도 바꾸지 않고 exit 3 이다. 닫으면 owns 잠금이 풀리고 fix·drop 도 task_closed 라
    그 워커를 정리할 길이 없다. worker-list 를 묻지 못하면 확인할 수 없으므로 역시 바꾸지 않는다. 끝난 Dispatch 의
    release 실패는 Dispatch 마다 경고로 남기고 cleaned 는 쓰지 않는다. 전이는 한다."""
    cfg = config.load(p)
    st = state.require(p, tid)
    _expect_round(tid, st, expect_round)  # 상태보다 먼저: 다른 라운드로 옮겨 갔으면 그 항목은 이미 처리된 것이다
    if st["status"] in state.CLOSED:
        raise state.closed_error(st)
    if st["status"] not in ("approved", "awaiting_user"):
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(accept 는 approved·awaiting_user 에서)", CONFLICT,
                         data={"status": st["status"]})
    _held_for_accept(p, tid, decision)
    to = "awaiting_user" if st["status"] == "approved" and cfg.is_approval(st["role"]) else "done"
    h = Horch(p.horch_home)
    rows = h.workers()
    for slot in _slots(st):
        for row in dispatch.slot_rows(rows, slot):
            if row["state"] in ("launching", "active"):
                raise _live_error(tid, slot, row, h.cmd())
    warnings: list[str] = []
    slot = work_slot(st)
    cleaned = bool(slot.get("cleaned"))
    if not cleaned:
        cleaned = True
        for row in dispatch.slot_rows(rows, slot):
            if row["state"] not in dispatch.CLEANABLE:
                continue
            try:  # 한 Dispatch 의 실패가 나머지(이전 시도)의 release 를 막지 않게 하나씩
                dispatch.cleanup(h, row["id"], kill=False)
            except HteamError as exc:
                cleaned = False
                warnings.append(f"작업 Dispatch {row['id']}({slot['title']})를 정리하지 못했다: {exc.message}")
    die_at("accept_before_final")
    with state.project_lock(p):  # 선행의 새 라운드(fix 가 같은 잠금 안에서 쓴다)와 겹치지 않게 이 안에서 다시 본다
        _held_for_accept(p, tid, decision)  # 결정 기록도 같은 잠금 안에서 쓴다
        if st["status"] == "awaiting_user" and cfg.is_approval(st["role"]):
            _refuse_stale(p, cfg, tid)
        with state.edit(p, tid, expect={st["status"]}) as cur:
            if cur["round"] != st["round"]:  # 멈춘 사이 다음 라운드가 같은 상태에 닿았다. 본 적 없는 라운드를 닫지 않는다
                raise _changed(tid, st, cur)
            work_slot(cur)["cleaned"] = cleaned
            state.move(cur, to, "accept")
    out = {"task": tid, "status": to, "warnings": warnings}
    if to == "awaiting_user":  # 승인 직무: 다른 승인 태스크와 묶어 사용자에게 묻는다(설계 11.4)
        out["next"] = [SHIM, "design-review"]
        out["hint"] = (f"`{SHIM} start-ready` 뒤 `{SHIM} design-review`. exit 3 approval_not_ready 면 다른 승인 직무 "
                       "태스크를 accept 한 뒤 다시 부른다")
    return out


def drop(p, tid: str, force: bool) -> dict:
    """dropped 로(설계 6.4). 끝나지 않은 실행 키와 리뷰 시도는 canceled. active 는 --force 로만 abandon --kill 뒤
    release. 모든 대상의 정리를 확인한 뒤, 취소 때 본 상태·라운드 그대로일 때만 dropped 를 쓴다(pending 이면 그 사이
    start 가 라운드를 쓰지 않았을 때만)."""
    h = Horch(p.horch_home)
    st = state.require(p, tid)
    if st["status"] in state.CLOSED:
        raise state.closed_error(st)
    seen: dict = {}
    released = _close_round(p, h, tid, kill=force, seen=seen)
    with _closing(p, tid, seen) as cur:
        state.move(cur, "dropped", "drop", force=force)
    return {"task": tid, "status": "dropped", "released": released}


def _cli(args) -> dict:
    return {k: getattr(args, k) for k in ("model", "effort", "worker") if getattr(args, k, None)}


def _cmd_start(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return start(p, args.task, _cli(args))


def _cmd_start_ready(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return start_ready(p)


def _cmd_fix(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return fix(p, args.task, note=args.note, supplement=args.supplement, force_round=args.force_round, cli=_cli(args),
               expect_round=args.expect_round)


def _cmd_accept(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return accept(p, args.task, args.expect_round)


def _cmd_drop(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return drop(p, args.task, args.force)


def _overrides(s) -> None:
    s.add_argument("--model")
    s.add_argument("--effort")
    s.add_argument("--worker", choices=config.AGENTS)


def register(sub) -> None:
    s = sub.add_parser("start")
    s.add_argument("task")
    _overrides(s)
    s.set_defaults(func=_cmd_start)
    sub.add_parser("start-ready").set_defaults(func=_cmd_start_ready)
    s = sub.add_parser("fix")
    s.add_argument("task")
    s.add_argument("--note")
    s.add_argument("--supplement", help="디렉터 보강 태스크 ID(설계 11.4)")
    s.add_argument("--force-round", action="store_true")
    s.add_argument("--round", type=int, dest="expect_round", help="지금 라운드가 이것일 때만(설계 6.4)")
    _overrides(s)
    s.set_defaults(func=_cmd_fix)
    s = sub.add_parser("accept")
    s.add_argument("task")
    s.add_argument("--round", type=int, dest="expect_round", help="지금 라운드가 이것일 때만(설계 6.4)")
    s.set_defaults(func=_cmd_accept)
    s = sub.add_parser("drop")
    s.add_argument("task")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=_cmd_drop)
