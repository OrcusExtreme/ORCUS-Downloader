"""
ORCUS Downloader - FFmpeg Lifecycle & Auto-Provisioning Manager
(C) Copyright 2026. OrcusExtreme

Ensures ffmpeg.exe and ffprobe.exe are always available across any Windows environment,
including bare-metal PCs with no prior developer tools or media encoders installed.
"""

import os
import sys
import shutil
import zipfile
import threading
import urllib.request
import time

_download_lock = threading.Lock()

# Primary fast mirror (individual lightweight zip archives from GitHub CDN)
FFBINARIES_FFMPEG_URL = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffmpeg-6.1-win-64.zip"
FFBINARIES_FFPROBE_URL = "https://github.com/ffbinaries/ffbinaries-prebuilt/releases/download/v6.1/ffprobe-6.1-win-64.zip"

# Fallback full archives
FALLBACK_ARCHIVES = [
    {
        "name": "yt-dlp FFmpeg Builds",
        "url": "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
    },
    {
        "name": "Gyan.dev Release Essentials",
        "url": "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    }
]


def get_local_storage_dir() -> str:
    """Returns persistent local AppData directory for storing downloaded FFmpeg binaries."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        app_data = os.environ.get("APPDATA")
        if app_data:
            base = app_data
        else:
            base = os.path.expanduser("~")
    else:
        base = local_app_data

    target_dir = os.path.join(base, "ORCUS Downloader", "bin")
    os.makedirs(target_dir, exist_ok=True)
    return target_dir


def _check_dir_has_ffmpeg(directory: str) -> bool:
    """Checks whether the given directory contains an executable ffmpeg."""
    if not directory or not os.path.isdir(directory):
        return False
    ffmpeg_exe = os.path.join(directory, "ffmpeg.exe")
    return os.path.isfile(ffmpeg_exe) and os.path.getsize(ffmpeg_exe) > 1000


def get_ffmpeg_dir() -> str | None:
    """
    Discovers the directory containing ffmpeg.exe in priority order:
    1. PyInstaller bundled resources (sys._MEIPASS or app directory / bin)
    2. Local persistent AppData cache (%LOCALAPPDATA%/ORCUS Downloader/bin)
    3. User home fallback directory (~/.orcus_downloader/bin)
    4. System PATH (shutil.which)

    Uses path_utils.find_ffmpeg_bin_dir() for unified path resolution.
    """
    try:
        import path_utils
        found = path_utils.find_ffmpeg_bin_dir()
        if found:
            return found
    except ImportError:
        pass

    # Direct fallback search if path_utils is not imported
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(meipass)
            candidates.append(os.path.join(meipass, "bin"))
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        exe_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    candidates.extend([
        os.path.join(exe_dir, "bin"),
        exe_dir,
        os.path.join(exe_dir, "ffmpeg", "bin"),
        get_local_storage_dir(),
        os.path.join(os.path.expanduser("~"), ".orcus_downloader", "bin"),
    ])

    for c in candidates:
        if _check_dir_has_ffmpeg(c):
            _ensure_in_path(c)
            return os.path.abspath(c)

    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        found_dir = os.path.dirname(os.path.abspath(which_ffmpeg))
        _ensure_in_path(found_dir)
        return found_dir

    return None


def _ensure_in_path(directory: str):
    """Ensures the directory is at the beginning of os.environ['PATH']."""
    norm_dir = os.path.normpath(directory)
    current_paths = [os.path.normpath(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if norm_dir not in current_paths:
        os.environ["PATH"] = norm_dir + os.pathsep + os.environ.get("PATH", "")


def is_ffmpeg_available() -> bool:
    """Returns True if a functional FFmpeg directory is found."""
    return get_ffmpeg_dir() is not None


def _download_and_extract_single(url: str, target_dir: str, binary_name: str,
                                 progress_callback=None, pct_start=0.0, pct_end=100.0) -> bool:
    """Downloads a single zip archive and extracts binary_name into target_dir."""
    temp_zip = os.path.join(target_dir, f"{binary_name}.tmp.zip")
    try:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ORCUS Downloader/1.0"
            }
        )

        with urllib.request.urlopen(req, timeout=30) as resp, open(temp_zip, "wb") as out_file:
            total_bytes = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 256 * 1024
            start_time = time.time()
            last_update = 0

            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)

                now = time.time()
                if now - last_update >= 0.2 or (total_bytes and downloaded >= total_bytes):
                    last_update = now
                    elapsed = now - start_time
                    spd_mb = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                    fraction = (downloaded / total_bytes) if total_bytes else 0.5
                    overall_pct = pct_start + fraction * (pct_end - pct_start)
                    dl_mb = downloaded / (1024 * 1024)
                    tot_mb = total_bytes / (1024 * 1024) if total_bytes else 0

                    if progress_callback:
                        msg = f"Downloading {binary_name}: {dl_mb:.1f}/{tot_mb:.1f} MB ({overall_pct:.1f}%) @ {spd_mb:.1f} MB/s"
                        progress_callback(overall_pct, msg)

        # Extract binary
        with zipfile.ZipFile(temp_zip, "r") as z:
            out_path = os.path.join(target_dir, binary_name)
            for info in z.infolist():
                if os.path.basename(info.filename).lower() == binary_name.lower():
                    with z.open(info) as src, open(out_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    break

        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass

        return os.path.isfile(os.path.join(target_dir, binary_name))
    except Exception:
        if os.path.exists(temp_zip):
            try:
                os.remove(temp_zip)
            except Exception:
                pass
        return False


def download_and_install_ffmpeg(progress_callback=None) -> str:
    """
    Downloads static FFmpeg binaries and extracts ffmpeg.exe and ffprobe.exe
    into the persistent AppData directory.
    Thread-safe; avoids parallel duplicate downloads.
    """
    with _download_lock:
        # Check again in case another thread just completed the download
        existing = get_ffmpeg_dir()
        if existing:
            return existing

        target_dir = get_local_storage_dir()

        # Strategy 1: High-speed standalone zip packages (ffbinaries via GitHub CDN)
        if progress_callback:
            progress_callback(0, "Connecting to media engine server (FFmpeg)...")

        ok_ffmpeg = _download_and_extract_single(
            FFBINARIES_FFMPEG_URL, target_dir, "ffmpeg.exe",
            progress_callback=progress_callback, pct_start=0.0, pct_end=50.0
        )

        if ok_ffmpeg:
            # Also download ffprobe
            _download_and_extract_single(
                FFBINARIES_FFPROBE_URL, target_dir, "ffprobe.exe",
                progress_callback=progress_callback, pct_start=50.0, pct_end=95.0
            )

            _ensure_in_path(target_dir)
            if progress_callback:
                progress_callback(100, "Media engine (FFmpeg) setup complete.")
            return target_dir

        # Strategy 2: Fallback full archives
        last_error = None
        temp_zip = os.path.join(target_dir, "ffmpeg_archive.tmp.zip")

        for source in FALLBACK_ARCHIVES:
            src_name = source["name"]
            src_url = source["url"]

            if progress_callback:
                progress_callback(0, f"Connecting to fallback mirror ({src_name})...")

            try:
                if os.path.exists(temp_zip):
                    try:
                        os.remove(temp_zip)
                    except Exception:
                        pass

                req = urllib.request.Request(
                    src_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ORCUS Downloader/1.0"
                    }
                )

                with urllib.request.urlopen(req, timeout=30) as resp, open(temp_zip, "wb") as out_file:
                    total_bytes = int(resp.headers.get("Content-Length", 0))
                    downloaded = 0
                    chunk_size = 256 * 1024
                    start_time = time.time()
                    last_update = 0

                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if now - last_update >= 0.2 or (total_bytes and downloaded >= total_bytes):
                            last_update = now
                            elapsed = now - start_time
                            spd_mb = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                            pct = (downloaded / total_bytes * 100) if total_bytes > 0 else 0
                            dl_mb = downloaded / (1024 * 1024)
                            tot_mb = total_bytes / (1024 * 1024) if total_bytes else 0

                            if progress_callback:
                                msg = f"Downloading FFmpeg: {dl_mb:.1f}/{tot_mb:.1f} MB ({pct:.1f}%) @ {spd_mb:.1f} MB/s"
                                progress_callback(pct, msg)

                if progress_callback:
                    progress_callback(95, "Extracting ffmpeg.exe & ffprobe.exe...")

                with zipfile.ZipFile(temp_zip, "r") as z:
                    found_ffmpeg = False
                    for info in z.infolist():
                        base_name = os.path.basename(info.filename).lower()
                        if base_name in ("ffmpeg.exe", "ffprobe.exe"):
                            out_path = os.path.join(target_dir, base_name)
                            with z.open(info) as src, open(out_path, "wb") as dst:
                                shutil.copyfileobj(src, dst)
                            if base_name == "ffmpeg.exe":
                                found_ffmpeg = True

                    if not found_ffmpeg:
                        raise RuntimeError("Archive did not contain ffmpeg.exe")

                if os.path.exists(temp_zip):
                    try:
                        os.remove(temp_zip)
                    except Exception:
                        pass

                _ensure_in_path(target_dir)

                if progress_callback:
                    progress_callback(100, "Media engine (FFmpeg) setup complete.")

                return target_dir

            except Exception as e:
                last_error = e
                if os.path.exists(temp_zip):
                    try:
                        os.remove(temp_zip)
                    except Exception:
                        pass
                continue

        raise RuntimeError(
            f"Failed to automatically download FFmpeg: {str(last_error)}. "
            f"Please check your internet connection or place ffmpeg.exe manually in:\n{target_dir}"
        )


def ensure_ffmpeg(progress_callback=None) -> str:
    """
    Ensures FFmpeg is available. If not already present, downloads and configures it.
    Returns the directory containing ffmpeg.exe.
    """
    found = get_ffmpeg_dir()
    if found:
        return found
    return download_and_install_ffmpeg(progress_callback=progress_callback)
