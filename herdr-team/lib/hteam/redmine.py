"""Redmine 연동(설계 8.12, 7단계): 관제의 사건 큐, 이슈를 닫는 때, 전송 자식 `hteam redmine-sync`, 키 읽기·가리기,
status 요약과 doctor 점검.

선택 기능이다: config.toml 에 [redmine] 이 있을 때만 켜지고, 태스크 사양에 issue 가 있을 때만 그 이슈를 바꾼다. 관제는
사건마다 `state/redmine/queue/<순번>.json` 을 원자적으로 쓰기만 하고(enqueue), HTTP 는 전송 자식 하나가 이 모듈에서만
한다(sync). 키는 전송 자식과 doctor 만 읽고(read_key) 큐·로그·outbox·프롬프트·오류 글에 쓰지 않는다(오류 글은 mask).

잠금: 순번은 `state/redmine/queue.lock` 안에서 정하고 그 안에서 다른 잠금을 잡지 않는다. 전송자는 실행 내내
`state/redmine/sync.lock` 을 비차단으로 쥔다(못 쥐면 보내지 않고 busy). sync.lock 을 쥔 채 슬롯·프로젝트·태스크 잠금을
잡지 않는다.

approval·review·workspace 는 함수 안에서 가져온다(approval 이 tasks 를 쓰고 tasks.run_work 가 이 모듈을 쓴다)."""
from __future__ import annotations

import fcntl
import http.client
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import config, gitio, roles, specs, state, testgate
from .errors import USAGE, HteamError
from .paths import find_project, report_rel, review_rel
from .util import age_seconds, flock, now, read_json, write_atomic, write_json

# 사건 → [redmine].status 의 키(None 은 상태를 바꾸지 않고 노트만 보낸다, 설계 8.12 표)
EVENTS = {"start": "start", "done": "done", "changes": "changes", "approve": None, "merged": None, "closed": "closed",
          "drop": None}
RETRY_S = (60, 120, 300, 600)  # 연결 실패·5xx 를 다시 보내는 간격(그 뒤는 600)
GIVE_UP_S = 86400  # 이보다 오래된 항목은 다시 보내지 않고 failed 로 옮긴다
TIMEOUT_S = 10  # PUT 하나
DOCTOR_TIMEOUT_S = 5  # doctor 의 GET /users/current.json
SUMMARY_MAX = 300  # done 노트의 요약
P1_LINES = 5  # changes 노트의 막는 지적 줄 수
P1_WIDTH = 200  # 줄마다
ERROR_WIDTH = 200  # 오류 글(가린 뒤 자른다)
MASK = "***"
BUSY_TEXT = "다른 hteam redmine-sync 가 보내는 중이라 보내지 않았다(state/redmine/sync.lock)"
OFF_TEXT = "config.toml 에 [redmine] 이 없다(Redmine 연동이 꺼져 있다)"
ISSUE_RE = SEQ_RE = re.compile(r"[0-9]+")  # 이슈 번호, 큐 파일 이름의 순번
NAME_WIDTH = 6  # 큐 파일 이름의 순번 자릿수


def issue_of(p, tid: str) -> str | None:
    """그 태스크 사양의 issue(사양을 읽지 못하면 None)."""
    try:
        return specs.load(p, tid).issue
    except HteamError:
        return None


def _name(seq: int) -> str:
    return f"{seq:0{NAME_WIDTH}d}.json"


def _numbers(folder) -> list[int]:
    return [int(f.stem) for f in folder.glob("*.json") if SEQ_RE.fullmatch(f.stem)]


def _next_seq(p) -> int:
    """seq 파일의 수 + 1. 없거나 읽지 못하면 queue/·failed/ 의 가장 큰 번호 + 1(queue.lock 안에서 부른다)."""
    try:
        return int(p.redmine_seq.read_text(encoding="utf-8").strip()) + 1
    except (OSError, ValueError):
        return max([0, *_numbers(p.redmine_queue), *_numbers(p.redmine_failed)]) + 1


