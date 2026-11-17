"""생존 판정(설계 10장)과 observed 감시(설계 9장: blocked·error·idle·exited·lost, 13.6: not_started, 16.7·16.8: Stop 기록의
백그라운드 일로 idle 넘기기, relay_failed)."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

from . import hcio, relay

# 세션 기록이 있는 Claude 워커의 idle 을 그 turn 의 Stop 기록이 올 때까지 미루는 상한(초, 설계 16.7). 시험은
# HORCH_TEST_IDLE_RECORD_GRACE_S 로 줄인다
IDLE_RECORD_GRACE_S = 10


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


def idle_turn(info: dict | None, start_turn: int | None = None) -> int | None:
    """done 없이 턴을 마친 워커의 turn 번호(설계 9장 observed idle). 아니면 None.

    상태 idle 또는 done(아무도 보지 않는 Claude 는 done 에 머문다)이고 turn 이 start_turn(입력을 보내기 직전의 turn,
    새 터미널은 None 이라 0)보다 커야 한다(설계 13.6). turn 이 없거나 기준선 그대로면 이 Dispatch 의 턴 전이므로
    사건이 아니다. 판정 live 와 active 는 호출자가 본다.
    """
    if status_word(info) not in ("idle", "done"):
        return None
    turn = info.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int) or turn <= (start_turn or 0):
        return None
    return turn


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


def probe(terminal: str | None, expected_argv: list[str] | None,
          timeout: float | None = None) -> tuple[str, dict | None]:
    """timeout 은 hc get 하나의 시간 제한(초, None 이면 hcio 기본). 넘기면 모름(unverifiable)."""
    if not terminal:
        return "unverifiable", None
    try:
        info = hcio.get(terminal, timeout=timeout)
    except hcio.HcFailure:
        return "unverifiable", None
    return verdict(info, expected_argv), info


def loads_argv(text: str | None) -> list[str] | None:
    return json.loads(text) if text else None


def expected_argv(row) -> list[str] | None:
    """생존 판정이 견줄 argv(설계 13.6): 고정 터미널의 terminal_argv 가 있으면 그것, 없으면 launch_argv."""
    return loads_argv(row["terminal_argv"] or row["launch_argv"])


def _epoch(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def not_started(store, row, info: dict | None, now_ts: float | None = None) -> bool:
    """--terminal 로 넣은 입력이 시작되지 않았나(설계 13.6). 보낸 뒤 NOT_STARTED_S 동안 turn 이 start_turn 그대로이고
    상태 idle·done 이며 이 Dispatch 의 워커 명령(seen_at)도 보낸 메시지도 없으면 True."""
    from .persist import NOT_STARTED_S  # persist 가 이 모듈을 import 하므로 여기서 가져온다
    if not row["persistent"] or row["launch_argv"] is not None or row["state"] != "active":
        return False
    delivery = json.loads(row["delivery"]) if row["delivery"] else {}
    since = _epoch(delivery.get("at") or row["created_at"])
    if (time.time() if now_ts is None else now_ts) - since < NOT_STARTED_S:
        return False
    if status_word(info) not in ("idle", "done") or info.get("turn") != (row["start_turn"] or 0):
        return False
    cur = store.one("SELECT seen_at, (SELECT COUNT(*) FROM messages m WHERE m.dispatch_id = d.id "
                    "AND m.sender = 'dispatch:' || d.id) AS sent FROM dispatches d WHERE d.id=?", (row["id"],))
    return cur["seen_at"] is None and not cur["sent"]


def idle_record_grace_s() -> float:
    try:
        return float(os.environ.get("HORCH_TEST_IDLE_RECORD_GRACE_S", IDLE_RECORD_GRACE_S))
    except ValueError:
        return float(IDLE_RECORD_GRACE_S)


def idle_hold(home, row, turn: int) -> str | None:
    """그 turn 의 idle 을 내지 않을 까닭(설계 16.7). observe_one 과 worker-list 가 같이 쓴다.

    "background": 그 turn 을 끝낸 Stop 기록(turn 이 같은 마지막 것)이 그 Dispatch 의 created_at 과 같거나 뒤이고 그
    background 에 끝나지 않은 일(relay.running_background: status 가 없거나 running·pending)이 있다. 백그라운드 일을 기다리는
    워커다(내지 않는다). 끝난 일(completed·failed·killed 등)만 남은 기록은 붙잡지 않는다(최종 리뷰 I1).
    "no_record": 그 기록이 없고(turn 이 null 인 기록·앞 Dispatch 의 기록은 없는 것과 같다) 그 터미널에 세션 기록이 있는 Claude
    Dispatch 다. Stop 훅이 아직 기록을 남기지 않았을 수 있다(observe_one 은 기다리고 목록은 낸다).
    None: 낸다(기록에 끝나지 않은 백그라운드 일이 없거나, 세션 기록이 없는 워커: Codex, 0.5.0 전 Claude, 훅이 돌지 않은
    세션)."""
    terminal = row["terminal"]
    stop = relay.stop_for_turn(home, terminal, turn)
    if stop is not None and isinstance(stop.get("at"), str) and stop["at"] >= row["created_at"]:
        return "background" if relay.running_background(stop["background"]) else None
    if row["agent"] == "claude" and relay.record(home, terminal) is not None:
        return "no_record"
    return None


def _waited(store, dispatch_id: str, turn: int) -> bool:
    """그 turn 의 Stop 기록을 처음 기다리기 시작한 때(observations 의 idle_wait)부터 idle_record_grace_s 가 지났다."""
    seen = store.one("SELECT created_at FROM observations WHERE dispatch_id=? AND kind='idle_wait' AND key=?",
                     (dispatch_id, str(turn)))
    return seen is not None and time.time() - _epoch(seen["created_at"]) >= idle_record_grace_s()


def observe_one(store, run_id: str, dispatch_id: str, timeout: float | None = None) -> list[int]:
    """active Dispatch 하나를 판정해 새 사건이면 observed 메시지를 Run 메일함에 쓴다(설계 9장).

    0.5.0(설계 16.7·16.8): 판정 live 이고 그 터미널의 세션 기록이 write_failed 면 relay_failed(key 는 그 Claude pid)를 한 번
    내고, hc 상태에서 나오는 사건(blocked·error·idle·not_started)은 내지 않는다(hc 상태가 옛것이다). idle 은 idle_hold 가
    background 면 내지 않고 observations 에도 넣지 않는다(다음 판정이 다시 본다). no_record 면 observations 에 idle_wait(처음
    본 시각, 메시지 없음)를 남기고 IDLE_RECORD_GRACE_S 가 지난 뒤에 낸다."""
    from . import mailbox  # mailbox 가 이 모듈을 import 하므로 여기서 가져온다
    from .ids import now
    row = store.one("SELECT * FROM dispatches WHERE id=?", (dispatch_id,))
    if not row or row["state"] != "active":
        return []
    verdict_, info = probe(row["terminal"], expected_argv(row), timeout)
    word = status_word(info)
    events = []
    failed = relay.record(store.home, row["terminal"]) if verdict_ == "live" else None
    if failed is not None and failed["decided"] != "write_failed":
        failed = None
    if failed is not None:
        # 대리 보고 쓰기가 실패했다(설계 16.8): hc 에 남은 상태는 옛것이라 그 낱말로 사건을 내지 않는다
        events.append(("relay_failed", str(failed["pid"])))
    elif verdict_ == "live":
        if word in ("blocked", "error"):
            turn = info.get("turn")
            if turn is not None:  # turn 이 없으면 같은 사건을 가를 key 가 없다. 모름이므로 보내지 않는다
                events.append((word, str(turn)))
        idle_at = idle_turn(info, row["start_turn"])
        if idle_at is not None:
            # done 없이 턴을 마쳤다. key 가 turn 이라 턴마다 한 번만 보낸다(같은 턴의 idle·done 은 한 사건).
            # 그 턴을 끝낸 Stop 에 백그라운드 일이 있으면 내지 않고, 그 기록을 기다리는 동안은 idle_wait 만 남긴다(16.7)
            hold = idle_hold(store.home, row, idle_at)
            if hold is None or (hold == "no_record" and _waited(store, dispatch_id, idle_at)):
                events.append(("idle", str(idle_at)))
            elif hold == "no_record":
                events.append(("idle_wait", str(idle_at)))
        if not_started(store, row, info):
            # 넣은 입력이 시작되지 않았다(설계 13.6). horch 는 다시 보내지 않는다. 호출자가 정한다
            events.append(("not_started", str(row["start_turn"])))
    if verdict_ in ("exited", "lost"):
        events.append((verdict_, verdict_))
    created: list[int] = []
    for kind, key in events:
        with store.tx():
            # hc 판정은 트랜잭션 밖에서 했다. 그 사이 done·abandon 으로 바뀌었으면 옛 판정을 쓰지 않는다(10장 원칙)
            cur = store.one("SELECT state, terminal FROM dispatches WHERE id=?", (dispatch_id,))
            if cur["state"] != "active" or cur["terminal"] != row["terminal"]:
                return created
            ins = store.run("INSERT OR IGNORE INTO observations(dispatch_id, kind, key, created_at) VALUES (?,?,?,?)",
                            (dispatch_id, kind, key, now()))
            if ins.rowcount and kind != "idle_wait":  # idle_wait 은 처음 본 시각만 남긴다(메시지 없음, 설계 16.7)
                fields = {"dispatch": dispatch_id, "kind": kind, "key": key, "terminal": row["terminal"], "status": word}
                if kind == "not_started":
                    fields.update(start_turn=row["start_turn"], turn=info.get("turn"),
                                  delivery=json.loads(row["delivery"]) if row["delivery"] else None)
                if kind == "relay_failed":  # 설계 16.8: 세션 기록의 pid·last·write_failures
                    fields.update(pid=failed["pid"], last=failed.get("last"), write_failures=failed["write_failures"])
                body = json.dumps(fields, ensure_ascii=False)
                created.append(mailbox.post(store, run_id=run_id, mailbox=f"run:{run_id}", sender="horch",
                                            type="observed", subject=f"{kind} {dispatch_id}", body=body,
                                            dispatch_id=dispatch_id))
    return created


def observe(store, run_id: str) -> list[int]:
    """Run 의 active Dispatch 를 모두 판정한다. 소유자의 대기는 시간 예산이 있는 workers.Sweep 을 쓴다."""
    created: list[int] = []
    for row in store.all("SELECT id FROM dispatches WHERE run_id=? AND state='active' ORDER BY created_at, id",
                         (run_id,)):
        created += observe_one(store, run_id, row["id"])
    return created
