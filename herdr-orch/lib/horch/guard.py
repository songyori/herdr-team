"""launch-guard: 워커 터미널에서 에이전트보다 먼저 돌며 Dispatch 를 등록한 뒤 exec 한다(설계 5·8장)."""
from __future__ import annotations

import json
import os
import signal
from pathlib import Path

from . import agents, auth
from .errors import CONFLICT, MISSING, USAGE, HorchError


def inject_codex_env(argv: list[str], terminal: str, env: dict[str, str] | None = None) -> list[str]:
    """Codex 설정이 inherit=core 여도 Codex 셸에 HC_TERMINAL_ID 와 worker-start --env 값이 보이게 한다.
    --env 값은 HC_TERMINAL_ID 뒤에 이름 순서로 더한다(사전 검증 S2: 환경에만 두면 사용자 정책이 뺀다)."""
    if argv and Path(argv[0]).name == "codex":
        extra = ["-c", f"shell_environment_policy.set.HC_TERMINAL_ID={agents.toml_str(terminal)}"]
        for name in sorted(env or {}):
            extra += ["-c", f"shell_environment_policy.set.{name}={agents.toml_str(env[name])}"]  # -c 값은 TOML 이다
        return [argv[0], *extra, *argv[1:]]
    return list(argv)


def claim(store, dispatch_id: str, terminal: str) -> None:
    """launching 이면 이 터미널로 등록한다. 등록과 launch_failed 판정은 같은 행의 조건부 쓰기라 한쪽만 성공한다."""
    with store.tx():
        row = store.one("SELECT state, terminal FROM dispatches WHERE id=?", (dispatch_id,))
        if row is None:
            raise HorchError("unknown_dispatch", f"Dispatch {dispatch_id} 가 없다", CONFLICT)
        if row["state"] == "launching":
            store.run("UPDATE dispatches SET terminal=?, state='active' WHERE id=? AND state='launching'",
                      (terminal, dispatch_id))
            return
        if row["state"] == "active" and row["terminal"] == terminal:
            return
        raise HorchError("guard_refused",
                         f"Dispatch {dispatch_id} 는 {row['state']}(터미널 {row['terminal'] or '없음'})라 "
                         f"이 터미널({terminal})에서 에이전트를 실행하지 않는다", CONFLICT)


def run(store, dispatch_id: str, argv: list[str]) -> None:
    terminal = auth.caller()
    if not terminal:
        raise HorchError("no_terminal", "$HC_TERMINAL_ID 가 없다. 가드는 hc 터미널 안에서만 돈다", CONFLICT)
    if not argv:
        raise HorchError("usage", "에이전트 명령이 없다", USAGE)
    claim(store, dispatch_id, terminal)
    # worker-start --env 값(설계 14.3). hc run 터미널은 부른 셸의 환경을 물려받지 않으므로 exec 직전에 더한다
    raw = store.one("SELECT env FROM dispatches WHERE id=?", (dispatch_id,))["env"]
    env = json.loads(raw) if raw is not None else None
    final = inject_codex_env(argv, terminal, env)
    store.close()
    # CPython 이 무시로 바꾼 SIGPIPE·SIGXFSZ 는 exec 뒤에도 남아 에이전트와 자식이 물려받으므로 되돌린다.
    for name in ("SIGPIPE", "SIGXFSZ"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), signal.SIG_DFL)
    if env is not None:
        os.environ.update(env)  # 같은 이름은 덮어쓴다. 프리앰블에는 넣지 않는다(Codex 는 위의 -c 인자로도 받는다)
    try:
        os.execvp(final[0], final)
    except OSError as exc:
        raise HorchError("exec_failed", f"{final[0]} 를 실행하지 못했다: {exc}", MISSING) from exc
