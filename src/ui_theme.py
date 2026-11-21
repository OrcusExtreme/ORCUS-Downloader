"""
ORCUS Downloader - Workspace-style (Material 3) Design System
(C) Copyright 2026. OrcusExtreme

Design tokens (light/dark color pairs), Roboto typography, Material Icons
rendered to CTkImage, widget factory helpers, tooltips and persisted settings.

Every color is a (light, dark) tuple so CustomTkinter re-themes the whole UI
automatically when ctk.set_appearance_mode() is toggled.
"""

import os
import json
import tkinter as tk
from types import SimpleNamespace

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

import path_utils

# -----------------------------------------------------------------------------
# Color tokens: (light, dark)
# -----------------------------------------------------------------------------
C = SimpleNamespace(
    bg=("#F8FAFD", "#131314"),
    surface=("#FFFFFF", "#1E1F20"),
    surface_low=("#F0F4F9", "#282A2C"),
    surface_high=("#E9EEF6", "#333537"),
    hover=("#E9ECF1", "#37393B"),
    hover_on_surface=("#F1F3F4", "#2A2B2D"),

    text=("#1F1F1F", "#E3E3E3"),
    text_secondary=("#444746", "#C4C7C5"),
    text_tertiary=("#747775", "#8E918F"),
    text_disabled=("#A8ABA9", "#5F6368"),

    outline=("#747775", "#8E918F"),
    outline_variant=("#C4C7C5", "#444746"),

    primary=("#0B57D0", "#A8C7FA"),
    primary_hover=("#1E64D4", "#9BBBEF"),
    on_primary=("#FFFFFF", "#062E6F"),
    primary_container=("#D3E3FD", "#0842A0"),
    primary_container_hover=("#C2D3EF", "#184FA7"),
    on_primary_container=("#041E49", "#D3E3FD"),

    secondary_container=("#C2E7FF", "#004A77"),
    secondary_container_hover=("#B0D6EF", "#0F5683"),
    on_secondary_container=("#001D35", "#C2E7FF"),

    error=("#B3261E", "#F2B8B5"),
    error_hover_bg=("#FBEDEC", "#352829"),
    error_container=("#F9DEDC", "#8C1D18"),
    on_error_container=("#410E0B", "#F9DEDC"),

    success=("#146C2E", "#6DD58C"),
    success_container=("#C4EED0", "#0F5223"),
    on_success_container=("#072711", "#C4EED0"),

    warning=("#8C5000", "#FFB95C"),
    warning_container=("#FFDF99", "#5A4300"),
    on_warning_container=("#261A00", "#FFDF99"),

    disabled_bg=("#E3E3E3", "#2E2F31"),
)

PLATFORM_COLORS = {
    'CHZZK': ("#00A86B", "#3DDC97"),
    'SOOP': ("#1A73E8", "#8AB4F8"),
    'YouTube': ("#D93025", "#F28B82"),
    'X (Twitter)': ("#1F1F1F", "#E3E3E3"),
    'Instagram': ("#C13584", "#F48FB1"),
    'TikTok': ("#00838F", "#4DD0E1"),
    'NaverTV': ("#03A94D", "#5BD68D"),
    'Twitch': ("#7B3FE4", "#C5A3FF"),
}

# Status chip styles: kind -> (bg, fg)
STATUS_STYLES = {
    'neutral': (C.surface_high, C.text_secondary),
    'info': (C.primary_container, C.on_primary_container),
    'success': (C.success_container, C.on_success_container),
    'warning': (C.warning_container, C.on_warning_container),
    'error': (C.error_container, C.on_error_container),
}

# -----------------------------------------------------------------------------
# Typography (Roboto is bundled & registered by CustomTkinter on Windows)
# -----------------------------------------------------------------------------
def font(size: int = 14, medium: bool = False) -> ctk.CTkFont:
    return ctk.CTkFont(family="Roboto Medium" if medium else "Roboto", size=size)


