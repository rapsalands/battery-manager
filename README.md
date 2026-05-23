# battery-manager

A small daemon and GTK tray applet that cycles your laptop battery between
configurable low/high percentages on Linux, working around firmware quirks
on ASUS laptops where the kernel only exposes a single end threshold.

Built and tested on Ubuntu + GNOME + ASUS ProArt P16 H7606WV. Should work on
any ASUS laptop where `/sys/class/power_supply/BAT*/charge_control_end_threshold`
is writable, and on any modern GNOME / KDE / Cinnamon desktop with
AppIndicator support.

<!-- Drop a screenshot at assets/screenshot-tray.png and the image below will render. -->
![tray indicator and settings dialog](assets/screenshot-tray.png)

## Why

Holding a Li-ion battery at 100% for long periods shortens its lifespan.
Most laptops let you cap charging at, say, 80%. ASUS hardware on Linux
exposes only `charge_control_end_threshold` — a single "stop charging at
this percent" knob. That's enough for a simple cap, but if you want
deeper cycling (e.g. drain to 20% before recharging to 80%), the firmware
gets in the way: it silently ignores threshold values that sit too far
below current capacity, and resets the threshold on AC events.

This project works around that with a small persistent daemon that:

  - tracks the current "phase" (drain or charge) in a state file so AC
    plug/unplug events can't confuse it,
  - in drain phase, keeps the threshold a few points below current capacity
    (so the firmware actually respects it) and steps it down as capacity
    falls,
  - in charge phase, sets the threshold to the configured high value,
  - re-asserts the threshold every poll so any firmware reset is corrected
    within seconds.

A separate tray applet shows current state, lets you toggle the daemon on/off
and adjust the low/high thresholds without touching the terminal.

## Features

  - 20/80 (or any) cycling on ASUS hardware that only exposes the end
    threshold
  - Persistent phase across reboots and AC events
  - Desktop notifications on phase changes
  - System tray applet (GTK 3 + AppIndicator):
    - live status (capacity, phase, current threshold, configured range)
    - one-click enable/disable
    - settings dialog for low/high thresholds
  - Polkit rule so the tray can start/stop the service without password
    prompts
  - Autostarts at login
  - Zero Python dependencies beyond stdlib + system GTK bindings

## Requirements

  - Linux with `charge_control_end_threshold` exposed (kernel ≥ 5.4 on
    most ASUS laptops)
  - Python 3.11+ (for `tomllib`)
  - `python3-venv`, `python3-gi`, `gir1.2-gtk-3.0`
  - `gir1.2-ayatanaappindicator3-0.1` (installed automatically by
    `install.sh` on Debian/Ubuntu)
  - A desktop environment that renders AppIndicator tray icons. On
    GNOME, install the
    [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)
    (shipped by default on Ubuntu). To remove the system's own battery
    icon and avoid duplication, the
    [Just Perfection extension](https://extensions.gnome.org/extension/3843/just-perfection/)
    has a toggle for it.

## Install

Two options, pick whichever fits.

### Option A — `.deb` package (recommended for end users)

Download the `.deb` from the latest
[release](https://github.com/rapsalands/battery-manager/releases),
or build it locally with `./packaging/build-deb.sh`. Then:

```sh
sudo apt install ./battery-manager_0.1.0_all.deb
```

apt resolves the GTK / AppIndicator / systemd dependencies for you. The
package installs to `/opt/battery-manager/`, drops a systemd unit, a
polkit rule, and a system-wide autostart entry; the daemon starts
immediately and the tray launches on next login.

To remove:

```sh
sudo apt remove battery-manager       # leaves config in place
sudo apt purge battery-manager        # also removes config and resets threshold
```

### Option B — source install (developers / forkers)

```sh
git clone https://github.com/rapsalands/battery-manager.git
cd battery-manager
./install.sh
```

The installer will:

  1. detect a compatible battery under `/sys/class/power_supply/`
  2. apt-install any missing GTK/AppIndicator typelibs
  3. create a `venv/` with `--system-site-packages` (so the venv sees
     system GTK bindings)
  4. install and start a systemd service at `battery-manager.service`
  5. install a polkit rule allowing your user to control the service
     without a password
  6. install an autostart entry and launch the tray now

It only writes files under the project folder, plus:

  - `/etc/systemd/system/battery-manager.service`
  - `/etc/polkit-1/rules.d/50-battery-manager.rules`
  - `~/.config/autostart/battery-manager-tray.desktop`

## Configuration

Edit `config.toml` and restart the service:

```sh
sudo systemctl restart battery-manager.service
```

Defaults:

```toml
low = 20            # resume charging when battery falls to this percent
high = 80           # stop charging when battery reaches this percent
poll_seconds = 20   # how often the daemon checks state
drain_delta = 10    # threshold gap below capacity during drain phase
battery = ""        # empty = auto-detect; or set e.g. "BAT0"
notify_user = ""    # auto-filled by install.sh; empty disables notifications
```

You can also change low/high from the tray Settings dialog without
editing the file.

## How it works

  - `battery_manager.py` runs as a root systemd service, polls the
    battery, writes `state.json`, and flips
    `charge_control_end_threshold` according to phase.
  - `battery_tray.py` runs as your user, reads `state.json` / sysfs on
    a 2s timer, drives the AppIndicator icon and menu, and writes
    `config.toml` when you Apply changes from the settings dialog.
  - `systemctl start/stop/restart battery-manager.service` from the
    user-level tray is allowed without a password thanks to the polkit
    rule installed by `install.sh`.

```
┌─ system (root) ──────────────┐    ┌─ user ─────────────────────────┐
│  battery_manager.py (daemon) │◀───│  battery_tray.py (GTK)         │
│  reads/writes sysfs          │    │  reads state.json + sysfs      │
│  reads config.toml           │    │  writes config.toml on Apply   │
│  writes state.json           │    │  controls service via polkit   │
└──────────────────────────────┘    └────────────────────────────────┘
```

## Inspect

```sh
systemctl status battery-manager.service
journalctl -u battery-manager.service -f
cat /sys/class/power_supply/BAT*/charge_control_end_threshold
cat state.json
```

## Uninstall

```sh
./uninstall.sh
```

Stops the tray and daemon, removes the systemd unit, polkit rule and
autostart entry, and resets the battery threshold to 100. The project
folder is left in place; delete it manually if you want.

## Caveats

  - Tested only on the ASUS ProArt P16 H7606WV so far. The firmware
    quirk handling (dynamic chase) is designed for ASUS hardware; on
    machines that expose both start and end thresholds the simpler
    approach (set both, done) is better — use TLP or `asusctl` for that.
  - The "20/80 cycling" pattern this tool enables is not the same as the
    conventional advice of "just cap at 80%." Whether deeper cycles are
    actually better for battery life is debated. If you only want the
    cap, use `asusctl -c 80` or TLP; you don't need this project.
  - GNOME does not render AppIndicator tray icons natively; you need
    the AppIndicator extension (default on Ubuntu).

## License

MIT — see [LICENSE](LICENSE).
