# Cursor Usage · Cursor 用量本地看板

<p align="center">
  <img src="assets/app.png" width="96" alt="Cursor Usage 图标">
</p>

读取当前电脑的 Cursor 登录状态，展示计费周期、套餐内额度、个人按需用量、每日趋势和模型成本。
有两种形态，共用同一套数据核心和看板：

- **桌面版**（Windows 11）：托盘、悬浮球、任务栏组件和独立看板窗口
- **Cursor 插件**：状态栏常驻显示用量，命令面板打开看板，跟随编辑器主题

数据只保存在本机。

> [!IMPORTANT]
> 这是非官方社区项目，与 Cursor / Anysphere 无隶属或认可关系。项目使用非公开接口，
> Cursor 更新后接口或登录数据格式可能变化。使用者应自行确认其使用方式符合 Cursor
> 的服务条款。

## 功能

- 六个分析页：总览、个人按需、套餐内、日期、模型、历史周期
  - 套餐内按 Cursor 的两个独立额度池拆分：Cursor 模型（Auto / Composer）与其他模型（API）
  - 环形额度进度（带时间进度刻度）与周期末预估、带迷你趋势的指标卡、与上周期同一天的对比
  - 每日趋势（可切换累计 / Token）、7 日均线、星期分布、使用时段热力图（星期 × 小时）
  - 模型成本、Token 用量与构成、缓存命中率、每次请求成本、输出 / 输入比；按厂商着色
  - 点击任一天或任一模型，从右侧打开详情（当天模型构成 / 模型每日趋势与 token 构成）
- 快捷键：`1`–`6` 切换页面、`R` 刷新、`L` 切换中文 / English、`,` 设置、`Esc` 关闭面板
- 中文 / English：顶栏右上角的地球图标一键切换；设置里可选"自动"（跟随系统或 Cursor 的显示语言）。
  托盘、悬浮球、任务栏组件、提醒和插件状态栏同步切换
- 浅色 / 深色主题；表格排序、导出 CSV，导出完整报告 JSON
- 可配置预警阈值与个人按需预算
- 悬浮球与 Windows 11 主屏任务栏组件，和看板在同一个进程里运行
- 系统托盘（图标即用量仪表，接近上限时变色；菜单内显示已用 / 剩余与 Token）、开机启动、后台定时刷新
- 额度预警通知：两个额度池或个人按需达到 80% / 95%，或按当前节奏 3 天内将用完时提醒
- 支持本机 Cursor 登录、环境变量或手动 Session Token（DPAPI 加密保存）
- 低资源占用：单进程，组件事件驱动，用量事件增量拉取，数据未变化时不写盘

## 架构

```text
CursorUsage.exe（单进程）
├─ 主线程：pywebview 窗口，加载 web/dist/index.html
│    ├─ packages/ui    看板界面（Preact）
│    └─ packages/core  数据核心（TypeScript）：登录解析、拉取、重试、增量事件缓存、
│                       聚合、预警、历史快照。所有 I/O 通过 Host 接口
├─ cursor_usage_app/bridge.py   Host 的 Python 实现（js_api）：HTTP、读写 state.vscdb、
│                               凭证、数据文件、通知
├─ 原生 UI 线程：一个 Win32 消息循环同时承载任务栏组件和悬浮球
└─ 托盘线程
```

Cursor 插件（`packages/extension`）复用同一个 core 与看板：引擎运行在扩展进程里（关掉面板
状态栏也照常更新），用 Node 内置的 `fetch` 和 `node:sqlite` 实现 `Host`，看板通过
`postMessage` 接收数据快照。

## Cursor 插件

```powershell
npm ci
npm run package:extension                      # 生成 release\cursor-usage-<版本>.vsix
cursor --install-extension release\cursor-usage-0.1.0.vsix
```

也可以在 Cursor 的扩展面板里选择“从 VSIX 安装…”。安装后状态栏右侧会出现用量，点击或执行命令
`Cursor Usage: 打开用量看板`。设置项见 [packages/extension/README.md](packages/extension/README.md)。

插件以只读方式读取 `state.vscdb`（依赖 Cursor 内置的 `node:sqlite`，数 GB 的数据库也只需
几毫秒），手动凭证保存在 VS Code 的 SecretStorage。