# -----------------------------------------------------------------------------
# Material Icons (Apache 2.0, google/material-design-icons, Outlined style)
# -----------------------------------------------------------------------------
ICON_CODEPOINTS = {
    'download': 0xF090, 'downloading': 0xF001, 'content_paste': 0xF098,
    'folder_open': 0xE2C8, 'play_arrow': 0xE037, 'pause': 0xE034,
    'stop': 0xE047, 'close': 0xE5CD, 'delete': 0xE872, 'refresh': 0xE5D5,
    'add': 0xE145, 'dark_mode': 0xE51C, 'light_mode': 0xE518,
    'history': 0xE889, 'queue': 0xE03C, 'playlist_add': 0xE03B,
    'link': 0xE157, 'movie': 0xE02C, 'music_note': 0xE405,
    'content_cut': 0xF08B, 'check_circle': 0xE86C, 'warning': 0xE002,
    'info': 0xE88E, 'minimize': 0xE931, 'replay': 0xE042,
    'cleaning_services': 0xF0FF, 'error': 0xE000, 'schedule': 0xE8B5,
    'video_library': 0xE04A, 'smart_display': 0xF06A, 'open_in_new': 0xE89E,
    'picture_in_picture_alt': 0xE911, 'task_alt': 0xE2E6,
}

_ICON_FONT_FILE = os.path.join("assets", "fonts", "MaterialIconsOutlined-Regular.otf")
_icon_font_cache = {}
_icon_cache = {}


def _icon_font(px: int):
    if px not in _icon_font_cache:
        path = path_utils.get_resource_path(_ICON_FONT_FILE)
        try:
            _icon_font_cache[px] = ImageFont.truetype(path, px)
        except Exception:
            _icon_font_cache[px] = None
    return _icon_font_cache[px]


def _render_icon(name: str, color: str, size: int) -> Image.Image:
    """Renders (and caches) the PIL bitmap for an icon in one color."""
    key = (name, color, size)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    px = size * 3  # supersample for crisp HiDPI rendering
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    f = _icon_font(px)
    cp = ICON_CODEPOINTS.get(name)
    if f is not None and cp is not None:
        ImageDraw.Draw(img).text((0, 0), chr(cp), font=f, fill=color, anchor="la")
    _icon_cache[key] = img
    return img


def icon(name: str, color=C.text_secondary, size: int = 20) -> ctk.CTkImage:
    """Returns a theme-aware CTkImage for a Material icon (color is a (light, dark) pair).

    Only the PIL bitmaps are cached. Each call returns a fresh CTkImage because a
    CTkImage keeps callbacks to every widget using it (CustomTkinter 5.2 never
    removes them on destroy), so sharing one would keep destroyed widgets alive."""
    return ctk.CTkImage(
        light_image=_render_icon(name, color[0], size),
        dark_image=_render_icon(name, color[1], size),
        size=(size, size),
    )


def rounded_image(pil_img: Image.Image, size, radius: int = 12) -> ctk.CTkImage:
    """Center-crops a PIL image to `size`, rounds its corners (alpha) and wraps it."""
    w, h = size
    scale = 2
    tw, th = w * scale, h * scale
    src = pil_img.convert("RGBA")
    sr = src.width / src.height
    tr = tw / th
    if sr > tr:
        nw = int(src.height * tr)
        left = (src.width - nw) // 2
        src = src.crop((left, 0, left + nw, src.height))
    else:
        nh = int(src.width / tr)
        top = (src.height - nh) // 2
        src = src.crop((0, top, src.width, top + nh))
    src = src.resize((tw, th), Image.LANCZOS)
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tw - 1, th - 1), radius=radius * scale, fill=255)
    src.putalpha(mask)
    return ctk.CTkImage(light_image=src, dark_image=src, size=size)


# -----------------------------------------------------------------------------
# Widget factories
# -----------------------------------------------------------------------------
def _btn(parent, text, icon_name, command, fg, hover, text_color, height,
         border=None, icon_color=None, width=0, font_size=14, **kw):
    state = kw.pop("state", "normal")
    b = ctk.CTkButton(
        parent, text=text, command=command,
        image=icon(icon_name, icon_color or text_color, 18) if icon_name else None,
        compound="left", width=width, height=height,
        corner_radius=height // 2,
        fg_color=fg, hover_color=hover, text_color=text_color,
        text_color_disabled=C.text_disabled,
        border_width=1 if border else 0, border_color=border if border else None,
        font=font(font_size, medium=True), **kw
    )
    b._icon_name = icon_name
    b._icon_color = icon_color or text_color
    b._icon_size = 18
    b._orig_fg = fg
    if state == "disabled":
        set_enabled(b, False)
    return b


