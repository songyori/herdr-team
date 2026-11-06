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

LIB = Path(__file__).resolve().parents[1] / "lib"
# hteam 모듈. _load() 가 herdr-team 프로젝트에서만 채운다
herdr = outbox = roles = HteamError = PLUGIN_ROOT = SHIM = Project = None
die_at = flock = read_json = write_atomic = write_json = None

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
SETUP_PREFIXES = (".herdr-team/", ".claude/", "docs/superpowers/")
SETUP_FILES = {"CLAUDE.md", "AGENTS.md", ".gitignore"}
STATE_DIR = ".herdr-team/state"
SESSION_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# 캐시하는 역할. 코디네이터는 캐시하지 않는다(늘 환경 변수와 nonce 로 본다)
CACHED_RE = re.compile(r"^(main|reviewer|worker(:[a-z][a-z0-9-]*)?)$")
NOISE_RE = re.compile(r"[\s#*_>|\-`]+")
FINGERPRINT = 80  # 정규화한 render.context 앞 80자가 메인 텍스트에 있으면 보여 준 것으로 본다
TAIL_BYTES = 1 << 20

# 메인 Bash 의 horch 직접 실행 판별(calls_horch)
HORCH_RE = re.compile(r"(^|[\s;&|(`'\"/])horch(?=$|[\s;&|)`'\"])")  # 명령을 나누지 못할 때: 낱말만 나와도 거부
WRAPPERS = {"env", "command", "builtin", "exec", "nohup", "time", "nice", "sudo"}
WRAPPER_ARGS = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-R", "-T", "-U", "-r", "-t"},
                "env": {"-u", "-C", "-S"}, "nice": {"-n"}, "time": {"-f", "-o"}, "exec": {"-a"}}  # 값을 받는 옵션
