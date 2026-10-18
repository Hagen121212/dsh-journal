from __future__ import annotations

import re
from pathlib import Path

HOME = Path.home()
HOME_PATTERNS = [
    re.escape(str(HOME)),
    re.escape(str(HOME).replace("\\", "/")),
    re.escape(str(HOME).replace("\\", "\\\\")),
]

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "<private-key>"),
    (re.compile(r"(?i)(DEEPSEEK_API_KEY\s*[:=]\s*)\S+"), r"\1<redacted>"),
    (re.compile(r"(?i)(secret\s*[:=]\s*)\S+"), r"\1<redacted>"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "<api-key>"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"), "Bearer <token>"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "<email>"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "<phone>"),
    (re.compile(r"\b[0-9a-fA-F]{40,}\b"), "<hex-token>"),
    (re.compile(r"\b[A-Za-z0-9+/]{60,}={0,2}\b"), "<base64-token>"),
]

for pat in HOME_PATTERNS:
    _PATTERNS.append((re.compile(pat, re.I), "<home>"))


def redact(text: str | None) -> str:
    if not text:
        return ""
    out = str(text)
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def contains_secret(text: str | None) -> bool:
    if not text:
        return False
    return bool(
        re.search(r"\bsk-[A-Za-z0-9_-]{12,}\b", text)
        or re.search(r"(?i)DEEPSEEK_API_KEY\s*[:=]", text)
        or "BEGIN " in text and "PRIVATE KEY" in text
    )
