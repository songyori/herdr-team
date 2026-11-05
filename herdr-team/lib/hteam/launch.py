"""시작 장벽 자식(설계 5.4).

자식은 먼저 stdin 에서 한 바이트를 기다린다. hteam 은 자식의 pid·시작 시각을 상태 파일에 쓴 다음에야 그 바이트를 보낸다.
바이트를 받으면 horch 로 exec 한다(pid 가 그대로 horch 프로세스가 된다). EOF 면(hteam 이 기록 전에 죽음) 실행하지 않고 끝난다.
그래서 상태 파일에 자식 pid 가 없으면 horch 는 실행되지 않은 것이다.
"""
from __future__ import annotations

import subprocess
import sys

from . import procs

NOT_RUN = 75  # 시작 바이트 없이 끝난 자식의 exit 코드
CHILD = (
    "import os, sys\n"
    "if not os.read(0, 1):\n"
    f"    sys.exit({NOT_RUN})\n"
    "fd = os.open(os.devnull, os.O_RDONLY)\n"
    "os.dup2(fd, 0)\n"
    "os.execv(sys.argv[1], sys.argv[1:])\n"
)


class Barrier:
    def __init__(self, argv: list[str]):
        self.proc = subprocess.Popen([sys.executable, "-c", CHILD, *argv], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.pid = self.proc.pid
        self.started = procs.start_time(self.pid) or ""

    def record(self) -> dict:
        return {"pid": self.pid, "started": self.started}

    def go(self, timeout: float = 600) -> tuple[int, str, str]:
        """시작 바이트를 보내고 horch 가 끝날 때까지 기다린다.

        바이트는 communicate(input=…) 로 보낸다. stdin 을 직접 닫은 뒤 communicate() 를 부르면
        Python 3.11 은 닫힌 stdin 을 flush 하다 ValueError 를 낸다(3.12 부터 무시)."""
        out, err = self.proc.communicate(input=b"x", timeout=timeout)
        return self.proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def abort(self) -> None:
        """기록에 실패했다. 바이트 없이 stdin 을 닫아 자식이 horch 를 실행하지 않고 끝나게 한다."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=30)
        for pipe in (self.proc.stdout, self.proc.stderr):
            if pipe:
                pipe.close()
