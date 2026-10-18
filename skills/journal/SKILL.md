---
name: journal
description: 查看“思维年轮”聊天复盘：本周摘要、五维状态、待确认洞察，并打开本地网页。用户问“我这周聊了什么”“我的成长”“思维年轮”“周报”时使用。
whenToUse: 用户想查看聊天复盘、周报、双周成长画像、待确认洞察，或想打开思维年轮网页时。
---

# 思维年轮

本地服务地址：`http://127.0.0.1:8765`

## 读取摘要

先尝试读取：

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/api/summary" | ConvertTo-Json -Depth 8
```

如果连接失败，说明本地服务没开。不要在这个会话里直接启动长驻进程，让用户运行仓库里的 `start_web.cmd`（macOS / Linux 用 `journal.sh serve`），等 2 秒再读。

登录后该服务通常会自动启动；如果仍然失败，让用户看 `$JOURNAL_HOME/logs/weekly.log` 和 `$JOURNAL_HOME/logs/web.log`。

## 怎么回复

用中文，5-8 行，按这个顺序：

1. 本周一句话（`latest_weekly.one_line`；没有就写“本周周报还没生成”）。
2. 五维状态：`latest_growth.dimensions` 里是数字就写 `x/5`，是 `null` 就写“观察中”。
3. L4 状态：`pending_insights` 条待确认；`stats.accepted_insights` 条已确认、`stats.notes` 条修正。待确认大于 0 就提醒到网页处理；等于 0 就说明已进入 L4 档案。
4. 最新报告：给周报/成长报告链接；如果有 `latest_l4`，再给 `http://127.0.0.1:8765/reports/l4/<period_start>`。
5. 完整网页：`http://127.0.0.1:8765/`。

如果用户想看某场会话，给 `/sessions/<session_id>` 链接；想搜索，给 `/search?q=关键词`。

## 边界

- 不主动替用户接受或驳回洞察；那是用户在网页上的确认动作。
- 不输出 API key、凭据文件内容或未脱敏的本地路径。
- 不把 `null` 分数解释成“0 分”；它表示证据不足。
- 周报每周日 20:00 自动生成；成长报告每两个周日一次，满 3 个点才谈趋势。