def set_enabled(button, enabled: bool):
    """Enables/disables a factory button with Material disabled styling
    (neutral container + greyed label/icon)."""
    orig_fg = getattr(button, "_orig_fg", None)
    icon_name = getattr(button, "_icon_name", None)
    if enabled:
        kw = {"state": "normal"}
        if orig_fg is not None:
            kw["fg_color"] = orig_fg
        if icon_name:
            kw["image"] = icon(icon_name, button._icon_color, button._icon_size)
    else:
        kw = {"state": "disabled"}
        if orig_fg is not None and orig_fg != "transparent":
            kw["fg_color"] = C.disabled_bg
        if icon_name:
            kw["image"] = icon(icon_name, C.text_disabled, button._icon_size)
    button.configure(**kw)


def set_button_icon(button, icon_name, color=None):
    """Swaps a factory button's icon (and optionally its icon color)."""
    button._icon_name = icon_name
    if color is not None:
        button._icon_color = color
    if button.cget("state") == "disabled":
        button.configure(image=icon(icon_name, C.text_disabled, button._icon_size))
    else:
        button.configure(image=icon(icon_name, button._icon_color, button._icon_size))


def filled_button(parent, text, icon_name=None, command=None, height=40, **kw):
    return _btn(parent, text, icon_name, command, C.primary, C.primary_hover,
                C.on_primary, height, **kw)


def tonal_button(parent, text, icon_name=None, command=None, height=40, **kw):
    return _btn(parent, text, icon_name, command, C.primary_container,
                C.primary_container_hover, C.on_primary_container, height, **kw)


def outlined_button(parent, text, icon_name=None, command=None, height=40, danger=False, **kw):
    if danger:
        return _btn(parent, text, icon_name, command, "transparent", C.error_hover_bg,
                    C.error, height, border=C.outline_variant, **kw)
    return _btn(parent, text, icon_name, command, "transparent", C.hover_on_surface,
                C.primary, height, border=C.outline_variant, **kw)


def text_button(parent, text, icon_name=None, command=None, height=36, danger=False, **kw):
    color = C.error if danger else C.primary
    hover = C.error_hover_bg if danger else C.hover_on_surface
    return _btn(parent, text, icon_name, command, "transparent", hover, color, height, **kw)


def icon_button(parent, icon_name, command=None, size=36, color=C.text_secondary,
                hover=C.hover_on_surface, tooltip=None):
    b = ctk.CTkButton(
        parent, text="", image=icon(icon_name, color, 20), command=command,
        width=size, height=size, corner_radius=size // 2,
        fg_color="transparent", hover_color=hover, border_width=0,
    )
    b._icon_name = icon_name
    b._icon_color = color
    b._icon_size = 20
    b._orig_fg = "transparent"
    b._tooltip = Tooltip(b, tooltip) if tooltip else None
    return b


def entry(parent, placeholder="", height=44, **kw):
    return ctk.CTkEntry(
        parent, placeholder_text=placeholder, height=height,
        corner_radius=height // 2 if height >= 40 else 8,
        fg_color=C.surface_low, border_width=1, border_color=C.surface_low,
        text_color=C.text, placeholder_text_color=C.text_tertiary,
        font=font(14), **kw
    )


def option_menu(parent, values, height=40, width=170, **kw):
    return ctk.CTkOptionMenu(
        parent, values=values, height=height, width=width, corner_radius=8,
        fg_color=C.surface_low, button_color=C.surface_low,
        button_hover_color=C.surface_high,
        text_color=C.text, text_color_disabled=C.text_disabled,
        dropdown_fg_color=C.surface, dropdown_hover_color=C.surface_high,
        dropdown_text_color=C.text, font=font(14), dropdown_font=font(14),
        **kw
    )


def segmented(parent, values, command=None, height=40, **kw):
    return ctk.CTkSegmentedButton(
        parent, values=values, command=command, height=height, corner_radius=height // 2,
        fg_color=C.outline_variant, selected_color=C.secondary_container,
        selected_hover_color=C.secondary_container_hover,
        unselected_color=C.surface, unselected_hover_color=C.hover_on_surface,
        text_color=C.text, text_color_disabled=C.text_disabled,
        font=font(14, medium=True), border_width=1, **kw
    )


