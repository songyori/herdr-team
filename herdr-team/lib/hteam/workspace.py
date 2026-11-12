"""작업 공간(설계 5.10): 슬롯 상태(state/slots.json), 슬롯 잠금, 슬롯 폴더(저장소 전체의 git worktree)·태스크 브랜치·
표시 파일, setup·teardown 실행, 관제 자식 `hteam slot prepare`·`slot release`, accept 의 병합(5.10.6), 마무리 full 의 슬롯
(5.10.7), 큐 명령 `hteam slot reset`·status 의 workspace(5.10.8).

잠금 순서는 슬롯 잠금(state/slots/slot-<N>.lock) → 프로젝트 잠금(state/lock) → git 잠금(state/git.lock, 병합만) →
태스크 잠금이다. 슬롯 잠금은 준비·놓기·마무리 full 자식이 그 슬롯을 쓰는 동안 쥐고, 프로젝트 잠금을 쥔 쪽은 슬롯 잠금을
비차단으로만 시도한다(5.10.3).
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

from . import config, gitio, roles, specs, state, testgate
from .errors import CONFLICT, FAIL, USAGE, HteamError
from .util import die_at, flock, now, show, write_json

MARKER_REL = ".herdr-team/state/slot.json"  # 작업 루트의 표시 파일 {main_root, slot, task}(5.10.2)
SLOT_STATES = ("free", "preparing", "busy", "dirty")
SLOT_KEYS = frozenset(str(n) for n in range(1, 10))  # slots.json 의 슬롯 키(설정 slots 는 1–9)
SLOT_DEFAULT = {"state": "free", "task": None, "branch": None, "base_branch": None, "base": None, "setup_done": None,
                "since": None}
MINUTE_S = 60  # setup·teardown 시간 상한은 setup_timeout_min × MINUTE_S 초다(시험이 줄인다)
DIRTY_SHOWN = 20  # slot_dirty 출력의 files 개수
MERGE_BLOCKED_S = 600  # 병합 거부가 이보다 오래 이어지면 workspace_failed(merge_blocked) 를 한 번 올린다(5.10.6)
MERGE_REFUSED = ("merge_pending", "merge_blocked", "base_moved")  # 상태를 바꾸지 않은 병합 거부(관제가 다시 한다)


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
        if n not in SLOT_KEYS:  # 뒤에서 int(n) 으로 풀고 str(n) 으로 찾는다
            raise _bad_slots(f"슬롯 키 {json.dumps(n, ensure_ascii=False)} 가 1–9 의 숫자가 아니다")
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
    """태스크가 도는 작업 루트. 작업 공간 태스크가 아니거나 병합한 태스크면 메인 프로젝트 루트다: 병합한 태스크의 보고서·
    리뷰 파일은 병합 커밋으로 기준 브랜치에 있고, 슬롯은 놓은 뒤 다른 태스크가 다시 쓴다(5.10.6)."""
    ws = st.get("workspace")
    return Path(ws["root"]) if ws and not ws.get("merge") else p.root


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
    없다. 병합한 작업 공간 태스크는 메인 폴더 태스크와 같다(task_root 와 같은 판정): 메인 폴더에서 돌고, 놓은 슬롯은 다른
    태스크가 다시 쓴다."""
    ws = st.get("workspace")
    if ws and not ws.get("merge"):
        return slot_env(cfg, ws["slot"])
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


