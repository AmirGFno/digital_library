# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for the installed (folder) edition.

The setup program installs this folder under Program Files. Keeping the app as
a folder instead of one packed EXE is what makes small updates possible: a new
release ships only the files whose content changed, and the in-place updater
replaces exactly those.
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
    [],
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DigitalLibrary",
)
