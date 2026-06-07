"""Low-level terminal control for the interactive picker.

Rather than depend on curses (whose truecolor support is awkward), we drive the
terminal directly with ANSI escapes and read keystrokes from raw-mode stdin.
This gives precise control over 24-bit color rendering, which is the whole
point of the previews.
"""

from __future__ import annotations

import os
import select
import shutil
import sys
import termios
import tty
from dataclasses import dataclass

# Normalized key names returned by ``read_key``.
KEY_LEFT = "LEFT"
KEY_RIGHT = "RIGHT"
KEY_UP = "UP"
KEY_DOWN = "DOWN"
KEY_ENTER = "ENTER"
KEY_ESC = "ESC"
KEY_BACKSPACE = "BACKSPACE"
KEY_CTRL_C = "CTRL_C"
KEY_HOME = "HOME"
KEY_END = "END"
KEY_PGUP = "PGUP"
KEY_PGDN = "PGDN"


@dataclass
class Size:
    cols: int
    rows: int


def get_size() -> Size:
    size = shutil.get_terminal_size(fallback=(80, 24))
    return Size(cols=size.columns, rows=size.lines)


def compose_frame(text: str) -> str:
    """Turn a ``\\n``-separated frame into absolutely-positioned ANSI output.

    Each line is drawn at column 1 of its row (``ESC[row;1H``) after clearing
    that line (``ESC[2K``); a trailing ``ESC[J`` wipes any rows left over from
    a previously taller frame. This is safe in raw mode, where ``\\n`` is a
    bare line feed that does not return the cursor to column 1.
    """
    lines = text.split("\n")
    parts = ["\x1b[H"]
    for i, line in enumerate(lines):
        parts.append(f"\x1b[{i + 1};1H\x1b[2K")
        parts.append(line)
    # Park below the frame and clear anything beneath it.
    parts.append(f"\x1b[{len(lines) + 1};1H\x1b[J")
    return "".join(parts)


class Terminal:
    """Context manager: raw mode + alternate screen + hidden cursor."""

    def __init__(self, in_stream=None, out_stream=None):
        self.in_stream = in_stream or sys.stdin
        self.out_stream = out_stream or sys.stdout
        self.fd = self.in_stream.fileno()
        self._saved = None

    def __enter__(self) -> "Terminal":
        self._saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        # Enter alternate screen, hide cursor, clear.
        self.write("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
        return self

    def __exit__(self, *exc) -> None:
        # Restore cursor, leave alternate screen, reset attributes.
        self.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        self.flush()
        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)

    def write(self, text: str) -> None:
        self.out_stream.write(text)

    def flush(self) -> None:
        self.out_stream.flush()

    def render(self, text: str) -> None:
        """Draw a full frame, positioning each row explicitly.

        Raw mode disables output post-processing (``OPOST``/``ONLCR``), so a
        bare ``\\n`` moves the cursor down *without* returning to column 1 --
        which would cascade the frame diagonally across the screen. We instead
        place every row at column 1 with an absolute cursor move, clear each
        line as we go, and erase anything left below from a taller prior frame.
        Positioning absolutely also discards any pending auto-wrap from a
        full-width line.
        """
        self.write(compose_frame(text))
        self.flush()

    def read_key(self, timeout: float | None = None) -> str | None:
        """Read one normalized keypress. ``None`` on timeout."""
        if timeout is not None:
            ready, _, _ = select.select([self.fd], [], [], timeout)
            if not ready:
                return None
        ch = os.read(self.fd, 1)
        if not ch:
            return None
        byte = ch[0]

        if byte == 0x03:
            return KEY_CTRL_C
        if byte in (0x0D, 0x0A):
            return KEY_ENTER
        if byte in (0x7F, 0x08):
            return KEY_BACKSPACE
        if byte != 0x1B:
            try:
                return ch.decode("utf-8", errors="ignore")
            except Exception:
                return None

        # Escape sequence: peek for more bytes.
        seq = self._read_escape_tail()
        return self._decode_escape(seq)

    def _read_escape_tail(self) -> bytes:
        data = b""
        # Grab whatever immediately follows the ESC (arrow keys, etc.).
        while True:
            ready, _, _ = select.select([self.fd], [], [], 0.02)
            if not ready:
                break
            more = os.read(self.fd, 1)
            if not more:
                break
            data += more
            # CSI sequences terminate on a final byte in the @-~ range.
            if data[:1] == b"[" or data[:1] == b"O":
                if len(data) >= 2 and 0x40 <= data[-1] <= 0x7E and data[-1] != ord("["):
                    break
            else:
                break
        return data

    @staticmethod
    def _decode_escape(seq: bytes) -> str:
        mapping = {
            b"[A": KEY_UP,
            b"[B": KEY_DOWN,
            b"[C": KEY_RIGHT,
            b"[D": KEY_LEFT,
            b"OA": KEY_UP,
            b"OB": KEY_DOWN,
            b"OC": KEY_RIGHT,
            b"OD": KEY_LEFT,
            b"[H": KEY_HOME,
            b"[F": KEY_END,
            b"OH": KEY_HOME,
            b"OF": KEY_END,
            b"[1~": KEY_HOME,
            b"[4~": KEY_END,
            b"[5~": KEY_PGUP,
            b"[6~": KEY_PGDN,
        }
        if seq in mapping:
            return mapping[seq]
        if not seq:
            return KEY_ESC
        return KEY_ESC
