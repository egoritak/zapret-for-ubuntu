#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import select
import tempfile
import urllib.error
import urllib.request
import webbrowser
import getpass
import pwd
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tkinter import Canvas, IntVar, StringVar, Tk, Toplevel
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

try:
    from PIL import Image, ImageTk

    PIL_AVAILABLE = True
    if hasattr(Image, "Resampling"):
        RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    else:
        RESAMPLE_LANCZOS = Image.LANCZOS
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False
    RESAMPLE_LANCZOS = None

try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    GTK_TRAY_AVAILABLE = True
    try:
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
    except Exception:
        GdkPixbuf = None
except Exception:
    GLib = None
    GdkPixbuf = None
    Gtk = None
    GTK_TRAY_AVAILABLE = False


FALLBACK_VERSION_URL = (
    "https://raw.githubusercontent.com/Flowseal/"
    "zapret-discord-youtube/main/.service/version.txt"
)
FALLBACK_RELEASE_URL = "https://github.com/Flowseal/zapret-discord-youtube/releases/tag/"
FALLBACK_DOWNLOAD_URL = "https://github.com/Flowseal/zapret-discord-youtube/releases/latest"
LINUX_UPSTREAM_REPO = "https://github.com/bol-van/zapret.git"
LINUX_SYNC_INTERVAL_SEC = 12 * 3600
SOURCES_DIRNAME = "zapret-discord"
LEGACY_SOURCES_DIRNAMES = ("sources",)
LEGACY_SOURCE_DIRS = ("bin", "lists", "utils", ".service")
LEGACY_SOURCE_FILES = ("service.bat",)
LEGACY_STRATEGY_PATTERNS = ("general*.bat", "general*.sh")
AUTOSTART_SERVICE_NAME = "zapret-discord-autostart.service"
DESKTOP_ENTRY_FILENAME = "zapret-gui.desktop"
DESKTOP_ICON_BASENAME = "zapret-gui"
APP_WM_CLASS = "ZapretGui"
APP_ICONS_DIRNAME = "icons"
APP_ICON_FILENAME = "zapret.ico"


def natural_sort_key(value: str) -> list[object]:
    return [int(chunk) if chunk.isdigit() else chunk.lower() for chunk in re.split(r"(\d+)", value)]


@dataclass(frozen=True)
class Runtime:
    mode: str
    prefix: list[str]


@dataclass(frozen=True)
class Strategy:
    name: str
    path: Path
    kind: str


class OperationCancelled(Exception):
    pass


