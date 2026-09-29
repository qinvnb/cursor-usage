import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, describe, expect, it } from "vitest";
import { createNodeHost, credentialsInfo, httpRequest, readLocalAuthFrom, resolveStateDb, type SecretStore } from "../src/nodeHost";
import { setLang } from "@cursor-usage/core";
import { dashboardHtml, levelOf, statusView, summaryText } from "../src/present";
import { route, type ExtensionFacade } from "../src/router";

const dir = mkdtempSync(join(tmpdir(), "cu-ext-"));
afterAll(() => rmSync(dir, { recursive: true, force: true }));

function memorySecrets(): SecretStore & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get: async (k) => data.get(k),
    store: async (k, v) => void data.set(k, v),
    delete: async (k) => void data.delete(k),
  };
}

const summary = (over: Partial<Record<string, number>> = {}) =>
  ({
    email: null,
    planName: "Pro",
    unifiedUsedCents: 0,
    individualUsedCents: 1234,
    individualLimitCents: 60000,
    individualRemainingCents: 58766,
    includedUsedCents: 2000,
    includedLimitCents: 2000,
    includedRemainingCents: 0,
    usedPercent: 2,
    topOnDemandModel: null,
    billingCycleStart: "1",
    billingCycleEnd: "2",
    ...over,
  }) as any;

const idle = { state: "idle", runningFull: false, lastError: null, lastSuccessAt: null, consecutiveFailures: 0, retryAt: null } as const;

describe("local auth via node:sqlite", () => {
  it("reads cursorAuth keys read-only", async () => {
    const { DatabaseSync } = (process as any).getBuiltinModule("node:sqlite") as typeof import("node:sqlite");
    const path = join(dir, "state.vscdb");
    const db = new DatabaseSync(path);
    db.exec("CREATE TABLE ItemTable (key TEXT UNIQUE ON CONFLICT REPLACE, value BLOB)");
    const insert = db.prepare("INSERT INTO ItemTable VALUES (?, ?)");
    insert.run("cursorAuth/accessToken", "a.b.c");
    insert.run("cursorAuth/cachedEmail", new TextEncoder().encode("me@x.y"));
    insert.run("workbench.other", "x");
    db.close();
    expect(await readLocalAuthFrom(path)).toEqual({ accessToken: "a.b.c", cachedEmail: "me@x.y" });
    await expect(readLocalAuthFrom(join(dir, "missing.vscdb"))).rejects.toThrow("找不到");
  });

  it("finds state.vscdb next to the extension's global storage", () => {
    const storage = join(dir, "qinvnb.cursor-usage");
    expect(resolveStateDb("", storage, {})).toBe(join(dir, "state.vscdb"));
    expect(resolveStateDb("  C:/custom.vscdb ", storage, {})).toBe("C:/custom.vscdb");
  });
});

describe("node host", () => {
  it("only talks to Cursor hosts", async () => {
    await expect(httpRequest({ url: "https://example.com/x", method: "GET", headers: {}, timeoutMs: 1000 })).rejects.toThrow("blocked");
    const fake = (async () => new Response('{"ok":1}', { status: 201, headers: { "Retry-After": "3" } })) as typeof fetch;
    const res = await httpRequest({ url: "https://api2.cursor.sh/x", method: "POST", headers: {}, body: "{}", timeoutMs: 1000 }, fake);
    expect(res).toEqual({ status: 201, headers: { "content-type": "text/plain;charset=UTF-8", "retry-after": "3" }, body: '{"ok":1}' });
  });

  it("keeps manual credentials in secret storage and never writes Cursor's db", async () => {
    const secrets = memorySecrets();
    const host = createNodeHost({
      store: { read: async () => null, write: async () => {} },
      secrets,
      settings: () => ({ authSource: "manual", persistLocalRefresh: true, alertsEnabled: true, refreshSeconds: 60 }),
      stateDbOverride: () => "",
      globalStorageDir: dir,
      notify: async () => {},
      onReport: () => {},
      env: {},
    });
    await host.saveCredentials({ accessToken: " header.payload.signature ", email: "a@b.c" });
    expect(await host.getCredentials()).toEqual({ accessToken: "header.payload.signature", refreshToken: "", email: "a@b.c" });
    expect((await credentialsInfo(secrets)).tokenPreview).toBe("…ignature");
    await expect(host.writeLocalAuth({ accessToken: "x" })).rejects.toThrow();
    expect((await host.loadSettings()).persistLocalRefresh).toBe(false);
  });
});

