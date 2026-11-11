"""메인 → 관제 요청 큐(설계 7.1, 8.3 의 큐 명령, 8.5 의 틱 3).

메인은 horch 를 부르지 않는다. horch 를 건드리는 메인 명령(큐 명령)은 `state/drive/queue/` 의 요청 파일로 관제에 넘기고,
관제(와 그 자식)에서 부르면 그 자리에서 실행한다(route).

메인 쪽(submit): 메인 쪽 검사(부르는 쪽) → 관제 생존 → queue.lock 안에서 번호와 요청 파일 → 결과 파일을 0.2초마다 90초까지
기다린다. 넘거나 신호로 끊기면 `.abandoned` 를 남기고(결과가 이미 와 있으면 outbox result 로 옮기고) 돌아온다.

관제 쪽(run_pending): 틱마다 번호순으로 모두 실행한다. 실행 직전 요청 파일에 started_at 을 쓰고, 큐 요청이 바꾼 기록에는
request 를 남긴다. 다시 뜬 관제는 started_at 이 있고 결과가 없는 요청을 그 기록으로 복구하거나(recorded) 다시 실행한다.
관제 안의 fix·accept·drop 이 리뷰 관문의 finish 잠금을 만나면(review_busy) 그 요청을 미룬다(8.5).

queue.lock 안에서는 outbox 잠금(그 안에서 다른 잠금을 잡지 않는 잎 잠금)만 잡는다.
"""
from __future__ import annotations

import re
import signal
import time

from . import drive, outbox, roles, state, testgate, workspace
from .errors import FAIL, MISSING, HteamError
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

FILE_RE = re.compile(r"^(\d{6})\.(?:json|result\.json|abandoned)$")  # 번호를 세는 파일
REQUEST_RE = re.compile(r"^\d{6}\.json$")


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
def route(p, command: str, args: dict, execute, *, check=None, expect_round=None) -> dict:
    """큐 명령의 길(설계 7.1, 8.3). 관제(그 자식 포함)면 execute(None) 를 그 자리에서, 메인이면 require_main → check() →
    submit. expect_round() 는 ROUND_COMMANDS 가 메인 쪽 검사 뒤 본 라운드다."""
    if roles.drive_env(p):
        return execute(None)
    outbox.require_main(p)
    if check is not None:
        check()
    return submit(p, command, args, expect_round=expect_round() if expect_round is not None else None)


def _signal_exit(code: int):
    def handler(*_):
        raise SystemExit(code)
    return handler


def submit(p, command: str, args: dict, *, expect_round: int | None = None) -> dict:
    """관제 생존을 보고 요청을 쓴 뒤 결과를 기다린다(설계 7.1 순서 2–6). 관제 결과(성공이면 그 결과, 실패면 그 code·exit 의
    HteamError) 또는 {"status": "queued", "request", "message"}."""
    live = drive.liveness(p)
    if live["hung"]:
        raise HteamError("drive_hung", HUNG_MESSAGE, FAIL)
    if not live["alive"]:
        raise HteamError("drive_down", DOWN_MESSAGE, FAIL)
    req: dict = {"id": None, "command": command, "args": args, "at": now()}
    if expect_round is not None:
        req["expect_round"] = expect_round
    with flock(p.queue_lock):
        n = _next_number(p)
        write_atomic(p.queue_seq, f"{n + 1}\n")
        req["id"] = f"q-{n:06d}"
        write_json(_request_path(p, req["id"]), req)
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
                    request=req["id"], nowait=True, force=bool(a.get("force")))
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


def _finish(p, d, path, req: dict, outcome: dict) -> None:
    """결과를 쓴다: 메인이 기다리기를 그만뒀으면(.abandoned) outbox result, 아니면 결과 파일. 그다음 요청 파일을 지운다."""
    res, mark = _result_path(path), _abandoned_path(path)
    with flock(p.queue_lock):
        if mark.exists():
            _post_result(p, req, outcome)
            mark.unlink(missing_ok=True)
        else:
            write_json(res, outcome)
    die_at("queue_result_written")
    path.unlink(missing_ok=True)
    if outcome.get("ok"):
        d.log(f"요청 {req['id']} {req.get('command')}: 완료")
    else:
        err = outcome.get("error") or {}
        d.log(f"요청 {req['id']} {req.get('command')}: {err.get('code')}: {err.get('message')}")


def run_pending(p, d) -> list[str]:
    """틱 3(설계 7.1 "재실행 막기", 8.5). 남은 요청을 번호순으로 모두 실행(또는 기록으로 복구)하고 그 id 를 돌려준다.
    리뷰 관문 때문에 미룬 요청(review_busy)과 결과 파일만 남은 요청은 세지 않는다."""
    done: list[str] = []
    for path in _request_files(p):
        d.heartbeat()
        req = read_json(path, None)
        if _result_path(path).exists():  # 결과를 쓴 뒤 요청 파일을 지우기 전에 관제가 죽었다
            path.unlink(missing_ok=True)
            continue
        try:
            rec = recorded(p, req) if req.get("started_at") else None  # 실행을 시작한 뒤 결과 전에 관제가 죽었다
            if rec is not None:
                outcome = {"ok": True, "result": rec}
            else:
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


# --- CLI ---
def _cmd_test_confirm(args) -> dict:
    p = find_project(args.root)
    return route(p, "test-confirm", {}, lambda req: drive.Drive(p).confirm_test(force=True),
                 check=lambda: testgate.require_config(p))


def register(sub) -> None:
    sub.add_parser("test-confirm").set_defaults(func=_cmd_test_confirm)
