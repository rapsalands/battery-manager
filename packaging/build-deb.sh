#!/usr/bin/env bash
# Build a .deb package for battery-manager.
# Usage: ./packaging/build-deb.sh
# Output: build/battery-manager_<version>_all.deb
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG=packaging
VERSION="$(awk -F': ' '/^Version:/{print $2}' "$DIR/$PKG/control")"
STAGE="$DIR/build/battery-manager_${VERSION}_all"
OUT="$DIR/build/battery-manager_${VERSION}_all.deb"

command -v dpkg-deb >/dev/null || {
    echo "ERROR: dpkg-deb not found; install with: sudo apt install dpkg" >&2
    exit 1
}

echo "Staging $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$STAGE/opt/battery-manager"

# Project files (templates and code) installed under /opt/battery-manager/.
# Templates (.service, .polkit.rules, -tray.desktop) are kept with their
# original names; postinst renders them into /etc/... at install time.
install -m 644 \
    "$DIR/battery_manager.py" \
    "$DIR/battery_tray.py" \
    "$DIR/config.toml" \
    "$DIR/battery-manager.service" \
    "$DIR/battery-manager.polkit.rules" \
    "$DIR/battery-manager-tray.desktop" \
    "$DIR/LICENSE" \
    "$DIR/README.md" \
    "$STAGE/opt/battery-manager/"

chmod 755 "$STAGE/opt/battery-manager/battery_manager.py"
chmod 755 "$STAGE/opt/battery-manager/battery_tray.py"

# DEBIAN control files
install -m 644 "$DIR/$PKG/control"   "$STAGE/DEBIAN/control"
install -m 644 "$DIR/$PKG/conffiles" "$STAGE/DEBIAN/conffiles"
install -m 755 "$DIR/$PKG/postinst"  "$STAGE/DEBIAN/postinst"
install -m 755 "$DIR/$PKG/prerm"     "$STAGE/DEBIAN/prerm"
install -m 755 "$DIR/$PKG/postrm"    "$STAGE/DEBIAN/postrm"

# Source install runs Python from a venv; the .deb has no venv (deps come
# from apt-installed python3-gi etc.). Rewrite the service + autostart
# templates to use system python3 instead.
sed -i 's|__DIR__/venv/bin/python|/usr/bin/python3|' \
    "$STAGE/opt/battery-manager/battery-manager.service"
sed -i 's|__DIR__/venv/bin/python|/usr/bin/python3|' \
    "$STAGE/opt/battery-manager/battery-manager-tray.desktop"

dpkg-deb --build --root-owner-group "$STAGE" "$OUT"
echo
echo "Built: $OUT"
echo "Inspect with: dpkg-deb -c $OUT"
echo "Install with: sudo apt install $OUT"
