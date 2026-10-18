#!/usr/bin/env python3
"""Build a self-contained demo home from the synthetic dataset.

    python tools/build_demo.py --home demo-home

The script never touches real DSH data: it only reads
``examples/demo_dataset.json`` (all content is fictional) and writes a fresh
SQLite database plus report files under ``--home``. It is used to take the
screenshots in ``docs/`` and to smoke-test the Web UI without an API key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from journal.config import Config  # noqa: E402
from journal.db import (  # noqa: E402
    connect,
    finish_run,
    init_db,
    link_session_topics,
    list_insights,
    save_card,
    save_observations,
    save_report,
    start_run,
    upsert_session,
    replace_messages,
)
from journal.l4 import render_l4_md  # noqa: E402
from journal.report_md import render_growth_md, render_weekly_md  # noqa: E402
from journal.util import TZ, local_date, now_ms, write_json, write_text  # noqa: E402

DATASET = ROOT / "examples" / "demo_dataset.json"


def _ms(date_str: str, time_str: str = "09:00") -> int:
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    return int(dt.timestamp() * 1000)


def _demo_config(home: Path) -> Config:
    cfg = Config.load()
    cfg.home = home
    cfg.data_dir = home / "data"
    cfg.db_path = cfg.data_dir / "journal.db"
    cfg.reports_dir = home / "reports"
    cfg.logs_dir = home / "logs"
    cfg.ensure_dirs()
    return cfg


def _session_rows(session: dict) -> tuple[dict, list[dict]]:
    sid = session["id"]
    start = _ms(session["date"], session.get("start_time", "09:00"))
    rows: list[dict] = []
    cursor = 0
    for item in session["messages"]:
        cursor += 1
        ts = start + cursor * 90_000
        if item["role"] == "user":
            mid = f"{sid}:user:{item['id']}"
            seq = cursor * 10
            rows.append({
                "id": mid, "session_id": sid, "source_id": item["id"], "seq": seq,
                "block_index": 0, "role": "user", "kind": "text", "content": item["text"],
                "ts_ms": ts, "local_date": local_date(ts), "turn": cursor, "step": None,
                "tool_name": None, "tool_call_id": None, "meta_json": None,
            })
        else:
            mid = f"{sid}:assistant:{item['id']}:text:0"
            seq = cursor * 10 - 5
            rows.append({
                "id": mid, "session_id": sid, "source_id": item["id"], "seq": seq,
                "block_index": 0, "role": "assistant", "kind": "text", "content": item["text"],
                "ts_ms": ts, "local_date": local_date(ts), "turn": cursor, "step": 1,
                "tool_name": None, "tool_call_id": None, "meta_json": None,
            })
    user_chars = sum(len(r["content"]) for r in rows if r["role"] == "user")
    assistant_chars = sum(len(r["content"]) for r in rows if r["role"] == "assistant")
    local = local_date(start)
    iso = datetime.fromtimestamp(start / 1000, tz=TZ).strftime("%G-W%V")
    row = {
        "id": sid,
        "title": session["title"],
        "cwd": "~/projects/notes",
        "created_at_ms": start,
        "updated_at_ms": rows[-1]["ts_ms"],
        "local_date": local,
        "iso_week": iso,
        "source_path": f"(demo)/sessions/{sid}/session.v4.jsonl",
        "source_hash": hashlib.sha256(sid.encode()).hexdigest(),
        "model": session.get("model", "deepseek-flash"),
        "message_count": len(rows),
        "user_chars": user_chars,
        "assistant_chars": assistant_chars,
        "ingested_at_ms": now_ms(),
    }
    return row, rows


def _verified(items):
    out = []
    for item in items or []:
        item = dict(item)
        item["verified"] = True
        out.append(item)
    return out


def _clean_card(card: dict) -> dict:
    card = dict(card)
    for key in ("key_turns", "self_statements", "corrections", "commitments"):
        card[key] = _verified(card.get(key))
    card["signals"] = {k: _verified(v) for k, v in (card.get("signals") or {}).items()}
    if isinstance(card.get("memorable_quote"), dict):
        card["memorable_quote"] = _verified([card["memorable_quote"]])[0]
    return card


def _insert_insights(conn, insights: list[dict]) -> None:
    for ins in insights:
        fingerprint = hashlib.sha256(
            (ins["kind"] + "|" + ins["statement"]).encode("utf-8")
        ).hexdigest()
        ts = now_ms()
        conn.execute(
            """INSERT INTO insights(fingerprint, kind, statement, original_statement, evidence_json,
            confidence, status, times_seen, first_seen_date, last_seen_date, created_at_ms, updated_at_ms)
            VALUES(?,?,?,?,?,?,?,1,?,?,?,?)""",
            (
                fingerprint, ins["kind"], ins["statement"], ins.get("original_statement"),
                json.dumps(ins.get("evidence") or [], ensure_ascii=False),
                ins.get("confidence", "low"), ins.get("status", "pending"),
                ins.get("date"), ins.get("date"), ts, ts,
            ),
        )
    conn.commit()


def _insert_reports(cfg: Config, conn, dataset: dict) -> None:
    cards = [
        {"session_id": s["id"], "title": s["title"]}
        for s in dataset["sessions"]
    ]
    for rep in dataset["reports"]:
        kind = rep["kind"]
        start, end = rep["period_start"], rep["period_end"]
        data = dict(rep.get("data") or {})
        title = rep["title"]
        if kind == "weekly":
            iso = datetime.strptime(start, "%Y-%m-%d").isocalendar()
            week_tag = f"{iso.year}-W{iso.week:02d}"
            period = {"start": start, "end": end, "week": week_tag}
            data["period"] = period
            md = render_weekly_md(data, title=title, cards=cards, period=period)
            folder = cfg.reports_dir / "weekly"
            name = f"{week_tag}.md"
        elif kind in ("growth", "baseline"):
            baseline = kind == "baseline"
            data["period"] = {"start": start, "end": end, "baseline": baseline}
            data["cards"] = list(cards)
            md = render_growth_md(data, title=title, baseline=baseline)
            folder = cfg.reports_dir / ("baseline" if baseline else "growth")
            name = f"{end}.md"
        elif kind == "l4":
            rows = list_insights(conn, None)
            md = render_l4_md(rows, start, next_review="2026-11-08")
            folder = cfg.reports_dir / "l4"
            name = f"{start}.md"
        else:
            raise ValueError(f"unknown report kind: {kind}")
        write_text(folder / name, md)
        json_path = folder / (name[:-3] + ".json")
        write_json(json_path, data)
        save_report(
            conn, kind, start, end, title, str(folder / name), str(json_path),
            {"sessions": len(dataset["sessions"]), "demo": True},
        )
    conn.commit()


def build(home: Path, dataset_path: Path = DATASET, clean: bool = False) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if clean and home.exists():
        shutil.rmtree(home)
    cfg = _demo_config(home)
    conn = connect(cfg)
    init_db(conn)

    run_id = start_run(conn, "backfill")
    for session in dataset["sessions"]:
        row, messages = _session_rows(session)
        upsert_session(conn, row)
        replace_messages(conn, session["id"], messages)
        save_card(conn, session["id"], _clean_card(session["card"]), row["model"], "v1")
        link_session_topics(conn, session["id"], session.get("topics") or [])
        conn.commit()

    _insert_insights(conn, dataset.get("insights") or [])

    for rep in dataset["reports"]:
        if rep["kind"] in ("baseline", "growth"):
            save_observations(
                conn, rep["period_start"], rep["period_end"],
                (rep.get("data") or {}).get("dimensions") or {},
            )
    conn.commit()

    _insert_reports(cfg, conn, dataset)
    finish_run(conn, run_id, "ok", {"sessions": len(dataset["sessions"]), "demo": True})
    conn.commit()

    summary = {
        "home": str(home),
        "sessions": len(dataset["sessions"]),
        "insights": len(dataset.get("insights") or []),
        "reports": len(dataset["reports"]),
    }
    conn.close()
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the synthetic demo database")
    parser.add_argument("--home", default=str(ROOT / "demo-home"), help="where to write the demo home")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--clean", action="store_true", help="delete the target home first")
    args = parser.parse_args(argv)
    summary = build(Path(args.home).expanduser().resolve(), Path(args.dataset), clean=args.clean)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n启动预览：")
    print(f"  set JOURNAL_HOME={summary['home']}")
    print("  python -m journal.cli serve --port 8766")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
