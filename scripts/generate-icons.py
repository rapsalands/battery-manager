#!/usr/bin/env python3
"""Regenerate the custom 'holding' tray icons.

The tray uses these for the "AC plugged in but daemon is holding charge"
state, since the standard battery-level-N-plugged-in-symbolic icons look
indistinguishable from charging at a glance.

Design: vertical battery silhouette + fill bar proportional to capacity
+ a small outlined-circle pause badge in the bottom-right corner. All
shapes use currentColor so GTK paints them with the theme color.

Run with: ./scripts/generate-icons.py
"""
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "icons"
ICONS.mkdir(exist_ok=True)


def svg(cap: int) -> str:
    fill_h = round(11 * cap / 100, 2)
    fill_y = round(14 - fill_h, 2)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
  <!-- battery cap -->
  <rect x="5.5" y="0.5" width="3" height="1.5" rx="0.3"/>
  <!-- battery body outline -->
  <rect x="2" y="2" width="10" height="13" rx="1.4" fill="none" stroke="currentColor" stroke-width="1"/>
  <!-- fill proportional to capacity ({cap}%) -->
  <rect x="3" y="{fill_y}" width="8" height="{fill_h}" rx="0.4"/>
  <!-- pause badge bottom-right: outlined circle + two bars -->
  <circle cx="12.5" cy="12.5" r="3" fill="none" stroke="currentColor" stroke-width="1"/>
  <rect x="11.1" y="10.8" width="0.9" height="3.4" rx="0.25" fill="currentColor"/>
  <rect x="13.0" y="10.8" width="0.9" height="3.4" rx="0.25" fill="currentColor"/>
</svg>
'''


def main() -> None:
    for cap in range(0, 101, 10):
        out = ICONS / f"battery-manager-holding-{cap}-symbolic.svg"
        out.write_text(svg(cap))
        print(f"wrote {out.name}")


if __name__ == "__main__":
    main()
