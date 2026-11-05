import unittest

from tests.helpers import HorchCase


class CliTest(HorchCase):
    def test_version(self):
        code, out = self.horch("version")
        self.assertEqual(code, 0)
        self.assertEqual(out, {"ok": True, "version": "0.1.0"})

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
