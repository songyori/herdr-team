"""테스트 관문(설계 5.7): `[test]` 형식·HEAD 읽기·식별값, 사용자 확정 기록, 대상 계산, 실행(프로세스 그룹·시간 초과·
중단·tail·exclusive 잠금), 기록, `hteam test`. 리뷰 관문(6.1 4a)도 이 모듈을 쓴다(gate_results).

git 은 gitio 로만 부른다. 테스트 명령은 이 모듈이 `/bin/sh -c` 로 직접 돌린다(horch·hc 를 거치지 않는다, 설계 3.3).
`hteam test` 는 역할을 확인하지 않고 config.toml 을 읽지 않는다(워커·관제·메인 누구나 부른다, 설계 8.3).

작업 루트(설계 5.7 7단계·5.10.4): 태스크의 작업 커밋·대상 파일·커밋 안 된 변경·테스트 명령의 cwd 는 그 태스크의 작업 루트
(p.work_root)다. 태스크로 들어가는 함수가 태스크 상태로 p 를 다시 묶는다(workspace.view). `[test]` 설정·확정 기록·테스트
기록·로그는 상태 루트(p.root, 메인)의 것이다. 작업 공간 태스크의 테스트는 슬롯 env 와 HTEAM_SLOT 을 받는다.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shlex
import signal
import subprocess
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import gitio, state
from .errors import FAIL, TIMEOUT, USAGE, HteamError
from .globs import matches_any, owns_problem
from .paths import SHIM, find_project
from .util import dumps, now, read_json, read_json_strict, show, write_json

PLAN_FILE = "docs/planning/tasks.toml"  # plan.PLAN_FILE 과 같다(plan 이 이 모듈을 쓰므로 따로 둔다)
KEYS = ("quick", "full", "timeout_min", "ok_exit", "exclusive", "tester_paths", "full_if")
DEFAULT_TIMEOUT_MIN = 30
DEVELOPER_ROLE, TESTER_ROLE = "developer", "tester"  # 묶음 규칙·관문의 직무 이름은 설정과 관계없이 글자 그대로다
GATED_ROLES = (DEVELOPER_ROLE, TESTER_ROLE)
PASSED = ("passed", "flaky", "skipped")
TAIL_LINES, TAIL_WIDTH, TAIL_BYTES = 60, 300, 65536
KILL_GRACE_S = 5.0
LOCK_POLL_S = 0.2
DIRTY_SHOWN = 20
DROP_ENV = ("HTEAM_ROLE", "HTEAM_LAUNCH", "HC_TERMINAL_ID")  # 테스트 명령이 관제·워커 터미널로 보이지 않게(14장)
STATUS_TEXT = {"passed": "통과", "flaky": "통과(불안정 의심: 첫 실행은 실패했고 다시 실행해 통과했다)",
               "skipped": "돌리지 않음(관련 파일 없음)", "failed": "실패", "timeout": "시간 초과"}
CONFIRM_LINE = ("이 명령은 리뷰 전에 관제 환경에서 자동으로 돈다(Codex 샌드박스 밖, 사용자 권한). "
                "워커도 자기 환경에서 돌린다.")
CONFIRM_HINT = (f"커밋된 `[test]` 를 사용자가 확정하지 않았다. 관제가 확정 질문을 올린다. 확정 기록이 빠졌으면 "
                f"`{SHIM} test-confirm`")
NO_CONFIG = (f"커밋된 HEAD 의 {PLAN_FILE} 에 [test] 가 없다(작업 트리에만 있으면 커밋한다). 테스트 관문이 꺼져 있다")


@dataclass(frozen=True)
class GateConfig:
    quick: str
    full: str
    timeout_min: int
    ok_exit: tuple[int, ...]
    exclusive: bool
    # 7단계 키(설계 5.2·5.7). 돌릴 명령을 바꾸지 않으므로 식별값(normalized·digest)에 넣지 않는다
    tester_paths: tuple[str, ...] | None = None
    full_if: tuple[str, ...] = ()


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _quoted_files(command: str) -> bool:
    """`{files}` 가 셸 따옴표 안에 있는가(또는 앞에 가려지지 않은 역슬래시가 있는가). 보안은 위치 인자가 맡고(파일은
    `"$@"` 로 넘어가 셸 문법으로 다시 읽히지 않는다) 이 검사는 잘못 쓴 설정을 알린다: 따옴표 안의 `"$@"` 는 파일이 따로
    넘어가지 않는다. `$(...)`·백틱 안은 새 인용 문맥이라 맨 위 문맥만 본다. 따옴표 밖 단어 시작의 `#` 는 줄 끝까지 주석이다."""
    stack = [["top", ""]]  # [종류(top·$(·`), 따옴표(""·'·")]
    i = 0
    while i < len(command):
        ctx = stack[-1]
        kind, quote = ctx
        ch = command[i]
        if command.startswith("{files}", i) and quote:
            return True
        if quote == "'":
            if ch == "'":
                ctx[1] = ""
        elif ch == "\\":
            if command.startswith("{files}", i + 1):
                return True
            escapable = quote == "" or command[i + 1:i + 2] in ("$", "`", '"', "\\", "\n")
            i += 2 if escapable else 1
            continue
        elif ch == "$" and command.startswith("$(", i):
            stack.append(["$(", ""])
            i += 2
            continue
        elif ch == "`":
            if kind == "`" and not quote:
                stack.pop()
            else:
                stack.append(["`", ""])
        elif ch == ")" and kind == "$(" and not quote:
            stack.pop()
        elif ch == '"':
            ctx[1] = "" if quote else '"'
        elif ch == "'" and not quote:
            ctx[1] = "'"
        elif ch == "#" and not quote and (i == 0 or command[i - 1] in " \t\n;&|()"):
            end = command.find("\n", i)
            i = len(command) if end < 0 else end
            continue
        i += 1
    return False


def config_problems(raw) -> list[str]:
    """`[test]` 형식 검사(설계 5.7). 해당하는 문제를 모두 모은다. 문구는 orca-team 원문 그대로다."""
    if not isinstance(raw, dict):
        return ["[test] 는 표여야 한다"]
    found = []
    unknown = sorted(set(raw) - set(KEYS))
    if unknown:
        found.append(f"[test]: 모르는 키 {', '.join(unknown)}")
    for name in ("quick", "full"):
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            found.append(f"[test]: {name} 는 비지 않은 명령 문자열이어야 한다")
    quick, full = raw.get("quick"), raw.get("full")
    if isinstance(quick, str) and quick.strip() and quick.count("{files}") != 1:
        found.append("[test]: quick 은 {files} 를 정확히 한 번 담는다")
    if isinstance(quick, str) and _quoted_files(quick):
        found.append("[test]: quick 의 {files} 는 따옴표 밖에 둔다(hteam 이 파일을 따로 인자로 넘긴다)")
    if isinstance(full, str) and "{files}" in full:
        found.append("[test]: full 은 {files} 를 담지 않는다")
    timeout = raw.get("timeout_min", DEFAULT_TIMEOUT_MIN)
    if not _int(timeout) or not 1 <= timeout <= 240:
        found.append("[test]: timeout_min 은 1–240 정수")
    ok = raw.get("ok_exit", [0])
    if not isinstance(ok, list) or not ok or not all(_int(x) for x in ok):
        found.append("[test]: ok_exit 는 정수 목록")
    if not isinstance(raw.get("exclusive", False), bool):
        found.append("[test]: exclusive 는 true 또는 false")
    if "tester_paths" in raw:  # 7단계. 항목의 {key} 를 채운 경로가 owns 값 규칙(4.1)을 지켜야 한다
        paths = raw["tester_paths"]
        if not (isinstance(paths, list) and paths and all(isinstance(x, str) and x.count("{key}") == 1 for x in paths)):
            found.append("[test]: tester_paths 는 {key} 를 한 번씩 담은 경로 목록이다")
        else:
            found += [f"[test]: tester_paths {x!r}: {why}" for x in paths
                      if (why := owns_problem(x.replace("{key}", "key")))]
    if "full_if" in raw:  # 7단계. owns 문법의 glob 목록(빈 목록은 된다)
        patterns = raw["full_if"]
        if not (isinstance(patterns, list) and all(isinstance(x, str) and x.strip() for x in patterns)):
            found.append("[test]: full_if 는 glob 목록이다")
        else:
            found += [f"[test]: full_if {x!r}: {why}" for x in patterns if (why := owns_problem(x))]
    return found


def parse_config(raw) -> GateConfig:
    problems = config_problems(raw)
    if problems:
        raise HteamError("bad_test_config", f"{PLAN_FILE} [test] 검증 실패: " + "; ".join(problems), USAGE,
                         f"기획 태스크로 {PLAN_FILE} 의 [test] 를 고친다(사용자가 직접 넣었으면 사용자가 고친다)")
    paths = raw.get("tester_paths")
    return GateConfig(raw["quick"].strip(), raw["full"].strip(), raw.get("timeout_min", DEFAULT_TIMEOUT_MIN),
                      tuple(raw.get("ok_exit", [0])), raw.get("exclusive", False),
                      tuple(paths) if paths is not None else None, tuple(raw.get("full_if", [])))


def normalized(cfg: GateConfig) -> dict:
    return {"quick": cfg.quick, "full": cfg.full, "timeout_min": cfg.timeout_min, "ok_exit": list(cfg.ok_exit),
            "exclusive": cfg.exclusive}


def digest(cfg: GateConfig) -> str:
    """확정 식별값(설계 5.7): 기본값까지 채운 정규화 값의 SHA-256. 공백·기본값 생략에 같고 명령·값이 바뀌면 다르다."""
    data = json.dumps(normalized(cfg), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _unreadable(why) -> HteamError:
    return HteamError("plan_unreadable", f"{PLAN_FILE} 읽기 실패: {why}", USAGE,
                      f"기획 태스크로 {PLAN_FILE} 를 고친다(사용자가 직접 넣었으면 사용자가 고친다)")


def load_config(p) -> GateConfig | None:
    """커밋된 HEAD 의 `[test]`(설계 5.7). 파일이 HEAD 에 없거나 커밋이 없으면, 또는 표 test 가 없으면 None(관문이
    꺼진다). 작업 트리는 읽지 않는다: 증분 기획 워커가 고치는 중인 tasks.toml 이 관문을 바꾸지 않게 한다."""
    try:
        text = gitio.head_file(p.root, gitio.to_top(gitio.top_prefix(p.root), PLAN_FILE))
        data = tomllib.loads(text) if text is not None else None
    except HteamError as exc:
        raise _unreadable(exc.message) from None
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise _unreadable(exc) from None
    if data is None or "test" not in data:
        return None
    return parse_config(data["test"])


def require_config(p) -> GateConfig:
    cfg = load_config(p)
    if cfg is None:
        raise HteamError("no_test_config", NO_CONFIG, USAGE)
    return cfg


def worktree_config(p) -> GateConfig:
    """작업 트리의 tasks.toml `[test]`(기획자의 확정 질문은 커밋 전이다, 설계 5.7)."""
    try:
        data = tomllib.loads((p.root / PLAN_FILE).read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise _unreadable(exc) from None
    if "test" not in data:
        raise HteamError("no_test_config", f"{PLAN_FILE} 에 [test] 가 없다(작업 트리)", USAGE,
                         "[test] 를 쓴 계획일 때만 --test-confirm 으로 묻는다")
    return parse_config(data["test"])


# --- 사용자 확정 기록(설계 5.7, 프로젝트 밖) ---

def approvals_path(p) -> Path:
    """`${XDG_STATE_HOME:-~/.local/state}/herdr-team/projects/<루트 실제 경로의 SHA-1 앞 16자>/test-approvals.json`.
    Codex 워커의 기본 샌드박스(작업 폴더만 쓸 수 있다)가 실수로 바꾸지 못하는 곳이다. 프로젝트를 옮기면 다시 확정한다."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(str(Path.home()), ".local", "state")
    key = hashlib.sha1(os.fsencode(os.path.realpath(p.root))).hexdigest()[:16]
    return Path(base) / "herdr-team" / "projects" / key / "test-approvals.json"


