"""horch 명령 파싱, 실행, JSON 출력."""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from . import agents, auth, comms, guard, runs, workers
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
    s = sub.add_parser("worker-start")
    spec = s.add_mutually_exclusive_group()
    spec.add_argument("--spec")
    spec.add_argument("--spec-file")
    s.add_argument("--title")
    s.add_argument("--agent", required=True, choices=sorted(agents.AGENTS))
    s.add_argument("--model")
    s.add_argument("--effort")
    s.add_argument("--cwd")
    s.add_argument("--agent-arg", action="append", default=[])
    s.add_argument("--task")
    s.add_argument("--retry", action="store_true")
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
    if args.cmd == "worker-start":
        run_id = auth.owner_run_id(store)
        spec = args.spec
        if args.spec_file:
            try:
                spec = Path(args.spec_file).read_text(encoding="utf-8")
            except OSError as exc:
                raise HorchError("bad_spec_file", f"spec 파일을 읽지 못했다: {exc}", USAGE) from exc
        return workers.start(store, run_id, spec=spec, title=args.title, agent=args.agent, model=args.model,
                             effort=args.effort, cwd=args.cwd or os.getcwd(), extra=args.agent_arg,
                             task_id=args.task, retry=args.retry)
    # --- 저장소 명령 끝 ---
    raise HorchError("usage", f"알 수 없는 명령: {args.cmd}", USAGE)


def _guard_argv(argv: list[str]) -> tuple[str | None, str, list[str]] | None:
    """launch-guard 는 argparse 를 거치지 않는다. -- 뒤 에이전트 인자를 그대로 넘기려고."""
    head = argv[:2] if argv[:1] == ["--home"] and len(argv) >= 2 else []
    rest = argv[len(head):]
    if not rest or rest[0] != "launch-guard":
        return None
    rest = rest[1:]
    if "--" not in rest:
        raise HorchError("usage", "launch-guard 는 -- 뒤에 에이전트 명령이 필요하다", USAGE)
    cut = rest.index("--")
    opts, agent = rest[:cut], rest[cut + 1:]
    if len(opts) != 2 or opts[0] != "--dispatch":
        raise HorchError("usage", "형식: launch-guard --dispatch <id> -- <에이전트 명령>", USAGE)
    return (head[1] if head else None), opts[1], agent


def _run_guard(home_arg: str | None, dispatch_id: str, agent_argv: list[str]) -> int:
    try:
        store = Store(resolve_home(home_arg))
        guard.run(store, dispatch_id, agent_argv)  # 성공하면 돌아오지 않는다
    except HorchError as exc:
        print(f"[horch] launch-guard: {exc.message}", flush=True)
        return exc.exit_code
    return FAIL


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        guard_args = _guard_argv(argv)
    except HorchError as exc:
        print(f"[horch] launch-guard: {exc.message}", flush=True)
        return exc.exit_code
    if guard_args is not None:
        return _run_guard(*guard_args)
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
