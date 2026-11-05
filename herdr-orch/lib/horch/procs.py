"""프로세스 생존 확인. pid 재사용을 막으려고 시작 시각을 함께 비교한다.

확인할 수 없으면 "살아 있음"(모름)으로 둔다. 거짓 "죽음"만 해롭고 거짓 "삶"은 지연일 뿐이다.
"""
from __future__ import annotations

import os
import subprocess

# lstart 는 로컬 시간이라 TZ·로케일에 따라 값이 달라진다. 항상 같은 환경으로 부른다.
_PS_ENV_OVERRIDE = {"TZ": "UTC", "LC_ALL": "C"}


def _ps_state(pid: int) -> tuple[str, str] | None | bool:
    """(stat, lstart) 를 돌려준다. 행이 없으면 None, ps 를 못 돌렸으면 False."""
    try:
        proc = subprocess.run(["ps", "-o", "stat=", "-o", "lstart=", "-p", str(pid)],
                              capture_output=True, text=True, timeout=5,
                              env={**os.environ, **_PS_ENV_OVERRIDE})
    except (OSError, subprocess.TimeoutExpired):
        return False
    text = proc.stdout.strip()
    if not text:
        # 행이 없다: ps 가 정상 종료(1)했으면 프로세스가 없는 것, 다른 실패면 모름
        return None if proc.returncode in (0, 1) and not proc.stderr.strip() else False
    parts = text.split(None, 1)
    return parts[0], (parts[1].strip() if len(parts) > 1 else "")


def start_time(pid: int) -> str | None:
    state = _ps_state(pid)
    if not state:
        return None
    return state[1] or None


def alive(pid: int | None, started: str | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    state = _ps_state(pid)
    if state is False:
        return True          # ps 를 못 돌렸다: 모름 -> 살아 있음
    if state is None:
        return False         # ps 는 정상인데 행이 없다: 없다
    stat, lstart = state
    if stat.startswith("Z"):
        return False         # 좀비: 이미 끝났다
    if not started:
        return True          # 재사용 여부를 확인할 수 없다: 보수적으로 살아 있음
    return lstart == started


def me() -> tuple[int, str]:
    pid = os.getpid()
    return pid, start_time(pid) or ""
