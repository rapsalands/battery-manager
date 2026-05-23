#!/usr/bin/env python3
"""Regenerate the tray icons.

Four state icons:
  charging      — green   filled battery + white lightning bolt
  holding       — orange  filled battery + white pause bars (at cap,
                          plugged in, daemon intentionally not charging)
  discharging-N — blue    outlined battery with proportional inner fill
                          showing actual capacity (N = 0..100, step 10)
  disabled      — gray    outlined battery + red X (daemon stopped)

Charging and holding are solid-color silhouettes — they're transient
or at-the-cap states where the percentage is less informative; the
text label next to the icon shows actual capacity. Discharging gets
per-capacity variants because when you're running on battery the
exact level genuinely matters.

Run: ./scripts/generate-icons.py
"""
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "icons"
ICONS.mkdir(exist_ok=True)


def cap_body(color: str, filled: bool) -> str:
    """Battery cap rect + body shape, either solid-filled or outlined."""
    cap = f'  <rect x="6" y="0.5" width="4" height="1.5" rx="0.3" fill="{color}"/>\n'
    if filled:
        body = f'  <rect x="3.5" y="2" width="9" height="13" rx="1.3" fill="{color}"/>\n'
    else:
        body = (
            f'  <rect x="3.5" y="2" width="9" height="13" rx="1.3" '
            f'fill="none" stroke="{color}" stroke-width="1.3"/>\n'
        )
    return cap + body


# Solid-color icons (no per-capacity variants).

CHARGING = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#43a047", filled=True)}  <path d="M 9 4 L 5.5 9 L 7.5 9 L 7 13 L 10.5 8 L 8.5 8 Z" fill="white"/>
</svg>
'''

HOLDING = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#ef6c00", filled=True)}  <rect x="4.5" y="5.7" width="7" height="1.8" rx="0.4" fill="white"/>
  <rect x="4.5" y="9.0" width="7" height="1.8" rx="0.4" fill="white"/>
</svg>
'''

DISABLED = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#9e9e9e", filled=False)}  <path d="M 4.5 4.5 L 11.5 14" stroke="#e53935" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M 11.5 4.5 L 4.5 14" stroke="#e53935" stroke-width="1.8" stroke-linecap="round"/>
</svg>
'''


def discharging(capacity: int) -> str:
    """Blue outlined battery with proportional inner fill."""
    # Interior fill area: y=3.5 to y=13.5 (h=10), x=4.5 to x=11.5 (w=7)
    fill_h = round(10 * capacity / 100, 2)
    fill_y = round(13.5 - fill_h, 2)
    inner = ""
    if capacity > 0:
        inner = (
            f'  <rect x="4.5" y="{fill_y}" width="7" height="{fill_h}" '
            f'rx="0.3" fill="#42a5f5"/>\n'
        )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">\n'
        f'{cap_body("#1976d2", filled=False)}{inner}'
        f'</svg>\n'
    )


SOLID_ICONS = {
    "battery-manager-charging.svg": CHARGING,
    "battery-manager-holding.svg": HOLDING,
    "battery-manager-disabled.svg": DISABLED,
}


def main() -> None:
    # Clean any old per-cap holding icons from prior design.
    for old in ICONS.glob("battery-manager-holding-*-symbolic.svg"):
        old.unlink()
        print(f"removed {old.name}")
    # Wipe old discharging files so renames/removals are reflected.
    for old in ICONS.glob("battery-manager-discharging*.svg"):
        old.unlink()
    for name, content in SOLID_ICONS.items():
        out = ICONS / name
        out.write_text(content)
        print(f"wrote {out.name}")
    for cap in range(0, 101, 10):
        out = ICONS / f"battery-manager-discharging-{cap}.svg"
        out.write_text(discharging(cap))
        print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
