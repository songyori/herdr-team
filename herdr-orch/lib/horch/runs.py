"""Run 만들기(run-create), 넘겨받기(run-use, 설계 6장), 호출자 상태(status)."""
from __future__ import annotations

import json

from . import auth, hcio, liveness
from .errors import CONFLICT, FAIL, USAGE, HorchError
from .ids import new_id, now

# run-use 는 소유자 판정(hc get)을 쓰기 잠금 안에서 한다. 다른 프로세스는 busy_timeout(5초)만 기다리므로
# 그보다 짧게 끊는다. 끊긴 판정은 모름(unverifiable)이라 --force 없이는 거부한다(설계 10장).
USE_PROBE_TIMEOUT_S = 3.0


def _caller_facts(terminal: str) -> tuple[str | None, str | None, list[str] | None]:
    try:
        info = hcio.get(terminal)
    except hcio.HcFailure as exc:
        raise HorchError("hc_unavailable", f"호출자 터미널 {terminal} 을 hc 에서 읽지 못했다: {exc.kind}", FAIL) from exc
    labels = info.get("labels") or {}
    return labels.get("herdr.space"), labels.get("herdr.tab"), info.get("argv")


def run_json(store, run_id: str) -> dict:
    row = store.one("SELECT * FROM runs WHERE id=?", (run_id,))
    owner = store.one("SELECT terminal FROM bindings WHERE run_id=?", (run_id,))
    return {"id": row["id"], "objective": row["objective"], "owner": owner["terminal"] if owner else None,
            "owner_space": row["owner_space"], "owner_tab": row["owner_tab"], "created_at": row["created_at"]}


def _bind(store, terminal: str, run_id: str, argv) -> None:
    """트랜잭션 안에서 부른다. 호출자의 이전 binding 과 그 Run 의 이전 binding 을 지운다."""
    store.run("DELETE FROM bindings WHERE terminal=?", (terminal,))
    store.run("DELETE FROM bindings WHERE run_id=?", (run_id,))
    store.run("INSERT INTO bindings(terminal, run_id, argv) VALUES (?,?,?)", (terminal, run_id, json.dumps(argv)))


def create(store, objective: str) -> dict:
    term = auth.require_terminal()
    auth.refuse_worker(store, term)
    space, tab, argv = _caller_facts(term)
    run_id, ts = new_id("run"), now()
    with store.tx():
        store.run("INSERT INTO runs(id, objective, owner_space, owner_tab, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?)", (run_id, objective, space, tab, ts, ts))
        _bind(store, term, run_id, argv)
    return {"run": run_json(store, run_id), "placement": "pane" if space and tab else "none"}


def use(store, run_id: str, force: bool) -> dict:
    term = auth.require_terminal()
    auth.refuse_worker(store, term)
    if not store.one("SELECT 1 FROM runs WHERE id=?", (run_id,)):
        raise HorchError("unknown_run", f"Run {run_id} 가 없다", USAGE)
    # 이미 자기 것이면 아무것도 바꾸지 않는다. hc 를 부르지 않으므로 hc 장애에도 성공한다.
    mine = store.one("SELECT 1 FROM bindings WHERE run_id=? AND terminal=?", (run_id, term))
    if mine:
        return {"run": run_json(store, run_id), "previous_owner": term, "previous_verdict": None}
    space, tab, argv = _caller_facts(term)
    # 설계 6장: binding 조회, 생존 판정, 허용 검사, 갱신을 한 BEGIN IMMEDIATE 안에서 한다.
    # 판정하는 동안 다른 쓰기(같은 terminal·argv 로 다시 묶기 포함)는 binding 을 바꾸지 못한다.
    # 판정은 hc get 한 번이고 USE_PROBE_TIMEOUT_S 안에 끝나지 않으면 모름이다.
    with store.tx():
        owner = store.one("SELECT terminal, argv FROM bindings WHERE run_id=?", (run_id,))
        prev = owner["terminal"] if owner else None
        if prev == term:
            return {"run": run_json(store, run_id), "previous_owner": prev, "previous_verdict": None}
        verdict = None
        if prev:
            verdict, _ = liveness.probe(prev, liveness.loads_argv(owner["argv"]), timeout=USE_PROBE_TIMEOUT_S)
            if verdict == "live":
                raise HorchError("owner_alive", f"Run {run_id} 의 소유자 {prev} 가 살아 있다", CONFLICT)
            if verdict == "unverifiable" and not force:
                raise HorchError("owner_unverifiable", f"소유자 {prev} 의 상태를 확인할 수 없다", CONFLICT,
                                 "소유자가 끝났다고 확신하면 --force")
        _bind(store, term, run_id, argv)
        store.run("UPDATE runs SET owner_space=?, owner_tab=?, updated_at=? WHERE id=?", (space, tab, now(), run_id))
    return {"run": run_json(store, run_id), "previous_owner": prev, "previous_verdict": verdict}


def status(store) -> dict:
    term = auth.caller()
    out = {"terminal": term, "dispatch": None, "run": None}
    if not term:
        return out
    worker = store.one("SELECT id, state FROM dispatches WHERE terminal=? AND state IN ('launching','active')", (term,))
    if worker:
        out["dispatch"] = {"id": worker["id"], "state": worker["state"]}
    binding = store.one("SELECT run_id FROM bindings WHERE terminal=?", (term,))
    if not binding:
        return out
    run_id = binding["run_id"]
    box = f"run:{run_id}"
    counts = {r["state"]: r["n"] for r in store.all(
        "SELECT state, COUNT(*) AS n FROM dispatches WHERE run_id=? GROUP BY state", (run_id,))}
    open_delivery = store.one("SELECT id FROM deliveries WHERE mailbox=? AND acked_at IS NULL ORDER BY id LIMIT 1", (box,))
    unread = store.one("SELECT COUNT(*) AS n FROM messages WHERE mailbox=? AND delivery_id IS NULL AND type != 'reply'",
                       (box,))["n"]
    # 답할 수 있는 질문만: 묻고 기다리는 워커(launching·active)의 것. 버리거나 끝난 Dispatch 의 질문은 뺀다
    unanswered = [{"id": r["id"], "dispatch": r["dispatch_id"], "body": r["body"][:200]} for r in store.all(
        "SELECT q.id, q.dispatch_id, q.body FROM messages q JOIN dispatches d ON d.id=q.dispatch_id "
        "WHERE q.run_id=? AND q.type='question' AND d.state IN ('launching','active') AND NOT EXISTS "
        "(SELECT 1 FROM messages r WHERE r.reply_to=q.id AND r.type='reply') ORDER BY q.id", (run_id,))]
    out["run"] = {**run_json(store, run_id), "dispatches": counts,
                  "open_delivery": open_delivery["id"] if open_delivery else None,
                  "unread": unread, "unanswered": unanswered}
    return out
