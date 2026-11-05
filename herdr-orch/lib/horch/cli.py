"""horch 명령 파싱, 실행, JSON 출력."""
from __future__ import annotations

import argparse
import json
import signal
import sys

from . import comms, runs
from .errors import FAIL, USAGE, HorchError
from .paths import VERSION, resolve_home
from .store import Store


class Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise HorchError("usage", message, USAGE)


def build_parser() -> Parser:
    p = Parser(prog="horch")
    p.add_argument("--home")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    sub.add_parser("version")
    s = sub.add_parser("run-create")
    s.add_argument("--objective", required=True)
    s = sub.add_parser("run-use")
    s.add_argument("--id", required=True)
    s.add_argument("--force", action="store_true")
    sub.add_parser("status")
    s = sub.add_parser("send")
    s.add_argument("--to", required=True)
    s.add_argument("--subject")
    s.add_argument("--body", required=True)
    s = sub.add_parser("check")
    s.add_argument("--dispatch")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--timeout-ms", type=int, default=900000)
    s.add_argument("--ack", type=int)
    # --- 명령 파서 끝 ---
    return p


def _dispatch(args) -> dict:
    home = resolve_home(args.home)
    if args.cmd == "version":
        return {"version": VERSION}
    # --- 저장소 없는 명령 끝 ---
    store = Store(home)
    try:
        return _with_store(args, store)
    finally:
        store.close()


def _with_store(args, store: Store) -> dict:
    if args.cmd == "run-create":
        return runs.create(store, args.objective)
    if args.cmd == "run-use":
        return runs.use(store, args.id, args.force)
    if args.cmd == "status":
        return runs.status(store)
    if args.cmd == "send":
        return comms.send(store, args.to, args.subject, args.body)
    if args.cmd == "check":
        return comms.check(store, dispatch=args.dispatch, wait=args.wait, timeout_ms=args.timeout_ms, ack=args.ack)
    # --- 저장소 명령 끝 ---
    raise HorchError("usage", f"알 수 없는 명령: {args.cmd}", USAGE)


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