def _set_aside(p, n: int, tid: str, files: list[str] | None, *, after: dict | None = None) -> None:
    """새로 잡은 슬롯 폴더를 쓸 수 없다(files: 커밋 안 된 변경. None 이면 폴더가 git worktree 가 아니다. after 는 그렇게
    만든 setup 의 결과): 슬롯을 태스크 없는 dirty 로 두고 예약을 푼다(태스크는 pending 그대로). 파일은 건드리지 않는다."""
    with _reserved(p, n, tid) as rec:
        _reset(rec, state="dirty")
    if files is None:
        what = (f"slot-{n} 폴더가 git worktree 가 아니어서(.git 이 없거나 깨졌다) {tid} 를 준비하지 않았다" if after is None
                else f"slot-{n} 폴더가 setup 뒤 git worktree 가 아니게 되어(.git 이 없거나 깨졌다) {tid} 를 준비하지 않았다"
                f"(setup {after['status']}, 로그 {after['log']}. 그 뒤 git 은 부르지 않았다)")
        raise HteamError("slot_dirty", what, CONFLICT, "사용자와 폴더를 확인한다(그 폴더에서 git 을 부르면 메인 저장소가 "
                         "잡힌다). 쓸 것이 없으면 폴더를 치우고 git worktree prune 한다",
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


def _setup_error(n: int, result: dict) -> HteamError:
    """setup 이 통과하지 못했다(준비와 마무리 full 이 같은 꼴로 낸다)."""
    return HteamError("setup_failed", f"slot-{n} setup 이 {result['status']}(exit {result['exit']})로 끝났다. 로그: "
                      f"{result['log']}", FAIL, data={"slot": n, "kind": "setup_failed", "status": result["status"],
                                                      "exit": result["exit"], "log": result["log"],
                                                      "tail": result["tail"]})


def _setup_failed(p, n: int, tid: str, base: str, top: Path, branch: str, result: dict) -> None:
    """setup 실패·시간 초과·실행 불가: 브랜치를 떠나고 커밋 없는 빈 브랜치는 지운다(다시 시작이 branch_exists 로 막히지
    않게). 슬롯은 free(setup_done 없음: 반쯤 된 환경), 태스크는 라운드 없는 launch_failed. 폴더와 무시된 파일은 남긴다."""
    gitio.switch_detach(top)
    if gitio.branch_tip(top, branch) == base:
        gitio.delete_branch(top, branch, force=True)
    with _reserved(p, n, tid) as rec:
        _reset(rec, setup_done=None)
        _launch_failed(p, tid, "slot_setup_failed", slot=n)
    raise _setup_error(n, result)


def prepare(p, cfg, tid: str) -> dict:
    """`hteam slot prepare T` 의 몸통: start 가 써 둔 예약(preparing)의 폴더·브랜치·표시 파일·setup 을 하고 ready 를 남긴다.
    내내 슬롯 잠금을 쥔다(관제는 그 잠금으로 자식이 살았는지 안다). 앞 자식이 중간에 죽었으면 남은 것부터 잇는다: 브랜치가
    이미 herdr/T 면 git 을, setup_done 이 T 면 setup 을 다시 하지 않는다. setup 뒤 폴더가 자기 worktree 가 아니게 됐으면(setup
    이 .git 을 지웠다) git 을 더 부르지 않고 dirty(not_worktree)로 둔다(_set_aside)."""
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
            if not own_worktree(top):  # setup 이 .git 을 지웠다: 실패 갈래의 git(switch --detach)도 메인을 잡는다
                _set_aside(p, n, tid, None, after=result)
            if result["status"] != "passed":
                _setup_failed(p, n, tid, rec["base"], top, branch, result)
            with _reserved(p, n, tid) as now_rec:
                now_rec["setup_done"] = tid
            die_at("slot_setup_done")
        with _reserved(p, n, tid) as now_rec:
            now_rec["ready"] = True
    return {"task": tid, "slot": n, "root": str(root), "branch": branch, "base_branch": rec["base_branch"],
            "base": rec["base"], "setup": result, "ready": True}


# --- 병합(5.10.6, 6.4 의 7단계 줄) ---

def first_line(text: str | None) -> str:
    """git 출력의 첫 줄(빈 줄은 건너뛴다)."""
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def _tail(text: str) -> str:
    """git 출력의 끝: testgate.read_tail 과 같은 규칙(공백뿐인 줄을 빼고 줄마다 TAIL_WIDTH 자, 마지막 TAIL_LINES 줄)."""
    lines = [line[:testgate.TAIL_WIDTH] for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-testgate.TAIL_LINES:])


