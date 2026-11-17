"""horch 호출. horch 를 부르는 유일한 모듈(설계 3.1). 늘 `--home <프로젝트>/.herdr-team/state/horch` 로 부른다."""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

from .errors import FAIL, MISSING, HteamError
from .paths import PLUGIN_ROOT


def _registry() -> Path:
    return Path(os.environ.get("HTEAM_PLUGINS_JSON")
                or Path.home() / ".claude" / "plugins" / "installed_plugins.json")


# hteam 이 받는 가장 낮은 herdr-orch 버전(12단계: Claude 상태 대리 보고·relay-status·launch-guard 의 HORCH_HOME, 0.5.0).
# 설치 기록에서 고를 때 거르고, HERDR_ORCH_BIN·형제 경로로 고른 horch 도 본다(설계 3.3 12단계)
HORCH_MIN = "0.5.0"
SCOPE_RANK = {"local": 0, "project": 1, "user": 2}  # Claude Code 처럼 좁은 범위가 앞선다


# ASCII 숫자 1–6자리 조각 셋만(str.isdigit 는 "²"·전각 숫자도 참이라 int() 가 실패하고, 아주 긴 숫자는 int 변환 상한
# 4300자리를 넘어 실패한다)
VERSION_RE = re.compile(r"[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}")


def version_tuple(text) -> tuple[int, ...] | None:
    """`X.Y.Z`(ASCII 숫자, 조각마다 1–6자리) → (X, Y, Z). 읽지 못하면 None(변환이 실패해도 None)."""
    text = str(text or "").strip()
    if not VERSION_RE.fullmatch(text):
        return None
    try:
        return tuple(int(x) for x in text.split("."))
    except ValueError:
        return None


