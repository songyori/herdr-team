"""메인과 관제의 연결(설계 7장): outbox(관제 → 메인), watch, render 검사, answer, reask.

0.4.0 에서 tell·notify·applied 를 없앴다. 메인 → 관제는 요청 큐(queue.py)이고, 관제는 같은 append 를 안에서 부른다.
이 명령들은 설정을 읽지 않는다(설계 4.2). 설정이 깨져도 동작한다.

outbox(`state/outbox.jsonl`)는 LF 로 끝나는 JSON 줄이다. 줄은 LF 로만 나눈다(본문의 U+2028 등은 경계가 아니다).
LF 로 끝나지 않은 마지막 조각은 쓰는 중이거나 쓰다 죽은 줄이라 읽지 않는다. 커서(`outbox.cursor`)와 ID 번호는
완결된 줄 수로 센다(읽지 못한 줄도 센다). 그래서 깨진 줄을 건너뛰어도 ID 를 다시 쓰지 않는다.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import unicodedata

from . import herdr, procs, state, testgate
from .errors import CONFLICT, DENIED, FAIL, USAGE, HteamError
from .horch import Horch
from .paths import find_project
from .util import bad_side_file, die_at, env_float, flock, now, read_json, read_json_strict, write_atomic, write_json

TYPES = ("progress", "ask", "question", "approval", "decide", "result", "done")  # 설계 7.2
RENDER_KEYS = {"header", "question", "context", "options", "multiSelect"}
OPTION_KEYS = {"label", "description"}
DESCRIPTION_MAX = 300  # 질문 줄과 같은 상한. 선택지 설명으로 context(4000자) 상한을 돌아가지 못하게 한다
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


def test_confirm(render: dict, cfg) -> dict:
    """`--test-confirm`(설계 5.7): render.context 끝에 `## 테스트 명령` 절을 붙인 질문 필드와 확정 식별값. 붙인 뒤 context 가
    4000자를 넘으면 exit 2(묻는 쪽이 줄인다)."""
    context = render.get("context")
    joined = (context.rstrip("\n") + "\n\n" if context else "") + testgate.confirm_section(cfg)
    if len(joined) > 4000:
        raise HteamError("bad_render", f"테스트 명령 절을 붙이면 context 가 4000자를 넘는다({len(joined)}자)", USAGE,
                         "context 를 줄인다(기획 확정 질문이면 태스크 그래프 표의 제목 열부터 뺀다)")
    return {"render": {**render, "context": joined}, "test_digest": testgate.digest(cfg),
            "test_commands": {"quick": cfg.quick, "full": cfg.full}}


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


def append(p, fields: dict, guard=None, reuse=None, fill=None) -> dict:
    """outbox 에 flock 으로 한 줄을 더한다. guard(entries) 는 같은 잠금 안에서 먼저 부른다. reuse(entries) 가 항목을
    돌려주면 쓰지 않고 그 항목을 돌려준다(이미 쓴 같은 항목. 끊긴 마지막 줄을 완결한 뒤에 보므로 LF 만 빠진 항목도 찾는다).
    fill(oid) 가 있으면 잠금 안에서 정한 id 로 부른 결과(dict)를 fields 에 합쳐 쓴다(decide commands 의 `{id}`, 설계 8.10).

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
        oid = f"out-{count + 1:04d}"
        entry = {"id": oid, "at": now(), **fields, **(fill(oid) if fill is not None else {}), "answered": False}
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


def open_decide(p, st: dict) -> str | None:
    """태스크의 열린 decide(설계 8.10): decide 가 있고 그 라운드가 지금 라운드이고 답 파일이 없으면 그 out id. 재확인과
    start-ready 는 이 태스크를 건드리지 않는다."""
    oid = st.get("decide")
    if not oid or st.get("decide_round") != st.get("round"):
        return None
    if (p.answers / f"{oid}.json").exists():
        return None
    return oid


def answer_strict(p, oid: str) -> dict | None:
    """answer_of 와 같으나 답 파일이 있는데 읽지 못하거나 JSON 객체가 아니면 bad_side_file 이다(손상을 "답 없음" 으로
    보지 않는다). 일괄 승인 결정과 status 의 안내가 쓴다. answer_of 의 다른 호출자(ask·answer)는 그대로다."""
    path, none = p.answers / f"{oid}.json", object()
    data = read_json_strict(path, none)
    if data is none:
        return None
    if not isinstance(data, dict):
        raise bad_side_file(path, "JSON 객체가 아니다")
    return data


def view(p, entry: dict) -> dict:
    return {**entry, "answered": answer_of(p, entry["id"]) is not None}


