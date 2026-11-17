"""메인 → 관제 요청 큐(설계 7.1, 8.3 의 큐 명령, 8.5 의 틱 3).

메인은 horch 를 부르지 않는다. horch 를 건드리는 메인 명령(큐 명령)은 `state/drive/queue/` 의 요청 파일로 관제에 넘기고,
관제(와 그 자식)에서 부르면 그 자리에서 실행한다(route).

메인 쪽(submit): 메인 쪽 검사(부르는 쪽) → 관제 생존 → queue.lock 안에서 번호와 요청 파일 → 결과 파일을 0.2초마다 90초까지
기다린다. 넘거나 신호로 끊기면 `.abandoned` 를 남기고(결과가 이미 와 있으면 outbox result 로 옮기고) 돌아온다.

관제 쪽(run_pending): 틱마다 번호순으로 모두 실행한다. 실행 직전 요청 파일에 started_at 을 쓰고, 큐 요청이 바꾼 기록에는
request 를 남긴다. 다시 뜬 관제는 started_at 이 있고 결과가 없는 요청을 그 기록으로 복구하거나(recorded) 다시 실행한다.
관제 안의 fix·accept·drop 이 리뷰 관문의 finish 잠금을 만나면(review_busy) 그 요청을 미룬다(8.5).

미룬 fix(12단계, 설계 7.1 `fix T --after A`): 메인은 요청 파일(after)과 .abandoned 를 같은 queue.lock 안에서 쓰고 기다리지
않는다(deferred). 관제는 A 가 done 이 될 때까지 그 요청을 건너뛰고(뒤 요청을 막지 않는다), 실행·실패 전에 queue.lock 안에서
요청 파일을 다시 읽는다(hteam cancel 과의 배제). 그 태스크는 재확인이 자동으로 다루지 않는다(held_tasks).

queue.lock 안에서는 outbox 잠금(그 안에서 다른 잠금을 잡지 않는 잎 잠금)만 잡는다. 사양·상태 파일은 잠금 없이 읽는다.
"""
from __future__ import annotations

import re
import signal
import time

from . import drive, outbox, roles, state, testgate, workspace
from .errors import CONFLICT, FAIL, MISSING, USAGE, HteamError
from .paths import find_project
from .util import bad_side_file, die_at, env_float, flock, now, read_json, read_json_strict, write_atomic, write_json

QUEUE_COMMANDS = ("start", "start-ready", "fix", "accept", "drop", "review", "design-decide", "scope", "agent reset",
                  "slot reset", "test-confirm", "reply")  # review 는 --retry 만
ROUND_COMMANDS = ("fix", "accept", "drop", "scope", "review")  # 메인이 본 라운드를 expect_round 로 담는다

# 설계 7.1 원문
DOWN_MESSAGE = "관제(hteam drive)가 꺼져 있다. 메인에서 /herdr-team:up 으로 살린 뒤 다시 한다"
HUNG_MESSAGE = ("관제가 멈춘 것 같다(프로세스는 살아 있는데 heartbeat 가 끊겼다). 긴 작업 중일 수 있으니 잠시 뒤 다시 한다. 계속되면 "
                "사용자에게 관제 탭을 확인해 달라고 한다(관제를 다시 띄우는 명령은 이 상태를 고치지 않는다)")
QUEUED_MESSAGE = "관제가 처리 중이다. 결과는 hteam watch 의 result 메시지로 온다"
SUBMIT_ERRORS = frozenset({"drive_down", "drive_hung"})  # 큐에 넣기 전의 거부(아무것도 쓰지 않았다)
# 미룬 fix(12단계, 설계 7.1 원문)
DEFERRED_MESSAGE = "{after} 가 done 이 되면 관제가 실행한다. 결과는 hteam watch 의 result 메시지로 온다"
AFTER_CYCLE = "{task}: {after} 는 {task} 가 끝나야 진행한다. 서로 기다려 멈춘다"
AFTER_CLOSED = "{task}: 선행 {after} 가 병합 없이 끝났다(dropped). 기다릴 것이 없다. 지금 fix 하거나 다시 판단한다"
AFTER_FAILED = "{after} 가 병합 없이 끝났다({status}). {task} 의 fix 를 하지 않았다. 다시 판단한다"
AFTER_WAIT_LOG = "요청 {rid} fix: {after} 를 기다린다"

