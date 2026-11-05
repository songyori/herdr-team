"""테스트 공통: 임시 저장 루트, 가짜 hc 상태, horch 실행."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "horch"
FAKES = Path(__file__).resolve().parent / "fakes"
sys.path.insert(0, str(ROOT / "lib"))


class HorchCase(unittest.TestCase):
    """가짜 hc 상태 파일: {"next": int, "terminals": {addr: {...}}, "fail": {cmd: {...}}, "screens": {addr: str}, "sent": [...]}"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.hcdir = self.tmp / "hc"
        self.hcdir.mkdir()
        self.set_hc_state({"next": 1, "terminals": {}, "fail": {}, "screens": {}, "sent": []})
        drop = ("HC_TERMINAL_ID", "CODEX_SANDBOX", "HERDR_ORCH_HOME", "XDG_STATE_HOME")
        self.env = {k: v for k, v in os.environ.items() if k not in drop}
        self.env.update({
            "PATH": f"{FAKES}{os.pathsep}{os.environ['PATH']}",
            "FAKE_HC_DIR": str(self.hcdir),
            "HORCH_POLL": "0.05",
            "HORCH_SWEEP_INTERVAL": "0.1",
            "HORCH_REWAKE_INTERVAL": "0.3",
            "PYTHONDONTWRITEBYTECODE": "1",
        })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- 가짜 hc 상태 ---
    def hc_state(self) -> dict:
        return json.loads((self.hcdir / "state.json").read_text())

    def set_hc_state(self, state: dict) -> None:
        (self.hcdir / "state.json").write_text(json.dumps(state))

    def add_terminal(self, address: str, *, name: str | None = None, state: str = "live",
                     status: str | None = None, argv: list[str] | None = None,
                     labels: dict | None = None, reason: str | None = None, turn: int = 0) -> None:
        st = self.hc_state()
        st["terminals"][address] = {
            "address": address, "name": name, "state": state,
            "status": {"app": "claude-code", "state": status, "msg": ""} if status else None,
            "argv": argv or ["sh"], "labels": labels or {}, "reason": reason, "turn": turn,
            "cwd": str(self.tmp), "exit_code": None if state == "live" else 0,
        }
        self.set_hc_state(st)

    def update_terminal(self, address: str, **fields) -> None:
        st = self.hc_state()
        t = st["terminals"][address]
        if "status" in fields:
            word = fields.pop("status")
            t["status"] = {"app": "claude-code", "state": word, "msg": ""} if word else None
        t.update(fields)
        self.set_hc_state(st)

    def fail_hc(self, command: str, kind: str, code: int = 1, create: bool = False) -> None:
        st = self.hc_state()
        st["fail"][command] = {"kind": kind, "code": code, "create": create}
        self.set_hc_state(st)

    def hc_calls(self) -> list[list[str]]:
        path = self.hcdir / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def hc_sent(self) -> list[dict]:
        return self.hc_state().get("sent", [])

    # --- horch 실행 ---
    def horch(self, *args: str, terminal: str | None = None, env: dict | None = None,
              timeout: float = 30) -> tuple[int, dict]:
        proc = subprocess.run(self._cmd(args), capture_output=True, text=True,
                              env=self._env(terminal, env), timeout=timeout)
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = {"raw": proc.stdout, "stderr": proc.stderr}
        return proc.returncode, data

    def horch_bg(self, *args: str, terminal: str | None = None, env: dict | None = None) -> subprocess.Popen:
        return subprocess.Popen(self._cmd(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=self._env(terminal, env))

    @staticmethod
    def finish(proc: subprocess.Popen, timeout: float = 30) -> tuple[int, dict]:
        out, err = proc.communicate(timeout=timeout)
        try:
            return proc.returncode, json.loads(out)
        except ValueError:
            return proc.returncode, {"raw": out, "stderr": err}

    def _cmd(self, args) -> list[str]:
        return [sys.executable, str(BIN), "--home", str(self.home), *args]

    def _env(self, terminal: str | None, extra: dict | None) -> dict:
        env = dict(self.env)
        if terminal:
            env["HC_TERMINAL_ID"] = terminal
        if extra:
            env.update(extra)
        return env

    # --- DB ---
    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.home / "orch.db")
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        return conn

    # --- 자주 쓰는 준비 ---
    def make_owner(self, address: str = "t100", space: str | None = "spA", tab: str | None = "tbA") -> str:
        labels = {"herdr.space": space, "herdr.tab": tab} if space and tab else {}
        self.add_terminal(address, argv=["claude"], labels=labels, status="idle")
        code, out = self.horch("run-create", "--objective", "test", terminal=address)
        self.assertEqual(code, 0, out)
        return out["run"]["id"]

    def start_worker(self, owner: str = "t100", agent: str = "claude", title: str = "T",
                     spec: str = "do it", extra: tuple[str, ...] = ()) -> dict:
        code, out = self.horch("worker-start", "--agent", agent, "--title", title, "--spec", spec,
                               "--cwd", str(self.tmp), *extra, terminal=owner)
        self.assertEqual(code, 0, out)
        return out
