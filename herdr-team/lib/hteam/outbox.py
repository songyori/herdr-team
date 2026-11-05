"""메인과 코디네이터의 연결(설계 7장): tell, notify(outbox), watch, render 검사, answer, applied, reask.

이 명령들은 설정을 읽지 않는다(설계 4.2). 설정이 깨져도 동작한다.
"""
from __future__ import annotations

import json
import os
import sys
import time

from . import herdr, procs, roles, state
from .errors import CONFLICT, DENIED, USAGE, HteamError
from .horch import Horch
from .paths import find_project
from .util import env_float, flock, now, read_json, write_atomic, write_json

TYPES = ("progress", "question", "approval", "done")
RENDER_KEYS = {"header", "question", "context", "options", "multiSelect"}


def validate_render(obj, default_header: str) -> dict:
    """설계 7.4 형식. 어기면 exit 2(bad_render, errors 목록)."""
    if not isinstance(obj, dict):
        raise HteamError("bad_render", "질문은 JSON 객체다", USAGE)
    errors = [f"모르는 필드: {k}" for k in sorted(set(obj) - RENDER_KEYS)]
    header = obj.get("header", default_header)
    if not isinstance(header, str) or not header.strip() or len(header) > 12:
        errors.append("header 는 12자 이하 문자열이다")
    question = obj.get("question")
    lines = question.split("\n") if isinstance(question, str) else []
    if len(lines) != 2:
        errors.append("question 은 '한 줄 질문\\n예: 보기' 두 줄이다")
    else:
        if not lines[0].strip() or len(lines[0]) > 300:
            errors.append("question 첫 줄은 300자 이하 한 줄 질문이다")
        if not lines[1].startswith("예: ") or not lines[1][3:].strip() or len(lines[1]) - 3 > 300:
            errors.append("question 둘째 줄은 '예: ' 로 시작하는 300자 이하 보기다")
    context = obj.get("context")
    if context is not None and (not isinstance(context, str) or len(context) > 4000):
        errors.append("context 는 4000자 이하 문자열이다")
    options = obj.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= 4:
        errors.append("options 는 2–4개다")
    else:
        labels = []
        for i, opt in enumerate(options):
            label = opt.get("label") if isinstance(opt, dict) else None
            desc = opt.get("description") if isinstance(opt, dict) else None
            if not isinstance(label, str) or not label.strip() or len(label) > 30:
                errors.append(f"options[{i}].label 은 30자 이하 문자열이다")
            if not isinstance(desc, str) or not desc.strip():
                errors.append(f"options[{i}].description 이 없다")
            labels.append(label)
        first = options[0] if isinstance(options[0], dict) else {}
        if not str(first.get("label", "")).endswith("(추천)"):
            errors.append("추천안이 맨 앞이고 label 이 '(추천)' 으로 끝난다")
        if not str(first.get("description", "")).startswith("추천 사유:"):
            errors.append("추천안 description 은 '추천 사유:' 로 시작한다")
        if len(set(map(str, labels))) != len(labels):
            errors.append("options label 이 겹친다")
    if obj.get("multiSelect", False) is not False:
        errors.append("multiSelect 는 false 다")
    if errors:
        raise HteamError("bad_render", "질문 형식이 틀렸다: " + "; ".join(errors), USAGE, data={"errors": errors})
    out = {"header": header, "question": question, "options": options, "multiSelect": False}
    if context:
        out["context"] = context
    return out


def read_render(text: str, default_header: str) -> dict:
    try:
        obj = json.loads(text)
    except ValueError as exc:
        raise HteamError("bad_render", f"질문 JSON 을 읽지 못했다: {exc}", USAGE) from exc
    return validate_render(obj, default_header)


def read_outbox(p) -> list[dict]:
    try:
        lines = p.outbox.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    return [json.loads(line) for line in lines if line.strip()]


def append(p, fields: dict, guard=None) -> dict:
    """outbox 에 flock 으로 한 줄을 더한다. guard(entries) 는 같은 잠금 안에서 먼저 부른다."""
    p.ensure_state()
    with flock(p.state / "outbox.lock"):
        entries = read_outbox(p)
        if guard is not None:
            guard(entries)
        entry = {"id": f"out-{len(entries) + 1:04d}", "at": now(), **fields, "answered": False}
        with p.outbox.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return entry


