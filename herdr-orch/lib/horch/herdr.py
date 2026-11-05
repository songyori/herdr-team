"""herdr-app 호출. herdr-app 을 부르는 유일한 모듈."""
from __future__ import annotations

import subprocess


def app_status() -> tuple[bool, str]:
    try:
        proc = subprocess.run(["herdr-app", "status"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return False, "herdr-app 이 PATH 에 없다"
    except subprocess.TimeoutExpired:
        return False, "herdr-app status 가 10초 안에 끝나지 않았다"
    lines = (proc.stdout or proc.stderr).strip().splitlines()
    return proc.returncode == 0, lines[0] if lines else f"exit {proc.returncode}"
