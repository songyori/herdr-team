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

from . import config, coord, gitio, herdr, roles
from .errors import CONFLICT, DENIED, FAIL, TIMEOUT, USAGE, HteamError
from .horch import Horch
from .paths import PLUGIN_ROOT, SHIM, TEMPLATES, Project, find_project
from .util import env_float, flock, now, read_json, write_json

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
    try:
        home = root / ".herdr-team" / "state" / "horch"
        temp = None
        if not home.exists():
            temp = tempfile.mkdtemp(prefix="hteam-doctor-")
            home = Path(temp)
        try:
            h = Horch(home)
            checks.append(_check("horch", True, str(h.bin)))
            code, data = h.call("doctor")
        finally:
            if temp:
                shutil.rmtree(temp, ignore_errors=True)
        bad = [c["name"] for c in data.get("checks") or [] if not c.get("ok") and c.get("level") == "error"]
        checks.append(_check("horch_doctor", code == 0, "hc·herdr-app 포함 통과" if code == 0 else
                             f"실패: {', '.join(bad) or (data.get('error') or {}).get('message')}"))
    except HteamError as exc:
        checks.append(_check("horch", False, exc.message))
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    checks.append(_check("herdr_terminal", term, term or "$HC_TERMINAL_ID 가 없다. Herdr 터미널 안에서 실행한다"))
    claude = shutil.which("claude")
    checks.append(_check("claude", claude, claude or "PATH 에 없다"))
    codex = shutil.which("codex")
    checks.append(_check("codex", codex, codex or "PATH 에 없다(리뷰어·Codex 워커에 쓴다)"))
    if codex:
        try:
            proc = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=30)
            checks.append(_check("codex_login", proc.returncode == 0,
                                 _first_line(proc.stdout or proc.stderr) or f"exit {proc.returncode}"))
            proc = subprocess.run([codex, "features", "list"], capture_output=True, text=True, timeout=30)
            row = next((ln.split() for ln in proc.stdout.splitlines() if ln.split()[:1] == ["image_generation"]), None)
            checks.append(_check("codex_image_generation", bool(row) and row[-1] == "true",
                                 " ".join(row) if row else "항목 없음. codex features enable image_generation(이미지 생성만 막힌다)",
                                 "warning"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks.append(_check("codex_login", False, str(exc)))
    checks.append(_check("chrome_devtools_mcp", _chrome_mcp(root), "디렉터 레퍼런스 캡처에 쓴다(없으면 링크만 남긴다)",
                         "warning"))
    if not all(c["ok"] for c in checks if c["level"] == "error"):
        raise HteamError("unhealthy", "필수 점검이 실패했다", FAIL, data={"checks": checks})
    return {"healthy": True, "checks": checks}


def _append_section(path: Path, text: str) -> bool:
    """MARK 가 없을 때만 절을 덧붙인다. 있으면 그대로 둔다."""
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if MARK in old:
        return False
    sep = "" if not old or old.endswith("\n\n") else ("\n" if old.endswith("\n") else "\n\n")
    path.write_text(old + sep + text.rstrip() + "\n", encoding="utf-8")
    return True


def scaffold(root: Path, description: str) -> dict:
    """설계 9.1 3. 있는 파일은 덮어쓰지 않는다. state/setup-mode·plugin-root 를 만든다."""
    if not description.strip():
        raise HteamError("no_description", "프로젝트 설명이 비었다", USAGE)
    root = Path(root)
    if not root.is_dir():
        raise HteamError("no_root", f"{root} 폴더가 없다", USAGE)
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
        (created if _append_section(root / name, (TEMPLATES / tpl).read_text(encoding="utf-8")) else skipped).append(name)
    ignore = root / ".gitignore"
    lines = ignore.read_text(encoding="utf-8").splitlines() if ignore.exists() else []
    if ".herdr-team/state/" in lines:
        skipped.append(".gitignore")
    else:
        ignore.write_text("\n".join(lines + [".herdr-team/state/"]) + "\n", encoding="utf-8")
        created.append(".gitignore")
    p = Project(root)
    p.ensure_state()
    p.setup_mode.write_text(now() + "\n", encoding="utf-8")
    p.plugin_root_file.write_text(str(PLUGIN_ROOT) + "\n", encoding="utf-8")
    return {"root": str(root), "created": created, "skipped": skipped}


def team_tab(root: Path, space: str) -> str:
    """팀 탭 id 는 프로젝트·space 마다 고정이다(없으면 Herdr 가 새 탭으로 만든다)."""
    return "tb" + hashlib.sha1(f"herdr-team\n{root}\n{space}".encode("utf-8")).hexdigest()[:32]


def _read_run(p) -> dict:
    run = read_json(p.run_file, {})
    return run if isinstance(run, dict) else {}


def _run_update(p, fn) -> dict:
    """run.json 을 잠금(state/run.lock) 안에서 읽고 fn 으로 바꿔 쓴다. fn 이 예외를 내면 쓰지 않는다."""
    p.ensure_state()
    with flock(p.state / "run.lock"):
        run = _read_run(p)
        fn(run)
        write_json(p.run_file, run)
        return run


def _bound(run: dict) -> bool:
    return bool(run.get("run_id")) and run.get("bound_nonce") == (run.get("pending_launch") or {}).get("nonce")


def up(p, wait_run: float | None, force: bool = False) -> dict:
    """설계 9.3: 코디네이터가 살아 있으면 그대로, 아니면 pending_launch 를 먼저 쓰고 팀 탭에 띄운다.

    새로 띄우는 것은 처음이거나 끝남·소실(exited·lost)이 확인됐을 때만이다. 확인할 수 없으면(unverifiable) 기록과
    nonce 를 그대로 두고 exit 3. 사용자가 끝났다고 확인하면 --force 로 띄우고, bind 가 run-use --force 로 넘겨받는다."""
    cfg = config.load(p)
    seen = _read_run(p).get("pending_launch") or {}
    view = coord.coordinator_view(p)
    if view["alive"] or view["starting"]:
        result = {"status": "alive" if view["alive"] and _bound(_read_run(p)) else "starting",
                  "terminal": view["terminal"], "launched": False}
    elif view["verdict"] == "unverifiable" and not force:
        raise HteamError("coordinator_unverifiable", f"코디네이터 터미널 {view['terminal']} 의 상태를 확인할 수 없다", CONFLICT,
                         "기록과 nonce 는 그대로 두었다. pane 을 보고 끝났다고 확신하면 hteam up --force",
                         data={"terminal": view["terminal"]})
    else:
        main = os.environ.get("HC_TERMINAL_ID", "").strip()
        if not main:
            raise HteamError("no_terminal", "Herdr 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
        space = (herdr.get(main).get("labels") or {}).get("herdr.space")
        if not space:
            raise HteamError("no_space", f"메인 터미널 {main} 에 herdr.space 라벨이 없다", FAIL)
        nonce, tab = secrets.token_hex(8), team_tab(p.root, space)
        before: dict = {}

        def pending(run: dict) -> None:
            if (run.get("pending_launch") or {}).get("nonce") != seen.get("nonce"):
                raise HteamError("launch_raced", "판정하는 사이에 다른 hteam up 이 코디네이터를 띄웠다", CONFLICT,
                                 "hteam status 로 코디네이터를 확인한다")
            before.update(run)
            # 인계 승인(force)은 bind 가 성공할 때까지 이어 받는다: 강제로 띄운 코디네이터가 bind 전에 끝나 다시 띄워도
            # 이전 소유자는 여전히 확인할 수 없으므로 bind 의 run-use 에 --force 가 필요하다
            forced = force or bool((run.get("pending_launch") or {}).get("force") and not _bound(run))
            run.update(pending_launch={"nonce": nonce, "at": now(), "force": forced}, team_space=space, team_tab=tab,
                       launched_at=now())
            run.pop("coordinator_terminal", None)
            run.pop("coordinator_argv", None)

        _run_update(p, pending)
        argv = ["env", "HTEAM_ROLE=coordinator", f"HTEAM_LAUNCH={nonce}", "claude"]
        for flag, value in (("--model", cfg.coordinator.get("model")), ("--effort", cfg.coordinator.get("effort"))):
            if value:
                argv += [flag, value]
        argv += [*cfg.args("claude"), "--", COORD_PROMPT]
        try:
            res = herdr.run_bg(f"hteam-coord-{secrets.token_hex(3)}", str(p.root),
                               {"herdr.space": space, "herdr.tab": tab, "hteam.role": "coordinator"}, argv)
            address = res.get("address")
            if not address or address == main:
                raise HteamError("same_terminal", f"코디네이터 터미널({address})이 메인 터미널과 같거나 없다", CONFLICT)
        except HteamError:
            # 띄우지 못했다: pending_launch 를 되돌린다(없는 코디네이터를 starting 으로 180초 기다리지 않게). 그사이 다른
            # up 이 덮어썼거나, hc 가 실패를 알렸지만 터미널은 떠서 이 nonce 로 bind 까지 했으면 건드리지 않는다
            def restore(run: dict) -> None:
                if (run.get("pending_launch") or {}).get("nonce") == nonce and run.get("bound_nonce") != nonce:
                    run.clear()
                    run.update(before)

            _run_update(p, restore)
            raise

        def record(run: dict) -> None:
            if (run.get("pending_launch") or {}).get("nonce") == nonce:
                run.update(coordinator_terminal=address, coordinator_argv=argv)

        _run_update(p, record)
        result = {"status": "launched", "terminal": address, "team_tab": tab, "launched": True,
                  "tab_renamed": herdr.rename_tab(tab, "팀", pause=env_float("HTEAM_POLL", 0.3))}
    if wait_run:
        deadline = time.monotonic() + wait_run
        while not _bound(_read_run(p)):
            if time.monotonic() >= deadline:
                raise HteamError("timeout", f"{wait_run:g}초 안에 코디네이터가 bind 하지 않았다", TIMEOUT,
                                 "코디네이터 pane 을 본다(폴더 신뢰 확인 창 등)", data=result)
            time.sleep(env_float("HTEAM_POLL", 0.5))
        result["run_id"] = _read_run(p).get("run_id")
    return result


def bind(p) -> dict:
    """설계 9.3: 코디네이터만(HTEAM_ROLE·HTEAM_LAUNCH nonce). 이전 run_id 가 있으면 run-use, 없으면 run-create."""
    roles.require_coordinator(p)
    term = os.environ.get("HC_TERMINAL_ID", "").strip()
    if not term:
        raise HteamError("no_terminal", "Herdr 터미널 안에서 실행해야 한다($HC_TERMINAL_ID 없음)", DENIED)
    h = Horch(p.horch_home)
    run = _read_run(p)
    nonce = os.environ["HTEAM_LAUNCH"]
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
            hint = err.get("hint") or ""
            if err.get("code") == "owner_unverifiable":
                hint = ("이전 코디네이터의 상태를 확인할 수 없다. 메인에 알린다. 사용자가 끝났다고 확인하면 이 코디네이터를 "
                        "끝내고 메인에서 hteam up --force")
            raise HteamError(f"horch_{err.get('code')}", f"run-use 실패: {err.get('message')}", code or FAIL,
                             hint, data={"horch": data})
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

    def record(r: dict) -> None:
        if (r.get("pending_launch") or {}).get("nonce") != nonce:
            raise HteamError("not_coordinator", "bind 하는 사이에 hteam up 이 새 코디네이터를 띄웠다(nonce 가 바뀌었다)",
                             DENIED, "이 코디네이터는 멈춘다")
        r.update(run_id=data["run"]["id"], coordinator_terminal=term, bound_nonce=nonce, bound_at=now())
        if argv is not None:
            r["coordinator_argv"] = argv

    _run_update(p, record)
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