describe("status bar", () => {
  it("auto mode shows included until exhausted, then on-demand", () => {
    expect(statusView(summary({ includedUsedCents: 500 }), idle, "auto").text).toBe("$(pulse) 套餐 $5.00 / $20.00");
    expect(statusView(summary(), idle, "auto").text).toBe("$(pulse) 按需 $12.34 / $600");
    expect(statusView(summary(), idle, "both").text).toContain("套餐 $20.00 / $20.00 · 按需");
  });

  it("shows the two included pools when the plan splits them", () => {
    const pools = summary({ autoPercentUsed: 10.4, apiPercentUsed: 62 });
    expect(statusView(pools, idle, "auto").text).toBe("$(pulse) 套餐 Auto 10% · API 62%");
    expect(statusView(pools, idle, "included").level).toBe("ok");
    const apiDone = summary({ autoPercentUsed: 10.4, apiPercentUsed: 100 });
    expect(statusView(apiDone, idle, "auto").text).toBe("$(pulse) 按需 $12.34 / $600");
    expect(statusView(apiDone, idle, "included").level).toBe("danger");
    expect(statusView(apiDone, idle, "auto").tooltip).toContain("| 套餐内 · 其他模型（API） | 100% | 100% | 0% |");
    expect(summaryText(apiDone)).toContain("套餐内 Cursor 模型（Auto）：已用 10%");
  });

  it("shows this cycle's tokens in the tooltip and summary", () => {
    const s = { ...summary(), tokens: { inputTokens: 12_000, outputTokens: 960_000, cacheReadTokens: 258_900_000, cacheWriteTokens: 4_000, total: 259_876_000 } };
    expect(statusView(s, idle, "auto").tooltip).toContain("本周期 Token：259.9M（输入 12.0K · 输出 960.0K · 缓存读取 258.9M · 缓存写入 4.0K）");
    expect(summaryText(s)).toContain("本周期 Token：259.9M");
    expect(summaryText(summary())).not.toContain("Token");
  });

  it("speaks English when the language is English", () => {
    setLang("en");
    try {
      const pools = summary({ autoPercentUsed: 10.4, apiPercentUsed: 100 });
      expect(statusView(pools, idle, "included").text).toBe("$(pulse) Plan Auto 10% · API 100%");
      expect(statusView(pools, idle, "auto").text).toBe("$(pulse) On-demand $12.34 / $600");
      expect(statusView(pools, idle, "auto").tooltip).toContain("| Included · Other models (API) | 100% | 100% | 0% |");
      expect(summaryText(pools)).toContain("Included Cursor models (Auto): 10% used");
      expect(summaryText(null)).toBe("Cursor usage: not synced yet");
    } finally {
      setLang("zh");
    }
  });

  it("colors by threshold", () => {
    expect(levelOf(50, 100)).toBe("ok");
    expect(levelOf(85, 100)).toBe("warn");
    expect(levelOf(96, 100)).toBe("danger");
    expect(levelOf(60, 100, [50, 70])).toBe("warn");
    expect(statusView(summary(), idle, "included").level).toBe("danger");
  });

  it("placeholder before the first sync", () => {
    expect(statusView(null, idle, "auto").text).toContain("sync~spin");
    expect(summaryText(null)).toContain("尚未同步");
  });
});

describe("webview", () => {
  it("adds a CSP and nonces every script", () => {
    const html = dashboardHtml('<html><head><title>x</title></head><body><script type="module">1</script><script>2</script></body></html>', "N0NCE", "vscode-resource:");
    expect(html).toContain("Content-Security-Policy");
    expect(html).toContain("script-src 'nonce-N0NCE'");
    // The two page scripts plus the injected locale script.
    expect(html.match(/<script nonce="N0NCE"/g)).toHaveLength(3);
    expect(html).not.toContain("connect-src");
  });

  it("passes the editor locale to the page, escaped", () => {
    const html = dashboardHtml("<html><head></head><body></body></html>", "N", "x:", "en</script><b>");
    expect(html).toContain('window.__cursorUsageLocale="en\\u003c/script>\\u003cb>"');
    expect(html).not.toContain("</script><b>");
  });
});

describe("router", () => {
  const facade = {
    refresh: async (o: unknown) => ({ refreshed: o }),
    loadSettings: async () => ({ a: 1 }),
    saveSettings: async () => {
      throw new Error("nope");
    },
  } as unknown as ExtensionFacade;

  it("dispatches known methods and reports errors", async () => {
    expect(await route(facade, { id: 1, method: "refresh", args: [{ full: true }] })).toEqual({ type: "response", id: 1, ok: true, result: { refreshed: { full: true } } });
    expect(await route(facade, { id: 2, method: "saveSettings", args: [{}] })).toEqual({ type: "response", id: 2, ok: false, error: "nope" });
    expect(await route(facade, { id: 3, method: "constructor" })).toMatchObject({ ok: false, error: "unknown method: constructor" });
  });
});
