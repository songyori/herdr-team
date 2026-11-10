"""고정 터미널(설계 13장, 0.2.0): 터미널 확인, 리셋 예약 읽기, --terminal 로 같은 터미널에 새 Dispatch 넣기,
보내기 표시 뒤 실행자가 죽은 Dispatch 정리, 닫기(terminal-close), 세션 비우기(terminal-reset)."""
from __future__ import annotations

import json
import re
import sqlite3
import time

from . import hcio, liveness, preamble, procs, workers
from .errors import CONFLICT, FAIL, TIMEOUT, USAGE, HorchError
from .ids import new_id, now
from .paths import horch_cmd
from .store import write_atomic

RESET_PREFIX = "reset:"  # meta 의 터미널 예약 key 접두사. 값은 <pid>|<시작 시각>|<at>|<종류 reset·close>(설계 13.8 의 3, 13.5)
NOT_STARTED_S = 60  # 넣은 입력이 이만큼(초) 시작되지 않으면 observed not_started(설계 13.6)
GET_TIMEOUT_S = 5.0  # 터미널 확인의 hc get(설계 13.4 의 2)
READY = ("idle", "done")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")  # terminal-reset --name(Codex 대화 이름, 설계 13.8 의 2)
CLEAR_KEYS = ["/", "c", "l", "e", "a", "r"]  # 감싼 send 는 슬래시 명령을 실행하지 않으므로 키로 친다(설계 13.1)
RESET_POLL_S = 0.2  # 비우기 대체 신호 hc get 폴링 간격(설계 13.8 의 6)
POLL_GET_TIMEOUT_S = 3.0  # 폴링 hc get 한 번의 시간. 남은 시간으로 줄이지 않는다(설계 13.11)


def _dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def reservation(store, terminal: str) -> dict | None:
    """살아 있는 프로세스의 터미널 예약(terminal-reset 또는 terminal-close). 값이 없거나 해석할 수 없거나 그 프로세스가
    죽었으면 None. 종류가 없는 값은 reset 이다."""
    row = store.one("SELECT value FROM meta WHERE key=?", (RESET_PREFIX + terminal,))
    if not row:
        return None
    parts = row["value"].split("|", 3)
    if len(parts) < 3 or not parts[0].isdigit():
        return None
    pid = int(parts[0])
    if not procs.alive(pid, parts[1]):
        return None
    return {"pid": pid, "started": parts[1], "at": parts[2], "kind": parts[3] if len(parts) > 3 else "reset"}


