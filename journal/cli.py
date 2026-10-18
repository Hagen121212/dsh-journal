from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta

from .cards import generate_pending_cards
from .config import Config
from .db import (
    connect,
    finish_run,
    get_report,
    init_db,
    last_run,
    list_reports,
    session_weeks,
    start_run,
    stats,
)
from .growth import generate_growth
from .ingest import sync
from .l4 import generate_l4
from .llm import BudgetExceeded, LLM
from .util import TZ, iso_week, now_ms
from .weekly import generate_weekly


def _today() -> date:
    return datetime.now(tz=TZ).date()


def _baseline_range(conn) -> tuple[str, str] | None:
    s = stats(conn)
    if not s["first_date"] or not s["last_date"]:
        return None
    return s["first_date"], s["last_date"]


def _growth_window(conn, cfg: Config) -> tuple[str, str] | None:
    last = conn.execute(
        "SELECT * FROM reports WHERE kind IN ('baseline','growth') ORDER BY period_start DESC, generated_at_ms DESC LIMIT 1"
    ).fetchone()
    if not last:
        return None
    try:
        last_end = date.fromisoformat(last["period_end"])
    except Exception:
        return None
    today = _today()
    # The scheduler runs on Sundays. A 14-day interval would drift to every
    # third Sunday (13 days on the second Sunday), so allow one day of slack.
    if (today - last_end).days < max(1, cfg.growth_interval_days - 1):
        return None
    start = last_end + timedelta(days=1)
    return start.isoformat(), today.isoformat()


def _run_baseline(cfg, conn, llm, force=False) -> dict:
    rng = _baseline_range(conn)
    if not rng:
        return {"skipped": True, "reason": "no_sessions"}
    existing = conn.execute("SELECT id FROM reports WHERE kind='baseline' LIMIT 1").fetchone()
    if existing and not force:
        return {"skipped": True, "reason": "exists"}
    data = generate_growth(cfg, conn, llm, period_start=rng[0], period_end=rng[1], baseline=True)
    return {"ok": True, "period": rng}


def cmd_sync(cfg, conn, args) -> dict:
    return sync(cfg, conn, force=args.force, limit=args.limit)


def cmd_cards(cfg, conn, args) -> dict:
    llm = LLM(cfg)
    out = generate_pending_cards(cfg, conn, llm, limit=args.limit, force=args.force)
    out["usage"] = llm.usage_summary()
    return out


def cmd_baseline(cfg, conn, args) -> dict:
    llm = LLM(cfg)
    out = _run_baseline(cfg, conn, llm, force=getattr(args, "force", False))
    out["usage"] = llm.usage_summary()
    return out


def cmd_growth(cfg, conn, args) -> dict:
    llm = LLM(cfg)
    if args.baseline:
        return cmd_baseline(cfg, conn, args)
    if args.start and args.end:
        start, end = args.start, args.end
    else:
        win = _growth_window(conn, cfg)
        if not win:
            return {"skipped": True, "reason": "not_due_or_no_baseline"}
        start, end = win
    from .cards import cards_for_period
    if not cards_for_period(conn, start, end):
        return {"skipped": True, "reason": "no_cards", "period": [start, end]}
    data = generate_growth(cfg, conn, llm, period_start=start, period_end=end, baseline=False)
    return {"ok": True, "period": [start, end], "usage": llm.usage_summary(), "summary": data.get("period_summary")}


def cmd_weekly(cfg, conn, args) -> dict:
    llm = LLM(cfg)
    out: dict = {}
    out["sync"] = sync(cfg, conn, force=False)
    out["cards"] = generate_pending_cards(cfg, conn, llm, limit=12)
    out["weekly"] = generate_weekly(cfg, conn, llm, date_str=args.date or _today().isoformat(), force=args.force)
    if not args.no_growth:
        win = _growth_window(conn, cfg)
        if win:
            from .cards import cards_for_period
            if not cards_for_period(conn, win[0], win[1]):
                out["growth"] = {"skipped": True, "reason": "no_cards", "period": win}
            else:
                data = generate_growth(cfg, conn, llm, period_start=win[0], period_end=win[1], baseline=False)
                out["growth"] = {"ok": True, "period": win, "summary": data.get("period_summary")}
        else:
            out["growth"] = {"skipped": True, "reason": "not_due"}
    out["usage"] = llm.usage_summary()
    return out


