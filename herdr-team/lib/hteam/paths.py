"""버전, 플러그인 경로, 대상 프로젝트 경로(설계 3.4)와 프로젝트 찾기(8.3 `--root`)."""
from __future__ import annotations

import os
from pathlib import Path

from .errors import USAGE, HteamError

VERSION = "0.6.1"
PLUGIN_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = PLUGIN_ROOT / "templates"
# 관제·워커·메인이 부르는 hteam 명령. 프로젝트 루트 기준 shim 경로다(작업 폴더는 늘 프로젝트 루트).
SHIM = ".herdr-team/bin/hteam"


class Project:
    """대상 프로젝트의 파일 위치. 만들지는 않는다(ensure_state 만 state 폴더를 만든다).

    root 는 상태 루트(메인 프로젝트)이고 모든 경로가 그 기준이다. work_root 는 작업 루트(파일·git·시험)로 기본은 root,
    작업 공간 슬롯에서 찾았으면 그 슬롯이다(설계 5.10.2, project_at)."""

    def __init__(self, root: Path, work_root: Path | None = None):
        self.root = Path(root).resolve()
        self.work_root = Path(work_root).resolve() if work_root is not None else self.root
        self.team = self.root / ".herdr-team"
        self.config = self.team / "config.toml"
        self.project_md = self.team / "project.md"
        self.roles = self.team / "roles"
        self.tasks = self.team / "tasks"
        self.state = self.team / "state"
        self.horch_home = self.state / "horch"
        self.run_file = self.state / "run.json"
        self.run_lock = self.state / "run.lock"
        # 관제(설계 8장): pid·heartbeat·drive.log(Task 4), 요청 큐(7.1), 마무리·보강·테스트 확정 기록(8.4·8.9), 워커 사본(8.7)과
        # 자식 프로세스(8.8). 쓰기는 각 단계가 한다
        self.drive_dir = self.state / "drive"
        self.drive_pid = self.drive_dir / "drive.pid"
        self.heartbeat = self.drive_dir / "heartbeat"
        self.drive_log = self.drive_dir / "drive.log"
        self.queue_dir = self.drive_dir / "queue"
        self.queue_lock = self.drive_dir / "queue.lock"
        self.queue_seq = self.drive_dir / "queue.seq"
        self.finish_file = self.drive_dir / "finish.json"
        self.supplement_file = self.drive_dir / "supplement.json"
        self.test_confirm_file = self.drive_dir / "test-confirm.json"
        self.workers_file = self.drive_dir / "workers.json"
        self.jobs_dir = self.drive_dir / "jobs"
        # 고정 에이전트(설계 5.9.1): crew.json 과 그 잠금, 인수인계 사양(5.9.7). 관제와 그 자식만 쓴다
        self.crew_file = self.state / "crew.json"
        self.crew_lock = self.state / "crew.json.lock"
        self.crew_dir = self.state / "crew"
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
        # 질문 보기(설계 7.4a 8단계): 긴 render.context 전문 <out-id>.md, 보기 명령 출력 .log, 보기 기록 .view.json, 잠금 .lock
        self.questions = self.state / "questions"
        self.design_review = self.state / "design-review.json"
        self.text_rules = self.team / "text-rules.md"
        self.auto_up = self.state / "auto-up.json"
        self.auto_up_pid = self.state / "auto-up.pid"
        self.auto_up_log = self.state / "auto-up.log"
        self.tests = self.state / "tests"  # 테스트 기록 T-xxx.json·final.json, exclusive 잠금 .lock(설계 5.7)
        self.test_logs = self.tests / "logs"
        # 작업 공간(설계 5.10.2): 슬롯 상태, 슬롯 폴더(slot-<N>, git worktree)와 슬롯 잠금(slot-<N>.lock), setup·teardown
        # 로그, 병합의 git 잠금(5.10.6)
        self.slots_file = self.state / "slots.json"
        self.slots_dir = self.state / "slots"
        self.slot_logs = self.slots_dir / "logs"
        self.git_lock = self.state / "git.lock"
        # Redmine 연동(설계 8.12): 관제가 쓰는 사건 큐와 그 순번·잠금, 보내지 못한 항목, 전송자 하나의 잠금, 마지막 전송 결과.
        # 만드는 것은 redmine.enqueue·sync 다([redmine] 이 없으면 만들지 않는다)
        self.redmine_dir = self.state / "redmine"
        self.redmine_queue = self.redmine_dir / "queue"
        self.redmine_failed = self.redmine_dir / "failed"
        self.redmine_lock = self.redmine_dir / "queue.lock"
        self.redmine_sync_lock = self.redmine_dir / "sync.lock"
        self.redmine_seq = self.redmine_dir / "seq"
        self.redmine_status = self.redmine_dir / "status.json"

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

    def state_ref(self, rel: str) -> str:
        """세션(워커·리뷰어)에게 주는 상태 루트(메인) 파일 rel(프로젝트 기준 상대 경로)의 경로. 두 루트가 같으면 rel 그대로,
        다르면(슬롯) 작업 루트에서 메인 루트로 가는 상대 경로 뒤에 rel(`../../../../.herdr-team/state/…` 꼴)이다. 슬롯 세션의
        cwd 는 작업 루트이고(설계 5.10.4), 상태 루트가 기준이다(5.10.2: 슬롯의 커밋된 팀 파일은 옛 사본일 수 있다). 프롬프트와
        커밋되는 파일에 절대 경로를 넣지 않는다(Codex 커밋 리뷰 b916c8c P2, 리뷰 반영 2차 G1·G2)."""
        if self.work_root == self.root:
            return rel
        return (Path(os.path.relpath(self.root, self.work_root)) / rel).as_posix()


