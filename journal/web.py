from __future__ import annotations

import json
import mimetypes
import sqlite3
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from .cards import card_payload, cards_for_period
from .config import Config
from .db import (
    connect,
    get_card,
    get_messages,
    get_report,
    get_session,
    get_topic,
    init_db,
    last_run,
    list_insights,
    list_reports,
    list_sessions,
    list_topics,
    observation_series,
    search,
    set_insight_status,
    stats,
)
from .redact import redact
from .util import iso_week, one_line, truncate
from .webutil import (
    attr,
    badge,
    e,
    heatmap,
    md_to_html,
    message_anchor,
    session_url,
    svg_spark,
)


NAV = [
    ("/", "概览", "dashboard"),
    ("/timeline", "时间线", "timeline"),
    ("/topics", "主题", "topics"),
    ("/growth", "成长", "growth"),
    ("/insights", "洞察", "insights"),
    ("/reports", "报告", "reports"),
]

DIM_LABELS = ["技术判断力", "决策质量", "研究方法", "逻辑语言能力", "思维认知方式"]


def _read_json(path: str | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_report(conn: sqlite3.Connection, kind: str | None = None):
    if kind:
        return conn.execute(
            "SELECT * FROM reports WHERE kind=? ORDER BY period_start DESC, generated_at_ms DESC LIMIT 1", (kind,)
        ).fetchone()
    return conn.execute(
        "SELECT * FROM reports WHERE kind IN ('growth','baseline') ORDER BY period_start DESC, generated_at_ms DESC LIMIT 1"
    ).fetchone()


def _fmt_date(s: str | None) -> str:
    if not s:
        return ""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return f"{d.month}月{d.day}日"
    except Exception:
        return s


def _week_label(week: str | None, start: str | None, end: str | None) -> str:
    if week and start and end:
        return f"{week} · {_fmt_date(start)} – {_fmt_date(end)}"
    return week or ""


def _topic_chips(topics: list[dict]) -> str:
    out = []
    for t in topics or []:
        if not isinstance(t, dict):
            continue
        name = t.get("name")
        if not name:
            continue
        out.append(f'<span class="chip">{e(name)}</span>')
    return "".join(out)


def _quote_block(ev: dict, title: str | None = None) -> str:
    q = (ev.get("quote") or ev.get("text") or "").strip()
    if not q:
        return ""
    sid = ev.get("session_id")
    mid = ev.get("message_id")
    href = session_url(sid, mid) if sid else ""
    verified = ev.get("verified")
    meta = []
    if href:
        meta.append(f'<a href="{attr(href)}">原话</a>')
    if title:
        meta.append(e(title))
    if verified is False:
        meta.append('<span class="warn">未通过原文校验</span>')
    footer = " · ".join(meta)
    return f'<blockquote class="evidence"><p>{e(q)}</p><footer>{footer}</footer></blockquote>'


def _evidence_list(evs: list[dict], title: str | None = None, limit: int = 3) -> str:
    return "".join(_quote_block(x, title) for x in (evs or [])[:limit] if isinstance(x, dict))


def _score_label(score) -> str:
    if score is None:
        return "观察中"
    try:
        return f"{float(score):g}/5"
    except Exception:
        return "观察中"


def _conf_label(c: str | None) -> str:
    return {"low": "低", "medium": "中", "high": "高"}.get(str(c), "低")


def _page(title: str, body: str, active: str, conn: sqlite3.Connection, cfg: Config, q: str = "") -> str:
    nav = []
    for href, label, key in NAV:
        cls = "nav-link active" if key == active else "nav-link"
        nav.append(f'<a class="{cls}" href="{href}">{label}</a>')
    run = last_run(conn)
    run_html = ""
    if run:
        status = run["status"]
        when = datetime.fromtimestamp((run["finished_at_ms"] or run["started_at_ms"] or 0) / 1000).strftime("%m-%d %H:%M")
        cls = "run-ok" if status == "ok" else "run-bad"
        run_html = f'<div class="sidebar-run {cls}">上次运行 {when} · {e(status)}</div>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · 思维年轮</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div class="shell">
  <aside class="sidebar">
    <a class="brand" href="/">
      <span class="brand-mark">年</span>
      <span class="brand-text">思维年轮<small>DeepSeek Journal</small></span>
    </a>
    <nav class="nav">{''.join(nav)}</nav>
    <div class="sidebar-foot">
      <div class="sidebar-note">每周日 20:00 自动生成</div>
      {run_html}
    </div>
  </aside>
  <main class="main">
    <header class="topbar">
      <div class="crumb">{e(title)}</div>
      <form class="search" action="/search" method="get">
        <input name="q" value="{attr(q)}" placeholder="搜索对话、人物、概念…" autocomplete="off">
        <button type="submit" aria-label="搜索">搜索</button>
      </form>
    </header>
    {body}
    <footer class="footer">本地运行 · 数据只在你的机器上 · 引用均可回链原文</footer>
  </main>
</div>
</body>
</html>"""


def _stat(label: str, value, sub: str = "") -> str:
    return f"""<div class="stat"><div class="stat-label">{e(label)}</div><div class="stat-value">{e(value)}</div><div class="stat-sub">{e(sub)}</div></div>"""


def dashboard(conn: sqlite3.Connection, cfg: Config) -> str:
    s = stats(conn)
    weekly = _latest_report(conn, "weekly")
    weekly_data = _read_json(weekly["json_path"]) if weekly else {}
    growth = _latest_report(conn)
    growth_data = _read_json(growth["json_path"]) if growth else {}
    latest_sessions = list_sessions(conn, limit=6)
    topics = list_topics(conn)[:8]

    if weekly:
        hero = f"""
        <section class="hero">
          <div class="eyebrow">{e(weekly['title'])}</div>
          <h1>{e(weekly_data.get('one_line') or '本周周报已生成')}</h1>
          <div class="hero-actions">
            <a class="btn primary" href="/reports/weekly/{e(weekly['period_start'])}">读本周周报</a>
            <a class="btn" href="/timeline">看时间线</a>
          </div>
        </section>"""
    else:
        hero = f"""
        <section class="hero">
          <div class="eyebrow">起点</div>
          <h1>先建立基线，再谈成长。</h1>
          <p class="lede">周报会在每周日 20:00 自动生成。第一份成长报告需要至少两个观察点。</p>
          <div class="hero-actions">
            <a class="btn primary" href="/growth">看基线画像</a>
            <a class="btn" href="/timeline">浏览会话</a>
          </div>
        </section>"""

    stat_html = "".join([
        _stat("会话", s["sessions"], f"{s['first_date'] or ''} 起"),
        _stat("消息", s["messages"], f"用户 {s['user_messages']} 条"),
        _stat("主题", s["topics"], "跨会话线程"),
        _stat("待确认洞察", s["pending_insights"], f"已确认 {s['accepted_insights']} · 修正 {s['notes']}" if not s["pending_insights"] else "到「洞察」页处理"),
    ])

    dims = []
    series = observation_series(conn)
    for dim in DIM_LABELS:
        rows = series.get(dim, [])
        latest = rows[-1] if rows else None
        vals = [r["score"] for r in rows]
        if not latest:
            note = "还没有观察点"
        elif latest["score"] is None:
            note = f"{len(rows)} 个观察点 · 置信度{_conf_label(latest['confidence'])}"
        else:
            note = f"置信度 {_conf_label(latest['confidence'])}"
        dims.append(f"""
        <a class="card dim-card" href="/growth">
          <div class="dim-head"><span>{e(dim)}</span><span class="dim-score">{_score_label(latest['score'] if latest else None)}</span></div>
          {svg_spark(vals)}
          <div class="dim-note">{e(note)}</div>
        </a>""")

    recent = []
    for sess in latest_sessions:
        p = card_payload(conn, sess["id"], verified_only=False) or {}
        summary = p.get("summary") or "尚未生成会话卡。"
        recent.append(f"""
        <a class="session-row" href="/sessions/{e(sess['id'])}">
          <div class="session-date">{e(_fmt_date(sess['local_date']))}</div>
          <div class="session-main">
            <div class="session-title">{e(sess['title'])}</div>
            <div class="session-summary">{e(truncate(summary, 150))}</div>
            <div class="chips">{_topic_chips(p.get('topics') or [])}</div>
          </div>
        </a>""")

    topic_html = "".join(
        f'<a class="chip chip-lg" href="/topics/{t["id"]}">{e(t["name"])}<span>{t["n"]}</span></a>'
        for t in topics
    ) or '<div class="empty">还没有主题。生成会话卡后会自动出现。</div>'

    growth_note = ""
    if growth:
        growth_note = f"""
        <div class="card soft">
          <div class="eyebrow">{e(growth['title'])}</div>
          <p class="clamp-4">{e(growth_data.get('period_summary') or '')}</p>
          <a class="text-link" href="/reports/{e(growth['kind'])}/{e(growth['period_start'])}">读完整画像 →</a>
        </div>"""

    body = f"""
    {hero}
    <section class="stats">{stat_html}</section>
    <section class="section">
      <div class="section-head"><h2>五维状态</h2><a class="text-link" href="/growth">成长页 →</a></div>
      <div class="grid dims">{''.join(dims)}</div>
    </section>
    <section class="section two-col">
      <div>
        <div class="section-head"><h2>最近会话</h2><a class="text-link" href="/timeline">全部 →</a></div>
        <div class="card list-card">{''.join(recent) or '<div class="empty">还没有会话。</div>'}</div>
      </div>
      <div>
        <div class="section-head"><h2>主题</h2><a class="text-link" href="/topics">全部 →</a></div>
        <div class="card">{topic_html}</div>
        <div class="section-head spaced"><h2>最新画像</h2></div>
        {growth_note or '<div class="card empty">基线画像生成后会显示在这里。</div>'}
      </div>
    </section>
    """
    return _page("概览", body, "dashboard", conn, cfg)


def timeline(conn: sqlite3.Connection, cfg: Config, topic_id: int | None = None) -> str:
    sessions = list_sessions(conn, limit=300, topic_id=topic_id)
    groups: dict[str, list] = {}
    for s in sessions:
        groups.setdefault(s["iso_week"] or "未知", []).append(s)
    blocks = []
    for week, items in groups.items():
        start = min((x["local_date"] for x in items if x["local_date"]), default="")
        end = max((x["local_date"] for x in items if x["local_date"]), default="")
        rows = []
        for s in items:
            p = card_payload(conn, s["id"], verified_only=False) or {}
            rows.append(f"""
            <a class="session-row" href="/sessions/{e(s['id'])}">
              <div class="session-date">{e(_fmt_date(s['local_date']))}</div>
              <div class="session-main">
                <div class="session-title">{e(s['title'])}</div>
                <div class="session-summary">{e(truncate(p.get('summary') or '尚未生成会话卡。', 180))}</div>
                <div class="chips">{_topic_chips(p.get('topics') or [])}</div>
              </div>
            </a>""")
        blocks.append(f"""
        <section class="week-block">
          <div class="week-head"><span>{e(_week_label(week, start, end))}</span><span class="muted">{len(items)} 个会话</span></div>
          <div class="card list-card">{''.join(rows)}</div>
        </section>""")
    body = f"""
    <div class="page-head"><div><h1>时间线</h1><p class="lede">按周回看你在追什么、什么时候换了问题。</p></div></div>
    {''.join(blocks) or '<div class="empty card">还没有会话。</div>'}
    """
    return _page("时间线", body, "timeline", conn, cfg)


def topics_index(conn: sqlite3.Connection, cfg: Config) -> str:
    topics = list_topics(conn)
    parents: dict[str, list] = {}
    for t in topics:
        parents.setdefault(t["parent"] or "未归类", []).append(t)
    blocks = []
    for parent, items in parents.items():
        cards = "".join(f"""
        <a class="topic-card" href="/topics/{t['id']}">
          <div class="topic-name">{e(t['name'])}</div>
          <div class="topic-meta">{t['n']} 个会话 · 最近 {e(_fmt_date(t['last_date']))}</div>
          <div class="topic-parent">{e(parent)}</div>
        </a>""" for t in items)
        blocks.append(f"""
        <section class="section">
          <div class="section-head"><h2>{e(parent)}</h2><span class="muted">{len(items)} 个线程</span></div>
          <div class="topic-grid">{cards}</div>
        </section>""")
    body = f"""
    <div class="page-head"><div><h1>主题</h1><p class="lede">分类不是目的；把同一问题跨会话串起来，才看得到变化。</p></div></div>
    {''.join(blocks) or '<div class="empty card">还没有主题。</div>'}
    """
    return _page("主题", body, "topics", conn, cfg)


def topic_detail(conn: sqlite3.Connection, cfg: Config, topic_id: int) -> str:
    t = get_topic(conn, topic_id)
    if not t:
        return not_found_page(conn, cfg, "主题不存在")
    sessions = list_sessions(conn, limit=200, topic_id=topic_id)
    rows = []
    for s in sessions:
        p = card_payload(conn, s["id"], verified_only=False) or {}
        rows.append(f"""
        <a class="session-row" href="/sessions/{e(s['id'])}">
          <div class="session-date">{e(_fmt_date(s['local_date']))}</div>
          <div class="session-main">
            <div class="session-title">{e(s['title'])}</div>
            <div class="session-summary">{e(truncate(p.get('summary') or '', 220))}</div>
            <div class="chips">{_topic_chips(p.get('topics') or [])}</div>
          </div>
        </a>""")
    body = f"""
    <div class="page-head">
      <div><div class="eyebrow">{e(t['parent'] or '未归类')}</div><h1>{e(t['name'])}</h1><p class="lede">{len(sessions)} 个会话</p></div>
      <a class="btn" href="/topics">返回主题</a>
    </div>
    <div class="card list-card">{''.join(rows) or '<div class="empty">这个主题下还没有会话。</div>'}</div>
    """
    return _page(t["name"], body, "topics", conn, cfg)


def _render_transcript(conn: sqlite3.Connection, session_id: str, highlight: str | None, show_reasoning: bool) -> str:
    msgs = get_messages(conn, session_id, include_reasoning=show_reasoning, include_tools=True)
    rows = []
    for m in msgs:
        if m["kind"] == "tool_result" and not show_reasoning:
            continue
        mid = m["id"]
        anchor = message_anchor(mid)
        hl = " highlight" if highlight and (highlight == mid or highlight == anchor) else ""
        if m["role"] == "user":
            rows.append(f'<div id="{anchor}" class="msg user{hl}"><div class="msg-role">你</div><div class="msg-body">{e(m["content"])}</div></div>')
        elif m["kind"] == "text":
            rows.append(f'<div id="{anchor}" class="msg assistant{hl}"><div class="msg-role">AI</div><div class="msg-body">{e(m["content"])}</div></div>')
        elif m["kind"] == "reasoning":
            rows.append(f'<details id="{anchor}" class="msg tool{hl}"><summary>模型推理</summary><pre>{e(m["content"])}</pre></details>')
        elif m["kind"] == "tool_call":
            rows.append(f'<details id="{anchor}" class="msg tool{hl}"><summary>工具调用 · {e(m["tool_name"] or "tool")}</summary><pre>{e(m["content"])}</pre></details>')
        elif m["kind"] == "tool_result":
            rows.append(f'<details id="{anchor}" class="msg tool{hl}"><summary>工具输出 · {e(m["tool_name"] or "tool")}</summary><pre>{e(m["content"])}</pre></details>')
    return "".join(rows) or '<div class="empty">没有可显示的原文。</div>'


def session_detail(conn: sqlite3.Connection, cfg: Config, session_id: str, query: dict) -> str:
    s = get_session(conn, session_id)
    if not s:
        return not_found_page(conn, cfg, "会话不存在")
    p = card_payload(conn, session_id, verified_only=False) or {}
    highlight = (query.get("m") or [None])[0]
    show_reasoning = (query.get("reasoning") or ["0"])[0] == "1"

    topics = _topic_chips(p.get("topics") or [])
    signals = p.get("signals") or {}
    signal_blocks = []
    for key, label in [
        ("question_quality", "提问质量"),
        ("logic_language", "逻辑语言"),
        ("decision", "决策"),
        ("research", "研究方法"),
        ("cognition", "认知方式"),
        ("technical", "技术判断"),
    ]:
        items = signals.get(key) or []
        if not items:
            continue
        signal_blocks.append(f"""
        <div class="signal">
          <h3>{e(label)}</h3>
          {''.join(f'<div class="obs"><p>{e(x.get("observation") or "")}</p>{_quote_block(x)}</div>' for x in items)}
        </div>""")

    key_turns = "".join(f"""
      <div class="turn">
        <div class="turn-desc">{e(x.get('description') or '')}</div>
        {_quote_block(x)}
        <div class="muted small">{e(x.get('why_it_matters') or '')}</div>
      </div>""" for x in (p.get("key_turns") or []))

    self_html = "".join(f'<li>{e(x.get("statement") or "")}{_quote_block(x)}</li>' for x in (p.get("self_statements") or []))
    corr_html = "".join(f'<li><span class="muted">{e(x.get("from") or "")} →</span> {e(x.get("to") or "")}{_quote_block(x)}</li>' for x in (p.get("corrections") or []))
    commit_html = "".join(f'<li>{e(x.get("commitment") or "")} <span class="badge">{e(x.get("status") or "unknown")}</span>{_quote_block(x)}</li>' for x in (p.get("commitments") or []))
    loops_html = "".join(f"<li>{e(x)}</li>" for x in (p.get("open_loops") or []))

    card_html = f"""
    <section class="card card-pad">
      <div class="eyebrow">会话卡</div>
      <h2>这段对话在思考什么</h2>
      <p class="summary">{e(p.get('summary') or '尚未生成会话卡。')}</p>
      <div class="kv"><span>目标</span><p>{e(p.get('goal') or '—')}</p></div>
      <div class="chips">{topics}</div>
    </section>
    {f'<section class="section"><div class="section-head"><h2>关键转折</h2></div>{key_turns}</section>' if key_turns else ''}
    {f'<section class="section"><div class="section-head"><h2>思维信号</h2></div>{''.join(signal_blocks)}</section>' if signal_blocks else ''}
    {f'<section class="section two-col"><div class="card"><h3>自我描述</h3><ul class="clean">{self_html}</ul></div><div class="card"><h3>修正</h3><ul class="clean">{corr_html or "<li class='muted'>暂无</li>"}</ul></div></section>' if self_html or corr_html else ''}
    {f'<section class="section"><div class="card"><h3>承诺与未闭环</h3><ul class="clean">{commit_html}{loops_html}</ul></div></section>' if commit_html or loops_html else ''}
    """

    body = f"""
    <div class="page-head">
      <div>
        <div class="eyebrow">{e(s['local_date'])} · {e(s['model'] or '')}</div>
        <h1>{e(s['title'])}</h1>
        <div class="meta-line">{s['message_count']} 条消息 · {s['user_chars']} 字用户输入 · {e(s['iso_week'] or '')}</div>
      </div>
      <a class="btn" href="/timeline">返回时间线</a>
    </div>
    {card_html}
    <section class="section">
      <div class="section-head"><h2>对话原文</h2><span class="muted">{s['message_count']} 条</span></div>
      <div class="card transcript">{_render_transcript(conn, session_id, highlight, show_reasoning)}</div>
    </section>
    """
    return _page(s["title"], body, "timeline", conn, cfg)


def growth_page(conn: sqlite3.Connection, cfg: Config) -> str:
    latest = _latest_report(conn)
    data = _read_json(latest["json_path"]) if latest else {}
    series = observation_series(conn)
    dim_cards = []
    for dim in DIM_LABELS:
        rows = series.get(dim, [])
        cur = rows[-1] if rows else None
        values = [r["score"] for r in rows]
        ev = []
        if cur and cur["evidence_json"]:
            try:
                ev = json.loads(cur["evidence_json"]) or []
            except Exception:
                ev = []
        dim_cards.append(f"""
        <section class="card dim-detail">
          <div class="dim-head"><h2>{e(dim)}</h2><span class="dim-score">{_score_label(cur['score'] if cur else None)}</span></div>
          <div class="dim-meta">置信度 {e(_conf_label(cur['confidence'] if cur else 'low'))} · {len(rows)} 个观察点</div>
          {svg_spark(values, width=260, height=56)}
          <p>{e(cur['rationale'] if cur else '还没有足够证据，继续积累。')}</p>
          {''.join(_quote_block(x) for x in ev[:3])}
          <p class="muted small">反例/保留：{e(cur['counter_evidence'] if cur else '—')}</p>
        </section>""")

    report_list = list_reports(conn, limit=20)
    report_rows = []
    for r in report_list:
        report_rows.append(f'<a class="report-row" href="/reports/{e(r["kind"])}/{e(r["period_start"])}"><span class="badge">{e(r["kind"])}</span><span>{e(r["title"])}</span><span class="muted">{e(r["period_start"])}</span></a>')

    body = f"""
    <div class="page-head"><div><div class="eyebrow">双周观察</div><h1>成长</h1><p class="lede">分数只是索引；证据和反例才是主体。证据不足时，允许“观察中”。</p></div></div>
    {f'<section class="card soft"><div class="eyebrow">{e(latest["title"])}</div><p>{e(data.get("period_summary") or "")}</p><a class="text-link" href="/reports/{e(latest["kind"])}/{e(latest["period_start"])}">读完整报告 →</a></section>' if latest else '<div class="empty card">还没有基线或成长报告。</div>'}
    <section class="grid detail">{''.join(dim_cards)}</section>
    <section class="section"><div class="section-head"><h2>报告</h2></div><div class="card list-card">{''.join(report_rows) or '<div class="empty">还没有报告。</div>'}</div></section>
    """
    return _page("成长", body, "growth", conn, cfg)


def insights_page(conn: sqlite3.Connection, cfg: Config, status: str | None = None) -> str:
    all_rows = list_insights(conn, None)
    counts = {
        "pending": sum(1 for r in all_rows if r["status"] == "pending"),
        "accepted": sum(1 for r in all_rows if r["status"] == "accepted"),
        "rejected": sum(1 for r in all_rows if r["status"] == "rejected"),
    }
    rows = [r for r in all_rows if r["status"] == status] if status else all_rows

    kind_label = {
        "pattern": "模式",
        "strength": "优势",
        "blind_spot": "盲点",
        "value": "价值排序",
        "question_style": "提问风格",
        "note": "修正/备注",
    }
    status_label = {"pending": "待确认", "accepted": "已确认", "rejected": "已驳回"}
    verdict_label = {
        "confirmed": "本期仍成立",
        "weakened": "本期减弱",
        "contradicted": "本期出现反例",
        "insufficient": "本期证据不足",
        "revisit": "值得重看",
        "user_correction": "来源修正",
    }

    def card_html(r) -> str:
        try:
            ev = json.loads(r["evidence_json"] or "[]")
        except Exception:
            ev = []
        k = kind_label.get(r["kind"], r["kind"] or "观察")
        badges = f'<span class="badge">{e(k)}</span><span class="badge">{e(status_label.get(r["status"], r["status"]))}</span>'
        if r["last_verdict"]:
            badges += f'<span class="badge badge-weekly">{e(verdict_label.get(r["last_verdict"], r["last_verdict"]))}</span>'
        original = ""
        if r["kind"] == "note" and r["original_statement"]:
            original = f'<div class="muted small" style="margin:-4px 0 8px">原判断：{e(r["original_statement"])}</div>'
        note_hint = ""
        if r["kind"] == "note":
            note_hint = '<div class="muted small" style="margin-top:8px">这是来源/归属修正，不会作为自我认知特质使用。</div>'
        elif r["status"] == "accepted":
            note_hint = '<div class="muted small" style="margin-top:8px">已进入 L4 档案；下一次成长报告会逐条复核它是否仍成立。</div>'

        if r["status"] == "pending":
            actions = f"""
            <form class="inline" method="post" action="/insights/{r['id']}/status">
              <input type="hidden" name="status" value="accepted"><button class="btn primary" type="submit">接受</button>
            </form>
            <form class="inline" method="post" action="/insights/{r['id']}/status">
              <input type="hidden" name="status" value="rejected"><button class="btn" type="submit">驳回</button>
            </form>"""
        elif r["status"] == "accepted":
            actions = f"""
            <form class="inline" method="post" action="/insights/{r['id']}/status">
              <input type="hidden" name="status" value="pending"><button class="btn" type="submit">改回待确认</button>
            </form>
            <form class="inline" method="post" action="/insights/{r['id']}/status">
              <input type="hidden" name="status" value="rejected"><button class="btn" type="submit">驳回</button>
            </form>"""
        else:
            actions = f"""
            <form class="inline" method="post" action="/insights/{r['id']}/status">
              <input type="hidden" name="status" value="pending"><button class="btn" type="submit">改回待确认</button>
            </form>
            <form class="inline" method="post" action="/insights/{r['id']}/status">
              <input type="hidden" name="status" value="accepted"><button class="btn primary" type="submit">接受</button>
            </form>"""
        actions += f"""
        <details class="edit"><summary>改写</summary>
          <form method="post" action="/insights/{r['id']}/status">
            <input type="hidden" name="status" value="accepted">
            <textarea name="statement" rows="3">{e(r['statement'])}</textarea>
            <button class="btn primary" type="submit">保存并接受</button>
          </form>
        </details>"""
        return f"""
        <article class="card insight">
          <div class="insight-head">{badges}<span class="muted">置信度 {e(_conf_label(r['confidence']))} · 出现 {r['times_seen']} 次</span></div>
          <h2>{e(r['statement'])}</h2>
          {original}
          {''.join(_quote_block(x) for x in ev[:3])}
          {note_hint}
          <div class="actions">{actions}</div>
        </article>"""

    if status == "accepted":
        traits = [r for r in rows if r["kind"] != "note"]
        notes = [r for r in rows if r["kind"] == "note"]
        sections = [("已确认的自我认知", traits), ("你的修正", notes)]
    elif status is None:
        sections = [
            ("待确认", [r for r in rows if r["status"] == "pending"]),
            ("已确认的自我认知", [r for r in rows if r["status"] == "accepted" and r["kind"] != "note"]),
            ("你的修正", [r for r in rows if r["status"] == "accepted" and r["kind"] == "note"]),
            ("已驳回", [r for r in rows if r["status"] == "rejected"]),
        ]
    else:
        sections = [("", rows)]

    section_html = []
    for title, items in sections:
        if not items:
            continue
        if title:
            section_html.append(f'<div class="section-head" style="margin-top:26px"><h2>{e(title)}</h2><span class="muted">{len(items)} 条</span></div>')
        section_html.append("".join(card_html(r) for r in items))

    tabs = [
        ("pending", "待确认", counts["pending"]),
        ("accepted", "已确认", counts["accepted"]),
        ("rejected", "已驳回", counts["rejected"]),
        (None, "全部", len(all_rows)),
    ]
    tab_html = "".join(
        f'<a class="tab {"active" if (status or None) == k else ""}" href="/insights{("?status=" + k) if k else ""}">{label} {n}</a>'
        for k, label, n in tabs
    )

    archive_note = ""
    if counts["accepted"] or counts["rejected"]:
        accepted_traits = sum(1 for r in all_rows if r["status"] == "accepted" and r["kind"] != "note")
        note_count = sum(1 for r in all_rows if r["kind"] == "note")
        l4_row = conn.execute(
            "SELECT * FROM reports WHERE kind='l4' ORDER BY period_start DESC LIMIT 1"
        ).fetchone()
        l4_link = f' · <a class="text-link" href="/reports/l4/{e(l4_row["period_start"])}">查看 L4 档案</a>' if l4_row else ""
        archive_note = f"""
        <section class="card soft" style="margin-bottom:18px">
          <div class="eyebrow">L4 档案</div>
          <p>已确认 {accepted_traits} 条、修正 {note_count} 条、驳回 {counts['rejected']} 条。已确认的判断会在每次成长报告里逐条复核；修正只用于纠正来源/归属，不作为你的特质。{l4_link}</p>
        </section>"""

    body = f"""
    <div class="page-head"><div><div class="eyebrow">L4 · 候选自我认知</div><h1>洞察</h1><p class="lede">AI 起草的假设，不是定论。接受、改写或驳回；你的判断优先。</p></div></div>
    {archive_note}
    <div class="tabs">{tab_html}</div>
    {''.join(section_html) or '<div class="empty card">还没有候选洞察。基线或双周报告生成后会出现在这里。</div>'}
    """
    return _page("洞察", body, "insights", conn, cfg)


def reports_page(conn: sqlite3.Connection, cfg: Config) -> str:
    rows = list_reports(conn, limit=100)
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["kind"], []).append(r)
    labels = {"weekly": "周报", "growth": "成长报告", "baseline": "基线画像", "l4": "L4 档案"}
    blocks = []
    for kind in ["weekly", "l4", "growth", "baseline"]:
        items = groups.get(kind) or []
        if not items:
            continue
        links = "".join(
            f'<a class="report-row" href="/reports/{e(r["kind"])}/{e(r["period_start"])}"><span>{e(r["title"])}</span><span class="muted">{e(r["period_start"])}</span></a>'
            for r in items
        )
        blocks.append(f'<section class="section"><div class="section-head"><h2>{labels.get(kind, kind)}</h2></div><div class="card list-card">{links}</div></section>')
    body = f"""
    <div class="page-head"><div><h1>报告</h1><p class="lede">周报是原料，成长报告做纵向对比。所有报告都以 Markdown 存在 D 盘。</p></div></div>
    {''.join(blocks) or '<div class="empty card">还没有报告。</div>'}
    """
    return _page("报告", body, "reports", conn, cfg)


def report_view(conn: sqlite3.Connection, cfg: Config, kind: str, period_start: str) -> str:
    r = get_report(conn, kind, period_start)
    if not r:
        return not_found_page(conn, cfg, "报告不存在")
    try:
        md = Path(r["path"]).read_text(encoding="utf-8")
    except Exception:
        md = "报告文件丢失。"
    # The page header already shows the title; drop the duplicate H1 in the body.
    if md.startswith("# "):
        md = md.split("\n", 1)[1].lstrip("\n") if "\n" in md else ""
    body = f"""
    <div class="page-head">
      <div><div class="eyebrow">{e(kind)} · {e(r['period_start'])}</div><h1>{e(r['title'])}</h1></div>
      <a class="btn" href="/reports">返回报告</a>
    </div>
    <article class="card card-pad prose report-body">{md_to_html(md)}</article>
    """
    return _page(r["title"], body, "reports", conn, cfg)


def search_page(conn: sqlite3.Connection, cfg: Config, q: str) -> str:
    rows = search(conn, q, limit=60) if q else []
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["session_id"], []).append(r)
    blocks = []
    for sid, items in groups.items():
        s = get_session(conn, sid)
        if not s:
            continue
        snippets = []
        for r in items[:4]:
            text = r["content"] or ""
            idx = text.lower().find(q.lower()) if q else -1
            if idx >= 0:
                start = max(0, idx - 80)
                snippet = ("…" if start else "") + text[start:start + 220] + ("…" if start + 220 < len(text) else "")
            else:
                snippet = truncate(text, 220)
            safe = e(snippet)
            if q:
                safe = safe.replace(e(q), f"<mark>{e(q)}</mark>")
            snippets.append(f'<div class="snippet"><span class="role">{e(r["role"])}</span>{safe}</div>')
        blocks.append(f"""
        <div class="card search-result">
          <a class="session-title" href="/sessions/{e(sid)}">{e(s['title'])}</a>
          <div class="muted small">{e(s['local_date'])} · {len(items)} 条命中</div>
          {''.join(snippets)}
        </div>""")
    body = f"""
    <div class="page-head"><div><h1>搜索</h1><p class="lede">{f'“{e(q)}” 的 {len(rows)} 条结果' if q else '输入关键词搜索全部原文。'}</p></div></div>
    {''.join(blocks) or ('<div class="empty card">没有找到。试试更短的关键词。</div>' if q else '')}
    """
    return _page("搜索", body, "", conn, cfg, q=q)


def not_found_page(conn: sqlite3.Connection, cfg: Config, msg: str = "页面不存在") -> str:
    body = f'<div class="empty card"><h1>{e(msg)}</h1><p><a class="text-link" href="/">回到概览</a></p></div>'
    return _page(msg, body, "", conn, cfg)


def api_summary(conn: sqlite3.Connection) -> dict:
    s = stats(conn)
    weekly = _latest_report(conn, "weekly")
    wd = _read_json(weekly["json_path"]) if weekly else {}
    growth = _latest_report(conn)
    gd = _read_json(growth["json_path"]) if growth else {}
    l4 = conn.execute(
        "SELECT * FROM reports WHERE kind='l4' ORDER BY period_start DESC LIMIT 1"
    ).fetchone()
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": s,
        "latest_weekly": {
            "title": weekly["title"] if weekly else None,
            "period_start": weekly["period_start"] if weekly else None,
            "one_line": wd.get("one_line"),
            "next_experiment": wd.get("next_experiment"),
        } if weekly else None,
        "latest_growth": {
            "title": growth["title"] if growth else None,
            "kind": growth["kind"] if growth else None,
            "period_start": growth["period_start"] if growth else None,
            "summary": gd.get("period_summary"),
            "dimensions": {k: (v or {}).get("score") for k, v in (gd.get("dimensions") or {}).items()},
        } if growth else None,
        "latest_l4": {
            "title": l4["title"] if l4 else None,
            "period_start": l4["period_start"] if l4 else None,
        } if l4 else None,
        "pending_insights": s.get("pending_insights", 0),
    }


class Handler(BaseHTTPRequestHandler):
    cfg: Config
    server_version = "dsh-journal/0.1"

    def log_message(self, fmt, *args):
        print(f"[web] {self.address_string()} {fmt % args}")

    def _conn(self) -> sqlite3.Connection:
        return connect(self.cfg)

    def _send(self, body: bytes, status: int = 200, ctype: str = "text/html; charset=utf-8", extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html_text: str, status: int = 200):
        self._send(html_text.encode("utf-8"), status)

    def _redirect(self, location: str):
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        conn = self._conn()
        try:
            if path == "/static/style.css":
                p = self.cfg.static_dir / "style.css"
                self._send(p.read_bytes(), ctype="text/css; charset=utf-8")
                return
            if path == "/static/app.js":
                p = self.cfg.static_dir / "app.js"
                if p.exists():
                    self._send(p.read_bytes(), ctype="application/javascript; charset=utf-8")
                    return
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if path == "/api/summary":
                self._send(json.dumps(api_summary(conn), ensure_ascii=False).encode("utf-8"),
                           ctype="application/json; charset=utf-8",
                           extra={"Access-Control-Allow-Origin": "*"})
                return
            if path == "/":
                self._html(dashboard(conn, self.cfg)); return
            if path == "/timeline":
                self._html(timeline(conn, self.cfg)); return
            if path == "/topics":
                self._html(topics_index(conn, self.cfg)); return
            if path.startswith("/topics/"):
                try:
                    tid = int(path.split("/")[2])
                except Exception:
                    self._html(not_found_page(conn, self.cfg, "主题不存在"), 404); return
                self._html(topic_detail(conn, self.cfg, tid)); return
            if path.startswith("/sessions/"):
                sid = path.split("/", 2)[2]
                self._html(session_detail(conn, self.cfg, sid, query)); return
            if path == "/growth":
                self._html(growth_page(conn, self.cfg)); return
            if path == "/insights":
                status = (query.get("status") or [None])[0]
                self._html(insights_page(conn, self.cfg, status)); return
            if path == "/reports":
                self._html(reports_page(conn, self.cfg)); return
            if path.startswith("/reports/"):
                parts = path.split("/")
                if len(parts) >= 4:
                    kind, period = parts[2], parts[3]
                    self._html(report_view(conn, self.cfg, kind, period)); return
            if path == "/search":
                q = (query.get("q") or [""])[0].strip()
                self._html(search_page(conn, self.cfg, q)); return
            self._html(not_found_page(conn, self.cfg), 404)
        finally:
            conn.close()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        form = parse_qs(body)
        conn = self._conn()
        try:
            if path.startswith("/insights/") and path.endswith("/status"):
                try:
                    iid = int(path.split("/")[2])
                except Exception:
                    self._redirect("/insights"); return
                status = (form.get("status") or ["pending"])[0]
                if status not in ("pending", "accepted", "rejected"):
                    status = "pending"
                statement = (form.get("statement") or [""])[0].strip()
                if statement:
                    import hashlib
                    row = conn.execute("SELECT kind, statement, original_statement FROM insights WHERE id=?", (iid,)).fetchone()
                    kind = row["kind"] if row else "pattern"
                    original = (row["original_statement"] if row else None) or (row["statement"] if row else None)
                    fp = hashlib.sha256((kind + "|" + statement).encode("utf-8")).hexdigest()
                    conn.execute(
                        "UPDATE insights SET statement=?, original_statement=COALESCE(original_statement, ?), fingerprint=?, status=?, updated_at_ms=? WHERE id=?",
                        (statement, original, fp, status, int(time.time() * 1000), iid),
                    )
                else:
                    set_insight_status(conn, iid, status)
                conn.commit()
                # Keep the exportable L4 archive in sync with one-click decisions.
                try:
                    from .l4 import generate_l4
                    generate_l4(self.cfg, conn)
                except Exception:
                    pass
                self._redirect("/insights?status=" + status)
                return
            self._redirect("/")
        finally:
            conn.close()


def _web_log(cfg: Config, message: str) -> None:
    try:
        cfg.logs_dir.mkdir(parents=True, exist_ok=True)
        with (cfg.logs_dir / "web.log").open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {message}\n")
    except Exception:
        pass


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765):
    cfg.ensure_dirs()
    conn = connect(cfg)
    init_db(conn)
    conn.close()
    Handler.cfg = cfg
    _web_log(cfg, f"starting http://{host}:{port}")
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except Exception as e:
        import traceback
        _web_log(cfg, f"failed: {e}\n{traceback.format_exc()}")
        raise
    print(f"思维年轮已启动：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _web_log(cfg, "stopped")
        server.server_close()


if __name__ == "__main__":
    serve(Config.load())