def cmd_backfill(cfg, conn, args) -> dict:
    llm = LLM(cfg)
    out: dict = {}
    out["sync"] = sync(cfg, conn, force=args.force)
    out["cards"] = generate_pending_cards(cfg, conn, llm, force=args.force)
    out["baseline"] = _run_baseline(cfg, conn, llm, force=args.force)

    # Retrospective weekly reports for completed weeks, oldest first.
    current = iso_week(now_ms())
    weeks = [r for r in session_weeks(conn) if r["iso_week"] and r["iso_week"] != current]
    weekly_results = []
    for w in reversed(weeks):
        try:
            weekly_results.append(generate_weekly(cfg, conn, llm, date_str=w["start"], force=args.force))
        except BudgetExceeded:
            weekly_results.append({"skipped": True, "reason": "budget"})
            break
        except Exception as e:
            weekly_results.append({"error": str(e), "week": w["iso_week"]})
    out["weekly"] = weekly_results
    out["usage"] = llm.usage_summary()
    return out


def cmd_l4(cfg, conn, args) -> dict:
    return generate_l4(cfg, conn, args.date)


def cmd_status(cfg, conn, args) -> dict:
    s = stats(conn)
    reports = [
        {"kind": r["kind"], "title": r["title"], "period_start": r["period_start"], "path": r["path"]}
        for r in list_reports(conn, limit=20)
    ]
    run = last_run(conn)
    return {
        "home": str(cfg.home),
        "db": str(cfg.db_path),
        "stats": s,
        "reports": reports,
        "last_run": dict(run) if run else None,
    }


def cmd_serve(cfg, conn, args) -> dict:
    from .web import serve
    serve(cfg, host=args.host, port=args.port)
    return {"ok": True}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="journal", description="思维年轮 · DeepSeek 聊天复盘")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("sync", help="同步 DSH 会话")
    q.add_argument("--force", action="store_true")
    q.add_argument("--limit", type=int)

    q = sub.add_parser("cards", help="生成会话卡")
    q.add_argument("--force", action="store_true")
    q.add_argument("--limit", type=int)

    q = sub.add_parser("baseline", help="生成基线画像")
    q.add_argument("--force", action="store_true")
    q.set_defaults(baseline=True)

    q = sub.add_parser("growth", help="生成双周成长报告")
    q.add_argument("--start")
    q.add_argument("--end")
    q.add_argument("--baseline", action="store_true")

    q = sub.add_parser("weekly", help="每周任务：同步、卡片、周报、按需成长报告")
    q.add_argument("--date", help="YYYY-MM-DD，默认今天")
    q.add_argument("--force", action="store_true")
    q.add_argument("--no-growth", action="store_true")

    q = sub.add_parser("backfill", help="首次全量回填 + 基线 + 历史周报")
    q.add_argument("--force", action="store_true")

    q = sub.add_parser("serve", help="启动本地网页")
    q.add_argument("--host", default="127.0.0.1")
    q.add_argument("--port", type=int, default=8765)

    q = sub.add_parser("l4", help="导出 L4 自我认知档案")
    q.add_argument("--date", help="YYYY-MM-DD，默认今天")

    sub.add_parser("status", help="查看状态")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = Config.load()
    cfg.ensure_dirs()
    conn = connect(cfg)
    init_db(conn)
    # A process that died mid-run leaves a stale "running" row; age it out.
    conn.execute(
        "UPDATE runs SET status='error', error='stale (process ended)' "
        "WHERE status='running' AND finished_at_ms IS NULL AND started_at_ms < ?",
        (now_ms() - 6 * 3600 * 1000,),
    )
    conn.commit()
    kind = args.cmd
    run_id = None
    if kind not in ("status", "serve"):
        run_id = start_run(conn, kind)
    try:
        if kind == "sync":
            out = cmd_sync(cfg, conn, args)
        elif kind == "cards":
            out = cmd_cards(cfg, conn, args)
        elif kind == "baseline":
            out = cmd_baseline(cfg, conn, args)
        elif kind == "growth":
            out = cmd_growth(cfg, conn, args)
        elif kind == "weekly":
            out = cmd_weekly(cfg, conn, args)
        elif kind == "l4":
            out = cmd_l4(cfg, conn, args)
        elif kind == "backfill":
            out = cmd_backfill(cfg, conn, args)
        elif kind == "status":
            out = cmd_status(cfg, conn, args)
        elif kind == "serve":
            out = cmd_serve(cfg, conn, args)
        else:
            out = {"error": "unknown command"}
        finish_run(conn, run_id, "ok", {k: v for k, v in out.items() if k != "usage"}, None) if run_id else None
        conn.commit()
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    except BudgetExceeded as e:
        if run_id:
            finish_run(conn, run_id, "error", {}, str(e))
            conn.commit()
        print(json.dumps({"error": str(e), "kind": "budget"}, ensure_ascii=False), file=sys.stderr)
        return 2
    except Exception as e:
        if run_id:
            finish_run(conn, run_id, "error", {}, str(e))
            conn.commit()
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
