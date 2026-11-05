"""hteam 명령 파싱, 실행, JSON 출력(설계 8.3).

명령은 모듈마다 `register(sub)` 로 등록한다. 각 하위 파서는 `set_defaults(func=<args -> dict>)` 를 둔다.
"""
from __future__ import annotations

import argparse
import importlib
import json
import signal
import sys

from .errors import FAIL, USAGE, HteamError
from .paths import VERSION

# 명령을 등록하는 모듈. 태스크마다 한 줄씩 더한다.
COMMAND_MODULES: tuple[str, ...] = (
    "specs",
    "plan",
    "tasks",
    "review",
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
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        args = build_parser().parse_args(argv)
        result = args.func(args)
        # 성공 봉투도 try 안에서 직렬화한다. dict 가 아니거나 JSON 으로 못 바꾸면 internal 오류로 알린다.
        line = json.dumps({"ok": True, **result}, ensure_ascii=False)
    except HteamError as exc:
        _emit(exc.to_json())
        return exc.exit_code
    except Exception as exc:  # 버그도 JSON 으로 알린다
        _emit({"ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}", "hint": ""}})
        return FAIL
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    return 0
