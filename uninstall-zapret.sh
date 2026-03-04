#!/usr/bin/env bash
set -euo pipefail

APP_NAME="zapret-for-ubuntu"
SERVICE_NAME="zapret-discord-autostart.service"
SELF_PATH="$(readlink -f "$0" 2>/dev/null || realpath "$0")"
APP_DIR="$(cd "$(dirname "$SELF_PATH")" && pwd)"
ASSUME_YES=0

for arg in "$@"; do
  if [ "$arg" = "--yes" ]; then
    ASSUME_YES=1
  fi
done

log() {
  printf '[UNINSTALL] %s\n' "$*"
}

resolve_ws_user() {
  if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
    printf '%s' "${SUDO_USER}"
    return
  fi

  if [ -n "${PKEXEC_UID:-}" ] && [ "${PKEXEC_UID}" != "0" ]; then
    getent passwd "${PKEXEC_UID}" | cut -d: -f1 || true
    return
  fi

  printf ''
}

resolve_ws_home() {
  local ws_user
  ws_user="$(resolve_ws_user)"
  if [ -z "$ws_user" ]; then
    printf ''
    return
  fi
  getent passwd "$ws_user" | cut -d: -f6 || true
}

ensure_root() {
  if [ "$(id -u)" -eq 0 ]; then
    return
  fi

  if command -v pkexec >/dev/null 2>&1; then
    exec pkexec "$SELF_PATH" "$@"
  fi
  if command -v sudo >/dev/null 2>&1; then
    exec sudo "$SELF_PATH" "$@"
  fi

  echo "Root privileges are required (pkexec/sudo not found)." >&2
  exit 1
}

confirm_if_needed() {
  local ws_home
  ws_home="$(resolve_ws_home)"
  local sources_hint="${APP_DIR}/zapret-discord"
  if [ -n "$ws_home" ]; then
    sources_hint="${ws_home}/.local/share/${APP_NAME}/zapret-discord"
  fi

  if [ "$ASSUME_YES" -eq 1 ]; then
    return
  fi
  printf "This will remove systemd service, '%s' and package '%s'. Continue? [y/N]: " "$sources_hint" "$APP_NAME"
  read -r answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *) echo "Cancelled."; exit 0 ;;
  esac
}

cleanup_systemd_service() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return
  fi

  log "Stopping/disabling systemd service ${SERVICE_NAME}..."
  systemctl stop "${SERVICE_NAME}" >/dev/null 2>&1 || true
  systemctl disable "${SERVICE_NAME}" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}" || true
  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl reset-failed >/dev/null 2>&1 || true
}

cleanup_user_desktop_entries() {
  local ws_user=""
  ws_user="$(resolve_ws_user)"

  if [ -z "$ws_user" ]; then
    return
  fi

  local home_dir
  home_dir="$(getent passwd "$ws_user" | cut -d: -f6 || true)"
  if [ -z "$home_dir" ]; then
    return
  fi

  rm -f "${home_dir}/.local/share/applications/zapret-gui.desktop" || true
  rm -f "${home_dir}/.local/share/icons/hicolor/256x256/apps/zapret-gui.png" || true
}

cleanup_local_dirs() {
  local ws_home=""
  ws_home="$(resolve_ws_home)"

  if [ -n "$ws_home" ]; then
    if [ -d "${ws_home}/.local/share/${APP_NAME}/zapret-discord" ]; then
      log "Removing ${ws_home}/.local/share/${APP_NAME}/zapret-discord ..."
      rm -rf "${ws_home}/.local/share/${APP_NAME}/zapret-discord"
    fi
    if [ -d "${ws_home}/.local/state/${APP_NAME}" ]; then
      log "Removing ${ws_home}/.local/state/${APP_NAME} ..."
      rm -rf "${ws_home}/.local/state/${APP_NAME}"
    fi
  fi

  if [ -d "${APP_DIR}/zapret-discord" ]; then
    log "Removing ${APP_DIR}/zapret-discord ..."
    rm -rf "${APP_DIR}/zapret-discord"
  fi
  if [ -d "${APP_DIR}/.linux-backend" ]; then
    log "Removing ${APP_DIR}/.linux-backend ..."
    rm -rf "${APP_DIR}/.linux-backend"
  fi
}

purge_installed_package_if_present() {
  if dpkg-query -W -f='${Status}' "${APP_NAME}" 2>/dev/null | grep -q "install ok installed"; then
    log "Purging package ${APP_NAME} ..."
    dpkg --purge "${APP_NAME}" || true
  fi

  rm -f "/usr/bin/${APP_NAME}" || true

  case "${APP_DIR}" in
    "/opt/${APP_NAME}"|"/opt/${APP_NAME}/"*)
      log "Removing ${APP_DIR} ..."
      rm -rf "${APP_DIR}" || true
      ;;
  esac
}

main() {
  ensure_root "$@"
  confirm_if_needed

  cleanup_systemd_service
  cleanup_user_desktop_entries
  cleanup_local_dirs
  purge_installed_package_if_present

  log "Done."
}

main "$@"
