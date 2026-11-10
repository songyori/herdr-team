"""hc(herdr-core) 호출. hc 를 부르는 유일한 모듈."""
from __future__ import annotations

import json
import os
import subprocess

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


def kill(terminal: str) -> dict:
    return _json(["kill", terminal])


def rm(terminal: str, timeout: float | None = None) -> dict:
    return _json(["rm", terminal], timeout=timeout)


def server_status() -> dict:
    return _json(["server", "status"])
