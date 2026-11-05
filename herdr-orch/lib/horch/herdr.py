"""herdr-app 호출. herdr-app 을 부르는 유일한 모듈."""
from __future__ import annotations

import json
import subprocess

_DETAIL_MAX = 200


def _detail(text: str, code: int) -> str:
    """herdr-app status 출력을 doctor 의 한 줄 설명으로 줄인다.

    출력은 여러 줄 JSON 일 수 있다(실환경 확인). 첫 줄만 쓰면 "{" 가 된다. JSON 객체면 최상위의
    단순 값과 목록 길이를 "키 값" 으로 잇고, 오류 객체면 그 message 를, 보일 것이 없으면 ok/exit 코드를 쓴다.
    JSON 이 아니면 첫 줄을 그대로 쓴다.
    """
    text = text.strip()
    try:
        data = json.loads(text)
    except ValueError:
        lines = text.splitlines()
        return lines[0] if lines else f"exit {code}"
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str) and err["message"]:
            return err["message"][:_DETAIL_MAX]
        parts = []
        for key, value in data.items():
            if isinstance(value, bool):
                parts.append(f"{key} {'true' if value else 'false'}")
            elif isinstance(value, (str, int, float)):
                parts.append(f"{key} {value}")
            elif isinstance(value, list):
                parts.append(f"{key} {len(value)}개")
        if parts:
            return ", ".join(parts)[:_DETAIL_MAX]
    return "ok" if code == 0 else f"exit {code}"


def app_status() -> tuple[bool, str]:
    try:
        proc = subprocess.run(["herdr-app", "status"], capture_output=True, text=True, timeout=10)
    except FileNotFoundError:
        return False, "herdr-app 이 PATH 에 없다"
    except subprocess.TimeoutExpired:
        return False, "herdr-app status 가 10초 안에 끝나지 않았다"
    except OSError as exc:  # 실행 권한 없음, 형식 오류 등
        return False, str(exc)
    return proc.returncode == 0, _detail(proc.stdout or proc.stderr or "", proc.returncode)
