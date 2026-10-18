from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from .cards import cards_for_period
from .config import Config
from .db import get_report, save_report
from .growth import _verify_evidence
from .llm import LLM
from .prompts import WEEKLY_SYSTEM, weekly_user_prompt
from .report_md import render_weekly_md
from .util import TZ, now_ms, week_bounds, write_json, write_text


def _week_range(date_str: str) -> tuple[str, str, str]:
    anchor = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
    start, end = week_bounds(anchor)
    iso = start.isocalendar()
    week_tag = f"{iso.year}-W{iso.week:02d}"
    end_date = (end - timedelta(seconds=1)).strftime("%Y-%m-%d")
    return start.strftime("%Y-%m-%d"), end_date, week_tag


def last_weekly_experiment(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT meta_json FROM reports WHERE kind='weekly' ORDER BY period_start DESC LIMIT 1").fetchone()
    if not row:
        return None
    try:
        return (json.loads(row["meta_json"] or "{}") or {}).get("next_experiment")
    except Exception:
        return None


def normalize_weekly(raw: dict[str, Any], conn: sqlite3.Connection, cards: list[dict]) -> dict[str, Any]:
    valid = {c.get("session_id") for c in cards}
    out: dict[str, Any] = {
        "one_line": str(raw.get("one_line") or "").strip(),
        "threads": [],
        "turns": [],
        "open_loops": [str(x).strip() for x in (raw.get("open_loops") or []) if str(x).strip()],
        "last_experiment": raw.get("last_experiment") if isinstance(raw.get("last_experiment"), dict) else {"status": "none"},
        "lookback": None,
        "next_experiment": raw.get("next_experiment") if isinstance(raw.get("next_experiment"), dict) else {},
    }
    for t in raw.get("threads") or []:
        if not isinstance(t, dict):
            continue
        sids = [s for s in (t.get("session_ids") or []) if s in valid]
        if not sids and not t.get("summary"):
            continue
        out["threads"].append({
            "topic": str(t.get("topic") or "").strip(),
            "summary": str(t.get("summary") or "").strip(),
            "session_ids": sids,
        })
    for t in raw.get("turns") or []:
        if not isinstance(t, dict):
            continue
        ev = _verify_evidence([{
            "quote": t.get("quote"),
            "session_id": t.get("session_id"),
            "message_id": t.get("message_id"),
        }], conn)[0]
        if ev.get("verified") and ev.get("session_id") in valid:
            out["turns"].append({
                "description": str(t.get("description") or "").strip(),
                "quote": ev.get("quote"),
                "session_id": ev.get("session_id"),
                "message_id": ev.get("message_id"),
                "why": str(t.get("why") or "").strip(),
            })
    lb = raw.get("lookback")
    if isinstance(lb, dict):
        ev = _verify_evidence([lb], conn)[0]
        if ev.get("verified") and ev.get("session_id") in valid:
            out["lookback"] = {
                "quote": ev.get("quote"),
                "session_id": ev.get("session_id"),
                "message_id": ev.get("message_id"),
                "why": str(lb.get("why") or "").strip(),
            }
    return out


def generate_weekly(
    cfg: Config,
    conn: sqlite3.Connection,
    llm: LLM,
    *,
    date_str: str,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    start, end, week_tag = _week_range(date_str)
    existing = get_report(conn, "weekly", start)
    if existing and not force:
        if verbose:
            print(f"  = 周报已存在：{week_tag}")
        return {"skipped": True, "week": week_tag}
    cards = cards_for_period(conn, start, end)
    if not cards:
        if verbose:
            print(f"  - {week_tag} 没有可用的会话卡")
        return {"skipped": True, "week": week_tag, "reason": "no_cards"}
    prior = last_weekly_experiment(conn)
    raw = llm.chat_json(
        WEEKLY_SYSTEM,
        weekly_user_prompt(cards, start, end, json.dumps(prior, ensure_ascii=False) if prior else None),
        label=f"weekly:{week_tag}",
        max_tokens=24000,
        effort="low",
    )
    data = normalize_weekly(raw, conn, cards)
    data["period"] = {"start": start, "end": end, "week": week_tag}
    title = f"{week_tag} 周报（{start} 至 {end}）"
    out_dir = cfg.reports_dir / "weekly"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{week_tag}.md"
    json_path = out_dir / f"{week_tag}.json"
    md = render_weekly_md(data, title=title, cards=cards, period=data["period"])
    write_text(md_path, md)
    write_json(json_path, data)
    save_report(
        conn, "weekly", start, end, title, str(md_path), str(json_path),
        {"sessions": len(cards), "next_experiment": data.get("next_experiment")},
    )
    conn.commit()
    if verbose:
        print(f"  + {title}")
        print(f"    {md_path}")
    return data
