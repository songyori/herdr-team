"""작업 공간(설계 5.10): 슬롯 상태(state/slots.json), 슬롯 잠금, 슬롯 폴더(저장소 전체의 git worktree)·태스크 브랜치·
표시 파일, setup·teardown 실행, 관제 자식 `hteam slot prepare`.

잠금 순서는 슬롯 잠금(state/slots/slot-<N>.lock) → 프로젝트 잠금(state/lock) → 태스크 잠금이다. 슬롯 잠금은 준비·놓기·
마무리 full 자식이 그 슬롯을 쓰는 동안 쥐고, 프로젝트 잠금을 쥔 쪽은 슬롯 잠금을 비차단으로만 시도한다(5.10.3).
git 은 gitio 로만 부른다. 이 모듈은 paths 를 위에서 가져오지 않는다(paths.project_at 이 marker 를 늦게 가져온다).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

from . import config, gitio, roles, state, testgate
from .errors import CONFLICT, FAIL, HteamError
from .util import die_at, flock, now, show, write_json

MARKER_REL = ".herdr-team/state/slot.json"  # 작업 루트의 표시 파일 {main_root, slot, task}(5.10.2)
SLOT_STATES = ("free", "preparing", "busy", "dirty")
SLOT_DEFAULT = {"state": "free", "task": None, "branch": None, "base_branch": None, "base": None, "setup_done": None,
                "since": None}
MINUTE_S = 60  # setup·teardown 시간 상한은 setup_timeout_min × MINUTE_S 초다(시험이 줄인다)
DIRTY_SHOWN = 20  # slot_dirty 출력의 files 개수


def branch_of(tid: str) -> str:
    return f"herdr/{tid}"


# --- 슬롯 상태(5.10.2) ---

def _bad_slots(why: str) -> HteamError:
    return HteamError("bad_slots_file", f"state/slots.json 을 읽지 못했다: {why}", FAIL,
                      "파일을 직접 고치거나 치운 뒤 다시 한다(덮어쓰지 않았다)")


def load(p) -> dict:
    """state/slots.json(엄격). 없으면 {"slots": {}}(모든 슬롯이 free). 읽지 못하거나 꼴이 틀리면 bad_slots_file 이고
    아무것도 쓰지 않는다."""
    try:
        text = p.slots_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"slots": {}}
    except (OSError, ValueError) as exc:
        raise _bad_slots(str(exc)) from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise _bad_slots(f"JSON 이 아니다: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("slots"), dict):
        raise _bad_slots('{"slots": {…}} 꼴이 아니다')
    for n, rec in data["slots"].items():
        if not isinstance(rec, dict):
            raise _bad_slots(f"slot {n} 기록이 JSON 객체가 아니다")
    return data


def entry(data: dict, n: int) -> dict:
    """슬롯 n 의 기록(새 dict). 없는 번호는 free 기본값이다."""
    return {**SLOT_DEFAULT, **data["slots"].get(str(n), {})}


def save(p, data: dict) -> None:
    """임시 파일 + os.replace. 부르는 쪽이 프로젝트 잠금을 쥔다."""
    write_json(p.slots_file, data)


def held_by(data: dict, tid: str) -> int | None:
    """tid 가 쥔 슬롯 번호(가장 작은 것). 없으면 None."""
    return min((int(n) for n, rec in data["slots"].items() if rec.get("task") == tid), default=None)


# --- 경로와 환경(5.10.2·5.7) ---

def folder(p, n: int) -> Path:
    return p.slots_dir / f"slot-{n}"


def work_root(p, n: int) -> Path:
    """슬롯 n 의 작업 루트: 슬롯 폴더 아래 프로젝트의 하위 경로(프로젝트가 저장소 루트면 폴더 그대로)."""
    return folder(p, n) / gitio.top_prefix(p.root)


def own_worktree(top) -> bool:
    """top 이 자기 git worktree 의 맨 위인가(`rev-parse --show-toplevel` 이 top 과 같은 폴더). 슬롯 폴더에 git 을 부르기
    전에 본다: `.git` 이 없으면(worktree add 가 mkdir 직후 죽었다, 사용자가 지웠다) git 이 위로 올라가 메인 저장소를 보고
    그 브랜치·작업 트리를 바꾼다. 폴더가 없거나 `.git` 이 깨졌으면 False. 같은 폴더는 (st_dev, st_ino)로 견준다
    (대소문자를 가리지 않는 파일 시스템의 철자 차이, firmlink)."""
    found = gitio.worktree_top(top)
    return found is not None and os.path.samefile(found, top)


def require_worktree(p, st: dict) -> None:
    """작업 공간 태스크의 슬롯 폴더가 자기 git worktree 인가(own_worktree). 아니면 그 폴더에 git 을 부르지 않고 exit 1
    slot_not_worktree: `.git` 이 없으면 git 이 위로 올라가 메인 저장소를 보고 리뷰 커밋이 메인 작업 트리로 간다. 리뷰가 슬롯에
    쓰고 커밋하기 전에 본다. 작업 공간 태스크가 아니면 보지 않는다."""
    ws = st.get("workspace")
    if ws and not own_worktree(folder(p, ws["slot"])):
        raise HteamError("slot_not_worktree", f"{st['id']} 의 slot-{ws['slot']} 폴더가 git worktree 가 아니다(.git 이 없거나 "
                         "깨졌다). 그 폴더에서 git 을 부르지 않았다", FAIL,
                         "사용자와 폴더를 확인한다(그 폴더에서 git 을 부르면 메인 저장소가 잡힌다)",
                         data={"slot": ws["slot"]})


def task_root(p, st: dict) -> Path:
    """태스크가 도는 작업 루트. 작업 공간 태스크가 아니면 메인 프로젝트 루트다."""
    return Path(st["workspace"]["root"]) if st.get("workspace") else p.root


def view(p, st: dict):
    """태스크의 두 루트(설계 5.10.2): 상태 루트는 p.root 그대로, 작업 루트는 그 태스크의 task_root. 태스크의 git 조회·작업
    트리 파일·커밋·시험은 이것의 work_root 에서 한다(슬롯 안에서 찾은 p 여도 태스크 상태가 위치를 정한다)."""
    from .paths import Project  # 이 모듈은 paths 를 위에서 가져오지 않는다(모듈 설명)
    return Project(p.root, work_root=task_root(p, st))


def env_args(env: dict[str, str]) -> list[str]:
    """horch worker-start 의 `--env=KEY=VALUE` 인자(이름 순서, 값은 한 인자로)."""
    return [f"--env={k}={env[k]}" for k in sorted(env)]


def slot_env(cfg, n: int) -> dict[str, str]:
    """[workspace.env] 값의 {slot} 을 n 으로 채운 것 + HTEAM_SLOT. cfg 는 config.Config 또는 config.TestSettings 다."""
    return {**{k: v.replace("{slot}", str(n)) for k, v in cfg.workspace.env.items()}, "HTEAM_SLOT": str(n)}


def task_env(p, cfg, st: dict) -> dict[str, str]:
    """태스크의 시험 환경 변수: 작업 공간 태스크면 그 슬롯 값, worktree 모드의 메인 폴더 태스크면 슬롯 0 값(5.7), shared 면
    없다."""
    if st.get("workspace"):
        return slot_env(cfg, st["workspace"]["slot"])
    return slot_env(cfg, 0) if cfg.workspace.on else {}


# --- 슬롯 잠금(5.10.3 끝 문단) ---

@contextlib.contextmanager
def slot_lock(p, n: int, *, nowait: bool = False) -> Iterator[None]:
    """state/slots/slot-<N>.lock 의 flock. nowait 면 기다리지 않는다: 못 쥐면 exit 3 slot_locked."""
    path = p.slots_dir / f"slot-{n}.lock"
    if not nowait:
        with flock(path):
            yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HteamError("slot_locked", f"slot-{n} 을 다른 hteam 자식(준비·놓기·마무리 full)이 쓰는 중이다", CONFLICT,
                             "끝나면 관제가 다시 본다") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def slot_busy(p, n: int) -> bool:
    """슬롯 잠금을 다른 실행자(준비·놓기·마무리 full 자식)가 쥐었나. 비차단으로 잡아 보고 곧 놓는다."""
    try:
        with slot_lock(p, n, nowait=True):
            pass
    except HteamError as exc:
        if exc.code == "slot_locked":
            return True
        raise
    return False


# --- 표시 파일(5.10.2) ---

def write_marker(root, main_root, n: int, tid: str) -> None:
    write_json(Path(root) / MARKER_REL, {"main_root": str(main_root), "slot": n, "task": tid})


def marker(root) -> dict | None:
    """root 의 표시 파일 {main_root, slot, task}. 없거나 깨졌거나, main_root 가 herdr-team 프로젝트가 아니거나, main_root 의
    git common dir 이 root 의 것과 다르면(폴더를 옮겼다) None 이다."""
    try:
        data = json.loads((Path(root) / MARKER_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    main, n, tid = data.get("main_root"), data.get("slot"), data.get("task")
    if not (isinstance(main, str) and os.path.isabs(main) and isinstance(n, int) and not isinstance(n, bool)
            and 1 <= n <= 9 and isinstance(tid, str) and state.ID_RE.fullmatch(tid)):
        return None
    if not (Path(main) / ".herdr-team" / "config.toml").is_file():
        return None
    mine = gitio.common_dir(root)
    if mine is None or gitio.common_dir(main) != mine:
        return None
    return {"main_root": main, "slot": n, "task": tid}


# --- setup·teardown(5.10.3 의 4, 5.7 의 실행 규칙) ---

def run_hook(p, cfg, n: int, kind: str, tid: str) -> dict | None:
    """슬롯 n 의 작업 루트에서 [workspace] 의 setup·teardown(kind)을 `/bin/sh -c` 로 돌린다. 명령이 없으면 부르지 않고
    None. 새 세션(그룹 종료), stdin /dev/null, 출력은 로그 하나, 시간 상한 setup_timeout_min. 중단되면 그룹을 끝내고 다시
    올린다. 자식은 잠금 기술자를 물려받지 않는다(Popen 의 close_fds 기본값)."""
    command = getattr(cfg.workspace, kind)
    if not command:
        return None
    root = work_root(p, n)
    env = testgate.child_env(cfg, {**slot_env(cfg, n), "HTEAM_MAIN_ROOT": str(p.root), "HTEAM_SLOT_ROOT": str(root)})
    log = p.slot_logs / f"slot-{n}-{kind}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(f"$ {show(command)}\n")
        fh.flush()
        try:
            proc = subprocess.Popen(["/bin/sh", "-c", command], cwd=str(root), stdin=subprocess.DEVNULL, stdout=fh,
                                    stderr=subprocess.STDOUT, start_new_session=True, env=env)
        except OSError as exc:
            fh.write(f"실행하지 못했다: {exc}\n")
            proc = None
        code = None
        if proc is not None:
            try:
                code = proc.wait(timeout=cfg.workspace.setup_timeout_min * MINUTE_S)
            except subprocess.TimeoutExpired:
                testgate.kill_group(proc)
            except BaseException:  # 중단: setup 프로세스를 남기지 않는다
                testgate.kill_group(proc)
                raise
    if proc is None or code in (126, 127):
        status = "unrunnable"
    elif code is None:
        status = "timeout"
    else:
        status = "passed" if code == 0 else "failed"
    return {"kind": kind, "status": status, "exit": code, "seconds": round(time.monotonic() - start, 1),
            "log": log.relative_to(p.root).as_posix(), "tail": testgate.read_tail(log)}


# --- 준비(5.10.3 의 2–4) ---

def _not_reserved(tid: str) -> HteamError:
    return HteamError("slot_not_reserved", f"{tid} 가 준비할 슬롯 예약이 없다(state/slots.json 에 preparing 인 {tid} "
                      "슬롯이 없다)", CONFLICT, f"hteam start {tid} 가 슬롯을 예약한다")


def _mine(data: dict, n: int, tid: str) -> dict:
    """슬롯 n 이 아직 tid 의 preparing 예약이면 그 기록. 아니면(그 사이 drop·reset 이 바꿨다) slot_not_reserved."""
    rec = entry(data, n)
    if rec["task"] != tid or rec["state"] != "preparing":
        raise _not_reserved(tid)
    return rec


@contextlib.contextmanager
def _reserved(p, n: int, tid: str) -> Iterator[dict]:
    """프로젝트 잠금 안에서 예약을 다시 보고(_mine) 블록이 고친 기록을 블록이 끝난 뒤 쓴다. 블록 안은 프로젝트 잠금 안이다."""
    with state.project_lock(p):
        data = load(p)
        rec = _mine(data, n, tid)
        yield rec
        data["slots"][str(n)] = rec
        save(p, data)


def _reset(rec: dict, **fields) -> None:
    """기록을 태스크 없는 새 기록(기본 free)으로 바꾼다. setup_done 은 fields 에 없으면 그대로 둔다."""
    new = {**SLOT_DEFAULT, "setup_done": rec["setup_done"], "since": now(), **fields}
    rec.clear()
    rec.update(new)


def _launch_failed(p, tid: str, event: str, **info) -> None:
    with state.edit(p, tid) as st:
        state.move(st, "launch_failed", event, **info)


def _set_aside(p, n: int, tid: str, files: list[str] | None) -> None:
    """새로 잡은 슬롯 폴더를 쓸 수 없다(files: 커밋 안 된 변경. None 이면 폴더가 git worktree 가 아니다): 슬롯을 태스크
    없는 dirty 로 두고 예약을 푼다(태스크는 pending 그대로). 파일은 건드리지 않는다."""
    with _reserved(p, n, tid) as rec:
        _reset(rec, state="dirty")
    if files is None:
        raise HteamError("slot_dirty", f"slot-{n} 폴더가 git worktree 가 아니어서(.git 이 없거나 깨졌다) {tid} 를 준비하지 "
                         "않았다", CONFLICT, "사용자와 폴더를 확인한다(그 폴더에서 git 을 부르면 메인 저장소가 잡힌다). 쓸 "
                         "것이 없으면 폴더를 치우고 git worktree prune 한다",
                         data={"slot": n, "kind": "slot_dirty", "reason": "not_worktree"})
    raise HteamError("slot_dirty", f"slot-{n} 폴더에 커밋 안 된 변경이 있어 {tid} 를 준비하지 않았다: "
                     + ", ".join(show(f) for f in files[:5]), CONFLICT, f"사용자가 버려도 된다고 하면 hteam slot reset {n}",
                     data={"slot": n, "kind": "slot_dirty", "files": files[:DIRTY_SHOWN]})


def _refuse_branch(p, n: int, tid: str, branch: str) -> None:
    """처음 시작하는 태스크의 브랜치가 이미 있다: 슬롯을 free(폴더 남김), 태스크를 라운드 없는 launch_failed 로 쓴다."""
    with _reserved(p, n, tid) as rec:
        _reset(rec)
        _launch_failed(p, tid, "slot_branch_exists")
    raise HteamError("branch_exists", f"브랜치 {branch} 가 이미 있다. 새 브랜치를 만들지 않았다", CONFLICT,
                     "남은 브랜치를 어떻게 할지 사용자에게 묻는다", data={"slot": n, "kind": "branch_exists", "branch": branch})


def _setup_failed(p, n: int, tid: str, base: str, top: Path, branch: str, result: dict) -> None:
    """setup 실패·시간 초과·실행 불가: 브랜치를 떠나고 커밋 없는 빈 브랜치는 지운다(다시 시작이 branch_exists 로 막히지
    않게). 슬롯은 free(setup_done 없음: 반쯤 된 환경), 태스크는 라운드 없는 launch_failed. 폴더와 무시된 파일은 남긴다."""
    gitio.switch_detach(top)
    if gitio.branch_tip(top, branch) == base:
        gitio.delete_branch(top, branch, force=True)
    with _reserved(p, n, tid) as rec:
        _reset(rec, setup_done=None)
        _launch_failed(p, tid, "slot_setup_failed", slot=n)
    raise HteamError("setup_failed", f"slot-{n} setup 이 {result['status']}(exit {result['exit']})로 끝났다. 로그: "
                     f"{result['log']}", FAIL, data={"slot": n, "kind": "setup_failed", "status": result["status"],
                                                     "exit": result["exit"], "log": result["log"],
                                                     "tail": result["tail"]})


def prepare(p, cfg, tid: str) -> dict:
    """`hteam slot prepare T` 의 몸통: start 가 써 둔 예약(preparing)의 폴더·브랜치·표시 파일·setup 을 하고 ready 를 남긴다.
    내내 슬롯 잠금을 쥔다(관제는 그 잠금으로 자식이 살았는지 안다). 앞 자식이 중간에 죽었으면 남은 것부터 잇는다: 브랜치가
    이미 herdr/T 면 git 을, setup_done 이 T 면 setup 을 다시 하지 않는다."""
    with state.project_lock(p):
        n = held_by(load(p), tid)
    if n is None:
        raise _not_reserved(tid)
    with slot_lock(p, n, nowait=True):
        die_at("slot_prepare_locked")
        with state.project_lock(p):
            rec = _mine(load(p), n, tid)
        top, root, branch = folder(p, n), work_root(p, n), branch_of(tid)
        if top.exists() and not own_worktree(top):  # git 을 부르면 메인 작업 트리가 바뀐다: 아무 git 도 하지 않는다
            _set_aside(p, n, tid, None)
        ours = top.is_dir() and gitio.current_branch(top) == branch  # 앞 자식이 브랜치까지 했다
        if not top.exists():
            gitio.worktree_add(p.root, top, rec["base"])
            die_at("slot_worktree_added")
        elif not ours:
            files = gitio.dirty(top, ["."])
            if files:
                _set_aside(p, n, tid, files)
        if not ours:
            if not gitio.branch_exists(top, branch):
                gitio.switch_new(top, branch, rec["base"])
            elif state.require(p, tid).get("workspace"):
                gitio.switch(top, branch)  # 이미 시작한 태스크(복구·수정 라운드)
            else:
                _refuse_branch(p, n, tid, branch)
            die_at("slot_branch_made")
        write_marker(root, p.root, n, tid)
        result = None
        if cfg.workspace.setup and rec["setup_done"] != tid:
            result = run_hook(p, cfg, n, "setup", tid)
            if result["status"] != "passed":
                _setup_failed(p, n, tid, rec["base"], top, branch, result)
            with _reserved(p, n, tid) as now_rec:
                now_rec["setup_done"] = tid
            die_at("slot_setup_done")
        with _reserved(p, n, tid) as now_rec:
            now_rec["ready"] = True
    return {"task": tid, "slot": n, "root": str(root), "branch": branch, "base_branch": rec["base_branch"],
            "base": rec["base"], "setup": result, "ready": True}


# --- CLI ---

def _cmd_prepare(args) -> dict:
    from .paths import find_project  # 이 모듈은 paths 를 위에서 가져오지 않는다(모듈 설명)
    p = find_project(args.root)
    roles.require_drive(p)
    state.check_id(args.task)
    cfg = config.load(p)
    if not cfg.workspace.on:
        raise HteamError("workspace_off", '작업 공간이 꺼져 있다(config.toml [workspace] mode = "worktree" 가 아니다)',
                         CONFLICT)
    return prepare(p, cfg, args.task)


def register(sub) -> None:
    slot = sub.add_parser("slot")
    ssub = slot.add_subparsers(dest="slot_cmd", required=True, parser_class=slot.__class__)
    s = ssub.add_parser("prepare")
    s.add_argument("task")
    s.set_defaults(func=_cmd_prepare)
