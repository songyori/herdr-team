"""버전, 플러그인 경로, 대상 프로젝트 경로(설계 3.4)와 프로젝트 찾기(8.3 `--root`)."""
from __future__ import annotations

from pathlib import Path

from .errors import USAGE, HteamError

VERSION = "0.2.0"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = PLUGIN_ROOT / "templates"
# 코디네이터·워커가 부르는 hteam 명령. 프로젝트 루트 기준 shim 경로다(작업 폴더는 늘 프로젝트 루트).
SHIM = ".herdr-team/bin/hteam"


class Project:
    """대상 프로젝트의 파일 위치. 만들지는 않는다(ensure_state 만 state 폴더를 만든다)."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.team = self.root / ".herdr-team"
        self.config = self.team / "config.toml"
        self.project_md = self.team / "project.md"
        self.coordinator_md = self.team / "coordinator.md"
        self.roles = self.team / "roles"
        self.tasks = self.team / "tasks"
        self.state = self.team / "state"
        self.horch_home = self.state / "horch"
        self.run_file = self.state / "run.json"
        self.task_states = self.state / "tasks"
        self.plan_file = self.state / "plan.json"
        self.outbox = self.state / "outbox.jsonl"
        self.cursor = self.state / "outbox.cursor"
        self.answers = self.state / "answers"
        self.applied = self.state / "applied.json"
        self.ask_acks = self.state / "ask-acks.json"
        self.sessions = self.state / "sessions"
        self.setup_mode = self.state / "setup-mode"
        self.plugin_root_file = self.state / "plugin-root"
        self.hook_errors = self.state / "hook-errors.log"
        self.lock = self.state / "lock"
        self.watch_pid = self.state / "watch.pid"
        self.attention = self.state / "attention.json"
        self.context_denied = self.state / "context-denied.json"
        self.design_review = self.state / "design-review.json"
        self.text_rules = self.team / "text-rules.md"
        self.auto_up = self.state / "auto-up.json"
        self.auto_up_pid = self.state / "auto-up.pid"
        self.auto_up_log = self.state / "auto-up.log"

    def ensure_state(self) -> None:
        for folder in (self.state, self.task_states, self.answers, self.sessions):
            folder.mkdir(parents=True, exist_ok=True)

    def spec_path(self, tid: str) -> Path:
        return self.tasks / f"{tid}.md"

    def state_path(self, tid: str) -> Path:
        return self.task_states / f"{tid}.json"

    def task_dir(self, tid: str) -> Path:
        """라운드별로 조립한 워커 사양과 리뷰 프롬프트를 두는 곳."""
        return self.task_states / tid

    def work_file(self, tid: str, n: int) -> Path:
        """라운드 n 의 조립한 작업 사양(start·fix 가 쓰고 리뷰 프롬프트가 가리킨다)."""
        return self.task_dir(tid) / f"r{n}-work.md"

    def role_doc(self, role: str) -> Path:
        return self.roles / f"{role}.md"


def report_rel(tid: str) -> str:
    return f"docs/tasks/{tid}/report.md"


def review_rel(tid: str, rnd: int, attempt: int | None = None) -> str:
    name = f"r{rnd}.md" if attempt is None else f"r{rnd}-a{attempt}.md"
    return f"docs/reviews/{tid}/{name}"


def find_project(arg: str | None) -> Project:
    """--root 가 있으면 그 폴더, 없으면 현재 폴더에서 위로 `.herdr-team/config.toml` 을 찾는다."""
    if arg:
        root = Path(arg).expanduser().resolve()
        if (root / ".herdr-team" / "config.toml").is_file():
            return Project(root)
        raise HteamError("no_project", f"{root} 에 .herdr-team/config.toml 이 없다", USAGE,
                         "/herdr-team:init 으로 세팅하거나 --root 를 고친다")
    start = Path.cwd().resolve()
    for folder in (start, *start.parents):
        if (folder / ".herdr-team" / "config.toml").is_file():
            return Project(folder)
    raise HteamError("no_project", "herdr-team 프로젝트가 아니다(위로 .herdr-team/config.toml 이 없다)", USAGE,
                     "프로젝트 안에서 실행하거나 --root 를 준다")
