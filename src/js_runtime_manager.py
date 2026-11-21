"""
ORCUS Downloader - JavaScript Runtime (Deno) Lifecycle & Auto-Provisioning Manager
(C) Copyright 2026. OrcusExtreme

Recent yt-dlp releases require an external JavaScript runtime to solve YouTube's
signature / n-parameter challenges. Without one, YouTube only exposes a handful of
formats (often just the 360p progressive format 18), so "Best" quality silently
degrades to 640x360.

This module locates deno.exe (bundled, AppData cache, or PATH) and downloads it
on first use when missing, mirroring ffmpeg_manager's provisioning flow.
"""

import os
import shutil
import subprocess
import threading

import ffmpeg_manager
import path_utils

DENO_ZIP_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
DENO_EXE = "deno.exe"

_download_lock = threading.Lock()


def _is_valid_exe(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.path.getsize(path) > 1_000_000


def _runs(path: str) -> bool:
    """True if `deno --version` executes successfully (rejects truncated/corrupt downloads)."""
    try:
        r = subprocess.run([path, "--version"], capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode == 0
    except Exception:
        return False


def find_deno_exe() -> str | None:
    """Locates deno.exe: bundled app dirs -> AppData cache -> user home -> PATH."""
    app_dir = path_utils.get_app_dir()
    candidates = [
        path_utils.get_resource_path("bin"),
        os.path.join(app_dir, "_internal", "bin"),
        os.path.join(app_dir, "bin"),
        app_dir,
        ffmpeg_manager.get_local_storage_dir(),
        os.path.join(os.path.expanduser("~"), ".orcus_downloader", "bin"),
    ]
    for c in candidates:
        exe = os.path.join(c, DENO_EXE)
        if _is_valid_exe(exe):
            return os.path.abspath(exe)

    which = shutil.which("deno")
    if which:
        return os.path.abspath(which)
    return None


def ensure_deno(progress_callback=None) -> str | None:
    """
    Returns the path to deno.exe, downloading it into the AppData cache if missing.
    Returns None (instead of raising) when provisioning fails, so downloads can still
    proceed with reduced YouTube format availability.
    """
    found = find_deno_exe()
    if found:
        return found

    with _download_lock:
        found = find_deno_exe()
        if found:
            return found

        target_dir = ffmpeg_manager.get_local_storage_dir()
        # Download & extract into a staging folder, verify, then atomically move into
        # place: an interrupted download can never leave a truncated deno.exe behind.
        staging = os.path.join(target_dir, ".deno_staging")
        shutil.rmtree(staging, ignore_errors=True)
        os.makedirs(staging, exist_ok=True)
        if progress_callback:
            progress_callback(0, "Connecting to JS runtime server (Deno)...")

        exe = os.path.join(target_dir, DENO_EXE)
        try:
            ok = ffmpeg_manager._download_and_extract_single(
                DENO_ZIP_URL, staging, DENO_EXE,
                progress_callback=progress_callback, pct_start=0.0, pct_end=100.0
            )
            staged = os.path.join(staging, DENO_EXE)
            if ok and _is_valid_exe(staged) and _runs(staged):
                os.replace(staged, exe)
        except Exception:
            pass
        finally:
            shutil.rmtree(staging, ignore_errors=True)

        if _is_valid_exe(exe):
            if progress_callback:
                progress_callback(100, "JS runtime (Deno) setup complete.")
            return exe

        if progress_callback:
            progress_callback(100, "JS runtime (Deno) download failed; YouTube quality may be limited.")
        return None


def get_ytdlp_js_opts(deno_path: str | None) -> dict:
    """Returns yt-dlp params enabling the JS challenge solver."""
    runtimes = {'deno': {'path': deno_path}} if deno_path else {'deno': {}}
    return {
        'js_runtimes': runtimes,
        # Fallback: fetch the EJS solver script from GitHub if the yt-dlp-ejs
        # package is not available (e.g. stripped from a frozen build).
        'remote_components': ['ejs:github'],
    }
