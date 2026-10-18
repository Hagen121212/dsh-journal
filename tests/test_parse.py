from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from journal.ingest import build_transcript  # noqa: E402
from journal.sources.dsh import parse_session_file  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "examples" / "fixtures"


class ParseSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parsed = parse_session_file(FIXTURES / "minimal_session.jsonl", "s1", "hash")

    def test_injected_context_is_filtered(self) -> None:
        texts = " ".join(m.content for m in self.parsed.messages)
        self.assertNotIn("RUNTIME CONTEXT", texts)
        self.assertNotIn("injected", texts)

    def test_roles_and_kinds(self) -> None:
        user = [m for m in self.parsed.messages if m.role == "user"]
        assistant = [m for m in self.parsed.messages if m.role == "assistant"]
        self.assertEqual(len(user), 1)
        self.assertEqual([m.kind for m in assistant], ["text", "reasoning"])
        self.assertEqual(len([m for m in self.parsed.messages if m.role == "tool"]), 1)

    def test_ids_and_title(self) -> None:
        self.assertEqual(self.parsed.title, "测试会话")
        self.assertEqual(self.parsed.id, "s1")
        user = next(m for m in self.parsed.messages if m.role == "user")
        self.assertEqual(user.id, "s1:user:u1")
        self.assertEqual(user.turn, 1)

    def test_messages_are_sorted(self) -> None:
        seqs = [(m.seq, m.block_index) for m in self.parsed.messages]
        self.assertEqual(seqs, sorted(seqs))

    def test_broken_lines_are_counted_not_fatal(self) -> None:
        parsed = parse_session_file(FIXTURES / "broken_session.jsonl", "s2", "hash")
        self.assertEqual(parsed.parse_errors, 1)
        self.assertEqual(parsed.event_count, 3)
        self.assertEqual(int(parsed.messages[0].seq), 1)


class TranscriptTest(unittest.TestCase):
    def test_aliases_and_quotes_survive(self) -> None:
        messages = [
            {"id": "s1:user:u1", "role": "user", "kind": "text", "content": "怎么测？", "tool_name": None},
            {"id": "s1:assistant:a1:text:0", "role": "assistant", "kind": "text",
             "content": "先写最小用例。", "tool_name": None},
            {"id": "s1:assistant:a1:tool:1", "role": "assistant", "kind": "tool_call",
             "content": "{}", "tool_name": "read_file"},
        ]
        transcript, id_map = build_transcript(messages)
        self.assertIn("[m1] U1: 怎么测？", transcript)
        self.assertIn("[m2] A1: 先写最小用例。", transcript)
        self.assertIn("T1: read_file", transcript)
        self.assertEqual(id_map["m1"], "s1:user:u1")
        self.assertEqual(id_map["m2"], "s1:assistant:a1:text:0")


if __name__ == "__main__":
    unittest.main()
