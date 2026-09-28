# 安全说明

## 敏感数据

程序会读取本机 Cursor 登录状态。启用手动凭证时，访问令牌会保存在程序目录下的
`data/credentials.json`，内容使用 Windows DPAPI 按当前用户加密（其他用户或其他电脑
无法解密；同一用户下运行的程序仍可解密）。该文件及整个 `data/` 目录不得上传、提交或
随发行包分发。

诊断包会对常见令牌、Cookie 和敏感字段脱敏，但提交前仍建议人工检查内容。

本地 HTTP 服务只绑定 `127.0.0.1`，并校验 Host/Origin 以阻止跨站请求和 DNS Rebinding。
但同一用户权限下运行的本地进程仍可能访问本地接口，因此不要与不可信程序同时运行。

使用本机 Cursor 登录状态时默认只读 `state.vscdb`。只有在设置中开启“令牌过期时由本工具
刷新并写回 Cursor”后，才会刷新令牌并写回该数据库。

## 报告漏洞

请优先使用 GitHub 的 Private vulnerability reporting / Security Advisory 私下报告安全问题。
不要在公开 Issue 中粘贴令牌、Cookie、邮箱、`state.vscdb`、`credentials.json`、日志或诊断包。

## 支持范围

仅维护当前主分支。该项目使用 Cursor 的非公开接口，Cursor 更新后可能暂时不可用。
