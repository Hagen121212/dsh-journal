(function () {
  if (window.__DSH_JOURNAL_PANEL__) return;
  window.__DSH_JOURNAL_PANEL__ = true;

  var API = window.__DSH_JOURNAL_API__ || "http://127.0.0.1:8765";
  var SUMMARY = "/dsh-journal/summary";
  var DIMS = ["技术判断力", "决策质量", "研究方法", "逻辑语言能力", "思维认知方式"];
  var STORE_KEY = "dsh-journal-open";

  var css = `
  #dsh-journal-fab {
    position: fixed; right: 22px; left: auto; top: 86px; bottom: auto; z-index: 2147483000;
    display: flex; align-items: center; gap: 8px;
    padding: 7px 12px 7px 7px; border-radius: 999px;
    border: 1px solid #ddd6c8; background: #fffdf8; color: #20242a;
    box-shadow: 0 6px 22px rgba(0,0,0,.14); cursor: pointer;
    font: 13px/1.2 "Segoe UI","Microsoft YaHei","PingFang SC",system-ui,sans-serif;
  }
  #dsh-journal-fab:hover { border-color: #2f6f62; color: #2f6f62; }
  #dsh-journal-fab .mark {
    width: 27px; height: 27px; border-radius: 50%; display: grid; place-items: center;
    background: #2f6f62; color: #fff; font-family: "Songti SC",Georgia,serif; font-size: 15px;
  }
  #dsh-journal-fab .label { font-weight: 600; letter-spacing: .01em; }
  #dsh-journal-panel {
    position: fixed; right: 22px; left: auto; top: 138px; bottom: auto; z-index: 2147483001;
    width: 360px; max-width: calc(100vw - 24px); max-height: calc(100vh - 170px);
    display: none; flex-direction: column; overflow: hidden;
    background: #fffdf8; color: #20242a; border: 1px solid #e4dfd3;
    border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,.2);
    font: 13px/1.55 "Segoe UI","Microsoft YaHei","PingFang SC",system-ui,sans-serif;
  }
  #dsh-journal-panel.open { display: flex; }
  #dsh-journal-panel .j-head {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    padding: 13px 15px; border-bottom: 1px solid #eee9de; background: #faf8f2;
  }
  #dsh-journal-panel .j-head strong { display: block; font-size: 14px; }
  #dsh-journal-panel .j-head span { display: block; font-size: 10px; color: #7a7f78; margin-top: 1px; }
  #dsh-journal-panel .j-close {
    border: 0; background: transparent; color: #7a7f78; font-size: 20px; line-height: 1;
    cursor: pointer; padding: 2px 4px; border-radius: 6px;
  }
  #dsh-journal-panel .j-close:hover { background: #eee9de; color: #20242a; }
  #dsh-journal-panel .j-body { padding: 14px 15px 6px; overflow: auto; }
  #dsh-journal-panel .j-loading, #dsh-journal-panel .j-error, #dsh-journal-panel .j-empty {
    color: #7a7f78; font-size: 12px; padding: 10px 0 16px;
  }
  #dsh-journal-panel .j-error b { color: #a94442; font-size: 13px; }
  #dsh-journal-panel .j-error p { margin: 6px 0 0; }
  #dsh-journal-panel code {
    font-family: "Cascadia Code",Consolas,monospace; font-size: 11px;
    background: #eee9de; padding: 1px 4px; border-radius: 4px;
  }
  #dsh-journal-panel .j-stats {
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 14px;
  }
  #dsh-journal-panel .j-stats div {
    background: #faf8f2; border: 1px solid #eee9de; border-radius: 10px; padding: 8px 10px;
  }
  #dsh-journal-panel .j-stats b { display: block; font-family: Georgia,serif; font-size: 19px; line-height: 1.2; }
  #dsh-journal-panel .j-stats span { display: block; color: #7a7f78; font-size: 10px; margin-top: 1px; }
  #dsh-journal-panel .j-section { padding: 10px 0 12px; border-top: 1px solid #eee9de; }
  #dsh-journal-panel .j-section:first-of-type { border-top: 0; padding-top: 0; }
  #dsh-journal-panel .j-eyebrow {
    color: #7a7f78; font-size: 10px; letter-spacing: .08em; text-transform: uppercase; margin-bottom: 5px;
  }
  #dsh-journal-panel .j-oneline { margin: 0 0 6px; font-size: 13px; line-height: 1.65; }
  #dsh-journal-panel .j-summary {
    margin: 0; font-size: 12px; line-height: 1.65; color: #4c514c;
    display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden;
  }
  #dsh-journal-panel .j-link { color: #2f6f62; font-size: 12px; text-decoration: none; }
  #dsh-journal-panel .j-link:hover { text-decoration: underline; }
  #dsh-journal-panel .j-dims { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  #dsh-journal-panel .j-dim {
    display: flex; align-items: center; justify-content: space-between; gap: 6px;
    background: #faf8f2; border: 1px solid #eee9de; border-radius: 8px; padding: 6px 8px;
  }
  #dsh-journal-panel .j-dim span { font-size: 11px; color: #4c514c; }
  #dsh-journal-panel .j-dim b { font-size: 11px; color: #2f6f62; white-space: nowrap; }
  #dsh-journal-panel .j-hint { color: #7a7f78; font-size: 11px; padding: 2px 0 10px; }
  #dsh-journal-panel .j-foot {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 10px 15px 12px; border-top: 1px solid #eee9de; background: #faf8f2;
  }
  #dsh-journal-panel .j-refresh {
    border: 1px solid #ddd6c8; background: #fffdf8; color: #20242a; border-radius: 7px;
    padding: 4px 10px; font: inherit; font-size: 11px; cursor: pointer;
  }
  #dsh-journal-panel .j-refresh:hover { border-color: #2f6f62; color: #2f6f62; }
  #dsh-journal-panel .j-open { color: #2f6f62; font-size: 12px; text-decoration: none; }
  #dsh-journal-panel .j-open:hover { text-decoration: underline; }
  @media (prefers-color-scheme: dark) {
    #dsh-journal-fab { background: #1b1f21; color: #e8e6df; border-color: #303638; }
    #dsh-journal-panel { background: #1b1f21; color: #e8e6df; border-color: #303638; }
    #dsh-journal-panel .j-head, #dsh-journal-panel .j-foot { background: #171b1d; border-color: #303638; }
    #dsh-journal-panel .j-stats div, #dsh-journal-panel .j-dim { background: #171b1d; border-color: #303638; }
    #dsh-journal-panel .j-section { border-color: #303638; }
    #dsh-journal-panel .j-close:hover { background: #303638; }
    #dsh-journal-panel .j-summary, #dsh-journal-panel .j-dim span { color: #b9beb7; }
    #dsh-journal-panel .j-loading, #dsh-journal-panel .j-error, #dsh-journal-panel .j-empty,
    #dsh-journal-panel .j-hint, #dsh-journal-panel .j-head span,
    #dsh-journal-panel .j-stats span, #dsh-journal-panel .j-eyebrow { color: #9a9f98; }
    #dsh-journal-panel .j-link, #dsh-journal-panel .j-dim b, #dsh-journal-panel .j-open { color: #79b9a8; }
    #dsh-journal-panel code { background: #303638; }
    #dsh-journal-panel .j-refresh { background: #1b1f21; color: #e8e6df; border-color: #303638; }
  }
  @media (max-width: 560px) {
    #dsh-journal-fab { right: 12px; left: auto; top: 64px; bottom: auto; }
    #dsh-journal-fab .label { display: none; }
    #dsh-journal-panel { left: 12px; right: 12px; top: 116px; bottom: auto; width: auto; max-height: calc(100vh - 140px); }
  }
  `;

  var style = document.createElement("style");
  style.id = "dsh-journal-panel-style";
  style.textContent = css;
  document.head.appendChild(style);

  var fab = document.createElement("button");
  fab.id = "dsh-journal-fab";
  fab.type = "button";
  fab.title = "打开思维年轮";
  fab.innerHTML = '<span class="mark">年</span><span class="label">思维年轮</span>';
  document.body.appendChild(fab);

  var panel = document.createElement("section");
  panel.id = "dsh-journal-panel";
  panel.setAttribute("aria-label", "思维年轮");
  panel.innerHTML = [
    '<header class="j-head">',
    '  <div><strong>思维年轮</strong><span>每周日 20:00 更新</span></div>',
    '  <button class="j-close" type="button" aria-label="关闭">×</button>',
    '</header>',
    '<div class="j-body"><div class="j-loading">读取中…</div></div>',
    '<footer class="j-foot">',
    '  <button class="j-refresh" type="button">刷新</button>',
    '  <a class="j-open" href="' + API + '/" target="_blank" rel="noopener">打开完整网页 →</a>',
    '</footer>'
  ].join("");
  document.body.appendChild(panel);

  var body = panel.querySelector(".j-body");
  var closeBtn = panel.querySelector(".j-close");
  var refreshBtn = panel.querySelector(".j-refresh");

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }

  function dimValue(value) {
    if (value === null || value === undefined || value === "") return "观察中";
    var n = Number(value);
    return isNaN(n) ? "观察中" : n.toFixed(0) + "/5";
  }

  function render(data) {
    var s = data.stats || {};
    var w = data.latest_weekly;
    var g = data.latest_growth;
    var l4 = data.latest_l4;
    var dims = (g && g.dimensions) || {};
    var dimHtml = DIMS.map(function (name) {
      return '<div class="j-dim"><span>' + esc(name) + '</span><b>' + esc(dimValue(dims[name])) + '</b></div>';
    }).join("");

    var weeklyHtml = '<div class="j-section"><div class="j-eyebrow">本周</div>';
    if (w && w.one_line) {
      weeklyHtml += '<p class="j-oneline">' + esc(w.one_line) + '</p>';
      if (w.period_start) {
        weeklyHtml += '<a class="j-link" target="_blank" rel="noopener" href="' + API + '/reports/weekly/' + encodeURIComponent(w.period_start) + '">读周报 →</a>';
      }
    } else {
      weeklyHtml += '<p class="j-oneline">本周周报还没生成。</p>';
    }
    weeklyHtml += '</div>';

    var l4Link = "";
    if (l4 && l4.period_start) {
      l4Link = ' · <a class="j-link" target="_blank" rel="noopener" href="' + API + '/reports/l4/' + encodeURIComponent(l4.period_start) + '">L4 档案 →</a>';
    }

    var growthHtml = "";
    if (g && g.summary) {
      growthHtml = '<div class="j-section"><div class="j-eyebrow">最新画像' + l4Link + '</div><p class="j-summary">' + esc(g.summary) + '</p></div>';
    } else if (l4Link) {
      growthHtml = '<div class="j-section"><div class="j-eyebrow">最新画像' + l4Link + '</div></div>';
    }

    var hint = (s.pending_insights && Number(s.pending_insights) > 0)
      ? "有 " + esc(s.pending_insights) + " 条待确认洞察，去网页处理。"
      : "洞察都已处理。";

    body.innerHTML = [
      '<div class="j-stats">',
      '  <div><b>' + esc(s.sessions || 0) + '</b><span>会话</span></div>',
      '  <div><b>' + esc(s.accepted_insights || 0) + '</b><span>已确认</span></div>',
      '  <div><b>' + esc(data.pending_insights || 0) + '</b><span>待确认</span></div>',
      '</div>',
      weeklyHtml,
      '<div class="j-section"><div class="j-eyebrow">五维状态</div><div class="j-dims">' + dimHtml + '</div></div>',
      growthHtml,
      '<div class="j-hint">' + hint + '</div>'
    ].join("");
  }

  function showError(err) {
    body.innerHTML = [
      '<div class="j-error">',
      '<b>连不上本地服务</b>',
      '<p>' + esc(API.replace("http://", "")) + ' 没有响应。</p>',
      '<p>先启动本地 Web 服务（<code>start_web.cmd</code>），再点「刷新」。</p>',
      '<p style="color:#9a9f98;font-size:11px">' + esc(err && err.message ? err.message : "") + '</p>',
      '</div>'
    ].join("");
  }

  function fetchSummary(signal) {
    return fetch(SUMMARY, { cache: "no-store", signal: signal })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .catch(function () {
        // Standalone preview or an older host without the proxy route.
        return fetch(API + "/api/summary", { cache: "no-store", signal: signal })
          .then(function (res) {
            if (!res.ok) throw new Error("HTTP " + res.status);
            return res.json();
          });
      });
  }

  function refresh() {
    body.innerHTML = '<div class="j-loading">读取中…</div>';
    var controller = window.AbortController ? new AbortController() : null;
    var timer = controller ? setTimeout(function () { controller.abort(); }, 6000) : null;
    fetchSummary(controller ? controller.signal : undefined)
      .then(function (data) {
        if (timer) clearTimeout(timer);
        render(data);
      })
      .catch(function (err) {
        if (timer) clearTimeout(timer);
        showError(err);
      });
  }

  function openPanel() {
    panel.classList.add("open");
    try { localStorage.setItem(STORE_KEY, "1"); } catch (e) {}
    refresh();
  }

  function closePanel() {
    panel.classList.remove("open");
    try { localStorage.setItem(STORE_KEY, "0"); } catch (e) {}
  }

  fab.addEventListener("click", function () {
    if (panel.classList.contains("open")) closePanel(); else openPanel();
  });
  closeBtn.addEventListener("click", closePanel);
  refreshBtn.addEventListener("click", refresh);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closePanel();
  });

  try {
    if (localStorage.getItem(STORE_KEY) === "1") openPanel();
  } catch (e) {}
})();
