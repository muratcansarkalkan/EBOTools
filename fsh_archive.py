"""FSH directory inspection and external GX extraction/repacking helpers."""

from __future__ import annotations

from dataclasses import dataclass
import binascii
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import zlib


class FshError(ValueError):
    """An FSH archive or GX operation could not be processed safely."""


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
    """Return the filename-safe name used between Blender and GX."""
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
    """Convert a conventional 8-bit RGB PNG to RGBA for GX's 0x7D output."""
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
    # Indexed/grayscale PNGs are used by older backboard archives and must be
    # left for GX to interpret in their original 0x61-style format. The 0x7F
    # game failure only occurs for ordinary true-colour RGB input.
    if color_type != 2:
        return data
    if bit_depth != 8 or compression or filtering or interlace:
        raise FshError(
            "RGB GX textures must be 8-bit and non-interlaced. Convert this image to RGBA before export."
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
    """Copy a named PNG into precisely its selected archive's GX input folder."""
    source = Path(source_image).resolve()
    if not source.is_file():
        raise FshError(f"Texture image was not found for {texture_name!r}: {source}")
    if source.suffix.lower() != ".png":
        raise FshError(f"Texture {texture_name!r} must be a PNG before GX can pack it.")
    canonical_name = resolve_entry_name(archive, texture_name)
    destination = Path(texture_root).resolve() / archive.path.stem / f"{working_texture_name(canonical_name)}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    converted = _rgba_png_bytes(source.read_bytes())
    destination.write_bytes(converted)
    return destination


def _gx_executable(value: str | Path) -> Path:
    executable = Path(value)
    if executable.is_dir():
        for name in ("gx.exe", "gx"):
            candidate = executable / name
            if candidate.is_file():
                return candidate.resolve()
    if not executable.is_file():
        raise FshError(f"GX executable was not found: {value}")
    return executable.resolve()


def _run_gx(executable: Path, arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            [str(executable), *arguments],
            cwd=str(cwd),
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise FshError(f"Could not launch GX: {exc}") from exc
    if result.returncode:
        details = (result.stderr or result.stdout or "GX did not provide an error message.").strip()
        raise FshError(f"GX failed with exit code {result.returncode}: {details}")
    return result


def extract_archive(archive: FshArchive, gx_path: str | Path, output_root: str | Path) -> Path:
    """Extract one archive while keeping its textures in its own directory.

    The archive stem replaces the batch wildcard. For ``boststd.fsh``, the
    Windows batch expression ``-=boststd\\%%s.png`` becomes the literal GX
    argument ``-=boststd\\%s.png`` when subprocess calls GX directly.
    """
    executable = _gx_executable(gx_path)
    destination_root = Path(output_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / archive.path.stem
    destination.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nba_live_gx_") as temporary:
        staging = Path(temporary)
        staged_archive = staging / archive.path.name
        name_map = _working_name_map(archive.texture_names)
        staged_archive.write_bytes(
            _rewrite_directory_names(archive.path.read_bytes(), name_map)
        )
        output_pattern = f"-={archive.path.stem}\\%s.png"
        _run_gx(executable, ["-f!*_mm*", output_pattern, staged_archive.name], staging)
        expected = staging / archive.path.stem
        search_roots = [expected, staging]
        copied = 0
        for name in archive.texture_names:
            working_name = name_map[name]
            match = None
            for root in search_roots:
                direct = root / f"{working_name}.png"
                if direct.is_file():
                    match = direct
                    break
                matches = list(root.rglob(f"{working_name}.png")) if root.is_dir() else []
                if matches:
                    match = matches[0]
                    break
            if match is not None:
                shutil.copy2(match, destination / match.name)
                copied += 1
        if not copied:
            raise FshError(
                f"GX completed but no PNG textures were found for {archive.path.name}. "
                "Check that this GX version supports the documented extraction arguments."
            )
    return destination


def repack_archive(
    archive: FshArchive,
    texture_directory: str | Path,
    gx_path: str | Path,
    output_directory: str | Path,
    *,
    required_names: frozenset[str] = frozenset(),
) -> Path:
    executable = _gx_executable(gx_path)
    images = Path(texture_directory).resolve()
    if not images.is_dir():
        raise FshError(f"Extracted texture directory is missing: {images}")
    expected = archive.texture_names | required_names
    name_map = _working_name_map(expected)
    missing = sorted(name for name in expected if not (images / f"{name_map[name]}.png").is_file())
    if missing:
        raise FshError(
            f"Refusing to repack {archive.path.name}: missing required textures "
            + ", ".join(missing)
        )

    output = Path(output_directory).resolve()
    output.mkdir(parents=True, exist_ok=True)
    temporary_result = output / f"{archive.path.stem}.newfsh"
    # Never give GX the whole persistent extraction directory. It may contain
    # stale PNGs or textures staged for the companion main/VRAM archive, which
    # would silently create duplicate global texture names in both FSH files.
    with tempfile.TemporaryDirectory(prefix="nba_live_gx_pack_") as temporary:
        staging = Path(temporary)
        for name in sorted(expected):
            safe_name = name_map[name]
            shutil.copy2(images / f"{safe_name}.png", staging / f"{safe_name}.png")
        _run_gx(executable, [str(staging / "*.png"), "=", str(temporary_result)], output)
    if not temporary_result.is_file():
        raise FshError(f"GX did not create the expected archive: {temporary_result}")

    # GX builds from unique PNG filenames. Verify original membership, and
    # restore repeated identical names in the FSH directory when necessary.
    rebuilt_safe = read_fsh(temporary_result)
    reverse_names = {working: original for original, working in name_map.items()}
    temporary_result.write_bytes(
        _rewrite_directory_names(temporary_result.read_bytes(), reverse_names)
    )
    rebuilt = read_fsh(temporary_result)
    missing_after = expected - rebuilt.texture_names
    if missing_after:
        raise FshError(
            f"Repacked archive {temporary_result.name} lost textures: " + ", ".join(sorted(missing_after))
        )
    duplicate_names = {
        name for name in expected if sum(entry.name == name for entry in archive.entries) > 1
    }
    if duplicate_names:
        data = restore_duplicate_entries(archive, rebuilt)
        temporary_result.write_bytes(data)
        read_fsh(temporary_result)

    final_path = output / archive.path.name
    temporary_result.replace(final_path)
    return final_path


def restore_duplicate_entries(original: FshArchive, rebuilt: FshArchive) -> bytes:
    """Recreate duplicate directory entries by duplicating rebuilt image blocks."""
    source = rebuilt.path.read_bytes()
    by_name: dict[str, FshEntry] = {}
    for entry in rebuilt.entries:
        by_name.setdefault(entry.name, entry)
    ordered_entries: list[tuple[str, bytes]] = []
    for entry in original.entries:
        match = by_name.get(entry.name)
        if match is None:
            raise FshError(f"Cannot restore missing archive entry {entry.name!r}.")
        ordered_entries.append((entry.name, source[match.offset:match.offset + match.size]))
    for entry in rebuilt.entries:
        if entry.name not in original.texture_names:
            ordered_entries.append((entry.name, source[entry.offset:entry.offset + entry.size]))

    metadata_start = struct.unpack_from(">I", source, 12)[0]
    first_data = rebuilt.entries[0].offset
    marker_start = source.find(b"G427", 16)
    if marker_start < 0 or marker_start >= first_data:
        raise FshError("Cannot identify the FSH archive metadata suffix.")
    suffix = source[marker_start:first_data]
    old_metadata_delta = metadata_start - marker_start
    directory_length = sum(8 + len(name.encode("ascii")) + 1 for name, _ in ordered_entries)
    marker_position = 16 + directory_length
    # Preserve the first image's 16-byte alignment while retaining GX metadata.
    padding = (-marker_position - len(suffix)) % 16
    header_end = marker_position + len(suffix) + padding
    directory = bytearray()
    cursor = header_end
    for name, payload in ordered_entries:
        directory.extend(struct.pack(">II", cursor, len(payload)))
        directory.extend(name.encode("ascii") + b"\0")
        cursor += len(payload)
    output = bytearray(b"ShpF")
    output.extend(struct.pack("<I", cursor))
    output.extend(struct.pack(">I", len(ordered_entries)))
    output.extend(struct.pack(">I", marker_position + old_metadata_delta))
    output.extend(directory)
    output.extend(suffix)
    output.extend(b"\0" * padding)
    for _, payload in ordered_entries:
        output.extend(payload)
    return bytes(output)
