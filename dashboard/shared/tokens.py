"""dashboard/shared/tokens.py — single source of truth for colour tokens.

Pure data (no Streamlit import). Consumed by:
  * design.py        — builds the :root CSS custom properties
  * chart_helpers.py — PLOT_COLORS / diverging_colors
  * table_styles.py  — Styler cell colours (glide-data-grid can't resolve var())
  * pages            — via these modules, never raw hex
"""
from __future__ import annotations

COLORS: dict[str, str] = {
    # Surfaces
    "ground":    "#0a0a0a",
    "surface":   "#131316",
    "sunken":    "#0e0e10",
    "rail":      "#0a0a0c",
    # Ink
    "ink":       "#edeef0",
    "ink-mid":   "#c8cad0",
    "dim":       "#8b8d93",
    "faint":     "#55575e",
    # Signal
    "bull":      "#16c784",
    "bear":      "#ff4d4d",
    "amber":     "#f2a93b",
    # Accent
    "accent":    "#ff9500",
    "accent-hi": "#ffb340",
    # Categorical
    "violet":    "#c77dff",
    "azure":     "#5a8fd6",
}


def hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgba(name: str, alpha: float) -> str:
    """`rgba(r,g,b,a)` string for a named token."""
    r, g, b = hex_to_rgb(COLORS[name])
    return f"rgba({r},{g},{b},{alpha})"


def css_vars(indent: str = "      ") -> str:
    """`--name: #hex;` lines for a :root block."""
    return "\n".join(f"{indent}--{k}: {v};" for k, v in COLORS.items())


def mix(a: str, b: str, t: float) -> str:
    """Opaque `#rrggbb` blend of tokens `a` -> `b` at fraction t (0 = a, 1 = b).

    Opaque (not alpha) so text drawn with it stays legible on any surface,
    including Styler cells in the glide-data-grid canvas.
    """
    ra, ga, ba = hex_to_rgb(COLORS[a])
    rb, gb, bb = hex_to_rgb(COLORS[b])
    t = max(0.0, min(1.0, t))
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in ((ra, rb), (ga, gb), (ba, bb)))


def ordinal_ramp(n: int, stops: tuple[str, ...] = ("bull", "amber", "bear")) -> list[str]:
    """`n` evenly spaced opaque shades along the token stops (best -> worst).

    Default bull -> amber -> bear. n=5 gives bull / bull-soft / amber /
    bear-soft / bear; n=6 gives six distinct ordinal steps (TQS grades).
    """
    if n < 2:
        return [COLORS[stops[0]]] * max(n, 0)
    segs = len(stops) - 1
    out = []
    for i in range(n):
        pos = i / (n - 1) * segs
        k = min(int(pos), segs - 1)
        out.append(mix(stops[k], stops[k + 1], pos - k))
    return out
