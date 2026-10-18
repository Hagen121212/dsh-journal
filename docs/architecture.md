# 架构

## 一句话

Python 标准库写的单进程引擎：读 DSH 会话 → 解析成消息 → 存 SQLite → 调用 DeepSeek 生成结构化卡片与报告 → 用本地 HTTP 服务渲染。Node 只用来解压 zstd。

## 模块

```text
journal/
  config.py       配置加载（tomllib + 环境变量），路径推导
  util.py         时间/周计算、哈希、JSON 读写、文本截断、时区
  redact.py       入库前的密钥与路径脱敏
  sources/dsh.py  DSH 会话发现、zstd 解压、JSONL 事件解析
  ingest.py       同步流程、转录构建（mN 别名）、引用校验
  db.py           SQLite schema、查询封装、FTS5 搜索
  llm.py          DeepSeek chat/completions 客户端、预算护栏、JSON 修复
  prompts.py      三个 system prompt 与 user prompt 组装
  cards.py        会话卡生成与证据清洗
  weekly.py       周报生成与归一化
  growth.py       双周成长报告、观察序列、prior 组装
  l4.py           L4 档案导出
  report_md.py    Markdown 渲染（引用 → /sessions/... 链接）
  web.py          本地 HTTP 服务与页面渲染
  webutil.py      HTML 转义、日期格式化等
  cli.py          命令入口
```

## 数据流

### 1. 同步

`cli sync` → `sources.dsh.iter_sessions` 遍历 `$DSH_HOME/sessions/**/session.v4.jsonl.zstd` → `decompress` 调 `tools/decompress_session.mjs`（Node，按 magic 分帧解压多帧 zstd）→ `parse_session_file` 解析事件流。

解析时：

- `session` 事件提供 id / cwd / createdAt
- `session/title` 取质量最高的标题（`source.kind != fallback` 优先）
- `user/message`、`agent/inbox/spliced` 里的用户消息才计入；`source.kind` 为 `runtime-context` / `skill-catalog` / `time-context` 的注入内容被丢弃
- `assistant/message` 按 block 顺序拆成 text / reasoning / tool_call
- `tool/result` 截断到 2000 字，只作上下文

入库时 `redact()` 已经作用在每条内容上，`replace_messages` 同时维护 FTS5（trigram）索引。会话按 `source_hash` 判断是否需要重解析。

### 2. 会话卡

`cards.generate_card`：

1. `build_transcript` 把消息压成 `[m1] U1: ...` 形式（用户 4000 字、助手 700 字、总 45000 字上限），并维护 `mN → message_id` 映射。
2. 调模型，要求返回固定 JSON。
3. `normalize_card` 清洗：每条 evidence 的 `quote` 必须能在对应消息（或本会话任一消息）里找到，`verified=false` 的会被下游过滤掉。
4. `save_card` 写库，`link_session_topics` 建立主题关联。

### 3. 周报与成长报告

- `weekly.generate_weekly` 取本周有卡片的会话 → 调模型 → `normalize_weekly`（转折与回看必须通过引用校验）→ 渲染 Markdown + JSON → `save_report`。
- `growth.generate_growth` 取窗口内卡片 → 组装 `prior`（上次观察、上次实验、已确认/已驳回洞察、来源修正）→ 调模型 → `normalize_growth`（同上校验，`score` 收敛到 1–5 或 `null`）→ `save_observations` → `upsert_insight`（候选洞察）→ 渲染。

两者都会把“下两周实验”写进报告的 meta，下一次生成时读出来判断是否完成。

### 4. 洞察与 L4

```text
报告里的候选洞察 → insights(status=pending)
        │  网页 POST /insights/<id>/status
        ├─ accepted → l4.generate_l4 重写 L4 档案
        ├─ rejected → 下次不再原样重提
        └─ 改写 → 保留 original_statement，作为来源修正
```

`l4.generate_l4` 每次都从数据库重新渲染整份档案，因此网页上的每一次确认都会立刻反映到 `reports/l4/*.md`。

### 5. Web

`web.py` 是 `http.server.ThreadingHTTPServer` 的薄封装：每个请求开一个 SQLite 连接，渲染服务端 HTML（无前端框架），样式在 `static/style.css`。

路由：`/`、`/timeline`、`/topics`、`/growth`、`/insights`、`/reports`、`/search`、`/sessions/<id>`、`/api/summary`。

`/api/summary` 是给 DSH 面板用的只读摘要，带 `Access-Control-Allow-Origin: *`（因为面板从 DSH 的 origin 发起请求）。

## 数据库

| 表 | 作用 |
| --- | --- |
| `sessions` | 会话元数据 + 卡片状态 |
| `messages` | 消息（含 reasoning、tool_call、tool_result） |
| `messages_fts` | FTS5 trigram 全文索引 |
| `topics` / `session_topics` | 一级/二级主题与关联 |
| `cards` | 会话卡（JSON 字段拆列） |
| `observations` | 每期每维度的分数、证据、反例、变化 |
| `insights` | 候选/已确认/已驳回的自我认知 |
| `reports` | 报告索引（kind, period, 文件路径） |
| `runs` | 每次 CLI 运行的记录，用于诊断 |

`init_db` 里带轻量前向迁移（`ALTER TABLE` 补列），所以旧库可以直接升级。

## 失败处理

- 单个会话解析失败只记日志并跳过，不中断同步。
- API 调用有 4 次指数退避重试；400/401/402/403/404 不重试。
- 预算护栏（调用次数、总 token）触发 `BudgetExceeded`，命令以退出码 2 结束并保留已完成的结果。
- 模型返回坏 JSON 时先尝试剥离代码围栏，再发一次“修复 JSON”的请求；仍失败则抛 `LLMError`。
- 进程若在运行中崩溃，`runs` 表会留下 `running`，下次启动时把超过 6 小时的记录标成 `error`。

## 扩展点

- **新的数据源**：在 `journal/sources/` 加一个模块，产出 `ParsedSession`，在 `ingest` 里接入即可。其余流程与数据源无关。
- **新的报告类型**：`save_report` + `report_md` 里加一个 renderer；`web.py` 的报告列表会按 `reports.kind` 自动展示。
- **换模型**：改 `config.toml` 的 `model.model` / `reasoning_effort`；提示词在 `prompts.py`，不依赖具体模型。

## 已知坑

- **多帧 zstd**：DSH 的会话文件由多个 zstd frame 拼接，Node 的 `zstdDecompressSync` 只解第一帧，必须按 magic（`28 b5 2f fd`）切分。
- **注入上下文**：DSH 会把 runtime-context 等写成 user message，必须按 `source.kind` 过滤，否则会污染“你的提问”统计。
- **插件注入时机**：桌面端在启动时收集注入表，热加载只能注册 API，按钮需要完整重启才会出现。
- **面板位置**：DSH 左下角有“更多”、右下角有鲸鱼，面板放在右上角。
- **报告链接**：Markdown 里是 `/sessions/...` 相对路径，脱离本地 Web 服务点不开。
