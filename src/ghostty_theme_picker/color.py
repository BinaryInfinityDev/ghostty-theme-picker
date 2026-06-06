"""Color parsing and terminal color emission.

This module knows how to turn the hex colors found in Ghostty theme files into
RGB triples, reason about them (perceived lightness, WCAG contrast), and emit
the ANSI escape sequences needed to paint them in a terminal.

It supports two output modes:

* ``truecolor`` -- 24-bit ``38;2;r;g;b`` / ``48;2;r;g;b`` sequences. This is
  what Ghostty (and most modern terminals) understand and is the most faithful
  reproduction of a theme.
* ``256`` -- a fallback that maps each color to the nearest xterm-256 palette
  entry, for terminals that do not advertise truecolor support.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
ITALIC = "\x1b[3m"

# Matches any ANSI escape sequence so we can measure the *visible* width of a
# styled string.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


@dataclass(frozen=True)
class RGB:
    """A 24-bit color."""

    r: int
    g: int
    b: int

    def __post_init__(self) -> None:
        for value in (self.r, self.g, self.b):
            if not 0 <= value <= 255:
                raise ValueError(f"color channel out of range: {value}")

    @property
    def hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def blend(self, other: "RGB", t: float) -> "RGB":
        """Linearly interpolate towards ``other``. ``t`` in [0, 1]."""
        t = max(0.0, min(1.0, t))
        return RGB(
            round(self.r + (other.r - self.r) * t),
            round(self.g + (other.g - self.g) * t),
            round(self.b + (other.b - self.b) * t),
        )


def parse_color(value: str) -> RGB | None:
    """Parse a color as written in a Ghostty theme file.

    Accepts ``#rrggbb``, ``rrggbb``, ``#rgb``, ``rgb`` and the X11
    ``rgb:rr/gg/bb`` form. Returns ``None`` for anything unrecognized so that
    parsing a theme never crashes on a stray value.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None

    # X11 style: rgb:rr/gg/bb (each component 1-4 hex digits, we take MSBs)
    if text.lower().startswith("rgb:"):
        parts = text[4:].split("/")
        if len(parts) == 3:
            try:
                channels = []
                for part in parts:
                    part = part.strip()
                    if not part:
                        return None
                    # Scale to 8 bits regardless of how many hex digits given.
                    scaled = int(part, 16) / ((1 << (4 * len(part))) - 1)
                    channels.append(round(scaled * 255))
                return RGB(*channels)
            except ValueError:
                return None
        return None

    text = text.lstrip("#").strip()
    if len(text) == 3 and all(c in "0123456789abcdefABCDEF" for c in text):
        text = "".join(c * 2 for c in text)
    if len(text) != 6 or any(c not in "0123456789abcdefABCDEF" for c in text):
        return None
    try:
        return RGB(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _linear_channel(value: int) -> float:
    c = value / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: RGB) -> float:
    """WCAG relative luminance in [0, 1]."""
    return (
        0.2126 * _linear_channel(color.r)
        + 0.7152 * _linear_channel(color.g)
        + 0.0722 * _linear_channel(color.b)
    )


def contrast_ratio(a: RGB, b: RGB) -> float:
    """WCAG contrast ratio between two colors (1.0 .. 21.0)."""
    la, lb = relative_luminance(a), relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def perceived_brightness(color: RGB) -> float:
    """Perceived brightness in [0, 1] using the classic ITU-R weighting.

    This tracks human perception of "is this light or dark" better than raw
    luminance for the purpose of classifying a background.
    """
    return (0.299 * color.r + 0.587 * color.g + 0.114 * color.b) / 255.0


def is_light(color: RGB) -> bool:
    return perceived_brightness(color) > 0.5


def best_text_on(background: RGB) -> RGB:
    """Pick black or white text for maximum legibility on ``background``."""
    return RGB(0, 0, 0) if perceived_brightness(background) > 0.55 else RGB(255, 255, 255)


# --- xterm-256 nearest-color mapping (for the non-truecolor fallback) --------

_CUBE_STEPS = (0, 95, 135, 175, 215, 255)


def _nearest_cube_index(value: int) -> int:
    best_i, best_d = 0, 1 << 30
    for i, step in enumerate(_CUBE_STEPS):
        d = abs(step - value)
        if d < best_d:
            best_i, best_d = i, d
    return best_i


def to_xterm256(color: RGB) -> int:
    """Map a 24-bit color to the closest xterm-256 palette index."""
    ri, gi, bi = (
        _nearest_cube_index(color.r),
        _nearest_cube_index(color.g),
        _nearest_cube_index(color.b),
    )
    cube = RGB(_CUBE_STEPS[ri], _CUBE_STEPS[gi], _CUBE_STEPS[bi])
    cube_index = 16 + 36 * ri + 6 * gi + bi

    # Grayscale ramp 232..255 maps to gray levels 8, 18, ... 238.
    gray_avg = round((color.r + color.g + color.b) / 3)
    gray_i = max(0, min(23, round((gray_avg - 8) / 10)))
    gray_level = 8 + 10 * gray_i
    gray = RGB(gray_level, gray_level, gray_level)
    gray_index = 232 + gray_i

    if _dist(color, cube) <= _dist(color, gray):
        return cube_index
    return gray_index


def _dist(a: RGB, b: RGB) -> int:
    return (a.r - b.r) ** 2 + (a.g - b.g) ** 2 + (a.b - b.b) ** 2


def visible_width(text: str) -> int:
    """Number of visible columns in ``text`` (escape sequences excluded).

    Assumes the previews use only single-width characters, which they do.
    """
    return len(_ANSI_RE.sub("", text))


def detect_color_mode(env: dict[str, str] | None = None) -> str:
    """Return ``"truecolor"`` or ``"256"`` based on the environment."""
    env = os.environ if env is None else env
    colorterm = env.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return "truecolor"
    term = env.get("TERM", "").lower()
    if "ghostty" in term or "truecolor" in term or "direct" in term:
        return "truecolor"
    return "256"


class Painter:
    """Emits foreground/background escape sequences in the chosen color mode."""

    def __init__(self, mode: str = "truecolor"):
        if mode not in ("truecolor", "256"):
            raise ValueError(f"unknown color mode: {mode}")
        self.mode = mode

    def fg(self, color: RGB) -> str:
        if self.mode == "truecolor":
            return f"\x1b[38;2;{color.r};{color.g};{color.b}m"
        return f"\x1b[38;5;{to_xterm256(color)}m"

    def bg(self, color: RGB) -> str:
        if self.mode == "truecolor":
            return f"\x1b[48;2;{color.r};{color.g};{color.b}m"
        return f"\x1b[48;5;{to_xterm256(color)}m"

    @staticmethod
    def reset() -> str:
        return RESET
