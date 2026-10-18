from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from .cards import cards_for_period
from .config import Config
from .db import (
    get_messages_by_ids,
    get_report,
    save_observations,
    save_report,
    update_insight_verdict,
    upsert_insight,
)
from .ingest import verify_quote
from .llm import LLM
from .prompts import DIMENSIONS, GROWTH_SYSTEM, growth_user_prompt
from .report_md import render_growth_md
from .util import now_ms, write_json, write_text


def _verify_evidence(items: Any, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    ids = [str(x.get("message_id")) for x in items if isinstance(x, dict) and x.get("message_id")]
    rows = get_messages_by_ids(conn, ids)
    out = []
    for x in items:
        if not isinstance(x, dict):
            continue
        quote = str(x.get("quote") or "").strip()
        mid = str(x.get("message_id") or "")
        sid = str(x.get("session_id") or "")
        row = rows.get(mid)
        verified = bool(row and quote and verify_quote(quote, row["content"] or ""))
        if not verified and quote:
            # Fallback: scan this session's messages if we know it.
            if sid:
                candidate = conn.execute(
                    "SELECT * FROM messages WHERE session_id=? AND content LIKE ? LIMIT 3",
                    (sid, f"%{quote[:40]}%"),
                ).fetchall()
                for c in candidate:
                    if verify_quote(quote, c["content"] or ""):
                        row, verified, mid = c, True, c["id"]
                        break
        out.append({
            **x,
            "quote": quote,
            "message_id": mid or None,
            "session_id": (row["session_id"] if row else sid) or None,
            "verified": verified,
        })
    return out


def _clean_evidence(items: Any, conn: sqlite3.Connection, require: bool = True) -> list[dict[str, Any]]:
    ev = _verify_evidence(items, conn)
    if require:
        return [x for x in ev if x.get("verified")]
    return ev


def normalize_growth(raw: dict[str, Any], conn: sqlite3.Connection, baseline: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "period_summary": str(raw.get("period_summary") or "").strip(),
        "dimensions": {},
        "recurring_patterns": [],
        "gaps": [],
        "insights": [],
        "experiment": raw.get("experiment") if isinstance(raw.get("experiment"), dict) else {},
        "old_dialogue": raw.get("old_dialogue") if isinstance(raw.get("old_dialogue"), dict) else None,
    }
    dims = raw.get("dimensions") if isinstance(raw.get("dimensions"), dict) else {}
    for name in DIMENSIONS:
        d = dims.get(name) if isinstance(dims.get(name), dict) else {}
        score = d.get("score")
        try:
            score = float(score) if score is not None else None
        except Exception:
            score = None
        if score is not None:
            score = max(1.0, min(5.0, score))
        if baseline:
            score = None
        out["dimensions"][name] = {
            "score": score,
            "confidence": str(d.get("confidence") or "low"),
            "rationale": str(d.get("rationale") or "").strip(),
            "evidence": _clean_evidence(d.get("evidence"), conn),
            "counter_evidence": str(d.get("counter_evidence") or "暂未发现").strip(),
            "change": "no_baseline" if baseline else str(d.get("change") or "无明显变化").strip(),
        }

    for p in raw.get("recurring_patterns") or []:
        if not isinstance(p, dict):
            continue
        ev = _clean_evidence(p.get("evidence"), conn)
        if ev:
            out["recurring_patterns"].append({
                "pattern": str(p.get("pattern") or "").strip(),
                "occurrences": p.get("occurrences"),
                "evidence": ev,
            })

    for g in raw.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        ev = _clean_evidence(g.get("evidence"), conn)
        if ev:
            out["gaps"].append({
                "stated": str(g.get("stated") or "").strip(),
                "enacted": str(g.get("enacted") or "").strip(),
                "evidence": ev,
            })

    for ins in raw.get("insights") or []:
        if not isinstance(ins, dict):
            continue
        stmt = str(ins.get("statement") or "").strip()
        ev = _clean_evidence(ins.get("evidence"), conn)
        if stmt and ev:
            out["insights"].append({
                "kind": str(ins.get("kind") or "pattern"),
                "statement": stmt,
                "confidence": str(ins.get("confidence") or "low"),
                "evidence": ev,
            })

    out["insight_updates"] = []
    valid_verdicts = {"confirmed", "weakened", "contradicted", "insufficient", "revisit"}
    for u in raw.get("insight_updates") or []:
        if not isinstance(u, dict):
            continue
        stmt = str(u.get("statement") or "").strip()
        verdict = str(u.get("verdict") or "").strip()
        if not stmt or verdict not in valid_verdicts:
            continue
        ev = _clean_evidence(u.get("evidence"), conn)
        note = str(u.get("note") or "").strip()
        if verdict != "insufficient" and not ev:
            verdict = "insufficient"
            note = (note + "（本期未找到可回链证据）").strip()
        out["insight_updates"].append({
            "statement": stmt,
            "verdict": verdict,
            "note": note,
            "evidence": ev,
        })
    return out


def _evidence_preview(raw: str | None, limit: int = 2) -> list[dict[str, Any]]:
    try:
        items = json.loads(raw or "[]")
    except Exception:
        return []
    out = []
    for x in items[-limit:] if isinstance(items, list) else []:
        if isinstance(x, dict) and x.get("quote"):
            out.append({
                "quote": x.get("quote"),
                "session_id": x.get("session_id"),
                "message_id": x.get("message_id"),
            })
    return out


def prior_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM observations ORDER BY period_start DESC, id DESC LIMIT 20"
    ).fetchall()
    latest = rows[0]["period_start"] if rows else None
    dims = {}
    for r in rows:
        if r["period_start"] != latest:
            continue
        dims[r["dimension"]] = {
            "score": r["score"],
            "confidence": r["confidence"],
            "rationale": r["rationale"],
            "change": r["change_note"],
        }
    last_growth = conn.execute(
        "SELECT * FROM reports WHERE kind IN ('growth','baseline') ORDER BY period_start DESC LIMIT 1"
    ).fetchone()
    experiment = None
    if last_growth:
        try:
            experiment = (json.loads(last_growth["meta_json"] or "{}") or {}).get("experiment")
        except Exception:
            experiment = None

    def ins_rows(sql: str) -> list[dict[str, Any]]:
        out = []
        for r in conn.execute(sql).fetchall():
            out.append({
                "statement": r["statement"],
                "kind": r["kind"],
                "confidence": r["confidence"],
                "evidence": _evidence_preview(r["evidence_json"]),
            })
        return out

    return {
        "period": latest,
        "dimensions": dims,
        "last_experiment": experiment,
        "accepted_insights": ins_rows(
            "SELECT * FROM insights WHERE status='accepted' AND kind<>'note' ORDER BY id"
        ),
        "rejected_insights": ins_rows(
            "SELECT * FROM insights WHERE status='rejected' ORDER BY id"
        ),
        "user_corrections": [
            {
                "statement": r["statement"],
                "original_statement": r["original_statement"],
                "evidence": _evidence_preview(r["evidence_json"]),
            }
            for r in conn.execute(
                "SELECT * FROM insights WHERE status='accepted' AND kind='note' ORDER BY id"
            ).fetchall()
        ],
    }


