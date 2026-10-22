"""Colour codes: parse what a person types (hex, rgb(), hsl()) into ``#rrggbb``.

Used by the accent setting, which takes a preset name or any colour code. A custom accent also
needs a variant for the dark theme: the same hue, lifted towards white so it reads on dark.
"""

import colorsys
import re

_HEX = re.compile(r"^#?([0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$")
_FUNC = re.compile(r"^(rgba?|hsla?)\(\s*([^)]*)\)$")
_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)"
_PART = re.compile(rf"^({_NUM})(%|deg)?$")


def parse_color(text: str) -> str | None:
    """``"#F97316"``, ``"f73"``, ``"rgb(249 115 22)"``, ``"hsl(25, 95%, 53%)"`` -> ``"#f97316"``.

    Alpha is accepted and ignored (an accent is always opaque). ``None`` if it is not a colour.
    """
    s = text.strip().lower()
    m = _HEX.match(s)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h[:3])
        return "#" + h[:6]
    m = _FUNC.match(s)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2).strip()) if p]
    if len(parts) not in (3, 4):
        return None
    parsed = [_PART.match(p) for p in parts[:3]]
    if not all(parsed):
        return None
    values = [(float(p.group(1)), p.group(2) or "") for p in parsed if p]
    if m.group(1).startswith("rgb"):
        rgb = [v * 2.55 if unit == "%" else v for v, unit in values]
        if any(not 0 <= c <= 255 for c in rgb):
            return None
        return _hex(*(round(c) for c in rgb))
    (hue, _u), (sat, su), (light, lu) = values
    if su != "%" or lu != "%" or not (0 <= sat <= 100 and 0 <= light <= 100):
        return None
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360, light / 100, sat / 100)
    return _hex(round(r * 255), round(g * 255), round(b * 255))


def lighten(color: str, amount: float = 0.35) -> str:
    """``color`` (``#rrggbb``) mixed ``amount`` of the way towards white."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return _hex(*(round(c + (255 - c) * amount) for c in (r, g, b)))


def _hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"
