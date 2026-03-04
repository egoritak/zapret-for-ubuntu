#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

run_gui() {
  exec /usr/bin/python3 ./zapret_gui.py "$@"
}

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  run_gui "$@"
fi

if command -v pkexec >/dev/null 2>&1; then
  exec pkexec env \
    DISPLAY="${DISPLAY:-}" \
    XAUTHORITY="${XAUTHORITY:-}" \
    WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-}" \
    XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-}" \
    DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-}" \
    /usr/bin/python3 "$(pwd)/zapret_gui.py" "$@"
fi

exec sudo -E /usr/bin/python3 "$(pwd)/zapret_gui.py" "$@"