FILE_RE = re.compile(r"^(\d{6})\.(?:json|result\.json|abandoned)$")  # 번호를 세는 파일
REQUEST_RE = re.compile(r"^\d{6}\.json$")
RID_RE = re.compile(r"^q-\d{6}$")  # 요청 id(hteam cancel)


# --- 파일 ---
def _request_path(p, rid: str):
    return p.queue_dir / f"{rid[2:]}.json"  # q-000001 → 000001.json


def _result_path(path):
    return path.with_name(path.name[:-len(".json")] + ".result.json")


def _abandoned_path(path):
    return path.with_name(path.name[:-len(".json")] + ".abandoned")


def _next_number(p) -> int:
    """max(queue.seq 의 값(없거나 읽지 못하면 1), 남은 요청·결과·그만둔 표시의 가장 큰 번호 + 1). queue.lock 안에서 부른다."""
    try:
        seq = int(p.queue_seq.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        seq = 1
    top = 0
    if p.queue_dir.is_dir():
        for f in p.queue_dir.iterdir():
            m = FILE_RE.match(f.name)
            if m:
                top = max(top, int(m.group(1)))
    return max(seq, top + 1)


def annotate(p, req: dict, **fields) -> None:
    """요청 파일에 필드를 더해 원자적으로 쓴다(started_at, scope 의 target_dispatch)."""
    req.update(fields)
    write_json(_request_path(p, req["id"]), req)


def _body(req: dict, outcome: dict) -> str:
    """outbox result 의 body: `<command> <대상> — 완료` 또는 `— 실패: <code>: <message>`. 대상은 task → id → name."""
    args = req.get("args") or {}
    target = next((args[k] for k in ("task", "id", "name") if args.get(k)), None)
    head = f"{req.get('command')} {target}" if target else str(req.get("command"))
    if outcome.get("ok"):
        return f"{head} — 완료"
    err = outcome.get("error") or {}
    return f"{head} — 실패: {err.get('code')}: {err.get('message')}"


def _post_result(p, req: dict, outcome: dict) -> None:
    """메인이 기다리지 않는 결과를 outbox result 로 쓴다(설계 7.2). queue.lock 안에서 부른다."""
    outbox.append(p, {"type": "result", "from": "drive", "request": req["id"], "command": req.get("command"),
                      "result": outcome, "body": _body(req, outcome)})


def _unwrap(outcome) -> dict:
    """결과 파일 → 성공이면 그 결과, 실패면 그 code·exit 의 HteamError."""
    if outcome.get("ok"):
        return outcome.get("result") or {}
    err = outcome.get("error") or {}
    data = {k: v for k, v in outcome.items() if k not in ("ok", "error", "exit")}
    raise HteamError(err.get("code") or "failed", err.get("message") or "", outcome.get("exit") or FAIL,
                     err.get("hint") or "", data=data)


def _read_result(path) -> dict:
    outcome = read_json_strict(path, None)
    if not isinstance(outcome, dict):
        raise bad_side_file(path, "JSON 객체가 아니다")
    return outcome


def _take(path) -> dict:
    outcome = _read_result(path)
    path.unlink(missing_ok=True)
    return _unwrap(outcome)


# --- 메인 ---
def route(p, command: str, args: dict, execute, *, check=None, expect_round=None, after: str | None = None) -> dict:
    """큐 명령의 길(설계 7.1, 8.3). 관제(그 자식 포함)면 execute(None) 를 그 자리에서, 메인이면 require_main → check() →
    submit. expect_round() 는 ROUND_COMMANDS 가 메인 쪽 검사 뒤 본 라운드다.

    after 는 `fix --after` 의 선행 태스크다(12단계, 7.1): 메인 쪽 검사(_after_check) 뒤 선행이 이미 done 이면 --after 를
    떼고 지금 요청으로 보내 결과에 after: already_done 을 더하고, 아니면 미룬 요청으로 넣는다. 관제 안에서는 받지 않는다."""
    if roles.drive_env(p):
        if after is not None:
            raise HteamError("usage", "--after 는 메인이 관제에 맡기는 fix 에만 쓴다(관제 안에서는 쓰지 않는다)", USAGE)
        return execute(None)
    outbox.require_main(p)
    if check is not None:
        check()
    rnd = expect_round() if expect_round is not None else None
    if after is None:
        return submit(p, command, args, expect_round=rnd)
    if _after_check(p, args["task"], after):  # 선행이 이미 done: 지금 fix 로 보낸다
        return {**submit(p, command, args, expect_round=rnd), "after": "already_done"}
    return submit(p, command, args, expect_round=rnd, after=after)


def _cycle(task: str, after: str) -> HteamError:
    return HteamError("after_cycle", AFTER_CYCLE.format(task=task, after=after), CONFLICT)


def _after_check(p, task: str, after: str) -> bool:
    """`fix task --after after` 의 메인 쪽 검사(설계 7.1 12단계, 순서 1 에 더한다). 선행이 이미 done 이면 True.
    같은 태스크면 exit 2 usage, 선행 상태가 없으면 exit 2 unknown_task, dropped 면 exit 3 after_closed, 서로 기다리면
    exit 3 after_cycle."""
    if after == task:
        raise HteamError("usage", f"--after 는 다른 태스크다({task} 가 자기 자신을 기다릴 수 없다)", USAGE)
    st = state.require(p, after)
    if st["status"] == "done":
        return True
    if st["status"] == "dropped":
        raise HteamError("after_closed", AFTER_CLOSED.format(task=task, after=after), CONFLICT)
    if after_cycle(p, task, after):
        raise _cycle(task, after)
    return False


def after_cycle(p, task: str, after: str, extra: list[tuple[str, str]] | None = None) -> bool:
    """`fix task --after after` 를 더하면 서로 기다리는가(설계 7.1 12단계): 기다림 그래프에서 after 에서 task 로 가는 길이
    있다. 그래프는 사양의 depends_on(approval.Graph. 시작 판정 tasks.deps_met 와 같은 값이고, 사양을 읽지 못한 태스크는 그
    간선만 빠진다)에 남은 미룬 요청의 `fix X --after Y`(X 가 Y 를 기다린다)와 extra 의 (X, Y) 를 더한 것이다. 잠금을 잡지
    않는다(submit 은 queue.lock 안에서 다시 부른다)."""
    from . import approval  # approval 이 이 모듈을 쓴다
    graph = approval.Graph(p)
    waits: dict[str, set[str]] = {}
    for x, y in [(_task_of(r), r.get("after")) for r in deferred(p)] + list(extra or []):
        if isinstance(x, str) and isinstance(y, str):
            waits.setdefault(x, set()).add(y)
    seen, todo = {after}, [after]
    while todo:
        cur = todo.pop()
        for nxt in [*graph.deps(cur), *sorted(waits.get(cur, ()))]:
            if nxt == task:
                return True
            if nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return False


def _signal_exit(code: int):
    def handler(*_):
        raise SystemExit(code)
    return handler


def submit(p, command: str, args: dict, *, expect_round: int | None = None, after: str | None = None) -> dict:
    """관제 생존을 보고 요청을 쓴 뒤 결과를 기다린다(설계 7.1 순서 2–6). 관제 결과(성공이면 그 결과, 실패면 그 code·exit 의
    HteamError) 또는 {"status": "queued", "request", "message"}.

    after 가 있으면(미룬 fix, 12단계) 같은 queue.lock 안에서 서로 기다림을 다시 검사하고(병렬로 들어온 서로의 --after.
    걸리면 번호를 쓰지 않고 exit 3 after_cycle) .abandoned 와 요청 파일을 쓴 뒤 기다리지 않고
    {"status": "deferred", "request", "after", "message"} 다. 결과는 관제가 outbox result 로 쓴다."""
    live = drive.liveness(p)
    if live["hung"]:
        raise HteamError("drive_hung", HUNG_MESSAGE, FAIL)
    if not live["alive"]:
        raise HteamError("drive_down", DOWN_MESSAGE, FAIL)
    req: dict = {"id": None, "command": command, "args": args, "at": now()}
    if expect_round is not None:
        req["expect_round"] = expect_round
    if after is not None:
        req["after"] = after
    with flock(p.queue_lock):
        if after is not None and after_cycle(p, args["task"], after):
            raise _cycle(args["task"], after)
        n = _next_number(p)
        write_atomic(p.queue_seq, f"{n + 1}\n")
        req["id"] = f"q-{n:06d}"
        path = _request_path(p, req["id"])
        if after is not None:  # 표시를 먼저: 그 사이 죽어도 아무도 읽지 않는 결과 파일이 생기지 않는다
            path.parent.mkdir(parents=True, exist_ok=True)
            _abandoned_path(path).touch()
        write_json(path, req)
    if after is not None:
        return {"status": "deferred", "request": req["id"], "after": after,
                "message": DEFERRED_MESSAGE.format(after=after)}
    return _wait(p, req)


def _wait(p, req: dict) -> dict:
    path = _request_path(p, req["id"])
    res, mark = _result_path(path), _abandoned_path(path)
    total = env_float("HTEAM_QUEUE_WAIT_S", drive.QUEUE_WAIT_S)
    poll = env_float("HTEAM_QUEUE_POLL_S", drive.QUEUE_POLL_S)
    # 기다리는 동안만: SIGHUP 129, SIGINT 130(SIGTERM 143 은 cli 가 SystemExit 로 바꾼다)
    old = {sig: signal.signal(sig, _signal_exit(code)) for sig, code in ((signal.SIGHUP, 129), (signal.SIGINT, 130))}
    try:
        deadline = time.monotonic() + total
        while True:
            if res.exists():
                return _take(res)
            left = deadline - time.monotonic()
            if left <= 0:
                with flock(p.queue_lock):
                    if not res.exists():  # 결과가 아직 없을 때만 그만둔다. 그 뒤 관제가 outbox result 로 쓴다
                        mark.touch()
                        return {"status": "queued", "request": req["id"], "message": QUEUED_MESSAGE}
                return _take(res)
            time.sleep(min(poll, left))
    except (SystemExit, KeyboardInterrupt):
        with flock(p.queue_lock):
            if res.exists():  # 결과가 이미 왔다: 메인이 받지 못하므로 outbox result 로 옮긴다
                _post_result(p, req, _read_result(res))
                res.unlink(missing_ok=True)
            else:
                mark.touch()
        raise
    finally:
        for sig, handler in old.items():
            signal.signal(sig, handler)


# --- 관제 ---
def _request_files(p) -> list:
    if not p.queue_dir.is_dir():
        return []
    return sorted((f for f in p.queue_dir.iterdir() if REQUEST_RE.match(f.name)), key=lambda f: f.name)


def _is_deferred(req: dict) -> bool:
    """미룬 요청(설계 7.1 12단계): after 가 있고 started_at 이 없다."""
    return bool(req.get("after")) and not req.get("started_at")


def _task_of(req: dict) -> str | None:
    args = req.get("args")
    task = args.get("task") if isinstance(args, dict) else None
    return task if isinstance(task, str) else None


def waiting(p) -> bool:
    """결과 없는 요청 파일이 있다(관제가 아직 실행하지 않았거나 review_busy 로 미뤘다). 관제 다시 묶기의 한가함(설계 8.13).
    미룬 요청은 세지 않는다(7.1 12단계: 세면 선행을 기다리는 동안 다시 묶기가 멈춘다). 읽지 못하는 요청 파일은 센다."""
    for f in _request_files(p):
        if _result_path(f).exists():
            continue
        req = read_json(f, None)
        if req is None and not f.exists():  # 그 사이 실행·취소로 지워졌다
            continue
        if not (isinstance(req, dict) and _is_deferred(req)):
            return True
    return False


def deferred(p) -> list[dict]:
    """미룬 요청(설계 7.1 12단계)의 요청 파일 내용, 번호순. 결과 파일이 있거나 읽지 못하는 요청은 뺀다. 잠금을 잡지 않는다."""
    found = []
    for f in _request_files(p):
        req = read_json(f, None)
        if isinstance(req, dict) and _is_deferred(req) and not _result_path(f).exists():
            found.append(req)
    return found


def held_tasks(p) -> set[str]:
    """미룬 요청의 대상 태스크(설계 7.1 12단계 "대상 태스크 붙잡기"). 재확인(Drive.reconcile_task)이 자동으로 다루지 않는다."""
    return {t for t in map(_task_of, deferred(p)) if t}


def recorded(p, req: dict) -> dict | None:
    """started_at 은 있는데 결과가 없는 요청(실행 중 관제가 죽었다)의 기록. 있으면 복구 결과, 없으면 None(다시 실행한다).

    start·fix·accept·drop·scope·review 는 그 태스크 history 에 이 요청 id 의 사건이 있거나 queued_fix.request 가 이 id,
    design-decide 는 그 묶음의 결정 기록 request 가 이 id, test-confirm 은 test-confirm.json 의 asked 에 이 id 의 항목이
    있다, slot reset 은 그 슬롯 기록의 reset_request 가 이 id 다(설계 5.10.8). start-ready·reply 는 기록이 없다(다시 해도
    결과가 같다)."""
    rid, cmd, args = req.get("id"), req.get("command"), req.get("args") or {}
    if cmd in ("start", "fix", "accept", "drop", "scope", "review"):
        st = state.load(p, args.get("task"))
        if st is None:
            return None
        hit = any(isinstance(e, dict) and e.get("request") == rid for e in st.get("history") or [])
        if hit or (st.get("queued_fix") or {}).get("request") == rid:
            return {"recovered": True, "task": st["id"], "status": st["status"], "round": st["round"]}
        return None
    if cmd == "design-decide":
        from . import approval  # approval 이 이 모듈을 쓴다
        b = next((x for x in approval.load(p)["batches"] if x.get("id") == args.get("id")), None)
        if b is not None and (b.get("decision") or {}).get("request") == rid:
            return {"recovered": True, "id": args["id"]}
    if cmd == "test-confirm":
        hit = next((a for a in drive.confirm_record(p)["asked"] if a.get("request") == rid), None)
        if hit is not None:
            return {"recovered": True, "asked": hit.get("out_id"), "digest": hit.get("digest")}
    if cmd == "slot reset" and isinstance(args.get("slot"), int):
        rec = workspace.entry(workspace.load(p), args["slot"])
        if rec.get("reset_request") == rid:
            return {"recovered": True, "slot": args["slot"], "state": rec["state"]}
    return None


def _overrides(args: dict) -> dict:
    return {k: args[k] for k in ("model", "effort", "worker") if args.get(k)}


def _x_start(p, d, req):
    from . import tasks
    a = req["args"]
    return tasks.start_command(p, a["task"], _overrides(a), request=req["id"])  # 메인의 start 와 같은 waiting 결과(설계 5.4)


def _x_start_ready(p, d, req):
    from . import tasks
    return tasks.start_ready(p)


def _x_fix(p, d, req):
    from . import tasks
    a = req["args"]
    res = tasks.fix(p, a["task"], note=a.get("note"), supplement=a.get("supplement"),
                    force_round=bool(a.get("force_round")), cli=_overrides(a), expect_round=req.get("expect_round"),
                    request=req["id"], nowait=True, force=bool(a.get("force")), base_merge=bool(a.get("base_merge")))
    if "round" in res:  # 새 라운드를 열었다(설계 8.11. 대기열에만 넣은 결과에는 round 가 없다)
        d.log(f"{a['task']} r{res['round']} 수정 시작")
    return res


def _x_accept(p, d, req):
    """accept 뒤 처리는 관제 판정 경로와 같다(설계 8.6). 그 예외는 큐 결과를 바꾸지 않는다(격리 accept:<T>)."""
    from . import tasks
    task = req["args"]["task"]
    res = tasks.accept(p, task, req.get("expect_round"), request=req["id"], nowait=True)
    d.isolated(f"accept:{task}", lambda: d.after_accept(task, res))
    return res


def _x_drop(p, d, req):
    """drop 뒤 관제가 그 슬롯을 놓는다(설계 5.10.6, 8.8). 놓기의 예외는 큐 결과를 바꾸지 않는다(격리 release:<T>)."""
    from . import tasks
    a = req["args"]
    res = tasks.drop(p, a["task"], bool(a.get("force")), req.get("expect_round"), request=req["id"], nowait=True)
    d.isolated(f"release:{a['task']}", d.release_step)
    return res


def _x_review(p, d, req):
    return d.spawn_review(req["args"]["task"], retry=True, expect_round=req.get("expect_round"), request=req["id"])


def _x_design_decide(p, d, req):
    from . import approval
    return approval.decide(p, req["args"]["id"], None, request=req["id"], nowait=True)


def _x_scope(p, d, req):
    from . import tasks
    a = req["args"]
    return tasks.scope(p, a["task"], a["body"], expect_round=req.get("expect_round"), request=req["id"],
                       target=req.get("target_dispatch"), remember=lambda did: annotate(p, req, target_dispatch=did))


def _x_agent_reset(p, d, req):
    """agent reset(설계 5.9.7): 큐 실행도 이름을 검사한다. 다시 해도 결과가 같다(7.1)."""
    from . import config, crew  # crew 가 이 모듈을 쓴다
    return crew.agent_reset(p, config.load(p), req["args"]["name"], request=req["id"])


def _x_slot_reset(p, d, req):
    """slot reset(설계 5.10.8): 큐 실행도 모드·번호를 검사한다. 요청 id 를 슬롯 기록에 남긴다(recorded)."""
    from . import config
    return workspace.reset(p, config.load(p), req["args"]["slot"], request=req["id"])


def _x_test_confirm(p, d, req):
    return d.confirm_test(force=True, request=req["id"])


def _x_reply(p, d, req):
    """워커 질문의 회신(설계 7.4). 거부면 horch 의 code·message·hint·exit 그대로(메인의 reply_failed 가 그 까닭을 보인다)."""
    a = req["args"]
    code, data = d.horch().call("reply", "--id", str(a.get("message_id")), f"--body={a.get('body')}")
    if code != 0 or not data.get("ok"):
        err = data.get("error") or {}
        raise HteamError(err.get("code") or "horch_failed", err.get("message") or "", code or FAIL, err.get("hint") or "")
    return {k: v for k, v in data.items() if k != "ok"}


# 실행 표(관제 안이라 모두 기다리지 않는다)
EXECUTORS = {"start": _x_start, "start-ready": _x_start_ready, "fix": _x_fix, "accept": _x_accept, "drop": _x_drop,
             "review": _x_review, "design-decide": _x_design_decide, "scope": _x_scope, "agent reset": _x_agent_reset,
             "slot reset": _x_slot_reset,
             "test-confirm": _x_test_confirm, "reply": _x_reply}


def _settle(p, path, req: dict, outcome: dict) -> None:
    """결과를 쓴다(queue.lock 안에서 부른다): 메인이 기다리기를 그만뒀으면(.abandoned) outbox result, 아니면 결과 파일."""
    res, mark = _result_path(path), _abandoned_path(path)
    if mark.exists():
        _post_result(p, req, outcome)
        mark.unlink(missing_ok=True)
    else:
        write_json(res, outcome)


def _log_outcome(d, req: dict, outcome: dict) -> None:
    if outcome.get("ok"):
        d.log(f"요청 {req['id']} {req.get('command')}: 완료")
    else:
        err = outcome.get("error") or {}
        d.log(f"요청 {req['id']} {req.get('command')}: {err.get('code')}: {err.get('message')}")


def _finish(p, d, path, req: dict, outcome: dict) -> None:
    """결과를 쓰고(_settle) 요청 파일을 지운다."""
    with flock(p.queue_lock):
        _settle(p, path, req, outcome)
    die_at("queue_result_written")
    path.unlink(missing_ok=True)
    _log_outcome(d, req, outcome)


def _after_turn(p, d, path, req: dict) -> tuple[str, dict]:
    """미룬 fix 의 차례(설계 7.1 12단계). queue.lock 안에서 요청 파일을 다시 읽고(hteam cancel 과의 배제) 선행 상태를 본다.

    ("gone", req): 그 사이 취소됐다. ("run", 요청): 선행이 done 이라 started_at 을 썼다(그 뒤로는 cancel 이 지우지 못한다).
    ("failed", 요청): 선행이 dropped 이거나 상태 파일이 없어 실행하지 않고 after_failed 결과를 쓰고 요청 파일을 지웠다.
    ("wait", 요청): 그 밖(pending·working·changes 등. 읽지 못한 상태 파일도 고쳐질 때까지 기다린다). 처음 미룰 때만 로그."""
    after, task = req["after"], _task_of(req)
    with flock(p.queue_lock):
        cur = read_json(path, None)
        if not isinstance(cur, dict):  # 그 사이 hteam cancel 이 지웠다
            return "gone", req
        try:
            st = state.load(p, after)
        except HteamError:
            st = {"status": "unreadable"}
        status = st.get("status") if st is not None else None
        if status == "done":
            annotate(p, cur, started_at=now())
            return "run", cur
        failed = status in ("dropped", None)
        if failed:
            err = HteamError("after_failed", AFTER_FAILED.format(after=after, status=status or "상태 없음", task=task),
                             CONFLICT)
            outcome = {"ok": False, "error": err.to_json()["error"], "exit": err.exit_code}
            _settle(p, path, cur, outcome)
            path.unlink(missing_ok=True)
    if failed:
        _log_outcome(d, cur, outcome)
        return "failed", cur
    if cur["id"] not in d.after_waits:
        d.after_waits.add(cur["id"])
        d.log(AFTER_WAIT_LOG.format(rid=cur["id"], after=after))
    return "wait", cur


def run_pending(p, d) -> list[str]:
    """틱 3(설계 7.1 "재실행 막기", 8.5). 남은 요청을 번호순으로 모두 실행(또는 기록으로 복구)하고 그 id 를 돌려준다.
    리뷰 관문 때문에 미룬 요청(review_busy)과 결과 파일만 남은 요청은 세지 않는다. 미룬 fix(after 가 있고 started_at 이
    없음, 12단계)는 _after_turn 이 정한다: 선행을 기다리거나 그 사이 취소됐으면 그대로 다음 요청으로 간다(세지 않는다).
    목록을 만든 뒤 첫 읽기 전에 지워진(취소된) 요청도 결과 없이 건너뛴다. 있는데 읽지 못하는 요청 파일은 지금처럼 다룬다."""
    done: list[str] = []
    for path in _request_files(p):
        d.heartbeat()
        req = read_json(path, None)
        if req is None and not path.exists():  # 목록을 만든 뒤 hteam cancel 이 지웠다: 결과를 남기지 않는다
            continue
        if _result_path(path).exists():  # 결과를 쓴 뒤 요청 파일을 지우기 전에 관제가 죽었다
            path.unlink(missing_ok=True)
            continue
        fresh = False  # 미룬 fix 를 실행한다: started_at 은 _after_turn 이 queue.lock 안에서 썼다
        if isinstance(req, dict) and _is_deferred(req):
            turn, req = _after_turn(p, d, path, req)
            if turn == "failed":
                done.append(req["id"])
            if turn != "run":
                continue
            fresh = True
        try:
            # 실행을 시작한 뒤 결과 전에 관제가 죽었다
            rec = recorded(p, req) if req.get("started_at") and not fresh else None
            if rec is not None:
                outcome = {"ok": True, "result": rec}
            else:
                if not fresh:
                    annotate(p, req, started_at=now())
                die_at("queue_started")
                outcome = {"ok": True, "result": EXECUTORS[req["command"]](p, d, req)}
        except HteamError as exc:
            if exc.code == "review_busy":  # 리뷰 관문이 finish 잠금을 쥐었다(8.5): 그대로 두고 다음 틱에 다시
                req.pop("started_at", None)
                write_json(path, req)
                continue
            outcome = {"ok": False, "error": exc.to_json()["error"], "exit": exc.exit_code, **exc.data}
            if exc.exit_code == MISSING:  # 의존 프로그램 없음은 결과를 쓰고 관제를 끝낸다(8.5 격리 밖)
                _finish(p, d, path, req, outcome)
                raise
        except Exception as exc:  # noqa: BLE001  버그도 결과로 알린다(cli 의 internal 과 같은 모양)
            outcome = {"ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}", "hint": ""},
                       "exit": FAIL}
        die_at("queue_executed")
        _finish(p, d, path, req, outcome)
        done.append(req["id"])
    return done


