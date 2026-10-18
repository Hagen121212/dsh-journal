import fs from "node:fs";

const CLIENT = fs.readFileSync(new URL("./client.js", import.meta.url), "utf8");
const MARKER = "dsh-journal-panel";
const JOURNAL_API = "http://127.0.0.1:8765/api/summary";

function injectRow(table) {
  try {
    if (!Array.isArray(table)) return;
    for (const row of table) {
      if (!row) continue;
      if (row.kind === "script" && typeof row.text === "string" && row.text.includes(MARKER)) return;
    }
    table.push({ kind: "script", placement: "body", text: CLIENT });
  } catch (err) {
    // Never let a panel injection break the host page.
  }
}

function injectHtml(html) {
  if (typeof html !== "string") return html;
  if (html.includes(MARKER)) return html;
  const tag = `<script data-${MARKER}>${CLIENT}</script>`;
  return html.includes("</body>") ? html.replace("</body>", `${tag}</body>`) : html + tag;
}

export default {
  name: "dsh-journal-panel",
  apply(root) {
    // Desktop host: the row table is the only reliable injection channel.
    try {
      root.on("webserver/index-inject", injectRow);
    } catch (err) {}

    // Web host: a same-origin proxy plus an index tap.
    try {
      root.inject(["webServer"], (ctx) => {
        const ws = ctx.webServer || (typeof ctx.get === "function" ? ctx.get("webServer") : null);
        if (!ws) return;
        if (typeof ws.register === "function") {
          try {
            ws.register({
              kind: "exact",
              path: "/dsh-journal/summary",
              handler: async (req, res) => {
                const headers = {
                  "Content-Type": "application/json; charset=utf-8",
                  "Cache-Control": "no-store",
                };
                try {
                  const upstream = await fetch(JOURNAL_API, { cache: "no-store" });
                  const text = await upstream.text();
                  res.writeHead(upstream.status, headers);
                  res.end(text);
                } catch (err) {
                  res.writeHead(503, headers);
                  res.end(JSON.stringify({ error: "journal server offline" }));
                }
              },
            });
          } catch (err) {}
        }
        if (typeof ws.tapIndex === "function") {
          try {
            ws.tapIndex(injectHtml);
          } catch (err) {}
        }
      });
    } catch (err) {}
  },
};
