"""생존 판정(설계 10장). observe 는 Task 10 에서 더한다."""
from __future__ import annotations

import json

from . import hcio


def status_word(info: dict | None) -> str | None:
    """hc 가 보고한 에이전트 상태 낱말. get 은 {"state": ...}, ls 는 문자열을 준다."""
    if not info:
        return None
    status = info.get("status")
    if isinstance(status, dict):
        return status.get("state")
    if isinstance(status, str):
        return status
    return None


def verdict(info: dict | None, expected_argv: list[str] | None) -> str:
    if info is None:
        return "unverifiable"
    state = info.get("state")
    if state == "finished":
        return "exited"
    if state != "live":
        return "unverifiable"
    if info.get("reason") == "stopped_by_restart":
        return "lost"
    if expected_argv is not None:
        argv = info.get("argv")
        if argv is None:
            # argv 를 알 수 없으면 터미널이 끝났다고 단정하지 못한다(10장): 모름.
            return "unverifiable"
        if argv != expected_argv:
            return "lost"
    return "live"


def probe(terminal: str | None, expected_argv: list[str] | None) -> tuple[str, dict | None]:
    if not terminal:
        return "unverifiable", None
    try:
        info = hcio.get(terminal)
    except hcio.HcFailure:
        return "unverifiable", None
    return verdict(info, expected_argv), info


def loads_argv(text: str | None) -> list[str] | None:
    return json.loads(text) if text else None