def _reserve(store, terminal: str, kind: str, *, running_ok: bool = False) -> tuple[str, str]:
    """BEGIN IMMEDIATE 에서 진행 중 Dispatch 와 살아 있는 다른 예약을 다시 본 뒤 터미널 예약을 쓴다(설계 13.8 의 3, 13.5).
    --terminal 넣기는 같은 트랜잭션 꼴로 예약을 보므로 서로 배제된다. running_ok 면 진행 중 Dispatch 가 있어도 잡는다
    (terminal-close --abandon). 죽은 프로세스의 옛 값은 덮어쓴다. 반환 (key, value) 는 _release 로 지운다."""
    pid, started = procs.me()
    key, value = RESET_PREFIX + terminal, f"{pid}|{started}|{now()}|{kind}"
    with store.tx():
        running = _running_on(store, terminal)
        if running and not running_ok:
            raise _busy(terminal, running)
        held = reservation(store, terminal)
        if held:
            raise _busy(terminal, None, held["kind"])
        store.run("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))
    return key, value


def _release(store, key: str, value: str) -> None:
    """자기 예약일 때만 지운다(조건부 쓰기)."""
    with store.tx():
        store.run("DELETE FROM meta WHERE key=? AND value=?", (key, value))


def last_persistent(store, run_id: str, terminal: str) -> sqlite3.Row | None:
    """그 Run·터미널의 가장 최근 고정 Dispatch. 다시 넣는 Dispatch 는 이 값(에이전트·argv·cwd)을 옮긴다."""
    return store.one("SELECT * FROM dispatches WHERE run_id=? AND terminal=? AND persistent=1 "
                     "ORDER BY created_at DESC, rowid DESC LIMIT 1", (run_id, terminal))


def _gone(terminal: str, verdict: str) -> HorchError:
    return HorchError("terminal_gone", f"고정 터미널 {terminal} 이 없거나 끝났거나 다른 프로그램이다({verdict})", CONFLICT,
                      data={"verdict": verdict})


def _busy(terminal: str, dispatch_id: str | None, kind: str = "reset") -> HorchError:
    """kind 는 dispatch_id 가 없을 때 그 터미널을 잡은 예약의 종류(reset·close)."""
    if dispatch_id:
        message = f"고정 터미널 {terminal} 에 진행 중인 Dispatch {dispatch_id} 가 있다"
    elif kind == "close":
        message = f"고정 터미널 {terminal} 을 닫는 중이다(terminal-close)"
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
    held = reservation(store, terminal)
    if held:
        raise _busy(terminal, None, held["kind"])
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
            held = reservation(store, terminal)
            if held:
                raise _busy(terminal, None, held["kind"])
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
        cur = store.run("UPDATE dispatches SET delivery=?, state='active' WHERE id=? AND state='launching'",
                        (_dumps(result), dispatch_id))
        if not cur.rowcount:
            # 워커가 먼저 와서 active 로 넘겼다(auth.worker_dispatch). 결과만 쓴다
            store.run("UPDATE dispatches SET delivery=? WHERE id=? AND state='active'", (_dumps(result), dispatch_id))
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


def close(store, run_id: str, terminal: str, abandon: bool) -> dict:
    """terminal-close(설계 13.5): 이 Run 의 고정 터미널을 끄고 지운 뒤 그 터미널의 끝나지 않은 고정 Dispatch 를 정리한다.
    kill 전에 터미널 예약(종류 close)을 잡아 끝날 때까지 쥔다: 그동안 --terminal 넣기·terminal-reset 은 terminal_busy 다
    (Codex 커밋 리뷰 c6d82d2). kill·rm 이 실패하면 상태를 바꾸지 않는다. 다시 부르면 이어 한다(끝난 터미널은 rm 만,
    이미 없으면 기록만)."""
    try:
        info = hcio.get(terminal, timeout=GET_TIMEOUT_S)
    except hcio.HcFailure as exc:
        if exc.kind != "not_found":
            raise HorchError("hc_failed", f"hc get {terminal} 실패: {exc.kind}", FAIL) from exc
        return _close_records(store, run_id, terminal, False)  # 이미 닫혔다. 기록만 정리한다
    labels = info.get("labels") or {}
    if labels.get("horch.run") != run_id or labels.get("horch.persistent") != "1":
        raise HorchError("not_persistent_terminal", f"{terminal} 은 이 Run 의 고정 터미널이 아니다", CONFLICT)
    key, value = _reserve(store, terminal, "close", running_ok=abandon)
    try:
        if info.get("state") == "live":
            workers._kill_ok(terminal)
        workers._rm_ok(terminal)
        return _close_records(store, run_id, terminal, True)
    finally:
        _release(store, key, value)


def _close_records(store, run_id: str, terminal: str, closed: bool) -> dict:
    """한 트랜잭션에서 진행 중 고정 Dispatch 를 abandoned, 이어서 settled·retained·abandoned 를 released 로 쓴다."""
    ts = now()
    mine = "run_id=? AND terminal=? AND persistent=1"
    with store.tx():
        ongoing = store.one(f"SELECT id FROM dispatches WHERE {mine} AND state IN ('launching','active') LIMIT 1",
                            (run_id, terminal))
        store.run(f"UPDATE dispatches SET state='abandoned' WHERE {mine} AND state IN ('launching','active')",
                  (run_id, terminal))
        # 방금 abandoned 로 쓴 것도 released 에 든다(터미널이 없으니 남길 것이 없다)
        released = [r["id"] for r in store.all(f"SELECT id FROM dispatches WHERE {mine} "
                                               "AND state IN ('settled','retained','abandoned') ORDER BY created_at, rowid",
                                               (run_id, terminal))]
        store.run(f"UPDATE dispatches SET state='released', closed_at=? WHERE {mine} "
                  "AND state IN ('settled','retained','abandoned')", (ts, run_id, terminal))
    abandoned = ongoing["id"] if ongoing else None
    if not closed:
        return {"terminal": terminal, "closed": False, "reason": "not_found", "abandoned": abandoned, "released": released}
    return {"terminal": terminal, "closed": True, "abandoned": abandoned, "released": released}


def _seen(info: dict) -> dict:
    return {"status": liveness.status_word(info), "turn": info.get("turn"), "title": info.get("title", "")}


def _cleared(status, turn, turn_before: int) -> bool:
    """비웠다는 신호: turn 이 오르고 idle 이다(설계 13.8 의 6). /clear 뒤에는 Claude·Codex 모두 idle 이고 보통 턴은 done 으로
    끝난다. done 을 받으면 보통 글로 처리된 /clear 를 비운 것으로 본다(X2·X3b)."""
    return status == "idle" and isinstance(turn, int) and turn > turn_before


def reset(store, run_id: str, terminal: str, name: str | None, timeout_ms: int) -> dict:
    """terminal-reset(설계 13.8): 터미널 예약 → events 구독 → hc keys 로 /clear → turn 신호(사건, 없으면 hc get 폴링) 대기.
    예약은 끝날 때(성공·실패·시간 초과·예외) 자기 값일 때만 지운다."""
    if name is not None and not NAME_RE.fullmatch(name):
        raise HorchError("usage", "--name 은 소문자로 시작하는 소문자·숫자·- 1–32자다", USAGE)
    _, prev = inspect(store, run_id, terminal)
    agent = prev["agent"]
    warnings: list[str] = []
    if name is not None and agent != "codex":
        warnings.append("name_ignored")  # Claude 는 띄울 때 준 제목이 /clear 뒤에도 남는다(설계 13.8 의 2)
        name = None
    key, value = _reserve(store, terminal, "reset")
    try:
        return _clear(terminal, agent, name, timeout_ms, warnings)
    finally:
        _release(store, key, value)


def _clear(terminal: str, agent: str, name: str | None, timeout_ms: int, warnings: list[str]) -> dict:
    stream = None
    try:
        try:
            # 구독을 keys 보다 먼저 붙인다. 늦게 붙으면 비운 turn 사건을 놓친다(설계 13.8 의 4)
            stream = hcio.events(terminal)
        except hcio.HcFailure:
            stream = None  # 대체 신호(hc get 폴링)만 쓴다
        try:
            info = hcio.get(terminal, timeout=GET_TIMEOUT_S)
        except hcio.HcFailure as exc:
            raise HorchError("hc_failed", f"hc get {terminal} 실패: {exc.kind}", FAIL) from exc
        turn_before = info.get("turn") or 0
        last = _seen(info)
        names = ["space", *name] if agent == "codex" and name else []
        try:
            hcio.keys(terminal, CLEAR_KEYS + names + ["enter"])
        except hcio.HcFailure as exc:
            raise HorchError("hc_failed", f"hc keys {terminal} 실패: {exc.kind}", FAIL) from exc
        start = time.monotonic()
        deadline = start + timeout_ms / 1000
        last_state = None  # 마지막 status·snapshot 사건의 상태(turn 사건에 상태가 없을 때 쓴다)

        def on_event(event: dict) -> dict | None:
            nonlocal last_state
            word = liveness.status_word(event)
            if event.get("type") != "turn":
                last_state = word or last_state
                return None
            word = word or last_state
            if not _cleared(word, event.get("turn"), turn_before):
                return None
            seconds = time.monotonic() - start
            try:
                title = hcio.get(terminal, timeout=POLL_GET_TIMEOUT_S).get("title", "")
            except hcio.HcFailure:
                title = ""
            return _reset_result(terminal, agent, event["turn"], word, title, seconds, "event", warnings)

        next_poll = start
        while True:
            now_m = time.monotonic()
            if now_m >= deadline:
                break
            if stream is not None and not stream.closed and now_m < next_poll:
                event = stream.read(min(next_poll, deadline) - now_m)
                done = on_event(event) if event is not None else None
                if done:
                    return done
                continue
            if now_m < next_poll:
                time.sleep(min(next_poll, deadline) - now_m)
                continue
            try:
                info = hcio.get(terminal, timeout=POLL_GET_TIMEOUT_S)
            except hcio.HcFailure:
                info = None
            if info is not None:
                last = _seen(info)
                if _cleared(last["status"], last["turn"], turn_before):
                    return _reset_result(terminal, agent, last["turn"], last["status"], last["title"],
                                         time.monotonic() - start, "poll", warnings)
            next_poll = time.monotonic() + RESET_POLL_S
        # 시간 초과로 정하기 전에 이미 온 사건을 기다리지 않고 다 읽는다. 느린 폴링 hc get 이 마감을 넘기는 동안 온
        # 신호를 놓치지 않는다(Codex 커밋 리뷰 c6d82d2). 마감을 지키는 read 가 아니라 drain 으로 읽는다(2cd720c)
        for event in stream.drain() if stream is not None else []:
            done = on_event(event)
            if done:
                return done
        raise HorchError("reset_timeout", f"고정 터미널 {terminal} 을 비웠다는 신호가 {timeout_ms}ms 안에 오지 않았다", TIMEOUT,
                         "비웠는지 알 수 없다. 터미널을 닫고(terminal-close) 새로 띄운다",
                         data={"turn_before": turn_before, "last": last})
    finally:
        if stream is not None:
            stream.close()


def _reset_result(terminal, agent, turn, status, title, seconds, signal, warnings) -> dict:
    return {"terminal": terminal, "agent": agent, "turn": turn, "status": status, "title": title,
            "seconds": round(float(seconds), 3), "signal": signal, "warnings": warnings}
