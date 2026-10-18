from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from ..config import Config
from ..redact import redact
from ..util import now_ms, sha256_file, truncate


@dataclass
class ParsedMessage:
    id: str
    source_id: str
    seq: int
    block_index: int
    role: str
    kind: str
    content: str
    ts_ms: int | None
    turn: int | None
    step: int | None
    tool_name: str | None = None
    tool_call_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedSession:
    id: str
    title: str
    cwd: str | None
    created_at_ms: int | None
    updated_at_ms: int | None
    model: str | None
    source_path: str
    source_hash: str
    messages: list[ParsedMessage]
    event_count: int
    parse_errors: int


def find_node(cfg: Config) -> str:
    candidates = []
    if cfg.node_path:
        candidates.append(Path(cfg.node_path))
    which = shutil.which("node")
    if which:
        candidates.append(Path(which))
    candidates.extend([
        cfg.dsh_home / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
        cfg.dsh_home / "dsh-runtimes" / "dsh-primary-runtime" / "dependencies" / "node" / "node.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "node.exe",
    ])
    for p in candidates:
        if p and p.exists():
            return str(p)
    raise RuntimeError("找不到 Node.js。请设置 DSH_NODE 环境变量指向 node.exe。")


def session_files(cfg: Config) -> list[Path]:
    root = cfg.dsh_home / "sessions"
    if not root.exists():
        return []
    files = sorted(root.rglob("session.v4.jsonl.zstd"), key=lambda p: p.stat().st_mtime)
    return files


def decompress(src: Path, dst: Path, cfg: Config) -> None:
    helper = Path(__file__).resolve().parent.parent.parent / "tools" / "decompress_session.mjs"
    if not helper.exists():
        raise RuntimeError(f"缺少解压脚本：{helper}")
    node = find_node(cfg)
    tmp_dir = cfg.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_dir / f"{src.parent.name}.decompress.log"
    dst.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(
            [node, str(helper), str(src), str(dst)],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
    if proc.returncode != 0:
        detail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"解压失败 {src}: {detail}")


def _blocks_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for b in content:
        if isinstance(b, str):
            parts.append(b)
        elif isinstance(b, dict):
            if b.get("type") == "text" and b.get("text"):
                parts.append(str(b["text"]))
            elif b.get("type") == "image":
                parts.append("[图片]")
    return "\n".join(parts).strip()


def _title_from_user(text: str) -> str:
    s = " ".join(text.split())
    if s.startswith("@"):
        s = s.split(" ", 1)[-1]
    if len(s) > 32:
        s = s[:32] + "…"
    return s or "未命名会话"


def _parse_user_event(ev: dict[str, Any]) -> dict[str, Any] | None:
    data = ev.get("data") or {}
    msg = data.get("message") if isinstance(data.get("message"), dict) else data
    if not isinstance(msg, dict):
        return None
    if msg.get("role") != "user":
        return None
    src = msg.get("source") or data.get("source") or {}
    if isinstance(src, dict) and src.get("kind") not in (None, "user"):
        return None
    mid = msg.get("id") or f"user-{ev.get('seq')}"
    text = _blocks_text(msg.get("content"))
    if not text:
        return None
    return {
        "id": str(mid),
        "seq": int(ev.get("seq") or 0),
        "time": int(ev.get("time") or 0),
        "text": text,
        "surface": data.get("surfaceOp") or ev.get("surfaceOp"),
    }


