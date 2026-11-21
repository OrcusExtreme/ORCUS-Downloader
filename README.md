# ⚡ ORCUS Downloader

<p align="center">
  <img src="app_icon.png" alt="ORCUS Downloader Logo" width="100" height="100"/>
</p>

<p align="center">
  <b>A sleek, high-performance desktop media downloader built with CustomTkinter & yt-dlp.</b><br/>
  Support for 8 major platforms with true best-quality downloads, interactive task queuing, clipping, high-bitrate MP3 tagging, light/dark themes, and system tray integration.
</p>

<p align="center">
  <a href="https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS_Downloader_v1.1.0_Setup.exe">
    <img src="https://img.shields.io/badge/Download-Installer_Setup_(v1.1.0)-success?style=for-the-badge&logo=windows&color=0078D6" alt="Download Windows Installer"/>
  </a>
  <a href="https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS.Downloader.exe">
    <img src="https://img.shields.io/badge/Download-Portable_Exe-lightgrey?style=for-the-badge&logo=windows" alt="Download Portable Exe"/>
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows" alt="Platform"/>
  <a href="https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest">
    <img src="https://img.shields.io/badge/Release-v1.1.0-orange?style=flat-square&logo=github" alt="Release"/>
  </a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python" alt="Python"/>
  <img src="https://img.shields.io/badge/GUI-CustomTkinter-blueviolet?style=flat-square" alt="GUI"/>
  <img src="https://img.shields.io/badge/Engine-yt--dlp-FF0000?style=flat-square" alt="yt-dlp"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License"/>
</p>

---

## ✨ Key Features

- **🎯 True Best Quality (up to 4K / 60fps)**:
  - YouTube signature / n-challenges are solved with a bundled **Deno** JS runtime (yt-dlp EJS), so high-resolution DASH streams are never silently replaced by the 360p fallback.
  - `Best (Original)` picks the highest resolution in any codec (H.264 / VP9 / AV1) and merges it into MP4; fixed resolutions pick the closest available height.
  - The finished download reports its actual resolution (e.g. `[3840x2160]`) and warns — after retrying with browser cookies — if YouTube only offered low-quality formats.
- **🎨 Workspace-style Interface with Light & Dark Themes**:
  - Material 3-inspired layout: navigation drawer, rounded surfaces, pill buttons, status chips and Material Icons.
  - One-click light/dark toggle in the top bar (remembered between launches; follows the Windows theme on first run).
- **🌐 8 Supported Platforms**:
  - **CHZZK (치지직)**: Native progressive MP4 stream extraction bypassing HLS segment bottlenecks.
  - **SOOP (아프리카TV)**: High-speed full-bandwidth original quality VOD downloads.
  - **YouTube**: Videos, shorts, and music with automatic playlist/mix sanitization.
  - **X (Twitter)**, **Instagram Reels**, **TikTok**, **NaverTV**, and **Twitch**.
- **📋 Interactive Task Queue**:
  - Add individual media links one-by-one with custom resolution and format settings.
  - Individual task cards featuring independent progress bars, speed, size metrics, and status badges (`Waiting`, `Downloading`, `Paused`, `Completed`).
  - Per-item controls (`Start`, `Pause`, `Cancel`, `Remove`) + Global batch controls (`Start All`, `Pause All`, `Stop All`, `Clear Finished`).
- **🎵 High-Fidelity MP3 Audio Tagging**:
  - Converts audio to **320kbps MP3**.
  - Automatically fetches the video's original cover art and embeds it into the MP3 file (`Attached Picture`).
  - Injects full ID3v2 tags (Title, Artist, Album, Uploader).
- **✂️ Video Clipping (Range Download)**:
  - Download only the desired section by specifying start and end timestamps (e.g. `00:00:10` to `00:01:30`) without fetching the entire video.
- **🖼️ Real-Time Asynchronous Live Preview**:
  - Pasting a URL immediately fetches the video title, channel name, duration, and thumbnail into a preview card.
- **📜 Download History Management**:
  - Persistent local history (`~/.orcus_downloader_history.json`).
  - Direct **[Open Folder]** (reveals file in Windows Explorer) and **[Play]** (launches default media player) with missing-file safety alerts.
- **🔔 System Tray Minimization**:
  - Minimize to Windows System Tray upon closing or via the header button (`pystray` integration).
  - Background downloads continue uninterrupted with tray notifications on completion.

---

## 📂 Project Structure

