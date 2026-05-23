#!/usr/bin/env python3
"""System tray indicator for battery-manager.

Reads state from the daemon's files (state.json, config.toml) and sysfs,
displays current capacity + phase, and provides a Settings dialog for
adjusting low/high thresholds and toggling the daemon on/off.

Service control (start/stop/restart) requires a polkit rule to allow
the current user to manage battery-manager.service without a password
prompt; installed by install.sh.
"""
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gtk, GLib, AyatanaAppIndicator3 as AppIndicator3

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.toml"
STATE_FILE = HERE / "state.json"
ICONS_DIR = HERE / "icons"
SERVICE_NAME = "battery-manager.service"
POLL_MS = 2000
APP_ID = "battery-manager-tray"


def detect_battery() -> str:
    base = Path("/sys/class/power_supply")
    for bat in sorted(base.glob("BAT*")):
        if (bat / "charge_control_end_threshold").exists():
            return bat.name
    return ""


def load_config() -> dict:
    cfg = {"low": 20, "high": 80, "battery": ""}
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            cfg.update(tomllib.load(f))
    if not cfg.get("battery"):
        cfg["battery"] = detect_battery()
    return cfg


def update_config_file(updates: dict) -> None:
    text = CONFIG_FILE.read_text()
    for key, val in updates.items():
        if isinstance(val, bool):
            new = f"{key} = {str(val).lower()}"
        elif isinstance(val, str):
            new = f'{key} = "{val}"'
        else:
            new = f"{key} = {val}"
        text, n = re.subn(
            rf"^{re.escape(key)}\s*=.*$",
            new,
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if n == 0:
            text = text.rstrip() + f"\n{new}\n"
    CONFIG_FILE.write_text(text)


def is_service_active() -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", SERVICE_NAME],
        capture_output=True, text=True,
    )
    return r.stdout.strip() == "active"


def systemctl(action: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", action, SERVICE_NAME],
        capture_output=True, text=True, timeout=15,
    )


def read_state() -> dict:
    cfg = load_config()
    battery = cfg.get("battery") or detect_battery()
    battery_dir = Path("/sys/class/power_supply") / battery if battery else None

    state = {
        "low": cfg.get("low", 20),
        "high": cfg.get("high", 80),
        "drain_delta": cfg.get("drain_delta", 10),
        "phase": "unknown",
        "capacity": None,
        "threshold": None,
        "status": None,
        "enabled": is_service_active(),
    }
    if STATE_FILE.exists():
        try:
            state["phase"] = json.loads(STATE_FILE.read_text()).get(
                "phase", "unknown"
            )
        except Exception:
            pass
    if battery_dir is not None:
        try:
            state["capacity"] = int((battery_dir / "capacity").read_text().strip())
            state["threshold"] = int(
                (battery_dir / "charge_control_end_threshold").read_text().strip()
            )
            state["status"] = (battery_dir / "status").read_text().strip()
        except Exception:
            pass
    return state


def battery_icon(state: dict) -> str:
    """Pick a tray icon that conveys the current state at a glance.

    For "Not charging" (AC connected but daemon holding the threshold)
    we ship a custom icon — battery + pause badge — because the
    standard battery-level-N-plugged-in-symbolic looks too much like
    charging at small sizes. For other states the standard
    freedesktop battery-level-N icons are used."""
    cap = state.get("capacity")
    if cap is None:
        return "battery-missing-symbolic"
    status = state.get("status", "")
    level = max(0, min(100, round(cap / 10) * 10))
    if status == "Full":
        return "battery-level-100-charged-symbolic"
    if status == "Charging":
        return f"battery-level-{level}-charging-symbolic"
    if status == "Not charging":
        return f"battery-manager-holding-{level}-symbolic"
    return f"battery-level-{level}-symbolic"


def status_text(state: dict) -> str:
    """Plain-English summary of what the daemon is doing right now —
    no jargon ("phase", "threshold"); written to be understandable
    without reading docs or running commands."""
    if not state.get("enabled"):
        return (
            "Battery manager disabled\n"
            "Laptop will charge normally up to 100%."
        )
    cap = state.get("capacity")
    if cap is None:
        return "Battery not detected"
    status = state.get("status", "")
    low, high = state["low"], state["high"]

    if status == "Charging":
        return (
            f"Battery {cap}%  —  charging\n"
            f"Plugged in. Will stop at {high}%, then\n"
            f"hold until it drops to {low}%."
        )
    if status == "Not charging":
        return (
            f"Battery {cap}%  —  plugged in, not charging\n"
            f"Holding between {low}% and {high}%.\n"
            f"Will recharge when it drops to {low}%."
        )
    if status == "Discharging":
        return (
            f"Battery {cap}%  —  on battery\n"
            f"Plug in to cycle between {low}% and {high}%."
        )
    if status == "Full":
        return f"Battery {cap}%  —  full"
    return f"Battery {cap}%  —  {status}"


