"""작업 라운드(설계 5.4·6.4): start, start-ready, fix, accept, drop, scope(7.1).

CLI 는 큐 명령이다(설계 7.1): 관제(와 그 자식)에서 부르면 바로 하고, 메인에서 부르면 요청 큐로 관제에 넘긴다(queue.route).
큐 요청이 바꾼 history 사건에는 request(요청 id)를 남긴다(다시 뜬 관제의 재실행 막기). 관제 안의 fix·drop 은 finish 잠금을
기다리지 않고 accept 는 먼저 탐침한다(nowait, 설계 8.5)."""
from __future__ import annotations

import contextlib
import os
from typing import Iterator

from . import compose, config, crew, dispatch, gitio, outbox, plan, procs, queue, redmine, roles, specs, state, workspace
from .errors import CONFLICT, FAIL, MISSING, USAGE, HteamError
from .globs import any_overlap, within
from .horch import Horch, failure
from .paths import SHIM, find_project
from .util import die_at, now, write_atomic


def work_slot(st: dict) -> dict:
    return st["rounds"][-1]["work"]


def lock_conflicts(p, tid: str, owns: list[str]) -> list[dict]:
    """잠금을 가진 다른 태스크 가운데 owns 가 겹치는 것. 작업 공간 슬롯을 쥔 태스크는 pending(예약)이어도 잠금을 가진다
    (설계 5.10.3: 같은 옛 기준에서 두 태스크가 브랜치를 준비하지 않게). 닫힌 태스크는 슬롯을 쥐어도 아니다(잠금은 병합까지)."""
    holders = {rec.get("task") for rec in workspace.load(p)["slots"].values() if rec.get("task")}
    found = []
    for other in state.all_states(p):
        if other["id"] == tid:
            continue
        if other["status"] not in state.LOCKING and (other["id"] not in holders or other["status"] in state.CLOSED):
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
    """note 는 사용자 요청 라운드(from_user)면 사용자 요청, 아니면 지시다. coord_note 는 사용자 요청 라운드를
    잇는 일반 fix 의 지시다(사용자 요청과 섞지 않는다)."""
    rd = {"round": n, "round_base": head, "agent": choice.worker, "model": choice.model, "effort": choice.effort,
          "note": note, "supplement": supplement, "work": dispatch.new_slot(roles.work_title(st["id"], n)),
          "reviews": [], "verdict": None}
    if coord_note:
        rd["coord_note"] = coord_note
    return rd


def _crew_choice(cfg, spec, cli: dict, plc: dict):
    """고정 에이전트 라운드의 작업 에이전트·모델(설계 4.1 6단계)과 model_ignored. 처음 띄우면 [crew.<이름>] > [defaults],
    같은 터미널에 넣으면 떠 있는 세션의 entry 값(설정을 바꿨어도 세션 그대로). 리뷰어는 직무 규칙 그대로다."""
    choice, ignored = config.crew_choice(cfg, plc["crew"], spec.role, spec.front, cli)
    if plc["mode"] == "insert":
        choice.model, choice.effort = plc["entry"]["model"], plc["entry"]["effort"]
    return choice, ignored


def _crew_round(rd: dict, plc: dict, ignored, forced: bool = False) -> None:
    """라운드 기록의 고정 에이전트 이름(설계 5.3·5.9.1 의 crew) 또는 temp, model_ignored, forced."""
    rd["crew"] = plc["crew"].name if plc["kind"] == "crew" else "temp"
    if plc["kind"] == "crew":
        rd["model_ignored"] = bool(ignored)
    if forced:
        rd["forced"] = True


def _agent_busy(reason: str) -> HteamError:
    return HteamError("agent_busy", reason, CONFLICT, data={"reason": "agent", "detail": reason})


def _recovery_place(p, cfg, spec, rd: dict) -> dict:
    """같은 라운드 복구의 배정: 그 라운드의 고정 에이전트(바쁘거나 리셋 중이면 기다린다), temp·없음이면 임시 워커."""
    name = crew.round_crew(rd)
    return crew.place(p, cfg, spec.role, rd["agent"], crew_name=name) if name else dict(crew.TEMP)


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


def _req(request: str | None) -> dict:
    """큐 요청이 바꾼 history 사건에 넣을 필드(설계 7.1 재실행 막기)."""
    return {"request": request} if request else {}


def _slot_preparing(n: int) -> HteamError:
    return HteamError("slot_preparing", f"작업 공간 slot-{n} 을 준비하는 중이다(관제가 hteam slot prepare 를 돌린다)",
                      CONFLICT, "준비가 끝나면 관제가 띄운다")


def _no_free_slot(cfg) -> HteamError:
    return HteamError("no_free_slot", f"빈 작업 공간 슬롯이 없다(slots = {cfg.workspace.slots})", CONFLICT,
                      "슬롯이 비면 관제가 띄운다")


def _base_detached(tid: str) -> HteamError:
    return HteamError("base_detached", f"메인 폴더가 detached HEAD 라 {tid} 의 작업 공간 슬롯을 잡지 않았다(기준 브랜치가 "
                      "없다). 메인 폴더를 기준 브랜치로 되돌린 뒤 다시 시작한다", CONFLICT,
                      f"메인 폴더에서 git switch <기준 브랜치> 뒤 hteam start {tid}")


def _take_slot(p, cfg, st: dict, owns: list[str], data: dict) -> tuple[HteamError | None, str | None, bool]:
    """작업 공간 태스크의 슬롯 잡기(설계 5.10.3 의 1·5, 끝 문단). 프로젝트 잠금 → 태스크 잠금 안에서 부른다. data 는 읽은
    slots.json 이고 이 함수가 고친다. 쓸 것이 없는 기다림은 바로 올린다(상태 블록이 예외로 끝나 아무것도 쓰지 않는다). 아니면
    (상태를 쓴 뒤 올릴 기다림, drive.log 줄, data 를 저장할지).

    - 슬롯이 없으면: 메인 폴더가 detached HEAD 면 base_detached, 빈 슬롯이 없으면 no_free_slot(둘 다 아무것도 쓰지 않는다).
      아니면 가장 작은 free 슬롯에 예약(preparing)을 쓰고 상태에 owns 를 남긴 뒤 slot_preparing(예약이 owns 잠금을 쥔다).
    - preparing 이고 준비가 끝나지 않았으면 slot_preparing(아무것도 쓰지 않는다).
    - preparing·ready 면 busy 로 바꾸고 상태에 workspace 를 쓴다. 부르는 쪽이 이어 띄운다.
    - busy 면(수정 라운드·같은 라운드 복구) 그대로 이어 한다."""
    tid = st["id"]
    n = workspace.held_by(data, tid)
    if n is None:
        branch = gitio.current_branch(p.root)
        if branch is None:
            raise _base_detached(tid)
        n = next((i for i in range(1, cfg.workspace.slots + 1) if workspace.entry(data, i)["state"] == "free"), None)
        if n is None:
            raise _no_free_slot(cfg)
        data["slots"][str(n)] = {**workspace.SLOT_DEFAULT, "state": "preparing", "task": tid,
                                 "branch": workspace.branch_of(tid), "base_branch": branch, "base": gitio.head(p.root),
                                 "setup_done": workspace.entry(data, n)["setup_done"], "since": now()}
        st["owns"] = owns
        return _slot_preparing(n), f"slot-{n} {tid} 잡기 preparing", True
    rec = workspace.entry(data, n)
    if rec["state"] == "preparing" and not rec.get("ready"):
        raise _slot_preparing(n)
    if rec["state"] == "preparing":
        data["slots"][str(n)] = {k: v for k, v in {**rec, "state": "busy", "since": now()}.items() if k != "ready"}
        st["workspace"] = {"slot": n, "branch": rec["branch"], "base_branch": rec["base_branch"],
                           "root": str(workspace.work_root(p, n)), "merge": None}
        if st["base"] is None:
            st["base"] = rec["base"]
        return None, f"slot-{n} {tid} 사용 busy", True
    return None, None, False