def _bad_approvals(path: Path, why: str) -> HteamError:
    return HteamError("bad_test_approvals", f"테스트 명령 확정 기록을 읽지 못했다({path}): {why}", FAIL,
                      "그 파일을 직접 고치거나 치운 뒤 다시 한다(덮어쓰지 않았다). 치우면 [test] 를 다시 확정한다")


def read_approvals(p) -> list[dict]:
    """엄격 읽기: 없으면 빈 목록, 있는데 읽지 못하거나 형식이 틀리면 bad_test_approvals(exit 1, 파일은 그대로)."""
    path = approvals_path(p)
    try:
        data = read_json_strict(path, {"approved": []})
    except HteamError as exc:
        raise _bad_approvals(path, exc.message) from None
    items = data.get("approved") if isinstance(data, dict) else None
    if not isinstance(items, list) or not all(isinstance(a, dict) and isinstance(a.get("digest"), str) for a in items):
        raise _bad_approvals(path, "형식이 틀렸다({\"approved\": [{digest, …}]} 가 아니다)")
    return items


def is_approved(p, value: str) -> bool:
    return any(a["digest"] == value for a in read_approvals(p))


def approve(p, value: str, out_id: str, quick: str, full: str) -> None:
    """확정 기록에 식별값을 더한다(이미 있으면 그대로). 읽기 → 더하기 → 임시 파일 + os.replace. 잠그지 않는다(한계)."""
    items = read_approvals(p)
    if any(a["digest"] == value for a in items):
        return
    write_json(approvals_path(p), {"approved": [*items, {"digest": value, "out_id": out_id, "at": now(),
                                                         "quick": quick, "full": full}]})