def _open(p, items: list[tuple[int, dict]], warnings: list[str]) -> list[tuple[int, dict]]:
    found = []
    for n, e in items:
        if e["type"] not in ("ask", "question", "approval", "decide"):
            continue
        if answer_of(p, e["id"]):  # 답 파일이 있으면 닫힌 것이다(설계 7.4·7.6)
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
    """답이 없는 ask(묻는 태스크가 아직 working)와 답 파일이 없는 question·approval·decide(설계 7.6).

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


def _terminal() -> str:
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        raise HteamError("no_terminal", "Herdr 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
    return term


def require_main(p) -> str:
    """메인 터미널에서 불렀는지 확인한다(answer·watch·reask·큐 명령이 무엇이든 쓰기 전에 부른다). 실수 방지용이다(설계 8.3).

    관제(HTEAM_ROLE·run.json 의 터미널·horch Run 소유자·hc 라벨 hteam.role)와 워커·리뷰어는 메인이 아니다. horch status 는
    launching·active Dispatch 만 알려 주므로, 끝난 Dispatch 의 터미널은 horch 가 워커 터미널을 띄울 때 붙이는 hc 라벨
    (horch.dispatch)로 가린다. horch worker-list 는 Run 소유자 터미널에서만 되므로 메인에서 부를 수 없다.
    확인할 수 없으면 거부한다(exit 1 main_unverified)."""
    term = _terminal()
    hint = "메인 세션 터미널에서 실행한다. 관제·워커는 horch 로 주고받는다"
    if os.environ.get("HTEAM_ROLE") == "drive" or term == _run(p).get("drive_terminal"):
        raise HteamError("not_main", "관제 터미널은 이 명령을 부르지 않는다(메인 전용)", DENIED, hint)
    code, data = Horch(p.horch_home).call("status")
    if code != 0 or not data.get("ok"):
        err = data.get("error") or {}
        raise HteamError("main_unverified", f"horch status 로 이 터미널({term})을 확인하지 못했다: {err.get('code')}",
                         FAIL, "다시 시도한다")
    if data.get("dispatch") or data.get("run"):
        who = "워커" if data.get("dispatch") else "Run 소유자(관제)"
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
        if labels.get("hteam.role") == "drive":  # Run 연결 전이라 run.json·horch 가 아직 모르는 관제(설계 9.3)
            raise HteamError("not_main", f"{where} 은 hteam up 이 띄운 관제 터미널이다(메인 전용)", DENIED, hint)
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


def _orphaned(p) -> bool:
    """관제가 꺼졌다(설계 7.3): 살아 있지도, 멈추지도(hung), 띄우는 중이지도 않다. pid·heartbeat 로 본다(hc 를 부르지 않는다)."""
    from . import drive  # drive 가 이 모듈을 쓴다
    v = drive.view(p, _run(p))  # run.json 을 읽지 못하면 bad_run_file(watch 가 그 오류로 끝난다)
    return not (v["alive"] or v["hung"] or v["starting"])


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
    """2초마다 outbox 를 본다. 새 줄이 있으면 출력하고 끝난다. 관제가 꺼졌으면 orphaned(멈춤이면 끝내지 않는다).

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


def _link_answer(p, oid: str, text: str, decision: dict | None = None) -> bool:
    """답 파일을 원자적으로 만든다(os.link). 이미 있으면 False. decision 은 일괄 승인의 결정(design-decide, 설계 7.4)."""
    p.ensure_state()
    path = p.answers / f"{oid}.json"
    tmp = p.answers / f".{oid}.{os.getpid()}.tmp"
    record = {"id": oid, "answer": text, **({"decision": decision} if decision is not None else {}), "at": now()}
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
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


def _record_confirm(p, entry: dict, text: str) -> bool:
    """테스트 명령 확정 질문(test_digest 가 있는 항목)에 첫 선택지(추천안) label 그대로 답하면 답을 쓰기 전에 그 식별값을
    확정 기록에 더한다(설계 5.7. 이미 있으면 그대로, 확정 기록이 손상됐으면 bad_test_approvals 로 멈춘다). 그 밖의 답은
    기록하지 않는다."""
    digest = entry.get("test_digest")
    options = (entry.get("render") or {}).get("options") or [{}]
    if not digest or text != options[0].get("label"):
        return False
    commands = entry.get("test_commands") or {}
    testgate.approve(p, digest, entry["id"], commands.get("quick"), commands.get("full"))
    return True


def _reply_failed(entry: dict, exc: HteamError) -> HteamError:
    tid = entry.get("task") or "T-xxx"
    why = f"{exc.code}: {exc.message}"[:300]
    return HteamError("reply_failed", f"워커에게 답을 보내지 못했다({why}). 워커가 끝났으면 답을 지시로 넣어 hteam fix {tid} "
                      f'--note "<답>", 아직 일하는 중이면 hteam scope {tid} "<답>" 로 전한다. 이 decide 는 닫았다', CONFLICT)


