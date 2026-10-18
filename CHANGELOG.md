# Changelog

## 0.1.0 — 2026-10-19

首个公开版本。

- 解析 DSH 的多帧 zstd 会话，过滤注入的 runtime-context / skill-catalog / time-context
- 入库前脱敏密钥、token、邮箱、手机号、本机路径
- SQLite + FTS5（trigram）全文搜索
- 会话卡：目标、关键转折、信号、自我描述、修正、承诺，引用逐条校验
- 周报、基线画像、双周成长报告（五维）
- L4 候选洞察：网页接受 / 改写 / 驳回，确认后进入档案并在下期逐条复核
- 本地 Web：概览、时间线、主题、成长、洞察、报告、搜索、证据回链
- DSH `/journal` 技能与右上角浮动面板插件
- 合成演示库（`tools/build_demo.py`）与 unittest
