# Ubuntu GUI launcher

`zapret_gui.py` is a GUI launcher for Ubuntu with strategy selection and `Connect`/`Disconnect`.

## What it does

- detects strategies dynamically:
  - `general (ALT*).bat`
  - `general*.sh`
- checks project updates on startup (same source URLs as `service.bat`);
- on Linux, `.bat` strategies are automatically converted to Linux `nfqws` config and run **without Wine**;
- on first `.bat` launch, automatically clones/updates official Linux backend (`bol-van/zapret`) and builds binaries.
- main window is minimal: one large `Connect/Disconnect` action button + strategy dropdown + footer controls.

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

## Notes

- If `utils/check_updates.enabled` is missing, startup update check is skipped.
- Strategy and update sources are read dynamically each start, so replacing project files with newer versions is supported.
- Keep project path without spaces for robust shell option parsing.
