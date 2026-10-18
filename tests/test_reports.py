from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from journal.report_md import render_growth_md, render_weekly_md  # noqa: E402

CARDS = [{"session_id": "demo-001", "title": "给命令行工具加 --dry-run"}]

EVIDENCE = [{
    "quote": "我倾向上只覆盖会丢数据的操作。",
    "session_id": "demo-001",
    "message_id": "demo-001:user:u2",
    "verified": True,
}]


class WeeklyReportTest(unittest.TestCase):
    def test_sections_links_and_quotes(self) -> None:
        data = {
            "one_line": "这周把模糊问题收窄成可验证的实验。",
            "threads": [{"topic": "把范围收窄", "summary": "先定规则再动手。", "session_ids": ["demo-001"]}],
            "turns": [{"description": "从列举功能转为给出标准", "quote": "我倾向上只覆盖会丢数据的操作。",
                       "session_id": "demo-001", "message_id": "demo-001:user:u2", "why": "可复用"}],
            "open_loops": ["判定表还没写"],
            "last_experiment": {"status": "none", "evidence": "首次周报"},
            "lookback": None,
            "next_experiment": {"title": "写判定表", "how": "四列", "done_when": "覆盖删除与覆盖"},
        }
        md = render_weekly_md(data, title="2026-W42 周报", cards=CARDS,
                              period={"start": "2026-10-12", "end": "2026-10-18"})
        self.assertIn("# 2026-W42 周报", md)
        self.assertIn("## 一句话", md)
        self.assertIn("## 在追的线", md)
        self.assertIn("## 关键转折", md)
        self.assertIn("## 下周一个实验", md)
        # Evidence links must stay clickable relative paths.
        self.assertIn("/sessions/demo-001", md)
        self.assertIn("> 我倾向上只覆盖会丢数据的操作。", md)

    def test_empty_data_still_renders(self) -> None:
        md = render_weekly_md({}, title="空周报", cards=[],
                              period={"start": "2026-10-12", "end": "2026-10-18"})
        self.assertIn("# 空周报", md)
        self.assertIn("本周暂无概括。", md)


class GrowthReportTest(unittest.TestCase):
    def _data(self, score):
        dims = {
            name: {
                "score": score,
                "confidence": "medium",
                "rationale": f"{name} 的判断",
                "evidence": EVIDENCE,
                "counter_evidence": "暂未发现",
                "change": "no_baseline",
            }
            for name in ["技术判断力", "决策质量", "研究方法", "逻辑语言能力", "思维认知方式"]
        }
        return {
            "period_summary": "这一期在收窄问题。",
            "dimensions": dims,
            "recurring_patterns": [],
            "gaps": [],
            "insights": [],
            "insight_updates": [],
            "experiment": {"title": "写判定表", "why": "验证", "how": "四列", "done_when": "能覆盖删除"},
            "old_dialogue": None,
            "cards": CARDS,
        }

    def test_baseline_does_not_score(self) -> None:
        md = render_growth_md(self._data(None), title="基线画像", baseline=True)
        self.assertIn("观察中（基线不打分）", md)
        self.assertIn("不构成成长结论", md)
        self.assertNotIn("3/5", md)

    def test_scored_report_shows_value_and_confidence(self) -> None:
        md = render_growth_md(self._data(3), title="成长复盘", baseline=False)
        self.assertIn("3/5（置信度：中）", md)
        self.assertIn("**反例/保留**：暂未发现", md)
        self.assertIn("## 下两周一个实验", md)

    def test_insight_updates_are_rendered(self) -> None:
        data = self._data(3)
        data["insight_updates"] = [{
            "statement": "你倾向先给约束再要方案。",
            "verdict": "confirmed",
            "note": "这一期仍然如此。",
            "evidence": EVIDENCE,
        }]
        md = render_growth_md(data, title="成长复盘", baseline=False)
        self.assertIn("## 已确认认知的复核", md)
        self.assertIn("[仍成立] 你倾向先给约束再要方案。", md)


if __name__ == "__main__":
    unittest.main()