# --- 큐 쓰기(관제) ---
def enqueue(p, cfg, st_or_tid, event: str, *, notes: str, issue: str | None = None) -> dict | None:
    """사건 하나를 큐에 쓴다(설계 8.12 의 전송 첫 문장). [redmine] 이 없거나 issue(주지 않으면 사양의 issue)가 없으면 아무것도
    쓰지 않고 None. 순번은 queue.lock 안에서 정하고 seq 를 먼저 쓴 뒤 항목을 임시 파일 + os.replace 로 쓴다. 키는 쓰지 않는다."""
    if event not in EVENTS:
        raise HteamError("bad_redmine_event", f"모르는 Redmine 사건이다: {event}", USAGE)
    if cfg.redmine is None:
        return None
    tid = st_or_tid["id"] if isinstance(st_or_tid, dict) else st_or_tid
    issue = issue or issue_of(p, tid)
    if issue is None:
        return None
    field = EVENTS[event]
    with flock(p.redmine_lock):
        seq = _next_seq(p)
        write_atomic(p.redmine_seq, f"{seq}\n")
        item = {"seq": seq, "issue": issue, "task": tid, "event": event,
                "status_id": cfg.redmine.status[field] if field else None, "notes": notes, "at": now()}
        write_json(p.redmine_queue / _name(seq), item)
    return item


def _event(p, cfg, st: dict, event: str, note) -> dict | None:
    """사건 자리의 공통: 꺼져 있거나 이슈가 없으면 노트를 만들지 않는다. note 는 노트 글을 만드는 함수다."""
    if cfg.redmine is None:
        return None
    issue = issue_of(p, st["id"])
    if issue is None:
        return None
    return enqueue(p, cfg, st, event, notes=note(), issue=issue)


def _agent(name: str | None) -> str:
    from .approval import AGENT_NAMES
    return AGENT_NAMES.get(name or "", name or "")


def _shown(lines: list[str]) -> str:
    """막는 지적 줄: 최대 P1_LINES 개, 줄마다 앞 목록 표시 `- `·끝 마침표 하나를 떼고 P1_WIDTH 자, ` / ` 로 잇는다. 없으면 `(없음)`."""
    shown = [line.strip().removeprefix("- ").removesuffix(".")[:P1_WIDTH] for line in lines[:P1_LINES]]
    return " / ".join(shown) if shown else "(없음)"


def _p1_lines(p, st: dict, rnd: int) -> list[str]:
    """그 라운드 리뷰 결과(`<작업 루트>/docs/reviews/T-xxx/rN.md`)의 `## 지적 사항` 절에서 낱말 P1 이 든 줄(`없음` 줄은 뺀다)."""
    from . import review, workspace
    try:
        text = (workspace.task_root(p, st) / review_rel(st["id"], rnd)).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return []
    found = review.FINDINGS_RE.search(text)
    if not found:
        return []
    return [line for line in found.group(1).splitlines()
            if review.BROAD_P1_RE.search(line) and not review.NONE_LINE_RE.match(line)]


def _changes_note(st: dict, who: str, lines: list[str]) -> str:
    tid, rnd = st["id"], st["round"]
    return f"{tid} r{rnd} 리뷰: 수정 요청({who}). 막는 지적: {_shown(lines)}. 리뷰: {review_rel(tid, rnd)}"


def started(p, cfg, st: dict) -> dict | None:
    """작업 라운드 시작(start·fix·대기열): 그 라운드와 그 라운드의 에이전트."""
    rd = state.current_round(st)
    return _event(p, cfg, st, "start", lambda: f"herdr-team: {st['id']} r{rd['round']} 작업을 시작했다"
                                               f"({cfg.role_title(st['role'])}, {_agent(rd['agent'])}).")