def _merge_refused(code: str, ws: dict, message: str, hint: str, **data) -> HteamError:
    return HteamError(code, message, CONFLICT, hint, data={"kind": code, "slot": ws["slot"], **data})


def _blocked(tid: str, ws: dict, message: str, output: str) -> HteamError:
    return _merge_refused("merge_blocked", ws, message, "사용자가 메인 폴더의 병합 상태를 정리한 뒤 관제가 다시 병합한다",
                          output=output[-600:])


def merge(p, cfg, st: dict) -> dict:
    """작업 공간 태스크 st 의 태스크 브랜치를 메인 폴더의 기준 브랜치에 `git merge --no-ff` 한다(5.10.6). 부르는 쪽
    (tasks.accept)이 프로젝트 잠금을 쥐고, 이 함수가 git 잠금을 쥔다. 결과 {"result": "merged", "sha"} 또는
    {"result": "conflict", "base", "files"}(되돌렸다). 거부는 상태를 바꾸지 않는 예외다: 메인 폴더에 끝나지 않은 병합이
    있거나 되돌리지 못했으면 merge_blocked, 메인 폴더 브랜치가 기준 브랜치가 아니면 base_moved, 병합이 시작되지 않았으면
    (index 에 올린 변경, 덮을 커밋 안 된 파일, index.lock) merge_pending. 병합이 시작됐는데 충돌 파일이 없으면 git 훅
    (commit-msg·pre-merge-commit)이 병합 커밋을 거부한 것이다: 되돌린 뒤 merge_blocked(data 의 tail 은 git stderr 의 끝, 비면
    git 출력 끝). 갈래는 git 메시지가 아니라 MERGE_HEAD·충돌 파일로 가른다(로캘을 타지 않는다). rerere 는 병합에서 끈다
    (gitio.merge_no_ff: 기록된 해결이 충돌 파일을 비우면 훅 거부로 보인다)."""
    ws, tid = st["workspace"], st["id"]
    with flock(p.git_lock):
        if gitio.merge_head(p.root):
            raise _blocked(tid, ws, f"메인 폴더에 끝나지 않은 병합(MERGE_HEAD)이 있어 {tid} 를 병합하지 않았다", "")
        cur = gitio.current_branch(p.root)
        if cur != ws["base_branch"]:
            raise _merge_refused("base_moved", ws, f"메인 폴더 브랜치가 {cur or 'detached HEAD'} 라 {tid} 를 기준 브랜치 "
                                 f"{ws['base_branch']} 에 병합하지 않았다", "메인 폴더를 기준 브랜치로 되돌릴지 사용자에게 묻는다",
                                 branch=cur, base_branch=ws["base_branch"])
        base = gitio.head(p.root)
        proc = gitio.merge_no_ff(p.root, ws["branch"], f"[{tid}] merge: {specs.load(p, tid).title}")
        output = ((proc.stderr or "") + (proc.stdout or "")).strip()
        # 훅 출력은 stderr 로 온다. 자동 병합한 파일이 많으면 stdout 의 `Auto-merging` 줄이 output 의 끝을 채우므로 따로 둔다
        hook_out = (proc.stderr or "").strip() or output
        if proc.returncode == 0:
            return {"result": "merged", "sha": gitio.head(p.root)}
        if not gitio.merge_head(p.root):  # 병합이 시작되지 않았다: 거부(다시 한다)
            raise _merge_refused("merge_pending", ws, f"{tid} 병합이 거부됐다(관제가 다음 재확인에 다시 한다): "
                                 f"{first_line(output)[:200]}",
                                 "메인 폴더의 index 에 올린 변경·커밋 안 된 파일·index.lock 을 확인한다", output=output[-600:])
        prefix = gitio.top_prefix(p.root)
        files = sorted(gitio.from_top(prefix, f) for f in gitio.unmerged(p.root))
        gitio.merge_abort(p.root)
        if gitio.merge_head(p.root):  # 되돌렸는지 확인한다
            raise _blocked(tid, ws, f"{tid} 병합 충돌을 되돌리지 못했다(git merge --abort 뒤에도 MERGE_HEAD 가 남았다)",
                           output)
        if not files:  # 충돌 없이 멈췄다: 훅이 병합 커밋을 거부했다. 기다려도 풀리지 않는다(--no-verify 로 건너뛰지 않는다)
            raise _merge_refused("merge_blocked", ws, f"{tid} 병합 커밋을 git 훅이 거부했다(충돌 파일 없음, 되돌렸다): "
                                 f"{first_line(hook_out)[:200]}", "사용자와 훅 출력(tail)을 보고 훅이나 병합 메시지 규칙을 정한 "
                                 "뒤 관제가 다시 병합한다(훅을 건너뛰지 않는다)", tail=_tail(hook_out))
        return {"result": "conflict", "base": base, "files": files}


