"""Claude·Codex 실행 명령(설계 8장 에이전트 명령)."""
from __future__ import annotations

from pathlib import Path

from .errors import USAGE, HorchError

AGENTS = {"claude": "claude", "codex": "codex"}


def executable(agent: str) -> str:
    try:
        return AGENTS[agent]
    except KeyError:
        raise HorchError("unknown_agent", f"지원하지 않는 에이전트: {agent}", USAGE) from None


def build(agent: str, *, model: str | None, effort: str | None, extra: list[str], preamble: str,
          home: Path) -> list[str]:
    exe = executable(agent)
    if agent == "claude":
        argv = [exe]
        if model:
            argv += ["--model", model]
        if effort:
            argv += ["--effort", effort]
    else:
        argv = [exe, "--no-daemon", "-s", "workspace-write", "-a", "never", "--add-dir", str(home)]
        if model:
            argv += ["-m", model]
        if effort:
            argv += ["-c", f"model_reasoning_effort={effort}"]
    # extra 끝의 가변 인자 옵션(--add-dir 등)이 프리앰블을 삼키지 않도록 "--" 로 끊는다.
    return [*argv, *extra, "--", preamble]
