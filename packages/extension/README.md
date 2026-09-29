# Cursor Usage · Dashboard

See your Cursor usage without leaving the editor. The status bar shows your included usage or
on-demand spend at a glance; click it for a full dashboard. English and 中文.

> Unofficial community project, not affiliated with Cursor / Anysphere. It relies on Cursor's
> non-public APIs and may need an update when Cursor changes them.

[中文说明](#中文说明)

## Features

- **Status bar**: `Plan Auto x% · API y%` or `On-demand $x / $y`, coloured when a threshold is
  crossed. Hover for both included pools (Cursor models / other models), on-demand spend and this
  cycle's tokens
- **Dashboard** (`Cursor Usage: Open Usage Dashboard`): quota rings with end-of-cycle projection,
  daily trend (cost / tokens), on-demand and included breakdowns, activity heatmap, model costs,
  tokens and cache hit rate, past cycles. Follows the editor theme
- **Included usage split into Cursor's two pools**: Cursor models (Auto / Composer) and other
  models (API), each with its own percentage, pace and model list
- **Alerts** when a pool or on-demand usage crosses a threshold (default 80% / 95%), exceeds your
  own on-demand budget, or will run out within 3 days at the current pace
- Commands: `Refresh Usage Now`, `Copy Usage Summary`

## Data & privacy

- Reads the current Cursor sign-in from `state.vscdb` **read-only**; never writes it back
- Talks only to `api2.cursor.sh` and `cursor.com`
- Usage data stays in the extension's global storage; manual credentials go to VS Code's
  encrypted SecretStorage
- Needs Cursor's built-in SQLite support (present in recent Cursor versions)

## Settings

| Setting | Default | Description |
|---|---|---|
| `cursorUsage.language` | `auto` | Display language: auto (follow Cursor) / zh / en |
| `cursorUsage.refreshSeconds` | 120 | Auto refresh interval (seconds) |
| `cursorUsage.statusBar` | `auto` | Status bar content: auto / ondemand / included / both / hidden |
| `cursorUsage.alerts.enabled` | true | Enable alerts |
| `cursorUsage.alerts.thresholds` | [80, 95] | Alert thresholds (%) |
| `cursorUsage.onDemandBudget` | 0 | Personal on-demand budget in USD; 0 = off |
| `cursorUsage.stateDbPath` | empty | Path to `state.vscdb`, if not found automatically |

## FAQ

- **Nothing appears in the status bar after installing**: Cursor 3.x glass mode disables
  third-party extensions; use classic mode.
- Running the [desktop app](https://github.com/qinvnb/cursor-usage) as well? Both fetch on their
  own; raise the refresh interval of one of them.

---

## 中文说明

在 Cursor 里直接查看自己的用量：状态栏常驻显示套餐内额度或个人按需用量，点击打开完整看板。

> 非官方社区项目，与 Cursor / Anysphere 无隶属关系；使用 Cursor 的非公开接口，Cursor 更新后可能需要升级本插件。

### 功能

- **状态栏**：显示「套餐 Auto x% · API y%」或「按需 $x / $y」，超过预警阈值时变色；悬停查看
  两个套餐内额度池（Cursor 模型 / 其他模型）、个人按需和本周期 Token 明细
- **用量看板**（命令 `Cursor Usage: 打开用量看板`）：额度环形进度与周期末预估、每日趋势（金额 / Token）、
  个人按需 / 套餐内分析、日期与使用时段热力图、模型成本、Token 与缓存命中率、历史周期对比；跟随编辑器主题
- **预警通知**：两个额度池或个人按需超过阈值（默认 80% / 95%）、超过自定义按需预算，
  或按当前节奏 3 天内用完时提醒
- 命令：`刷新用量`、`复制用量摘要`

### 数据与隐私

- 以**只读**方式读取当前 Cursor 的登录状态（`state.vscdb`），不会写回
- 只访问 `api2.cursor.sh` 和 `cursor.com`
- 用量数据保存在插件的全局存储目录；手动凭证保存在 VS Code 的加密 SecretStorage
- 需要 Cursor 内置的 SQLite 支持（较新的 Cursor 版本均已具备）

### 常见问题

- **装好后状态栏没有出现**：Cursor 3.x 的 glass 模式会禁用第三方插件，请在 classic 模式下使用。
- 同时使用 [Cursor Usage 桌面版](https://github.com/qinvnb/cursor-usage) 时，两者各自拉取数据，
  可以把其中一个的刷新间隔调大。设置项见上方英文表格。
