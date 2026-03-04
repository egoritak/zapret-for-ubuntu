# Ubuntu GUI launcher

`zapret_gui.py` is a GUI launcher for Ubuntu with strategy selection and `Connect`/`Disconnect`.
Launcher logic and zapret-discord sources are now separated.

## Directory layout

- launcher/app files:
  - `zapret_gui.py`
  - `run-ubuntu-gui.sh`
  - `.linux-backend/`
  - `icons/zapret.ico`
- replaceable zapret-discord sources:
  - `zapret-discord/`
  - (`bin/`, `lists/`, `utils/`, `.service/`, `service.bat`, `general*.bat`, `general*.sh`)

To update source files, replace contents of `zapret-discord/` only.

## What it does

- detects strategies dynamically:
  - `general (ALT*).bat`
  - `general*.sh`
- checks project updates on startup (same source URLs as `service.bat`);
- on Linux, `.bat` strategies are automatically converted to Linux `nfqws` config and run **without Wine**;
- on startup, launcher ensures managed systemd service exists (creates/updates it when missing);
- `Connect/Disconnect` controls managed systemd service state (`start`/`stop`);
- `Autostart` checkbox controls service boot autostart (`enable`/`disable`);
- when a newer version is detected, update button (`⟳`) appears near version badge;
- update button downloads release zip and replaces `zapret-discord/` automatically;
- on first `.bat` service preparation, launcher clones/updates official Linux backend (`bol-van/zapret`) and builds binaries.
- main window is minimal: one large `Connect/Disconnect` action button + strategy dropdown + footer controls.
- app can stay in system tray with `Show Zapret`, `Connect/Disconnect`, `Exit`.
- if old flat layout is detected, launcher auto-migrates known source files into `zapret-discord/`.

## Run

```bash
./run-ubuntu-gui.sh
```

or

```bash
python3 ./zapret_gui.py
```

At first `Connect` for `.bat`, build can take a few minutes.
You will be asked for administrator privileges (`pkexec` or `sudo`) to apply firewall/NFQUEUE rules.

## Dependencies

- `python3`
- `python3-tk`
- `python3-pil` (recommended for proper icon conversion/rendering)
- `python3-gi` + Gtk3 introspection (`gir1.2-gtk-3.0`) for tray icon/menu
- `git`
- `make`
- `gcc`
- netfilter development/runtime packages required by `nfqws` build and run
- `pkexec` or `sudo` (root privileges are required to apply firewall/NFQUEUE rules)

## How Linux `.bat` conversion works

When you press `Connect` on `general (ALT*).bat` in Ubuntu:

1. launcher extracts `winws` args from selected `.bat`;
2. converts `--wf-tcp/--wf-udp` to `NFQWS_PORTS_TCP/UDP`;
3. writes generated Linux config to:
   - `.linux-backend/state/config.generated`
4. installs/updates managed systemd unit:
   - `/etc/systemd/system/zapret-discord-autostart.service`
5. starts service with:
   - `systemctl start zapret-discord-autostart.service`

Generated config uses your current username as `WS_USER`, so `nfqws` can read lists/binary payloads
inside your home directory.

The backend repository is stored at:

- `.linux-backend/zapret`

## Logs

- launcher writes logs to:
  - `.linux-backend/logs/launcher.log`
- use `Logs` button to open built-in log viewer.

## Update Button

- update button appears only when local version is outdated;
- archive URL pattern:
  - `https://github.com/Flowseal/zapret-discord-youtube/releases/download/{VERSION}/zapret-discord-youtube-{VERSION}.zip`
- during update:
  - active service is stopped;
  - `Connect/Disconnect` action is blocked;
  - main circle button shows `Updating` with spinner;
  - source files in `zapret-discord/` are replaced from downloaded archive;
  - user override files are preserved:
    - `lists/ipset-exclude-user.txt`
    - `lists/list-exclude-user.txt`
    - `lists/list-general-user.txt`
    - `utils/check_updates.enabled`
    - `utils/game_filter.enabled`

## UI state

- selected alternative is remembered between launches in:
  - `.linux-backend/state/selected_strategy.txt`

## Systemd Autostart

- `Autostart` checkbox controls system service boot enable state:
  - `zapret-discord-autostart.service`
- when enabled, launcher:
  - generates config for currently selected `.bat` alternative
  - installs/updates systemd unit in `/etc/systemd/system/`
  - runs `systemctl enable zapret-discord-autostart.service`
- when disabled, launcher runs:
  - `systemctl disable zapret-discord-autostart.service`
- checkbox state is synced from `systemctl is-enabled` on startup.
- connection state (button `Connect/Disconnect`) is synced from `systemctl is-active` on startup.

## Tray behavior

- app uses `icons/zapret.ico` as window/tray icon;
- closing the main window hides app to tray;
- tray menu has:
  - `Show Zapret`
  - `Connect`/`Disconnect`
  - `Exit`

## Menu entry

- launcher auto-creates desktop entry in user menu:
  - `~/.local/share/applications/zapret-gui.desktop`
- icon is installed to:
  - `~/.local/share/icons/hicolor/256x256/apps/zapret-gui.png`

## Notes

- If `zapret-discord/utils/check_updates.enabled` is missing, startup update check is skipped.
- Strategy and update sources are read dynamically each start, so replacing project files with newer versions is supported.
- Keep project path without spaces for robust shell option parsing.
