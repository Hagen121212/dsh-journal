from __future__ import annotations

import json
import sqlite3
from typing import Any

from .config import Config
from .db import (
    card_dict,
    get_card,
    get_messages,
    get_session,
    link_session_topics,
    list_sessions,
    save_card,
)
from .ingest import build_transcript, resolve_alias, verify_quote
from .llm import BudgetExceeded, LLM
from .prompts import CARD_SYSTEM, card_user_prompt
from .util import truncate


SIGNAL_KEYS = ["question_quality", "logic_language", "decision", "research", "cognition", "technical"]


def _clean_evidence(item: Any, id_map: dict[str, str], messages_by_id: dict[str, sqlite3.Row]) -> dict[str, Any]:
    if not isinstance(item, dict):
        item = {}
    quote = str(item.get("quote") or "").strip()
    mid = resolve_alias(item.get("message_id"), id_map)
    verified = False
    if mid and mid in messages_by_id:
        verified = verify_quote(quote, messages_by_id[mid]["content"] or "")
    if not verified and quote:
        for m in messages_by_id.values():
            if verify_quote(quote, m["content"] or ""):
                mid = m["id"]
                verified = True
                break
    out = dict(item)
    out["quote"] = quote
    out["message_id"] = mid
    out["verified"] = bool(verified)
    return out