# --- 놓기(5.10.6) ---

def _workspace_off() -> HteamError:
    return HteamError("workspace_off", '작업 공간이 꺼져 있다(config.toml [workspace] mode = "worktree" 가 아니다)',
                      CONFLICT)


def _write(p, n: int, keep, rec: dict) -> None:
    """프로젝트 잠금 안에서 슬롯 n 의 기록이 아직 keep(기록) 이 참인 것이면 rec 로 쓴다."""
    with state.project_lock(p):
        data = load(p)
        if keep(entry(data, n)):
            data["slots"][str(n)] = rec
            save(p, data)


def release(p, cfg, tid: str) -> dict:
    """`hteam slot release T` 의 몸통: 병합하거나 버린 태스크의 슬롯을 놓는다. 슬롯 잠금(nowait)을 쥔 채 teardown →
    작업 트리 검사 → (깨끗하면) `git switch --detach` → (병합한 브랜치면) `git branch -d` → free. 슬롯에 끝나지 않은 병합이
    있거나, 버린 태스크의 슬롯에 커밋 안 된 변경이 있거나, switch 가 거부되면 switch·브랜치 지우기를 하지 않고 태스크 없는
    dirty 로 둔다(정리는 slot reset). 슬롯 폴더가 자기 worktree 가 아니면 teardown 도 git 도 부르지 않고(결과의 teardown
    None, reason not_worktree) dirty 로 둔다(그 폴더에서 부른 git 은 메인 작업 트리를 바꾼다). teardown 뒤에도 다시 본다
    (teardown 이 .git 을 지웠다): 아니면 git 을 더 부르지 않고 dirty(reason not_worktree, teardown 결과는 그대로). 슬롯
    폴더와 무시된 파일은 지우지 않는다. 다시 불러도 같은 결과로 잇는다(teardown 은 다시 돈다)."""
    nothing = {"task": tid, "slot": None, "state": None, "teardown": None, "branch_deleted": False, "dirty": []}
    with state.project_lock(p):
        n = held_by(load(p), tid)
    if n is None:
        return nothing
    st = state.require(p, tid)
    if st["status"] not in ("done", "dropped"):
        raise HteamError("task_open", f"{tid} 는 {st['status']} 다. 슬롯은 병합하거나 버린 뒤에 놓는다", CONFLICT,
                         data={"status": st["status"]})

    def mine(rec: dict) -> bool:  # 기록이 아직 이 태스크의 것인가
        return rec["task"] == tid

    with slot_lock(p, n, nowait=True):
        with state.project_lock(p):
            if not mine(entry(load(p), n)):
                return nothing
        top, branch = folder(p, n), branch_of(tid)
        if not own_worktree(top):  # teardown 보다 먼저: 그 폴더의 사용자 명령(git reset 등)도 메인 저장소를 잡는다
            _write(p, n, mine, {**SLOT_DEFAULT, "state": "dirty", "since": now()})
            return {"task": tid, "slot": n, "teardown": None, "branch_deleted": False, "dirty": [], "state": "dirty",
                    "reason": "not_worktree"}
        teardown = run_hook(p, cfg, n, "teardown", tid)
        die_at("slot_release_teardown")
        out = {"task": tid, "slot": n, "teardown": teardown, "branch_deleted": False, "dirty": []}
        dirty = {**SLOT_DEFAULT, "state": "dirty", "since": now()}  # 태스크 연결을 푼다(브랜치·병합 상태·파일은 그대로)
        if teardown is not None and not own_worktree(top):  # teardown 이 .git 을 지웠거나 폴더를 다시 만들었다
            _write(p, n, mine, dirty)
            return {**out, "state": "dirty", "reason": "not_worktree"}
        # 작업 트리 검사는 switch 보다 먼저다: git 은 병합 중 switch 를 거부한다
        merging = bool(gitio.merge_head(top))
        files = gitio.dirty(top, ["."]) if merging or st["status"] == "dropped" else []
        keep = merging or bool(files)
        if not keep:
            try:
                gitio.switch_detach(top)
            except HteamError as exc:
                if exc.code != "git_failed":
                    raise
                keep, files = True, gitio.dirty(top, ["."])  # switch 가 거부했다: 다시 하지 않고 남긴다
        if keep:
            _write(p, n, mine, dirty)
            return {**out, "state": "dirty", "dirty": files[:DIRTY_SHOWN]}
        if st["status"] == "done" and gitio.branch_exists(p.root, branch):  # 버린 태스크의 브랜치는 기록으로 남긴다
            try:
                gitio.delete_branch(p.root, branch)
                out["branch_deleted"] = True
            except HteamError as exc:
                if exc.code != "git_failed":
                    raise
        die_at("slot_release_detached")
        _write(p, n, mine, {**SLOT_DEFAULT, "since": now()})  # setup_done 없음: teardown 했으니 다음 태스크가 다시 한다
    return {**out, "state": "free"}


