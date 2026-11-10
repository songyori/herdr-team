#!/usr/bin/env python3
"""herdr-team Claude Code 훅(설계 9.4). 사용법: hteam_hook.py <session-start|role-mark|guard|stop>

`.herdr-team/config.toml` 이 없는 프로젝트에서는 아무것도 하지 않는다(hteam 모듈도 가져오지 않는다).
훅 오류로 세션이 막히면 안 되므로 예외(hteam 을 가져오지 못한 것 포함)는 state/hook-errors.log 에 남기고 통과시킨다.
실수 방지용이지 보안 경계가 아니다.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
import traceback
from pathlib import Path

HOOK_START = time.monotonic()  # 자동 부활의 4초 규칙과 마감은 훅이 시작한 때부터 잰다(설계 9.5)
LIB = Path(__file__).resolve().parents[1] / "lib"
# hteam 모듈. _load() 가 herdr-team 프로젝트에서만 채운다
outbox = roles = HteamError = PLUGIN_ROOT = SHIM = Project = None
die_at = flock = read_json = write_atomic = write_json = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SETUP_PREFIXES = (".herdr-team/", ".claude/", "docs/superpowers/")
SETUP_FILES = {"CLAUDE.md", "AGENTS.md", ".gitignore"}
STATE_DIR = ".herdr-team/state"
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# 캐시하는 역할. 관제는 Claude 세션이 아니다(관제 환경의 세션은 캐시하지 않고 늘 환경 변수와 run.json 으로 본다)
CACHED_RE = re.compile(r"^(main|reviewer|worker(:[a-z][a-z0-9-]*)?)$")
NOISE_RE = re.compile(r"[\s#*_>|\-`]+")
FINGERPRINT = 80  # 정규화한 render.context 앞 80자가 메인 텍스트에 있으면 보여 준 것으로 본다
CONTEXT_DENY_MAX = 3  # 같은 질문을 context 없이 물으면 보일 때까지 거부하되 이만큼만(그 뒤는 통과시킨다: 탈출구)
TAIL_BYTES = 1 << 20

# 메인 Bash 의 horch 거부(horch_denied). brief 의 낱말 규칙 그대로다
HORCH_RE = re.compile(r"(^|[\s;&|(`'\"/<>])horch(?=$|[\s;&|)`'\"<>])")
# 메인 Bash 의 hteam drive 거부(drive_denied, 설계 9.4): hteam 낱말은 HORCH_RE 와 같은 경계, 앞 옵션 --root 를 건너뛴
# 하위 명령이 정확히 drive 일 때
DRIVE_RE = re.compile(r"(^|[\s;&|(`'\"/<>])hteam['\"]?(?:\s+--root(?:=\S+|\s+\S+))*\s+['\"]?drive['\"]?"
                      r"(?=$|[\s;&|)`'\"<>])")


def _load() -> None:
    """hteam 모듈을 가져온다. herdr-team 프로젝트를 찾은 뒤에만 부른다. 실패는 main() 이 오류 기록으로 남긴다."""
    global outbox, roles, HteamError, PLUGIN_ROOT, SHIM, Project
    global die_at, flock, read_json, write_atomic, write_json
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    from hteam import outbox, roles
    from hteam.errors import HteamError
    from hteam.paths import PLUGIN_ROOT, SHIM, Project
    from hteam.util import die_at, flock, read_json, write_atomic, write_json


def find_root(payload: dict) -> Path | None:
    start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()).resolve()
    for folder in (start, *start.parents):
        if (folder / ".herdr-team" / "config.toml").is_file():
            return folder
    return None


def log_error(root: Path, text: str) -> None:
    """state/hook-errors.log 에 남긴다. hteam 을 가져오지 못했어도 쓸 수 있게 표준 라이브러리만 쓴다."""
    event = sys.argv[1] if len(sys.argv) > 1 else "?"
    path = Path(root) / ".herdr-team" / "state" / "hook-errors.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {event}\n{text.rstrip()}\n\n")
    except OSError:
        pass


def _session(payload: dict) -> str | None:
    sid = payload.get("session_id")
    return sid if isinstance(sid, str) and SESSION_RE.match(sid) and ".." not in sid else None


def role_of(p, payload: dict, *, fresh: bool = False) -> str:
    """관제 환경 → 캐시 → 판별. 확실할 때만 state/sessions/<session id> 에 캐시한다.

    관제는 Claude 세션이 아니다(설계 9.4): 관제 환경(HTEAM_ROLE=drive 이고 run.json 의 drive_terminal)의 세션은 모름
    (unknown)이다. fresh(SessionStart): 캐시를 믿지 않고 지운 뒤 다시 판별한다. `claude --continue`·`--resume` 은 session id
    를 그대로 이어 쓰므로 다른 터미널(워커 등)에서 쓰던 캐시가 남아 있을 수 있다. run.json 을 읽지 못해 관제 환경인지 확인할
    수 없으면 오류를 남기고 모름(unknown)으로 둔다."""
    sid = _session(payload)
    cache = p.sessions / sid if sid else None
    if fresh and cache is not None:
        cache.unlink(missing_ok=True)
    try:
        if roles.drive_env(p):
            return "unknown"
    except HteamError as exc:
        log_error(p.root, f"역할 판별: {exc.code}: {exc.message}")
        return "unknown"
    if cache is not None and cache.is_file():
        cached = cache.read_text(encoding="utf-8").strip()
        if CACHED_RE.match(cached):
            return cached
    role, sure = roles.detect(p)
    if sure and role and cache is not None:
        p.ensure_state()
        write_atomic(cache, role + "\n")
    return role or "unknown"


def _below(real: Path, folder: Path) -> str | None:
    """real 이 folder 자신이거나 그 안이면 folder 기준 상대 경로, 아니면 None.

    글자로 먼저 보고, 다르면 real 과 그 조상 가운데 folder 와 같은 폴더(st_dev, st_ino)를 찾는다. 대소문자를 가리지 않는
    파일 시스템(macOS 기본)의 `PROJ/…` 나 firmlink(`/System/Volumes/Data/…`)도 같은 폴더로 본다."""
    try:
        return real.relative_to(folder).as_posix()
    except ValueError:
        pass
    try:
        want = os.stat(folder)
    except OSError:
        return None
    for anc in (real, *real.parents):
        try:
            got = os.stat(anc)
        except OSError:
            continue
        if (got.st_dev, got.st_ino) == (want.st_dev, want.st_ino):
            return real.relative_to(anc).as_posix()
    return None


def _cwd(payload: dict) -> Path | None:
    cwd = payload.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and os.path.isabs(cwd) else None


def where(p, raw, cwd: Path | None = None) -> tuple[str, Path | None, str | None]:
    """("inside", 실제 경로, 프로젝트 기준 상대 경로) | ("outside", 실제 경로, None) | ("unknown", None, None).

    `~` 는 홈으로, 상대 경로는 cwd(훅 입력의 cwd, 없으면 프로젝트 루트) 기준으로 푼다. `..` 와 심볼릭 링크는 실제 경로로
    푼 뒤 판단한다. 풀 수 없으면 unknown(허용으로 다루지 않는다): 빈 값·문자열이 아님·NUL 문자·심볼릭 링크 순환
    (Python 3.13 부터 resolve() 가 오류 없이 링크를 남긴다) 등."""
    if not isinstance(raw, str) or not raw:
        return "unknown", None, None
    try:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = (cwd or p.root) / path
        real = path.resolve()
        if any(part.is_symlink() for part in (real, *real.parents)):
            return "unknown", None, None
    except (OSError, RuntimeError, ValueError):
        return "unknown", None, None
    rel = _below(real, p.root)
    return ("inside", real, rel) if rel is not None else ("outside", real, None)


def _in_state(p, real: Path, rel: str | None) -> bool:
    folded = (rel or "").casefold()  # 대소문자를 가리지 않는 파일 시스템에서 `State/` 도 같은 폴더다
    return folded == STATE_DIR or folded.startswith(STATE_DIR + "/") or _below(real, p.state) is not None


def _plain(cmd: str) -> bool:
    """셸 연산자·치환·heredoc 이 없는 명령인가. 따옴표 밖의 `; & | < >`·줄바꿈·`$'`, 작은따옴표 밖의 `` ` ``·`$(` 가
    있으면 False 다(heredoc `<<` 도 `<` 다). 따옴표가 닫히지 않아도 False. `\\` 로 막은 글자는 글자다(셸과 같다)."""
    quote, i = None, 0
    while i < len(cmd):
        c = cmd[i]
        if quote == "'":
            if c == "'":
                quote = None
        elif c == "\\":
            i += 1  # 다음 글자는 글자다(따옴표 밖 `\\` 줄바꿈은 줄 잇기)
        elif c == "`" or cmd.startswith("$(", i):
            return False
        elif quote == '"':
            if c == '"':
                quote = None
        elif c in ";&|<>\n" or cmd.startswith("$'", i):
            return False
        elif c in "'\"":
            quote = c
        i += 1
    return quote is None


def hteam_only(cmd: str) -> bool:
    """명령 전체가 hteam 한 번 호출인가(첫 단어의 basename 이 hteam 이고 연산자·치환·heredoc 이 없다).
    이때 horch 낱말은 answer·scope 의 글일 뿐 실행이 아니다."""
    if not _plain(cmd):
        return False
    try:
        words = shlex.split(cmd)
    except ValueError:
        return False
    return bool(words) and os.path.basename(words[0]) == "hteam"


def horch_denied(cmd: str) -> bool:
    """메인 Bash 명령을 horch 직접 호출로 보고 거부하는가(설계 9.4). 셸 문법을 따라가지 않는다: hteam 한 번 호출만
    허용 목록이고, 나머지는 horch 낱말이 나오면 거부한다(닫힌 쪽. `ls …/horch`·`grep horch` 도 거부된다)."""
    return not hteam_only(cmd) and bool(HORCH_RE.search(cmd))


def drive_denied(cmd: str) -> bool:
    """메인 Bash 명령을 관제 실행(`hteam drive`)으로 보고 거부하는가(설계 9.4). hteam 한 번 호출이면 앞 옵션(`--root` 는
    다음 단어까지, `--root=…` 와 그 밖의 `-…` 는 한 단어)을 건너뛴 하위 명령이 정확히 drive 일 때만(글 안의 `hteam drive`
    낱말은 실행이 아니다). 아니면 DRIVE_RE 가 어디서든 맞으면 거부한다(닫힌 쪽, horch 규칙과 같다)."""
    if hteam_only(cmd):
        words = shlex.split(cmd)
        i = 1
        while i < len(words) and words[i].startswith("-"):
            i += 2 if words[i] == "--root" else 1
        return i < len(words) and words[i] == "drive"
    return bool(DRIVE_RE.search(cmd))


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _transcript_text(path) -> str | None:
    """transcript(JSONL) 끝부분의 assistant text. 읽지 못하면 None(판단 불가 → 통과)."""
    if not isinstance(path, str) or not path or not Path(path).is_file():
        return None
    try:
        with open(path, "rb") as fh:
            size = fh.seek(0, os.SEEK_END)
            fh.seek(max(0, size - TAIL_BYTES))
            data = fh.read()
    except OSError:
        return None
    texts = []
    for raw in data.split(b"\n")[1 if size > TAIL_BYTES else 0:]:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            return None
        message = entry.get("message") if isinstance(entry, dict) and entry.get("type") == "assistant" else None
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            texts += [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"
                      and isinstance(b.get("text"), str)]
    return "\n".join(texts)


def _denied(p) -> dict:
    """context-denied.json = {"denied": {out-id: 거부한 횟수}}. 옛 형식 {"ids": [...]} 는 한 번씩 거부한 것으로 읽는다.
    읽지 못하면 빈 기록이다(한 번 더 거부할 뿐이다)."""
    data = read_json(p.context_denied, {})
    if not isinstance(data, dict):
        return {}
    found = {i: 1 for i in data.get("ids") or [] if isinstance(i, str)} if isinstance(data.get("ids"), list) else {}
    counts = data.get("denied")
    if isinstance(counts, dict):
        found.update({k: v for k, v in counts.items() if isinstance(k, str) and isinstance(v, int)
                      and not isinstance(v, bool)})
    return found


def context_guard(p, payload: dict, tool_input: dict):
    """메인이 render.context 를 먼저 보여 주지 않고 그 질문을 물으면 보일 때까지 거부한다. 같은 질문은 CONTEXT_DENY_MAX
    번까지만 거부하고 그 뒤는 통과시킨다(메인이 끝내 보여 주지 못해도 질문이 막히지 않는다)."""
    questions = tool_input.get("questions")
    asked = {q["question"].strip() for q in questions if isinstance(q, dict) and isinstance(q.get("question"), str)} \
        if isinstance(questions, list) else set()
    if not asked:
        return None
    with flock(p.state / "context-denied.lock"):  # context-denied.json 읽고 고쳐 쓰기가 겹쳐 기록을 잃지 않게
        return _context_guard_locked(p, payload, asked)


def _context_guard_locked(p, payload: dict, asked: set):
    denied = _denied(p)
    die_at("context_denied_read")  # 테스트: 읽은 뒤 멈춰 겹친 호출을 재현한다
    items = [q for q in outbox.open_questions(p)
             if denied.get(q["id"], 0) < CONTEXT_DENY_MAX and isinstance(q.get("render"), dict)
             and isinstance(q["render"].get("context"), str) and NOISE_RE.sub("", q["render"]["context"])
             and q["render"].get("question", "").strip() in asked]
    if not items:
        return None
    text = _transcript_text(payload.get("transcript_path"))
    if text is None:
        return None
    shown = NOISE_RE.sub("", text)
    unshown = [q for q in items if NOISE_RE.sub("", q["render"]["context"])[:FINGERPRINT] not in shown]
    if not unshown:
        return None
    for q in unshown:
        denied[q["id"]] = denied.get(q["id"], 0) + 1
    write_json(p.context_denied, {"denied": denied})  # 임시 파일 + os.replace
    blocks = "\n\n".join(f"[{q['id']}]\n{q['render']['context']}" for q in unshown)
    last = [q["id"] for q in unshown if denied[q["id"]] >= CONTEXT_DENY_MAX]
    tail = (f"\n\n({', '.join(last)}: 이번이 마지막 거부다. 다음에는 확인하지 않고 통과시킨다. 그래도 먼저 보여 준다.)"
            if last else "")
    return deny("이 질문에는 먼저 보여 줄 `render.context` 가 있다. 아래 내용을 요약하거나 바꾸지 말고 답변 글(텍스트)로 "
                "그대로 출력한 뒤 같은 render 로 AskUserQuestion 을 다시 부른다([out-id] 줄은 출력하지 않는다). 생각·도구 설명 "
                "줄(화면에 짧은 진행 설명으로 보이는 줄 포함)은 원문이 아니라 요약으로 보이고 훅도 보인 것으로 세지 않는다. 글을 "
                "쓴 뒤 같은 응답에서 이어서 AskUserQuestion 을 부른다. 턴을 끝내지 않는다(사용자의 다른 말을 기다리지 않는다). "
                f"보여 줄 때까지 거부한다.\n\n{blocks}{tail}")


def guard(p, payload: dict):
    role = role_of(p, payload)
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool == "AskUserQuestion":
        if role == "main":
            return context_guard(p, payload, tool_input)
        if role in ("worker:planner", "worker:director"):
            return deny("기획·디렉터 워커는 AskUserQuestion 을 쓰지 않는다. 질문 JSON 을 "
                        f"`{SHIM} ask-user --task T-xxx --json -` 의 표준 입력으로 보낸다(직무 문서, Bash timeout 600000).")
        if role == "reviewer":
            return deny("리뷰어는 묻지 않는다. 판단할 수 없는 것은 리뷰 파일에 적고 판정을 마친다.")
        if role.startswith("worker"):
            return deny("워커는 사용자에게 직접 묻지 않는다. 프리앰블의 ask 명령(horch ask)으로 묻는다(메인이 답한다).")
        return None
    if tool in EDIT_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        kind, real, rel = where(p, raw, _cwd(payload))
        if kind != "unknown" and _in_state(p, real, rel):
            return deny("`.herdr-team/state/` 는 hteam 이 관리한다. 직접 고치지 않는다. 복구는 `hteam status` 의 next 를 따른다.")
        if role == "main":
            in_team = kind != "unknown" and _below(real, p.team) is not None
            if kind == "unknown":  # setup-mode 에서도 거부한다
                return deny(f"경로를 확인할 수 없다({raw!r}). 메인은 풀 수 없는 경로를 고치지 않는다.")
            # 프로젝트 밖(스크래치 파일 등)은 이 프로젝트의 제품 파일이 아니므로 막지 않는다
            setup = in_team or rel in SETUP_FILES or (rel or "").startswith(SETUP_PREFIXES)
            if kind == "inside" and not setup and not p.setup_mode.exists():
                return deny(f"메인은 제품 파일({rel})을 고치지 않는다. 태스크로 맡긴다(`{SHIM} task new` → 사양 커밋 → "
                            f"`{SHIM} start`, CLAUDE.md \"메인 규칙\").")
        return None
    command = tool_input.get("command")
    if tool != "Bash" or role != "main" or not isinstance(command, str):
        return None
    if horch_denied(command):
        return deny(f"메인은 horch 를 직접 부르지 않는다(Run 에 묶이면 깨우기 글이 사용자 입력란에 들어온다). 같은 일은 hteam "
                    f"큐 명령으로 한다. horch 가 나오는 글은 `{SHIM} answer <out-id> \"<답>\"` 이나 "
                    f"`{SHIM} scope T-xxx \"<내용>\"` 한 번의 호출 안에만 둔다: 다른 명령과 잇지 않고(; && | 없이) "
                    "리다이렉션·$(…)·백틱·heredoc 도 쓰지 않는다. 그 밖의 명령은 horch 라는 낱말만 나와도 거부한다(ls·grep 포함).")
    if drive_denied(command):
        return deny("hteam drive 는 관제 탭에서만 돈다. 메인 터미널이 관제가 되면 horch 깨우기 글이 사용자 입력란에 들어온다. "
                    "관제를 띄우려면 /herdr-team:up 을 쓴다")
    return None


def auto_up(p, force: bool) -> str | None:
    """관제 자동 부활 확인(설계 9.5). 메인 세션에서만 부른다. Herdr 터미널 밖($HC_TERMINAL_ID 없음)이면 하지 않는다
    (up 이 exit 5 다). autoup 은 이 두 훅에서만 늦게 가져온다(guard 훅은 도구 호출마다 돈다). 예외는 막지 않고 라벨
    auto-up 으로 hook-errors.log 에 남긴다."""
    if not os.environ.get("HC_TERMINAL_ID", "").strip():
        return None
    try:
        from hteam import autoup
        return autoup.check(p, force=force, started=HOOK_START)
    except Exception:  # noqa: BLE001
        log_error(p.root, "auto-up\n" + traceback.format_exc())
        return None


def session_start(p, payload: dict):
    p.ensure_state()
    write_atomic(p.plugin_root_file, str(PLUGIN_ROOT) + "\n")
    if role_of(p, payload, fresh=True) != "main":
        return None
    notice = auto_up(p, force=True)
    lines = ["herdr-team 프로젝트다. 너는 메인이다(사용자와 대화하는 세션). 첫 지시가 워커 지시(\"너는 herdr-orch 워커다\")면 "
             "이 안내를 무시한다.",
             f"- {notice}" if notice else
             "- 관제(hteam drive)는 훅이 확인하고 꺼져 있으면 자동으로 다시 띄운다(config.toml [drive] auto_up). watch 가 꺼져 "
             f"있으면 Bash `run_in_background: true` 로 `{SHIM} watch` 를 띄운다. 관제 상태가 의심되면 "
             "`/herdr-team:up` 을 실행한다.",
             "- 메인은 사용자와 대화하고 판단한다. 산출물은 태스크로 맡기고, 관제가 올린 decide 를 처리한다"
             "(CLAUDE.md \"메인 규칙\")."]
    if not os.environ.get("HC_TERMINAL_ID", "").strip():
        lines.append("- 이 세션은 Herdr 터미널이 아니다($HC_TERMINAL_ID 없음). watch·answer·큐 명령은 Herdr 터미널의 메인 "
                     "세션에서만 된다. 사용자에게 Herdr 안에서 다시 열라고 알린다.")
    asked = len(outbox.open_questions(p))
    if asked:
        lines.append(f"- 답하지 않은 질문이 {asked}건 있다(decide 포함). `/herdr-team:up` 이 `hteam reask` 로 다시 보여 준다.")
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}}


