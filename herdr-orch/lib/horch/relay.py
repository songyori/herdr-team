"""Claude 상태 대리 보고와 Stop 기록(설계 16장, 0.5.0).

Claude Code 는 시작 때 한 번 Herdr 에 상태 보고(OSC 7501)를 할 수 있는지 묻고, 2초 안에 답을 받지 못하면 그 세션 내내
보고하지 않는다(16.1). 그런 세션이면 herdr-orch 훅(hooks/horch_hook.py)이 그 Claude 의 tty 에 Claude 와 같은 형식의 상태 글을
대신 쓴다. 대상과 역할은 훅이 환경 변수로 정한다(HORCH_HOME 이 있으면 worker, HORCH_RELAY_HOME 만 있으면 main, 16.2). 파일은
모두 그 홈 아래다(16.3): 세션 기록 relay/<터미널>.json(Claude 프로세스 하나에 하나), 잠금 relay/<터미널>.lock, 워커 Stop 기록
relay/<터미널>.stops.json, 로그 relay.log. 기록을 읽고 고치고 tty 에 쓰는 일은 터미널마다의 잠금 안에서 한다. hc 조회와 ps 는
잠금 밖에서 먼저 하고 잠금 안에서 기록을 다시 읽는다.

훅은 handle 을, 훅이 분리 실행한 확인기는 check 를 부른다. handle 의 예외를 밖으로 내지 않는 것은 부르는 쪽(훅) 책임이다.
observe_one·worker-list·relay-status 는 읽기 함수(record·stops·stop_for_turn·write_failed)만 쓰고 잠금을 잡지 않는다(쓰기가
원자적이라 늘 완전한 파일을 읽는다). 훅은 자기 Claude(그 터미널의 전경 프로세스이고 훅의 조상인 것)의 tty 에만 쓴다(16.10).
확인기는 훅의 자손이 아니므로 판정에 쓴 hc get 의 전경 pid 와 그 시작 시각이 기록의 Claude 일 때만 쓴다. 메인의 Stop 에서
그 Claude 의 상태가 Herdr 에 가지 않으면(no_tty·write_failed) 한 번 알린다(handle 이 훅 출력으로 그 Stop 을 막는 글을
돌려준다). 이 모듈은 DB 모듈을 가져오지 않고, hc 모듈(hcio)은 hc 를 부를 때만 가져온다(빠른 길은 기록 파일과 ps 만 본다,
16.6).
"""
from __future__ import annotations

import calendar
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

from .ids import now
from .paths import PLUGIN_ROOT

DECIDE_S = 3.0  # Claude 시작 뒤 판정까지(시작 질의의 2초 창 뒤). 시험은 HORCH_TEST_RELAY_DECIDE_S
CHECK_BUDGET_S = 10.0  # 확인기가 판정을 시도하는 시간(확인기 시작부터)
CHECK_EVERY_S = 1.0  # 확인기가 hc 실패 뒤 다시 보는 간격
FOREGROUND_FRESH_S = 1.0  # 확인기: 전경 검사부터 잠금을 잡기까지 이보다 오래 걸렸으면 잠금을 놓고 전경부터 다시 본다
LOCK_WAIT_S = 10.0  # 터미널 잠금 대기 상한. 넘으면 그 사건은 쓰지 않고 relay.log 에 남긴다
WRITE_RETRIES = 2  # tty 쓰기가 실패하면 같은 사건 안에서 더 해 보는 횟수
WRITE_PAUSE_S = 0.1  # 그 간격
FAIL_LIMIT = 3  # 이어진 쓰기 실패가 이만큼이면 write_failed
STOPS_KEEP = 20  # Stop 기록(stops)을 남기는 수
DESC_MAX = 80  # 백그라운드 일 description 글자 수
RUNNING_STATUSES = ("running", "pending")  # 끝나지 않은 백그라운드 일의 status(대소문자 무시). 없는 status 도 끝나지 않은 일로 본다
REVERIFY_SLACK_MS = 1000  # 다시 확인: 마지막 대리 쓰기 시도보다 이만큼 넘게 뒤인 상태 변화만 Claude 의 보고로 본다
HC_TIMEOUT = 3.0  # hc get 시간 제한(초)
PS_TIMEOUT = 3.0  # ps 시간 제한(초)
MAX_DEPTH = 16  # 조상을 따라 올라가는 상한

EVENTS = frozenset({"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
                    "PermissionRequest", "PermissionDenied", "Elicitation", "ElicitationResult", "Stop", "StopFailure",
                    "SessionEnd"})
LAST_EVENTS = ("Stop", "StopFailure", "SessionEnd")  # 턴의 마지막 사건: 뒤에 다시 해 볼 사건이 없다
QUIET = ("off", "no_tty", "write_failed")  # 쓰지 않는 판정
NOTICED = ("no_tty", "write_failed")  # 메인에 한 번 알리는 판정: 상태가 Herdr 에 가지 않는다
# 메인 알림(계획 리뷰 plan2 r1 의 1): 메인의 Stop 을 한 번 막는 글
NOTICE = ('herdr-orch: 이 세션은 Herdr 에 상태를 보고하지 않고 대신 보낼 수도 없다(Claude 시작 질의 실패, 대리 쓰기 실패). '
          '질문이 Herdr "Needs you" 로 뜨지 않는다. 사용자에게 그대로 알린다: 일이 덜 몰린 때 /exit 뒤 같은 터미널에서 '
          'claude --resume 으로 다시 열면 풀린다. 세션을 스스로 끝내지 않는다.')
