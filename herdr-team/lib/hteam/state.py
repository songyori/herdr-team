"""태스크 상태 파일(설계 5.3). 태스크마다 flock, 이전 상태 확인, 임시 파일 + os.replace. 프로젝트 잠금(13장).

잠금 순서는 늘 프로젝트 잠금(state/lock) → 태스크 잠금(state/tasks/T-xxx.lock)이다. 읽기는 잠금 없이 한다.
"""
from __future__ import annotations

import contextlib
import json
import re
from typing import Iterator

from .errors import CONFLICT, FAIL, USAGE, HteamError
from .util import flock, now, read_json, write_atomic

STATUSES = ("pending", "working", "launch_failed", "reviewing", "approved", "changes", "awaiting_user", "done",
            "dropped")
LOCKING = frozenset({"working", "launch_failed", "reviewing", "approved", "changes", "awaiting_user"})
CLOSED = frozenset({"done", "dropped"})
ID_RE = re.compile(r"T-(\d{3,})")


def id_number(tid: str) -> int:
    return int(tid[2:])


def new(tid: str, role: str) -> dict:
    return {"id": tid, "role": role, "status": "pending", "round": 0, "base": None, "owns": [], "rounds": [],
            "launcher": None, "history": [{"at": now(), "from": None, "to": "pending", "event": "create"}],
            "note": None, "updated_at": now()}


@contextlib.contextmanager
def project_lock(p) -> Iterator[None]:
    """owns 잠금 검사와 상태 쓰기를 한 잠금 안에서 한다(설계 13장)."""
    p.ensure_state()
    with flock(p.lock):
        yield


def check_id(tid: str) -> None:
    """경로를 만들기 전에 태스크 ID 모양을 확인한다(`../run` 같은 값 차단)."""
    if not isinstance(tid, str) or not ID_RE.fullmatch(tid):
        raise HteamError("bad_task_id", f"태스크 ID 는 T- 와 숫자 3자리 이상이다: {tid!r}", USAGE)


def _read_state(path, tid: str) -> dict | None:
    """없으면 None. 읽을 수 없거나 JSON 객체가 아니면 bad_state_file(없는 것으로 보지 않는다)."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise _corrupt(path, tid, str(exc)) from None
    try:
        st = json.loads(text)
    except ValueError as exc:
        raise _corrupt(path, tid, f"JSON 이 아니다: {exc}") from None
    if not isinstance(st, dict):
        raise _corrupt(path, tid, "JSON 객체가 아니다")
    return st


def _corrupt(path, tid: str, why: str, exit_code: int = FAIL) -> HteamError:
    return HteamError("bad_state_file", f"{tid} 상태 파일이 손상됐다({path.name}): {why}", exit_code,
                      "파일을 직접 고치거나 치운 뒤 다시 시도한다")


def load(p, tid: str) -> dict | None:
    check_id(tid)
    return _read_state(p.state_path(tid), tid)


def require(p, tid: str) -> dict:
    st = load(p, tid)
    if st is None:
        raise HteamError("unknown_task", f"{tid} 의 상태가 없다", USAGE, "plan apply 또는 task new 로 만든다")
    return st


def save(p, st: dict) -> None:
    st["updated_at"] = now()
    write_atomic(p.state_path(st["id"]), json.dumps(st, ensure_ascii=False, indent=2) + "\n")


def closed_error(st: dict) -> HteamError:
    return HteamError("task_closed", f"{st['id']} 는 {st['status']} 다", CONFLICT, data={"status": st["status"]})


@contextlib.contextmanager
def edit(p, tid: str, expect=None) -> Iterator[dict]:
    """태스크 잠금 아래에서 읽고, 블록이 예외 없이 끝나면 원자적으로 쓴다. expect 가 있으면 이전 상태를 확인한다."""
    check_id(tid)
    p.ensure_state()
    with flock(p.task_states / f"{tid}.lock"):
        st = require(p, tid)
        if expect is not None and st["status"] not in expect:
            if st["status"] in CLOSED:
                raise closed_error(st)
            raise HteamError("bad_state", f"{tid} 는 {st['status']} 다(필요: {', '.join(sorted(expect))})", CONFLICT,
                             data={"status": st["status"]})
        yield st
        save(p, st)


def create(p, tid: str, role: str) -> dict:
    """없을 때만 pending 으로 만든다. 있으면 그대로 돌려준다. 손상된 파일이 있으면 덮어쓰지 않고 exit 3 이다."""
    check_id(tid)
    p.ensure_state()
    with flock(p.task_states / f"{tid}.lock"):
        try:
            st = load(p, tid)
        except HteamError as exc:
            if exc.code == "bad_state_file":
                exc.exit_code = CONFLICT
            raise
        if st is None:
            st = new(tid, role)
            save(p, st)
        return st


def move(st: dict, to: str, event: str, **info) -> None:
    """전이와 시각을 history 에 남긴다. 리뷰 변조 검사가 이 시각으로 리뷰 중 시작된 태스크를 찾는다."""
    st["history"].append({"at": now(), "from": st["status"], "to": to, "event": event, **info})
    st["status"] = to


def state_ids(p) -> list[str]:
    """상태 파일 이름의 ID. 손상된 파일도 센다(번호 재사용 방지)."""
    if not p.task_states.is_dir():
        return []
    return sorted((f.stem for f in p.task_states.glob("T-*.json") if ID_RE.fullmatch(f.stem)), key=id_number)


def all_states(p) -> list[dict]:
    """읽히는 상태만 ID 순으로 돌려준다. 손상됐거나 id 가 파일 이름과 다른 파일은 건너뛴다."""
    found = []
    for tid in state_ids(p):
        st = read_json(p.state_path(tid), None)
        if isinstance(st, dict) and st.get("id") == tid:
            found.append(st)
    return found


def current_round(st: dict) -> dict | None:
    return st["rounds"][-1] if st.get("rounds") else None


def open_attempt(rd: dict | None) -> dict | None:
    """끝나지 않은(결과 없음, 취소 안 됨) 마지막 리뷰 시도."""
    if not rd:
        return None
    for att in reversed(rd.get("reviews", [])):
        if att.get("result") is None and not att.get("canceled"):
            return att
    return None


def latest_attempt(rd: dict | None) -> dict | None:
    """취소되지 않은 마지막 시도(끝났든 아니든)."""
    if not rd:
        return None
    live = [a for a in rd.get("reviews", []) if not a.get("canceled")]
    return live[-1] if live else None
