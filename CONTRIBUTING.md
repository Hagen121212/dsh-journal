# 贡献指南

先说清楚这个项目的边界：它是一个**本地单人工具**，优先保证“证据可回链”和“数据不出本机”。任何削弱这两点的改动都会被拒绝。

## 开发环境

- Python 3.11+
- Node ≥ 22.15（只在解压 zstd 时需要）
- 不需要第三方 Python 包

```bash
python -m unittest discover -s tests -v
python tools/build_demo.py --home demo-home --clean
JOURNAL_HOME=demo-home python -m journal.cli serve --port 8766
```

## 可以提什么

- 新的数据源（目前只有 DSH）
- 解析器对新版会话格式的适配
- 脱敏规则（新的密钥/路径模式）
- 报告结构与提示词的改进，尤其是“减少过度解读”
- Web 的可用性与无障碍问题
- 文档、示例、截图（**必须用合成数据**）

## 不要提交

- 任何真实聊天记录、数据库、报告、日志、备份
- 本机路径、用户名、邮箱、手机号、API key
- `config.toml`（用 `config.example.toml` 演示配置）
- `docs/screenshots/` 里带真实内容的截图

提交前自查：

```bash
grep -rInE "sk-[A-Za-z0-9_-]{12,}|DEEPSEEK_API_KEY\s*[:=]|[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}" \
  --exclude-dir=.git --exclude-dir=demo-home .
```

## 提交信息

用一句话说明改了什么、为什么。涉及提示词的改动，请附上“同一批会话改前/改后”的对比，说明它减少或增加了哪种误判。

## 引用校验是硬约束

不要为了“报告更好看”而放宽 `verify_quote` 或跳过 evidence 校验。宁可让报告短一些，也不要出现无法回链的判断。

## 许可证

提交即表示同意以 MIT 许可证发布你的贡献。
