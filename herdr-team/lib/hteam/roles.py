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


# 관제만 하는 명령을 관제 밖에서 불렀을 때(설계 7.1 원문)
DRIVE_ONLY_MESSAGE = ("이 명령은 관제(hteam drive)가 스스로 한다. 메인이 관제 큐로 넣는 명령은 start, start-ready, fix, accept, "
                      "drop, review --retry, design-decide, scope, agent reset, test-confirm 이다")


def drive_env(p) -> bool:
    """관제 판별(설계 8.2): HTEAM_ROLE=drive 이고 $HC_TERMINAL_ID 가 run.json 의 drive_terminal 이다. 관제가 띄운 자식은
    환경을 물려받아 같이 관제다. nonce 는 관제가 시작할 때만 본다. run.json 을 읽지 못하면 bad_run_file(exit 1)."""
    if os.environ.get("HTEAM_ROLE") != "drive":
        return False
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        return False
    from .outbox import _run  # outbox 가 이 모듈을 import 하므로 여기서 가져온다
    return term == _run(p).get("drive_terminal")


def require_drive(p) -> None:
    if not drive_env(p):
        raise HteamError("drive_only", DRIVE_ONLY_MESSAGE, DENIED, "메인은 큐 명령으로 관제에 넘긴다")


LABEL_BUDGET = 5.0  # 훅 시간 안에 끝나게 hc 라벨 확인(조상 포함)에 쓰는 전체 시간(초)


def detect(p) -> tuple[str | None, bool]:
    """(역할, 확실한가). 역할: main·reviewer·worker:<직무>·worker(hteam 제목이 아닌 horch 워커).

    워커는 $HC_TERMINAL_ID 가 horch 의 launching·active Dispatch 터미널인 것으로 안다(`horch status` 의 dispatch).
    horch 를 부르지 못하거나 태스크를 모르면 (None, False): 캐시하지 않고 다음에 다시 본다.
    관제는 Claude 세션이 아니다(설계 9.4): HTEAM_ROLE 이 있는 세션(어떤 값이든)과 run.json 의 관제 터미널은 모름이다.
    메인은 require_main 과 같은 근거로 가린다: horch Run 소유자는 메인이 아니고(모름), 끝난 Dispatch 의 워커처럼 horch
    status 가 모르는 터미널은 hc 라벨(자신과 parent 조상의 horch.dispatch·hteam.role)로 가린다.
    """
    if os.environ.get("HTEAM_ROLE"):
        return None, False
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        return "main", True
    from .horch import Horch
    from .util import read_json
    run = read_json(p.run_file, None)
    if isinstance(run, dict) and term == run.get("drive_terminal"):
        return None, False
    try:
        code, data = Horch(p.horch_home).call("status", timeout=8)
    except HteamError:
        return None, False
    if code != 0 or not data.get("ok"):
        return None, False
    dispatch = data.get("dispatch")
    if isinstance(dispatch, dict):
        info = parse_title(dispatch.get("title") or "")
        if info is None:
            return "worker", True
        if info["kind"] == "review":
            return "reviewer", True
        task = read_json(p.state_path(info["task"]), None)
        role = task.get("role") if isinstance(task, dict) else None
        return (f"worker:{role}", True) if isinstance(role, str) and role else (None, False)
    if dispatch or data.get("run"):
        return None, False  # 모르는 모양이거나 Run 소유자(관제 환경 없이 Run 에 묶인 터미널)
    labeled = _label_role(term)
    if labeled == "worker":
        return "worker", True
    if labeled == "main":
        return "main", True
    return None, False


def _label_role(term: str) -> str | None:
    """이 터미널과 hc parent 조상의 라벨로 본 역할(require_main 과 같은 규칙).

    worker(horch.dispatch: horch 가 띄운 워커 터미널), drive(hteam.role=drive: hteam up 이 띄운 관제 터미널),
    main(둘 다 없고 조상을 끝까지 봤다). hc 실패·순환·너무 깊음·시간 초과는 None(모름)."""
    import time

    from . import herdr
    from .outbox import PARENT_DEPTH, _parent_ref
    deadline = time.monotonic() + LABEL_BUDGET
    node, seen = term, {term}
    for depth in range(PARENT_DEPTH + 1):
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        try:
            info = herdr.get(node, timeout=min(3.0, left))
        except HteamError:
            return None
        labels = info.get("labels") if isinstance(info.get("labels"), dict) else {}
        if labels.get("horch.dispatch"):
            return "worker"
        if labels.get("hteam.role") == "drive":
            return "drive"
        parent = _parent_ref(info.get("parent"))
        if not parent:
            return "main"
        if parent in seen or depth == PARENT_DEPTH:
            return None
        seen.add(parent)
        node = parent
    return None