def _prepare_start(p, cfg, spec, choice, cli: dict, cap: Capacity | None = None, request: str | None = None) -> dict:
    """시작 예약(설계 5.4 1–4). 프로젝트 잠금 안에서 상태 → 잠금 → 결정 → 동시 수 상한 뒤 배정(5.9.4)을 보고 배정을
    돌려준다. 기다려야 하면 아무것도 쓰지 않고 exit 3 agent_busy.

    작업 공간 태스크(설계 5.10.3)는 배정 뒤 슬롯을 잡는다(_take_slot). 예약을 쓰면 상태(owns)를 저장한 뒤 slots.json 을 쓰고
    잠금을 놓은 다음 slot_preparing 을 올린다. slots.json 은 상태 쓰기가 끝난 뒤 같은 프로젝트 잠금 안에서 쓴다(상태 쓰기가
    실패하면 슬롯도 그대로다). 띄울 슬롯(busy·준비 끝)이 자기 worktree 가 아니면 아무것도 쓰지 않고 exit 1 slot_not_worktree
    (workspace.require_worktree): 슬롯에 워커를 띄우는 start·start-ready·같은 라운드 복구가 모두 여기를 지난다. fix 는 fix 가
    본다."""
    tid = spec.id
    wait, line = None, None
    with state.project_lock(p):
        state.create(p, tid, spec.role)  # 사양만 있고 상태가 없으면 pending 으로 만든다
        with state.edit(p, tid) as st:
            if st["status"] in state.CLOSED:
                raise state.closed_error(st)
            if st["status"] not in ("pending", "launch_failed"):
                raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(start 는 pending·launch_failed 에서)", CONFLICT,
                                 data={"status": st["status"]})
            # start-ready 만: 후보를 고른 뒤 관제가 지금 라운드에 decide 를 올렸을 수 있다(설계 5.4). start T 는 보지 않는다
            if cap is not None and (oid := outbox.open_decide(p, st)):
                raise HteamError("decide_open", f"메인이 답하지 않은 decide {oid} 가 있다", CONFLICT)
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
            plc = _recovery_place(p, cfg, spec, rd) if recovering else crew.place(p, cfg, spec.role, choice.worker)
            if plc["kind"] == "wait":
                raise _agent_busy(plc["reason"])
            slots, keep = None, False
            if cfg.workspace.covers(spec.role):
                slots = workspace.load(p)
                wait, line, keep = _take_slot(p, cfg, st, owns, slots)
                if wait is None:  # 띄울 슬롯(busy·준비 끝)이 worktree 가 아니면 라운드·상태·slots.json 을 쓰기 전에 거부한다
                    workspace.require_worktree(p, st)
            if wait is None:
                if not recovering:
                    st["role"] = spec.role  # 워커는 이 사양의 직무로 뜬다. planner 하나 검사가 저장된 직무를 본다
                    st.pop("start_cli", None)  # 기다리게 둔 start 의 옵션은 이 라운드로 끝난다(start_command)
                    head = gitio.head(workspace.task_root(p, st))  # 작업 공간 태스크면 슬롯의 HEAD(설계 5.10.4)
                    ch, ignored = _crew_choice(cfg, spec, cli, plc) if plc["kind"] == "crew" else (choice, None)
                    rd = _new_round(st, st["round"] + 1, head, ch)
                    _crew_round(rd, plc, ignored)
                    text = compose.work_spec(p, cfg, spec, rd, owns, st)
                    if st["base"] is None:
                        st["base"] = head  # 태스크를 처음 띄울 때 한 번만
                    st["rounds"].append(rd)
                    st["round"] = rd["round"]
                else:
                    stored = _spec_file(p, tid, rd["round"])  # base·round_base·사양은 그대로
                    text = stored.read_text(encoding="utf-8") if stored.is_file() else \
                        compose.work_spec(p, cfg, spec, rd, owns, st)
                st["owns"] = owns
                _begin(p, st, rd, text, "start", **_req(request))
        if keep:
            workspace.save(p, slots)
    if line:
        from .drive import Drive  # drive 가 tasks 를 쓴다
        Drive(p).log(line)
    if wait is not None:
        raise wait
    return plc


TRANSIENT = ("terminal_not_ready", "terminal_busy")  # 확인과 보내기 사이에 세션이 일을 시작했다(일시 거부, 5.9.3 의 3)


def run_work(p, cfg, h, tid: str, plc: dict | None = None) -> dict:
    """현재 라운드 작업 워커를 띄운다(설계 5.4 5–6). 실패하면 launch_failed 그대로 exit 1(horch 의 12 는 12).

    plc 는 배정(crew.place): 임시 워커는 지금 그대로, 고정 에이전트의 처음은 에이전트 탭에 --keep-open(Claude 는 --name),
    살아 있는 세션은 --terminal 로 넣는다(5.9.2·5.9.3). 넣기가 일시 거부면 그 라운드에 transient 를 쓰고 그대로 실패,
    terminal_gone 이면 터미널을 잊고 같은 라운드를 새 세션으로 띄운다. working 뒤 고정 에이전트 기록(crew.after_launch)."""
    plc = plc or dict(crew.TEMP)
    st = state.require(p, tid)
    rd = st["rounds"][-1]
    args, where = cfg.args(rd["agent"]), {}
    if st.get("workspace"):  # 작업 공간 태스크: 슬롯의 작업 루트와 슬롯 env 로 띄운다(설계 5.10.3 의 5)
        where.update(cwd=workspace.task_root(p, st), env=workspace.slot_env(cfg, st["workspace"]["slot"]))
    if plc["kind"] == "crew":
        if plc["mode"] == "insert":
            where["same_terminal"] = plc["terminal"]
        else:
            where["keep_open_tab"] = crew.agent_tab(p.root, outbox._run(p).get("team_space"), plc["crew"].name)
            extra = crew.name_arg(plc["crew"])
            args = [*args, extra] if extra else args
    try:
        res = dispatch.launch(p, h, tid, work_slot, agent=rd["agent"], model=rd["model"], effort=rd["effort"],
                              args=args, spec_file=_spec_file(p, tid, rd["round"]),
                              expect={"launch_failed"}, on_fresh=_launch_basis, **where)
    except HteamError as exc:
        code = (((exc.data or {}).get("horch") or {}).get("error") or {}).get("code")
        if plc["kind"] == "crew" and code in TRANSIENT:
            with dispatch.owned(p, tid, work_slot, {"launch_failed"}) as st:
                work_slot(st)["transient"] = True  # 관제 재확인이 decide 를 올리지 않고 start-ready 가 다시 넣는다(8.7)
            raise
        if plc["kind"] == "crew" and plc["mode"] == "insert" and code == "terminal_gone":
            crew.forget(p, plc["crew"].name)
            return run_work(p, cfg, h, tid, {"kind": "crew", "crew": plc["crew"], "mode": "fresh"})
        raise
    try:
        # fix·drop 의 취소·전이가 그 사이 끼었으면 working 으로 두지 않는다(정리는 그쪽이 horch 상태로 한다)
        with dispatch.owned(p, tid, work_slot, {"launch_failed"}) as st:
            cur = st["rounds"][-1]
            if res["mode"] == "adopt":  # 실제로 도는 워커에 맞춘다(리뷰어는 이 agent 의 반대쪽)
                cur.update(agent=res["agent"], model=res["model"], effort=res["effort"])
            cur["work"].pop("transient", None)
            for key in ("start_turn", "delivery"):  # 같은 터미널에 넣었을 때(5.9.3 의 3)
                if res.get(key) is not None:
                    cur[key] = res[key]
            state.move(st, "working", "launched", dispatch=res["dispatch"])
            rd = cur
    except HteamError as exc:
        dispatch.left_running(exc, res, h)
        raise
    redmine.started(p, cfg, st)  # 설계 8.12: 라운드 시작(start·fix·대기열·복구 모두 이 자리를 지난다)
    if plc["kind"] == "crew":
        crew.after_launch(p, plc, tid, rd, res)
    out = {"task": tid, "round": rd["round"], "status": "working", "agent": rd["agent"], "model": rd["model"],
           "effort": rd["effort"], **res}
    nxt, hint = _adopted_next(cfg, tid, rd["round"], res)
    if nxt is not None:
        out["next"] = nxt
    if hint:
        out["hint"] = hint
    return out


def fix_next(cfg, tid: str, rnd: int, note: str | None) -> tuple[list[str] | None, str | None]:
    """다음 명령으로 fix 를 권하되 라운드 상한(max_rounds)에 닿았으면 권하지 않고 그 까닭을 준다: fix 가 --force-round 없이
    exit 3 로 거부하고 상한은 사용자가 정한다(설계 13장). cfg 가 None(설정을 읽지 못했다)이면 상한을 보지 않는다.
    status 의 next(coord)와 이어 붙인 작업 워커의 next(_adopted_next)가 같이 쓴다."""
    limit = cfg.max_rounds if cfg else None
    if limit is not None and rnd >= limit:
        return None, (f"max_rounds({limit}) 에 닿았다. fix 는 --force-round 없이 exit 3 로 거부한다. 메인에 묻고, 사용자가 "
                      f"계속하라고 하면 {SHIM} fix {tid} --force-round --note …")
    return [SHIM, "fix", tid, *(("--note", note) if note else ())], None  # 리뷰 수정 요청은 메모 없이(설계 10장)


