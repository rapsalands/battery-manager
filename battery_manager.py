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


def effective_threshold(high: int) -> int:
    """Firmware stops charging slightly before the written threshold
    (battery tops out at ~threshold - 0.5%). Add 1 so the user-visible
    cap of `high` actually shows `high`% on the indicator."""
    return min(100, high + 1)


def write_threshold(paths: dict, target: int, capacity: int, status: str) -> None:
    """Write target to charge_control_end_threshold, with a firmware
    'kick' first if we need charging to resume from a stopped state.

    ASUS firmware latches into a stopped state after hitting a cap,
    and will not resume charging just because we raise the threshold
    above the current capacity. Writing 100 (no cap), waiting for the
    firmware to react and start charging, then writing the real target
    is what actually gets it moving again."""
    if capacity < target and status != "Charging":
        paths["threshold"].write_text("100\n")
        # Wait for firmware to actually start charging before clamping
        # back down to the target. Poll status up to ~3s.
        for _ in range(15):
            time.sleep(0.2)
            if read_str(paths["status"]) == "Charging":
                break
    paths["threshold"].write_text(f"{target}\n")


def tick(paths: dict, cfg: dict, last: dict) -> None:
    capacity = read_int(paths["capacity"])
    threshold = read_int(paths["threshold"])
    status = read_str(paths["status"])
    target = effective_threshold(cfg["high"])

    # Bug observed in the wild: firmware sometimes keeps charging
    # *past* the threshold once a charging session is mid-flight (e.g.
    # plug in at 48%, charge through 80% and keep going to 83%+).
    # The "set threshold below current capacity = stop charging" trick
    # works to halt this. Write threshold ~6 below capacity to force a
    # stop, then restore target on the next iteration.
    if status == "Charging" and capacity > cfg["high"]:
        force_stop = max(40, capacity - 6)
        log.warning(
            "charging past cap: cap=%d%% high=%d%% threshold=%d, "
            "forcing stop with threshold=%d",
            capacity, cfg["high"], threshold, force_stop,
        )
        paths["threshold"].write_text(f"{force_stop}\n")
        time.sleep(1.5)
        # Read back to see if it actually stopped
        new_status = read_str(paths["status"])
        if new_status != "Charging":
            log.info("force-stop worked: status now %s", new_status)
        else:
            log.warning("force-stop did not stop charging; firmware may need a kick")
        # Continue to the normal write below, which restores target=high+1.

    if threshold != target:
        write_threshold(paths, target, capacity, status)
        log.info(
            "cap=%d%% status=%s threshold %d -> %d (cap setting %d%%)",
            capacity, status, threshold, target, cfg["high"],
        )

    if status != last["status"]:
        log.info(
            "status %s -> %s (cap=%d%%)", last["status"], status, capacity,
        )
        # Suppress notifications for the firmware's trickle cycle at
        # the cap (Not-charging -> Charging -> Not-charging every
        # minute or two, with capacity barely moving). Only notify on
        # transitions a user actually cares about:
        #   - real unplug (anything -> Discharging)
        #   - real plug-in (Discharging -> Charging) OR charge starting
        #     from clearly below the cap (>= 5% below)
        #   - charging finished after gaining >= 3% (a real session,
        #     not a 1% top-up)
        if status == "Charging" and last["status"] != "Charging":
            from_discharging = last["status"] == "Discharging"
            clearly_below_cap = capacity <= cfg["high"] - 5
            if from_discharging or clearly_below_cap:
                notify(
                    cfg["notify_user"],
                    f"Battery {capacity}% — charging",
                    f"Plugged in. Will stop at {cfg['high']}%.",
                    icon="battery-good-charging",
                )
            last["charge_start_cap"] = capacity
        elif status == "Not charging" and last["status"] == "Charging":
            start = last.get("charge_start_cap")
            if start is not None and capacity - start >= 3:
                notify(
                    cfg["notify_user"],
                    f"Battery {capacity}% — charging stopped",
                    f"Reached cap (set to {cfg['high']}%). Plugged in; paused to preserve battery health.",
                    icon="battery-full",
                )
            last["charge_start_cap"] = None
        elif status == "Discharging" and last["status"] != "Discharging":
            notify(
                cfg["notify_user"],
                f"Battery {capacity}% — on battery",
                f"Will recharge to {cfg['high']}% on plug-in.",
                icon="battery-good",
            )
            last["charge_start_cap"] = None
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

    # Always assert threshold on startup (with kick if firmware is
    # stopped but should be charging) so a fresh service restart
    # always reaches the configured cap, even if state was already
    # at the target value.
    write_threshold(paths, effective_threshold(cfg["high"]), capacity, status)

    last = {"status": status, "charge_start_cap": None}
    while True:
        try:
            tick(paths, cfg, last)
        except Exception:
            log.exception("tick failed")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