def _entry_version(entry: dict, install: Path) -> tuple[int, ...] | None:
    """설치 기록의 version, 없으면 설치 폴더의 .claude-plugin/plugin.json version."""
    found = version_tuple(entry.get("version"))
    if found is None:
        try:
            found = version_tuple(json.loads((install / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
                                  .get("version"))
        except (OSError, ValueError, AttributeError):
            return None
    return found


def _covers(entry: dict, project: Path | None) -> bool:
    """project·local 범위 기록은 projectPath 가 이 프로젝트(또는 그 위 폴더)일 때만 쓴다. user 범위는 늘 쓴다. 경로를
    해석하지 못하면(없는 사용자의 `~이름`, 권한 등) 예외가 그대로 나간다(_from_registry 가 그 항목만 뺀다)."""
    if entry.get("scope", "user") == "user":
        return True
    raw = entry.get("projectPath")
    if project is None or not isinstance(raw, str) or not raw:
        return False
    return project.resolve().is_relative_to(Path(raw).expanduser().resolve())


def _corrupt(entry) -> str | None:
    """설치 기록 항목의 자료형이 틀렸으면 그 필드 이름. 맞으면 None(값이 맞는지는 고르면서 본다)."""
    if not isinstance(entry, dict):
        return "항목"
    if not isinstance(entry.get("installPath"), str) or not entry["installPath"]:
        return "installPath"
    scope = entry.get("scope", "user")
    if not isinstance(scope, str) or scope not in SCOPE_RANK:
        return "scope"
    if scope != "user" and not isinstance(entry.get("projectPath"), str):
        return "projectPath"
    if "version" in entry and not isinstance(entry["version"], str):
        return "version"
    return None


def _from_registry(project: Path | None) -> tuple[Path | None, list[str]]:
    """installed_plugins.json 의 herdr-orch 설치 가운데 이 프로젝트에 맞고(범위·projectPath) HORCH_MIN 이상인 것.
    좁은 범위(local → project → user)가 앞서고, 같은 범위면 herdr-team 마켓플레이스, 그다음 높은 버전이다. (경로, 뺀 까닭).
    자료형이 틀린 항목(손상된 기록)과 경로를 해석하지 못한 항목(RuntimeError·OSError·ValueError)은 그 항목만 까닭과 함께
    빼고 나머지를 계속 본다."""
    try:
        data = json.loads(_registry().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, []
    plugins = data.get("plugins", data) if isinstance(data, dict) else {}
    found, skipped, low = [], [], version_tuple(HORCH_MIN)
    for key, entries in (plugins.items() if isinstance(plugins, dict) else []):
        name, _, market = key.partition("@")
        if name != "herdr-orch" or not isinstance(entries, list):
            continue
        for entry in entries:
            bad = _corrupt(entry)
            if bad:
                skipped.append(f"{key} 손상된 설치 기록({bad})")
                continue
            scope = entry.get("scope", "user")
            try:
                install = Path(entry["installPath"]).expanduser()
                binary = install / "bin" / "horch"
                if not binary.is_file() or not _covers(entry, project):
                    continue
                binary = binary.resolve()
            except (RuntimeError, OSError, ValueError) as exc:
                skipped.append(f"{key} {scope} 경로를 해석하지 못했다({type(exc).__name__})")
                continue
            version = _entry_version(entry, install)
            if version is None or version < low:
                skipped.append(f"{key} {scope} " + (f"{'.'.join(map(str, version))}({HORCH_MIN} 보다 낮다)" if version
                                                     else "버전 모름"))
                continue
            found.append(((SCOPE_RANK[scope], market != "herdr-team", tuple(-x for x in version)), binary))
    if not found:
        return None, skipped
    return min(found, key=lambda x: x[0])[1], skipped


VERSION_PROBE_S = 10.0  # plugin.json 이 없는 horch 의 `horch version` 조회 상한(호출의 timeout 이 더 짧으면 그만큼)
# 버전을 확인한 horch(경로 → 버전. 설치 기록에서 고른 것은 HORCH_MIN 이상만 안다). 확인하지 못한 것은 두지 않는다(다음
# 호출이 다시 본다, 계획 리뷰 plan2-r1 의 8). 이 프로세스 동안 둔다
_VERSIONS: dict[str, tuple[int, ...]] = {}


def _plugin_version(binary: Path) -> tuple[int, ...] | None:
    """horch 가 든 플러그인 폴더(`<플러그인>/bin/horch` 의 `<플러그인>/.claude-plugin/plugin.json`)의 version."""
    try:
        return version_tuple(json.loads((binary.parent.parent / ".claude-plugin" / "plugin.json")
                                        .read_text(encoding="utf-8")).get("version"))
    except (OSError, ValueError, AttributeError):
        return None


def _too_old(binary: Path, version: tuple[int, ...]) -> HteamError:
    return HteamError("horch_missing", f"고른 herdr-orch(horch)가 {'.'.join(map(str, version))}({HORCH_MIN} 보다 낮다)"
                      f"이다: {binary}", MISSING, f"herdr-orch 를 {HORCH_MIN} 이상으로 올리거나(/plugin update "
                      "herdr-orch@herdr-team) HERDR_ORCH_BIN 을 고친다")


def _checked(binary: Path) -> Path:
    """HERDR_ORCH_BIN·형제 경로로 고른 horch 의 버전(12단계, 설계 3.3). 같은 플러그인의 plugin.json 으로 알면 여기서
    HORCH_MIN 아래를 exit 12 로 멈추고 기억한다. 모르면 첫 호출(Horch.call)이 `horch version` 으로 본다(_probe)."""
    version = _plugin_version(binary)
    if version is not None:
        if version < version_tuple(HORCH_MIN):
            raise _too_old(binary, version)
        _VERSIONS[str(binary)] = version
    return binary


def _probe(binary: Path, timeout: float) -> tuple[int, ...] | None:
    """binary 의 버전. 이미 알면 그것이고, 모르면 timeout 초 안에서 `horch version` 을 한 번 부른다. 답하면 기억하고 돌려준다.
    시간 초과·실행 오류·잘못된 출력이면 None 이고 기억하지 않는다(다음 호출이 다시 본다)."""
    key = str(binary)
    if key in _VERSIONS:
        return _VERSIONS[key]
    if timeout <= 0:
        return None
    try:
        proc = subprocess.run([sys.executable, key, "version"], capture_output=True, text=True, timeout=timeout)
        version = version_tuple(parse(proc.stdout, proc.stderr).get("version"))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if version is not None:
        _VERSIONS[key] = version
    return version


def version_confirmed(home: Path, timeout: float = VERSION_PROBE_S) -> bool:
    """홈 home 으로 부를 horch 의 버전이 HORCH_MIN 이상으로 확인됐는가(12단계, 설계 3.3. 고정 에이전트 새 세션 entry 의
    relay_ready 를 적을지 crew 가 본다). 이미 알면 다시 부르지 않고, 모르면 timeout 안에서 한 번 더 본다. horch 를 찾지
    못했거나 낮거나 확인하지 못하면 False 다. 예외를 내지 않는다."""
    try:
        binary = Horch(home).bin
    except HteamError:
        return False
    version = _probe(binary, timeout)
    return version is not None and version >= version_tuple(HORCH_MIN)


def find_horch(project: Path | None = None) -> Path:
    """HERDR_ORCH_BIN → 형제 ../herdr-orch/bin/horch → installed_plugins.json 의 herdr-orch(이 프로젝트에 맞는 범위와
    HORCH_MIN 이상, _from_registry). project 는 프로젝트 루트(project·local 범위 설치를 고를 때 본다). 없으면 exit 12.
    12단계: HERDR_ORCH_BIN·형제 경로로 고른 horch 도 HORCH_MIN 아래면 exit 12 다(_checked, 첫 호출의 _probe)."""
    env = os.environ.get("HERDR_ORCH_BIN")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return _checked(path.resolve())
        raise HteamError("horch_missing", f"HERDR_ORCH_BIN 이 가리키는 파일이 없다: {path}", MISSING)
    sibling = PLUGIN_ROOT.parent / "herdr-orch" / "bin" / "horch"
    if sibling.is_file():
        return _checked(sibling.resolve())
    path, skipped = _from_registry(project)
    if path is not None:
        _VERSIONS.setdefault(str(path), version_tuple(HORCH_MIN))  # 설치 기록에서 HORCH_MIN 이상만 골랐다
        return path
    why = f". 쓰지 않은 설치: {', '.join(skipped)}" if skipped else ""
    raise HteamError("horch_missing", f"herdr-orch(horch)를 찾지 못했다{why}", MISSING,
                     f"/plugin install herdr-orch@herdr-team(또는 update, {HORCH_MIN} 이상)으로 설치하거나 "
                     "HERDR_ORCH_BIN 을 준다")


def _project_of(home: Path) -> Path | None:
    """hteam 의 horch 홈(`<프로젝트>/.herdr-team/state/horch`)에서 프로젝트 루트. 그 모양이 아니면 None."""
    home = Path(home)
    if home.name == "horch" and home.parent.name == "state" and home.parent.parent.name == ".herdr-team":
        return home.parent.parent.parent
    return None


def parse(stdout: str, stderr: str = "") -> dict:
    """stdout 의 마지막 JSON 객체 줄. 없으면 bad_output 오류 모양. 줄은 LF 로만 나눈다(본문의 U+2028 등은 경계가 아니다)."""
    for line in reversed((stdout or "").strip().split("\n")):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    tail = ((stdout or "") + (stderr or "")).strip()[-500:]
    return {"ok": False, "error": {"code": "bad_output", "message": f"horch 출력이 JSON 이 아니다: {tail}", "hint": ""}}


def failure(code: int, data: dict, args: tuple) -> HteamError:
    err = data.get("error") or {}
    return HteamError("horch_failed", f"horch {args[0] if args else ''} 실패: {err.get('code')}: {err.get('message')}",
                      MISSING if code == MISSING else FAIL, err.get("hint") or "", data={"horch": data})


def agent_args(args: list[str]) -> list[str]:
    """`-` 로 시작하는 인자도 값으로 넘어가게 `--agent-arg=<인자>` 로 붙인다."""
    return [f"--agent-arg={a}" for a in args]


class Horch:
    def __init__(self, home: Path, project: Path | None = None):
        """project 는 프로젝트 루트다. 주지 않으면 home(`<프로젝트>/.herdr-team/state/horch`)에서 찾는다."""
        self.bin = find_horch(project if project is not None else _project_of(home))
        self.home = Path(home)

    def argv(self, *args: str) -> list[str]:
        return [sys.executable, str(self.bin), "--home", str(self.home), *args]

    def cmd(self) -> str:
        """사람과 에이전트에게 보여 줄 horch 명령(절대 경로와 --home 포함)."""
        return " ".join(shlex.quote(a) for a in self.argv())

    def call(self, *args: str, timeout: float = 120) -> tuple[int, dict]:
        start = time.monotonic()
        # 12단계(설계 3.3): 버전을 아직 모르는 horch 는 같은 시간 예산 안에서 먼저 본다(계획 리뷰 plan2-r1 의 6).
        # 확인하지 못하면 이 호출은 그대로 하고 다음 호출이 다시 본다
        version = _probe(self.bin, min(VERSION_PROBE_S, timeout))
        if version is not None and version < version_tuple(HORCH_MIN):
            return MISSING, _too_old(self.bin, version).to_json()
        left = timeout - (time.monotonic() - start)
        try:
            if left <= 0:
                raise subprocess.TimeoutExpired(self.argv(*args), timeout)
            proc = subprocess.run(self.argv(*args), capture_output=True, text=True, timeout=left)
        except subprocess.TimeoutExpired:
            return FAIL, {"ok": False, "error": {"code": "horch_timeout",
                                                 "message": f"horch {args[0]} 가 {timeout:g}초 안에 끝나지 않았다",
                                                 "hint": ""}}
        return proc.returncode, parse(proc.stdout, proc.stderr)

    def ok(self, *args: str, timeout: float = 120) -> dict:
        code, data = self.call(*args, timeout=timeout)
        if code != 0 or not data.get("ok"):
            raise failure(code, data, args)
        return data

    def workers(self, states=None) -> list[dict]:
        """worker-list 행. 관제(Run 소유자) 환경에서만 된다. states 를 주면 그 상태만(--state 반복)."""
        flags = [x for s in states or () for x in ("--state", s)]
        return list(self.ok("worker-list", *flags).get("workers") or [])