def gate_state(p) -> dict:
    """`hteam status` 의 test_gate(설계 5.7): none(HEAD 에 [test] 없음)·approved·unapproved·error(형식·읽기·확정 기록)."""
    try:
        cfg = load_config(p)
        value = digest(cfg) if cfg is not None else None
        ok = value is not None and is_approved(p, value)
    except HteamError as exc:
        return {"state": "error", "digest": None, "error": exc.message}
    if cfg is None:
        return {"state": "none", "digest": None, "error": None}
    if ok:
        return {"state": "approved", "digest": value, "error": None}
    return {"state": "unapproved", "digest": value, "error": None, "hint": CONFIRM_HINT}


def approved_config(p) -> GateConfig:
    """`hteam test` 의 설정: HEAD 의 [test] 가 있고 사용자가 확정한 것. 아니면 no_test_config·test_unapproved(exit 2)."""
    cfg = require_config(p)
    if not is_approved(p, digest(cfg)):
        raise HteamError("test_unapproved", "커밋된 [test] 를 사용자가 확정하지 않았다. 관제가 메인에 확정 질문을 올린다"
                         "(hteam status 의 test_gate)", USAGE)
    return cfg


def fence(text: str) -> str:
    """text 를 감쌀 펜스: 안의 가장 긴 백틱 연속보다 하나 길게(최소 3개). 출력이 펜스를 닫지 못하게 한다."""
    longest, run = 0, 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(3, longest + 1)