发布到 Open VSX（Cursor 的扩展市场）：在 [open-vsx.org](https://open-vsx.org) 创建 namespace
`qinvnb` 和访问令牌后执行

```powershell
$env:OVSX_PAT = "<token>"; npm run build; npm run publish:ovsx -w cursor-usage
```

## 环境要求

- Windows 11（任务栏组件仅支持主屏任务栏）
- 已安装并登录 Cursor
- Microsoft Edge WebView2 Runtime（Windows 11 通常已内置）
- 从源码运行 / 构建：Python 3.11–3.13、Node.js 22.5+（测试用到 `node:sqlite`）

## 直接使用

1. 从 GitHub Releases 下载最新的 `CursorUsage-v<版本>-win-x64.zip`。
2. 解压完整文件夹，不要只复制 EXE。
3. 运行 `CursorUsage.exe`；应用默认从托盘启动。
4. 从托盘选择“显示看板”或“立即刷新”。

首次运行可能触发 Windows SmartScreen，因为社区构建未进行商业代码签名。

## 从源码运行

```powershell
git clone https://github.com/qinvnb/cursor-usage.git
cd cursor-usage
npm ci
npm run build                      # 生成 web/dist/index.html
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py --show-window
```

常用参数：

```powershell
python run.py --refresh 30      # 自动刷新间隔（秒），会写入设置
python run.py --show-window     # 启动后立即显示看板（默认只进托盘）
python run.py --no-tray         # 不启用系统托盘，关闭窗口即退出
python run.py --debug           # 打开 WebView 开发者工具
```

只改界面时可以不启动桌面端：`npm run dev` 会在浏览器里用测试数据运行真实的数据核心。

可选环境变量：`CURSOR_SESSION_TOKEN` / `CURSOR_ACCESS_TOKEN` 可提供会话令牌，
`CURSOR_STATE_DB` 可指定 Cursor `state.vscdb` 路径。

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

依次运行 TypeScript 测试、构建看板、Python 测试和 PyInstaller，输出
`dist\CursorUsage\CursorUsage.exe`。脚本会备份并恢复 `dist\CursorUsage\data\`。

创建不包含本机数据的 Release 压缩包（版本号默认取 `cursor_usage_app/__init__.py`）：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_release.ps1
```

## 数据与隐私

打包运行时，数据保存在 `CursorUsage.exe` 同目录的 `data\`；源码运行时保存在项目根目录的
`data\`（已被 `.gitignore` 排除）。可能包含：

- `usage.json`：账号用量、邮箱和模型汇总
- `summary.json`：托盘、悬浮球、任务栏组件使用的精简摘要（含邮箱）
- `history.json`：已结束计费周期的合计快照（最多 24 个）
- `alerts.json`：本周期已发送过的预警
- `credentials.json`：手动输入的令牌，使用 Windows DPAPI 按当前用户加密
- `settings.json`：应用设置
- `exports\`：导出的 CSV；`logs\`：最长保留 7 天的脱敏日志

不要提交、上传或分发 `data\`。详细说明见 [SECURITY.md](SECURITY.md)。

使用本机登录状态时，应用只读取 Cursor 的 `state.vscdb`。本机令牌过期时默认**不会**
自行刷新（Cursor 运行时会自己续期），以免刷新令牌轮换导致 Cursor 被登出；需要时可在设置
中开启“令牌过期时由本工具刷新”。

应用不监听任何网络端口：看板页面通过 pywebview 的进程内桥接访问本地功能，桥接只允许
访问 `api2.cursor.sh` 和 `cursor.com`。可选的“检查更新”（默认关闭）每天最多访问一次
GitHub Releases，不上传任何用量数据。

刷新连续失败时会自动退避（30 秒起，最长 15 分钟），标题栏显示下次重试时间；手动刷新不受
退避限制。

## 测试

```powershell
npm test                                            # 数据核心（含与旧 Python 实现逐字段比对的 golden 测试）
npm run typecheck
python -m unittest discover -s tests -p "test_*.py" # 桥接、数据文件、原生组件、单实例
```

资源占用可在应用运行时测量：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\measure_cpu.ps1 -Seconds 300
```

## 项目结构

```text
packages/core/      数据核心（TypeScript，平台无关）
packages/ui/        看板界面，构建为单文件 web/dist/index.html
packages/extension/ Cursor 插件：NodeHost、状态栏、命令、Webview 面板
cursor_usage_app/   桌面端：bridge.py、store.py、托盘、单实例、native/（任务栏组件、悬浮球）
tests/              Python 测试
scripts/            构建、发布、资源占用测量
```

## 已知限制

- 任务栏组件依赖 Windows 11 Explorer/UI Automation 的当前布局；找不到安全空位时会隐藏并重试。
- 全屏视频或演示时组件会隐藏；普通窗口最大化不会。
- Cursor 非公开接口变更后，可能需要更新本项目。

## 排障

- 看不到数据：确认 Cursor 已登录，再从托盘执行“立即刷新”。
- 任务栏组件未显示：在设置中查看它的状态说明，或从托盘选择“重新嵌入”。
- 其他问题：在设置或托盘中导出诊断包。

## 许可证

[MIT](LICENSE)
