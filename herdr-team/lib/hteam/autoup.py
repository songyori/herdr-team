"""코디네이터 자동 부활(설계 9.5): 메인 세션 훅(SessionStart·UserPromptSubmit)이 코디네이터 터미널을 확인하고, 확실히
죽었을 때만(exited·lost) `hteam up` 을 분리된 백그라운드 프로세스로 실행한다. 프롬프트를 막지 않고 bind 를 기다리지 않는다.

훅 제한(15초) 안에 끝나도록 바깥 프로그램(ps·hc·sh)은 모두 훅 시작 + HOOK_DEADLINE_S 까지 남은 시간을 시간 제한으로
받는다. 띄우기 전에 시간이 모자라면 아무것도 쓰지 않고 멈춘다(다음 프롬프트가 바로 다시 확인한다). 생존 판정은 up·horch 와
같은 herdr.probe 다(hc 가 모르는 터미널, 조회 실패는 확인 불가라 띄우지 않는다). 두 번 띄우는 것은 up 의 run.json 잠금이
막으므로 이 모듈의 상태 파일은 잠그지 않고 원자적으로만 쓴다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from . import config, herdr, outbox, procs
from .errors import HteamError
from .paths import PLUGIN_ROOT
from .util import age_seconds, now, read_json, write_json

CHECK_INTERVAL_S = 60  # UserPromptSubmit 의 확인 간격(SessionStart 는 간격과 관계없다)
RETRY_WINDOW_S = 600  # 자동으로 띄운 뒤 이 안에 다시 죽으면 FAILED(다시 띄우지 않는다)
PID_STALE_S = 60  # auto-up.pid 를 쓴 지 이 안이고 그 프로세스가 살아 있으면 자동 실행이 진행 중이다
PROBE_TIMEOUT_S = 3
SPAWN_WAIT_S = 5
PS_TIMEOUT_S = 5  # procs 의 ps 기본 제한과 같다
HOOK_START_BUDGET_S = 4  # 훅이 시작한 지 이만큼 지났으면(역할 판별이 오래 걸렸다) 이번 확인을 건너뛴다
HOOK_DEADLINE_S = 12  # 훅 시작부터 바깥 프로그램을 부를 수 있는 마지막 시각(15초 훅 제한 안에 끝나게)
MIN_LEFT_S = 1  # 띄우기 전 단계는 남은 시간이 이보다 적으면 멈춘다
STARTING_S = 180  # coord.STARTING_S 와 같다(띄운 지 이 안이면 시작 중이다)

PREFIX = "herdr-team: "
REVIVED = (PREFIX + "코디네이터가 꺼져 있어 자동으로 다시 띄우는 중이다. 답변 첫 줄에 사용자에게 이 사실을 한 줄로 알린다. "
           "요청은 평소대로 hteam tell 로 넘긴다(Run 메일함에 쌓였다가 새 코디네이터가 bind 하면 처리된다). watch 가 꺼져 "
           "있으면 띄우고, 답하지 않은 질문이 있으면 hteam reask 로 다시 보여 준다.")
UNKNOWN = (PREFIX + "코디네이터가 살아 있는지 확인하지 못했거나 자동으로 다시 띄우지 못했다(hc 조회 실패·시간 초과·터미널 없음, "
           "기록: .herdr-team/state/auto-up.log). 답변 첫 줄에 사용자에게 한 줄로 알리고 팀 탭의 코디네이터 pane 을 확인해 "
           "달라고 한다. 끝났다고 확인되면 /herdr-team:up 을 실행한다.")
NO_HANDLE = (PREFIX + "코디네이터 실행 기록이 불확실하다(run.json 에 코디네이터 터미널이 없다). 답변 첫 줄에 사용자에게 한 줄로 "
             "알리고 /herdr-team:up 결과를 확인한다.")
DISABLED = (PREFIX + "코디네이터가 꺼져 있다(config.toml 의 [coordinator] auto_up = false). 답변 첫 줄에 사용자에게 한 줄로 "
            "알리고 /herdr-team:up 을 안내한다.")
FAILED = (PREFIX + "자동으로 다시 띄운 코디네이터가 10분 안에 다시 꺼졌거나 뜨지 못했다(기록: .herdr-team/state/auto-up.log). "
          "답변 첫 줄에 사용자에게 한 줄로 알리고, 그 기록으로 원인을 확인한 뒤 /herdr-team:up 을 실행하도록 안내한다. "
          "10분 동안은 자동으로 다시 띄우지 않는다.")


def within(stamp, seconds: float) -> bool:
    """0 <= 흐른 초 < seconds. 없음·해석 실패·미래 시각은 안이 아니다."""
    age = age_seconds(stamp) if isinstance(stamp, str) else None
    return age is not None and 0 <= age < seconds


def _clock() -> float:
    """훅 시작 시각(HOOK_START)과 같은 단조 시계. 시험이 가상 시계로 바꾼다(subprocess 의 시간 제한은 건드리지 않는다)."""
    return time.monotonic()


def _left(deadline: float) -> float:
    return deadline - _clock()


def _record(p) -> dict:
    """auto-up.json. 없거나 JSON 객체가 아니면 빈 기록(확인할 때가 된다)."""
    rec = read_json(p.auto_up, {})
    return rec if isinstance(rec, dict) else {}


def _run(p) -> dict | None:
    """자격이 있으면 run.json. bind 한 적이 없거나(run_id 없음) 읽지 못하거나 setup-mode 면 None."""
    if p.setup_mode.exists():
        return None
    try:
        run = outbox._run(p)
    except HteamError:  # bad_run_file: status·up 이 알린다
        return None
    return run if run.get("run_id") else None


def _in_progress(p, deadline: float) -> bool | None:
    """앞서 띄운 hteam up 이 아직 도는가. auto-up.pid 를 쓴 지 PID_STALE_S 안일 때만 ps 로 본다. 시간이 모자라면 None."""
    try:
        written = time.time() - p.auto_up_pid.stat().st_mtime
    except OSError:
        return False
    rec = read_json(p.auto_up_pid, None)
    if not (0 <= written < PID_STALE_S) or not isinstance(rec, dict):
        return False
    if _left(deadline) < MIN_LEFT_S:
        return None
    return procs.record_alive(rec, timeout=min(PS_TIMEOUT_S, _left(deadline)))


def decide(p, deadline: float) -> tuple[str | None, str | None] | None:
    """(할 일 "spawn" 또는 None, 안내 문구 또는 None). 시간이 모자라면 None. 파일을 쓰지 않고 hc 조회는 많아야 한 번이다."""
    run = _run(p)
    if run is None:
        return None, None
    try:
        auto_up = config.load(p).auto_up
    except HteamError:  # 설정 오류는 status·up 이 알린다
        return None, None
    if within(run.get("launched_at") or (run.get("pending_launch") or {}).get("at"), STARTING_S):
        return None, None
    busy = _in_progress(p, deadline)
    if busy is None:
        return None
    if busy:
        return None, None
    term = run.get("coordinator_terminal")
    if not term:
        return None, NO_HANDLE
    if _left(deadline) < MIN_LEFT_S:
        return None
    verdict = herdr.probe(term, run.get("coordinator_argv"), timeout=min(PROBE_TIMEOUT_S, _left(deadline)))
    if verdict == "live":
        return None, None
    if verdict not in ("exited", "lost"):
        return None, UNKNOWN
    if within(_record(p).get("spawned_at"), RETRY_WINDOW_S):
        return None, FAILED
    return ("spawn", REVIVED) if auto_up else (None, DISABLED)


def spawn_up(p, deadline: float) -> bool:
    """`<플러그인>/bin/hteam --root <루트> up` 을 분리 실행한다(sh 가 백그라운드로 띄우고 pid 를 찍고 바로 끝난다). 출력은
    auto-up.log 에 덧붙인다. pid 를 받으면 auto-up.pid 에 {pid, started} 를 쓰고 True. 환경은 훅의 것(메인의
    $HC_TERMINAL_ID 포함)에 로그 경로만 더한다."""
    p.ensure_state()
    with p.auto_up_log.open("a", encoding="utf-8") as fh:
        fh.write(f"--- {now()} hteam up (자동)\n")
    argv = ["/bin/sh", "-c", '"$0" "$@" </dev/null >>"$HTEAM_AUTO_UP_LOG" 2>&1 & echo $!',
            sys.executable, str(PLUGIN_ROOT / "bin" / "hteam"), "--root", str(p.root), "up"]
    try:
        proc = subprocess.run(argv, cwd=str(p.root), env={**os.environ, "HTEAM_AUTO_UP_LOG": str(p.auto_up_log)},
                              capture_output=True, text=True, start_new_session=True,
                              timeout=min(SPAWN_WAIT_S, max(_left(deadline), 0)))
        pid = int(proc.stdout.strip().split("\n")[-1])
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    left = _left(deadline)  # 띄운 뒤에는 멈추지 않는다. 시간이 모자라면 시작 시각 없이 남긴다
    started = procs.start_time(pid, timeout=min(PS_TIMEOUT_S, left)) if left >= MIN_LEFT_S else None
    write_json(p.auto_up_pid, {"pid": pid, "started": started})
    return True


def check(p, force: bool, started: float) -> str | None:
    """설계 9.5 의 확인. 안내 문구(메인 모델에게 넘길 것) 또는 None. started 는 훅 시작 시각(time.monotonic).

    force(SessionStart)는 간격과 같은 안내 줄이기를 보지 않는다. 자격이 없거나, 훅이 시작한 지 HOOK_START_BUDGET_S 가
    지났거나, 간격 안이거나, 시간이 모자라면 아무 파일도 쓰지 않는다. 확인을 마치면 auto-up.json 을 한 번에 쓴다. 판정·띄우기가
    예외로 끝나면 checked_at 만 쓰려 하고(실패하면 넘어간다) 예외를 다시 낸다(훅이 기록한다)."""
    if _run(p) is None or _clock() - started >= HOOK_START_BUDGET_S:
        return None
    rec = _record(p)
    if not force and within(rec.get("checked_at"), CHECK_INTERVAL_S):
        return None
    deadline = started + HOOK_DEADLINE_S
    try:
        result = decide(p, deadline)
        if result is None:
            return None
        action, notice = result
        spawned = False
        if action == "spawn":
            if _left(deadline) < MIN_LEFT_S:
                return None
            spawned = spawn_up(p, deadline)
            if not spawned:
                notice = UNKNOWN
    except Exception:
        try:
            write_json(p.auto_up, {**rec, "checked_at": now()})
        except OSError:
            pass
        raise
    repeat = not spawned and notice == rec.get("notice")
    out = {**rec, "checked_at": now()}
    if spawned:
        out["spawned_at"] = out["checked_at"]
    if notice is None:
        out.pop("notice", None)
    else:
        out["notice"] = notice
    write_json(p.auto_up, out)
    if notice is None or (repeat and not force):
        return None
    return notice