SHELLS = {"bash", "sh", "zsh"}
INTERP_RE = re.compile(r"^(python[0-9.]*|bash|sh|zsh)$")
SHELL_C_RE = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")  # -c, -lc 등
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PUNCT = set("();<>|&")
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?[ \t]*(\\?)(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
NEST = 4  # 명령 치환·-c 글을 따라 들어가는 깊이 상한. 넘으면 낱말 규칙(닫힌 쪽)


def _load() -> None:
    """hteam 모듈을 가져온다. herdr-team 프로젝트를 찾은 뒤에만 부른다. 실패는 main() 이 오류 기록으로 남긴다."""
    global herdr, outbox, roles, HteamError, PLUGIN_ROOT, SHIM, Project
    global die_at, flock, read_json, write_atomic, write_json
    if str(LIB) not in sys.path:
        sys.path.insert(0, str(LIB))
    from hteam import herdr, outbox, roles
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
    """코디네이터 환경 → 캐시 → 판별. 확실할 때만 state/sessions/<session id> 에 캐시한다.

    fresh(SessionStart): 캐시를 믿지 않고 지운 뒤 다시 판별한다. `claude --continue`·`--resume` 은 session id 를 그대로
    이어 쓰므로 다른 터미널(워커 등)에서 쓰던 캐시가 남아 있을 수 있다. run.json 을 읽지 못해 코디네이터인지 확인할 수
    없으면 오류를 남기고 모름(unknown)으로 둔다."""
    sid = _session(payload)
    cache = p.sessions / sid if sid else None
    if fresh and cache is not None:
        cache.unlink(missing_ok=True)
    try:
        if roles.coordinator_env(p):
            return "coordinator"
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


def _heredocs(cmd: str) -> tuple[str, list[str]]:
    """(heredoc 본문 줄을 뺀 명령, 명령 치환이 일어나는 본문들). 본문은 명령이 아니다. 구분자를 따옴표나 `\\` 로 막은
    본문은 글자 그대로라 치환도 없다."""
    kept, bodies, pending = [], [], []
    for line in cmd.split("\n"):
        if pending:
            delim, literal, body = pending[0]
            if line.strip() == delim:
                pending.pop(0)
                if not literal:
                    bodies.append("\n".join(body))
            else:
                body.append(line)
            continue
        kept.append(line)
        pending = [(m.group(3), bool(m.group(1) or m.group(2)), []) for m in HEREDOC_RE.finditer(line)]
    bodies += ["\n".join(body) for _, literal, body in pending if not literal]
    return "\n".join(kept), bodies


def _substitutions(text: str, quotes: bool = True) -> list[str]:
    """셸이 실행하는 명령 치환 `$(…)`·`` `…` `` 의 본문(큰따옴표 안 포함). 작은따옴표 안과 `\\` 로 막은 글자는 건너뛴다.
    quotes=False 는 heredoc 본문이다(따옴표가 글자일 뿐이다)."""
    found, i, quote = [], 0, None
    while i < len(text):
        c = text[i]
        if quote == "'":
            quote = None if c == "'" else quote
            i += 1
        elif c == "\\":
            i += 2
        elif quotes and c == "'" and quote is None:
            quote, i = "'", i + 1
        elif quotes and c == '"':
            quote, i = (None if quote == '"' else '"'), i + 1
        elif c == "`":
            end = text.find("`", i + 1)
            end = len(text) if end < 0 else end
            found.append(text[i + 1:end])
            i = end + 1
        elif text.startswith("$(", i) and not text.startswith("$((", i):
            depth, j = 1, i + 2
            while j < len(text) and depth:
                depth += {"(": 1, ")": -1}.get(text[j], 0)
                j += 1
            found.append(text[i + 2:j - 1] if depth == 0 else text[i + 2:])
            i = j
        else:
            i += 1
    return found


def calls_horch(cmd: str, depth: int = 0) -> bool:
    """Bash 명령이 horch 를 실행하는가(설계 9.4 '직접 부르면'). 인자나 따옴표 안 글에 나오는 낱말은 실행이 아니다.

    단순 명령(`; & && | || ( )`·줄바꿈으로 나눔)마다 앞의 NAME=값·감싸는 명령(env·sudo 등)과 그 옵션을 건너뛴 명령어를
    본다. 이름이 horch 이거나, python·셸의 첫 인자(스크립트)가 horch 이거나, `bash|sh|zsh -c <글>`·`eval <글>` 의 글이
    horch 를 실행하면 참이다. 명령 치환 본문도 같은 규칙으로 본다. 따옴표가 맞지 않아 나누지 못하면 낱말만 나와도
    참이다(닫힌 쪽)."""
    if depth > NEST:
        return bool(HORCH_RE.search(cmd))
    text, bodies = _heredocs(cmd)
    inner = _substitutions(text) + [s for body in bodies for s in _substitutions(body, quotes=False)]
    if any(calls_horch(s, depth + 1) for s in inner):
        return True
    try:
        lex = shlex.shlex(text.replace("\n", ";"), posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        lex.commenters = ""  # `#` 뒤를 버리면 뒤따르는 명령까지 숨을 수 있다
        tokens = list(lex)
    except ValueError:
        return bool(HORCH_RE.search(cmd))
    words, target = [], False
    for tok in tokens + [";"]:
        if target:  # 리다이렉션 대상(파일 이름)은 명령어가 아니다
            target = False
            continue
        if tok and set(tok) <= PUNCT:
            if ("<" in tok or ">" in tok) and "(" not in tok and ")" not in tok:
                target = True
                continue
            if words and _simple_calls(words, depth):
                return True
            words = []
        else:
            words.append(tok)
    return False


def _command_index(words: list[str]) -> int:
    """단순 명령에서 명령어의 위치. 앞의 NAME=값, 감싸는 명령과 그 옵션(값을 받는 옵션은 값까지)을 건너뛴다."""
    i, wrapper = 0, None
    while i < len(words):
        word = words[i]
        if ASSIGN_RE.match(word) or word in WRAPPERS:
            wrapper = word if word in WRAPPERS else wrapper
            i += 1
        elif wrapper and word == "--":
            return i + 1
        elif wrapper and word.startswith("-") and len(word) > 1:
            i += 2 if word in WRAPPER_ARGS.get(wrapper, ()) else 1
        else:
            return i
    return i


def _simple_calls(words: list[str], depth: int) -> bool:
    i = _command_index(words)
    if i >= len(words):
        return False
    name, args = os.path.basename(words[i]), words[i + 1:]
    if name == "horch":
        return True
    if name == "eval":
        return calls_horch(" ".join(args), depth + 1)
    if name in SHELLS:
        flag = next((k for k, a in enumerate(args) if SHELL_C_RE.match(a)), None)
        if flag is not None:
            return flag + 1 < len(args) and calls_horch(args[flag + 1], depth + 1)
    if INTERP_RE.match(name):
        script = next((a for a in args if not a.startswith("-")), "")
        return os.path.basename(script) == "horch"
    return False


def deny(reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def _transcript_text(path) -> str | None:
    """transcript(JSONL) 끝부분의 assistant text. 읽지 못하면 None(판단 불가 → 통과)."""
    if not isinstance(path, str) or not path or not Path(path).is_file():
        return None
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
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


def _denied_ids(p) -> list:
    data = read_json(p.context_denied, {})
    ids = data.get("ids") if isinstance(data, dict) else None
    return ids if isinstance(ids, list) else []


def context_guard(p, payload: dict, tool_input: dict):
    """메인이 render.context 를 먼저 보여 주지 않고 그 질문을 물으면 그 질문에 한해 한 번 거부한다."""
    questions = tool_input.get("questions")
    asked = {q["question"].strip() for q in questions if isinstance(q, dict) and isinstance(q.get("question"), str)} \
        if isinstance(questions, list) else set()
    if not asked:
        return None
    with flock(p.state / "context-denied.lock"):  # context-denied.json 읽고 고쳐 쓰기가 겹쳐 기록을 잃지 않게
        return _context_guard_locked(p, payload, asked)


def _context_guard_locked(p, payload: dict, asked: set):
    denied = _denied_ids(p)
    die_at("context_denied_read")  # 테스트: 읽은 뒤 멈춰 겹친 호출을 재현한다
    items = [q for q in outbox.open_questions(p)
             if q["id"] not in denied and isinstance(q.get("render"), dict)
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
    write_json(p.context_denied, {"ids": [*denied, *(q["id"] for q in unshown)]})  # 임시 파일 + os.replace
    blocks = "\n\n".join(f"[{q['id']}]\n{q['render']['context']}" for q in unshown)
    return deny("이 질문에는 먼저 보여 줄 `render.context` 가 있다. 아래 내용을 요약하거나 바꾸지 말고 평문으로 그대로 "
                f"출력한 뒤 같은 render 로 AskUserQuestion 을 다시 부른다([out-id] 줄은 출력하지 않는다).\n\n{blocks}")


def guard(p, payload: dict):
    role = role_of(p, payload)
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool == "AskUserQuestion":
        if role == "main":
            return context_guard(p, payload, tool_input)
        if role == "coordinator":
            return deny("코디네이터는 사용자에게 직접 묻지 않는다. 질문 JSON(render)을 "
                        f"`{SHIM} notify --type question --json -` 의 표준 입력으로 메인에 올린다(coordinator.md \"메인에 묻기\").")
        if role in ("worker:planner", "worker:director"):
            return deny("기획·디렉터 워커는 AskUserQuestion 을 쓰지 않는다. 질문 JSON 을 "
                        f"`{SHIM} ask-user --task T-xxx --json -` 의 표준 입력으로 보낸다(직무 문서, Bash timeout 600000).")
        if role == "reviewer":
            return deny("리뷰어는 묻지 않는다. 판단할 수 없는 것은 리뷰 파일에 적고 판정을 마친다.")
        if role.startswith("worker"):
            return deny("워커는 사용자에게 직접 묻지 않는다. 프리앰블의 ask 명령(horch ask)으로 코디네이터에게 묻는다.")
        return None
    if tool in EDIT_TOOLS:
        raw = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        kind, real, rel = where(p, raw, _cwd(payload))
        if kind != "unknown" and _in_state(p, real, rel):
            return deny("`.herdr-team/state/` 는 hteam 이 관리한다. 직접 고치지 않는다. 복구는 `hteam status` 의 next 를 따른다.")
        in_team = kind != "unknown" and _below(real, p.team) is not None
        if role == "coordinator" and not in_team:
            shown = rel if kind == "inside" else repr(raw)
            return deny(f"코디네이터는 `.herdr-team/` 밖({shown})을 고치지 않는다. 프로젝트 밖과 풀 수 없는 경로도 같다. "
                        "`hteam task new` 로 워커에게 맡긴다.")
        if role == "main":
            if kind == "unknown":  # setup-mode 에서도 거부한다
                return deny(f"경로를 확인할 수 없다({raw!r}). 메인은 풀 수 없는 경로를 고치지 않는다.")
            # 프로젝트 밖(스크래치 파일 등)은 이 프로젝트의 제품 파일이 아니므로 막지 않는다
            setup = in_team or rel in SETUP_FILES or (rel or "").startswith(SETUP_PREFIXES)
            if kind == "inside" and not setup and not p.setup_mode.exists():
                return deny(f"메인은 제품 파일({rel})을 고치지 않는다. `{SHIM} tell \"<요청>\"` 으로 코디네이터에게 넘긴다.")
        return None
    command = tool_input.get("command")
    if tool == "Bash" and role == "main" and isinstance(command, str) and calls_horch(command):
        return deny(f"메인은 horch 를 직접 부르지 않는다(Run 에 묶이면 깨우기 글이 사용자 입력란에 들어온다). "
                    f"`{SHIM} tell \"<글>\"` 을 쓴다.")
    return None


def session_start(p, payload: dict):
    p.ensure_state()
    write_atomic(p.plugin_root_file, str(PLUGIN_ROOT) + "\n")
    if role_of(p, payload, fresh=True) != "main":
        return None
    lines = ["herdr-team 프로젝트다. 너는 메인이다(사용자와 대화하는 세션). 첫 지시가 코디네이터나 워커 지시면 이 안내를 무시한다.",
             f"- 먼저 `/herdr-team:up` 을 실행한다. 산출물 작업은 `{SHIM} tell \"<요청>\"` 으로 코디네이터에게 넘긴다."]
    asked = len(outbox.open_questions(p))
    if asked:
        lines.append(f"- 답하지 않은 질문이 {asked}건 있다. `/herdr-team:up` 이 `hteam reask` 로 다시 보여 준다.")
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n".join(lines)}}


def role_mark(p, payload: dict):
    role_of(p, payload)  # 아직 캐시가 없으면 이번 프롬프트에서 다시 판별한다
    return None


def stop(p, payload: dict):
    """메인이고 코디네이터가 살아 있는데 watch 가 없으면 턴을 끝내지 못하게 한다. stop_hook_active 면 다시 막지 않는다.

    watch 생존은 watch.pid 기록(pid + 시작 시각)으로 본다. 죽었거나 pid 가 다른 프로세스에 다시 쓰였으면 watch 가 없다.
    run.json 을 읽지 못하면 bad_run_file 이 오류 기록으로 남고 막지 않는다."""
    if payload.get("stop_hook_active") or p.setup_mode.exists() or role_of(p, payload) != "main":
        return None
    if outbox.watch_alive(p):
        return None
    run = outbox._run(p)
    if not run.get("coordinator_terminal") or \
            herdr.probe(run["coordinator_terminal"], run.get("coordinator_argv")) != "live":
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
