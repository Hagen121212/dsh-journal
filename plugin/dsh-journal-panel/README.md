# dsh-journal-panel

> 这个目录与独立仓库 [Hagen121212/dsh-journal-panel](https://github.com/Hagen121212/dsh-journal-panel) 内容一致；单独立装、提 issue、看版本请走那边。这里是随主项目一起分发的副本。

「思维年轮」的 DSH 轻量面板。在 DSH 右上角放一个「年」按钮，点开后读取本机 `http://127.0.0.1:8765/api/summary`，显示：

- 会话数 / 已确认洞察 / 待确认洞察
- 本周一句话 + 周报链接
- 五维状态（证据不足时显示“观察中”）
- 最新画像摘要、L4 档案链接
- 打开完整网页

完整网页仍然是主界面；这个面板只做“大概”。

> 非官方插件。它依赖 DSH 的内部注入点（`webserver/index-inject`、`webServer.register`、`tapIndex`），只在 2026-10 的 DeepSeek Harness 桌面版上验证过；升级 DSH 后若按钮消失，先按下面的回滚。

## 安装

```powershell
dsh plugin --profile desktop add <path-to-this-folder>
```

或从 npm 安装（发布后）：

```powershell
dsh plugin --profile desktop add dsh-journal-panel
```

安装后**完整重启** DeepSeek Harness。桌面端的注入表在启动时收集，热加载只会注册 API，不会补上按钮。

## 配置

面板默认连 `http://127.0.0.1:8765`。如果本地 Web 换了端口，改 `lib/client.js` 顶部的 `API` 常量，或给页面注入：

```html
<script>window.__DSH_JOURNAL_API__ = "http://127.0.0.1:9000";</script>
```

## 回滚

```powershell
dsh plugin --profile desktop remove dsh-journal-panel
```

## 组件边界

- 只读本机的 `127.0.0.1`，不向外发任何请求。
- 面板不写数据库；接受/驳回洞察仍在完整网页里完成。