def fenced(text: str, lang: str = "") -> str:
    tick = fence(text)
    return f"{tick}{lang}\n{text}\n{tick}"


def confirm_section(cfg: GateConfig) -> str:
    """확정 질문 context 끝의 `## 테스트 명령` 절(설계 5.7): 경고 한 줄과 정규화한 다섯 값의 TOML 블록. 7단계 키
    tester_paths·full_if 는 있으면 뒤에 함께 보인다(식별값에는 들지 않는다)."""
    values = normalized(cfg)
    lines = [f"quick = {json.dumps(values['quick'], ensure_ascii=False)}",
             f"full = {json.dumps(values['full'], ensure_ascii=False)}",
             f"timeout_min = {values['timeout_min']}",
             f"ok_exit = {json.dumps(values['ok_exit'])}",
             f"exclusive = {'true' if values['exclusive'] else 'false'}"]
    if cfg.tester_paths is not None:
        lines.append(f"tester_paths = {json.dumps(list(cfg.tester_paths), ensure_ascii=False)}")
    if cfg.full_if:
        lines.append(f"full_if = {json.dumps(list(cfg.full_if), ensure_ascii=False)}")
    body = "\n".join(lines)
    return f"## 테스트 명령\n{CONFIRM_LINE}\n{fenced(body, 'toml')}"


# --- 대상 계산(설계 5.7) ---

def _report(path: str, tid: str) -> bool:
    """테스트 대상이 아닌 보고서 경로: 태스크 보고서 폴더와 QA 보고서."""
    return path.startswith(f"docs/tasks/{tid}/") or path.startswith("docs/qa/")


def work_commits(p, st: dict) -> list[dict]:
    """작업 커밋 = 리뷰 대상 커밋(설계 6.1 3)."""
    from . import review  # review 가 이 모듈을 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    return review.target_commits(p, st)


def changed_files(p, commits: list[dict]) -> list[str]:
    from . import review
    return review.changed_files(p, commits)


def task_target(p, tid: str) -> tuple[dict, list[dict]]:
    """(상태, 작업 커밋). 작업 커밋은 그 태스크의 작업 루트에서 센다: 슬롯 안에서 부른 `hteam test T` 도 위치는 찾은 폴더가
    아니라 태스크 상태의 workspace.root 다(설계 5.10.4)."""
    from . import workspace  # workspace 가 이 모듈을 쓴다
    state.check_id(tid)
    st = state.load(p, tid)
    if st is None or not st.get("base"):
        raise HteamError("not_started", f"{tid} 는 아직 시작하지 않은 태스크다(hteam start)", USAGE)
    return st, work_commits(workspace.view(p, st), st)


