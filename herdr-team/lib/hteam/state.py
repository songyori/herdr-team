"""태스크 상태 파일(설계 5.3). 태스크마다 flock, 이전 상태 확인, 임시 파일 + os.replace. 프로젝트 잠금(13장).

잠금 순서는 늘 프로젝트 잠금(state/lock) → 태스크 잠금(state/tasks/T-xxx.lock)이다. 읽기는 잠금 없이 한다.
"""
from __future__ import annotations

import contextlib
import json
import re
from typing import Iterator

from .errors import CONFLICT, USAGE, HteamError
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


def load(p, tid: str) -> dict | None:
    return read_json(p.state_path(tid), None)


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
    """없을 때만 pending 으로 만든다. 있으면 그대로 돌려준다."""
    p.ensure_state()
    with flock(p.task_states / f"{tid}.lock"):
        st = load(p, tid)
        if st is None:
            st = new(tid, role)
            save(p, st)
        return st


def move(st: dict, to: str, event: str, **info) -> None:
    """전이와 시각을 history 에 남긴다. 리뷰 변조 검사가 이 시각으로 리뷰 중 시작된 태스크를 찾는다."""
    st["history"].append({"at": now(), "from": st["status"], "to": to, "event": event, **info})
    st["status"] = to


def all_states(p) -> list[dict]:
    if not p.task_states.is_dir():
        return []
    found = []
    for path in p.task_states.glob("T-*.json"):
        if ID_RE.fullmatch(path.stem):
            st = read_json(path, None)
            if isinstance(st, dict):
                found.append(st)
    return sorted(found, key=lambda s: id_number(s["id"]))


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
