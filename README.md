# ⚡ ORCUS Downloader

<p align="center">
  <img src="app_icon.png" alt="ORCUS Downloader Logo" width="100" height="100"/>
</p>

<p align="center">
  <b>A sleek, high-performance desktop media downloader built with CustomTkinter & yt-dlp.</b><br/>
  Support for 8 major platforms with interactive task queuing, clipping, high-bitrate MP3 tagging, and system tray integration.
</p>

<p align="center">
  <a href="https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS_Downloader_v1.0.4_Setup.exe">
    <img src="https://img.shields.io/badge/Download-Installer_Setup_(v1.0.4)-success?style=for-the-badge&logo=windows&color=0078D6" alt="Download Windows Installer"/>
  </a>
  <a href="https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS.Downloader.exe">
    <img src="https://img.shields.io/badge/Download-Portable_Exe-lightgrey?style=for-the-badge&logo=windows" alt="Download Portable Exe"/>
  </a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Platform-Windows-0078D6?style=flat-square&logo=windows" alt="Platform"/>
  <a href="https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest">
    <img src="https://img.shields.io/badge/Release-v1.0.4-orange?style=flat-square&logo=github" alt="Release"/>
  </a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python" alt="Python"/>
  <img src="https://img.shields.io/badge/GUI-CustomTkinter-blueviolet?style=flat-square" alt="GUI"/>
  <img src="https://img.shields.io/badge/Engine-yt--dlp-FF0000?style=flat-square" alt="yt-dlp"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License"/>
</p>

---

## ✨ Key Features

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
yt_dlp/
├── .github/
│   └── workflows/
│       └── build-release.yml    # Automated CI/CD build & release pipeline
├── src/
│   ├── __init__.py
│   ├── app.py                   # Main GUI application & Task Queue
│   ├── downloader_core.py       # Core 8-platform download engine & patchers
│   └── history_manager.py       # Download history CRUD & Windows shell launcher
├── main.py                      # Source execution entry point
├── app_icon.ico                 # Multi-resolution application icon
├── app_icon.png                 # High-resolution round brand logo
├── requirements.txt             # Python package dependencies
├── .gitignore                   # Git ignore specifications
├── LICENSE                      # MIT License
├── README.md                    # Project documentation
└── ORCUS Downloader.exe         # Prebuilt standalone Windows executable
```

---

## 🚀 Quick Start
 
### Option 1: Windows Installer (Recommended)
Download and run the **[ORCUS_Downloader_v1.0.4_Setup.exe](https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS_Downloader_v1.0.4_Setup.exe)** installer:
- **100% Self-Contained**: Completely standalone for clean Windows PCs. No Python, FFmpeg, or dependencies required!
- **Auto-Provisioned FFmpeg Engine**: Bundles complete `ffmpeg.exe` and `ffprobe.exe` binaries with zero PATH setup needed.
- **System Integration**: Installs to `C:\Program Files\ORCUS Downloader` with optional Desktop icon, Start Menu shortcuts, and clean Windows Control Panel Uninstaller.
- **Ultra-Fast Speed Pipeline (v1.0.4)**: Single-pass metadata execution (`process_ie_result`), 8-thread concurrent fragment downloads, and CPU multi-core FFmpeg postprocessing (`-threads 0`).

### Option 2: Portable Executable
Simply download **[ORCUS.Downloader.exe (Portable)](https://github.com/OrcusExtreme/ORCUS-Downloader/releases/latest/download/ORCUS.Downloader.exe)** to run directly without installation.

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
   *(FFmpeg is automatically detected or auto-downloaded on first run if missing.)*

---

## 🛠️ Building Standalone Executable & Installer

You can build both the directory distribution and Inno Setup installer using the automated PowerShell script:

```powershell
.\build_installer.ps1
```

Or manually via PyInstaller and Inno Setup:

```powershell
# 1. PyInstaller onedir distribution
python -m PyInstaller ORCUS_Downloader.spec --clean --noconfirm

# 2. Inno Setup 6 installer compilation
iscc setup.iss
```

The resulting standalone installer will be placed in `installer_output/ORCUS_Downloader_v1.0.4_Setup.exe`.

---

## ⚖️ License & Copyright

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

**(C) Copyright 2026. OrcusExtreme**
