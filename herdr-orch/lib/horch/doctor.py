"""doctor 점검(설계 10장). 필수 점검이 실패하면 exit 1."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import hcio, herdr
from .errors import FAIL, HorchError


def _check(name: str, ok, detail: str, level: str = "error") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "level": level}


def run(home: Path) -> dict:
    checks = [_check("python", sys.version_info >= (3, 11), platform.python_version())]
    hc_path = shutil.which("hc")
    checks.append(_check("hc", hc_path, hc_path or "PATH 에 없다"))
    if hc_path:
        try:
            st = hcio.server_status()
            checks.append(_check("hc_server", True, f"pid {st.get('pid')}, version {st.get('version')}"))
        except (hcio.HcFailure, HorchError) as exc:
            checks.append(_check("hc_server", False, str(exc)))
    ok, detail = herdr.app_status()
    checks.append(_check("herdr_app", ok, detail))
    try:
        home.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=home) as probe:
            probe.write(b"ok")
            probe.flush()
        checks.append(_check("home_writable", True, str(home)))
    except OSError as exc:
        checks.append(_check("home_writable", False, f"{home}: {exc}"))
    checks.append(_check("ps", shutil.which("ps"), "프로세스 생존 확인에 쓴다"))
    for agent in ("claude", "codex"):
        path = shutil.which(agent)
        checks.append(_check(agent, path, path or "PATH 에 없다", "warning"))
    if shutil.which("codex"):
        try:
            text = subprocess.run(["codex", "--help"], capture_output=True, text=True, timeout=20).stdout
            checks.append(_check("codex_no_daemon", "--no-daemon" in text, "codex --help 에 --no-daemon", "warning"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append(_check("codex_no_daemon", False, str(exc), "warning"))
    if not all(c["ok"] for c in checks if c["level"] == "error"):
        raise HorchError("unhealthy", "필수 점검이 실패했다", FAIL, data={"checks": checks})
    return {"healthy": True, "checks": checks}