def _answer_decide(p, entry: dict, text: str) -> dict:
    """decide 는 답 파일로 닫는다(설계 7.4, 8.10). 워커 질문이면 답 파일을 쓰기 전에 요청 큐 reply 로 워커에게 보낸다:
    관제가 꺼졌거나 멈췄으면 그 오류(답 파일 없음, 다시 답할 수 있다), 회신이 거부되면 닫고 reply_failed, 90초 안에 끝나지
    않으면 닫고 queued."""
    oid = entry["id"]
    if answer_of(p, oid) is not None:
        raise HteamError("already_answered", f"{oid} 에는 이미 답했다", CONFLICT)
    if entry.get("kind") != "worker_question" and entry.get("message_id") is None:
        if not _link_answer(p, oid, text):
            raise HteamError("already_answered", f"{oid} 에는 이미 답했다", CONFLICT)
        return {"id": oid, "type": "decide", "closed": True, "replied": False}
    from . import queue  # queue 가 이 모듈을 쓴다
    try:
        res = queue.submit(p, "reply", {"message_id": entry.get("message_id"), "body": text, "task": entry.get("task")})
    except HteamError as exc:
        if exc.code in queue.SUBMIT_ERRORS:
            raise
        _link_answer(p, oid, text)
        raise _reply_failed(entry, exc) from None
    _link_answer(p, oid, text)
    if res.get("status") == "queued":
        return {"id": oid, "type": "decide", "closed": True, "replied": None, "status": "queued",
                "request": res["request"]}
    return {"id": oid, "type": "decide", "closed": True, "replied": True, "reply": res.get("message")}


def answer(p, oid: str, text: str) -> dict:
    """메인의 답(설계 7.4). 메인 확인을 어떤 쓰기보다 먼저 한다.

    ask 는 답 파일(두 번째 답은 exit 3). question 은 답 파일만 쓴다(Run 에 보내지 않는다. 같은 답이면 다시 성공). 테스트
    명령 확정 질문은 답을 쓰기 전에 확정 기록을 남긴다(_record_confirm, 기록 뒤 죽어 다시 부르면 같은 값을 다시 더한다).
    decide 는 _answer_decide. 일괄 승인(approval)은 design-decide 로 닫는다. 그 밖의 종류는 답하지 않는다."""
    require_main(p)
    entry = _entry(p, oid)
    kind = entry["type"]
    if kind == "approval":
        raise HteamError("use_design_decide", f"{oid} 은 일괄 승인 질문이다. 태스크별 결정을 "
                         f"`hteam design-decide {oid} --json -` 으로 넘긴다", USAGE)
    if kind not in ("ask", "question", "decide"):
        raise HteamError("not_answerable", f"{oid} 은 {kind} 항목이라 답하지 않는다", USAGE)
    if kind == "decide":
        return _answer_decide(p, entry, text)
    if kind == "ask":
        if answer_of(p, oid) is not None:  # 이미 답한 질문에 확정 기록을 남기지 않는다
            raise HteamError("already_answered", f"{oid} 에는 이미 답했다", CONFLICT)
        confirmed = _record_confirm(p, entry, text)
        if not _link_answer(p, oid, text):
            raise HteamError("already_answered", f"{oid} 에는 이미 답했다", CONFLICT)
        return {"id": oid, "type": "ask", "delivered": "file", "test_confirmed": confirmed}
    previous = answer_of(p, oid)
    if previous is not None and previous.get("answer") != text:
        raise HteamError("already_answered", f"{oid} 에는 이미 다른 답을 했다", CONFLICT)
    confirmed = _record_confirm(p, entry, text)
    if not _link_answer(p, oid, text) and (answer_of(p, oid) or {}).get("answer") != text:
        raise HteamError("already_answered", f"{oid} 에는 이미 다른 답을 했다", CONFLICT)
    return {"id": oid, "type": "question", "test_confirmed": confirmed}


def applied_ids(p) -> dict:
    """적용한 답 기록(out-id → 시각). 없으면 {}. 읽지 못하면 bad_side_file 이다: 빈 기록으로 보면 적용한 답을 다시
    처리하고(같은 fix 를 두 번 등) mark_applied 가 덮어써 기록을 잃는다."""
    data = read_json_strict(p.applied, {})
    if not isinstance(data, dict):
        raise bad_side_file(p.applied, "JSON 객체가 아니다")
    return data


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


def _cmd_watch(args) -> dict:
    p = find_project(args.root)
    require_main(p)  # 관제·워커가 부르면 잠금·커서를 건드리기 전에 거부한다
    return watch(p)


def _cmd_answer(args) -> dict:
    return answer(find_project(args.root), args.id, args.text)


def _cmd_reask(args) -> dict:
    p = find_project(args.root)
    require_main(p)
    return reask(p)


def register(sub) -> None:
    sub.add_parser("watch").set_defaults(func=_cmd_watch)
    s = sub.add_parser("answer")
    s.add_argument("id")
    s.add_argument("text")
    s.set_defaults(func=_cmd_answer)
    sub.add_parser("reask").set_defaults(func=_cmd_reask)
