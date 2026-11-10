"""관제 `hteam drive`(설계 8장, 6단계): 관제 탭의 셸 터미널에서 도는 프로그램이 horch Run 을 갖고 정해진 절차를 돌린다.
판단이 필요한 일은 outbox decide 로 메인에 올린다(8.10).

시작 순서(8.2 의 1–7: 실행 거부, drive.pid 단일 인스턴스, Run 연결, 탭 이름, 시작 재확인), heartbeat 와 생존 판정
(liveness·view), 틱 순서와 단계마다 격리(8.5), decide 쓰기(8.10), drive.log(8.11), 요청 큐(7.1, queue.run_pending)와
그 틱의 start-ready. 나머지 틱 단계의 몸통(메시지 처리 8.6, 자식 8.8, 리셋 5.9.7, 보기 6.5, 재확인 8.7)은 뒤 단계가 채운다.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import time

from . import config, herdr, outbox, procs, state
from .errors import CONFLICT, DENIED, FAIL, MISSING, USAGE, HteamError
from .horch import Horch
from .paths import find_project
from .util import age_seconds, env_float, local_age, local_now, now, read_json, write_atomic

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
TASK_RE = re.compile(r"^T-\d{3,}$")


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
    """관제 한 프로세스. 틱(설계 8.5)과 격리·decide·로그를 갖는다. 단계 몸통은 뒤 단계가 채운다."""

    def __init__(self, p):
        self.p = p
        self.last_reconcile: float | None = None  # monotonic. 처음은 None(첫 틱이 재확인한다)
        self.failing = False  # 메일 확인이 실패 중이다(틱 사이를 IDLE_FAIL_S 로 늘린다)
        self._ack: int | None = None  # 다음 check 에 줄 지난 delivery
        self._raised: set[tuple[str, str]] = set()  # 올린 격리 실패(키, 문구). 이 프로세스 안의 기억
        self._failed: set[tuple[str | None, str]] = set()  # 올린 관제 절차 실패(태스크, 문구). 이 프로세스 안의 기억
        self._horch: Horch | None = None

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
        """outbox decide 줄을 쓰고 out id 를 돌려준다. 태스크 ID 이고 상태가 있으면 그 태스크에 decide·decide_round 를 쓴다."""
        if kind not in DECIDE_KINDS:
            raise HteamError("bad_decide_kind", f"모르는 decide 종류다: {kind}", USAGE)
        summary = summary or "(요약 없음)"
        entry = outbox.append(self.p, {"type": "decide", "from": "drive", "kind": kind, "task": task,
                                       "summary": summary, "files": list(files), "commands": list(commands),
                                       "body": f"[{kind}] {task or '-'}: {summary}", **extra})
        if isinstance(task, str) and TASK_RE.match(task) and self.p.state_path(task).exists():
            with state.edit(self.p, task) as st:
                st["decide"] = entry["id"]
                st["decide_round"] = st["round"]
        self.log(f"decide {entry['id']} {kind} {task or '-'}: {summary[:80]}")
        return entry["id"]

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
        """`horch check --wait` 한 번. 처리한 묶음은 다음 check 의 --ack 로 확인한다(처리가 실패해도)."""
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
        self._ack = data.get("delivery")
        for m in data.get("messages") or []:
            self.isolated(f"msg:{m.get('id')}", lambda m=m: self.handle(m), lambda exc, m=m: self._message_failure(m, exc))

    @staticmethod
    def _message_failure(m: dict, exc: Exception):
        """처리하지 못한 메시지는 다시 오지 않으므로 원문을 담아 올린다(설계 8.5)."""
        said = (f"메시지 {m.get('id')} 처리 실패: {type(exc).__name__}: {exc} "
                f"[type={m.get('type')} dispatch={m.get('dispatch') or '-'}] {str(m.get('body') or '')[:200]}")
        if m.get("type") == "question":
            return said, {"question": m.get("body"), "message_id": m.get("id")}
        return said

    def handle(self, message: dict) -> None:
        """메시지 처리(설계 8.6). Task 6 이 채운다."""

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
        """관제가 리뷰를 돌린다(설계 8.8). 지금은 바로 부른다. Task 6 이 자식 프로세스로 바꾼다."""
        from . import review  # review 가 queue 를 거쳐 이 모듈을 쓴다
        return review.review(self.p, tid, retry=retry, expect_round=expect_round, request=request)

    def confirm_test(self, force: bool = False, request: str | None = None) -> dict:
        """`[test]` 확정 질문 올리기(설계 8.4, test-confirm 7.1). Task 10 이 채운다."""
        return {"asked": None}

    def reap_jobs(self) -> None:
        """끝난 자식 처리(설계 8.8, 자식마다 job:<키> 격리). Task 6 이 채운다."""

    def reset_step(self) -> None:
        """고정 에이전트마다 리셋 단계(설계 5.9.7, 에이전트마다 reset:<이름> 격리). Task 8 이 채운다."""

    def view_step(self) -> None:
        """리뷰 보기 pane 닫기·열기(설계 6.5, 에이전트마다 view:<이름> 격리). Task 9 가 채운다."""

    def reconcile(self) -> None:
        """재확인(설계 8.7). Task 6·10 이 채운다."""

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
