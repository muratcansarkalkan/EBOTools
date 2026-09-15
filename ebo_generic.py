#!/usr/bin/env python3
"""Generic NBA Live EBO v17 container primitives.

This module is intentionally asset-agnostic.  It handles the common EBO
container mechanisms verified against NBA Live 06 RMS, court, backboard,
player, and morph files:

- EboFileHeader
- local USD/type dictionary
- EboChunkHeader / EboChunkTOC
- imports + IAT fixups
- exports
- string pool
- exact round-trip of existing chunk payloads
- EA skin weight/bone packing
- EA morph RLE encode/decode

Higher-level Geometry, Material, RMS, skin, and morph semantic compilers can
sit on top of this layer without hard-coding a particular court/backboard
layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import struct
from typing import Iterable, Sequence


EBO_MAGIC = 0x004F4245  # b"EBO\0" little-endian
EBO_VERSION = 17
HEADER_SIZE = 0x60

_HEADER_FMT = "<IIIHHIIIIIHHHHH"
_HEADER_CORE_SIZE = struct.calcsize(_HEADER_FMT)

CHUNK_HEADER_SIZE = 0x14
TOC_SIZE = 0x10
IMPORT_SIZE = 0x18
EXPORT_SIZE = 0x0C


class EboError(ValueError):
    pass


def align_up(value: int, alignment: int = 4) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise EboError(f"Alignment must be a positive power of two, got {alignment}.")
    return (value + alignment - 1) & ~(alignment - 1)


def read_cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise EboError(f"Invalid string offset 0x{offset:X}.")
    end = data.find(b"\0", offset)
    if end < 0:
        raise EboError(f"Unterminated string at 0x{offset:X}.")
    try:
        return data[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise EboError(f"Non-ASCII EBO string at 0x{offset:X}.") from exc


@dataclass(frozen=True)
class EboHeader:
    version: int
    declared_size: int
    endian_original: int
    endian_current: int
    chunks_offset: int
    usd_offset: int
    imports_offset: int
    exports_offset: int
    strings_offset: int
    chunk_count: int
    usd_count: int
    import_count: int
    export_count: int
    string_count: int
    tail_bytes: bytes


@dataclass(frozen=True)
class EboChunkTOC:
    flags: int
    usd_index: int
    struct_count: int
    aligned_size: int
    relative_data_offset: int
    file_offset: int
    data_offset: int
    type_name: str


@dataclass(frozen=True)
class EboChunk:
    flags: int
    toc_count: int
    relative_toc_offset: int
    chunk_type: int
    version: int
    size: int
    file_offset: int
    tocs: tuple[EboChunkTOC, ...]
    raw: bytes


@dataclass(frozen=True)
class EboImport:
    type_name: str
    name: str
    file_offset: int
    iat_relative_offset: int
    fixup_field_offsets: tuple[int, ...]


@dataclass(frozen=True)
class EboExport:
    type_name: str
    name: str
    file_offset: int
    data_offset: int


@dataclass(frozen=True)
class EboFile:
    header: EboHeader
    usd_types: tuple[str, ...]
    strings: tuple[str, ...]
    string_prefix: bytes
    chunks: tuple[EboChunk, ...]
    imports: tuple[EboImport, ...]
    exports: tuple[EboExport, ...]
    source_data: bytes


def _parse_strings(data: bytes, strings_offset: int, count: int) -> tuple[bytes, tuple[str, ...], dict[int, str]]:
    # EA's serializer uses a 4-byte prefix before the first string.  The prefix
    # is not globally constant across all EBO families, so preserve it.
    if strings_offset + 4 > len(data):
        raise EboError("String table prefix extends beyond file.")
    prefix = data[strings_offset:strings_offset + 4]
    pos = strings_offset + 4
    strings: list[str] = []
    by_relative: dict[int, str] = {}

    for _ in range(count):
        rel = pos - strings_offset
        value = read_cstring(data, pos)
        strings.append(value)
        by_relative[rel] = value
        raw_len = len(value.encode("ascii")) + 1
        pos += raw_len
        # Shipped PC EBO string entries are 2-byte aligned.
        if raw_len & 1:
            pos += 1

    if pos > len(data):
        raise EboError("String table extends beyond file.")
    return prefix, tuple(strings), by_relative


def parse_ebo(data: bytes) -> EboFile:
    if len(data) < HEADER_SIZE:
        raise EboError("File is smaller than EboFileHeader.")
    fields = struct.unpack_from(_HEADER_FMT, data, 0)
    (
        magic,
        version,
        declared_size,
        endian_original,
        endian_current,
        chunks_offset,
        usd_offset,
        imports_offset,
        exports_offset,
        strings_offset,
        chunk_count,
        usd_count,
        import_count,
        export_count,
        string_count,
    ) = fields

    if magic != EBO_MAGIC:
        raise EboError("Not an EBO file.")
    if version != EBO_VERSION:
        raise EboError(f"Unsupported EBO version {version}; expected {EBO_VERSION}.")
    if declared_size != len(data):
        raise EboError(f"Declared EBO size {declared_size} != actual {len(data)}.")

    header = EboHeader(
        version=version,
        declared_size=declared_size,
        endian_original=endian_original,
        endian_current=endian_current,
        chunks_offset=chunks_offset,
        usd_offset=usd_offset,
        imports_offset=imports_offset,
        exports_offset=exports_offset,
        strings_offset=strings_offset,
        chunk_count=chunk_count,
        usd_count=usd_count,
        import_count=import_count,
        export_count=export_count,
        string_count=string_count,
        tail_bytes=data[_HEADER_CORE_SIZE:HEADER_SIZE],
    )

    prefix, strings, strings_by_rel = _parse_strings(data, strings_offset, string_count)

    def string_rel(rel: int) -> str:
        if rel == 0:
            return ""
        try:
            return strings_by_rel[rel]
        except KeyError as exc:
            raise EboError(f"Unknown string-pool offset 0x{rel:X}.") from exc

    usd_rel = [
        struct.unpack_from("<I", data, usd_offset + i * 4)[0]
        for i in range(usd_count)
    ]
    usd_types = tuple(string_rel(rel) for rel in usd_rel)

    chunks: list[EboChunk] = []
    cursor = chunks_offset
    for chunk_index in range(chunk_count):
        if cursor + CHUNK_HEADER_SIZE > len(data):
            raise EboError(f"Chunk {chunk_index} header exceeds file.")
        flags, toc_count, rel_toc, chunk_type, chunk_version, chunk_size = struct.unpack_from(
            "<HHIIII", data, cursor
        )
        if chunk_size < CHUNK_HEADER_SIZE or cursor + chunk_size > len(data):
            raise EboError(f"Chunk {chunk_index} has invalid size {chunk_size}.")

        toc_base = cursor + rel_toc
        tocs: list[EboChunkTOC] = []
        for toc_index in range(toc_count):
            toc_offset = toc_base + toc_index * TOC_SIZE
            tflags, usd_index, struct_count, aligned_size, rel_data = struct.unpack_from(
                "<HHIIi", data, toc_offset
            )
            if usd_index >= len(usd_types):
                raise EboError(
                    f"Chunk {chunk_index} TOC {toc_index} references USD {usd_index}, "
                    f"but only {len(usd_types)} types exist."
                )
            target = toc_offset + rel_data
            if not 0 <= target <= len(data):
                raise EboError(f"Chunk {chunk_index} TOC {toc_index} target is outside file.")
            tocs.append(
                EboChunkTOC(
                    flags=tflags,
                    usd_index=usd_index,
                    struct_count=struct_count,
                    aligned_size=aligned_size,
                    relative_data_offset=rel_data,
                    file_offset=toc_offset,
                    data_offset=target,
                    type_name=usd_types[usd_index],
                )
            )

        chunks.append(
            EboChunk(
                flags=flags,
                toc_count=toc_count,
                relative_toc_offset=rel_toc,
                chunk_type=chunk_type,
                version=chunk_version,
                size=chunk_size,
                file_offset=cursor,
                tocs=tuple(tocs),
                raw=data[cursor:cursor + chunk_size],
            )
        )
        cursor += chunk_size

    imports: list[EboImport] = []
    for index in range(import_count):
        offset = imports_offset + index * IMPORT_SIZE
        _next, _prev, type_rel, name_rel, iat_rel, iat_count = struct.unpack_from(
            "<IIIIII", data, offset
        )
        iat_start = offset + iat_rel
        fields: list[int] = []
        for i in range(iat_count):
            field_rel = struct.unpack_from("<i", data, iat_start + i * 4)[0]
            # EboIATEntry::oImportAddress is relative to the owning EboImport.
            fields.append(offset + field_rel)
        imports.append(
            EboImport(
                type_name=string_rel(type_rel),
                name=string_rel(name_rel),
                file_offset=offset,
                iat_relative_offset=iat_rel,
                fixup_field_offsets=tuple(fields),
            )
        )

    exports: list[EboExport] = []
    for index in range(export_count):
        offset = exports_offset + index * EXPORT_SIZE
        type_rel, name_rel, data_rel = struct.unpack_from("<IIi", data, offset)
        exports.append(
            EboExport(
                type_name=string_rel(type_rel),
                name=string_rel(name_rel),
                file_offset=offset,
                data_offset=offset + data_rel,
            )
        )

    return EboFile(
        header=header,
        usd_types=usd_types,
        strings=strings,
        string_prefix=prefix,
        chunks=tuple(chunks),
        imports=tuple(imports),
        exports=tuple(exports),
        source_data=data,
    )


def _build_string_pool(strings: Sequence[str], prefix: bytes) -> tuple[bytes, dict[str, int]]:
    if len(prefix) != 4:
        raise EboError("EBO string prefix must be exactly 4 bytes.")
    pool = bytearray(prefix)
    offsets: dict[str, int] = {}

    for value in strings:
        # EA GetStringOffset resolves the first equal string.
        offsets.setdefault(value, len(pool))
        raw = value.encode("ascii") + b"\0"
        pool += raw
        if len(raw) & 1:
            pool += b"\0"

    return bytes(pool), offsets


def rebuild_container_exact(ebo: EboFile) -> bytes:
    """Regenerate container tables around unchanged parsed chunk payloads.

    This deliberately does not reinterpret or mutate chunk payload structures.
    It is the stable migration layer for moving the existing tool away from
    hard-coded global EBO tables.  Higher-level semantic compilers can replace
    individual chunks later.
    """
    pool, string_offsets = _build_string_pool(ebo.strings, ebo.string_prefix)

    chunk_offsets: list[int] = []
    cursor = HEADER_SIZE
    for chunk in ebo.chunks:
        chunk_offsets.append(cursor)
        cursor += chunk.size

    usd_offset = align_up(cursor, 4)
    imports_offset = usd_offset + len(ebo.usd_types) * 4
    iat_count = sum(len(item.fixup_field_offsets) for item in ebo.imports)
    iat_offset = imports_offset + len(ebo.imports) * IMPORT_SIZE
    exports_offset = align_up(iat_offset + iat_count * 4, 4)
    strings_offset = align_up(exports_offset + len(ebo.exports) * EXPORT_SIZE, 4)
    final_size = strings_offset + len(pool)

    out = bytearray(final_size)
    struct.pack_into(
        _HEADER_FMT,
        out,
        0,
        EBO_MAGIC,
        ebo.header.version,
        final_size,
        ebo.header.endian_original,
        ebo.header.endian_current,
        HEADER_SIZE,
        usd_offset,
        imports_offset,
        exports_offset,
        strings_offset,
        len(ebo.chunks),
        len(ebo.usd_types),
        len(ebo.imports),
        len(ebo.exports),
        len(ebo.strings),
    )
    out[_HEADER_CORE_SIZE:HEADER_SIZE] = ebo.header.tail_bytes

    old_to_new_chunk: dict[int, int] = {}
    for chunk, new_offset in zip(ebo.chunks, chunk_offsets):
        old_to_new_chunk[chunk.file_offset] = new_offset
        out[new_offset:new_offset + chunk.size] = chunk.raw

    # Current migration path intentionally preserves chunk order and size.
    # Therefore chunk-internal EBO-base-relative fields remain at the same
    # absolute offsets.  Refuse silently-dangerous relocation for now.
    for old_offset, new_offset in old_to_new_chunk.items():
        if old_offset != new_offset:
            raise EboError(
                "Chunk relocation would require semantic pointer rewriting; "
                "use the higher-level serializer instead."
            )

    for index, type_name in enumerate(ebo.usd_types):
        struct.pack_into("<I", out, usd_offset + index * 4, string_offsets[type_name])

    iat_cursor = iat_offset
    for index, item in enumerate(ebo.imports):
        offset = imports_offset + index * IMPORT_SIZE
        struct.pack_into(
            "<IIIIII",
            out,
            offset,
            0,
            0,
            string_offsets[item.type_name],
            string_offsets[item.name],
            iat_cursor - offset,
            len(item.fixup_field_offsets),
        )
        for field_offset in item.fixup_field_offsets:
            struct.pack_into("<i", out, iat_cursor, field_offset - offset)
            iat_cursor += 4

    for index, item in enumerate(ebo.exports):
        offset = exports_offset + index * EXPORT_SIZE
        struct.pack_into(
            "<IIi",
            out,
            offset,
            string_offsets[item.type_name],
            string_offsets[item.name],
            item.data_offset - offset,
        )

    out[strings_offset:strings_offset + len(pool)] = pool
    return bytes(out)


# ---------------------------------------------------------------------------
# NBA Live PC skin palette helpers
# ---------------------------------------------------------------------------

def _float_to_u32(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(value)))[0]


def _u32_to_float(value: int) -> float:
    return struct.unpack("<f", struct.pack("<I", value & 0xFFFFFFFF))[0]


def pack_weight_bone(weight: float, bone_index: int) -> int:
    """Pack EA skin weight + 8-bit bone index into one 32-bit word."""
    if not 0 <= bone_index <= 0xFF:
        raise EboError(f"Bone index {bone_index} exceeds packed 8-bit range.")
    return (_float_to_u32(weight) & 0xFFFFFF00) | bone_index


def unpack_weight_bone(value: int) -> tuple[float, int]:
    bone = value & 0xFF
    weight = _u32_to_float(value & 0xFFFFFF00)
    return weight, bone


def influence_count(signature: Sequence[int], epsilon: float = 0.0001) -> int:
    if len(signature) != 4:
        raise EboError("Skin signature must contain exactly four packed components.")
    count = 1
    for packed in signature[1:]:
        weight, _bone = unpack_weight_bone(packed)
        if abs(weight) > epsilon:
            count += 1
    return count


@dataclass(frozen=True)
class SkinPalette:
    signatures: tuple[tuple[int, int, int, int], ...]
    palette_indices: tuple[int, ...]
    n4_weights: int
    n3_weights: int
    n2_weights: int
    n1_weights: int


def build_skin_palette(
    vertex_weights: Sequence[Sequence[float]],
    vertex_bones: Sequence[Sequence[int]],
) -> SkinPalette:
    """Build the compiled NBA Live PC palette from per-vertex 4-influence data.

    Final palette order verified from NBA Live 06 player files:
        1-weight, 2-weight, 3-weight, 4-weight.
    """
    if len(vertex_weights) != len(vertex_bones):
        raise EboError("Weight and bone arrays have different vertex counts.")

    unique: list[tuple[int, int, int, int]] = []
    original_indices: list[int] = []
    lookup: dict[tuple[int, int, int, int], int] = {}

    for weights, bones in zip(vertex_weights, vertex_bones):
        if len(weights) > 4 or len(bones) > 4:
            raise EboError("NBA Live PC compiled skin supports at most four influences.")
        padded_weights = list(weights[:4]) + [0.0] * (4 - len(weights))
        padded_bones = list(bones[:4]) + [0] * (4 - len(bones))
        packed = tuple(
            pack_weight_bone(weight, bone)
            for weight, bone in zip(padded_weights, padded_bones)
        )
        idx = lookup.get(packed)
        if idx is None:
            idx = len(unique)
            lookup[packed] = idx
            unique.append(packed)
        original_indices.append(idx)

    order = sorted(range(len(unique)), key=lambda i: influence_count(unique[i]))
    remap = {old: new for new, old in enumerate(order)}
    sorted_signatures = tuple(unique[i] for i in order)
    remapped_indices = tuple(remap[i] for i in original_indices)

    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for sig in sorted_signatures:
        counts[influence_count(sig)] += 1

    return SkinPalette(
        signatures=sorted_signatures,
        palette_indices=remapped_indices,
        n4_weights=counts[4],
        n3_weights=counts[3],
        n2_weights=counts[2],
        n1_weights=counts[1],
    )


# ---------------------------------------------------------------------------
# NBA Live morph RLE helpers
# ---------------------------------------------------------------------------

def decode_morph_rle(
    controls: bytes,
    payload: bytes,
    element_size: int,
) -> bytes:
    if element_size not in (1, 2, 4):
        raise EboError(f"Unsupported morph RLE element size {element_size}.")
    out = bytearray()
    payload_cursor = 0

    for control in controls:
        if control & 0x80:
            count = (control & 0x7F) + 1
            byte_count = count * element_size
            end = payload_cursor + byte_count
            if end > len(payload):
                raise EboError("Morph RLE literal block exceeds payload.")
            out += payload[payload_cursor:end]
            payload_cursor = end
        else:
            count = control + 1
            end = payload_cursor + element_size
            if end > len(payload):
                raise EboError("Morph RLE repeat block exceeds payload.")
            value = payload[payload_cursor:end]
            payload_cursor = end
            out += value * count

    if payload_cursor != len(payload):
        raise EboError(
            f"Morph RLE consumed {payload_cursor} bytes but payload has {len(payload)}."
        )
    return bytes(out)


def encode_morph_rle(raw: bytes, element_size: int) -> tuple[bytes, bytes]:
    """Encode EA's literal/repeat control stream.

    Returns (controls, payload).  The caller may choose raw storage when the
    compressed representation is not smaller.
    """
    if element_size not in (1, 2, 4):
        raise EboError(f"Unsupported morph RLE element size {element_size}.")
    if len(raw) % element_size:
        raise EboError("Morph raw data is not element-aligned.")

    elems = [
        raw[i:i + element_size]
        for i in range(0, len(raw), element_size)
    ]
    controls = bytearray()
    payload = bytearray()
    i = 0

    while i < len(elems):
        # Repeated run, max 128.
        run = 1
        while i + run < len(elems) and run < 128 and elems[i + run] == elems[i]:
            run += 1
        if run >= 2:
            controls.append(run - 1)
            payload += elems[i]
            i += run
            continue

        # Literal block until next repeat run or max 128.
        start = i
        i += 1
        while i < len(elems) and (i - start) < 128:
            lookahead = 1
            while (
                i + lookahead < len(elems)
                and lookahead < 128
                and elems[i + lookahead] == elems[i]
            ):
                lookahead += 1
            if lookahead >= 2:
                break
            i += 1

        count = i - start
        controls.append(0x80 | (count - 1))
        for elem in elems[start:i]:
            payload += elem

    return bytes(controls), bytes(payload)


def morph_fixed_point_element_size(fixed_point_type: int) -> int:
    mapping = {0: 4, 1: 1, 2: 2}
    try:
        return mapping[fixed_point_type]
    except KeyError as exc:
        raise EboError(f"Unknown MorphStreamHeader fixed-point type {fixed_point_type}.") from exc


def quantize_morph_value(value: float, scale: float, offset: float, fixed_point_type: int):
    if fixed_point_type == 0:
        return float(value)
    if scale == 0:
        raise EboError("Morph quantization scale cannot be zero.")
    normalized = (float(value) + float(offset)) / float(scale)
    if fixed_point_type == 1:
        return max(0, min(255, int(normalized * 255.0)))
    if fixed_point_type == 2:
        return max(0, min(65535, int(normalized * 65535.0)))
    raise EboError(f"Unknown fixed-point morph type {fixed_point_type}.")


def dequantize_morph_value(value: int | float, scale: float, offset: float, fixed_point_type: int) -> float:
    if fixed_point_type == 0:
        return float(value)
    maximum = 255.0 if fixed_point_type == 1 else 65535.0 if fixed_point_type == 2 else None
    if maximum is None:
        raise EboError(f"Unknown fixed-point morph type {fixed_point_type}.")
    return (float(value) / maximum) * float(scale) - float(offset)


def load_ebo(path: str | Path) -> EboFile:
    return parse_ebo(Path(path).read_bytes())


def roundtrip_file(source: str | Path, destination: str | Path) -> bool:
    source = Path(source)
    rebuilt = rebuild_container_exact(parse_ebo(source.read_bytes()))
    Path(destination).write_bytes(rebuilt)
    return rebuilt == source.read_bytes()