class TrayApp:
    def __init__(self) -> None:
        self.indicator = AppIndicator3.Indicator.new(
            APP_ID,
            "battery-level-80-symbolic",
            AppIndicator3.IndicatorCategory.HARDWARE,
        )
        if ICONS_DIR.is_dir():
            # Tells GTK to look here for our custom holding icons in
            # addition to the system theme.
            self.indicator.set_icon_theme_path(str(ICONS_DIR))
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self._build_menu()
        self.refresh()
        GLib.timeout_add(POLL_MS, self.refresh)

    def _build_menu(self) -> None:
        self.menu = Gtk.Menu()

        self.status_item = Gtk.MenuItem(label="(loading…)")
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        self.toggle_item = Gtk.CheckMenuItem(label="Enabled")
        self.toggle_handler = self.toggle_item.connect("toggled", self.on_toggle)
        self.menu.append(self.toggle_item)

        settings_item = Gtk.MenuItem(label="Settings…")
        settings_item.connect("activate", self.on_settings)
        self.menu.append(settings_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit tray")
        quit_item.connect("activate", lambda _: Gtk.main_quit())
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def refresh(self) -> bool:
        s = read_state()

        label = f"{s['capacity']}%" if s["capacity"] is not None else "?"
        self.indicator.set_label(label, "100%")
        self.indicator.set_icon_full(battery_icon(s), "battery")

        self.status_item.set_label(status_text(s))

        self.toggle_item.handler_block(self.toggle_handler)
        self.toggle_item.set_active(s["enabled"])
        self.toggle_item.handler_unblock(self.toggle_handler)

        return True

    def on_toggle(self, item: Gtk.CheckMenuItem) -> None:
        if item.get_active():
            systemctl("start")
        else:
            systemctl("stop")
        GLib.timeout_add(500, self._refresh_once)

    def _refresh_once(self) -> bool:
        self.refresh()
        return False

    def on_settings(self, _item) -> None:
        s = read_state()
        dlg = Gtk.Dialog(title="Battery manager settings", modal=True)
        dlg.add_buttons(
            "Cancel", Gtk.ResponseType.CANCEL,
            "Apply", Gtk.ResponseType.OK,
        )
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_margin_top(14)
        box.set_margin_bottom(14)
        box.set_margin_start(18)
        box.set_margin_end(18)

        low_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        low_row.pack_start(Gtk.Label(label="Low threshold:", xalign=0), True, True, 0)
        low_spin = Gtk.SpinButton.new_with_range(1, 99, 1)
        low_spin.set_value(s["low"])
        low_row.pack_start(low_spin, False, False, 0)
        box.add(low_row)

        high_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        high_row.pack_start(Gtk.Label(label="High threshold:", xalign=0), True, True, 0)
        high_spin = Gtk.SpinButton.new_with_range(2, 100, 1)
        high_spin.set_value(s["high"])
        high_row.pack_start(high_spin, False, False, 0)
        box.add(high_row)

        enabled_check = Gtk.CheckButton(label="Daemon enabled")
        enabled_check.set_active(s["enabled"])
        box.add(enabled_check)

        dlg.show_all()
        response = dlg.run()
        if response == Gtk.ResponseType.OK:
            low = int(low_spin.get_value())
            high = int(high_spin.get_value())
            want_enabled = enabled_check.get_active()
            if low >= high:
                self._error("Low threshold must be less than high threshold.")
            else:
                update_config_file({"low": low, "high": high})
                if want_enabled:
                    systemctl("restart" if s["enabled"] else "start")
                elif s["enabled"]:
                    systemctl("stop")
        dlg.destroy()
        self.refresh()

    def _error(self, msg: str) -> None:
        d = Gtk.MessageDialog(
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg,
        )
        d.run()
        d.destroy()


def main() -> int:
    TrayApp()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
