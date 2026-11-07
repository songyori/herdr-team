"""테스트 공통: 임시 git 프로젝트, 실제 horch + horch 의 가짜 hc·herdr-app·claude·codex, hteam 실행, 가짜 에이전트 동작.

실제 hc·Herdr·에이전트를 건드리지 않는다. 가짜 hc 의 run 은 프로그램을 실행하지 않으므로, 워커·리뷰어가 할 일은
`act()`(tests/fakes/agent-act)가 워커 터미널 환경에서 대신한다.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
BIN = ROOT / "bin" / "hteam"
HORCH_BIN = REPO / "herdr-orch" / "bin" / "horch"
HORCH_FAKES = REPO / "herdr-orch" / "tests" / "fakes"
FAKES = Path(__file__).resolve().parent / "fakes"
sys.path.insert(0, str(ROOT / "lib"))

NONCE = "nonce-test"
COORD = "t100"  # 코디네이터 터미널(Run 소유자)
MAIN = "t1"  # 메인 터미널

BASE_CONFIG = """max_parallel = 4
user_approval_roles = []

[coordinator]
model = "opus"
effort = "xhigh"

[review]
max_rounds = 3

[defaults]
worker = "claude"
claude_model = "sonnet"
claude_effort = "xhigh"
codex_model = "gpt-6.1-sol"
codex_effort = "high"

[agents.claude]
args = []
[agents.codex]
args = ["--disable=hooks"]

[roles.planner]
title = "기획"
owns = ["docs/planning/**"]

[roles.developer]
title = "개발"
claude_model = "opus"
owns = ["src/**"]

[roles.tester]
title = "테스트"
owns = ["tests/**", "docs/qa/**"]
"""

VALID_BODY = """## Target
src/app.py

## Change
hello 를 출력한다.

## Constraints
표준 라이브러리만.

