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

datas = [('.\\assets\\app_icon.ico', 'assets'), ('.\\assets\\app_icon.png', 'assets')]
binaries = []
hiddenimports = ['Crypto.Cipher.AES']
tmp_ret = collect_all('lark_oapi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('dingtalk_stream')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['nga_wolf_gui.py'],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NGA-Wolf-Watcher-Classic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\app_icon.ico'],
)
