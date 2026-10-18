from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from journal.ingest import normalize_quote, resolve_alias, verify_quote  # noqa: E402


class VerifyQuoteTest(unittest.TestCase):
    def test_exact_match(self) -> None:
        self.assertTrue(verify_quote("先别改代码", "我想先别改代码，先想清楚。"))

    def test_whitespace_and_newlines_are_normalized(self) -> None:
        self.assertTrue(verify_quote("先测清楚\n时间花在哪", "先测清楚 时间花在哪，再优化。"))

    def test_trailing_punctuation_is_tolerated(self) -> None:
        self.assertTrue(verify_quote("别急着扩展。", "那就先只处理删除和覆盖，写一个判定表我看看，别急着扩展。"))

    def test_paraphrase_is_rejected(self) -> None:
        self.assertFalse(verify_quote("先别写代码", "我想先别改代码，先想清楚。"))

    def test_empty_is_rejected(self) -> None:
        self.assertFalse(verify_quote("", "任意内容"))
        self.assertFalse(verify_quote("   ", "任意内容"))

    def test_normalize_quote(self) -> None:
        self.assertEqual(normalize_quote("  a \n b\tc  "), "a b c")


class ResolveAliasTest(unittest.TestCase):
    def test_alias_lookup(self) -> None:
        id_map = {"m1": "s1:user:u1"}
        self.assertEqual(resolve_alias("m1", id_map), "s1:user:u1")
        self.assertIsNone(resolve_alias("m9", id_map))

    def test_raw_session_id_passthrough(self) -> None:
        # DSH session ids start with "session-"; anything else must be an mN alias.
        self.assertEqual(resolve_alias("session-abc:user:u1", {}), "session-abc:user:u1")
        self.assertIsNone(resolve_alias("demo-001:user:u1", {}))

    def test_empty(self) -> None:
        self.assertIsNone(resolve_alias(None, {}))
        self.assertIsNone(resolve_alias("", {}))


if __name__ == "__main__":
    unittest.main()
