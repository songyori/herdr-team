"""고정 터미널(설계 13장, 0.2.0): 터미널 확인, 리셋 예약 읽기, --terminal 로 같은 터미널에 새 Dispatch 넣기,
보내기 표시 뒤 실행자가 죽은 Dispatch 정리."""
from __future__ import annotations

import json
import sqlite3

from . import hcio, liveness, preamble, procs, workers
from .errors import CONFLICT, FAIL, HorchError
from .ids import new_id, now
from .paths import horch_cmd
from .store import write_atomic

RESET_PREFIX = "reset:"  # meta 의 리셋 예약 key 접두사. 값은 <pid>|<시작 시각>|<at>(설계 13.8 의 3)
NOT_STARTED_S = 60  # 넣은 입력이 이만큼(초) 시작되지 않으면 observed not_started(설계 13.6)
GET_TIMEOUT_S = 5.0  # 터미널 확인의 hc get(설계 13.4 의 2)
READY = ("idle", "done")


def _dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def reservation(store, terminal: str) -> dict | None:
    """살아 있는 프로세스의 리셋 예약. 값이 없거나 해석할 수 없거나 그 프로세스가 죽었으면 None."""
    row = store.one("SELECT value FROM meta WHERE key=?", (RESET_PREFIX + terminal,))
    if not row:
        return None
    parts = row["value"].split("|", 2)
    if len(parts) != 3 or not parts[0].isdigit():
        return None
    pid = int(parts[0])
    if not procs.alive(pid, parts[1]):
        return None
    return {"pid": pid, "started": parts[1], "at": parts[2]}


def last_persistent(store, run_id: str, terminal: str) -> sqlite3.Row | None:
    """그 Run·터미널의 가장 최근 고정 Dispatch. 다시 넣는 Dispatch 는 이 값(에이전트·argv·cwd)을 옮긴다."""
    return store.one("SELECT * FROM dispatches WHERE run_id=? AND terminal=? AND persistent=1 "
                     "ORDER BY created_at DESC, rowid DESC LIMIT 1", (run_id, terminal))


def _gone(terminal: str, verdict: str) -> HorchError:
    return HorchError("terminal_gone", f"고정 터미널 {terminal} 이 없거나 끝났거나 다른 프로그램이다({verdict})", CONFLICT,
                      data={"verdict": verdict})


def _busy(terminal: str, dispatch_id: str | None) -> HorchError:
    if dispatch_id:
        message = f"고정 터미널 {terminal} 에 진행 중인 Dispatch {dispatch_id} 가 있다"
    else:
        message = f"고정 터미널 {terminal} 을 비우는 중이다(terminal-reset)"
    return HorchError("terminal_busy", message, CONFLICT, data={"dispatch": dispatch_id})


def _not_ready(terminal: str, status: str | None, turn) -> HorchError:
    return HorchError("terminal_not_ready",
                      f"고정 터미널 {terminal} 의 상태가 {status or '보고 없음'} 다(idle·done 일 때만 넣는다)", CONFLICT,
                      data={"status": status, "turn": turn})


def _running_on(store, terminal: str, own: str | None = None) -> str | None:
    """그 터미널의 진행 중(launching·active) Dispatch. own 은 빼고 본다."""
    row = store.one("SELECT id FROM dispatches WHERE terminal=? AND state IN ('launching','active') AND id IS NOT ? "
                    "LIMIT 1", (terminal, own))
    return row["id"] if row else None


