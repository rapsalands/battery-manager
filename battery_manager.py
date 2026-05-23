#!/usr/bin/env python3
"""Battery charge cycle manager for ASUS laptops.

The ASUS WMI firmware on this hardware does not honor every value
written to charge_control_end_threshold:

  - If threshold is at or just below current capacity, firmware respects
    it (charging stops).
  - If threshold is far below current capacity (roughly >30 points
    delta), firmware silently ignores it and keeps charging.
  - Firmware can also reset the threshold (e.g., on AC events).

So we cannot just write threshold=LOW and expect charging to stop while
the battery is high. Instead:

  - Maintain a persistent phase ("drain" or "charge") in state.json.
  - In drain phase, dynamically write threshold = capacity - drain_delta
    (clamped to LOW), so the firmware always sees a value it respects.
    As capacity falls, threshold falls with it.
  - In charge phase, write threshold = HIGH.
  - Re-assert every poll so firmware resets are corrected within seconds.
  - Switch drain -> charge when capacity hits LOW.
  - Switch charge -> drain when capacity hits HIGH.
"""
import json
import logging
import subprocess
import sys
import time
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG_FILE = HERE / "config.toml"
STATE_FILE = HERE / "state.json"

DEFAULTS = {
    "low": 20,
    "high": 80,
    "poll_seconds": 20,
    "battery": "",  # empty = auto-detect
    "notify_user": "",
    "drain_delta": 10,
}


def detect_battery() -> str:
    base = Path("/sys/class/power_supply")
    for bat in sorted(base.glob("BAT*")):
        if (bat / "charge_control_end_threshold").exists():
            return bat.name
    raise RuntimeError(
        "no battery exposing charge_control_end_threshold found under "
        "/sys/class/power_supply/; set 'battery' in config.toml manually"
    )

PHASE_DRAIN = "drain"
PHASE_CHARGE = "charge"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("battery-manager")


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            cfg.update(tomllib.load(f))
    if not (0 < cfg["low"] < cfg["high"] <= 100):
        raise ValueError(
            f"invalid thresholds: low={cfg['low']} high={cfg['high']}"
        )
    if cfg["drain_delta"] < 1:
        raise ValueError(f"drain_delta must be >= 1, got {cfg['drain_delta']}")
    return cfg


def load_phase(capacity: int, low: int, high: int) -> str:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if data.get("phase") in (PHASE_DRAIN, PHASE_CHARGE):
                return data["phase"]
            log.warning(
                "state file present but phase missing/invalid (%r); "
                "falling back to default", data,
            )
        except Exception:
            log.exception("could not read state file; falling back to default")
    else:
        log.warning("state file missing; falling back to default phase")
    # Safer default: at or above HIGH we're clearly in drain phase;
    # at or below LOW we're clearly in charge phase; in between, default
    # to DRAIN rather than CHARGE so a lost state file doesn't silently
    # cause unexpected charging.
    if capacity >= high:
        return PHASE_DRAIN
    if capacity <= low:
        return PHASE_CHARGE
    return PHASE_DRAIN


def save_phase(phase: str) -> None:
    # Atomic: write to a temp file then rename, so a kill mid-write
    # cannot leave a zero-byte state file behind.
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps({"phase": phase}) + "\n")
    tmp.replace(STATE_FILE)


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


def compute_target(phase: str, capacity: int, cfg: dict) -> int:
    if phase == PHASE_CHARGE:
        return cfg["high"]
    return max(cfg["low"], capacity - cfg["drain_delta"])


def next_phase(phase: str, capacity: int, cfg: dict) -> str:
    if phase == PHASE_DRAIN and capacity <= cfg["low"]:
        return PHASE_CHARGE
    if phase == PHASE_CHARGE and capacity >= cfg["high"]:
        return PHASE_DRAIN
    return phase


def tick(paths: dict, cfg: dict, state: dict) -> None:
    capacity = read_int(paths["capacity"])
    threshold = read_int(paths["threshold"])
    status = read_str(paths["status"])

    np = next_phase(state["phase"], capacity, cfg)
    if np != state["phase"]:
        log.info("phase %s -> %s (cap=%d%%)", state["phase"], np, capacity)
        state["phase"] = np
        save_phase(np)
        if np == PHASE_DRAIN:
            notify(
                cfg["notify_user"],
                f"Battery at {capacity}% — holding",
                f"Reached {cfg['high']}%. Charging paused; will resume at {cfg['low']}%.",
                icon="battery-full",
            )
        else:
            notify(
                cfg["notify_user"],
                f"Battery at {capacity}% — charging",
                f"Dropped to {cfg['low']}%. Charging back up to {cfg['high']}%.",
                icon="battery-low",
            )

    target = compute_target(state["phase"], capacity, cfg)
    if target != threshold:
        paths["threshold"].write_text(f"{target}\n")
        log.info(
            "cap=%d%% status=%s phase=%s threshold %d -> %d",
            capacity, status, state["phase"], threshold, target,
        )


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
    phase = load_phase(capacity, cfg["low"], cfg["high"])
    save_phase(phase)
    state = {"phase": phase}

    log.info(
        "starting: battery=%s low=%d high=%d delta=%d poll=%ds "
        "phase=%s cap=%d%% threshold=%d",
        cfg["battery"], cfg["low"], cfg["high"], cfg["drain_delta"],
        cfg["poll_seconds"], phase, capacity, threshold,
    )
    notify(
        cfg["notify_user"],
        "Battery manager running",
        f"phase={phase}  cap={capacity}%  threshold={threshold}%  "
        f"low={cfg['low']}  high={cfg['high']}",
        icon="battery",
    )

    while True:
        try:
            tick(paths, cfg, state)
        except Exception:
            log.exception("tick failed")
        time.sleep(cfg["poll_seconds"])


if __name__ == "__main__":
    sys.exit(main())
