"""세팅과 관제 실행(설계 9.1–9.3): doctor, scaffold, up(관제를 띄운다), setup-done, upgrade."""
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
import tomllib
from pathlib import Path

from . import browser, config, drive, gitio, herdr, image, outbox, redmine, workspace
from .browser import BROWSER_SERVER
from .errors import CONFLICT, FAIL, TIMEOUT, USAGE, HteamError
from .horch import Horch
from .paths import PLUGIN_ROOT, TEMPLATES, Project, find_project
from .util import die_at, env_float, flock, now, write_atomic, write_json

MARK = "<!-- herdr-team -->"
# 템플릿 → 프로젝트 경로. 있는 파일은 덮어쓰지 않는다.
FILES = {
    "config.toml": ".herdr-team/config.toml",
    "design-rules.md": ".herdr-team/design-rules.md",
    "text-rules.md": ".herdr-team/text-rules.md",
    "roles/planner.md": ".herdr-team/roles/planner.md",
    "roles/director.md": ".herdr-team/roles/director.md",
    "roles/designer.md": ".herdr-team/roles/designer.md",
    "roles/developer.md": ".herdr-team/roles/developer.md",
    "roles/tester.md": ".herdr-team/roles/tester.md",
    "shim.py": ".herdr-team/bin/hteam",
}
# upgrade 가 템플릿으로 바꾸는 복사한 규칙 파일(설계 9.6): config.toml 은 사용자 설정이라 뺀다(출력에도 없다)
UPGRADE = {src: rel for src, rel in FILES.items() if src != "config.toml"}
SECTIONS = (("CLAUDE.md", "CLAUDE.section.md"), ("AGENTS.md", "AGENTS.section.md"))  # 덧붙인 절은 바꾸지 않고 알린다
UPGRADE_NEXT = ("바뀐 파일을 확인하고(git diff -- .herdr-team) 커밋한다. manual 의 절은 템플릿과 견줘 직접 고친다. 직무 문서는 "
                "워커 사양에 라운드마다 들어가므로 커밋하면 다음 라운드부터 적용된다. 테스트 관문을 쓰려면 "
                "docs/planning/tasks.toml 에 [test] 를 넣고 커밋한다(README \"묶음 검증\"). "
                "CLAUDE.md 절을 고쳤으면 메인 세션을 새로 연다(메인 규칙은 세션을 시작할 때 읽힌다).")
# up 이 띄울 때 바꾸는 run.json 키. 띄우기가 확실히 실패하면 이것만 되돌린다(main_terminals 등 다른 키는 그대로 둔다).
LAUNCH_KEYS = ("pending_launch", "team_space", "team_tab", "launched_at", "drive_terminal", "drive_argv")
# up 이 판정한 뒤 이 키가 바뀌었으면 판정이 낡았다(다른 up 이 띄웠거나 관제가 Run 에 묶였다): launch_raced.
RACE_KEYS = ("pending_launch", "run_id", "bound_nonce", "bound_at", "drive_terminal", "drive_argv")


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


def _codex_browser(root: Path) -> dict:
    """Codex 리뷰어가 chrome-devtools 로 화면을 렌더할 수 있나(경고만, 설계 6.2·9.2). 설정이 아직 없으면(init 의 scaffold 전)
    보지 않는다. 정의가 없거나, npx 가 없거나, 샌드박스·승인 우회가 없으면(도구 호출이 -a never 로 거부된다) 경고다."""
    p = Project(root)
    if not p.config.exists():
        return _check("codex_browser", True, "설정이 아직 없다(scaffold 뒤 doctor 가 다시 본다)", "warning")
    try:
        args = config.load(p).args("codex")
    except HteamError as exc:
        return _check("codex_browser", False, f"설정을 읽지 못했다: {exc.message}", "warning")
    if not browser.defines(args):
        return _check("codex_browser", False, f"[agents.codex].args 에 {BROWSER_SERVER}(chrome-devtools) 정의가 없다(리뷰어는 "
                      "화면을 코드로만 본다)", "warning")
    if not shutil.which("npx"):
        return _check("codex_browser", False, "npx 가 PATH 에 없어 chrome-devtools 서버를 띄우지 못한다(Node.js 설치)",
                      "warning")
    if not any(a.split("=", 1)[0] in config.CODEX_BYPASS for a in args):
        return _check("codex_browser", False, "Codex 리뷰어의 브라우저 도구는 승인 정책으로 거부된다(코드로만 본다). "
                      "[agents.codex].args 에 템플릿 기본인 `--dangerously-bypass-approvals-and-sandbox` 를 다시 넣는다",
                      "warning")
    return _check("codex_browser", True, f"{BROWSER_SERVER} 정의·npx·샌드박스 우회가 있다", "warning")


