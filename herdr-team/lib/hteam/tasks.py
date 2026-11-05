"""작업 라운드(설계 5.4·6.4): start, start-ready, fix, accept, drop."""
from __future__ import annotations

from . import compose, config, dispatch, gitio, plan, procs, roles, specs, state
from .errors import CONFLICT, FAIL, USAGE, HteamError
from .globs import any_overlap, within
from .horch import Horch
from .paths import find_project
from .util import write_atomic


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


def _check_locks(p, cfg, spec, owns: list[str]) -> None:
    bad = state.unreadable_ids(p)
    if bad:  # 그 태스크의 잠금(owns·직무)을 알 수 없다. 겹칠 수 있으니 새 작업을 띄우지 않는다
        files = [p.state_path(t).name for t in bad]
        raise HteamError("bad_state_file", f"상태 파일을 읽을 수 없어 잠금을 확인할 수 없다: {', '.join(files)}", FAIL,
                         "파일을 직접 고치거나 치운 뒤 다시 시도한다", data={"files": files})
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
    return p.task_dir(tid) / f"r{n}-work.md"


def _begin(p, st: dict, rd: dict, text: str, event: str, **info) -> None:
    """실행 키·실행자·라운드를 launch_failed 와 함께 먼저 쓴다(설계 5.4 3). 사양 파일도 쓴다."""
    st["launcher"] = {"key": rd["work"]["title"], **procs.me()}
    state.move(st, "launch_failed", event, key=rd["work"]["title"], round=rd["round"], **info)
    write_atomic(_spec_file(p, st["id"], rd["round"]), text)


def _new_round(st: dict, n: int, head: str, choice, note=None, supplement=None) -> dict:
    return {"round": n, "round_base": head, "agent": choice.worker, "model": choice.model, "effort": choice.effort,
            "note": note, "supplement": supplement, "work": dispatch.new_slot(roles.work_title(st["id"], n)),
            "reviews": [], "verdict": None}


def occupied(p, tid: str) -> list[str]:
    """동시 수 상한이 세는 다른 태스크: working, 그리고 지금 띄우는 중인 launch_failed(다른 실행자나 장벽 자식이
    살아 있다. start 든 start-ready 든). 프로젝트 잠금 안에서 부른다."""
    found = []
    for s in state.all_states(p):
        if s["id"] == tid:
            continue
        rd = state.current_round(s)
        if s["status"] == "working" or (s["status"] == "launch_failed" and rd and dispatch.busy(s, rd["work"])):
            found.append(s["id"])
    return found


def _prepare_start(p, cfg, spec, choice, cli: dict, limit: int | None = None) -> None:
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
            if limit is not None:
                # 상한 검사와 예약(아래 _begin 의 launch_failed·실행자)을 한 프로젝트 잠금 안에서 한다(start-ready 만)
                busy = occupied(p, tid)
                if len(busy) >= limit:
                    raise HteamError("parallel_limit", f"동시 수 상한 {limit} 에 닿았다: {', '.join(busy)}", CONFLICT,
                                     data={"occupied": busy})
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
                          expect={"launch_failed"})
    try:
        # fix·drop 의 취소·전이가 그 사이 끼었으면 working 으로 두지 않는다(정리는 그쪽이 horch 상태로 한다)
        with dispatch.owned(p, tid, work_slot, {"launch_failed"}) as st:
            if res["mode"] == "adopt":  # 실제로 도는 워커에 맞춘다(리뷰어는 이 agent 의 반대쪽)
                st["rounds"][-1].update(agent=res["agent"], model=res["model"], effort=res["effort"])
            state.move(st, "working", "launched", dispatch=res["dispatch"])
            rd = st["rounds"][-1]
    except HteamError as exc:
        dispatch.left_running(exc, res)
        raise
    return {"task": tid, "round": rd["round"], "status": "working", "agent": rd["agent"], "model": rd["model"],
            "effort": rd["effort"], **res}


def start(p, tid: str, cli: dict, cfg=None, h=None, limit: int | None = None) -> dict:
    """limit 은 start-ready 만 준다(max_parallel 은 start-ready 만 본다, 설계 5.4)."""
    cfg = cfg or config.load(p)
    spec = specs.check(p, cfg, tid)
    choice = config.resolve(cfg, spec.role, spec.front, cli)
    h = h or Horch(p.horch_home)
    _prepare_start(p, cfg, spec, choice, cli, limit)
    return run_work(p, cfg, h, tid)


def deps_met(p, cfg, spec) -> bool:
    """선행이 done 이거나, 선행·후행이 모두 승인 직무이고 선행이 awaiting_user(설계 5.3)."""
    for dep in spec.depends_on:
        ds = state.load(p, dep)
        if ds is None:
            return False
        if ds["status"] == "done":
            continue
        if ds["status"] == "awaiting_user" and cfg.is_approval(spec.role) and cfg.is_approval(ds.get("role")):
            continue
        return False
    return True


WAIT_CODES = {"owns_locked": "lock", "planner_busy": "lock", "launching": "launching", "parallel_limit": "limit"}


def start_ready(p) -> dict:
    """tasks.toml 순서로 사양 → 의존 → 잠금 → 동시 수 상한을 보고 통과한 것을 start 한다(설계 5.4).

    잠금·상한은 start 가 프로젝트 잠금 안에서 본다(복구는 저장된 owns, 상한 검사와 예약은 원자적).
    한 태스크의 오류(예상 밖 오류 포함)는 그 태스크만 실패로 두고 계속한다."""
    cfg = config.load(p)
    h = Horch(p.horch_home)
    started, waiting, failed = [], [], []
    for tid in plan.order(p):
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
                waiting.append({"task": tid, "reason": "deps", "detail": ", ".join(spec.depends_on)})
                continue
            res = start(p, tid, {}, cfg=cfg, h=h, limit=cfg.max_parallel)
            started.append({"task": tid, "round": res["round"], "dispatch": res["dispatch"],
                            "warnings": res["warnings"]})
        except HteamError as exc:
            if exc.code in WAIT_CODES:
                waiting.append({"task": tid, "reason": WAIT_CODES[exc.code], "detail": exc.message})
            else:
                failed.append({"task": tid, "error": exc.to_json()["error"]})
        except Exception as exc:  # 버그·예상 밖 오류도 이 태스크만 실패로 둔다(cli 의 internal 과 같은 모양)
            failed.append({"task": tid, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}",
                                                  "hint": ""}})
    if failed:
        raise HteamError("start_failed", f"{len(failed)}개 태스크를 띄우지 못했다", FAIL,
                         "실패한 태스크는 hteam status 의 next 를 따른다",
                         data={"started": started, "waiting": waiting, "failed": failed})
    return {"started": started, "waiting": waiting}


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
