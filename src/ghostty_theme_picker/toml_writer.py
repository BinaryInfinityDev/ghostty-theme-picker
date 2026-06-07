"""A tiny TOML serializer.

Python 3.11 ships ``tomllib`` for *reading* TOML but has no writer in the
standard library. We only need to emit a small, well-defined document
(scalars, arrays of scalars, one table, and an array of tables), so a focused
serializer keeps us dependency-free while remaining correct for the values we
produce -- in particular theme names, which can contain spaces, parentheses
and other punctuation.
"""

from __future__ import annotations

_BARE_KEY_CHARS = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def escape_string(value: str) -> str:
    """Encode a string as a TOML basic string (including surrounding quotes)."""
    out = ['"']
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def format_key(key: str) -> str:
    if key and all(c in _BARE_KEY_CHARS for c in key):
        return key
    return escape_string(key)


def format_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Keep it readable and round-trippable.
        return repr(value)
    if isinstance(value, str):
        return escape_string(value)
    raise TypeError(f"unsupported scalar type: {type(value)!r}")


def format_array(values: list) -> str:
    return "[" + ", ".join(format_scalar(v) for v in values) + "]"


def format_keyval(key: str, value: object) -> str:
    if isinstance(value, list):
        return f"{format_key(key)} = {format_array(value)}"
    return f"{format_key(key)} = {format_scalar(value)}"