RESTART = "restart"  # 같은 프로세스의 /clear: working 다음 idle 을 한 번의 쓰기에 둘(turn 이 오른다)
ROLES = ("worker", "main")  # 훅이 환경 변수로 정한 역할(16.2)
HOOK_SCRIPT = PLUGIN_ROOT / "hooks" / "horch_hook.py"
TERMINAL_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # 파일 이름으로 쓴다(16.3). fullmatch
_PS_ENV = {"TZ": "UTC", "LC_ALL": "C"}  # lstart 를 UTC·C 로케일로 읽는다(procs 와 같다)


class _Busy(Exception):
    """터미널 잠금을 기다림 상한 안에 잡지 못했다."""


class _Late(Exception):
    """훅 마감이 지나 ps 를 부를 시간이 없다: 그 사건의 대리 보고를 건너뛴다(15초 훅 제한)."""


def osc(state: str, kind: str | None = None) -> bytes:
    """Claude 와 같은 OSC 7501 상태 글(16.1): `ESC]7501;state=<상태>:app=claude-code[:kind=<종류>]BEL`.
    clear 는 지우기 `ESC]7501;state=clear BEL` 이다. msg·title 은 넣지 않는다(16.10)."""
    if state == "clear":
        return b"\x1b]7501;state=clear\x07"
    text = f"state={state}:app=claude-code" + (f":kind={kind}" if kind else "")
    return b"\x1b]7501;" + text.encode("ascii") + b"\x07"


# --- 파일 ---
def valid_terminal(terminal) -> bool:
    """파일 이름으로 쓸 수 있는 터미널 주소인가(영문자·숫자·_·.·:·- 1–64자, 16.3)."""
    return isinstance(terminal, str) and TERMINAL_RE.fullmatch(terminal) is not None


def _dir(home) -> Path:
    return Path(home) / "relay"


def _record_path(home, terminal: str) -> Path:
    return _dir(home) / f"{terminal}.json"


