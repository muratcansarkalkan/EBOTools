"""Native FSH directory inspection, extraction, and repacking helpers."""

from __future__ import annotations

from dataclasses import dataclass
import binascii
from pathlib import Path
import re
import shutil
import struct
import zlib


class FshError(ValueError):
    """An FSH archive operation could not be processed safely."""


@dataclass(frozen=True)
class FshEntry:
    name: str
    offset: int
    size: int
    width: int
    height: int
    format_code: int
    flags: int
    occurrence: int


@dataclass(frozen=True)
class FshArchive:
    path: Path
    entries: tuple[FshEntry, ...]

    @property
    def texture_names(self) -> frozenset[str]:
        return frozenset(entry.name for entry in self.entries)


def working_texture_name(name: str) -> str:
    """Return the filename-safe name used for extracted texture files."""
    return name.replace(":", "-")


def _working_name_map(names) -> dict[str, str]:
    mapping = {name: working_texture_name(name) for name in names}
    reverse: dict[str, str] = {}
    for original, working in mapping.items():
        previous = reverse.get(working)
        if previous is not None and previous != original:
            raise FshError(
                f"FSH names {previous!r} and {original!r} both map to working filename {working!r}."
            )
        reverse[working] = original
    return mapping


def _rewrite_directory_names(data: bytes, replacements: dict[str, str]) -> bytes:
    """Rewrite equal-length ShpF directory names without touching image data."""
    output = bytearray(data)
    count = struct.unpack_from(">I", data, 8)[0]
    position = 16
    for _ in range(count):
        end = data.find(b"\0", position + 8)
        if end < 0:
            raise FshError("Cannot rewrite a truncated FSH texture directory.")
        name = data[position + 8:end].decode("ascii")
        replacement = replacements.get(name, name)
        encoded = replacement.encode("ascii")
        if len(encoded) != end - (position + 8):
            raise FshError("Temporary FSH name translation must preserve name length.")
        output[position + 8:end] = encoded
        position = end + 1
    return bytes(output)


