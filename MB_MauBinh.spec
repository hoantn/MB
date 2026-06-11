# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules
from glob import glob

hiddenimports = ['requests', 'cbor2', 'nacl', 'websocket', 'PIL', 'cv2', 'numpy', 'imagehash']
hiddenimports += [
    'PySide6',
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtNetwork',
]
hiddenimports += collect_submodules('shiboken6')

binaries = []
binaries += collect_dynamic_libs('PySide6')
binaries += collect_dynamic_libs('shiboken6')

datas = [
    ('vision\\opp', 'vision\\opp'),
    ('chrome_ext', 'chrome_ext'),
    ('icon.ico', '.'),
]
datas += [(p, 'config') for p in glob('config/config*.json')]
datas += collect_data_files('PySide6')
datas += collect_data_files('shiboken6')

a = Analysis(
    ['ui2\\main.py'],
    pathex=[],
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
    name='MB_MauBinh',
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
    name='MB_MauBinh',
)