def _adopted_next(cfg, tid: str, rnd: int, res: dict) -> tuple[list[str] | None, str | None]:
    """이어 붙인 작업 Dispatch 가 이미 끝났으면(done 뒤 settled·retained·released) 다음 명령. 그 worker_done 은 태스크가
    launch_failed 일 때 와서(그때 next 는 start) 다시 오지 않으므로 여기서 준다."""
    if res.get("mode") != "adopt" or res.get("state") not in ("settled", "retained", "released"):
        return None, None
    if res.get("outcome") == "succeeded":
        return [SHIM, "review", tid], "이어 붙인 작업 워커가 이미 성공으로 끝났다"
    nxt, why = fix_next(cfg, tid, rnd, f"작업 실패: {(res.get('summary') or '')[:200]}")
    return nxt, "이어 붙인 작업 워커가 이미 실패로 끝났다" + (f". {why}" if why else "")


def start(p, tid: str, cli: dict, cfg=None, h=None, cap: Capacity | None = None, request: str | None = None) -> dict:
    """cap 은 start-ready 만 준다(max_parallel 은 start-ready 만 본다, 설계 5.4). request 는 큐 요청 id(start 사건에 남긴다)."""
    cfg = cfg or config.load(p)
    spec = specs.check(p, cfg, tid)
    choice = config.resolve(cfg, spec.role, spec.front, cli)
    h = h or Horch(p.horch_home)
    try:
        plc = _prepare_start(p, cfg, spec, choice, cli, cap, request)
    except HteamError as exc:
        if exc.code == "base_detached":  # 잠금을 모두 놓은 뒤 메인에 올린다(설계 5.10.1·5.10.8). 관제 안에서만 불린다
            from .drive import Drive  # drive 가 tasks 를 쓴다
            Drive(p).decide("workspace_failed", tid, exc.message, commands=[f"hteam start {tid}"],
                            detail={"kind": "base_moved", "detached": True})
        raise
    return run_work(p, cfg, h, tid, plc)


# hteam start 의 기다림(설계 5.4 의 6단계 문단): 처음 시작하는 태스크가 지금 시작할 수 없으면 pending 그대로 exit 0
START_WAIT = {"deps_unmet": "deps", "owns_locked": "lock", "planner_busy": "lock", "agent_busy": "agent",
              "slot_preparing": "slot_setup", "no_free_slot": "slot"}
WAIT_TAIL = {"deps": "선행이 끝나면 관제가 띄운다", "lock": "잠금이 풀리면 관제가 띄운다", "agent": "에이전트가 비면 관제가 띄운다",
             "slot_setup": "준비가 끝나면 관제가 띄운다", "slot": "슬롯이 비면 관제가 띄운다"}
SLOT_WAIT = ("slot_preparing", "no_free_slot")  # 준비 실패 뒤(라운드 없는 launch_failed)의 start 도 기다림이다(설계 5.10.3)


def _prep_failed(st: dict) -> bool:
    """슬롯 준비가 실패해 라운드 없이 launch_failed 다(설계 5.10.3 의 4). start 는 처음 시작(pending)처럼 다룬다."""
    return st["status"] == "launch_failed" and not st["rounds"]


def _waiting(p, tid: str, reason: str, said: str, cli: dict, *, prep_failed: bool = False) -> dict:
    """기다림 결과. 받은 --worker·--model·--effort 는 상태의 start_cli 에 남긴다: start-ready 가 이 태스크를 띄울 때 쓴다
    (Codex 브랜치 리뷰 p6r1). 라운드 없는 launch_failed(prep_failed)도 같다(Codex 커밋 리뷰 b916c8c P2). 새 라운드를 쓰는
    시작 예약이 지운다(_prepare_start)."""
    if cli:
        with state.edit(p, tid) as st:
            if st["status"] == "pending" or _prep_failed(st):
                st["start_cli"] = dict(cli)
    kept = "launch_failed(라운드 없음) 그대로 두었다" if prep_failed else "pending 으로 두었다"
    return {"id": tid, "status": "waiting", "reason": reason, "message": f"{tid}: {said}. {kept}. {WAIT_TAIL[reason]}"}


def start_command(p, tid: str, cli: dict, *, request: str | None = None) -> dict:
    """`hteam start T` 와 큐 요청 start 의 명령 의미(설계 5.4 의 6단계 문단). 처음 시작(상태 없음·pending)이면 먼저 의존을
    보고(끝나지 않았으면 기다린다), 잠금·에이전트 거부를 exit 0 waiting 으로 바꾼다. 같은 라운드 복구는 그 오류 그대로다.
    처음 시작(라운드 없는 launch_failed 포함)인데 옵션이 없으면 앞서 기다리게 둔 start 의 옵션(start_cli)을 쓴다. 옵션을
    명시하면 그 값이 새 기준이다."""
    cfg = config.load(p)
    spec = specs.check(p, cfg, tid)
    st = state.load(p, tid) or state.create(p, tid, spec.role)  # 기다리게 둬도 start-ready 가 볼 상태가 있어야 한다
    first = st["status"] == "pending"
    prep_failed = _prep_failed(st)  # 슬롯 준비가 실패했다(라운드 없음)
    if (first or prep_failed) and not cli:
        cli = st.get("start_cli") or {}
    if first and not deps_met(p, cfg, spec):
        return _waiting(p, tid, "deps", f"선행이 끝나지 않았다({_unmet_text(unmet_deps(p, cfg, spec), spec)})", cli)
    try:
        return start(p, tid, cli, cfg=cfg, request=request)
    except HteamError as exc:
        if exc.code in START_WAIT and (first or (prep_failed and exc.code in SLOT_WAIT)):
            return _waiting(p, tid, START_WAIT[exc.code], exc.message, cli, prep_failed=prep_failed)
        raise


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
              "deps_unmet": "deps", "decision_pending": "decision", "decide_open": "decide", "agent_busy": "agent",
              "slot_preparing": "slot_setup", "no_free_slot": "slot", "base_detached": "decide"}


def _transient(p, tid: str) -> bool:
    """지금 라운드의 작업 실행 기록에 일시 거부 표시(transient)가 있나."""
    rd = state.current_round(_load_quiet(p, tid) or {})
    return bool(rd and rd["work"].get("transient"))


def _refused(exc: HteamError, note: str | None) -> str:
    """관제 절차 실패 문구(설계 8.5)."""
    return f"관제 절차 실패: {exc.code}: {exc.message}" + (f" (아직 전하지 못한 지시: {note})" if note else "")


def drain(p, cfg) -> list[dict]:
    """수정 대기열 비우기(설계 5.9.5, start-ready 맨 앞): 설정 순서로 에이전트마다 맡은 태스크·리셋이 없고 큐가 있으면 맨 앞
    하나의 queued_fix 로 fix(from_queue) 한다. 작업 터미널이 확인 불가이거나 쉬지 않으면 꺼내지 않는다. 리뷰 관문이 잡고 있으면
    그대로 두고, 그 밖의 거부는 queued_fix 를 지우고 decide 로 올린다. 새 라운드를 연 [{task, round, dispatch}]."""
    from .drive import Drive  # drive 가 tasks 를 쓴다
    out: list[dict] = []
    data = crew.load(p)
    for name in cfg.crew:
        e = {**crew.blank(name), **(data.get(name) or {})}
        if e["task"] or e["resetting"] or not e["queue"]:
            continue
        tid = e["queue"][0]
        q = (state.load(p, tid) or {}).get("queued_fix")
        if not q:
            crew.unqueue(p, tid)  # 라운드를 연 뒤 큐에서 빼기 전에 멈췄다
            continue
        if e["terminal"]:
            verdict, info = crew.probe(e["terminal"], e["terminal_argv"])
            if verdict == "unknown" or (verdict == "live" and crew.word(info) not in crew.READY):
                continue
        try:
            res = fix(p, tid, note=q.get("note"), supplement=q.get("supplement"), force_round=bool(q.get("force_round")),
                      cli={}, from_queue=True, request=q.get("request"), nowait=True)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            if exc.code == "review_busy":  # 리뷰 관문이 finish 잠금을 쥐었다: 다음 start-ready 가 다시 꺼낸다
                continue
            if (state.load(p, tid) or {}).get("queued_fix"):  # 라운드를 열기 전에 거부됐다
                crew.clear_queued(p, tid)
                flags = " --force-round" if exc.code == "max_rounds" else ""
                Drive(p).decide("escalation", tid, _refused(exc, q.get("note")),
                                commands=[f'hteam fix {tid}{flags} --note "<지시>"', f"hteam drop {tid}"])
            else:
                crew.unqueue(p, tid)
            continue
        if "round" not in res:  # 그 사이 다시 바빠져 줄을 섰다
            continue
        Drive(p).log(f"{tid} r{res['round']} 수정 시작")
        out.append({"task": tid, "round": res["round"], "dispatch": res["dispatch"]})
    return out