def worked(p, cfg, st: dict, body: dict) -> dict | None:
    """작업 worker_done(succeeded): 본문의 summary 앞 SUMMARY_MAX 자와 report_path(없으면 보고서 기본 경로)."""
    return _event(p, cfg, st, "done", lambda: f"{st['id']} r{st['round']} 작업을 마쳤다. 요약: "
                                              f"{str(body.get('summary') or '')[:SUMMARY_MAX]}. 보고서: "
                                              f"{body.get('report_path') or report_rel(st['id'])}")


def reviewer_changes(p, cfg, st: dict) -> dict | None:
    """리뷰어 REQUEST_CHANGES: 리뷰어는 그 라운드의 마지막 리뷰 시도 에이전트(없으면 `리뷰어`), 막는 지적은 리뷰 결과의 P1 줄."""
    def note() -> str:
        att = state.latest_attempt(state.current_round(st)) or {}
        who = _agent(att.get("agent")) or "리뷰어"
        return _changes_note(st, who, _p1_lines(p, st, st["round"]))
    return _event(p, cfg, st, "changes", note)


def hteam_changes(p, cfg, st: dict) -> dict | None:
    """hteam 반려(사전 검사·테스트 관문): 막는 지적은 그 라운드 기록의 prechecks 그대로."""
    return _event(p, cfg, st, "changes",
                  lambda: _changes_note(st, "hteam", list((state.current_round(st) or {}).get("prechecks") or [])))


def approved(p, cfg, st: dict) -> dict | None:
    """리뷰 APPROVE: 보고서(작업 루트의 것. 작업 공간 태스크는 병합 전이다)에 claude.ai 아티팩트 URL 이 있으면 마지막 것."""
    from . import approval, workspace

    def note() -> str:
        att = state.latest_attempt(state.current_round(st)) or {}
        text = f"{st['id']} r{st['round']} 리뷰: 승인({_agent(att.get('agent')) or '리뷰어'})."
        url = approval.link(p, st["id"], root=workspace.task_root(p, st))
        return text + (f" 아티팩트: {url}" if url.startswith("https://claude.ai/") else "")
    return _event(p, cfg, st, "approve", note)


def merged(p, cfg, st: dict) -> dict | None:
    """작업 공간 병합(설계 5.10.6): 상태의 workspace.base_branch 와 병합 커밋 workspace.merge."""
    ws = st["workspace"]
    return _event(p, cfg, st, "merged", lambda: f"기준 브랜치 {ws['base_branch']} 에 병합했다({ws['merge'][:7]}).")


def dropped(p, cfg, st: dict) -> dict | None:
    return _event(p, cfg, st, "drop", lambda: f"{st['id']} 를 버렸다.")


# --- 닫는 때(설계 8.12, 사용자 결정) ---
def _depends(p, tid: str) -> list[str]:
    try:
        return specs.load(p, tid).depends_on
    except HteamError:
        return []


def _closable(issue: str, states: list[dict], issues: dict[str, str | None],
              testers: list[tuple[dict, list[str]]]) -> bool:
    """이슈 issue 를 가진 모든 태스크가 done·dropped 이고, 그 가운데 done 이고 어느 tester 의 depends_on 에 든 태스크마다 그
    tester 들 가운데 done 인 것이 하나 있다(묶음 tester 가 drop 되면 그 묶음의 이슈를 닫지 않는다). 사양을 읽지 못한 태스크는
    issue 가 None 이라 빠진다."""
    mine = [s for s in states if issues[s["id"]] == issue]
    if not mine or any(s["status"] not in ("done", "dropped") for s in mine):
        return False
    for s in mine:
        if s["status"] != "done":
            continue
        covering = [t for t, deps in testers if s["id"] in deps]
        if covering and not any(t["status"] == "done" for t in covering):
            return False
    return True


