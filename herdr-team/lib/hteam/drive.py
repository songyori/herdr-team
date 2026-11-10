"""관제 `hteam drive`(설계 8장, 6단계): 관제 탭의 셸 터미널에서 도는 프로그램이 horch Run 을 갖고 정해진 절차를 돌린다.
판단이 필요한 일은 outbox decide 로 메인에 올린다(8.10).

시작 순서(8.2 의 1–7: 실행 거부, drive.pid 단일 인스턴스, Run 연결, 탭 이름, 시작 재확인), heartbeat 와 생존 판정
(liveness·view), 틱 순서와 단계마다 격리(8.5), decide 쓰기와 표시(8.10), drive.log(8.11), 요청 큐(7.1, queue.run_pending)와
그 틱의 start-ready, 메시지 처리(8.6 의 이벤트 표·review-finish 결과 표·review 자식 결과 표·accept 뒤), 자식 프로세스(8.8),
재확인(8.7, reconcile_task·워커 목록 사본). 고정 에이전트의 worker_done·exited 정리와 재확인의 터미널 확인·큐 맞추기,
리셋 단계·인수인계 Dispatch 메시지·끝나지 않은 인수인계 정리(5.9.7), 입력 유실 재투입(5.9.8)은 crew 모듈에 맡긴다
(5.9.3·5.9.5·8.7 의 2·3). 묶음·마무리·기획 적용·디자인 단계(8.4·8.9)는 자리 메서드로 두고 뒤 단계가 채운다. 보기(6.5)
단계도 뒤 단계가 채운다.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time

from . import config, dispatch, herdr, outbox, procs, state
from .errors import CONFLICT, DENIED, FAIL, MISSING, USAGE, HteamError
from .globs import matches_any
from .horch import Horch
from .paths import PLUGIN_ROOT, find_project, report_rel, review_rel
from .util import age_seconds, env_float, local_age, local_now, now, read_json, write_atomic, write_json

# 시간 상수(설계 8.5 표, orca-team 코드 값). 뒤 단계도 여기서 가져온다
WAIT_MS = 10000  # horch check --wait 한 번
IDLE_S = 1.0  # 틱 사이
IDLE_FAIL_S = 5.0  # 메일 확인이 실패 중일 때 틱 사이
RECONCILE_S = 60  # 재확인 간격
DRIVE_STALE_S = 120  # heartbeat 가 이보다 오래면 멈춤
LAUNCH_GRACE_S = 180  # 띄운 뒤 다시 띄우지 않는 유예
QUEUE_WAIT_S = 90
QUEUE_POLL_S = 0.2
NOT_STARTED_S = 60
LIVENESS_UNKNOWN_S = 1800
RESET_STUCK_S = 1800
RESET_BUSY_S = 1800
RESET_UNKNOWN_S = 1800
RESET_FAIL_LIMIT = 3
RESET_CLEAR_TIMEOUT_MS = 10000
UNKNOWN_START_LIMIT = 3
NO_STATUS_GRACE_S = 60
BIND_TRIES = 3  # Run 연결 재시도
BIND_RETRY_S = 5.0
PID_TRIES = 3  # drive.pid 를 만들다 다른 관제와 경합하면 이만큼 다시 한다

# decide 종류(설계 8.10, orca 의 DECIDE_KINDS 와 같은 순서)
DECIDE_KINDS = ("worker_failed", "worker_question", "escalation", "max_rounds", "repeat_test_failure", "test_config",
                "planning_gaps", "unknown_regression", "token_update")
TITLE = "herdr-team 관제"  # 관제 탭 이름과 관제 pane 제목(8.2 의 5)

# 정해진 글(설계 8.6 원문)
IDLE_SUBJECT = "done 요청"
IDLE_TEXT = "턴을 마쳤는데 done 이 없다. 일이 끝났으면 프리앰블의 done 명령을 부른다. 남았으면 이어서 하고 끝나면 done 을 부른다."
GONE_NOTE = "이전 작업자가 중간에 끝났다. 보고서와 [{tid}] 커밋을 확인하고 남은 일을 이어서 한다"
BLOCKED_TAIL = (". 사용자에게 그 탭(고정 에이전트면 에이전트 탭, 아니면 관제 탭)을 보고 승인하거나 거절해 달라고 한다. "
                "그 뒤 작업자가 이어 가면 worker_done 이 와서 리뷰로 간다")
NO_STATUS_TEXT = "{tid} 작업자가 상태를 보고하지 않는다(시작 확인 창일 수 있다). 사용자에게 그 탭을 보고 넘겨 달라고 한다"
UNKNOWN_TEXT = ("작업자 생존을 {minutes}분 넘게 확인하지 못했다({word}). 끝났는지 알 수 없어 그대로 둔다. 작업자 탭이 멈췄으면 "
                "다시 보내거나 중단한다")
LIFTED_TEXT = "{tid}: {oid} 은 작업자가 이어 가서 닫아도 된다(worker_done 이 와서 리뷰로 간다)"
UNTRACKED_NOTE = "리뷰 중 소유 경로에 추적 안 된 파일이 생겼다. 커밋하거나 지운다: {paths}"
UNCOMMITTED_NOTE = "커밋 안 된 파일을 커밋하거나 지운다"
GATE_NOTE = "테스트 관문 반려: quick 이 통과하지 못했다({file} 의 출력 끝을 본다)"
# worker_question 의 판단 근거 문서(설계 7.7, 있는 것만)
GROUNDS = ("docs/planning/spec.md", "docs/planning/contracts.md", "docs/planning/interview.md", "docs/planning/voice.md")
TEST_CONFIG_CODES = frozenset({"test_unrunnable", "bad_test_config", "plan_unreadable"})
LIVE = ("launching", "active")  # 진행 중인 Dispatch(horch 상태)


def _heartbeat_age(p) -> float | None:
    try:
        text = p.heartbeat.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    return local_age(text)


def liveness(p, timeout: float | None = None) -> dict:
    """drive_alive(설계 8.2): drive.pid 의 {pid, started} 가 살아 있는 같은 프로세스이고 heartbeat 가 0 이상
    DRIVE_STALE_S 미만 전이면 alive. pid 만 살아 있으면 hung(heartbeat 없음·해석 실패·오프셋 없음·미래 포함).

    파일과 ps 만 본다(hc·horch 를 부르지 않는다). timeout 은 ps 의 시간 제한(None 이면 procs 기본)."""
    rec = read_json(p.drive_pid, None)
    pid = rec.get("pid") if isinstance(rec, dict) else None
    age = _heartbeat_age(p)
    out = {"alive": False, "hung": False, "pid": None, "started": None,
           "heartbeat_age": age if age is not None and age >= 0 else None}
    if not isinstance(pid, int) or isinstance(pid, bool):
        return out
    out.update(pid=pid, started=rec.get("started"))
    alive = procs.record_alive(rec) if timeout is None else procs.record_alive(rec, timeout=timeout)
    if not alive:
        return out
    fresh = age is not None and 0 <= age < DRIVE_STALE_S
    out.update(alive=fresh, hung=not fresh)
    return out


def _bound(run: dict) -> bool:
    """관제가 지금 pending_launch 의 nonce 로 Run 에 묶였다."""
    return bool(run.get("run_id")) and run.get("bound_nonce") == (run.get("pending_launch") or {}).get("nonce")


def view(p, run: dict) -> dict:
    """status·up 이 보이는 관제(설계 8.3): {terminal, alive, hung, starting, pid, heartbeat_age}.

    starting: 살아 있지도 멈추지도 않았고, 아직 Run 에 묶이지 않았고, 띄운 지(launched_at, 없으면 pending_launch.at)
    LAUNCH_GRACE_S 안이다. 묶인 뒤 죽은 관제는 시작 유예 없이 다시 띄운다. pid 는 alive·hung 일 때만."""
    live = liveness(p)
    starting = False
    if not live["alive"] and not live["hung"] and not _bound(run):
        age = age_seconds(run.get("launched_at") or (run.get("pending_launch") or {}).get("at"))
        starting = age is not None and 0 <= age < LAUNCH_GRACE_S
    return {"terminal": run.get("drive_terminal"), "alive": live["alive"], "hung": live["hung"], "starting": starting,
            "pid": live["pid"] if live["alive"] or live["hung"] else None, "heartbeat_age": live["heartbeat_age"]}


class Drive:
    """관제 한 프로세스. 틱(설계 8.5)과 격리·decide·로그, 메시지 처리(8.6)·자식(8.8)·재확인(8.7)을 갖는다."""

    def __init__(self, p):
        self.p = p
        self.last_reconcile: float | None = None  # monotonic. 처음은 None(첫 틱이 재확인한다)
        self.failing = False  # 메일 확인이 실패 중이다(틱 사이를 IDLE_FAIL_S 로 늘린다)
        self._ack: int | None = None  # 다음 check 에 줄 지난 delivery
        self._open: int | None = None  # 지금 처리 중인 delivery(미룬 메시지가 있으면 ack 하지 않아 다시 온다)
        self._done: set = set()  # _open 묶음에서 이미 처리한 메시지 id
        self._held: dict = {}  # 미룬 메시지 id → 처음 미룬 시각(monotonic)
        self._raised: set[tuple[str, str]] = set()  # 올린 격리 실패(키, 문구). 이 프로세스 안의 기억
        self._failed: set[tuple[str | None, str]] = set()  # 올린 관제 절차 실패(태스크, 문구). 이 프로세스 안의 기억
        self._horch: Horch | None = None
        # 돌고 있는 자식(설계 8.8): {키: {proc, args, out, err}}. 키는 review:<T> 와 final
        self.jobs: dict[str, dict] = {}
        self.rows: list[dict] = []  # 마지막 워커 목록(재확인). locate 가 기록 전 Dispatch 를 제목으로 찾을 때 쓴다
        self.retry_reviews: set[str] = set()  # 관문 잠금 대기 초과로 미룬 리뷰(8.7 의 4)
        self._retry_args: dict[str, list[str]] = {}  # 미룬 리뷰의 원래 자식 인자(큐 review --retry 의 --retry·--round·--request)
        self._job_args: dict[str, list[str]] = {}  # 결과를 처리 중인 리뷰 자식의 인자
        self.pending_marks: dict[str, tuple[str, int]] = {}  # 리뷰 자식이 도는 태스크의 미룬 decide 표시(out id, 라운드)

    def horch(self) -> Horch:
        if self._horch is None:
            self._horch = Horch(self.p.horch_home)
        return self._horch

    # --- 기록(8.2·8.11) ---
    def log(self, text: str) -> None:
        """`<로컬 시각> <글>` 을 관제 탭 화면(stdout)과 drive.log 에 쓴다. 쓰기 실패는 무시한다. 회전하지 않는다."""
        line = f"{local_now()} {text}\n"
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        try:
            self.p.drive_dir.mkdir(parents=True, exist_ok=True)
            with open(self.p.drive_log, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError:
            pass

    def heartbeat(self) -> None:
        write_atomic(self.p.heartbeat, local_now() + "\n")

    def idle_seconds(self) -> float:
        if os.environ.get("HTEAM_DRIVE_IDLE_S"):
            return env_float("HTEAM_DRIVE_IDLE_S", IDLE_S)
        return IDLE_FAIL_S if self.failing else IDLE_S

    # --- decide(8.10) ---
    def decide(self, kind: str, task: str | None, summary: str, *, files=(), commands=(), **extra) -> str:
        """outbox decide 줄을 쓰고 out id 를 돌려준다. commands 의 `{id}` 는 그 out id 로 바꿔 쓴다(자기 답 명령).

        태스크 ID 꼴이고 상태가 있으면 그 태스크에 decide·decide_round 를 쓴다. 그 태스크의 리뷰 자식이 돌면 쓰지 않고
        pending_marks 에 두었다가 자식이 끝난 뒤 쓴다(설계 8.8)."""
        if kind not in DECIDE_KINDS:
            raise HteamError("bad_decide_kind", f"모르는 decide 종류다: {kind}", USAGE)
        summary = summary or "(요약 없음)"
        commands = list(commands)
        fill = (lambda oid: {"commands": [c.replace("{id}", oid) for c in commands]}) \
            if any("{id}" in c for c in commands) else None
        entry = outbox.append(self.p, {"type": "decide", "from": "drive", "kind": kind, "task": task,
                                       "summary": summary, "files": list(files), "commands": commands,
                                       "body": f"[{kind}] {task or '-'}: {summary}", **extra}, fill=fill)
        if isinstance(task, str) and state.ID_RE.fullmatch(task) and self.p.state_path(task).exists():
            if self.running(f"review:{task}"):
                self.pending_marks[task] = (entry["id"], state.require(self.p, task)["round"])
            else:
                with state.edit(self.p, task) as st:
                    st["decide"] = entry["id"]
                    st["decide_round"] = st["round"]
        self.log(f"decide {entry['id']} {kind} {task or '-'}: {summary[:80]}")
        return entry["id"]

    def progress(self, body: str) -> None:
        """메인에 알리기만 하는 진행(outbox progress, 설계 7.2)."""
        outbox.append(self.p, {"type": "progress", "from": "drive", "body": body})

    # --- 격리(8.5) ---
    def isolated(self, key: str, fn, summary=None):
        """fn() 의 값. 예외면 로그를 남기고 (key, 문구)마다 한 번만 decide escalation 을 올린 뒤 None.

        의존 프로그램 없음(HteamError exit 12)·KeyboardInterrupt·SystemExit 는 그대로 올린다(관제가 끝난다). summary(exc)
        가 있으면 decide 문구를 그것으로 하고, (문구, extra) 튜플이면 extra 를 decide 줄에 더한다."""
        try:
            return fn()
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            err = exc
        except Exception as exc:  # noqa: BLE001  단계 하나의 실패가 관제를 끝내지 않는다
            err = exc
        text = f"{key} 실패: {type(err).__name__}: {err}"
        self.log(text)
        extra: dict = {}
        said = summary(err) if summary is not None else text
        if isinstance(said, tuple):
            said, extra = said
        if (key, said) in self._raised:
            return None
        try:
            self.decide("escalation", None, said, **extra)
        except Exception as exc:  # noqa: BLE001  올리지 못하면 기억하지 않는다(다음 실패가 다시 올린다)
            self.log(f"{key} 실패를 올리지 못했다: {type(exc).__name__}: {exc}")
            return None
        self._raised.add((key, said))
        return None

    # --- 틱 단계(8.5) ---
    def check_mail(self) -> None:
        """`horch check --wait` 한 번. 처리한 묶음은 다음 check 의 --ack 로 확인한다(처리가 실패해도).

        handle 이 미룬 메시지(아직 상태에 기록되지 않은 진행 중 Dispatch, 8.6)가 있으면 그 묶음을 ack 하지 않는다. horch 는
        ack 안 된 묶음을 다시 주므로 다음 틱에 그 메시지만 다시 처리한다(이미 처리한 메시지는 건너뛴다)."""
        ms = int(env_float("HTEAM_DRIVE_WAIT_MS", WAIT_MS))
        args = ["check", "--wait", "--timeout-ms", str(ms)]
        if self._ack is not None:
            args += ["--ack", str(self._ack)]
        try:
            data = self.horch().ok(*args, timeout=ms / 1000 + 30)
        except Exception:
            self.failing = True  # ack 는 그대로 둔다(다음에 같은 ack 를 준다)
            raise
        self.failing = False
        delivery = data.get("delivery")
        if delivery != self._open:  # 새 묶음
            self._open, self._done = delivery, set()
        held = False
        for m in data.get("messages") or []:
            if m.get("id") in self._done:
                continue
            if self.isolated(f"msg:{m.get('id')}", lambda m=m: self.handle(m),
                             lambda exc, m=m: self._message_failure(m, exc)) is True:
                held = True
                continue
            self._done.add(m.get("id"))
        self._ack = None if held else delivery

    @staticmethod
    def _message_failure(m: dict, exc: Exception):
        """처리하지 못한 메시지는 다시 오지 않으므로 원문을 담아 올린다(설계 8.5)."""
        said = (f"메시지 {m.get('id')} 처리 실패: {type(exc).__name__}: {exc} "
                f"[type={m.get('type')} dispatch={m.get('dispatch') or '-'}] {str(m.get('body') or '')[:200]}")
        if m.get("type") == "question":
            return said, {"question": m.get("body"), "message_id": m.get("id")}
        return said

    # --- 메시지(8.6) ---
    def handle(self, message: dict) -> bool | None:
        """메시지 처리(설계 8.6 표). status 는 ack 만 한다(로그도 없다). 인수인계 Dispatch 는 handoff_message 가 맡는다.
        Dispatch 로 태스크·라운드·종류를 찾고(coord.locate), 모르거나 끝났거나 지난 Dispatch 면 로그만 남긴다.

        못 찾으면 워커 목록을 한 번 새로 받아 다시 찾는다. 상태 파일에는 아직 없고 새 목록에 이 Run 의 진행 중(launching·
        active) 워커로 있으면(리뷰 자식·start 가 띄운 직후 기록 전) True 를 돌려 미룬다(check_mail 이 ack 하지 않는다). 처음
        미룬 뒤 RECONCILE_S 가 지나면 버린다. question(늘)과 미뤘던 escalation 은 그 Dispatch 가 지금 목록에서 더는 진행 중이
        아니면(끝난 워커의 질문) decide 로 올리지 않고 로그만 남긴다."""
        kind = message.get("type")
        if kind == "status":
            return None
        if self.handoff_message(message):
            return None
        from . import coord  # coord 가 이 모듈을 쓴다
        body = coord._body(message)
        did = message.get("dispatch") or body.get("dispatch")
        mid = message.get("id")
        held, fresh = mid in self._held, False
        loc = coord.locate(self.p, did, self.rows)
        if did and (loc is None or (held and not loc["recorded"])):
            loc = coord.locate(self.p, did, self.write_workers())
            fresh = True
            row = dispatch.row_by_id(self.rows, did)
            if loc is not None and not loc["recorded"] and row is not None and row.get("state") in LIVE:
                first = self._held.setdefault(mid, time.monotonic())
                if time.monotonic() - first < RECONCILE_S:
                    return True
                loc = None  # 상한을 넘겼다: 지금처럼 버린다
        self._held.pop(mid, None)
        if loc is None:
            self.log(f"모르는 Dispatch 의 {kind} 무시: {did or '-'}")
            return None
        tid = loc["task"]
        if loc["status"] in state.CLOSED:
            self.log(f"{tid} 이미 끝난 태스크({loc['status']})의 {kind} 무시: {did}")
            return
        if loc["canceled"] or not loc["current"]:
            self.log(f"{tid} 지난 디스패치의 {kind} 무시: {did}")
            return
        if kind == "question" or (held and kind == "escalation"):
            row = dispatch.row_by_id(self.rows if fresh else self.write_workers(), did)
            if row is None or row.get("state") not in LIVE:  # 끝난 워커의 질문: 답할 곳이 없다. 종료 메시지가 마무리한다
                self.log(f"{tid} 끝난 디스패치의 {kind} 무시: {did}")
                return None
        work = loc["kind"] == "work"
        if kind == "worker_done":
            if work:
                self.on_work_done(tid, did, body)
            else:
                self._lift(tid, did)
                self.finish_review(tid)
        elif kind == "question":
            self._question(tid, message)
        elif kind == "escalation":
            text = str(message.get("body") or "")
            self.decide("escalation", tid, text[:300] or "워커가 done 없이 멈췄다", files=self._files(*self._grounds(tid)))
        elif kind == "observed":
            word = body.get("kind")
            if word == "idle":
                self._idle(tid, did, loc["round"], work)
            elif word in ("blocked", "error"):
                self._stuck(tid, did, word)
            elif word in ("exited", "lost"):
                if work:
                    self._gone(tid, did)
                else:
                    self.finish_review(tid)
            elif word == "not_started":
                self.on_not_started(tid, did, body)

    def on_work_done(self, tid: str, did: str, body: dict) -> None:
        """작업 worker_done(8.6, 재확인의 settled 도 같다): 고정 에이전트 정리 → 확인 창 표시 풀기 → 생존 모름 표시 지우기 →
        working 이면 성공은 리뷰 자식, 실패는 worker_failed decide."""
        self.crew_done(tid, did)
        self._lift(tid, did)
        self._clear_unknown(tid)
        st = state.require(self.p, tid)
        if st["status"] != "working":
            return  # 재확인이 맞춘다
        if body.get("outcome") == "succeeded":
            self.start_review(tid)
            return
        self.decide("worker_failed", tid, str(body.get("summary") or "")[:300] or "워커가 실패를 보고했다",
                    files=self._files(*self._grounds(tid)),
                    commands=[self._fix_cmd(st, "<원인과 지시>"), f"hteam drop {tid}"])

    def _question(self, tid: str, m: dict) -> None:
        text = str(m.get("body") or "")
        role = (state.load(self.p, tid) or {}).get("role")
        files = self._files(*self._grounds(tid), *GROUNDS, f".herdr-team/roles/{role}.md", ".herdr-team/project.md")
        self.decide("worker_question", tid, text[:300], files=files, commands=['hteam answer {id} "<답>"'],
                    question=text, message_id=m.get("id"))

    def _idle(self, tid: str, did: str, rnd: int, work: bool) -> None:
        """observed idle: 그 Dispatch 에 처음이면 done 요청 글. 두 번째면 작업은 decide 한 번, 리뷰는 abandon --kill 뒤
        review-finish(시도 실패, 자동 재시도)."""
        st = state.require(self.p, tid)
        slot = self._slot(st, rnd, work) or {}
        if slot.get("idle_nudged") != did:
            self.horch().ok("send", "--to", f"dispatch:{did}", "--subject", IDLE_SUBJECT, f"--body={IDLE_TEXT}")
            self._mark(tid, rnd, work, idle_nudged=did)
        elif not work:
            self.horch().ok("worker-abandon", "--dispatch", did, "--kill")
            self.finish_review(tid)
        elif slot.get("idle_escalated") != did:
            self.decide("escalation", tid, f"{tid} 작업자가 done 없이 턴을 두 번 마쳤다",
                        commands=[self._fix_cmd(st), f"hteam drop {tid}"])
            self._mark(tid, rnd, work, idle_escalated=did)

    def _stuck(self, tid: str, did: str, word: str) -> None:
        """observed blocked·error: hc 7501 상태(kind·msg)로 decide. 화면은 읽지 않는다(--lines 0, orch 13.1)."""
        data = self.horch().ok("worker-show", "--dispatch", did, "--lines", "0")
        status = ((data.get("worker") or {}).get("hc") or {}).get("status")
        status = status if isinstance(status, dict) else {}
        msg = str(status.get("msg") or "")
        if word == "error":
            self.decide("escalation", tid, f"{tid} 작업자가 오류 상태다({msg[:120]})", detail=msg)
            return
        st = state.require(self.p, tid)
        what = status.get("kind") or status.get("state") or word
        oid = self.decide("escalation", tid, f"{tid} 작업자가 확인 창에서 멈췄다({what}: {msg[:120]}){BLOCKED_TAIL}",
                          commands=[self._fix_cmd(st, force=True), f"hteam drop {tid} --force"], detail=msg)
        with state.edit(self.p, tid) as cur:
            cur["blocked_decide"] = {"id": oid, "dispatch": did}

    def _gone(self, tid: str, did: str) -> None:
        """작업 exited·lost: 최대 라운드면 max_rounds decide, 아니면 이어서 하는 fix."""
        self.crew_gone(tid, did)
        st = state.require(self.p, tid)
        if st["round"] >= self._limit():
            self.decide("max_rounds", tid, "작업자가 worker_done 없이 끝났고 최대 라운드다",
                        commands=[self._fix_cmd(st), f"hteam drop {tid}"])
        else:
            self.fix_task(tid, GONE_NOTE.format(tid=tid))

    def _lift(self, tid: str, did: str) -> None:
        """확인 창 표시 풀기(8.6): blocked_decide 가 이 Dispatch 일 때만. 그 decide 의 라운드 표시(상태와 미룬 표시
        pending_marks)도 지워 리뷰로 간다. 그 decide 에 답이 없으면 progress 를 한 번 쓴다."""
        if ((state.load(self.p, tid) or {}).get("blocked_decide") or {}).get("dispatch") != did:
            return
        oid = None
        with state.edit(self.p, tid) as st:
            mark = st.get("blocked_decide") or {}
            if mark.get("dispatch") == did:
                oid = mark.get("id")
                st.pop("blocked_decide", None)
                if oid and st.get("decide") == oid:
                    st.pop("decide", None)
                    st.pop("decide_round", None)
        if oid and (self.pending_marks.get(tid) or (None,))[0] == oid:
            del self.pending_marks[tid]  # 리뷰 자식이 도는 동안 미룬 같은 decide 의 표시도 쓰지 않는다
        if oid and outbox.answer_of(self.p, oid) is None:
            self.progress(LIFTED_TEXT.format(tid=tid, oid=oid))

    def _clear_unknown(self, tid: str) -> None:
        st = state.load(self.p, tid) or {}
        if "liveness_unknown_since" in st or "liveness_escalated" in st:
            with state.edit(self.p, tid) as cur:
                cur.pop("liveness_unknown_since", None)
                cur.pop("liveness_escalated", None)

    @staticmethod
    def _slot(st: dict, rnd: int, work: bool) -> dict | None:
        """라운드 rnd 가 지금 라운드면 그 작업 실행 기록 또는 마지막 리뷰 시도."""
        rd = state.current_round(st)
        if not rd or rd["round"] != rnd:
            return None
        return rd["work"] if work else state.latest_attempt(rd)

    def _mark(self, tid: str, rnd: int, work: bool, **fields) -> None:
        with state.edit(self.p, tid) as st:
            slot = self._slot(st, rnd, work)
            if slot is not None:
                slot.update(fields)

    def _limit(self) -> int:
        return config.load(self.p).max_rounds

    def _fix_cmd(self, st: dict, note: str = "<지시>", *, force: bool = False) -> str:
        """decide 의 fix 명령(설계 8.10): 지금 라운드가 max_rounds 이상이면 --force-round."""
        flags = (["--force-round"] if st["round"] >= self._limit() else []) + (["--force"] if force else [])
        return " ".join(["hteam fix", st["id"], *flags, f'--note "{note}"'])

    def _files(self, *rels: str) -> list[str]:
        """decide files: 있는 파일만(프로젝트 루트 기준)."""
        return [r for r in rels if (self.p.root / r).exists()]

    @staticmethod
    def _grounds(tid: str) -> tuple[str, str]:
        return f".herdr-team/tasks/{tid}.md", report_rel(tid)

    # --- review-finish 결과(8.6) ---
    def finish_review(self, tid: str) -> None:
        """review-finish 를 이 프로세스에서 부른다(nowait: 다른 리뷰 실행자가 finish 잠금을 쥐었으면 review_busy)."""
        from . import review  # review 가 queue 를 거쳐 이 모듈을 쓴다
        try:
            res = review.review_finish(self.p, tid, nowait=True)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            if exc.code in ("review_failed", "review_tampered"):
                rd = state.current_round(state.require(self.p, tid))
                last = state.latest_attempt(rd) or {}
                self._review_failure(tid, exc, rd["round"], last.get("attempt"))
            elif exc.exit_code != CONFLICT:  # exit 3(리뷰어가 아직 돈다, review_busy 등)은 기다린다. 재확인이 맞춘다
                self.procedure_failed(tid, exc)
            return
        if res.get("retried"):
            return
        self.log(f"{tid} r{res['round']} {res['verdict']}")
        if res["status"] == "approved":
            self.accept_task(tid)
        elif res["status"] == "changes":
            self._reviewer_changes(tid, res.get("warnings") or [])

    def _review_failure(self, tid: str, exc: HteamError, rnd: int, attempt) -> None:
        """리뷰 실패·변조 decide. 그 시도를 review_failure_asked 에 남긴다(재확인이 같은 시도로 다시 올리지 않게, 8.7)."""
        self.decide("escalation", tid, f"리뷰 실패({exc.code}): {exc.message[:300]}",
                    commands=[f"hteam review {tid} --retry", f"hteam drop {tid}"])
        with state.edit(self.p, tid) as st:
            st["review_failure_asked"] = [rnd, attempt]

    def _reviewer_changes(self, tid: str, warnings: list[str]) -> None:
        """리뷰어 REQUEST_CHANGES: 최대 라운드면 max_rounds, 아니면 fix(리뷰 중 소유 경로에 생긴 추적 안 된 파일만 note, 5.5)."""
        st = state.require(self.p, tid)
        if st["round"] >= self._limit():
            self._max_rounds(st)
            return
        owns = st.get("owns") or []
        mine = [w for w in warnings if not w.startswith("../") and matches_any(w, owns)]
        self.fix_task(tid, UNTRACKED_NOTE.format(paths=", ".join(mine)) if mine else None)

    def _max_rounds(self, st: dict) -> None:
        tid = st["id"]
        self.decide("max_rounds", tid, f"최대 {self._limit()} 라운드에도 승인되지 않았다",
                    files=self._files(review_rel(tid, st["round"])), commands=[self._fix_cmd(st), f"hteam drop {tid}"])

    def hteam_changes(self, tid: str) -> None:
        """hteam 반려(사전 검사·테스트 관문)의 다음(8.6): 같은 관문 실패 두 라운드면 repeat_test_failure, 최대 라운드면
        max_rounds, 아니면 반려 사유 note 로 fix."""
        from . import review
        st = state.require(self.p, tid)
        if _same_gate_failure(st):
            self.decide("repeat_test_failure", tid, "같은 quick 테스트 실패로 hteam 사전 검사가 두 라운드 연속 반려했다",
                        files=self._files(review_rel(tid, st["round"])), commands=[self._fix_cmd(st), f"hteam drop {tid}"])
            return
        if st["round"] >= self._limit():
            self._max_rounds(st)
            return
        problems = (state.current_round(st) or {}).get("prechecks") or []
        if problems == [review.GATE_PROBLEM]:
            note = GATE_NOTE.format(file=review_rel(tid, st["round"]))
        else:
            note = ("사전 검사 반려: " + "; ".join(problems))[:300]
        self.fix_task(tid, note)

    # --- review 자식 결과(8.6) ---
    def on_review_result(self, tid: str, code: int, data: dict | None) -> None:
        """`hteam review T` 자식의 결과 표(8.6). data 는 자식 stdout 의 마지막 JSON 객체(없으면 None)."""
        if data is None:
            self.decide("escalation", tid, f"리뷰를 시작하지 못했다(exit {code}): 출력이 없다")
            return
        if code == 0:
            if data.get("status") == "changes":
                self.hteam_changes(tid)
            elif data.get("tests_skipped"):
                self.confirm_test()
            return  # 보기 pane 은 같은 틱의 view_step 이 연다
        err = data.get("error") or {}
        ecode, message = err.get("code"), str(err.get("message") or "")
        if code == 2 and ecode in TEST_CONFIG_CODES:
            self.decide("test_config", tid, message[:300], files=self._files("docs/planning/tasks.toml"),
                        commands=['hteam task new --role planner --title "[test] 고치기"'])
        elif code == 2 and ecode == "uncommitted_owned":
            self.fix_task(tid, UNCOMMITTED_NOTE)
        elif code == 4 and ecode == "test_lock_timeout":
            self.retry_reviews.add(tid)  # 다음 재확인이 같은 인자로 다시 띄운다
            if self._job_args.get(tid):
                self._retry_args[tid] = self._job_args[tid]
        elif code == 1 and ecode == "bad_test_approvals":
            self.decide("escalation", tid, message[:300])
        elif code == CONFLICT:
            return  # 진행 중 리뷰·launching 등: 그 리뷰가 쓴 상태를 재확인이 처리한다
        else:
            self.decide("escalation", tid, f"리뷰를 시작하지 못했다(exit {code}): " + f"{ecode}: {message}"[:300])

    # --- accept·fix(8.6·8.7) ---
    def accept_task(self, tid: str) -> dict | None:
        """관제 판정 경로의 accept. review_busy 면 기다리고(재확인이 다시 본다), 그 밖의 거부는 관제 절차 실패."""
        from . import tasks  # tasks 가 queue 를 거쳐 이 모듈을 쓴다
        try:
            res = tasks.accept(self.p, tid, nowait=True)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            if exc.code != "review_busy":
                self.procedure_failed(tid, exc)
            return None
        self.after_accept(tid, res)
        return res

    def after_accept(self, tid: str, res: dict) -> None:
        """accept 뒤(설계 8.6, 관제 판정 경로와 큐 accept 모두): release 실패 progress, 직무·결과별 다음 자리, start-ready."""
        for warning in res.get("warnings") or []:
            self.progress(f"{tid} 워커 해제 실패: {str(warning)[:200]}")
        role = (state.load(self.p, tid) or {}).get("role")
        if res.get("status") == "done" and role == "planner":
            self.apply_plan(tid)
        elif res.get("status") == "done" and role == "tester":
            self.batch_done(tid)
        elif res.get("status") == "awaiting_user":
            self.design_step()
        self.start_ready()

    def fix_task(self, tid: str, note: str | None = None) -> dict | None:
        """관제의 모든 fix(8.6·8.7). 먼저 drive_fix 를 쓴다: fix 가 이전 Dispatch 를 정리한 뒤 새 라운드를 쓰기 전에 관제가 죽어도
        재확인이 같은 지시로 잇는다. 새 라운드를 쓰는 쓰기가 drive_fix 를 지운다. review_busy 면 표시를 두고 다음 재확인이
        잇는다. 그 밖의 거부는 표시를 지우고 관제 절차 실패. 다만 태스크가 launch_failed 로 남았으면(새 라운드를 열었으나 띄우지
        못했다) 재확인의 launch_failed decide 하나로 올린다(설계 8.5)."""
        from . import tasks
        with state.edit(self.p, tid) as st:
            st["drive_fix"] = {"round": st["round"], "note": note, "at": now()}
        try:
            res = tasks.fix(self.p, tid, note=note, supplement=None, force_round=False, cli={}, nowait=True)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            if exc.code == "review_busy":
                return None
            cur = state.load(self.p, tid) or {}
            if cur.get("drive_fix"):
                with state.edit(self.p, tid) as st:
                    st.pop("drive_fix", None)
            if cur.get("status") != "launch_failed":
                self.procedure_failed(tid, exc, note=note)
            return None
        if "round" in res:  # 새 라운드를 열었다(대기열에만 넣은 결과는 꺼낼 때 드레인이 남긴다)
            self.log(f"{tid} r{res['round']} 수정 시작")
        return res

    def procedure_failed(self, task: str | None, exc: HteamError, *, note: str | None = None) -> str | None:
        """관제가 정한 절차(accept·fix·start 등)가 hteam 오류로 거부됐다(설계 8.5): decide escalation
        `관제 절차 실패: <code>: <message>[ (아직 전하지 못한 지시: <note>)]` 를 (태스크, 글)마다 이 프로세스 안에서 한 번 올린다.
        올렸으면 out id, 이미 올렸으면 None."""
        text = f"관제 절차 실패: {exc.code}: {exc.message}" + (f" (아직 전하지 못한 지시: {note})" if note else "")
        if (task, text) in self._failed:
            return None
        oid = self.decide("escalation", task, text)
        self._failed.add((task, text))
        return oid

    def run_queue(self) -> list:
        """요청 큐 실행(설계 7.1, 틱 3). 이번에 실행(또는 기록으로 복구)한 요청 id(번호순)."""
        from . import queue  # queue 가 이 모듈을 쓴다
        return queue.run_pending(self.p, self)

    def start_ready(self) -> dict | None:
        """요청을 실행한 틱의 start-ready(설계 8.5 의 4). 띄우지 못한 태스크는 launch_failed 면 넘기고(재확인의 launch_failed
        decide 가 한 번 올린다, 8.7) 아니면 관제 절차 실패로 올린다. 그 밖의 오류는 올린다(격리가 받는다)."""
        from . import tasks  # tasks 가 queue 를 거쳐 이 모듈을 쓴다
        try:
            return tasks.start_ready(self.p)
        except HteamError as exc:
            if exc.code != "start_failed":
                raise
            for item in exc.data.get("failed") or []:
                tid = item.get("task")
                try:
                    st = state.load(self.p, tid)
                except HteamError:
                    st = None
                if st is not None and st.get("status") == "launch_failed":
                    continue
                err = item.get("error") or {}
                self.procedure_failed(tid, HteamError(err.get("code") or "failed", err.get("message") or "",
                                                      hint=err.get("hint") or ""))
            return exc.data

    def spawn_review(self, tid: str, *, retry: bool, expect_round: int | None = None,
                     request: str | None = None) -> dict:
        """큐 `review --retry`(설계 7.1)도 리뷰 자식으로 돌린다(관문을 다시 돌므로, 8.8). 리뷰 자식이 있거나 다른 리뷰
        실행자가 finish 잠금을 쥐었으면 exit 3 review_busy(큐가 미룬다, 8.5). expect_round 는 띄우기 전에 한 번 보고, 자식이
        finish 잠금 안에서 다시 본다(숨은 --round). request 는 자식의 숨은 --request 로 history 에 남는다."""
        from . import tasks
        key = f"review:{tid}"
        if key in self.jobs:
            raise state._review_busy(tid)
        state.finish_probe(self.p, tid)
        if expect_round is not None:
            tasks._expect_round(tid, state.require(self.p, tid), expect_round)
        args = ["review", tid, *(["--retry"] if retry else []),
                *(["--round", str(expect_round)] if expect_round is not None else []),
                *(["--request", request] if request else [])]
        self.spawn(key, args)
        self.log(f"{tid} 리뷰 시작")
        return {"task": tid, "spawned": True}

    def confirm_test(self, force: bool = False, request: str | None = None) -> dict:
        """`[test]` 확정 질문 올리기(설계 8.4, test-confirm 7.1). Task 10 이 채운다."""
        return {"asked": None}

    # --- 자식 프로세스(8.8) ---
    def running(self, key: str) -> bool:
        """그 키의 자식이 아직 거두어지지 않았다(돌고 있거나 끝났지만 이번 틱의 reap_jobs 전)."""
        return key in self.jobs

    def spawn(self, key: str, args: list[str]) -> bool:
        """`hteam --root <루트> <args>` 자식을 환경 그대로(관제로 판별된다, 8.2) 띄운다. stdin 은 /dev/null, stdout·stderr 는
        state/drive/jobs/<키의 ":" 를 "-" 로>.out·.err(덮어쓴다). 그 키의 자식이 있으면 띄우지 않고 False."""
        if key in self.jobs:
            return False
        self.p.jobs_dir.mkdir(parents=True, exist_ok=True)
        name = key.replace(":", "-")
        out, err = self.p.jobs_dir / f"{name}.out", self.p.jobs_dir / f"{name}.err"
        argv = [sys.executable, str(PLUGIN_ROOT / "bin" / "hteam"), "--root", str(self.p.root), *args]
        with open(out, "w", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe)
        self.jobs[key] = {"proc": proc, "args": list(args), "out": out, "err": err}
        return True

    def start_review(self, tid: str, args: list[str] | None = None) -> bool:
        """리뷰 자식(8.8). 그 자식이 있거나 다른 리뷰 실행자(죽은 관제가 남긴 자식 등)가 finish 잠금을 쥐었으면 띄우지 않는다
        (다음 재확인이 다시 본다). 잡히면 놓고 띄운다(리뷰가 다시 잡는다). args 는 자식 인자(기본 `review T`. 미룬 큐
        review --retry 는 원래 인자)."""
        key = f"review:{tid}"
        if key in self.jobs or state.finish_busy(self.p, tid):
            return False
        self.spawn(key, args or ["review", tid])
        self.log(f"{tid} 리뷰 시작")
        return True

    def reap_jobs(self) -> None:
        """끝난 자식 처리(설계 8.8). 처리 전에 목록에서 뺀다(처리 실패가 같은 결과를 다시 읽지 않게). 자식마다 job:<키> 격리."""
        for key, job in list(self.jobs.items()):
            if job["proc"].poll() is None:
                continue
            del self.jobs[key]
            code = job["proc"].returncode
            out, err = _read(job.get("out")), _read(job.get("err"))
            if key.startswith("review:"):
                tid = key.split(":", 1)[1]
                self.isolated(f"job:{key}", lambda tid=tid, code=code, out=out, args=job.get("args"):
                              self._review_done(tid, code, out, args))
            elif key == "final":
                self.isolated(f"job:{key}",
                              lambda code=code, out=out, err=err: self.final_done(code, _last_json(out) or {}, err))

    def _review_done(self, tid: str, code: int, out: str, args: list[str] | None = None) -> None:
        """리뷰 자식이 끝났다: 도는 동안 올린 decide 의 표시를 먼저 쓰고(그 뒤 결과 처리가 쓰는 새 표시가 이긴다) 결과를 처리한다.
        args(그 자식의 인자)는 잠금 대기 초과로 다시 띄울 때 쓴다."""
        mark = self.pending_marks.pop(tid, None)
        if mark:
            with state.edit(self.p, tid) as st:
                st["decide"], st["decide_round"] = mark
        self._job_args[tid] = list(args or [])
        try:
            self.on_review_result(tid, code, _last_json(out))
        finally:
            self._job_args.pop(tid, None)

    def reset_step(self) -> None:
        """고정 에이전트마다 리셋 단계(설계 5.9.7). 설정 순서로, 에이전트마다 reset:<이름> 격리."""
        from . import crew  # crew 가 이 모듈을 쓴다
        cfg = self.isolated("reset", lambda: config.load(self.p))
        if cfg is None:
            return
        for name in cfg.crew:
            self.isolated(f"reset:{name}", lambda name=name: crew.begin_reset(self, cfg, name))

    def view_step(self) -> None:
        """리뷰 보기 pane 닫기·열기(설계 6.5, 에이전트마다 view:<이름> 격리). Task 9 가 채운다."""

    # --- 재확인(8.7) ---
    def write_workers(self) -> list[dict]:
        """`horch worker-list` 한 번. 사본 state/drive/workers.json = {at, rows}(메인의 status 가 읽는다, 8.3)."""
        rows = self.horch().workers()
        write_json(self.p.workers_file, {"at": now(), "rows": rows})
        self.rows = rows
        return rows

    def reconcile(self) -> None:
        """재확인(설계 8.7 의 순서). 태스크마다 reconcile:<T> 로 격리한다(한 태스크의 예외가 다른 태스크를 막지 않는다)."""
        from . import coord
        rows = self.write_workers()
        self.crew_check()
        self.handoff_check()
        for tid in sorted(self.retry_reviews):
            if self.start_review(tid, self._retry_args.get(tid)):
                self.retry_reviews.discard(tid)
                self._retry_args.pop(tid, None)
        states = state.all_states(self.p)
        quiet = [s for s in states if not outbox.open_decide(self.p, s) and not self.running(f"review:{s['id']}")]
        for item in coord.attention(self.p, rows, NO_STATUS_GRACE_S, states=quiet):
            if item.get("attention") == "no_status":  # attention.json 이 한 번만 알린다
                self.decide("escalation", item["task"], NO_STATUS_TEXT.format(tid=item["task"]))
        for st in states:
            self.heartbeat()
            self.isolated(f"reconcile:{st['id']}", lambda st=st: self.reconcile_task(st))
        self.unbatched()
        self.start_ready()
        self.design_step()
        self.resume_decisions()
        self.finish_step()

    def reconcile_task(self, st: dict) -> None:
        """메시지 없이 끝난 일을 태스크 상태별로 맞춘다(설계 8.7 표). 열린 decide 가 지금 라운드면(메인이 답하지 않았다)·
        리뷰 자식이 돌면 건드리지 않는다. 지금 라운드의 drive_fix 는 상태별 처리 대신 같은 지시로 fix 를 잇는다."""
        tid = st["id"]
        st = state.require(self.p, tid)
        if outbox.open_decide(self.p, st) or self.running(f"review:{tid}"):
            return
        status = st["status"]
        if status not in state.CLOSED and st.get("drive_fix"):
            pending = st["drive_fix"]
            if pending.get("round") == st["round"]:
                self.fix_task(tid, pending.get("note"))  # 정리는 다시 불러도 이어 한다(6.4)
            else:
                with state.edit(self.p, tid) as cur:
                    cur.pop("drive_fix", None)
            return
        rd = state.current_round(st)
        if status == "working":
            if not st.get("queued_fix"):
                resend = rd["work"].get("resend")
                if resend:  # 재투입이 끝나기 전에 관제가 죽었거나 터미널을 확인하지 못했다: 작업자 확인 대신 잇는다(5.9.8)
                    self.on_not_started(tid, resend["from"], None)
                else:
                    self._check_work(st, rd)
        elif status == "reviewing":
            self._check_review(st, rd)
        elif status == "approved":
            self.accept_task(tid)
        elif status == "changes":
            if st.get("queued_fix"):
                return
            if (rd or {}).get("review_source") == "hteam":
                self.hteam_changes(tid)
            else:
                self._reviewer_changes(tid, [])
        elif status == "pending":
            self._dropped_deps(st)
        elif status == "launch_failed":
            self._launch_failed(st, rd)
        elif status == "done" and st.get("role") == "planner" and not st.get("plan_applied"):
            self.apply_plan(tid)

    def _check_work(self, st: dict, rd: dict) -> None:
        """작업자 확인(8.7): 작업 실행 기록의 워커 행으로 본다. 쉬는 고정 에이전트는 crew_check 만 본다."""
        tid = st["id"]
        row = dispatch.slot_row(self.rows, rd["work"])
        if state.open_attempt(rd) or (row is not None and row["state"] == "retained"):
            self.start_review(tid)  # 리뷰가 retain·시도 기록 뒤 관문이나 리뷰어 띄우기 도중에 끊겼다(6.1 의 0)
            return
        if row is None:
            return
        if row["state"] == "settled":  # worker_done 을 놓쳤다
            self.on_work_done(tid, row["id"], {"outcome": row.get("outcome"), "summary": row.get("summary"),
                                               "report_path": row.get("report_path")})
            return
        if row["state"] != "active":
            return
        verdict = row.get("verdict")
        if verdict == "live":
            self._clear_unknown(tid)
        elif verdict in ("exited", "lost"):
            self._gone(tid, row["id"])
        elif verdict == "unverifiable":
            self._unknown(st, row)

    def _unknown(self, st: dict, row: dict) -> None:
        """생존 모름: 처음 본 시각을 적고 LIVENESS_UNKNOWN_S 넘게 이어지면 decide 한 번. 작업자를 죽이지 않는다."""
        tid = st["id"]
        since = st.get("liveness_unknown_since")
        if not since:
            with state.edit(self.p, tid) as cur:
                cur["liveness_unknown_since"] = now()
            return
        age = age_seconds(since)
        if age is None or age < LIVENESS_UNKNOWN_S or st.get("liveness_escalated"):
            return
        word = row.get("status") or row.get("verdict")
        self.decide("escalation", tid, UNKNOWN_TEXT.format(minutes=int(age // 60), word=word),
                    commands=[self._fix_cmd(st, force=True), f"hteam drop {tid} --force"])
        with state.edit(self.p, tid) as cur:
            cur["liveness_escalated"] = True

    def _check_review(self, st: dict, rd: dict) -> None:
        """reviewing(8.7): 열린 시도가 없으면 decide 전에 끊긴 실패·변조를 한 번 올리고, 띄우지 못한 시도는 리뷰 자식으로
        잇고(6.1 의 0), 리뷰어가 끝났으면 review-finish."""
        from . import review
        tid = st["id"]
        att = state.open_attempt(rd)
        if att is None:
            last = state.latest_attempt(rd)
            err = review.attempt_error(tid, rd["round"], last) if last else None
            if err is not None and st.get("review_failure_asked") != [rd["round"], last["attempt"]]:
                self._review_failure(tid, err, rd["round"], last["attempt"])
            return
        if not att.get("dispatch"):
            self.start_review(tid)
            return
        row = dispatch.slot_row(self.rows, att)
        if row is not None and dispatch.review_ended(row):
            self.finish_review(tid)

    def _dropped_deps(self, st: dict) -> None:
        """pending 의 선행이 dropped 면 decide 한 번(같은 목록이면 다시 올리지 않는다)."""
        from . import approval, tasks
        tid = st["id"]
        gone = tasks.dropped_blockers(approval.Graph(self.p), tid, lambda d: tasks._load_quiet(self.p, d))
        names = sorted(gone, key=state.id_number)
        if not names or st.get("dropped_deps_asked") == names:
            return
        self.decide("escalation", tid, f"선행 태스크 {', '.join(names)} 가 중단(dropped)돼 {tid} 를 시작할 수 없다. 진행하지 "
                    "않으면 drop 하고, 이어 가려면 depends_on 을 고친다", files=self._files(self._grounds(tid)[0]),
                    commands=[f"hteam drop {tid}", f"depends_on 을 고쳐 커밋한 뒤 hteam start {tid}"])
        with state.edit(self.p, tid) as cur:
            cur["dropped_deps_asked"] = names

    def _launch_failed(self, st: dict, rd: dict | None) -> None:
        """launch_failed decide 한 번(라운드·history 길이로). 일괄 승인·보강의 대기 라운드, 실행자·장벽 자식이 살아 있을 때,
        일시 거부(transient)는 올리지 않는다(start-ready 가 다시 넣는다)."""
        from . import approval
        tid = st["id"]
        if not rd or approval.unlaunched(st):
            return
        work = rd["work"]
        if dispatch.busy(st, work) or work.get("transient"):
            return
        mark = [st["round"], len(st.get("history") or [])]
        if st.get("launch_failed_asked") == mark:
            return
        left = [r["id"] for r in self.rows if r.get("title") == work["title"] and r.get("state") in ("launching", "active")]
        workers = f"남은 워커 {len(left)}개({', '.join(left)})" if left else "남은 워커 없음"
        err = work.get("error") or {}
        tail = f" 오류: {err.get('code')}: {str(err.get('message') or '')[:200]}" if err else ""
        self.decide("escalation", tid, f"{tid} r{rd['round']} 실행이 실패했거나 도중에 끊겼다(launch_failed). {workers}.{tail}",
                    commands=[f"hteam start {tid}", f"hteam drop {tid}"])
        with state.edit(self.p, tid) as cur:
            cur["launch_failed_asked"] = mark

    # --- 자리(뒤 단계가 채운다) ---
    def handoff_message(self, m: dict) -> bool:
        """인수인계 Dispatch 메시지면 처리하고 True(설계 8.6 의 인수인계 줄). 메시지를 태스크로 찾기 전에 부른다."""
        from . import crew
        return crew.handoff_message(self, m)

    def crew_done(self, tid: str, did: str) -> None:
        """고정 에이전트의 작업 worker_done(5.9.3 끝): 그 태스크를 맡은 에이전트를 비우고 since_reset 을 센다."""
        from . import crew  # crew 가 이 모듈을 쓴다
        crew.work_done(self.p, tid, did)

    def crew_gone(self, tid: str, did: str) -> None:
        """고정 에이전트 작업 터미널의 exited·lost(5.9.8): 맡은 에이전트(없으면 그 라운드의 에이전트)의 터미널을 정리하고
        잊는다. 뒤의 fix 가 같은 에이전트의 새 세션으로 띄운다(라운드 crew 가 그대로다)."""
        from . import crew
        name = crew.holder(self.p, tid) or crew.round_crew(state.current_round(state.require(self.p, tid)) or {})
        if name:
            crew.forget(self.p, name)

    def on_not_started(self, tid: str, did: str, body: dict | None) -> None:
        """observed not_started(입력 유실 재투입, 5.9.8). 재확인이 남은 resend 를 이을 때는 body 가 None 이다."""
        from . import crew
        crew.not_started(self, tid, did)

    def crew_check(self) -> None:
        """고정 에이전트 터미널 확인(8.7 의 2) 뒤 큐 맞추기(5.9.5). 잊은 에이전트가 맡고 있던 태스크마다 그 Dispatch 의 observed
        exited·lost 와 같은 메시지로 handle 을 부른다(horch 의 같은 관찰이 뒤에 오면 지난 Dispatch 로 무시된다)."""
        from . import crew
        gone = crew.check_terminals(self)
        crew.sync_queues(self.p)
        for tid, did, term, kind in gone:
            body = {"dispatch": did, "kind": kind, "key": kind, "terminal": term, "status": None}
            m = {"id": None, "type": "observed", "sender": "horch", "subject": f"observed {did}",
                 "body": json.dumps(body, ensure_ascii=False), "dispatch": did}
            self.isolated(f"reconcile:{tid}", lambda m=m: self.handle(m))

    def handoff_check(self) -> None:
        """끝나지 않은 인수인계 정리(8.7 의 3)."""
        from . import crew
        crew.handoff_check(self)

    def apply_plan(self, tid: str) -> None:
        """기획 적용(8.9). Task 10 이 채운다."""

    def batch_done(self, tid: str) -> None:
        """묶음 처리(done tester, 8.4). Task 10 이 채운다."""

    def design_step(self) -> None:
        """디자인 단계(8.9). Task 10 이 채운다."""

    def unbatched(self) -> None:
        """묶음 처리 안 된 done tester(8.7 의 6). Task 10 이 채운다."""

    def resume_decisions(self) -> None:
        """끝나지 않은 일괄 승인 결정 이어 하기와 답 파일에만 있는 결정 실행(8.7 의 7). Task 10 이 채운다."""

    def finish_step(self) -> None:
        """마무리(8.4). Task 10 이 채운다."""

    def final_done(self, code: int, out: dict, err: str) -> None:
        """마무리 전체 테스트 자식(키 final)의 결과(8.4). Task 10 이 채운다."""

    def tick(self) -> None:
        """설계 8.5 의 틱 순서. 단계마다 격리한다(reap_jobs·reset_step·view_step 은 그 안에서 항목마다)."""
        self.heartbeat()
        self.isolated("check", self.check_mail)
        done = self.isolated("queue", self.run_queue)
        if done:
            self.isolated("start_ready", self.start_ready)
        self.reap_jobs()
        self.heartbeat()
        self.reset_step()
        self.view_step()
        if self.last_reconcile is None or time.monotonic() - self.last_reconcile >= RECONCILE_S:
            self.last_reconcile = time.monotonic()
            self.isolated("reconcile", self.reconcile)


def _read(path) -> str:
    """자식 출력 파일. 없거나 읽지 못하면 빈 글."""
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _last_json(text: str) -> dict | None:
    """출력의 마지막 JSON 객체 줄(hteam 은 끝에 JSON 한 줄을 쓴다). 없으면 None."""
    for line in reversed(text.strip().split("\n")):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _same_gate_failure(st: dict) -> bool:
    """최근 두 판정 라운드가 모두 hteam 테스트 관문 반려이고 quick 출력 끝이 숫자만 빼고 같다(8.6 의 repeat_test_failure)."""
    from . import review
    judged = [r for r in st["rounds"] if r.get("verdict")]
    if len(judged) < 2:
        return False
    a, b = judged[-2], judged[-1]
    if not all(r.get("review_source") == "hteam" and r.get("prechecks") == [review.GATE_PROBLEM] for r in (a, b)):
        return False

    def tail(r: dict) -> str:  # 걸린 시간·숫자만 다른 같은 실패
        return re.sub(r"\d+(?:\.\d+)?", "N", ((r.get("tests") or {}).get("quick") or {}).get("tail") or "")
    return tail(a) == tail(b)


def _acquire(p) -> dict:
    """drive.pid 를 O_CREAT|O_EXCL 로 만들고 {pid, started} 를 쓴다(설계 8.2 의 3). 살아 있는 같은 프로세스의 파일이면
    drive_running. 죽었거나 읽지 못하는 파일은 지우고 다시 한다(경합으로 PID_TRIES 번 실패하면 drive_running)."""
    p.drive_dir.mkdir(parents=True, exist_ok=True)
    me = procs.me()
    for _ in range(PID_TRIES):
        try:
            fd = os.open(p.drive_pid, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            rec = read_json(p.drive_pid, None)
            if isinstance(rec, dict) and isinstance(rec.get("pid"), int) and procs.record_alive(rec):
                raise HteamError("drive_running", f"hteam drive 가 이미 실행 중이다(pid {rec['pid']})", CONFLICT,
                                 "관제 탭을 확인한다(hteam status 의 drive)") from None
            p.drive_pid.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(me))
        return me
    raise HteamError("drive_running", "drive.pid 를 만들지 못했다(다른 관제와 경합)", CONFLICT,
                     "관제 탭을 확인한다(hteam status 의 drive)")


def _release(p) -> None:
    """drive.pid 가 이 프로세스의 것일 때만 지운다."""
    rec = read_json(p.drive_pid, None)
    if isinstance(rec, dict) and rec.get("pid") == os.getpid():
        p.drive_pid.unlink(missing_ok=True)


def _objective(p) -> str:
    try:
        text = p.project_md.read_text(encoding="utf-8") if p.project_md.exists() else ""
    except (OSError, UnicodeDecodeError):
        text = ""
    return (text.strip().splitlines() or [""])[0][:200] or "herdr-team"


def _horch_error(data: dict) -> str | None:
    if data.get("ok"):
        return None
    return str((data.get("error") or {}).get("code") or "failed")


def _connect(p, d: Drive, term: str, nonce: str) -> tuple[str, str]:
    """Run 연결(설계 8.2 의 4, 0.3.0 의 bind). 시도마다 run.lock 안에서 run-use(없으면 run-create)하고 run.json 에 묶는다.

    이전 소유자가 owner_unverifiable 이면 --force 로 넘겨받는다(drive.pid 잠금이 다른 관제가 없음을 보인다). owner_alive 는
    exit 3, 그 밖의 실패는 BIND_RETRY_S 간격으로 BIND_TRIES 번까지 다시 한다. (mode, run_id)."""
    from .setup import _run_update  # setup 이 이 모듈을 가져오므로 여기서 가져온다

    h = d.horch()
    retry = env_float("HTEAM_BIND_RETRY_S", BIND_RETRY_S)
    result: dict = {}

    def bind(run: dict) -> None:
        mode, data = "rebound", None
        if run.get("run_id"):
            code, data = h.call("run-use", "--id", run["run_id"])
            err = _horch_error(data)
            if err == "owner_unverifiable":
                code, data = h.call("run-use", "--id", run["run_id"], "--force")
                err = _horch_error(data)
            if err == "unknown_run":
                data = None  # Run 이 없어졌다: 새로 만든다
            elif err == "owner_alive":
                raise HteamError("horch_owner_alive", f"run-use 실패: {(data.get('error') or {}).get('message')}",
                                 CONFLICT, "관제 기록과 다른 Run 소유자가 살아 있다. 사용자가 그 터미널을 확인한다",
                                 data={"horch": data})
            elif err:
                raise HteamError(f"horch_{err}", f"run-use 실패: {(data.get('error') or {}).get('message')}",
                                 code or FAIL, (data.get("error") or {}).get("hint") or "", data={"horch": data})
        if data is None:
            mode = "created"
            code, data = h.call("run-create", "--objective", _objective(p))
            err = _horch_error(data)
            if err:
                raise HteamError(f"horch_{err}", f"run-create 실패: {(data.get('error') or {}).get('message')}",
                                 code or FAIL, (data.get("error") or {}).get("hint") or "", data={"horch": data})
        try:
            argv = herdr.get(term).get("argv")
        except HteamError:
            argv = None
        run.update(run_id=data["run"]["id"], drive_terminal=term, bound_nonce=nonce, bound_at=now())
        if argv is not None:
            run["drive_argv"] = argv
        run.pop("launched_at", None)
        result.update(mode=mode, run_id=run["run_id"])

    for n in range(1, BIND_TRIES + 1):
        try:
            _run_update(p, bind)
            return result["mode"], result["run_id"]
        except HteamError as exc:
            if exc.exit_code in (MISSING, CONFLICT) or n == BIND_TRIES:
                raise
            d.log(f"Run 연결 실패({n}/{BIND_TRIES}): {exc.code}: {exc.message}. {retry:g}초 뒤 다시 한다")
            d.heartbeat()
            time.sleep(retry)
            d.heartbeat()
    raise AssertionError("도달하지 않는다")


def _hangup(*_) -> None:
    raise SystemExit(129)


def main(p) -> dict:
    """설계 8.2 의 시작 순서. HTEAM_DRIVE_TICKS(시험)가 있으면 그만큼 틱을 돈 뒤 끝낸다."""
    if os.environ.get("CLAUDECODE"):
        raise HteamError("drive_in_claude", "hteam drive 는 관제 탭에서만 돈다. Claude 세션 안에서는 띄우지 않는다"
                         "(메인은 /herdr-team:up)", USAGE)
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        raise HteamError("no_terminal", "HC_TERMINAL_ID 가 없다. hteam drive 는 Herdr 터미널(관제 탭)에서 돈다", USAGE)
    nonce = os.environ.get("HTEAM_LAUNCH") or ""
    launch = (outbox._run(p).get("pending_launch") or {}).get("nonce")
    if os.environ.get("HTEAM_ROLE") != "drive" or not nonce or nonce != launch:
        raise HteamError("not_drive", "hteam up 이 띄운 관제 터미널이 아니다(HTEAM_ROLE·HTEAM_LAUNCH 가 run.json 의 "
                         "pending_launch 와 다르다)", DENIED, "관제는 메인에서 /herdr-team:up 으로 띄운다")
    config.load(p)
    _acquire(p)
    signal.signal(signal.SIGHUP, _hangup)  # 탭이 닫히면 exit 129(SIGTERM 143 은 cli 가 SystemExit 로 바꾼다)
    try:
        d = Drive(p)
        d.heartbeat()  # Run 연결 동안 hung 으로 보이지 않게(8.2 의 "오래 걸리는 단계 사이")
        mode, run_id = _connect(p, d, term, nonce)
        tab = outbox._run(p).get("team_tab")
        if tab:
            herdr.rename_tab(tab, TITLE)
        try:
            sys.stdout.write(f"\x1b]2;{TITLE}\x07")  # 관제 pane 제목(OSC 2)
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        d.log(f"관제 시작({term}): {mode}")
        d.last_reconcile = time.monotonic()
        d.isolated("reconcile", d.reconcile)  # 시작 재확인
        try:
            limit = int(os.environ.get("HTEAM_DRIVE_TICKS") or 0)
        except ValueError:
            limit = 0
        ticks = 0
        while True:
            d.tick()
            ticks += 1
            if limit and ticks >= limit:
                d.log(f"관제 종료: ticks: {ticks}")
                return {"run_id": run_id, "mode": mode, "ticks": ticks}
            time.sleep(d.idle_seconds())
    except BaseException as exc:
        text = exc.message if isinstance(exc, HteamError) else str(exc)
        Drive(p).log(f"관제 종료: {type(exc).__name__}: {text}")
        raise
    finally:
        _release(p)


def _cmd_drive(args) -> dict:
    return main(find_project(args.root))


def register(sub) -> None:
    sub.add_parser("drive").set_defaults(func=_cmd_drive)
