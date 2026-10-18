from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import Config
from .util import now_ms, sha256_text


SCHEMA = r"""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT,
  cwd TEXT,
  created_at_ms INTEGER,
  updated_at_ms INTEGER,
  local_date TEXT,
  iso_week TEXT,
  source_path TEXT,
  source_hash TEXT,
  model TEXT,
  message_count INTEGER DEFAULT 0,
  user_chars INTEGER DEFAULT 0,
  assistant_chars INTEGER DEFAULT 0,
  ingested_at_ms INTEGER,
  card_status TEXT DEFAULT 'pending',
  card_at_ms INTEGER,
  prompt_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_created ON sessions(created_at_ms);
CREATE INDEX IF NOT EXISTS idx_sessions_week ON sessions(iso_week);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  source_id TEXT,
  seq INTEGER,
  block_index INTEGER DEFAULT 0,
  role TEXT,
  kind TEXT,
  content TEXT,
  ts_ms INTEGER,
  local_date TEXT,
  turn INTEGER,
  step INTEGER,
  tool_name TEXT,
  tool_call_id TEXT,
  meta_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq, block_index);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts_ms);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  message_id UNINDEXED,
  session_id UNINDEXED,
  content,
  tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS topics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  parent TEXT,
  description TEXT,
  aliases TEXT,
  created_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS session_topics (
  session_id TEXT NOT NULL,
  topic_id INTEGER NOT NULL,
  confidence REAL,
  source TEXT,
  PRIMARY KEY (session_id, topic_id)
);

CREATE TABLE IF NOT EXISTS cards (
  session_id TEXT PRIMARY KEY,
  summary TEXT,
  goal TEXT,
  key_turns_json TEXT,
  conclusions_json TEXT,
  open_loops_json TEXT,
  topics_json TEXT,
  signals_json TEXT,
  self_statements_json TEXT,
  corrections_json TEXT,
  commitments_json TEXT,
  memorable_quote_json TEXT,
  raw_json TEXT,
  model TEXT,
  prompt_version TEXT,
  created_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  period_start TEXT,
  period_end TEXT,
  dimension TEXT,
  score REAL,
  confidence TEXT,
  rationale TEXT,
  evidence_json TEXT,
  counter_evidence TEXT,
  change_note TEXT,
  created_at_ms INTEGER
);
CREATE INDEX IF NOT EXISTS idx_obs_period ON observations(period_start, period_end);

CREATE TABLE IF NOT EXISTS insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT UNIQUE,
  kind TEXT,
  statement TEXT,
  original_statement TEXT,
  evidence_json TEXT,
  confidence TEXT,
  status TEXT DEFAULT 'pending',
  last_verdict TEXT,
  last_verdict_note TEXT,
  times_seen INTEGER DEFAULT 1,
  first_seen_date TEXT,
  last_seen_date TEXT,
  created_at_ms INTEGER,
  updated_at_ms INTEGER
);

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,
  period_start TEXT,
  period_end TEXT,
  title TEXT,
  path TEXT,
  json_path TEXT,
  generated_at_ms INTEGER,
  meta_json TEXT,
  UNIQUE(kind, period_start)
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,
  started_at_ms INTEGER,
  finished_at_ms INTEGER,
  status TEXT,
  stats_json TEXT,
  error TEXT
);
"""


