# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)
icon = root / "assets" / "app.ico"
dashboard = root / "web" / "dist" / "index.html"
if not dashboard.is_file():
    raise SystemExit("web/dist/index.html is missing: run `npm ci && npm run build` first")

a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "web" / "dist"), "web/dist"),
        (str(root / "assets"), "assets"),
    ],
    hiddenimports=[
        "webview",
        "pystray",
        "PIL",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageChops",
        "cursor_usage_app",
        "cursor_usage_app.bridge",
        "cursor_usage_app.store",
        "cursor_usage_app.tray",
        "cursor_usage_app.updates",
        "cursor_usage_app.autostart",
        "cursor_usage_app.diagnostics",
        "cursor_usage_app.instance",
        "cursor_usage_app.logging_setup",
        "cursor_usage_app.i18n",
        "cursor_usage_app.icon_art",
        "cursor_usage_app.native",
        "cursor_usage_app.native.win",
        "cursor_usage_app.native.ball",
        "cursor_usage_app.native.taskbar",
        "cursor_usage_app.native.ui_thread",
        "uiautomation",
        "comtypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The floating ball is a native window now; Tk is no longer used.
    # numpy (~26 MB) is only an optional extra of comtypes / Pillow; nothing here needs it.
    excludes=["tkinter", "_tkinter", "PIL.ImageTk", "numpy"],
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
