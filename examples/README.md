# examples

这里的全部内容都是**合成数据**：人名、项目、对话均为虚构，用于演示界面、截图和手动测试。它不包含任何真实聊天记录。

## 文件

- `demo_dataset.json`：5 段虚构会话（会话卡、主题、关键引用）、5 条洞察（3 已确认、1 驳回、1 来源修正）、5 份报告（基线、两周周报、成长复盘、L4 档案）。
- `fixtures/minimal_session.jsonl`：一段最小的 DSH 会话事件流，用来测解析器（含一条注入的 runtime-context）。
- `fixtures/broken_session.jsonl`：夹了一行坏 JSON 的会话，用来测容错。

## 生成演示库

```bash
python tools/build_demo.py --home demo-home --clean
JOURNAL_HOME=demo-home python -m journal.cli serve --port 8766
```

打开 <http://127.0.0.1:8766/> 就能看到和 `docs/screenshots/` 一样的界面，不需要 API key，也不会读取 `~/.dsh`。

`demo-home/` 已被 `.gitignore` 排除。

## 想改内容

直接编辑 `demo_dataset.json`，重新跑一次 `build_demo.py --clean`。所有时间戳、消息 id 由脚本推导；卡片里的 `message_id` 需要写成 `demo-001:user:u1` 这种形式（脚本不会改写字面量）。

## 用它写测试

`tests/` 里的测试只依赖标准库和仓库自身；如果你要扩大测试面，可以从这份数据集里取字段复用，但**不要**把真实会话改一改放进来。
