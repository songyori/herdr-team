"""hc(herdr-core) 호출. hc 를 부르는 유일한 모듈."""
from __future__ import annotations

import json
import subprocess

from .errors import MISSING, HorchError

TIMEOUT_S = 30


class HcFailure(Exception):
    """hc 가 실패를 돌려줬다. kind 는 hc 오류 kind(예: not_found) 또는 exit_<코드>·timeout·bad_output."""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.message = message


def _call(args: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["hc", *args], capture_output=True, text=True, timeout=TIMEOUT_S)
    except FileNotFoundError as exc:
        raise HorchError("hc_missing", "hc 실행 파일을 찾지 못했다", MISSING,
                         "herdr-core 를 설치하고 PATH 에 hc 를 둔다") from exc
    except subprocess.TimeoutExpired as exc:
        raise HcFailure("timeout", f"hc {' '.join(args[:2])} 가 {TIMEOUT_S}초 안에 끝나지 않았다") from exc


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
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    raise HcFailure("bad_output", text[-500:])


def _json(args: list[str], tail: list[str] | None = None) -> dict:
    proc = _call([*args, "--json", *(tail or [])])
    if proc.returncode != 0:
        raise _failure(proc)
    return _parse(proc.stdout)


def get(terminal: str) -> dict:
    return _json(["get", terminal])


def ls_all() -> list[dict]:
    return list(_json(["ls", "--all"]).get("terminals") or [])


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


def send(terminal: str, text: str, if_status: str | None = None) -> dict:
    args = ["send", terminal, text]
    if if_status:
        args += ["--if", if_status]
    return _json(args)


def kill(terminal: str) -> dict:
    return _json(["kill", terminal])


def rm(terminal: str) -> dict:
    return _json(["rm", terminal])


def server_status() -> dict:
    return _json(["server", "status"])
