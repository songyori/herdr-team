"""시작 장벽 자식(설계 5.4).

자식은 먼저 stdin 에서 한 바이트를 기다린다. hteam 은 자식의 pid·시작 시각을 상태 파일에 쓴 다음에야 그 바이트를 보낸다.
바이트를 받으면 horch 로 exec 한다(pid 가 그대로 horch 프로세스가 된다). EOF 면(hteam 이 기록 전에 죽음) 실행하지 않고 끝난다.
그래서 상태 파일에 자식 pid 가 없으면 horch 는 실행되지 않은 것이다.
"""
from __future__ import annotations

import os
import signal
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
        # 자식은 자기 프로세스 그룹을 갖는다. 시간이 넘으면 horch 와 그 hc 호출을 함께 죽인다(kill)
        self.proc = subprocess.Popen([sys.executable, "-c", CHILD, *argv], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        self.pid = self.proc.pid
        self.started = procs.start_time(self.pid) or ""
        self.sent = False  # 시작 바이트를 보내려 했다(그 뒤로는 horch 가 떴는지 모른다)

    def record(self) -> dict:
        return {"pid": self.pid, "started": self.started}

    def send(self) -> None:
        """시작 바이트를 쓰고 stdin 을 닫는다. hteam 은 launched 기록을 저장한 직후 태스크 잠금을 쥔 채 부른다.

        닫은 stdin 은 떼어(None) 둔다. 닫힌 stdin 이 붙은 채 communicate() 를 부르면 Python 3.11 은 그것을
        flush 하다 ValueError 를 낸다(3.12 부터 무시)."""
        if self.sent:
            return
        self.sent = True
        stdin, self.proc.stdin = self.proc.stdin, None
        try:
            stdin.write(b"x")
            stdin.flush()
        finally:
            try:
                stdin.close()
            except OSError:
                pass

    def go(self, timeout: float = 600) -> tuple[int, str, str]:
        """시작 바이트를 아직 안 보냈으면 보내고, horch 가 끝날 때까지 출력을 읽는다. 잠금 없이 부른다."""
        self.send()
        out, err = self.proc.communicate(timeout=timeout)
        return self.proc.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")

    def kill(self) -> None:
        """시간이 넘었다. 자식(horch)과 그 프로세스 그룹(hc 호출)을 죽이고 거둔다. 예외를 내지 않는다.
        horch 가 만든 launching Dispatch 는 실행자가 죽었으므로 horch 가 launch_failed 로 바꾼다(제목으로 복구).
        이미 거둔 뒤면 아무것도 하지 않는다(그 pid·pgid 는 재사용될 수 있다)."""
        if self.proc.returncode is not None:
            return
        try:
            # 자식은 새 세션의 리더라 pgid == pid 다. 거두기 전이라 pid 가 재사용되지 않으므로 늘 그룹을 죽인다.
            # 리더가 좀비면 macOS 의 getpgid 는 ESRCH 를 내지만 killpg 는 남은 자손에 닿는다
            os.killpg(self.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self.proc.communicate(timeout=5)  # 남은 출력을 비우고 거둔다
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass
        for pipe in (self.proc.stdout, self.proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except Exception:
                pass

    def abort(self) -> None:
        """기록에 실패했다. 바이트 없이 stdin 을 닫아 자식이 horch 를 실행하지 않고 끝나게 한다.

        호출자는 원래 오류를 다시 던지는 중이다. 그 오류를 가리지 않게 최선을 다할 뿐 예외를 내지 않는다.
        기다려도 끝나지 않으면 죽인다(바이트를 받지 않은 자식은 horch 를 실행하지 않았다)."""
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=30)
        except Exception:
            try:
                self.proc.kill()
                self.proc.wait(timeout=5)
            except Exception:
                pass
        for pipe in (self.proc.stdout, self.proc.stderr):
            try:
                if pipe:
                    pipe.close()
            except Exception:
                pass
