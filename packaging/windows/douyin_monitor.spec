# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH).parents[1]

datas = [
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "locales"), "locales"),
    (str(ROOT / "config" / "default_settings.json"), "config"),
    (str(ROOT / "config" / "language.json"), "config"),
    (str(ROOT / "crawlers" / "douyin" / "web" / "config.yaml"), "crawlers/douyin/web"),
    (str(ROOT / "crawlers" / "tiktok" / "web" / "config.yaml"), "crawlers/tiktok/web"),
    (str(ROOT / "crawlers" / "tiktok" / "app" / "config.yaml"), "crawlers/tiktok/app"),
]

hiddenimports = [
    "flet",
    "httpx",
    "yaml",
    "loguru",
    "PIL",
    "qrcode",
]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    name="DouyinMonitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="DouyinMonitor",
)
