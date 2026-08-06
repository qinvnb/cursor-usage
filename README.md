# Cursor Usage · Cursor 用量本地看板

<p align="center">
  <img src="assets/app.png" width="96" alt="Cursor Usage 图标">
</p>

Windows 11 本地桌面看板，读取当前电脑的 Cursor 登录状态，展示计费周期、套餐内额度、
个人按需用量、日期趋势和模型成本。数据只保存在本机。

> [!IMPORTANT]
> 这是非官方社区项目，与 Cursor / Anysphere 无隶属或认可关系。项目使用非公开接口，
> Cursor 更新后接口或登录数据格式可能变化。使用者应自行确认其使用方式符合 Cursor
> 的服务条款。

## 功能

- 首页、个人按需、套餐内、日期和模型多维分析
- 本地 Chart.js 图表，无 CDN 依赖
- 悬浮球与 Windows 11 主屏任务栏组件
- 系统托盘、开机启动、后台定时刷新
- 单实例 IPC、组件异常重启与 Explorer 重启恢复
- 设置备份恢复、7 天脱敏日志和诊断包导出
- 支持本机 Cursor 登录、环境变量或手动 Session Token

## 环境要求

- Windows 11（任务栏组件仅支持主屏任务栏）
- 已安装并登录 Cursor
- Python 3.11–3.13（源码运行/构建；CI 使用 3.13）
- Microsoft Edge WebView2 Runtime（Windows 11 通常已内置）
- 可访问 Cursor 服务的网络

## 直接使用

1. 从 GitHub Releases 下载 `CursorUsage-v1.0.0-win-x64.zip`。
2. 解压完整文件夹，不要只复制 EXE。
3. 运行 `CursorUsage.exe`；应用默认从托盘启动。
4. 从托盘选择“显示看板”或“立即刷新”。

预编译版本不需要安装 Python。首次运行可能触发 Windows SmartScreen，因为社区构建未进行
商业代码签名。

## 从源码运行

```powershell
git clone <your-repository-url>
cd cursor-usage-app
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

常用参数：

```powershell
python run.py --refresh 30      # 后台刷新间隔，单位为秒
python run.py --start-hidden    # 明确使用默认的隐藏启动行为
python run.py --show-window     # 启动后立即显示看板
python run.py --no-tray         # 不启用系统托盘
python run.py --browser         # 使用默认浏览器打开看板
python run.py --port 8765       # 指定本地 HTTP 端口；默认随机端口
```

可选环境变量：`CURSOR_SESSION_TOKEN` / `CURSOR_ACCESS_TOKEN` 可提供会话令牌，
`CURSOR_STATE_DB` 可指定 Cursor `state.vscdb` 路径。

## 构建

开发构建：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_exe.ps1
```

输出位于 `dist\CursorUsage\CursorUsage.exe`。使用文件夹版发布是为了让悬浮球和任务栏组件
快速启动，并可靠结束子进程。构建脚本会备份并恢复本机 `data\`，避免开发时丢失数据。

创建不包含本机数据的 GitHub Release 压缩包：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\package_release.ps1 -Version 1.0.0
```

发布前请确认压缩包内不存在 `data\`。

## 数据与隐私

打包运行时，数据保存在 `CursorUsage.exe` 同目录的 `data\`；源码运行时保存在项目根目录的
`data\`。该目录已被 `.gitignore` 排除。

可能包含：

- `usage.json`：账号用量、邮箱和模型汇总
- `credentials.json`：手动输入的访问/刷新令牌（明文，仅限当前文件系统权限）
- `settings.json`：应用设置
- `logs\`：最长保留 7 天的脱敏日志

不要提交、上传或随发行包分发 `data\`。手动令牌仅应在可信电脑上使用。详细说明见
[SECURITY.md](SECURITY.md)。

使用本机登录状态时，应用会读取 Cursor 的 `state.vscdb`；访问令牌过期且刷新成功后，
可能把新令牌写回该数据库，以保持 Cursor 与看板的登录状态一致。

程序只监听随机端口的 `127.0.0.1`，不会主动将统计数据发送给第三方；网络请求用于访问
Cursor 服务。诊断包不会主动包含凭证、Cookie、Token 或完整用量事件，但分享前仍应检查。

## 测试

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## 项目结构

```text
cursor_usage_app/   Python 桌面应用、HTTP 服务、组件与数据层
web/                看板页面、样式和本地 Chart.js
assets/             多尺寸应用图标
scripts/            图标生成、构建和发布脚本
tests/              单元测试
CursorUsage.spec    PyInstaller 文件夹版配置
```

## 已知限制

- 任务栏组件依赖 Windows 11 Explorer/UI Automation 的当前布局。
- 找不到安全空位时，任务栏组件会隐藏并退避重试，不会移动系统控件。
- 网页视频真全屏时组件会隐藏；普通窗口最大化不会隐藏。
- Cursor 非公开接口变更后，可能需要更新本项目。

## 排障

- 看不到数据：确认 Cursor 已登录，再从托盘执行“立即刷新”。
- 任务栏组件未显示：从托盘选择“重新嵌入”，并检查任务栏左侧是否有可用空间。
- 组件状态异常：从设置或托盘导出诊断包。
- 构建文件被占用：先从托盘退出正在运行的应用。

## 许可证

[MIT](LICENSE)
