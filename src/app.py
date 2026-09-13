import os
import sys
import time
import subprocess
import threading
from PIL import Image
import customtkinter as ctk
from tkinter import filedialog, messagebox

import downloader_core
import history_manager

# System Tray support via pystray
try:
    import pystray
    from pystray import MenuItem as item
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

# Set theme and color palette
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class QueueItem:
    """Represents a single download task in the queue."""
    def __init__(self, item_id: int, url: str, download_type: str, resolution: str, output_dir: str):
        self.id = item_id
        self.url = url
        self.download_type = download_type
        self.resolution = resolution
        self.output_dir = output_dir

        self.title = "Fetching info..."
        self.uploader = ""
        self.platform = downloader_core.detect_platform(url)
        self.status = "Waiting"  # Waiting, Downloading, Paused, Completed, Cancelled, Error
        self.pct = 0.0
        self.downloaded_mb = 0.0
        self.total_mb = 0.0
        self.speed = ""
        self.eta = ""
        self.filepath = None
        self.error_msg = ""
        self.worker = None

        # UI card widgets binding
        self.card_frame = None
        self.lbl_title = None
        self.lbl_info = None
        self.progress_bar = None
        self.lbl_status = None
        self.btn_start = None
        self.btn_pause = None
        self.btn_cancel = None
        self.btn_remove = None


class OrcusDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("ORCUS Downloader")
        self.geometry("860x800")
        self.minsize(800, 740)

        # Base path for resources (supports PyInstaller bundle and src/ submodule)
        if getattr(sys, 'frozen', False):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))

        self.icon_ico = os.path.join(self.base_dir, "app_icon.ico")
        self.icon_png = os.path.join(self.base_dir, "app_icon.png")

        # Fallback to parent directory if running from src/
        if not os.path.exists(self.icon_ico):
            parent_ico = os.path.join(os.path.dirname(self.base_dir), "app_icon.ico")
            if os.path.exists(parent_ico):
                self.icon_ico = parent_ico

        if not os.path.exists(self.icon_png):
            parent_png = os.path.join(os.path.dirname(self.base_dir), "app_icon.png")
            if os.path.exists(parent_png):
                self.icon_png = parent_png

        # Set window icon
        if os.path.exists(self.icon_ico):
            try:
                self.iconbitmap(self.icon_ico)
            except Exception:
                pass

        # Single download state
        self.single_worker = None
        self.single_downloaded_path = None
        self.last_preview_url = ""

        # Queue download state
        self.queue_items = []
        self.queue_counter = 0
        self.is_queue_running = False
        self.current_queue_index = -1

        # Tray state
        self.tray_icon = None
        self.is_hidden_in_tray = False

        # Build UI
        self._build_ui()

        # Initialize System Tray
        if PYSTRAY_AVAILABLE:
            self._init_tray()
            self.protocol("WM_DELETE_WINDOW", self._on_close_window)
        else:
            self.protocol("WM_DELETE_WINDOW", self._quit_app)

    # -------------------------------------------------------------
    # UI Header & Tabs
    # -------------------------------------------------------------
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Header Frame
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=24, pady=(14, 4), sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        # Logo Icon
        if os.path.exists(self.icon_png):
            try:
                logo_img = ctk.CTkImage(
                    light_image=Image.open(self.icon_png),
                    dark_image=Image.open(self.icon_png),
                    size=(46, 46)
                )
                logo_label = ctk.CTkLabel(header_frame, image=logo_img, text="")
                logo_label.grid(row=0, column=0, rowspan=2, padx=(0, 12), sticky="w")
            except Exception:
                pass

        title_label = ctk.CTkLabel(
            header_frame, text="ORCUS Downloader",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold")
        )
        title_label.grid(row=0, column=1, sticky="w")

        subtitle_label = ctk.CTkLabel(
            header_frame,
            text="High-Performance Media Downloader for YouTube, CHZZK, SOOP, X/Twitter, Instagram, TikTok & more",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#A0A5B5"
        )
        subtitle_label.grid(row=1, column=1, sticky="w")

        # Tray Minimize Button
        if PYSTRAY_AVAILABLE:
            tray_btn = ctk.CTkButton(
                header_frame, text="🔔 Minimize to Tray", width=125, height=30,
                font=ctk.CTkFont(size=11), fg_color="#3A3D4E", hover_color="#4B4E63",
                command=self._hide_to_tray
            )
            tray_btn.grid(row=0, column=2, rowspan=2, padx=(10, 0), sticky="e")

        # 2. Main Tabview
        self.tabview = ctk.CTkTabview(self, corner_radius=12, fg_color=("#2B2D3A", "#1E1F29"))
        self.tabview.grid(row=1, column=0, padx=24, pady=(2, 6), sticky="nsew")

        self.tab_single = self.tabview.add("📥 Single Download")
        self.tab_queue = self.tabview.add("📋 Task Queue")
        self.tab_history = self.tabview.add("📜 Download History")

        self._build_single_tab()
        self._build_queue_tab()
        self._build_history_tab()

        # 3. Status Bar
        self.status_bar = ctk.CTkLabel(
            self, text="Ready. Enter a URL to begin.",
            font=ctk.CTkFont(size=12), text_color="#999999", anchor="w"
        )
        self.status_bar.grid(row=2, column=0, padx=28, pady=(2, 2), sticky="ew")

        # 4. Copyright Footer
        copyright_label = ctk.CTkLabel(
            self, text="(C) Copyright 2026. OrcusExtreme",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#63667B"
        )
        copyright_label.grid(row=3, column=0, padx=28, pady=(2, 8), sticky="s")

    # -------------------------------------------------------------
    # Tab 1: Single Download
    # -------------------------------------------------------------
    def _build_single_tab(self):
        tab = self.tab_single
        tab.grid_columnconfigure(0, weight=1)

        # URL Row
        url_frame = ctk.CTkFrame(tab, fg_color="transparent")
        url_frame.pack(fill="x", padx=12, pady=(8, 4))
        url_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(url_frame, text="Media URL:", font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w")

        self.single_platform_badge = ctk.CTkLabel(
            url_frame, text="[Platform: Waiting]",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#8E8E93"
        )
        self.single_platform_badge.grid(row=0, column=1, sticky="e")

        self.single_url_entry = ctk.CTkEntry(
            url_frame, placeholder_text="Paste YouTube, CHZZK, SOOP, X/Twitter, Instagram Reels, TikTok URL...",
            height=36, font=ctk.CTkFont(size=12)
        )
        self.single_url_entry.grid(row=1, column=0, padx=(0, 8), pady=(4, 0), sticky="ew")
        self.single_url_entry.bind("<KeyRelease>", self._on_single_url_change)
        self.single_url_entry.bind("<FocusOut>", lambda e: self._fetch_thumbnail_preview())

        paste_btn = ctk.CTkButton(
            url_frame, text="Paste", width=74, height=36,
            fg_color="#434556", hover_color="#53566B",
            command=self._paste_single_url
        )
        paste_btn.grid(row=1, column=1, pady=(4, 0), sticky="e")

        # Live Thumbnail & Info Card
        self.preview_card = ctk.CTkFrame(tab, fg_color=("#22232E", "#15161E"), corner_radius=10)
        self.preview_card.pack(fill="x", padx=12, pady=5)
        self.preview_card.grid_columnconfigure(1, weight=1)

        self.thumb_label = ctk.CTkLabel(
            self.preview_card, text="🎬\nPreview",
            width=130, height=75, corner_radius=8,
            fg_color=("#2B2D3A", "#1E1F29"), text_color="#8E8E93",
            font=ctk.CTkFont(size=12)
        )
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=10, pady=8, sticky="nsw")

        self.preview_title = ctk.CTkLabel(
            self.preview_card, text="Title: Enter URL to auto-fetch info",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w", wraplength=520
        )
        self.preview_title.grid(row=0, column=1, padx=(4, 10), pady=(8, 2), sticky="ew")

        self.preview_meta = ctk.CTkLabel(
            self.preview_card, text="Uploader: -  |  Duration: -  |  Platform: -",
            font=ctk.CTkFont(size=11), text_color="#A0A5B5", anchor="w"
        )
        self.preview_meta.grid(row=1, column=1, padx=(4, 10), pady=0, sticky="ew")

        self.preview_status_lbl = ctk.CTkLabel(
            self.preview_card, text="Status: Ready",
            font=ctk.CTkFont(size=11), text_color="#63667B", anchor="w"
        )
        self.preview_status_lbl.grid(row=2, column=1, padx=(4, 10), pady=(0, 6), sticky="ew")

        # Download Settings
        opts_frame = ctk.CTkFrame(tab, fg_color=("#22232E", "#15161E"), corner_radius=10)
        opts_frame.pack(fill="x", padx=12, pady=5)
        opts_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(opts_frame, text="Format:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=(12, 6), pady=6, sticky="w"
        )
        self.single_format_seg = ctk.CTkSegmentedButton(
            opts_frame, values=["🎬 Video (MP4)", "🎵 Audio (MP3 320k)"],
            selected_color="#6C66EB", selected_hover_color="#5A54D6", height=32,
            command=self._on_format_changed
        )
        self.single_format_seg.set("🎬 Video (MP4)")
        self.single_format_seg.grid(row=0, column=1, padx=6, pady=6, sticky="ew")

        ctk.CTkLabel(opts_frame, text="Resolution:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=2, padx=(12, 6), pady=6, sticky="w"
        )
        self.single_res_menu = ctk.CTkOptionMenu(
            opts_frame,
            values=["Best (Original)", "2160p (4K)", "1440p (2K)", "1080p (FHD)", "720p (HD)", "480p", "360p"],
            fg_color="#3A3D4E", button_color="#4B4E63", height=32
        )
        self.single_res_menu.set("Best (Original)")
        self.single_res_menu.grid(row=0, column=3, padx=(6, 12), pady=6, sticky="ew")

        # Range Clipping
        self.clip_enabled_var = ctk.BooleanVar(value=False)
        self.clip_cb = ctk.CTkCheckBox(
            opts_frame, text="Clip specific range:",
            variable=self.clip_enabled_var, font=ctk.CTkFont(size=12),
            command=self._on_clip_toggle
        )
        self.clip_cb.grid(row=1, column=0, columnspan=2, padx=(12, 6), pady=6, sticky="w")

        clip_inputs_frame = ctk.CTkFrame(opts_frame, fg_color="transparent")
        clip_inputs_frame.grid(row=1, column=2, columnspan=2, padx=(6, 12), pady=6, sticky="ew")
        clip_inputs_frame.grid_columnconfigure((1, 3), weight=1)

        ctk.CTkLabel(clip_inputs_frame, text="Start:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0, 4))
        self.clip_start_entry = ctk.CTkEntry(
            clip_inputs_frame, placeholder_text="00:00:00", width=68, height=28,
            font=ctk.CTkFont(size=11), state="disabled"
        )
        self.clip_start_entry.grid(row=0, column=1, padx=(0, 8), sticky="ew")

        ctk.CTkLabel(clip_inputs_frame, text="End:", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=(0, 4))
        self.clip_end_entry = ctk.CTkEntry(
            clip_inputs_frame, placeholder_text="00:01:30", width=68, height=28,
            font=ctk.CTkFont(size=11), state="disabled"
        )
        self.clip_end_entry.grid(row=0, column=3, sticky="ew")

        # Destination Folder
        ctk.CTkLabel(opts_frame, text="Save Folder:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=2, column=0, padx=(12, 6), pady=(4, 8), sticky="w"
        )
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(default_dir):
            default_dir = os.getcwd()

        self.single_dir_entry = ctk.CTkEntry(opts_frame, height=32, font=ctk.CTkFont(size=11))
        self.single_dir_entry.insert(0, default_dir)
        self.single_dir_entry.grid(row=2, column=1, columnspan=2, padx=6, pady=(4, 8), sticky="ew")

        single_browse_btn = ctk.CTkButton(
            opts_frame, text="Browse...", width=74, height=32,
            fg_color="#434556", hover_color="#53566B",
            command=lambda: self._browse_directory(self.single_dir_entry)
        )
        single_browse_btn.grid(row=2, column=3, padx=(6, 12), pady=(4, 8), sticky="e")

        # Action Buttons
        btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=5)
        btn_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.single_start_btn = ctk.CTkButton(
            btn_frame, text="🚀 Start Download", height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#6C66EB", hover_color="#5A54D6",
            command=self._start_single_download
        )
        self.single_start_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.single_pause_btn = ctk.CTkButton(
            btn_frame, text="⏸️ Pause", height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#E67E22", hover_color="#D35400",
            state="disabled",
            command=self._toggle_single_pause
        )
        self.single_pause_btn.grid(row=0, column=1, padx=4, sticky="ew")

        self.single_cancel_btn = ctk.CTkButton(
            btn_frame, text="⏹️ Cancel", height=40,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#D9534F", hover_color="#C9302C",
            state="disabled",
            command=self._cancel_single_download
        )
        self.single_cancel_btn.grid(row=0, column=2, padx=4, sticky="ew")

        self.single_folder_btn = ctk.CTkButton(
            btn_frame, text="📂 Open Folder", height=40,
            font=ctk.CTkFont(size=13),
            fg_color="#3A3D4E", hover_color="#4B4E63",
            command=lambda: history_manager.open_file_folder(self.single_downloaded_path or self.single_dir_entry.get())
        )
        self.single_folder_btn.grid(row=0, column=3, padx=(4, 0), sticky="ew")

        # Progress Dashboard
        dash = ctk.CTkFrame(tab, fg_color=("#22232E", "#15161E"), corner_radius=10)
        dash.pack(fill="x", padx=12, pady=(4, 8))
        dash.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.single_progress_bar = ctk.CTkProgressBar(
            dash, height=12, corner_radius=6, progress_color="#32E6AA"
        )
        self.single_progress_bar.set(0.0)
        self.single_progress_bar.grid(row=0, column=0, columnspan=4, padx=12, pady=(10, 8), sticky="ew")

        self.single_lbl_pct = self._create_metric_box(dash, "Progress", "0.0%", row=1, col=0)
        self.single_lbl_size = self._create_metric_box(dash, "Downloaded Size", "0.0 / 0.0 MB", row=1, col=1)
        self.single_lbl_speed = self._create_metric_box(dash, "Speed", "0.00 MB/s", row=1, col=2)
        self.single_lbl_eta = self._create_metric_box(dash, "Remaining (ETA)", "--:--", row=1, col=3)

    # -------------------------------------------------------------
    # Tab 2: Interactive Task Queue
    # -------------------------------------------------------------
    def _build_queue_tab(self):
        tab = self.tab_queue
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        # Input Frame to add a single item to queue
        add_frame = ctk.CTkFrame(tab, fg_color=("#22232E", "#15161E"), corner_radius=10)
        add_frame.pack(fill="x", padx=12, pady=(8, 6))
        add_frame.grid_columnconfigure(0, weight=1)

        # Row 0: URL & Platform
        url_sub = ctk.CTkFrame(add_frame, fg_color="transparent")
        url_sub.pack(fill="x", padx=12, pady=(8, 4))
        url_sub.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(url_sub, text="Add Link to Queue:", font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w")
        self.q_input_badge = ctk.CTkLabel(url_sub, text="[Platform: Waiting]", font=ctk.CTkFont(size=11), text_color="#8E8E93")
        self.q_input_badge.grid(row=0, column=1, sticky="e")

        self.q_url_entry = ctk.CTkEntry(
            url_sub, placeholder_text="Paste a video URL to add into the queue list...",
            height=34, font=ctk.CTkFont(size=12)
        )
        self.q_url_entry.grid(row=1, column=0, padx=(0, 6), pady=(4, 0), sticky="ew")
        self.q_url_entry.bind("<KeyRelease>", self._on_q_url_change)

        q_paste_btn = ctk.CTkButton(
            url_sub, text="Paste", width=64, height=34,
            fg_color="#434556", hover_color="#53566B",
            command=self._paste_q_url
        )
        q_paste_btn.grid(row=1, column=1, pady=(4, 0), sticky="e")

        # Row 1: Format, Resolution, Output dir & Add Button
        opts_sub = ctk.CTkFrame(add_frame, fg_color="transparent")
        opts_sub.pack(fill="x", padx=12, pady=(4, 8))
        opts_sub.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(opts_sub, text="Format:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=0, padx=(0, 4), sticky="w")
        self.q_format_seg = ctk.CTkSegmentedButton(
            opts_sub, values=["🎬 MP4", "🎵 MP3"],
            selected_color="#6C66EB", selected_hover_color="#5A54D6", height=28
        )
        self.q_format_seg.set("🎬 MP4")
        self.q_format_seg.grid(row=0, column=1, padx=(0, 10), sticky="w")

        ctk.CTkLabel(opts_sub, text="Resolution:", font=ctk.CTkFont(size=11, weight="bold")).grid(row=0, column=2, padx=(0, 4), sticky="w")
        self.q_res_menu = ctk.CTkOptionMenu(
            opts_sub,
            values=["Best (Original)", "2160p (4K)", "1440p (2K)", "1080p (FHD)", "720p (HD)", "480p", "360p"],
            fg_color="#3A3D4E", button_color="#4B4E63", width=110, height=28
        )
        self.q_res_menu.set("Best (Original)")
        self.q_res_menu.grid(row=0, column=3, padx=(0, 10), sticky="w")

        add_btn = ctk.CTkButton(
            opts_sub, text="➕ Add to Queue", width=120, height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2ECC71", hover_color="#27AE60",
            command=self._add_item_to_queue
        )
        add_btn.grid(row=0, column=4, sticky="e")

        # Global Queue Controls Bar
        ctrl_frame = ctk.CTkFrame(tab, fg_color="transparent")
        ctrl_frame.pack(fill="x", padx=12, pady=(0, 6))
        ctrl_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.q_start_all_btn = ctk.CTkButton(
            ctrl_frame, text="🚀 Start All", height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#6C66EB", hover_color="#5A54D6",
            command=self._start_queue_all
        )
        self.q_start_all_btn.grid(row=0, column=0, padx=(0, 4), sticky="ew")

        self.q_pause_all_btn = ctk.CTkButton(
            ctrl_frame, text="⏸️ Pause All", height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#E67E22", hover_color="#D35400",
            command=self._pause_queue_all
        )
        self.q_pause_all_btn.grid(row=0, column=1, padx=4, sticky="ew")

        self.q_stop_all_btn = ctk.CTkButton(
            ctrl_frame, text="⏹️ Stop All", height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#D9534F", hover_color="#C9302C",
            command=self._stop_queue_all
        )
        self.q_stop_all_btn.grid(row=0, column=2, padx=4, sticky="ew")

        clear_completed_btn = ctk.CTkButton(
            ctrl_frame, text="🧹 Clear Finished", height=34,
            font=ctk.CTkFont(size=12),
            fg_color="#3A3D4E", hover_color="#4B4E63",
            command=self._clear_completed_queue
        )
        clear_completed_btn.grid(row=0, column=3, padx=4, sticky="ew")

        open_out_btn = ctk.CTkButton(
            ctrl_frame, text="📂 Open Output", height=34,
            font=ctk.CTkFont(size=12),
            fg_color="#3A3D4E", hover_color="#4B4E63",
            command=lambda: history_manager.open_file_folder(self.single_dir_entry.get())
        )
        open_out_btn.grid(row=0, column=4, padx=(4, 0), sticky="ew")

        # Scrollable Task Queue Cards
        self.queue_scroll = ctk.CTkScrollableFrame(tab, height=360, fg_color=("#22232E", "#15161E"))
        self.queue_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.queue_scroll.grid_columnconfigure(0, weight=1)

        self.q_empty_label = ctk.CTkLabel(
            self.queue_scroll, text="Queue is currently empty.\nEnter URLs above and click [➕ Add to Queue] to start managing multiple downloads.",
            font=ctk.CTkFont(size=13), text_color="#8E8E93"
        )
        self.q_empty_label.pack(pady=40)

    # -------------------------------------------------------------
    # Tab 3: History
    # -------------------------------------------------------------
    def _build_history_tab(self):
        tab = self.tab_history
        tab.grid_columnconfigure(0, weight=1)

        # Header of History
        top_bar = ctk.CTkFrame(tab, fg_color="transparent")
        top_bar.pack(fill="x", padx=12, pady=(10, 6))
        top_bar.grid_columnconfigure(0, weight=1)

        self.history_count_lbl = ctk.CTkLabel(
            top_bar, text="0 Completed Downloads",
            font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
        )
        self.history_count_lbl.grid(row=0, column=0, sticky="w")

        refresh_btn = ctk.CTkButton(
            top_bar, text="🔄 Refresh", width=76, height=30,
            fg_color="#3A3D4E", hover_color="#4B4E63",
            command=self._load_history_list
        )
        refresh_btn.grid(row=0, column=1, padx=(0, 6), sticky="e")

        clear_btn = ctk.CTkButton(
            top_bar, text="🗑️ Clear All", width=76, height=30,
            fg_color="#D9534F", hover_color="#C9302C",
            command=self._clear_all_history
        )
        clear_btn.grid(row=0, column=2, sticky="e")

        # Scrollable list for history items
        self.history_scroll = ctk.CTkScrollableFrame(tab, height=400, fg_color=("#22232E", "#15161E"))
        self.history_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.history_scroll.grid_columnconfigure(0, weight=1)

        # Auto refresh on tab switch
        self.tabview.configure(command=self._on_tab_changed)
        self._load_history_list()

    def _on_tab_changed(self):
        if self.tabview.get() == "📜 Download History":
            self._load_history_list()

    def _load_history_list(self):
        for child in self.history_scroll.winfo_children():
            child.destroy()

        records = history_manager.get_history()
        self.history_count_lbl.configure(text=f"{len(records)} Completed Downloads")

        if not records:
            empty_lbl = ctk.CTkLabel(
                self.history_scroll, text="No download history found.",
                font=ctk.CTkFont(size=13), text_color="#8E8E93"
            )
            empty_lbl.pack(pady=40)
            return

        for rec in records:
            card = ctk.CTkFrame(self.history_scroll, fg_color=("#2B2D3A", "#1E1F29"), corner_radius=8)
            card.pack(fill="x", padx=4, pady=4)
            card.grid_columnconfigure(0, weight=1)

            title_text = rec.get('title', 'Unknown Title')
            timestamp = rec.get('timestamp', '')
            platform = rec.get('platform', 'Media')
            fmt = rec.get('format', 'MP4')
            size_mb = rec.get('file_size_mb', 0)
            filepath = rec.get('filepath') or rec.get('file_path') or ''
            rec_id = rec.get('id')

            lbl_title = ctk.CTkLabel(
                card, text=f"[{platform}] {title_text}",
                font=ctk.CTkFont(size=13, weight="bold"), anchor="w"
            )
            lbl_title.grid(row=0, column=0, padx=12, pady=(8, 2), sticky="w")

            meta_str = f"Format: {fmt} | Size: {size_mb:.1f} MB | Date: {timestamp}"
            lbl_meta = ctk.CTkLabel(
                card, text=meta_str, font=ctk.CTkFont(size=11),
                text_color="#A0A5B5", anchor="w"
            )
            lbl_meta.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

            # Actions
            btn_box = ctk.CTkFrame(card, fg_color="transparent")
            btn_box.grid(row=0, column=1, rowspan=2, padx=12, pady=8, sticky="e")

            open_btn = ctk.CTkButton(
                btn_box, text="📂 Open Folder", width=86, height=28,
                fg_color="#3A3D4E", hover_color="#4B4E63",
                command=lambda p=filepath: history_manager.open_file_folder(p)
            )
            open_btn.pack(side="left", padx=3)

            play_btn = ctk.CTkButton(
                btn_box, text="▶️ Play", width=62, height=28,
                fg_color="#6C66EB", hover_color="#5A54D6",
                command=lambda p=filepath: history_manager.play_file(p)
            )
            play_btn.pack(side="left", padx=3)

            del_btn = ctk.CTkButton(
                btn_box, text="❌", width=34, height=28,
                fg_color="#D9534F", hover_color="#C9302C",
                command=lambda i=rec_id: self._delete_history_item(i)
            )
            del_btn.pack(side="left", padx=3)

    def _delete_history_item(self, rec_id):
        history_manager.delete_history(rec_id)
        self._load_history_list()

    def _clear_all_history(self):
        if messagebox.askyesno("Clear History", "Are you sure you want to clear all download history records?\n(Downloaded media files will NOT be deleted)"):
            history_manager.clear_history()
            self._load_history_list()

    # -------------------------------------------------------------
    # Queue Management & Card UI Logic
    # -------------------------------------------------------------
    def _on_q_url_change(self, event=None):
        url = self.q_url_entry.get().strip()
        platform = downloader_core.detect_platform(url)
        colors = {
            'CHZZK': ("#00FFA3", "[CHZZK]"),
            'SOOP': ("#2B7FFF", "[SOOP]"),
            'YouTube': ("#FF3B30", "[YouTube]"),
            'X (Twitter)': ("#1DA1F2", "[X / Twitter]"),
            'Instagram': ("#E1306C", "[Instagram]"),
            'TikTok': ("#00F2FE", "[TikTok]"),
            'NaverTV': ("#03CF5D", "[NaverTV]"),
            'Twitch': ("#9146FF", "[Twitch]"),
            'Other': ("#8E8E93", "[Detected]")
        }
        color, text = colors.get(platform, ("#8E8E93", "[Platform: Waiting]"))
        self.q_input_badge.configure(text=text, text_color=color)

    def _paste_q_url(self):
        try:
            text = self.clipboard_get()
            self.q_url_entry.delete(0, 'end')
            self.q_url_entry.insert(0, text.strip())
            self._on_q_url_change()
        except Exception:
            pass

    def _add_item_to_queue(self):
        url = self.q_url_entry.get().strip()
        if not url or not url.startswith("http"):
            messagebox.showwarning("Invalid URL", "Please enter a valid http/https media link.")
            return

        fmt_val = self.q_format_seg.get()
        download_type = "audio" if "MP3" in fmt_val else "video"

        res_raw = self.q_res_menu.get()
        res_map = {
            "Best (Original)": "best",
            "2160p (4K)": "2160",
            "1440p (2K)": "1440",
            "1080p (FHD)": "1080",
            "720p (HD)": "720",
            "480p": "480",
            "360p": "360"
        }
        resolution = res_map.get(res_raw, "best")
        out_dir = self.single_dir_entry.get().strip()

        self.queue_counter += 1
        item = QueueItem(self.queue_counter, url, download_type, resolution, out_dir)
        self.queue_items.append(item)

        # Clear input
        self.q_url_entry.delete(0, 'end')
        self._on_q_url_change()

        # Render Queue Card
        self._render_queue_cards()

        # Fetch title asynchronously in background
        threading.Thread(target=self._async_fetch_queue_meta, args=(item,), daemon=True).start()

    def _async_fetch_queue_meta(self, item: QueueItem):
        info = downloader_core.fetch_preview_info(item.url)
        if info:
            item.title = info.get('title', item.url)
            item.uploader = info.get('uploader', '')
            item.platform = info.get('platform', item.platform)
            self.after(0, lambda: self._update_queue_card_info(item))

    def _render_queue_cards(self):
        if not self.queue_items:
            self.q_empty_label.pack(pady=40)
            return
        else:
            self.q_empty_label.pack_forget()

        # Ensure every item has its card frame
        for idx, it in enumerate(self.queue_items):
            if it.card_frame is None or not it.card_frame.winfo_exists():
                self._create_queue_card_widget(it)

    def _create_queue_card_widget(self, it: QueueItem):
        card = ctk.CTkFrame(self.queue_scroll, fg_color=("#2B2D3A", "#1E1F29"), corner_radius=8)
        card.pack(fill="x", padx=4, pady=4)
        card.grid_columnconfigure(0, weight=1)
        it.card_frame = card

        # Top row: Platform badge + Title
        top_row = ctk.CTkFrame(card, fg_color="transparent")
        top_row.grid(row=0, column=0, padx=12, pady=(8, 2), sticky="ew")
        top_row.grid_columnconfigure(1, weight=1)

        badge_colors = {
            'CHZZK': "#00FFA3", 'SOOP': "#2B7FFF", 'YouTube': "#FF3B30",
            'X (Twitter)': "#1DA1F2", 'Instagram': "#E1306C", 'TikTok': "#00F2FE",
            'NaverTV': "#03CF5D", 'Twitch': "#9146FF"
        }
        b_color = badge_colors.get(it.platform, "#8E8E93")

        lbl_badge = ctk.CTkLabel(
            top_row, text=f"[{it.platform}]",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=b_color
        )
        lbl_badge.grid(row=0, column=0, padx=(0, 6), sticky="w")

        it.lbl_title = ctk.CTkLabel(
            top_row, text=it.title,
            font=ctk.CTkFont(size=12, weight="bold"), anchor="w"
        )
        it.lbl_title.grid(row=0, column=1, sticky="ew")

        # Action Buttons on Top-Right
        btn_box = ctk.CTkFrame(card, fg_color="transparent")
        btn_box.grid(row=0, column=1, rowspan=2, padx=10, pady=6, sticky="e")

        it.btn_start = ctk.CTkButton(
            btn_box, text="▶️ Start", width=62, height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color="#2ECC71", hover_color="#27AE60",
            command=lambda i=it: self._start_individual_queue_item(i)
        )
        it.btn_start.pack(side="left", padx=2)

        it.btn_pause = ctk.CTkButton(
            btn_box, text="⏸️", width=34, height=28,
            fg_color="#E67E22", hover_color="#D35400", state="disabled",
            command=lambda i=it: self._toggle_queue_item_pause(i)
        )
        it.btn_pause.pack(side="left", padx=2)

        it.btn_cancel = ctk.CTkButton(
            btn_box, text="⏹️", width=34, height=28,
            fg_color="#D9534F", hover_color="#C9302C", state="disabled",
            command=lambda i=it: self._cancel_queue_item(i)
        )
        it.btn_cancel.pack(side="left", padx=2)

        it.btn_remove = ctk.CTkButton(
            btn_box, text="❌", width=32, height=28,
            fg_color="#434556", hover_color="#53566B",
            command=lambda i=it: self._remove_queue_item(i)
        )
        it.btn_remove.pack(side="left", padx=2)

        # Middle row: Progress Bar
        it.progress_bar = ctk.CTkProgressBar(card, height=8, corner_radius=4, progress_color="#32E6AA")
        it.progress_bar.set(0.0)
        it.progress_bar.grid(row=1, column=0, padx=12, pady=2, sticky="ew")

        # Bottom row: Details & Status
        bot_row = ctk.CTkFrame(card, fg_color="transparent")
        bot_row.grid(row=2, column=0, columnspan=2, padx=12, pady=(2, 8), sticky="ew")
        bot_row.grid_columnconfigure(0, weight=1)

        fmt_desc = "MP3 Audio (320k)" if it.download_type == "audio" else f"Video ({it.resolution})"
        it.lbl_info = ctk.CTkLabel(
            bot_row, text=f"Format: {fmt_desc} | Size: 0.0 MB | Speed: 0.0 MB/s",
            font=ctk.CTkFont(size=11), text_color="#A0A5B5", anchor="w"
        )
        it.lbl_info.grid(row=0, column=0, sticky="w")

        it.lbl_status = ctk.CTkLabel(
            bot_row, text=f"Status: {it.status}",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="#8E8E93", anchor="e"
        )
        it.lbl_status.grid(row=0, column=1, sticky="e")

    def _update_queue_card_info(self, it: QueueItem):
        if it.lbl_title and it.lbl_title.winfo_exists():
            it.lbl_title.configure(text=it.title)

    def _remove_queue_item(self, it: QueueItem):
        if it.worker and it.worker.is_alive():
            it.worker.cancel()
        if it.card_frame and it.card_frame.winfo_exists():
            it.card_frame.destroy()
        if it in self.queue_items:
            self.queue_items.remove(it)
        if not self.queue_items:
            self.q_empty_label.pack(pady=40)

    def _clear_completed_queue(self):
        to_remove = [it for it in self.queue_items if it.status in ("Completed", "Cancelled", "Error")]
        for it in to_remove:
            self._remove_queue_item(it)

    # Individual Task Execution
    def _start_individual_queue_item(self, it: QueueItem):
        if it.worker and it.worker.is_alive():
            return

        it.status = "Downloading"
        it.btn_start.configure(state="disabled")
        it.btn_pause.configure(state="normal", text="⏸️", fg_color="#E67E22")
        it.btn_cancel.configure(state="normal")
        it.btn_remove.configure(state="disabled")
        it.lbl_status.configure(text="Status: Downloading", text_color="#32E6AA")

        callbacks = {
            'on_start': lambda title, up, dur, plat: self._cb_q_start(it, title, up, dur, plat),
            'on_progress': lambda p, dl, tot, spd, eta, fn: self._cb_q_progress(it, p, dl, tot, spd, eta, fn),
            'on_status': lambda msg: self._cb_q_status(it, msg),
            'on_finish': lambda s, m, f: self._cb_q_finish(it, s, m, f),
        }

        it.worker = downloader_core.DownloaderWorker(
            it.url, it.output_dir, callbacks,
            download_type=it.download_type,
            resolution=it.resolution
        )
        it.worker.start()

    def _toggle_queue_item_pause(self, it: QueueItem):
        if not it.worker or not it.worker.is_alive():
            return
        if it.worker.is_paused:
            it.worker.resume()
            it.status = "Downloading"
            it.btn_pause.configure(text="⏸️", fg_color="#E67E22")
            it.lbl_status.configure(text="Status: Downloading", text_color="#32E6AA")
        else:
            it.worker.pause()
            it.status = "Paused"
            it.btn_pause.configure(text="▶️", fg_color="#2ECC71")
            it.lbl_status.configure(text="Status: Paused", text_color="#E67E22")

    def _cancel_queue_item(self, it: QueueItem):
        if it.worker and it.worker.is_alive():
            it.worker.cancel()
            it.status = "Cancelled"
            it.lbl_status.configure(text="Status: Cancelled", text_color="#D9534F")

    # Callbacks for individual queue items
    def _cb_q_start(self, it: QueueItem, title, uploader, dur, plat):
        it.title = title
        it.uploader = uploader
        self.after(0, lambda: self._ui_q_start(it))

    def _ui_q_start(self, it: QueueItem):
        if it.lbl_title and it.lbl_title.winfo_exists():
            it.lbl_title.configure(text=it.title)

    def _cb_q_progress(self, it: QueueItem, pct, dl_mb, tot_mb, spd, eta, fn):
        it.pct = pct
        it.downloaded_mb = dl_mb
        it.total_mb = tot_mb
        it.speed = spd
        it.eta = eta
        self.after(0, lambda: self._ui_q_progress(it))

    def _ui_q_progress(self, it: QueueItem):
        if it.progress_bar and it.progress_bar.winfo_exists():
            it.progress_bar.set(it.pct / 100.0)
            fmt_desc = "MP3 (320k)" if it.download_type == "audio" else f"MP4 ({it.resolution})"
            info_txt = f"{fmt_desc} | {it.downloaded_mb:.1f}/{it.total_mb:.1f} MB ({it.pct:.1f}%) | {it.speed} | ETA: {it.eta}"
            it.lbl_info.configure(text=info_txt)

    def _cb_q_status(self, it: QueueItem, msg):
        self.after(0, lambda: self.status_bar.configure(text=f"Queue: {msg}"))

    def _cb_q_finish(self, it: QueueItem, success, message, filepath):
        self.after(0, lambda: self._ui_q_finish(it, success, message, filepath))

    def _ui_q_finish(self, it: QueueItem, success, message, filepath):
        it.btn_start.configure(state="normal", text="▶️ Restart")
        it.btn_pause.configure(state="disabled")
        it.btn_cancel.configure(state="disabled")
        it.btn_remove.configure(state="normal")
        it.filepath = filepath

        if success and filepath and os.path.exists(filepath):
            it.status = "Completed"
            it.progress_bar.set(1.0)
            it.lbl_status.configure(text="Status: Completed", text_color="#32E6AA")
            # Save to history
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            history_manager.add_history(
                title=os.path.basename(filepath),
                url=it.url,
                file_path=filepath,
                format_type="MP3" if it.download_type == "audio" else "MP4",
                file_size_mb=file_size_mb,
                platform=it.platform
            )
        else:
            if "cancel" in message.lower():
                it.status = "Cancelled"
                it.lbl_status.configure(text="Status: Cancelled", text_color="#D9534F")
            else:
                it.status = "Error"
                it.lbl_status.configure(text="Status: Failed", text_color="#D9534F")

        # Check if queue batch is running
        if self.is_queue_running:
            self._run_next_queue_item()

    # Batch Queue Execution
    def _start_queue_all(self):
        if not self.queue_items:
            messagebox.showinfo("Queue Empty", "Please add one or more download links to the queue first.")
            return

        self.is_queue_running = True
        self.q_start_all_btn.configure(state="disabled")
        self.current_queue_index = -1
        self._run_next_queue_item()

    def _run_next_queue_item(self):
        if not self.is_queue_running:
            return

        # Find next waiting or uncompleted item
        next_item = None
        for it in self.queue_items:
            if it.status in ("Waiting", "Cancelled", "Error"):
                next_item = it
                break

        if next_item:
            self._start_individual_queue_item(next_item)
        else:
            # All done
            self.is_queue_running = False
            self.q_start_all_btn.configure(state="normal")
            self.status_bar.configure(text="All tasks in queue have completed.")
            if PYSTRAY_AVAILABLE and self.tray_icon:
                try:
                    self.tray_icon.notify("Queue Finished", "All queued download tasks have finished!")
                except Exception:
                    pass
            messagebox.showinfo("Queue Finished", "All queued downloads have been processed!")

    def _pause_queue_all(self):
        for it in self.queue_items:
            if it.status == "Downloading":
                self._toggle_queue_item_pause(it)

    def _stop_queue_all(self):
        self.is_queue_running = False
        self.q_start_all_btn.configure(state="normal")
        for it in self.queue_items:
            if it.status == "Downloading" or (it.worker and it.worker.is_alive()):
                self._cancel_queue_item(it)

    # -------------------------------------------------------------
    # Single Download Handlers & Live Preview
    # -------------------------------------------------------------
    def _create_metric_box(self, parent, label_text, default_val, row, col):
        box = ctk.CTkFrame(parent, fg_color=("#1A1B24", "#0E0F15"), corner_radius=6)
        box.grid(row=row, column=col, padx=6, pady=(0, 10), sticky="nsew")
        lbl = ctk.CTkLabel(box, text=label_text, font=ctk.CTkFont(size=11), text_color="#8E8E93")
        lbl.pack(pady=(6, 1))
        val_lbl = ctk.CTkLabel(box, text=default_val, font=ctk.CTkFont(size=12, weight="bold"))
        val_lbl.pack(pady=(0, 6))
        return val_lbl

    def _on_single_url_change(self, event=None):
        url = self.single_url_entry.get().strip()
        platform = downloader_core.detect_platform(url)
        colors = {
            'CHZZK': ("#00FFA3", "[CHZZK]"),
            'SOOP': ("#2B7FFF", "[SOOP]"),
            'YouTube': ("#FF3B30", "[YouTube]"),
            'X (Twitter)': ("#1DA1F2", "[X / Twitter]"),
            'Instagram': ("#E1306C", "[Instagram]"),
            'TikTok': ("#00F2FE", "[TikTok]"),
            'NaverTV': ("#03CF5D", "[NaverTV]"),
            'Twitch': ("#9146FF", "[Twitch]"),
            'Other': ("#8E8E93", "[Detected]")
        }
        color, text = colors.get(platform, ("#8E8E93", "[Platform: Waiting]"))
        self.single_platform_badge.configure(text=text, text_color=color)

        if url.startswith("http") and url != self.last_preview_url:
            self.after(600, self._fetch_thumbnail_preview)

    def _fetch_thumbnail_preview(self):
        url = self.single_url_entry.get().strip()
        if not url.startswith("http") or url == self.last_preview_url:
            return

        self.last_preview_url = url
        self.preview_status_lbl.configure(text="Status: Fetching preview metadata...", text_color="#E67E22")

        def _worker():
            info = downloader_core.fetch_preview_info(url)
            self.after(0, lambda: self._apply_preview_info(info))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_preview_info(self, info):
        if not info:
            self.preview_status_lbl.configure(text="Status: Info lookup failed (Download can still proceed)", text_color="#8E8E93")
            return

        self.preview_title.configure(text=f"Title: {info.get('title', 'Unknown')}")
        self.preview_meta.configure(
            text=f"Uploader: {info.get('uploader', 'Unknown')}  |  Duration: {info.get('duration_str', 'N/A')}  |  Platform: {info.get('platform', '')}"
        )
        self.preview_status_lbl.configure(text="Status: Ready to download", text_color="#32E6AA")

        pil_img = info.get('thumbnail_image')
        if pil_img:
            try:
                ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(130, 75))
                self.thumb_label.configure(image=ctk_img, text="")
            except Exception:
                pass

    def _paste_single_url(self):
        try:
            text = self.clipboard_get()
            self.single_url_entry.delete(0, 'end')
            self.single_url_entry.insert(0, text.strip())
            self._on_single_url_change()
            self._fetch_thumbnail_preview()
        except Exception:
            pass

    def _on_format_changed(self, value):
        if "MP3" in value:
            self.single_res_menu.configure(state="disabled")
        else:
            self.single_res_menu.configure(state="normal")

    def _on_clip_toggle(self):
        if self.clip_enabled_var.get():
            self.clip_start_entry.configure(state="normal")
            self.clip_end_entry.configure(state="normal")
        else:
            self.clip_start_entry.configure(state="disabled")
            self.clip_end_entry.configure(state="disabled")

    def _browse_directory(self, entry_widget):
        folder = filedialog.askdirectory(initialdir=entry_widget.get())
        if folder:
            entry_widget.delete(0, 'end')
            entry_widget.insert(0, folder)

    # Single Download Execution
    def _start_single_download(self):
        url = self.single_url_entry.get().strip()
        out_dir = self.single_dir_entry.get().strip()

        if not url:
            messagebox.showwarning("Input Required", "Please enter a valid media URL.")
            return
        if not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to create output folder:\n{str(e)}")
                return

        fmt_val = self.single_format_seg.get()
        download_type = "audio" if "MP3" in fmt_val else "video"

        res_raw = self.single_res_menu.get()
        res_map = {
            "Best (Original)": "best",
            "2160p (4K)": "2160",
            "1440p (2K)": "1440",
            "1080p (FHD)": "1080",
            "720p (HD)": "720",
            "480p": "480",
            "360p": "360"
        }
        resolution = res_map.get(res_raw, "best")

        clip_start, clip_end = None, None
        if self.clip_enabled_var.get():
            clip_start = self.clip_start_entry.get().strip() or None
            clip_end = self.clip_end_entry.get().strip() or None

        self.single_progress_bar.set(0.0)
        self.single_lbl_pct.configure(text="0.0%")
        self.single_lbl_size.configure(text="0.0 / 0.0 MB")
        self.single_lbl_speed.configure(text="Calculating...")
        self.single_lbl_eta.configure(text="--:--")
        self.single_downloaded_path = None

        self.single_start_btn.configure(state="disabled")
        self.single_pause_btn.configure(state="normal", text="⏸️ Pause", fg_color="#E67E22")
        self.single_cancel_btn.configure(state="normal")
        self.status_bar.configure(text="Initializing download...")

        callbacks = {
            'on_start': lambda t, u, d, p: self._cb_single_start(t, u, d, p, download_type),
            'on_progress': self._cb_single_progress,
            'on_status': self._cb_single_status,
            'on_finish': lambda s, m, f: self._cb_single_finish(s, m, f, url, download_type),
        }

        self.single_worker = downloader_core.DownloaderWorker(
            url, out_dir, callbacks,
            download_type=download_type,
            resolution=resolution,
            clip_start=clip_start,
            clip_end=clip_end
        )
        self.single_worker.start()

    def _toggle_single_pause(self):
        if not self.single_worker or not self.single_worker.is_alive():
            return
        if self.single_worker.is_paused:
            self.single_worker.resume()
            self.single_pause_btn.configure(text="⏸️ Pause", fg_color="#E67E22", hover_color="#D35400")
            self.status_bar.configure(text="Resumed download.")
        else:
            self.single_worker.pause()
            self.single_pause_btn.configure(text="▶️ Resume", fg_color="#2ECC71", hover_color="#27AE60")
            self.status_bar.configure(text="Download paused. Click [Resume] to continue.")

    def _cancel_single_download(self):
        if self.single_worker and self.single_worker.is_alive():
            self.single_worker.cancel()
            self.status_bar.configure(text="Cancelling download...")

    def _cb_single_start(self, title, uploader, dur_str, platform, download_type):
        self.after(0, lambda: self._ui_single_start(title, uploader, dur_str, platform, download_type))

    def _ui_single_start(self, title, uploader, dur_str, platform, download_type):
        self.preview_title.configure(text=f"Title: {title}")
        self.preview_meta.configure(text=f"Uploader: {uploader}  |  Duration: {dur_str}  |  Platform: {platform}")

    def _cb_single_progress(self, pct, downloaded_mb, total_mb, speed_str, eta_str, filename):
        self.after(0, lambda: self._ui_single_progress(pct, downloaded_mb, total_mb, speed_str, eta_str))

    def _ui_single_progress(self, pct, downloaded_mb, total_mb, speed_str, eta_str):
        self.single_progress_bar.set(pct / 100.0)
        self.single_lbl_pct.configure(text=f"{pct:5.1f}%")
        self.single_lbl_size.configure(text=f"{downloaded_mb:.1f} / {total_mb:.1f} MB")
        self.single_lbl_speed.configure(text=speed_str)
        self.single_lbl_eta.configure(text=eta_str)

    def _cb_single_status(self, status_text):
        self.after(0, lambda: self.status_bar.configure(text=status_text))

    def _cb_single_finish(self, success, message, filepath, url, download_type):
        self.after(0, lambda: self._ui_single_finish(success, message, filepath, url, download_type))

    def _ui_single_finish(self, success, message, filepath, url, download_type):
        self.single_start_btn.configure(state="normal")
        self.single_pause_btn.configure(state="disabled", text="⏸️ Pause")
        self.single_cancel_btn.configure(state="disabled")
        self.single_downloaded_path = filepath
        self.status_bar.configure(text=message)

        if success and filepath and os.path.exists(filepath):
            self.single_progress_bar.set(1.0)
            self.single_lbl_pct.configure(text="100.0%")
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            history_manager.add_history(
                title=os.path.basename(filepath),
                url=url,
                file_path=filepath,
                format_type="MP3" if download_type == "audio" else "MP4",
                file_size_mb=file_size_mb,
                platform=downloader_core.detect_platform(url)
            )
            if PYSTRAY_AVAILABLE and self.tray_icon:
                try:
                    self.tray_icon.notify("Download Complete", f"Finished: {os.path.basename(filepath)}")
                except Exception:
                    pass

            messagebox.showinfo("Download Complete", f"Successfully downloaded!\n\nSaved to:\n{filepath}")
        else:
            if "cancel" in message.lower():
                self.status_bar.configure(text="Download was cancelled.")
            else:
                messagebox.showerror("Error", message)

    # -------------------------------------------------------------
    # System Tray Integration
    # -------------------------------------------------------------
    def _init_tray(self):
        try:
            image = Image.open(self.icon_png)
        except Exception:
            image = Image.new('RGB', (64, 64), color=(108, 102, 235))

        menu = pystray.Menu(
            item('Open ORCUS Downloader', self._show_from_tray, default=True),
            item('Open Save Folder', lambda: history_manager.open_file_folder(self.single_dir_entry.get())),
            pystray.Menu.SEPARATOR,
            item('Exit', self._quit_app)
        )
        self.tray_icon = pystray.Icon("ORCUS Downloader", image, "ORCUS Downloader", menu)
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _hide_to_tray(self):
        self.withdraw()
        self.is_hidden_in_tray = True
        if self.tray_icon:
            try:
                self.tray_icon.notify("ORCUS Downloader", "App is running in the system tray background.")
            except Exception:
                pass

    def _show_from_tray(self):
        self.after(0, self._restore_window)

    def _restore_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        self.is_hidden_in_tray = False

    def _on_close_window(self):
        self._hide_to_tray()

    def _quit_app(self):
        # Cancel any active single worker
        if self.single_worker and self.single_worker.is_alive():
            try:
                self.single_worker.cancel()
            except Exception:
                pass
        # Cancel any active queue workers
        for it in self.queue_items:
            if it.worker and it.worker.is_alive():
                try:
                    it.worker.cancel()
                except Exception:
                    pass
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        try:
            self.quit()
            self.destroy()
        except Exception:
            pass
        sys.exit(0)


if __name__ == "__main__":
    app = OrcusDownloaderApp()
    app.mainloop()
