/**
 * Manual check: render media/dashboard.html exactly as the extension would
 * (CSP + nonce), with a stub acquireVsCodeApi that answers like the router and
 * pushes a snapshot. Usage:
 *   npx esbuild scripts/webview-harness.mts --bundle --platform=node --format=esm --outfile=%TEMP%/harness.mjs
 *   node %TEMP%/harness.mjs <usage.json> <out.html> [editor-locale, e.g. en]   (run from the repo root)
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dashboardHtml } from "../packages/extension/src/present.ts";

const [usagePath, outPath, locale = ""] = process.argv.slice(2);
const raw = readFileSync("packages/extension/media/dashboard.html", "utf8");
const report = JSON.parse(readFileSync(usagePath, "utf8"));
const nonce = "HARNESS";

const stub = `<script nonce="${nonce}">
window.__requests = [];
window.acquireVsCodeApi = () => ({
  getState() {}, setState() {},
  postMessage(msg) {
    const reply = (data) => setTimeout(() => window.dispatchEvent(new MessageEvent("message", { data })), 10);
    if (msg.type === "ready") return reply({ type: "snapshot", snapshot: { report: ${JSON.stringify(report)}, history: [], status: { state: "idle", runningFull: false, lastError: null, lastSuccessAt: Date.now(), consecutiveFailures: 0, retryAt: null } } });
    window.__requests.push(msg.method);
    const results = {
      loadSettings: { authSource: "auto", alertsEnabled: true, alertThresholds: [80, 95], onDemandBudget: 0, refreshSeconds: 120 },
      appInfo: { version: "0.1.0", dataDir: "(globalStorage)", platform: "cursor-extension", update: null, hasManualCredentials: false, hasRefreshToken: false, manualEmail: "", tokenPreview: "" },
    };
    reply({ type: "response", id: msg.id, ok: true, result: results[msg.method] ?? null });
  },
});
</script>`;

// Theme variables Cursor injects into webviews (dark theme), plus the body class.
const themeVars = `<style nonce="${nonce}">:root{--vscode-editor-background:#181818;--vscode-sideBar-background:#1f1f1f;--vscode-foreground:#cccccc;--vscode-descriptionForeground:#9d9d9d;--vscode-disabledForeground:#6e6e6e;--vscode-widget-border:#313131;--vscode-panel-border:#2b2b2b;--vscode-input-border:#3c3c3c;--vscode-list-hoverBackground:#2a2d2e;--vscode-focusBorder:#0078d4;--vscode-font-family:"Segoe UI",sans-serif}</style>`;

let html = dashboardHtml(raw, nonce, "https://harness.invalid", locale);
html = html.replace("<head>", `<head>\n${themeVars}\n${stub}`).replace("<body>", '<body class="vscode-dark">');
writeFileSync(outPath, html);
console.log("wrote", outPath);
