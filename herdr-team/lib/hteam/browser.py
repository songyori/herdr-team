"""Codex 의 브라우저 MCP 서버(설계 4.1·6.2·12장·14장).

리뷰어의 서버는 herdr-team 전용 이름 `hteam-browser` 다(기본 `[agents.codex].args` 의 서버 테이블 한 쌍). 사용자 Codex(설정·
플러그인)에 같은 일을 하는 `chrome-devtools` 서버가 켜져 있으면, hteam 이 띄우는 codex(디스패치의 워커·리뷰어, 이미지)에서만
그 정의를 통째로 꺼서 준다: transport 키 하나와 `enabled=false`. 일부 키만(`.enabled=false`) 주면 플러그인 정의에서
`invalid transport`, url 정의에 command 를 주면 `url is not supported for stdio` 로 codex 가 시작하지 못한다(codex-cli 0.166).
사용자 설정 파일은 고치지 않는다. 다른 이름의 사용자 서버는 범위 밖이다.

이 모듈은 codex 를 읽기 전용 `codex mcp get chrome-devtools --json` 으로만 부른다. 프로세스 안에서 프로젝트마다 한 번만
조회하고(캐시), QUERY_TIMEOUT 초를 넘기면 끄지 않는다. 조회 실패·시간 초과·codex 없음은 끄지 않고 경고 한 줄을 낸다
(부른 쪽이 warnings 에 남기고 하던 일을 계속한다)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

BROWSER_SERVER = "hteam-browser"  # Codex 리뷰어의 chrome-devtools MCP 서버 이름(사용자·플러그인의 chrome-devtools 와 나눈다)
BROWSER_KEY = f"mcp_servers.{BROWSER_SERVER}"
USER_BROWSER = "chrome-devtools"  # 사용자·플러그인이 흔히 쓰는 같은 일의 서버 이름. hteam 이 띄우는 codex 에서만 끈다
QUERY_TIMEOUT = 15  # `codex mcp get` 상한(초)
_cache: dict[str, tuple[list[str], str | None]] = {}


def config_items(args: list[str]) -> list[tuple[int, int, str]]:
    """Codex 인자의 `-c`·`--config` 값마다 (시작 인덱스, 끝 인덱스(뒤), 값). 분리형 `-c X`·`--config X` 와 붙인 형
    `-cX`·`-c=X`·`--config=X` 를 모두 읽는다(codex 가 모두 받는다). 값이 없는 끝의 `-c` 는 세지 않는다. doctor·디스패치
    (defines)와 이미지 인자 정리(image.codex_args)가 이 파서 하나를 쓴다."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in ("-c", "--config"):
            if i + 1 < len(args):
                out.append((i, i + 2, args[i + 1]))
                i += 2
                continue
        elif a.startswith("--config="):
            out.append((i, i + 1, a[len("--config="):]))
        elif a.startswith("-c") and not a.startswith("--") and len(a) > 2:
            out.append((i, i + 1, a[2:].removeprefix("=")))
        i += 1
    return out


def key_of(value: str) -> str:
    """`-c` 값 `key = value` 의 키. codex 는 `=` 앞의 앞뒤 공백만 같은 키로 읽는다(안쪽 공백은 다른 키)."""
    return value.split("=", 1)[0].strip()


def defines(args: list[str]) -> bool:
    """args 의 `-c`·`--config` 값에 hteam-browser 정의(`mcp_servers.hteam-browser=…` 또는 `mcp_servers.hteam-browser.…`)가
    있나(config_items)."""
    for _, _, v in config_items(args):
        key = key_of(v)
        if key == BROWSER_KEY or key.startswith(BROWSER_KEY + "."):
            return True
    return False


def has_profile(args: list[str]) -> bool:
    """args 가 codex 프로필을 고르나(`-p X`·`-pX`·`--profile X`·`--profile=X`). `codex mcp get` 은 `-c` 만 받고 프로필을
    받지 않아(codex-cli 0.166 `mcp get --help`) 조회가 실행과 다른 설정을 읽는다."""
    return any(a in ("-p", "--profile") or a.startswith("--profile=")
               or (a.startswith("-p") and not a.startswith("--") and len(a) > 2) for a in args)


def user_off(root: Path, args: list[str] | None = None) -> tuple[list[str], str | None]:
    """(끄는 `-c` 한 쌍 또는 빈 목록, 경고 또는 None). 프로세스 안에서 (root, 실행 인자의 `-c` 값) 마다 한 번만 조회한다.
    조회에도 실행의 `-c`·`--config` 를 넘겨 같은 설정을 읽게 한다. 프로필(`-p`)은 `mcp get` 이 받지 않으므로 args 에
    프로필이 있으면 조회를 믿지 않고 끄지 않는다(같은 이름 서버가 없는 프로필에 `enabled=false` 만 주면 codex 가
    `invalid transport` 로 시작하지 못한다)."""
    args = args or []
    if has_profile(args):
        return _skip("프로필이 있어 조회가 실행과 다른 설정을 읽는다")
    cfg = [x for _, _, v in config_items(args) for x in ("-c", v)]
    key = json.dumps([str(root), cfg])
    if key not in _cache:
        _cache[key] = _query(root, cfg)
    off, warning = _cache[key]
    return list(off), warning


def _skip(why: str) -> tuple[list[str], str]:
    return [], f"사용자 Codex 의 {USER_BROWSER} 서버를 확인하지 못해 끄지 않았다({why})"


def _query(root: Path, cfg: list[str]) -> tuple[list[str], str | None]:
    if not shutil.which("codex"):
        return _skip("codex 가 PATH 에 없다")
    try:
        proc = subprocess.run(["codex", "mcp", "get", USER_BROWSER, "--json", *cfg], capture_output=True, text=True,
                              timeout=QUERY_TIMEOUT, stdin=subprocess.DEVNULL, cwd=root)
    except subprocess.TimeoutExpired:
        return _skip(f"`codex mcp get` 이 {QUERY_TIMEOUT}초 안에 끝나지 않았다")
    except OSError as exc:
        return _skip(f"`codex mcp get` 을 부르지 못했다: {exc}")
    if proc.returncode != 0:
        if "No MCP server named" in proc.stderr + proc.stdout:
            return [], None  # 정의가 없다. 끌 것이 없다
        tail = (proc.stderr.strip() or proc.stdout.strip())[-200:]
        return _skip(f"`codex mcp get` exit {proc.returncode}: {tail}")
    try:
        info = json.loads(proc.stdout)
    except ValueError:
        return _skip("`codex mcp get` 출력이 JSON 이 아니다")
    if not isinstance(info, dict) or not isinstance(info.get("transport"), dict):
        return _skip("`codex mcp get` 출력의 모양이 다르다")
    if info.get("enabled") is not True:
        return [], None  # 이미 꺼져 있다
    kind = info["transport"].get("type")
    field = {"stdio": "command", "streamable_http": "url"}.get(kind)
    value = info["transport"].get(field) if field else None
    if not isinstance(value, str) or not value:
        return _skip(f"모르는 transport({kind})")
    return ["-c", f"mcp_servers.{USER_BROWSER}={{{field}={json.dumps(value, ensure_ascii=False)},enabled=false}}"], None