def releasable(p) -> list[tuple[int, str]]:
    """놓을 슬롯: 기록의 태스크가 done·dropped 인데 기록이 busy 이거나 준비를 마친(ready) preparing 인 (번호, 태스크).
    번호 순. 놓기 도중 관제나 자식이 죽어도 재확인이 이것으로 잇는다(5.10.6)."""
    found = []
    data = load(p)
    for key in sorted(data["slots"], key=int):
        rec = entry(data, int(key))
        tid = rec["task"]
        if not tid or not (rec["state"] == "busy" or (rec["state"] == "preparing" and rec.get("ready"))):
            continue
        st = state.load(p, tid)
        if st is not None and st["status"] in ("done", "dropped"):
            found.append((int(key), tid))
    return found


# --- slot reset(5.10.8) ---

def slot_number(cfg, value) -> int:
    """`slot reset <N>` 의 번호: 1–slots 의 정수(문자열이면 숫자만). 아니면 exit 2 bad_slot."""
    text = str(value)
    if not (text.isascii() and text.isdigit() and 1 <= int(text) <= cfg.workspace.slots):
        raise HteamError("bad_slot", f"슬롯 번호는 1–{cfg.workspace.slots} 다: {text}", USAGE)
    return int(text)


def check_reset(cfg, value) -> int:
    """slot reset 의 입력 검사(모드 → 번호). 메인이 큐에 넣기 전에도 본다."""
    if not cfg.workspace.on:
        raise _workspace_off()
    return slot_number(cfg, value)


