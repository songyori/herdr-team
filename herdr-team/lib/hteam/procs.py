"""프로세스 생존 확인. pid 재사용을 막으려고 시작 시각을 함께 비교한다(horch 와 같은 규칙).

확인할 수 없으면 "살아 있음"(모름)으로 둔다. 거짓 "죽음"만 해롭고 거짓 "삶"은 지연일 뿐이다.
"""
from __future__ import annotations

import os
import subprocess

# lstart 는 로컬 시간이라 TZ·로케일에 따라 값이 달라진다. 항상 같은 환경으로 부른다.
_PS_ENV_OVERRIDE = {"TZ": "UTC", "LC_ALL": "C"}


def _ps_state(pid: int, timeout: float = 5) -> tuple[str, str] | None | bool:
    """(stat, lstart) 를 돌려준다. 행이 없으면 None, ps 를 못 돌렸으면(시간 제한 timeout 초 포함) False."""
    try:
        proc = subprocess.run(["ps", "-o", "stat=", "-o", "lstart=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, **_PS_ENV_OVERRIDE})
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = proc.stdout.strip()
    if not text:
        return None if proc.returncode in (0, 1) and not proc.stderr.strip() else False
    parts = text.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def start_time(pid: int, timeout: float = 5) -> str | None:
    state = _ps_state(pid, timeout)
    if not state:
        return None
    return state[1] or None


def alive(pid: int | None, started: str | None, timeout: float = 5) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    state = _ps_state(pid, timeout)
    if state is False:
        return True
    if state is None:
        return False
    stat, lstart = state
    if stat.startswith("Z"):
        return False
    if not started:
        return True
    return lstart == started


def me() -> dict:
    pid = os.getpid()
    return {"pid": pid, "started": start_time(pid) or ""}


def record_alive(rec: dict | None, timeout: float = 5) -> bool:
    """{pid, started} 기록이 가리키는 프로세스가 살아 있나. 기록이 없으면 False. timeout 은 ps 의 시간 제한(초)."""
    return bool(rec) and alive(rec.get("pid"), rec.get("started"), timeout)
