from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Week boundaries and report dates are computed in this zone.
TZ = ZoneInfo(os.environ.get("JOURNAL_TZ", "Asia/Shanghai"))


def now_ms() -> int:
    return int(datetime.now(tz=TZ).timestamp() * 1000)


def ms_to_local(ms: int | None) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=TZ)


def local_date(ms: int | None) -> str | None:
    dt = ms_to_local(ms)
    return dt.strftime("%Y-%m-%d") if dt else None


def iso_week(ms: int | None) -> str | None:
    dt = ms_to_local(ms)
    if not dt:
        return None
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def week_bounds(anchor: datetime) -> tuple[datetime, datetime]:
    """Monday 00:00 to next Monday 00:00, local time."""
    start = anchor - timedelta(days=anchor.weekday())
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def date_range(start: datetime, end: datetime):
    cur = start
    while cur < end:
        yield cur
        cur += timedelta(days=1)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def truncate(text: str | None, limit: int, suffix: str = "…") -> str:
    if not text:
        return ""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))] + suffix


def one_line(text: str | None, limit: int = 120) -> str:
    if not text:
        return ""
    s = re.sub(r"\s+", " ", str(text)).strip()
    return truncate(s, limit)


def strip_code_fence(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def parse_llm_json(text: str) -> dict:
    s = strip_code_fence(text or "")
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        pass
    start = s.find("{")
    end = s.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(s[start : end + 1])
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def human_bytes(n: int) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"
