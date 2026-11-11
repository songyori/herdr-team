"""status(태스크별 next, 설계 8.3·13장)와 관제가 쓰는 Dispatch 찾기(locate)·손볼 행(attention).

0.4.0 에서 코디네이터의 wait·which 와 메시지 주석을 없앴다(관제가 안에서 처리한다, 8.6). status 는 horch 를 부르지 않고
관제가 재확인마다 쓰는 워커 목록 사본(state/drive/workers.json, 8.7)을 읽는다. 메인이 읽는 hint 에는 horch 명령을 넣지
않는다(메인은 horch 를 부르지 않는다, 7.1·9.4)."""
from __future__ import annotations

import json
import time

from . import approval, config, crew, dispatch, drive, outbox, roles, state, tasks, testgate, workspace
from .errors import HteamError
from .horch import Horch
from .paths import SHIM, find_project
from .util import age_seconds, flock, read_json, write_json

LIVE = ("launching", "active")
NO_ROWS = "관제의 워커 목록 사본이 없다(관제가 재확인마다 쓴다)"
DRIVE_ONLY = ("review", "review-finish", "design-review")  # 관제만 하는 next(review 는 --retry 없이, 설계 8.3)
CANCELED_HINT = "앞선 fix·drop 이 끝나지 않았다(실행 키가 취소됐다). 같은 명령을 다시 한다"
QUEUED_HINT = "수정 라운드가 에이전트 대기열에 있다. 에이전트가 비면 관제가 띄운다"  # queued_fix(설계 5.9.5)
# horch.workers._attention 이 내는 값 가운데 실제 상태 보고를 본 것이 아닌 상태: 시작 전·확인 불가·워커가 죽음.
# 이 상태는 정상 관측(attention.json 의 ok)으로 치지 않는다
UNCONFIRMED = frozenset({"no_status", "launching", "launch_failed", "unverifiable",
                         "exited_without_done", "lost_without_done"})


def H(*args: str) -> list[str]:
    return [SHIM, *args]


_fix = tasks.fix_next  # fix 를 권하되 라운드 상한이면 권하지 않는다(이어 붙인 워커의 next 와 같은 판정)


def _round_canceled(rd: dict | None) -> bool:
    """fix·drop 이 이 라운드를 닫는 중이다(취소를 저장한 뒤 멈췄거나 진행 중). review 의 round_canceled 와 같은 기준."""
    return bool(rd) and (bool(rd["work"].get("canceled")) or any(a.get("canceled") for a in rd["reviews"]))


def locate(p, did: str | None, rows: list[dict] | None = None, *, states: list[dict] | None = None) -> dict | None:
    """Dispatch → {task, round, kind, attempt, current, status, recorded, canceled, finished}. 상태 파일에 없으면 horch 제목으로
    찾는다. canceled: 현재 라운드를 fix·drop 이 닫는 중이다. finished: 그 리뷰 시도에 이미 결과가 있다.
    states 를 주면(state.all_states 결과) 상태 파일을 다시 읽지 않는다(메시지마다 읽지 않게)."""
    if not did:
        return None
    if states is None:
        states = state.all_states(p)
    for st in states:
        cur = state.current_round(st)
        for rd in st["rounds"]:
            last = rd is cur
            canceled = last and _round_canceled(rd)
            if rd["work"].get("dispatch") == did:
                return {"task": st["id"], "round": rd["round"], "kind": "work", "attempt": None,
                        "current": last, "status": st["status"], "recorded": True, "canceled": canceled,
                        "finished": False}
            for att in rd["reviews"]:
                if att.get("dispatch") == did:
                    latest = state.latest_attempt(rd)
                    return {"task": st["id"], "round": rd["round"], "kind": "review", "attempt": att["attempt"],
                            "current": last and latest is att, "status": st["status"], "recorded": True,
                            "canceled": canceled, "finished": att.get("result") is not None}
    row = dispatch.row_by_id(rows or [], did)
    info = roles.parse_title(row.get("title")) if row else None
    if not info:
        return None
    # all_states 는 손상된 상태 파일을 뺀다. 그런 태스크는 모르는 것으로 본다
    st = next((s for s in states if s["id"] == info["task"]), None)
    if not st:
        return None
    rd = state.current_round(st)
    same_round = bool(rd) and rd["round"] == info["round"]
    # 같은 horch Task 를 다시 띄우면 이전 Dispatch 도 제목·라운드가 같다. 그 Task 의 최신 시도이고 현재 실행 기록과
    # 어긋나지 않을 때만 현재다(지난 시도의 늦은 observed 가 현재 워커를 정리하는 next 를 만들지 않게)
    newest = dispatch.latest_for_task(rows or [], row["task"])
    current = same_round and newest is not None and newest["id"] == did
    if info["kind"] == "review":
        slot = state.latest_attempt(rd)
        current = current and slot is not None and slot["attempt"] == info["attempt"]
    else:
        slot = rd["work"] if rd else None
    if slot is not None:
        # 기록된 Dispatch·horch Task 가 있으면 같아야 한다(같은 제목의 다른 horch Task 는 현재가 아니다)
        current = current and slot.get("dispatch") in (None, did) and slot.get("horch_task") in (None, row["task"])
    return {**info, "current": current, "status": st["status"], "recorded": False,
            "canceled": same_round and _round_canceled(rd),
            "finished": bool(info["kind"] == "review" and slot and slot.get("result") is not None)}


def _body(m: dict) -> dict:
    try:
        value = json.loads(m.get("body") or "")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _current_slots(st: dict) -> list[tuple[dict, dict]]:
    """끝나지 않은 태스크의 현재 라운드 작업·현재 리뷰 시도 실행 기록과 그 위치. 닫는 중(취소)인 기록은 뺀다."""
    rd = state.current_round(st)
    if st["status"] in state.CLOSED or not rd:
        return []
    found = []
    if not rd["work"].get("canceled"):
        found.append((rd["work"], {"task": st["id"], "round": rd["round"], "kind": "work"}))
    att = state.latest_attempt(rd)
    if att and att.get("result") is None:
        found.append((att, {"task": st["id"], "round": rd["round"], "kind": "review", "attempt": att["attempt"]}))
    return found


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def attention(p, rows: list[dict], grace: float, *, states: list[dict] | None = None,
              horch_cmd: str = "horch") -> list[dict]:
    """메시지 없이도 손볼 행(설계 8.2): grace 초 넘게 이어진 no_status, launch_failed. 끝나지 않은 태스크의 현재 라운드·
    현재 시도 Dispatch 만 본다.

    state/attention.json = {"reported": {Dispatch: 알린 단어}, "since": {Dispatch: no_status 를 센 시작 시각(epoch)}}.
    state/attention.json 의 "ok" 는 정상(no_status 아님)으로 본 Dispatch 다. 그 뒤 다시 no_status 가 되면 생성 시각이 아니라
    그때부터 센다(생성 시각은 처음 관측일 때만 쓴다).
    한 번 알린 것은 다시 알리지 않는다. reported 는 지금 보는 Dispatch(끝나지 않은 태스크의 현재 라운드·시도)만 남긴다
    (끝난 Dispatch 가 쌓이지 않게. 다시 볼 일이 없다). no_status 는 Dispatch 를 만든 시각(worker-list 의 created_at)부터
    센다(처음 본 시각부터 세면 wait 이 늦게 돌면 최악 2배를 기다린다). 그 시각을 읽지 못하면 처음 본 시각이다. 시각을
    파일에 남기므로 wait 호출이 바뀌어도 이어 센다. no_status 가 풀리면 지운다(다시 no_status 가 되면 그때부터 센다).
    horch_cmd: 힌트에 넣을 horch 명령(--home 포함, Horch.cmd)."""
    if states is None:
        states = state.all_states(p)
    p.ensure_state()
    found = []
    with flock(p.state / "attention.lock"):
        data = _dict(read_json(p.attention, {}))
        reported, since = dict(_dict(data.get("reported"))), dict(_dict(data.get("since")))
        ok = set(d for d in (data.get("ok") if isinstance(data.get("ok"), list) else []) if isinstance(d, str))
        before = (dict(reported), dict(since), set(ok))
        now = time.time()
        watching, current = set(), set()
        for st in states:
            for slot, loc in _current_slots(st):
                row = dispatch.slot_row(rows, slot)  # 기록된 Task 의 최신 시도, 기록 전이면 실행 키(제목)로 찾은 것
                if row is None:
                    continue
                did, word = row["id"], row.get("attention")
                current.add(did)
                if word not in UNCONFIRMED:  # 실제 상태 보고가 있는 관측(없음·idle·blocked·error 등)
                    ok.add(did)
                if word not in ("no_status", "launch_failed") or reported.get(did) == word:
                    continue
                if word == "no_status":
                    watching.add(did)
                    first = since.get(did)
                    if not isinstance(first, (int, float)):
                        age = age_seconds(row.get("created_at"))
                        fresh = age is not None and age > 0 and did not in ok
                        first = since[did] = now - age if fresh else now
                    if now - first < grace:
                        continue
                    hint = (f"시작 확인 창에서 멈췄을 수 있다. `{horch_cmd} worker-show --dispatch {did} --lines 80` 으로 "
                            "화면을 보고 메인에 질문으로 올린다(키를 누르지 않는다)")
                    item = {**loc, "dispatch": did, "attention": word, "next": None, "horch_next": row.get("next"),
                            "hint": hint}
                else:
                    # horch 의 worker-start --retry 는 hteam 상태를 건너뛴다. hteam 명령(start·review)만 준다
                    nxt = H("start", loc["task"]) if loc["kind"] == "work" else H("review", loc["task"])
                    item = {**loc, "dispatch": did, "attention": word, "next": nxt, "hint": "띄우기에 실패했다"}
                found.append(item)
                reported[did] = word
        since = {d: at for d, at in since.items() if d in watching}
        reported = {d: w for d, w in reported.items() if d in current}
        ok &= current
        if (reported, since, ok) != before:
            write_json(p.attention, {"reported": reported, "since": since, "ok": sorted(ok)})
    return found


