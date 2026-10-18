from __future__ import annotations

from urllib.parse import quote

from .util import one_line, truncate


DIM_LABELS = {
    "技术判断力": "技术判断力",
    "决策质量": "决策质量",
    "研究方法": "研究方法",
    "逻辑语言能力": "逻辑语言能力",
    "思维认知方式": "思维认知方式",
}


def _session_index(cards: list[dict]) -> dict[str, dict]:
    return {c.get("session_id"): c for c in cards if c.get("session_id")}


def _session_link(sid: str | None, cards: list[dict], text: str | None = None) -> str:
    if not sid:
        return text or ""
    c = _session_index(cards).get(sid) or {}
    label = text or c.get("title") or sid
    return f"[{label}](/sessions/{sid})"


def _evidence_link(ev: dict, cards: list[dict]) -> str:
    sid = ev.get("session_id")
    mid = ev.get("message_id")
    if not sid:
        return ""
    if mid:
        return f"[原话](/sessions/{sid}?m={quote(str(mid))})"
    return _session_link(sid, cards, "原话")


def _quote_block(ev: dict, cards: list[dict]) -> str:
    q = (ev.get("quote") or "").strip()
    if not q:
        return ""
    lines = q.splitlines() or [q]
    body = "\n".join("> " + line for line in lines)
    return body + "\n>\n> — " + _evidence_link(ev, cards)


def _evidence_list(evs: list[dict], cards: list[dict], limit: int = 3) -> str:
    out = []
    for ev in (evs or [])[:limit]:
        b = _quote_block(ev, cards)
        if b:
            out.append(b)
    return "\n\n".join(out)


def _score_text(d: dict, baseline: bool) -> str:
    if baseline:
        return "观察中（基线不打分）"
    score = d.get("score")
    if score is None:
        return "观察中（证据不足）"
    conf = {"low": "低", "medium": "中", "high": "高"}.get(str(d.get("confidence")), str(d.get("confidence") or "低"))
    return f"{score:g}/5（置信度：{conf}）"


def render_growth_md(data: dict, *, title: str, baseline: bool) -> str:
    cards = data.get("cards") or []
    period = data.get("period") or {}
    out: list[str] = []
    out.append(f"# {title}\n")
    out.append(f"> 期间：{period.get('start', '')} 至 {period.get('end', '')} ｜ 会话：{len(cards)} ｜ 模式：{'基线画像' if baseline else '双周成长复盘'}\n")
    if baseline:
        out.append("> 这是第一次全量回看，只建立起点，不构成成长结论。第 2 周末出第一份真正的成长报告；满 3 个点（6 周）才标“趋势”。\n")

    out.append("## 本期概览\n")
    out.append((data.get("period_summary") or "暂无概览。").strip() + "\n")

    out.append("## 五维画像\n")
    for name in DIM_LABELS:
        d = (data.get("dimensions") or {}).get(name) or {}
        out.append(f"### {name}\n")
        out.append(f"**状态**：{_score_text(d, baseline)}  \n")
        if d.get("rationale"):
            out.append(f"**判断**：{d['rationale']}  \n")
        ev = _evidence_list(d.get("evidence") or [], cards)
        if ev:
            out.append(ev + "\n")
        if d.get("counter_evidence"):
            out.append(f"**反例/保留**：{d['counter_evidence']}  \n")
        if not baseline and d.get("change"):
            change = d["change"]
            if change == "no_baseline":
                change = "首次基线，暂不比较"
            out.append(f"**变化**：{change}  \n")
        out.append("")

    patterns = data.get("recurring_patterns") or []
    if patterns:
        out.append("## 重复出现的模式\n")
        for p in patterns:
            occ = f"（出现 {p.get('occurrences')} 次）" if p.get("occurrences") else ""
            out.append(f"### {p.get('pattern', '')}{occ}\n")
            q = _evidence_list(p.get("evidence") or [], cards, limit=2)
            if q:
                out.append(q + "\n")

    updates = data.get("insight_updates") or []
    if updates:
        out.append("## 已确认认知的复核\n")
        out.append("> 这些是你在「洞察」页确认过的自我认知；这一期逐条复核，允许减弱或出现反例。\n")
        verdict_label = {
            "confirmed": "仍成立",
            "weakened": "减弱",
            "contradicted": "出现反例",
            "insufficient": "证据不足",
            "revisit": "值得重看",
        }
        for u in updates:
            label = verdict_label.get(u.get("verdict"), u.get("verdict") or "")
            out.append(f"### [{label}] {u.get('statement', '')}\n")
            if u.get("note"):
                out.append(u["note"] + "\n")
            q = _evidence_list(u.get("evidence") or [], cards, limit=2)
            if q:
                out.append(q + "\n")

    gaps = data.get("gaps") or []
    if gaps:
        out.append("## 言行差距\n")
        for g in gaps:
            out.append(f"- **说的**：{g.get('stated', '')}")
            out.append(f"  **做的/没做的**：{g.get('enacted', '')}")
            q = _evidence_list(g.get("evidence") or [], cards, limit=1)
            if q:
                out.append("\n" + q + "\n")

    insights = data.get("insights") or []
    if insights:
        out.append("## 候选自我认知（待确认）\n")
        out.append("> 这些是 AI 从对话里起草的假设，不是定论。到网页「洞察」页一键接受、改写或驳回；接受后会进入你的自我认知档案。\n")
        kind_label = {
            "pattern": "模式",
            "strength": "优势",
            "blind_spot": "盲点",
            "value": "价值排序",
            "question_style": "提问风格",
        }
        for ins in insights:
            k = kind_label.get(ins.get("kind"), ins.get("kind") or "观察")
            conf = {"low": "低", "medium": "中", "high": "高"}.get(str(ins.get("confidence")), "低")
            out.append(f"### [{k}] {ins.get('statement', '')}\n")
            out.append(f"置信度：{conf}  \n")
            q = _evidence_list(ins.get("evidence") or [], cards, limit=2)
            if q:
                out.append(q + "\n")

    exp = data.get("experiment") or {}
    if exp:
        out.append("## 下两周一个实验\n")
        out.append(f"**{exp.get('title', '')}**\n")
        if exp.get("why"):
            out.append(f"- 为什么：{exp['why']}")
        if exp.get("how"):
            out.append(f"- 怎么做：{exp['how']}")
        if exp.get("done_when"):
            out.append(f"- 算完成：{exp['done_when']}")
        out.append("")

    old = data.get("old_dialogue") or {}
    if old and old.get("session_id"):
        out.append("## 旧对话对照\n")
        out.append(f"**当时**：{old.get('then', '')}\n")
        out.append(f"**现在**：{old.get('now', '')}\n")
        out.append(f"**变化**：{old.get('what_changed', '')}\n")
        out.append(f"来源：{_session_link(old.get('session_id'), cards)}\n")

    out.append("## 数据附录\n")
    out.append(f"- 会话数：{len(cards)}")
    out.append(f"- 覆盖日期：{period.get('start', '')} 至 {period.get('end', '')}")
    out.append("- 所有引用均可点击回到原会话；未通过原文校验的引用已自动剔除。")
    out.append("")
    return "\n".join(out)