def start_ready(p) -> dict:
    """tasks.toml 순서로 사양 → 의존 → 잠금 → 동시 수 상한을 보고 통과한 것을 start 한다(설계 5.4). 먼저 고정 에이전트의
    수정 대기열을 비운다(drain, 5.9.5).

    잠금·상한은 start 가 프로젝트 잠금 안에서 본다(복구는 저장된 owns, 상한 검사와 예약은 원자적).
    한 태스크의 오류(예상 밖 오류 포함)는 그 태스크만 실패로 두고 계속한다. 일시 거부(transient)로 남은 launch_failed 는
    실패가 아니라 대기 사유 agent 다."""
    cfg = config.load(p)
    h = Horch(p.horch_home)
    cap = Capacity(h, cfg.max_parallel)
    drained = drain(p, cfg)
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
            oid = outbox.open_decide(p, st)  # 메인이 답하지 않은 지금 라운드의 decide 가 있으면 띄우지 않는다(설계 5.4)
            if oid:
                waiting.append({"task": tid, "reason": "decide", "detail": f"메인이 답하지 않은 decide {oid} 가 있다"})
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
            res = start(p, tid, st.get("start_cli") or {}, cfg=cfg, h=h, cap=cap)  # 기다리게 둔 start 의 옵션
            started.append({"task": tid, "round": res["round"], "dispatch": res["dispatch"],
                            "warnings": res["warnings"], **{k: res[k] for k in ("next", "hint") if res.get(k)}})
        except Exception as exc:
            if not isinstance(exc, HteamError):  # 버그·예상 밖 오류도 이 태스크만 실패로 둔다(cli 의 internal 모양)
                failed.append({"task": tid, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}",
                                                      "hint": ""}})
            elif exc.code in WAIT_CODES:
                waiting.append({"task": tid, "reason": WAIT_CODES[exc.code], "detail": exc.message})
            elif exc.code == "launch_failed" and _transient(p, tid):
                waiting.append({"task": tid, "reason": "agent", "detail": exc.message})
            else:
                failed.append({"task": tid, "error": exc.to_json()["error"]})
    if failed:
        raise HteamError("start_failed", f"{len(failed)}개 태스크를 띄우지 못했다", FAIL,
                         "실패한 태스크는 hteam status 의 next 를 따른다",
                         data={"started": started, "waiting": waiting, "failed": failed, "drained": drained})
    return {"started": started, "waiting": waiting, "drained": drained}


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
            if row["state"] == "active" and row.get("persistent") and (
                    row.get("verdict") == "unverifiable" or
                    (row.get("verdict") == "live" and row.get("status") in ("working", "blocked"))):
                # 고정 Dispatch 는 --keep-terminal 로만 버리므로 세션이 계속 일한다. 일하는 중이거나 확인할 수 없으면 정리하지
                # 않는다(설정에서 지운 고정 에이전트 태스크를 임시 워커로 고칠 때 두 워커가 같은 파일을 고치지 않게)
                said = row.get("status") if row.get("verdict") == "live" else "상태 확인 불가"
                raise HteamError("worker_active", f"Dispatch {did}({slot['title']}) 가 아직 active 다(고정 에이전트 세션 "
                                 f"{said})", CONFLICT, "세션이 쉬거나 끝난 뒤 다시 한다. 사용자에게 그 에이전트 탭을 확인해 "
                                 "달라고 한다", data={"dispatch": did})
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


