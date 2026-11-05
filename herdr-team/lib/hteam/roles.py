"""호출자 역할(설계 8.3·9.4). 실수 방지용이지 보안 경계가 아니다."""
from __future__ import annotations

import os
import re

from .errors import DENIED, HteamError

TITLE_RE = re.compile(r"^(T-\d{3,}) r(\d+) (작업|리뷰 a(\d+))$")


def work_title(tid: str, rnd: int) -> str:
    return f"{tid} r{rnd} 작업"


def review_title(tid: str, rnd: int, attempt: int) -> str:
    return f"{tid} r{rnd} 리뷰 a{attempt}"


def parse_title(title: str) -> dict | None:
    """horch Task 제목(실행 키) → {task, round, kind, attempt}. hteam 제목이 아니면 None."""
    m = TITLE_RE.match(title or "")
    if not m:
        return None
    review = m.group(3) != "작업"
    return {"task": m.group(1), "round": int(m.group(2)), "kind": "review" if review else "work",
            "attempt": int(m.group(4)) if review else None}


def coordinator_env(p) -> bool:
    """HTEAM_ROLE=coordinator 이고 HTEAM_LAUNCH 가 run.json 의 pending_launch.nonce 와 같다(hteam up 이 띄운 터미널)."""
    if os.environ.get("HTEAM_ROLE") != "coordinator":
        return False
    nonce = os.environ.get("HTEAM_LAUNCH")
    from .outbox import _run  # outbox 가 이 모듈을 import 하므로 여기서 가져온다
    launch = _run(p).get("pending_launch")  # run.json 을 읽지 못하면 bad_run_file(exit 1)
    return bool(nonce) and isinstance(launch, dict) and nonce == launch.get("nonce")


def require_coordinator(p) -> None:
    if not coordinator_env(p):
        raise HteamError("not_coordinator", "이 명령은 코디네이터만 부른다", DENIED,
                         "hteam up 이 띄운 코디네이터 터미널에서 실행한다")
