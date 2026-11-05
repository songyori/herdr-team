"""horch 호출. horch 를 부르는 유일한 모듈(설계 3.1). 늘 `--home <프로젝트>/.herdr-team/state/horch` 로 부른다."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from .errors import FAIL, MISSING, HteamError
from .paths import PLUGIN_ROOT


def _registry() -> Path:
    return Path(os.environ.get("HTEAM_PLUGINS_JSON")
                or Path.home() / ".claude" / "plugins" / "installed_plugins.json")


def find_horch() -> Path:
    """HERDR_ORCH_BIN → 형제 ../herdr-orch/bin/horch → installed_plugins.json 의 herdr-orch. 없으면 exit 12."""
    env = os.environ.get("HERDR_ORCH_BIN")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return path.resolve()
        raise HteamError("horch_missing", f"HERDR_ORCH_BIN 이 가리키는 파일이 없다: {path}", MISSING)
    sibling = PLUGIN_ROOT.parent / "herdr-orch" / "bin" / "horch"
    if sibling.is_file():
        return sibling.resolve()
    try:
        data = json.loads(_registry().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    plugins = data.get("plugins", data) if isinstance(data, dict) else {}
    for key, entries in (plugins.items() if isinstance(plugins, dict) else []):
        if key.split("@", 1)[0] != "herdr-orch" or not isinstance(entries, list):
            continue
        for entry in entries:
            path = entry.get("installPath") if isinstance(entry, dict) else None
            if path and (Path(path) / "bin" / "horch").is_file():
                return (Path(path) / "bin" / "horch").resolve()
    raise HteamError("horch_missing", "herdr-orch(horch)를 찾지 못했다", MISSING,
                     "/plugin install herdr-orch@herdr-team 으로 설치하거나 HERDR_ORCH_BIN 을 준다")


def parse(stdout: str, stderr: str = "") -> dict:
    """stdout 의 마지막 JSON 객체 줄. 없으면 bad_output 오류 모양."""
    for line in reversed((stdout or "").strip().splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    tail = ((stdout or "") + (stderr or "")).strip()[-500:]
    return {"ok": False, "error": {"code": "bad_output", "message": f"horch 출력이 JSON 이 아니다: {tail}", "hint": ""}}


def failure(code: int, data: dict, args: tuple) -> HteamError:
    err = data.get("error") or {}
    return HteamError("horch_failed", f"horch {args[0] if args else ''} 실패: {err.get('code')}: {err.get('message')}",
                      MISSING if code == MISSING else FAIL, err.get("hint") or "", data={"horch": data})


def agent_args(args: list[str]) -> list[str]:
    """`-` 로 시작하는 인자도 값으로 넘어가게 `--agent-arg=<인자>` 로 붙인다."""
    return [f"--agent-arg={a}" for a in args]


class Horch:
    def __init__(self, home: Path):
        self.bin = find_horch()
        self.home = Path(home)

    def argv(self, *args: str) -> list[str]:
        return [sys.executable, str(self.bin), "--home", str(self.home), *args]

    def cmd(self) -> str:
        """사람과 에이전트에게 보여 줄 horch 명령(절대 경로와 --home 포함)."""
        return " ".join(shlex.quote(a) for a in self.argv())

    def call(self, *args: str, timeout: float = 120) -> tuple[int, dict]:
        try:
            proc = subprocess.run(self.argv(*args), capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return FAIL, {"ok": False, "error": {"code": "horch_timeout",
                                                 "message": f"horch {args[0]} 가 {timeout:g}초 안에 끝나지 않았다",
                                                 "hint": ""}}
        return proc.returncode, parse(proc.stdout, proc.stderr)

    def ok(self, *args: str, timeout: float = 120) -> dict:
        code, data = self.call(*args, timeout=timeout)
        if code != 0 or not data.get("ok"):
            raise failure(code, data, args)
        return data

    def workers(self, states=None) -> list[dict]:
        """worker-list 행. 코디네이터(Run 소유자) 터미널에서만 된다. states 를 주면 그 상태만(--state 반복)."""
        flags = [x for s in states or () for x in ("--state", s)]
        return list(self.ok("worker-list", *flags).get("workers") or [])