def code_head(p, tid: str, commits: list[dict]) -> str | None:
    """작업 커밋을 뒤에서부터 보며 보고서 경로 밖 파일(프로젝트 밖 `../` 포함)을 하나라도 바꾼 첫 커밋. 재사용 기준이다."""
    prefix = gitio.top_prefix(p.work_root)
    for c in reversed(commits):
        if any(not _report(gitio.from_top(prefix, f), tid) for f in gitio.commit_files(p.work_root, c["sha"])):
            return c["sha"]
    return None


def quick_files(p, tid: str, commits: list[dict]) -> list[str]:
    """작업 커밋이 바꾼 파일 가운데 보고서 경로 밖이고 프로젝트 안이며 지금 작업 트리에 파일로 있는 것, 정렬."""
    return sorted(f for f in changed_files(p, commits)
                  if not _report(f, tid) and not f.startswith("../") and (p.work_root / f).is_file())


def check_committed(p, st: dict, commits: list[dict]) -> None:
    """quick 사전 거부(실행 전): 작업 커밋 없음, 소유 경로의 커밋 안 된 변경(추적하지 않는 새 파일 포함)."""
    tid = st["id"]
    if not commits:
        raise HteamError("no_work_commit", f"아직 `[{tid}]` 작업 커밋이 없다. 작업을 먼저 커밋한 뒤 hteam test 를 "
                         "돌린다(quick 은 커밋된 변경만 본다)", USAGE)
    owns = list(st.get("owns") or [])
    prefix = gitio.top_prefix(p.work_root)
    found = [gitio.from_top(prefix, x) for x in gitio.dirty(p.work_root, [gitio.glob_spec(o) for o in owns])]
    bad = sorted(x for x in found if not _report(x, tid) and matches_any(x, owns))
    if bad:
        raise HteamError("uncommitted_owned", f"{tid}: 소유 경로에 커밋하지 않은 변경이 있다: "
                         f"{', '.join(show(x) for x in bad)}. quick 은 커밋된 변경만 본다. 워커는 커밋하거나 지운 뒤 "
                         "hteam test 를 다시 돌린다. 리뷰에서 나왔으면 "
                         f"`hteam fix {tid} --note \"커밋 안 된 파일을 커밋하거나 지운다\"` 로 되돌려 보낸다", USAGE)


def dirty_files(p, allowed: list[str]) -> list[str]:
    """실행 직후 추적 파일의 커밋 안 된 변경(추적하지 않는 파일 제외) 가운데 allowed 밖, 정렬."""
    prefix = gitio.top_prefix(p.work_root)
    found = (gitio.from_top(prefix, x) for x in gitio.modified_tracked(p.work_root))
    return sorted(x for x in found if x.startswith("../") or not matches_any(x, allowed))


# --- 실행(설계 5.7) ---

def child_env(cfg=None, extra: dict[str, str] | None = None) -> dict[str, str]:
    """테스트 명령과 작업 공간 setup·teardown 의 환경(설계 5.7·5.10.3 의 4): 지금 환경에서 DROP_ENV 를 빼고 extra 를
    더한다. cfg 는 config.Config·config.TestSettings 또는 None 이다. 아직 쓰지 않는다(설계 5.7 의 [redmine] key_env 빼기가
    쓴다)."""
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    env.update(extra or {})
    return env


def log_path(p, name: str) -> Path:
    return p.test_logs / f"{name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"