def _close_round(p, h, tid: str, *, kill: bool, check=None, seen: dict | None = None, nowait: bool = False) -> list[dict]:
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
    태스크)를 지키려고 프로젝트 잠금은 쥐지 않는다. nowait(관제 안)면 finish 잠금을 기다리지 않는다: 리뷰 관문이 돌면
    아무것도 바꾸지 않고 exit 3 review_busy(설계 8.5)."""
    seen = {} if seen is None else seen
    with state.finish_lock(p, tid, nowait=nowait):
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


def _keep_abandon(h, did: str | None) -> None:
    """쉬는 고정 에이전트 세션을 둔 채 그 Dispatch 를 버린다(active 일 때만, 설계 5.9.5·5.9.6). release 는 _close_round 가 한다."""
    row = dispatch.row_by_id(h.workers(), did)
    if row is not None and row["state"] == "active":
        h.ok("worker-abandon", "--dispatch", did, "--keep-terminal")


def _crew_fix(p, h, tid: str, member, st: dict, *, force: bool, from_queue: bool) -> tuple[dict | None, bool]:
    """고정 에이전트 라운드 fix 의 에이전트 보기(설계 5.9.5·5.9.6): (배정, forced). 배정이 None 이면 대기열에 넣는다.
    held(그 에이전트가 아직 이 태스크를 맡았다)면 바쁨으로 보지 않는다(자기 뒤에 줄 서면 드레인이 영영 꺼내지 않는다).
    --force 는 대상 확인(맡은 태스크·지금 작업 Dispatch)을 통과했을 때만 세션을 닫고 새 세션으로 띄운다."""
    rd = state.current_round(st) or {}
    did = rd["work"].get("dispatch") if rd else None
    e = crew.entry(p, member.name)
    held = e["task"] == tid
    fresh = {"kind": "crew", "crew": member, "mode": "fresh"}
    if force and held and did and e["dispatch"] == did:
        crew.close_session(p, member.name, tid)
        return fresh, True
    if not held and (e["task"] or e["resetting"] or (not from_queue and any(x != tid for x in e["queue"]))):
        return None, False
    if not e["terminal"]:
        return fresh, False
    verdict, info = crew.probe(e["terminal"], e["terminal_argv"])
    if verdict == "gone":
        crew.forget(p, member.name)
        return fresh, False
    if verdict == "unknown":
        if held:
            raise HteamError("unverifiable", f"{tid}: 이 태스크를 맡은 {member.title} 에이전트 작업 터미널({e['terminal']}) "
                             "상태를 확인하지 못했다", FAIL, "잠시 뒤 다시 한다")
        return None, False
    word = crew.word(info)
    if word in crew.READY:
        if held:  # 떼고 바로 넣는다(5.9.5): 버린 Dispatch 에서는 worker_done 이 오지 않으므로 맡은 태스크도 비운다
            _keep_abandon(h, did)
            crew.free(p, tid)
        return {"kind": "crew", "crew": member, "mode": "insert", "terminal": e["terminal"], "entry": e}, False
    if held:
        raise HteamError("worker_active", f"{tid}: 고정 에이전트가 아직 이 태스크를 하고 있을 수 있다({word or '보고 없음'}). "
                         "worker_done 을 기다린다. 지금 고쳐야 하면 --force(세션을 닫고 새 세션으로 띄운다)", CONFLICT)
    return None, False


def _require_slot(p, st: dict) -> None:
    """작업 공간 직무 태스크의 fix 는 그 태스크가 busy 슬롯을 쥘 때만 한다(설계 5.10.3·6.4). 준비 실패 뒤의 라운드 없는
    launch_failed 등은 아무것도 바꾸지 않고 exit 3 slot_not_held: fix 는 슬롯을 잡지 않으므로 그대로 두면 슬롯 env·작업 공간 절
    없이 메인 폴더에서 워커가 뜬다. 다시 시작은 hteam start T(슬롯을 다시 잡는다)."""
    tid = st["id"]
    data = workspace.load(p)
    n = workspace.held_by(data, tid)
    if n is None or workspace.entry(data, n)["state"] != "busy":
        raise HteamError("slot_not_held", f"{tid} 는 작업 공간 슬롯을 쥐고 있지 않다(슬롯 준비가 끝나지 않았거나 실패했다). "
                         "fix 는 슬롯 밖에서 새 라운드를 열지 않는다", CONFLICT, f"hteam start {tid}",
                         data={"status": st["status"], "slot": n})


def fix(p, tid: str, *, note: str | None, supplement: str | None, force_round: bool, cli: dict,
        expect_round: int | None = None, queue: bool = False, from_user: bool = False,
        extra_from: tuple[str, ...] = (), follower: bool = False, request: str | None = None,
        nowait: bool = False, force: bool = False, from_queue: bool = False) -> dict:
    """새 라운드(설계 6.4). 입력(사양·owns·잠금)을 먼저 검사하고, 이전 라운드들의 작업·리뷰 Dispatch 를 모두 정리한
    뒤에만 새 라운드를 쓰고 띄운다(이전 워커와 새 워커가 같은 폴더에서 함께 일하지 않게). 일하는 중인 워커는
    abandon --kill 뒤 release.

    일괄 승인 결정(설계 11.4)이 부를 때: queue 면 새 라운드를 쓰고 띄우지 않는다(launch_failed, queued. start-ready 가
    의존이 풀린 뒤 띄운다). from_user 면 사용자 요청 라운드다(결정만 준다. awaiting_user 에서의 다른 fix, 예를 들어
    --supplement 는 사용자 요청이 아니다). 다만 일반 fix 가 아직 사용자에게 다시 보이지 않은 사용자 요청 라운드(워커 실패
    등)를 닫으면 그 요청을 --note 와 합쳐 잇고 사용자 요청 라운드로 둔다(요청을 잃지 않는다). 보강 라운드(--supplement)가
    다시 승인되지 못한 채 닫히면 --supplement 없는 fix 도 그 보강 ID 를 잇는다(awaiting_user 에서 연 fix 는 잇지 않는다). extra_from 은 FIX_FROM 밖에서 더 받을 상태다(결정이 고치는 의존 태스크는
    리뷰 중·승인됨이어도 다시 만든다).

    request 는 큐 요청 id(fix 사건에 남긴다). nowait(관제 안)면 라운드를 닫는 finish 잠금을 기다리지 않는다(_close_round).
    보강 후행 태스크의 대기 라운드(_queue_followers)에는 잇지 않는다(알려진 한계, 설계 13장).

    고정 에이전트 라운드(설계 5.9.5)는 같은 에이전트가 고친다: 비어 있으면 같은 터미널에 넣고, 바쁘면 queued_fix 로 대기열에
    넣어 {id, status: queued, agent} 를 돌려준다(새 라운드는 드레인이 꺼낼 때 연다). force 는 일하는 세션을 닫고 새 세션으로
    띄운다(5.9.6, 임시 워커는 무시한다). from_queue 는 드레인이 맨 앞을 골라 부를 때다(큐 자리를 세지 않는다)."""
    cfg = config.load(p)
    spec = specs.check(p, cfg, tid)
    choice = config.resolve(cfg, spec.role, spec.front, cli)
    # 대기열의 수정(queued_fix)이 있으면 그 지시를 잇는다(새 라운드 쓰기가 표시를 지운다, 5.9.5). 사용자 결정 라운드(from_user)면
    # 대기 지시는 사용자 요청과 섞지 않고 지시(coord_note)로 잇는다(설계 7.4). supplement·force_round 는 같이 합친다
    queued = (state.load(p, tid) or {}).get("queued_fix")
    held_note = None
    if from_user and queued:
        held_note, queued = queued.get("note"), {**queued, "note": None}
    note, supplement, force_round = crew.merged(queued, note, supplement, force_round)
    followers: list[dict] = []
    defer = False
    if supplement is not None:
        _check_supplement(p, supplement)
        if not queue:
            followers = _supplement_followers(p, cfg, tid, supplement)  # 바꾸기 전에 거부할 것을 모두 본다
            die_at("supplement_followers_found")  # 테스트: 사전 검사 뒤 의존 태스크를 고치기 전에 결정이 끼는 순서
            kept = _reuse_queued(p, cfg, spec, tid, supplement, note, expect_round, choice, cli)
            if kept is not None:  # 이미 같은 보강의 대기 라운드가 있다. 새 라운드 없이 메모만 더한다(라운드 상한을 쓰지 않는다)
                kept["followers"], kept["warnings"] = _queue_followers(p, followers, supplement, tid) if followers else ([], [])
                return kept
            # 선행 승인 태스크가 아직 다시 승인되지 않았으면(보강 라운드가 도는 중) 바로 띄우지 않고 대기로 둔다. 띄우면
            # 선행의 옛 라운드를 basis 로 남겨 선행이 다시 승인된 뒤 approval_stale 이 된다(설계 11.4)
            defer = cfg.is_approval(spec.role) and not deps_met(p, cfg, spec)
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

    first = state.require(p, tid)
    allowed(first)
    if cfg.workspace.covers(spec.role):
        _require_slot(p, first)
        workspace.require_worktree(p, first)  # 슬롯이 worktree 가 아니면 이전 워커 정리·새 라운드 전에 거부한다
    last = state.current_round(first) or {}
    member = cfg.crew.get(crew.round_crew(last) or "")  # 설정에서 그 고정 에이전트를 지웠으면 임시 경로
    if member is not None and cli.get("worker") and cli["worker"] != last.get("agent"):
        raise HteamError("usage", f"{tid}: 고정 에이전트 태스크의 수정 라운드는 작업 에이전트를 바꾸지 못한다", USAGE)
    owns = checked_owns(cfg, spec)  # 입력 검사(owns·잠금)는 이전 워커를 정리하기 전에 한다
    _check_locks(p, cfg, spec, owns)
    if not queue or follower:  # 끝나지 않은 결정이 고치는 태스크면 워커를 죽이거나 라운드를 닫기 전에 거부한다(_closing 에서 다시 본다)
        _start_gate(p, cfg, spec, check_deps=False)
    plc, forced = dict(crew.TEMP), False
    if member is not None and (queue or defer):
        plc = {"kind": "crew", "crew": member, "mode": "fresh"}  # 띄우지 않는 라운드: start-ready 의 복구가 배정한다
    elif member is not None:
        plc, forced = _crew_fix(p, h, tid, member, first, force=force, from_queue=from_queue)
        if plc is None:
            return crew.enqueue(p, tid, member.name, note=note, supplement=supplement, force_round=force_round,
                                request=request)
    rchoice, ignored = _crew_choice(cfg, spec, cli, plc) if plc["kind"] == "crew" else (choice, None)
    seen: dict = {}
    _close_round(p, h, tid, kill=True, check=allowed, seen=seen, nowait=nowait)
    die_at("fix_closed")  # 테스트: 이전 라운드를 정리한 뒤 새 라운드를 쓰기 전에 죽는다(관제 fix 이어 하기, 설계 8.7)
    with _closing(p, tid, seen) as st:
        _check_locks(p, cfg, spec, owns)
        if not queue or follower:  # 결정 밖의 fix 는 끝나지 않은 결정이 고치는 태스크를 띄우지 않는다(결정 자신의 fix 는 queue 다)
            _start_gate(p, cfg, spec, check_deps=False)
        old = st["status"]
        prior = state.current_round(st) or {}
        coord_note = None
        if not from_user and prior.get("from_user") and prior.get("note") and old != "awaiting_user":
            # 결정이 연 사용자 요청 라운드가 사용자에게 다시 보이지 못한 채 닫힌다(워커 실패, 리뷰 수정 요청 뒤 changes 등).
            # 그 요청을 그대로 잇고 지시는 따로 적는다(워커·리뷰어가 지시를 사용자 요청으로 읽지 않게)
            # 이미 그 라운드에 적힌 지시는 새 지시와 함께 잇는다(같은 지시는 쌓지 않는다)
            kept = (prior["coord_note"].split(" / ") if prior.get("coord_note") else []) + ([note] if note else [])
            coord_note = " / ".join(dict.fromkeys(kept)) if kept else None
            note, from_user = prior["note"], True
        if held_note:  # 앞 지시 → 대기 지시 순서, 같은 줄은 한 번
            coord_note = crew.merged({"note": coord_note}, held_note, None, False)[0]
        if supplement is None and prior.get("supplement") and old != "awaiting_user":
            # 보강 라운드가 다시 승인되지 못한 채 닫힌다(작업 실패, 리뷰 수정 요청 등). 끝나지 않은 보강을 잇는다
            # (수정 블록이 보강 결과를 계속 보이고, 다시 승인된 뒤 그 라운드의 제안을 보강 대상으로 보지 않는다)
            supplement = prior["supplement"]
        st["role"] = spec.role  # 첫 실행과 같이 워커가 뜨는 사양의 직무로 맞춘다. planner 하나 검사가 저장된 직무를 본다
        rd = _new_round(st, st["round"] + 1, gitio.head(workspace.task_root(p, st)), rchoice, note=note,
                        supplement=supplement, coord_note=coord_note)
        _crew_round(rd, plc, ignored, forced)
        if st.get("base_merge"):  # 기준 병합 라운드(설계 5.10.6): 사양의 작업 공간 절이 병합 지시를 받는다
            rd["base_merge"] = st["base_merge"]
            if gitio.merge_head(workspace.task_root(p, st)) == st["base_merge"]:
                rd["merge_resume"] = True  # 앞 워커가 시작한 병합이 슬롯에 남았다
        if from_user:
            rd["from_user"] = True  # 사용자 일괄 승인의 수정 요청(설계 11.4). 수정 블록이 사용자 요청으로 적는다
            # 마지막으로 실제 리뷰된 라운드의 판정(그 뒤 라운드는 띄우지 않았거나 판정 전에 닫혔다). 수정 요청이면 그 지적도
            # 다루게 한다
            rd["prior_verdict"], rd["prior_review_round"] = _last_review(st)
        if queue or defer:
            rd["queued"] = True
        text = compose.work_spec(p, cfg, spec, rd, owns, st)
        st["rounds"].append(rd)
        st["round"] = rd["round"]
        st["owns"] = owns
        st["note"] = note
        st.pop("drive_fix", None)  # 관제 fix 표시는 새 라운드를 쓰는 이 쓰기에서 지운다(설계 8.7)
        st.pop("queued_fix", None)  # 대기열의 수정도 이 라운드가 한다(설계 5.9.5)
        _begin(p, st, rd, text, "fix", previous=old, force_round=force_round, **_req(request))
    crew.unqueue(p, tid)  # 라운드 전이가 확정된 뒤에 큐에서 뺀다(그 사이 멈추면 큐 맞추기가 뺀다)
    fixed, skipped = _queue_followers(p, followers, supplement, tid) if followers else ([], [])
    if queue or defer:  # 띄우지 않는다. start-ready 의 의존 검사가 선행이 다시 승인된 뒤에 띄운다(설계 11.4)
        return {"task": tid, "round": rd["round"], "status": "launch_failed", "queued": True, "followers": fixed,
                "warnings": skipped, "next": [SHIM, "start-ready"],
                "hint": "수정 라운드를 만들었다. start-ready 가 선행이 끝난(승인 직무는 awaiting_user) 뒤에 띄운다"}
    res = run_work(p, cfg, h, tid, plc)
    if followers:
        res["followers"] = fixed
    if skipped:
        res["warnings"] = [*(res.get("warnings") or []), *skipped]
    return res


def _supplement_followers(p, cfg, tid: str, sup: str) -> list[dict]:
    """`fix --supplement` 가 고치는 태스크 tid 에 직간접으로 의존하는 승인 직무 태스크 가운데 보강 라운드를 대기로 만들 것
    (일괄 승인 결정이 의존 태스크를 함께 고치는 것과 같다, 설계 11.4). 선행이 새 라운드를 열면 이 태스크들은 옛 선행을 보고 만든
    것이라 그대로 두면 approval_stale 이 된다. 아직 시작하지 않은(pending)·끝난 태스크와 이미 그 보강의 대기 라운드가 있는
    태스크는 건너뛴다(중복 없음). 끝나지 않은 결정이 고치는 태스크는 아무것도 바꾸기 전에 exit 3 으로 거부한다. 진행 중이거나
    리뷰 중인 태스크는 결정처럼 다시 만든다(옛 선행을 보고 만들었다)."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    graph = approval.Graph(p)
    found = []
    for other in sorted(set(specs.list_ids(p)) | {s["id"] for s in state.all_states(p)}, key=state.id_number):
        if other == tid or tid not in graph.ancestors(other) or not cfg.is_approval(graph.role(other)):
            continue
        st = state.load(p, other)
        if st is None or st["status"] == "pending" or st["status"] in state.CLOSED:
            continue
        rd = state.current_round(st) or {}
        if rd.get("supplement") == sup and approval.unlaunched(st):
            continue  # 이미 이 보강의 대기 라운드가 있다
        held = approval.held_by_decision(p, other)
        if held:
            raise approval._decision_pending({"id": held})
        found.append({"task": other, "round": st["round"]})
    return found


def _reuse_queued(p, cfg, spec, tid: str, sup: str, note: str | None, expect_round: int | None, choice, cli: dict) -> dict | None:
    """tid 에 아직 띄우지 않은 같은 보강(sup)의 대기 라운드가 있으면(선행의 `fix --supplement` 가 만들었다) 새 라운드를 만들지
    않고 그 라운드에 메모만 더한다(라운드 수 그대로, max_rounds 를 쓰지 않는다). 없으면 None. 프로젝트 잠금 → 태스크 잠금
    아래에서 다시 확인하고, 끝나지 않은 결정이 고치는 태스크면 exit 3 으로 아무것도 바꾸지 않는다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    with state.project_lock(p):
        with state.edit(p, tid) as st:
            rd = state.current_round(st) or {}
            if not (approval.unlaunched(st) and rd.get("supplement") == sup):
                return None
            if rd["work"].get("canceled"):  # 앞선 fix·drop 이 취소를 기록한 채 끊겼다. 재사용하면 시작이 launch_canceled 로 실패한다
                return None
            if cli.get("worker") and choice.worker != rd.get("agent"):  # 다른 워커 에이전트는 새 라운드로 만든다
                return None
            _start_gate(p, cfg, spec, check_deps=False)
            _expect_round(tid, st, expect_round)
            if cli.get("model"):  # 명시한 모델·effort 는 대기 라운드에 반영한다(안 주면 그대로)
                rd["model"] = choice.model
            if cli.get("effort"):
                rd["effort"] = choice.effort
            if note:
                key = "coord_note" if rd.get("from_user") else "note"
                parts = (rd.get(key) or "").split(" / ") + [note]
                rd[key] = " / ".join(dict.fromkeys(x for x in parts if x))
                if key == "note":
                    st["note"] = rd[key]
            write_atomic(_spec_file(p, tid, rd["round"]), compose.work_spec(p, cfg, spec, rd, st.get("owns") or checked_owns(cfg, spec), st))
            return {"task": tid, "round": rd["round"], "status": st["status"], "queued": True, "reused": True,
                    "next": [SHIM, "start-ready"],
                    "hint": "같은 보강의 대기 라운드에 메모를 더했다(새 라운드 없음). start-ready 가 선행이 다시 승인된 뒤 띄운다"}


def _queue_followers(p, followers: list[dict], sup: str, tid: str) -> tuple[list[dict], list[str]]:
    """_supplement_followers 가 고른 태스크마다 보강 라운드를 대기(queued)로 만든다. 선행 tid 의 새 라운드가 다시 승인되면
    start-ready 가 띄우고 그때 basis 가 선행의 새 라운드를 적는다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    note = f"선행 {tid} 가 디렉터 보강 {sup} 를 반영해 고쳐졌다. 이 화면도 그 결과를 반영한다"
    done: list[dict] = []
    skipped: list[str] = []
    for f in followers:
        try:
            # follower: 결정 소유자가 아니다. 끝나지 않은 결정이 고치는 태스크는 잠금 안에서 다시 보고 바꾸지 않는다
            res = fix(p, f["task"], note=note, supplement=sup, force_round=True, cli={}, expect_round=f["round"], queue=True,
                      extra_from=approval.DEPENDENT_FROM, follower=True)
        except HteamError as exc:
            if exc.code == "decision_pending":  # 그 태스크는 결정이 고친다(사용자 요청을 지킨다)
                skipped.append(f"{f['task']} 는 끝나지 않은 일괄 승인 결정 {(exc.data or {}).get('pending')} 이 고치므로 보강 "
                               "대기 라운드를 만들지 않았다(결정이 고친 뒤 그 화면의 보강은 fix --supplement 로 따로 한다)")
                continue
            if exc.code not in ("round_changed", "task_closed"):
                raise
            continue
        done.append({"task": f["task"], "round": res["round"]})
    return done, skipped


def _check_supplement(p, sup: str) -> None:
    """--supplement 는 끝난(done) 디렉터 보강 태스크만 받는다(설계 11.4: 보강이 끝나면 제안한 화면을 고친다)."""
    state.check_id(sup)
    if not p.spec_path(sup).is_file():
        raise HteamError("unknown_task", f"--supplement {sup} 사양이 없다", USAGE)
    role = specs.load(p, sup).role
    if role != "director":
        raise HteamError("bad_supplement", f"--supplement {sup} 는 {role} 태스크다(디렉터 보강 태스크만 준다)", USAGE)
    st = state.load(p, sup)
    if st is not None and st["status"] == "dropped":
        raise HteamError("supplement_not_done", f"보강 태스크 {sup} 는 버려졌다(dropped). 끝난 보강 태스크만 받는다", CONFLICT,
                         "새 보강 태스크를 만들어 done 이 된 뒤 fix --supplement 한다")
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
                         "의존 태스크다", CONFLICT, f"관제가 재확인마다 결정 {held} 을 기록대로 마저 한다. 그 뒤 start-ready",
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


def _live_error(tid: str, slot: dict, row: dict) -> HteamError:
    """살아 있는 워커 때문에 accept 하지 않는다. 큐 결과로 메인에 가므로 힌트에 horch 명령을 넣지 않는다(메인은 horch 를
    부르지 않는다, 설계 7.1·9.4)."""
    did = row["id"]
    if row["state"] == "launching":
        return HteamError("launching", f"{tid} 의 Dispatch {did}({slot['title']})가 아직 launching 이다", CONFLICT,
                          "끝난 뒤 다시 한다", data={"dispatch": did})
    return HteamError("worker_active", f"{tid} 의 Dispatch {did}({slot['title']})가 아직 active 다. 살아 있는 워커가 "
                      "파일을 고칠 수 있어 owns 잠금을 풀지 않는다", CONFLICT,
                      "사용자에게 그 워커 탭을 확인해 달라고 한다(살아 있는 워커가 끝나야 accept 한다). 태스크를 버리려면 "
                      f"{SHIM} drop {tid} --force", data={"dispatch": did})


def _held_for_accept(p, tid: str, decision: str | None) -> None:
    """끝나지 않은 일괄 승인 결정이 고치는 태스크(또는 그 의존 태스크)는 손으로 accept 하지 않는다. 사용자 수정 요청이
    결정을 다시 할 때 round_changed 로 조용히 사라진다(설계 11.4). decision 은 그 결정 자신의 accept 항목(_apply)이다."""
    from . import approval  # approval 이 tasks 를 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    held = approval.held_by_decision(p, tid)
    if held and held != decision:
        raise HteamError("decision_pending", f"{tid} 는 끝나지 않은 일괄 승인 결정 {held} 이 고치는 태스크이거나 그 "
                         "의존 태스크다", CONFLICT, f"관제가 재확인마다 결정 {held} 을 기록대로 마저 한다",
                         data={"pending": held})


def accept(p, tid: str, expect_round: int | None = None, decision: str | None = None, request: str | None = None,
           nowait: bool = False) -> dict:
    """approved → done(승인 직무면 awaiting_user), awaiting_user → done(설계 6.4). 작업 Dispatch 를 release 한다
    (같은 horch Task 의 이전 시도도).

    태스크의 작업·리뷰 Dispatch 가 하나라도 launching·active 면(review 는 retain 실패를 견디므로 approved 에도 작업
    워커가 살아 있을 수 있다) 아무것도 바꾸지 않고 exit 3 이다. 닫으면 owns 잠금이 풀리고 fix·drop 도 task_closed 라
    그 워커를 정리할 길이 없다. worker-list 를 묻지 못하면 확인할 수 없으므로 역시 바꾸지 않는다. 끝난 Dispatch 의
    release 실패는 Dispatch 마다 경고로 남기고 cleaned 는 쓰지 않는다. 전이는 한다.

    nowait(관제 안)면 무엇보다 먼저 finish 잠금을 탐침한다(리뷰 관문이 돌면 아무것도 바꾸지 않고 review_busy, 설계 8.5).
    잠금 순서상 finish 잠금을 쥔 채 프로젝트 잠금을 잡지 않으므로 탐침만 한다. request 는 accept 사건에 남긴다.

    작업 공간 태스크(설계 5.10.6, 6.4 의 7단계 줄)는 프로젝트 잠금 안에서 상태를 쓰기 전에 기준 브랜치에 병합한다
    (workspace.merge, 관제 판정·큐·관제 안의 CLI accept 가 모두 이 한 곳을 지난다). 병합하면 같은 쓰기에서 workspace.merge·
    done(결과의 merge), 충돌이면 changes·라운드의 merge_conflict·base_merge·base 이동(결과의 merge_conflict). 병합 거부
    (merge_pending·merge_blocked·base_moved)는 상태·라운드를 바꾸지 않고 첫 거부 시각 merge_wait 만 남긴 뒤 그대로 올린다
    (exit 3, data 의 first 는 이번이 첫 거부인지)."""
    if nowait:
        state.finish_probe(p, tid)
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
                raise _live_error(tid, slot, row)
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
    outcome = None
    with state.project_lock(p):  # 선행의 새 라운드(fix 가 같은 잠금 안에서 쓴다)와 겹치지 않게 이 안에서 다시 본다
        _held_for_accept(p, tid, decision)  # 결정 기록도 같은 잠금 안에서 쓴다
        if st["status"] == "awaiting_user" and cfg.is_approval(st["role"]):
            _refuse_stale(p, cfg, tid)
        now_st = state.require(p, tid)
        ws = now_st.get("workspace")
        if (now_st["status"], now_st["round"]) == (st["status"], st["round"]) and ws and not ws.get("merge"):
            outcome = _merge(p, cfg, now_st)  # 다르면 아래 쓰기가 거부한다(병합하지 않는다)
        with state.edit(p, tid, expect={st["status"]}) as cur:
            if cur["round"] != st["round"]:  # 멈춘 사이 다음 라운드가 같은 상태에 닿았다. 본 적 없는 라운드를 닫지 않는다
                raise _changed(tid, st, cur)
            work_slot(cur)["cleaned"] = cleaned
            cur.pop("queued_fix", None)  # 대기열의 수정은 하지 않는다(설계 5.9.5)
            cur.pop("merge_wait", None)
            if outcome and outcome["result"] == "conflict":
                conflict = {"base": outcome["base"], "files": outcome["files"]}
                cur["rounds"][-1]["merge_conflict"] = conflict
                cur["base_merge"] = cur["base"] = outcome["base"]  # 기준 병합 라운드가 풀 기준, 리뷰 대상의 새 기준
                to = "changes"
                state.move(cur, to, "merge_conflict", **conflict, **_req(request))
            else:
                if outcome:
                    cur["workspace"]["merge"] = outcome["sha"]
                state.move(cur, to, "accept", **({"merge": outcome["sha"]} if outcome else {}), **_req(request))
    if outcome and outcome["result"] == "merged":  # 설계 8.12: 병합 노트(workspace.merge 를 쓴 뒤)
        redmine.merged(p, cfg, state.require(p, tid))
    crew.unqueue(p, tid)
    out = {"task": tid, "status": to, "warnings": warnings}
    if outcome and outcome["result"] == "merged":
        out["merge"] = outcome["sha"]
    elif outcome:
        out["merge_conflict"] = {"base": outcome["base"], "files": outcome["files"]}
    if to == "awaiting_user":  # 승인 직무: 다른 승인 태스크와 묶어 사용자에게 묻는다(설계 11.4)
        out["next"] = [SHIM, "design-review"]
        out["hint"] = (f"`{SHIM} start-ready` 뒤 `{SHIM} design-review`. exit 3 approval_not_ready 면 다른 승인 직무 "
                       "태스크를 accept 한 뒤 다시 부른다")
    return out


def _merge(p, cfg, st: dict) -> dict:
    """accept 의 병합(workspace.merge). 거부면 태스크 잠금 안에서 merge_wait 가 없을 때만 첫 거부 시각을 쓰고(상태·라운드는
    그대로) data 의 first 에 이번에 썼는지를 더해 그대로 올린다(관제가 10분 거부를 잰다, 설계 5.10.6)."""
    try:
        return workspace.merge(p, cfg, st)
    except HteamError as exc:
        if exc.code not in workspace.MERGE_REFUSED:
            raise
        with state.edit(p, st["id"]) as cur:
            first = "merge_wait" not in cur
            cur.setdefault("merge_wait", {"since": now(), "asked": []})
        exc.data["first"] = first
        raise


DROP_HINT = ("이전 세션을 닫지 못했다. 사용자에게 그 에이전트 탭의 작업 pane 을 닫아 달라고 한다. 닫지 않으면 이전 세션이 지금 "
             "풀린 소유 경로를 계속 고칠 수 있다")


def _drop_session(p, h, tid: str, st: dict, force: bool) -> str | None:
    """drop 의 고정 에이전트 세션(설계 5.9.6). 대상 확인(맡은 태스크·지금 작업 Dispatch)을 통과했을 때만: 쉬는 세션이면
    Dispatch 만 버리고 세션은 둔다(--force 와 상관없다). --force 이고 일하는 중이면 세션을 닫고 잊는다. 닫지 못하면 그 세션에
    다음 태스크를 넣지 않게 터미널을 잊고 Dispatch 를 버려 보고 hint 를 돌려준다. --force 없이 일하는 세션이면 _close_round 가
    worker_active 로 거부한다."""
    rd = state.current_round(st) or {}
    name = crew.round_crew(rd)
    did = rd["work"].get("dispatch") if rd else None
    if not name or not did:
        return None
    e = crew.entry(p, name)
    if e["task"] != tid or e["dispatch"] != did:
        return None
    verdict, info = crew.probe(e["terminal"], e["terminal_argv"]) if e["terminal"] else ("gone", None)
    word = crew.word(info) if verdict == "live" else None
    if word in crew.READY:
        _keep_abandon(h, did)
    elif force and word in ("working", "blocked"):
        try:
            crew.close_session(p, name, tid)
        except HteamError:
            crew.detach(p, name)
            try:
                _keep_abandon(h, did)
            except HteamError:
                pass  # 정리는 _close_round 가 다시 본다
            return DROP_HINT
    return None


