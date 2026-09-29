import { L, normalizeLangPref, normalizeThresholds, parseSessionInput, type Report } from "@cursor-usage/core";
import { Fragment } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { AppApi, AppInfo, ComponentStatus, SettingsMap } from "../api";
import { applyLanguage } from "./App";
import { BellIcon, BoxIcon, CloseIcon, GlobeIcon, KeyboardIcon, KeyIcon, MonitorIcon, PowerIcon, SyncIcon } from "./icons";
import { Chip } from "./kit";

interface Props {
  api: AppApi;
  report: Report | null;
  settings: SettingsMap;
  onChange: (settings: SettingsMap) => void;
  onClose: () => void;
  onCredentialsChanged: () => void;
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label class="switch">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} onChange={(e) => onChange((e.target as HTMLInputElement).checked)} />
      <span />
    </label>
  );
}

function NumberField({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  onCommit,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  onCommit: (v: number) => void;
}) {
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  const n = Number(text);
  const invalid = text === "" || !Number.isFinite(n) || n < min || n > max;
  const commit = () => {
    if (!invalid && n !== value) onCommit(n);
    if (invalid) setText(String(value));
  };
  return (
    <div class="field">
      <div>
        <div>{label}</div>
        <div class="hint">{invalid ? L(`请输入 ${min}–${max}`, `Enter ${min}–${max}`) : hint || `${min}–${max}`}</div>
      </div>
      <input
        type="number"
        class={invalid ? "invalid num" : "num"}
        min={min}
        max={max}
        step={step}
        value={text}
        aria-label={label}
        onInput={(e) => setText((e.target as HTMLInputElement).value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
      />
    </div>
  );
}

function ThresholdField({ value, onCommit }: { value: number[]; onCommit: (v: number[]) => void }) {
  const [text, setText] = useState(value.join(", "));
  useEffect(() => setText(value.join(", ")), [value.join(",")]);
  const parsed = text
    .split(/[,，\s]+/)
    .filter(Boolean)
    .map(Number);
  const invalid = !parsed.length || parsed.some((v) => !Number.isFinite(v) || v < 1 || v > 100);
  const commit = () => {
    if (invalid) return setText(value.join(", "));
    const next = normalizeThresholds(parsed).sort((a, b) => a - b);
    if (next.join(",") !== value.join(",")) onCommit(next);
  };
  return (
    <div class="field">
      <div>
        <div>{L("预警阈值（%）", "Alert thresholds (%)")}</div>
        <div class="hint">
          {invalid ? L("请输入 1–100 之间的数字，用逗号分隔", "Numbers from 1 to 100, separated by commas") : L("用逗号分隔，例如 50, 80, 95", "Comma-separated, e.g. 50, 80, 95")}
        </div>
      </div>
      <input
        type="text"
        class={invalid ? "invalid num" : "num"}
        style={{ width: "120px", textAlign: "right" }}
        value={text}
        aria-label={L("预警阈值", "Alert thresholds")}
        onInput={(e) => setText((e.target as HTMLInputElement).value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
      />
    </div>
  );
}

function ToggleField({ label, hint, checked, onChange }: { label: string; hint?: preact.ComponentChildren; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div class="field">
      <div>
        <div>{label}</div>
        {hint && <div class="hint">{hint}</div>}
      </div>
      <Switch checked={checked} onChange={onChange} label={label} />
    </div>
  );
}

function Group({ icon, title, children }: { icon: preact.ComponentChildren; title: string; children: preact.ComponentChildren }) {
  return (
    <div class="group">
      <h3>
        {icon}
        {title}
      </h3>
      {children}
    </div>
  );
}

function dockState(state: string): string {
  const map: Record<string, [string, string]> = {
    running: ["已嵌入任务栏", "Embedded in the taskbar"],
    starting: ["正在嵌入", "Embedding"],
    retrying: ["等待资源管理器", "Waiting for Explorer"],
    hidden: ["暂时隐藏", "Temporarily hidden"],
    stopped: ["未开启", "Off"],
    error: ["出错", "Error"],
  };
  const pair = map[state];
  return pair ? L(pair[0], pair[1]) : state || "—";
}

function dockReason(reason: string): string {
  const map: Record<string, [string, string]> = {
    fullscreen: ["全屏应用运行中", "A fullscreen app is running"],
    "no-uia-confirmed-free-space": ["任务栏没有足够空位", "Not enough free space on the taskbar"],
    "uia-pending": ["正在读取任务栏布局", "Reading the taskbar layout"],
    "vertical-or-nonstandard-taskbar": ["不支持竖向或非标准任务栏", "Vertical or non-standard taskbars are not supported"],
    "taskbar-too-small-or-auto-hidden": ["任务栏自动隐藏或过小", "The taskbar is auto-hidden or too small"],
    "requires-windows-11": ["需要 Windows 11", "Requires Windows 11"],
  };
  const pair = map[reason];
  return pair ? L(pair[0], pair[1]) : "";
}

const shortcuts = (): [string, string][] => [
  ["1 – 6", L("切换页面", "Switch page")],
  ["R", L("立即刷新", "Refresh now")],
  ["L", L("切换中文 / English", "Toggle English / 中文")],
  [",", L("打开设置", "Open settings")],
  ["Esc", L("关闭面板", "Close panel")],
];

export function SettingsDrawer({ api, report, settings, onChange, onClose, onCredentialsChanged }: Props) {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [status, setStatus] = useState<ComponentStatus | null>(null);
  const [token, setToken] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [message, setMessage] = useState<{ text: string; error?: boolean } | null>(null);
  const caps = api.capabilities;

  useEffect(() => {
    api.appInfo().then(setInfo).catch(() => {});
    let timer: ReturnType<typeof setInterval> | undefined;
    if (caps.desktopWidgets) {
      const load = () => api.componentStatus().then(setStatus).catch(() => {});
      load();
      timer = setInterval(load, 3000);
    }
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => {
      if (timer) clearInterval(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  const save = async (patch: SettingsMap) => {
    try {
      onChange(await api.saveSettings(patch));
    } catch (error) {
      setMessage({ text: `${L("保存失败", "Save failed")}: ${(error as Error).message}`, error: true });
    }
  };

  const saveToken = async () => {
    try {
      const parsed = parseSessionInput(token);
      await api.saveCredentials({ accessToken: parsed.accessToken, refreshToken: refreshToken.trim() || undefined, email: parsed.emailHint || undefined });
      onChange(await api.saveSettings({ authSource: "manual" }));
      setToken("");
      setRefreshToken("");
      setInfo(await api.appInfo());
      setMessage({ text: L("已保存，正在同步", "Saved, syncing") });
      onCredentialsChanged();
    } catch (error) {
      setMessage({ text: (error as Error).message, error: true });
    }
  };

  const clearToken = async () => {
    onChange(await api.clearCredentials());
    setInfo(await api.appInfo());
    setMessage({ text: L("已清除手动凭证，改用本机 Cursor 登录", "Manual credentials cleared; using the local Cursor sign-in") });
    onCredentialsChanged();
  };

  const exportReport = async () => {
    if (!report) return;
    const path = await api.exportFile(L("用量报告", "usage-report"), "json", JSON.stringify(report, null, 2));
    setMessage({ text: `${L("已导出", "Exported")}: ${path}` });
  };

  const setLanguage = (value: string) => {
    const pref = normalizeLangPref(value);
    applyLanguage(pref);
    void save({ language: pref });
  };

  const dock = status?.taskbarWidget || {};
  const dockOk = dock.state === "running";
  const s = settings;
  const thresholds: number[] = Array.isArray(s.alertThresholds) && s.alertThresholds.length ? s.alertThresholds : [80, 95];

  return (
    <>
      <div class="scrim" onClick={onClose} />
      <aside class="drawer" role="dialog" aria-label={L("设置", "Settings")}>
        <div class="drawer-head">
          <h2>{L("设置", "Settings")}</h2>
          <button class="icon-btn" aria-label={L("关闭", "Close")} onClick={onClose}>
            <CloseIcon />
          </button>
        </div>
        <div class="drawer-body">
          {message && (
            <div class="banner" style={message.error ? undefined : { background: "var(--c-included-soft)", borderColor: "transparent" }}>
              {message.text}
            </div>
          )}

          <Group icon={<GlobeIcon />} title="语言 / Language">
            <div class="field">
              <div>
                <div>{L("界面语言", "Display language")}</div>
                <div class="hint">{L("自动：跟随系统或 Cursor 的显示语言", "Auto follows the system or Cursor display language")}</div>
              </div>
              <select value={normalizeLangPref(s.language)} onChange={(e) => setLanguage((e.target as HTMLSelectElement).value)}>
                <option value="auto">{L("自动", "Auto")}</option>
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </div>
          </Group>

          {caps.desktopWidgets && (
            <Group icon={<MonitorIcon />} title={L("桌面组件", "Desktop widgets")}>
              <ToggleField
                label={L("任务栏组件", "Taskbar widget")}
                hint={
                  s.dockEnabled ? (
                    <>
                      <Chip tone={dockOk ? "ok" : "warn"}>{dockState(dock.state || "")}</Chip>
                      {dock.reason && !dockOk && dockReason(dock.reason) ? ` ${dockReason(dock.reason)}` : ""}
                    </>
                  ) : (
                    L("在 Windows 11 任务栏空位显示用量", "Show usage in free space on the Windows 11 taskbar")
                  )
                }
                checked={!!s.dockEnabled}
                onChange={(v) => save({ dockEnabled: v })}
              />
              <ToggleField
                label={L("悬浮球", "Floating ball")}
                hint={L("可拖动；右键打开菜单", "Drag to move; right-click for the menu")}
                checked={!!s.ballEnabled}
                onChange={(v) => save({ ballEnabled: v })}
              />
              <details>
                <summary class="muted" style={{ cursor: "pointer", padding: "8px 0" }}>
                  {L("外观", "Appearance")}
                </summary>
                <NumberField label={L("悬浮球大小", "Ball size")} value={s.ballSize ?? 120} min={72} max={240} step={4} onCommit={(v) => save({ ballSize: v })} />
                <NumberField label={L("悬浮球不透明度 %", "Ball opacity %")} value={s.ballOpacity ?? 100} min={40} max={100} step={5} onCommit={(v) => save({ ballOpacity: v })} />
                <NumberField label={L("悬浮球字号", "Ball font size")} value={s.ballFontSize ?? 14} min={8} max={28} onCommit={(v) => save({ ballFontSize: v })} />
                <NumberField label={L("悬浮球圆环宽度", "Ball ring width")} value={s.ballRingWidth ?? 7} min={3} max={18} onCommit={(v) => save({ ballRingWidth: v })} />
                <NumberField label={L("任务栏组件宽度", "Taskbar widget width")} value={s.dockWidth ?? 220} min={180} max={520} step={10} onCommit={(v) => save({ dockWidth: v })} />
                <ToggleField label={L("任务栏紧凑模式", "Compact taskbar widget")} checked={!!s.dockCompact} onChange={(v) => save({ dockCompact: v })} />
              </details>
              {s.dockEnabled && (
                <div class="row-actions">
                  <button class="btn" onClick={() => api.reembedDock()}>
                    {L("重新嵌入任务栏", "Re-embed in taskbar")}
                  </button>
                </div>
              )}
            </Group>
          )}

          <Group icon={<SyncIcon />} title={L("同步", "Sync")}>
            <NumberField
              label={L("自动刷新间隔（秒）", "Auto refresh interval (s)")}
              hint={L("每 10 分钟自动做一次含模型明细的完整同步", "A full sync with model details runs every 10 minutes")}
              value={s.refreshSeconds ?? 60}
              min={15}
              max={3600}
              step={5}
              onCommit={(v) => save({ refreshSeconds: v })}
            />
            {caps.updates && (
              <ToggleField
                label={L("检查更新", "Check for updates")}
                hint={
                  info
                    ? info.update
                      ? L(`当前 v${info.version}，可更新到 v${info.update.version}`, `v${info.version} installed, v${info.update.version} available`)
                      : L(`当前 v${info.version}`, `v${info.version} installed`)
                    : undefined
                }
                checked={!!s.checkUpdates}
                onChange={(v) => save({ checkUpdates: v })}
              />
            )}
            {info?.update && (
              <div class="row-actions">
                <button class="btn" onClick={() => api.openUrl(info.update!.url)}>
                  {L("打开下载页", "Open download page")}
                </button>
              </div>
            )}
          </Group>

          <Group icon={<BellIcon />} title={L("预警", "Alerts")}>
            <ToggleField
              label={L("额度预警", "Usage alerts")}
              hint={L(
                "超过阈值，或按当前节奏 3 天内用完时提醒；每个周期每档只提醒一次",
                "Notify when a threshold is crossed or usage will run out within 3 days; once per level per cycle",
              )}
              checked={s.alertsEnabled !== false}
              onChange={(v) => save({ alertsEnabled: v })}
            />
            <ThresholdField value={thresholds} onCommit={(v) => save({ alertThresholds: v })} />
            <NumberField
              label={L("个人按需预算（$）", "On-demand budget ($)")}
              hint={L("低于 Cursor 上限时，按这个预算计算预警；0 表示不使用", "Alerts use this budget when it is below the Cursor limit; 0 = off")}
              value={Number(s.onDemandBudget || 0)}
              min={0}
              max={100000}
              step={10}
              onCommit={(v) => save({ onDemandBudget: v })}
            />
          </Group>

          {caps.autostart && (
            <Group icon={<PowerIcon />} title={L("启动", "Startup")}>
              <ToggleField label={L("开机自动启动", "Launch at sign-in")} checked={!!s.launchAtStartup} onChange={(v) => save({ launchAtStartup: v })} />
              <ToggleField label={L("启动时只显示托盘", "Start in the tray")} checked={s.startHidden !== false} onChange={(v) => save({ startHidden: v })} />
            </Group>
          )}

          <Group icon={<KeyIcon />} title={L("账号", "Account")}>
            <div class="field">
              <div>{L("凭证来源", "Credentials")}</div>
              <select value={s.authSource === "manual" ? "manual" : "auto"} onChange={(e) => save({ authSource: (e.target as HTMLSelectElement).value })}>
                <option value="auto">{L("本机 Cursor 登录", "Local Cursor sign-in")}</option>
                <option value="manual">{L("手动凭证", "Manual credentials")}</option>
              </select>
            </div>
            {caps.localTokenRefresh && (
              <ToggleField
                label={L("令牌过期时由本工具刷新", "Refresh expired tokens here")}
                hint={L("默认关闭：Cursor 运行时会自己续期。开启后会把新令牌写回 Cursor", "Off by default: Cursor renews tokens itself. When on, new tokens are written back to Cursor")}
                checked={!!s.persistLocalRefresh}
                onChange={(v) => save({ persistLocalRefresh: v })}
              />
            )}
            <div class="field stack">
              <div>
                <div>{L("手动凭证", "Manual credentials")}</div>
                <div class="hint">
                  {info?.hasManualCredentials
                    ? `${L("已保存", "Saved")} ${info.tokenPreview}${info.manualEmail ? ` · ${info.manualEmail}` : ""}`
                    : L("粘贴 access token 或 WorkosCursorSessionToken", "Paste an access token or WorkosCursorSessionToken")}
                </div>
              </div>
              <textarea
                value={token}
                placeholder={L("eyJ… 或 WorkosCursorSessionToken=…", "eyJ… or WorkosCursorSessionToken=…")}
                onInput={(e) => setToken((e.target as HTMLTextAreaElement).value)}
              />
              <input
                type="password"
                placeholder={L("refresh token（可选）", "refresh token (optional)")}
                value={refreshToken}
                onInput={(e) => setRefreshToken((e.target as HTMLInputElement).value)}
              />
              <div class="row-actions">
                <button class="btn primary" disabled={!token.trim()} onClick={saveToken}>
                  {L("保存凭证", "Save credentials")}
                </button>
                {info?.hasManualCredentials && (
                  <button class="btn" onClick={clearToken}>
                    {L("清除", "Clear")}
                  </button>
                )}
              </div>
            </div>
          </Group>

          <Group icon={<BoxIcon />} title={L("数据", "Data")}>
            <div class="row-actions">
              <button class="btn" disabled={!report} onClick={exportReport}>
                {L("导出完整报告（JSON）", "Export full report (JSON)")}
              </button>
              {caps.diagnostics && (
                <button class="btn" onClick={async () => setMessage({ text: `${L("诊断包已导出", "Diagnostics exported")}: ${await api.exportDiagnostics()}` })}>
                  {L("导出诊断包", "Export diagnostics")}
                </button>
              )}
            </div>
            {info && (
              <div class="hint" style={{ paddingBottom: "8px" }}>
                {L("数据目录", "Data folder")}: {info.dataDir}
              </div>
            )}
          </Group>

          <Group icon={<KeyboardIcon />} title={L("快捷键", "Shortcuts")}>
            <div class="shortcuts">
              {shortcuts().map(([k, v]) => (
                <Fragment key={k}>
                  <span>
                    <kbd>{k}</kbd>
                  </span>
                  <span>{v}</span>
                </Fragment>
              ))}
            </div>
          </Group>
        </div>
      </aside>
    </>
  );
}
