import json
import unittest

from tests.helpers import HorchCase


class CliTest(HorchCase):
    def test_version(self):
        code, out = self.horch("version")
        self.assertEqual(code, 0)
        self.assertEqual(out, {"ok": True, "version": "0.3.0"})

    def test_unserializable_success_is_internal_json(self):
        # 성공 봉투를 직렬화하다 실패해도 JSON 한 개(internal)로 알린다(traceback·빈 출력이 아니다)
        import io
        import signal
        from contextlib import redirect_stdout
        from unittest import mock
        from horch import cli
        buf = io.StringIO()
        self.addCleanup(signal.signal, signal.SIGTERM, signal.getsignal(signal.SIGTERM))  # main 이 처리기를 바꾼다
        with mock.patch.object(cli, "_dispatch", lambda args: {"bad": object()}), redirect_stdout(buf):
            code = cli.main(["--home", str(self.home), "version"])
        out = json.loads(buf.getvalue())
        self.assertEqual((code, out["ok"], out["error"]["code"]), (1, False, "internal"))

    def test_version_does_not_create_home(self):
        self.horch("version")
        self.assertFalse(self.home.exists())

    def test_unknown_command_is_usage_error(self):
        code, out = self.horch("nope")
        self.assertEqual(code, 2)
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"]["code"], "usage")

    def test_missing_command_is_usage_error(self):
        code, out = self.horch()
        self.assertEqual(code, 2)
        self.assertEqual(out["error"]["code"], "usage")


if __name__ == "__main__":
    unittest.main()