def read_fsh(path: str | Path) -> FshArchive:
    source = Path(path)
    data = source.read_bytes()
    if len(data) < 16 or data[:4] != b"ShpF":
        raise FshError(f"{source.name} is not a supported ShpF archive.")
    declared_size = struct.unpack_from("<I", data, 4)[0]
    if declared_size != len(data):
        raise FshError(f"{source.name} declares {declared_size} bytes but contains {len(data)}.")
    count = struct.unpack_from(">I", data, 8)[0]
    position = 16
    entries: list[FshEntry] = []
    occurrences: dict[str, int] = {}
    for index in range(count):
        if position + 9 > len(data):
            raise FshError(f"{source.name} has a truncated texture directory.")
        offset, size = struct.unpack_from(">II", data, position)
        end = data.find(b"\0", position + 8)
        if end < 0:
            raise FshError(f"{source.name} contains an unterminated texture name.")
        try:
            name = data[position + 8:end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise FshError(f"{source.name} contains a non-ASCII texture name.") from exc
        if not name or offset + size > len(data) or offset + 32 > len(data):
            raise FshError(f"{source.name} has invalid directory entry {index}.")
        format_code, flags = struct.unpack_from("<HH", data, offset)
        width, height = struct.unpack_from("<II", data, offset + 24)
        occurrence = occurrences.get(name, 0)
        occurrences[name] = occurrence + 1
        entries.append(FshEntry(name, offset, size, width, height, format_code, flags, occurrence))
        position = end + 1
    return FshArchive(source, tuple(entries))


def asset_base_name(ebo_path: str | Path) -> str:
    """Both stadium EBO variants share the base stadium FSH archives."""
    stem = Path(ebo_path).stem
    if stem.lower().endswith("_trans"):
        return stem[:-6]
    # Backboard variants place their role before the game-year suffix:
    # minnbbd_trans_05/refl_05/shad_05 all use minnbbd_05.fsh.
    return re.sub(r"_(?:trans|refl|shad)(?=_\d{2}$)", "", stem, flags=re.IGNORECASE)


def find_archives(ebo_path: str | Path, archive_directory: str | Path | None = None) -> tuple[FshArchive, ...]:
    ebo = Path(ebo_path)
    root = Path(archive_directory) if archive_directory else ebo.parent
    base = asset_base_name(ebo)
    archives: list[FshArchive] = []
    for suffix in (".fsh", "_vram.fsh"):
        candidate = root / (base + suffix)
        if candidate.is_file():
            archives.append(read_fsh(candidate))
    return tuple(archives)


def texture_ownership(archives: tuple[FshArchive, ...]) -> dict[str, tuple[str, ...]]:
    """Retain every archive containing each name; duplicates are not discarded."""
    owners: dict[str, list[str]] = {}
    for archive in archives:
        for entry in archive.entries:
            aliases = (entry.name, entry.name.split(":", 1)[1]) if ":" in entry.name else (entry.name,)
            for alias in aliases:
                if archive.path.name not in owners.setdefault(alias, []):
                    owners[alias].append(archive.path.name)
    return {name: tuple(paths) for name, paths in owners.items()}


def resolve_entry_name(archive: FshArchive, texture_name: str) -> str:
    """Resolve an EBO texture name to its canonical slot-qualified FSH name."""
    if texture_name in archive.texture_names:
        return texture_name
    matches = [
        entry.name for entry in archive.entries
        if ":" in entry.name and entry.name.split(":", 1)[1] == texture_name
    ]
    unique = tuple(dict.fromkeys(matches))
    if len(unique) == 1:
        return unique[0]
    if len(unique) > 1:
        raise FshError(
            f"Texture {texture_name!r} matches multiple entries in {archive.path.name}: "
            + ", ".join(unique)
        )
    return texture_name


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def ensure_placeholder_png(path: str | Path, *, size: int = 64) -> Path:
    """Create an obvious RGBA checkerboard without overwriting user artwork."""
    destination = Path(path)
    if destination.is_file():
        return destination
    if size < 2 or size > 1024:
        raise FshError(f"Unsupported placeholder texture size: {size}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows = bytearray()
    tile = max(1, size // 8)
    for y in range(size):
        rows.append(0)
        for x in range(size):
            color = (255, 0, 255, 255) if ((x // tile) + (y // tile)) % 2 == 0 else (16, 16, 16, 255)
            rows.extend(color)
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = signature + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _png_chunk(b"IEND", b"")
    destination.write_bytes(png)
    return destination


def _rgba_png_bytes(data: bytes) -> bytes:
    """Convert a conventional 8-bit RGB PNG to RGBA."""
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise FshError("Texture image is not a valid PNG file.")
    position = len(signature)
    chunks: list[tuple[bytes, bytes]] = []
    while position + 12 <= len(data):
        length = struct.unpack_from(">I", data, position)[0]
        end = position + 12 + length
        if end > len(data):
            raise FshError("Texture PNG contains a truncated chunk.")
        kind = data[position + 4:position + 8]
        payload = data[position + 8:position + 8 + length]
        chunks.append((kind, payload))
        position = end
        if kind == b"IEND":
            break
    ihdr = next((payload for kind, payload in chunks if kind == b"IHDR"), None)
    if ihdr is None or len(ihdr) != 13:
        raise FshError("Texture PNG is missing a valid IHDR chunk.")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", ihdr)
    if color_type == 6:
        return data
    if color_type != 2:
        return data
    if bit_depth != 8 or compression or filtering or interlace:
        raise FshError(
            "RGB textures must be 8-bit and non-interlaced. Convert this image to RGBA before export."
        )
    compressed = b"".join(payload for kind, payload in chunks if kind == b"IDAT")
    try:
        encoded_rows = zlib.decompress(compressed)
    except zlib.error as exc:
        raise FshError(f"Texture PNG pixel data could not be decoded: {exc}") from exc
    stride = width * 3
    if len(encoded_rows) != height * (stride + 1):
        raise FshError("Texture PNG has an unexpected RGB scanline length.")
    previous = bytearray(stride)
    rgba_rows = bytearray()
    cursor = 0
    for _ in range(height):
        filter_type = encoded_rows[cursor]
        filtered = encoded_rows[cursor + 1:cursor + 1 + stride]
        cursor += stride + 1
        row = bytearray(stride)
        for index, value in enumerate(filtered):
            left = row[index - 3] if index >= 3 else 0
            above = previous[index]
            upper_left = previous[index - 3] if index >= 3 else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                pa, pb, pc = abs(estimate - left), abs(estimate - above), abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else above if pb <= pc else upper_left
            else:
                raise FshError(f"Texture PNG uses unsupported scanline filter {filter_type}.")
            row[index] = (value + predictor) & 0xFF
        rgba_rows.append(0)
        for index in range(0, stride, 3):
            rgba_rows.extend(row[index:index + 3])
            rgba_rows.append(255)
        previous = row
    new_ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    output = bytearray(signature)
    output.extend(_png_chunk(b"IHDR", new_ihdr))
    for kind, payload in chunks:
        if kind not in {b"IHDR", b"IDAT", b"IEND", b"PLTE", b"tRNS"}:
            output.extend(_png_chunk(kind, payload))
    output.extend(_png_chunk(b"IDAT", zlib.compress(bytes(rgba_rows), 9)))
    output.extend(_png_chunk(b"IEND", b""))
    return bytes(output)


def archive_kind(path: str | Path) -> str:
    """Return the Blender archive selector corresponding to an FSH filename."""
    return "VRAM" if Path(path).stem.lower().endswith("_vram") else "MAIN"


def stage_texture(
    archive: FshArchive,
    texture_root: str | Path,
    texture_name: str,
    source_image: str | Path,
) -> Path:
    """Copy a named PNG into precisely its selected archive staging folder."""
    source = Path(source_image).resolve()
    if not source.is_file():
        raise FshError(f"Texture image was not found for {texture_name!r}: {source}")
    if source.suffix.lower() != ".png":
        raise FshError(f"Texture {texture_name!r} must be a PNG before FSH packing.")
    canonical_name = resolve_entry_name(archive, texture_name)
    destination = Path(texture_root).resolve() / archive.path.stem / f"{working_texture_name(canonical_name)}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    converted = _rgba_png_bytes(source.read_bytes())
    destination.write_bytes(converted)
    return destination



def _rgb_from_565(value: int) -> tuple[int, int, int]:
    r = (value >> 11) & 31
    g = (value >> 5) & 63
    b = value & 31
    return (
        (r << 3) | (r >> 2),
        (g << 2) | (g >> 4),
        (b << 3) | (b >> 2),
    )


def _decode_color_block(block: bytes, *, dxt1: bool) -> list[tuple[int, int, int, int]]:
    if len(block) != 8:
        raise FshError("Truncated DXT colour block.")
    c0, c1, bits = struct.unpack("<HHI", block)
    p0 = _rgb_from_565(c0)
    p1 = _rgb_from_565(c1)
    if dxt1 and c0 <= c1:
        palette = (
            (*p0, 255),
            (*p1, 255),
            tuple((p0[i] + p1[i]) // 2 for i in range(3)) + (255,),
            (0, 0, 0, 0),
        )
    else:
        p2 = tuple((2 * p0[i] + p1[i]) // 3 for i in range(3))
        p3 = tuple((p0[i] + 2 * p1[i]) // 3 for i in range(3))
        palette = ((*p0, 255), (*p1, 255), (*p2, 255), (*p3, 255))
    return [palette[(bits >> (2 * index)) & 3] for index in range(16)]


def _decode_dxt1(payload: bytes, width: int, height: int) -> bytes:
    expected = ((width + 3) // 4) * ((height + 3) // 4) * 8
    if len(payload) < expected:
        raise FshError(f"Truncated DXT1 payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    cursor = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            pixels = _decode_color_block(payload[cursor:cursor + 8], dxt1=True)
            cursor += 8
            for iy in range(4):
                y = by + iy
                if y >= height:
                    continue
                for ix in range(4):
                    x = bx + ix
                    if x >= width:
                        continue
                    rgba[(y * width + x) * 4:(y * width + x + 1) * 4] = bytes(pixels[iy * 4 + ix])
    return bytes(rgba)


def _decode_dxt3(payload: bytes, width: int, height: int) -> bytes:
    expected = ((width + 3) // 4) * ((height + 3) // 4) * 16
    if len(payload) < expected:
        raise FshError(f"Truncated DXT3 payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    cursor = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            alpha_bits = int.from_bytes(payload[cursor:cursor + 8], "little")
            colors = _decode_color_block(payload[cursor + 8:cursor + 16], dxt1=False)
            cursor += 16
            for index, color in enumerate(colors):
                x = bx + (index & 3)
                y = by + (index >> 2)
                if x >= width or y >= height:
                    continue
                alpha = ((alpha_bits >> (4 * index)) & 0xF) * 17
                offset = (y * width + x) * 4
                rgba[offset:offset + 4] = bytes((color[0], color[1], color[2], alpha))
    return bytes(rgba)


def _dxt5_alpha_palette(a0: int, a1: int) -> tuple[int, ...]:
    if a0 > a1:
        return (
            a0, a1,
            (6 * a0 + a1) // 7,
            (5 * a0 + 2 * a1) // 7,
            (4 * a0 + 3 * a1) // 7,
            (3 * a0 + 4 * a1) // 7,
            (2 * a0 + 5 * a1) // 7,
            (a0 + 6 * a1) // 7,
        )
    return (
        a0, a1,
        (4 * a0 + a1) // 5,
        (3 * a0 + 2 * a1) // 5,
        (2 * a0 + 3 * a1) // 5,
        (a0 + 4 * a1) // 5,
        0, 255,
    )


def _decode_dxt5(payload: bytes, width: int, height: int) -> bytes:
    expected = ((width + 3) // 4) * ((height + 3) // 4) * 16
    if len(payload) < expected:
        raise FshError(f"Truncated DXT5 payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    cursor = 0
    for by in range(0, height, 4):
        for bx in range(0, width, 4):
            a0, a1 = payload[cursor], payload[cursor + 1]
            alpha_palette = _dxt5_alpha_palette(a0, a1)
            alpha_bits = int.from_bytes(payload[cursor + 2:cursor + 8], "little")
            colors = _decode_color_block(payload[cursor + 8:cursor + 16], dxt1=False)
            cursor += 16
            for index, color in enumerate(colors):
                x = bx + (index & 3)
                y = by + (index >> 2)
                if x >= width or y >= height:
                    continue
                alpha = alpha_palette[(alpha_bits >> (3 * index)) & 7]
                offset = (y * width + x) * 4
                rgba[offset:offset + 4] = bytes((color[0], color[1], color[2], alpha))
    return bytes(rgba)



def _decode_bgra32(payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 4
    if len(payload) < expected:
        raise FshError(f"Truncated 32-bit FSH payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(expected)
    for i in range(width * height):
        b, g, r, a = payload[i * 4:i * 4 + 4]
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    return bytes(rgba)


def _decode_bgr24(payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 3
    if len(payload) < expected:
        raise FshError(f"Truncated 24-bit FSH payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        b, g, r = payload[i * 3:i * 3 + 3]
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, 255))
    return bytes(rgba)


def _decode_565(payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 2
    if len(payload) < expected:
        raise FshError(f"Truncated RGB565 FSH payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        r, g, b = _rgb_from_565(struct.unpack_from("<H", payload, i * 2)[0])
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, 255))
    return bytes(rgba)


def _decode_1555(payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 2
    if len(payload) < expected:
        raise FshError(f"Truncated ARGB1555 FSH payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        value = struct.unpack_from("<H", payload, i * 2)[0]
        a = 255 if value & 0x8000 else 0
        r5, g5, b5 = (value >> 10) & 31, (value >> 5) & 31, value & 31
        r, g, b = (r5 << 3) | (r5 >> 2), (g5 << 3) | (g5 >> 2), (b5 << 3) | (b5 >> 2)
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    return bytes(rgba)


def _decode_4444(payload: bytes, width: int, height: int) -> bytes:
    expected = width * height * 2
    if len(payload) < expected:
        raise FshError(f"Truncated ARGB4444 FSH payload: expected {expected} bytes, got {len(payload)}.")
    rgba = bytearray(width * height * 4)
    for i in range(width * height):
        value = struct.unpack_from("<H", payload, i * 2)[0]
        a = ((value >> 12) & 15) * 17
        r = ((value >> 8) & 15) * 17
        g = ((value >> 4) & 15) * 17
        b = (value & 15) * 17
        rgba[i * 4:i * 4 + 4] = bytes((r, g, b, a))
    return bytes(rgba)

def _rgba_to_png_bytes(width: int, height: int, rgba: bytes) -> bytes:
    if len(rgba) != width * height * 4:
        raise FshError("Internal RGBA buffer size mismatch.")
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)
        rows.extend(rgba[y * stride:(y + 1) * stride])
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        signature
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _png_chunk(b"IEND", b"")
    )


def _entry_payload(data: bytes, entry: FshEntry) -> tuple[int, bytes]:
    block = data[entry.offset:entry.offset + entry.size]
    if len(block) < 32:
        raise FshError(f"Texture {entry.name!r} has a truncated FSH image block.")
    format_type = block[0]
    payload_offset = struct.unpack_from("<I", block, 8)[0]
    payload_size = struct.unpack_from("<I", block, 12)[0]
    if payload_offset < 32 or payload_offset > len(block):
        payload_offset = 32
    if payload_size <= 0 or payload_offset + payload_size > len(block):
        payload_size = len(block) - payload_offset
    return format_type, block[payload_offset:payload_offset + payload_size]


def extract_archive(archive: FshArchive, output_root: str | Path) -> Path:
    """Extract native DXT1/DXT3/DXT5 FSH entries to RGBA PNG files."""
    destination_root = Path(output_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / archive.path.stem
    destination.mkdir(parents=True, exist_ok=True)
    data = archive.path.read_bytes()
    name_map = _working_name_map(archive.texture_names)
    written: set[str] = set()
    unsupported: list[str] = []
    for entry in archive.entries:
        if entry.name in written:
            continue
        format_type, payload = _entry_payload(data, entry)
        format_type &= 0x7F
        if format_type == 0x60:
            rgba = _decode_dxt1(payload, entry.width, entry.height)
        elif format_type == 0x61:
            rgba = _decode_dxt3(payload, entry.width, entry.height)
        elif format_type == 0x62:
            rgba = _decode_dxt5(payload, entry.width, entry.height)
        elif format_type == 0x7D:
            rgba = _decode_bgra32(payload, entry.width, entry.height)
        elif format_type == 0x7F:
            rgba = _decode_bgr24(payload, entry.width, entry.height)
        elif format_type == 0x7E:
            rgba = _decode_1555(payload, entry.width, entry.height)
        elif format_type == 0x78:
            rgba = _decode_565(payload, entry.width, entry.height)
        elif format_type == 0x6D:
            rgba = _decode_4444(payload, entry.width, entry.height)
        else:
            unsupported.append(f"{entry.name} (0x{format_type:02X})")
            continue
        target = destination / f"{name_map[entry.name]}.png"
        target.write_bytes(_rgba_to_png_bytes(entry.width, entry.height, rgba))
        written.add(entry.name)
    if unsupported:
        raise FshError(
            f"{archive.path.name} contains unsupported native FSH formats: "
            + ", ".join(unsupported)
            + ". Supported formats are DXT1/0x60, DXT3/0x61, DXT5/0x62, "
            "ARGB4444/0x6D, RGB565/0x78, BGRA32/0x7D, ARGB1555/0x7E, and BGR24/0x7F."
        )
    if not written:
        raise FshError(f"No supported textures were found in {archive.path.name}.")
    return destination


def _original_blocks(archive: FshArchive) -> dict[str, bytes]:
    data = archive.path.read_bytes()
    blocks: dict[str, bytes] = {}
    for entry in archive.entries:
        blocks.setdefault(entry.name, bytes(data[entry.offset:entry.offset + entry.size]))
    return blocks


def _rebuild_preserving_layout(
    archive: FshArchive,
    replacement_blocks: dict[str, bytes],
    required_names: frozenset[str],
    excluded_names: frozenset[str] = frozenset(),
) -> bytes:
    source = archive.path.read_bytes()
    original_by_name = _original_blocks(archive)
    ordered: list[tuple[str, bytes]] = []

    # Preserve original directory order, except for entries explicitly
    # superseded by a material texture rename during export.
    for entry in archive.entries:
        if entry.name in excluded_names:
            continue
        block = replacement_blocks.get(entry.name, original_by_name[entry.name])
        ordered.append((entry.name, block))

    # Append genuinely new required textures. An excluded source name must not
    # be reintroduced even if it happens to appear in required_names.
    existing_names = {name for name, _ in ordered}
    for name in sorted(required_names - existing_names - excluded_names):
        block = replacement_blocks.get(name)
        if block is None:
            raise FshError(f"No encoded image block is available for new texture {name!r}.")
        ordered.append((name, block))

    first_data = min(entry.offset for entry in archive.entries)
    marker_start = source.find(b"G427", 16, first_data)
    if marker_start >= 0:
        suffix = source[marker_start:first_data]
        metadata_start = struct.unpack_from(">I", source, 12)[0]
        metadata_delta = metadata_start - marker_start
    else:
        # Native writer-compatible fallback for unusual archives without G427.
        suffix = b"G427\0\0\0\0"
        metadata_delta = len(suffix)

    directory_length = sum(9 + len(name.encode("ascii")) for name, _ in ordered)
    marker_position = 16 + directory_length
    padding = (-marker_position - len(suffix)) % 16
    first_new_data = marker_position + len(suffix) + padding
    directory = bytearray()
    cursor = first_new_data
    for name, block in ordered:
        directory.extend(struct.pack(">II", cursor, len(block)))
        directory.extend(name.encode("ascii") + b"\0")
        cursor += len(block)

    output = bytearray(b"ShpF")
    output.extend(struct.pack("<I", cursor))
    output.extend(struct.pack(">I", len(ordered)))
    output.extend(struct.pack(">I", marker_position + metadata_delta))
    output.extend(directory)
    output.extend(suffix)
    output.extend(b"\0" * padding)
    for _, block in ordered:
        output.extend(block)
    return bytes(output)


def repack_archive(
    archive: FshArchive,
    texture_directory: str | Path,
    output_directory: str | Path,
    *,
    required_names: frozenset[str] = frozenset(),
    excluded_names: frozenset[str] = frozenset(),
) -> Path:
    """Rebuild an FSH natively, preserving untouched image blocks byte-for-byte."""
    try:
        from . import synthetic_fsh
    except ImportError:
        import synthetic_fsh

    images = Path(texture_directory).resolve()
    if not images.is_dir():
        raise FshError(f"Extracted texture directory is missing: {images}")
    # Required textures are added, while superseded source textures are
    # deliberately omitted from the rebuilt archive.
    expected = (archive.texture_names | required_names) - excluded_names
    name_map = _working_name_map(expected)
    missing = sorted(name for name in expected if not (images / f"{name_map[name]}.png").is_file())
    if missing:
        raise FshError(
            f"Refusing to repack {archive.path.name}: missing required textures "
            + ", ".join(missing)
        )

    replacement_blocks: dict[str, bytes] = {}
    try:
        for name in sorted(expected):
            encoded = synthetic_fsh._encode_native_texture(images / f"{name_map[name]}.png")
            replacement_blocks[name] = synthetic_fsh._native_block(encoded)
    except synthetic_fsh.SyntheticFshError as exc:
        raise FshError(str(exc)) from exc

    rebuilt_data = _rebuild_preserving_layout(
        archive,
        replacement_blocks,
        required_names,
        excluded_names,
    )
    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    final_path = output / archive.path.name
    final_path.write_bytes(rebuilt_data)
    read_fsh(final_path)
    return final_path


