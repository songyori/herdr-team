"""hteam 오류와 exit 코드. 코드는 horch 와 같다(설계 8.3)."""
from __future__ import annotations

OK = 0
FAIL = 1
USAGE = 2
CONFLICT = 3
TIMEOUT = 4
DENIED = 5
MISSING = 12


class HteamError(Exception):
    """명령을 실패로 끝낸다. cli 가 JSON 오류로 바꿔 출력한다. data 는 오류 JSON 최상위에 합친다."""

    def __init__(self, code: str, message: str, exit_code: int = FAIL, hint: str = "",
                 data: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.hint = hint
        self.data = data or {}

    def to_json(self) -> dict:
        out = {"ok": False, "error": {"code": self.code, "message": self.message, "hint": self.hint}}
        out.update(self.data)
        return out
