# 隐私说明

思维年轮是一个**本地单人工具**。它读你自己的聊天记录，因此默认假设这些内容只应该留在你自己的机器上。

## 数据存在哪

所有数据都在 `$JOURNAL_HOME`（默认 `~/DeepSeekJournal`）：

```text
$JOURNAL_HOME/
  data/journal.db      SQLite：会话、消息、卡片、观察、洞察、报告索引
  data/tmp/            解压中的临时 JSONL（同步结束即删）
  reports/weekly/      周报 .md + .json
  reports/growth/      成长报告 .md + .json
  reports/baseline/    基线画像
  reports/l4/          L4 档案
  logs/                sync / weekly / web 日志
```

这些目录**不在仓库里**，`.gitignore` 已排除 `data/`、`reports/`、`logs/`、`*.db`、`config.toml`、`api_key.txt`。

## 什么会离开这台机器

只有一件事：**发往 DeepSeek API 的请求**（`base_url` 默认 `https://api.deepseek.com`）。请求里包含：

- 会话转录（用户消息 + 助手回复的文本，可能包含工具调用的名字与参数）
- 会话卡 / 观察的上下文，用于生成周报与成长报告

请求**不包含**：API key 以外的凭据、其他本地文件、数据库路径。

除此之外没有任何遥测、崩溃上报或“匿名统计”。

## 发送前的脱敏

`journal/redact.py` 在**入库时**就会替换掉：

| 类型 | 处理 |
| --- | --- |
| `sk-…` 形式的密钥 | `<api-key>` |
| `DEEPSEEK_API_KEY=…` / `secret=…` | `<redacted>` |
| `Bearer …` | `Bearer <token>` |
| PEM 私钥块 | `<private-key>` |
| 邮箱 | `<email>` |
| 中国大陆手机号 | `<phone>` |
| 40 位以上 hex、长 base64 | `<hex-token>` / `<base64-token>` |
| 当前用户的主目录路径 | `<home>` |

脱敏是**按模式匹配**，不是保证。它拦得住常见密钥和路径，拦不住自然语言里的个人信息（例如你自己说出的学校、公司、地址）。如果你担心这类内容，请在运行前自行处理，或只用 `--limit` 在少量会话上试。

## 网络暴露面

- Web 服务只绑定 `127.0.0.1`，默认端口 8765。
- 没有登录、没有鉴权：**任何能访问这个端口的本机进程都能读到你的全部复盘数据**。
- 不要改 `--host 0.0.0.0`，不要把端口转发到局域网或公网，不要放进容器对外映射。
- `/api/summary` 带 `Access-Control-Allow-Origin: *`，这是为了让 DSH 面板从自己的 origin 读取；它同样只在本机回环上可达。

## API key

读取顺序：

1. 环境变量 `DEEPSEEK_API_KEY`
2. `$DSH_HOME/.credentials.yaml` 里的 `refs.DEEPSEEK_API_KEY`
3. `$JOURNAL_HOME/api_key.txt`

key 只存在于进程内存里，**不写数据库、不写报告、不写日志**。`api_key.txt` 已被 `.gitignore` 排除。

## 截图与分享

如果你要公开自己的截图或报告片段：

- 截图前先换成演示库（`tools/build_demo.py`），不要直接截真实数据。
- 报告里即使引用已脱敏，也会暴露你的关注点、项目名和判断方式。分享前通读一遍。
- `$JOURNAL_HOME/backups/` 里的备份同样包含原始数据，不要一起打包分享。

## 删除数据

停掉 Web 服务，然后删除整个 `$JOURNAL_HOME` 即可。没有云端副本，也没有回收站以外的残留。
