# -*- mode: python ; coding: utf-8 -*-
import shutil
import subprocess
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


LOCAL_DEP_DIRS = [
    Path(".build_deps"),
    Path(".build_dingtalk_only"),
]


def local_dep_paths():
    paths = []
    for path in LOCAL_DEP_DIRS:
        if path.exists():
            resolved = str(path.resolve())
            paths.append(resolved)
            if resolved not in sys.path:
                sys.path.insert(0, resolved)
    return paths


def ensure_webui_dist():
    index_path = Path("webui") / "dist" / "index.html"
    package_json = Path("webui") / "package.json"
    package_lock = Path("webui") / "package-lock.json"
    if index_path.exists() or not package_json.exists() or not package_lock.exists():
        return
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("npm is required to build webui/dist before packaging.")
    subprocess.run([npm, "ci"], cwd="webui", check=True)
    subprocess.run([npm, "run", "build"], cwd="webui", check=True)


def ensure_macos_icon():
    icon_dir = Path("build") / "macos" / "app_icon.iconset"
    icon_file = Path("build") / "macos" / "app_icon.icns"
    source = Path("assets") / "app_icon.png"
    if sys.platform != "darwin" or icon_file.exists() or not source.exists():
        return icon_file
    sips = shutil.which("sips")
    iconutil = shutil.which("iconutil")
    if not sips or not iconutil:
        return None
    icon_dir.mkdir(parents=True, exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        subprocess.run(
            [sips, "-z", str(size), str(size), str(source), "--out", str(icon_dir / f"icon_{size}x{size}.png")],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                sips,
                "-z",
                str(size * 2),
                str(size * 2),
                str(source),
                "--out",
                str(icon_dir / f"icon_{size}x{size}@2x.png"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
    subprocess.run([iconutil, "-c", "icns", str(icon_dir), "-o", str(icon_file)], check=True)
    return icon_file


def app_version():
    try:
        from build_version import APP_VERSION

        return str(APP_VERSION).lstrip("v") or "0.0.0"
    except Exception:
        return "1.5.7"


ensure_webui_dist()
macos_icon = ensure_macos_icon()
version = app_version()
pathex = local_dep_paths()

datas = [
    ("assets/app_icon.png", "assets"),
    ("webui/dist", "webui/dist"),
]
binaries = []
hiddenimports = ["Crypto.Cipher.AES"]

for package in ("lark_oapi", "customtkinter", "webview", "pystray", "PIL", "dingtalk_stream", "qrcode", "questionary"):
    tmp_ret = collect_all(package)
    datas += tmp_ret[0]
    binaries += tmp_ret[1]
    hiddenimports += tmp_ret[2]


a = Analysis(
    ["nga_wolf_webgui.py"],
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
    [],
    exclude_binaries=True,
    name="NGA-Wolf-Watcher",
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
    name="NGA-Wolf-Watcher",
)

app = BUNDLE(
    coll,
    name="NGA-Wolf-Watcher.app",
    icon=str(macos_icon) if macos_icon else None,
    bundle_identifier="com.huangbwww.ngawolfwatcher",
    info_plist={
        "CFBundleName": "NGA Wolf Watcher",
        "CFBundleDisplayName": "NGA Wolf Watcher",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "NSHighResolutionCapable": "True",
    },
)
