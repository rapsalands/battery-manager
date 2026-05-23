#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_NAME="$(whoami)"

SERVICE_SRC="$DIR/battery-manager.service"
SERVICE_DST="/etc/systemd/system/battery-manager.service"
POLKIT_SRC="$DIR/battery-manager.polkit.rules"
POLKIT_DST="/etc/polkit-1/rules.d/50-battery-manager.rules"
AUTOSTART_SRC="$DIR/battery-manager-tray.desktop"
AUTOSTART_DST="$HOME/.config/autostart/battery-manager-tray.desktop"
CONFIG_FILE="$DIR/config.toml"

detect_battery() {
    for bat in /sys/class/power_supply/BAT*; do
        if [ -e "$bat/charge_control_end_threshold" ]; then
            basename "$bat"
            return 0
        fi
    done
    return 1
}

echo "[1/9] detecting compatible battery"
if ! BATTERY=$(detect_battery); then
    echo "  ERROR: no battery exposing charge_control_end_threshold found" >&2
    echo "  This tool requires an ASUS laptop (or other hardware) with kernel" >&2
    echo "  support for charge_control_end_threshold in /sys/class/power_supply/" >&2
    exit 1
fi
THRESHOLD_FILE=/sys/class/power_supply/$BATTERY/charge_control_end_threshold
echo "  found: $BATTERY"

echo "[2/9] checking apt packages"
APT_PKGS="gir1.2-ayatanaappindicator3-0.1 python3-gi gir1.2-gtk-3.0"
NEED=""
for pkg in $APT_PKGS; do
    if ! dpkg -l "$pkg" >/dev/null 2>&1; then
        NEED="$NEED $pkg"
    fi
done
if [ -n "$NEED" ]; then
    echo "  installing:$NEED"
    sudo apt-get update -qq
    sudo apt-get install -y $NEED
else
    echo "  all required apt packages already installed"
fi

echo "[3/9] stopping daemon if running (needed to recreate venv)"
sudo systemctl stop battery-manager.service 2>/dev/null || true

echo "[4/9] (re)creating venv with --system-site-packages"
if [ -d "$DIR/venv" ]; then
    if ! grep -q "include-system-site-packages = true" "$DIR/venv/pyvenv.cfg" 2>/dev/null; then
        echo "  existing venv lacks --system-site-packages; recreating"
        rm -rf "$DIR/venv"
    fi
fi
if [ ! -d "$DIR/venv" ]; then
    python3 -m venv --system-site-packages "$DIR/venv"
fi

echo "[5/9] verifying GTK + AppIndicator bindings importable"
"$DIR/venv/bin/python" -c "
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AyatanaAppIndicator3', '0.1')
from gi.repository import Gtk, AyatanaAppIndicator3
print('  gi bindings ok')
"

echo "[6/9] populating config.toml with this user / battery if blank"
# notify_user
if grep -q '^notify_user = ""' "$CONFIG_FILE"; then
    sed -i "s|^notify_user = \"\"|notify_user = \"$USER_NAME\"|" "$CONFIG_FILE"
    echo "  notify_user -> $USER_NAME"
fi
# battery (left blank means auto-detect at runtime; we don't force-write)

echo "[7/9] sanity check: write to charge_control_end_threshold"
ORIGINAL=$(cat "$THRESHOLD_FILE")
echo "$ORIGINAL" | sudo tee "$THRESHOLD_FILE" > /dev/null
echo "  ok (current value: $ORIGINAL)"

echo "[8/9] installing systemd service + polkit rule"
sed "s|__DIR__|$DIR|g" "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null
sed "s|__SUBJECT_MATCH__|subject.user == \"$USER_NAME\"|g" "$POLKIT_SRC" | sudo tee "$POLKIT_DST" > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now battery-manager.service

echo "[9/9] installing tray autostart and launching it"
mkdir -p "$(dirname "$AUTOSTART_DST")"
sed "s|__DIR__|$DIR|g" "$AUTOSTART_SRC" > "$AUTOSTART_DST"
pkill -f "battery_tray.py" 2>/dev/null || true
sleep 0.3
nohup "$DIR/venv/bin/python" "$DIR/battery_tray.py" >/dev/null 2>&1 &
disown

echo
echo "done. Tray icon should appear in your top panel within a second."
echo "Inspect daemon with:"
echo "  systemctl status battery-manager.service"
echo "  journalctl -u battery-manager.service -f"
