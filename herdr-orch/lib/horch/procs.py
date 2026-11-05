"""프로세스 생존 확인. pid 재사용을 막으려고 시작 시각을 함께 비교한다."""
from __future__ import annotations

import os
import subprocess


def start_time(pid: int) -> str | None:
    try:
        proc = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = proc.stdout.strip()
    return text or None


def alive(pid: int | None, started: str | None) -> bool:
    if not pid or not started:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return start_time(pid) == started


def me() -> tuple[int, str]:
    pid = os.getpid()
    return pid, start_time(pid) or ""