```text
ORCUS-Downloader/
├── .github/
│   └── workflows/
│       └── build-release.yml    # Automated CI/CD build & release pipeline
├── assets/
│   └── fonts/                   # Material Icons (Outlined) font + Apache 2.0 license
├── src/
│   ├── __init__.py
│   ├── app.py                   # Main GUI application (pages, queue, history, tray)
│   ├── ui_theme.py              # Design tokens (light/dark), icons, widget factories, settings
│   ├── downloader_core.py       # Core 8-platform download engine, format selection & patchers
│   ├── js_runtime_manager.py    # Deno (YouTube JS challenge solver) discovery & auto-provisioning
│   ├── ffmpeg_manager.py        # FFmpeg discovery & auto-provisioning
│   ├── history_manager.py       # Download history CRUD & Windows shell launcher
│   ├── path_utils.py            # Resource path resolution (source / onedir / onefile)
│   └── version.py               # App version (keep in sync with setup.iss)
├── main.py                      # Source execution entry point
├── ORCUS_Downloader.spec        # PyInstaller onedir spec (bundles FFmpeg + Deno)
├── setup.iss                    # Inno Setup 6 installer script
├── build_installer.ps1          # One-shot build: binaries → PyInstaller → installer
├── app_icon.ico / app_icon.png  # Application icons
├── requirements.txt             # Python package dependencies
├── LICENSE                      # MIT License
├── README.md                    # Project documentation
└── ORCUS Downloader.exe         # Prebuilt portable Windows executable
```

---

## 🚀 Quick Start
 
### Option 1: Windows Installer (Recommended)
Download and run the **[ORCUS_Downloader_v1.1.0_Setup.exe](https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS_Downloader_v1.1.0_Setup.exe)** installer:
- **100% Self-Contained**: Completely standalone for clean Windows PCs. No Python, FFmpeg, Deno, or other dependencies required!
- **Bundled Media & JS Engines**: Ships `ffmpeg.exe`, `ffprobe.exe` and `deno.exe` with zero PATH setup needed.
- **System Integration**: Installs to `C:\Program Files\ORCUS Downloader` with optional Desktop icon, Start Menu shortcuts, and clean Windows Control Panel Uninstaller.
- **Ultra-Fast Speed Pipeline**: Single-pass metadata execution (`process_ie_result`), 8-thread concurrent fragment downloads, and CPU multi-core FFmpeg postprocessing (`-threads 0`).

### Option 2: Portable Executable
Simply download **[ORCUS.Downloader.exe (Portable)](https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS.Downloader.exe)** to run directly without installation.
FFmpeg and Deno are downloaded automatically to `%LOCALAPPDATA%\ORCUS Downloader\bin` on first launch.

### Option 3: Run from Source

1. **Clone the repository**:
   ```bash
   git clone https://github.com/OrcusExtreme/ORCUS-Downloader.git
   cd ORCUS-Downloader
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Launch the application**:
   ```bash
   python main.py
   ```
   *(FFmpeg and Deno are automatically detected, or auto-downloaded on first run if missing.)*

---

## 🛠️ Building Standalone Executable & Installer

Requirements: Python 3.11+ with `pip install -r requirements.txt`, and [Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

Build the directory distribution and the Inno Setup installer with the automated PowerShell script:

```powershell
.\build_installer.ps1                                   # uses "python" on PATH
.\build_installer.ps1 -Python C:\Python313\python.exe   # explicit interpreter
.\build_installer.ps1 -Portable                         # also rebuilds the portable "ORCUS Downloader.exe"
```

The script downloads FFmpeg and Deno into `bin/` when missing, verifies the bundle, and writes the installer to `installer_output/ORCUS_Downloader_v<version>_Setup.exe`.
The version is defined in `setup.iss` (`MyAppVersion`) and `src/version.py`; the script refuses to build if they differ.

Or manually via PyInstaller and Inno Setup:

```powershell
# 1. PyInstaller onedir distribution (expects bin/ffmpeg.exe, bin/ffprobe.exe, bin/deno.exe)
python -m PyInstaller ORCUS_Downloader.spec --clean --noconfirm

# 2. Inno Setup 6 installer compilation
iscc setup.iss
```

---

## 🩺 Troubleshooting

- **YouTube downloads come out as 640x360** — the JS runtime is missing or failed to download. Check that `deno.exe` exists in `%LOCALAPPDATA%\ORCUS Downloader\bin` (portable/source) or the install folder, then retry.
- **Logs** — yt-dlp warnings and errors are written to `%LOCALAPPDATA%\ORCUS Downloader\logs\ytdlp.log`.
- **Theme preference** — stored in `%LOCALAPPDATA%\ORCUS Downloader\settings.json`; delete it to follow the Windows theme again.

---

## ⚖️ License & Copyright

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

Third-party components keep their own licenses: [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense), [Deno](https://github.com/denoland/deno) (MIT), [FFmpeg](https://ffmpeg.org/legal.html), [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (MIT, bundles Roboto), and [Material Icons](https://github.com/google/material-design-icons) (Apache 2.0, see `assets/fonts/MaterialIcons-LICENSE.txt`).

**(C) Copyright 2026. OrcusExtreme**
