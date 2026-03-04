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
import urllib.error
import urllib.request
import webbrowser
import getpass
import pwd
from dataclasses import dataclass
from pathlib import Path
from tkinter import Canvas, StringVar, Tk, Toplevel
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText


FALLBACK_VERSION_URL = (
    "https://raw.githubusercontent.com/Flowseal/"
    "zapret-discord-youtube/main/.service/version.txt"
)
FALLBACK_RELEASE_URL = "https://github.com/Flowseal/zapret-discord-youtube/releases/tag/"
FALLBACK_DOWNLOAD_URL = "https://github.com/Flowseal/zapret-discord-youtube/releases/latest"
LINUX_UPSTREAM_REPO = "https://github.com/bol-van/zapret.git"
LINUX_SYNC_INTERVAL_SEC = 12 * 3600


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
    def __init__(self, root: Tk, base_dir: Path) -> None:
        self.root = root
        self.base_dir = base_dir
        self.process: subprocess.Popen[str] | None = None
        self.current_runtime_mode: str | None = None
        self.is_busy = False
        self.busy_operation: str | None = None
        self.cancel_requested = False
        self.active_command_proc: subprocess.Popen[str] | None = None
        self.strategies_map: dict[str, Strategy] = {}
        self.download_url = FALLBACK_DOWNLOAD_URL
        self.last_selected_strategy: Strategy | None = None

        self.linux_root = self.base_dir / ".linux-backend"
        self.linux_repo_dir = self.linux_root / "zapret"
        self.linux_state_dir = self.linux_root / "state"
        self.linux_sync_stamp = self.linux_root / ".last_sync"
        self.linux_generated_config = self.linux_state_dir / "config.generated"
        self.logs_dir = self.linux_root / "logs"
        self.log_file = self.logs_dir / "launcher.log"

        self.log_window: Toplevel | None = None
        self.log_text: ScrolledText | None = None
        self.log_history: list[str] = []
        self.action_canvas: Canvas | None = None
        self.action_circle_id: int | None = None
        self.action_text_id: int | None = None

        self.strategy_var = StringVar()
        self.status_var = StringVar(value="Idle")
        self.local_version = self.read_local_version()
        self.version_badge_var = StringVar(value=f"v{self.local_version} · checking...")

        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self._setup_style()
        self._build_ui()
        self.refresh_strategies()
        self.ensure_user_lists()
        self.check_updates_async()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_style(self) -> None:
        self.root.title("Zapret")
        self.root.geometry("720x520")
        self.root.minsize(640, 460)

        self.palette = {
            "bg": "#edf2f8",
            "card": "#ffffff",
            "text": "#16253b",
            "muted": "#5d6e8a",
            "accent": "#0f6fff",
            "accent_hover": "#0d61e1",
            "accent_pressed": "#0b52be",
        }
        self.root.configure(bg=self.palette["bg"])

        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("App.TFrame", background=self.palette["bg"])
        style.configure("Card.TFrame", background=self.palette["card"], relief="flat")
        style.configure(
            "Field.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=("Ubuntu", 10),
        )
        style.configure(
            "InfoCaption.TLabel",
            background=self.palette["card"],
            foreground=self.palette["muted"],
            font=("Ubuntu", 9),
        )
        style.configure(
            "InfoValue.TLabel",
            background=self.palette["card"],
            foreground=self.palette["text"],
            font=("Ubuntu", 10, "bold"),
        )

        style.configure(
            "Primary.TButton",
            font=("Ubuntu", 11, "bold"),
            foreground="#ffffff",
            background=self.palette["accent"],
            borderwidth=0,
            focusthickness=0,
            padding=(18, 10),
        )
        style.map(
            "Primary.TButton",
            background=[
                ("pressed", self.palette["accent_pressed"]),
                ("active", self.palette["accent_hover"]),
            ],
        )

        style.configure(
            "Secondary.TButton",
            font=("Ubuntu", 10, "bold"),
            foreground=self.palette["text"],
            background="#dde5f2",
            borderwidth=0,
            focusthickness=0,
            padding=(14, 9),
        )
        style.map(
            "Secondary.TButton",
            background=[
                ("pressed", "#c9d5e9"),
                ("active", "#d2dced"),
            ],
        )

        style.configure(
            "Ghost.TButton",
            font=("Ubuntu", 10),
            foreground=self.palette["text"],
            background=self.palette["card"],
            borderwidth=0,
            focusthickness=0,
            padding=(8, 8),
        )
        style.map(
            "Ghost.TButton",
            foreground=[("active", self.palette["accent"])],
            background=[("active", "#f2f6ff")],
        )

        style.configure(
            "App.TCombobox",
            padding=7,
            arrowsize=16,
            fieldbackground="#f8fbff",
            background="#f8fbff",
            foreground=self.palette["text"],
            selectbackground="#dce9ff",
            selectforeground=self.palette["text"],
            bordercolor="#d6deea",
            lightcolor="#d6deea",
            darkcolor="#d6deea",
            relief="flat",
        )

    def _build_ui(self) -> None:
        app = ttk.Frame(self.root, style="App.TFrame", padding=(18, 16))
        app.pack(fill="both", expand=True)

        card = ttk.Frame(app, style="Card.TFrame", padding=(20, 16))
        card.pack(fill="both", expand=True)

        center = ttk.Frame(card, style="Card.TFrame")
        center.pack(fill="both", expand=True)

        self.action_canvas = Canvas(
            center,
            width=236,
            height=236,
            bg=self.palette["card"],
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.action_canvas.pack(pady=(6, 6))
        self.action_circle_id = self.action_canvas.create_oval(
            10, 10, 226, 226, fill=self.palette["accent"], outline=""
        )
        self.action_text_id = self.action_canvas.create_text(
            118,
            118,
            text="Connect",
            fill="#ffffff",
            font=("Ubuntu", 22, "bold"),
        )
        self.action_canvas.bind("<Button-1>", lambda _event: self.toggle_connection())
        self.action_canvas.bind("<Enter>", lambda _event: self._action_hover(True))
        self.action_canvas.bind("<Leave>", lambda _event: self._action_hover(False))

        ttk.Label(center, textvariable=self.status_var, style="InfoCaption.TLabel").pack(pady=(2, 10))

        chooser = ttk.Frame(card, style="Card.TFrame")
        chooser.pack(fill="x", pady=(4, 0))
        ttk.Label(chooser, text="Alternative", style="Field.TLabel").pack(anchor="w", pady=(0, 6))
        self.strategy_combo = ttk.Combobox(
            chooser,
            textvariable=self.strategy_var,
            style="App.TCombobox",
            state="readonly",
            postcommand=lambda: self.refresh_strategies(quiet=True),
        )
        self.strategy_combo.pack(fill="x")

        footer = ttk.Frame(app, style="Card.TFrame", padding=(14, 10))
        footer.pack(fill="x", pady=(10, 0))

        ttk.Label(footer, textvariable=self.version_badge_var, style="InfoValue.TLabel").pack(side="left")
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
        if self.current_runtime_mode == "linux-zapret":
            return True
        return self.process is not None and self.process.poll() is None

    def refresh_action_button(self) -> None:
        if self.action_canvas is None or self.action_circle_id is None or self.action_text_id is None:
            return

        if not self.strategies_map:
            fill = "#b7c4d8"
            text = "No strategy"
        elif self.is_busy:
            fill = "#f25566"
            text = "Disconnect"
        elif self.is_connected():
            fill = "#f25566"
            text = "Disconnect"
        else:
            fill = self.palette["accent"]
            text = "Connect"

        self.action_canvas.itemconfigure(self.action_circle_id, fill=fill)
        self.action_canvas.itemconfigure(self.action_text_id, text=text)

    def _action_hover(self, is_hover: bool) -> None:
        if (
            not is_hover
            or self.action_canvas is None
            or self.action_circle_id is None
            or self.is_busy
        ):
            self.refresh_action_button()
            return

        if self.is_connected():
            fill = "#ea4659"
        else:
            fill = self.palette["accent_hover"]
        self.action_canvas.itemconfigure(self.action_circle_id, fill=fill)

    def toggle_connection(self) -> None:
        if not self.strategies_map:
            self.log("No strategy available.")
            return
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

    def refresh_strategies(self, quiet: bool = False) -> None:
        found: list[Strategy] = []

        bat_files = [p for p in self.base_dir.glob("general (ALT*).bat") if p.is_file()]
        if not bat_files:
            bat_files = [
                p
                for p in self.base_dir.glob("general*.bat")
                if p.is_file() and p.name.lower() != "service.bat"
            ]
        found.extend(Strategy(name=p.name, path=p, kind="bat") for p in bat_files)

        sh_files = [p for p in self.base_dir.glob("general*.sh") if p.is_file()]
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
            if not quiet:
                self.log("No strategy files found (expected general*.bat or general*.sh).")
            return

        if self.action_canvas is not None:
            self.action_canvas.configure(state="normal")
        current = self.strategy_var.get()
        if current not in strategy_names:
            self.strategy_var.set(strategy_names[0])

        bat_count = sum(1 for item in found if item.kind == "bat")
        sh_count = sum(1 for item in found if item.kind == "sh")
        self.refresh_action_button()
        if not quiet:
            self.log(f"Loaded {len(found)} strategy file(s): .bat={bat_count}, .sh={sh_count}")

    def ensure_user_lists(self) -> None:
        lists_dir = self.base_dir / "lists"
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
        game_flag = self.base_dir / "utils" / "game_filter.enabled"
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
        native_winws = self.base_dir / "bin" / "winws"
        if native_winws.exists() and os.access(native_winws, os.X_OK):
            return Runtime(mode="native", prefix=[str(native_winws)])

        winws_exe = self.base_dir / "bin" / "winws.exe"
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
            "%BIN%": self.to_runtime_path(runtime, self.base_dir / "bin", with_trailing_sep=True),
            "%LISTS%": self.to_runtime_path(runtime, self.base_dir / "lists", with_trailing_sep=True),
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
                    cwd=self.base_dir,
                )
                self.mark_linux_synced()
                need_build = True
            else:
                self.log("Linux backend is fresh enough, skipping git pull.")
        else:
            self.log("Cloning Linux zapret backend (first run)...")
            self.run_logged_command(
                ["git", "clone", "--depth=1", LINUX_UPSTREAM_REPO, str(self.linux_repo_dir)],
                cwd=self.base_dir,
            )
            self.mark_linux_synced()
            need_build = True

        if need_build:
            jobs = max(1, min(os.cpu_count() or 1, 8))
            self.log("Building Linux binaries (nfqws/tpws/ip2net/mdig)...")
            self.run_logged_command(
                ["make", "-C", str(self.linux_repo_dir), f"-j{jobs}"],
                cwd=self.base_dir,
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
            owner_uid = self.base_dir.stat().st_uid
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

    def generate_linux_config_from_bat(self, strategy_path: Path) -> Path:
        runtime = Runtime(mode="native", prefix=[])
        game_filter = self.read_game_filter_values()
        args = self.extract_args(strategy_path, runtime, game_filter)
        tcp_ports, udp_ports, nfq_args = self.split_wf_ports_and_nfqws_args(args)
        nfqws_opt = self.build_nfqws_opt_block(nfq_args)
        ws_user = self.determine_ws_user()

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
        self.linux_generated_config.write_text(config_text, encoding="utf-8")
        return self.linux_generated_config

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
        if " " in str(self.base_dir.resolve()):
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
        self.run_logged_command(command, cwd=self.base_dir, env=env)

    def stop_linux_backend(self) -> None:
        if not self.linux_generated_config.exists():
            self.log("Linux backend config was not generated yet.")
            return
        command, env = self.build_elevated_command("stop")
        self.log("Stopping Linux zapret service...")
        self.run_logged_command(command, cwd=self.base_dir, env=env)

    def connect(self) -> None:
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

    def _connect_worker(self, strategy: Strategy) -> None:
        strategy_name = strategy.name
        strategy_path = strategy.path
        try:
            self.ensure_user_lists()

            if strategy.kind == "bat" and sys.platform.startswith("linux"):
                self.start_linux_from_bat(strategy_path)
                self.process = None
                self.current_runtime_mode = "linux-zapret"
                self.set_status(f"Connected ({strategy_name} via Linux backend)")
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
                cwd=self.base_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=env,
                preexec_fn=os.setsid,
            )

            self.set_status(f"Connected ({strategy_name})")
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

    def parse_update_sources(self) -> tuple[str, str, str]:
        version_url = FALLBACK_VERSION_URL
        release_url = FALLBACK_RELEASE_URL
        download_url = FALLBACK_DOWNLOAD_URL

        service_bat = self.base_dir / "service.bat"
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
        local_file = self.base_dir / ".service" / "version.txt"
        if local_file.exists():
            value = local_file.read_text(encoding="utf-8", errors="ignore").strip()
            if value:
                return value

        service_bat = self.base_dir / "service.bat"
        if service_bat.exists():
            text = service_bat.read_text(encoding="utf-8", errors="ignore")
            match = re.search(r'set\s+"LOCAL_VERSION=([^"]+)"', text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return "unknown"

    def check_updates_async(self) -> None:
        threading.Thread(target=self.check_updates, daemon=True).start()

    def check_updates(self) -> None:
        flag = self.base_dir / "utils" / "check_updates.enabled"
        if not flag.exists():
            self.set_version_badge(f"v{self.local_version} · auto-check off")
            return

        version_url, release_url, download_url = self.parse_update_sources()
        self.download_url = download_url
        local_version = self.read_local_version()

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
            self.log(f"Update check failed: {exc}")
            return

        if not latest_version:
            self.set_version_badge(f"v{local_version} · check failed")
            return

        if latest_version == local_version:
            self.set_version_badge(f"v{local_version} \u2713")
            return

        self.download_url = f"{release_url}{latest_version}" if release_url else download_url
        self.set_version_badge(f"v{local_version} \u2192 v{latest_version}")
        self.log(f"New version available: {latest_version}")
        self.log(f"Release page: {self.download_url}")

    def open_release_page(self) -> None:
        if not self.download_url:
            self.log("Release URL is not available.")
            return
        webbrowser.open(self.download_url)
        self.log(f"Opened: {self.download_url}")

    def on_close(self) -> None:
        self.disconnect()
        self.root.destroy()


def main() -> None:
    root = Tk()
    app = ZapretGuiApp(root=root, base_dir=Path(__file__).resolve().parent)
    app.log(f"Launcher started. Log file: {app.log_file}")
    root.mainloop()


if __name__ == "__main__":
    main()
