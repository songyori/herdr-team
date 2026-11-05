"""버전, 저장 루트, horch 절대 경로."""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

VERSION = "0.1.0"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
HORCH_BIN = PLUGIN_ROOT / "bin" / "horch"


def resolve_home(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    env = os.environ.get("HERDR_ORCH_HOME")
    if env:
        return Path(env).expanduser().resolve()
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return (Path(state).expanduser() / "herdr-orch").resolve()


def horch_argv(home: Path) -> list[str]:
    """워커·깨우기 글에 넣는 horch 실행 argv. PATH 와 환경에 기대지 않는다."""
    return [sys.executable, str(HORCH_BIN), "--home", str(home)]


def horch_cmd(home: Path) -> str:
    return " ".join(shlex.quote(a) for a in horch_argv(home))