def cursor(p) -> int:
    try:
        return int(p.cursor.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def answer_of(p, oid: str) -> dict | None:
    return read_json(p.answers / f"{oid}.json", None)


def view(p, entry: dict) -> dict:
    return {**entry, "answered": answer_of(p, entry["id"]) is not None}


def open_questions(p) -> list[dict]:
    """답이 없는 ask(묻는 태스크가 아직 working)와 답이 없는 question·approval(설계 7.6)."""
    found = []
    for e in read_outbox(p):
        if e.get("type") not in ("ask", "question", "approval") or answer_of(p, e["id"]):
            continue
        if e["type"] == "ask":
            st = state.load(p, e.get("from", ""))
            if not st or st["status"] != "working":
                continue
        found.append(view(p, e))
    return found


def _run_id(p) -> str:
    run_id = read_json(p.run_file, {}).get("run_id")
    if not run_id:
        raise HteamError("no_run", "코디네이터 Run 이 아직 없다", CONFLICT, "hteam up 으로 코디네이터를 띄운다")
    return run_id


def note_main(p) -> str:
    """메인 터미널을 run.json 의 main_terminals 에 남긴다. wait 가 `[main]` 글의 발신자를 이것으로 확인한다.

    목록은 줄이지 않는다: 지운 터미널의 아직 처리하지 않은 메시지가 메인이 아닌 것으로 보이면 안 된다(Run 동안 몇 개뿐이다)."""
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        raise HteamError("no_terminal", "Herdr 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
    p.ensure_state()
    with flock(p.state / "run.lock"):
        run = read_json(p.run_file, {}) or {}
        mains = list(run.get("main_terminals") or [])
        if term not in mains:
            run["main_terminals"] = mains + [term]
        write_json(p.run_file, run)
    return term


def tell(p, text: str) -> dict:
    """메인 → 코디네이터(설계 7.1). 메인은 Run 소유자가 아니므로 외부 발신자다."""
    note_main(p)
    first = (text.strip().splitlines() or [""])[0][:60]
    out = Horch(p.horch_home).ok("send", "--to", f"run:{_run_id(p)}", "--subject", f"[main] {first}", "--body", text)
    return {"message": out["message"], "wake": out.get("wake")}


def notify(p, kind: str, body: str | None, json_text: str | None) -> dict:
    if kind in ("question", "approval"):
        if json_text is None:
            raise HteamError("usage", f"--type {kind} 는 --json - 로 질문(render)을 준다", USAGE)
        fields = {"type": kind, "render": read_render(json_text, "질문" if kind == "question" else "승인"),
                  "from": "coordinator"}
    else:
        if not body:
            raise HteamError("usage", f"--type {kind} 는 --body 가 필요하다", USAGE)
        fields = {"type": kind, "body": body, "from": "coordinator"}
    entry = append(p, fields)
    return {"id": entry["id"], "type": kind}


def _orphaned(p) -> bool:
    run = read_json(p.run_file, {})
    term = run.get("coordinator_terminal")
    return bool(term) and herdr.probe(term, run.get("coordinator_argv")) in ("exited", "lost")


def watch(p) -> dict:
    """2초마다 outbox 를 본다. 새 항목이 있으면 출력하고(그 뒤 커서를 옮긴다) 끝난다. 코디네이터가 없으면 orphaned."""
    p.ensure_state()
    rec = read_json(p.watch_pid, None)
    if procs.record_alive(rec) and rec.get("pid") != os.getpid():
        raise HteamError("watch_running", f"watch 가 이미 돈다(pid {rec['pid']})", CONFLICT, data={"pid": rec["pid"]})
    write_json(p.watch_pid, procs.me())
    poll, every = env_float("HTEAM_POLL", 2.0), env_float("HTEAM_ORPHAN_CHECK", 10.0)
    last = 0.0
    try:
        while True:
            entries, cur = read_outbox(p), cursor(p)
            if len(entries) > cur:
                total = len(entries)
                return {"messages": [view(p, e) for e in entries[cur:]], "count": total - cur,
                        "_after": lambda: write_atomic(p.cursor, f"{total}\n")}
            if time.monotonic() - last >= every:
                last = time.monotonic()
                if _orphaned(p):
                    return {"status": "orphaned", "messages": [], "count": 0}
            time.sleep(poll)
    finally:
        if (read_json(p.watch_pid, None) or {}).get("pid") == os.getpid():
            p.watch_pid.unlink(missing_ok=True)


def watch_alive(p) -> bool:
    return procs.record_alive(read_json(p.watch_pid, None))


def _link_answer(p, oid: str, text: str) -> bool:
    """답 파일을 원자적으로 만든다(os.link). 이미 있으면 False."""
    p.ensure_state()
    path = p.answers / f"{oid}.json"
    tmp = p.answers / f".{oid}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"id": oid, "answer": text, "at": now()}, ensure_ascii=False), encoding="utf-8")
    try:
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    finally:
        tmp.unlink(missing_ok=True)


def answer(p, oid: str, text: str) -> dict:
    entry = next((e for e in read_outbox(p) if e["id"] == oid), None)
    if entry is None:
        raise HteamError("unknown_question", f"outbox 에 {oid} 가 없다", USAGE)
    if entry["type"] not in ("ask", "question", "approval"):
        raise HteamError("not_a_question", f"{oid} 는 {entry['type']} 라 답할 수 없다", USAGE)
    if entry["type"] == "ask":
        if not _link_answer(p, oid, text):
            raise HteamError("already_answered", f"{oid} 에는 이미 답했다", CONFLICT)
        return {"id": oid, "type": "ask", "delivered": "file"}
    if not _link_answer(p, oid, text) and answer_of(p, oid)["answer"] != text:
        raise HteamError("already_answered", f"{oid} 에는 이미 다른 답을 했다", CONFLICT)
    note_main(p)
    out = Horch(p.horch_home).ok("send", "--to", f"run:{_run_id(p)}", "--subject", f"[main] reply {oid}",
                                 "--body", text)  # 다시 실행하면 같은 답을 다시 보낸다(적어도 한 번)
    return {"id": oid, "type": entry["type"], "sent": True, "message": out["message"]}


def applied_ids(p) -> dict:
    return read_json(p.applied, {}) or {}


def mark_applied(p, oid: str) -> dict:
    p.ensure_state()
    with flock(p.state / "applied.lock"):
        data = applied_ids(p)
        data.setdefault(oid, now())
        write_json(p.applied, data)
    return {"id": oid, "applied": True}


def reask(p) -> dict:
    """이미 출력된(커서 앞) 열린 질문을 다시 낸다. 아직 전하지 않은 것은 watch 가 준다."""
    index = {e["id"]: i for i, e in enumerate(read_outbox(p))}
    cur = cursor(p)
    return {"messages": [q for q in open_questions(p) if index[q["id"]] < cur]}


def _cmd_tell(args) -> dict:
    return tell(find_project(args.root), args.text)


def _cmd_notify(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    text = sys.stdin.read() if args.json == "-" else args.json
    return notify(p, args.type, args.body, text)


def _cmd_watch(args) -> dict:
    return watch(find_project(args.root))


def _cmd_answer(args) -> dict:
    return answer(find_project(args.root), args.id, args.text)


def _cmd_applied(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return mark_applied(p, args.id)


def _cmd_reask(args) -> dict:
    return reask(find_project(args.root))


def register(sub) -> None:
    s = sub.add_parser("tell")
    s.add_argument("text")
    s.set_defaults(func=_cmd_tell)
    s = sub.add_parser("notify")
    s.add_argument("--type", required=True, choices=TYPES)
    body = s.add_mutually_exclusive_group(required=True)
    body.add_argument("--body")
    body.add_argument("--json", help="'-' 면 표준 입력")
    s.set_defaults(func=_cmd_notify)
    sub.add_parser("watch").set_defaults(func=_cmd_watch)
    s = sub.add_parser("answer")
    s.add_argument("id")
    s.add_argument("text")
    s.set_defaults(func=_cmd_answer)
    s = sub.add_parser("applied")
    s.add_argument("id")
    s.set_defaults(func=_cmd_applied)
    sub.add_parser("reask").set_defaults(func=_cmd_reask)
