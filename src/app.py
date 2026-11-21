import os
import re
import sys
import threading
from PIL import Image
import customtkinter as ctk
from tkinter import filedialog, messagebox

import downloader_core
import history_manager
import ffmpeg_manager
import js_runtime_manager
import ui_theme as ui
from ui_theme import C
from version import __version__

# System Tray support via pystray
try:
    import pystray
    from pystray import MenuItem as item
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False

ctk.set_default_color_theme("blue")
ctk.set_appearance_mode(ui.initial_appearance())

RESOLUTION_OPTIONS = ["Best (Original)", "2160p (4K)", "1440p (2K)", "1080p (FHD)", "720p (HD)", "480p", "360p"]
RES_MAP = {
    "Best (Original)": "best",
    "2160p (4K)": "2160",
    "1440p (2K)": "1440",
    "1080p (FHD)": "1080",
    "720p (HD)": "720",
    "480p": "480",
    "360p": "360",
}
FORMAT_VIDEO = "Video (MP4)"
FORMAT_AUDIO = "Audio (MP3)"

PLATFORM_LABELS = {'X (Twitter)': "X / Twitter", 'Other': "Other site"}


def _shorten(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _fit(text: str, font, max_px: int) -> str:
    """Truncates text with an ellipsis so it renders within max_px (handles wide CJK glyphs)."""
    text = text or ""
    try:
        if font.measure(text) <= max_px:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.measure(text[:mid].rstrip() + "…") <= max_px:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "…"
    except Exception:
        return _shorten(text, 60)


QUEUE_TITLE_PX = 400
HISTORY_TITLE_PX = 440


def _res_label(resolution: str) -> str:
    return "Best quality" if resolution in (None, "", "best") else f"{resolution}p"


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
        self.lbl_badge = None
        self.lbl_info = None
        self.progress_bar = None
        self.lbl_status = None
        self.btn_start = None
        self.btn_pause = None
        self.btn_cancel = None
        self.btn_remove = None


class OrcusDownloaderApp(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=C.bg)

        self.title("ORCUS Downloader")
        self.geometry("1120x820")
        self.minsize(980, 780)

        import path_utils
        self.icon_ico = path_utils.get_resource_path("app_icon.ico")
        self.icon_png = path_utils.get_resource_path("app_icon.png")

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
        self._batch_attempted = set()

        # Navigation state
        self.pages = {}
        self.nav_buttons = {}
        self.current_page = None

        # Tray state
        self.tray_icon = None
        self.is_hidden_in_tray = False

        # Font used to measure/truncate list titles (14px Roboto Medium)
        self._measure_font = ui.font(14, medium=True)

        # Build UI
        self._build_ui()

        # Initialize System Tray
        if PYSTRAY_AVAILABLE:
            self._init_tray()
            self.protocol("WM_DELETE_WINDOW", self._on_close_window)
        else:
            self.protocol("WM_DELETE_WINDOW", self._quit_app)

        # Pre-warm or auto-provision FFmpeg / Deno in background
        threading.Thread(target=self._init_engines_background, daemon=True).start()

    def _init_engines_background(self):
        """Ensures FFmpeg and the YouTube JS runtime (Deno) are available; downloads them if missing."""
        def _status(text):
            self.after(0, lambda: self.status_bar.configure(text=text))

        if not ffmpeg_manager.is_ffmpeg_available():
            _status("Setting up media engine (FFmpeg) in background...")
            try:
                ffmpeg_manager.ensure_ffmpeg(progress_callback=lambda p, m: _status(f"Setup: {m}"))
            except Exception:
                pass

        if not js_runtime_manager.find_deno_exe():
            _status("Setting up YouTube JS runtime (Deno) in background...")
            js_runtime_manager.ensure_deno(progress_callback=lambda p, m: _status(f"Setup: {m}"))

        _status("Ready. Paste a link to begin.")

    # -------------------------------------------------------------
    # App shell: top app bar, navigation drawer, content surface
    # -------------------------------------------------------------
    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_app_bar()
        self._build_nav_drawer()

        # Content surface (rounded white sheet)
        self.content = ctk.CTkFrame(self, fg_color=C.surface, corner_radius=16)
        self.content.grid(row=1, column=1, sticky="nsew", padx=(0, 16), pady=(4, 16))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        for key in ("single", "queue", "history"):
            page = ctk.CTkFrame(self.content, fg_color="transparent")
            page.grid(row=0, column=0, sticky="nsew", padx=32, pady=(24, 8))
            page.grid_remove()
            self.pages[key] = page
        self.tab_single = self.pages["single"]
        self.tab_queue = self.pages["queue"]
        self.tab_history = self.pages["history"]

        # Status bar (inside content surface)
        divider = ctk.CTkFrame(self.content, height=1, fg_color=C.outline_variant)
        divider.grid(row=1, column=0, sticky="ew", padx=16)
        status_row = ctk.CTkFrame(self.content, fg_color="transparent")
        status_row.grid(row=2, column=0, sticky="ew", padx=28, pady=(8, 10))
        status_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(status_row, text="", image=ui.icon('info', C.text_tertiary, 16)).grid(
            row=0, column=0, padx=(0, 8))
        self.status_bar = ctk.CTkLabel(
            status_row, text="Ready. Paste a link to begin.",
            font=ui.font(12), text_color=C.text_secondary, anchor="w"
        )
        self.status_bar.grid(row=0, column=1, sticky="ew")

        self._build_single_tab()
        self._build_queue_tab()
        self._build_history_tab()

        self._select_page("single")

    def _build_app_bar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent", height=64)
        bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(20, 16), pady=(8, 4))
        bar.grid_columnconfigure(2, weight=1)

        if os.path.exists(self.icon_png):
            try:
                logo_img = ctk.CTkImage(
                    light_image=Image.open(self.icon_png),
                    dark_image=Image.open(self.icon_png),
                    size=(36, 36)
                )
                ctk.CTkLabel(bar, image=logo_img, text="").grid(row=0, column=0, padx=(4, 12))
            except Exception:
                pass

        ui.label(bar, "ORCUS Downloader", 22, color=C.text_secondary).grid(row=0, column=1, sticky="w")

        # Light / dark toggle: [sun] (switch) [moon]
        theme_box = ctk.CTkFrame(bar, fg_color=C.surface_low, corner_radius=20, height=40)
        theme_box.grid(row=0, column=3, padx=(0, 8))
        ctk.CTkLabel(theme_box, text="", image=ui.icon('light_mode', C.text_secondary, 18)).pack(
            side="left", padx=(12, 6), pady=6)
        self.theme_switch = ctk.CTkSwitch(
            theme_box, text="", width=44, switch_width=40, switch_height=22,
            fg_color=C.outline_variant, progress_color=C.primary,
            button_color=("#FFFFFF", "#062E6F"), button_hover_color=("#F1F3F4", "#0B3D8C"),
            command=self._toggle_theme
        )
        self.theme_switch.pack(side="left", pady=6)
        ctk.CTkLabel(theme_box, text="", image=ui.icon('dark_mode', C.text_secondary, 18)).pack(
            side="left", padx=(2, 12), pady=6)
        if ctk.get_appearance_mode() == "Dark":
            self.theme_switch.select()
        ui.Tooltip(self.theme_switch, "Toggle light / dark theme")

        if PYSTRAY_AVAILABLE:
            ui.icon_button(bar, 'minimize', command=self._hide_to_tray, size=40,
                           hover=C.hover, tooltip="Minimize to tray").grid(row=0, column=4)

    def _build_nav_drawer(self):
        nav = ctk.CTkFrame(self, fg_color="transparent", width=244)
        nav.grid(row=1, column=0, sticky="ns", padx=(12, 12), pady=(4, 16))
        nav.pack_propagate(False)

        new_btn = ctk.CTkButton(
            nav, text="New download", image=ui.icon('add', C.on_secondary_container, 22),
            compound="left", height=56, width=172, corner_radius=16,
            fg_color=C.secondary_container, hover_color=C.secondary_container_hover,
            text_color=C.on_secondary_container, font=ui.font(14, medium=True),
            command=self._new_download
        )
        new_btn.pack(anchor="w", padx=4, pady=(4, 16))

        for key, text, icon_name in (("single", "Download", "download"),
                                     ("queue", "Queue", "queue"),
                                     ("history", "History", "history")):
            b = ctk.CTkButton(
                nav, text=text, anchor="w", height=40, corner_radius=20,
                image=ui.icon(icon_name, C.text_secondary, 20), compound="left",
                fg_color="transparent", hover_color=C.hover, text_color=C.text,
                font=ui.font(14), command=lambda k=key: self._select_page(k)
            )
            b.pack(fill="x", pady=1)
            b._icon_name = icon_name
            self.nav_buttons[key] = b

        ui.label(nav, f"v{__version__}  ·  © 2026 OrcusExtreme", 11, color=C.text_tertiary).pack(
            side="bottom", anchor="w", padx=16, pady=(0, 4))

    def _select_page(self, key):
        if self.current_page == key:
            return
        for k, page in self.pages.items():
            if k == key:
                page.grid()
            else:
                page.grid_remove()
        for k, b in self.nav_buttons.items():
            if k == key:
                b.configure(fg_color=C.primary_container, hover_color=C.primary_container,
                            text_color=C.on_primary_container, font=ui.font(14, medium=True),
                            image=ui.icon(b._icon_name, C.on_primary_container, 20))
            else:
                b.configure(fg_color="transparent", hover_color=C.hover,
                            text_color=C.text, font=ui.font(14),
                            image=ui.icon(b._icon_name, C.text_secondary, 20))
        self.current_page = key
        if key == "history":
            self._load_history_list()

    def _new_download(self):
        self._select_page("single")
        self.single_url_entry.delete(0, 'end')
        self.single_url_entry.focus_set()
        self._on_single_url_change()

    def _toggle_theme(self):
        mode = "dark" if self.theme_switch.get() else "light"
        ctk.set_appearance_mode(mode)
        ui.save_settings(appearance=mode)

    def _update_nav_counts(self):
        active = len(self.queue_items)
        self.nav_buttons["queue"].configure(text=f"Queue  ({active})" if active else "Queue")

    def _page_header(self, page, title, subtitle):
        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 20))
        hdr.grid_columnconfigure(0, weight=1)
        ui.label(hdr, title, 24).grid(row=0, column=0, sticky="w")
        sub = ui.label(hdr, subtitle, 13, color=C.text_secondary)
        sub.grid(row=1, column=0, sticky="w", pady=(2, 0))
        return hdr, sub

    def _set_platform_chip(self, chip, url):
        if not url:
            chip.configure(text="  No link  ", fg_color=C.surface_high, text_color=C.text_secondary,
                           image=ui.icon('link', C.text_secondary, 14))
            return
        platform = downloader_core.detect_platform(url)
        color = ui.PLATFORM_COLORS.get(platform, C.text_secondary)
        chip.configure(text=f"  {PLATFORM_LABELS.get(platform, platform)}  ", fg_color=C.surface_high,
                       text_color=color, image=ui.icon('smart_display', color, 14))

    # -------------------------------------------------------------
    # Page 1: Single Download
    # -------------------------------------------------------------
    def _build_single_tab(self):
        page = self.tab_single
        self._page_header(page, "Download",
                          "YouTube, CHZZK, SOOP, X, Instagram, TikTok, NaverTV, Twitch and more")

        # URL row: [ entry ............ ][platform chip][Paste]
        url_row = ctk.CTkFrame(page, fg_color="transparent")
        url_row.pack(fill="x")
        url_row.grid_columnconfigure(0, weight=1)

        self.single_url_entry = ui.entry(url_row, "Paste a video link", height=48)
        self.single_url_entry.grid(row=0, column=0, sticky="ew")
        self.single_url_entry.bind("<KeyRelease>", self._on_single_url_change)
        self.single_url_entry.bind("<FocusOut>", lambda e: self._fetch_thumbnail_preview())
        self.single_url_entry.bind("<Return>", lambda e: self._start_single_download())

        self.single_platform_badge = ui.chip(url_row, "No link", 'neutral', 'link', height=28)
        self.single_platform_badge.grid(row=0, column=1, padx=(10, 0))

        ui.tonal_button(url_row, "Paste", "content_paste", self._paste_single_url, height=48,
                        width=110).grid(row=0, column=2, padx=(10, 0))

        # Preview card
        self.preview_card = ui.card(page, radius=12)
        self.preview_card.pack(fill="x", pady=(16, 0))
        self.preview_card.grid_columnconfigure(1, weight=1)

        self._thumb_placeholder = ui.icon('movie', C.text_tertiary, 32)
        self.thumb_label = ctk.CTkLabel(
            self.preview_card, text="", image=self._thumb_placeholder,
            width=160, height=90, corner_radius=8, fg_color=C.surface_low
        )
        self.thumb_label.grid(row=0, column=0, rowspan=3, padx=12, pady=12, sticky="nsw")

        self.preview_title = ui.label(
            self.preview_card, "Paste a link to see video details", 16, medium=True,
            anchor="w", justify="left", wraplength=520
        )
        self.preview_title.grid(row=0, column=1, padx=(4, 16), pady=(14, 2), sticky="ew")

        self.preview_meta = ui.label(self.preview_card, "Channel  ·  Duration  ·  Platform", 13,
                                     color=C.text_secondary, anchor="w")
        self.preview_meta.grid(row=1, column=1, padx=(4, 16), sticky="ew")

        self.preview_status_lbl = ui.chip(self.preview_card, "Waiting for link", 'neutral', 'schedule')
        self.preview_status_lbl.grid(row=2, column=1, padx=(4, 16), pady=(6, 12), sticky="w")

        # Options
        opts = ctk.CTkFrame(page, fg_color="transparent")
        opts.pack(fill="x", pady=(20, 0))
        opts.grid_columnconfigure(4, weight=1)

        def _cap(text, row, col, padx=(0, 12), pady=0):
            ui.label(opts, text, 13, medium=True, color=C.text_secondary).grid(
                row=row, column=col, padx=padx, pady=pady, sticky="w")

        _cap("Format", 0, 0)
        self.single_format_seg = ui.segmented(opts, [FORMAT_VIDEO, FORMAT_AUDIO],
                                              command=self._on_format_changed)
        self.single_format_seg.set(FORMAT_VIDEO)
        self.single_format_seg.grid(row=0, column=1, sticky="w")

        _cap("Quality", 0, 2, padx=(28, 12))
        self.single_res_menu = ui.option_menu(opts, RESOLUTION_OPTIONS, width=180)
        self.single_res_menu.set("Best (Original)")
        self.single_res_menu.grid(row=0, column=3, sticky="w")

        # Range clipping
        self.clip_enabled_var = ctk.BooleanVar(value=False)
        self.clip_cb = ui.checkbox(opts, "Trim", variable=self.clip_enabled_var,
                                   command=self._on_clip_toggle)
        self.clip_cb.grid(row=1, column=0, pady=(14, 0), sticky="w")

        clip_inputs = ctk.CTkFrame(opts, fg_color="transparent")
        clip_inputs.grid(row=1, column=1, columnspan=4, pady=(14, 0), sticky="w")
        ui.label(clip_inputs, "Start", 13, color=C.text_secondary).pack(side="left", padx=(0, 8))
        self.clip_start_entry = ui.entry(clip_inputs, "00:00:00", height=36, width=110, state="disabled")
        self.clip_start_entry.pack(side="left")
        ui.label(clip_inputs, "End", 13, color=C.text_secondary).pack(side="left", padx=(16, 8))
        self.clip_end_entry = ui.entry(clip_inputs, "00:01:30", height=36, width=110, state="disabled")
        self.clip_end_entry.pack(side="left")
        ui.label(clip_inputs, "HH:MM:SS", 12, color=C.text_tertiary).pack(side="left", padx=(12, 0))
        self._on_clip_toggle()

        # Destination folder
        _cap("Save to", 2, 0, pady=(14, 0))
        default_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.exists(default_dir):
            default_dir = os.getcwd()
        dir_row = ctk.CTkFrame(opts, fg_color="transparent")
        dir_row.grid(row=2, column=1, columnspan=4, pady=(14, 0), sticky="ew")
        dir_row.grid_columnconfigure(0, weight=1)
        self.single_dir_entry = ui.entry(dir_row, height=40)
        self.single_dir_entry.insert(0, default_dir)
        self.single_dir_entry.grid(row=0, column=0, sticky="ew")
        ui.outlined_button(dir_row, "Browse", "folder_open",
                           lambda: self._browse_directory(self.single_dir_entry),
                           width=110).grid(row=0, column=1, padx=(10, 0))

        # Action buttons
        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.pack(fill="x", pady=(22, 0))

        self.single_start_btn = ui.filled_button(actions, "Download", "download",
                                                 self._start_single_download, width=150)
        self.single_start_btn.pack(side="left")

        self.single_pause_btn = ui.tonal_button(actions, "Pause", "pause",
                                                self._toggle_single_pause, width=120, state="disabled")
        self.single_pause_btn.pack(side="left", padx=(10, 0))

        self.single_cancel_btn = ui.outlined_button(actions, "Cancel", "close", self._cancel_single_download,
                                                    danger=True, width=120, state="disabled")
        self.single_cancel_btn.pack(side="left", padx=(10, 0))

        self.single_folder_btn = ui.text_button(
            actions, "Open folder", "folder_open",
            lambda: history_manager.open_file_folder(self.single_downloaded_path or self.single_dir_entry.get()),
            height=40
        )
        self.single_folder_btn.pack(side="right")

        # Progress card
        dash = ui.card(page, radius=12)
        dash.pack(fill="x", pady=(20, 0))
        dash.grid_columnconfigure((0, 1, 2), weight=1)

        ui.label(dash, "Progress", 14, medium=True).grid(row=0, column=0, padx=16, pady=(14, 0), sticky="w")
        self.single_lbl_pct = ui.label(dash, "0.0%", 14, medium=True, color=C.primary)
        self.single_lbl_pct.grid(row=0, column=2, padx=16, pady=(14, 0), sticky="e")

        self.single_progress_bar = ui.progress_bar(dash, height=6)
        self.single_progress_bar.grid(row=1, column=0, columnspan=3, padx=16, pady=(10, 10), sticky="ew")

        self.single_lbl_size = self._create_metric_box(dash, "Downloaded", "0.0 / 0.0 MB", row=2, col=0)
        self.single_lbl_speed = self._create_metric_box(dash, "Speed", "0.00 MB/s", row=2, col=1)
        self.single_lbl_eta = self._create_metric_box(dash, "Time left", "--:--", row=2, col=2)

    def _create_metric_box(self, parent, label_text, default_val, row, col):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=row, column=col, padx=16, pady=(0, 14), sticky="w")
        ui.label(box, label_text, 12, color=C.text_tertiary).pack(anchor="w")
        val_lbl = ui.label(box, default_val, 15, medium=True)
        val_lbl.pack(anchor="w")
        return val_lbl

    # -------------------------------------------------------------
    # Page 2: Task Queue
    # -------------------------------------------------------------
    def _build_queue_tab(self):
        page = self.tab_queue
        self._page_header(page, "Queue", "Add several links and download them one after another")

        add_card = ui.card(page, radius=12)
        add_card.pack(fill="x")
        add_card.grid_columnconfigure(0, weight=1)

        self.q_url_entry = ui.entry(add_card, "Paste a video link to add to the queue", height=44)
        self.q_url_entry.grid(row=0, column=0, padx=(16, 0), pady=(16, 0), sticky="ew")
        self.q_url_entry.bind("<KeyRelease>", self._on_q_url_change)
        self.q_url_entry.bind("<Return>", lambda e: self._add_item_to_queue())

        ui.tonal_button(add_card, "Paste", "content_paste", self._paste_q_url, height=44,
                        width=110).grid(row=0, column=1, padx=(10, 16), pady=(16, 0))

        opts_row = ctk.CTkFrame(add_card, fg_color="transparent")
        opts_row.grid(row=1, column=0, columnspan=2, padx=16, pady=(12, 16), sticky="ew")
        opts_row.grid_columnconfigure(1, weight=1)

        self.q_input_badge = ui.chip(opts_row, "No link", 'neutral', 'link', height=28)
        self.q_input_badge.grid(row=0, column=0, sticky="w")

        self.q_format_seg = ui.segmented(opts_row, ["MP4", "MP3"], height=36)
        self.q_format_seg.set("MP4")
        self.q_format_seg.grid(row=0, column=2, padx=(0, 10))

        self.q_res_menu = ui.option_menu(opts_row, RESOLUTION_OPTIONS, height=36, width=160)
        self.q_res_menu.set("Best (Original)")
        self.q_res_menu.grid(row=0, column=3, padx=(0, 10))

        ui.filled_button(opts_row, "Add", "playlist_add", self._add_item_to_queue,
                         height=36, width=96).grid(row=0, column=4)

        # Global queue controls
        ctrl = ctk.CTkFrame(page, fg_color="transparent")
        ctrl.pack(fill="x", pady=(16, 8))

        self.q_start_all_btn = ui.filled_button(ctrl, "Start all", "play_arrow", self._start_queue_all,
                                                width=130)
        self.q_start_all_btn.pack(side="left")
        self.q_pause_all_btn = ui.tonal_button(ctrl, "Pause all", "pause", self._pause_queue_all, width=130)
        self.q_pause_all_btn.pack(side="left", padx=(10, 0))
        self.q_stop_all_btn = ui.outlined_button(ctrl, "Stop all", "stop", self._stop_queue_all,
                                                 danger=True, width=120)
        self.q_stop_all_btn.pack(side="left", padx=(10, 0))

        ui.text_button(ctrl, "Open folder", "folder_open",
                       lambda: history_manager.open_file_folder(self.single_dir_entry.get()),
                       height=40).pack(side="right")
        ui.text_button(ctrl, "Clear finished", "cleaning_services", self._clear_completed_queue,
                       height=40).pack(side="right", padx=(0, 4))

        # Scrollable task list
        self.queue_scroll = ui.scroll_frame(page)
        self.queue_scroll.pack(fill="both", expand=True, pady=(4, 8))
        self.queue_scroll.grid_columnconfigure(0, weight=1)

        self.q_empty_label = self._empty_state(
            self.queue_scroll, 'queue', "Your queue is empty",
            "Paste links above and select Add to download several videos in a row."
        )
        self.q_empty_label.pack(pady=60)

    def _empty_state(self, parent, icon_name, title, body):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(box, text="", image=ui.icon(icon_name, C.text_tertiary, 56)).pack()
        ui.label(box, title, 16, medium=True).pack(pady=(10, 2))
        ui.label(box, body, 13, color=C.text_secondary).pack()
        return box

    # -------------------------------------------------------------
    # Page 3: History
    # -------------------------------------------------------------
    def _build_history_tab(self):
        page = self.tab_history
        hdr, self.history_count_lbl = self._page_header(page, "History", "0 completed downloads")

        btns = ctk.CTkFrame(hdr, fg_color="transparent")
        btns.grid(row=0, column=1, rowspan=2, sticky="e")
        ui.outlined_button(btns, "Refresh", "refresh", self._load_history_list, width=110).pack(side="left")
        ui.text_button(btns, "Clear all", "delete", self._clear_all_history, danger=True,
                       height=40).pack(side="left", padx=(8, 0))

        self.history_scroll = ui.scroll_frame(page)
        self.history_scroll.pack(fill="both", expand=True, pady=(0, 8))
        self.history_scroll.grid_columnconfigure(0, weight=1)

        self._load_history_list()

    def _load_history_list(self):
        for child in self.history_scroll.winfo_children():
            child.destroy()

        records = history_manager.get_history()
        n = len(records)
        self.history_count_lbl.configure(text=f"{n} completed download{'s' if n != 1 else ''}")

        if not records:
            self._empty_state(self.history_scroll, 'history', "No downloads yet",
                              "Finished downloads will appear here.").pack(pady=60)
            return

        for idx, rec in enumerate(records):
            if idx > 0:
                ctk.CTkFrame(self.history_scroll, height=1, fg_color=C.outline_variant).pack(fill="x", padx=8)

            row = ctk.CTkFrame(self.history_scroll, fg_color="transparent")
            row.pack(fill="x", padx=(0, 8), pady=2)
            row.grid_columnconfigure(1, weight=1)

            title_text = rec.get('title', 'Unknown Title')
            timestamp = rec.get('timestamp', '')
            platform = rec.get('platform', 'Media')
            fmt = rec.get('format', 'MP4')
            size_mb = rec.get('file_size_mb', 0) or 0
            filepath = rec.get('filepath') or rec.get('file_path') or ''
            rec_id = rec.get('id')
            is_audio = 'mp3' in str(fmt).lower()

            ctk.CTkLabel(
                row, text="", width=40, height=40, corner_radius=20, fg_color=C.surface_low,
                image=ui.icon('music_note' if is_audio else 'movie', C.primary, 20)
            ).grid(row=0, column=0, rowspan=2, padx=(8, 14), pady=10)

            ui.label(row, _fit(title_text, self._measure_font, HISTORY_TITLE_PX), 14, medium=True,
                     anchor="w").grid(
                row=0, column=1, sticky="w", pady=(10, 0))
            meta = f"{fmt}  ·  {size_mb:.1f} MB  ·  {platform}  ·  {timestamp}"
            ui.label(row, meta, 12, color=C.text_secondary, anchor="w").grid(
                row=1, column=1, sticky="w", pady=(0, 10))

            acts = ctk.CTkFrame(row, fg_color="transparent")
            acts.grid(row=0, column=2, rowspan=2, padx=(8, 0))
            ui.icon_button(acts, 'folder_open', lambda p=filepath: history_manager.open_file_folder(p),
                           tooltip="Show in folder").pack(side="left")
            ui.icon_button(acts, 'play_arrow', lambda p=filepath: history_manager.play_file(p),
                           tooltip="Play").pack(side="left")
            ui.icon_button(acts, 'delete', lambda i=rec_id: self._delete_history_item(i),
                           tooltip="Remove from history").pack(side="left")

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
        self._set_platform_chip(self.q_input_badge, self.q_url_entry.get().strip())

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

        download_type = "audio" if "MP3" in self.q_format_seg.get() else "video"
        resolution = RES_MAP.get(self.q_res_menu.get(), "best")
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
        self._update_nav_counts()
        if not self.queue_items:
            self.q_empty_label.pack(pady=60)
            return
        else:
            self.q_empty_label.pack_forget()

        # Ensure every item has its card frame
        for it in self.queue_items:
            if it.card_frame is None or not it.card_frame.winfo_exists():
                self._create_queue_card_widget(it)

    def _set_q_status(self, it: QueueItem, text, kind, icon_name):
        if it.lbl_status and it.lbl_status.winfo_exists():
            ui.set_chip(it.lbl_status, text, kind, icon_name)

    def _create_queue_card_widget(self, it: QueueItem):
        card = ui.card(self.queue_scroll, radius=12)
        card.pack(fill="x", padx=(0, 8), pady=4)
        card.grid_columnconfigure(1, weight=1)
        it.card_frame = card

        ctk.CTkLabel(
            card, text="", width=40, height=40, corner_radius=20, fg_color=C.surface_low,
            image=ui.icon('music_note' if it.download_type == "audio" else 'movie', C.primary, 20)
        ).grid(row=0, column=0, rowspan=3, padx=(14, 12), pady=12, sticky="n")

        it.lbl_title = ui.label(card, _fit(it.title, self._measure_font, QUEUE_TITLE_PX), 14, medium=True, anchor="w")
        it.lbl_title.grid(row=0, column=1, sticky="ew", pady=(12, 0))

        meta = ctk.CTkFrame(card, fg_color="transparent")
        meta.grid(row=1, column=1, sticky="w")
        it.lbl_badge = ui.label(meta, PLATFORM_LABELS.get(it.platform, it.platform), 12, medium=True,
                                color=ui.PLATFORM_COLORS.get(it.platform, C.text_secondary))
        it.lbl_badge.pack(side="left")
        fmt_desc = "MP3 · 320 kbps" if it.download_type == "audio" else f"MP4 · {_res_label(it.resolution)}"
        it.lbl_info = ui.label(meta, f"  ·  {fmt_desc}", 12, color=C.text_secondary)
        it.lbl_info.pack(side="left")

        it.progress_bar = ui.progress_bar(card, height=4)
        it.progress_bar.grid(row=2, column=1, sticky="ew", pady=(8, 14))

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.grid(row=0, column=2, rowspan=3, padx=(12, 10), pady=8, sticky="e")

        it.lbl_status = ui.chip(right, "Waiting", 'neutral', 'schedule')
        it.lbl_status.pack(anchor="e", pady=(2, 4), padx=(0, 4))

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.pack(anchor="e")
        it.btn_start = ui.icon_button(btns, 'play_arrow', lambda i=it: self._start_individual_queue_item(i),
                                      color=C.primary, tooltip="Start")
        it.btn_start.pack(side="left")
        it.btn_pause = ui.icon_button(btns, 'pause', lambda i=it: self._toggle_queue_item_pause(i),
                                      tooltip="Pause / resume")
        it.btn_pause.pack(side="left")
        it.btn_cancel = ui.icon_button(btns, 'stop', lambda i=it: self._cancel_queue_item(i),
                                       color=C.error, hover=C.error_hover_bg, tooltip="Stop")
        it.btn_cancel.pack(side="left")
        it.btn_remove = ui.icon_button(btns, 'close', lambda i=it: self._remove_queue_item(i),
                                       tooltip="Remove")
        it.btn_remove.pack(side="left")
        ui.set_enabled(it.btn_pause, False)
        ui.set_enabled(it.btn_cancel, False)

    def _update_queue_card_info(self, it: QueueItem):
        if it.lbl_title and it.lbl_title.winfo_exists():
            it.lbl_title.configure(text=_fit(it.title, self._measure_font, QUEUE_TITLE_PX))
        if it.lbl_badge and it.lbl_badge.winfo_exists():
            it.lbl_badge.configure(text=PLATFORM_LABELS.get(it.platform, it.platform),
                                   text_color=ui.PLATFORM_COLORS.get(it.platform, C.text_secondary))

    def _remove_queue_item(self, it: QueueItem):
        if it.worker and it.worker.is_alive():
            it.worker.cancel()
        if it.card_frame and it.card_frame.winfo_exists():
            it.card_frame.destroy()
        if it in self.queue_items:
            self.queue_items.remove(it)
        self._update_nav_counts()
        if not self.queue_items:
            self.q_empty_label.pack(pady=60)

    def _clear_completed_queue(self):
        to_remove = [it for it in self.queue_items if it.status in ("Completed", "Cancelled", "Error")]
        for it in to_remove:
            self._remove_queue_item(it)

    # Individual Task Execution
    def _start_individual_queue_item(self, it: QueueItem):
        if it.worker and it.worker.is_alive():
            return

        it.status = "Downloading"
        ui.set_enabled(it.btn_start, False)
        ui.set_button_icon(it.btn_pause, 'pause')
        ui.set_enabled(it.btn_pause, True)
        ui.set_enabled(it.btn_cancel, True)
        ui.set_enabled(it.btn_remove, False)
        it.progress_bar.configure(progress_color=C.primary)
        self._set_q_status(it, "Downloading", 'info', 'downloading')

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
            ui.set_button_icon(it.btn_pause, 'pause')
            self._set_q_status(it, "Downloading", 'info', 'downloading')
        else:
            it.worker.pause()
            it.status = "Paused"
            ui.set_button_icon(it.btn_pause, 'play_arrow')
            self._set_q_status(it, "Paused", 'warning', 'pause')

    def _cancel_queue_item(self, it: QueueItem):
        if it.worker and it.worker.is_alive():
            it.worker.cancel()
            it.status = "Cancelled"
            self._set_q_status(it, "Cancelled", 'neutral', 'close')

    # Callbacks for individual queue items
    def _cb_q_start(self, it: QueueItem, title, uploader, dur, plat):
        it.title = title
        it.uploader = uploader
        self.after(0, lambda: self._ui_q_start(it))

    def _ui_q_start(self, it: QueueItem):
        if it.lbl_title and it.lbl_title.winfo_exists():
            it.lbl_title.configure(text=_fit(it.title, self._measure_font, QUEUE_TITLE_PX))

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
            fmt_desc = "MP3 · 320 kbps" if it.download_type == "audio" else f"MP4 · {_res_label(it.resolution)}"
            info_txt = (f"  ·  {fmt_desc}  ·  {it.downloaded_mb:.1f} / {it.total_mb:.1f} MB ({it.pct:.1f}%)"
                        f"  ·  {it.speed}  ·  {it.eta} left")
            it.lbl_info.configure(text=info_txt)

    def _cb_q_status(self, it: QueueItem, msg):
        self.after(0, lambda: self.status_bar.configure(text=f"Queue: {msg}"))

    def _cb_q_finish(self, it: QueueItem, success, message, filepath):
        self.after(0, lambda: self._ui_q_finish(it, success, message, filepath))

    def _ui_q_finish(self, it: QueueItem, success, message, filepath):
        if not (it.card_frame and it.card_frame.winfo_exists()):
            if self.is_queue_running:
                self._run_next_queue_item()
            return

        ui.set_button_icon(it.btn_start, 'replay')
        if it.btn_start._tooltip:
            it.btn_start._tooltip.text = "Restart"
        ui.set_enabled(it.btn_start, True)
        ui.set_button_icon(it.btn_pause, 'pause')
        ui.set_enabled(it.btn_pause, False)
        ui.set_enabled(it.btn_cancel, False)
        ui.set_enabled(it.btn_remove, True)
        it.filepath = filepath

        if success and filepath and os.path.exists(filepath):
            it.status = "Completed"
            it.progress_bar.set(1.0)
            res_match = re.search(r"\[(\d+x\d+|\d+p)\]", message or "")
            res_txt = f" · {res_match.group(1)}" if res_match else ""
            if "⚠" in (message or ""):
                it.progress_bar.configure(progress_color=C.warning)
                self._set_q_status(it, f"Low quality{res_txt}", 'warning', 'warning')
            else:
                it.progress_bar.configure(progress_color=C.success)
                self._set_q_status(it, f"Completed{res_txt}", 'success', 'check_circle')
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
                self._set_q_status(it, "Cancelled", 'neutral', 'close')
            else:
                it.status = "Error"
                it.error_msg = message
                it.progress_bar.configure(progress_color=C.error)
                self._set_q_status(it, "Failed", 'error', 'error')
                if it.btn_start._tooltip:
                    it.btn_start._tooltip.text = "Retry"
                self.status_bar.configure(text=f"Queue: {_shorten(message.replace(chr(10), ' '), 160)}")

        # Check if queue batch is running
        if self.is_queue_running:
            self._run_next_queue_item()

    # Batch Queue Execution
    def _start_queue_all(self):
        if not self.queue_items:
            messagebox.showinfo("Queue Empty", "Please add one or more download links to the queue first.")
            return

        self.is_queue_running = True
        self._batch_attempted = set()
        ui.set_enabled(self.q_start_all_btn, False)
        self.current_queue_index = -1
        self._run_next_queue_item()

    def _run_next_queue_item(self):
        if not self.is_queue_running:
            return

        # Next waiting / unfinished item, each attempted at most once per batch run
        # (otherwise a permanently failing or user-stopped item would loop forever).
        attempted = getattr(self, "_batch_attempted", set())
        next_item = None
        for it in self.queue_items:
            if it.status in ("Waiting", "Cancelled", "Error") and it.id not in attempted:
                next_item = it
                break

        if next_item:
            attempted.add(next_item.id)
            self._start_individual_queue_item(next_item)
        else:
            # All done
            self.is_queue_running = False
            ui.set_enabled(self.q_start_all_btn, True)
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
        ui.set_enabled(self.q_start_all_btn, True)
        for it in self.queue_items:
            if it.status == "Downloading" or (it.worker and it.worker.is_alive()):
                self._cancel_queue_item(it)

    # -------------------------------------------------------------
    # Single Download Handlers & Live Preview
    # -------------------------------------------------------------
    def _on_single_url_change(self, event=None):
        url = self.single_url_entry.get().strip()
        self._set_platform_chip(self.single_platform_badge, url)

        if url.startswith("http") and url != self.last_preview_url:
            self.after(600, self._fetch_thumbnail_preview)

    def _fetch_thumbnail_preview(self):
        url = self.single_url_entry.get().strip()
        if not url.startswith("http") or url == self.last_preview_url:
            return

        self.last_preview_url = url
        ui.set_chip(self.preview_status_lbl, "Fetching details…", 'info', 'downloading')

        def _worker():
            info = downloader_core.fetch_preview_info(url)
            self.after(0, lambda: self._apply_preview_info(info))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_preview_info(self, info):
        if not info:
            ui.set_chip(self.preview_status_lbl, "Couldn't load details — you can still download",
                        'neutral', 'info')
            return

        self.preview_title.configure(text=_shorten(info.get('title', 'Unknown'), 140))
        self.preview_meta.configure(
            text=f"{info.get('uploader', 'Unknown')}  ·  {info.get('duration_str', 'N/A')}  ·  "
                 f"{PLATFORM_LABELS.get(info.get('platform', ''), info.get('platform', ''))}"
        )
        ui.set_chip(self.preview_status_lbl, "Ready to download", 'success', 'check_circle')

        pil_img = info.get('thumbnail_image')
        if pil_img:
            try:
                self.thumb_label.configure(image=ui.rounded_image(pil_img, (160, 90), radius=8),
                                           fg_color="transparent")
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
        enabled = self.clip_enabled_var.get()
        for e in (self.clip_start_entry, self.clip_end_entry):
            if enabled:
                e.configure(state="normal", fg_color=C.surface_low, border_color=C.surface_low,
                            text_color=C.text)
            else:
                e.configure(state="disabled", fg_color=C.surface, border_color=C.outline_variant,
                            text_color=C.text_disabled)

    def _browse_directory(self, entry_widget):
        folder = filedialog.askdirectory(initialdir=entry_widget.get())
        if folder:
            entry_widget.delete(0, 'end')
            entry_widget.insert(0, folder)

    # Single Download Execution
    def _start_single_download(self):
        if self.single_worker and self.single_worker.is_alive():
            return
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

        download_type = "audio" if "MP3" in self.single_format_seg.get() else "video"
        resolution = RES_MAP.get(self.single_res_menu.get(), "best")

        clip_start, clip_end = None, None
        if self.clip_enabled_var.get():
            clip_start = self.clip_start_entry.get().strip() or None
            clip_end = self.clip_end_entry.get().strip() or None

        self.single_progress_bar.configure(progress_color=C.primary)
        self.single_progress_bar.set(0.0)
        self.single_lbl_pct.configure(text="0.0%")
        self.single_lbl_size.configure(text="0.0 / 0.0 MB")
        self.single_lbl_speed.configure(text="Calculating...")
        self.single_lbl_eta.configure(text="--:--")
        self.single_downloaded_path = None

        ui.set_enabled(self.single_start_btn, False)
        self.single_pause_btn.configure(text="Pause")
        ui.set_button_icon(self.single_pause_btn, 'pause')
        ui.set_enabled(self.single_pause_btn, True)
        ui.set_enabled(self.single_cancel_btn, True)
        ui.set_chip(self.preview_status_lbl, "Downloading", 'info', 'downloading')
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
            self.single_pause_btn.configure(text="Pause")
            ui.set_button_icon(self.single_pause_btn, 'pause')
            ui.set_chip(self.preview_status_lbl, "Downloading", 'info', 'downloading')
            self.status_bar.configure(text="Resumed download.")
        else:
            self.single_worker.pause()
            self.single_pause_btn.configure(text="Resume")
            ui.set_button_icon(self.single_pause_btn, 'play_arrow')
            ui.set_chip(self.preview_status_lbl, "Paused", 'warning', 'pause')
            self.status_bar.configure(text="Download paused. Select Resume to continue.")

    def _cancel_single_download(self):
        if self.single_worker and self.single_worker.is_alive():
            self.single_worker.cancel()
            self.status_bar.configure(text="Cancelling download...")

    def _cb_single_start(self, title, uploader, dur_str, platform, download_type):
        self.after(0, lambda: self._ui_single_start(title, uploader, dur_str, platform, download_type))

    def _ui_single_start(self, title, uploader, dur_str, platform, download_type):
        self.preview_title.configure(text=_shorten(title, 140))
        self.preview_meta.configure(
            text=f"{uploader}  ·  {dur_str}  ·  {PLATFORM_LABELS.get(platform, platform)}")

    def _cb_single_progress(self, pct, downloaded_mb, total_mb, speed_str, eta_str, filename):
        self.after(0, lambda: self._ui_single_progress(pct, downloaded_mb, total_mb, speed_str, eta_str))

    def _ui_single_progress(self, pct, downloaded_mb, total_mb, speed_str, eta_str):
        self.single_progress_bar.set(pct / 100.0)
        self.single_lbl_pct.configure(text=f"{pct:.1f}%")
        self.single_lbl_size.configure(text=f"{downloaded_mb:.1f} / {total_mb:.1f} MB")
        self.single_lbl_speed.configure(text=speed_str)
        self.single_lbl_eta.configure(text=eta_str)

    def _cb_single_status(self, status_text):
        self.after(0, lambda: self.status_bar.configure(text=status_text))

    def _cb_single_finish(self, success, message, filepath, url, download_type):
        self.after(0, lambda: self._ui_single_finish(success, message, filepath, url, download_type))

    def _ui_single_finish(self, success, message, filepath, url, download_type):
        ui.set_enabled(self.single_start_btn, True)
        self.single_pause_btn.configure(text="Pause")
        ui.set_button_icon(self.single_pause_btn, 'pause')
        ui.set_enabled(self.single_pause_btn, False)
        ui.set_enabled(self.single_cancel_btn, False)
        self.single_downloaded_path = filepath
        self.status_bar.configure(text=message.split("\n")[0])

        if success and filepath and os.path.exists(filepath):
            self.single_progress_bar.set(1.0)
            self.single_lbl_pct.configure(text="100.0%")
            low_quality = "⚠" in message
            self.single_progress_bar.configure(progress_color=C.warning if low_quality else C.success)
            res_match = re.search(r"\[(\d+x\d+|\d+p)\]", message)
            res_txt = f" · {res_match.group(1)}" if res_match else ""
            if low_quality:
                ui.set_chip(self.preview_status_lbl, f"Downloaded in low quality{res_txt}", 'warning', 'warning')
            else:
                ui.set_chip(self.preview_status_lbl, f"Downloaded{res_txt}", 'success', 'check_circle')

            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            self.single_lbl_size.configure(text=f"{file_size_mb:.1f} MB")
            self.single_lbl_speed.configure(text="—")
            self.single_lbl_eta.configure(text="Done")
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

            if low_quality:
                messagebox.showwarning("Download Complete (Low Quality)", f"{message}\n\nSaved to:\n{filepath}")
            else:
                messagebox.showinfo("Download Complete", f"{message}\n\nSaved to:\n{filepath}")
        else:
            self.single_lbl_speed.configure(text="—")
            self.single_lbl_eta.configure(text="--:--")
            if "cancel" in message.lower():
                ui.set_chip(self.preview_status_lbl, "Cancelled", 'neutral', 'close')
                self.status_bar.configure(text="Download was cancelled.")
            else:
                self.single_progress_bar.configure(progress_color=C.error)
                ui.set_chip(self.preview_status_lbl, "Failed", 'error', 'error')
                messagebox.showerror("Error", message)

    # -------------------------------------------------------------
    # System Tray Integration
    # -------------------------------------------------------------
    def _init_tray(self):
        try:
            image = Image.open(self.icon_png)
        except Exception:
            image = Image.new('RGB', (64, 64), color=(11, 87, 208))

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
