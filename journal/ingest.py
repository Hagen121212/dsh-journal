from __future__ import annotations

import json
import sqlite3
import traceback
from pathlib import Path
from typing import Any

from .config import Config
from .db import get_session_source, replace_messages, upsert_session
from .sources.dsh import iter_sessions, load_session
from .util import local_date, iso_week, now_ms, truncate


def sync(
    cfg: Config,
    conn: sqlite3.Connection,
    *,
    force: bool = False,
    limit: int | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    stats = {"scanned": 0, "processed": 0, "skipped": 0, "errors": 0, "messages": 0, "sessions": []}
    log_path = cfg.logs_dir / "sync.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    for path, dir_id, source_hash in iter_sessions(cfg):
        stats["scanned"] += 1
        if limit is not None and stats["processed"] >= limit:
            break
        existing = get_session_source(conn, dir_id)
        if existing and existing["source_hash"] == source_hash and not force:
            stats["skipped"] += 1
            continue
        try:
            parsed = load_session(path, dir_id, source_hash, cfg)
        except Exception as e:
            stats["errors"] += 1
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n[{now_ms()}] sync failed {path}: {e}\n{traceback.format_exc()[-3000:]}\n")
            if verbose:
                print(f"  ! 跳过 {path.parent.name}: {e}")
            continue

        user_chars = sum(len(m.content) for m in parsed.messages if m.role == "user" and m.kind == "text")
        assistant_chars = sum(len(m.content) for m in parsed.messages if m.role == "assistant" and m.kind == "text")
        row = {
            "id": parsed.id,
            "title": parsed.title,
            "cwd": parsed.cwd,
            "created_at_ms": parsed.created_at_ms,
            "updated_at_ms": parsed.updated_at_ms,
            "local_date": local_date(parsed.created_at_ms),
            "iso_week": iso_week(parsed.created_at_ms),
            "source_path": parsed.source_path,
            "source_hash": parsed.source_hash,
            "model": parsed.model,
            "message_count": len(parsed.messages),
            "user_chars": user_chars,
            "assistant_chars": assistant_chars,
            "ingested_at_ms": now_ms(),
        }
        upsert_session(conn, row)
        conn.execute(
            "UPDATE sessions SET card_status='pending', card_at_ms=NULL WHERE id=?",
            (parsed.id,),
        )
        replace_messages(conn, parsed.id, [
            {
                "id": m.id,
                "session_id": parsed.id,
                "source_id": m.source_id,
                "seq": m.seq,
                "block_index": m.block_index,
                "role": m.role,
                "kind": m.kind,
                "content": m.content,
                "ts_ms": m.ts_ms,
                "local_date": local_date(m.ts_ms),
                "turn": m.turn,
                "step": m.step,
                "tool_name": m.tool_name,
                "tool_call_id": m.tool_call_id,
                "meta_json": json.dumps(m.meta, ensure_ascii=False) if m.meta else None,
            }
            for m in parsed.messages
        ])
        conn.commit()
        stats["processed"] += 1
        stats["messages"] += len(parsed.messages)
        stats["sessions"].append(parsed.id)
        if verbose:
            print(f"  + {parsed.title[:40]}  ({len(parsed.messages)} 条, {user_chars} 字用户输入)")

    return stats


def build_transcript(
    messages: list[sqlite3.Row],
    *,
    max_chars: int = 60000,
    user_limit: int = 4000,
    assistant_limit: int = 1200,
    tool_limit: int = 160,
) -> tuple[str, dict[str, str]]:
    """Build a compact, quote-friendly transcript with m1..mN aliases."""
    id_map: dict[str, str] = {}
    lines: list[str] = []
    turn = 0
    total = 0
    for m in messages:
        role = m["role"]
        kind = m["kind"]
        if role == "user" and kind == "text":
            turn += 1
            text = (m["content"] or "").strip()
            if not text:
                continue
            alias = f"m{len(id_map) + 1}"
            id_map[alias] = m["id"]
            text = truncate(text, user_limit)
            line = f"[{alias}] U{turn}: {text}"
        elif role == "assistant" and kind == "text":
            text = (m["content"] or "").strip()
            if not text:
                continue
            alias = f"m{len(id_map) + 1}"
            id_map[alias] = m["id"]
            text = truncate(text, assistant_limit)
            line = f"[{alias}] A{turn}: {text}"
        elif role == "assistant" and kind == "tool_call":
            line = f"    T{turn}: {m['tool_name'] or 'tool'}"
        else:
            continue
        total += len(line) + 1
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines), id_map


def resolve_alias(value: Any, id_map: dict[str, str]) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    if s in id_map:
        return id_map[s]
    # Allow raw message ids too.
    if s.startswith("session-"):
        return s
    return None


def normalize_quote(s: str) -> str:
    return " ".join((s or "").split()).strip()


def verify_quote(quote: str, message_content: str) -> bool:
    q = normalize_quote(quote)
    c = normalize_quote(message_content)
    if not q:
        return False
    if q in c:
        return True
    # Allow the model to trim punctuation at the edges.
    q2 = q.strip("。！？!?，,；;：:…\"'“”‘’ ")
    return bool(q2 and q2 in c)