def parse_session_file(path: Path, session_id: str, source_hash: str) -> ParsedSession:
    header: dict[str, Any] = {}
    title = ""
    title_quality = 0
    model = None
    messages: list[ParsedMessage] = []
    users: dict[str, dict[str, Any]] = {}
    assistants: dict[str, dict[str, Any]] = {}
    tool_names: dict[str, str] = {}
    event_count = 0
    parse_errors = 0
    max_time = 0
    turn = None
    step = None

    def add_user(u: dict[str, Any]) -> None:
        existing = users.get(u["id"])
        if existing is None or u["seq"] >= existing["seq"]:
            users[u["id"]] = u

    with path.open("r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                parse_errors += 1
                continue
            if not isinstance(ev, dict):
                continue
            event_count += 1
            t = ev.get("type")
            ts = ev.get("time")
            if isinstance(ts, int):
                max_time = max(max_time, ts)

            if t == "session":
                header = ev
            elif t == "session/title":
                d = ev.get("data") or {}
                cand = (d.get("title") or "").strip()
                if cand:
                    q = 2 if (d.get("source") or {}).get("kind") != "fallback" else 1
                    if q >= title_quality:
                        title, title_quality = cand, q
            elif t == "model/selection":
                model = (ev.get("data") or {}).get("model") or model
            elif t == "turn/start":
                turn = (ev.get("data") or {}).get("turn", turn)
            elif t == "step/start":
                d = ev.get("data") or {}
                turn = d.get("turn", turn)
                step = d.get("step", step)
            elif t == "user/message":
                u = _parse_user_event(ev)
                if u:
                    add_user(u)
            elif t == "agent/inbox/spliced":
                for ins in ((ev.get("data") or {}).get("inserted") or []):
                    if isinstance(ins, dict) and ins.get("role") == "user":
                        src = ins.get("source") or {}
                        if isinstance(src, dict) and src.get("kind") not in (None, "user"):
                            continue
                        mid = ins.get("id") or f"inbox-{ev.get('seq')}"
                        text = _blocks_text(ins.get("content"))
                        if text:
                            add_user({
                                "id": str(mid),
                                "seq": int(ev.get("seq") or 0),
                                "time": int(ev.get("time") or 0),
                                "text": text,
                                "surface": "inbox",
                            })
            elif t == "assistant/message":
                d = ev.get("data") or {}
                msg = d.get("message") if isinstance(d.get("message"), dict) else {}
                if msg.get("role") == "assistant":
                    mid = str(msg.get("id") or f"assistant-{ev.get('seq')}")
                    assistants[mid] = {
                        "id": mid,
                        "seq": int(ev.get("seq") or 0),
                        "time": int(ev.get("time") or 0),
                        "turn": d.get("turn", turn),
                        "step": d.get("step", step),
                        "content": msg.get("content") or [],
                    }
            elif t == "tool/call":
                d = ev.get("data") or {}
                cid = d.get("callId")
                if cid:
                    tool_names[cid] = d.get("name") or "tool"
            elif t == "tool/result":
                d = ev.get("data") or {}
                msg = d.get("message") or {}
                cid = d.get("toolCallId") or msg.get("toolCallId")
                text = _blocks_text(msg.get("content"))
                if text:
                    messages.append(ParsedMessage(
                        id=f"{session_id}:tool-result:{ev.get('seq')}",
                        source_id=f"tool-result-{ev.get('seq')}",
                        seq=int(ev.get("seq") or 0),
                        block_index=0,
                        role="tool",
                        kind="tool_result",
                        content=redact(truncate(text, 2000)),
                        ts_ms=ts,
                        turn=d.get("turn", turn),
                        step=d.get("step", step),
                        tool_name=tool_names.get(cid, "tool"),
                        tool_call_id=cid,
                        meta={"truncated": len(text) > 2000},
                    ))

    # User messages
    user_turn = 0
    for u in sorted(users.values(), key=lambda x: x["seq"]):
        user_turn += 1
        messages.append(ParsedMessage(
            id=f"{session_id}:user:{u['id']}",
            source_id=u["id"],
            seq=u["seq"],
            block_index=0,
            role="user",
            kind="text",
            content=redact(u["text"]),
            ts_ms=u["time"],
            turn=user_turn,
            step=None,
            meta={"surface": u.get("surface")},
        ))

    # Assistant messages, preserving block order.
    for a in sorted(assistants.values(), key=lambda x: x["seq"]):
        block_index = 0
        text_buf: list[str] = []
        reason_buf: list[str] = []

        def flush_text() -> None:
            nonlocal block_index, text_buf
            if text_buf:
                content = redact("\n".join(text_buf).strip())
                if content:
                    messages.append(ParsedMessage(
                        id=f"{session_id}:assistant:{a['id']}:text:{block_index}",
                        source_id=a["id"], seq=a["seq"], block_index=block_index,
                        role="assistant", kind="text", content=content, ts_ms=a["time"],
                        turn=a.get("turn"), step=a.get("step"), meta={},
                    ))
                    block_index += 1
                text_buf = []

        def flush_reason() -> None:
            nonlocal block_index, reason_buf
            if reason_buf:
                content = redact("\n".join(reason_buf).strip())
                if content:
                    messages.append(ParsedMessage(
                        id=f"{session_id}:assistant:{a['id']}:reasoning:{block_index}",
                        source_id=a["id"], seq=a["seq"], block_index=block_index,
                        role="assistant", kind="reasoning", content=content, ts_ms=a["time"],
                        turn=a.get("turn"), step=a.get("step"), meta={},
                    ))
                    block_index += 1
                reason_buf = []

        content = a.get("content")
        if isinstance(content, str):
            text_buf.append(content)
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    text_buf.append(str(b.get("text") or ""))
                elif bt == "reasoning":
                    reason_buf.append(str(b.get("text") or ""))
                elif bt in ("tool-call", "tool_call"):
                    flush_text()
                    flush_reason()
                    cid = b.get("id") or b.get("callId")
                    name = b.get("name") or tool_names.get(cid, "tool")
                    args = b.get("arguments")
                    if not isinstance(args, str):
                        args = json.dumps(args, ensure_ascii=False)
                    messages.append(ParsedMessage(
                        id=f"{session_id}:assistant:{a['id']}:tool:{block_index}",
                        source_id=a["id"], seq=a["seq"], block_index=block_index,
                        role="assistant", kind="tool_call", content=redact(truncate(args or "", 1200)),
                        ts_ms=a["time"], turn=a.get("turn"), step=a.get("step"),
                        tool_name=str(name), tool_call_id=cid, meta={},
                    ))
                    block_index += 1
        flush_text()
        flush_reason()

    messages.sort(key=lambda m: (m.seq or 0, m.block_index))

    sid = str(header.get("id") or session_id)
    created = header.get("createdAt") if isinstance(header.get("createdAt"), int) else None
    first_user = next((m.content for m in messages if m.role == "user"), "")
    if not title or title_quality < 2:
        title = _title_from_user(first_user) if first_user else (title or "未命名会话")

    return ParsedSession(
        id=sid,
        title=title,
        cwd=header.get("cwd"),
        created_at_ms=created,
        updated_at_ms=max_time or created,
        model=model,
        source_path=str(path),
        source_hash=source_hash,
        messages=messages,
        event_count=event_count,
        parse_errors=parse_errors,
    )


def iter_sessions(cfg: Config) -> Iterator[tuple[Path, str, str]]:
    """Yield (path, session_id, hash) for every DSH session file."""
    for p in session_files(cfg):
        sid = p.parent.name
        try:
            h = sha256_file(p)
        except OSError:
            continue
        yield p, sid, h


def load_session(path: Path, session_id: str, source_hash: str, cfg: Config) -> ParsedSession:
    tmp = cfg.data_dir / "tmp" / f"{session_id}.jsonl"
    decompress(path, tmp, cfg)
    try:
        return parse_session_file(tmp, session_id, source_hash)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass
