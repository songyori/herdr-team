"""관제 `hteam drive`(설계 8장, 6단계): 관제 탭의 셸 터미널에서 도는 프로그램이 horch Run 을 갖고 정해진 절차를 돌린다.
판단이 필요한 일은 outbox decide 로 메인에 올린다(8.10).

시작 순서(8.2 의 1–7: 실행 거부, drive.pid 단일 인스턴스, Run 연결, 탭 이름, 시작 재확인), heartbeat 와 생존 판정
(liveness·view), 틱 순서와 단계마다 격리(8.5), decide 쓰기와 표시(8.10), drive.log(8.11), 요청 큐(7.1, queue.run_pending)와
그 틱의 start-ready, 메시지 처리(8.6 의 이벤트 표·review-finish 결과 표·review 자식 결과 표·accept 뒤), 자식 프로세스(8.8),
재확인(8.7, reconcile_task·워커 목록 사본). 고정 에이전트의 worker_done·exited 정리와 재확인의 터미널 확인·큐 맞추기,
리셋 단계·인수인계 Dispatch 메시지·끝나지 않은 인수인계 정리(5.9.7), 입력 유실 재투입(5.9.8)은 crew 모듈에 맡긴다
(5.9.3·5.9.5·8.7 의 2·3). 관제 자동화: 묶음 처리·마무리·`[test]` 확정 질문(8.4), 기획 적용·디자인 단계·보강·관제가
만드는 태스크와 중복 방지(8.9), 끝나지 않은 일괄 승인 결정 이어 하기와 답 파일에만 있는 결정 실행(7.4·11.4, 8.7 의 7).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time

from . import config, dispatch, followups, gitio, herdr, outbox, procs, specs, state, testgate, workspace
from .errors import CONFLICT, DENIED, FAIL, MISSING, TIMEOUT, USAGE, HteamError
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
                "planning_gaps", "unknown_regression", "token_update", "workspace_failed", "merge_conflict")
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
GATE_FULL_NOTE = "테스트 관문 반려: full_if 로 돌린 full 이 통과하지 못했다({file} 의 출력 끝을 본다)"
REPEAT_GATE_TEXT = "같은 {kind} 테스트 실패로 hteam 사전 검사가 두 라운드 연속 반려했다"  # kind 는 quick·full
# worker_question 의 판단 근거 문서(설계 7.7, 있는 것만)
GROUNDS = ("docs/planning/spec.md", "docs/planning/contracts.md", "docs/planning/interview.md", "docs/planning/voice.md")
TEST_CONFIG_CODES = frozenset({"test_unrunnable", "bad_test_config", "plan_unreadable"})
LIVE = ("launching", "active")  # 진행 중인 Dispatch(horch 상태)

# 관제 자동화(설계 8.4·8.9 원문)
JUDGE_KINDS = ("planning_gaps", "unknown_regression", "token_update")  # 마무리를 막는 열린 decide(8.4 의 2)
CONSTRAINTS = "다른 태스크의 소유 경로와 이 태스크 범위 밖은 건드리지 않는다"
REGRESSION_RUN = "이 항목의 실패한 테스트(항목에 적힌 이름)를 직접 돌리는 명령이 통과하고 그 명령과 출력 원문이 보고서에 있다"
REGRESSION_TEST = "`hteam test {tid}` 가 통과한다"  # 확정한 [test] 가 있을 때만. {tid} 는 create_task 가 새 ID 로 바꾼다
REGRESSION_COMMAND = 'hteam task new --role <원인 태스크 직무> --title "회귀 수정: <요약>"'
CLEANUP_ACCEPT = "항목마다 고쳤거나 고치지 않은 이유를 보고서에 적었다"
GAP_COMMANDS = ('hteam scope T-xxx "<추가 범위>"', 'hteam task new --role planner --title "<증분 기획>"')
SUPPLEMENT_CHANGE = ("화면 디자이너의 시스템 추가 제안이다. 제안마다 받아들일지 정해 디자인 시스템에 더하고, 결정과 이유를 "
                     "출처(태스크 ID·라운드)와 함께 docs/design/direction.md 에 적는다.")
SUPPLEMENT_ACCEPT = "제안마다 반영 여부와 이유가 출처와 함께 `docs/design/direction.md` 에 있다"
SUPPLEMENT_OWNS = ["docs/design/system/**", "docs/design/direction.md"]
DIRECTION = "docs/design/direction.md"
DESIGN_QUIET = ("approval_not_ready", "already_asked", "nothing_to_approve", "supplement_needed", "decision_pending",
                "approval_stale")  # 디자인 단계가 조용히 넘기는 design-review 거부(8.9 의 4)
# 결정 이어 하기가 넘기는 거부(7.4). review_busy 는 결정의 fix·accept 가 리뷰 관문의 finish 잠금을 만났을 때다(다음 재확인이 잇는다)
DECISION_QUIET = ("approval_stale", "decision_conflict", "decision_pending", "review_busy")
FINAL_FAILED = "마지막 전체 테스트가 실패했다. 원인 태스크를 정해 회귀 수정 태스크를 만든다"
TEST_FIX_COMMAND = 'hteam task new --role planner --title "[test] 고치기"'
CHANGED_SHOWN = 15  # done 본문의 바뀐 주요 파일 수
CONFIRM_RENDER = {"header": "테스트 확정",
                  "question": "커밋된 [test] 명령을 리뷰 전에 자동으로 돌려도 되는가\n"
                              "예: 확정하면 다음 리뷰부터 quick 이 돌고 묶음 리뷰와 마무리가 full 을 돈다",
                  "options": [{"label": "확정한다 (추천)", "description": "추천 사유: 기획자가 쓴 명령이고 아래에 그대로 보인다"},
                              {"label": "고친다", "description": "[test] 를 고치는 기획 태스크를 만든다"}]}
# 관제 기록 파일의 모양: 키 → (자료형, 늘 두는가). 늘 두지 않는 키는 있을 때만 둔다(8.4 의 final_*)
FINISH_SHAPE = {"batches": (list, True), "rest_done": (bool, True), "reported": (list, True),
                "final_ids": (list, False), "final_failed": (list, False), "final_decide": (str, False)}


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


def _side(path, shape: dict) -> dict:
    """관제 기록 파일(finish·supplement·test-confirm). 깨지면 빈 기록으로 본다(설계 8.9 끝): JSON 객체가 아니면 모두, 키의
    자료형이 틀리면 그 키를 빈 값(늘 두지 않는 키는 없음)으로 본다."""
    raw = read_json(path, None)
    data = raw if isinstance(raw, dict) else {}
    out: dict = {}
    for key, (kind, always) in shape.items():
        if isinstance(data.get(key), kind):
            out[key] = data[key]
        elif always:
            out[key] = kind()
    return out


def confirm_record(p) -> dict:
    """state/drive/test-confirm.json(설계 8.4 끝): {"asked": [{digest, out_id, at, request?}], "escalated": [문구]}. 큐
    test-confirm 의 재실행 막기도 읽는다(7.1)."""
    rec = _side(p.test_confirm_file, {"asked": (list, True), "escalated": (list, True)})
    rec["asked"] = [a for a in rec["asked"] if isinstance(a, dict)]
    return rec


def _started_at(st: dict) -> str | None:
    """history 의 첫 start 사건 시각(done 본문의 "처음 시작한 태스크", 설계 8.4 의 7)."""
    return next((e.get("at") for e in st.get("history") or [] if isinstance(e, dict) and e.get("event") == "start"), None)


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
        # 돌고 있는 자식(설계 8.8): {키: {proc, args, out, err}}. 키는 review:<T>, final, 작업 공간 준비·놓기 slot:<N>
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
            self.decide("escalation", tid, text[:300] or "워커가 done 없이 멈췄다",
                        files=self._task_files(tid, state.require(self.p, tid)))
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
                    files=self._task_files(tid, st),
                    commands=[self._fix_cmd(st, "<원인과 지시>"), f"hteam drop {tid}"])

    def _question(self, tid: str, m: dict) -> None:
        text = str(m.get("body") or "")
        st = state.load(self.p, tid) or {}
        role = st.get("role")
        files = self._task_files(tid, st) + self._files(*GROUNDS, f".herdr-team/roles/{role}.md", ".herdr-team/project.md")
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

    def hc_status(self, did: str) -> dict:
        """그 Dispatch 터미널의 hc 7501 상태(kind·state·msg, 없으면 {}). observed 본문에는 상태 낱말만 있다. 화면은 읽지
        않는다(--lines 0, orch 13.1)."""
        data = self.horch().ok("worker-show", "--dispatch", did, "--lines", "0")
        status = ((data.get("worker") or {}).get("hc") or {}).get("status")
        return status if isinstance(status, dict) else {}

    def _stuck(self, tid: str, did: str, word: str) -> None:
        """observed blocked·error: hc 7501 상태(kind·msg)로 decide."""
        status = self.hc_status(did)
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

    def _work_files(self, st: dict, *rels: str) -> list[str]:
        """decide files 의 태스크 산출물(보고서·리뷰 파일): 그 태스크의 작업 루트에서 찾아 있는 것만, 메인 루트 기준 경로다
        (설계 5.10.2·8.10). 병합 전 작업 공간 태스크면 슬롯 경로(`.herdr-team/state/slots/slot-<N>/<rel>`)라 메인이 그대로 연다."""
        root = workspace.task_root(self.p, st)
        return [(root / r).relative_to(self.p.root).as_posix() for r in rels if (root / r).exists()]

    def _task_files(self, tid: str, st: dict) -> list[str]:
        """태스크 decide 의 근거 파일: 사양(메인 루트), 보고서(그 태스크의 작업 루트, _work_files)."""
        spec, report = self._grounds(tid)
        return self._files(spec) + self._work_files(st, report)

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
                    files=self._work_files(st, review_rel(tid, st["round"])),
                    commands=[self._fix_cmd(st), f"hteam drop {tid}"])

    def hteam_changes(self, tid: str) -> None:
        """hteam 반려(사전 검사·테스트 관문)의 다음(8.6): 같은 관문 실패 두 라운드면 repeat_test_failure, 최대 라운드면
        max_rounds, 아니면 반려 사유 note 로 fix."""
        from . import review
        st = state.require(self.p, tid)
        kind = _same_gate_failure(st)
        if kind:
            self.decide("repeat_test_failure", tid, REPEAT_GATE_TEXT.format(kind=kind),
                        files=self._work_files(st, review_rel(tid, st["round"])),
                        commands=[self._fix_cmd(st), f"hteam drop {tid}"])
            return
        if st["round"] >= self._limit():
            self._max_rounds(st)
            return
        problems = (state.current_round(st) or {}).get("prechecks") or []
        if problems == [review.GATE_PROBLEM]:
            note = GATE_NOTE.format(file=review_rel(tid, st["round"]))
        elif problems == [review.GATE_FULL_PROBLEM]:
            note = GATE_FULL_NOTE.format(file=review_rel(tid, st["round"]))
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
        """관제 판정 경로의 accept. review_busy 면 기다리고(재확인이 다시 본다), 작업 공간 병합 거부는 merge_refused, 그 밖의
        거부는 관제 절차 실패."""
        from . import tasks  # tasks 가 queue 를 거쳐 이 모듈을 쓴다
        try:
            res = tasks.accept(self.p, tid, nowait=True)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            if exc.code in workspace.MERGE_REFUSED:
                self.merge_refused(tid, exc)
            elif exc.code != "review_busy":
                self.procedure_failed(tid, exc)
            return None
        self.after_accept(tid, res)
        return res

    def merge_refused(self, tid: str, exc: HteamError) -> None:
        """작업 공간 병합 거부(설계 5.10.6, 8.10). 태스크는 approved 그대로라 다음 재확인이 다시 병합한다. merge_pending 은 첫
        거부만 로그를 남기고, 첫 거부(merge_wait.since)부터 MERGE_BLOCKED_S 가 지나면 workspace_failed(merge_blocked) 를 한 번
        올린다. merge_blocked·base_moved 는 바로 그 kind 로 한 번 올린다. decide 를 쓴 뒤 merge_wait.asked 에 kind 를 남긴다
        (그 사이 중단되면 다음 재확인이 한 번 더 올릴 수 있지만 잃지 않는다)."""
        kind = "merge_blocked" if exc.code == "merge_pending" else exc.code
        output = exc.data.get("output")
        wait = state.require(self.p, tid).get("merge_wait") or {"since": now(), "asked": []}
        if exc.code == "merge_pending":
            if exc.data.get("first"):
                self.log(f"{tid} 병합 거부: {workspace.first_line(output)[:120]}")
            if (age_seconds(wait["since"]) or 0) <= workspace.MERGE_BLOCKED_S:
                return
            summary = f"{tid} 병합이 10분 넘게 거부됐다: {workspace.first_line(output)}"
        else:
            self.log(f"{tid} 병합 못 함({exc.code}): {exc.message[:120]}")
            summary = exc.message
        if kind in wait["asked"]:
            return
        detail = {k: v for k, v in exc.data.items() if k not in ("first", "tail")}
        tail = {"tail": exc.data["tail"]} if "tail" in exc.data else {}  # 훅이 병합 커밋을 거부했다: git 출력 끝
        self.decide("workspace_failed", tid, summary, detail={**detail, "kind": kind}, **tail)  # 먼저 알린다(잃지 않는다)
        with state.edit(self.p, tid) as cur:
            mark = cur.setdefault("merge_wait", wait)
            mark["asked"] = [*mark.get("asked", []), kind]

    def conflict_decide(self, tid: str, conflict: dict) -> None:
        """decide merge_conflict(설계 5.10.6, 7.7): 충돌 파일을 보이고 fix(기준 병합 라운드) 나 drop 을 묻는다."""
        st = state.require(self.p, tid)
        files = conflict["files"]
        self.decide("merge_conflict", tid, f"기준 브랜치 {st['workspace']['base_branch']} 에 병합하다 충돌했다"
                    f"({len(files)}개 파일: {', '.join(files[:5])}). 되돌렸다", detail=conflict,
                    commands=[self._fix_cmd(st, "<충돌을 어떻게 풀지 사용자 지시>"), f"hteam drop {tid}"])

    def _conflict_asked(self, tid: str, conflict: dict) -> bool:
        """이 충돌(라운드 기록의 merge_conflict)의 decide 가 outbox 에 있나(kind·task·detail 로 가린다)."""
        return any(e.get("type") == "decide" and e.get("kind") == "merge_conflict" and e.get("task") == tid
                   and e.get("detail") == conflict for e in outbox.read_outbox(self.p))

    def after_accept(self, tid: str, res: dict) -> None:
        """accept 뒤(설계 8.6, 관제 판정 경로와 큐 accept 모두): release 실패 progress, 작업 공간 병합 로그·충돌 decide,
        직무·결과별 다음 자리, start-ready, 끝에 슬롯 놓기(release_step)."""
        for warning in res.get("warnings") or []:
            self.progress(f"{tid} 워커 해제 실패: {str(warning)[:200]}")
        if res.get("merge"):
            self.log(f"{tid} 병합 {res['merge'][:7]}")
        elif res.get("merge_conflict"):
            self.log(f"{tid} 병합 충돌: {', '.join(res['merge_conflict']['files'][:5])}")
            self.conflict_decide(tid, res["merge_conflict"])
        role = (state.load(self.p, tid) or {}).get("role")
        if res.get("status") == "done" and role == "planner":
            self.apply_plan(tid)
        elif res.get("status") == "done" and role == "tester":
            self.batch_done(tid)
        elif res.get("status") == "awaiting_user":
            self.design_step()
        self.start_ready()
        self.isolated("slots", self.release_step)

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
        decide 가 한 번 올린다, 8.7) 아니면 관제 절차 실패로 올린다. 그 밖의 오류는 올린다(격리가 받는다). 끝에 늘(오류여도)
        작업 공간 예약의 준비 자식을 띄운다(slot_step, 격리 slots): 이 start-ready 가 새로 쓴 예약도 다음 재확인을 기다리지
        않는다(5.10.3, Task 4 태스크 리뷰 Minor 1). 작업 공간이 꺼져 있으면 slots.json 이 없어 아무것도 하지 않는다."""
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
        finally:
            self.isolated("slots", self.slot_step)

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
        st = state.require(self.p, tid)
        if expect_round is not None:
            tasks._expect_round(tid, st, expect_round)
        args = ["review", tid, *(["--retry"] if retry else []),
                *(["--round", str(expect_round)] if expect_round is not None else []),
                *(["--request", request] if request else [])]
        self.spawn(key, args, rnd=st["round"])
        self.log(f"{tid} 리뷰 시작")
        return {"task": tid, "spawned": True}

    def confirm_test(self, force: bool = False, request: str | None = None) -> dict:
        """`[test]` 확정 질문(설계 8.4 끝 문단, 5.7, 7.1 의 test-confirm). 식별값마다 한 번 올리고 test-confirm.json 에 남긴다.
        force(큐 test-confirm)면 이미 물었어도 올린다. 같은 식별값의 질문이 열려 있으면 force 여도 새로 올리지 않는다.
        request 는 큐 요청 id 로 올린 항목에 남긴다(재실행 막기). force 이고 HEAD 에 [test] 가 없으면 exit 2 no_test_config.
        확정 기록 손상이면 묻지 않고 그 문구마다 decide escalation 한 번."""
        cfg = testgate.require_config(self.p) if force else testgate.load_config(self.p)
        if cfg is None:
            return {"asked": None, "reason": "none"}
        value = testgate.digest(cfg)
        try:
            approved = testgate.is_approved(self.p, value)
        except HteamError as exc:
            if exc.code != "bad_test_approvals":
                raise
            if exc.message not in confirm_record(self.p)["escalated"]:
                self.decide("escalation", None, f"테스트 명령 확정 기록을 읽지 못해 확정 질문을 올리지 않았다: {exc.message}",
                            files=[str(testgate.approvals_path(self.p))])
                rec = confirm_record(self.p)
                rec["escalated"].append(exc.message)
                write_json(self.p.test_confirm_file, rec)
            return {"asked": None, "reason": "bad_test_approvals"}
        if approved and not force:
            return {"asked": None, "reason": "approved"}
        for e in outbox.read_outbox(self.p):
            if e.get("type") == "question" and e.get("test_digest") == value and not self._answered(e["id"]):
                return {"asked": e["id"], "open": True, "digest": value}
        if not force and any(a.get("digest") == value for a in confirm_record(self.p)["asked"]):
            return {"asked": None, "reason": "asked"}
        render = outbox.validate_render(CONFIRM_RENDER, "질문")
        entry = outbox.append(self.p, {"type": "question", "from": "drive", "render": render,
                                       **outbox.test_confirm(render, cfg)})
        rec = confirm_record(self.p)
        rec["asked"].append({"digest": value, "out_id": entry["id"], "at": now(),
                             **({"request": request} if request else {})})
        write_json(self.p.test_confirm_file, rec)
        return {"asked": entry["id"], "digest": value}

    def _answered(self, oid: str) -> bool:
        """답 파일이 있다(outbox 항목이 닫혔다, 설계 7.4·8.10)."""
        return (self.p.answers / f"{oid}.json").exists()

    # --- 자식 프로세스(8.8) ---
    def running(self, key: str) -> bool:
        """그 키의 자식이 아직 거두어지지 않았다(돌고 있거나 끝났지만 이번 틱의 reap_jobs 전)."""
        return key in self.jobs

    def spawn(self, key: str, args: list[str], *, rnd: int | None = None) -> bool:
        """`hteam --root <루트> <args>` 자식을 환경 그대로(관제로 판별된다, 8.2) 띄운다. stdin 은 /dev/null, stdout·stderr 는
        state/drive/jobs/<키의 ":" 를 "-" 로>.out·.err(덮어쓴다). 그 키의 자식이 있으면 띄우지 않고 False. rnd 는 리뷰 자식을
        띄울 때의 태스크 라운드(거둘 때 라운드가 바뀌었으면 결과를 적용하지 않는다, _review_done)."""
        if key in self.jobs:
            return False
        self.p.jobs_dir.mkdir(parents=True, exist_ok=True)
        name = key.replace(":", "-")
        out, err = self.p.jobs_dir / f"{name}.out", self.p.jobs_dir / f"{name}.err"
        argv = [sys.executable, str(PLUGIN_ROOT / "bin" / "hteam"), "--root", str(self.p.root), *args]
        with open(out, "w", encoding="utf-8") as fo, open(err, "w", encoding="utf-8") as fe:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe)
        self.jobs[key] = {"proc": proc, "args": list(args), "out": out, "err": err, "round": rnd}
        return True

    def start_review(self, tid: str, args: list[str] | None = None) -> bool:
        """리뷰 자식(8.8). 그 자식이 있거나 다른 리뷰 실행자(죽은 관제가 남긴 자식 등)가 finish 잠금을 쥐었으면 띄우지 않는다
        (다음 재확인이 다시 본다). 잡히면 놓고 띄운다(리뷰가 다시 잡는다). args 는 자식 인자(기본 `review T`. 미룬 큐
        review --retry 는 원래 인자)."""
        key = f"review:{tid}"
        if key in self.jobs or state.finish_busy(self.p, tid):
            return False
        self.spawn(key, args or ["review", tid], rnd=state.require(self.p, tid)["round"])
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
                self.isolated(f"job:{key}", lambda tid=tid, code=code, out=out, args=job.get("args"),
                              rnd=job.get("round"): self._review_done(tid, code, out, args, rnd))
            elif key == "final":
                self.isolated(f"job:{key}",
                              lambda code=code, out=out, err=err: self.final_done(code, _last_json(out) or {}, err))
            elif key.startswith("slot:"):
                n, (_, step, tid) = int(key.split(":", 1)[1]), job["args"]  # 자식 인자 slot prepare|release T
                done = self._release_done if step == "release" else self._slot_done
                self.isolated(f"job:{key}",
                              lambda n=n, tid=tid, code=code, out=out, done=done: done(n, tid, code, _last_json(out)))

    def _review_done(self, tid: str, code: int, out: str, args: list[str] | None = None, rnd: int | None = None) -> None:
        """리뷰 자식이 끝났다: 도는 동안 올린 decide 의 표시를 먼저 쓰고(그 뒤 결과 처리가 쓰는 새 표시가 이긴다) 결과를 처리한다.
        args(그 자식의 인자)는 잠금 대기 초과로 다시 띄울 때 쓴다. rnd(띄울 때의 라운드)와 지금 라운드가 다르면 결과를 적용하지
        않고 로그만 남긴다: 자식이 끝난 뒤 거두기 전에 큐 fix 가 새 라운드를 열었다(지난 결과가 새 워커를 죽이지 않게)."""
        mark = self.pending_marks.pop(tid, None)
        if mark:
            with state.edit(self.p, tid) as st:
                st["decide"], st["decide_round"] = mark
        if rnd is not None and state.require(self.p, tid)["round"] != rnd:
            self.log(f"{tid} 지난 라운드의 리뷰 결과 무시: r{rnd}")
            return
        self._job_args[tid] = list(args or [])
        try:
            self.on_review_result(tid, code, _last_json(out))
        finally:
            self._job_args.pop(tid, None)

    # --- 작업 공간 준비(5.10.3, 8.8) ---
    def slot_step(self) -> None:
        """start 가 써 둔 예약(preparing, 준비가 끝나지 않은 것)마다 번호 순으로 준비 자식 `hteam slot prepare T`(키 slot:<N>)를
        띄운다. 그 키의 자식이 있거나, 그 태스크에 열린 decide 가 있거나(같은 실패를 되풀이하지 않는다), 슬롯 잠금을 다른
        실행자가 쥐었으면(앞 관제가 남긴 준비 자식이 산다) 띄우지 않는다. 자식이 죽었으면 다음 재확인이 다시 띄운다(준비는 이어
        하기 안전하다)."""
        data = workspace.load(self.p)
        for key in sorted(data["slots"], key=int):
            n = int(key)
            rec = workspace.entry(data, n)
            tid = rec["task"]
            if rec["state"] != "preparing" or rec.get("ready") or not tid or self.running(f"slot:{n}"):
                continue
            if outbox.open_decide(self.p, state.load(self.p, tid) or {}) or workspace.slot_busy(self.p, n):
                continue
            self.spawn(f"slot:{n}", ["slot", "prepare", tid])
            self.log(f"slot-{n} {tid} 준비 시작")

    def _slot_done(self, n: int, tid: str, code: int, data: dict | None) -> None:
        """준비 자식이 끝났다(설계 5.10.3 의 2–4, 5.10.8). 성공이면 start-ready 가 띄운다. setup_failed·branch_exists 는 그
        태스크에(라운드 없는 launch_failed 라 열린 decide 가 start-ready 를 막는다), slot_dirty 는 태스크 없이(그 태스크가 다른
        슬롯을 잡게) decide workspace_failed 를 올린다. 예약이 바뀌었거나 다른 자식이 쥐었으면 로그만 남긴다."""
        err = (data or {}).get("error") or {}
        if code == 0 and data and data.get("ok"):
            self.log(f"slot-{n} {tid} 준비 ready" + ("(setup passed)" if data.get("setup") else ""))
            self.isolated("start_ready", self.start_ready)
            return
        kind = err.get("code")
        if kind in ("slot_locked", "slot_not_reserved"):
            self.log(f"slot-{n} {tid} 준비 건너뜀({kind})")
            return
        if kind not in ("setup_failed", "slot_dirty", "branch_exists"):
            self.procedure_failed(tid, HteamError(kind or "failed", err.get("message") or f"exit {code}: 출력이 없다"))
            return
        self.log(f"slot-{n} {tid} 준비 {kind}")
        if kind == "slot_dirty":
            self.decide("workspace_failed", None, err["message"], commands=[f"hteam slot reset {n}"],
                        detail={"kind": kind, "slot": n, "files": data.get("files") or [], "task": tid})
            self.isolated("start_ready", self.start_ready)
        elif kind == "setup_failed":
            self.decide("workspace_failed", tid, err["message"], files=self._files(data["log"]),
                        commands=[f"hteam start {tid}"], tail=data.get("tail") or "",
                        detail={k: data.get(k) for k in ("kind", "slot", "status", "exit", "log")})
        else:
            self.decide("workspace_failed", tid, err["message"], commands=[f"hteam start {tid}"],
                        detail={"kind": kind, "slot": n, "branch": data.get("branch")})

    # --- 작업 공간 놓기(5.10.6, 8.8) ---
    def release_step(self) -> None:
        """병합했거나 버린 태스크가 아직 쥔 슬롯(workspace.releasable)마다 놓기 자식 `hteam slot release T`(키 slot:<N>)를
        띄운다. 그 키의 자식이 있거나 슬롯 잠금을 다른 실행자가 쥐었으면 띄우지 않는다. 놓기 도중 관제나 자식이 죽어도 다음
        재확인이 잇는다(태스크가 done·dropped 인데 슬롯이 busy)."""
        for n, tid in workspace.releasable(self.p):
            if self.running(f"slot:{n}") or workspace.slot_busy(self.p, n):
                continue
            self.spawn(f"slot:{n}", ["slot", "release", tid])
            self.log(f"slot-{n} {tid} 놓기 시작")

    def _release_done(self, n: int, tid: str, code: int, data: dict | None) -> None:
        """놓기 자식이 끝났다(설계 5.10.6): 로그 `slot-<N> <T> 놓기 <free|dirty>`, teardown 이 통과하지 못했으면 progress,
        dirty 로 남겼으면 progress. slot_locked(다른 실행자가 쥐었다)는 다음 재확인이 본다. 그 밖은 놓기 실패 로그."""
        err = (data or {}).get("error") or {}
        if not (code == 0 and data and data.get("ok")):
            if err.get("code") != "slot_locked":
                said = str(err.get("message") or f"exit {code}: 출력이 없다")
                self.log(f"slot-{n} {tid} 놓기 실패: {err.get('code') or 'failed'}: {said[:120]}")
            return
        if not data.get("state"):  # 그 사이 다른 놓기가 풀었다
            return
        td = data.get("teardown")
        failed = td is not None and td.get("status") != "passed"
        self.log(f"slot-{n} {tid} 놓기 {data['state']}" + (f" (teardown {td['status']})" if failed else ""))
        if failed:
            self.progress(f"slot-{n} {tid} teardown 이 {td['status']}(exit {td.get('exit')})로 끝났다(놓기는 마쳤다). "
                          f"로그: {td.get('log')}")
        if data["state"] != "dirty":
            return
        if data.get("reason") == "not_worktree":
            self.progress(f"slot-{n} 폴더가 git worktree 가 아니어서(.git 이 없거나 깨졌다) {tid} 를 놓지 못하고 dirty 로 "
                          "두었다. 그 폴더에서 teardown 도 git 도 부르지 않았다. 사용자와 폴더를 확인한다. 쓸 것이 없으면 폴더를 "
                          f"치우고 git worktree prune 한 뒤 hteam slot reset {n}")
            return
        merged = (state.load(self.p, tid) or {}).get("status") == "done"
        why = f"{tid} 는 병합했다" if merged else f"{tid} 를 버렸다"
        shown = ", ".join(data.get("dirty", [])[:5]) or "git switch 가 거부했다"
        self.progress(f"slot-{n} 에 커밋 안 된 변경이 남아 dirty 로 두었다({why}): {shown}. 사용자가 버려도 된다고 하면 "
                      f"hteam slot reset {n}")

    def reset_step(self) -> None:
        """고정 에이전트마다 리셋 단계(설계 5.9.7). 설정 순서로, 에이전트마다 reset:<이름> 격리."""
        from . import crew  # crew 가 이 모듈을 쓴다
        cfg = self.isolated("reset", lambda: config.load(self.p))
        if cfg is None:
            return
        for name in cfg.crew:
            self.isolated(f"reset:{name}", lambda name=name: crew.begin_reset(self, cfg, name))

    # --- 리뷰 보기(6.5) ---
    def view_step(self) -> None:
        """리뷰 보기 pane 닫기·열기(설계 6.5, 8.5 의 8). crew.json 의 에이전트마다(그 순서로) view:<이름> 격리. 리뷰 자식이
        리뷰어를 띄운 틱에도 여기서 연다(8.6). 열기·닫기 실패는 로그 한 줄뿐이고 태스크 상태·decide 를 건드리지 않는다."""
        from . import crew  # crew 가 이 모듈을 쓴다
        data = self.isolated("view", lambda: crew.load(self.p))
        for name in data or {}:
            self.isolated(f"view:{name}", lambda name=name: self._view(name))

    def _view(self, name: str) -> None:
        """에이전트 하나(6.5 의 2–4·6·7). 연 보기가 끝나지 않았으면 그대로 둔다(한 탭에 하나. 떼거나 보기 pane 이 죽어도 그
        리뷰 동안은 다시 열지 않는다). 끝났으면 닫고, 닫았으면 같은 단계에서 이 에이전트의 남은 리뷰(가장 먼저 시작한 것)로
        연다. 열지 못하면 pane·terminal null 과 error 를 view 에 남겨 그 시도 동안 다시 열지 않는다."""
        from . import crew
        entry = crew.load(self.p).get(name) or {}
        view = entry.get("view")
        if view:
            if not self._view_ended(view):
                return
            if not self._close_view(name, view):
                return  # 닫지 못했다(로그). 다음 틱에 다시
        found = self._running_review(name)
        if found is None:
            return
        st, rd, att = found
        record = {"pane": None, "terminal": None, "reviewer": att["terminal"], "task": st["id"], "round": rd["round"],
                  "attempt": att["attempt"]}
        try:
            if not entry.get("work_pane"):
                raise HteamError("no_work_pane", "작업 pane 을 모른다", FAIL)
            # 일반 attach(--observe 는 크기를 맞추지 않아 좁은 pane 에서 TUI 가 깨진다, X5). terminal.show 는 쓰지 않는다
            record.update(herdr.split_right(entry["work_pane"], [herdr.hc_path(), "attach", att["terminal"]]))
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            record["error"] = exc.message
            self.log(f"{name} 리뷰 보기 열기 실패: {exc.message}")
        with crew.edit(self.p) as data:
            if data.get(name) is not None and data[name].get("view") is None:
                data[name]["view"] = record

    def _view_ended(self, view: dict) -> bool:
        """보기의 리뷰 시도가 끝났나(6.5 의 3, 하나라도 맞으면): 태스크가 없거나 done·dropped, 지금 라운드가 보기의 라운드가
        아니다, 그 시도가 없거나 결과가 있다, 그 시도나 작업 실행 기록이 취소됐다, 리뷰어 터미널이 finished 이거나 없다.
        hc get 이 다른 까닭으로 실패하면 끝나지 않은 것으로 본다(모르면 그대로 둔다)."""
        st = state.load(self.p, view["task"])
        if st is None or st["status"] in state.CLOSED:
            return True
        rd = state.current_round(st)
        if rd is None or rd["round"] != view["round"]:
            return True
        att = next((a for a in rd["reviews"] if a["attempt"] == view["attempt"]), None)
        if att is None or att.get("result") is not None or att.get("canceled") or rd["work"].get("canceled"):
            return True
        try:
            info = herdr.get(view["reviewer"], timeout=3)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            return exc.data.get("kind") == "not_found"
        return info.get("state") == "finished"

    def _close_view(self, name: str, view: dict) -> bool:
        """보기 닫기(6.5 의 3, 멱등): pane 이 남아 있으면 pane.close, 보기 터미널은 hc rm(이미 없으면 성공) 뒤 view 를 비운다.
        실패하면 로그 한 줄을 남기고 view 를 그대로 둔 채 False(다음 틱에 다시 한다)."""
        from . import crew
        try:
            if view.get("pane") and view.get("terminal") and herdr.pane_of(view["terminal"]):
                herdr.close_pane(view["pane"])
            if view.get("terminal"):
                herdr.rm(view["terminal"])
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            self.log(f"{name} 리뷰 보기 닫기 실패: {exc.message}")
            return False
        with crew.edit(self.p) as data:
            if data.get(name) is not None and data[name].get("view") == view:
                data[name]["view"] = None
        return True

    def _running_review(self, name: str) -> tuple[dict, dict, dict] | None:
        """이 에이전트의 도는 리뷰 (상태, 라운드, 시도)(6.5 의 4): reviewing 이고 지금 라운드를 이 에이전트가 맡았고 열린 시도에
        Dispatch·리뷰어 터미널이 있으며 그 터미널이 live(hc get 실패·live 아님은 후보가 아니다). 여럿이면 가장 먼저 시작한
        리뷰(시도 기준점 시각, 태스크 번호)."""
        from . import crew
        found = []
        for st in state.all_states(self.p):
            rd = state.current_round(st)
            if st["status"] != "reviewing" or crew.round_crew(rd) != name:
                continue
            att = state.open_attempt(rd)
            if att and att.get("dispatch") and att.get("terminal"):
                found.append(((att["baseline"]["at"], state.id_number(st["id"])), st, rd, att))
        for _, st, rd, att in sorted(found, key=lambda item: item[0]):
            try:
                live = herdr.get(att["terminal"], timeout=3).get("state") == "live"
            except HteamError as exc:
                if exc.exit_code == MISSING:
                    raise
                live = False
            if live:
                return st, rd, att
        return None

    # --- 재확인(8.7) ---
    def write_workers(self) -> list[dict]:
        """`horch worker-list` 한 번. 사본 state/drive/workers.json = {at, rows}(메인의 status 가 읽는다, 8.3)."""
        rows = self.horch().workers()
        write_json(self.p.workers_file, {"at": now(), "rows": rows})
        self.rows = rows
        return rows

    def reconcile(self) -> None:
        """재확인(설계 8.7 의 순서). 태스크마다 reconcile:<T> 로 격리한다(한 태스크의 예외가 다른 태스크를 막지 않는다).
        6·7 단계(묶음 처리 → start-ready → 디자인 단계 → 결정 이어 하기 → 마무리)도 단계마다 격리한다."""
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
        self.isolated("slots", self.release_step)  # 끊긴 놓기를 잇는다(설계 5.10.6)
        self.isolated("batches", self.unbatched)  # 8.7 의 6
        self.isolated("start_ready", self.start_ready)  # 8.7 의 7. 끝에 작업 공간 예약의 준비 자식(slot_step, 5.10.3)
        self.isolated("design", self.design_step)
        self.isolated("decisions", self.resume_decisions)
        self.isolated("finish", self.finish_step)

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
                if not resend:
                    self._check_work(st, rd)
                elif self.on_not_started(tid, resend["from"], None):
                    # 재투입 예약은 작업자 확인 대신 잇는다(5.9.8). 입력이 들어간 증거로 지웠으면 같은 재확인에서 작업자
                    # 확인으로 돌아간다(놓친 worker_done 등)
                    st = state.require(self.p, tid)
                    self._check_work(st, state.current_round(st))
        elif status == "reviewing":
            self._check_review(st, rd)
        elif status == "approved":
            self.accept_task(tid)
        elif status == "changes":
            if st.get("queued_fix"):
                return
            conflict = (rd or {}).get("merge_conflict")
            if conflict:  # 병합 충돌(5.10.6): 자동 fix 를 하지 않는다. decide 전에 관제가 죽었으면 여기서 올린다
                if not self._conflict_asked(tid, conflict):
                    self.conflict_decide(tid, conflict)
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

    # --- 고정 에이전트(crew 모듈, 5.9) ---
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

    def on_not_started(self, tid: str, did: str, body: dict | None) -> bool:
        """observed not_started(입력 유실 재투입, 5.9.8). 재확인이 남은 resend 를 이을 때는 body 가 None 이다. 입력이 들어간
        증거로 예약을 지웠으면 True."""
        from . import crew
        return crew.not_started(self, tid, did)

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

    # --- 관제 자동화 기록(8.9 의 중복 방지) ---
    def _finish(self) -> dict:
        """state/drive/finish.json: {batches, rest_done, reported[, final_ids, final_failed, final_decide]}(설계 8.4)."""
        return _side(self.p.finish_file, FINISH_SHAPE)

    def _write_finish(self, fin: dict) -> None:
        write_json(self.p.finish_file, fin)

    def _supplement(self) -> dict:
        """state/drive/supplement.json: {"supplements": [{task, from: {T: 라운드}, handled, token_update}]}(설계 8.9)."""
        data = _side(self.p.supplement_file, {"supplements": (list, True)})
        data["supplements"] = [r for r in data["supplements"]
                               if isinstance(r, dict) and isinstance(r.get("task"), str) and isinstance(r.get("from"), dict)]
        return data

    def _write_supplement(self, data: dict) -> None:
        write_json(self.p.supplement_file, data)

    def _spec_rel(self, tid: str) -> str:
        return str(self.p.spec_path(tid).relative_to(self.p.root))

    def _source_tasks(self, source: str) -> list[str]:
        """사양 `## Change` 첫 줄이 `출처: <source> followups` 인 태스크(후속 다시 만들기를 막는다, 8.9)."""
        return [t for t in specs.list_ids(self.p) if followups.source_of(self.p, t) == source]

    # --- 관제가 만드는 태스크(8.9 의 1–5) ---
    def create_task(self, *, role: str, title: str, target: str, change: str, acceptance: list[str],
                    owns: list[str] | None = None, depends: list[str] | None = None,
                    plan_append: bool = False) -> str | None:
        """`task new` 와 같은 함수로 다음 ID 의 사양과 pending 상태를 만들고(직무·owns 검사. 입력 오류는 사양을 쓰기 전에
        그대로 올린다) 네 절을 채워 덮어쓴다. acceptance 의 `{tid}` 는 새 ID 로 바꾼다. 사양 검사가 실패하면 커밋하지 않고
        decide escalation 뒤 None(덮어쓴 파일은 커밋 안 된 채 남는다). 통과하면 `spec: <T>` 경로 지정 커밋과 로그 뒤 ID.
        시작은 부른 쪽이 start_ready 로 한다."""
        cfg = config.load(self.p)
        tid = specs.new(self.p, cfg, role, title, owns, depends)["id"]
        rel = self._spec_rel(tid)
        lines = [line.replace("{tid}", tid) for line in acceptance]
        body = (f"## Target\n{target}\n\n## Change\n{change}\n\n## Constraints\n{CONSTRAINTS}\n\n## Acceptance\n"
                + "".join(f"- {line}\n" for line in lines))
        write_atomic(self.p.spec_path(tid), specs.render(tid, role, title, body, owns=owns, depends=depends,
                                                         front={"plan": "append"} if plan_append else None))
        try:
            specs.check(self.p, cfg, tid)
        except HteamError as exc:
            self.decide("escalation", tid, f"{tid} 사양 검사 실패로 커밋하지 않았다: {exc.message}", files=[rel])
            return None
        gitio.commit_paths(self.p.root, [rel], f"spec: {tid}")
        self.log(f"{tid} 생성 [{role}] {title}")
        return tid

    # --- 묶음 처리(8.4) ---
    def _make_followups(self, found: dict, *, source: str, key: str, task: str) -> tuple[list[str], int]:
        """후속 만들기(설계 8.4 의 세 목록, 묶음과 묶음 밖이 같이 쓴다). found 는 followups.collect 결과, source 는 출처
        (`T-xxx`·`rest`), key 는 정리 태스크 이름, task 는 decide 의 task. 차례: 회귀 → 후속 → 기획 누락.
        (만든 태스크, 올린 decide 수)."""
        src = f"출처: {source} followups"
        made: list[str] = []
        raised = 0
        for item in found["regressions"]:
            causes = list(dict.fromkeys(ref for ref in re.findall(r"T-\d{3,}", item["text"])
                                        if ref in found["tasks"] and ref != item["task"]))
            if len(causes) != 1:  # 원인이 없거나 둘 이상이면 메인이 정한다
                self.decide("unknown_regression", task, item["text"][:300],
                            files=[review_rel(item["task"], item["round"])], commands=[REGRESSION_COMMAND], source=src)
                raised += 1
                continue
            cause = state.require(self.p, causes[0])
            owns = list(cause.get("owns") or [])  # 시작 때 확정한 owns
            acceptance = [REGRESSION_RUN]
            if testgate.gate_state(self.p)["state"] == "approved":
                acceptance.append(REGRESSION_TEST)
            tid = self.create_task(role=cause["role"], title="회귀 수정: " + item["text"][:40], target=", ".join(owns),
                                   change=f"{src}\n{item['text']}", acceptance=acceptance, owns=owns)
            if tid:
                made.append(tid)
        by_role: dict[str, list[dict]] = {}  # 항목을 낸 리뷰의 태스크 직무(처음 나온 순서)
        for item in found["followups"]:
            by_role.setdefault(state.require(self.p, item["task"])["role"], []).append(item)
        for role, items in by_role.items():
            owners = dict.fromkeys(i["task"] for i in items)
            owns = sorted({o for t in owners for o in state.require(self.p, t).get("owns") or []})
            change = src + "".join(f"\n- {i['id'] or '-'}: {i['text']}" for i in items)
            try:
                tid = self.create_task(role=role, title=f"묶음 정리: {key}", target=", ".join(owns), change=change,
                                       acceptance=[CLEANUP_ACCEPT], owns=owns)
            except HteamError as exc:
                if exc.exit_code == MISSING:
                    raise
                self.decide("escalation", task, f"묶음 정리 태스크({role})를 만들지 못했다: {exc.code}: {exc.message}",
                            files=sorted({review_rel(i["task"], i["round"]) for i in items}), items=items, source=src)
                raised += 1
                continue
            if tid:
                made.append(tid)
        gaps = found["planning_gaps"]
        if gaps:
            self.decide("planning_gaps", task, f"기획 누락 {len(gaps)}건: " + "; ".join(g["text"][:60] for g in gaps),
                        files=sorted({review_rel(g["task"], g["round"]) for g in gaps}), commands=GAP_COMMANDS,
                        items=gaps, source=src)
            raised += 1
        return made, raised

    def batch_done(self, tid: str) -> None:
        """묶음 처리(설계 8.4, done tester): 같은 묶음은 한 번(finish.json batches). 고정 에이전트 리셋 표시가 후속 태스크보다
        먼저다(orca §17 P2-4). `출처: <T> followups` 태스크가 아직 없을 때만 후속을 만든다. 그 뒤 batches 에 더하고 progress.
        도중에 죽으면 batches 에 없어 재확인이 다시 한다(표시는 멱등, 만든 후속은 출처 줄로 다시 만들지 않는다)."""
        from . import crew  # crew 가 이 모듈을 쓴다
        if tid in self._finish()["batches"]:
            return
        marked = crew.mark_batch_reset(self.p)
        made: list[str] = []
        if not self._source_tasks(tid):
            key = specs.load(self.p, tid).front.get("plan_key") or tid
            made, _ = self._make_followups(followups.collect(self.p, followups.group_members(self.p, tid)),
                                           source=tid, key=key, task=tid)
        fin = self._finish()
        fin["batches"].append(tid)
        self._write_finish(fin)
        self.progress(f"묶음 완료: {tid}" + (f". 리셋할 에이전트: {', '.join(marked)}" if marked else ""))
        if made:
            self.start_ready()

    def unbatched(self) -> None:
        """재확인의 묶음 처리(8.7 의 6): finish.json batches 에 없는 done tester(ID 순)."""
        done = self._finish()["batches"]
        for st in state.all_states(self.p):
            if st.get("role") == testgate.TESTER_ROLE and st["status"] == "done" and st["id"] not in done:
                self.batch_done(st["id"])

    # --- 마무리(8.4) ---
    def finish_step(self) -> None:
        """마무리(설계 8.4 의 1–7): 모든 태스크가 끝났고 판단을 기다리는 decide 가 없고 이 태스크 묶음으로 아직 알리지 않았으면,
        묶음 밖 후속(전역 한 번) → 마지막 전체 테스트 자식(확정한 [test]) 또는 확정 질문 → done. 읽지 못하는 상태 파일이
        있으면 끝났는지 모르므로 보류한다(손상을 없는 태스크로 보지 않는다)."""
        states = state.all_states(self.p)
        if not states or any(s["status"] not in state.CLOSED for s in states) or self.running("final"):
            return
        bad = state.unreadable_ids(self.p)
        if bad:  # 읽히는 태스크가 모두 끝났을 때만 알린다(진행 중에는 재확인마다 같은 줄을 남기지 않는다)
            self.log(f"마무리 보류: 상태 파일을 읽을 수 없다: {', '.join(self.p.state_path(t).name for t in bad)}")
            return
        if any(e.get("type") == "decide" and e.get("kind") in JUDGE_KINDS and not self._answered(e["id"])
               for e in outbox.read_outbox(self.p)):
            return
        ids = [s["id"] for s in states]
        fin = self._finish()
        if fin["reported"] == ids:
            return
        if "final_decide" in fin:  # 앞 전체 테스트 실패로 올린 decide 에 답하기 전에는 다시 돌리지 않는다
            if not self._answered(fin["final_decide"]):
                return
            fin.pop("final_failed", None)
            del fin["final_decide"]
            self._write_finish(fin)
        if not fin["rest_done"] and not self._source_tasks("rest"):
            fin["rest_done"] = True  # 먼저 쓴다(전역 한 번)
            self._write_finish(fin)
            made, raised = self._make_followups(followups.collect(self.p, followups.rest_members(self.p)),
                                                source="rest", key="rest", task="rest")
            if made:
                self.start_ready()
            if made or raised:  # 새 태스크가 끝나거나 판단이 온 뒤 다시 온다
                return
        gate = testgate.gate_state(self.p)["state"]
        if gate in ("approved", "error"):  # error(형식·확정 기록)는 자식이 exit 코드로 알린다
            fin = self._finish()
            fin["final_ids"] = ids
            self._write_finish(fin)
            self.spawn("final", ["test", "--full"])
            self.log("마지막 전체 테스트 시작")
            return
        if gate == "unapproved":
            self.confirm_test()
            return
        self._report(states)

    def final_done(self, code: int, out: dict, err: str) -> None:
        """마지막 전체 테스트 자식의 결과(설계 8.4 의 6). out 은 자식 stdout 의 마지막 JSON 객체({} 일 수 있다), err 는
        stderr 글. 도는 동안 태스크가 바뀌었으면(끝나지 않은 태스크나 읽지 못하는 상태 파일이 있거나 final_ids 와 다르다)
        결과를 버린다."""
        states = state.all_states(self.p)
        ids = [s["id"] for s in states]
        fin = self._finish()
        moved = (any(s["status"] not in state.CLOSED for s in states) or bool(state.unreadable_ids(self.p))
                 or fin.get("final_ids", ids) != ids)
        if fin.pop("final_ids", None) is not None:
            self._write_finish(fin)
        if moved:
            self.log("마지막 전체 테스트 결과를 버린다(그 사이 태스크가 바뀌었다)")
            return
        error = out.get("error") or {}
        ecode, message = error.get("code"), str(error.get("message") or "")
        if code == 0:
            status, seconds = out.get("status"), out.get("seconds")
            self._report(states, f"마지막 전체 테스트: {status} ({seconds:g}초)")
            return
        if code == TIMEOUT:
            self.log("전체 테스트 잠금 대기 초과. 다음 확인 때 다시 한다")
            return
        if code == CONFLICT and ecode in ("no_free_slot", "slot_locked"):  # worktree 모드(5.10.7): 슬롯이 비면 다시 한다
            self.log("마지막 전체 테스트: 빈 슬롯이 없어 다음 확인 때 다시 한다")
            return
        if code == USAGE and ecode == "test_unapproved":
            self.confirm_test()
            return
        if ecode in ("setup_failed", "slot_dirty"):  # worktree 모드의 슬롯 준비 실패(5.10.7). 답하기 전에는 다시 돌리지 않는다
            logs = self._files(out["log"]) if out.get("log") else []
            oid = self.decide("workspace_failed", None, message, files=logs, tail=out.get("tail") or "",
                              detail={k: out.get(k) for k in ("kind", "slot", "status", "exit", "log", "reason")
                                      if out.get(k) is not None})
        elif code == FAIL and ecode == "bad_test_approvals":  # 8.6 리뷰 자식 표와 같다. 답하기 전에는 다시 돌리지 않는다
            oid = self.decide("escalation", None, f"마지막 전체 테스트를 돌리지 못했다: {message}")
        elif code == FAIL:
            oid = self.decide("unknown_regression", None, FINAL_FAILED, files=[out["log"]] if out.get("log") else [],
                              tail=out.get("tail") or message, source="출처: final followups")
        else:  # 2 의 다른 code, 12·신호 같은 나머지
            said = err.strip()[-300:] or message
            oid = self.decide("test_config", None, f"전체 테스트를 돌리지 못했다(exit {code}): {said}",
                              files=[testgate.PLAN_FILE], commands=[TEST_FIX_COMMAND])
        fin = self._finish()
        fin.update(final_failed=ids, final_decide=oid)
        self._write_finish(fin)

    def _report(self, states: list[dict], last: str | None = None) -> None:
        """done(설계 8.4 의 7): 태스크마다 한 줄, 바뀐 주요 파일, 마지막 전체 테스트 줄. 쓴 뒤 reported 를 적는다."""
        lines = ["모든 태스크가 끝났다."]
        for st in states:
            try:
                title = specs.load(self.p, st["id"]).title
            except HteamError:
                title = st["id"]
            verdict = (state.current_round(st) or {}).get("verdict") or "-"
            lines.append(f"- {st['id']} [{st.get('role')}] {title}: {st['status']}, r{st['round']} {verdict}")
        changed = self._changed_files(states)
        if changed:
            lines.append("바뀐 주요 파일: " + ", ".join(changed[:CHANGED_SHOWN])
                         + (" …" if len(changed) > CHANGED_SHOWN else ""))
        if last:
            lines.append(last)
        outbox.append(self.p, {"type": "done", "from": "drive", "body": "\n".join(lines)})
        fin = self._finish()
        fin["reported"] = [st["id"] for st in states]
        self._write_finish(fin)

    def _changed_files(self, states: list[dict]) -> list[str]:
        """처음 시작한 태스크(history 첫 start 시각, 같으면 번호 순)의 base 부터 HEAD 까지 바뀐 경로(프로젝트 기준)에서
        `.herdr-team/` 아래를 뺀 것(orca §17 P3-12)."""
        based = [st for st in states if st.get("base")]
        if not based:
            return []
        first = min(based, key=lambda st: (_started_at(st) is None, _started_at(st) or "", state.id_number(st["id"])))
        prefix = gitio.top_prefix(self.p.root)
        names = [n[len(prefix):] for n in gitio.diff_names(self.p.root, first["base"], "HEAD") if n.startswith(prefix)]
        return [n for n in names if not n.startswith(".herdr-team/")]

    # --- 기획 적용(8.9) ---
    def apply_plan(self, tid: str) -> None:
        """planner 태스크가 done(설계 8.9): append(front matter `plan: append` 이거나 이미 적용한 계획이 있다, orca f4ebe86)로
        plan apply. 거부면 기획 수정 태스크. 어느 경우든 plan_applied 를 쓰고 start-ready. 이미 적용했으면 아무것도 안 한다."""
        from . import plan
        st = state.load(self.p, tid)
        if st is None or st.get("plan_applied"):
            return
        prior = read_json(self.p.plan_file, None)
        append = (specs.load(self.p, tid).front.get("plan") == "append"
                  or bool(isinstance(prior, dict) and prior.get("tasks")))
        try:
            res = plan.apply(self.p, config.load(self.p), append)
        except HteamError as exc:
            if exc.exit_code == MISSING:
                raise
            lines = [f"hteam plan apply{' --append' if append else ''} 가 거부했다. 오류 원문:", f"{exc.code}: {exc.message}",
                     *(f"- {e}" for e in exc.data.get("errors") or []), "기존 docs/planning/ 을 읽고 이 오류만 고친다."]
            self.create_task(role="planner", title="tasks.toml 고치기", target=testgate.PLAN_FILE, change="\n".join(lines),
                             acceptance=["`hteam plan check` 가 통과한다"], plan_append=append)
        else:
            parts = []
            for item in res["applied"]:
                sp = specs.load(self.p, item["id"])
                parts.append(f"{sp.id} [{sp.role}] {sp.title}" + (f" ← {', '.join(sp.depends_on)}" if sp.depends_on else ""))
            self.progress("기획 적용: " + "; ".join(parts) if parts else f"기획 적용: {tid} 가 새 태스크를 더하지 않았다")
        with state.edit(self.p, tid) as cur:
            cur["plan_applied"] = True
        self.start_ready()

    # --- 디자인 단계와 보강(8.9, 11.4) ---
    def design_step(self) -> None:
        """디자인 단계(설계 8.9 의 1–4): 승인 직무 태스크에 awaiting_user 가 있고 진행 중이거나 곧 시작할 것(대기열의 수정
        포함)이 없으면 보강을 먼저 하고, 보강할 것이 없으면 design-review(처리한 것으로 본 제안은 skip). 기다리는 거부는
        조용히 넘긴다."""
        from . import approval  # approval 이 queue 를 거쳐 이 모듈을 쓴다
        cfg = config.load(self.p)
        states = state.all_states(self.p)
        mine = [st for st in states if cfg.is_approval(st.get("role"))]
        if not any(st["status"] == "awaiting_user" for st in mine):
            return
        v = approval.view(self.p, cfg, states)
        if v["blockers"] or any(st.get("queued_fix") for st in mine):
            return
        skip = self._supplement_step(cfg, v["supplement"])
        if skip is None:
            return
        try:
            res = approval.design_review(self.p, skip=skip)
        except HteamError as exc:
            if exc.exit_code == CONFLICT and exc.code in DESIGN_QUIET:
                return
            raise
        self.log(f"디자인 승인 질문 {res['id']}: {', '.join(t['task'] for t in res['tasks'])}")

    def _supplement_step(self, cfg, proposals: list[dict]) -> frozenset | None:
        """보강 진행(설계 8.9, supplement.json). 끝나지 않은 보강을 먼저 잇는다: done 이면 기록한 라운드 그대로 awaiting_user 인
        화면마다 `fix --supplement`(화면 먼저, 기록은 나중, orca 449e56f), dropped 면 처리한 것으로 둔다, 진행 중이면 기다린다.
        그다음 proposals(approval.view 의 supplement) 가운데 처리한 것으로 볼 것(빈 제안, direction.md 에 `<T> r<n>`, 기록의
        from)을 빼고 남으면 보강 태스크와 기록을 만들고 UI 기반을 처리한다. 기다리거나 무언가를 했으면 None, 아니면 skip."""
        from . import tasks  # tasks 가 queue 를 거쳐 이 모듈을 쓴다
        data = self._supplement()
        for rec in data["supplements"]:
            if rec.get("handled"):
                continue
            status = (state.load(self.p, rec["task"]) or {}).get("status")
            if status == "done":
                for screen, rnd in rec["from"].items():
                    cur = state.load(self.p, screen)
                    if cur and cur["status"] == "awaiting_user" and cur["round"] == rnd:
                        try:  # 관제는 finish 잠금을 기다리지 않는다. 보강 후행의 대기 라운드 fix 는 잇지 않는다(13장 한계)
                            tasks.fix(self.p, screen, note=None, supplement=rec["task"], force_round=False, cli={},
                                      nowait=True)
                        except HteamError as exc:
                            if exc.code == "review_busy":
                                return None  # 기록하지 않고 다음 재확인에(고친 화면은 라운드가 올라 건너뛴다)
                            raise
                rec["handled"] = True
                self._write_supplement(data)
                self.start_ready()
                return None  # 고친 화면이 다시 awaiting_user 가 될 때까지
            if status == "dropped":  # 다시 만들지 않는다(승인 질문으로 간다)
                rec["handled"] = True
                self._write_supplement(data)
                continue
            return None  # 보강 중: 기다린다
        try:
            direction = (self.p.root / DIRECTION).read_text(encoding="utf-8")
        except FileNotFoundError:
            direction = ""
        recorded = {(t, n) for rec in data["supplements"] for t, n in rec["from"].items()}
        skip: set[tuple[str, int]] = set()
        left: list[tuple[dict, list[str]]] = []
        for s in proposals:
            if s.get("error"):  # 보고서를 읽지 못했다: design-review 가 unreadable_report 로 알린다
                continue
            mark = (s["task"], s["round"])
            lines = [line.strip() for line in (s.get("proposal") or "").splitlines() if line.strip()]
            bare = [line[2:] if line.startswith(("- ", "* ")) else line for line in lines]
            if (all(followups.is_empty(x) for x in bare) or mark in recorded
                    or re.search(re.escape(s["task"]) + rf" r{s['round']}(?!\d)", direction)):
                skip.add(mark)
            else:
                left.append((s, lines))
        if not left:
            return frozenset(skip)
        props = [f"- {s['task']} r{s['round']}: {' '.join(lines)}" for s, lines in left]
        sid = self.create_task(role="director", title=f"디자인 시스템 보강: {', '.join(s['task'] for s, _ in left)} 제안",
                               target=", ".join(SUPPLEMENT_OWNS), change=SUPPLEMENT_CHANGE + "".join(f"\n{x}" for x in props),
                               acceptance=[SUPPLEMENT_ACCEPT], owns=list(SUPPLEMENT_OWNS))
        if sid is None:
            return None
        rec = {"task": sid, "from": {s["task"]: s["round"] for s, _ in left}, "handled": False, "token_update": None}
        data["supplements"].append(rec)
        self._write_supplement(data)
        self._ui_foundation(cfg, data, rec, props)
        self.start_ready()
        return None

    def _ui_foundation(self, cfg, data: dict, rec: dict, props: list[str]) -> None:
        """UI 기반 처리(설계 8.9·11.4, 보강 태스크를 만든 직후 한 번). `plan_key: ui-foundation` 태스크 U 가 pending 이면 U 가
        보강을 기다리게 한다. U 가 dropped 이거나 U 에 직접 의존하는 태스크가 시작했으면 사양을 바꾸지 않고 token_update
        decide(task U: 열린 decide 가 보강 태스크를 막지 않게). 그 밖에는 토큰 갱신 태스크를 만들어 U 에 직접 의존하는 pending
        태스크가 그것을 기다리게 한다. 시작함 = 상태가 pending·dropped 아님(상태가 없으면 pending)."""
        sid = rec["task"]
        found = {}
        for t in specs.list_ids(self.p):
            try:
                found[t] = specs.load(self.p, t)
            except HteamError:
                continue
        ui = next((sp for sp in found.values() if sp.front.get("plan_key") == "ui-foundation"), None)
        if ui is None:
            return

        def status(t: str) -> str:
            return (state.load(self.p, t) or {}).get("status") or "pending"

        deps = [t for t, sp in found.items() if ui.id in sp.depends_on]  # 토큰 갱신 태스크를 만들기 전에 센다
        ust = state.load(self.p, ui.id) or {}
        ustatus = ust.get("status") or "pending"
        if ustatus == "pending":
            if specs.add_depends(self.p, ui.id, sid):
                gitio.commit_paths(self.p.root, [self._spec_rel(ui.id)], f"spec: {ui.id}")
            return
        if ustatus == "dropped" or any(status(t) not in ("pending", "dropped") for t in deps):
            rec["token_update"] = self.decide(
                "token_update", ui.id, f"디자인 시스템 보강 {sid} 을 시작한다. UI 기반 개발 태스크에 바뀔 토큰을 반영할지 정한다",
                files=[DIRECTION], commands=['hteam task new --role developer --title "토큰 갱신 반영: <요약>"',
                                             f'hteam scope {ui.id} "<바뀐 토큰>"'])
            self._write_supplement(data)
            return
        owns = list(ust.get("owns") or []) or specs.owns_of(cfg, ui)
        token = self.create_task(
            role="developer", title=f"토큰 갱신: {sid} 반영", target=", ".join(owns),
            change=f"디자인 시스템 보강 {sid} 의 결정({DIRECTION})에 따라 바뀐 토큰·컴포넌트를 UI 기반 코드에 반영한다.\n"
                   + "\n".join(props),
            acceptance=[f"보강 {sid} 의 결정 가운데 반영한 토큰과 반영하지 않은 이유가 보고서에 있다"], owns=owns,
            depends=[sid, ui.id])
        if token is None:
            return
        changed = [t for t in deps if status(t) == "pending" and specs.add_depends(self.p, t, token)]
        if changed:
            gitio.commit_paths(self.p.root, [self._spec_rel(t) for t in changed], f"spec: {', '.join(changed)}")

    # --- 결정 이어 하기(7.4, 11.4, 8.7 의 7) ---
    def resume_decisions(self) -> None:
        """일괄 승인 묶음마다: 결정이 기록돼 있고 끝나지 않았으면 기록대로 잇는다. 결정이 없고 답 파일에만 결정이 있으면(큐
        제출 실패·메인 사망) 그것을 실행한다. 결정 없는 답은 둔다. 기다리는 거부는 넘긴다(다음 재확인이 다시 본다)."""
        from . import approval  # approval 이 queue 를 거쳐 이 모듈을 쓴다
        for b in approval.load(self.p)["batches"]:
            oid = b.get("id")
            if not oid:
                continue
            d = b.get("decision")
            if d is not None and d.get("done"):
                continue
            text = None
            if d is None:
                ans = outbox.answer_strict(self.p, oid)
                decision = ans.get("decision") if isinstance(ans, dict) else None
                if not isinstance(decision, dict):
                    continue
                text = json.dumps({"fix": decision.get("fix") or {}}, ensure_ascii=False)
            try:
                approval.decide(self.p, oid, text, nowait=True)
            except HteamError as exc:
                if exc.exit_code == CONFLICT and exc.code in DECISION_QUIET:
                    continue
                raise

    def tick(self) -> None:
        """설계 8.5 의 틱 순서. 단계마다 격리한다(reap_jobs·reset_step·view_step 은 그 안에서 항목마다)."""
        self.heartbeat()
        self.isolated("check", self.check_mail)
        done = self.isolated("queue", self.run_queue)
        if done:
            self.isolated("start_ready", self.start_ready)  # 끝에 slot_step
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


def _same_gate_failure(st: dict) -> str | None:
    """최근 두 판정 라운드가 모두 같은 종류(quick, full_if 의 full)의 hteam 테스트 관문 반려이고 그 출력 끝이 숫자만 빼고
    같으면 그 종류(8.6 의 repeat_test_failure, 5.7 7단계). 아니면 None(quick 과 full 이 섞이면 같은 실패가 아니다)."""
    from . import review
    judged = [r for r in st["rounds"] if r.get("verdict")]
    if len(judged) < 2:
        return None
    a, b = judged[-2], judged[-1]
    kind = next((k for k, problem in (("quick", review.GATE_PROBLEM), ("full", review.GATE_FULL_PROBLEM))
                 if all(r.get("review_source") == "hteam" and r.get("prechecks") == [problem] for r in (a, b))), None)
    if kind is None:
        return None

    def tail(r: dict) -> str:  # 걸린 시간·숫자만 다른 같은 실패
        return re.sub(r"\d+(?:\.\d+)?", "N", ((r.get("tests") or {}).get(kind) or {}).get("tail") or "")
    return kind if tail(a) == tail(b) else None


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
        d.heartbeat()  # Run 연결 동안 hung 으로 보이지 않게(8.2 의 "Run 연결 앞과 재시도 앞뒤")
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