def reset(p, cfg, n, *, request: str | None = None) -> dict:
    """`hteam slot reset <N>`(큐 명령): 태스크 없는 dirty 슬롯만 `git reset --hard`·`git clean -fd`(무시된 파일은 남는다)
    뒤 free 로 쓴다. 되돌릴 수 없으므로 메인은 사용자 확인 뒤에만 부른다. request(큐 요청 id)를 기록에 남긴다(재실행 막기).
    슬롯 폴더가 자기 worktree 가 아니면 그 폴더에서 git 을 부르지 않는다(메인 작업 트리를 지운다): 폴더가 없으면(사용자가
    치웠다) 메인 루트에서 `git worktree prune` 만 하고 free, 있으면 exit 1 slot_not_worktree."""
    n = check_reset(cfg, n)
    with slot_lock(p, n, nowait=True):
        with state.project_lock(p):
            data = load(p)
            rec = entry(data, n)
            if rec["state"] != "dirty" or rec["task"]:
                raise HteamError("slot_not_dirty", f"slot-{n} 은 {rec['state']}({rec['task'] or '태스크 없음'})라 reset 하지 "
                                 "않는다(dirty 이고 태스크가 없을 때만)", CONFLICT,
                                 data={"slot": n, "state": rec["state"], "task": rec["task"]})
            top = folder(p, n)
            if top.exists():
                if not own_worktree(top):
                    raise HteamError("slot_not_worktree", f"slot-{n} 폴더가 git worktree 가 아니다(.git 이 없거나 깨졌다). 그 "
                                     "폴더에서 git 을 부르지 않았다", FAIL, "사용자와 폴더를 확인한다(그 폴더에서 git 을 부르면 "
                                     "메인 저장소가 잡힌다). 쓸 것이 없으면 폴더를 치우고 git worktree prune 한 뒤 다시 한다",
                                     data={"slot": n})
                gitio.reset_hard(top)
                gitio.clean_untracked(top)
            else:  # 남은 worktree 등록을 지운다: 남으면 다음 worktree add 가 "missing but already registered" 로 실패한다
                gitio.worktree_prune(p.root)
            data["slots"][str(n)] = {**SLOT_DEFAULT, "since": now(), "reset_request": request}
            save(p, data)
    return {"slot": n, "state": "free"}


# --- 마무리 full(5.10.7) ---

def claim_final(p, cfg) -> tuple[int, str]:
    """마무리 full 이 쓸 슬롯을 잡는다(프로젝트 잠금 안): free 이거나 앞 마무리 full 이 남긴 기록(busy, 태스크 없음,
    use final)인데 슬롯 잠금이 풀린 가장 작은 번호를 busy·use final·base(메인 HEAD) 로 쓴다. (번호, base). 없으면 exit 3
    no_free_slot."""
    with state.project_lock(p):
        data = load(p)
        for n in range(1, cfg.workspace.slots + 1):
            rec = entry(data, n)
            left = rec["state"] == "busy" and not rec["task"] and rec.get("use") == "final"
            if (rec["state"] == "free" or left) and not slot_busy(p, n):
                base = gitio.head(p.root)
                data["slots"][str(n)] = {**SLOT_DEFAULT, "state": "busy", "use": "final", "base": base, "since": now()}
                save(p, data)
                return n, base
    raise HteamError("no_free_slot", f"빈 슬롯이 없다(slot-1–{cfg.workspace.slots} 을 모두 쓰는 중이다). 마무리 full 은 "
                     "슬롯이 비면 다시 한다", CONFLICT)


def free_final(p, n: int) -> None:
    """마무리 full 의 기록을 free 로(아직 그 기록일 때만)."""
    _write(p, n, lambda rec: rec["state"] == "busy" and not rec["task"] and rec.get("use") == "final",
           {**SLOT_DEFAULT, "since": now()})


def _final_dirty(p, n: int) -> None:
    """마무리 full 이 잡은 슬롯을 쓸 수 없다: 태스크 없는 dirty 로 둔다(아직 그 기록일 때만. 정리는 slot reset). 뒤의
    free_final 은 이 기록을 덮지 않는다."""
    _write(p, n, lambda rec: rec.get("use") == "final" and not rec["task"],
           {**SLOT_DEFAULT, "state": "dirty", "since": now()})


