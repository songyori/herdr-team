"""세팅과 코디네이터(설계 9.1–9.3): doctor, scaffold, up, bind, setup-done."""
from __future__ import annotations

import hashlib
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, coord, gitio, herdr, outbox, roles
from .errors import CONFLICT, DENIED, FAIL, TIMEOUT, USAGE, HteamError
from .horch import Horch
from .paths import PLUGIN_ROOT, SHIM, TEMPLATES, Project, find_project
from .util import die_at, env_float, flock, now, write_json

MARK = "<!-- herdr-team -->"
COORD_PROMPT = f"`{SHIM} bind` 를 실행하고 `.herdr-team/coordinator.md` 를 따른다."
# 템플릿 → 프로젝트 경로. 있는 파일은 덮어쓰지 않는다.
FILES = {
    "config.toml": ".herdr-team/config.toml",
    "coordinator.md": ".herdr-team/coordinator.md",
    "roles/planner.md": ".herdr-team/roles/planner.md",
    "roles/developer.md": ".herdr-team/roles/developer.md",
    "roles/tester.md": ".herdr-team/roles/tester.md",
    "shim.py": ".herdr-team/bin/hteam",
}
# up 이 띄울 때 바꾸는 run.json 키. 띄우기가 확실히 실패하면 이것만 되돌린다(main_terminals 등 다른 키는 그대로 둔다).
LAUNCH_KEYS = ("pending_launch", "team_space", "team_tab", "launched_at", "coordinator_terminal", "coordinator_argv")
# up 이 판정한 뒤 이 키가 바뀌었으면 판정이 낡았다(다른 up 이 띄웠거나 코디네이터가 bind 했다): launch_raced.
RACE_KEYS = ("pending_launch", "run_id", "bound_nonce", "bound_at", "coordinator_terminal", "coordinator_argv")


def _check(name: str, ok, detail: str, level: str = "error") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail, "level": level}


def _first_line(text: str) -> str:
    return (text.strip().splitlines() or [""])[0][:200]


def _chrome_mcp(root: Path) -> bool:
    """Chrome DevTools MCP 설정이 보이나(경고만). 사용자·프로젝트 설정 파일에서 이름을 찾는다."""
    home = Path(os.environ.get("HOME") or Path.home())
    for path in (home / ".claude.json", home / ".claude" / "settings.json", root / ".mcp.json"):
        try:
            if "chrome-devtools" in path.read_text(encoding="utf-8"):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _horch_checks(root: Path) -> list[dict]:
    """horch 찾기와 horch doctor. horch 항목은 늘 하나다(찾은 뒤 doctor 가 실패해도 두 번 적지 않는다)."""
    home = root / ".herdr-team" / "state" / "horch"
    temp = None
    try:
        if not home.exists():
            temp = tempfile.mkdtemp(prefix="hteam-doctor-")
            home = Path(temp)
        h = Horch(home)
        code, data = h.call("doctor")
    except HteamError as exc:
        return [_check("horch", False, exc.message)]
    except OSError as exc:
        return [_check("horch", False, str(exc))]
    finally:
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
    bad = [c["name"] for c in data.get("checks") or [] if not c.get("ok") and c.get("level") == "error"]
    return [_check("horch", True, str(h.bin)),
            _check("horch_doctor", code == 0, "hc·herdr-app 포함 통과" if code == 0 else
                   f"실패: {', '.join(bad) or (data.get('error') or {}).get('message')}")]


