from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from .util import TZ


def e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def attr(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def session_url(sid: str, mid: str | None = None) -> str:
    base = f"/sessions/{quote(str(sid))}"
    if mid:
        return base + "?m=" + quote(str(mid))
    return base


def message_anchor(mid: str) -> str:
    import hashlib
    return "m-" + hashlib.sha1(str(mid).encode("utf-8")).hexdigest()[:10]


def badge(text: str, kind: str = "") -> str:
    cls = "badge" + (f" badge-{kind}" if kind else "")
    return f'<span class="{cls}">{e(text)}</span>'


def _safe_url(url: str) -> str:
    u = (url or "").strip()
    if u.startswith("/") or u.startswith("#") or u.startswith("http://") or u.startswith("https://"):
        return html.escape(u, quote=True)
    return "#"


def inline_md(text: str) -> str:
    placeholders: list[str] = []

    def stash(s: str) -> str:
        placeholders.append(s)
        return f"@@PH{len(placeholders) - 1}@@"

    def link_repl(m):
        label = html.escape(m.group(1), quote=False)
        url = _safe_url(m.group(2))
        return stash(f'<a href="{url}">{label}</a>')

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link_repl, text)
    text = re.sub(r"`([^`]+)`", lambda m: stash(f"<code>{html.escape(m.group(1), quote=False)}</code>"), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    for i, ph in enumerate(placeholders):
        text = text.replace(f"@@PH{i}@@", ph)
    return text


def md_to_html(md: str) -> str:
    lines = (md or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    quote_lines: list[str] = []
    list_items: list[str] = []
    list_kind = ""
    in_code = False
    code_lines: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            out.append("<p>" + inline_md(" ".join(para).strip()) + "</p>")
            para = []

    def flush_quote():
        nonlocal quote_lines
        if quote_lines:
            body = []
            buf = []
            for q in quote_lines:
                if q.strip() == "":
                    if buf:
                        body.append("<p>" + inline_md(" ".join(buf).strip()) + "</p>")
                        buf = []
                else:
                    buf.append(q)
            if buf:
                body.append("<p>" + inline_md(" ".join(buf).strip()) + "</p>")
            out.append("<blockquote>" + "".join(body) + "</blockquote>")
            quote_lines = []

    def flush_list():
        nonlocal list_items, list_kind
        if list_items:
            tag = "ol" if list_kind == "ol" else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline_md(x)}</li>" for x in list_items) + f"</{tag}>")
            list_items = []
            list_kind = ""

    for raw in lines:
        line = raw.rstrip()
        if in_code:
            if line.strip().startswith("```"):
                out.append("<pre><code>" + html.escape("\n".join(code_lines), quote=False) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                code_lines.append(raw)
            continue
        if line.strip().startswith("```"):
            flush_para(); flush_quote(); flush_list()
            in_code = True
            continue
        if not line.strip():
            flush_para(); flush_quote(); flush_list()
            continue
        if line.startswith(">"):
            flush_para(); flush_list()
            quote_lines.append(line[1:].lstrip())
            continue
        if line.startswith("#"):
            flush_para(); flush_quote(); flush_list()
            m = re.match(r"^(#{1,4})\s+(.*)$", line)
            if m:
                level = len(m.group(1))
                out.append(f"<h{level}>{inline_md(m.group(2))}</h{level}>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            flush_para(); flush_quote()
            if list_kind and list_kind != "ul":
                flush_list()
            list_kind = "ul"
            list_items.append(re.sub(r"^\s*[-*]\s+", "", line))
            continue
        if re.match(r"^\s*\d+\.\s+", line):
            flush_para(); flush_quote()
            if list_kind and list_kind != "ol":
                flush_list()
            list_kind = "ol"
            list_items.append(re.sub(r"^\s*\d+\.\s+", "", line))
            continue
        if re.match(r"^\s*---+\s*$", line):
            flush_para(); flush_quote(); flush_list()
            out.append("<hr>")
            continue
        flush_quote()
        para.append(line.strip())
    flush_para(); flush_quote(); flush_list()
    if in_code and code_lines:
        out.append("<pre><code>" + html.escape("\n".join(code_lines), quote=False) + "</code></pre>")
    return "\n".join(out)


def svg_spark(values: list[float | None], width: int = 180, height: int = 44, color: str = "var(--accent)") -> str:
    nums = [v for v in values if v is not None]
    if not nums:
        return '<div class="spark-empty">尚无趋势</div>'
    if len(nums) == 1:
        return (
            f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-label="单点">'
            f'<circle cx="{width/2:.1f}" cy="{height/2:.1f}" r="4" fill="{color}"/>'
            f'<text x="{width/2:.1f}" y="{height-2:.1f}" text-anchor="middle" font-size="9" fill="var(--muted)">首个观察点</text>'
            f'</svg>'
        )
    lo, hi = min(nums), max(nums)
    if hi == lo:
        hi = lo + 1
    pad = 6
    pts = []
    for i, v in enumerate(values):
        if v is None:
            continue
        x = pad + i * (width - 2 * pad) / max(1, len(values) - 1)
        y = height - pad - (v - lo) / (hi - lo) * (height - 2 * pad)
        pts.append((x, y))
    path = " ".join(("M" if i == 0 else "L") + f"{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{color}"/>' for x, y in pts)
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-label="趋势">'
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
        f"{dots}</svg>"
    )


def heatmap(dates: dict[str, int], weeks: int = 12) -> str:
    today = datetime.now(tz=TZ).date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
    max_n = max(dates.values()) if dates else 1
    cells = []
    for i in range(weeks * 7):
        d = start + timedelta(days=i)
        n = dates.get(d.strftime("%Y-%m-%d"), 0)
        level = 0 if n == 0 else min(4, 1 + int((n / max(1, max_n)) * 3))
        cells.append(f'<span class="hm-cell hm-{level}" title="{d.isoformat()} · {n} 个会话"></span>')
    return '<div class="heatmap">' + "".join(cells) + "</div>"