def inspect(store, run_id: str, terminal: str, *, own: str | None = None) -> tuple[dict, sqlite3.Row]:
    """설계 13.4 의 2(own 이 있으면 5)의 표를 차례로 본다. 걸리면 HorchError. 반환 (hc get 정보, 앞 고정 Dispatch)."""
    try:
        info = hcio.get(terminal, timeout=GET_TIMEOUT_S)
    except hcio.HcFailure as exc:
        if exc.kind == "not_found":
            raise _gone(terminal, "not_found") from exc
        raise HorchError("hc_failed", f"hc get {terminal} 실패: {exc.kind}", FAIL) from exc
    prev = last_persistent(store, run_id, terminal)
    verdict = liveness.verdict(info, liveness.expected_argv(prev) if prev else None)
    if verdict in ("exited", "lost"):
        raise _gone(terminal, verdict)
    if verdict != "live":
        raise HorchError("hc_failed", f"고정 터미널 {terminal} 의 상태를 확인할 수 없다({verdict})", FAIL)
    labels = info.get("labels") or {}
    if labels.get("horch.run") != run_id or labels.get("horch.persistent") != "1" or prev is None:
        raise HorchError("not_persistent_terminal", f"{terminal} 은 이 Run 의 고정 터미널이 아니다", CONFLICT)
    running = _running_on(store, terminal, own)
    if running:
        raise _busy(terminal, running)
    if reservation(store, terminal):
        raise _busy(terminal, None)
    status = liveness.status_word(info)
    if status not in READY:
        raise _not_ready(terminal, status, info.get("turn"))
    return info, prev


def start_on(store, run_id: str, terminal: str, *, spec, title, task_id, retry) -> dict:
    """worker-start --terminal(설계 13.4 의 1–8): 이 Run 의 고정 터미널에 새 Task·Dispatch 를 만들어 프리앰블을 넣는다."""
    workers._check_task_args(task_id, spec, title)
    if task_id:
        workers.reconcile_launching(store, run_id)
    _, prev = inspect(store, run_id, terminal)
    pid, started = procs.me()
    given_task = bool(task_id)
    dispatch_id, ts = new_id("dsp"), now()
    try:
        with store.tx():
            # 리셋 예약 확인과 Dispatch 예약이 한 트랜잭션이라 terminal-reset 과 서로 배제된다(설계 13.4 의 3)
            workers._require_owner(store, run_id)
            if reservation(store, terminal):
                raise _busy(terminal, None)
            task_id, attempt, title, spec = workers._task_for(store, run_id, task_id, title, spec, retry, ts)
            # 떠 있는 세션을 그대로 쓰므로 에이전트·모델·effort·인자·cwd·argv 는 앞 고정 Dispatch 의 것이다
            store.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, model, effort, agent_args, cwd, "
                      "terminal, state, persistent, terminal_argv, launcher_pid, launcher_started, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,'launching',1,?,?,?,?)",
                      (dispatch_id, task_id, run_id, attempt, prev["agent"], prev["model"], prev["effort"],
                       prev["agent_args"], prev["cwd"], terminal, prev["terminal_argv"], pid, started, ts))
    except sqlite3.IntegrityError as exc:
        if "dispatches.terminal" in str(exc):  # dispatch_one_per_terminal
            raise _busy(terminal, _running_on(store, terminal)) from exc
        if not (given_task or "dispatches.task_id" in str(exc)):
            raise
        raise HorchError("task_busy", f"Task {task_id} 에 이미 실행 중인 Dispatch 가 있다", CONFLICT) from exc
    workers._die_at("terminal_created")
    base = {"task": task_id, "dispatch": dispatch_id}
    progress = {"attempted": False}  # 보내기 표시를 썼나(그 뒤로는 launch_failed 로 바꾸지 않는다)
    try:
        return _deliver(store, run_id, terminal, base, spec, progress)
    except Exception as exc:
        # 만든 뒤의 어떤 오류든 호출자가 task·dispatch 를 알아야 한다(workers.start 와 같다)
        if not progress["attempted"]:
            try:
                workers._mark_failed(store, dispatch_id)  # 조건부 쓰기
            except Exception:
                pass
        if isinstance(exc, HorchError):
            exc.data = {**base, **exc.data}
            raise
        if progress["attempted"]:
            raise HorchError("record_failed", f"보내기 표시 뒤 오류(들어갔을 수 있다): {type(exc).__name__}: {exc}", FAIL,
                             "dispatch 는 launching 이다. 다음 소유자 명령이 불확실한 active 로 둔다", data=base) from exc
        raise HorchError("launch_failed", f"넣기 준비 중 오류: {type(exc).__name__}: {exc}", FAIL, data=base) from exc


