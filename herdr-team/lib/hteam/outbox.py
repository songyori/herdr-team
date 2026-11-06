"""메인과 코디네이터의 연결(설계 7장): tell, notify(outbox), watch, render 검사, answer, applied, reask.

이 명령들은 설정을 읽지 않는다(설계 4.2). 설정이 깨져도 동작한다.

outbox(`state/outbox.jsonl`)는 LF 로 끝나는 JSON 줄이다. 줄은 LF 로만 나눈다(본문의 U+2028 등은 경계가 아니다).
LF 로 끝나지 않은 마지막 조각은 쓰는 중이거나 쓰다 죽은 줄이라 읽지 않는다. 커서(`outbox.cursor`)와 ID 번호는
완결된 줄 수로 센다(읽지 못한 줄도 센다). 그래서 깨진 줄을 건너뛰어도 ID 를 다시 쓰지 않는다.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import time
import unicodedata

from . import herdr, procs, roles, state
from .errors import CONFLICT, DENIED, FAIL, USAGE, HteamError
from .horch import Horch
from .paths import SHIM, find_project
from .util import die_at, env_float, flock, now, read_json, write_atomic, write_json

TYPES = ("progress", "question", "approval", "done")
RENDER_KEYS = {"header", "question", "context", "options", "multiSelect"}
OPTION_KEYS = {"label", "description"}
DESCRIPTION_MAX = 300  # 질문 줄과 같은 상한. 선택지 설명으로 context(4000자) 상한을 돌아가지 못하게 한다
_REPLY_SUBJECT = re.compile(r"\s*reply\b", re.IGNORECASE)
PARENT_DEPTH = 10  # require_main 이 따라가는 hc parent 단계 상한


def _bad_chars(text: str, allow: str = "") -> bool:
    """제어 문자(Cc)나 줄·문단 구분자(Zl·Zp)가 있나(allow 의 글자는 뺀다).

    워커가 쓴 질문을 메인이 그대로 보여 주므로, 한 줄 필드에 줄을 꾸며 가짜 구조를 만들지 못하게 한다."""
    return any(ch not in allow and unicodedata.category(ch) in ("Cc", "Zl", "Zp") for ch in text)


def validate_render(obj, default_header: str) -> dict:
    """설계 7.4 형식. 어기면 exit 2(bad_render, errors 목록)."""
    if not isinstance(obj, dict):
        raise HteamError("bad_render", "질문은 JSON 객체다", USAGE)
    errors = [f"모르는 필드: {k}" for k in sorted(set(obj) - RENDER_KEYS)]
    header = obj.get("header", default_header)
    if not isinstance(header, str) or not header.strip() or len(header) > 12:
        errors.append("header 는 12자 이하 문자열이다")
    elif _bad_chars(header):
        errors.append("header 는 한 줄이다(줄바꿈·제어 문자 없음)")
    question = obj.get("question")
    lines = question.split("\n") if isinstance(question, str) else []
    if len(lines) != 2:
        errors.append("question 은 '한 줄 질문\\n예: 보기' 두 줄이다")
    else:
        if not lines[0].strip() or len(lines[0]) > 300:
            errors.append("question 첫 줄은 300자 이하 한 줄 질문이다")
        if not lines[1].startswith("예: ") or not lines[1][3:].strip() or len(lines[1]) - 3 > 300:
            errors.append("question 둘째 줄은 '예: ' 로 시작하는 300자 이하 보기다")
        if _bad_chars(lines[0]) or _bad_chars(lines[1]):
            errors.append("question 의 두 줄에는 다른 줄바꿈·제어 문자가 없다")
    context = obj.get("context")
    if context is not None and (not isinstance(context, str) or len(context) > 4000):
        errors.append("context 는 4000자 이하 문자열이다")
    elif isinstance(context, str) and _bad_chars(context, allow="\n\t"):
        errors.append("context 에는 줄바꿈·탭 말고 제어 문자가 없다")
    options = obj.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= 4:
        errors.append("options 는 2–4개다")
    else:
        labels = []
        for i, opt in enumerate(options):
            if isinstance(opt, dict):
                errors += [f"options[{i}] 모르는 필드: {k}" for k in sorted(set(opt) - OPTION_KEYS)]
            label = opt.get("label") if isinstance(opt, dict) else None
            desc = opt.get("description") if isinstance(opt, dict) else None
            if not isinstance(label, str) or not label.strip() or len(label) > 30:
                errors.append(f"options[{i}].label 은 30자 이하 문자열이다")
            elif _bad_chars(label):
                errors.append(f"options[{i}].label 은 한 줄이다(줄바꿈·제어 문자 없음)")
            if not isinstance(desc, str) or not desc.strip():
                errors.append(f"options[{i}].description 이 없다")
            elif len(desc) > DESCRIPTION_MAX:
                errors.append(f"options[{i}].description 은 {DESCRIPTION_MAX}자 이하다")
            elif _bad_chars(desc):
                errors.append(f"options[{i}].description 은 한 줄이다(줄바꿈·제어 문자 없음)")
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


def _parse(raw: bytes) -> tuple[int, list[tuple[int, dict]], list[int]]:
    """outbox 바이트 → (완결된 줄 수, [(줄 번호, 항목)], 읽지 못한 줄 번호). 마지막 LF 뒤 조각은 세지 않는다."""
    complete = raw.split(b"\n")[:-1]
    items, bad = [], []
    for n, line in enumerate(complete, 1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line.decode("utf-8"))
        except ValueError:  # UnicodeDecodeError 포함
            entry = None
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("type"), str):
            bad.append(n)
            continue
        items.append((n, entry))
    return len(complete), items, bad


def _scan(p) -> tuple[int, list[tuple[int, dict]], list[int]]:
    try:
        raw = p.outbox.read_bytes()
    except FileNotFoundError:
        raw = b""
    return _parse(raw)


def _bad_warnings(bad: list[int]) -> list[str]:
    return [f"outbox {n}번째 줄을 읽지 못해 건너뛰었다" for n in bad]


def read_outbox(p) -> list[dict]:
    """읽을 수 있는 항목만(깨진 줄과 쓰는 중인 마지막 조각은 뺀다)."""
    return [e for _, e in _scan(p)[1]]


def append(p, fields: dict, guard=None, reuse=None) -> dict:
    """outbox 에 flock 으로 한 줄을 더한다. guard(entries) 는 같은 잠금 안에서 먼저 부른다. reuse(entries) 가 항목을
    돌려주면 쓰지 않고 그 항목을 돌려준다(이미 쓴 같은 항목. 끊긴 마지막 줄을 완결한 뒤에 보므로 LF 만 빠진 항목도 찾는다).

    ID 는 완결된 줄 수 + 1 이다. 앞 쓰기가 줄 중간에서 끊겼으면(쓰는 쪽은 늘 이 잠금을 쥐므로 잠금 안에서 본 LF 없는
    끝은 죽은 쓰기다) guard 보다 먼저 LF 를 써서 남긴다. 그래야 guard(중복 검사)와 잠금 없이 읽는 쪽이 같은 줄을 본다."""
    p.ensure_state()
    with flock(p.state / "outbox.lock"):
        try:
            raw = p.outbox.read_bytes()
        except FileNotFoundError:
            raw = b""
        if raw and not raw.endswith(b"\n"):
            _write(p, b"\n")
            raw += b"\n"
        count, items, _ = _parse(raw)
        entries = [e for _, e in items]
        if guard is not None:
            guard(entries)
        if reuse is not None:
            found = reuse(entries)
            if found is not None:
                return found
        entry = {"id": f"out-{count + 1:04d}", "at": now(), **fields, "answered": False}
        _write(p, (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
    return entry


def _write(p, data: bytes) -> None:
    with p.outbox.open("ab") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def cursor(p) -> int:
    """watch 가 메인에 전한 완결된 줄 수."""
    try:
        return int(p.cursor.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0


def unread(p) -> int:
    """커서 뒤 완결된 줄 수(읽지 못한 줄도 센다. ID·커서와 같은 기준). 쓰는 중인 마지막 조각은 세지 않는다."""
    return max(0, _scan(p)[0] - cursor(p))


def answer_of(p, oid: str) -> dict | None:
    return read_json(p.answers / f"{oid}.json", None)


def _unsent(entry: dict, ans: dict | None) -> bool:
    """question·approval 의 답을 남겼지만 코디네이터에게 보냈다는 기록(sent_at)이 없다."""
    return entry.get("type") in ("question", "approval") and bool(ans) and not ans.get("sent_at")


def view(p, entry: dict) -> dict:
    ans = answer_of(p, entry["id"])
    out = {**entry, "answered": ans is not None}
    if _unsent(entry, ans):
        out.update(unsent=True, answer=ans.get("answer"),
                   hint=f"답을 남겼지만 코디네이터에게 보내지 못했다. `{SHIM} answer {entry['id']} \"<같은 답>\"` 으로 "
                        "같은 답을 다시 보낸다")
    return out


def _open(p, items: list[tuple[int, dict]], warnings: list[str]) -> list[tuple[int, dict]]:
    found = []
    for n, e in items:
        if e["type"] not in ("ask", "question", "approval"):
            continue
        ans = answer_of(p, e["id"])
        if ans and not _unsent(e, ans):
            continue
        if e["type"] == "ask":
            try:
                st = state.load(p, e.get("from", ""))
            except HteamError as exc:  # 손상된 상태 파일 하나로 열린 질문 전체가 막히지 않게 한다
                warnings.append(f"{e['id']}: {e.get('from')} 상태를 읽지 못해 열린 질문에서 뺐다({exc.code})")
                continue
            if not st or st.get("status") != "working":
                continue
        found.append((n, view(p, e)))
    return found


def open_questions(p, warnings: list | None = None) -> list[dict]:
    """답이 없는 ask(묻는 태스크가 아직 working)와 답이 없거나 보내지 못한 question·approval(설계 7.6).

    warnings 를 주면 읽지 못한 outbox 줄과 상태 파일 경고를 덧붙인다."""
    _, items, bad = _scan(p)
    sink = warnings if warnings is not None else []
    sink.extend(_bad_warnings(bad))
    return [q for _, q in _open(p, items, sink)]


def _bad_run(why: str) -> HteamError:
    return HteamError("bad_run_file", f"run.json 을 읽지 못했다: {why}", FAIL,
                      "파일을 직접 고치거나 치운 뒤 hteam up 으로 다시 만든다")


def _run(p) -> dict:
    """run.json. 없으면 {}. 있는데 읽지 못하면 bad_run_file(덮어쓰지 않는다)."""
    try:
        text = p.run_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise _bad_run(str(exc)) from None
    try:
        run = json.loads(text)
    except ValueError as exc:
        raise _bad_run(f"JSON 이 아니다: {exc}") from None
    if not isinstance(run, dict):
        raise _bad_run("JSON 객체가 아니다")
    return run


def _run_id(p) -> str:
    run_id = _run(p).get("run_id")
    if not run_id:
        raise HteamError("no_run", "코디네이터 Run 이 아직 없다", CONFLICT, "hteam up 으로 코디네이터를 띄운다")
    return run_id


def _terminal() -> str:
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        raise HteamError("no_terminal", "Herdr 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
    return term


def require_main(p) -> str:
    """메인 터미널에서 불렀는지 확인한다(tell·answer·watch·reask 가 무엇이든 쓰기 전에 부른다). 실수 방지용이다(설계 8.3).

    코디네이터(HTEAM_ROLE·run.json 의 터미널·horch Run 소유자·hc 라벨 hteam.role)와 워커·리뷰어는 메인이 아니다. horch status 는
    launching·active Dispatch 만 알려 주므로, 끝난 Dispatch 의 터미널은 horch 가 워커 터미널을 띄울 때 붙이는 hc 라벨
    (horch.dispatch)로 가린다. horch worker-list 는 Run 소유자 터미널에서만 되므로 메인에서 부를 수 없다.
    확인할 수 없으면 거부한다(exit 1 main_unverified)."""
    term = _terminal()
    hint = "메인 세션 터미널에서 실행한다. 코디네이터·워커는 horch 로 주고받는다"
    if os.environ.get("HTEAM_ROLE") == "coordinator" or term == _run(p).get("coordinator_terminal"):
        raise HteamError("not_main", "코디네이터는 이 명령을 부르지 않는다(메인 전용)", DENIED, hint)
    code, data = Horch(p.horch_home).call("status")
    if code != 0 or not data.get("ok"):
        err = data.get("error") or {}
        raise HteamError("main_unverified", f"horch status 로 이 터미널({term})을 확인하지 못했다: {err.get('code')}",
                         FAIL, "다시 시도한다")
    if data.get("dispatch") or data.get("run"):
        who = "워커" if data.get("dispatch") else "Run 소유자(코디네이터)"
        raise HteamError("not_main", f"{term} 은 {who} 터미널이다(메인 전용)", DENIED, hint)
    # 이 터미널과 hc parent 조상(기본 `hc run` 은 띄운 터미널을 parent 로 남긴다)의 라벨을 본다. --no-parent 로 띄운
    # 자식은 못 가린다(실수 방지용, 설계 14장). 조상을 끝까지 따라가지 못하면(hc 실패·순환·너무 깊음) 확인 불가다.
    node, seen = term, {term}
    for depth in range(PARENT_DEPTH + 1):
        info = _hc_info(node, term)
        labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
        where = term if node == term else f"{term}(조상 {node} 아래에서 띄움)"
        if labels.get("horch.dispatch"):
            raise HteamError("not_main", f"{where} 은 horch 가 띄운 워커 터미널이다(메인 전용)", DENIED, hint)
        if labels.get("hteam.role") == "coordinator":  # bind 전이라 run.json·horch 가 아직 모르는 코디네이터(설계 9.3)
            raise HteamError("not_main", f"{where} 은 hteam up 이 띄운 코디네이터 터미널이다(메인 전용)", DENIED, hint)
        parent = _parent_ref(info.get("parent"))
        if not parent:
            return term
        if parent in seen or depth == PARENT_DEPTH:
            raise HteamError("main_unverified", f"{term} 의 parent 를 끝까지 따라가지 못했다(순환이거나 {PARENT_DEPTH}단계 넘음)",
                             FAIL, "메인 세션 터미널에서 실행한다")
        seen.add(parent)
        node = parent
    return term


def _parent_ref(value) -> str | None:
    """hc get 의 parent(띄운 터미널 주소). 모르는 모양이면 따라가지 않는다."""
    if isinstance(value, dict):
        value = value.get("address")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _hc_info(node: str, term: str) -> dict:
    try:
        return herdr.get(node)
    except HteamError as exc:
        what = "이 터미널" if node == term else f"조상 터미널 {node}"
        raise HteamError("main_unverified", f"hc 로 {what}({term})을 확인하지 못했다: {exc.message}", FAIL,
                         "다시 시도한다") from None


def note_main(p) -> str:
    """메인 터미널을 run.json 의 main_terminals 에 남긴다. wait 가 `[main]` 글의 발신자를 이것으로 확인한다.

    목록은 줄이지 않는다: 지운 터미널의 아직 처리하지 않은 메시지가 메인이 아닌 것으로 보이면 안 된다(Run 동안 몇 개뿐이다).
    run.json 을 읽지 못하면 덮어쓰지 않고 bad_run_file 이다."""
    term = _terminal()
    p.ensure_state()
    with flock(p.state / "run.lock"):
        run = _run(p)
        mains = list(run.get("main_terminals") or [])
        if term not in mains:
            run["main_terminals"] = mains + [term]
            write_json(p.run_file, run)
    return term


def _send(p, run_id: str, subject: str, body: str) -> dict:
    """Run 메일함에 보낸다. 값은 `--옵션=값` 한 인자로 넘긴다(`-` 로 시작하는 글이 horch 옵션으로 읽히지 않게)."""
    return Horch(p.horch_home).ok("send", f"--to=run:{run_id}", f"--subject={subject}", f"--body={body}")


def tell(p, text: str) -> dict:
    """메인 → 코디네이터(설계 7.1). 메인은 Run 소유자가 아니므로 외부 발신자다."""
    require_main(p)
    run_id = _run_id(p)
    note_main(p)
    first = (text.strip().splitlines() or [""])[0][:60]
    if _REPLY_SUBJECT.match(first):
        first = f"지시: {first}"  # 답 제목(`[main] reply <out-id>`)으로 읽히지 않게
    out = _send(p, run_id, f"[main] {first}", text)
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
    run = _run(p)  # 읽지 못하면 bad_run_file(watch 가 그 오류로 끝난다)
    term = run.get("coordinator_terminal")
    return bool(term) and herdr.probe(term, run.get("coordinator_argv")) in ("exited", "lost")


def _lock_watch(p):
    """watch 단일 실행 잠금(state/watch.lock). 잡으면 열린 파일을 돌려준다. 다른 watch 가 쥐고 있으면 watch_running."""
    fh = open(p.state / "watch.lock", "a+")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        pid = (read_json(p.watch_pid, None) or {}).get("pid")
        raise HteamError("watch_running", f"watch 가 이미 돈다(pid {pid or '모름'})", CONFLICT, data={"pid": pid}) from None
    return fh


def _unlock_watch(p, fh) -> None:
    try:
        if (read_json(p.watch_pid, None) or {}).get("pid") == os.getpid():
            p.watch_pid.unlink(missing_ok=True)
    finally:
        fh.close()  # 닫으면 flock 이 풀린다


def watch(p) -> dict:
    """2초마다 outbox 를 본다. 새 줄이 있으면 출력하고 끝난다. 코디네이터 터미널이 끝났으면 orphaned.

    커서는 출력한 뒤(_after)에 옮긴다(적어도 한 번 전달). 단일 실행 잠금은 커서를 옮길 때까지 쥔다: 그 사이에 다른 watch 가
    떠서 같은 항목을 다시 주지 않게 한다. watch.pid 는 생사 확인(watch_alive)용 기록일 뿐이다."""
    p.ensure_state()
    fh = _lock_watch(p)
    handed = False
    try:
        write_json(p.watch_pid, procs.me())
        poll, every = env_float("HTEAM_POLL", 2.0), env_float("HTEAM_ORPHAN_CHECK", 10.0)
        last = 0.0
        while True:
            count, items, bad = _scan(p)
            cur = cursor(p)
            if count > cur:
                messages = [view(p, e) for n, e in items if n > cur]

                def after() -> None:
                    try:
                        die_at("watch_before_cursor")
                        write_atomic(p.cursor, f"{count}\n")
                    finally:
                        _unlock_watch(p, fh)

                out = {"messages": messages, "count": len(messages), "_after": after}
                fresh_bad = [n for n in bad if n > cur]
                if fresh_bad:
                    out["warnings"] = _bad_warnings(fresh_bad)
                handed = True
                return out
            if time.monotonic() - last >= every:
                last = time.monotonic()
                if _orphaned(p):
                    return {"status": "orphaned", "messages": [], "count": 0}
            time.sleep(poll)
    finally:
        if not handed:
            _unlock_watch(p, fh)


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


def _entry(p, oid: str) -> dict:
    entry = next((e for e in read_outbox(p) if e["id"] == oid), None)
    if entry is None:
        raise HteamError("unknown_question", f"outbox 에 {oid} 가 없다", USAGE)
    return entry


def answer(p, oid: str, text: str) -> dict:
    """메인의 답(설계 7.4). 메인 확인을 어떤 쓰기보다 먼저 한다.

    question·approval 은 답 파일을 먼저 남기고 보낸 뒤 sent_at 을 적는다. 보내지 못하면 sent_at 이 없어 열린 질문에
    unsent 로 남는다. 같은 답으로 다시 실행하면 다시 보낸다(적어도 한 번)."""
    require_main(p)
    entry = _entry(p, oid)
    if entry["type"] not in ("ask", "question", "approval"):
        raise HteamError("not_a_question", f"{oid} 는 {entry['type']} 라 답할 수 없다", USAGE)
    if entry["type"] == "ask":
        if not _link_answer(p, oid, text):
            raise HteamError("already_answered", f"{oid} 에는 이미 답했다", CONFLICT)
        return {"id": oid, "type": "ask", "delivered": "file"}
    previous = answer_of(p, oid)
    if previous is not None and previous.get("answer") != text:
        raise HteamError("already_answered", f"{oid} 에는 이미 다른 답을 했다", CONFLICT)
    run_id = _run_id(p)
    note_main(p)
    if not _link_answer(p, oid, text) and (answer_of(p, oid) or {}).get("answer") != text:
        raise HteamError("already_answered", f"{oid} 에는 이미 다른 답을 했다", CONFLICT)
    out = _send(p, run_id, f"[main] reply {oid}", text)  # 다시 실행하면 같은 답을 다시 보낸다(적어도 한 번)
    write_json(p.answers / f"{oid}.json", {**(answer_of(p, oid) or {"id": oid, "answer": text}), "sent_at": now(),
                                          "message": out["message"]})
    return {"id": oid, "type": entry["type"], "sent": True, "message": out["message"]}


def applied_ids(p) -> dict:
    return read_json(p.applied, {}) or {}


def mark_applied(p, oid: str) -> dict:
    entry = _entry(p, oid)
    if entry["type"] not in ("question", "approval"):
        raise HteamError("not_a_question", f"{oid} 는 {entry['type']} 라 적용 기록을 남기지 않는다", USAGE)
    p.ensure_state()
    with flock(p.state / "applied.lock"):
        data = applied_ids(p)
        data.setdefault(oid, now())
        write_json(p.applied, data)
    return {"id": oid, "applied": True}


def reask(p) -> dict:
    """이미 출력된(커서 앞) 열린 질문을 다시 낸다. 아직 전하지 않은 것은 watch 가 준다. outbox 는 한 번만 읽는다."""
    _, items, bad = _scan(p)
    cur = cursor(p)
    warnings = _bad_warnings(bad)
    out = {"messages": [q for n, q in _open(p, items, warnings) if n <= cur]}
    if warnings:
        out["warnings"] = warnings
    return out


def _cmd_tell(args) -> dict:
    return tell(find_project(args.root), args.text)


def _cmd_notify(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    text = sys.stdin.read() if args.json == "-" else args.json
    return notify(p, args.type, args.body, text)


def _cmd_watch(args) -> dict:
    p = find_project(args.root)
    require_main(p)  # 코디네이터가 wait 와 헷갈려 부르면 잠금·커서를 건드리기 전에 거부한다
    return watch(p)


def _cmd_answer(args) -> dict:
    return answer(find_project(args.root), args.id, args.text)


def _cmd_applied(args) -> dict:
    p = find_project(args.root)
    roles.require_coordinator(p)
    return mark_applied(p, args.id)


def _cmd_reask(args) -> dict:
    p = find_project(args.root)
    require_main(p)
    return reask(p)


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
