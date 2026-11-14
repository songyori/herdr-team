"""질문 보기(설계 7.4a 8단계): 선택 창 미리보기에 다 들어가지 않는 긴 render.context 를 메인 옆 "질문 보기" pane 에 보인다.

- `hteam question-view <out-id>`: 훅(9.4 PreToolUse)이 새 세션의 분리된 자식으로 띄우는 내부 명령. 남은 보기를 정리하고, 메인
  pane 오른쪽에 pager pane 을 열고, 그 터미널이 끝날 때까지 기다린 뒤 지운다. 늘 exit 0 이다(질문을 막지 않는다).
- `hteam question-pager <out-id>`: 보기 pane 안에서 돈다. 전문을 마크다운으로 그려(mdrender, 설계 7.4a 9단계) 출력하고, pane
  폭이 바뀌면 다시 그리고, 답이 오거나 질문이 닫히면 끝난다. JSON 이 아니라 글을 출력하는 예외 명령이다(cli.main 의 JSON
  봉투를 거치지 않고 SystemExit 으로 끝난다).

파일은 state/questions/ 아래 <out-id>.md(전문, 훅이 쓴다)·.log(보기 명령 출력)·.view.json(연 보기 {pane, terminal, main, at,
pid})·.lock(보기 기록 잠금)이다. Herdr 는 herdr.py 로만 부른다.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import re
import shutil
import sys
import time
from typing import Iterator

from . import herdr, mdrender, outbox
from .errors import USAGE, HteamError
from .paths import PLUGIN_ROOT, find_project
from .util import flock, now, read_json, write_json

OUT_RE = re.compile(r"out-\d{4,}")
VIEW_POLL_S = 2.0  # 보기 터미널을 보는 간격
VIEW_MAX_S = 7200  # 이만큼 지나면 보기 pane 을 닫고 끝난다
PAGER_POLL_S = 2.0  # pager 가 답·질문 닫힘을 보는 간격
PAGER_MAX_S = 7200
PAGER_END = "(답하면 이 pane 은 닫힌다)"
CLEAR = "\x1b[H\x1b[2J\x1b[3J"  # 다시 그리기 전에 화면과 스크롤을 지운다


def _oid(raw: str) -> str:
    if not OUT_RE.fullmatch(raw):
        raise HteamError("usage", f"out-id 가 아니다: {raw!r}", USAGE)
    return raw


def _log(oid: str, text: str) -> None:
    """보기 명령의 로그 한 줄(표준 오류. 훅이 띄우면 state/questions/<out-id>.log 에 남는다)."""
    sys.stderr.write(f"{now()} question-view {oid}: {text}\n")
    sys.stderr.flush()


def _view_file(p, oid: str):
    return p.questions / f"{oid}.view.json"


@contextlib.contextmanager
def _try_lock(p, oid: str) -> Iterator[bool]:
    """state/questions/<out-id>.lock 을 비차단으로 쥔다. 쥐었으면 True, 다른 보기 명령이 쥐고 있으면 False."""
    p.questions.mkdir(parents=True, exist_ok=True)
    with open(p.questions / f"{oid}.lock", "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _record(p, oid: str) -> dict | None:
    rec = read_json(_view_file(p, oid), None)
    return rec if isinstance(rec, dict) and isinstance(rec.get("terminal"), str) and rec["terminal"] else None


def _state_of(terminal: str) -> str:
    """보기 터미널의 상태: live·finished·gone(hc 가 모른다, not_found)·unknown(그 밖의 오류나 모르는 상태)."""
    try:
        info = herdr.get(terminal)
    except HteamError as exc:
        return "gone" if exc.data.get("kind") == "not_found" else "unknown"
    state = info.get("state")
    return state if state in ("live", "finished") else "unknown"


def _close(rec: dict, live: bool) -> None:
    """보기를 닫는다: 살아 있으면 pane.close 뒤 hc rm, 끝났으면 hc rm(이미 없으면 성공). 실패는 HteamError 그대로."""
    if live and rec.get("pane"):
        herdr.close_pane(rec["pane"])
    herdr.rm(rec["terminal"])


def _sweep(p, oid: str) -> None:
    """남은 보기 정리(설계 7.4a): 다른 질문의 view.json 가운데 그 id 의 잠금을 비차단으로 쥘 수 있는 것만, 잠금 안에서 기록을
    다시 읽어 질문이 답을 받았거나 열린 질문이 아니거나 터미널이 끝났으면 정리한다. 터미널을 hc 가 모르면(not_found) 기록만
    지운다. 읽지 못하면(다른 오류) 기록을 두고 다음에 다시 본다. close_pane·rm 이 실패해도 기록을 둔다."""
    others = sorted(path.name[:-len(".view.json")] for path in p.questions.glob("*.view.json"))
    others = [other for other in others if other != oid and OUT_RE.fullmatch(other)]
    if not others:
        return
    try:
        open_ids = {q["id"] for q in outbox.open_questions(p)}
    except OSError as exc:  # outbox 를 읽지 못하면 질문이 닫혔는지 모른다: 이번에는 정리하지 않는다
        _log(oid, f"남은 보기 정리를 건너뛴다(outbox 를 읽지 못했다: {exc})")
        return
    for other in others:
        with _try_lock(p, other) as locked:
            if not locked:
                continue  # 그 질문의 보기 명령이 지금 열고 있다
            rec = _record(p, other)
            if rec is None:
                continue
            state = _state_of(rec["terminal"])
            if state == "gone":
                _view_file(p, other).unlink(missing_ok=True)
                continue
            closed = outbox.answer_of(p, other) is not None or other not in open_ids
            if state == "unknown" or (state == "live" and not closed):
                continue
            try:
                _close(rec, live=state == "live")
            except HteamError as exc:
                _log(oid, f"{other} 의 남은 보기를 닫지 못했다(기록을 둔다): {exc.message}")
                continue
            _view_file(p, other).unlink(missing_ok=True)


def _open(p, oid: str) -> dict:
    """잠금 안에서 열지 정하고 연다(설계 7.4a). 열었으면 {"view": "opened", "rec": 기록}, 아니면 {"view": <까닭>}."""
    if outbox.answer_of(p, oid) is not None:
        return {"view": "answered"}
    if not (p.questions / f"{oid}.md").is_file():
        return {"view": "no_file"}
    main = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not main:
        return {"view": "no_main"}
    rec = _record(p, oid)
    if rec is not None:
        state = _state_of(rec["terminal"])
        if state == "unknown":  # 살아 있을지 모르는 보기 옆에 또 열지 않는다
            _log(oid, f"보기 터미널 {rec['terminal']} 을 읽지 못해 다시 열지 않는다")
            return {"view": "view_unknown", "terminal": rec["terminal"]}
        if state == "live" and rec.get("main") == main:
            return {"view": "exists", "terminal": rec["terminal"]}
        try:  # 다른 메인 옆의 보기(메인을 새로 열어 다시 물었다)나 끝난 보기: 닫고 지운 뒤 지금 메인 옆에 연다
            if state != "gone":
                _close(rec, live=state == "live")
            _view_file(p, oid).unlink(missing_ok=True)
        except HteamError as exc:
            _log(oid, f"앞 보기 {rec['terminal']} 를 닫지 못해 기록을 두고 새로 열지 않는다: {exc.message}")
            return {"view": "view_unknown", "terminal": rec["terminal"]}
    pane = herdr.pane_of(main)
    if not pane:
        _log(oid, f"메인 터미널 {main} 의 pane 을 찾지 못했다")
        return {"view": "no_pane"}
    argv = [sys.executable, str(PLUGIN_ROOT / "bin" / "hteam"), "--root", str(p.root), "question-pager", oid]
    try:
        opened = herdr.split_right(pane, argv)
    except HteamError as exc:
        _log(oid, f"보기 pane 을 열지 못했다: {exc.message}")
        return {"view": "split_failed"}
    rec = {"pane": opened["pane"], "terminal": opened["terminal"], "main": main, "at": now(), "pid": os.getpid()}
    try:
        write_json(_view_file(p, oid), rec)
    except OSError as exc:
        _log(oid, f"보기 기록을 쓰지 못해 연 pane 을 닫는다: {exc}")
        try:
            _close(rec, live=True)
        except HteamError as err:
            _log(oid, f"연 보기 pane 을 닫지 못했다: {err.message}")
        return {"view": "split_failed"}
    return {"view": "opened", "rec": rec}


def _wait(p, oid: str, rec: dict) -> dict:
    """잠금 없이 보기 터미널이 끝나거나 없어질 때까지 VIEW_POLL_S 마다 본다. 끝나면 hc rm 하고, 같은 id 잠금 안에서 view.json 이
    아직 이 터미널을 가리킬 때만 지운다(다른 메인 옆에 새로 연 기록을 지우지 않게). VIEW_MAX_S 가 지나면 pane 을 닫고 같이
    정리한다. rm 이 실패하면 기록을 둔다(다음 보기 명령의 정리가 다시 한다)."""
    term, view = rec["terminal"], "closed"
    deadline = time.monotonic() + VIEW_MAX_S
    while _state_of(term) not in ("finished", "gone"):
        if time.monotonic() >= deadline:
            view = "timeout"
            try:
                herdr.close_pane(rec["pane"])
            except HteamError as exc:
                _log(oid, f"시간이 지나 보기 pane 을 닫지 못했다: {exc.message}")
            break
        time.sleep(VIEW_POLL_S)
    try:
        herdr.rm(term)
    except HteamError as exc:
        _log(oid, f"보기 터미널 {term} 을 지우지 못했다(기록을 둔다): {exc.message}")
        return {"view": view, "terminal": term}
    p.questions.mkdir(parents=True, exist_ok=True)
    with flock(p.questions / f"{oid}.lock"):
        now_rec = _record(p, oid)
        if now_rec is not None and now_rec["terminal"] == term:
            _view_file(p, oid).unlink(missing_ok=True)
    return {"view": view, "terminal": term}


def view(p, oid: str) -> dict:
    _sweep(p, oid)
    with _try_lock(p, oid) as locked:
        if not locked:
            return {"view": "busy"}
        got = _open(p, oid)
    if got["view"] != "opened":
        return got
    return _wait(p, oid, got["rec"])


def _width() -> int:
    """pane 의 열 수(설계 7.4a 9단계). 표준 출력 터미널의 크기가 먼저다(환경의 COLUMNS 가 실제 폭을 가리지 않게). 터미널이
    아니거나 읽지 못하면 shutil(COLUMNS, 없으면 80)."""
    try:
        return os.get_terminal_size(sys.stdout.fileno()).columns
    except (OSError, ValueError):
        return shutil.get_terminal_size((80, 24)).columns


def _draw(text: str, width: int, clear: bool) -> None:
    """text 를 width 칸으로 그려 PAGER_END 와 함께 쓴다. 색은 표준 출력이 터미널일 때만. 렌더가 예외를 내면 글 그대로 쓴다
    (렌더 결함이 보기를 막지 않게, 설계 7.4a). clear 면 화면과 스크롤을 먼저 지운다."""
    try:
        body = mdrender.render(text, width, sys.stdout.isatty())
    except Exception:  # noqa: BLE001 - 어떤 렌더 결함이어도 글은 보인다
        body = text
    if clear:
        sys.stdout.write(CLEAR)
    sys.stdout.write(body + "\n\n" + PAGER_END + "\n")
    sys.stdout.flush()


def pager(p, oid: str) -> None:
    """보기 pane 안(설계 7.4a): 전문을 마크다운으로 그려(9단계) 빈 줄 뒤 PAGER_END 와 함께 출력하고, PAGER_POLL_S 마다 답 파일이
    생겼거나 그 질문이 열린 질문이 아니면 끝난다. 그 사이 pane 폭이 바뀌면 같은 글을 새 폭으로 다시 그린다. PAGER_MAX_S 가
    지나도 끝난다. 파일이 없으면 그렇게 적고 끝난다. 늘 exit 0(SystemExit, JSON 출력 없음)."""
    md = p.questions / f"{oid}.md"
    try:
        text = md.read_text(encoding="utf-8").rstrip("\n")
    except (OSError, ValueError):
        sys.stdout.write(f"(질문 보기 파일이 없다: {md})\n")
        sys.stdout.flush()
        raise SystemExit(0)
    width = _width()
    _draw(text, width, False)
    deadline = time.monotonic() + PAGER_MAX_S
    while time.monotonic() < deadline:
        time.sleep(PAGER_POLL_S)
        if (p.answers / f"{oid}.json").exists():
            break
        try:
            if oid not in {q["id"] for q in outbox.open_questions(p)}:
                break
        except OSError:
            continue  # outbox 를 읽지 못했다: 다음에 다시 본다
        now_width = _width()
        if now_width != width:
            width = now_width
            _draw(text, width, True)
    sys.stdout.flush()
    raise SystemExit(0)


# --- CLI ---
def _cmd_view(args) -> dict:
    return view(find_project(args.root), _oid(args.id))


def _cmd_pager(args) -> dict:
    pager(find_project(args.root), _oid(args.id))
    return {}  # 닿지 않는다(pager 는 SystemExit 으로 끝난다)


def register(sub) -> None:
    s = sub.add_parser("question-view")
    s.add_argument("id")
    s.set_defaults(func=_cmd_view)
    s = sub.add_parser("question-pager")
    s.add_argument("id")
    s.set_defaults(func=_cmd_pager)