def checkbox(parent, text, variable=None, command=None, **kw):
    return ctk.CTkCheckBox(
        parent, text=text, variable=variable, command=command,
        checkbox_width=18, checkbox_height=18, corner_radius=3, border_width=2,
        fg_color=C.primary, hover_color=C.primary_hover, border_color=C.text_secondary,
        checkmark_color=C.on_primary, text_color=C.text, font=font(14), **kw
    )


def card(parent, outlined=True, color=C.surface, radius=16, **kw):
    return ctk.CTkFrame(
        parent, fg_color=color, corner_radius=radius,
        border_width=1 if outlined else 0, border_color=C.outline_variant, **kw
    )


def progress_bar(parent, height=6):
    pb = ctk.CTkProgressBar(parent, height=height, corner_radius=height // 2,
                            fg_color=C.surface_high, progress_color=C.primary)
    pb.set(0.0)
    return pb


def scroll_frame(parent, **kw):
    return ctk.CTkScrollableFrame(
        parent, fg_color="transparent", corner_radius=0,
        scrollbar_button_color=C.outline_variant,
        scrollbar_button_hover_color=C.outline, **kw
    )


def label(parent, text, size=14, medium=False, color=C.text, **kw):
    return ctk.CTkLabel(parent, text=text, font=font(size, medium), text_color=color, **kw)


def chip(parent, text, kind='neutral', icon_name=None, height=24):
    bg, fg = STATUS_STYLES[kind]
    return ctk.CTkLabel(
        parent, text=f" {text} " if not icon_name else f"  {text}  ",
        image=icon(icon_name, fg, 14) if icon_name else None, compound="left",
        height=height, corner_radius=8, fg_color=bg, text_color=fg,
        font=font(12, medium=True), padx=8,
    )


def set_chip(chip_label, text, kind='neutral', icon_name=None):
    bg, fg = STATUS_STYLES[kind]
    chip_label.configure(
        text=f"  {text}  " if icon_name else f" {text} ", fg_color=bg, text_color=fg,
        image=icon(icon_name, fg, 14) if icon_name else None,
    )


# -----------------------------------------------------------------------------
# Tooltip
# -----------------------------------------------------------------------------
class Tooltip:
    """Small Material-style tooltip (inverse surface) shown on hover."""

    def __init__(self, widget, text, delay_ms=500):
        self.widget = widget
        self.text = text
        self.delay = delay_ms
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _e=None):
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _pointer_inside(self) -> bool:
        w = self.widget
        px, py = w.winfo_pointerxy()
        x, y = w.winfo_rootx(), w.winfo_rooty()
        return x <= px < x + w.winfo_width() and y <= py < y + w.winfo_height()

    def _show(self):
        self._after = None
        try:
            if self._tip or not self.widget.winfo_exists() or not self._pointer_inside():
                return
        except Exception:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        bg, fg = ("#E3E3E3", "#1F1F1F") if dark else ("#303030", "#F2F2F2")
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        # Plain tk.Toplevel: CTkToplevel calls update() during construction, which can
        # process a <Leave> before self._tip is set and leave the tooltip stranded.
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except Exception:
            pass
        tk.Label(tip, text=self.text, bg=bg, fg=fg, font=("Roboto", 9), padx=8, pady=3).pack()
        tip.update_idletasks()
        tip.geometry(f"+{x - tip.winfo_reqwidth() // 2}+{y}")
        self._tip = tip

    def _hide(self, _e=None):
        self._cancel()
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None


# -----------------------------------------------------------------------------
# Persisted settings (theme)
# -----------------------------------------------------------------------------
def _settings_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "ORCUS Downloader")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "settings.json")


def load_settings() -> dict:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(**updates):
    data = load_settings()
    data.update(updates)
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def initial_appearance() -> str:
    """'light' or 'dark' — saved choice, else follow the Windows app theme."""
    mode = load_settings().get("appearance")
    if mode in ("light", "dark"):
        return mode
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
    except Exception:
        return "light"
