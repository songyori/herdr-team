"""테스트 하네스 자체 검증: 헬퍼의 상태 변경이 가짜 hc 와 겹쳐도 사라지지 않는다."""
from __future__ import annotations

import subprocess
import threading
import time
import unittest

from tests.helpers import HorchCase


class HarnessLockTest(HorchCase):
    def test_update_terminal_survives_concurrent_fake_hc(self) -> None:
        addr = "t900"
        self.add_terminal(addr, status="idle")
        errors: list[str] = []

        def hammer() -> None:
            for _ in range(30):
                proc = subprocess.run(["hc", "get", addr, "--json"], capture_output=True,
                                      text=True, env=self.env, timeout=30)
                if proc.returncode != 0:
                    errors.append(proc.stderr)

        th = threading.Thread(target=hammer)
        th.start()
        for i in range(30):
            self.update_terminal(addr, status=f"s{i}")
            time.sleep(0.015)  # hc 호출(약 20ms)과 번갈아 겹치게 한다
        th.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.hc_state()["terminals"][addr]["status"]["state"], "s29")


if __name__ == "__main__":
    unittest.main()
