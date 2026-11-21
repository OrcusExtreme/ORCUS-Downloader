# -*- mode: python ; coding: utf-8 -*-
"""
ORCUS Downloader - PyInstaller Build Specification (--onedir mode)
(C) Copyright 2026. OrcusExtreme

Packages ORCUS Downloader into a standalone directory (dist/ORCUS Downloader)
containing the main executable, Python runtime, customtkinter assets,
application icons, and self-contained FFmpeg/FFprobe binaries.
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Project root directory
ROOT_DIR = os.path.abspath(os.path.dirname(__file__) if '__file__' in locals() else '.')

# -----------------------------------------------------------------------------
# 1. Static Assets & Data Files
# -----------------------------------------------------------------------------
datas = [
    (os.path.join(ROOT_DIR, 'app_icon.png'), '.'),
    (os.path.join(ROOT_DIR, 'app_icon.ico'), '.'),
    (os.path.join(ROOT_DIR, 'src'), 'src'),
    # Material Icons font (Apache 2.0) used by the Workspace-style UI
    (os.path.join(ROOT_DIR, 'assets'), 'assets'),
]

# Collect customtkinter themes, json configs, and bundled fonts
datas += collect_data_files('customtkinter')

# yt-dlp-ejs: YouTube JS challenge solver scripts (needed for >360p YouTube formats)
try:
    datas += collect_data_files('yt_dlp_ejs')
except Exception:
    pass

# -----------------------------------------------------------------------------
# 2. Binaries (Self-contained FFmpeg & FFprobe)
# -----------------------------------------------------------------------------
binaries = []

ffmpeg_src = os.path.join(ROOT_DIR, 'bin', 'ffmpeg.exe')
ffprobe_src = os.path.join(ROOT_DIR, 'bin', 'ffprobe.exe')

if os.path.isfile(ffmpeg_src):
    binaries.append((ffmpeg_src, 'bin'))

if os.path.isfile(ffprobe_src):
    binaries.append((ffprobe_src, 'bin'))

# Deno JS runtime (yt-dlp YouTube signature / n-challenge solving)
deno_src = os.path.join(ROOT_DIR, 'bin', 'deno.exe')
if os.path.isfile(deno_src):
    binaries.append((deno_src, 'bin'))

# -----------------------------------------------------------------------------
# 3. Hidden Imports & Dependencies
# -----------------------------------------------------------------------------
hiddenimports = [
    'customtkinter',
    'pystray',
    'pystray._win32',
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',
    'PIL._tkinter_finder',
    'mutagen',
    'mutagen.mp3',
    'mutagen.id3',
    'yt_dlp',
    'yt_dlp.extractor',
    'yt_dlp.extractor.youtube',
    'yt_dlp.extractor.chzzk',
    'yt_dlp_ejs',
    'path_utils',
    'ffmpeg_manager',
    'js_runtime_manager',
    'ui_theme',
    'version',
    'downloader_core',
    'app',
]

hiddenimports += collect_submodules('customtkinter')

# -----------------------------------------------------------------------------
# 4. Analysis
# -----------------------------------------------------------------------------
a = Analysis(
    ['main.py'],
    pathex=[ROOT_DIR, os.path.join(ROOT_DIR, 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# -----------------------------------------------------------------------------
# 5. Executable (GUI Mode, No Console Window)
# -----------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ORCUS Downloader',
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
    icon=os.path.join(ROOT_DIR, 'app_icon.ico'),
)

# -----------------------------------------------------------------------------
# 6. Collect (Outputs to dist/ORCUS Downloader)
# -----------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    # Never UPX-pack the large third-party executables (slow startup, AV false positives)
    upx_exclude=['deno.exe', 'ffmpeg.exe', 'ffprobe.exe'],
    name='ORCUS Downloader',
)
