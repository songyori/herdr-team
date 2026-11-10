"""hc(herdr-core) 호출. hc 를 부르는 유일한 모듈."""
from __future__ import annotations

import json
import os
import select
import subprocess
import time

from .errors import MISSING, HorchError

TIMEOUT_S = 30


class HcFailure(Exception):
    """hc 가 실패를 돌려줬다. kind 는 hc 오류 kind(예: not_found) 또는 exit_<코드>·timeout·bad_output."""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


def _call(args: list[str], timeout: float | None = None, env: dict | None = None) -> subprocess.CompletedProcess:
    """timeout 은 초. None 이면 TIMEOUT_S. 시간을 넘기면 hc 를 죽이고 HcFailure("timeout").
    env 가 있으면 hc 를 그 환경으로 부른다(None 이면 이 프로세스의 환경)."""
    limit = TIMEOUT_S if timeout is None else timeout
    try:
        return subprocess.run(["hc", *args], capture_output=True, text=True, timeout=limit, env=env)
    except FileNotFoundError as exc:
        raise HorchError("hc_missing", "hc 실행 파일을 찾지 못했다", MISSING,
                         "herdr-core 를 설치하고 PATH 에 hc 를 둔다") from exc
    except OSError as exc:
        # 실행 권한 없음 등. 터미널이 끝났다는 뜻이 아니므로 호출자는 모름으로 다룬다.
        raise HcFailure("exec_failed", str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HcFailure("timeout", f"hc {' '.join(args[:2])} 가 {limit:g}초 안에 끝나지 않았다") from exc


def _failure(proc: subprocess.CompletedProcess) -> HcFailure:
    for text in (proc.stderr or "", proc.stdout or ""):
        for line in reversed(text.strip().splitlines()):
            try:
                err = json.loads(line).get("error")
            except (ValueError, AttributeError):
                continue
            if isinstance(err, dict):
                return HcFailure(str(err.get("kind") or f"exit_{proc.returncode}"), str(err.get("message") or ""))
    return HcFailure(f"exit_{proc.returncode}", ((proc.stderr or "") + (proc.stdout or "")).strip()[-500:])


def _parse(text: str) -> dict:
    text = text.strip()
    candidates = [text, *reversed(text.splitlines())]
    for cand in candidates:
        try:
            value = json.loads(cand)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
        break  # 유효한 JSON 이지만 객체가 아니다
    raise HcFailure("bad_output", text[-500:])


def _json(args: list[str], tail: list[str] | None = None, timeout: float | None = None,
          env: dict | None = None) -> dict:
    proc = _call([*args, "--json", *(tail or [])], timeout, env)
    if proc.returncode != 0:
        raise _failure(proc)
    return _parse(proc.stdout)


def get(terminal: str, timeout: float | None = None) -> dict:
    return _json(["get", terminal], timeout=timeout)


def ls_all(timeout: float | None = None) -> list[dict]:
    return list(_json(["ls", "--all"], timeout=timeout).get("terminals") or [])


def read(terminal: str, lines: int) -> str:
    proc = _call(["read", terminal, "--lines", str(lines)])
    if proc.returncode != 0:
        raise _failure(proc)
    return proc.stdout


def run_bg(name: str, cwd: str, labels: dict[str, str], argv: list[str]) -> dict:
    args = ["run", "--bg", "--no-parent", "--no-notify", "--name", name, "--cwd", cwd]
    for key, value in labels.items():
        args += ["--label", f"{key}={value}"]
    return _json(args, ["--", *argv])


def send(terminal: str, text: str, if_status: str | None = None, untagged: bool = False, timeout: float = 30) -> dict:
    """hc send 의 결과(sent·started·status·turn)를 그대로 돌려준다.
    untagged 면 HC_TERMINAL_ID 를 뺀 환경으로 보낸다. hc 가 글을 <hc from=…> 로 감싸지 않는다(설계 13.1)."""
    args = ["send", terminal, text]
    if if_status:
        args += ["--if", if_status]
    env = {k: v for k, v in os.environ.items() if k != "HC_TERMINAL_ID"} if untagged else None
    return _json(args, timeout=timeout, env=env)


def label(terminal: str, pairs: dict[str, str], timeout: float = 10) -> dict:
    """hc label T k=v …. 빈 값은 k= 로 그 라벨을 지운다."""
    return _json(["label", terminal, *(f"{k}={v}" for k, v in pairs.items())], timeout=timeout)


def keys(terminal: str, keys: list[str], timeout: float = 10) -> dict:
    """hc keys --json T <키…>. 이름 있는 키(enter, space 등)와 글자 하나씩. --json 은 키 앞에 둔다
    (키 목록 뒤에 두면 키 이름으로 읽힐 수 있다). 슬래시 명령은 감싼 send 가 아니라 이것으로 친다(설계 13.1)."""
    proc = _call(["keys", "--json", terminal, *keys], timeout)
    if proc.returncode != 0:
        raise _failure(proc)
    return _parse(proc.stdout)


class EventStream:
    """hc events 구독. read 가 마감까지 다음 사건을 평평한 dict 로 준다(hc 의 줄 꼴은 이 모듈만 안다).

    사건: {"type", "terminal"} 에 종류마다 더한다. snapshot(구독 첫 줄과 missed 뒤 다시 온 스냅숏의 이 터미널):
    status·turn·title, status: status, turn: turn·status(그 turn 이 끝난 뒤 상태), title: title. status 는 hc get 과 같은 꼴
    ({"app", "state"} 또는 낱말)이라 liveness.status_word 로 읽는다. heartbeat·missed·그 밖의 종류와 JSON 객체가 아닌 줄은
    건너뛴다. 호출자가 늘 close 한다."""

    def __init__(self, proc: subprocess.Popen, terminal: str | None = None):
        self._proc = proc
        self._terminal = terminal
        self._fd = proc.stdout.fileno()
        self._buf = b""
        self.closed = False  # EOF 를 봤거나 닫았다

    def _event(self, line: bytes) -> dict | None:
        try:
            value = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            return None
        return _flat(value, self._terminal) if isinstance(value, dict) else None

    def _next_event(self) -> dict | None:
        while b"\n" in self._buf:
            line, self._buf = self._buf.split(b"\n", 1)
            event = self._event(line)
            if event is not None:
                return event
        return None

    def read(self, timeout: float) -> dict | None:
        """마감(초)까지 다음 사건. 없거나 EOF 면 None. 0 이면 기다리지 않고 이미 온 것만 본다(버퍼와 파이프)."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            event = self._next_event()
            if event is not None or self.closed:
                return event
            ready, _, _ = select.select([self._fd], [], [], max(0.0, deadline - time.monotonic()))
            if not ready:
                return None
            chunk = os.read(self._fd, 65536)
            if not chunk:
                self.closed = True  # 줄바꿈 없이 끝난 마지막 줄도 본다
                tail, self._buf = self._buf, b""
                return self._event(tail) if tail else None
            self._buf += chunk

    def close(self) -> None:
        """살아 있으면 terminate → 2초 → kill 하고 파이프를 닫는다. 여러 번 불러도 된다."""
        self.closed = True
        proc = self._proc
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if proc.stdout and not proc.stdout.closed:
            proc.stdout.close()


def _flat(value: dict, terminal: str | None) -> dict | None:
    """hc events 의 한 줄 → 평평한 사건(EventStream 참고). 첫 줄은 스냅숏 {"channel", "seq", "terminals": [get 꼴]},
    그 뒤는 JSON-RPC 알림 {"jsonrpc", "method": "event", "params": {"type", "terminal", "seq", "data"}}다."""
    if isinstance(value.get("terminals"), list):
        for item in value["terminals"]:
            if isinstance(item, dict) and (terminal is None or item.get("address") == terminal):
                return {"type": "snapshot", "terminal": item.get("address"), "status": item.get("status"),
                        "turn": item.get("turn"), "title": item.get("title")}
        return None
    params = value.get("params") if value.get("method") == "event" else None
    data = params.get("data") if isinstance(params, dict) else None
    if not isinstance(data, dict):
        return None
    kind = params.get("type")
    base = {"type": kind, "terminal": params.get("terminal")}
    if kind == "turn":
        return {**base, "turn": data.get("turn"), "status": data.get("state")}
    if kind == "status":
        return {**base, "status": data.get("status")}
    if kind == "title":
        return {**base, "title": data.get("title")}
    return None


def events(terminal: str) -> EventStream:
    """hc events --json --terminal T 를 띄운다. 마감은 호출자가 read 로 정하고 끝나면 close 한다(설계 13.7)."""
    try:
        proc = subprocess.Popen(["hc", "events", "--json", "--terminal", terminal], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise HorchError("hc_missing", "hc 실행 파일을 찾지 못했다", MISSING,
                         "herdr-core 를 설치하고 PATH 에 hc 를 둔다") from exc
    except OSError as exc:
        raise HcFailure("exec_failed", str(exc)) from exc
    return EventStream(proc, terminal)


def kill(terminal: str, timeout: float = 30) -> dict:
    return _json(["kill", terminal], timeout=timeout)


def rm(terminal: str, timeout: float | None = None) -> dict:
    return _json(["rm", terminal], timeout=timeout)


def server_status() -> dict:
    return _json(["server", "status"])
