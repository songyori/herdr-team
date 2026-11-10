"""hc·herdr-app 직접 호출(설계 3.3). 관제 실행·생존 확인, 탭 이름 붙이기, 고정 에이전트 작업 터미널 상태와 pane 배치(5.9.2)뿐이다.
워커 실행은 늘 horch 를 거친다."""
from __future__ import annotations

import json
import subprocess
import time

from .errors import FAIL, MISSING, HteamError


def _hc(args: list[str], tail: list[str] | None = None, timeout: float = 30) -> dict:
    try:
        proc = subprocess.run(["hc", *args, "--json", *(tail or [])], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise HteamError("hc_missing", "hc 실행 파일을 찾지 못했다", MISSING, "herdr-core 를 설치한다") from None
    except OSError as exc:  # 실행 권한 없음 등. horch hcio 와 같이 실패(모름)로 다룬다
        raise HteamError("hc_failed", f"hc {args[0]} 를 실행하지 못했다: {exc}", FAIL,
                         data={"kind": "exec_failed"}) from None
    except subprocess.TimeoutExpired:
        raise HteamError("hc_timeout", f"hc {args[0]} 가 {timeout:g}초 안에 끝나지 않았다", FAIL) from None
    except UnicodeDecodeError:  # 출력이 UTF-8 이 아니다(ValueError). 읽을 수 없는 출력과 같이 다룬다
        raise HteamError("hc_failed", f"hc {args[0]} 출력이 UTF-8 이 아니다", FAIL, data={"kind": "bad_output"}) from None
    if proc.returncode != 0:
        kind = f"exit_{proc.returncode}"
        for line in reversed((proc.stderr or proc.stdout or "").strip().split("\n")):
            try:
                err = json.loads(line).get("error")
            except (ValueError, AttributeError):
                continue
            if isinstance(err, dict):
                kind = str(err.get("kind") or kind)
                break
        raise HteamError("hc_failed", f"hc {args[0]} 실패: {kind}", FAIL, data={"kind": kind})
    for line in reversed(proc.stdout.strip().split("\n")):  # LF 로만 나눈다(값의 U+2028 등은 경계가 아니다)
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise HteamError("hc_failed", f"hc {args[0]} 출력이 JSON 이 아니다", FAIL, data={"kind": "bad_output"})


def get(terminal: str, timeout: float = 10) -> dict:
    return _hc(["get", terminal], timeout=timeout)


def verdict(info: dict | None, expected_argv: list[str] | None) -> str:
    """horch liveness.verdict 와 같은 규칙(herdr-orch 설계 10장). 끝났다는 확실한 증거가 있을 때만 exited·lost.

    horch 에는 임의 터미널을 판정하는 명령이 없어 hteam 이 같은 규칙을 따로 둔다. 같은지는 테스트가 horch 코드와 비교한다."""
    if info is None:
        return "unverifiable"
    state = info.get("state")
    if state == "finished":
        return "exited"
    if state != "live":
        return "unverifiable"
    if info.get("reason") == "stopped_by_restart":
        return "lost"
    if expected_argv is not None:
        argv = info.get("argv")
        if argv is None:
            return "unverifiable"
        if argv != expected_argv:
            return "lost"
    return "live"


def probe(terminal: str | None, argv: list[str] | None, timeout: float = 10) -> str:
    """live·exited·lost·unverifiable. hc get 실패(not_found·시간 초과·hc 없음·출력 해석 실패 포함)는 horch 와 같이
    모름이다. timeout 은 hc get 의 시간 제한(초. 자동 부활은 3초, 설계 9.5)."""
    if not terminal:
        return "unverifiable"
    try:
        info = get(terminal, timeout=timeout)
    except HteamError:
        return "unverifiable"
    return verdict(info, argv)


def run_bg(name: str, cwd: str, labels: dict[str, str], argv: list[str]) -> dict:
    """코디네이터를 띄운다. --keep: Herdr 재시작 등으로 잃은 프로그램을 원래 명령으로 다시 실행하지 않고 셸로 바꾼다
    (같은 nonce 의 코디네이터가 저절로 되살아나지 않게. 터미널은 남아 원인을 볼 수 있다)."""
    args = ["run", "--bg", "--no-parent", "--no-notify", "--keep", "--name", name, "--cwd", cwd]
    for key, value in labels.items():
        args += ["--label", f"{key}={value}"]
    return _hc(args, ["--", *argv])


def _app(args: list[str], timeout: float) -> subprocess.CompletedProcess | None:
    """herdr-app 한 번. 실행하지 못했거나 시간을 넘기면 None."""
    try:
        return subprocess.run(["herdr-app", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None


def _json(text: str):
    """출력 전체를 JSON 으로, 안 되면 마지막 JSON 줄. 읽지 못하면 None."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed(text.strip().split("\n")):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


def pane_of(terminal: str, timeout: float = 10) -> str | None:
    """`herdr-app ls` 에서 그 터미널의 pane id(설계 5.9.2 의 5). 탭의 목록 키는 terminals 이고 항목은 {terminal, pane, status,
    app, name, sub_agents} 다(2026-11-10 확인). 실패·없음은 None."""
    proc = _app(["ls"], timeout)
    data = _json(proc.stdout) if proc is not None and proc.returncode == 0 else None
    if not isinstance(data, dict):
        return None
    for space in data.get("spaces") or []:
        for tab in (space or {}).get("tabs") or []:
            for item in (tab or {}).get("terminals") or []:
                if isinstance(item, dict) and item.get("terminal") == terminal:
                    return item.get("pane")
    return None


def swap(pane: str, target: str, timeout: float = 10) -> None:
    """`herdr-app do pane.swap '{"pane", "target"}'`(설계 5.9.2 의 5). 실패는 herdr_app_failed(exit 1)."""
    proc = _app(["do", "pane.swap", json.dumps({"pane": pane, "target": target})], timeout)
    if proc is None:
        raise HteamError("herdr_app_failed", "herdr-app pane.swap 를 실행하지 못했다", FAIL)
    if proc.returncode != 0:
        said = (proc.stdout or proc.stderr or "").strip()[:200]
        raise HteamError("herdr_app_failed", f"herdr-app pane.swap 실패(exit {proc.returncode}): {said}", FAIL)


def _blocks(node) -> list[str]:
    """doc.get 의 탭 root 를 깊이 우선으로 훑어 block 노드의 content.terminal 을 만난 차례로."""
    if not isinstance(node, dict):
        return []
    if node.get("type") == "block":
        term = (node.get("content") or {}).get("terminal")
        return [term] if term else []
    return [t for child in node.get("children") or [] for t in _blocks(child)]


def tab_row(tab: str, timeout: float = 5) -> list[str] | None:
    """core 문서 doc.get herdr-app(`hc connect` JSON-RPC 한 줄)에서 그 탭의 터미널 순서(설계 5.9.2 의 5: 배치 확인).
    읽지 못하면 None."""
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "doc.get", "params": {"name": "herdr-app"}})
    try:
        proc = subprocess.run(["hc", "connect"], input=req + "\n", capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.split("\n"):
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if not isinstance(msg, dict) or msg.get("id") != 1:
            continue
        value = (msg.get("result") or {}).get("value") if isinstance(msg.get("result"), dict) else None
        for space in (value or {}).get("spaces") or []:
            for item in (space or {}).get("tabs") or []:
                if isinstance(item, dict) and item.get("id") == tab:
                    return _blocks(item.get("root"))
        return None
    return None


def rename_tab(tab: str, name: str, tries: int = 10, pause: float = 0.3) -> bool:
    """탭이 화면에 생길 때까지 잠깐 다시 시도한다. 끝내 안 되면 False(번호 이름으로 둔다)."""
    for i in range(tries):
        try:
            proc = subprocess.run(["herdr-app", "do", "tab.rename", "--id", tab, "--name", name],
                                  capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if proc.returncode == 0:
            return True
        if i < tries - 1:
            time.sleep(pause)
    return False
