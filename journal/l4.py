from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config
from .db import list_insights, save_report
from .report_md import _quote_block
from .util import TZ, now_ms, write_text


KIND_LABEL = {
    "pattern": "模式",
    "strength": "优势",
    "blind_spot": "盲点",
    "value": "价值排序",
    "question_style": "提问风格",
    "note": "修正/备注",
}
VERDICT_LABEL = {
    "confirmed": "仍成立",
    "weakened": "减弱",
    "contradicted": "出现反例",
    "insufficient": "证据不足",
    "revisit": "值得重看",
    "user_correction": "来源修正",
}


def _evidence(row) -> list[dict]:
    try:
        items = json.loads(row["evidence_json"] or "[]")
    except Exception:
        return []
    return [x for x in items if isinstance(x, dict) and x.get("quote")]


def render_l4_md(rows: list[sqlite3.Row], date_str: str, next_review: str | None = None) -> str:
    accepted = [r for r in rows if r["status"] == "accepted" and r["kind"] != "note"]
    notes = [r for r in rows if r["status"] == "accepted" and r["kind"] == "note"]
    rejected = [r for r in rows if r["status"] == "rejected"]
    next_text = f"下一次复核：{next_review} ｜ " if next_review else ""
    out = [f"# L4 档案：已确认的自我认知\n"]
    out.append(f"> 更新：{date_str} ｜ {next_text}已确认 {len(accepted)} 条 ｜ 修正 {len(notes)} 条 ｜ 驳回 {len(rejected)} 条\n")
    out.append("> 这份档案只收录你在「洞察」页确认过的内容。AI 起草的候选判断不在这里；下一次成长报告会逐条复核已确认项是否仍成立。\n")

    out.append("## 已确认\n")
    if not accepted:
        out.append("还没有已确认的自我认知。\n")
    for r in accepted:
        label = KIND_LABEL.get(r["kind"], r["kind"] or "观察")
        out.append(f"### [{label}] {r['statement']}\n")
        conf = {"low": "低", "medium": "中", "high": "高"}.get(str(r["confidence"]), "低")
        out.append(f"置信度：{conf} ｜ 首次出现：{r['first_seen_date'] or ''}\n")
        if r["last_verdict"]:
            out.append(f"最近复核：{VERDICT_LABEL.get(r['last_verdict'], r['last_verdict'])}\n")
        for ev in _evidence(r)[:3]:
            q = _quote_block(ev, [])
            if q:
                out.append(q + "\n")

    out.append("## 你的修正\n")
    if not notes:
        out.append("还没有修正记录。\n")
    for r in notes:
        out.append(f"### {r['statement']}\n")
        if r["original_statement"]:
            out.append(f"原判断：{r['original_statement']}\n")
        out.append("> 这是来源/归属修正，不作为自我认知特质使用。\n")
        for ev in _evidence(r)[:3]:
            q = _quote_block(ev, [])
            if q:
                out.append(q + "\n")

    out.append("## 已驳回\n")
    if not rejected:
        out.append("没有被驳回的判断。\n")
    for r in rejected:
        label = KIND_LABEL.get(r["kind"], r["kind"] or "观察")
        out.append(f"### [{label}] {r['statement']}\n")
        out.append("> 你不认同这个判断。系统不会原样重提；只有出现强新证据时才值得重看。\n")
        for ev in _evidence(r)[:2]:
            q = _quote_block(ev, [])
            if q:
                out.append(q + "\n")

    out.append("## 下一次复核\n")
    out.append(f"下一次成长报告（{next_review or '待定'}）会逐条检查已确认项：仍成立 / 减弱 / 出现反例 / 证据不足。修正项只用于提醒 AI 不要错误归属来源。\n")
    return "\n".join(out)


def generate_l4(cfg: Config, conn: sqlite3.Connection, date_str: str | None = None) -> dict:
    date_str = date_str or datetime.now(tz=TZ).strftime("%Y-%m-%d")
    rows = list_insights(conn, None)
    accepted = [r for r in rows if r["status"] == "accepted" and r["kind"] != "note"]
    notes = [r for r in rows if r["status"] == "accepted" and r["kind"] == "note"]
    rejected = [r for r in rows if r["status"] == "rejected"]
    out_dir = cfg.reports_dir / "l4"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{date_str}.md"
    json_path = out_dir / f"{date_str}.json"
    title = "L4 档案：已确认的自我认知"
    last = conn.execute(
        "SELECT period_end FROM reports WHERE kind IN ('baseline','growth') ORDER BY period_start DESC LIMIT 1"
    ).fetchone()
    next_review = None
    if last and last["period_end"]:
        try:
            next_review = (datetime.strptime(last["period_end"], "%Y-%m-%d") + timedelta(days=13)).strftime("%Y-%m-%d")
        except Exception:
            next_review = None
    write_text(md_path, render_l4_md(rows, date_str, next_review))
    json_path.write_text(json.dumps({
        "updated": date_str,
        "accepted": [dict(r) for r in accepted],
        "notes": [dict(r) for r in notes],
        "rejected": [dict(r) for r in rejected],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    save_report(
        conn, "l4", date_str, date_str, title, str(md_path), str(json_path),
        {"accepted": len(accepted), "notes": len(notes), "rejected": len(rejected)},
    )
    conn.commit()
    print(f"  + {title}")
    print(f"    {md_path}")
    return {
        "ok": True,
        "date": date_str,
        "accepted": len(accepted),
        "notes": len(notes),
        "rejected": len(rejected),
        "path": str(md_path),
    }