def _gone(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except (ProcessLookupError, PermissionError):  # macOS 는 좀비만 남은 그룹에 EPERM 을 낸다
        return True
    return False


def kill_group(proc: subprocess.Popen) -> None:
    """그룹에 SIGTERM → 5초 동안 0.05초마다 sh 를 거두며 그룹이 남았는지 본다 → 남았든 아니든 SIGKILL → sh 를 거둔다.
    sh 가 먼저 끝나도 SIGTERM 을 무시한 그룹 프로세스(브라우저·e2e 도우미)가 남지 않는다."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)
    deadline = time.monotonic() + KILL_GRACE_S
    while time.monotonic() < deadline:
        proc.poll()
        if _gone(proc.pid):
            break
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait()


def read_tail(log: Path) -> str:
    """로그 끝 64 KiB 를 UTF-8(바꿈 문자)로 풀고 공백뿐인 줄을 빼고 줄마다 300자로 잘라 마지막 60줄. 읽지 못하면 ""."""
    try:
        with open(log, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            data = fh.read()
    except OSError:
        return ""
    lines = [line[:TAIL_WIDTH] for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
    return "\n".join(lines[-TAIL_LINES:])


def execute(p, command: str, log: Path, timeout_s: float, ok_exit, args=(), shown: str | None = None, *, cwd=None,
            env: dict[str, str] | None = None) -> dict:
    """`/bin/sh -c <명령> sh <args…>`(args 는 위치 인자 $1…), 로그 첫 줄은 shown(없으면 명령). cwd 는 주지 않으면 작업 루트(p.work_root), stdin /dev/null, 출력은 로그 하나, 새 세션(자기 프로세스 그룹).
    환경은 child_env(None, env)(env 는 작업 공간 슬롯 env 등).
    hteam 이 중단되면(SIGINT·SIGTERM) 그룹을 끝내고 다시 올린다(기록 없이 끝난다)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(f"$ {show(shown or command)}\n")  # 첫 줄 하나. 여러 줄 명령의 줄바꿈은 \n 으로 보인다
        fh.flush()
        try:
            proc = subprocess.Popen(["/bin/sh", "-c", command, "sh", *args], cwd=str(cwd or p.work_root), stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT, start_new_session=True, env=child_env(None, env))
        except OSError as exc:
            raise HteamError("test_unrunnable", f"[test] 명령을 실행하지 못했다: {exc}", USAGE) from None
        try:
            code = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            kill_group(proc)
            code = None
        except BaseException:  # 중단: 테스트 프로세스를 남기지 않는다
            kill_group(proc)
            raise
    if code is None:
        status = "timeout"
    elif code in (126, 127):  # ok_exit 보다 먼저 본다
        status = "unrunnable"
    else:
        status = "passed" if code in ok_exit else "failed"
    return {"status": status, "exit": code, "seconds": round(time.monotonic() - start, 1), "tail": read_tail(log)}


@contextlib.contextmanager
def run_lock(p, cfg: GateConfig, wait_s: float) -> Iterator[None]:
    """exclusive 면 명령 한 번 동안 `state/tests/.lock` 의 flock. 비차단으로 0.2초마다 시도한다(다른 잠금과 교착하지 않는다)."""
    if not cfg.exclusive:
        yield
        return
    p.tests.mkdir(parents=True, exist_ok=True)
    with open(p.tests / ".lock", "a") as fh:
        deadline = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise HteamError("test_lock_timeout", f"테스트 잠금(exclusive)을 {wait_s:g}초 안에 얻지 못했다. "
                                     "다른 테스트 실행이 끝난 뒤 다시 한다", TIMEOUT) from None
                time.sleep(LOCK_POLL_S)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def attempt(p, cfg: GateConfig, command: str, name: str, timeout_s: float | None = None,
            lock_wait: float | None = None, args=(), shown: str | None = None, *, cwd=None,
            env: dict[str, str] | None = None) -> dict:
    limit = cfg.timeout_min * 60
    with run_lock(p, cfg, limit if lock_wait is None else lock_wait):
        log = log_path(p, name)
        result = execute(p, command, log, limit if timeout_s is None else timeout_s, cfg.ok_exit, args, shown, cwd=cwd,
                         env=env)
    return {"command": shown or command, "log": log.relative_to(p.root).as_posix(), **result}


def run_quick(p, cfg: GateConfig, files: list[str], name: str, *, cwd=None, env: dict[str, str] | None = None) -> dict:
    """관련 파일이 없으면 돌리지 않고 skipped(통과로 본다). 1차가 failed 면 바로 2차, 2차가 통과면 flaky."""
    if not files:
        return {"status": "skipped", "exit": None, "seconds": 0.0, "command": None, "log": None, "tail": "",
                "files": []}
    # 파일은 위치 인자로 넘긴다: 이름이 셸 문법으로 다시 읽히지 않는다. 기록·로그에 보이는 명령만 shlex.quote 한 문자열이다
    script = cfg.quick.replace("{files}", '"$@"')
    shown = cfg.quick.replace("{files}", " ".join(shlex.quote(f) for f in files))
    first = attempt(p, cfg, script, f"{name}-quick-a1", args=files, shown=shown, cwd=cwd, env=env)
    if first["status"] != "failed":  # 시간 초과는 다시 돌리지 않는다
        return {**first, "files": files}
    second = attempt(p, cfg, script, f"{name}-quick-a2", args=files, shown=shown, cwd=cwd, env=env)
    if second["status"] == "passed":
        return {**second, "status": "flaky", "first": {"exit": first["exit"], "log": first["log"]}, "files": files}
    return {**second, "files": files}


def _unrunnable(result: dict) -> HteamError:
    return HteamError("test_unrunnable", f"[test] 명령을 실행할 수 없다(exit {result['exit']}, 명령: "
                      f"{json.dumps(result['command'], ensure_ascii=False)}). 기획 태스크로 {PLAN_FILE} 의 [test] 를 "
                      f"고치거나 사용자가 직접 고친다. 출력 끝: {result['tail'][-300:]}", USAGE)


def _local_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def records(p, tid: str) -> dict:
    """`state/tests/T-xxx.json`(quick·full 의 마지막 기록). 잃어도 다시 돌릴 뿐이라 느슨하게 읽는다."""
    data = read_json(p.tests / f"{tid}.json", {})
    return data if isinstance(data, dict) else {}


def _save(path: Path, kind: str, entry: dict) -> None:
    data = read_json(path, {})
    data = data if isinstance(data, dict) else {}
    data[kind] = entry
    write_json(path, data)  # 임시 파일 + os.replace. 파일 잠금은 없다(한계)


def record_task(p, cfg: GateConfig, st: dict, commits: list[dict], kind: str) -> dict:
    """태스크 하나의 quick·full 을 돌려 종류별 마지막 기록으로 남긴다. 실행 불가(126·127)는 기록하지 않는다. 테스트는 그
    태스크의 작업 루트에서 그 태스크의 시험 env(workspace.task_env: 작업 공간 태스크는 슬롯 값, worktree 모드의 메인 폴더
    태스크는 슬롯 0 값, shared 는 없음)로 돈다(설계 5.7 7단계). 설정은 검사 없이 읽는다(config.test_settings, 설계 4.2)."""
    from . import config, workspace  # workspace 가 이 모듈을 쓴다. 불러오는 순서가 꼬이지 않게 여기서 가져온다
    p = workspace.view(p, st)
    env = workspace.task_env(p, config.test_settings(p), st)
    tid, rnd = st["id"], st.get("round") or 1
    name = f"{tid}-r{rnd}"
    if kind == "quick":
        check_committed(p, st, commits)
        result = run_quick(p, cfg, quick_files(p, tid, commits), name, env=env)
    else:
        result = attempt(p, cfg, cfg.full, f"{name}-full", env=env)
    if result["status"] == "unrunnable":
        raise _unrunnable(result)
    allowed = list(st.get("owns") or []) + [f"docs/tasks/{tid}/**"]
    entry = {"round": rnd, "head": code_head(p, tid, commits), "config": digest(cfg), **result,
             "dirty": dirty_files(p, allowed), "at": _local_now()}
    _save(p.tests / f"{tid}.json", kind, entry)
    return entry


def run_task(p, tid: str, kind: str) -> dict:
    state.check_id(tid)
    cfg = approved_config(p)
    st, commits = task_target(p, tid)
    return {"task": tid, "kind": kind, **record_task(p, cfg, st, commits, kind)}


def run_final(p) -> dict:
    """태스크 없는 full(마무리, 설계 8.4): `state/tests/final.json` 의 full."""
    cfg = approved_config(p)
    start = gitio.head(p.root)  # 실행 전 HEAD 로 기록한다: 실행 중 들어온 커밋에 passed 가 붙지 않게
    result = attempt(p, cfg, cfg.full, "final-full")
    if result["status"] == "unrunnable":
        raise _unrunnable(result)
    end = gitio.head(p.root)
    entry = {"head": start, "head_moved": end if end != start else None, "config": digest(cfg), **result,
             "dirty": dirty_files(p, []), "at": _local_now()}
    _save(p.tests / "final.json", "full", entry)
    return {"task": None, "kind": "full", **entry}


def gate_results(p, st: dict, role: str, commits: list[dict]) -> dict | None:
    """리뷰 관문(설계 6.1 4a). None 이면 관문이 없다(직무가 developer·tester 가 아니거나 HEAD 에 [test] 가 없다).
    결과는 {head(code_head), config(식별값), 그리고 quick·full 기록 또는 skipped: "unapproved"}. 실행 불가·잠금 대기
    초과·형식·읽기 오류는 예외로 올라간다(리뷰는 아무것도 쓰지 않는다)."""
    from . import workspace
    if role not in GATED_ROLES:
        return None
    cfg = load_config(p)
    if cfg is None:
        return None
    p = workspace.view(p, st)
    tid, value = st["id"], digest(cfg)
    head = code_head(p, tid, commits)
    out = {"head": head, "config": value}
    if not is_approved(p, value):
        return {**out, "skipped": "unapproved"}
    saved = records(p, tid)
    if role == TESTER_ROLE:  # full 한 번만. 같은 라운드·같은 code_head·같은 식별값이면 상태와 관계없이 다시 쓴다
        full = saved.get("full")
        if not (isinstance(full, dict) and full.get("round") == (st.get("round") or 1) and full.get("head") == head
                and full.get("config") == value):
            full = record_task(p, cfg, st, commits, "full")
        return {**out, "full": full}
    quick = saved.get("quick")  # developer: 같은 code_head·식별값의 통과 기록이면 다시 쓴다(라운드는 보지 않는다)
    if not (isinstance(quick, dict) and quick.get("head") == head and quick.get("config") == value
            and quick.get("status") in PASSED):
        quick = record_task(p, cfg, st, commits, "quick")
    return {**out, "quick": quick}


def retry_results(p, st: dict, role: str, commits: list[dict], prev: dict | None) -> dict | None:
    """`review --retry`(설계 6.1): code_head·식별값·확정 여부가 앞 시도의 관문 결과(prev)와 같으면 그것을 그대로 쓰고,
    다르면 관문을 다시 돌린다."""
    from . import workspace
    if role not in GATED_ROLES:
        return None
    cfg = load_config(p)
    if cfg is None:
        return None
    p = workspace.view(p, st)
    value = digest(cfg)
    if (prev and prev.get("head") == code_head(p, st["id"], commits) and prev.get("config") == value
            and bool(prev.get("skipped")) == (not is_approved(p, value))):
        return prev
    return gate_results(p, st, role, commits)


def summary(tests: dict | None) -> dict:
    """출력·history 에 더하는 관문 요약: {tests: {종류: status}} 또는 {tests_skipped: "unapproved"}. 관문이 없으면 {}."""
    if not tests:
        return {}
    if tests.get("skipped"):
        return {"tests_skipped": tests["skipped"]}
    return {"tests": {k: tests[k]["status"] for k in ("quick", "full") if k in tests}}


def failed_quick(tests: dict | None) -> bool:
    """developer 관문의 quick 이 failed·timeout 이다(리뷰어를 띄우지 않고 반려한다)."""
    return bool(tests) and "quick" in tests and tests["quick"].get("status") not in PASSED


def describe(entry: dict, kind: str, p=None) -> list[str]:
    """관문 결과 한 종류의 줄(설계 6.2). 명령은 JSON 문자열(util.dumps)로 보인다: 여러 줄 명령이 새 줄·절을 만들지 못하고,
    UTF-8 이 아닌 파일 이름(os.fsdecode 의 서로게이트)도 `\\udcXX` 로 보여 프롬프트·반려 파일을 쓸 수 있다. p(그 태스크의
    view)를 주면 로그는 그 세션이 여는 경로(p.state_ref: 슬롯 태스크면 상태 루트의 절대 경로)다."""
    def log(rel):
        return rel if p is None else p.state_ref(rel)

    first = f"{kind}: {STATUS_TEXT.get(entry.get('status'), entry.get('status'))}"
    if entry.get("command"):
        first += f" ({entry['seconds']}초" + (f", exit {entry['exit']})" if entry.get("exit") is not None else ")")
    lines = [first]
    if entry.get("command"):
        lines += [f"{kind} 명령: {dumps(entry['command'])}", f"{kind} 로그: {log(entry['log'])}"]
    if entry.get("status") == "flaky" and isinstance(entry.get("first"), dict):
        lines.append(f"{kind} 첫 실행 로그: {log(entry['first'].get('log'))}")
    dirty = list(entry.get("dirty") or [])
    if dirty:
        more = f" 외 {len(dirty) - DIRTY_SHOWN}개" if len(dirty) > DIRTY_SHOWN else ""
        lines.append(f"실행 때 커밋 안 된 다른 파일: {', '.join(show(d) for d in dirty[:DIRTY_SHOWN])}{more}")
    return lines


def _cmd_test(args) -> dict:
    p = find_project(args.root)
    if args.task is None and not args.full:
        raise HteamError("usage", "태스크 ID 또는 --full 이 필요하다", USAGE)
    out = run_task(p, args.task, "full" if args.full else "quick") if args.task else run_final(p)
    out["_exit"] = 0 if out["status"] in PASSED else FAIL
    return out


def register(sub) -> None:
    s = sub.add_parser("test")
    s.add_argument("task", nargs="?")
    s.add_argument("--full", action="store_true")
    s.set_defaults(func=_cmd_test)
