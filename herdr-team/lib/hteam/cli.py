"""hteam 명령 파싱, 실행, JSON 출력(설계 8.3).

명령은 모듈마다 `register(sub)` 로 등록한다. 각 하위 파서는 `set_defaults(func=<args -> dict>)` 를 둔다.
"""
from __future__ import annotations

import argparse
import importlib
import signal
import sys

from .errors import FAIL, USAGE, HteamError
from .paths import VERSION
from .util import dumps

# 명령을 등록하는 모듈. 태스크마다 한 줄씩 더한다.
COMMAND_MODULES: tuple[str, ...] = (
    "specs",
    "plan",
    "tasks",
    "review",
    "outbox",
    "ask",
    "approval",
    "lint",
    "image",
    "coord",
    "setup",
    "testgate",
    "followups",
)


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise HteamError("usage", message, USAGE)


def build_parser() -> Parser:
    p = Parser(prog="hteam")
    p.add_argument("--root", help="프로젝트 루트(기본: 현재 폴더에서 위로 .herdr-team/config.toml 을 찾는다)")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    sub.add_parser("version").set_defaults(func=lambda args: {"version": VERSION})
    for name in COMMAND_MODULES:
        importlib.import_module(f"hteam.{name}").register(sub)
    return p


def _emit(obj: dict) -> None:
    sys.stdout.write(dumps(obj) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        args = build_parser().parse_args(argv)
        result = args.func(args)
        # 결과의 _after(인자 없는 함수)는 출력에 넣지 않고 JSON 을 출력한 뒤에 부른다. _exit 는 성공 봉투와 함께 낼 exit
        # 코드다(hteam test 의 failed·timeout 은 결과를 출력하고 exit 1, 설계 5.7)
        after = result.pop("_after", None)
        code = result.pop("_exit", 0)
        # 성공 봉투도 try 안에서 직렬화한다. dict 가 아니거나 JSON 으로 못 바꾸면 internal 오류로 알린다.
        line = dumps({"ok": True, **result})
    except HteamError as exc:
        _emit(exc.to_json())
        return exc.exit_code
    except Exception as exc:  # 버그도 JSON 으로 알린다
        _emit({"ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}", "hint": ""}})
        return FAIL
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    if after:
        _run_after(after)  # 출력한 뒤에야 한다(watch 커서: 적어도 한 번 전달)
    return code


def _run_after(after) -> None:
    """이미 성공 결과를 출력했으므로 stdout·exit 코드를 바꾸지 않는다. 실패는 stderr 에 한 줄로만 남긴다.

    watch 커서라면 옮기지 못한 항목을 다음 watch 가 다시 준다(적어도 한 번 전달이 유지된다)."""
    try:
        after()
    except Exception as exc:
        sys.stderr.write(f"hteam: 출력 뒤 처리 실패(결과는 이미 출력했다): {type(exc).__name__}: {exc}\n")
        sys.stderr.flush()