class ZapretGuiApp:
    def __init__(self, root: Tk, app_dir: Path) -> None:
        self.root = root
        self.app_dir = app_dir
        self.sources_root = self._prepare_sources_root()
        self.source_dir = self._prepare_source_dir()
        self.process: subprocess.Popen[str] | None = None
        self.current_runtime_mode: str | None = None
        self.is_busy = False
        self.busy_operation: str | None = None
        self.cancel_requested = False
        self.active_command_proc: subprocess.Popen[str] | None = None
        self.strategies_map: dict[str, Strategy] = {}
        self.release_page_url = FALLBACK_DOWNLOAD_URL
        self.update_archive_url = ""
        self.latest_version = ""
        self.update_available = False
        self.update_in_progress = False
        self.update_spinner_frames = ["↻", "↺", "⟳", "⟲"]
        self.update_spinner_index = 0
        self.update_animation_job: str | None = None
        self.last_selected_strategy: Strategy | None = None

        self.linux_root = self.app_dir / ".linux-backend"
        self.linux_repo_dir = self.linux_root / "zapret"
        self.linux_state_dir = self.linux_root / "state"
        self.linux_sync_stamp = self.linux_root / ".last_sync"
        self.linux_generated_config = self.linux_state_dir / "config.generated"
        self.selected_strategy_file = self.linux_state_dir / "selected_strategy.txt"
        self.autostart_config_file = self.linux_state_dir / "config.autostart.generated"
        self.autostart_strategy_file = self.linux_state_dir / "autostart_strategy.txt"
        self.autostart_local_unit = self.linux_state_dir / AUTOSTART_SERVICE_NAME
        self.autostart_system_unit = Path("/etc/systemd/system") / AUTOSTART_SERVICE_NAME
        self.logs_dir = self.linux_root / "logs"
        self.log_file = self.logs_dir / "launcher.log"

        self.log_window: Toplevel | None = None
        self.log_text: ScrolledText | None = None
        self.log_history: list[str] = []
        self.action_canvas: Canvas | None = None
        self.action_glow_outer_id: int | None = None
        self.action_glow_inner_id: int | None = None
        self.action_ring_id: int | None = None
        self.action_circle_id: int | None = None
        self.action_text_id: int | None = None
        self.action_hovered = False
        self.strategy_combo: ttk.Combobox | None = None
        self.autostart_check: ttk.Checkbutton | None = None
        self.update_button: ttk.Button | None = None
        self.autostart_busy = False
        self.autostart_update_in_progress = False
        self.autostart_enabled_cached = False
        self.autostart_strategy_cached = ""
        self.service_active_cached = False
        self.tray_available = False
        self.tray_icon: object | None = None
        self.tray_menu: object | None = None
        self.tray_toggle_item: object | None = None
        self.tray_thread: threading.Thread | None = None
        self.is_exiting = False
        self.icons_dir = self.app_dir / APP_ICONS_DIRNAME
        self.icon_source_path = self.resolve_icon_source_path()
        self.icon_png_path = self.linux_state_dir / "zapret-icon-256.png"
        self.tk_icon_photo = None

        self.strategy_var = StringVar()
        self.autostart_var = IntVar(value=0)
        self.autostart_info_var = StringVar(value="Autostart: off")
        self.status_var = StringVar(value="Idle")
        self.local_version = self.read_local_version()
        self.version_badge_var = StringVar(value=f"v{self.local_version} · checking...")
        self.last_selected_strategy_name = self.load_selected_strategy_name()

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.prepare_icon_assets()
        self._setup_window_class()

        self._setup_style()
        self._build_ui()
        self.refresh_strategies()
        self.ensure_user_lists()
        self.check_updates_async()
        self.ensure_managed_service_async()
        self.refresh_autostart_state_async()
        self.ensure_desktop_entry()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.setup_tray_icon()

    def _prepare_sources_root(self) -> Path:
        primary = self.app_dir / SOURCES_DIRNAME
        if not primary.exists():
            for legacy_name in LEGACY_SOURCES_DIRNAMES:
                legacy = self.app_dir / legacy_name
                if not legacy.exists():
                    continue
                try:
                    shutil.move(str(legacy), str(primary))
                    break
                except Exception:
                    # If move failed, keep fallback logic in _prepare_source_dir.
                    break
        primary.mkdir(parents=True, exist_ok=True)
        return primary

    def _path_has_source_markers(self, path: Path) -> bool:
        if not path.exists() or not path.is_dir():
            return False
        if (path / "bin").is_dir():
            return True
        if (path / "lists").is_dir():
            return True
        if (path / "service.bat").is_file():
            return True
        if any(path.glob("general*.bat")):
            return True
        if any(path.glob("general*.sh")):
            return True
        return False

    def _discover_source_dir_in(self, root: Path) -> Path:
        candidates = [entry for entry in root.iterdir() if entry.is_dir()]
        candidates = sorted(candidates, key=lambda item: natural_sort_key(item.name), reverse=True)
        for candidate in candidates:
            if self._path_has_source_markers(candidate):
                return candidate
        if self._path_has_source_markers(root):
            return root
        return root

    def _discover_source_dir(self) -> Path:
        return self._discover_source_dir_in(self.sources_root)

    def _migrate_legacy_sources(self) -> bool:
        moved_any = False
        self.sources_root.mkdir(parents=True, exist_ok=True)

        for name in LEGACY_SOURCE_DIRS:
            src = self.app_dir / name
            dst = self.sources_root / name
            if not src.exists() or dst.exists():
                continue
            shutil.move(str(src), str(dst))
            moved_any = True

        for name in LEGACY_SOURCE_FILES:
            src = self.app_dir / name
            dst = self.sources_root / name
            if not src.exists() or dst.exists():
                continue
            shutil.move(str(src), str(dst))
            moved_any = True

        for pattern in LEGACY_STRATEGY_PATTERNS:
            for src in self.app_dir.glob(pattern):
                if not src.is_file():
                    continue
                dst = self.sources_root / src.name
                if dst.exists():
                    continue
                shutil.move(str(src), str(dst))
                moved_any = True

        return moved_any

    def _prepare_source_dir(self) -> Path:
        self.sources_root.mkdir(parents=True, exist_ok=True)
        discovered = self._discover_source_dir()
        if discovered != self.sources_root or self._path_has_source_markers(discovered):
            return discovered

        for legacy_name in LEGACY_SOURCES_DIRNAMES:
            legacy_root = self.app_dir / legacy_name
            if legacy_root.exists() and legacy_root.is_dir():
                legacy_discovered = self._discover_source_dir_in(legacy_root)
                if legacy_discovered != legacy_root or self._path_has_source_markers(legacy_discovered):
                    return legacy_discovered

        if self._path_has_source_markers(self.app_dir):
            self._migrate_legacy_sources()
            return self._discover_source_dir()

        return self.sources_root

    def _setup_style(self) -> None:
        self.root.title("Zapret")
        self.root.geometry("430x760")
        self.root.minsize(390, 680)
        self._setup_window_icon()

        self.palette = {
            "bg": "#060912",
            "card": "#111827",
            "card_alt": "#151d2e",
            "text": "#f4f7ff",
            "muted": "#6d7b9a",
            "accent": "#ffb561",
            "accent_hover": "#ffc883",
            "accent_pressed": "#ef9f49",
            "danger": "#ff5f8a",
            "danger_hover": "#ff7aa2",
            "border": "#242d40",
        }
        self.root.configure(bg=self.palette["bg"])

        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("App.TFrame", background=self.palette["bg"])
        style.configure(
            "Card.TFrame",
            background=self.palette["card"],
            relief="flat",
            borderwidth=1,
        )
        style.configure(
            "Field.TLabel",
            background=self.palette["bg"],
            foreground=self.palette["muted"],
            font=("Ubuntu", 11),
        )
        style.configure(
            "InfoCaption.TLabel",
            background=self.palette["bg"],
            foreground=self.palette["muted"],
            font=("Ubuntu", 10),
        )
        style.configure(
            "InfoValue.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=("Ubuntu", 10, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background=self.palette["bg"],
            foreground="#8d9abc",
            font=("Ubuntu", 10),
        )

        style.configure(
            "Secondary.TButton",
            font=("Ubuntu", 10),
            foreground=self.palette["text"],
            background=self.palette["card_alt"],
            borderwidth=0,
            focusthickness=0,
            relief="flat",
            padding=(12, 8),
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("pressed", "#1c2537"),
                ("active", "#1a2233"),
            ],
            foreground=[("active", self.palette["accent_hover"])],
        )

        style.configure(
            "Ghost.TButton",
            font=("Ubuntu", 10),
            foreground=self.palette["muted"],
            background=self.palette["card"],
            borderwidth=0,
            focusthickness=0,
            relief="flat",
            padding=(8, 8),
        )
        style.map(
            "Ghost.TButton",
            foreground=[("active", self.palette["accent_hover"])],
            background=[("active", self.palette["card"])],
        )

        style.configure(
            "App.TCombobox",
            padding=10,
            arrowsize=16,
            fieldbackground=self.palette["card_alt"],
            background=self.palette["card_alt"],
            foreground=self.palette["text"],
            selectbackground="#23314c",
            selectforeground="#ffffff",
            bordercolor=self.palette["border"],
            lightcolor=self.palette["border"],
            darkcolor=self.palette["border"],
            relief="flat",
        )
        style.map(
            "App.TCombobox",
            fieldbackground=[("readonly", self.palette["card_alt"])],
            selectbackground=[("readonly", "#23314c")],
        )
        style.configure(
            "App.TCheckbutton",
            background=self.palette["bg"],
            foreground=self.palette["muted"],
            font=("Ubuntu", 10),
            relief="flat",
            padding=(4, 2),
        )
        style.map(
            "App.TCheckbutton",
            foreground=[
                ("selected", self.palette["text"]),
                ("active", self.palette["text"]),
                ("disabled", "#4f5c78"),
            ],
            background=[
                ("selected", self.palette["bg"]),
                ("active", self.palette["bg"]),
            ],
        )

    def _setup_window_class(self) -> None:
        try:
            self.root.wm_class(APP_WM_CLASS, APP_WM_CLASS)
            return
        except Exception:
            pass
        try:
            self.root.tk.call("wm", "class", self.root._w, APP_WM_CLASS)
        except Exception:
            pass

    def resolve_icon_source_path(self) -> Path:
        preferred = self.icons_dir / APP_ICON_FILENAME
        legacy = self.app_dir / APP_ICON_FILENAME
        try:
            self.icons_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return preferred if preferred.exists() else legacy

        if preferred.exists():
            return preferred

        if legacy.exists():
            try:
                shutil.move(str(legacy), str(preferred))
                return preferred
            except OSError:
                try:
                    shutil.copy2(legacy, preferred)
                    return preferred
                except OSError:
                    return legacy

        return preferred

    def _setup_window_icon(self) -> None:
        if PIL_AVAILABLE and Image is not None and ImageTk is not None and self.icon_source_path.exists():
            try:
                image = Image.open(self.icon_source_path).convert("RGBA")
                self.tk_icon_photo = ImageTk.PhotoImage(image)
                self.root.iconphoto(True, self.tk_icon_photo)
                return
            except Exception:
                pass
        if self.icon_source_path.exists():
            try:
                self.root.iconbitmap(str(self.icon_source_path))
            except Exception:
                pass

    def _build_ui(self) -> None:
        app = ttk.Frame(self.root, style="App.TFrame", padding=(16, 14))
        app.pack(fill="both", expand=True)

        center = ttk.Frame(app, style="App.TFrame")
        center.pack(fill="both", expand=True)

        top_spacer = ttk.Frame(center, style="App.TFrame")
        top_spacer.pack(fill="x", pady=(8, 12))

        self.action_canvas = Canvas(
            center,
            width=332,
            height=332,
            bg=self.palette["bg"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.action_canvas.pack(pady=(12, 2))
        self.action_glow_outer_id = self.action_canvas.create_oval(
            62, 62, 270, 270, outline="#2a2f3d", width=16
        )
        self.action_glow_inner_id = self.action_canvas.create_oval(
            68, 68, 264, 264, outline="#3b4255", width=8
        )
        self.action_circle_id = self.action_canvas.create_oval(
            84, 84, 248, 248, fill=self.palette["bg"], outline=""
        )
        self.action_ring_id = self.action_canvas.create_oval(
            76, 76, 256, 256, outline=self.palette["accent"], width=2
        )
        self.action_text_id = self.action_canvas.create_text(
            166,
            166,
            text="Connect",
            fill=self.palette["accent_hover"],
            font=("Ubuntu", 27, "bold"),
        )
        self.action_canvas.bind("<Button-1>", lambda _event: self.toggle_connection())
        self.action_canvas.bind("<Enter>", lambda _event: self._action_hover(True))
        self.action_canvas.bind("<Leave>", lambda _event: self._action_hover(False))

        ttk.Label(center, textvariable=self.status_var, style="Status.TLabel").pack(pady=(2, 14))

        chooser = ttk.Frame(center, style="App.TFrame")
        chooser.pack(fill="x", pady=(8, 18), padx=(14, 14))
        ttk.Label(chooser, text="Alternative", style="Field.TLabel").pack(anchor="center", pady=(0, 7))
        self.strategy_combo = ttk.Combobox(
            chooser,
            textvariable=self.strategy_var,
            style="App.TCombobox",
            state="readonly",
            postcommand=lambda: self.refresh_strategies(quiet=True),
            justify="center",
        )
        self.strategy_combo.pack(fill="x")
        self.strategy_combo.bind("<<ComboboxSelected>>", self.on_strategy_selected)

        autostart_row = ttk.Frame(center, style="App.TFrame")
        autostart_row.pack(fill="x", padx=(14, 14), pady=(0, 12))
        self.autostart_check = ttk.Checkbutton(
            autostart_row,
            text="Autostart With Selected Alternative",
            style="App.TCheckbutton",
            variable=self.autostart_var,
            command=self.on_autostart_toggled,
        )
        self.autostart_check.pack(anchor="center")
        ttk.Label(
            autostart_row,
            textvariable=self.autostart_info_var,
            style="InfoCaption.TLabel",
            justify="center",
            wraplength=340,
        ).pack(anchor="center", pady=(2, 0))

        footer = ttk.Frame(app, style="Card.TFrame", padding=(14, 12))
        footer.pack(fill="x", pady=(8, 0), padx=(0, 0), side="bottom")

        version_box = ttk.Frame(footer, style="Card.TFrame")
        version_box.pack(side="left")
        ttk.Label(version_box, textvariable=self.version_badge_var, style="InfoValue.TLabel").pack(side="left")
        self.update_button = ttk.Button(
            version_box,
            text="⟳",
            style="Ghost.TButton",
            command=self.start_update,
            width=3,
        )
        self.update_button.pack(side="left", padx=(8, 0))
        self.update_button.pack_forget()
        self.open_update_button = ttk.Button(
            footer, text="Release Page", style="Ghost.TButton", command=self.open_release_page
        )
        self.open_update_button.pack(side="right", padx=(8, 0))
        self.logs_button = ttk.Button(
            footer, text="Logs", style="Secondary.TButton", command=self.open_logs_window
        )
        self.logs_button.pack(side="right")

        self.refresh_action_button()

    def append_log(self, message: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {message}"

        self.log_history.append(line)
        if len(self.log_history) > 4000:
            self.log_history = self.log_history[-4000:]

        try:
            with self.log_file.open("a", encoding="utf-8") as handle:
                handle.write(f"{line}\n")
        except OSError:
            pass

        if self.log_text is not None and self.log_text.winfo_exists():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{line}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def log(self, message: str) -> None:
        self.root.after(0, self.append_log, message)

    @staticmethod
    def _hex_to_rgb(color: str) -> tuple[int, int, int]:
        value = color.lstrip("#")
        return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)

    def _mix_color(self, left: str, right: str, factor: float) -> str:
        t = max(0.0, min(1.0, factor))
        lr, lg, lb = self._hex_to_rgb(left)
        rr, rg, rb = self._hex_to_rgb(right)
        r = round(lr + (rr - lr) * t)
        g = round(lg + (rg - lg) * t)
        b = round(lb + (rb - lb) * t)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _action_theme(self) -> dict[str, str]:
        if self.update_in_progress:
            return {
                "label": f"Updating {self._update_spinner_symbol()}",
                "fill": "#1b1f2a",
                "text": self.palette["accent_hover"],
                "ring": self.palette["accent_hover"],
                "glow": self.palette["accent"],
                "cursor": "arrow",
            }
        if not self.strategies_map:
            return {
                "label": "No strategy",
                "fill": "#101623",
                "text": "#7384a6",
                "ring": "#3f4960",
                "glow": "#2f3b52",
                "cursor": "arrow",
            }
        if self.is_busy:
            if self.cancel_requested or self.busy_operation in {"disconnect", "service-stop"}:
                busy_label = "Stopping..."
            elif self.busy_operation in {"connect", "service-start"}:
                busy_label = "Connecting..."
            else:
                busy_label = "Working..."
            return {
                "label": busy_label,
                "fill": "#221824",
                "text": "#ffdbe8",
                "ring": self.palette["danger_hover"],
                "glow": self.palette["danger"],
                "cursor": "hand2",
            }
        if self.is_connected():
            return {
                "label": "Connected",
                "fill": "#0d101a",
                "text": self.palette["accent"],
                "ring": self.palette["accent_hover"],
                "glow": self.palette["accent"],
                "cursor": "hand2",
            }
        return {
            "label": "Connect",
            "fill": "#0d101a",
            "text": "#b3bdd1",
            "ring": "#65708a",
            "glow": "#3a445a",
            "cursor": "hand2",
        }

    def _render_action_button(self) -> None:
        if (
            self.action_canvas is None
            or self.action_glow_outer_id is None
            or self.action_glow_inner_id is None
            or self.action_ring_id is None
            or self.action_circle_id is None
            or self.action_text_id is None
        ):
            return

        theme = self._action_theme()
        hover_bonus = 0.12 if self.action_hovered and self.strategies_map else 0.0

        outer_outline = self._mix_color(self.palette["bg"], theme["glow"], 0.38 + hover_bonus)
        inner_outline = self._mix_color(self.palette["bg"], theme["glow"], 0.64 + hover_bonus)
        ring_outline = self._mix_color(theme["ring"], "#ffffff", 0.18 + hover_bonus)
        fill_color = self._mix_color(theme["fill"], self.palette["bg"], 0.12)

        self.action_canvas.configure(cursor=theme["cursor"])
        self.action_canvas.itemconfigure(self.action_glow_outer_id, outline=outer_outline, width=13)
        self.action_canvas.itemconfigure(self.action_glow_inner_id, outline=inner_outline, width=6)
        self.action_canvas.itemconfigure(self.action_ring_id, outline=ring_outline, width=2)
        self.action_canvas.itemconfigure(self.action_circle_id, fill=fill_color)
        self.action_canvas.itemconfigure(self.action_text_id, text=theme["label"], fill=theme["text"])

    def _terminate_subprocess(self, proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name == "posix":
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
            else:
                proc.terminate()
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass

    def _request_cancel(self) -> None:
        self.cancel_requested = True
        proc = self.active_command_proc
        if proc is not None:
            self._terminate_subprocess(proc)

    def is_connected(self) -> bool:
        if sys.platform.startswith("linux"):
            return self.service_active_cached
        if self.current_runtime_mode == "linux-zapret":
            return True
        return self.process is not None and self.process.poll() is None

    def refresh_action_button(self) -> None:
        self._render_action_button()
        self.refresh_tray_menu_state()

    def _action_hover(self, is_hover: bool) -> None:
        self.action_hovered = is_hover
        self.refresh_action_button()

    def setup_tray_icon(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        if not GTK_TRAY_AVAILABLE:
            self.log("System tray support is not available (Gtk3/PyGObject missing).")
            return
        if self.tray_thread is not None:
            return
        self.tray_thread = threading.Thread(target=self._tray_main, daemon=True)
        self.tray_thread.start()

    def _tray_main(self) -> None:
        if Gtk is None:
            return
        try:
            icon = Gtk.StatusIcon()
            icon_path = self.icon_png_path if self.icon_png_path.exists() else self.icon_source_path
            if icon_path.exists():
                try:
                    if GdkPixbuf is not None:
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path), 24, 24, True)
                        icon.set_from_pixbuf(pixbuf)
                    else:
                        icon.set_from_file(str(icon_path))
                except Exception:
                    icon.set_from_icon_name("applications-system")
            else:
                icon.set_from_icon_name("applications-system")
            icon.set_title("Zapret")
            icon.set_tooltip_text("Zapret")
            icon.set_visible(True)

            menu = Gtk.Menu()
            item_show = Gtk.MenuItem(label="Show Zapret")
            item_show.connect("activate", self._tray_on_show)
            menu.append(item_show)

            item_toggle = Gtk.MenuItem(label="Connect")
            item_toggle.connect("activate", self._tray_on_toggle)
            menu.append(item_toggle)

            item_exit = Gtk.MenuItem(label="Exit")
            item_exit.connect("activate", self._tray_on_exit)
            menu.append(item_exit)
            menu.show_all()

            icon.connect("activate", self._tray_on_show)
            icon.connect("popup-menu", self._tray_on_popup)

            self.tray_icon = icon
            self.tray_menu = menu
            self.tray_toggle_item = item_toggle
            self.tray_available = True
            self.refresh_tray_menu_state()
            Gtk.main()
        except Exception as exc:  # pylint: disable=broad-except
            self.tray_available = False
            self.log(f"System tray initialization failed: {exc}")

    def _tray_toggle_label(self) -> str:
        if self.update_in_progress:
            return "Updating..."
        return "Disconnect" if (self.is_busy or self.is_connected()) else "Connect"

    def refresh_tray_menu_state(self) -> None:
        if not self.tray_available or self.tray_toggle_item is None or GLib is None:
            return
        label = self._tray_toggle_label()

        def _apply() -> bool:
            if self.tray_toggle_item is not None:
                self.tray_toggle_item.set_label(label)
            return False

        GLib.idle_add(_apply)

    def _tray_on_show(self, *_args: object) -> None:
        self.root.after(0, self.show_window)

    def _tray_on_toggle(self, *_args: object) -> None:
        self.root.after(0, self.toggle_connection)

    def _tray_on_exit(self, *_args: object) -> None:
        self.root.after(0, self.exit_application)

    def _tray_on_popup(self, icon_obj: object, button: int, activate_time: int) -> None:
        if self.tray_menu is None or Gtk is None:
            return
        self.tray_menu.popup(None, None, Gtk.StatusIcon.position_menu, icon_obj, button, activate_time)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.focus_force()
        except Exception:
            pass

    def hide_window_to_tray(self) -> None:
        self.root.withdraw()
        self.log("Window hidden to tray.")

    def stop_tray_icon(self) -> None:
        if not self.tray_available or GLib is None or Gtk is None:
            return

        def _quit() -> bool:
            try:
                if self.tray_icon is not None:
                    self.tray_icon.set_visible(False)
            except Exception:
                pass
            try:
                Gtk.main_quit()
            except Exception:
                pass
            return False

        self.tray_available = False
        GLib.idle_add(_quit)

    def exit_application(self) -> None:
        if self.is_exiting:
            return
        if self.update_in_progress:
            self.log("Update is in progress. Exit is blocked until update finishes.")
            return
        self.is_exiting = True
        if not sys.platform.startswith("linux"):
            self.disconnect()
        elif self.is_busy:
            self._request_cancel()
        self.stop_tray_icon()
        self.root.destroy()

    def prepare_icon_assets(self) -> None:
        if not self.icon_source_path.exists() or not PIL_AVAILABLE or Image is None:
            return
        try:
            self.linux_state_dir.mkdir(parents=True, exist_ok=True)
            image = Image.open(self.icon_source_path).convert("RGBA")
            image = image.resize((256, 256), RESAMPLE_LANCZOS)
            image.save(self.icon_png_path, format="PNG")
        except Exception:
            pass

    def _chown_for_user(self, path: Path, uid: int, gid: int) -> None:
        if os.geteuid() != 0:
            return
        try:
            os.chown(path, uid, gid)
        except OSError:
            pass

    def ensure_desktop_entry(self) -> None:
        if not sys.platform.startswith("linux"):
            return

        user = self.determine_ws_user()
        try:
            pw_record = pwd.getpwnam(user)
        except KeyError:
            return

        home = Path(pw_record.pw_dir)
        uid = pw_record.pw_uid
        gid = pw_record.pw_gid
        apps_dir = home / ".local" / "share" / "applications"
        icons_dir = home / ".local" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        desktop_file = apps_dir / DESKTOP_ENTRY_FILENAME
        icon_file = icons_dir / f"{DESKTOP_ICON_BASENAME}.png"

        try:
            apps_dir.mkdir(parents=True, exist_ok=True)
            icons_dir.mkdir(parents=True, exist_ok=True)
            self._chown_for_user(apps_dir, uid, gid)
            self._chown_for_user(icons_dir, uid, gid)
        except OSError as exc:
            self.log(f"Failed to prepare desktop entry directories: {exc}")
            return

        if PIL_AVAILABLE and Image is not None and self.icon_source_path.exists():
            try:
                image = Image.open(self.icon_source_path).convert("RGBA")
                image = image.resize((256, 256), RESAMPLE_LANCZOS)
                image.save(icon_file, format="PNG")
            except Exception as exc:  # pylint: disable=broad-except
                self.log(f"Failed to export menu icon: {exc}")
        elif self.icon_png_path.exists():
            try:
                shutil.copy2(self.icon_png_path, icon_file)
            except OSError as exc:
                self.log(f"Failed to copy menu icon: {exc}")

        self._chown_for_user(icon_file, uid, gid)

        exec_path = self.app_dir / "run-ubuntu-gui.sh"
        icon_value = str(icon_file) if icon_file.exists() else DESKTOP_ICON_BASENAME
        entry_text = (
            "[Desktop Entry]\n"
            "Version=1.0\n"
            "Type=Application\n"
            "Name=Zapret\n"
            "Comment=Zapret Launcher\n"
            f"Exec={exec_path}\n"
            f"Path={self.app_dir}\n"
            f"Icon={icon_value}\n"
            f"StartupWMClass={APP_WM_CLASS}\n"
            "Terminal=false\n"
            "Categories=Network;Utility;\n"
            "StartupNotify=true\n"
        )

        try:
            desktop_file.write_text(entry_text, encoding="utf-8")
            os.chmod(desktop_file, 0o644)
            self._chown_for_user(desktop_file, uid, gid)
        except OSError as exc:
            self.log(f"Failed to write desktop entry: {exc}")

    def toggle_connection(self) -> None:
        if not self.strategies_map:
            self.log("No strategy available.")
            return
        if self.update_in_progress:
            self.log("Update is in progress. Wait until it finishes.")
            return
        if sys.platform.startswith("linux") and not self.is_busy:
            self.service_active_cached = self.is_service_active()
        if self.is_busy or self.is_connected():
            self.disconnect()
        else:
            self.connect()

    def open_logs_window(self) -> None:
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.lift()
            self.log_window.focus_set()
            return

        self.log_window = Toplevel(self.root)
        self.log_window.title("Zapret Logs")
        self.log_window.geometry("920x520")
        self.log_window.minsize(720, 400)
        self.log_window.configure(bg="#0f1726")

        container = ttk.Frame(self.log_window, padding=(12, 12))
        container.pack(fill="both", expand=True)

        self.log_text = ScrolledText(
            container,
            wrap="word",
            state="normal",
            bg="#0f1726",
            fg="#d9e3f2",
            insertbackground="#d9e3f2",
            selectbackground="#244a85",
            relief="flat",
            borderwidth=0,
            font=("Ubuntu Mono", 10),
        )
        self.log_text.pack(fill="both", expand=True)
        self.log_text.insert("end", "\n".join(self.log_history[-1500:]))
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

        button_row = ttk.Frame(container)
        button_row.pack(fill="x", pady=(10, 0))
        ttk.Button(
            button_row,
            text="Close",
            style="Secondary.TButton",
            command=self._close_log_window,
        ).pack(side="right")

        self.log_window.protocol("WM_DELETE_WINDOW", self._close_log_window)
        self.log("Opened logs window.")

    def _close_log_window(self) -> None:
        if self.log_window is not None and self.log_window.winfo_exists():
            self.log_window.destroy()
        self.log_window = None
        self.log_text = None

    def set_status(self, value: str) -> None:
        def _apply() -> None:
            self.status_var.set(value)
            self.refresh_action_button()

        self.root.after(0, _apply)

    def set_version_badge(self, value: str) -> None:
        self.root.after(0, self.version_badge_var.set, value)

    def set_strategy_selector_enabled(self, enabled: bool) -> None:
        def _apply() -> None:
            if self.strategy_combo is None or not self.strategy_combo.winfo_exists():
                return
            self.strategy_combo.configure(state="readonly" if enabled else "disabled")

        self.root.after(0, _apply)

    def set_update_button_enabled(self, enabled: bool) -> None:
        def _apply() -> None:
            if self.update_button is None or not self.update_button.winfo_exists():
                return
            self.update_button.configure(state="normal" if enabled else "disabled")

        self.root.after(0, _apply)

    def _apply_update_button_visibility(self, visible: bool) -> None:
        if self.update_button is None or not self.update_button.winfo_exists():
            return
        if visible:
            if not self.update_button.winfo_manager():
                self.update_button.pack(side="left", padx=(8, 0))
        elif self.update_button.winfo_manager():
            self.update_button.pack_forget()

    def set_update_available_state(
        self,
        *,
        available: bool,
        latest_version: str = "",
        archive_url: str = "",
        release_page_url: str = "",
    ) -> None:
        def _apply() -> None:
            self.update_available = available
            self.latest_version = latest_version.strip()
            self.update_archive_url = archive_url.strip()
            if release_page_url:
                self.release_page_url = release_page_url.strip()
            self._apply_update_button_visibility(self.update_available and not self.update_in_progress)

        self.root.after(0, _apply)

    def _update_spinner_symbol(self) -> str:
        if not self.update_spinner_frames:
            return "*"
        return self.update_spinner_frames[self.update_spinner_index % len(self.update_spinner_frames)]

    def _run_update_animation_step(self) -> None:
        if not self.update_in_progress:
            self.update_animation_job = None
            self.refresh_action_button()
            return
        if self.update_spinner_frames:
            self.update_spinner_index = (self.update_spinner_index + 1) % len(self.update_spinner_frames)
        self.refresh_action_button()
        self.update_animation_job = self.root.after(180, self._run_update_animation_step)

    def start_update_animation(self) -> None:
        self.stop_update_animation()
        self.update_spinner_index = 0
        self.update_animation_job = self.root.after(180, self._run_update_animation_step)

    def stop_update_animation(self) -> None:
        if self.update_animation_job is not None:
            try:
                self.root.after_cancel(self.update_animation_job)
            except Exception:
                pass
        self.update_animation_job = None

    def run_logged_command(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        if self.cancel_requested:
            raise OperationCancelled()
        self.log(" ".join(shlex.quote(part) for part in command))
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            preexec_fn=os.setsid if os.name == "posix" else None,
        )
        self.active_command_proc = proc
        lines: list[str] = []
        try:
            stream = proc.stdout
            while True:
                if self.cancel_requested:
                    self._terminate_subprocess(proc)

                if stream is not None:
                    if os.name == "posix":
                        ready, _, _ = select.select([stream], [], [], 0.2)
                        if ready:
                            line = stream.readline()
                            if line:
                                output = line.rstrip()
                                if output:
                                    lines.append(output)
                                    self.log(output)
                    else:
                        line = stream.readline()
                        if line:
                            output = line.rstrip()
                            if output:
                                lines.append(output)
                                self.log(output)

                rc = proc.poll()
                if rc is not None:
                    if stream is not None and os.name == "posix":
                        while True:
                            ready, _, _ = select.select([stream], [], [], 0.0)
                            if not ready:
                                break
                            line = stream.readline()
                            if not line:
                                break
                            output = line.rstrip()
                            if output:
                                lines.append(output)
                                self.log(output)
                    break

            rc = proc.wait(timeout=1)
            if self.cancel_requested:
                raise OperationCancelled()
            if rc != 0:
                raise RuntimeError(f"Command failed with exit code {rc}: {' '.join(command)}")
            return "\n".join(lines)
        finally:
            if self.active_command_proc is proc:
                self.active_command_proc = None

    def run_command_capture(
        self,
        command: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output = (proc.stdout or "").strip()
            return proc.returncode, output
        except OSError as exc:
            return 127, str(exc)

    def elevate_command(self, command: list[str]) -> list[str]:
        if os.geteuid() == 0:
            return command
        if shutil.which("pkexec") is not None:
            return ["pkexec", *command]
        if shutil.which("sudo") is not None:
            return ["sudo", *command]
        raise RuntimeError("Neither pkexec nor sudo is available for privileged Linux operations.")

    def refresh_strategies(self, quiet: bool = False) -> None:
        found: list[Strategy] = []

        bat_files = [p for p in self.source_dir.glob("general (ALT*).bat") if p.is_file()]
        if not bat_files:
            bat_files = [
                p
                for p in self.source_dir.glob("general*.bat")
                if p.is_file() and p.name.lower() != "service.bat"
            ]
        found.extend(Strategy(name=p.name, path=p, kind="bat") for p in bat_files)

        sh_files = [p for p in self.source_dir.glob("general*.sh") if p.is_file()]
        found.extend(Strategy(name=p.name, path=p, kind="sh") for p in sh_files)

        found = sorted(found, key=lambda item: natural_sort_key(item.name))
        self.strategies_map = {item.name: item for item in found}
        strategy_names = [item.name for item in found]
        self.strategy_combo["values"] = strategy_names

        if not strategy_names:
            self.strategy_var.set("")
            if self.action_canvas is not None:
                self.action_canvas.configure(state="disabled")
            self.refresh_action_button()
            self.update_autostart_info_label()
            if not quiet:
                self.log("No strategy files found (expected general*.bat or general*.sh).")
            return

        if self.action_canvas is not None:
            self.action_canvas.configure(state="normal")
        current = self.strategy_var.get()
        if current not in strategy_names:
            remembered = self.last_selected_strategy_name or ""
            chosen = remembered if remembered in strategy_names else strategy_names[0]
            self.strategy_var.set(chosen)
            self.last_selected_strategy_name = chosen
            self.save_selected_strategy_name(chosen)
        else:
            self.last_selected_strategy_name = current
            self.save_selected_strategy_name(current)

        bat_count = sum(1 for item in found if item.kind == "bat")
        sh_count = sum(1 for item in found if item.kind == "sh")
        self.refresh_action_button()
        self.update_autostart_info_label()
        if not quiet:
            self.log(f"Loaded {len(found)} strategy file(s): .bat={bat_count}, .sh={sh_count}")

    def on_strategy_selected(self, _event: object | None = None) -> None:
        selected = self.strategy_var.get().strip()
        if not selected:
            return
        self.last_selected_strategy_name = selected
        self.save_selected_strategy_name(selected)
        self.update_autostart_info_label()

    def load_selected_strategy_name(self) -> str:
        try:
            value = self.selected_strategy_file.read_text(encoding="utf-8").strip()
            return value
        except OSError:
            return ""

    def save_selected_strategy_name(self, name: str) -> None:
        clean = name.strip()
        if not clean:
            return
        try:
            self.linux_state_dir.mkdir(parents=True, exist_ok=True)
            self.selected_strategy_file.write_text(f"{clean}\n", encoding="utf-8")
        except OSError:
            return

    def set_autostart_var_safely(self, enabled: bool) -> None:
        def _apply() -> None:
            self.autostart_update_in_progress = True
            self.autostart_var.set(1 if enabled else 0)
            self.autostart_update_in_progress = False

        self.root.after(0, _apply)

    def compose_autostart_info(self, enabled: bool, service_strategy: str) -> str:
        if not enabled:
            return "Autostart: off"
        clean_service = service_strategy.strip()
        if not clean_service:
            return "Autostart: enabled (unknown alternative)"
        selected = self.strategy_var.get().strip()
        if selected and selected != clean_service:
            return f"Autostart: {clean_service} (selected: {selected})"
        return f"Autostart: {clean_service}"

    def set_autostart_cache(self, enabled: bool, service_strategy: str) -> None:
        self.autostart_enabled_cached = enabled
        self.autostart_strategy_cached = service_strategy.strip()

    def update_autostart_info_label(self) -> None:
        def _apply() -> None:
            text = self.compose_autostart_info(
                self.autostart_enabled_cached,
                self.autostart_strategy_cached,
            )
            self.autostart_info_var.set(text)

        self.root.after(0, _apply)

    def update_autostart_info_label_sync(self) -> None:
        text = self.compose_autostart_info(
            self.autostart_enabled_cached,
            self.autostart_strategy_cached,
        )
        self.autostart_info_var.set(text)

    def set_autostart_check_enabled(self, enabled: bool) -> None:
        def _apply() -> None:
            if self.autostart_check is None or not self.autostart_check.winfo_exists():
                return
            self.autostart_check.configure(state="normal" if enabled else "disabled")

        self.root.after(0, _apply)

    def refresh_autostart_state_async(self) -> None:
        threading.Thread(target=self.refresh_autostart_state, daemon=True).start()

    def ensure_managed_service_async(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        threading.Thread(target=self.ensure_managed_service, daemon=True).start()

    def managed_service_exists(self) -> bool:
        return self.autostart_system_unit.exists() or self.autostart_local_unit.exists()

    def ensure_managed_service(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        if self.managed_service_exists():
            return

        strategy_name = self.strategy_var.get().strip()
        strategy = self.strategies_map.get(strategy_name)
        if strategy is None:
            self.log("Cannot create systemd service: no strategy selected.")
            return
        if strategy.kind != "bat":
            self.log("Cannot create systemd service: only .bat alternatives are supported.")
            return

        try:
            self.log("Managed service not found. Creating systemd service...")
            self.install_or_update_managed_service(strategy)
            self.log(f"Managed service created for {strategy.name}.")
        except Exception as exc:  # pylint: disable=broad-except
            self.log(f"[ERROR] Failed to create managed service: {exc}")
        finally:
            self.refresh_autostart_state_async()

    def refresh_autostart_state(self) -> None:
        enabled = self.is_autostart_enabled()
        active = self.is_service_active()
        strategy = self.read_autostart_strategy_name() if (enabled or active or self.managed_service_exists()) else ""

        def _apply() -> None:
            self.set_autostart_cache(enabled, strategy)
            self.service_active_cached = active
            self.autostart_update_in_progress = True
            self.autostart_var.set(1 if enabled else 0)
            self.autostart_update_in_progress = False
            self.update_autostart_info_label_sync()
            if not self.is_busy:
                self.status_var.set("Connected" if active else "Idle")
                self.refresh_action_button()

        self.root.after(0, _apply)

    def is_service_active(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        rc, output = self.run_command_capture(
            ["systemctl", "is-active", AUTOSTART_SERVICE_NAME],
            cwd=self.app_dir,
        )
        if rc != 0:
            return False
        return output.splitlines()[0].strip() == "active" if output else False

    def is_autostart_enabled(self) -> bool:
        if not sys.platform.startswith("linux"):
            return False
        rc, output = self.run_command_capture(
            ["systemctl", "is-enabled", AUTOSTART_SERVICE_NAME],
            cwd=self.app_dir,
        )
        if rc != 0:
            return False
        return output.splitlines()[0].strip() == "enabled" if output else False

    def read_autostart_strategy_name(self) -> str:
        desc_pattern = re.compile(r"^Description=Zapret Discord Autostart\s*\((.+)\)\s*$")
        for candidate in (self.autostart_system_unit, self.autostart_local_unit):
            try:
                text = candidate.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for line in text.splitlines():
                match = desc_pattern.match(line.strip())
                if match:
                    return match.group(1).strip()

        try:
            return self.autostart_strategy_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def on_autostart_toggled(self) -> None:
        if self.autostart_update_in_progress:
            return
        if self.update_in_progress:
            self.log("Cannot change autostart while update is in progress.")
            self.refresh_autostart_state_async()
            return
        if self.autostart_busy:
            self.log("Autostart operation is already in progress.")
            self.refresh_autostart_state_async()
            return
        if self.is_busy:
            self.log("Cannot change autostart while another operation is in progress.")
            self.refresh_autostart_state_async()
            return

        enabled = bool(self.autostart_var.get())
        strategy_name = self.strategy_var.get().strip()
        threading.Thread(
            target=self._autostart_worker,
            args=(enabled, strategy_name),
            daemon=True,
        ).start()

    def _autostart_worker(self, enabled: bool, strategy_name: str) -> None:
        self.autostart_busy = True
        self.set_autostart_check_enabled(False)
        try:
            if enabled:
                strategy = self.strategies_map.get(strategy_name)
                if strategy is None:
                    raise RuntimeError("Select a strategy before enabling autostart.")
                self.enable_autostart_service(strategy)
                self.log(f"Autostart enabled for {strategy.name}.")
                self.set_autostart_cache(True, strategy.name)
                self.update_autostart_info_label()
            else:
                self.disable_autostart_service()
                self.log("Autostart disabled.")
                self.set_autostart_cache(False, "")
                self.update_autostart_info_label()
        except Exception as exc:  # pylint: disable=broad-except
            self.log(f"[ERROR] Failed to update autostart: {exc}")
        finally:
            self.autostart_busy = False
            self.set_autostart_check_enabled(True)
            self.refresh_autostart_state_async()

    @staticmethod
    def _systemd_escape(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def write_autostart_unit(self, config_path: Path, strategy: Strategy) -> None:
        script = self.linux_repo_dir / "init.d" / "sysv" / "zapret"
        if not script.exists():
            raise RuntimeError(f"Linux service script not found: {script}")

        self.linux_state_dir.mkdir(parents=True, exist_ok=True)
        base = self._systemd_escape(str(self.linux_repo_dir))
        rw = self._systemd_escape(str(self.linux_state_dir))
        cfg = self._systemd_escape(str(config_path))
        start = self._systemd_escape(str(script))
        unit_text = (
            "[Unit]\n"
            f"Description=Zapret Discord Autostart ({strategy.name})\n"
            "After=network-online.target\n"
            "Wants=network-online.target\n"
            "\n"
            "[Service]\n"
            "Type=oneshot\n"
            "RemainAfterExit=yes\n"
            f'Environment="ZAPRET_BASE={base}"\n'
            f'Environment="ZAPRET_RW={rw}"\n'
            f'Environment="ZAPRET_CONFIG={cfg}"\n'
            f"ExecStart={start} restart\n"
            f"ExecStop={start} stop\n"
            "TimeoutStartSec=180\n"
            "TimeoutStopSec=40\n"
            "\n"
            "[Install]\n"
            "WantedBy=multi-user.target\n"
        )
        self.autostart_local_unit.write_text(unit_text, encoding="utf-8")

    def install_or_update_managed_service(self, strategy: Strategy) -> None:
        if not sys.platform.startswith("linux"):
            raise RuntimeError("Managed service is supported only on Linux.")
        if strategy.kind != "bat":
            raise RuntimeError("Managed service supports only .bat alternatives on Linux backend.")
        if " " in str(self.source_dir.resolve()):
            raise RuntimeError("Project path contains spaces. Move project to a path without spaces.")

        self.log("Preparing managed systemd service for selected alternative...")
        self.ensure_linux_backend()
        config_path = self.generate_linux_config_from_bat(strategy.path, output_path=self.autostart_config_file)
        self.log(f"Generated service config: {config_path}")
        self.write_autostart_unit(config_path, strategy)
        self.autostart_strategy_file.write_text(f"{strategy.name}\n", encoding="utf-8")

        install_cmd = self.elevate_command(
            [
                "install",
                "-m",
                "0644",
                str(self.autostart_local_unit),
                str(self.autostart_system_unit),
            ]
        )
        reload_cmd = self.elevate_command(["systemctl", "daemon-reload"])

        self.run_logged_command(install_cmd, cwd=self.app_dir)
        self.run_logged_command(reload_cmd, cwd=self.app_dir)

    def enable_autostart_service(self, strategy: Strategy) -> None:
        if not self.managed_service_exists():
            self.install_or_update_managed_service(strategy)
        elif self.read_autostart_strategy_name() != strategy.name:
            self.install_or_update_managed_service(strategy)

        enable_cmd = self.elevate_command(["systemctl", "enable", AUTOSTART_SERVICE_NAME])
        self.run_logged_command(enable_cmd, cwd=self.app_dir)

    def disable_autostart_service(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        disable_cmd = self.elevate_command(["systemctl", "disable", AUTOSTART_SERVICE_NAME])
        rc, output = self.run_command_capture(disable_cmd, cwd=self.app_dir)
        if output:
            for line in output.splitlines():
                if line.strip():
                    self.log(line.strip())
        if rc != 0:
            lowered = output.lower()
            benign = ("not loaded", "not-found", "does not exist", "no such file")
            if not any(token in lowered for token in benign):
                raise RuntimeError(f"systemctl disable failed with code {rc}.")

    def start_managed_service(self, strategy: Strategy) -> None:
        service_strategy = self.read_autostart_strategy_name()
        if not self.managed_service_exists() or service_strategy != strategy.name:
            self.install_or_update_managed_service(strategy)

        start_cmd = self.elevate_command(["systemctl", "start", AUTOSTART_SERVICE_NAME])
        self.run_logged_command(start_cmd, cwd=self.app_dir)

    def stop_managed_service(self) -> None:
        stop_cmd = self.elevate_command(["systemctl", "stop", AUTOSTART_SERVICE_NAME])
        rc, output = self.run_command_capture(stop_cmd, cwd=self.app_dir)
        if output:
            for line in output.splitlines():
                if line.strip():
                    self.log(line.strip())
        if rc != 0:
            lowered = output.lower()
            benign = ("not loaded", "not-found", "does not exist", "no such file")
            if not any(token in lowered for token in benign):
                raise RuntimeError(f"systemctl stop failed with code {rc}.")

    def ensure_user_lists(self) -> None:
        lists_dir = self.source_dir / "lists"
        lists_dir.mkdir(parents=True, exist_ok=True)

        defaults = {
            "ipset-exclude-user.txt": "203.0.113.113/32\n",
            "list-general-user.txt": "domain.example.abc\n",
            "list-exclude-user.txt": "domain.example.abc\n",
        }
        for filename, content in defaults.items():
            target = lists_dir / filename
            if not target.exists():
                target.write_text(content, encoding="utf-8")

    def read_game_filter_values(self) -> dict[str, str]:
        default = {"GameFilter": "12", "GameFilterTCP": "12", "GameFilterUDP": "12"}
        game_flag = self.source_dir / "utils" / "game_filter.enabled"
        if not game_flag.exists():
            return default

        mode = game_flag.read_text(encoding="utf-8", errors="ignore").splitlines()
        mode_name = mode[0].strip().lower() if mode else ""

        if mode_name == "all":
            return {
                "GameFilter": "1024-65535",
                "GameFilterTCP": "1024-65535",
                "GameFilterUDP": "1024-65535",
            }
        if mode_name == "tcp":
            return {"GameFilter": "1024-65535", "GameFilterTCP": "1024-65535", "GameFilterUDP": "12"}
        return {"GameFilter": "1024-65535", "GameFilterTCP": "12", "GameFilterUDP": "1024-65535"}

    def resolve_runtime(self) -> Runtime:
        native_winws = self.source_dir / "bin" / "winws"
        if native_winws.exists() and os.access(native_winws, os.X_OK):
            return Runtime(mode="native", prefix=[str(native_winws)])

        winws_exe = self.source_dir / "bin" / "winws.exe"
        if winws_exe.exists():
            wine = shutil.which("wine")
            if wine is None:
                raise RuntimeError("wine is not installed, but bin/winws.exe exists.")
            return Runtime(mode="wine", prefix=[wine, str(winws_exe)])

        raise RuntimeError("winws executable not found in ./bin (expected winws or winws.exe).")

    def to_runtime_path(self, runtime: Runtime, path: Path, with_trailing_sep: bool = False) -> str:
        resolved = path.resolve()
        if runtime.mode == "wine":
            converted = f"Z:{resolved.as_posix()}"
            if with_trailing_sep and not converted.endswith("/"):
                converted += "/"
            return converted

        converted = resolved.as_posix()
        if with_trailing_sep and not converted.endswith("/"):
            converted += "/"
        return converted

    def extract_args(self, strategy_path: Path, runtime: Runtime, game_filter: dict[str, str]) -> list[str]:
        lines = strategy_path.read_text(encoding="utf-8", errors="ignore").splitlines()

        capture = False
        fragments: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not capture:
                match = re.search(r'"?%BIN%winws\.exe"?\s*(.*)$', stripped, flags=re.IGNORECASE)
                if not match:
                    continue
                capture = True
                fragment = match.group(1).strip()
            else:
                fragment = stripped

            if fragment.endswith("^"):
                fragments.append(fragment[:-1].rstrip())
                continue

            if fragment:
                fragments.append(fragment)
            break

        if not fragments:
            raise RuntimeError(f"Failed to parse winws arguments from {strategy_path.name}.")

        args_line = " ".join(fragments)
        replacements = {
            "%BIN%": self.to_runtime_path(runtime, self.source_dir / "bin", with_trailing_sep=True),
            "%LISTS%": self.to_runtime_path(runtime, self.source_dir / "lists", with_trailing_sep=True),
            "%GameFilter%": game_filter["GameFilter"],
            "%GameFilterTCP%": game_filter["GameFilterTCP"],
            "%GameFilterUDP%": game_filter["GameFilterUDP"],
        }
        for placeholder, value in replacements.items():
            args_line = args_line.replace(placeholder, value)

        try:
            return shlex.split(args_line, posix=True)
        except ValueError as exc:
            raise RuntimeError(f"Failed to tokenize arguments for {strategy_path.name}: {exc}") from exc

    def should_sync_linux_backend(self) -> bool:
        if not self.linux_sync_stamp.exists():
            return True
        try:
            last_sync = float(self.linux_sync_stamp.read_text(encoding="utf-8").strip())
        except ValueError:
            return True
        return (time.time() - last_sync) > LINUX_SYNC_INTERVAL_SEC

    def mark_linux_synced(self) -> None:
        self.linux_root.mkdir(parents=True, exist_ok=True)
        self.linux_sync_stamp.write_text(str(time.time()), encoding="utf-8")

    def ensure_linux_backend(self) -> None:
        self.linux_root.mkdir(parents=True, exist_ok=True)
        nfqws_bin = self.linux_repo_dir / "nfq" / "nfqws"
        need_build = not (nfqws_bin.exists() and os.access(nfqws_bin, os.X_OK))

        repo_git_dir = self.linux_repo_dir / ".git"
        if repo_git_dir.exists():
            if self.should_sync_linux_backend():
                self.log("Syncing Linux zapret backend from upstream...")
                self.run_logged_command(
                    ["git", "-C", str(self.linux_repo_dir), "pull", "--ff-only"],
                    cwd=self.app_dir,
                )
                self.mark_linux_synced()
                need_build = True
            else:
                self.log("Linux backend is fresh enough, skipping git pull.")
        else:
            self.log("Cloning Linux zapret backend (first run)...")
            self.run_logged_command(
                ["git", "clone", "--depth=1", LINUX_UPSTREAM_REPO, str(self.linux_repo_dir)],
                cwd=self.app_dir,
            )
            self.mark_linux_synced()
            need_build = True

        if need_build:
            jobs = max(1, min(os.cpu_count() or 1, 8))
            self.log("Building Linux binaries (nfqws/tpws/ip2net/mdig)...")
            self.run_logged_command(
                ["make", "-C", str(self.linux_repo_dir), f"-j{jobs}"],
                cwd=self.app_dir,
            )

        if not (nfqws_bin.exists() and os.access(nfqws_bin, os.X_OK)):
            raise RuntimeError(f"Linux backend is prepared, but nfqws not found: {nfqws_bin}")

    def split_wf_ports_and_nfqws_args(self, args: list[str]) -> tuple[str, str, list[str]]:
        tcp_ports = "80,443"
        udp_ports = "443"
        nfq_args: list[str] = []

        for arg in args:
            if arg.startswith("--wf-tcp="):
                value = arg.split("=", 1)[1].strip()
                if value:
                    tcp_ports = value
                continue
            if arg.startswith("--wf-udp="):
                value = arg.split("=", 1)[1].strip()
                if value:
                    udp_ports = value
                continue
            nfq_args.append(arg)

        if not nfq_args:
            raise RuntimeError("Converted strategy has empty nfqws options.")
        return tcp_ports, udp_ports, nfq_args

    def build_nfqws_opt_block(self, nfq_args: list[str]) -> str:
        lines: list[str] = []
        current: list[str] = []

        for arg in nfq_args:
            current.append(arg)
            if arg == "--new":
                lines.append(" ".join(current))
                current = []
        if current:
            lines.append(" ".join(current))

        return "\n".join(lines)

    def determine_ws_user(self) -> str:
        try:
            owner_uid = self.source_dir.stat().st_uid
            if owner_uid != 0:
                return pwd.getpwuid(owner_uid).pw_name
        except Exception:
            pass

        for env_name in ("SUDO_USER", "PKEXEC_UID", "USER", "LOGNAME"):
            raw = os.environ.get(env_name, "").strip()
            if not raw:
                continue
            if env_name == "PKEXEC_UID":
                try:
                    uid = int(raw)
                    if uid != 0:
                        return pwd.getpwuid(uid).pw_name
                except Exception:
                    continue
            elif raw != "root":
                return raw

        current = getpass.getuser() or "root"
        return current

    def generate_linux_config_from_bat(
        self,
        strategy_path: Path,
        *,
        output_path: Path | None = None,
    ) -> Path:
        runtime = Runtime(mode="native", prefix=[])
        game_filter = self.read_game_filter_values()
        args = self.extract_args(strategy_path, runtime, game_filter)
        tcp_ports, udp_ports, nfq_args = self.split_wf_ports_and_nfqws_args(args)
        nfqws_opt = self.build_nfqws_opt_block(nfq_args)
        ws_user = self.determine_ws_user()
        target_path = output_path or self.linux_generated_config

        self.linux_state_dir.mkdir(parents=True, exist_ok=True)
        config_text = (
            "# Auto-generated from Windows strategy by zapret_gui.py\n"
            "# Regenerated on every Connect for .bat strategies on Linux.\n"
            "FWTYPE=nftables\n"
            "INIT_APPLY_FW=1\n"
            "MODE_FILTER=none\n"
            f"WS_USER={ws_user}\n"
            "DISABLE_IPV6=1\n"
            "TPWS_SOCKS_ENABLE=0\n"
            "TPWS_ENABLE=0\n"
            "NFQWS_ENABLE=1\n"
            "QNUM=200\n"
            f"NFQWS_PORTS_TCP={tcp_ports}\n"
            f"NFQWS_PORTS_UDP={udp_ports}\n"
            "NFQWS_TCP_PKT_OUT=9\n"
            "NFQWS_TCP_PKT_IN=3\n"
            "NFQWS_UDP_PKT_OUT=9\n"
            "NFQWS_UDP_PKT_IN=0\n"
            "NFQWS_OPT=\"\n"
            f"{nfqws_opt}\n"
            "\"\n"
        )
        target_path.write_text(config_text, encoding="utf-8")
        return target_path

    def build_elevated_command(self, action: str) -> tuple[list[str], dict[str, str]]:
        script = self.linux_repo_dir / "init.d" / "sysv" / "zapret"
        if not script.exists():
            raise RuntimeError(f"Linux service script not found: {script}")

        env = os.environ.copy()
        env["ZAPRET_BASE"] = str(self.linux_repo_dir)
        env["ZAPRET_RW"] = str(self.linux_state_dir)
        env["ZAPRET_CONFIG"] = str(self.linux_generated_config)

        base_command = [str(script), action]
        if os.geteuid() == 0:
            return base_command, env

        if shutil.which("pkexec") is not None:
            cmd = [
                "pkexec",
                "/usr/bin/env",
                f"ZAPRET_BASE={env['ZAPRET_BASE']}",
                f"ZAPRET_RW={env['ZAPRET_RW']}",
                f"ZAPRET_CONFIG={env['ZAPRET_CONFIG']}",
                str(script),
                action,
            ]
            return cmd, env

        if shutil.which("sudo") is not None:
            cmd = [
                "sudo",
                "/usr/bin/env",
                f"ZAPRET_BASE={env['ZAPRET_BASE']}",
                f"ZAPRET_RW={env['ZAPRET_RW']}",
                f"ZAPRET_CONFIG={env['ZAPRET_CONFIG']}",
                str(script),
                action,
            ]
            return cmd, env

        raise RuntimeError("Neither pkexec nor sudo is available for privileged Linux operations.")

    def start_linux_from_bat(self, strategy_path: Path) -> None:
        if " " in str(self.source_dir.resolve()):
            raise RuntimeError("Project path contains spaces. Move project to a path without spaces.")

        self.log("Preparing Linux backend for .bat strategy...")
        self.ensure_linux_backend()
        config_path = self.generate_linux_config_from_bat(strategy_path)
        self.log(f"Generated Linux config: {config_path}")
        ws_user = "unknown"
        for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("WS_USER="):
                ws_user = line.split("=", 1)[1].strip() or "unknown"
                break
        self.log(f"Using WS_USER={ws_user}")
        command, env = self.build_elevated_command("restart")
        self.log("Starting Linux zapret service (root privileges required)...")
        self.run_logged_command(command, cwd=self.app_dir, env=env)

    def stop_linux_backend(self) -> None:
        if not self.linux_generated_config.exists():
            self.log("Linux backend config was not generated yet.")
            return
        command, env = self.build_elevated_command("stop")
        self.log("Stopping Linux zapret service...")
        self.run_logged_command(command, cwd=self.app_dir, env=env)

    def connect(self) -> None:
        if self.update_in_progress:
            self.log("Update is in progress. Connect is temporarily disabled.")
            return
        if sys.platform.startswith("linux"):
            if self.is_busy:
                if self.busy_operation == "service-stop":
                    self.log("Service stop is in progress.")
                else:
                    self.log("Another operation is already in progress.")
                return

            strategy_name = self.strategy_var.get().strip()
            if not strategy_name:
                self.log("No strategy selected.")
                return

            strategy = self.strategies_map.get(strategy_name)
            if strategy is None:
                self.log(f"Selected strategy does not exist: {strategy_name}")
                return
            if strategy.kind != "bat":
                self.log("Only .bat alternatives are supported in Linux systemd mode.")
                return

            self.last_selected_strategy = strategy
            self.is_busy = True
            self.busy_operation = "service-start"
            self.set_status("Starting...")
            self.refresh_action_button()
            threading.Thread(target=self._connect_via_systemd_worker, args=(strategy,), daemon=True).start()
            return

        if self.is_busy:
            self.disconnect()
            return
        if self.process is not None and self.process.poll() is None:
            self.log("A strategy is already running. Use Disconnect first.")
            return

        strategy_name = self.strategy_var.get().strip()
        if not strategy_name:
            self.log("No strategy selected.")
            return

        strategy = self.strategies_map.get(strategy_name)
        if strategy is None:
            self.log(f"Selected strategy does not exist: {strategy_name}")
            return
        self.last_selected_strategy = strategy

        self.cancel_requested = False
        self.is_busy = True
        self.busy_operation = "connect"
        self.set_status("Connecting...")
        self.refresh_action_button()
        threading.Thread(target=self._connect_worker, args=(strategy,), daemon=True).start()

    def _connect_via_systemd_worker(self, strategy: Strategy) -> None:
        try:
            self.ensure_user_lists()
            self.start_managed_service(strategy)
            self.log(f"Service started with {strategy.name}.")
        except OperationCancelled:
            self.log("Connection start cancelled.")
            try:
                self.stop_managed_service()
            except Exception:
                pass
        except Exception as exc:  # pylint: disable=broad-except
            self.set_status("Error")
            self.log(f"[ERROR] {exc}")
        finally:
            self.is_busy = False
            self.busy_operation = None
            self.cancel_requested = False
            self.refresh_autostart_state_async()
            self.root.after(0, self.refresh_action_button)

    def _connect_worker(self, strategy: Strategy) -> None:
        strategy_name = strategy.name
        strategy_path = strategy.path
        try:
            self.ensure_user_lists()

            if strategy.kind == "bat" and sys.platform.startswith("linux"):
                self.start_linux_from_bat(strategy_path)
                self.process = None
                self.current_runtime_mode = "linux-zapret"
                self.set_status("Connected")
                self.log(f"Connected with {strategy_name} via Linux backend.")
                return

            if strategy.kind == "sh":
                runtime = Runtime(mode="shell", prefix=[])
                if os.access(strategy_path, os.X_OK):
                    args = [str(strategy_path.resolve())]
                else:
                    args = ["bash", str(strategy_path.resolve())]
            else:
                runtime = self.resolve_runtime()
                if runtime.mode == "wine" and sys.platform.startswith("linux"):
                    raise RuntimeError(
                        "winws.exe requires WinDivert driver and cannot run under Wine on Linux. "
                        "Use .bat on Linux only through built-in Linux backend conversion."
                    )
                game_filter = self.read_game_filter_values()
                args = self.extract_args(strategy_path, runtime, game_filter)

            command = runtime.prefix + args
            self.current_runtime_mode = runtime.mode
            if runtime.mode == "wine":
                self.log("Runtime: wine (Windows build).")
            if runtime.mode == "shell":
                self.log("Runtime: shell script.")
            self.log("Starting command:")
            self.log(" ".join(shlex.quote(part) for part in command))

            env = os.environ.copy()
            if runtime.mode == "wine":
                env.setdefault("WINEDEBUG", "-all")

            self.process = subprocess.Popen(
                command,
                cwd=self.source_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                preexec_fn=os.setsid,
            )

            self.set_status("Connected")
            self.log(f"Connected with {strategy_name}")

            threading.Thread(target=self.read_process_output, daemon=True).start()
            threading.Thread(target=self.watch_process, daemon=True).start()
        except OperationCancelled:
            self.process = None
            self.current_runtime_mode = None
            if strategy.kind == "bat" and sys.platform.startswith("linux"):
                try:
                    self.cancel_requested = False
                    self.stop_linux_backend()
                except Exception:
                    pass
            self.set_status("Idle")
            self.log("Connect cancelled.")
        except Exception as exc:  # pylint: disable=broad-except
            self.process = None
            self.set_status("Error")
            self.log(f"[ERROR] {exc}")
        finally:
            self.is_busy = False
            self.busy_operation = None
            self.cancel_requested = False
            self.root.after(0, self.refresh_action_button)

    def read_process_output(self) -> None:
        proc = self.process
        if proc is None or proc.stdout is None:
            return

        for line in proc.stdout:
            output = line.rstrip()
            if output:
                self.log(output)

    def watch_process(self) -> None:
        proc = self.process
        if proc is None:
            return

        exit_code = proc.wait()
        runtime_mode = self.current_runtime_mode

        def on_exit() -> None:
            if self.process is proc:
                self.process = None
                self.current_runtime_mode = None
                self.set_status("Idle")
                self.log(f"Process exited with code {exit_code}")
                if exit_code == 90 and runtime_mode == "wine" and sys.platform.startswith("linux"):
                    self.log(
                        "[ERROR] WinDivert initialization failed. Windows strategy cannot work via Wine on Linux."
                    )

        self.root.after(0, on_exit)

    def disconnect(self) -> None:
        if self.update_in_progress:
            self.log("Update is in progress. Disconnect is temporarily disabled.")
            return
        if sys.platform.startswith("linux"):
            if self.is_busy:
                if self.busy_operation == "service-start":
                    if not self.cancel_requested:
                        self.set_status("Stopping...")
                        self.log("Stopping current connection operation...")
                        self._request_cancel()
                    self.refresh_action_button()
                    return
                if self.busy_operation == "service-stop":
                    if not self.cancel_requested:
                        self.set_status("Stopping...")
                        self.log("Stopping current stop operation...")
                        self._request_cancel()
                    self.refresh_action_button()
                    return
                self.log("Another operation is already in progress.")
                return

            self.is_busy = True
            self.busy_operation = "service-stop"
            self.cancel_requested = False
            self.set_status("Stopping...")
            self.refresh_action_button()
            threading.Thread(target=self._disconnect_via_systemd_worker, daemon=True).start()
            return

        if self.is_busy and self.busy_operation == "connect":
            if not self.cancel_requested:
                self.set_status("Stopping...")
                self.log("Stopping current connection operation...")
                self._request_cancel()
            self.refresh_action_button()
            return

        proc = self.process
        if proc is None or proc.poll() is not None:
            if self.current_runtime_mode == "linux-zapret":
                try:
                    self.stop_linux_backend()
                    self.log("Disconnected Linux backend.")
                except Exception as exc:  # pylint: disable=broad-except
                    self.log(f"[ERROR] Failed to stop Linux backend: {exc}")
            self.process = None
            self.current_runtime_mode = None
            self.set_status("Idle")
            self.log("No running foreground process.")
            self.refresh_action_button()
            return

        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=3)
        except ProcessLookupError:
            pass
        except Exception as exc:  # pylint: disable=broad-except
            self.log(f"[ERROR] Failed to stop process cleanly: {exc}")
        finally:
            self.process = None
            self.current_runtime_mode = None
            self.set_status("Idle")
            self.log("Disconnected.")
            self.refresh_action_button()

    def _disconnect_via_systemd_worker(self) -> None:
        try:
            self.stop_managed_service()
            self.log("Service stopped.")
        except OperationCancelled:
            self.log("Service stop cancelled.")
        except Exception as exc:  # pylint: disable=broad-except
            self.set_status("Error")
            self.log(f"[ERROR] {exc}")
        finally:
            self.is_busy = False
            self.busy_operation = None
            self.cancel_requested = False
            self.refresh_autostart_state_async()
            self.root.after(0, self.refresh_action_button)

    def parse_update_sources(self) -> tuple[str, str, str]:
        version_url = FALLBACK_VERSION_URL
        release_url = FALLBACK_RELEASE_URL
        download_url = FALLBACK_DOWNLOAD_URL

        service_bat = self.source_dir / "service.bat"
        if not service_bat.exists():
            return version_url, release_url, download_url

        text = service_bat.read_text(encoding="utf-8", errors="ignore")
        patterns = {
            "GITHUB_VERSION_URL": FALLBACK_VERSION_URL,
            "GITHUB_RELEASE_URL": FALLBACK_RELEASE_URL,
            "GITHUB_DOWNLOAD_URL": FALLBACK_DOWNLOAD_URL,
        }
        values = {
            "GITHUB_VERSION_URL": version_url,
            "GITHUB_RELEASE_URL": release_url,
            "GITHUB_DOWNLOAD_URL": download_url,
        }

        for key, default_value in patterns.items():
            match = re.search(rf'set\s+"{key}=(.*?)"', text, flags=re.IGNORECASE)
            values[key] = match.group(1).strip() if match else default_value

        return values["GITHUB_VERSION_URL"], values["GITHUB_RELEASE_URL"], values["GITHUB_DOWNLOAD_URL"]

    def read_local_version(self) -> str:
        local_file = self.source_dir / ".service" / "version.txt"
        if local_file.exists():
            value = local_file.read_text(encoding="utf-8", errors="ignore").strip()
            if value:
                return value

        service_bat = self.source_dir / "service.bat"
        if service_bat.exists():
            text = service_bat.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "unknown"

    def check_updates_async(self) -> None:
        threading.Thread(target=self.check_updates, daemon=True).start()

    @staticmethod
    def build_release_archive_url(version: str) -> str:
        clean = version.strip()
        if not clean:
            return ""
        return (
            "https://github.com/Flowseal/zapret-discord-youtube/releases/download/"
            f"{clean}/zapret-discord-youtube-{clean}.zip"
        )

    @staticmethod
    def _source_score(path: Path) -> int:
        score = 0
        if (path / "service.bat").is_file():
            score += 8
        if (path / "bin").is_dir():
            score += 4
        if (path / "lists").is_dir():
            score += 4
        if any(path.glob("general*.bat")):
            score += 2
        if any(path.glob("general*.sh")):
            score += 1
        return score

    @staticmethod
    def _is_within_dir(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

    def _download_update_archive(self, url: str, target: Path) -> None:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "zapret-ubuntu-gui/1.0",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=45) as response, target.open("wb") as handle:
            shutil.copyfileobj(response, handle)

    def _extract_update_archive(self, archive_path: Path, extract_dir: Path) -> None:
        extract_root = extract_dir.resolve()
        with zipfile.ZipFile(archive_path, "r") as zip_file:
            for member in zip_file.infolist():
                member_target = (extract_dir / member.filename).resolve()
                if member_target != extract_root and extract_root not in member_target.parents:
                    raise RuntimeError("Update archive contains invalid paths.")
            zip_file.extractall(extract_dir)

    def _find_extracted_source_dir(self, extract_dir: Path) -> Path:
        best_path: Path | None = None
        best_score = -1
        for path in [extract_dir, *extract_dir.rglob("*")]:
            if not path.is_dir():
                continue
            score = self._source_score(path)
            if score > best_score:
                best_path = path
                best_score = score
        if best_path is None or best_score <= 0:
            raise RuntimeError("Cannot find zapret-discord payload inside downloaded archive.")
        return best_path

    def _backup_user_overrides(self) -> dict[Path, bytes]:
        overrides = (
            Path("lists/ipset-exclude-user.txt"),
            Path("lists/list-exclude-user.txt"),
            Path("lists/list-general-user.txt"),
            Path("utils/check_updates.enabled"),
            Path("utils/game_filter.enabled"),
        )
        backup: dict[Path, bytes] = {}
        for relative in overrides:
            target = self.source_dir / relative
            if target.is_file():
                backup[relative] = target.read_bytes()
        return backup

    def _restore_user_overrides(self, backup: dict[Path, bytes]) -> None:
        for relative, data in backup.items():
            target = self.source_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def _replace_source_tree(self, source_payload_dir: Path) -> None:
        source_root = self.source_dir.resolve()
        if source_root == self.app_dir.resolve():
            raise RuntimeError("Refusing to replace source tree: source directory points to application root.")
        if not self._is_within_dir(source_root, self.app_dir):
            raise RuntimeError("Refusing to replace source tree outside application directory.")
        if not source_payload_dir.is_dir():
            raise RuntimeError(f"Invalid extracted source directory: {source_payload_dir}")

        user_backup = self._backup_user_overrides()
        self.source_dir.mkdir(parents=True, exist_ok=True)

        for item in self.source_dir.iterdir():
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink(missing_ok=True)

        for item in source_payload_dir.iterdir():
            destination = self.source_dir / item.name
            if item.is_dir() and not item.is_symlink():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)

        self._restore_user_overrides(user_backup)

    def _update_worker(self, archive_url: str, target_version: str) -> None:
        work_dir: Path | None = None
        try:
            if sys.platform.startswith("linux"):
                self.log("Stopping current service before update...")
                self.stop_managed_service()
                self.log("Service stopped. Starting update...")
            else:
                self.log("Starting update...")

            self.linux_root.mkdir(parents=True, exist_ok=True)
            work_dir = Path(tempfile.mkdtemp(prefix="update-", dir=str(self.linux_root)))
            archive_path = work_dir / "release.zip"
            extract_dir = work_dir / "extract"
            extract_dir.mkdir(parents=True, exist_ok=True)

            self.log(f"Downloading update archive: {archive_url}")
            self._download_update_archive(archive_url, archive_path)
            self.log(f"Downloaded archive to: {archive_path}")

            self.log("Extracting archive...")
            self._extract_update_archive(archive_path, extract_dir)
            payload_dir = self._find_extracted_source_dir(extract_dir)
            self.log(f"Found source payload in: {payload_dir}")

            self.log(f"Replacing source directory: {self.source_dir}")
            self._replace_source_tree(payload_dir)

            self.local_version = self.read_local_version()
            self.log(f"Update complete: now at version {self.local_version} (target {target_version}).")
            self.set_status("Idle")
        except Exception as exc:  # pylint: disable=broad-except
            self.set_status("Error")
            self.log(f"[ERROR] Update failed: {exc}")
        finally:
            if work_dir is not None:
                try:
                    shutil.rmtree(work_dir)
                except OSError:
                    pass

            def _finish() -> None:
                self.update_in_progress = False
                self.is_busy = False
                self.busy_operation = None
                self.cancel_requested = False
                self.stop_update_animation()
                self.set_strategy_selector_enabled(True)
                self.set_autostart_check_enabled(True)
                self.set_update_button_enabled(True)
                self._apply_update_button_visibility(self.update_available)
                self.refresh_strategies(quiet=True)
                self.refresh_autostart_state_async()
                self.check_updates_async()
                self.refresh_action_button()

            self.root.after(0, _finish)

    def start_update(self) -> None:
        if self.update_in_progress:
            self.log("Update is already in progress.")
            return
        if self.is_busy:
            self.log("Cannot start update while another operation is in progress.")
            return
        if not self.update_available:
            self.log("Current version is already up to date.")
            return
        archive_url = self.update_archive_url.strip()
        if not archive_url:
            self.log("Update archive URL is not available.")
            return

        self.update_in_progress = True
        self.update_available = False
        self.is_busy = True
        self.busy_operation = "update"
        self.cancel_requested = False
        self.set_status("Updating...")
        self.set_strategy_selector_enabled(False)
        self.set_autostart_check_enabled(False)
        self.set_update_button_enabled(False)
        self._apply_update_button_visibility(False)
        self.start_update_animation()
        self.refresh_action_button()
        self.log(f"Starting update to {self.latest_version or 'new version'}...")
        threading.Thread(
            target=self._update_worker,
            args=(archive_url, self.latest_version),
            daemon=True,
        ).start()

    def check_updates(self) -> None:
        flag = self.source_dir / "utils" / "check_updates.enabled"
        if not flag.exists():
            self.set_version_badge(f"v{self.local_version} · auto-check off")
            self.set_update_available_state(available=False, release_page_url=FALLBACK_DOWNLOAD_URL)
            return

        version_url, release_url, download_url = self.parse_update_sources()
        self.release_page_url = download_url
        local_version = self.read_local_version()
        self.local_version = local_version

        req = urllib.request.Request(
            version_url,
            headers={
                "User-Agent": "zapret-ubuntu-gui/1.0",
                "Cache-Control": "no-cache",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=6) as response:
                latest_version = response.read().decode("utf-8", errors="replace").strip()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.set_version_badge(f"v{local_version} · check failed")
            self.set_update_available_state(available=False, release_page_url=download_url)
            self.log(f"Update check failed: {exc}")
            return

        if not latest_version:
            self.set_version_badge(f"v{local_version} · check failed")
            self.set_update_available_state(available=False, release_page_url=download_url)
            return

        release_page = f"{release_url}{latest_version}" if release_url else download_url

        if latest_version == local_version:
            self.set_version_badge(f"v{local_version} \u2713")
            self.set_update_available_state(
                available=False,
                latest_version=latest_version,
                archive_url="",
                release_page_url=release_page,
            )
            return

        archive_url = self.build_release_archive_url(latest_version)
        self.set_update_available_state(
            available=True,
            latest_version=latest_version,
            archive_url=archive_url,
            release_page_url=release_page,
        )
        self.set_version_badge(f"v{local_version} \u2192 v{latest_version}")
        self.log(f"New version available: {latest_version}")
        self.log(f"Release page: {release_page}")
        self.log(f"Update archive: {archive_url}")

    def open_release_page(self) -> None:
        if not self.release_page_url:
            self.log("Release URL is not available.")
            return
        url = self.release_page_url
        opened = False

        if os.geteuid() == 0:
            opened = self._open_url_as_desktop_user(url)
            if not opened:
                self.log("Failed to open release page via desktop user context, trying default browser fallback...")

        if not opened:
            try:
                opened = webbrowser.open(url)
            except Exception:
                opened = False

        if opened:
            self.log(f"Opened: {url}")
            return

        self.log(f"Could not open browser automatically. Open manually: {url}")

    def _open_url_as_desktop_user(self, url: str) -> bool:
        user = self.determine_ws_user()
        if not user or user == "root":
            return False

        xdg_open = shutil.which("xdg-open")
        sudo_bin = shutil.which("sudo")
        if xdg_open is None or sudo_bin is None:
            return False

        try:
            pw_record = pwd.getpwnam(user)
        except KeyError:
            return False

        uid = pw_record.pw_uid
        home = pw_record.pw_dir
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")

        env_args = [f"HOME={home}", f"XDG_RUNTIME_DIR={runtime_dir}"]
        for name in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS"):
            value = os.environ.get(name, "").strip()
            if value:
                env_args.append(f"{name}={value}")

        bus_path = Path(runtime_dir) / "bus"
        has_bus_var = any(item.startswith("DBUS_SESSION_BUS_ADDRESS=") for item in env_args)
        if not has_bus_var and bus_path.exists():
            env_args.append(f"DBUS_SESSION_BUS_ADDRESS=unix:path={bus_path}")

        command = [sudo_bin, "-u", user, "--", "env", *env_args, xdg_open, url]
        try:
            subprocess.Popen(
                command,
                cwd=self.app_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception:
            return False

    def on_close(self) -> None:
        if self.tray_available and not self.is_exiting:
            self.hide_window_to_tray()
            return
        self.exit_application()


def main() -> None:
    root = Tk(className=APP_WM_CLASS)
    app = ZapretGuiApp(root=root, app_dir=Path(__file__).resolve().parent)
    app.log(f"Source directory: {app.source_dir}")
    app.log(f"Launcher started. Log file: {app.log_file}")
    root.mainloop()


if __name__ == "__main__":
    main()
