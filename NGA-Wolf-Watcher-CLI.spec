# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


LOCAL_DEP_DIRS = [
    Path('.build_deps'),
    Path('.build_dingtalk_only'),
]

pathex = []
for path in LOCAL_DEP_DIRS:
    if path.exists():
        resolved = str(path.resolve())
        pathex.append(resolved)
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

datas = []
binaries = []
hiddenimports = ['Crypto.Cipher.AES']

for package in ('lark_oapi', 'PIL', 'qrcode', 'Crypto', 'dingtalk_stream', 'questionary', 'prompt_toolkit'):
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]


a = Analysis(
    ['ngawolf_cli.py'],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['customtkinter', 'webview', 'pystray', 'tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ngawolf',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    name='ngawolf',
)
