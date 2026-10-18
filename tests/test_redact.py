from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from journal.redact import contains_secret, redact  # noqa: E402


class RedactTest(unittest.TestCase):
    def test_api_key(self) -> None:
        out = redact("用这个 key：sk-abcdefghijklmnop1234")
        self.assertIn("<api-key>", out)
        self.assertNotIn("sk-abcdefghijklmnop1234", out)

    def test_env_assignment(self) -> None:
        out = redact("DEEPSEEK_API_KEY=sk-secret-value-here")
        self.assertNotIn("sk-secret-value-here", out)

    def test_email_and_phone(self) -> None:
        out = redact("联系 someone@example.com 或 13812345678")
        self.assertIn("<email>", out)
        self.assertIn("<phone>", out)

    def test_home_path(self) -> None:
        home = str(Path.home())
        out = redact(f"文件在 {home}\\notes\\a.md")
        self.assertIn("<home>", out)
        self.assertNotIn(home, out)

    def test_plain_text_is_untouched(self) -> None:
        text = "先写一个最小用例，再补边界。"
        self.assertEqual(redact(text), text)

    def test_contains_secret(self) -> None:
        self.assertTrue(contains_secret("sk-abcdefghijklmnop1234"))
        self.assertTrue(contains_secret("DEEPSEEK_API_KEY: x"))
        self.assertFalse(contains_secret("普通的一句话"))


if __name__ == "__main__":
    unittest.main()
