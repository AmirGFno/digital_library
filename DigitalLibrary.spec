# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition (portable single-file Windows executable).

This is the edition people download as one EXE: it stores its data next to
itself and never updates in place. The installed edition is described in
``DigitalLibraryInstalled.spec`` and is packed into a setup program.
"""
import os
import sys

ROOT = os.path.abspath(os.environ.get("DL_BUILD_ROOT") or os.getcwd())
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from build_config import DATAS, EXCLUDES, HIDDEN_IMPORTS  # noqa: E402

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DigitalLibrary",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
    version="version_info.txt",
)