def drop(p, tid: str, force: bool, expect_round: int | None = None, request: str | None = None,
         nowait: bool = False) -> dict:
    """dropped 로(설계 6.4). 끝나지 않은 실행 키와 리뷰 시도는 canceled. active 는 --force 로만 abandon --kill 뒤
    release. 모든 대상의 정리를 확인한 뒤, 취소 때 본 상태·라운드 그대로일 때만 dropped 를 쓴다(pending 이면 그 사이
    start 가 라운드를 쓰지 않았을 때만). expect_round 는 큐 요청이 본 라운드(바뀌었으면 round_changed, 설계 7.1),
    nowait(관제 안)면 finish 잠금을 기다리지 않는다(설계 8.5). request 는 drop 사건에 남긴다. 고정 에이전트 세션은
    _drop_session, 끝나면 queued_fix 를 지우고 큐에서 빼고 그 에이전트를 비운다(5.9.5·5.9.6)."""
    h = Horch(p.horch_home)
    st = state.require(p, tid)
    _expect_round(tid, st, expect_round)  # 상태보다 먼저: 다른 라운드로 옮겨 갔으면 그 요청은 이미 처리된 것이다
    if st["status"] in state.CLOSED:
        raise state.closed_error(st)
    hint = _drop_session(p, h, tid, st, force)
    seen: dict = {}
    released = _close_round(p, h, tid, kill=force, check=lambda cur: _expect_round(tid, cur, expect_round), seen=seen,
                            nowait=nowait)
    with _closing(p, tid, seen) as cur:
        # 준비가 끝나지 않은(ready 없는) 예약은 바로 푼다(준비 자식을 기다리지 않는다. 늦게 끝난 자식은 예약을 다시 보고 쓰지
        # 않는다). busy·준비를 마친 예약은 관제의 놓기(teardown 포함)가 푼다(설계 5.10.6·5.10.9). 읽지 못하면 bad_slots_file
        data = workspace.load(p)
        n = workspace.held_by(data, tid)
        rec = workspace.entry(data, n) if n is not None else None
        cur.pop("queued_fix", None)
        state.move(cur, "dropped", "drop", force=force, **_req(request))
        if rec is not None and rec["state"] == "preparing" and not rec.get("ready"):
            data["slots"][str(n)] = {**workspace.SLOT_DEFAULT, "setup_done": rec["setup_done"], "since": now()}
            workspace.save(p, data)  # 프로젝트 잠금 안(_closing)
    crew.unqueue(p, tid)
    crew.free(p, tid)
    try:  # drop 은 설정 없이 끝난다(설계 4장): 설정을 읽지 못하면 Redmine 노트만 건너뛴다(리뷰 J3)
        cfg = config.load(p)
    except HteamError:
        cfg = None
    if cfg is not None:
        redmine.dropped(p, cfg, cur)  # 설계 8.12: drop 노트(상태를 바꾸지 않는다)
    out = {"task": tid, "status": "dropped", "released": released}
    if hint:
        out["hint"] = hint
    return out


def _check_body(body: str) -> None:
    if not body or not body.strip():
        raise HteamError("usage", "범위 내용이 비었다", USAGE)


def _not_working(tid: str, status: str) -> HteamError:
    return HteamError("not_working", f"{tid}: 일하는 중(working)인 태스크에만 범위를 더한다(status={status}). 시작 전이면 "
                      "사양을 고쳐 커밋한다", CONFLICT, data={"status": status})


def scope(p, tid: str, body: str, *, expect_round: int | None = None, request: str | None = None,
          target: str | None = None, remember=None) -> dict:
    """일하는 중인 태스크의 작업 Dispatch 에 범위를 더한다(설계 7.1 `hteam scope`). `horch send --subject 추가 범위` 를
    요청 id 를 key 로 한 번만 보낸 뒤 history 에 scope 사건을 남긴다(상태 전이가 아니다).

    target 이 있으면(같은 요청을 다시 실행) 지금 상태를 보기 전에 그 Dispatch 로 같은 key 를 보낸다: horch 는 key 를 먼저
    찾으므로 이미 간 전송이면 Dispatch 상태와 상관없이 duplicate 다. 없으면 라운드(expect_round)·working·작업 Dispatch 를
    보고 remember(Dispatch) 로 요청 파일에 먼저 남긴 뒤 보낸다."""
    _check_body(body)
    h = Horch(p.horch_home)

    def send(did: str) -> None:
        args = ["send", "--to", f"dispatch:{did}", "--subject", "추가 범위"]
        if request:
            args += ["--key", request]
        code, data = h.call(*args, f"--body={body}")
        if code == 0 and data.get("ok"):
            return
        if (data.get("error") or {}).get("code") == "dispatch_not_active":
            raise _not_working(tid, state.require(p, tid)["status"])
        raise failure(code, data, tuple(args))

    if target:
        send(target)
    else:
        st = state.require(p, tid)
        _expect_round(tid, st, expect_round)
        did = (state.current_round(st) or {}).get("work", {}).get("dispatch")
        if st["status"] != "working" or not did:
            raise _not_working(tid, st["status"])
        if remember is not None:
            remember(did)
        send(did)
    die_at("scope_sent")
    with state.edit(p, tid) as st:
        if not (request and any(isinstance(e, dict) and e.get("event") == "scope" and e.get("request") == request
                                for e in st["history"])):
            st["history"].append({"at": now(), "event": "scope", "round": st["round"], "body": body, "request": request})
    return {"id": tid, "sent": True}


def _cli(args) -> dict:
    return {k: getattr(args, k) for k in ("model", "effort", "worker") if getattr(args, k, None)}


def _round(p, tid: str, given: int | None = None):
    """큐 요청의 expect_round(설계 7.1): --round N 이 있으면 N, 없으면 메인이 본 상태 파일의 라운드."""
    return lambda: given if given is not None else state.require(p, tid)["round"]


def _cmd_start(args) -> dict:
    p = find_project(args.root)
    cli = _cli(args)
    return queue.route(p, "start", {"task": args.task, **cli}, lambda req: start_command(p, args.task, cli),
                       check=lambda: specs.check(p, config.load(p), args.task))


def _cmd_start_ready(args) -> dict:
    p = find_project(args.root)
    return queue.route(p, "start-ready", {}, lambda req: start_ready(p), check=lambda: config.load(p))


def _cmd_fix(args) -> dict:
    p = find_project(args.root)
    cli = _cli(args)

    def check() -> None:
        specs.check(p, config.load(p), args.task)
        state.require(p, args.task)

    given = {"note": args.note, "supplement": args.supplement, "force_round": args.force_round or None,
             "force": args.force or None}
    return queue.route(p, "fix", {"task": args.task, **{k: v for k, v in given.items() if v is not None}, **cli},
                       lambda req: fix(p, args.task, note=args.note, supplement=args.supplement,
                                       force_round=args.force_round, cli=cli, expect_round=args.expect_round,
                                       nowait=True, force=args.force),
                       check=check, expect_round=_round(p, args.task, args.expect_round))


def _cmd_accept(args) -> dict:
    p = find_project(args.root)
    return queue.route(p, "accept", {"task": args.task}, lambda req: accept(p, args.task, args.expect_round, nowait=True),
                       check=lambda: state.require(p, args.task), expect_round=_round(p, args.task, args.expect_round))


def _cmd_drop(args) -> dict:
    p = find_project(args.root)
    return queue.route(p, "drop", {"task": args.task, **({"force": True} if args.force else {})},
                       lambda req: drop(p, args.task, args.force, nowait=True),
                       check=lambda: state.require(p, args.task), expect_round=_round(p, args.task))


def _cmd_scope(args) -> dict:
    p = find_project(args.root)

    def check() -> None:
        _check_body(args.body)
        state.require(p, args.task)

    return queue.route(p, "scope", {"task": args.task, "body": args.body}, lambda req: scope(p, args.task, args.body),
                       check=check, expect_round=_round(p, args.task))


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
    s.add_argument("--force", action="store_true", help="고정 에이전트의 일하는 세션을 닫고 새 세션으로(설계 5.9.6)")
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
    s = sub.add_parser("scope")
    s.add_argument("task")
    s.add_argument("body", help="더할 범위(일하는 중인 태스크만, 설계 7.1)")
    s.set_defaults(func=_cmd_scope)