def _live_hint(st: dict, rows: list[dict]) -> str | None:
    """태스크의 작업·리뷰 Dispatch(모든 라운드) 가운데 launching·active 인 것이 있으면 정리 안내. accept 는 이때 exit 3 이다."""
    tid = st["id"]
    for rd in st.get("rounds", []):
        for slot in (rd["work"], *rd["reviews"]):
            for row in dispatch.slot_rows(rows, slot):
                if row.get("state") not in LIVE:
                    continue
                did = row["id"]
                if row["state"] == "launching":
                    return f"{did}({slot['title']})가 아직 launching 이다. accept 는 exit 3 로 거부한다. 끝난 뒤 accept 한다"
                return (f"{did}({slot['title']})가 아직 active 다. accept 는 exit 3 로 거부한다(살아 있는 워커가 파일을 고칠 "
                        f"수 있다). 사용자에게 그 워커 탭을 확인해 달라고 한다. 태스크를 버리려면 {SHIM} drop {tid} --force")
    return None


def next_step(cfg, st: dict, by_task: dict[str, dict], have_rows: bool,
              rows: list[dict] | None = None,
              appr: dict | None = None,
              gone: dict[str, list[str]] | None = None) -> tuple[list[str] | None, str | None]:
    """태스크마다 다음 명령(설계 13장). 끝났다는 확실한 증거가 있을 때만 바꾸라고 하고, 모르면 기다린다.

    by_task: horch Task → 최신 시도 행. rows 를 주면(워커 목록 사본 전체) 지난 시도·제목으로 찾은 Dispatch 까지 본다.
    appr: approval.view 결과(끝나지 않은 일괄 승인 결정, awaiting_user 의 next). 읽지 못했으면 None.
    gone: 직간접 선행 가운데 dropped 인 것(tasks.dropped_blockers). start-ready 로 띄울 태스크(pending, 띄운 적 없는
    queued 라운드)는 영영 시작하지 못하므로 start-ready 를 권하지 않고 사람이 정할 일을 알린다."""
    tid, s = st["id"], st["status"]
    rd = state.current_round(st)
    if s == "pending":
        if gone:
            return None, tasks.dropped_hint(tid, gone)
        return H("start-ready"), None
    if s in state.CLOSED or not rd:
        return None, None
    slot = rd["work"]
    if appr is not None and tid in appr.get("replay", {}):  # 결정의 fix 가 취소를 저장한 뒤 멈췄어도 결정을 마저 한다
        oid = appr["replay"][tid]  # 일반 fix·accept 를 권하지 않는다(사용자 요청은 결정 기록에 있다). 잇는 것은 관제다
        return None, f"일괄 승인 결정 {oid} 이 끝나지 않았다. 관제가 재확인마다 기록대로 마저 한다"
    if _round_canceled(rd):
        return None, CANCELED_HINT
    no_rows = None if have_rows else NO_ROWS

    def latest(horch_task):
        return by_task.get(horch_task) if horch_task else None

    if s == "launch_failed":
        if dispatch.busy(st, slot):
            return None, "띄우는 중이다(launching)"
        if approval.unlaunched(st):
            # start T 는 의존을 보지 않는다. start-ready 가 선행이 다시 승인된 뒤에 띄운다(설계 11.4)
            if gone:
                return None, tasks.dropped_hint(tid, gone)
            return H("start-ready"), "일괄 승인 결정으로 연 수정 라운드다. 선행이 끝나면 start-ready 가 띄운다"
        return H("start", tid), None
    if s == "working":
        if state.open_attempt(rd):
            return H("review", tid), "끊긴 리뷰 시작을 이어 한다"
        row = latest(slot.get("horch_task"))
        if row is None:
            return None, no_rows
        if row["state"] in ("settled", "retained") or (row["state"] == "released" and row.get("outcome")):
            if row.get("outcome") == "succeeded":
                return H("review", tid), None
            return _fix(cfg, tid, st["round"], f"작업 실패: {(row.get('summary') or '')[:200]}")
        if row["state"] in ("abandoned", "released", "launch_failed") or row.get("verdict") in ("exited", "lost"):
            return _fix(cfg, tid, st["round"], "이전 워커가 done 없이 끝남")
        word = row.get("attention")
        if word == "idle":
            return None, "done 없이 턴을 마쳤다. 관제가 done 을 요구하고 두 번째면 decide 로 올린다"
        if word in ("blocked", "error", "no_status", "unverifiable"):
            return None, f"{word}: 관제가 decide 로 올린다. 사용자에게 그 워커 탭을 보게 한다"
        return None, None
    if s == "reviewing":
        att = state.latest_attempt(rd)
        if att is None:
            return None, None
        if att.get("result") in ("failed", "tampered"):
            return None, f"리뷰가 {att['result']} 로 멈췄다. 메인에 묻고(다시 시도 / 버림) 다시면 review {tid} --retry"
        if att.get("result") is None and not att.get("dispatch"):
            return H("review", tid), "끊긴 리뷰 시작을 이어 한다"
        row = latest(att.get("horch_task"))
        if row is None:
            return None, no_rows
        if dispatch.review_ended(row):
            return H("review-finish", tid), None
        if row.get("attention") == "idle":
            return None, "리뷰어가 done 없이 턴을 마쳤다. 관제가 done 을 요구한다"
        return None, None
    if s == "approved":
        if not have_rows:
            return H("accept", tid), f"{NO_ROWS}. 작업·리뷰 Dispatch 가 살아 있으면 accept 는 exit 3 로 거부한다"
        live = _live_hint(st, rows if rows is not None else list(by_task.values()))
        if live:
            return None, live
        return H("accept", tid), None
    if s == "changes":
        # 리뷰 파일은 새 워커가 수정 블록에서 읽는다. 메모는 다음 라운드의 요청이 돼 리뷰어가 P2 까지 막으므로 붙이지 않는다
        return _fix(cfg, tid, st["round"], None)
    if s == "awaiting_user":
        return _awaiting(cfg, st, appr)
    return None, None