def _stops_path(home, terminal: str) -> Path:
    return _dir(home) / f"{terminal}.stops.json"


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, obj) -> None:
    """임시 파일에 쓴 뒤 os.replace 한다(읽는 쪽은 잠금 없이도 완전한 파일만 본다). relay/ 는 0700 으로 만들고 홈은 만들지
    않는다(16.3). 실패하면 임시 파일을 남기지 않는다."""
    path.parent.mkdir(mode=0o700, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _strs(value) -> dict:
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def record(home, terminal: str) -> dict | None:
    """세션 기록 <home>/relay/<terminal>.json(16.3). 없거나 읽지 못하거나 pid·started_ms 가 정수가 아니면 None. 잠금을 잡지
    않는다. 빠졌거나 틀린 필드는 기본값으로 채워 돌려준다."""
    if not valid_terminal(terminal):
        return None
    rec = _read_json(_record_path(home, terminal), None)
    if not isinstance(rec, dict) or not _int(rec.get("pid")) or _int(rec.get("started_ms")) is None:
        return None
    tty = rec.get("tty")
    decided = rec.get("decided")
    return {**rec, "terminal": terminal, "tty": tty if isinstance(tty, str) and tty else None,
            "decided": decided if decided in ("on", *QUIET) else None,
            "pending": rec["pending"] if isinstance(rec.get("pending"), str) else "idle",
            "blockers": _strs(rec.get("blockers")), "perm_tools": _strs(rec.get("perm_tools")),
            "write_failures": _int(rec.get("write_failures")) or 0, "notified": rec.get("notified") is True}


def _new(terminal: str, claude: dict) -> dict:
    """새 기록(16.4 의 1). perm_tools 는 승인 키의 도구 이름이다(PostToolUse 가 입력 해시가 다를 때 같은 도구의 가장 오래된
    승인을 찾는다). notified 는 메인 알림을 냈는가다(Claude 프로세스마다 한 번)."""
    return {"terminal": terminal, "pid": claude["pid"], "tty": claude["tty"], "started_ms": claude["started_ms"],
            "decided": None, "pending": "idle", "last": None, "at": None, "blockers": {}, "perm_tools": {},
            "write_failures": 0, "notified": False}


def _save(home, rec: dict) -> None:
    _write_json(_record_path(home, rec["terminal"]), rec)


@contextlib.contextmanager
def _locked(home, terminal: str, wait: float | None = None) -> Iterator[None]:
    """터미널 잠금 <home>/relay/<terminal>.lock(flock). wait 초(기본 LOCK_WAIT_S) 안에 잡지 못하면 _Busy. 잡은 쪽은 hc 를
    기다리지 않으므로(조회는 잠금 밖) 실제로는 짧다."""
    folder = _dir(home)
    folder.mkdir(mode=0o700, exist_ok=True)
    deadline = time.monotonic() + (LOCK_WAIT_S if wait is None else wait)
    with open(folder / f"{terminal}.lock", "a+") as fh:
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise _Busy() from None
                time.sleep(0.02)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _log(home, text: str) -> None:
    """<home>/relay.log 에 UTC 시각을 붙인 한 줄(16.3). 쓰지 못해도 넘어간다."""
    try:
        with (Path(home) / "relay.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{now()} {text}\n")
    except OSError:
        pass


def _log_error(home, label: str, exc: BaseException) -> None:
    message = str(exc).replace("\n", " ")
    _log(home, f"오류({label}): {type(exc).__name__}: {message}")


# --- 지금 Claude ---
def _terminal() -> str | None:
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    return term if valid_terminal(term) else None


def _now_ms() -> int:
    return int(time.time() * 1000)


def _decide_s() -> float:
    try:
        return float(os.environ.get("HORCH_TEST_RELAY_DECIDE_S", DECIDE_S))
    except ValueError:
        return DECIDE_S


def _home_ok(home) -> bool:
    """홈이 절대 경로이고 폴더로 있다(만들지 않는다)."""
    path = Path(home)
    return path.is_absolute() and path.is_dir()


def _left(deadline: float | None) -> float | None:
    """훅 마감(time.monotonic 시각)까지 남은 초. 마감이 없으면 None."""
    return None if deadline is None else deadline - time.monotonic()


def _hc_get(terminal: str, deadline: float | None = None) -> dict | None:
    """hc get(HC_TIMEOUT 초). 실패(hc 없음·시간 초과·not_found 등)는 None. 훅 마감까지 HC_TIMEOUT 이 남지 않았으면 부르지
    않고 None(실패와 같다, 15초 훅 제한). 빠른 길은 hc 를 부르지 않으므로 hcio 는 늦게 가져온다."""
    left = _left(deadline)
    if left is not None and left < HC_TIMEOUT:
        return None
    from . import hcio
    from .errors import HorchError
    try:
        info = hcio.get(terminal, timeout=HC_TIMEOUT)
    except (hcio.HcFailure, HorchError):
        return None
    return info if isinstance(info, dict) else None


def _ps_row(pid: int, deadline: float | None = None) -> tuple[int, str | None, int] | None:
    """(ppid, tty 경로 또는 None, 시작 시각 epoch ms). 그 프로세스가 없거나 ps 가 실패하면(시간 초과 포함) None. 시작 시각은
    `ps -o lstart=`(초 단위)라 훅이 늦게 돌아도 같다. tty 는 `ps -o tty=` 의 이름에 /dev/ 를 붙인다(`??`·`?`·`-` 는 없음).
    시간 상한은 min(PS_TIMEOUT, 훅 마감까지 남은 시간)이고, 남은 시간이 없으면 _Late(16.6)."""
    timeout = PS_TIMEOUT
    left = _left(deadline)
    if left is not None:
        if left <= 0:
            raise _Late()
        timeout = min(PS_TIMEOUT, left)
    try:
        proc = subprocess.run(["ps", "-o", "ppid=", "-o", "tty=", "-o", "lstart=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=timeout, env={**os.environ, **_PS_ENV})
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    words = proc.stdout.split()
    if proc.returncode != 0 or len(words) < 7:
        return None
    try:
        ppid = int(words[0])
        started = calendar.timegm(time.strptime(" ".join(words[2:7]), "%a %b %d %H:%M:%S %Y"))
    except ValueError:
        return None
    return ppid, (None if words[1] in ("??", "?", "-") else f"/dev/{words[1]}"), started * 1000


def _ancestor(target, deadline: float | None = None) -> tuple[str | None, int] | None:
    """target 이 이 프로세스이거나 그 조상이면 (tty, 시작 시각 ms). 아니거나 ps 가 실패하면 None. 자기 자신에서는 ps 없이
    os.getppid 로 한 칸 오르고, 그 위는 `ps -p` 한 번에 한 칸씩 오른다(보통 훅의 부모나 그 셸의 부모가 Claude 라 한두 번,
    16.4). ps 는 훅 마감(deadline)을 지킨다(_ps_row)."""
    if _int(target) is None or target <= 1:
        return None
    me = pid = os.getpid()
    for _ in range(MAX_DEPTH):
        if pid == target:
            row = _ps_row(pid, deadline)
            return (row[1], row[2]) if row else None
        if pid <= 1:
            return None
        if pid == me:
            pid = os.getppid()
            continue
        row = _ps_row(pid, deadline)
        if row is None:
            return None
        pid = row[0]
    return None


def _of(rec: dict | None, pid: int, started_ms: int) -> bool:
    """기록이 그 프로세스(pid 와 시작 시각)의 것이다."""
    return rec is not None and rec["pid"] == pid and rec["started_ms"] == started_ms


def _alive(rec: dict, deadline: float | None = None) -> bool:
    """기록의 Claude 가 아직 산다: 그 pid 의 시작 시각(ps)이 started_ms 와 같다(끝났거나 pid 가 다시 쓰였으면 거짓). 잠금 안에서도
    부르는 짧은 조회다."""
    row = _ps_row(rec["pid"], deadline)
    return row is not None and row[2] == rec["started_ms"]


def _same(rec: dict | None, deadline: float | None = None) -> bool:
    """기록의 Claude 가 이 훅의 조상이고 그 시작 시각이 기록과 같다(pid 재사용이 아니다)."""
    got = _ancestor(rec["pid"], deadline) if rec is not None else None
    return got is not None and got[1] == rec["started_ms"]


def _foreground(info: dict | None, deadline: float | None = None) -> dict | None:
    """hc get 의 foreground.pid 가 이 훅의 조상이면 지금 Claude {pid, tty, started_ms}. 아니면 None(다른 터미널·프로세스에
    쓰지 않는다)."""
    fg = info.get("foreground") if isinstance(info, dict) else None
    pid = _int(fg.get("pid")) if isinstance(fg, dict) else None
    got = _ancestor(pid, deadline) if pid else None
    return {"pid": pid, "tty": got[0], "started_ms": got[1]} if got else None


# --- 사건 표(16.5) ---
def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _input_json(payload: dict) -> str:
    return json.dumps(payload.get("tool_input"), sort_keys=True, ensure_ascii=False)


def _tool_name(payload: dict) -> str:
    tool = payload.get("tool_name")
    return tool if isinstance(tool, str) else ""


def _tool_key(payload: dict) -> str:
    tid = payload.get("tool_use_id")
    return "tool:" + (tid if isinstance(tid, str) and tid else _hash(_input_json(payload)))


def _perm_key(payload: dict) -> str:
    return "perm:" + _hash(_tool_name(payload) + "\n" + _input_json(payload))


def _elic_server(payload: dict) -> str:
    server = payload.get("mcp_server_name")
    return server if isinstance(server, str) else ""


def _elic_key(payload: dict) -> str:
    eid = payload.get("elicitation_id")
    message = payload.get("message")
    return (f"elic:{_elic_server(payload)}:"
            + (eid if isinstance(eid, str) and eid else _hash(message if isinstance(message, str) else "")))


def _add(rec: dict, key: str, kind: str, tool: str | None = None) -> None:
    rec["blockers"].pop(key, None)  # 다시 오면 가장 최근 것이 된다
    rec["blockers"][key] = kind
    if tool is not None:
        rec["perm_tools"][key] = tool


def _drop(rec: dict, key: str | None) -> None:
    if key:
        rec["blockers"].pop(key, None)
        rec["perm_tools"].pop(key, None)


def _clear(rec: dict) -> None:
    rec["blockers"].clear()
    rec["perm_tools"].clear()


def _asks(payload: dict, role: str) -> bool:
    """사람에게 묻는 질문 도구인가. 워커의 질문은 horch ask 메일함으로 가고 다른 플러그인이 거부할 수 있어(거부된 도구에는
    PostToolUse 가 없다) 질문 목록에 넣지 않는다(16.2). 메인만 넣는다."""
    return role == "main" and _tool_name(payload) == "AskUserQuestion"


def _apply(rec: dict, event: str | None, payload: dict, role: str) -> str | None:
    """사건대로 blockers 를 고치고 그 사건의 상태를 돌려준다(쓰지 않는 사건은 None). blockers 가 비지 않으면 실제로 쓰는
    것은 가장 최근 것의 blocked 다(_target)."""
    if event == "SessionStart":  # compact 는 handle 이 먼저 거른다
        _clear(rec)
        return RESTART if payload.get("source") == "clear" else "idle"
    if event == "UserPromptSubmit":
        _clear(rec)
        return "working"
    if event == "PreToolUse":
        if _asks(payload, role):
            _add(rec, _tool_key(payload), "question")
        return "working"
    if event == "PermissionRequest":
        _add(rec, _perm_key(payload), "permission", _tool_name(payload))
        return "working"
    if event == "PermissionDenied":
        _drop(rec, _perm_key(payload))
        return "working"
    if event == "Elicitation":
        _add(rec, _elic_key(payload), "question")
        return "working"
    if event == "ElicitationResult":
        eid = payload.get("elicitation_id")
        prefix = f"elic:{_elic_server(payload)}:"
        _drop(rec, prefix + eid if isinstance(eid, str) and eid
              else next((k for k in rec["blockers"] if k.startswith(prefix)), None))
        return "working"
    if event in ("PostToolUse", "PostToolUseFailure"):
        _drop(rec, _tool_key(payload))
        key = _perm_key(payload)
        if key not in rec["blockers"]:  # 다른 플러그인이 입력을 바꿨다: 같은 도구의 가장 오래된 승인
            tool = _tool_name(payload)
            key = next((k for k in rec["blockers"] if k.startswith("perm:") and rec["perm_tools"].get(k) == tool), None)
        _drop(rec, key)
        return "working"
    if event == "Stop":
        _clear(rec)
        return "working" if role == "worker" and running_background(payload.get("background_tasks")) else "done"
    if event == "StopFailure":
        _clear(rec)
        return "error"
    if event == "SessionEnd":
        _clear(rec)
        return "clear"
    return None


def _final(event: str, payload: dict, role: str) -> bool:
    """턴의 마지막 사건이거나 blocked 를 쓰려던 사건(실패하면 hc 에 앞 상태가 남는다)."""
    if event in LAST_EVENTS or event in ("PermissionRequest", "Elicitation"):
        return True
    return event == "PreToolUse" and _asks(payload, role)


# --- 판정과 쓰기 ---
def _due(rec: dict | None, event: str | None) -> bool:
    """판정할 때인가: 판정 전이고, UserPromptSubmit 이 아니고(그 턴의 Claude 보고보다 먼저 돌 수 있다), 시작 뒤 DECIDE_S 가
    지났다(16.4 의 2)."""
    return (rec is not None and rec["decided"] is None and event != "UserPromptSubmit"
            and _now_ms() - rec["started_ms"] >= _decide_s() * 1000)


def _decide(home, rec: dict, info: dict) -> None:
    """status_ms 가 Claude 시작 이후면 off(스스로 보고한다). 아니면 tty 가 있으면 on, 없으면 no_tty. relay.log 한 줄."""
    ms = info.get("status_ms")
    if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms >= rec["started_ms"]:
        rec["decided"] = "off"
    else:
        rec["decided"] = "on" if rec["tty"] else "no_tty"
    _log(home, f"{rec['terminal']} {rec['pid']} {rec['decided']}")


def _label(state, kind=None) -> str:
    return f"{state}:{kind}" if kind else str(state)


def _self_reporting(rec: dict, info: dict) -> bool:
    """다시 확인(16.6): 상태 기록에 msg·title 이 있거나(대리 보고는 쓰지 않는다), status_ms 가 마지막 대리 쓰기 시도보다
    REVERIFY_SLACK_MS 넘게 뒤이고 그 상태가 last 와 다르다."""
    status = info.get("status") if isinstance(info.get("status"), dict) else {}
    if status.get("msg") or status.get("title"):
        return True
    ms, at = info.get("status_ms"), rec.get("at")
    if not (isinstance(ms, (int, float)) and isinstance(at, (int, float)) and ms > at + REVERIFY_SLACK_MS):
        return False
    return _label(status.get("state"), status.get("kind")) != rec.get("last")


def _target(rec: dict, word: str) -> tuple[str, str | None]:
    """쓸 상태: blockers 가 비지 않으면 가장 최근 것의 blocked(kind 그대로), 비었으면 사건의 상태."""
    if rec["blockers"]:
        return "blocked", list(rec["blockers"].values())[-1]
    return ("idle" if word == RESTART else word), None


def _write_once(tty: str, data: bytes) -> int:
    fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        return os.write(fd, data)
    finally:
        os.close(fd)


def _emit(tty: str | None, data: bytes) -> str | None:
    """tty 에 data 를 한 번의 write 로 쓴다. 실패하면(EAGAIN 포함) WRITE_PAUSE_S 간격으로 WRITE_RETRIES 번 더 해 본다(덜 쓴
    바이트는 나머지만). 성공이면 None, 아니면 마지막 오류 글."""
    if not tty:
        return "tty 없음"
    err = ""
    for i in range(1 + WRITE_RETRIES):
        if i:
            time.sleep(WRITE_PAUSE_S)
        try:
            n = _write_once(tty, data)
        except OSError as exc:
            err = f"{type(exc).__name__}: {exc}"
            continue
        data = data[n:]
        if not data:
            return None
        err = "덜 썼다"
    return err


def _write(home, rec: dict, event: str | None, word: str, stage: dict) -> None:
    """decided 가 on 인 세션에 쓴다(16.5). last 와 같으면 쓰지 않는다(/clear 의 working·idle 은 늘 쓴다).

    쓰기 전에 기록(판정·blockers·pending 과 쓰기 시도 시각 at)을 먼저 저장하고, 그 저장이 실패하면 쓰지 않는다(예외가
    올라간다). 저장하지 못한 첫 on 판정의 쓰기가 hc 의 status_ms 를 만들면 다음 사건이 그것을 Claude 의 보고로 보고 off 로
    굳기 때문이다. at 이 쓰기 시도 시각이라 쓴 뒤의 저장(last)이 실패해도 Stop 의 다시 확인이 자기 쓰기를 Claude 의 보고로
    보지 않는다(다음 사건은 같은 상태를 한 번 더 쓴다). 성공하면 last 를 고치고 write_failures 를 0 으로, 실패하면
    write_failures 를 올리고 relay.log 에 남긴다. 턴의 마지막 사건·blocked 쓰기가 실패했거나 실패가 FAIL_LIMIT 번 이어지면
    write_failed 로 두고 그 뒤 쓰지 않는다."""
    state, kind = _target(rec, word)
    label = _label(state, kind)
    restart = word == RESTART and not rec["blockers"]
    if label == rec.get("last") and not restart:
        stage["past"] = True
        return
    rec["at"] = _now_ms()
    _save(home, rec)  # 쓰기 전 저장: 실패하면 쓰지 않는다
    stage["past"] = True
    err = _emit(rec["tty"], osc("working") + osc("idle") if restart else osc(state, kind))
    if err is None:
        rec.update(last=label, write_failures=0)
        return
    rec["write_failures"] += 1
    _log(home, f"{rec['terminal']} {rec['pid']} 쓰기 실패({label}): {err}")
    if event in LAST_EVENTS or state == "blocked" or rec["write_failures"] >= FAIL_LIMIT:
        rec["decided"] = "write_failed"
        stage["failed"] = True  # 이 판정을 담은 마지막 저장이 실패하면 handle 이 보완 저장한다(Codex 계획 리뷰 r3)
        _log(home, f"{rec['terminal']} {rec['pid']} write_failed")


def _step(home, rec: dict, event: str | None, payload: dict, role: str, info: dict | None, stage: dict) -> None:
    """잠금 안에서 사건 하나를 기록에 반영한다: blockers, 판정 전이면 pending 과 판정(on 이면 그 자리에서 pending 또는 그
    사건의 상태를 쓴다), on 이면 Stop 의 다시 확인과 쓰기. event 가 None 이면 확인기다."""
    word = _apply(rec, event, payload, role)
    if rec["decided"] is None:
        if word is not None:
            rec["pending"] = "idle" if word == RESTART else word
        if info is None or not _due(rec, event):
            return
        _decide(home, rec, info)
        if rec["decided"] != "on":
            return
        word = word if word is not None else rec["pending"]
    elif rec["decided"] != "on":
        return
    elif event == "Stop" and info is not None and _self_reporting(rec, info):
        rec["decided"] = "off"
        _log(home, f"{rec['terminal']} {rec['pid']} off(다시 확인: Claude 가 스스로 보고한다)")
        return
    if word is not None:
        _write(home, rec, event, word, stage)


def _add_stop(home, terminal: str, pid: int, info: dict | None, payload: dict) -> None:
    """워커 Stop 기록(16.7): stops 끝에 {pid, turn, at, background} 를 더하고 STOPS_KEEP 개만 남긴다. turn 은 그 턴 끝의
    idle 사건이 가질 turn 이다(hc 상태가 working 이면 turn+1, 아니면 turn. turn 은 상태가 working 을 벗어날 때 오른다).
    hc 가 실패했으면 None. at 은 ids.now. 지금 Claude(pid)를 확인한 Stop 만 터미널 잠금 안에서 부른다. background 에는 끝난
    일도 status 와 함께 그대로 남긴다(무엇이 남는지 볼 수 있게). 백그라운드가 있는지는 읽는 쪽이 running_background 로 가른다."""
    turn = None
    if info is not None and _int(info.get("turn")) is not None:
        status = info.get("status") if isinstance(info.get("status"), dict) else {}
        turn = info["turn"] + 1 if status.get("state") == "working" else info["turn"]
    tasks = payload.get("background_tasks")
    background = [{"type": t.get("type"), "status": t.get("status"),
                   "description": str(t.get("description") or "")[:DESC_MAX]}
                  for t in (tasks if isinstance(tasks, list) else []) if isinstance(t, dict)]
    items = [*stops(home, terminal), {"pid": pid, "turn": turn, "at": now(), "background": background}]
    _write_json(_stops_path(home, terminal), {"stops": items[-STOPS_KEEP:]})


def _spawn(home, terminal: str, pid: int, started_ms: int) -> None:
    """판정 확인기(horch_hook.py relay-check <홈> <터미널> <pid> <started_ms>)를 분리 실행한다(표준 입출력 없이 새 세션으로.
    훅이 끝나도 돈다). 띄우지 못하면 relay.log 에 남기고 넘어간다(그 뒤 사건이 판정한다)."""
    try:
        subprocess.Popen([sys.executable, str(HOOK_SCRIPT), "relay-check", str(home), terminal, str(pid),
                          str(started_ms)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True, cwd=str(home))
    except OSError as exc:
        _log(home, f"{terminal} {pid} 확인기를 띄우지 못했다: {exc}")


def _give_up(home, terminal: str, pid: int, started_ms: int) -> None:
    """턴의 마지막 사건이나 blocked 를 쓰려던 사건이 tty 쓰기 전에 예외로 끝났거나, tty 쓰기 실패로 정한 write_failed 를
    저장하지 못했다: 뒤에 사건이 없어 hc 에 앞 상태가 남으므로 그 훅의 Claude(pid·started_ms)의 on 기록을 할 수 있는 만큼
    write_failed 로 둔다(16.5). 잠금 안의 기록이 다른 Claude 의 것이면(그 사이 새 Claude 가 만들었다) 바꾸지 않는다. 이 일의
    실패는 넘어간다(원래 예외는 부르는 쪽이 남긴다)."""
    try:
        with _locked(home, terminal, wait=1.0):
            rec = record(home, terminal)
            if _of(rec, pid, started_ms) and rec["decided"] == "on":
                rec["decided"] = "write_failed"
                _save(home, rec)
                _log(home, f"{terminal} {rec['pid']} write_failed(예외 뒤 보완)")
    except Exception:  # noqa: BLE001
        pass


def _notice_due(rec: dict, event: str | None, payload: dict, role: str) -> bool:
    """메인 알림을 낼 때인가(계획 리뷰 plan2 r1 의 1): 메인의 Stop 이고, 그 Claude 의 기록이 no_tty·write_failed(상태가 Herdr 에
    가지 않는다)이고, 아직 알리지 않았다. 다른 Stop 훅이 막아 이어진 턴(stop_hook_active)이어도 처음이면 알린다(orch 16.11.
    다음 사용자 턴이 없을 수 있다). 반복은 notified 를 먼저 저장해 막는다."""
    return event == "Stop" and role == "main" and rec["decided"] in NOTICED and not rec.get("notified")


def handle(home, event: str, payload: dict, *, role: str, deadline: float | None = None) -> dict | None:
    """훅 사건 하나를 대리 보고에 반영하고 훅이 낼 출력을 돌려준다(없으면 None). home 은 훅이 고른 홈(절대 경로인 폴더),
    role 은 worker·main 이다(16.2). $HC_TERMINAL_ID 가 없거나 모르는 사건·역할이거나 서브에이전트 사건(agent_id)이거나
    SessionStart(compact)면 아무것도 하지 않는다(compact 는 턴 중간이라 판정 전 기록에서도 판정·쓰기·기록 만들기를 하지 않는다.
    pending 도 그대로다). role 은 AskUserQuestion(메인만 질문 목록에 넣는다)과 Stop(메인은 done 이고 Stop 기록이 없다)에 쓴다.

    메인 알림: 메인의 Stop 에서 이 사건의 단계(판정·다시 확인·쓰기)를 마친 뒤 그 Claude 의 기록이 no_tty·write_failed 이고 아직
    알리지 않았으면(같은 Stop 의 쓰기 실패 포함) notified 를 먼저 저장하고 {"decision": "block", "reason": NOTICE} 를 돌려준다.
    저장하지 못하면 예외가 올라가 막지 않는다. stop_hook_active(다른 Stop 훅이 막아 이어진 턴)여도 처음이면 낸다.

    deadline 은 훅 마감(time.monotonic 시각): 남은 시간이 HC_TIMEOUT 보다 적으면 hc 를 부르지 않고, 잠금은 그때까지만
    기다린다. ps 도 마감까지만 기다리고 남은 시간이 없으면 그 사건을 건너뛴다. 잠금 대기 초과와 마감은 relay.log 에 남기고
    None 이다. 그 밖의 예외는 그대로 올린다(턴의 마지막 사건·blocked 를 쓰려던 사건이 tty 쓰기 전에 끝나거나 쓰기 실패로 정한
    write_failed 를 저장하지 못하면 먼저 그 훅의 Claude 기록을 write_failed 로 둔다)."""
    terminal = _terminal()
    if (terminal is None or event not in EVENTS or role not in ROLES or not isinstance(payload, dict)
            or payload.get("agent_id")):
        return None
    if event == "SessionStart" and payload.get("source") == "compact":
        return None  # 자동 compact 는 턴 중간이다: idle 을 쓰면 horch 가 턴 끝으로 본다
    if not _home_ok(home):
        return None
    home = Path(home)
    stage = {"past": False, "failed": False, "claude": None}
    try:
        return _handle(home, terminal, event, payload, role, stage, deadline)
    except _Busy:
        _log(home, f"{terminal} 잠금 대기 {LOCK_WAIT_S:g}초 초과({event}): 이 사건은 쓰지 않았다")
    except _Late:
        _log(home, f"{terminal} 훅 마감({event}): 이 사건은 대리 보고하지 않았다")
    except BaseException:
        if stage["claude"] and (stage["failed"] or (not stage["past"] and _final(event, payload, role))):
            _give_up(home, terminal, *stage["claude"])
        raise
    return None


def _handle(home: Path, terminal: str, event: str, payload: dict, role: str, stage: dict,
            deadline: float | None) -> dict | None:
    stop_rec = event == "Stop" and role == "worker"  # Stop 기록을 남기는 Stop
    rec = record(home, terminal)
    mine = _same(rec, deadline)
    if mine and rec["decided"] in QUIET and not stop_rec and not _notice_due(rec, event, payload, role):
        return None  # 빠른 길: 쓸 것도 알릴 것도 없다(잠금·hc 없음)
    info = _hc_get(terminal, deadline) if not mine or event == "Stop" or _due(rec, event) else None  # 잠금 밖
    claude = ({"pid": rec["pid"], "tty": rec["tty"], "started_ms": rec["started_ms"]} if mine
              else _foreground(info, deadline))
    if claude is None:
        # 지금 Claude 를 모른다(hc 실패·전경이 조상이 아님): 다음 사건에서 다시 한다. 워커 Stop 기록도 남기지 않는다(늦은 옛
        # 훅이 살아 있는 다른 세션의 turn 에 자기 백그라운드 목록을 덧붙이지 않게. horch 는 기록 없이 10초 뒤 idle 을 낸다)
        return None
    stage["claude"] = (claude["pid"], claude["started_ms"])  # 예외 보완(_give_up)은 이 Claude 의 기록만 바꾼다
    created = notify = False
    left = _left(deadline)
    with _locked(home, terminal, None if left is None else max(0.0, min(LOCK_WAIT_S, left))):
        rec = record(home, terminal)  # 잠금 밖에서 기다리는 사이 다른 훅이 판정했을 수 있다: 그 값을 따른다
        if not _of(rec, claude["pid"], claude["started_ms"]):
            if rec is not None and _alive(rec, deadline):
                # 잠금을 기다리는 사이 다른 Claude 가 기록을 만들었고 그 Claude 가 산다: 이 사건은 늦게 끝난 옛 Claude 의
                # 훅이다. 기록도 Stop 기록도 바꾸지 않고 쓰지 않는다(Codex 계획 리뷰 r2)
                _log(home, f"{terminal} {claude['pid']} 늦은 사건 버림({event}): 기록은 {rec['pid']} 의 것이다")
                return None
            rec, created = _new(terminal, claude), True
        if not _alive(rec, deadline):
            # 잠금 밖에서 확인한 뒤 hc 조회·잠금 대기 사이 그 Claude 가 끝났다(또는 ps 실패): 같은 tty 를 이어 쓰는 셸·다른
            # 프로그램에 옛 상태를 내지 않는다. 기록도 Stop 기록도 바꾸지 않는다(16.10, 계획 리뷰 plan2 r2 의 1)
            _log(home, f"{terminal} {claude['pid']} 사건 버림({event}): 그 Claude 가 끝났다(쓰기 없음)")
            return None
        if stop_rec:  # tty 쓰기 앞에 남긴다: horch 가 이 Stop 의 idle 을 볼 때 그 기록이 이미 있다
            try:
                _add_stop(home, terminal, claude["pid"], info, payload)
            except Exception as exc:  # noqa: BLE001  기록 쓰기가 실패해도 tty 에는 쓴다(horch 는 기록 없이 10초 뒤 낸다)
                _log_error(home, "Stop 기록", exc)
        _step(home, rec, event, payload, role, info, stage)
        notify = _notice_due(rec, event, payload, role)
        if notify:
            rec["notified"] = True  # 알림은 이 표시를 저장한 뒤에만 낸다(저장하지 못하면 다음 메인 Stop 이 다시 본다)
        _save(home, rec)
    if created and rec["decided"] is None:
        _spawn(home, terminal, rec["pid"], rec["started_ms"])
    return {"decision": "block", "reason": NOTICE} if notify else None


def _ours(rec: dict | None, pid: int, started_ms: int) -> bool:
    return _of(rec, pid, started_ms) and rec["decided"] is None


def _still_foreground(info: dict, pid: int, started_ms: int) -> bool:
    """판정에 쓴 hc get 의 foreground.pid 가 그 Claude 이고, 그 pid 의 시작 시각(ps)이 started_ms 와 같다(끝났거나 다른
    프로그램이 전경이거나 pid 가 다시 쓰이지 않았다)."""
    fg = info.get("foreground")
    if not isinstance(fg, dict) or _int(fg.get("pid")) != pid:
        return False
    row = _ps_row(pid)
    return row is not None and row[2] == started_ms


def check(home, terminal: str, pid: int, started_ms: int) -> None:
    """분리 실행된 판정 확인기(16.4 의 2, horch_hook.py relay-check). Claude 시작 DECIDE_S 뒤까지 자고, 기록이 그
    프로세스(pid·started_ms)의 것이고 판정 전이면 hc get 으로 판정한다. on 이면 그 자리에서 pending(질문·승인이 남았으면
    blocked)을 쓴다. hc 가 실패하면 CHECK_EVERY_S 간격으로 다시 보고, 판정하거나 시작 뒤 CHECK_BUDGET_S 가 지나면 끝난다.
    첫 질문이 답을 기다리는 동안에는 다음 훅 사건이 없으므로 확인기가 쓴다. 확인기는 훅의 자손이 아니어서 조상으로 Claude 를
    확인할 수 없다: 그 hc get 의 전경이 기록의 Claude 가 아니면(_still_foreground) 판정도 쓰기도 하지 않고 끝낸다. 전경
    검사부터 잠금을 잡기까지 FOREGROUND_FRESH_S 가 넘게 걸렸으면 잠금을 놓고 전경부터 다시 보고(예산 안), 잠금 안에서는
    판정·쓰기 직전에 그 Claude 가 아직 사는지(_alive) 다시 본다. 잠금은 예산 끝까지만 기다린다. 쓰기 실패로 정한 write_failed 를
    담은 마지막 저장이 실패하면 잠금을 놓은 뒤 _give_up 으로 그 Claude 의 on 기록만 보완하고 예외를 올린다(훅 경로와 같다,
    계획 리뷰 plan2 r1 의 3). 홈이 절대 경로인 폴더가 아니면 아무것도 하지 않는다."""
    if not valid_terminal(terminal) or not _home_ok(home):
        return
    home = Path(home)
    deadline = time.monotonic() + CHECK_BUDGET_S
    wait = started_ms / 1000 + _decide_s() - time.time()
    if wait > 0:
        time.sleep(min(wait, CHECK_BUDGET_S))
    while _ours(record(home, terminal), pid, started_ms):
        info = _hc_get(terminal)
        if info is None:  # hc 실패: 예산 안에서 1초 뒤 다시
            if time.monotonic() + CHECK_EVERY_S > deadline:
                return
            time.sleep(CHECK_EVERY_S)
            continue
        if not _still_foreground(info, pid, started_ms):  # ps 도 잠금 밖에서 본다
            _log(home, f"{terminal} {pid} 확인기: 전경이 그 Claude 가 아니다(판정·쓰기 없음)")
            return
        seen = time.monotonic()
        stage = {"past": False, "failed": False}
        try:
            with _locked(home, terminal, max(0.0, deadline - time.monotonic())):
                if time.monotonic() - seen > FOREGROUND_FRESH_S:
                    continue  # 잠금을 기다리는 사이 전경이 바뀌었을 수 있다: 잠금을 놓고 전경부터 다시 본다
                rec = record(home, terminal)
                if not _ours(rec, pid, started_ms):
                    return
                if not _alive(rec):  # 잠금 안에서 쓰기 직전에 그 Claude 가 아직 사는지 본다(ps 한 번)
                    _log(home, f"{terminal} {pid} 확인기: 그 Claude 가 끝났다(판정·쓰기 없음)")
                    return
                _step(home, rec, None, {}, "worker", info, stage)
                _save(home, rec)
        except _Busy:
            _log(home, f"{terminal} 잠금 대기 초과(확인기)")
        except BaseException:
            if stage["failed"]:
                # write_failed 를 담은 마지막 저장이 실패했다. 다음 사건이 없을 수 있다(첫 질문 대기): 잠금을 놓은 뒤(같은
                # 프로세스가 같은 잠금을 다시 잡는다) 그 Claude 의 on 기록만 보완한다
                _give_up(home, terminal, pid, started_ms)
            raise
        return


# --- 읽기(observe_one·worker-list·relay-status) ---
def running_background(tasks) -> list[dict]:
    """끝나지 않은 백그라운드 일만(최종 리뷰 I1). Stop 입력의 background_tasks 와 Stop 기록의 background 를 같이 받는다.
    사전인 항목 가운데 status 가 없거나(빈 문자열 포함) running·pending(대소문자 무시)인 것만 남긴다. 끝난 일(completed·failed·
    killed·stopped 등)은 세지 않는다: 목록에 끝난 일이 남는 판에서도 워커가 영영 "백그라운드 있음" 이 되지 않는다. 목록이
    아니면 빈 목록. _apply(대리 보고 Stop)와 liveness.idle_hold(observed idle·worker-list)가 같이 쓴다."""
    if not isinstance(tasks, list):
        return []
    return [t for t in tasks if isinstance(t, dict) and _unfinished(t.get("status"))]


def _unfinished(status) -> bool:
    if status is None or status == "":
        return True
    return isinstance(status, str) and status.strip().lower() in RUNNING_STATUSES


def stops(home, terminal: str) -> list[dict]:
    """<home>/relay/<terminal>.stops.json 의 stops(사전인 항목만, 오래된 것부터). 없거나 읽지 못하면 빈 목록."""
    if not valid_terminal(terminal):
        return []
    data = _read_json(_stops_path(home, terminal), None)
    items = data.get("stops") if isinstance(data, dict) else None
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def stop_for_turn(home, terminal: str, turn: int) -> dict | None:
    """turn 이 같은 마지막 Stop 기록(16.7). background 가 목록이 아니면 빈 목록으로 돌려준다. turn 이 정수가 아니거나 없으면
    None(turn 이 null 인 기록은 어느 turn 에도 맞지 않는다)."""
    want = _int(turn)
    if want is None:
        return None
    for item in reversed(stops(home, terminal)):
        if _int(item.get("turn")) == want:
            background = item.get("background")
            return {**item, "background": background if isinstance(background, list) else []}
    return None


def write_failed(home, terminal: str) -> bool:
    """세션 기록의 decided 가 write_failed 다(16.8)."""
    rec = record(home, terminal)
    return rec is not None and rec["decided"] == "write_failed"