def connect(cfg: Config) -> sqlite3.Connection:
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(cfg.db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Lightweight forward migrations for databases created by earlier builds.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(insights)")}
    for name, decl in [
        ("original_statement", "TEXT"),
        ("last_verdict", "TEXT"),
        ("last_verdict_note", "TEXT"),
    ]:
        if name not in cols:
            conn.execute(f"ALTER TABLE insights ADD COLUMN {name} {decl}")
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def upsert_session(conn: sqlite3.Connection, row: dict[str, Any]) -> None:
    cols = [
        "id", "title", "cwd", "created_at_ms", "updated_at_ms", "local_date", "iso_week",
        "source_path", "source_hash", "model", "message_count", "user_chars", "assistant_chars",
        "ingested_at_ms", "card_status", "card_at_ms", "prompt_version",
    ]
    vals = [row.get(c) for c in cols]
    conn.execute(
        f"""INSERT INTO sessions({','.join(cols)}) VALUES({','.join('?' for _ in cols)})
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title, cwd=excluded.cwd, updated_at_ms=excluded.updated_at_ms,
          local_date=excluded.local_date, iso_week=excluded.iso_week,
          source_path=excluded.source_path, source_hash=excluded.source_hash, model=excluded.model,
          message_count=excluded.message_count, user_chars=excluded.user_chars,
          assistant_chars=excluded.assistant_chars, ingested_at_ms=excluded.ingested_at_ms""",
        vals,
    )


def get_session_source(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT id, source_hash, card_status FROM sessions WHERE id=?", (session_id,)).fetchone()


def replace_messages(conn: sqlite3.Connection, session_id: str, rows: Iterable[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute("DELETE FROM messages_fts WHERE session_id=?", (session_id,))
    cols = [
        "id", "session_id", "source_id", "seq", "block_index", "role", "kind", "content",
        "ts_ms", "local_date", "turn", "step", "tool_name", "tool_call_id", "meta_json",
    ]
    payload = []
    fts = []
    for r in rows:
        payload.append(tuple(r.get(c) for c in cols))
        if r.get("content"):
            fts.append((r["id"], session_id, r["content"]))
    conn.executemany(
        f"INSERT OR REPLACE INTO messages({','.join(cols)}) VALUES({','.join('?' for _ in cols)})",
        payload,
    )
    conn.executemany("INSERT INTO messages_fts(message_id, session_id, content) VALUES(?,?,?)", fts)


def get_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()


def list_sessions(
    conn: sqlite3.Connection,
    limit: int = 100,
    offset: int = 0,
    week: str | None = None,
    topic_id: int | None = None,
    order: str = "created_at_ms DESC",
) -> list[sqlite3.Row]:
    where = ["s.message_count > 0"]
    params: list[Any] = []
    if week:
        where.append("s.iso_week=?")
        params.append(week)
    if topic_id:
        where.append("s.id IN (SELECT session_id FROM session_topics WHERE topic_id=?)")
        params.append(topic_id)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])
    return conn.execute(
        f"SELECT s.* FROM sessions s {clause} ORDER BY {order} LIMIT ? OFFSET ?", params
    ).fetchall()


def get_messages(
    conn: sqlite3.Connection,
    session_id: str,
    include_reasoning: bool = False,
    include_tools: bool = False,
) -> list[sqlite3.Row]:
    kinds = ["text"]
    if include_reasoning:
        kinds.append("reasoning")
    if include_tools:
        kinds.extend(["tool_call", "tool_result"])
    q = f"SELECT * FROM messages WHERE session_id=? AND kind IN ({','.join('?' for _ in kinds)}) ORDER BY seq, block_index"
    return conn.execute(q, [session_id, *kinds]).fetchall()


def get_messages_by_ids(conn: sqlite3.Connection, ids: list[str]) -> dict[str, sqlite3.Row]:
    if not ids:
        return {}
    q = f"SELECT * FROM messages WHERE id IN ({','.join('?' for _ in ids)})"
    return {r["id"]: r for r in conn.execute(q, ids).fetchall()}


def session_weeks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT iso_week, MIN(local_date) AS start, MAX(local_date) AS end, COUNT(*) AS n "
        "FROM sessions GROUP BY iso_week ORDER BY iso_week DESC"
    ).fetchall()


def save_card(conn: sqlite3.Connection, session_id: str, card: dict[str, Any], model: str, prompt_version: str) -> None:
    def j(v):
        return json.dumps(v, ensure_ascii=False) if v is not None else None

    conn.execute(
        """INSERT INTO cards(session_id, summary, goal, key_turns_json, conclusions_json, open_loops_json,
        topics_json, signals_json, self_statements_json, corrections_json, commitments_json,
        memorable_quote_json, raw_json, model, prompt_version, created_at_ms)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(session_id) DO UPDATE SET
          summary=excluded.summary, goal=excluded.goal, key_turns_json=excluded.key_turns_json,
          conclusions_json=excluded.conclusions_json, open_loops_json=excluded.open_loops_json,
          topics_json=excluded.topics_json, signals_json=excluded.signals_json,
          self_statements_json=excluded.self_statements_json, corrections_json=excluded.corrections_json,
          commitments_json=excluded.commitments_json, memorable_quote_json=excluded.memorable_quote_json,
          raw_json=excluded.raw_json, model=excluded.model, prompt_version=excluded.prompt_version,
          created_at_ms=excluded.created_at_ms""",
        (
            session_id, card.get("summary"), card.get("goal"), j(card.get("key_turns")),
            j(card.get("conclusions")), j(card.get("open_loops")), j(card.get("topics")),
            j(card.get("signals")), j(card.get("self_statements")), j(card.get("corrections")),
            j(card.get("commitments")), j(card.get("memorable_quote")), j(card), model,
            prompt_version, now_ms(),
        ),
    )
    conn.execute(
        "UPDATE sessions SET card_status='done', card_at_ms=?, prompt_version=? WHERE id=?",
        (now_ms(), prompt_version, session_id),
    )


def get_card(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM cards WHERE session_id=?", (session_id,)).fetchone()


def card_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for key in [
        "key_turns_json", "conclusions_json", "open_loops_json", "topics_json", "signals_json",
        "self_statements_json", "corrections_json", "commitments_json", "memorable_quote_json", "raw_json",
    ]:
        try:
            d[key.replace("_json", "")] = json.loads(d[key]) if d.get(key) else None
        except Exception:
            d[key.replace("_json", "")] = None
    return d


def ensure_topic(conn: sqlite3.Connection, name: str, parent: str | None = None) -> int:
    name = (name or "").strip()
    if not name:
        name = "未归类"
    row = conn.execute("SELECT id FROM topics WHERE name=?", (name,)).fetchone()
    if row:
        if parent:
            conn.execute("UPDATE topics SET parent=COALESCE(parent, ?) WHERE id=?", (parent, row["id"]))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO topics(name, parent, created_at_ms) VALUES(?,?,?)", (name, parent, now_ms())
    )
    return int(cur.lastrowid)


def link_session_topics(conn: sqlite3.Connection, session_id: str, topics: list[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM session_topics WHERE session_id=?", (session_id,))
    for t in topics:
        name = (t.get("name") or "").strip()
        if not name:
            continue
        tid = ensure_topic(conn, name, t.get("parent"))
        conn.execute(
            "INSERT OR REPLACE INTO session_topics(session_id, topic_id, confidence, source) VALUES(?,?,?,?)",
            (session_id, tid, float(t.get("confidence") or 0.5), "llm"),
        )
    conn.execute("DELETE FROM topics WHERE id NOT IN (SELECT DISTINCT topic_id FROM session_topics)")


def list_topics(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT t.*, COUNT(st.session_id) AS n, MAX(s.local_date) AS last_date
        FROM topics t LEFT JOIN session_topics st ON st.topic_id=t.id
        LEFT JOIN sessions s ON s.id=st.session_id
        GROUP BY t.id HAVING n>0 ORDER BY n DESC, t.name"""
    ).fetchall()


def get_topic(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM topics WHERE id=?", (topic_id,)).fetchone()


def save_observations(conn: sqlite3.Connection, period_start: str, period_end: str, dims: dict[str, Any]) -> None:
    conn.execute("DELETE FROM observations WHERE period_start=? AND period_end=?", (period_start, period_end))
    for dim, d in (dims or {}).items():
        if not isinstance(d, dict):
            continue
        conn.execute(
            """INSERT INTO observations(period_start, period_end, dimension, score, confidence, rationale,
            evidence_json, counter_evidence, change_note, created_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                period_start, period_end, dim, d.get("score"), d.get("confidence"), d.get("rationale"),
                json.dumps(d.get("evidence"), ensure_ascii=False), d.get("counter_evidence"),
                d.get("change"), now_ms(),
            ),
        )


def get_observations(conn: sqlite3.Connection, limit: int = 60) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM observations ORDER BY period_start DESC, dimension LIMIT ?", (limit,)
    ).fetchall()


def observation_series(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    out: dict[str, list[sqlite3.Row]] = {}
    for r in conn.execute("SELECT * FROM observations ORDER BY period_start"):
        out.setdefault(r["dimension"], []).append(r)
    return out


def upsert_insight(conn: sqlite3.Connection, ins: dict[str, Any], date: str) -> int:
    statement = (ins.get("statement") or "").strip()
    kind = (ins.get("kind") or "pattern").strip()
    fp = sha256_text(kind + "|" + statement)
    row = conn.execute("SELECT id, times_seen FROM insights WHERE fingerprint=?", (fp,)).fetchone()
    if row:
        conn.execute(
            "UPDATE insights SET evidence_json=?, confidence=?, times_seen=times_seen+1, last_seen_date=?, updated_at_ms=? WHERE id=?",
            (json.dumps(ins.get("evidence"), ensure_ascii=False), ins.get("confidence"), date, now_ms(), row["id"]),
        )
        return int(row["id"])
    cur = conn.execute(
        """INSERT INTO insights(fingerprint, kind, statement, evidence_json, confidence, status,
        times_seen, first_seen_date, last_seen_date, created_at_ms, updated_at_ms)
        VALUES(?,?,?,?,?, 'pending', 1, ?, ?, ?, ?)""",
        (fp, kind, statement, json.dumps(ins.get("evidence"), ensure_ascii=False), ins.get("confidence"),
         date, date, now_ms(), now_ms()),
    )
    return int(cur.lastrowid)


def list_insights(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    if status:
        return conn.execute("SELECT * FROM insights WHERE status=? ORDER BY times_seen DESC, updated_at_ms DESC", (status,)).fetchall()
    return conn.execute("SELECT * FROM insights ORDER BY status='pending' DESC, times_seen DESC, updated_at_ms DESC").fetchall()


def set_insight_status(conn: sqlite3.Connection, insight_id: int, status: str) -> None:
    conn.execute("UPDATE insights SET status=?, updated_at_ms=? WHERE id=?", (status, now_ms(), insight_id))


def update_insight_verdict(conn: sqlite3.Connection, statement: str, verdict: str, note: str, date: str) -> None:
    row = conn.execute(
        "SELECT id FROM insights WHERE status='accepted' AND kind<>'note' AND statement=?",
        (statement,),
    ).fetchone()
    if not row:
        return
    conn.execute(
        "UPDATE insights SET last_verdict=?, last_verdict_note=?, last_seen_date=?, updated_at_ms=? WHERE id=?",
        (verdict, note, date, now_ms(), row["id"]),
    )


def save_report(conn: sqlite3.Connection, kind: str, period_start: str, period_end: str, title: str,
                path: str, json_path: str | None, meta: dict | None = None) -> None:
    conn.execute(
        """INSERT INTO reports(kind, period_start, period_end, title, path, json_path, generated_at_ms, meta_json)
        VALUES(?,?,?,?,?,?,?,?)
        ON CONFLICT(kind, period_start) DO UPDATE SET period_end=excluded.period_end, title=excluded.title,
        path=excluded.path, json_path=excluded.json_path, generated_at_ms=excluded.generated_at_ms, meta_json=excluded.meta_json""",
        (kind, period_start, period_end, title, path, json_path, now_ms(),
         json.dumps(meta or {}, ensure_ascii=False)),
    )


def list_reports(conn: sqlite3.Connection, kind: str | None = None, limit: int = 50) -> list[sqlite3.Row]:
    if kind:
        return conn.execute("SELECT * FROM reports WHERE kind=? ORDER BY period_start DESC LIMIT ?", (kind, limit)).fetchall()
    return conn.execute("SELECT * FROM reports ORDER BY period_start DESC LIMIT ?", (limit,)).fetchall()


def get_report(conn: sqlite3.Connection, kind: str, period_start: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM reports WHERE kind=? AND period_start=?", (kind, period_start)).fetchone()


def start_run(conn: sqlite3.Connection, kind: str) -> int:
    cur = conn.execute("INSERT INTO runs(kind, started_at_ms, status) VALUES(?,?, 'running')", (kind, now_ms()))
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, stats: dict | None = None, error: str | None = None) -> None:
    conn.execute(
        "UPDATE runs SET finished_at_ms=?, status=?, stats_json=?, error=? WHERE id=?",
        (now_ms(), status, json.dumps(stats or {}, ensure_ascii=False), error, run_id),
    )


def last_run(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()


def search(conn: sqlite3.Connection, q: str, limit: int = 50) -> list[sqlite3.Row]:
    q = (q or "").strip()
    if not q:
        return []
    if len(q) >= 3:
        try:
            rows = conn.execute(
                """SELECT m.*, s.title, bm25(messages_fts) AS rank
                FROM messages_fts f JOIN messages m ON m.id=f.message_id
                JOIN sessions s ON s.id=m.session_id
                WHERE messages_fts MATCH ? AND m.kind='text' ORDER BY rank LIMIT ?""",
                (f'"{q}"', limit),
            ).fetchall()
            if rows:
                return rows
        except sqlite3.OperationalError:
            pass
    like = f"%{q}%"
    return conn.execute(
        """SELECT m.*, s.title, 0 AS rank FROM messages m JOIN sessions s ON s.id=m.session_id
        WHERE m.content LIKE ? AND m.kind='text' ORDER BY m.ts_ms DESC LIMIT ?""",
        (like, limit),
    ).fetchall()


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def one(sql, params=()):
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else 0

    return {
        "sessions": one("SELECT COUNT(*) FROM sessions WHERE message_count>0"),
        "messages": one("SELECT COUNT(*) FROM messages"),
        "user_messages": one("SELECT COUNT(*) FROM messages WHERE role='user' AND kind='text'"),
        "assistant_messages": one("SELECT COUNT(*) FROM messages WHERE role='assistant' AND kind='text'"),
        "topics": one("SELECT COUNT(DISTINCT topic_id) FROM session_topics"),
        "cards": one("SELECT COUNT(*) FROM cards"),
        "insights": one("SELECT COUNT(*) FROM insights"),
        "pending_insights": one("SELECT COUNT(*) FROM insights WHERE status='pending'"),
        "accepted_insights": one("SELECT COUNT(*) FROM insights WHERE status='accepted' AND kind<>'note'"),
        "rejected_insights": one("SELECT COUNT(*) FROM insights WHERE status='rejected'"),
        "notes": one("SELECT COUNT(*) FROM insights WHERE status='accepted' AND kind='note'"),
        "reports": one("SELECT COUNT(*) FROM reports"),
        "first_date": one("SELECT MIN(local_date) FROM sessions"),
        "last_date": one("SELECT MAX(local_date) FROM sessions"),
    }
