# Ubuntu GUI launcher

`zapret_gui.py` is a GUI launcher for Ubuntu with strategy selection and `Connect`/`Disconnect`.
Launcher logic and zapret-discord sources are now separated.

## Directory layout

- launcher/app files:
  - `zapret_gui.py`
  - `run-ubuntu-gui.sh`
  - `.linux-backend/`
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
- on first `.bat` launch, automatically clones/updates official Linux backend (`bol-van/zapret`) and builds binaries.
- main window is minimal: one large `Connect/Disconnect` action button + strategy dropdown + footer controls.
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
4. starts/restarts Linux zapret service script with this config:
   - `.linux-backend/zapret/init.d/sysv/zapret restart`

Generated config uses your current username as `WS_USER`, so `nfqws` can read lists/binary payloads
inside your home directory.

The backend repository is stored at:

- `.linux-backend/zapret`

## Logs

- launcher writes logs to:
  - `.linux-backend/logs/launcher.log`
- use `Logs` button to open built-in log viewer.

## UI state

- selected alternative is remembered between launches in:
  - `.linux-backend/state/selected_strategy.txt`

## Systemd Autostart

- `Autostart` checkbox controls system service:
  - `zapret-discord-autostart.service`
- when enabled, launcher:
  - generates config for currently selected `.bat` alternative
  - installs/updates systemd unit in `/etc/systemd/system/`
  - runs `systemctl enable --now zapret-discord-autostart.service`
- when disabled, launcher runs:
  - `systemctl disable --now zapret-discord-autostart.service`
- checkbox state is synced from `systemctl is-enabled` on startup.

## Notes

- If `zapret-discord/utils/check_updates.enabled` is missing, startup update check is skipped.
- Strategy and update sources are read dynamically each start, so replacing project files with newer versions is supported.
- Keep project path without spaces for robust shell option parsing.