# --- 미룬 요청 지우기(12단계) ---
def cancel(p, rid: str) -> dict:
    """`hteam cancel <q-NNNNNN>`(설계 7.1 12단계, 메인, 큐를 거치지 않는다). queue.lock 안에서 미룬 요청(after 가 있고
    started_at·결과가 없다)이면 요청 파일과 .abandoned 를 지운다. 관제는 같은 잠금 안에서 다시 읽고 started_at 을 쓰므로
    cancelled 를 받은 요청은 실행되지 않는다. 메인 확인은 부르는 쪽(_cmd_cancel)이 한다."""
    gone = HteamError("unknown_request", f"{rid} 요청이 큐에 없다(이미 끝났거나 취소했다)", USAGE,
                      "hteam status 의 deferred 에서 요청 id 를 본다")
    if not RID_RE.fullmatch(rid):
        raise gone
    path = _request_path(p, rid)
    with flock(p.queue_lock):
        finished = _result_path(path).exists()
        if not path.exists() and not finished:
            raise gone
        req = read_json(path, None)
        if finished or not isinstance(req, dict) or not _is_deferred(req):
            raise HteamError("not_deferred", f"{rid} 는 미룬 요청이 아니다(이미 시작했거나 결과가 있거나 --after 가 없다)",
                             CONFLICT, "시작한 요청은 거두지 않는다. 결과를 기다린다")
        path.unlink(missing_ok=True)
        _abandoned_path(path).unlink(missing_ok=True)
    return {"request": rid, "cancelled": True}


# --- CLI ---
def _cmd_test_confirm(args) -> dict:
    p = find_project(args.root)
    return route(p, "test-confirm", {}, lambda req: drive.Drive(p).confirm_test(force=True),
                 check=lambda: testgate.require_config(p))


def _cmd_cancel(args) -> dict:
    p = find_project(args.root)
    outbox.require_main(p)  # 메인 전용(answer·reask 와 같다). 관제·워커는 무엇이든 지우기 전에 거부한다
    return cancel(p, args.request)


def register(sub) -> None:
    sub.add_parser("test-confirm").set_defaults(func=_cmd_test_confirm)
    s = sub.add_parser("cancel")
    s.add_argument("request", help="미룬 요청 id(q-NNNNNN. hteam status 의 deferred, 설계 7.1 12단계)")
    s.set_defaults(func=_cmd_cancel)