def role_mark(p, payload: dict):
    """아직 캐시가 없으면 이번 프롬프트에서 다시 판별한다. 고정 에이전트 작업 터미널(state/crew.json)이면 늘 캐시를 지우고
    다시 판별한다(태스크마다 직무가 바뀐다, 설계 9.4 6단계). crew.json 을 읽지 못하면 오류를 남기고 캐시를 쓴다.
    메인이면 매 프롬프트 자동 부활을 확인한다(60초 간격)."""
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    fresh = False
    if term:
        try:
            fresh = roles.crew_terminal(p, term)
        except HteamError as exc:
            log_error(p.root, f"역할 판별: {exc.code}: {exc.message}")
    if role_of(p, payload, fresh=fresh) != "main":
        return None
    notice = auto_up(p, force=False)
    if not notice:
        return None
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": notice}}


def stop(p, payload: dict):
    """메인이고 run.json 에 run_id 가 있고 관제가 꺼지지 않았는데(8.2 의 alive·hung·starting) watch 가 없으면 턴을 끝내지
    못하게 한다(설계 9.4). 관제가 꺼졌으면 watch 가 곧바로 orphaned 로 끝나므로 막지 않는다(막으면 watch → orphaned → up
    실패 → Stop 이 사용자 입력 없이 되풀이된다. 꺼진 관제는 다음 프롬프트의 자동 부활 확인이 알린다, 9.5). 다만 outbox 에
    미전달 항목이 있으면(outbox.unread, watch 와 같은 기준) 관제가 꺼졌어도 막는다: watch 는 관제 생존을 보기 전에 그것을
    준다(Codex 커밋 리뷰 81c2c30). 전달하면 커서가 따라잡아 다음 Stop 은 막지 않는다. 관제 판정은 pid·heartbeat 만 본다
    (hc 를 부르지 않는다). stop_hook_active 면 다시 막지 않는다. Herdr 터미널 밖($HC_TERMINAL_ID
    없음)의 메인은 watch 를 띄울 수 없으므로(require_main 이 exit 5) 막지 않는다.

    watch 생존은 watch.pid 기록(pid + 시작 시각)으로 본다. 죽었거나 pid 가 다른 프로세스에 다시 쓰였으면 watch 가 없다.
    run.json 을 읽지 못하면 bad_run_file 이 오류 기록으로 남고 막지 않는다."""
    if payload.get("stop_hook_active") or p.setup_mode.exists() or role_of(p, payload) != "main":
        return None
    if not os.environ.get("HC_TERMINAL_ID", "").strip():
        return None
    if not outbox._run(p).get("run_id"):
        return None
    if outbox._orphaned(p) and not outbox.unread(p):
        return None
    if outbox.watch_alive(p):
        return None
    return {"decision": "block",
            "reason": f"herdr-team: watch 가 꺼져 있다. Bash `run_in_background: true` 로 `{SHIM} watch` 를 띄우고 턴을 "
                      "끝낸다. 이미 받은 메시지가 있으면 사용자에게 먼저 전한다."}


HANDLERS = {"session-start": session_start, "role-mark": role_mark, "guard": guard, "stop": stop}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in HANDLERS:
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        root = find_root(payload) if isinstance(payload, dict) else None
    except (ValueError, OSError, TypeError, RuntimeError):
        return 0
    if root is None:
        return 0
    try:
        _load()
        out = HANDLERS[sys.argv[1]](Project(root), payload)
    except Exception as exc:  # noqa: BLE001  훅은 세션을 막지 않는다(hteam 을 가져오지 못한 것 포함)
        code = getattr(exc, "code", None)
        log_error(root, (f"{code}\n" if isinstance(code, str) else "") + traceback.format_exc())
        return 0
    if out:
        print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
