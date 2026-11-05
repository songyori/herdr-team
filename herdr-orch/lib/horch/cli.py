"""horch 명령 파싱, 실행, JSON 출력."""
from __future__ import annotations

import argparse
import json
import signal
import sys

from .errors import FAIL, USAGE, HorchError
from .paths import VERSION, resolve_home


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise HorchError("usage", message, USAGE)


def build_parser() -> Parser:
    p = Parser(prog="horch")
    p.add_argument("--home")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    sub.add_parser("version")
    # --- 명령 파서 끝 ---
    return p


def _dispatch(args) -> dict:
    home = resolve_home(args.home)
    if args.cmd == "version":
        return {"version": VERSION}
    # --- 저장소 없는 명령 끝 ---
    raise HorchError("usage", f"알 수 없는 명령: {args.cmd} (home {home})", USAGE)


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        args = build_parser().parse_args(argv)
        result = _dispatch(args)
    except HorchError as exc:
        _emit(exc.to_json())
        return exc.exit_code
    except Exception as exc:  # 버그도 JSON 으로 알린다
        _emit({"ok": False, "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}", "hint": ""}})
        return FAIL
    _emit({"ok": True, **result})
    return 0