def _final_not_worktree(p, n: int, when: str, skipped: str = "마무리 full 을 돌리지 않았다") -> None:
    """마무리 full 이 잡은 슬롯 폴더가 git worktree 가 아니다(when: 비었거나 "setup 뒤 "·"full 뒤 "): dirty 로 두고 exit 3
    slot_dirty. 그 폴더에서 git·full·teardown 을 부르지 않는다(skipped 는 하지 않은 것을 적는 글)."""
    _final_dirty(p, n)
    raise HteamError("slot_dirty", f"slot-{n} 폴더가 {when}git worktree 가 아니어서(.git 이 없거나 깨졌다) {skipped}",
                     CONFLICT, "사용자와 폴더를 확인한다(그 폴더에서 git 을 부르면 메인 저장소가 잡힌다). 쓸 "
                     f"것이 없으면 폴더를 치우고 git worktree prune 한 뒤 hteam slot reset {n}",
                     data={"slot": n, "kind": "slot_dirty", "reason": "not_worktree"})


@contextlib.contextmanager
def final_slot(p, cfg) -> Iterator[tuple[int, str]]:
    """마무리 full 의 슬롯(5.10.7): claim_final → 슬롯 잠금(nowait) → 폴더가 없으면 worktree add, 있으면 기준 HEAD 로
    `git switch --detach` → setup(있으면. 실패면 setup_failed, teardown 은 돌리지 않는다) → 블록(full) → teardown(있으면,
    결과는 쓰지 않는다. 블록이 예외로 끝나도 돈다). 끝나면 늘 free_final. 폴더가 자기 worktree 가 아니면 git·setup 을 부르지
    않고, 커밋 안 된 변경이나 끝나지 않은 병합이 있으면 switch 하지 않고, 슬롯을 태스크 없는 dirty 로 두고 slot_dirty 다.
    setup 뒤에도 다시 본다(아니면 full·teardown 없이 같은 slot_dirty). 블록 뒤 teardown 전에도 다시 본다: full 이 .git 을
    지웠으면 teardown 의 git 이 메인 저장소를 잡는다. 아니면 teardown 없이 dirty 로 두고, 블록이 끝났으면 slot_dirty(그
    폴더에서 돈 full 결과는 부르는 쪽이 기록하지 않는다), 블록이 예외로 끝났으면 그 예외를 그대로 올린다. teardown 뒤에는
    git 을 부르지 않으므로 보지 않는다(다음에 그 슬롯을 쓰는 준비·마무리 full 이 git 전에 본다)."""
    n, base = claim_final(p, cfg)
    try:
        with slot_lock(p, n, nowait=True):
            top = folder(p, n)
            if not top.exists():
                gitio.worktree_add(p.root, top, base)
            elif not own_worktree(top):
                _final_not_worktree(p, n, "")
            else:
                # 준비(5.10.3 의 2)와 같은 검사: switch --detach 는 충돌하지 않는 변경을 들고 가서 full 이 슬롯에만 있는
                # 변경으로 거짓 통과하거나, 충돌하는 변경이면 switch 가 실패한다
                files = gitio.dirty(top, ["."])
                if files or gitio.merge_head(top):
                    _final_dirty(p, n)
                    shown = ", ".join(show(f) for f in files[:5]) or "끝나지 않은 병합(MERGE_HEAD)"
                    raise HteamError("slot_dirty", f"slot-{n} 폴더에 커밋 안 된 변경이 있어 마무리 full 을 돌리지 않았다: "
                                     f"{shown}", CONFLICT, f"사용자가 버려도 된다고 하면 hteam slot reset {n}",
                                     data={"slot": n, "kind": "slot_dirty", "files": files[:DIRTY_SHOWN]})
                gitio.switch_detach(top, base)
            if cfg.workspace.setup:
                result = run_hook(p, cfg, n, "setup", None)
                if not own_worktree(top):  # setup 이 .git 을 지웠다: full 의 git 조회가 메인 저장소를 본다
                    _final_not_worktree(p, n, "setup 뒤 ")
                if result["status"] != "passed":
                    raise _setup_error(n, result)
            try:
                yield n, base
            except BaseException:  # setup 을 했으면 full 이 실패해도 정리한다. 블록의 예외는 그대로 올린다
                if own_worktree(top):
                    run_hook(p, cfg, n, "teardown", None)
                else:  # full 이 .git 을 지웠다: teardown 의 git(reset 등)이 메인 저장소를 잡는다
                    _final_dirty(p, n)
                raise
            if not own_worktree(top):
                _final_not_worktree(p, n, "full 뒤 ", "마무리 full 결과를 기록하지 않고 teardown 도 돌리지 않았다")
            run_hook(p, cfg, n, "teardown", None)
    finally:
        free_final(p, n)


