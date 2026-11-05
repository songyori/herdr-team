"""Claude·Codex 실행 명령(설계 8장 에이전트 명령)."""
from __future__ import annotations

from pathlib import Path

from .errors import USAGE, HorchError

AGENTS = {"claude": "claude", "codex": "codex"}

# 호출자가 이 옵션을 주면 기본 -s·-a 를 빼야 한다(겹치면 Codex 가 시작 전에 exit 2 로 끝난다).
# --dangerously-bypass-approvals-and-sandbox 는 -a 와 충돌하고 -s 도 대신한다.
# --yolo·--full-auto 는 같은 계열 별칭·조합으로 보고 둘 다 뺀다(--full-auto 는 현재 도움말에 없어 보수적으로 처리).
# --approve-for-me 는 도움말상 "자동 검토로 승인 요청을 보내며 workspace-write 샌드박스를 쓴다"여서 -s·-a 모두 대신한다.
_BYPASS = {"--dangerously-bypass-approvals-and-sandbox", "--yolo", "--full-auto", "--approve-for-me"}


def _has(extra: list[str], names: set[str], short: str) -> bool:
    """extra 가 names 중 하나를 쓰는지 본다. short(-s·-a)는 `-sread-only`·`-s=…` 붙여쓰기도 잡는다."""
    for a in extra:
        if not a.startswith("-"):
            continue
        if a in names or a.split("=", 1)[0] in names:
            return True
        if a.startswith(short) and not a.startswith("--") and len(a) > len(short):
            return True
    return False


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
        argv = [exe, "--no-daemon"]
        if not _has(extra, _BYPASS | {"-s", "--sandbox"}, "-s"):
            argv += ["-s", "workspace-write"]
        if not _has(extra, _BYPASS | {"-a", "--ask-for-approval"}, "-a"):
            argv += ["-a", "never"]
        argv += ["--add-dir", str(home)]
        if model:
            argv += ["-m", model]
        if effort:
            argv += ["-c", f"model_reasoning_effort={effort}"]
    # extra 끝의 가변 인자 옵션(--add-dir 등)이 프리앰블을 삼키지 않도록 "--" 로 끊는다.
    return [*argv, *extra, "--", preamble]
