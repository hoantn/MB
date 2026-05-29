# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import (
    collect_submodules,
    collect_data_files,
    collect_dynamic_libs,
)

block_cipher = None

# --- Hidden imports: gom chắc các module hay bị thiếu khi build exe ---
hiddenimports = []
hiddenimports += [
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtNetwork",
]
hiddenimports += collect_submodules("shiboken6")
hiddenimports += collect_submodules("nacl")
hiddenimports += collect_submodules("cbor2")
hiddenimports += collect_submodules("ui2")

# Nếu project anh có các package này thì giữ; nếu không có thì không sao (PyInstaller bỏ qua)
hiddenimports += collect_submodules("engine")
hiddenimports += collect_submodules("browser")
hiddenimports += collect_submodules("capture")
hiddenimports += ["cv2"]

# --- Datas: đúng yêu cầu của anh ---
# - vision/opp là THƯ MỤC
# - config/config.json là FILE
# - icon.ico là FILE
datas = [
    ("vision/opp", "vision/opp"),
    ("chrome_ext", "chrome_ext"),
    ("config/config.json", "config"),
	("config/games", "config/games"),
    ("icon.ico", "."),
]

# --- Binaries/Datas bổ sung cho libs native (nacl/cbor2 thường là pyd/dll) ---
binaries = []
binaries += collect_dynamic_libs("nacl")
binaries += collect_dynamic_libs("cbor2")
binaries += collect_dynamic_libs("PySide6")
binaries += collect_dynamic_libs("shiboken6")

# PySide6/Qt plugins: gom data để tránh lỗi runtime (đen màn hình, missing plugin)
datas += collect_data_files("PySide6")
datas += collect_data_files("shiboken6")

a = Analysis(
    ["ui2/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "unittest",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MBTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,     # Windows không có strip.exe -> set False
    upx=False,        # nếu bị AV/UPX lỗi thì đổi False
    console=False,
	icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="MBTool",
)