# --- status(5.10.8) ---

def status_view(p, cfg) -> dict:
    """`hteam status` 의 workspace: 1–slots 와 기록에 있는 번호의 {n, state, task, branch}, 번호 순. slots.json 을 읽지 못하면
    bad_slots_file 을 그대로 올린다(부르는 쪽이 경고로 바꾼다)."""
    data = load(p)
    numbers = sorted(set(range(1, cfg.workspace.slots + 1)) | {int(k) for k in data["slots"]})
    rows = []
    for n in numbers:
        rec = entry(data, n)
        rows.append({"n": n, "state": rec["state"], "task": rec["task"], "branch": rec["branch"]})
    return {"mode": "worktree", "slots": rows}


# --- CLI ---

def _cmd_prepare(args) -> dict:
    from .paths import find_project  # 이 모듈은 paths 를 위에서 가져오지 않는다(모듈 설명)
    p = find_project(args.root)
    roles.require_drive(p)
    state.check_id(args.task)
    cfg = config.load(p)
    if not cfg.workspace.on:
        raise _workspace_off()
    return prepare(p, cfg, args.task)


def _cmd_release(args) -> dict:
    """관제 자식(설계 8.8): 관제 밖에서 부르면 drive_only."""
    from .paths import find_project  # 이 모듈은 paths 를 위에서 가져오지 않는다(모듈 설명)
    p = find_project(args.root)
    roles.require_drive(p)
    state.check_id(args.task)
    cfg = config.load(p)
    if not cfg.workspace.on:
        raise _workspace_off()
    return release(p, cfg, args.task)


def _cmd_reset(args) -> dict:
    """큐 명령(7.1, 5.10.8): 관제(와 자식)에서는 바로, 메인에서는 모드·번호 검사 뒤 요청 큐."""
    from . import queue  # queue 가 이 모듈을 쓴다
    from .paths import find_project  # 이 모듈은 paths 를 위에서 가져오지 않는다(모듈 설명)
    p = find_project(args.root)
    cfg = config.load(p)
    value = int(args.slot) if args.slot.isascii() and args.slot.isdigit() else args.slot
    return queue.route(p, "slot reset", {"slot": value}, lambda req: reset(p, cfg, args.slot),
                       check=lambda: check_reset(cfg, args.slot))


def register(sub) -> None:
    slot = sub.add_parser("slot")
    ssub = slot.add_subparsers(dest="slot_cmd", required=True, parser_class=slot.__class__)
    s = ssub.add_parser("prepare")
    s.add_argument("task")
    s.set_defaults(func=_cmd_prepare)
    s = ssub.add_parser("release")
    s.add_argument("task")
    s.set_defaults(func=_cmd_release)
    s = ssub.add_parser("reset")
    s.add_argument("slot")
    s.set_defaults(func=_cmd_reset)