def generate_growth(
    cfg: Config,
    conn: sqlite3.Connection,
    llm: LLM,
    *,
    period_start: str,
    period_end: str,
    baseline: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    cards = cards_for_period(conn, period_start, period_end)
    if not cards:
        raise ValueError(f"{period_start}~{period_end} 没有可用会话卡")
    prior = {} if baseline else prior_payload(conn)
    raw = llm.chat_json(
        GROWTH_SYSTEM,
        growth_user_prompt(cards, period_start, period_end, prior, baseline),
        label=("baseline" if baseline else "growth") + f":{period_end}",
        max_tokens=32000,
        effort="high",
    )
    data = normalize_growth(raw, conn, baseline)
    data["cards"] = cards
    data["period"] = {"start": period_start, "end": period_end, "baseline": baseline}

    # An "old dialogue" is only useful if it points at a real session in this batch.
    old = data.get("old_dialogue")
    if baseline:
        data["old_dialogue"] = None
    elif isinstance(old, dict):
        valid = {c.get("session_id") for c in cards}
        if old.get("session_id") not in valid:
            old["session_id"] = None
        if old.get("what_changed") == "no_baseline":
            old["what_changed"] = "首次基线，暂无可对照的旧对话"
        data["old_dialogue"] = old

    # Persist observations for every dimension, including nulls.
    save_observations(conn, period_start, period_end, data["dimensions"])
    for ins in data["insights"]:
        upsert_insight(conn, ins, period_end)
    for u in data.get("insight_updates") or []:
        update_insight_verdict(conn, u["statement"], u["verdict"], u.get("note") or "", period_end)

    date_tag = period_end
    if baseline:
        kind = "baseline"
        title = f"基线画像：{period_start} 至 {period_end}"
        out_dir = cfg.reports_dir / "baseline"
    else:
        kind = "growth"
        title = f"成长复盘：{period_start} 至 {period_end}"
        out_dir = cfg.reports_dir / "growth"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{date_tag}.md"
    json_path = out_dir / f"{date_tag}.json"
    meta = {
        "mode": "baseline" if baseline else "growth",
        "sessions": len(cards),
        "experiment": data.get("experiment"),
        "dimensions": {k: v.get("score") for k, v in data["dimensions"].items()},
    }
    md = render_growth_md(data, title=title, baseline=baseline)
    write_text(md_path, md)
    write_json(json_path, data)
    save_report(conn, kind, period_start, period_end, title, str(md_path), str(json_path), meta)
    conn.commit()
    if verbose:
        print(f"  + {title}")
        print(f"    {md_path}")
    return data
