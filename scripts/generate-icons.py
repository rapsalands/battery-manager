#!/usr/bin/env python3
"""Regenerate the tray icons.

Four full-color SVGs (no -symbolic suffix, so GTK does NOT theme-paint
them — they keep these colors on light and dark themes alike):

  charging    — green   filled battery with white lightning bolt
  holding     — orange  filled battery with white pause bars
                        (plugged in but daemon is intentionally not
                        topping up)
  discharging — blue    outlined battery with partial fill
                        (laptop running on battery)
  disabled    — gray    outlined battery with red X
                        (daemon stopped; laptop will charge to 100%)

Capacity is shown as the text label next to the icon (e.g., "69%"),
so we do not encode capacity in the icon itself — keeps it to four
files instead of forty.

Run: ./scripts/generate-icons.py
"""
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "icons"
ICONS.mkdir(exist_ok=True)


def cap_body(color: str, filled: bool, fill_inset: bool = False) -> str:
    """Return SVG for the battery cap + body outline.
    If filled=True the body is a solid color; otherwise outlined."""
    if filled:
        return (
            f'  <rect x="6" y="0.5" width="4" height="1.5" rx="0.3" fill="{color}"/>\n'
            f'  <rect x="3.5" y="2" width="9" height="13" rx="1.3" fill="{color}"/>\n'
        )
    return (
        f'  <rect x="6" y="0.5" width="4" height="1.5" rx="0.3" fill="{color}"/>\n'
        f'  <rect x="3.5" y="2" width="9" height="13" rx="1.3" fill="none" stroke="{color}" stroke-width="1.3"/>\n'
    )


CHARGING = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#43a047", filled=True)}  <path d="M 9 4 L 5.5 9 L 7.5 9 L 7 13 L 10.5 8 L 8.5 8 Z" fill="white"/>
</svg>
'''

HOLDING = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#ef6c00", filled=True)}  <rect x="4.5" y="5.7" width="7" height="1.8" rx="0.4" fill="white"/>
  <rect x="4.5" y="9.0" width="7" height="1.8" rx="0.4" fill="white"/>
</svg>
'''

DISCHARGING = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#1976d2", filled=False)}  <rect x="4.5" y="6.5" width="7" height="7.5" rx="0.4" fill="#42a5f5"/>
</svg>
'''

DISABLED = f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
{cap_body("#9e9e9e", filled=False)}  <path d="M 4.5 4.5 L 11.5 14" stroke="#e53935" stroke-width="1.8" stroke-linecap="round"/>
  <path d="M 11.5 4.5 L 4.5 14" stroke="#e53935" stroke-width="1.8" stroke-linecap="round"/>
</svg>
'''

ICONS_TO_WRITE = {
    "battery-manager-charging.svg": CHARGING,
    "battery-manager-holding.svg": HOLDING,
    "battery-manager-discharging.svg": DISCHARGING,
    "battery-manager-disabled.svg": DISABLED,
}


def main() -> None:
    # Remove any old per-capacity holding icons from prior design
    for old in ICONS.glob("battery-manager-holding-*-symbolic.svg"):
        old.unlink()
        print(f"removed {old.name}")
    for name, content in ICONS_TO_WRITE.items():
        out = ICONS / name
        out.write_text(content)
        print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
