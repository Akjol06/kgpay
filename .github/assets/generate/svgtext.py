"""Text -> SVG outline paths (GitHub renders README SVGs as <img>: no web fonts)."""

import math

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTCollection, TTFont

SUP = "/System/Library/Fonts/Supplemental/"
SYS = "/System/Library/Fonts/"


def _load(path, want=None):
    if path.endswith(".ttc"):
        for f in TTCollection(path).fonts:
            if f["name"].getDebugName(4) == want:
                return f
        names = [f["name"].getDebugName(4) for f in TTCollection(path).fonts]
        raise KeyError(f"{want} not in {names}")
    return TTFont(path)


class Face:
    def __init__(self, font):
        self.font = font
        self.gs = font.getGlyphSet()
        self.cmap = font.getBestCmap()
        self.upm = font["head"].unitsPerEm
        self.hmtx = font["hmtx"]

    def width(self, text, size, tracking=0.0):
        s = size / self.upm
        w = 0
        for ch in text:
            g = self.cmap.get(ord(ch))
            w += (self.hmtx[g][0] if g else self.upm * 0.5) * s + tracking
        return w - tracking if text else 0

    def path(self, text, x, y, size, tracking=0.0, anchor="start"):
        """Return the SVG path `d` for text whose baseline starts at (x, y)."""
        if anchor == "middle":
            x -= self.width(text, size, tracking) / 2
        elif anchor == "end":
            x -= self.width(text, size, tracking)
        s = size / self.upm
        pen = SVGPathPen(self.gs)
        cx = x
        for ch in text:
            g = self.cmap.get(ord(ch))
            if g is None:
                cx += self.upm * 0.5 * s + tracking
                continue
            tp = TransformPen(pen, (s, 0, 0, -s, cx, y))
            self.gs[g].draw(tp)
            cx += self.hmtx[g][0] * s + tracking
        return pen.getCommands()


DISPLAY = Face(_load(SUP + "Futura.ttc", "Futura Condensed ExtraBold"))
LABEL = Face(_load(SUP + "DIN Condensed Bold.ttf"))
MONO = Face(_load(SYS + "Menlo.ttc", "Menlo Regular"))
MONO_B = Face(_load(SYS + "Menlo.ttc", "Menlo Bold"))


def t(face, text, x, y, size, fill, tracking=0.0, anchor="start", extra=""):
    d = face.path(text, x, y, size, tracking, anchor)
    return f'<path d="{d}" fill="{fill}"{extra}/>'


def horn(cx, cy, k, color, width, flip=False):
    """Kochkor muyuz (ram's horn): a stem that splits into two inward-curling spirals."""
    sy = -1 if flip else 1

    def spiral(side):
        pts = []
        # start at the stem top, sweep outward and curl back in
        for i in range(0, 61):
            a = i / 60 * 2.45 * math.pi
            r = k * (1.0 - 0.7 * i / 60)
            # centre of the curl sits beside the stem
            ox, oy = side * k * 1.0, -k * 0.15
            px = ox - side * r * math.cos(a)
            py = oy - r * math.sin(a)
            pts.append((cx + px, cy + sy * py))
        return "M" + " L".join(f"{p[0]:.1f},{p[1]:.1f}" for p in pts)

    stem = f"M{cx:.1f},{cy - sy * k * 0.15:.1f} L{cx:.1f},{cy + sy * k * 1.15:.1f}"
    return (
        f'<path d="{spiral(-1)} {spiral(1)} {stem}" fill="none" stroke="{color}" '
        f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>'
    )
