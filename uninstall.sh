#!/usr/bin/env bash
set -euo pipefail

SERVICE_DST="/etc/systemd/system/battery-manager.service"
POLKIT_DST="/etc/polkit-1/rules.d/50-battery-manager.rules"
AUTOSTART_DST="$HOME/.config/autostart/battery-manager-tray.desktop"

detect_battery() {
    for bat in /sys/class/power_supply/BAT*; do
        if [ -e "$bat/charge_control_end_threshold" ]; then
            basename "$bat"
            return 0
        fi
    done
    return 1
}

echo "[1/5] killing tray if running"
pkill -f "battery_tray.py" 2>/dev/null || true

echo "[2/5] removing autostart entry"
rm -f "$AUTOSTART_DST"

echo "[3/5] stopping and disabling daemon"
sudo systemctl disable --now battery-manager.service 2>/dev/null || true

echo "[4/5] removing systemd unit and polkit rule"
sudo rm -f "$SERVICE_DST" "$POLKIT_DST"
sudo systemctl daemon-reload

echo "[5/5] resetting battery threshold to 100"
if BATTERY=$(detect_battery); then
    THRESHOLD_FILE=/sys/class/power_supply/$BATTERY/charge_control_end_threshold
    echo 100 | sudo tee "$THRESHOLD_FILE" > /dev/null
    echo "  reset $BATTERY threshold to 100"
fi

echo
echo "uninstalled. Project folder at $(dirname "$(readlink -f "$0")") left in place."
echo "Delete it manually if you no longer want it."
