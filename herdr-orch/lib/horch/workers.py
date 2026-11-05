"""워커 실행(설계 8장), launching 조정과 가드 거부 정리(설계 5장). 목록·정리 명령은 Task 10 에서 더한다."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from pathlib import Path

from . import agents, hcio, preamble, procs
from .errors import CONFLICT, FAIL, MISSING, USAGE, HorchError
from .ids import new_id, now
from .paths import horch_argv, horch_cmd
from .store import write_atomic


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


def cleanup_refused(store, run_id: str) -> list[str]:
    """가드가 거부해 끝난 터미널을 hc rm 한다. 이름으로 후보를 찾고 라벨(horch.run·horch.dispatch)과 상태를 get 으로 확인한다."""
    failed = {r["id"] for r in store.all("SELECT id FROM dispatches WHERE run_id=? AND state='launch_failed'", (run_id,))}
    if not failed:
        return []
    try:
        terminals = hcio.ls_all()
    except hcio.HcFailure:
        return []
    removed = []
    for t in terminals:
        if t.get("name") not in failed or t.get("state") != "finished":
            continue
        try:
            info = hcio.get(t["address"])
            labels = info.get("labels") or {}
            if (info.get("state") == "finished" and labels.get("horch.run") == run_id
                    and labels.get("horch.dispatch") in failed):
                hcio.rm(t["address"])
                removed.append(t["address"])
        except hcio.HcFailure:
            pass
    return removed


def _create(store, run_id: str, *, spec, title, agent, model, effort, cwd, task_id, retry) -> tuple[str, str, str, str]:
    """Task·Dispatch 를 한 트랜잭션에서 만든다. 재시도 허용 검사도 이 안에서 다시 한다."""
    pid, started = procs.me()
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
            store.run("INSERT INTO dispatches(id, task_id, run_id, attempt, agent, model, effort, cwd, state, "
                      "launcher_pid, launcher_started, created_at) VALUES (?,?,?,?,?,?,?,?,'launching',?,?,?)",
                      (dispatch_id, task_id, run_id, attempt, agent, model, effort, cwd, pid, started, ts))
    except sqlite3.IntegrityError as exc:
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
                                                effort=effort, cwd=str(cwd_path), task_id=task_id, retry=retry)
    _die_at("after_create")
    base = {"task": task_id, "dispatch": dispatch_id}
    ddir = store.dispatch_dir(run_id, dispatch_id)
    spec_path = ddir / "spec.md"
    write_atomic(spec_path, spec)
    text = preamble.render(task_id=task_id, dispatch_id=dispatch_id, spec_path=str(spec_path),
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
        write_atomic(ddir / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2))
        if _mark_failed(store, dispatch_id) == "launch_failed":
            code = exc.exit_code if isinstance(exc, HorchError) else FAIL
            raise HorchError("launch_failed", f"hc run 실패: {kind}", code, data=base) from exc
        address = None
    else:
        write_atomic(ddir / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2))
        _die_at("before_record")
        with store.tx():
            store.run("UPDATE dispatches SET terminal=?, state='active' WHERE id=? AND state='launching'",
                      (address, dispatch_id))
    row = store.one("SELECT state, terminal FROM dispatches WHERE id=?", (dispatch_id,))
    if address is not None and row["terminal"] != address:
        raise HorchError("terminal_mismatch", f"가드가 등록한 터미널 {row['terminal']} 와 hc 주소 {address} 가 다르다",
                         FAIL, data=base)
    return {**base, "terminal": row["terminal"], "state": row["state"], "placement": placement,
            "warning": None if placement == "pane" else "소유자 탭을 몰라 pane 없이 띄웠다(herdr 라벨 없음)"}