def _awaiting(cfg, st: dict, appr: dict | None) -> tuple[list[str] | None, str | None]:
    """awaiting_user 의 다음(설계 11.4): stale 이면 알리기만 하고, 이미 물었으면 그 답을 기다리고(답이 와 있으면 결정을
    안내한다. 답 해석은 메인이 하므로 next 는 주지 않는다), 진행 중이거나 시작할 수 있는 승인 태스크가 있으면 그것을
    기다리고, 아니면 design-review. 설정을 읽지 못했거나 지금 설정의 승인 직무가 아니면 그 사실을 알린다."""
    tid = st["id"]
    if cfg is None:
        return None, "사용자 일괄 승인을 기다린다(설정을 읽지 못했다. status 의 config_error 를 본다)"
    if not cfg.is_approval(st.get("role")):  # design-review 는 승인 직무 태스크만 묻는다
        return None, (f"{tid} 의 직무({st.get('role')})는 지금 설정의 승인 직무(user_approval_roles)가 아니다. 일괄 승인으로 "
                      f"묻지 않는다. 사용자 승인 없이 끝내려면 {SHIM} accept {tid}")
    if appr is None:
        return None, "사용자 일괄 승인을 기다린다(일괄 승인 기록을 읽지 못했다. status 의 warnings 를 본다)"
    late = next((s for s in appr["stale"] if s["task"] == st["id"]), None)
    if late:
        return None, (f"선행 {', '.join(late['because'])} 가 이 라운드를 연 뒤에 결정 밖에서 고쳐졌다. 묻지도 승인하지도 "
                      "않는다. 메인에 알린다")
    key = (st["id"], st["round"])
    if key in appr["asked"]:
        oid = appr["asked"][key]
        if oid is None:
            return H("design-review"), "일괄 승인 질문을 쓰다 멈췄다. design-review 가 마저 쓴다"
        if oid in appr.get("unreadable_answers", ()):  # 답이 왔지만 읽지 못한다. 기다리라고 하지 않는다
            return None, (f"일괄 승인 질문 {oid} 의 답 파일 `.herdr-team/state/answers/{oid}.json` 을 읽지 못했다(손상). "
                          f"design-decide {oid} 도 bad_side_file 로 멈춘다. 메인에 알린다(직접 고치거나 치운 뒤 "
                          "다시 한다)")
        if oid in appr.get("answered", ()):  # 결정이 아무것도 기록하지 못한 채 답 메시지를 ack 했을 수 있다
            return None, (f"일괄 승인 질문 {oid} 의 답이 와 있다(`.herdr-team/state/answers/{oid}.json`). 결정이 없으면 답을 "
                          f"해석해 {SHIM} design-decide {oid} --json - 로 결정한다")
        return None, f"일괄 승인 질문 {oid} 의 사용자 답을 기다린다(답이 오면 메인이 design-decide {oid})"
    if appr["blockers"]:
        names = ", ".join(b["task"] for b in appr["blockers"])
        return None, f"승인 직무 태스크 {names} 가 accept 로 awaiting_user 가 되면 함께 묻는다(그때 design-review)"
    if appr.get("supplement"):  # design-review 는 exit 3 supplement_needed 다(설계 11.4)
        bad = [s for s in appr["supplement"] if s.get("error")]
        if bad:  # 보고서를 읽지 못한다: design-review 는 exit 1 unreadable_report 로 멈춘다
            return None, f"{bad[0]['error']}. 제안이 있는지 알 수 없어 묻지 않는다(보고서를 고치거나 메인에 알린다)"
        names = ", ".join(f"{s['task']} r{s['round']}" for s in appr["supplement"])
        dirs = appr.get("directors") or []
        waiting = [d for d in dirs if d["status"] == "pending"]  # 만들어 두고 시작하지 않은 보강 태스크
        busy = ", ".join(f"{d['task']}({d['status']})" for d in dirs if d["status"] != "pending")
        if waiting and not busy:
            first = (f"만들어 둔 보강 태스크 {', '.join(d['task'] for d in waiting)} 는 아직 시작하지 않았다. "
                     "관제가 의존이 풀리면 시작한다. 끝나면")
        else:
            first = (f"보강 중인 director 태스크 {busy} 가 끝나기를 기다린다. 끝나면" if busy else
                     "관제가 디렉터 보강 태스크를 만든다. 끝나면")
        return None, (f"시스템 추가 제안({names})이 있어 묻기 전에 디자인 시스템을 보강한다. {first} 관제가 제안한 "
                      "태스크마다 fix --supplement 로 다시 고치게 한다(설계 8.9)")
    return H("design-review"), None


