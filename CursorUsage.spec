# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
icon = root / "assets" / "app.ico"

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "web"), "web"),
        (str(root / "assets"), "assets"),
    ],
    hiddenimports=[
        "webview",
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "cursor_usage_app",
        "cursor_usage_app.fetch",
        "cursor_usage_app.server",
        "cursor_usage_app.usage",
        "cursor_usage_app.tray",
        "cursor_usage_app.store",
        "cursor_usage_app.ball_tk",
        "cursor_usage_app.win_ui",
        "cursor_usage_app.autostart",
        "cursor_usage_app.component_supervisor",
        "cursor_usage_app.diagnostics",
        "cursor_usage_app.instance",
        "cursor_usage_app.logging_setup",
        "cursor_usage_app.taskbar_widget",
        "uiautomation",
        "comtypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CursorUsage",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon) if icon.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CursorUsage",
)
