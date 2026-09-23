"""Xbox EA Sports BIG/VIV, EBO and XSH import helpers.

Import-only support intended for NBA Live / NCAA March Madness Xbox assets.
The module deliberately does not provide Xbox export/repacking.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import struct

from . import ebo_core
from . import fsh_archive


class XboxAssetError(ValueError):
    pass


@dataclass(frozen=True)
class BigEntry:
    name: str
    offset: int
    size: int


def big_entries(data: bytes) -> tuple[BigEntry, ...]:
    if len(data) < 16 or data[:4] != b"BIGF":
        raise XboxAssetError("Not an EA BIGF/VIV archive.")
    count = int.from_bytes(data[8:12], "big")
    table_end = int.from_bytes(data[12:16], "big")
    pos = 16
    entries: list[BigEntry] = []
    for index in range(count):
        if pos + 9 > len(data):
            raise XboxAssetError(f"Truncated BIGF directory at entry {index}.")
        offset = int.from_bytes(data[pos:pos + 4], "big")
        size = int.from_bytes(data[pos + 4:pos + 8], "big")
        pos += 8
        end = data.find(b"\0", pos)
        if end < 0 or end > table_end:
            raise XboxAssetError(f"Invalid BIGF filename at entry {index}.")
        try:
            name = data[pos:end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise XboxAssetError(f"Non-ASCII BIGF filename at entry {index}.") from exc
        pos = end + 1
        if offset < table_end or size < 0 or offset + size > len(data):
            raise XboxAssetError(f"Invalid BIGF member range for {name!r}.")
        entries.append(BigEntry(name, offset, size))
    return tuple(entries)


def refpack_decompress(data: bytes) -> bytes:
    """Decode the EA RefPack flavor used by these Xbox VIV members."""
    if not data.startswith(b"\x10\xFB"):
        return data
    if len(data) < 5:
        raise XboxAssetError("Truncated RefPack header.")
    expected = int.from_bytes(data[2:5], "big")
    src = 5
    out = bytearray()

    def literal(count: int) -> None:
        nonlocal src
        if src + count > len(data):
            raise XboxAssetError("RefPack literal extends beyond compressed member.")
        out.extend(data[src:src + count])
        src += count

    def backref(distance: int, count: int) -> None:
        if distance <= 0 or distance > len(out):
            raise XboxAssetError("Invalid RefPack back-reference.")
        start = len(out) - distance
        for _ in range(count):
            out.append(out[start])
            start += 1

    while src < len(data) and len(out) < expected:
        control = data[src]
        src += 1

        if control < 0x80:
            if src >= len(data):
                raise XboxAssetError("Truncated RefPack short command.")
            b1 = data[src]
            src += 1
            plain = control & 3
            length = ((control & 0x1C) >> 2) + 3
            distance = ((control & 0x60) << 3) + b1 + 1
            literal(plain)
            backref(distance, length)

        elif control < 0xC0:
            if src + 2 > len(data):
                raise XboxAssetError("Truncated RefPack medium command.")
            b1, b2 = data[src], data[src + 1]
            src += 2
            plain = (b1 >> 6) & 3
            length = (control & 0x3F) + 4
            distance = ((b1 & 0x3F) << 8) + b2 + 1
            literal(plain)
            backref(distance, length)

        elif control < 0xE0:
            if src + 3 > len(data):
                raise XboxAssetError("Truncated RefPack long command.")
            b1, b2, b3 = data[src], data[src + 1], data[src + 2]
            src += 3
            plain = control & 3
            length = ((control & 0x0C) << 6) + b3 + 5
            distance = ((control & 0x10) << 12) + (b1 << 8) + b2 + 1
            literal(plain)
            backref(distance, length)

        elif control < 0xFC:
            literal(((control & 0x1F) << 2) + 4)

        else:
            literal(control & 3)
            break

    if len(out) != expected:
        raise XboxAssetError(
            f"RefPack member decoded to {len(out)} bytes; expected {expected}."
        )
    return bytes(out)


def member_bytes(viv_data: bytes, entry: BigEntry) -> bytes:
    return refpack_decompress(viv_data[entry.offset:entry.offset + entry.size])


def _xbox_buffer(data: bytes, offset: int, expected_stride: int) -> ebo_core.Buffer:
    if offset < 0 or offset + 28 > len(data):
        raise XboxAssetError(f"Xbox vertex-buffer header outside EBO at 0x{offset:X}.")
    one, data_offset, zero, byte_count, stride, one2, data_offset2 = struct.unpack_from(
        "<7I", data, offset
    )
    if stride != expected_stride:
        raise XboxAssetError(
            f"Unexpected Xbox buffer stride {stride} at 0x{offset:X}; expected {expected_stride}."
        )
    if data_offset != data_offset2:
        raise XboxAssetError(f"Xbox buffer at 0x{offset:X} has mismatched data pointers.")
    if byte_count <= 0 or data_offset + byte_count > len(data):
        raise XboxAssetError(f"Xbox buffer at 0x{offset:X} extends beyond the EBO.")
    return ebo_core.Buffer(offset, data_offset, byte_count, stride)


def _try_xbox_buffer(data: bytes, offset: int, expected_stride: int) -> ebo_core.Buffer | None:
    try:
        return _xbox_buffer(data, offset, expected_stride)
    except XboxAssetError:
        return None


def parse_xbox_ebo(data: bytes) -> ebo_core.Court:
    """Parse tested Xbox EBO v17 stadium, transparent-stadium, court and backboard geometry.

    Xbox descriptor type 6 is used for both static color geometry and normal-bearing
    backboard geometry.  The stream tuple is discovered structurally:

      STATIC_COLOR:  position(12), uv(8), color(4), indices
      XBOX_NORMAL:   position(12), uv(8), normal(12), aux/skin data, indices

    Descriptor type 2 found in Xbox court files represents the source line-shape
    records.  The game-visible court line geometry is also present as type-6
    *ShapeGeo objects, so type-2 records are intentionally skipped in Blender.
    """
    if len(data) < 48 or data[:4] != b"EBO\0":
        raise XboxAssetError("Not an EBO file.")
    version, declared_size = struct.unpack_from("<2I", data, 4)
    if version != 17:
        raise XboxAssetError(f"Unsupported Xbox EBO version {version}.")
    if declared_size != len(data):
        raise XboxAssetError(
            f"Xbox EBO declares {declared_size} bytes but contains {len(data)}."
        )

    mesh_table, string_table = struct.unpack_from("<2I", data, 28)
    mesh_count = struct.unpack_from("<H", data, 42)[0]
    if mesh_table + mesh_count * 12 != string_table:
        raise XboxAssetError("Xbox EBO mesh table does not match its mesh count.")

    meshes: list[ebo_core.Mesh] = []

    def cstring(offset: int) -> str:
        if not 0 <= offset < len(data):
            raise XboxAssetError(f"Invalid Xbox EBO string offset 0x{offset:X}.")
        end = data.find(b"\0", offset)
        if end < 0:
            raise XboxAssetError("Unterminated Xbox EBO string.")
        return data[offset:end].decode("ascii")

    for mesh_index in range(mesh_count):
        entry = mesh_table + mesh_index * 12
        kind, name_offset, relative = struct.unpack_from("<IIi", data, entry)
        record_type = "Geometry" if kind == 4 else cstring(string_table + kind)
        if record_type != "Geometry":
            raise XboxAssetError(
                f"Unsupported Xbox object record {record_type!r} at 0x{entry:X}."
            )
        mesh_offset = entry + 8 + relative
        mesh_name = cstring(string_table + name_offset)
        batch_count = struct.unpack_from("<I", data, mesh_offset + 12)[0]
        batch_table = struct.unpack_from("<I", data, mesh_offset + 16)[0]
        if batch_table != mesh_offset + 104:
            raise XboxAssetError(
                f"Unexpected Xbox material table location in {mesh_name!r}."
            )

        batches: list[ebo_core.Batch] = []
        for batch_index in range(batch_count):
            row = batch_table + batch_index * 48
            descriptor = struct.unpack_from("<I", data, row + 12)[0]
            if descriptor + 32 > len(data):
                raise XboxAssetError(
                    f"Xbox descriptor outside file in {mesh_name}, batch {batch_index}."
                )
            descriptor_kind = struct.unpack_from("<I", data, descriptor)[0]

            # Xbox court EBOs also contain source line-shape records.  Importing
            # these as Blender edges duplicates the real ShapeGeo line meshes and
            # creates the 'spider web' seen in the viewport, so skip them.
            if descriptor_kind == 2:
                continue
            if descriptor_kind != 6:
                raise XboxAssetError(
                    f"Unsupported Xbox descriptor type {descriptor_kind} "
                    f"in {mesh_name}, batch {batch_index}."
                )

            # Read enough descriptor words to locate the stream signature.  The
            # metadata prefix varies between ordinary/static, skinned/backboard,
            # and shot-clock batches, but the buffer wrappers themselves do not.
            max_words = min(20, (len(data) - descriptor) // 4)
            words = struct.unpack_from(f"<{max_words}I", data, descriptor)
            stream = None
            for word_index in range(1, max_words - 2):
                pos = _try_xbox_buffer(data, words[word_index], 12)
                uv = _try_xbox_buffer(data, words[word_index + 1], 8)
                if pos is None or uv is None:
                    continue
                color = _try_xbox_buffer(data, words[word_index + 2], 4)
                normal = _try_xbox_buffer(data, words[word_index + 2], 12)
                if color is not None:
                    stream = ("STATIC_COLOR", word_index, pos, uv, color, None)
                    break
                if normal is not None:
                    stream = ("XBOX_NORMAL", word_index, pos, uv, None, normal)
                    break
            if stream is None:
                raise XboxAssetError(
                    f"Could not identify Xbox vertex streams in {mesh_name}, batch {batch_index}."
                )

            profile, first_word, positions, uvs, colors, normals = stream
            vertex_count = positions.byte_count // 12
            if uvs.byte_count // 8 != vertex_count:
                raise XboxAssetError(
                    f"Xbox position/UV streams disagree in {mesh_name}, batch {batch_index}."
                )
            if colors is not None and colors.byte_count // 4 != vertex_count:
                raise XboxAssetError(
                    f"Xbox color stream disagrees in {mesh_name}, batch {batch_index}."
                )
            if normals is not None and normals.byte_count // 12 != vertex_count:
                raise XboxAssetError(
                    f"Xbox normal stream disagrees in {mesh_name}, batch {batch_index}."
                )

            if profile == "STATIC_COLOR":
                index_word = first_word + 3
                count_word = first_word + 4
            else:
                # Normal-bearing Xbox geometry has one auxiliary skin/palette
                # pointer between the normal stream and the raw index stream.
                index_word = first_word + 4
                count_word = first_word + 5

            if count_word + 2 >= max_words:
                raise XboxAssetError(
                    f"Truncated Xbox draw descriptor in {mesh_name}, batch {batch_index}."
                )
            index_ptr = words[index_word]
            index_count = words[count_word]
            material_off = words[count_word + 2]
            if index_count <= 0 or index_ptr + index_count * 2 > len(data):
                raise XboxAssetError(
                    f"Xbox index stream outside file in {mesh_name}, batch {batch_index}."
                )
            strip = struct.unpack_from(f"<{index_count}H", data, index_ptr)
            if any(value >= vertex_count for value in strip):
                raise XboxAssetError(
                    f"Xbox index exceeds vertex count in {mesh_name}, batch {batch_index}."
                )
            triangles = ebo_core._strip_triangles(strip, vertex_count)
            material = cstring(string_table + material_off)
            indices = ebo_core.Buffer(index_ptr, index_ptr, index_count * 2, 2)

            batches.append(
                ebo_core.Batch(
                    mesh_name=mesh_name,
                    batch_index=len(batches),
                    material=material,
                    vertex_count=vertex_count,
                    primitive_count=max(0, index_count - 2),
                    positions=positions,
                    uvs=uvs,
                    colors=colors,
                    indices=indices,
                    triangles=triangles,
                    normals=normals,
                    texture_names=(material,),
                    profile=profile,
                    descriptor_offset=descriptor,
                    count_word=count_word,
                    primitive_word=count_word,
                )
            )

        # Type-2-only court source-shape objects are intentionally omitted.
        if batches:
            meshes.append(ebo_core.Mesh(mesh_name, mesh_offset, tuple(batches)))

    return ebo_core.Court(data, tuple(meshes))

def xsh_entries(data: bytes) -> tuple[fsh_archive.FshEntry, ...]:
    if len(data) < 16 or data[:4] != b"ShpX":
        raise XboxAssetError("Not an Xbox ShpX texture archive.")
    declared = struct.unpack_from("<I", data, 4)[0]
    if declared != len(data):
        raise XboxAssetError(
            f"ShpX declares {declared} bytes but contains {len(data)}."
        )
    count = struct.unpack_from(">I", data, 8)[0]
    pos = 16
    result: list[fsh_archive.FshEntry] = []
    seen: dict[str, int] = {}
    for index in range(count):
        if pos + 9 > len(data):
            raise XboxAssetError("Truncated ShpX directory.")
        offset, size = struct.unpack_from(">II", data, pos)
        end = data.find(b"\0", pos + 8)
        if end < 0:
            raise XboxAssetError("Unterminated ShpX texture name.")
        name = data[pos + 8:end].decode("ascii")
        pos = end + 1
        if offset + size > len(data) or offset + 32 > len(data):
            raise XboxAssetError(f"Invalid ShpX entry {name!r}.")
        format_code, flags = struct.unpack_from("<HH", data, offset)
        width, height = struct.unpack_from("<II", data, offset + 24)
        occurrence = seen.get(name, 0)
        seen[name] = occurrence + 1
        result.append(
            fsh_archive.FshEntry(
                name, offset, size, width, height, format_code, flags, occurrence
            )
        )
    return tuple(result)


def _swizzled_address(x: int, y: int, width: int, height: int) -> int:
    """Xbox 2D Morton/tiled address for power-of-two P8 textures."""
    minimum = min(width, height)
    if minimum <= 0 or minimum & (minimum - 1):
        raise XboxAssetError("Xbox P8 unswizzle currently requires power-of-two dimensions.")
    bits = int(math.log2(minimum))
    address = 0
    for bit in range(bits):
        address |= ((x >> bit) & 1) << (2 * bit)
        address |= ((y >> bit) & 1) << (2 * bit + 1)
    if width > height:
        address |= (x >> bits) << (2 * bits)
    elif height > width:
        address |= (y >> bits) << (2 * bits)
    return address


def _palette_score(chunk: bytes) -> float:
    if len(chunk) != 1024:
        return -1.0
    alphas = chunk[3::4]
    extremes = sum(a in (0, 255) for a in alphas) / 256.0
    unique = len({chunk[i:i + 4] for i in range(0, 1024, 4)})
    return extremes * 100.0 + min(unique, 128) / 128.0 * 20.0


def _find_p8_palette(block: bytes, payload_offset: int, payload_size: int) -> bytes | None:
    """Locate a 256-entry BGRA palette near the end of a P8 Xbox image block."""
    candidates: set[int] = set()
    for off in (
        payload_offset + payload_size,
        payload_offset + payload_size + 16,
        payload_offset + payload_size + 32,
        payload_offset + payload_size + 64,
        len(block) - 1024,
        len(block) - 1088,
    ):
        if 0 <= off <= len(block) - 1024:
            candidates.add(off)

    # Some assets include mip data before/after the palette. Search the final
    # 4 KiB on 16-byte boundaries and select the most palette-like window.
    start = max(32, len(block) - 4096)
    candidates.update(range((start + 15) // 16 * 16, len(block) - 1024 + 1, 16))

    best: tuple[float, int] | None = None
    for off in candidates:
        score = _palette_score(block[off:off + 1024])
        if best is None or score > best[0]:
            best = (score, off)
    if best is None or best[0] < 65.0:
        return None
    return block[best[1]:best[1] + 1024]


def _decode_xbox_p8(block: bytes, width: int, height: int, fallback_palette: bytes | None = None) -> tuple[bytes, bytes]:
    payload_offset = struct.unpack_from("<I", block, 8)[0]
    payload_size = struct.unpack_from("<I", block, 12)[0]
    base_size = width * height
    if payload_offset < 32 or payload_offset + base_size > len(block):
        raise XboxAssetError("Xbox P8 base mip is truncated.")
    indices = block[payload_offset:payload_offset + base_size]
    palette_bytes = _find_p8_palette(block, payload_offset, payload_size)
    if palette_bytes is None:
        palette_bytes = fallback_palette
    if palette_bytes is None:
        raise XboxAssetError("Could not locate Xbox P8 palette and no reusable palette is available.")

    palette: list[tuple[int, int, int, int]] = []
    for i in range(256):
        b, g, r, a = palette_bytes[i * 4:i * 4 + 4]
        palette.append((r, g, b, a))

    rgba = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            source = _swizzled_address(x, y, width, height)
            if source >= len(indices):
                raise XboxAssetError("Xbox P8 swizzle address exceeds base mip.")
            color = palette[indices[source]]
            dest = (y * width + x) * 4
            rgba[dest:dest + 4] = bytes(color)
    return bytes(rgba), palette_bytes


def extract_xsh_bytes(
    data: bytes,
    destination: str | Path,
) -> dict[str, Path]:
    """Extract supported ShpX textures to PNG.

    Supported now:
      0x60 DXT1
      0x61 DXT3
      0x62 DXT5
      0x7B Xbox swizzled P8 + BGRA palette

    Unsupported individual entries are skipped so model import can continue.
    """
    entries = xsh_entries(data)
    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    output: dict[str, Path] = {}
    last_p8_palette: bytes | None = None

    for entry in entries:
        if entry.name in output:
            continue
        block = data[entry.offset:entry.offset + entry.size]
        fmt = block[0] & 0x7F
        try:
            if fmt in (0x60, 0x61, 0x62):
                payload_offset = struct.unpack_from("<I", block, 8)[0]
                payload_size = struct.unpack_from("<I", block, 12)[0]
                if payload_offset < 32 or payload_offset > len(block):
                    payload_offset = 32
                if payload_size <= 0 or payload_offset + payload_size > len(block):
                    payload_size = len(block) - payload_offset
                payload = block[payload_offset:payload_offset + payload_size]
                if fmt == 0x60:
                    rgba = fsh_archive._decode_dxt1(payload, entry.width, entry.height)
                elif fmt == 0x61:
                    rgba = fsh_archive._decode_dxt3(payload, entry.width, entry.height)
                else:
                    rgba = fsh_archive._decode_dxt5(payload, entry.width, entry.height)
            elif fmt == 0x7B:
                rgba, last_p8_palette = _decode_xbox_p8(
                    block, entry.width, entry.height, last_p8_palette
                )
            else:
                continue
            target = root / f"{fsh_archive.working_texture_name(entry.name)}.png"
            target.write_bytes(fsh_archive._rgba_to_png_bytes(entry.width, entry.height, rgba))
            output[entry.name] = target
        except (XboxAssetError, fsh_archive.FshError, struct.error):
            # One unusual texture must not prevent the EBO model itself loading.
            continue
    return output


def discover_viv_assets(viv_data: bytes) -> dict[str, dict[str, BigEntry]]:
    """Return supported Xbox arena EBO assets and their related XSH archives.

    Supported import stems include std, std_trans, crt, bbd and bbd_trans.
    Transparent variants intentionally share the parent asset's XSH archives.
    """
    entries = big_entries(viv_data)
    assets: dict[str, dict[str, BigEntry]] = {}
    suffixes = ("std", "std_trans", "crt", "bbd", "bbd_trans")

    for entry in entries:
        lower = entry.name.casefold()
        if not lower.endswith(".ebo"):
            continue
        stem = Path(entry.name).stem
        low_stem = stem.casefold()
        if not low_stem.endswith(suffixes):
            continue

        if low_stem.endswith("_trans"):
            texture_prefix = low_stem[:-6]
        else:
            texture_prefix = low_stem

        group: dict[str, BigEntry] = {"ebo": entry}
        for candidate in entries:
            cl = candidate.name.casefold()
            if not cl.endswith(".xsh"):
                continue
            candidate_stem = Path(candidate.name).stem.casefold()
            if candidate_stem.startswith(texture_prefix):
                group[candidate.name] = candidate
        assets[stem] = group

    return assets