def _deliver(store, run_id: str, terminal: str, base: dict, spec: str, progress: dict) -> dict:
    dispatch_id = base["dispatch"]
    ddir = store.dispatch_dir(run_id, dispatch_id)
    spec_path = ddir / "spec.md"
    write_atomic(spec_path, spec)
    text = preamble.render(task_id=base["task"], dispatch_id=dispatch_id, spec_path=str(spec_path),
                           horch=horch_cmd(store.home), continued=True)
    write_atomic(ddir / "preamble.md", text)
    # 만든 뒤 다시 본다(설계 13.4 의 5). 그 사이 사람이 친 글로 일을 시작했을 수 있다
    info, _ = inspect(store, run_id, terminal, own=dispatch_id)
    status, turn = liveness.status_word(info), info.get("turn")
    before = {"attempted": True, "turn_before": turn, "status_before": status}
    with store.tx():
        cur = store.run("UPDATE dispatches SET start_turn=?, delivery=? WHERE id=? AND state='launching'",
                        (turn, _dumps(before), dispatch_id))
    if not cur.rowcount:
        state = store.one("SELECT state FROM dispatches WHERE id=?", (dispatch_id,))["state"]
        raise HorchError("state_changed", f"그 사이 Dispatch {dispatch_id} 가 {state} 가 됐다", CONFLICT)
    progress["attempted"] = True
    workers._die_at("terminal_attempted")
    if_status = "idle" if status == "idle" else None  # done 은 --if 가 받지 않으므로 조건 없이 보낸다(설계 13.1)
    warnings: list[str] = []
    try:
        res = hcio.send(terminal, text, if_status=if_status, untagged=True)
        result = {**before, "via": "send", "if": if_status, "started": res.get("started"), "status": res.get("status"),
                  "turn": res.get("turn"), "at": now()}
    except hcio.HcFailure as exc:
        error = f"{exc.kind}: {exc.message}"
        if exc.kind == "status_mismatch":
            # 그 사이 상태가 바뀌어 hc 가 아무것도 치지 않았다
            with store.tx():
                store.run("UPDATE dispatches SET delivery=?, state='launch_failed' WHERE id=? AND state='launching'",
                          (_dumps({**before, "typed": False, "error": error}), dispatch_id))
            raise _not_ready(terminal, status, turn) from exc
        # 시간 초과·응답 유실: 들어갔을 수 있다. 들어가지 않았으면 not_started 가 알린다(설계 13.6)
        result = {**before, "uncertain": True, "error": error, "at": now()}
        warnings.append("delivery_uncertain")
    workers._die_at("terminal_sent")
    with store.tx():
        # 보내기 결과와 active 전이를 한 트랜잭션에서 쓴다. 둘 사이에 죽는 틈이 없다(설계 13.4 의 7)
        store.run("UPDATE dispatches SET delivery=?, state='active' WHERE id=? AND state='launching'",
                  (_dumps(result), dispatch_id))
    workers._die_at("terminal_recorded")
    try:
        hcio.label(terminal, {"horch.dispatch": dispatch_id})
    except hcio.HcFailure:
        warnings.append("label_failed")  # 고정 터미널의 정리는 이 라벨에 기대지 않는다(설계 13.5)
    state = store.one("SELECT state FROM dispatches WHERE id=?", (dispatch_id,))["state"]
    return {**base, "terminal": terminal, "state": state, "placement": "same_terminal", "start_turn": turn,
            "delivery": result, "warnings": warnings}


def settle_dead(store, row) -> None:
    """보내기 표시(delivery.attempted) 뒤 실행자가 죽은 launching 고정 Dispatch(설계 13.4 끝). hc 를 보지 않고
    불확실한 active 로 둔다. 들어갔는지는 판정(turn·seen_at·메시지, 아니면 not_started)이 정한다."""
    with store.tx():
        cur = store.one("SELECT state, delivery FROM dispatches WHERE id=?", (row["id"],))
        if cur["state"] != "launching":
            return
        delivery = {**json.loads(cur["delivery"] or "{}"), "uncertain": True, "error": "executor_died"}
        store.run("UPDATE dispatches SET state='active', delivery=? WHERE id=? AND state='launching'",
                  (_dumps(delivery), row["id"]))
