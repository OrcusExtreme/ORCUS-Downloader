"""
ORCUS Downloader - Path & Asset Resolution Utility
(C) Copyright 2026. OrcusExtreme

Provides unified path resolution across all deployment targets:
- Development environment (python main.py)
- PyInstaller directory mode (--onedir, sys.executable directory)
- PyInstaller single-file mode (--onefile, sys._MEIPASS directory)
"""

import os
import sys


def get_app_dir() -> str:
    """
    Returns the root directory of the application:
    - If frozen (packaged as an exe): the directory containing the executable.
    - If running from source: the project root directory (parent of src).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    else:
        # __file__ is in src/path_utils.py -> parent of src/ is project root
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_resource_path(relative_path: str = "") -> str:
    """
    Resolves an absolute path to a resource (icon, data, binary) across all environments:
    1. If running under PyInstaller --onefile: sys._MEIPASS
    2. If running under PyInstaller --onedir: directory of sys.executable
    3. If running from source: project root directory

    Args:
        relative_path: Relative path from application root (e.g., 'app_icon.ico', 'bin/ffmpeg.exe')
    """
    if getattr(sys, "frozen", False):
        # Check PyInstaller onefile temp folder first if present
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidate = os.path.join(meipass, relative_path)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)

        # Check PyInstaller onedir internal directory (_internal, PyInstaller 6+)
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        internal_candidate = os.path.join(exe_dir, "_internal", relative_path)
        if os.path.exists(internal_candidate):
            return os.path.abspath(internal_candidate)

        # Check PyInstaller onedir installation folder (next to exe)
        candidate = os.path.join(exe_dir, relative_path)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

        # Fallback to exe_dir
        return os.path.abspath(os.path.join(exe_dir, relative_path))
    else:
        # Development mode: relative to project root
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.abspath(os.path.join(project_root, relative_path))


def find_ffmpeg_bin_dir() -> str | None:
    """
    Locates the directory containing ffmpeg.exe & ffprobe.exe in order of priority:
    1. PyInstaller bundled resources:
       - <AppDir>/_internal/bin/ (PyInstaller 6+ onedir layout)
       - <AppDir>/bin/ (custom onedir layout)
       - <AppDir>/ (flat layout next to exe)
       - sys._MEIPASS/bin or sys._MEIPASS (onefile mode)
    2. Local persistent AppData cache (%LOCALAPPDATA%/ORCUS Downloader/bin)
    3. User home cache (~/.orcus_downloader/bin)
    4. System PATH environment variable

    Returns:
        Absolute path to the directory containing ffmpeg.exe, or None if not found.
    """
    import shutil

    # Priority 1: Check bundled application directories
    candidates = [
        get_resource_path("bin"),
        os.path.join(get_app_dir(), "_internal", "bin"),
        os.path.join(get_app_dir(), "bin"),
        get_app_dir(),
        os.path.join(get_app_dir(), "_internal"),
        os.path.join(get_app_dir(), "ffmpeg", "bin"),
    ]

    # Priority 2: Persistent AppData
    local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if local_app_data:
        candidates.append(os.path.join(local_app_data, "ORCUS Downloader", "bin"))

    # Priority 3: User home
    candidates.append(os.path.join(os.path.expanduser("~"), ".orcus_downloader", "bin"))

    for c in candidates:
        if c and os.path.isdir(c):
            ffmpeg_path = os.path.join(c, "ffmpeg.exe")
            if os.path.isfile(ffmpeg_path) and os.path.getsize(ffmpeg_path) > 1000:
                ensure_dir_in_path(c)
                return os.path.abspath(c)

    # Priority 4: System PATH
    which_ffmpeg = shutil.which("ffmpeg")
    if which_ffmpeg:
        found_dir = os.path.dirname(os.path.abspath(which_ffmpeg))
        ensure_dir_in_path(found_dir)
        return found_dir

    return None


def find_ffmpeg_exe() -> str | None:
    """Returns absolute path to ffmpeg.exe, or None if not found."""
    bin_dir = find_ffmpeg_bin_dir()
    if bin_dir:
        exe_path = os.path.join(bin_dir, "ffmpeg.exe")
        if os.path.isfile(exe_path):
            return exe_path
    return None


def find_ffprobe_exe() -> str | None:
    """Returns absolute path to ffprobe.exe, or None if not found."""
    bin_dir = find_ffmpeg_bin_dir()
    if bin_dir:
        exe_path = os.path.join(bin_dir, "ffprobe.exe")
        if os.path.isfile(exe_path):
            return exe_path
    return None


def ensure_dir_in_path(directory: str) -> None:
    """Ensures the specified directory is prepended to the current process os.environ['PATH']."""
    if not directory:
        return
    norm_dir = os.path.normcase(os.path.abspath(directory))
    current_paths = [os.path.normcase(os.path.abspath(p)) for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    if norm_dir not in current_paths:
        os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")

