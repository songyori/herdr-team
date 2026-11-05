"""워커 실행(설계 8장), launching 조정과 가드 거부 정리(설계 5장). 목록·정리·sweep."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from . import agents, auth, hcio, liveness, mailbox, preamble, procs
from .errors import CONFLICT, FAIL, MISSING, USAGE, HorchError
from .ids import new_id, now
from .paths import horch_argv, horch_cmd
from .store import write_atomic

STATES = ("launching", "active", "launch_failed", "settled", "retained", "abandoned", "released")
SWEEP_HC_TIMEOUT_S = 5.0  # sweep 안 hc 호출 하나의 최대 시간(hcio 기본 30초 대신)


def _hc_timeout(deadline: float | None) -> float | None:
    """deadline(monotonic) 까지 남은 시간에 맞춘 hc 시간 제한. deadline 이 없으면 None(hcio 기본)."""
    if deadline is None:
        return None
    return max(0.05, min(SWEEP_HC_TIMEOUT_S, deadline - time.monotonic()))


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def reconcile_launching(store, run_id: str) -> list[str]:
    """실행자가 죽은 launching Dispatch 를 launch_failed 로 바꾼다(조건부 쓰기)."""
    changed = []
    for row in store.all("SELECT id, launcher_pid, launcher_started FROM dispatches WHERE run_id=? AND state='launching'",
                         (run_id,)):
        if procs.alive(row["launcher_pid"], row["launcher_started"]):
            continue
        with store.tx():
            cur = store.run("UPDATE dispatches SET state='launch_failed' WHERE id=? AND state='launching'", (row["id"],))
        if cur.rowcount:
            changed.append(row["id"])
    return changed


def cleanup_refused(store, run_id: str, deadline: float | None = None) -> list[str]:
    """가드가 거부해 끝난 터미널을 hc rm 한다. 이름으로 후보를 찾고 라벨(horch.run·horch.dispatch)과 상태를 get 으로 확인한다.
    deadline(monotonic) 이 있으면 그때까지만 hc 를 부르고 남은 후보는 다음에 한다."""
    failed = {r["id"] for r in store.all("SELECT id FROM dispatches WHERE run_id=? AND state='launch_failed'", (run_id,))}
    if not failed or _expired(deadline):
        return []
    try:
        terminals = hcio.ls_all(timeout=_hc_timeout(deadline))
    except hcio.HcFailure:
        return []
    removed = []
    for t in terminals:
        if t.get("name") not in failed or t.get("state") != "finished":
            continue
        if _expired(deadline):
            break
        try:
            info = hcio.get(t["address"], timeout=_hc_timeout(deadline))
            labels = info.get("labels") or {}
            if (info.get("state") == "finished" and labels.get("horch.run") == run_id
                    and labels.get("horch.dispatch") == t["name"]):
                hcio.rm(t["address"], timeout=_hc_timeout(deadline))
                removed.append(t["address"])
        except hcio.HcFailure:
            pass
    return removed


def _create(store, run_id: str, *, spec, title, agent, model, effort, extra, cwd, task_id,
            retry) -> tuple[str, str, str, str]:
    """Task·Dispatch 를 한 트랜잭션에서 만든다. 재시도 허용 검사도 이 안에서 다시 한다."""
    pid, started = procs.me()
    given_task = bool(task_id)
    dispatch_id, ts = new_id("dsp"), now()
    try:
        with store.tx():
            if task_id:
                task = store.one("SELECT * FROM tasks WHERE id=? AND run_id=?", (task_id, run_id))
                if not task:
                    raise HorchError("unknown_task", f"이 Run 에 Task {task_id} 가 없다", USAGE)
                if task["status"] != "open":
                    raise HorchError("task_settled", f"Task {task_id} 는 이미 끝났다. 새 Task 로 만든다", CONFLICT)
                last = store.one("SELECT id, state FROM dispatches WHERE task_id=? ORDER BY attempt DESC LIMIT 1",
                                 (task_id,))
                if last and last["state"] == "launch_failed" and not retry:
                    raise HorchError("retry_required", f"Task {task_id} 의 직전 실행 {last['id']} 이 launch_failed 다",
                                     CONFLICT, "--retry 로 다시 띄운다")
                if last and last["state"] not in ("launch_failed", "abandoned", "released"):
                    raise HorchError("task_busy", f"Task {task_id} 의 최근 Dispatch {last['id']} 가 {last['state']} 다",
                                     CONFLICT)
                attempt = store.one("SELECT COALESCE(MAX(attempt), 0) + 1 AS a FROM dispatches WHERE task_id=?",
                                    (task_id,))["a"]
                title, spec = task["title"], task["spec"]
            else:
                task_id = new_id("task")
                store.run("INSERT INTO tasks(id, run_id, title, spec, status, created_at) VALUES (?,?,?,?,'open',?)",
                          (task_id, run_id, title, spec, ts))
                attempt = 1
            # agent_args: 재시도 안내(worker-list next)가 같은 모델·인자로 다시 띄우도록 남긴다
            store.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, model, effort, agent_args, cwd, "
                      "state, launcher_pid, launcher_started, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?,'launching',?,?,?)",
                      (dispatch_id, task_id, run_id, attempt, agent, model, effort,
                       json.dumps(list(extra), ensure_ascii=False), cwd, pid, started, ts))
    except sqlite3.IntegrityError as exc:
        # 한 Task 에 실행 중 Dispatch 는 하나뿐이라는 부분 유일 인덱스 위반(또는 --task 지정)만 task_busy 다. 나머지는 버그라 그대로 올린다
        if not (given_task or "dispatches.task_id" in str(exc)):
            raise
        raise HorchError("task_busy", f"Task {task_id} 에 이미 실행 중인 Dispatch 가 있다", CONFLICT) from exc
    return task_id, dispatch_id, title, spec


def _die_at(point: str) -> None:
    """테스트 전용: HORCH_TEST_DIE_AT 이 point 면 실행자를 그 자리에서 죽인다(설계 12장 장애 시점 재현)."""
    if os.environ.get("HORCH_TEST_DIE_AT") == point:
        os._exit(137)


def _mark_failed(store, dispatch_id: str) -> str:
    with store.tx():
        store.run("UPDATE dispatches SET state='launch_failed' WHERE id=? AND state='launching'", (dispatch_id,))
    return store.one("SELECT state FROM dispatches WHERE id=?", (dispatch_id,))["state"]


def _record_active(store, dispatch_id: str, address: str) -> None:
    """hc run 이 성공한 뒤 터미널을 기록한다(조건부 launching→active. 가드가 먼저 등록했으면 그대로 둔다)."""
    with store.tx():
        store.run("UPDATE dispatches SET terminal=?, state='active' WHERE id=? AND state='launching'",
                  (address, dispatch_id))


def start(store, run_id: str, *, spec, title, agent, model, effort, cwd, extra, task_id, retry) -> dict:
    exe = agents.executable(agent)
    if task_id and (spec is not None or title is not None):
        raise HorchError("usage", "--task 와 spec·--title 을 같이 줄 수 없다", USAGE)
    if not task_id and (not spec or not title):
        raise HorchError("usage", "--task 가 없으면 spec 과 --title 이 필요하다", USAGE)
    cwd_path = Path(cwd).expanduser().resolve()
    if not cwd_path.is_dir():
        raise HorchError("bad_cwd", f"작업 폴더가 없다: {cwd_path}", USAGE)
    if task_id:
        reconcile_launching(store, run_id)
    task_id, dispatch_id, title, spec = _create(store, run_id, spec=spec, title=title, agent=agent, model=model,
                                                effort=effort, extra=extra, cwd=str(cwd_path), task_id=task_id,
                                                retry=retry)
    _die_at("after_create")
    base = {"task": task_id, "dispatch": dispatch_id}
    progress: dict = {"ran": False, "terminal": None}  # hc run 이 성공했는지(성공 뒤에는 실패로 바꾸지 않는다)
    try:
        return _launch(store, run_id, exe, base, progress, spec=spec, agent=agent, model=model, effort=effort,
                       extra=extra, cwd_path=cwd_path)
    except Exception as exc:
        # 생성 뒤 어떤 오류든 호출자가 task·dispatch 를 알 수 있어야 한다(모르면 --task 없이 재시도해 워커가 중복된다)
        data = {**base, **({"terminal": progress["terminal"]} if progress["terminal"] else {})}
        if isinstance(exc, HorchError):
            exc.data = {**data, **exc.data}
            err = exc
        elif progress["ran"]:
            err = HorchError("record_failed", f"hc run 은 성공했으나 기록 중 오류: {type(exc).__name__}: {exc}", FAIL,
                             "dispatch 는 launching 이다. 가드가 등록했으면 active 로 보인다", data=data)
        else:
            err = HorchError("launch_failed", f"실행 준비 중 오류: {type(exc).__name__}: {exc}", FAIL, data=data)
        if not progress["ran"]:
            try:
                _mark_failed(store, dispatch_id)  # 조건부 쓰기. 늦은 가드는 펜스가 거부한다
            except Exception:
                pass
        if err is exc:
            raise
        raise err from exc


def _best_effort_receipt(path: Path, receipt: dict, warnings: list[str]) -> None:
    try:
        write_atomic(path, json.dumps(receipt, ensure_ascii=False, indent=2))
    except OSError as exc:
        warnings.append(f"receipt.json 을 쓰지 못했다: {exc}")


def _launch(store, run_id, exe, base, progress, *, spec, agent, model, effort, extra, cwd_path) -> dict:
    dispatch_id = base["dispatch"]
    ddir = store.dispatch_dir(run_id, dispatch_id)
    spec_path = ddir / "spec.md"
    write_atomic(spec_path, spec)
    text = preamble.render(task_id=base["task"], dispatch_id=dispatch_id, spec_path=str(spec_path),
                           horch=horch_cmd(store.home))
    write_atomic(ddir / "preamble.md", text)
    if shutil.which(exe) is None:
        _mark_failed(store, dispatch_id)
        raise HorchError("agent_missing", f"{exe} 를 PATH 에서 찾지 못했다", MISSING, data=base)
    agent_argv = agents.build(agent, model=model, effort=effort, extra=list(extra), preamble=text, home=store.home)
    launch_argv = [*horch_argv(store.home), "launch-guard", "--dispatch", dispatch_id, "--", *agent_argv]
    run = store.one("SELECT owner_space, owner_tab FROM runs WHERE id=?", (run_id,))
    labels: dict[str, str] = {}
    placement = "none"
    if run["owner_space"] and run["owner_tab"]:
        labels = {"herdr.space": run["owner_space"], "herdr.tab": run["owner_tab"]}
        placement = "pane"
    labels.update({"horch.run": run_id, "horch.dispatch": dispatch_id})
    with store.tx():
        store.run("UPDATE dispatches SET launch_argv=? WHERE id=?", (json.dumps(launch_argv), dispatch_id))
    receipt = {"dispatch": dispatch_id, "argv": launch_argv, "labels": labels, "cwd": str(cwd_path)}
    warnings: list[str] = []
    address = None
    try:
        result = hcio.run_bg(dispatch_id, str(cwd_path), labels, launch_argv)
        _die_at("after_run")
        address = result.get("address")
        receipt["result"] = result
        if not address:
            raise hcio.HcFailure("bad_output", "hc run 결과에 address 가 없다")
    except (hcio.HcFailure, HorchError) as exc:
        kind = exc.kind if isinstance(exc, hcio.HcFailure) else exc.code
        receipt["error"] = {"kind": kind, "message": str(exc)}
        _best_effort_receipt(ddir / "receipt.json", receipt, warnings)
        if _mark_failed(store, dispatch_id) == "launch_failed":
            code = exc.exit_code if isinstance(exc, HorchError) else FAIL
            raise HorchError("launch_failed", f"hc run 실패: {kind}", code, data=base) from exc
        address = None
    else:
        progress["ran"], progress["terminal"] = True, address
        _best_effort_receipt(ddir / "receipt.json", receipt, warnings)  # 실패해도 hc run 은 이미 성공했다
        _die_at("before_record")
        _record_active(store, dispatch_id, address)
    row = store.one("SELECT state, terminal FROM dispatches WHERE id=?", (dispatch_id,))
    if address is not None and row["state"] == "launch_failed":
        raise HorchError("launch_failed", "실행자가 죽은 것으로 판정돼 launch_failed 가 됐다. 가드가 거부한다", FAIL,
                         data={**base, "terminal": address})
    if address is not None and row["terminal"] != address:
        raise HorchError("terminal_mismatch", f"가드가 등록한 터미널 {row['terminal']} 와 hc 주소 {address} 가 다르다",
                         FAIL, data=base)
    return {**base, "terminal": row["terminal"], "state": row["state"], "placement": placement,
            "warning": None if placement == "pane" else "소유자 탭을 몰라 pane 없이 띄웠다(herdr 라벨 없음)",
            "warnings": warnings}


class Sweep:
    """소유자의 check --wait 가 틱마다 부른다(설계 9장 observed). sweep(deadline) -> 남은 일이 있으면 True.

    회차 처음에 launching 조정과 가드 거부 정리를 하고 그 Run 의 active Dispatch 를 줄 세운다.
    한 틱은 min(대기 deadline, 지금 + sweep 간격) 안에서만 새 판정을 시작하고, 남은 Dispatch 는 다음 틱에 이어 본다.
    hc 호출 하나는 SWEEP_HC_TIMEOUT_S 와 대기 deadline 중 이른 쪽에 끊는다. 끊긴 판정은 모름이라 아무것도 쓰지 않는다.
    """

    def __init__(self, store, run_id: str):
        self.store, self.run_id = store, run_id
        self.queue: list[str] = []

    def __call__(self, deadline: float) -> bool:
        until = min(deadline, time.monotonic() + mailbox.sweep_interval())
        if not self.queue:
            reconcile_launching(self.store, self.run_id)
            cleanup_refused(self.store, self.run_id, deadline=deadline)
            self.queue = [r["id"] for r in self.store.all(
                "SELECT id FROM dispatches WHERE run_id=? AND state='active' ORDER BY created_at, id", (self.run_id,))]
        while self.queue and not _expired(until):
            liveness.observe_one(self.store, self.run_id, self.queue.pop(0), timeout=_hc_timeout(deadline))
        return bool(self.queue)


def _row_json(r) -> dict:
    return {"id": r["id"], "task": r["task_id"], "attempt": r["attempt"], "agent": r["agent"], "model": r["model"],
            "effort": r["effort"], "agent_args": json.loads(r["agent_args"] or "[]"), "cwd": r["cwd"],
            "terminal": r["terminal"], "state": r["state"],
            "outcome": r["outcome"], "summary": r["summary"], "report_path": r["report_path"],
            "files_modified": json.loads(r["files_modified"] or "[]"), "created_at": r["created_at"],
            "settled_at": r["settled_at"], "closed_at": r["closed_at"]}


def _attention(home, r, verdict: str | None, word: str | None) -> tuple[str | None, list[str] | None]:
    base, d, st = horch_argv(home), r["id"], r["state"]
    if st == "launch_failed":
        if r["attempt"] != r["last_attempt"] or r["task_status"] != "open":
            return None, None  # 다음 시도가 이미 있거나 Task 가 끝났다. 이 행으로 재시도하면 반드시 거부된다
        argv = [*base, "worker-start", "--agent", r["agent"], "--task", r["task_id"], "--retry", "--cwd", r["cwd"]]
        if r["model"]:
            argv += ["--model", r["model"]]
        if r["effort"]:
            argv += ["--effort", r["effort"]]
        # "-" 로 시작하는 인자도 값으로 넘어가게 = 로 붙인다
        return "launch_failed", argv + [f"--agent-arg={a}" for a in json.loads(r["agent_args"] or "[]")]
    if st == "launching":
        return "launching", None
    if st == "active":
        if verdict in ("exited", "lost"):
            return f"{verdict}_without_done", [*base, "worker-abandon", "--dispatch", d]
        if verdict == "unverifiable":
            return "unverifiable", [*base, "worker-show", "--dispatch", d]
        if word in ("blocked", "error"):
            return word, [*base, "worker-show", "--dispatch", d, "--lines", "80"]
        if verdict == "live" and word is None:
            # 시작 확인 창(Claude 폴더 신뢰, Codex hook 검토)은 상태를 보고하지 않는다(설계 10장)
            return "no_status", [*base, "worker-show", "--dispatch", d, "--lines", "40"]
        return None, None
    if st in ("settled", "abandoned"):
        return st, [*base, "worker-release", "--dispatch", d]
    return None, None


def _describe(store, r) -> tuple[dict, dict | None]:
    item = _row_json(r)
    verdict, info = None, None
    if r["state"] in ("active", "settled", "retained", "abandoned") and r["terminal"]:
        verdict, info = liveness.probe(r["terminal"], liveness.loads_argv(r["launch_argv"]))
    word = liveness.status_word(info)
    item["verdict"], item["status"] = verdict, word
    item["attention"], item["next"] = _attention(store.home, r, verdict, word)
    return item, info


# _attention 이 쓰는 Task 상태와 그 Task 의 마지막 시도 번호를 함께 읽는다
_ROWS = ("SELECT d.*, t.title, t.status AS task_status, "
         "(SELECT MAX(x.attempt) FROM dispatches x WHERE x.task_id = d.task_id) AS last_attempt "
         "FROM dispatches d JOIN tasks t ON t.id = d.task_id")


def list_rows(store, run_id: str, states: list[str] | None) -> list[dict]:
    reconcile_launching(store, run_id)
    cleanup_refused(store, run_id)
    sql = _ROWS + " WHERE d.run_id=?"
    params: list = [run_id]
    if states:
        sql += f" AND d.state IN ({','.join('?' * len(states))})"
        params += list(states)
    rows = []
    for r in store.all(sql + " ORDER BY d.created_at, d.id", params):
        item, _ = _describe(store, r)
        item["title"] = r["title"]
        rows.append(item)
    return rows


def show(store, run_id: str, dispatch_id: str, lines: int) -> dict:
    reconcile_launching(store, run_id)
    auth.owned_dispatch(store, run_id, dispatch_id)
    r = store.one(_ROWS + " WHERE d.id=?", (dispatch_id,))
    item, info = _describe(store, r)
    item["title"] = r["title"]
    item["hc"] = {k: info.get(k) for k in ("state", "status", "reason", "turn", "exit_code")} if info else None
    item["screen"] = None
    if lines and r["terminal"]:
        try:
            item["screen"] = hcio.read(r["terminal"], lines)
        except hcio.HcFailure as exc:
            item["screen_error"] = exc.kind
    return {"worker": item}


def _kill_ok(terminal: str) -> None:
    try:
        hcio.kill(terminal)
    except hcio.HcFailure as exc:
        if exc.kind not in ("not_found", "finished"):
            raise HorchError("hc_failed", f"hc kill {terminal} 실패: {exc.kind}", FAIL) from exc


def _rm_ok(terminal: str) -> None:
    """kill 직후 hc 가 아직 live 로 볼 수 있어 그때만 잠깐 다시 한다. 다른 실패(시간 초과 등)는 바로 알린다."""
    tries = 10
    for i in range(tries):
        try:
            hcio.rm(terminal)
            return
        except hcio.HcFailure as exc:
            if exc.kind == "not_found":
                return
            if exc.kind != "live" or i == tries - 1:
                raise HorchError("hc_failed", f"hc rm {terminal} 실패: {exc.kind}", FAIL) from exc
            time.sleep(mailbox.poll_interval())


def _fetch(store, dispatch_id: str) -> dict:
    return _row_json(store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)))


def release(store, run_id: str, dispatch_id: str) -> dict:
    r = auth.owned_dispatch(store, run_id, dispatch_id)
    if r["state"] == "released":
        return {"dispatch": _row_json(r)}
    if r["state"] not in ("settled", "retained", "abandoned"):
        raise HorchError("not_releasable", f"Dispatch {dispatch_id} 는 {r['state']} 라 정리할 수 없다", CONFLICT)
    if r["terminal"]:
        try:
            info = hcio.get(r["terminal"])
        except hcio.HcFailure as exc:
            if exc.kind != "not_found":
                raise HorchError("hc_failed", f"hc get {r['terminal']} 실패: {exc.kind}", FAIL) from exc
            info = None
        if info is not None:
            # 주소가 다른 터미널에 다시 쓰였을 수 있다. 이 Dispatch 의 터미널이라는 증거(라벨) 없이는 죽이거나 지우지 않는다
            owner = (info.get("labels") or {}).get("horch.dispatch")
            if owner != dispatch_id:
                raise HorchError("terminal_mismatch",
                                 f"터미널 {r['terminal']} 의 horch.dispatch 라벨이 {owner} 다. 이 Dispatch 의 터미널이 아니다",
                                 FAIL, "hc get 으로 그 터미널을 확인한다. 상태는 바꾸지 않았다")
            if info.get("state") == "live":
                _kill_ok(r["terminal"])
            _rm_ok(r["terminal"])
    with store.tx():
        store.run("UPDATE dispatches SET state='released', closed_at=? WHERE id=? "
                  "AND state IN ('settled','retained','abandoned')", (now(), dispatch_id))
    return {"dispatch": _fetch(store, dispatch_id)}


def retain(store, run_id: str, dispatch_id: str) -> dict:
    r = auth.owned_dispatch(store, run_id, dispatch_id)
    if r["state"] == "retained":
        return {"dispatch": _row_json(r)}
    if r["state"] != "settled":
        raise HorchError("not_settled", f"Dispatch {dispatch_id} 는 {r['state']} 라 남길 수 없다", CONFLICT)
    with store.tx():
        store.run("UPDATE dispatches SET state='retained' WHERE id=? AND state='settled'", (dispatch_id,))
    return {"dispatch": _fetch(store, dispatch_id)}


def abandon(store, run_id: str, dispatch_id: str, kill: bool) -> dict:
    r = auth.owned_dispatch(store, run_id, dispatch_id)
    if r["state"] == "abandoned":
        return {"dispatch": _row_json(r), "verdict": None}
    if r["state"] != "active":
        raise HorchError("not_active", f"Dispatch {dispatch_id} 는 {r['state']} 다", CONFLICT)
    verdict, _ = liveness.probe(r["terminal"], liveness.loads_argv(r["launch_argv"]))
    if verdict == "unverifiable":
        raise HorchError("unverifiable", f"워커 터미널 {r['terminal']} 의 상태를 확인할 수 없다", FAIL)
    if verdict == "live":
        if not kill:
            raise HorchError("worker_alive", f"워커 {r['terminal']} 가 살아 있다", CONFLICT, "끝내려면 --kill")
        _kill_ok(r["terminal"])
    with store.tx():
        store.run("UPDATE dispatches SET state='abandoned' WHERE id=? AND state='active'", (dispatch_id,))
    row = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    if row["state"] != "abandoned":
        raise HorchError("state_changed", f"그 사이 Dispatch 가 {row['state']} 가 됐다", CONFLICT)
    return {"dispatch": _row_json(row), "verdict": verdict}
