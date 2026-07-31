# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_all

# 本文件所在目录（PyInstaller 提供 SPECPATH，与 CWD 无关，保证任意目录下都能打包）
ROOT = SPECPATH

# curl_cffi 含编译二进制（_wrapper.pyd + libcurl DLL），必须整体收集
cffi_datas, cffi_binaries, cffi_hidden = collect_all('curl_cffi')

a = Analysis(
    [os.path.join(ROOT, 'desktop', 'run.py')],
    pathex=[os.path.join(ROOT, 'standalone_build'), os.path.join(ROOT, 'desktop')],
    binaries=cffi_binaries,
    datas=[(os.path.join(ROOT, 'desktop', 'web', 'index.html'), 'web'),
           (os.path.join(ROOT, 'standalone_build', 'sources.json'), '.')] + cffi_datas,
    hiddenimports=cffi_hidden + ['chardet'],
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
    name='mybooks-book-source-app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