## Acceptance
- python3 src/app.py 가 hello 를 출력한다.
"""


# 테스트가 물려받지 않는 환경 변수: 바깥 세션의 역할·Herdr·horch 값과 git 의 저장소·설정 위치, 죽음·멈춤 재현 지점,
# 캐시 폴더(hteam image 의 실행 폴더가 사용자 캐시에 쌓이지 않게. HOME 은 임시 폴더다)
DROP_ENV = ("HC_TERMINAL_ID", "CODEX_SANDBOX", "HERDR_ORCH_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "HTEAM_ROLE",
            "HTEAM_LAUNCH", "HERDR_ORCH_BIN", "HERDR_TEAM_PLUGIN_ROOT", "CLAUDE_PROJECT_DIR", "HTEAM_TEST_DIE_AT",
            "HORCH_TEST_DIE_AT", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
            "GIT_CONFIG_GLOBAL", "HTEAM_TEST_PAUSE_AT", "HTEAM_TEST_PAUSE_FILE")


class TeamCase(unittest.TestCase):
    """가짜 hc 상태 파일 형식은 herdr-orch/tests/helpers.py 의 HorchCase 와 같다."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()
        self.hcdir = self.tmp / "hc"
        self.hcdir.mkdir()
        (self.tmp / "home").mkdir()
        self.set_hc_state({"next": 200, "terminals": {}, "fail": {}, "screens": {}, "sent": []})
        drop = DROP_ENV
        self.env = {k: v for k, v in os.environ.items() if k not in drop}
        self.env.update({
            "PATH": f"{FAKES}{os.pathsep}{HORCH_FAKES}{os.pathsep}{os.environ['PATH']}",
            "FAKE_HC_DIR": str(self.hcdir),
            "HOME": str(self.tmp / "home"),
            "HTEAM_PLUGINS_JSON": str(self.tmp / "no-plugins.json"),
            "HTEAM_KNOWN_MARKETPLACES_JSON": str(self.tmp / "no-markets.json"),
            "HORCH_POLL": "0.05",
            "HORCH_SWEEP_INTERVAL": "0.1",
            "HORCH_REWAKE_INTERVAL": "0.3",
            "HTEAM_POLL": "0.05",
            "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        })
        self.git("init", "-q", "-b", "main")
        (self.proj / "README.md").write_text("# proj\n")
        self.git("add", "README.md")
        self.git("commit", "-q", "-m", "init")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # --- git ---
    def git(self, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(self.proj), *args], capture_output=True, text=True, env=self.env)
        if proc.returncode != 0:
            raise AssertionError(f"git {args} 실패: {proc.stderr}")
        return proc.stdout

    def commit(self, rel: str, text: str, message: str) -> str:
        path = self.proj / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.git("add", "--", rel)
        self.git("commit", "-q", "-m", message, "--", rel)
        return self.git("rev-parse", "HEAD").strip()

    def submodule(self, rel: str = "sub") -> str:
        """프로젝트 안에 서브모듈 rel(추적 파일 a.txt 하나)을 더해 커밋한다. 서브모듈의 HEAD 를 낸다."""
        src = self.tmp / f"{rel.replace('/', '-')}-src"  # rel 이 하위 폴더(`tests/vendor`)여도 된다
        src.mkdir()
        (src / "a.txt").write_text("a\n")
        for args in (("init", "-q", "-b", "main"), ("add", "a.txt"), ("commit", "-q", "-m", "a")):
            subprocess.run(["git", "-C", str(src), *args], check=True, capture_output=True, env=self.env)
        self.git("-c", "protocol.file.allow=always", "submodule", "add", "-q", str(src), rel)
        self.git("commit", "-q", "-m", "서브모듈", "--", ".gitmodules", rel)
        return self.git("-C", rel, "rev-parse", "HEAD").strip()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    # --- 가짜 hc 상태(herdr-orch HorchCase 와 같은 잠금 규칙) ---
    @contextlib.contextmanager
    def _hc_locked(self):
        with open(self.hcdir / "lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.hcdir / "state.json"
            st = json.loads(path.read_text())
            yield st
            path.write_text(json.dumps(st))

    def hc_state(self) -> dict:
        with open(self.hcdir / "lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return json.loads((self.hcdir / "state.json").read_text())

    def set_hc_state(self, state: dict) -> None:
        with open(self.hcdir / "lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            (self.hcdir / "state.json").write_text(json.dumps(state))

    def add_terminal(self, address: str, *, name: str | None = None, state: str = "live",
                     status: str | None = None, argv: list[str] | None = None,
                     labels: dict | None = None, reason: str | None = None, turn: int = 0) -> None:
        with self._hc_locked() as st:
            st["terminals"][address] = {
                "address": address, "name": name, "state": state,
                "status": {"app": "claude-code", "state": status, "msg": ""} if status else None,
                "argv": argv or ["sh"], "labels": labels or {}, "reason": reason, "turn": turn,
                "cwd": str(self.proj), "exit_code": None if state == "live" else 0,
            }

    def update_terminal(self, address: str, **fields) -> None:
        with self._hc_locked() as st:
            t = st["terminals"][address]
            if "status" in fields:
                word = fields.pop("status")
                t["status"] = {"app": "claude-code", "state": word, "msg": ""} if word else None
            t.update(fields)

    def fail_hc(self, command: str, kind: str, code: int = 1) -> None:
        with self._hc_locked() as st:
            st["fail"][command] = {"kind": kind, "code": code, "create": False}

    def hc_calls(self) -> list[list[str]]:
        path = self.hcdir / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def herdr_calls(self) -> list[list[str]]:
        path = self.hcdir / "herdr-calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    # --- 프로젝트 준비 ---
    @property
    def team(self) -> Path:
        return self.proj / ".herdr-team"

    @property
    def state_dir(self) -> Path:
        return self.team / "state"

    @property
    def horch_home(self) -> Path:
        return self.state_dir / "horch"

    def init_project(self, config: str = BASE_CONFIG, roles: tuple[str, ...] = ("planner", "developer", "tester"),
                     commit: bool = True) -> None:
        """scaffold 없이 최소 프로젝트를 만든다: config.toml, 직무 문서, project.md, .gitignore."""
        (self.team / "roles").mkdir(parents=True, exist_ok=True)
        (self.team / "tasks").mkdir(exist_ok=True)
        (self.team / "config.toml").write_text(config, encoding="utf-8")
        (self.team / "project.md").write_text("테스트 프로젝트\n", encoding="utf-8")
        for role in roles:
            (self.team / "roles" / f"{role}.md").write_text(f"# {role} 직무 문서\n", encoding="utf-8")
        (self.proj / ".gitignore").write_text(".herdr-team/state/\n", encoding="utf-8")
        if commit:
            self.git("add", "--", ".herdr-team", ".gitignore")
            self.git("commit", "-q", "-m", "chore: setup", "--", ".herdr-team", ".gitignore")

    def setup_run(self) -> str:
        """코디네이터 터미널(COORD)에서 horch Run 을 만들고 run.json 을 bind 뒤 모양으로 쓴다."""
        self.add_terminal(COORD, argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbTeam"}, status="idle")
        self.add_terminal(MAIN, argv=["claude"], labels={"herdr.space": "spA", "herdr.tab": "tbMain"}, status="idle")
        code, out = self.horch("run-create", "--objective", "test", terminal=COORD)
        self.assertEqual(code, 0, out)
        run_id = out["run"]["id"]
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "run.json").write_text(json.dumps({
            "run_id": run_id, "pending_launch": {"nonce": NONCE, "at": "2026-01-01T00:00:00Z"},
            "bound_nonce": NONCE, "coordinator_terminal": COORD, "coordinator_argv": ["claude"],
            "team_space": "spA", "team_tab": "tbTeam", "launched_at": "2026-01-01T00:00:00Z"}))
        return run_id

    def write_spec(self, tid: str, role: str = "developer", title: str = "앱 만들기", *, owns: str | None = None,
                   depends: str | None = None, front: dict | None = None, body: str = VALID_BODY,
                   commit: bool = True) -> None:
        lines = ["---", f"id: {tid}", f"role: {role}", f"title: {title}"]
        if owns:
            lines.append(f"owns: {owns}")
        if depends:
            lines.append(f"depends_on: {depends}")
        for key, value in (front or {}).items():
            lines.append(f"{key}: {value}")
        lines += ["---", body]
        rel = f".herdr-team/tasks/{tid}.md"
        if commit:
            self.commit(rel, "\n".join(lines), f"spec: {tid}")
        else:
            path = self.proj / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines), encoding="utf-8")

    def task_state(self, tid: str) -> dict:
        return json.loads((self.state_dir / "tasks" / f"{tid}.json").read_text(encoding="utf-8"))

    # --- 실행 ---
    def _env(self, as_: str | None, terminal: str | None, extra: dict | None) -> dict:
        env = dict(self.env)
        if as_ == "coordinator":
            env.update({"HTEAM_ROLE": "coordinator", "HTEAM_LAUNCH": NONCE, "HC_TERMINAL_ID": COORD})
        elif as_ == "main":
            env["HC_TERMINAL_ID"] = MAIN
        if terminal:
            env["HC_TERMINAL_ID"] = terminal
        if extra:
            env.update(extra)
        return env

    def hteam(self, *args: str, as_: str | None = "coordinator", terminal: str | None = None,
              stdin: str | None = None, env: dict | None = None, timeout: float = 60,
              cwd: Path | None = None) -> tuple[int, dict]:
        proc = subprocess.run([sys.executable, str(BIN), *args], capture_output=True, text=True, input=stdin,
                              env=self._env(as_, terminal, env), timeout=timeout, cwd=str(cwd or self.proj))
        return proc.returncode, _parse(proc.stdout, proc.stderr)

    def hteam_bg(self, *args: str, as_: str | None = "coordinator", terminal: str | None = None,
                 stdin: str | None = None, env: dict | None = None) -> subprocess.Popen:
        proc = subprocess.Popen([sys.executable, str(BIN), *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, env=self._env(as_, terminal, env),
                                cwd=str(self.proj))
        if stdin is not None:
            proc.stdin.write(stdin)
        proc.stdin.close()
        proc.stdin = None  # finish() 의 communicate() 가 닫힌 stdin 을 flush 하지 않게(Python 3.11)
        self.addCleanup(self._reap, proc)
        return proc

    @staticmethod
    def _reap(proc: subprocess.Popen) -> None:
        """남은 백그라운드 hteam 을 끝내고 거둔다(좀비·열린 파이프를 남기지 않는다)."""
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=30)

    def wait_gone(self, rec, limit: float = 10.0) -> None:
        """시작 장벽 자식이 끝날 때까지 기다린다. 실행자가 시작 바이트 전에 죽으면 자식은 stdin 의 EOF 를 보고 스스로
        끝나지만 그 시점은 정해져 있지 않다. 살아 있는 동안의 복구는 launching(exit 3)이라 기다린 뒤에 복구한다."""
        import time
        from hteam import procs
        deadline = time.monotonic() + limit
        while procs.record_alive(rec):
            if time.monotonic() >= deadline:
                self.fail(f"{limit}초 안에 시작 장벽 자식(pid {rec.get('pid')})이 끝나지 않았다")
            time.sleep(0.05)

    @staticmethod
    def finish(proc: subprocess.Popen, timeout: float = 60) -> tuple[int, dict]:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, _parse(out, err)

    def horch(self, *args: str, terminal: str | None = COORD, timeout: float = 60) -> tuple[int, dict]:
        env = dict(self.env)
        if terminal:
            env["HC_TERMINAL_ID"] = terminal
        proc = subprocess.run([sys.executable, str(HORCH_BIN), "--home", str(self.horch_home), *args],
                              capture_output=True, text=True, env=env, timeout=timeout)
        return proc.returncode, _parse(proc.stdout, proc.stderr)

    def dispatch_row(self, did: str) -> dict:
        conn = sqlite3.connect(self.horch_home / "orch.db")
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT d.*, t.title FROM dispatches d JOIN tasks t ON t.id=d.task_id WHERE d.id=?",
                               (did,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row, did)
        return dict(row)

    def act(self, did: str, action: dict) -> tuple[int, dict]:
        """Dispatch did 의 워커 터미널에서 가짜 에이전트 동작을 한다(tests/fakes/agent-act)."""
        row = self.dispatch_row(did)
        preamble = self.horch_home / "runs" / row["run_id"] / "dispatches" / did / "preamble.md"
        env = dict(self.env)
        env["HC_TERMINAL_ID"] = row["terminal"]
        proc = subprocess.run([sys.executable, str(FAKES / "agent-act"), "--root", str(self.proj),
                               "--preamble", str(preamble)], input=json.dumps(action), capture_output=True,
                              text=True, env=env, timeout=60)
        return proc.returncode, _parse(proc.stdout, proc.stderr)

    # --- 태스크 흐름(Task 6 부터) ---
    def work_dispatch(self, tid: str) -> str:
        return self.task_state(tid)["rounds"][-1]["work"]["dispatch"]

    def act_work(self, tid: str, files: dict | None = None, *, outcome: str = "succeeded", commit: bool = True,
                 report: str | None = None) -> tuple[int, dict]:
        """현재 라운드 작업 워커가 owns 안에 커밋하고 보고서를 쓴 뒤 done 한다."""
        st = self.task_state(tid)
        rnd = st["round"]
        rel = f"docs/tasks/{tid}/report.md"
        action = {"write": files if files is not None else {"src/app.py": f"print('hello r{rnd}')\n"},
                  "report": report if report is not None else f"## r{rnd}\n- 바꾼 파일: src/app.py\n",
                  "report_path": rel,
                  "done": {"outcome": outcome, "summary": f"{tid} r{rnd} 끝", "report_path": rel}}
        if commit:
            action["commit"] = f"[{tid}] r{rnd} 작업"
        return self.act(self.work_dispatch(tid), action)

    def attempt(self, tid: str) -> dict:
        return self.task_state(tid)["rounds"][-1]["reviews"][-1]

    def act_review(self, tid: str, verdict: str | None = "APPROVE", *, outcome: str = "succeeded",
                   text: str = "## 지적 사항\n- 없음\n", write: bool = True, extra: dict | None = None) -> tuple[int, dict]:
        """현재 리뷰 시도의 리뷰어가 rN-aK.md 를 쓰고 done 한다."""
        att = self.attempt(tid)
        action = {"done": {"outcome": outcome, "summary": verdict or "판정 없음", "report_path": att["file"]}}
        if write:
            action["review"] = {"file": att["file"], "text": text, "verdict": verdict}
        action.update(extra or {})
        return self.act(att["dispatch"], action)


def _parse(stdout: str, stderr: str) -> dict:
    for line in reversed(stdout.strip().split("\n")):  # LF 로만 나눈다(본문의 U+2028 등은 경계가 아니다)
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return {"raw": stdout, "stderr": stderr}
