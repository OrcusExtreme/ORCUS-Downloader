import os
import sys
import json
import time
import subprocess
from tkinter import messagebox

HISTORY_FILE = os.path.join(os.path.expanduser("~"), ".orcus_downloader_history.json")

def get_history():
    """Loads download history records from disk."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def add_history_item(title, url, platform, download_type, filepath, filesize_bytes=0, duration_str="", file_size_mb=None, format_type=None):
    """Adds a newly completed download item to history."""
    items = get_history()
    
    calc_size_mb = file_size_mb if file_size_mb is not None else (round(filesize_bytes / (1024 * 1024), 2) if filesize_bytes else 0)
    actual_fmt = format_type or ("MP3" if download_type == "audio" else "MP4")
    norm_path = os.path.normpath(os.path.abspath(filepath)) if filepath else ""

    item = {
        "id": int(time.time() * 1000),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "url": url,
        "platform": platform,
        "type": download_type,
        "format": actual_fmt,
        "filepath": norm_path,
        "file_path": norm_path,
        "filename": os.path.basename(norm_path) if norm_path else "",
        "size_mb": calc_size_mb,
        "file_size_mb": calc_size_mb,
        "duration": duration_str,
        "exists": os.path.exists(norm_path) if norm_path else False
    }
    # Prepend to front
    items.insert(0, item)
    # Keep max 200 items
    items = items[:200]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
    return item

def add_history(title, url, file_path, format_type, file_size_mb, platform, duration_str=""):
    """Alias for add_history_item."""
    dl_type = "audio" if "mp3" in str(format_type).lower() else "video"
    return add_history_item(
        title=title, url=url, platform=platform, download_type=dl_type,
        filepath=file_path, file_size_mb=file_size_mb, format_type=format_type, duration_str=duration_str
    )

def delete_history(item_id):
    """Deletes an item from history list (does not delete file on disk)."""
    items = get_history()
    items = [i for i in items if i.get("id") != item_id]
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def delete_history_item(item_id):
    return delete_history(item_id)

def clear_history():
    """Clears all history entries."""
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    except Exception:
        pass

def clear_all_history():
    return clear_history()

def open_file_in_explorer(filepath):
    """
    Opens the directory containing the downloaded file in Windows Explorer.
    Uses os.startfile on the directory to ensure 100% reliability and prevent
    Windows Explorer /select argument parsing bugs (which default to Documents).
    """
    if not filepath:
        messagebox.showwarning("File Error", "No file path is specified for this history item.")
        return False

    norm_path = os.path.normpath(os.path.abspath(filepath))

    # Determine target directory
    if os.path.isdir(norm_path):
        target_dir = norm_path
    else:
        target_dir = os.path.dirname(norm_path)

    if os.path.isdir(target_dir):
        try:
            os.startfile(target_dir)
            return True
        except Exception as e:
            messagebox.showerror("Explorer Error", f"Failed to open download folder:\n{str(e)}")
            return False
    else:
        messagebox.showwarning(
            "Folder Not Found",
            f"The download folder cannot be found:\n{target_dir}\n\nIt may have been moved or deleted."
        )
        return False

def open_file_folder(filepath):
    return open_file_in_explorer(filepath)

def play_file_default(filepath):
    """Plays the file using the default system media player with alert feedback."""
    if not filepath:
        messagebox.showwarning("File Error", "No file path is specified for this history item.")
        return False

    norm_path = os.path.normpath(os.path.abspath(filepath))
    if os.path.isfile(norm_path):
        try:
            os.startfile(norm_path)
            return True
        except Exception as e:
            messagebox.showerror("Playback Error", f"Failed to play file with system player:\n{str(e)}")
            return False
    else:
        messagebox.showwarning(
            "File Not Found",
            f"The target media file cannot be played because it does not exist at:\n{norm_path}\n\nIt may have been moved or deleted."
        )
        return False

def play_file(filepath):
    return play_file_default(filepath)