def _codex_checks(codex: str) -> list[dict]:
    """로그인(필수)과 image_generation(경고)을 따로 본다. features 조회 실패는 경고일 뿐이다."""
    checks = []
    try:
        proc = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=30)
        checks.append(_check("codex_login", proc.returncode == 0,
                             _first_line(proc.stdout or proc.stderr) or f"exit {proc.returncode}"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append(_check("codex_login", False, str(exc)))
    try:
        proc = subprocess.run([codex, "features", "list"], capture_output=True, text=True, timeout=30)
        row = next((ln.split() for ln in proc.stdout.splitlines() if ln.split()[:1] == ["image_generation"]), None)
        checks.append(_check("codex_image_generation", bool(row) and row[-1] == "true",
                             " ".join(row) if row else "항목 없음. codex features enable image_generation(이미지 생성만 막힌다)",
                             "warning"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append(_check("codex_image_generation", False, f"codex features list 실패: {exc}", "warning"))
    return checks


def doctor(root: Path) -> dict:
    """설계 9.2. 필수 점검이 실패하면 exit 1(checks 포함).

    설계 9.2 의 "Codex 래퍼 실행 가능" 점검은 래퍼(scripts/codex-run.sh)가 들어오는 3단계에서 더한다."""
    checks = [_check("python", sys.version_info >= (3, 11), platform.python_version())]
    git = shutil.which("git")
    checks.append(_check("git", git, git or "PATH 에 없다"))
    if git:
        repo = gitio.is_repo(root)
        checks.append(_check("git_repo", repo, "git 저장소다" if repo else
                             "git 저장소가 아니다: git init 뒤 git commit --allow-empty -m init 을 권한다", "warning"))
    checks += _horch_checks(root)
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    checks.append(_check("herdr_terminal", term, term or "$HC_TERMINAL_ID 가 없다. Herdr 터미널 안에서 실행한다"))
    claude = shutil.which("claude")
    checks.append(_check("claude", claude, claude or "PATH 에 없다"))
    codex = shutil.which("codex")
    checks.append(_check("codex", codex, codex or "PATH 에 없다(리뷰어·Codex 워커에 쓴다)"))
    if codex:
        checks += _codex_checks(codex)
    checks.append(_check("chrome_devtools_mcp", _chrome_mcp(root), "디렉터 레퍼런스 캡처에 쓴다(없으면 링크만 남긴다)",
                         "warning"))
    if not all(c["ok"] for c in checks if c["level"] == "error"):
        raise HteamError("unhealthy", "필수 점검이 실패했다", FAIL, data={"checks": checks})
    return {"healthy": True, "checks": checks}


def _read_existing(path: Path) -> str | None:
    """있는 파일을 줄 끝 그대로 읽는다. 없으면 None. UTF-8 이 아니거나 읽지 못하면 unreadable_file(exit 2)."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        why = exc.reason if isinstance(exc, UnicodeDecodeError) else exc.strerror or str(exc)
        raise HteamError("unreadable_file", f"{path.name} 을 UTF-8 로 읽지 못했다: {why}", USAGE,
                         f"{path.name} 을 UTF-8 로 바꾸거나 고친 뒤 다시 한다(아무것도 바꾸지 않았다)") from None


def _append(path: Path, old: str | None, text: str, blank: bool) -> None:
    """기존 내용(old) 뒤에 text 를 덧붙인다. 기존 바이트는 건드리지 않고 기존 줄 끝(CRLF 면 CRLF)을 따른다.
    blank 면 앞 내용과 빈 줄 하나로 띄운다."""
    old = old or ""
    eol = "\r\n" if "\r\n" in old else "\n"
    body = eol.join(text.strip("\n").split("\n")) + eol
    sep = ""
    if old:
        if not old.endswith("\n"):
            sep = eol
        if blank and not (old + sep).endswith(eol + eol):
            sep += eol
    with open(path, "a", encoding="utf-8", newline="") as fh:
        fh.write(sep + body)


def scaffold(root: Path, description: str) -> dict:
    """설계 9.1 3. 있는 파일은 덮어쓰지 않는다. state/plugin-root 를 만들고, setup-done 전이면 state/setup-mode 를 만든다.

    CLAUDE.md·AGENTS.md·.gitignore 는 기존 내용 뒤에 덧붙이기만 한다. 셋 가운데 읽지 못하는 것이 있으면 아무것도 바꾸지
    않고 거부한다. setup-done 뒤에 다시 부르면 setup-mode 를 다시 켜지 않는다(state/setup-done)."""
    if not description.strip():
        raise HteamError("no_description", "프로젝트 설명이 비었다", USAGE)
    root = Path(root)
    if not root.is_dir():
        raise HteamError("no_root", f"{root} 폴더가 없다", USAGE)
    existing = {name: _read_existing(root / name) for name in ("CLAUDE.md", "AGENTS.md", ".gitignore")}
    created, skipped = [], []
    for src, rel in FILES.items():
        dst = root / rel
        if dst.exists():
            skipped.append(rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(TEMPLATES / src, dst)
        if rel.endswith("bin/hteam"):
            dst.chmod(0o755)
        created.append(rel)
    project_md = root / ".herdr-team" / "project.md"
    if project_md.exists():
        skipped.append(".herdr-team/project.md")
    else:
        project_md.write_text(description.strip() + "\n", encoding="utf-8")
        created.append(".herdr-team/project.md")
    keep = root / ".herdr-team" / "tasks" / ".gitkeep"
    if not keep.exists():
        keep.parent.mkdir(parents=True, exist_ok=True)
        keep.write_text("", encoding="utf-8")
        created.append(".herdr-team/tasks/.gitkeep")
    for name, tpl in (("CLAUDE.md", "CLAUDE.section.md"), ("AGENTS.md", "AGENTS.section.md")):
        if MARK in (existing[name] or ""):
            skipped.append(name)
            continue
        _append(root / name, existing[name], (TEMPLATES / tpl).read_text(encoding="utf-8"), blank=True)
        created.append(name)
    if ".herdr-team/state/" in [_ignore_pattern(ln) for ln in (existing[".gitignore"] or "").splitlines()]:
        skipped.append(".gitignore")
    else:
        _append(root / ".gitignore", existing[".gitignore"], ".herdr-team/state/", blank=False)
        created.append(".gitignore")
    p = Project(root)
    p.ensure_state()
    setup_mode = not _setup_done_file(p).exists()
    if setup_mode:
        p.setup_mode.write_text(now() + "\n", encoding="utf-8")
    p.plugin_root_file.write_text(str(PLUGIN_ROOT) + "\n", encoding="utf-8")
    return {"root": str(root), "created": created, "skipped": skipped, "setup_mode": setup_mode}


def _ignore_pattern(line: str) -> str:
    """git 이 읽는 .gitignore 패턴. 끝 공백은 백슬래시로 막지 않았으면 버린다. 앞 공백은 패턴의 일부다(지우지 않는다)."""
    while line.endswith(" ") and not line.endswith("\\ "):
        line = line[:-1]
    return line


def _setup_done_file(p) -> Path:
    """setup-done 이 남기는 표시. 있으면 scaffold 가 setup-mode 를 다시 켜지 않는다."""
    return p.state / "setup-done"


def team_tab(root: Path, space: str) -> str:
    """팀 탭 id 는 프로젝트·space 마다 고정이다(없으면 Herdr 가 새 탭으로 만든다)."""
    return "tb" + hashlib.sha1(f"herdr-team\n{root}\n{space}".encode("utf-8")).hexdigest()[:32]


def _read_run(p) -> dict:
    """run.json. 없으면 {}. 있는데 읽지 못하거나 JSON 객체가 아니면 bad_run_file(exit 1, 덮어쓰지 않는다)."""
    return outbox._run(p)


def _run_update(p, fn) -> dict:
    """run.json 을 잠금(state/run.lock) 안에서 읽고 fn 으로 바꿔 쓴다. fn 이 예외를 내면 쓰지 않는다.

    run.lock 은 다른 hteam 잠금 안에서 잡지 않는다(잡는 곳: setup 의 up·bind, outbox.note_main. 셋 다 안에서 다른
    hteam 잠금을 잡지 않는다)."""
    p.ensure_state()
    with flock(p.state / "run.lock"):
        run = _read_run(p)
        fn(run)
        write_json(p.run_file, run)
        return run


def _bound(run: dict) -> bool:
    return bool(run.get("run_id")) and run.get("bound_nonce") == (run.get("pending_launch") or {}).get("nonce")


def _never_started(exc: HteamError) -> bool:
    """hc 를 실행하지도 못했다(없음·실행 실패). 터미널이 생겼을 리 없다."""
    return exc.code == "hc_missing" or exc.data.get("kind") == "exec_failed"


def _uncertain(exc: HteamError) -> bool:
    """hc 가 무엇을 했는지 모른다: 시간 초과, 오류 JSON 없는 실패(exit_N), 읽을 수 없는 성공 출력(bad_output)."""
    kind = str(exc.data.get("kind") or "")
    return exc.code == "hc_timeout" or kind.startswith("exit_") or kind == "bad_output"


def _find_launched(name: str, argv: list[str]) -> tuple[str | None, bool]:
    """이번에 띄운 터미널을 이름으로 찾는다. (주소 또는 None, 확인했나). hc get 이 not_found 가 아닌 이유로 실패하면
    확인하지 못한 것이다. 이름이 같아도 argv(nonce 포함)가 다르면 이번 것이 아니다."""
    try:
        info = herdr.get(name)
    except HteamError as exc:
        return None, exc.data.get("kind") == "not_found"
    if info.get("address") and info.get("argv") == argv:
        return info["address"], True
    return None, True


def _wait_bound(p, nonce: str, wait: float | None) -> str | None:
    """wait 초 동안 이 nonce 의 코디네이터가 bind 하기를 기다린다. 했으면 bind 가 기록한 터미널, 아니면 None."""
    deadline = time.monotonic() + (wait or 0)
    while True:
        run = _read_run(p)
        if (run.get("pending_launch") or {}).get("nonce") == nonce and _bound(run):
            return run.get("coordinator_terminal")
        if time.monotonic() >= deadline:
            return None
        time.sleep(env_float("HTEAM_POLL", 0.5))


def up(p, wait_run: float | None, force: bool = False) -> dict:
    """설계 9.3: 코디네이터가 살아 있으면 그대로, 아니면 pending_launch 를 먼저 쓰고 팀 탭에 띄운다.

    메인만 부른다(무엇이든 바꾸기 전에 outbox.require_main). 새로 띄우는 것은 처음이거나 끝남·소실(exited·lost)이
    확인됐을 때만이다. 확인할 수 없으면(unverifiable) 기록과 nonce 를 그대로 두고 exit 3. 사용자가 끝났다고 확인하면
    --force 로 띄우고, bind 가 run-use --force 로 넘겨받는다.

    hc run 이 실패하면: 터미널이 생기지 않았다고 확인되면 이번에 바꾼 키만 되돌린다. 무엇을 했는지 모르면(시간 초과,
    응답 유실) 이름으로 찾아 있으면 기록하고, 없거나 찾지 못하면 nonce 와 pending_launch 를 남기고 exit 1
    launch_uncertain(떴다면 스스로 bind 한다. 아니면 180초 뒤 다음 up 이 새로 띄운다)."""
    cfg = config.load(p)
    main = outbox.require_main(p)
    seen = _read_run(p)
    view = coord.coordinator_view(p)
    if view["alive"] or view["starting"]:
        result = {"status": "alive" if view["alive"] and _bound(_read_run(p)) else "starting",
                  "terminal": view["terminal"], "launched": False}
    elif view["verdict"] == "unverifiable" and not force:
        raise HteamError("coordinator_unverifiable", f"코디네이터 터미널 {view['terminal']} 의 상태를 확인할 수 없다", CONFLICT,
                         "기록과 nonce 는 그대로 두었다. pane 을 보고 끝났다고 확신하면 hteam up --force",
                         data={"terminal": view["terminal"]})
    else:
        space = (herdr.get(main).get("labels") or {}).get("herdr.space")
        if not space:
            raise HteamError("no_space", f"메인 터미널 {main} 에 herdr.space 라벨이 없다", FAIL)
        nonce, tab, name = secrets.token_hex(8), team_tab(p.root, space), f"hteam-coord-{secrets.token_hex(3)}"
        before: dict = {}

        def pending(run: dict) -> None:
            if any(run.get(k) != seen.get(k) for k in RACE_KEYS):
                raise HteamError("launch_raced", "판정하는 사이에 다른 hteam up 이 띄웠거나 코디네이터가 bind 했다", CONFLICT,
                                 "hteam status 로 코디네이터를 확인한다(띄우는 중이면 hteam up --wait-run 180)")
            before.update({k: run[k] for k in LAUNCH_KEYS if k in run})
            # 인계 승인(force)은 bind 가 성공할 때까지 이어 받는다: 강제로 띄운 코디네이터가 bind 전에 끝나 다시 띄워도
            # 이전 소유자는 여전히 확인할 수 없으므로 bind 의 run-use 에 --force 가 필요하다
            forced = force or bool((run.get("pending_launch") or {}).get("force") and not _bound(run))
            run.update(pending_launch={"nonce": nonce, "at": now(), "force": forced}, team_space=space, team_tab=tab,
                       launched_at=now())
            run.pop("coordinator_terminal", None)
            run.pop("coordinator_argv", None)

        def restore(run: dict) -> None:
            # 이번 up 이 바꾼 키만 되돌린다. 그사이 다른 up 이 덮어썼거나 이 nonce 로 bind 까지 했으면 건드리지 않는다
            if (run.get("pending_launch") or {}).get("nonce") == nonce and run.get("bound_nonce") != nonce:
                for key in LAUNCH_KEYS:
                    if key in before:
                        run[key] = before[key]
                    else:
                        run.pop(key, None)

        die_at("up_before_pending")
        _run_update(p, pending)
        argv = ["env", "HTEAM_ROLE=coordinator", f"HTEAM_LAUNCH={nonce}", "claude"]
        for flag, value in (("--model", cfg.coordinator.get("model")), ("--effort", cfg.coordinator.get("effort"))):
            if value:
                argv += [flag, value]
        argv += [*cfg.args("claude"), "--", COORD_PROMPT]
        die_at("up_before_hc_run")
        recovered = bound_seen = False
        try:
            address = herdr.run_bg(name, str(p.root),
                                   {"herdr.space": space, "herdr.tab": tab, "hteam.role": "coordinator"}, argv).get("address")
            if not address:
                raise HteamError("hc_failed", "hc run 출력에 터미널 주소가 없다", FAIL, data={"kind": "bad_output"})
        except HteamError as exc:
            address, known = (None, True) if _never_started(exc) else _find_launched(name, argv)
            if address is None:
                if _never_started(exc) or (known and not _uncertain(exc)):
                    _run_update(p, restore)  # hc 가 거부했고 터미널도 없다: 확실한 실패
                    raise
                # 떴다면 곧 이 nonce 로 bind 한다: --wait-run 동안 기다린다. bind 가 터미널·argv 를 기록한다
                address = _wait_bound(p, nonce, wait_run)
                if address is None:
                    raise HteamError("launch_uncertain", f"코디네이터를 띄웠는지 확인하지 못했다(hc run: {exc.message})",
                                     FAIL, f"pending_launch 와 nonce 는 남겼다. 떴다면 팀 탭의 {name} pane 이 스스로 bind "
                                     f"한다. hteam status 의 coordinator 를 보고, 띄운 지 180초가 지나도 bind 하지 않으면 "
                                     f"hteam up(새로 띄운다)", data={"name": name, "terminal": None}) from None
                bound_seen = True
            recovered = True
        if address == main:
            _run_update(p, restore)
            raise HteamError("same_terminal", f"코디네이터 터미널({address})이 메인 터미널과 같다", CONFLICT)

        def record(run: dict) -> None:
            if (run.get("pending_launch") or {}).get("nonce") == nonce:
                run.update(coordinator_terminal=address, coordinator_argv=argv)

        if not bound_seen:
            _run_update(p, record)
        result = {"status": "launched", "terminal": address, "team_tab": tab, "launched": True,
                  "tab_renamed": herdr.rename_tab(tab, "팀", pause=env_float("HTEAM_POLL", 0.3))}
        if recovered:
            result["recovered"] = True  # hc 가 실패를 알렸지만 이름으로 찾았거나 그 nonce 로 bind 했다
    if wait_run:
        deadline = time.monotonic() + wait_run
        while not _bound(_read_run(p)):
            if time.monotonic() >= deadline:
                raise HteamError("timeout", f"{wait_run:g}초 안에 코디네이터가 bind 하지 않았다", TIMEOUT,
                                 "코디네이터 pane 을 본다(폴더 신뢰 확인 창 등)", data=result)
            time.sleep(env_float("HTEAM_POLL", 0.5))
        result["run_id"] = _read_run(p).get("run_id")
    return result


_BIND_HINTS = {
    "owner_alive": ("이전 코디네이터가 아직 살아 있다. 메인에 알린다. 사용자가 그 코디네이터와 이 코디네이터를 끝낸 뒤 메인에서 "
                    "hteam up(그 pane 을 닫아 상태를 확인할 수 없게 됐으면 hteam up --force)"),
    "owner_unverifiable": ("이전 코디네이터의 상태를 확인할 수 없다. 메인에 알린다. 사용자가 끝났다고 확인하면 이 코디네이터를 "
                           "끝내고 메인에서 hteam up --force"),
}


def bind(p) -> dict:
    """설계 9.3: 코디네이터만(HTEAM_ROLE·HTEAM_LAUNCH nonce). 이전 run_id 가 있으면 run-use, 없으면 run-create.

    nonce 확인부터 run-use·run-create 와 run.json 기록까지 run.lock 을 쥔다. 그래서 그사이 up 이 nonce 를 바꿔 지난
    코디네이터가 horch Run 을 차지한 채 run.json 만 새 코디네이터를 가리키는 일이 없다(up 은 bind 뒤에 launch_raced)."""
    p.ensure_state()
    with flock(p.state / "run.lock"):
        run = _read_run(p)
        roles.require_coordinator(p)
        term = os.environ.get("HC_TERMINAL_ID", "").strip()
        if not term:
            raise HteamError("no_terminal", "Herdr 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
        nonce = os.environ["HTEAM_LAUNCH"]
        h = Horch(p.horch_home)
        die_at("bind_locked")
        mode, data = "create", None
        if run.get("run_id"):
            # up --force 로 띄웠고 그 뒤 bind 가 아직 성공하지 않았을 때만 확인할 수 없는 이전 소유자를 넘겨받는다
            # (horch run-use --force). 그 밖에는 --force 없이 부른다
            force = ["--force"] if (run.get("pending_launch") or {}).get("force") and not _bound(run) else []
            code, data = h.call("run-use", "--id", run["run_id"], *force)
            if code == 0 and data.get("ok"):
                mode = "use"
            elif (data.get("error") or {}).get("code") != "unknown_run":
                err = data.get("error") or {}
                raise HteamError(f"horch_{err.get('code')}", f"run-use 실패: {err.get('message')}", code or FAIL,
                                 _BIND_HINTS.get(err.get("code")) or err.get("hint") or "", data={"horch": data})
        if mode == "create":
            try:
                objective = _first_line(p.project_md.read_text(encoding="utf-8")) if p.project_md.exists() else ""
            except (OSError, UnicodeDecodeError):
                objective = ""
            data = h.ok("run-create", "--objective", objective or "herdr-team")
        try:
            argv = herdr.get(term).get("argv")
        except HteamError:
            argv = None
        run.update(run_id=data["run"]["id"], coordinator_terminal=term, bound_nonce=nonce, bound_at=now())
        if argv is not None:
            run["coordinator_argv"] = argv
        write_json(p.run_file, run)
    return {"run_id": data["run"]["id"], "mode": mode, "previous_owner": data.get("previous_owner"),
            "owner_tab": data["run"].get("owner_tab"), "horch": h.cmd()}


def _root_arg(args) -> Path:
    return Path(args.root).expanduser().resolve() if args.root else Path.cwd()


def _cmd_doctor(args) -> dict:
    return doctor(_root_arg(args))


def _cmd_scaffold(args) -> dict:
    try:
        text = Path(args.description_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise HteamError("bad_description_file", f"설명 파일을 읽지 못했다: {exc}", USAGE) from exc
    return scaffold(_root_arg(args), text)


def _cmd_up(args) -> dict:
    return up(find_project(args.root), args.wait_run, args.force)


def _cmd_bind(args) -> dict:
    return bind(find_project(args.root))


def _cmd_setup_done(args) -> dict:
    p = find_project(args.root)
    p.ensure_state()
    _setup_done_file(p).write_text(now() + "\n", encoding="utf-8")
    p.setup_mode.unlink(missing_ok=True)
    return {"setup_mode": False}


def register(sub) -> None:
    sub.add_parser("doctor").set_defaults(func=_cmd_doctor)
    s = sub.add_parser("scaffold")
    s.add_argument("--description-file", required=True)
    s.set_defaults(func=_cmd_scaffold)
    s = sub.add_parser("up")
    s.add_argument("--wait-run", type=float, metavar="S")
    s.add_argument("--force", action="store_true", help="상태를 확인할 수 없는 코디네이터를 끝난 것으로 보고 새로 띄운다")
    s.set_defaults(func=_cmd_up)
    sub.add_parser("bind").set_defaults(func=_cmd_bind)
    sub.add_parser("setup-done").set_defaults(func=_cmd_setup_done)