def close_for(p, cfg, tid: str) -> list[dict]:
    """태스크 tid 가 done 이 된 뒤 닫을 이슈마다 closed 항목을 쓰고 그 목록을 돌려준다. 관제의 accept 뒤(Drive.after_accept)와
    일괄 승인 결정(approval._apply)이 이 함수 하나를 부른다.

    볼 이슈: tid 가 tester 면 사양 depends_on 가운데 developer 태스크의 issue(그 순서) 다음 tid 의 issue, 아니면 tid 의 issue.
    같은 이슈를 가진 다른 태스크가 끝나지 않아 미룬 이슈는 그 태스크가 done 이 될 때 이 함수가 다시 본다."""
    if cfg.redmine is None:
        return []
    states = state.all_states(p)
    by_id = {s["id"]: s for s in states}
    bundle = (by_id.get(tid) or {}).get("role") == testgate.TESTER_ROLE
    looked = [d for d in _depends(p, tid) if (by_id.get(d) or {}).get("role") == testgate.DEVELOPER_ROLE] \
        if bundle else []
    wanted = [i for i in dict.fromkeys(issue_of(p, t) for t in [*looked, tid]) if i is not None]
    if not wanted:
        return []
    issues = {s["id"]: issue_of(p, s["id"]) for s in states}
    if bundle:
        try:
            key = specs.load(p, tid).front.get("plan_key") or tid
        except HteamError:
            key = tid
        note = f"묶음 {key} 테스트({tid})가 끝나 종료한다."
    else:
        note = f"{tid} 가 끝나 종료한다."
    testers = [(s, _depends(p, s["id"])) for s in states if s.get("role") == testgate.TESTER_ROLE]
    return [enqueue(p, cfg, tid, "closed", notes=note, issue=issue) for issue in wanted
            if _closable(issue, states, issues, testers)]


# --- 키 ---
def _key_place(rm) -> str:
    return f"{rm.env_file} 의 {rm.key_env}" if rm.env_file else f"환경 변수 {rm.key_env}"


def _no_key_text(cfg) -> str:
    return f"Redmine API 키를 찾지 못했다({_key_place(cfg.redmine)})"


def read_key(p, cfg) -> str | None:
    """API 키. env_file 이 있으면 `<프로젝트>/<env_file>` 만 읽는다(빈 줄·# 줄을 빼고 `=` 앞을 strip 한 이름이 key_env 인 첫
    줄, 값은 strip 한 뒤 앞뒤가 같은 따옴표면 한 겹 벗긴다. 파일을 읽지 못하거나 그 이름이 없으면 None). 없으면 이 프로세스
    환경의 key_env. 빈 값은 None. 전송 자식과 doctor 만 부른다."""
    rm = cfg.redmine
    if not rm.env_file:
        return os.environ.get(rm.key_env) or None
    try:
        text = (p.root / rm.env_file).read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() != rm.key_env:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        return value or None
    return None


def mask(text: str, key: str | None) -> str:
    """key 가 있으면 text 의 그 값을 모두 `***` 로."""
    return text.replace(key, MASK) if key else text


# --- 전송(자식 hteam redmine-sync) ---
def _read_item(path) -> tuple[dict | None, str]:
    """큐 항목과 읽지 못한 까닭. 꼴: dict, seq 정수, issue 숫자 문자열, event·notes·at 문자열."""
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, str(exc)
    if not isinstance(item, dict):
        return None, "JSON 객체가 아니다"
    if not (isinstance(item.get("seq"), int) and not isinstance(item["seq"], bool)
            and isinstance(item.get("issue"), str) and ISSUE_RE.fullmatch(item["issue"])
            and all(isinstance(item.get(k), str) for k in ("event", "notes", "at"))):
        return None, "꼴이 틀렸다(seq 정수, issue 숫자 문자열, event·notes·at 문자열)"
    return item, ""


def _files(p) -> list:
    """큐 파일(`<순번>.json`)을 순번 순으로(자릿수가 늘어도 수의 차례)."""
    return sorted((f for f in p.redmine_queue.glob("*.json") if SEQ_RE.fullmatch(f.stem)),
                  key=lambda f: (len(f.stem), f.stem))