def _question(q: dict) -> dict:
    """열린 질문 요약(설계 8.3): {id, type, from}, decide 면 kind·task 를 더한다."""
    item = {"id": q["id"], "type": q["type"], "from": q.get("from")}
    if q["type"] == "decide":
        item.update(kind=q.get("kind"), task=q.get("task"))
    return item


def _workers_copy(p) -> tuple[list[dict] | None, str | None]:
    """관제의 워커 목록 사본(설계 8.7): (rows, at). 없거나 깨졌으면 (None, None)."""
    data = read_json(p.workers_file, None)
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return None, None
    return data["rows"], data.get("at")


def _drive_next(nxt: list[str] | None, hint: str | None) -> tuple[list[str] | None, str | None]:
    """관제만 하는 next 는 메인이 실행하지 않는다(설계 8.3): next 를 비우고 hint 에 `관제가 한다(hteam <인자>)`."""
    if not nxt or nxt[1] not in DRIVE_ONLY or "--retry" in nxt:
        return nxt, hint
    said = f"관제가 한다(hteam {' '.join(nxt[1:])})"
    return None, f"{said}. {hint}" if hint else said


def status(p) -> dict:
    cfg, config_error = None, None
    try:
        cfg = config.load(p)
    except HteamError as exc:
        config_error = exc.message
    horch_error, horch_cmd = None, None
    try:
        horch_cmd = Horch(p.horch_home).cmd()  # 힌트용 명령만 만든다. horch 는 부르지 않는다(설계 8.3)
    except HteamError as exc:
        horch_error = exc.message
    copied, workers_at = _workers_copy(p)
    rows = copied or []
    by_task: dict[str, dict] = {}
    for r in rows:
        if r.get("task") not in by_task or r["attempt"] > by_task[r["task"]]["attempt"]:
            by_task[r["task"]] = r
    items = []
    states = state.all_states(p)
    warnings: list[str] = []
    appr = None
    if cfg is not None and cfg.user_approval_roles:
        try:
            appr = approval.view(p, cfg, states)
        except HteamError as exc:  # 기록이 손상됐다. awaiting_user 는 next 없이 hint 만 준다
            warnings.append(f"일괄 승인 기록: {exc.message}")
    by_id, graph = {s["id"]: s for s in states}, approval.Graph(p)
    for st in states:
        spec = graph.spec(st["id"])  # dropped 선행을 볼 때 같은 사양을 다시 읽지 않는다
        title = spec.title if spec is not None else None
        gone = None  # 영영 시작하지 못하게 하는 dropped 선행(직간접). start-ready 로 띄울 태스크만 본다
        if st["status"] == "pending" or approval.unlaunched(st):
            gone = tasks.dropped_blockers(graph, st["id"], by_id.get)
        if st.get("queued_fix"):
            nxt, hint = None, QUEUED_HINT
        else:
            nxt, hint = _drive_next(*next_step(cfg, st, by_task, copied is not None, copied, appr=appr, gone=gone))
        rd = state.current_round(st)
        work = by_task.get(rd["work"].get("horch_task")) if rd and rd["work"].get("horch_task") else None
        items.append({"id": st["id"], "role": st.get("role"), "title": title, "status": st["status"],
                      "round": st["round"], "lock": st["status"] in state.LOCKING, "owns": st.get("owns") or [],
                      "dispatch": ({k: work.get(k) for k in ("id", "state", "outcome", "attention", "verdict")}
                                   if work else None),
                      "next": nxt, "hint": hint})
    questions = [_question(q) for q in outbox.open_questions(p, warnings)]
    warnings += [f"{tid} 상태 파일을 읽지 못해 목록에서 뺐다" for tid in state.unreadable_ids(p)]
    crew_rows: list[dict] = []
    if cfg is not None:
        warnings += config.crew_warnings(cfg)  # 설정 경고(오류 아님, 설계 4.2)
        try:
            crew_rows = crew.status_rows(p, cfg)  # crew.json 과 설정만 읽는다(hc 를 부르지 않는다)
        except HteamError as exc:
            warnings.append(f"고정 에이전트 기록: {exc.message}")
    slots = None
    if cfg is not None and cfg.workspace.on:  # worktree 모드에서만 키가 있다(설계 5.10.8)
        try:
            slots = workspace.status_view(p, cfg)
        except HteamError as exc:  # 슬롯 기록이 손상됐다. status 는 실패하지 않는다
            slots = {"mode": "worktree", "slots": []}
            warnings.append(f"작업 공간 기록: {exc.message}")
    run, run_error = {}, None
    try:
        run = outbox._run(p)
    except HteamError as exc:  # 손상된 run.json 을 없는 것처럼 숨기지 않는다(up·큐 명령은 bad_run_file 로 거부한다)
        run_error = exc.message
    out = {"tasks": items, "config_error": config_error, "run_error": run_error, "horch_error": horch_error,
           "horch": horch_cmd, "workers_at": workers_at, "drive": drive.view(p, run), "crew": crew_rows,
           "watch_alive": outbox.watch_alive(p),
           "open_questions": questions, "unread_outbox": outbox.unread(p), "test_gate": testgate.gate_state(p)}
    if slots is not None:
        out["workspace"] = slots
    if warnings:
        out["warnings"] = warnings
    return out


def _cmd_status(args) -> dict:
    return status(find_project(args.root))


def register(sub) -> None:
    sub.add_parser("status").set_defaults(func=_cmd_status)