def render_weekly_md(data: dict, *, title: str, cards: list[dict], period: dict) -> str:
    out: list[str] = []
    out.append(f"# {title}\n")
    out.append(f"> 期间：{period.get('start', '')} 至 {period.get('end', '')} ｜ 会话：{len(cards)}\n")

    out.append("## 一句话\n")
    out.append("> " + (data.get("one_line") or "本周暂无概括。") + "\n")

    threads = data.get("threads") or []
    if threads:
        out.append("## 在追的线\n")
        for t in threads:
            out.append(f"### {t.get('topic', '')}\n")
            if t.get("summary"):
                out.append(t["summary"] + "\n")
            sids = t.get("session_ids") or []
            if sids:
                out.append("来源：" + "、".join(_session_link(s, cards) for s in sids) + "\n")

    turns = data.get("turns") or []
    if turns:
        out.append("## 关键转折\n")
        for t in turns:
            out.append(f"### {t.get('description', '')}\n")
            q = _quote_block({"quote": t.get("quote"), "session_id": t.get("session_id"), "message_id": t.get("message_id")}, cards)
            if q:
                out.append(q + "\n")
            if t.get("why"):
                out.append(f"为什么关键：{t['why']}\n")

    loops = data.get("open_loops") or []
    if loops:
        out.append("## 未闭环\n")
        for x in loops:
            out.append(f"- {x}")
        out.append("")

    le = data.get("last_experiment") or {}
    if le:
        status = {"done": "完成", "partial": "部分完成", "not_done": "没做", "none": "无"}.get(le.get("status"), le.get("status") or "无")
        out.append("## 上周实验\n")
        out.append(f"**状态**：{status}  \n")
        if le.get("evidence"):
            out.append(f"**证据**：{le['evidence']}  \n")
        out.append("")

    lb = data.get("lookback") or {}
    if lb.get("quote"):
        out.append("## 值得回看的一段\n")
        out.append(_quote_block(lb, cards) + "\n")
        if lb.get("why"):
            out.append(f"为什么选它：{lb['why']}\n")

    ne = data.get("next_experiment") or {}
    if ne:
        out.append("## 下周一个实验\n")
        out.append(f"**{ne.get('title', '')}**\n")
        if ne.get("how"):
            out.append(f"- 怎么做：{ne['how']}")
        if ne.get("done_when"):
            out.append(f"- 算完成：{ne['done_when']}")
        out.append("")

    out.append("## 数据附录\n")
    out.append(f"- 会话数：{len(cards)}")
    out.append("- 引用可点击回到原会话；未通过原文校验的引用已自动剔除。")
    out.append("")
    return "\n".join(out)