def _later(seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _request(cfg, item: dict, key: str) -> urllib.request.Request:
    fields = {"notes": item["notes"]} if item.get("status_id") is None \
        else {"status_id": item["status_id"], "notes": item["notes"]}
    return urllib.request.Request(f"{cfg.redmine.url}/issues/{item['issue']}.json", method="PUT",
                                  data=json.dumps({"issue": fields}, ensure_ascii=False).encode("utf-8"),
                                  headers={"Content-Type": "application/json", "X-Redmine-API-Key": key})


def _put(cfg, item: dict, key: str) -> tuple[int | str, str]:
    """PUT 하나. (HTTP 상태 또는 "연결 실패", 오류 글). 오류 글은 전체에서 키를 가린 뒤 자른다(자른 뒤 가리면 경계에 걸린 키의
    앞부분이 남는다)."""
    try:
        with urllib.request.urlopen(_request(cfg, item, key), timeout=TIMEOUT_S) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")
        except (OSError, http.client.HTTPException):
            body = ""
        return exc.code, f"HTTP {exc.code}: {mask(body, key)[:ERROR_WIDTH]}"
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        return "연결 실패", f"연결 실패: {mask(str(exc), key)[:ERROR_WIDTH]}"


def _brief(item: dict, status, error: str | None = None) -> dict:
    out = {"seq": item["seq"], "issue": item["issue"], "event": item["event"], "status": status}
    if error is not None:
        out["error"] = error
    return out


def _fail(p, path, item: dict, error: str) -> None:
    write_json(p.redmine_failed / path.name, {**item, "error": error})
    path.unlink()


def _write_status(p, last: str | None) -> None:
    write_json(p.redmine_status, {"at": now(), "last_error": last})


def _send_all(p, cfg) -> dict:
    """큐를 순번 순으로 보낸다(설계 8.12). 같은 이슈의 뒤 항목은 앞 항목이 남아 있는 동안 보내지 않는다. 다른 이슈는 막지 않는다."""
    key = read_key(p, cfg)
    out: dict = {"sent": [], "failed": [], "retry": []}
    blocked: set[str] = set()
    last = None
    for path in _files(p):
        item, why = _read_item(path)
        if item is None:  # 파일 그대로 failed 로 옮긴다
            p.redmine_failed.mkdir(parents=True, exist_ok=True)
            os.replace(path, p.redmine_failed / path.name)
            error = f"큐 항목을 읽지 못했다: {why}"
            out["failed"].append({"seq": int(path.stem), "issue": "?", "event": "?", "status": "읽기 실패",
                                  "error": error})
            last = f"#? ? 읽기 실패: {error[:ERROR_WIDTH]}"
            continue
        issue = item["issue"]
        if issue in blocked or (item.get("next_at") and (age_seconds(item["next_at"]) or 0) < 0):
            blocked.add(issue)
            continue
        status, error = ("키 없음", _no_key_text(cfg)) if key is None else _put(cfg, item, key)
        if isinstance(status, int) and 200 <= status < 300:
            path.unlink()
            out["sent"].append(_brief(item, status))
            continue
        if isinstance(status, int) and 400 <= status < 500:  # 그 이슈를 막지 않는다(남은 앞 항목이 없다)
            _fail(p, path, item, error)
            out["failed"].append(_brief(item, status, error))
        elif (age_seconds(item["at"]) or 0) >= GIVE_UP_S:
            error = f"24시간 동안 보내지 못했다: {error}"
            _fail(p, path, item, error)
            out["failed"].append(_brief(item, status, error))
        else:
            tries = int(item.get("tries") or 0)
            item.update(tries=tries + 1, next_at=_later(RETRY_S[min(tries, len(RETRY_S) - 1)]), last_error=error)
            write_json(path, item)
            blocked.add(issue)
            out["retry"].append(_brief(item, status, error))
        last = error if status == "키 없음" else f"#{issue} {item['event']} {status}: {error[:ERROR_WIDTH]}"
    if out["sent"] or out["failed"] or out["retry"]:  # 아무것도 보내지 않았으면 앞 값을 둔다
        _write_status(p, last)  # 실패가 없으면 None(보냈다)
    return {**out, "pending": len(_files(p))}


def sync(p, cfg) -> dict:
    """전송(설계 8.12). 실행 내내 sync.lock 을 비차단으로 쥔다: 못 쥐면(다른 hteam redmine-sync 가 보내는 중이다. 관제가 다시
    떠 앞 관제의 자식과 겹친 때 등) 큐를 읽지도 보내지도 않고 busy 로 끝난다."""
    p.redmine_dir.mkdir(parents=True, exist_ok=True)
    with open(p.redmine_sync_lock, "a") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"busy": True, "message": BUSY_TEXT, "sent": [], "failed": [], "retry": [],
                    "pending": len(_files(p))}
        return {"busy": False, **_send_all(p, cfg)}