def report_rel(tid: str) -> str:
    return f"docs/tasks/{tid}/report.md"


def review_rel(tid: str, rnd: int, attempt: int | None = None) -> str:
    name = f"r{rnd}.md" if attempt is None else f"r{rnd}-a{attempt}.md"
    return f"docs/reviews/{tid}/{name}"


def handoff_rel(name: str) -> str:
    """고정 에이전트의 인수인계 파일(설계 5.5 의 7, 5.9.7)."""
    return f"docs/handoff/{name}.md"


def project_at(folder) -> Project:
    """`.herdr-team/config.toml` 이 있는 folder 의 프로젝트. folder 의 슬롯 표시 파일이 맞으면 상태 루트는 메인
    (main_root), 작업 루트는 folder 다(설계 5.10.2). 아니면 folder 하나다."""
    from .workspace import marker  # workspace 가 가져오는 모듈들이 이 모듈을 가져오므로 여기서 가져온다
    found = marker(folder)
    return Project(found["main_root"], work_root=folder) if found else Project(folder)


def find_project(arg: str | None) -> Project:
    """--root 가 있으면 그 폴더, 없으면 현재 폴더에서 위로 `.herdr-team/config.toml` 을 찾는다. 찾은 폴더가 작업 공간
    슬롯이면 상태 루트는 메인이다(project_at)."""
    if arg:
        root = Path(arg).expanduser().resolve()
        if (root / ".herdr-team" / "config.toml").is_file():
            return project_at(root)
        raise HteamError("no_project", f"{root} 에 .herdr-team/config.toml 이 없다", USAGE,
                         "/herdr-team:init 으로 세팅하거나 --root 를 고친다")
    start = Path.cwd().resolve()
    for folder in (start, *start.parents):
        if (folder / ".herdr-team" / "config.toml").is_file():
            return project_at(folder)
    raise HteamError("no_project", "herdr-team 프로젝트가 아니다(위로 .herdr-team/config.toml 이 없다)", USAGE,
                     "프로젝트 안에서 실행하거나 --root 를 준다")
