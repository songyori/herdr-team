"""기획자·디렉터의 직접 질문(설계 7.5): `hteam ask-user`. 설정을 읽지 않는다."""
from __future__ import annotations

import sys
import time

from . import outbox, state
from .errors import CONFLICT, DENIED, TIMEOUT, USAGE, HteamError
from .horch import Horch
from .paths import SHIM, find_project
from .util import bad_side_file, env_float, flock, now, read_json_strict, write_json

ASK_ROLES = {"planner": "기획", "director": "디자인"}  # 직무 → 기본 header


def _entries(p, tid: str) -> list[dict]:
    return [e for e in outbox.read_outbox(p) if e.get("type") == "ask" and e.get("from") == tid]


def _entry(p, tid: str, oid: str) -> dict:
    entry = next((e for e in _entries(p, tid) if e["id"] == oid), None)
    if entry is None:
        raise HteamError("unknown_question", f"{tid} 의 질문 {oid} 가 없다", USAGE)
    return entry


def _acks(p) -> dict:
    """반영 기록(out-id → 시각). 없으면 {}. 읽지 못하면 bad_side_file 이다: 빈 기록으로 보면 ack 한 번이 기록 전체를 덮어써
    `--pending` 이 반영한 답을 다시 내고 워커가 다시 반영한다."""
    data = read_json_strict(p.ask_acks, {})
    if not isinstance(data, dict):
        raise bad_side_file(p.ask_acks, "JSON 객체가 아니다")
    return data


def _check_caller(p, st: dict) -> None:
    """이 태스크의 현재 작업 워커 터미널에서만 새 질문을 한다(실수 방지)."""
    work = st["rounds"][-1]["work"] if st.get("rounds") else {}
    code, data = Horch(p.horch_home).call("status")
    mine = (data.get("dispatch") or {}).get("id") if code == 0 else None
    if not mine or mine != work.get("dispatch"):
        raise HteamError("not_this_worker", f"{st['id']} 의 작업 워커 터미널이 아니다", DENIED,
                         "기획·디렉터 워커가 자기 pane 의 셸에서 부른다")


def wait_answer(p, tid: str, oid: str) -> dict:
    """답 파일을 2초마다 본다. 540초(Bash 도구 최대 600초 안)가 지나면 exit 4 waiting."""
    deadline = time.monotonic() + env_float("HTEAM_ASK_TIMEOUT", 540.0)
    poll = env_float("HTEAM_POLL", 2.0)
    while True:
        ans = outbox.answer_of(p, oid)
        if ans:
            return {"id": oid, "answer": ans["answer"], "answered_at": ans.get("at")}
        left = deadline - time.monotonic()
        if left <= 0:
            raise HteamError("timeout", f"{oid} 의 답이 아직 없다", TIMEOUT,
                             f"`{SHIM} ask-user --task {tid} --wait {oid}` 로 다시 기다린다(Bash timeout 600000)",
                             data={"status": "waiting", "id": oid})
        time.sleep(min(poll, left))


def ask(p, tid: str, text: str) -> dict:
    st = state.require(p, tid)
    if st.get("role") not in ASK_ROLES:
        raise HteamError("not_ask_role", f"{tid} 는 {st.get('role')} 직무다(ask-user 는 planner·director 만)", CONFLICT,
                         "다른 직무는 프리앰블의 horch ask 로 코디네이터에게 묻는다")
    if st["status"] != "working":
        raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(ask-user 는 working 에서)", CONFLICT)
    _check_caller(p, st)
    render = outbox.read_render(text, ASK_ROLES[st["role"]])

    def one_open(entries: list[dict]) -> None:
        for e in entries:
            if e.get("type") == "ask" and e.get("from") == tid and not outbox.answer_of(p, e["id"]):
                raise HteamError("question_open", f"{tid} 에 답을 기다리는 질문 {e['id']} 가 있다", CONFLICT,
                                 f"`{SHIM} ask-user --task {tid} --wait {e['id']}`", data={"id": e["id"]})

    entry = outbox.append(p, {"type": "ask", "from": tid, "round": st["round"], "render": render}, guard=one_open)
    return wait_answer(p, tid, entry["id"])


def ack(p, tid: str, oid: str) -> dict:
    """답을 문서에 적었다는 기록. 새 질문과 같이 이 태스크의 현재 작업 워커 터미널에서만 한다."""
    _check_caller(p, state.require(p, tid))
    _entry(p, tid, oid)
    if not outbox.answer_of(p, oid):
        raise HteamError("not_answered", f"{oid} 에 아직 답이 없다", CONFLICT)
    p.ensure_state()
    with flock(p.state / "ask-acks.lock"):
        data = _acks(p)
        data.setdefault(oid, now())
        write_json(p.ask_acks, data)
    return {"id": oid, "acked": True}


def _item(p, e: dict, acks: dict) -> dict:
    ans = outbox.answer_of(p, e["id"])
    return {"id": e["id"], "round": e.get("round"), "question": e["render"]["question"],
            "answer": ans["answer"] if ans else None, "acked": e["id"] in acks}


def pending(p, tid: str) -> dict:
    """답이 왔지만 ack 되지 않은 질문. 수정 라운드의 워커가 먼저 확인한다."""
    acks = _acks(p)
    return {"pending": [i for i in (_item(p, e, acks) for e in _entries(p, tid)) if i["answer"] is not None
                        and not i["acked"]]}


def history(p, tid: str) -> dict:
    """이 태스크의 모든 질문과 답(이전 라운드 포함). render 는 메인이 사용자에게 보인 질문 그대로다(context·선택지)."""
    acks = _acks(p)
    return {"history": [{**_item(p, e, acks), "render": e["render"]} for e in _entries(p, tid)]}


def _cmd(args) -> dict:
    p = find_project(args.root)
    tid = args.task
    if args.json is not None:
        return ask(p, tid, sys.stdin.read() if args.json == "-" else args.json)
    if args.wait:
        _entry(p, tid, args.wait)
        return wait_answer(p, tid, args.wait)
    if args.ack:
        return ack(p, tid, args.ack)
    if args.pending:
        return pending(p, tid)
    return history(p, tid)


def register(sub) -> None:
    s = sub.add_parser("ask-user")
    s.add_argument("--task", required=True)
    mode = s.add_mutually_exclusive_group(required=True)
    mode.add_argument("--json", help="'-' 면 표준 입력")
    mode.add_argument("--wait", metavar="ID")
    mode.add_argument("--ack", metavar="ID")
    mode.add_argument("--pending", action="store_true")
    mode.add_argument("--history", action="store_true")
    s.set_defaults(func=_cmd)
