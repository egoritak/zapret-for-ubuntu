#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="zapret-for-ubuntu"
PKG_ROOT="${ROOT_DIR}/dist/pkg"
DIST_DIR="${ROOT_DIR}/dist"
ARCH="${DEB_ARCH:-$(dpkg --print-architecture)}"
VERSION="${DEB_VERSION:-1.0.${GITHUB_RUN_NUMBER:-0}}"
MAINTAINER="${DEB_MAINTAINER:-egoritak <noreply@users.noreply.github.com>}"
DEB_PATH="${DIST_DIR}/${APP_NAME}_${VERSION}_${ARCH}.deb"

rm -rf "${PKG_ROOT}" "${DEB_PATH}"
mkdir -p "${PKG_ROOT}/DEBIAN"
mkdir -p "${PKG_ROOT}/opt/${APP_NAME}"
mkdir -p "${PKG_ROOT}/opt/${APP_NAME}/icons"
mkdir -p "${PKG_ROOT}/opt/${APP_NAME}/zapret-discord"
mkdir -p "${PKG_ROOT}/usr/bin"
mkdir -p "${PKG_ROOT}/usr/share/applications"
mkdir -p "${PKG_ROOT}/usr/share/doc/${APP_NAME}"

install -m 0755 "${ROOT_DIR}/run-ubuntu-gui.sh" "${PKG_ROOT}/opt/${APP_NAME}/run-ubuntu-gui.sh"
install -m 0755 "${ROOT_DIR}/uninstall-zapret.sh" "${PKG_ROOT}/opt/${APP_NAME}/uninstall-zapret.sh"
install -m 0644 "${ROOT_DIR}/zapret_gui.py" "${PKG_ROOT}/opt/${APP_NAME}/zapret_gui.py"
install -m 0644 "${ROOT_DIR}/LICENSE.txt" "${PKG_ROOT}/usr/share/doc/${APP_NAME}/copyright"
install -m 0644 "${ROOT_DIR}/README.md" "${PKG_ROOT}/usr/share/doc/${APP_NAME}/README.md"

if [ -f "${ROOT_DIR}/icons/zapret.ico" ]; then
  install -m 0644 "${ROOT_DIR}/icons/zapret.ico" "${PKG_ROOT}/opt/${APP_NAME}/icons/zapret.ico"
fi

touch "${PKG_ROOT}/opt/${APP_NAME}/zapret-discord/.gitkeep"

cat > "${PKG_ROOT}/usr/bin/${APP_NAME}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
exec /opt/zapret-for-ubuntu/run-ubuntu-gui.sh "$@"
EOF
chmod 0755 "${PKG_ROOT}/usr/bin/${APP_NAME}"

cat > "${PKG_ROOT}/usr/share/applications/${APP_NAME}.desktop" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=Zapret for Ubuntu
Comment=GUI launcher for zapret on Ubuntu
Exec=/usr/bin/${APP_NAME}
Icon=/opt/${APP_NAME}/icons/zapret.ico
Terminal=false
Categories=Network;Utility;
StartupNotify=true
StartupWMClass=ZapretGui
EOF

cat > "${PKG_ROOT}/DEBIAN/control" <<EOF
Package: ${APP_NAME}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: ${ARCH}
Maintainer: ${MAINTAINER}
Depends: python3, python3-tk, python3-pil, python3-gi, gir1.2-gtk-3.0, policykit-1 | sudo, git, make, gcc
Description: Ubuntu GUI launcher for zapret-discord-youtube
 Linux desktop application to manage zapret strategies through a modern GUI.
 Includes systemd-based connect/disconnect control and built-in update flow.
EOF

cat > "${PKG_ROOT}/DEBIAN/postinst" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database /usr/share/applications || true
fi
EOF
chmod 0755 "${PKG_ROOT}/DEBIAN/postinst"

mkdir -p "${DIST_DIR}"
dpkg-deb --build "${PKG_ROOT}" "${DEB_PATH}"
sha256sum "${DEB_PATH}" > "${DEB_PATH}.sha256"

echo "Built package: ${DEB_PATH}"