def normalize_card(card: dict[str, Any], id_map: dict[str, str], messages_by_id: dict[str, sqlite3.Row], taxonomy: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    out["summary"] = str(card.get("summary") or "").strip()
    out["goal"] = str(card.get("goal") or "").strip()

    def ev_list(key: str) -> list[dict[str, Any]]:
        val = card.get(key)
        if not isinstance(val, list):
            return []
        return [_clean_evidence(x, id_map, messages_by_id) for x in val if isinstance(x, dict)]

    out["key_turns"] = ev_list("key_turns")
    out["conclusions"] = [str(x).strip() for x in (card.get("conclusions") or []) if str(x).strip()]
    out["open_loops"] = [str(x).strip() for x in (card.get("open_loops") or []) if str(x).strip()]

    topics = []
    for t in (card.get("topics") or []):
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        parent = str(t.get("parent") or "未归类").strip()
        if parent not in taxonomy:
            parent = "未归类"
        try:
            conf = float(t.get("confidence") or 0.5)
        except Exception:
            conf = 0.5
        topics.append({"name": name, "parent": parent, "confidence": max(0.0, min(1.0, conf))})
    topics.sort(key=lambda x: x["confidence"], reverse=True)
    out["topics"] = topics[:4]

    signals_in = card.get("signals") if isinstance(card.get("signals"), dict) else {}
    signals = {}
    for k in SIGNAL_KEYS:
        vals = signals_in.get(k) if isinstance(signals_in.get(k), list) else []
        signals[k] = [_clean_evidence(x, id_map, messages_by_id) for x in vals if isinstance(x, dict)]
    out["signals"] = signals

    out["self_statements"] = ev_list("self_statements")
    out["corrections"] = ev_list("corrections")
    out["commitments"] = ev_list("commitments")

    mq = card.get("memorable_quote")
    if isinstance(mq, dict):
        mq = dict(mq)
        if not mq.get("quote"):
            mq["quote"] = mq.get("text") or ""
        if not mq.get("text"):
            mq["text"] = mq.get("quote") or ""
        mq = _clean_evidence(mq, id_map, messages_by_id)
    out["memorable_quote"] = mq if isinstance(mq, dict) and mq.get("verified") else None
    return out


def generate_card(cfg: Config, conn: sqlite3.Connection, llm: LLM, session_id: str) -> dict[str, Any]:
    session = get_session(conn, session_id)
    if not session:
        raise ValueError(f"unknown session {session_id}")
    messages = get_messages(conn, session_id, include_reasoning=False, include_tools=True)
    if not any(m["role"] == "user" and m["kind"] == "text" for m in messages):
        conn.execute("UPDATE sessions SET card_status='empty', card_at_ms=? WHERE id=?", (0, session_id))
        return {"empty": True}
    transcript, id_map = build_transcript(messages, max_chars=45000, user_limit=4000, assistant_limit=700)
    user_prompt = card_user_prompt(session["title"] or "未命名会话", session["local_date"] or "", transcript, cfg.taxonomy)
    raw = llm.chat_json(CARD_SYSTEM, user_prompt, label=f"card:{session_id[-8:]}", max_tokens=24000, effort="low")
    messages_by_id = {
        m["id"]: m
        for m in messages
        if m["kind"] == "text" and m["role"] in ("user", "assistant")
    }
    card = normalize_card(raw, id_map, messages_by_id, cfg.taxonomy)
    save_card(conn, session_id, card, cfg.model, cfg.prompt_version)
    if card.get("topics"):
        link_session_topics(conn, session_id, card["topics"])
    conn.commit()
    return card


def generate_pending_cards(
    cfg: Config,
    conn: sqlite3.Connection,
    llm: LLM,
    *,
    limit: int | None = None,
    force: bool = False,
    verbose: bool = True,
) -> dict[str, Any]:
    if force:
        sessions = list_sessions(conn, limit=limit or 1000, order="created_at_ms ASC")
    else:
        sessions = conn.execute(
            "SELECT * FROM sessions WHERE COALESCE(card_status,'pending')<>'done' AND message_count>0 ORDER BY created_at_ms ASC"
            + (" LIMIT ?" if limit else ""),
            ((limit,) if limit else ()),
        ).fetchall()
    stats = {"total": len(sessions), "done": 0, "empty": 0, "errors": 0, "skipped": 0}
    for s in sessions:
        if s["message_count"] == 0:
            conn.execute("UPDATE sessions SET card_status='empty' WHERE id=?", (s["id"],))
            conn.commit()
            stats["empty"] += 1
            continue
        try:
            card = generate_card(cfg, conn, llm, s["id"])
            if card.get("empty"):
                stats["empty"] += 1
                if verbose:
                    print(f"  - 空会话：{s['title']}")
            else:
                stats["done"] += 1
                if verbose:
                    print(f"  + 卡片：{s['title'][:36]}  topics={[t['name'] for t in card.get('topics', [])]}")
        except BudgetExceeded:
            stats["skipped"] += 1
            if verbose:
                print("  ! 预算到顶，停止生成卡片")
            break
        except Exception as e:
            stats["errors"] += 1
            if verbose:
                print(f"  ! 卡片失败 {s['title'][:30]}: {e}")
    return stats


def card_payload(conn: sqlite3.Connection, session_id: str, *, verified_only: bool = True) -> dict[str, Any]:
    s = get_session(conn, session_id)
    row = get_card(conn, session_id)
    if not s or not row:
        return {}
    c = card_dict(row)
    payload: dict[str, Any] = {
        "session_id": s["id"],
        "title": s["title"],
        "date": s["local_date"],
        "summary": c.get("summary"),
        "goal": c.get("goal"),
        "conclusions": c.get("conclusions") or [],
        "open_loops": c.get("open_loops") or [],
        "topics": c.get("topics") or [],
        "memorable_quote": c.get("memorable_quote"),
        "key_turns": c.get("key_turns") or [],
        "signals": c.get("signals") or {},
        "self_statements": c.get("self_statements") or [],
        "corrections": c.get("corrections") or [],
        "commitments": c.get("commitments") or [],
    }

    def keep(items):
        if not isinstance(items, list):
            return []
        if not verified_only:
            return items
        return [x for x in items if isinstance(x, dict) and x.get("verified")]

    if verified_only:
        payload["key_turns"] = keep(payload["key_turns"])
        payload["self_statements"] = keep(payload["self_statements"])
        payload["corrections"] = keep(payload["corrections"])
        payload["commitments"] = keep(payload["commitments"])
        payload["signals"] = {k: keep(v) for k, v in (payload["signals"] or {}).items()}
        if payload.get("memorable_quote") and not payload["memorable_quote"].get("verified"):
            payload["memorable_quote"] = None
    return payload


def cards_for_period(conn: sqlite3.Connection, start: str, end: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id FROM sessions WHERE local_date>=? AND local_date<=? AND card_status='done' ORDER BY created_at_ms",
        (start, end),
    ).fetchall()
    return [p for p in (card_payload(conn, r["id"]) for r in rows) if p]