def due(p) -> bool:
    """지금 보낼 항목이 있나: 같은 이슈의 맨 앞 항목 가운데 next_at 이 없거나 지났거나, 읽지 못하는 항목이 있다."""
    seen: set[str] = set()
    for path in _files(p):
        item, _ = _read_item(path)
        if item is None:
            return True
        if item["issue"] in seen:
            continue
        seen.add(item["issue"])
        if not item.get("next_at") or (age_seconds(item["next_at"]) or 0) >= 0:
            return True
    return False


# --- status·doctor ---
def summary(p, cfg) -> dict:
    """`hteam status` 의 redmine: 남은 큐 수, failed 수, 마지막 전송의 last_error(status.json 을 느슨하게 읽는다). 키는 없다."""
    rec = read_json(p.redmine_status, {})
    last = rec.get("last_error") if isinstance(rec, dict) else None
    return {"enabled": True, "pending": len(_files(p)), "failed": len(list(p.redmine_failed.glob("*.json"))),
            "last_error": last if isinstance(last, str) else None}


def _check(name: str, ok, detail: str) -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "level": "warning"}


def _api(cfg, key: str) -> tuple[bool, str]:
    req = urllib.request.Request(f"{cfg.redmine.url}/users/current.json", headers={"X-Redmine-API-Key": key})
    try:
        with urllib.request.urlopen(req, timeout=DOCTOR_TIMEOUT_S) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        return False, f"연결 실패: {mask(str(exc), key)[:ERROR_WIDTH]}"
    return code == 200, "200" if code == 200 else f"HTTP {code}"


def checks(p, cfg) -> list[dict]:
    """doctor 의 Redmine 점검(설계 9.2, 경고만): 키를 찾는지(값은 보이지 않는다), GET /users/current.json 이 200 인지,
    env_file 이 있으면 git 이 추적하지 않는지."""
    rm = cfg.redmine
    key = read_key(p, cfg)
    found = rm.env_file or f"환경 변수 {rm.key_env}"
    out = [_check("redmine_key", key is not None,
                  f"키를 찾았다({found})" if key is not None else f"키를 찾지 못했다: {_key_place(rm)}")]
    out.append(_check("redmine_api", *_api(cfg, key)) if key is not None
               else _check("redmine_api", False, "키가 없어 보지 않았다"))
    if rm.env_file:
        tracked = gitio.tracked(p.root, rm.env_file)
        out.append(_check("redmine_env_file", not tracked,
                          f"git 이 추적하는 파일이다. .gitignore 에 넣고 git rm --cached -- {rm.env_file} 한다" if tracked
                          else "git 이 추적하지 않는 파일이다"))
    return out


# --- CLI ---
def _cmd_sync(args) -> dict:
    p = find_project(args.root)
    roles.require_drive(p)
    cfg = config.load(p)
    if cfg.redmine is None:
        raise HteamError("redmine_off", OFF_TEXT, USAGE, "Redmine 연동을 쓰려면 config.toml 에 [redmine] 을 넣는다")
    return sync(p, cfg)


def register(sub) -> None:
    sub.add_parser("redmine-sync").set_defaults(func=_cmd_sync)
