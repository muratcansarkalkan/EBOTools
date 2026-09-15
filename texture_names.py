"""Shared NBA Live TextureName / AssetName validation.

EBO AssetName is a string-pool reference and is not restricted to four
characters. NBA Live 06 stadium assets include names such as taud1..taud4.

The native ShpF writer in this addon also supports the game's NUL-terminated
directory-name form, while retaining compatibility with ordinary 4-char names.
"""

from __future__ import annotations

_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')
MAX_TEXTURE_NAME_BYTES = 63


class TextureNameError(ValueError):
    pass


def validate_texture_name(name: str) -> str:
    name = str(name).strip()
    if not name:
        raise TextureNameError("TextureName cannot be empty.")
    try:
        encoded = name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise TextureNameError(
            f"TextureName {name!r} must currently be ASCII."
        ) from exc
    if b"\0" in encoded:
        raise TextureNameError("TextureName cannot contain NUL.")
    if len(encoded) > MAX_TEXTURE_NAME_BYTES:
        raise TextureNameError(
            f"TextureName {name!r} is {len(encoded)} bytes; "
            f"maximum supported length is {MAX_TEXTURE_NAME_BYTES}."
        )
    if any(ch in name for ch in _WINDOWS_FORBIDDEN):
        raise TextureNameError(
            f"TextureName {name!r} contains unsupported filename characters."
        )
    return name
