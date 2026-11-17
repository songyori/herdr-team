"""hc·herdr-app 직접 호출(설계 3.3). 관제 실행·생존 확인, 탭 이름 붙이기, 고정 에이전트 작업 터미널 상태와 pane 배치(5.9.2),
리뷰 보기 pane(6.5: hc run 의 hc attach(11단계), pane.close, 보기 터미널 hc rm), 11단계 보강의 다시 묶기(8.13·5.9.7: parent·메인
확인의 get, 다시 묶기로 끝난 관제 터미널의 pane.close·hc rm)뿐이다. 워커 실행은 늘 horch 를 거친다. 12단계: 대리 보고 기록 읽기
(relay_status. 기록 파일을 직접 읽지 않고 Horch 로 `horch relay-status` 를 부른다, 설계 8.14 의 1)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

from .errors import FAIL, MISSING, HteamError
from .horch import Horch


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
        data = {"kind": f"exit_{proc.returncode}"}
        for line in reversed((proc.stderr or proc.stdout or "").strip().split("\n")):
            try:
                err = json.loads(line).get("error")
            except (ValueError, AttributeError):
                continue
            if isinstance(err, dict):
                # message 는 parent 없는 주소(not_found `no terminal "<주소>"`)를 가리는 데 쓴다(설계 6.5·9.3 11단계)
                data = {"kind": str(err.get("kind") or data["kind"]), "message": str(err.get("message") or "")}
                break
        raise HteamError("hc_failed", f"hc {args[0]} 실패: {data['kind']}", FAIL, data=data)
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


def relay_status(p, terminal: str, *, strict: bool = False, timeout: float = 5) -> dict | None:
    """그 터미널의 대리 보고 기록(12단계, 설계 8.14 의 1·herdr-orch 설계 16.8): `horch relay-status --terminal <t>` 출력의
    record. 기록이 없으면 None. horch 를 찾지 못했거나 실패하면 strict 면 HteamError 를 올리고(판정할 수 없음을 가려야 하는
    up 의 main_unreported), 아니면 None 이다(고정 에이전트 판정은 실패를 "기록 없음" 과 같이 다룬다)."""
    try:
        data = Horch(p.horch_home).ok("relay-status", "--terminal", terminal, timeout=timeout)
    except HteamError:
        if strict:
            raise
        return None
    record = data.get("record")
    return record if isinstance(record, dict) else None


def rm(terminal: str, timeout: float = 10) -> None:
    """`hc rm <터미널> --json`(설계 6.5 의 3: 끝난 보기 터미널 지우기). 이미 없으면(not_found) 성공이다. 그 밖의 실패(아직
    live 포함)는 hc_failed(data kind)."""
    try:
        _hc(["rm", terminal], timeout=timeout)
    except HteamError as exc:
        if exc.data.get("kind") != "not_found":
            raise


def hc_path() -> str:
    """이 프로세스 PATH 에서 찾은 hc 의 절대 경로(설계 6.5 의 2: 보기 pane 의 PATH 에 기대지 않는다). 없으면 hc_missing."""
    found = shutil.which("hc")
    if not found:
        raise HteamError("hc_missing", "hc 실행 파일을 찾지 못했다", MISSING, "herdr-core 를 설치한다")
    return os.path.abspath(found)


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


def run_bg(labels: dict[str, str], argv: list[str], *, parent: str | None = None, name: str | None = None,
           cwd: str | None = None, keep: bool = False, timeout: float = 30) -> dict:
    """`hc run --bg --no-notify`(관제 9.3, 리뷰 보기 6.5). hc 의 결과 JSON 을 돌려준다.

    parent 가 있으면 `--parent <parent> --outlive-parent`(Herdr Agents 목록에서 메인 아래에 들고, 메인 Claude·셸이 끝나거나
    hc kill 돼도 산다), 없으면 `--no-parent`(설계 3.2 11단계). `--no-notify` 는 늘 준다(메인 입력란에 알림을 넣지 않는다).
    그 parent 를 hc 가 찾지 못해 실패하면(parent_missing: 터미널이 생기지 않았다) `--no-parent` 로 한 번 더 띄우고 결과에
    parent_fallback {parent, message} 를 더한다. 다른 실패는 그대로 올린다(다시 띄우지 않는다).
    keep 은 `--keep`(관제: Herdr 재시작 등으로 잃은 프로그램을 원래 명령으로 다시 실행하지 않고 셸로 바꾼다. 같은 nonce 의
    관제가 저절로 되살아나지 않게. 터미널은 남아 원인을 볼 수 있다). name·cwd 는 줄 때만 넣는다(보기 터미널은 주지 않는다)."""

    def args_for(par: str | None) -> list[str]:
        args = ["run", "--bg", *(["--parent", par, "--outlive-parent"] if par else ["--no-parent"]), "--no-notify"]
        args += ["--keep"] if keep else []
        args += ["--name", name] if name else []
        args += ["--cwd", cwd] if cwd else []
        for key, value in labels.items():
            args += ["--label", f"{key}={value}"]
        return args

    try:
        return _hc(args_for(parent), ["--", *argv], timeout)
    except HteamError as exc:
        if not (parent and parent_missing(exc, parent)):
            raise
        out = _hc(args_for(None), ["--", *argv], timeout)
        return {**out, "parent_fallback": {"parent": parent, "message": exc.data.get("message")}}


def parent_missing(exc: HteamError, parent: str) -> bool:
    """hc run 이 그 parent 를 찾지 못해 터미널을 만들지 않았다(not_found, hc 0.1.20 의 문구 `no terminal "<parent>"`).
    herdr-orch 설계 15.3 과 같은 규칙이다. 다른 not_found 문구는 아니다."""
    return (exc.code == "hc_failed" and exc.data.get("kind") == "not_found"
            and exc.data.get("message") == f'no terminal "{parent}"')


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


def _do(name: str, args: dict, timeout: float) -> dict:
    """`herdr-app do <name> '<JSON>'` 한 번. 결과 JSON 객체(읽지 못하면 {}). 실패는 herdr_app_failed(exit 1, 문구
    `herdr-app <name> 실패: <출력의 error 또는 exit_<코드>>`), herdr-app 이 없으면 herdr_app_missing(exit 12)."""
    try:
        proc = subprocess.run(["herdr-app", "do", name, json.dumps(args, ensure_ascii=False)], capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        raise HteamError("herdr_app_missing", "herdr-app 실행 파일을 찾지 못했다", MISSING, "Herdr 앱을 설치한다") from None
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        raise HteamError("herdr_app_failed", f"herdr-app {name} 를 실행하지 못했다", FAIL) from None
    data = _json(proc.stdout or "")
    if proc.returncode != 0:
        if not isinstance(data, dict):
            data = _json(proc.stderr or "")
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            err = err.get("kind") or err.get("code") or err.get("message")
        raise HteamError("herdr_app_failed", f"herdr-app {name} 실패: {err or f'exit_{proc.returncode}'}", FAIL)
    return data if isinstance(data, dict) else {}


def swap(pane: str, target: str, timeout: float = 10) -> None:
    """`herdr-app do pane.swap '{"pane", "target"}'`(설계 5.9.2 의 5). 실패는 _do 와 같다."""
    _do("pane.swap", {"pane": pane, "target": target}, timeout)


def close_pane(pane: str, timeout: float = 10) -> None:
    """`herdr-app do pane.close '{"pane"}'`(설계 6.5 의 3). 실패는 _do 와 같다."""
    _do("pane.close", {"pane": pane}, timeout)


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
