#!/usr/bin/env python3
"""herdr-orch Claude Code 훅(설계 16.2). 사용법: horch_hook.py <Claude 훅 사건 이름>(표준 입력이 훅 입력) 또는
horch_hook.py relay-check <홈> <터미널> <pid> <started_ms>(대리 보고의 판정 확인기. 훅이 분리 실행하고 훅 입력이 없다).

대상은 Herdr 터미널($HC_TERMINAL_ID) 안의 Claude 세션 가운데 HORCH_HOME(horch 가 띄운 워커, 역할 worker) 또는
HORCH_RELAY_HOME(옵트인한 사람용 세션, 역할 main)이 있는 것이다. 둘 다 있으면 HORCH_HOME 이 앞선다. 홈이 절대 경로가 아니면
대상이 아니다. 그 밖의 세션은 hooks.json 의 셸 한 줄이 파이썬을 띄우지 않고 거른다. 훅은 늘 exit 0 이고, 출력은 메인
알림(메인의 Stop 을 한 번 막는 JSON, relay.handle 이 돌려준다) 하나뿐이다. 오류는 <홈>/relay.log 에 한 줄 남기고 출력하지
않는다. horch.relay 하나만 가져온다(DB 모듈은 가져오지 않는다).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HOOK_START = time.monotonic()  # 훅 마감은 훅이 시작한 때부터 잰다(설계 16.6)
HOOK_DEADLINE_S = 12  # 훅 시작부터 대리 보고를 마칠 시각(hooks.json 의 15초 제한 안)
LIB = Path(__file__).resolve().parents[1] / "lib"


def target() -> tuple[Path, str] | None:
    """(홈, 역할). HORCH_HOME 이 있으면 (그 홈, worker), 비었고 HORCH_RELAY_HOME 이 있으면 (그 홈, main). 고른 홈이 절대
    경로가 아니거나 둘 다 없으면 None(설계 16.2)."""
    home, role = os.environ.get("HORCH_HOME", ""), "worker"
    if not home:
        home, role = os.environ.get("HORCH_RELAY_HOME", ""), "main"
    if not home or not os.path.isabs(home):
        return None
    return Path(home), role


def _relay():
    sys.dont_write_bytecode = True  # 플러그인 폴더에 __pycache__ 를 남기지 않는다(bin/horch 와 같다)
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    from horch import relay
    return relay


def _log_error(home: Path, label: str, exc: BaseException) -> None:
    """<홈>/relay.log 에 `<시각> 오류(<사건>): <타입>: <메시지>` 한 줄(설계 16.3). relay 를 가져오지 못했어도 남긴다. 쓰지
    못하면 넘어간다."""
    try:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        message = str(exc).replace("\n", " ")
        with (home / "relay.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} 오류({label}): {type(exc).__name__}: {message}\n")
    except Exception:  # noqa: BLE001
        pass


def _check(args: list[str]) -> int:
    """확인기: relay-check <홈> <터미널> <pid> <started_ms>. 홈이 절대 경로가 아니면 아무것도 하지 않는다."""
    if len(args) != 4 or not os.path.isabs(args[0]):
        return 0
    home = Path(args[0])
    try:
        _relay().check(home, args[1], int(args[2]), int(args[3]))
    except Exception as exc:  # noqa: BLE001
        _log_error(home, "relay-check", exc)
    return 0


def main(argv: list[str]) -> int:
    if argv[:1] == ["relay-check"]:
        return _check(argv[1:])
    found = target()
    if len(argv) != 1 or found is None or not os.environ.get("HC_TERMINAL_ID"):
        return 0
    home, role = found
    event = argv[0]
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError, UnicodeDecodeError):
        return 0
    try:
        out = _relay().handle(home, event, payload, role=role, deadline=HOOK_START + HOOK_DEADLINE_S)
    except Exception as exc:  # noqa: BLE001  훅 오류는 세션을 막지 않는다
        _log_error(home, event, exc)
        return 0
    if out:  # 메인 알림(Stop 을 한 번 막는다)
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