WORKSPACE_GIT_MIN = (2, 23, 0)  # git switch·git worktree(설계 9.2 7단계)
SLOTS_REL = ".herdr-team/state/slots"
CODEX_ENV_POLICY = ("Codex 의 shell_environment_policy(include_only) 가 [workspace.env] 값을 Codex 셸에서 뺄 수 있다. "
                    "사용자 설정을 확인한다")


def _codex_include_only() -> bool:
    """사용자 Codex 설정(`$CODEX_HOME/config.toml`, 없으면 ~/.codex/config.toml)의 shell_environment_policy.include_only 가
    비어 있지 않은가(읽기만 한다). 파일이 없거나 읽지 못하면 False(경고하지 않는다). 사전 검증 S2: include_only 는 horch 가
    `-c shell_environment_policy.set.<이름>` 으로 넘긴 값도 Codex 셸에서 뺀다."""
    codex_home = os.environ.get("CODEX_HOME")
    base = Path(codex_home) if codex_home else Path(os.environ.get("HOME") or Path.home()) / ".codex"
    try:
        data = tomllib.loads((base / "config.toml").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    policy = data.get("shell_environment_policy")
    return isinstance(policy, dict) and bool(policy.get("include_only"))


def _workspace_checks(root: Path, cfg) -> list[dict]:
    """worktree 모드의 점검(설계 9.2 7단계): git 2.23 이상·첫 커밋(오류), dirty 슬롯(경고). 설정을 읽지 못했거나(cfg None)
    shared 면 없다(0.4.0 과 같은 점검 목록). git 이 PATH 에 없으면 앞 `git` 점검이 이미 오류라 git 점검 둘을 넣지 않는다.
    [workspace.env] 가 있으면 사용자 Codex 셸 환경 정책(include_only)도 경고로 본다(사전 검증 S2)."""
    if cfg is None or not cfg.workspace.on:
        return []
    checks = []
    if shutil.which("git"):
        try:
            line, ver = gitio.version(root)
            ok = ver is not None and ver >= WORKSPACE_GIT_MIN
            checks.append(_check("workspace_git", ok, "git {}.{}.{}".format(*ver) if ok else
                                 f"worktree 모드에는 git 2.23 이상이 필요하다(git switch·git worktree): 지금 {line}"))
        except HteamError as exc:
            checks.append(_check("workspace_git", False, exc.message))
        try:
            if not gitio.is_repo(root):
                checks.append(_check("workspace_head", False,
                                     "git 저장소가 아니다. worktree 모드는 git 저장소와 첫 커밋이 필요하다"))
            elif not gitio.has_head(root):
                checks.append(_check("workspace_head", False, "커밋이 없다. worktree 모드는 첫 커밋에서 슬롯을 만든다: "
                                     "git commit --allow-empty -m init"))
            else:
                checks.append(_check("workspace_head", True, "첫 커밋이 있다"))
        except HteamError as exc:
            checks.append(_check("workspace_head", False, exc.message))
    try:
        data = workspace.load(Project(root))
        dirty = sorted(int(n) for n, rec in data["slots"].items() if rec.get("state") == "dirty")
        checks.append(_check("workspace_slots", not dirty, "dirty 슬롯이 없다" if not dirty else
                             "dirty 슬롯: " + ", ".join(f"{n}({SLOTS_REL}/slot-{n})" for n in dirty) +
                             ". 커밋 안 된 변경이 남았다. git -C <슬롯 폴더> status 로 보고, 사용자가 버려도 된다고 하면 "
                             "hteam slot reset <번호>", "warning"))
    except HteamError as exc:
        checks.append(_check("workspace_slots", False, exc.message, "warning"))
    if cfg.workspace.env and _codex_include_only():
        checks.append(_check("codex_env_policy", False, CODEX_ENV_POLICY, "warning"))
    return checks


def _horch_checks(root: Path) -> list[dict]:
    """horch 찾기와 horch doctor. horch 항목은 늘 하나다(찾은 뒤 doctor 가 실패해도 두 번 적지 않는다)."""
    home = root / ".herdr-team" / "state" / "horch"
    temp = None
    try:
        if not home.exists():
            temp = tempfile.mkdtemp(prefix="hteam-doctor-")
            home = Path(temp)
        h = Horch(home, project=root)  # 임시 홈이어도 이 프로젝트 범위의 설치를 고른다
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
    """설계 9.2. 필수 점검이 실패하면 exit 1(checks 포함). Codex 래퍼(scripts/codex-run.sh)는 플러그인 파일이라
    없거나 실행할 수 없으면 설치가 깨진 것이다(오류)."""
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
    wrapper = os.access(image.WRAPPER, os.X_OK)
    checks.append(_check("codex_wrapper", wrapper, str(image.WRAPPER) if wrapper else
                         f"{image.WRAPPER} 가 없거나 실행할 수 없다(hteam image 가 쓴다). herdr-team 을 다시 설치한다"))
    checks.append(_check("chrome_devtools_mcp", _chrome_mcp(root), "디렉터 레퍼런스 캡처에 쓴다(없으면 링크만 남긴다)",
                         "warning"))
    checks.append(_codex_browser(root))
    cfg = None  # 설정을 읽지 못하는 것은 doctor 의 점검이 아니다(설정 경고·작업 공간·Redmine 점검을 하지 않는다)
    try:
        cfg = config.load(Project(root))
    except HteamError:
        pass
    checks += _workspace_checks(root, cfg)  # 설계 9.2 7단계: worktree 모드만
    if cfg is not None and cfg.redmine is not None:  # 설계 9.2 7단계: 경고만
        checks += redmine.checks(Project(root), cfg)
    warnings: list[str] = config.crew_warnings(cfg) if cfg is not None else []  # 설정 경고(설계 4.2)
    if not all(c["ok"] for c in checks if c["level"] == "error"):
        raise HteamError("unhealthy", "필수 점검이 실패했다", FAIL, data={"checks": checks, "warnings": warnings})
    return {"healthy": True, "checks": checks, "warnings": warnings}


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


def _section_manual(root: Path) -> list[dict]:
    """CLAUDE.md·AGENTS.md 의 `<!-- herdr-team -->` 절이 지금 템플릿 절(줄 끝을 LF 로 맞춘 전문)을 그대로 담지 않으면 manual.
    절에 끝 표시가 없어 어디까지가 hteam 의 글인지 모르므로 바꾸지 않는다."""
    found = []
    for name, tpl in SECTIONS:
        try:
            text = (root / name).read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            text = None
        section = (TEMPLATES / tpl).read_text(encoding="utf-8").strip("\n")
        if text is None or MARK not in text:
            found.append({"path": name, "reason": "herdr-team 절이 없다. scaffold 를 다시 하면 덧붙인다"})
        elif section not in text:
            found.append({"path": name, "reason": f"덧붙인 herdr-team 절이 템플릿과 다르다. templates/{tpl} 과 견줘 직접 바꾼다"})
    return found


def upgrade(root: Path) -> dict:
    """복사한 규칙 파일을 템플릿으로 바꾼다(설계 9.6). 파일마다 git 상태를 먼저 본다: 커밋하지 않은 변경·삭제가 있으면 건너뛰고,
    없으면(삭제를 커밋했거나 처음부터 없다) 만들고, 추적하지 않으면 건너뛰고, 다르면 덮어쓴다. 커밋하지 않는다(git 이 백업이다).
    역할을 확인하지 않고 config.toml 을 읽지 않는다."""
    updated, created, skipped = [], [], []
    try:  # 숨김 플래그가 붙은 파일은 git status 가 작업 트리 변경을 보지 않는다(경로는 저장소 최상위 기준)
        hidden, prefix, hidden_error = gitio.index_read(root)[1], gitio.top_prefix(root), None
    except HteamError as exc:
        hidden, prefix, hidden_error = set(), "", exc
    for src, rel in UPGRADE.items():
        dst = root / rel
        want = (TEMPLATES / src).read_text(encoding="utf-8")
        parts = Path(rel).parts
        if any((root.joinpath(*parts[:i])).is_symlink() for i in range(1, len(parts) + 1)):
            skipped.append({"path": rel, "reason": "경로에 심볼릭 링크가 있다. 템플릿과 직접 비교해 바꾼다"})
            continue
        if hidden_error is not None:
            skipped.append({"path": rel, "reason": f"git 상태를 읽지 못했다: {hidden_error.message}"})
            continue
        if prefix + rel in hidden:
            skipped.append({"path": rel, "reason": "git 숨김 플래그(assume-unchanged·skip-worktree)가 있다. "
                            "플래그를 풀고(git update-index --no-assume-unchanged --no-skip-worktree) 다시 한다"})
            continue
        try:
            codes = gitio.status_codes(root, rel)
            if any(code != "??" for code in codes):
                skipped.append({"path": rel, "reason": "커밋 안 된 변경이 있다(지운 것 포함). 커밋하거나 되돌린 뒤 다시 한다"})
                continue
            if not dst.exists():
                write_atomic(dst, want)
                created.append(rel)
            elif not gitio.tracked(root, rel):
                skipped.append({"path": rel, "reason": "git 에 추적되지 않는다. 템플릿과 직접 비교해 바꾼다"})
                continue
            elif dst.read_bytes() != want.encode("utf-8"):
                write_atomic(dst, want)  # 같은 폴더 임시 파일 + os.replace
                updated.append(rel)
        except HteamError as exc:
            skipped.append({"path": rel, "reason": f"git 상태를 읽지 못했다: {exc.message}"})
            continue
        if rel.endswith("bin/hteam"):
            dst.chmod(0o755)
    try:
        stat = gitio.diff_stat(root, updated + created)  # 바꾸거나 만든 파일만(건너뛴 파일의 사용자 변경이 섞이지 않게)
    except HteamError:
        stat = ""
    return {"updated": updated, "created": created, "skipped": skipped, "manual": _section_manual(root),
            "diff_stat": stat, "next": UPGRADE_NEXT}


def _ignore_pattern(line: str) -> str:
    """git 이 읽는 .gitignore 패턴. 끝 공백은 백슬래시로 막지 않았으면 버린다. 앞 공백은 패턴의 일부다(지우지 않는다)."""
    while line.endswith(" ") and not line.endswith("\\ "):
        line = line[:-1]
    return line


def _setup_done_file(p) -> Path:
    """setup-done 이 남기는 표시. 있으면 scaffold 가 setup-mode 를 다시 켜지 않는다."""
    return p.state / "setup-done"


def team_tab(root: Path, space: str) -> str:
    """관제 탭 id 는 프로젝트·space 마다 고정이다(0.3.0 팀 탭과 같은 식. 없으면 Herdr 가 새 탭으로 만든다)."""
    return "tb" + hashlib.sha1(f"herdr-team\n{root}\n{space}".encode("utf-8")).hexdigest()[:32]


def _read_run(p) -> dict:
    """run.json. 없으면 {}. 있는데 읽지 못하거나 JSON 객체가 아니면 bad_run_file(exit 1, 덮어쓰지 않는다)."""
    return outbox._run(p)


def _run_update(p, fn) -> dict:
    """run.json 을 잠금(state/run.lock) 안에서 읽고 fn 으로 바꿔 쓴다. fn 이 예외를 내면 쓰지 않는다.

    run.lock 은 다른 hteam 잠금 안에서 잡지 않는다(잡는 곳: setup 의 up, drive 의 Run 연결. 둘 다 안에서
    다른 hteam 잠금을 잡지 않는다)."""
    p.ensure_state()
    with flock(p.run_lock):
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
    """wait 초 동안 이 nonce 의 관제가 Run 에 묶이기를 기다린다. 묶였으면 관제가 기록한 터미널, 아니면 None."""
    deadline = time.monotonic() + (wait or 0)
    while True:
        run = _read_run(p)
        if (run.get("pending_launch") or {}).get("nonce") == nonce and _bound(run):
            return run.get("drive_terminal")
        if time.monotonic() >= deadline:
            return None
        time.sleep(env_float("HTEAM_POLL", 0.5))


HUNG_MESSAGE = "관제 프로세스가 살아 있지만 응답이 없다. 관제 탭을 확인한다"
STARTING_MESSAGE = "관제가 아직 시작 중이다(180초 안에 다시 띄우지 않는다). hteam status 로 확인한다"


def up(p, wait_run: float | None) -> dict:
    """설계 9.3: 관제(hteam drive)가 살아 있으면 그대로, 아니면 pending_launch 를 먼저 쓰고 관제 탭에 띄운다.

    메인만 부른다(무엇이든 바꾸기 전에 outbox.require_main). 관제 생존은 drive.view(pid·heartbeat, 8.2)다. 멈췄으면(hung)
    다시 띄우지 않고 알린다(--wait-run 도 기다리지 않는다). 띄운 지 180초 안이고 아직 Run 에 묶이지 않았으면 starting.

    hc run 이 실패하면: 터미널이 생기지 않았다고 확인되면 이번에 바꾼 키만 되돌린다. 무엇을 했는지 모르면(시간 초과,
    응답 유실) 이름으로 찾아 있으면 기록하고, 없거나 찾지 못하면 nonce 와 pending_launch 를 남기고 exit 1
    launch_uncertain(떴다면 관제가 스스로 Run 에 묶인다. 아니면 180초 뒤 다음 up 이 새로 띄운다)."""
    config.load(p)
    main = outbox.require_main(p)
    seen = _read_run(p)
    view = drive.view(p, seen)
    if view["hung"]:
        return {"status": "hung", "terminal": view["terminal"], "launched": False, "message": HUNG_MESSAGE}
    if view["alive"]:
        result = {"status": "running", "terminal": view["terminal"], "launched": False}
    elif view["starting"]:
        result = {"status": "starting", "terminal": view["terminal"], "launched": False, "message": STARTING_MESSAGE}
    else:
        space = (herdr.get(main).get("labels") or {}).get("herdr.space")
        if not space:
            raise HteamError("no_space", f"메인 터미널 {main} 에 herdr.space 라벨이 없다", FAIL)
        nonce, tab, name = secrets.token_hex(8), team_tab(p.root, space), f"hteam-drive-{secrets.token_hex(3)}"
        before: dict = {}

        def pending(run: dict) -> None:
            if any(run.get(k) != seen.get(k) for k in RACE_KEYS):
                raise HteamError("launch_raced", "판정하는 사이에 다른 hteam up 이 띄웠거나 관제가 Run 에 묶였다", CONFLICT,
                                 "hteam status 로 관제를 확인한다(띄우는 중이면 hteam up --wait-run 180)")
            before.update({k: run[k] for k in LAUNCH_KEYS if k in run})
            run.update(pending_launch={"nonce": nonce, "at": now()}, team_space=space, team_tab=tab, launched_at=now())
            run.pop("drive_terminal", None)
            run.pop("drive_argv", None)

        def restore(run: dict) -> None:
            # 이번 up 이 바꾼 키만 되돌린다. 그사이 다른 up 이 덮어썼거나 이 nonce 로 관제가 묶였으면 건드리지 않는다
            if (run.get("pending_launch") or {}).get("nonce") == nonce and run.get("bound_nonce") != nonce:
                for key in LAUNCH_KEYS:
                    if key in before:
                        run[key] = before[key]
                    else:
                        run.pop(key, None)

        die_at("up_before_pending")
        _run_update(p, pending)
        argv = ["env", "HTEAM_ROLE=drive", f"HTEAM_LAUNCH={nonce}", sys.executable, str(PLUGIN_ROOT / "bin" / "hteam"),
                "--root", str(p.root), "drive"]
        die_at("up_before_hc_run")
        recovered = bound_seen = False
        try:
            address = herdr.run_bg(name, str(p.root),
                                   {"herdr.space": space, "herdr.tab": tab, "hteam.role": "drive"}, argv).get("address")
            if not address:
                raise HteamError("hc_failed", "hc run 출력에 터미널 주소가 없다", FAIL, data={"kind": "bad_output"})
        except HteamError as exc:
            address, known = (None, True) if _never_started(exc) else _find_launched(name, argv)
            if address is None:
                if _never_started(exc) or (known and not _uncertain(exc)):
                    _run_update(p, restore)  # hc 가 거부했고 터미널도 없다: 확실한 실패
                    raise
                # 떴다면 곧 이 nonce 로 Run 에 묶인다: --wait-run 동안 기다린다. 관제가 터미널·argv 를 기록한다
                address = _wait_bound(p, nonce, wait_run)
                if address is None:
                    raise HteamError("launch_uncertain", f"관제를 띄웠는지 확인하지 못했다(hc run: {exc.message})",
                                     FAIL, f"pending_launch 와 nonce 는 남겼다. 떴다면 관제 탭의 {name} pane 이 스스로 "
                                     f"Run 에 묶인다. hteam status 의 drive 를 보고, 띄운 지 180초가 지나도 묶이지 "
                                     f"않으면 hteam up(새로 띄운다)", data={"name": name, "terminal": None}) from None
                bound_seen = True
            recovered = True
        if address == main:
            _run_update(p, restore)
            raise HteamError("same_terminal", f"관제 터미널({address})이 메인 터미널과 같다", CONFLICT)

        def record(run: dict) -> None:
            if (run.get("pending_launch") or {}).get("nonce") == nonce:
                run.update(drive_terminal=address, drive_argv=argv)

        if not bound_seen:
            _run_update(p, record)
        # 탭 이름은 관제가 시작하며 붙인다(설계 8.2 의 5)
        result = {"status": "launched", "terminal": address, "team_tab": tab, "launched": True}
        if recovered:
            result["recovered"] = True  # hc 가 실패를 알렸지만 이름으로 찾았거나 그 nonce 로 관제가 묶였다
    if wait_run:
        deadline = time.monotonic() + wait_run
        while not _bound(_read_run(p)):
            if time.monotonic() >= deadline:
                raise HteamError("timeout", f"관제가 {wait_run:g}초 안에 Run 을 만들지 않았다. 관제 탭(herdr-team 관제)을 "
                                 "확인한다", TIMEOUT, "관제 탭의 출력과 .herdr-team/state/drive/drive.log 를 본다",
                                 data=result)
            time.sleep(env_float("HTEAM_POLL", 0.5))
        result["run_id"] = _read_run(p).get("run_id")
    return result


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
    return up(find_project(args.root), args.wait_run)


def _cmd_upgrade(args) -> dict:
    return upgrade(find_project(args.root).root)


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
    s.set_defaults(func=_cmd_up)
    sub.add_parser("setup-done").set_defaults(func=_cmd_setup_done)
    sub.add_parser("upgrade").set_defaults(func=_cmd_upgrade)
