#!/usr/bin/env python3
"""Battery charge cap manager for ASUS laptops.

Maintains charge_control_end_threshold = high so the battery charges
up to `high` percent when plugged in and is held there. When you
unplug and use the laptop, the battery drains normally; plug back in
and it charges back up to `high`. Industry-standard battery-health
behavior (asusctl -c, TLP, Apple Optimized Charging, Lenovo Vantage
all do the same thing). Holding at 80% is much gentler than 100%; the
remaining gains from going lower aren't worth giving up usable juice.

The daemon re-asserts the threshold on every poll so firmware resets
(e.g., on AC plug/unplug events) are corrected within seconds, and
sends desktop notifications on state transitions (charging started /
reached cap / now on battery).
"""
import logging
import subprocess
import sys
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.toml"

DEFAULTS = {
    "high": 80,
    "poll_seconds": 30,
    "battery": "",       # empty = auto-detect
    "notify_user": "",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("battery-manager")


def detect_battery() -> str:
    base = Path("/sys/class/power_supply")
    for bat in sorted(base.glob("BAT*")):
        if (bat / "charge_control_end_threshold").exists():
            return bat.name
    raise RuntimeError(
        "no battery exposing charge_control_end_threshold found under "
        "/sys/class/power_supply/; set 'battery' in config.toml manually"
    )


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            user_cfg = tomllib.load(f)
        # Only accept keys we know about; ignore legacy keys (low,
        # drain_delta) from previous designs so old config files don't
        # error out.
        for k in DEFAULTS:
            if k in user_cfg:
                cfg[k] = user_cfg[k]
    if not (0 < cfg["high"] <= 100):
        raise ValueError(f"invalid high threshold: {cfg['high']}")
    return cfg


def read_int(path: Path) -> int:
    return int(path.read_text().strip())


def read_str(path: Path) -> str:
    return path.read_text().strip()


def notify(user: str, title: str, body: str, icon: str = "battery") -> None:
    if not user:
        return
    try:
        uid = subprocess.check_output(["id", "-u", user], text=True).strip()
        subprocess.run(
            [
                "runuser", "-u", user, "--",
                "env", f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                "notify-send",
                "--app-name=battery-manager",
                f"--icon={icon}",
                title, body,
            ],
            check=False,
            timeout=5,
            capture_output=True,
        )
    except Exception:
        log.debug("notify failed", exc_info=True)


def tick(paths: dict, cfg: dict, last: dict) -> None:
    capacity = read_int(paths["capacity"])
    threshold = read_int(paths["threshold"])
    status = read_str(paths["status"])

    if threshold != cfg["high"]:
        paths["threshold"].write_text(f"{cfg['high']}\n")
        log.info(
            "cap=%d%% status=%s threshold %d -> %d",
            capacity, status, threshold, cfg["high"],
        )

    if status != last["status"]:
        log.info(
            "status %s -> %s (cap=%d%%)", last["status"], status, capacity,
        )
        if status == "Charging" and last["status"] != "Charging":
            notify(
                cfg["notify_user"],
                f"Battery charging to {cfg['high']}%",
                f"At {capacity}%. Will stop at {cfg['high']}%.",
                icon="battery-good-charging",
            )
        elif status == "Not charging" and last["status"] == "Charging":
            notify(
                cfg["notify_user"],
                f"Battery reached cap ({cfg['high']}%)",
                "Plugged in. Charging stopped to preserve battery health.",
                icon="battery-full",
            )
        elif status == "Discharging" and last["status"] != "Discharging":
            notify(
                cfg["notify_user"],
                "On battery",
                f"At {capacity}%. Will recharge to {cfg['high']}% on plug-in.",
                icon="battery-good",
            )
        last["status"] = status


def main() -> int:
    cfg = load_config()
    if not cfg["battery"]:
        cfg["battery"] = detect_battery()
    battery_dir = Path("/sys/class/power_supply") / cfg["battery"]
    paths = {
        "capacity": battery_dir / "capacity",
        "status": battery_dir / "status",
        "threshold": battery_dir / "charge_control_end_threshold",
    }
    for name, p in paths.items():
        if not p.exists():
            log.error("missing sysfs file: %s (%s)", name, p)
            return 1

    capacity = read_int(paths["capacity"])
    threshold = read_int(paths["threshold"])
    status = read_str(paths["status"])

    log.info(
        "starting: battery=%s high=%d poll=%ds cap=%d%% threshold=%d status=%s",
        cfg["battery"], cfg["high"], cfg["poll_seconds"],
        capacity, threshold, status,
    )
    notify(
        cfg["notify_user"],
        "Battery manager running",
        f"Capping charge at {cfg['high']}%. Currently {capacity}% ({status}).",
        icon="battery",
    )

    last = {"status": status}
    while True:
        try:
            tick(paths, cfg, last)
        except Exception:
            log.exception("tick failed")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
