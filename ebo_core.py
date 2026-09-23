#!/usr/bin/env python3
"""Inspect and round-trip NBA Live 2005/2006 court and stadium EBOs through OBJ.

Examples:
    python nba_live_court_tool.py inspect mempcrt.ebo
    python nba_live_court_tool.py export mempcrt.ebo mempcrt.obj
    python nba_live_court_tool.py patch mempcrt.ebo edited.obj mempcrt_new.ebo
    python nba_live_court_tool.py rebuild mempcrt.ebo edited.obj mempcrt_new.ebo

The patch command preserves vertex counts and original triangle strips. The
rebuild command permits topology changes within existing mesh/material groups.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import math
from dataclasses import dataclass
from pathlib import Path
import struct
import sys


class CourtFormatError(ValueError):
    """The file does not match the currently supported court EBO layout."""


# Canonical Blender-facing names for the six native backboard clock channels.
# The runtime itself remains gNbaShotClock_RMRuntime (06-08) or
# gShotClock_RMRuntime (05); these labels are semantic aliases only.
SHOTCLOCK_CHANNEL_NAMES = {
    0: "GameMinTens",
    1: "GameMinOnes",
    2: "GameSecTens",
    3: "GameSecOnes",
    4: "ShotClockTens",
    5: "ShotClockOnes",
}
SHOTCLOCK_CHANNEL_INDICES = {
    name.casefold(): index for index, name in SHOTCLOCK_CHANNEL_NAMES.items()
}


def shotclock_rms_alias(uv_index: int) -> str | None:
    """Return e.g. ``NBAShotClock_ShotClockTens`` for a native channel."""
    channel = SHOTCLOCK_CHANNEL_NAMES.get(int(uv_index))
    return f"NBAShotClock_{channel}" if channel else None


def shotclock_uv_index_from_alias(value: str) -> int | None:
    """Decode a Blender-facing NBAShotClock_* semantic alias."""
    label = str(value or "").strip()
    prefix = "NBAShotClock_"
    if not label.casefold().startswith(prefix.casefold()):
        return None
    channel = label[len(prefix):].strip().casefold()
    return SHOTCLOCK_CHANNEL_INDICES.get(channel)


@dataclass(frozen=True)
class Buffer:
    offset: int
    data_offset: int
    byte_count: int
    stride: int


@dataclass(frozen=True)
class Batch:
    mesh_name: str
    batch_index: int
    material: str
    vertex_count: int
    primitive_count: int
    positions: Buffer
    uvs: Buffer | None
    colors: Buffer | None
    indices: Buffer
    triangles: tuple[tuple[int, int, int], ...]
    normals: Buffer | None = None
    texture_names: tuple[str, ...] = ()
    profile: str = "STATIC_COLOR"
    palette_count: int = 0
    selector_offset: int | None = None
    selectors: tuple[int, ...] = ()
    # Structural descriptor metadata. Export code uses these offsets instead
    # of deciding binary layout from asset/profile names. None means that the
    # serialized representation has no corresponding field.
    descriptor_offset: int = 0
    pcdata_word: int | None = None
    count_word: int | None = None
    primitive_word: int | None = None
    palette_word: int | None = None
    selector_word: int | None = None
    # Native backboard shot-clock materials carry one Float4 whose first
    # component is a stable channel ordinal. Full-arena samples use
    # 0,1,2,3,5,4 for time,time,time,time,tnum,tnum.
    shotclock_uv_index: int | None = None


@dataclass(frozen=True)
class Mesh:
    name: str
    offset: int
    batches: tuple[Batch, ...]


@dataclass(frozen=True)
class Court:
    data: bytes
    meshes: tuple[Mesh, ...]

    @property
    def batches(self) -> tuple[Batch, ...]:
        return tuple(batch for mesh in self.meshes for batch in mesh.batches)

    @property
    def vertex_count(self) -> int:
        return sum(batch.vertex_count for batch in self.batches)

    @property
    def triangle_count(self) -> int:
        return sum(len(batch.triangles) for batch in self.batches)


@dataclass(frozen=True)
class ExternalVariableGroup:
    """Runtime bindings use offsets relative to their 24-byte group record."""

    name: str
    offset: int
    links_offset: int
    targets: tuple[int, ...]


@dataclass(frozen=True)
class MeshSerializerPreamble:
    mesh_name: str
    offset: int
    end: int
    record_count: int


def _read(data: bytes | bytearray, fmt: str, offset: int) -> tuple:
    size = struct.calcsize(fmt)
    if offset < 0 or offset + size > len(data):
        raise CourtFormatError(f"Read outside file at offset {offset} ({size} bytes).")
    return struct.unpack_from(fmt, data, offset)


def _cstring(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise CourtFormatError(f"Invalid string offset: {offset}.")
    end = data.find(b"\0", offset)
    if end < 0:
        raise CourtFormatError(f"Unterminated string at offset {offset}.")
    try:
        return data[offset:end].decode("ascii")
    except UnicodeDecodeError as exc:
        raise CourtFormatError(f"Non-ASCII name at offset {offset}.") from exc


def _buffer(data: bytes, offset: int, expected_stride: int, minimum_count: int) -> Buffer:
    byte_count, stride, data_offset = _read(data, "<3I", offset)
    if stride != expected_stride:
        raise CourtFormatError(
            f"Unexpected buffer stride at {offset}: {stride}, expected {expected_stride}."
        )
    if byte_count < minimum_count * stride:
        raise CourtFormatError(f"Buffer at {offset} is shorter than its declared elements.")
    if data_offset + byte_count > len(data):
        raise CourtFormatError(f"Buffer at {offset} extends beyond the file.")
    return Buffer(offset, data_offset, byte_count, stride)


def _strip_triangles(indices: tuple[int, ...], vertex_count: int) -> tuple[tuple[int, int, int], ...]:
    triangles: list[tuple[int, int, int]] = []
    for index, value in enumerate(indices):
        if value >= vertex_count:
            raise CourtFormatError(f"Index {value} exceeds vertex count {vertex_count}.")
        if index < 2:
            continue
        first, second, third = indices[index - 2], indices[index - 1], value
        if first == second or second == third or first == third:
            continue
        if index % 2:
            first, second = second, first
        triangles.append((first, second, third))
    return tuple(triangles)


def _looks_like_buffer(data: bytes, offset: int, stride: int) -> bool:
    if offset < 0 or offset + 24 > len(data):
        return False
    try:
        byte_count, actual_stride, data_offset = _read(data, "<III", offset)
    except (CourtFormatError, struct.error):
        return False
    return (
        actual_stride == stride
        and byte_count > 0
        and byte_count % stride == 0
        and 0 <= data_offset <= len(data) - byte_count
    )


def _discover_pcdata_word(data: bytes, descriptor_offset: int, words: tuple[int, ...],
                          index_buffer: int, vertex_buffers: tuple[int, ...]) -> int | None:
    """Find the descriptor field that points to PCDataBuffers from its contents."""
    wanted = set(vertex_buffers)
    for word_index, candidate in enumerate(words):
        if candidate <= 0 or candidate + 20 + 4 * len(vertex_buffers) > len(data):
            continue
        try:
            index_ptr, zero, vertex_count, num_vbs, zero2 = _read(data, "<5I", candidate)
            vb_ptrs = _read(data, f"<{num_vbs}I", candidate + 20) if 0 < num_vbs <= 8 else ()
        except (CourtFormatError, struct.error):
            continue
        if index_ptr == index_buffer and zero == 0 and zero2 == 0 and num_vbs == len(vertex_buffers):
            if set(vb_ptrs) == wanted:
                return word_index
    return None


def parse_court(data: bytes) -> Court:
    if len(data) < 48 or data[:4] != b"EBO\0":
        raise CourtFormatError("Not an EBO file.")
    version, declared_size = _read(data, "<2I", 4)
    if version != 17:
        raise CourtFormatError(f"Unsupported EBO container version: {version}.")
    if declared_size != len(data):
        raise CourtFormatError(f"Declared size {declared_size} differs from actual size {len(data)}.")

    mesh_table, string_table = _read(data, "<2I", 28)
    mesh_count = _read(data, "<H", 42)[0]
    if mesh_table + mesh_count * 12 != string_table:
        raise CourtFormatError("Mesh table size does not match the declared mesh count.")

    meshes: list[Mesh] = []
    for index in range(mesh_count):
        entry = mesh_table + index * 12
        kind, name_offset, relative_offset = _read(data, "<IIi", entry)
        record_type = "Geometry" if kind == 4 else _cstring(data, string_table + kind)
        if record_type != "Geometry":
            raise CourtFormatError(
                f"Unsupported object-record type {record_type!r} at offset {entry}."
            )
        mesh_offset = entry + 8 + relative_offset
        mesh_name = _cstring(data, string_table + name_offset)
        batch_count = _read(data, "<I", mesh_offset + 12)[0]
        batch_table = _read(data, "<I", mesh_offset + 16)[0]
        if batch_table != mesh_offset + 104:
            raise CourtFormatError(f"Unexpected material table location in {mesh_name}.")

        batches: list[Batch] = []
        for batch_index in range(batch_count):
            descriptor_offset = _read(data, "<I", batch_table + batch_index * 48 + 12)[0]
            fields = _read(data, "<9I", descriptor_offset)
            # Some RenderMethods pack multiple draw descriptors contiguously
            # behind one material pointer.  APT score geometry demonstrates a
            # two-draw record (leading count 3).  Expand those structurally.
            descriptor_candidates = [descriptor_offset]
            if fields[0] != 5:
                scan = descriptor_offset + 4
                found = []
                for _ in range(8):
                    if scan + 36 > len(data):
                        break
                    if _read(data, "<I", scan)[0] == 5:
                        f = _read(data, "<9I", scan)
                        if (_looks_like_buffer(data, f[1], 12) and
                            _looks_like_buffer(data, f[2], 4) and
                            _looks_like_buffer(data, f[3], 2)):
                            found.append(scan)
                            scan += 9 * 4
                            continue
                    scan += 4
                if not found:
                    raise CourtFormatError(f"Unsupported stream descriptor in {mesh_name}, batch {batch_index}.")
                # The current Blender model represents one material row as one
                # batch, so parse the first draw now; additional draws are
                # retained as a compound frontend profile for later expansion.
                descriptor_offset = found[0]
                fields = _read(data, "<9I", descriptor_offset)
            palette_count = 0
            selector_offset = None
            selectors: tuple[int, ...] = ()
            shotclock_uv_index = None
            pcdata_word = count_word = primitive_word = palette_word_meta = selector_word_meta = None
            # Static Geometry begins with direct position/UV/colour/index
            # pointers. Skinned models instead begin with compression data.
            # Balls and main/transparent backboards use layout A; reflection
            # and planar-shadow backboards use the shifted layout B.
            # APT/frontend RenderMethods (e.g. TextureScaleApt/GouraudApt)
            # serialize position + Colour + index streams.  They have no UV
            # buffer: UV placement is driven by the frontend RenderMethod.
            # Detect this from the buffers themselves rather than the asset name.
            layout_frontend = (
                _looks_like_buffer(data, fields[1], 12)
                and _looks_like_buffer(data, fields[2], 4)
                and _looks_like_buffer(data, fields[3], 2)
            )
            layout_a = (
                _looks_like_buffer(data, fields[4], 12)
                and _looks_like_buffer(data, fields[5], 12)
                and _looks_like_buffer(data, fields[7], 8)
                and _looks_like_buffer(data, fields[8], 2)
            )
            layout_b = (
                _looks_like_buffer(data, fields[3], 12)
                and (
                    _looks_like_buffer(data, fields[5], 8)
                    or _looks_like_buffer(data, fields[5], 4)
                )
            )
            layout_c = (
                _looks_like_buffer(data, fields[5], 12)
                and _looks_like_buffer(data, fields[6], 12)
                and _looks_like_buffer(data, fields[8], 8)
            )
            if layout_c:
                _c_ext = _read(data, "<18I", descriptor_offset)
                layout_c = _looks_like_buffer(data, _c_ext[9], 2)
            if layout_frontend:
                position_offset, color_offset, index_offset = fields[1], fields[2], fields[3]
                vertex_count = _read(data, "<I", position_offset)[0] // 12
                primitive_count = _read(data, "<I", index_offset)[0] // 2 - 2
                positions = _buffer(data, position_offset, 12, vertex_count)
                normals = None
                uvs = None
                colors = _buffer(data, color_offset, 4, vertex_count)
                texture_names = ()
                material = f"frontend_{batch_index:02d}"
                profile = "FRONTEND_COLOR"
                # Frontend descriptors vary in where PCDataBuffers is stored
                # (compound draw records can shift it). Discover it from the
                # PCData structure instead of mapping by profile name.
                frontend_words = _read(data, "<12I", descriptor_offset)
                pcdata_word = _discover_pcdata_word(
                    data, descriptor_offset, frontend_words,
                    index_offset, (position_offset, color_offset)
                )
                count_word, primitive_word = 4, 5
            elif layout_a:
                extended = _read(data, "<17I", descriptor_offset)
                position_offset, normal_offset = extended[4], extended[5]
                uv_offset, index_offset = extended[7], extended[8]
                vertex_count = _read(data, "<I", position_offset)[0] // 12
                primitive_count = _read(data, "<I", index_offset)[0] // 2 - 2
                # Texture string references follow the fixed player descriptor.
                # The word before PCData is not a texture count: NBA Live 06's
                # ball has two names here while that word remains one. Stop at
                # the first value that is not a safe string-table reference.
                discovered: list[str] = []
                for item in range(4):
                    relative = _read(data, "<I", descriptor_offset + 64 + item * 4)[0]
                    if relative % 2:
                        break
                    try:
                        candidate = _cstring(data, string_table + relative)
                        validate_material_name(candidate)
                    except CourtFormatError:
                        break
                    discovered.append(candidate)
                texture_names = tuple(discovered)
                if not texture_names:
                    raise CourtFormatError(f"Player material in {mesh_name} has no texture names.")
                positions = _buffer(data, position_offset, 12, vertex_count)
                normals = _buffer(data, normal_offset, 12, vertex_count)
                uvs = _buffer(data, uv_offset, 8, vertex_count)
                colors = None
                material = texture_names[0]
                profile = "PLAYER_NORMAL"
                pcdata_word, count_word, primitive_word = 15, 9, 10
                palette_word_meta, selector_word_meta = 2, 6
            elif layout_c:
                extended = _read(data, "<18I", descriptor_offset)
                position_offset, normal_offset = extended[5], extended[6]
                uv_offset, index_offset = extended[8], extended[9]
                vertex_count = _read(data, "<I", position_offset)[0] // 12
                primitive_count = _read(data, "<I", index_offset)[0] // 2 - 2
                relative = extended[17]
                texture_names = (_cstring(data, string_table + relative),)

                # Word 2 is the extra Float4 unique to the native backboard
                # shot-clock descriptor. Its first float is the channel ordinal.
                channel_block = extended[2]
                if 0 <= channel_block <= len(data) - 16:
                    channel_value = _read(data, "<f", channel_block)[0]
                    if math.isfinite(channel_value):
                        rounded = int(round(channel_value))
                        if (
                            abs(channel_value - rounded) <= 1.0e-5
                            and rounded in SHOTCLOCK_CHANNEL_NAMES
                        ):
                            shotclock_uv_index = rounded

                positions = _buffer(data, position_offset, 12, vertex_count)
                normals = _buffer(data, normal_offset, 12, vertex_count)
                uvs = _buffer(data, uv_offset, 8, vertex_count)
                colors = None
                material = texture_names[0]
                profile = "BACKBOARD_SHOTCLOCK"
                pcdata_word, count_word, primitive_word = 16, 10, 11
                palette_word_meta, selector_word_meta = 3, 7
            elif layout_b:
                extended = _read(data, "<16I", descriptor_offset)
                position_offset = extended[3]
                colors = None
                # Reflection geometry has UV at word 6 and indices at word 7.
                # Planar shadows omit UV and put indices directly at word 6.
                stream_stride = _read(data, "<I", extended[5] + 4)[0]
                if stream_stride == 8:
                    vertex_count, primitive_count = extended[8], extended[9]
                    uvs = _buffer(data, extended[5], 8, vertex_count)
                    normals = None
                    colors = _buffer(data, extended[6], 4, vertex_count)
                    index_offset = extended[7]
                    relative = extended[15]
                    texture_names = (_cstring(data, string_table + relative),)
                    material = texture_names[0]
                    profile = "BACKBOARD_REFLECTION"
                    pcdata_word, count_word, primitive_word = 14, 8, 9
                    palette_word_meta, selector_word_meta = 1, 4
                elif stream_stride == 4:
                    vertex_count, primitive_count = extended[7], extended[8]
                    normals = None
                    colors = _buffer(data, extended[5], 4, vertex_count)
                    uvs = None
                    index_offset = extended[6]
                    texture_names = ()
                    material = f"shadow_{batch_index:02d}"
                    profile = "BACKBOARD_SHADOW"
                    pcdata_word, count_word, primitive_word = 13, 7, 8
                    palette_word_meta, selector_word_meta = 1, 4
                else:
                    raise CourtFormatError(
                        f"Unsupported backboard stream stride {stream_stride} in {mesh_name}."
                    )
                positions = _buffer(data, position_offset, 12, vertex_count)
            else:
                _, position_offset, uv_offset, color_offset, index_offset = fields[:5]
                vertex_count, primitive_count, _, material_offset = fields[5:]
                positions = _buffer(data, position_offset, 12, vertex_count)
                normals = None
                uvs = _buffer(data, uv_offset, 8, vertex_count)
                colors = _buffer(data, color_offset, 4, vertex_count)
                texture_names = (_cstring(data, string_table + material_offset),)
                material = texture_names[0]
                profile = "STATIC_COLOR"
            # Specialized backboard-style descriptors may carry a raw i16
            # per-vertex local-palette selector outside PCDataBuffers.  Only
            # expose it when the candidate is self-validating: one selector
            # per vertex and every value falls inside the declared palette.
            if selector_word_meta is not None and vertex_count:
                candidate_palette = extended[palette_word_meta]
                candidate_offset = extended[selector_word_meta]
                if 0 < candidate_palette <= 1024 and 0 <= candidate_offset <= len(data) - vertex_count * 2:
                    candidate = _read(data, f"<{vertex_count}H", candidate_offset)
                    if candidate and max(candidate) < candidate_palette:
                        palette_count = candidate_palette
                        selector_offset = candidate_offset
                        selectors = tuple(candidate)

            if not vertex_count:
                raise CourtFormatError(f"Material in {mesh_name} contains no vertices.")
            # A triangle strip needs its two initial vertices in addition to the
            # primitive count stored in the material descriptor.
            indices = _buffer(data, index_offset, 2, primitive_count + 2)
            strip = _read(data, f"<{primitive_count + 2}H", indices.data_offset)
            batches.append(
                Batch(
                    mesh_name=mesh_name,
                    batch_index=batch_index,
                    material=material,
                    vertex_count=vertex_count,
                    primitive_count=primitive_count,
                    positions=positions,
                    uvs=uvs,
                    colors=colors,
                    indices=indices,
                    triangles=_strip_triangles(strip, vertex_count),
                    normals=normals,
                    texture_names=texture_names,
                    profile=profile,
                    palette_count=palette_count,
                    selector_offset=selector_offset,
                    selectors=selectors,
                    descriptor_offset=descriptor_offset,
                    pcdata_word=pcdata_word,
                    count_word=count_word,
                    primitive_word=primitive_word,
                    palette_word=palette_word_meta,
                    selector_word=selector_word_meta,
                    shotclock_uv_index=shotclock_uv_index,
                )
            )
        meshes.append(Mesh(mesh_name, mesh_offset, tuple(batches)))
    return Court(data, tuple(meshes))


def validate_transform_selectors(court: Court) -> tuple[str, ...]:
    """Validate detected per-vertex local-palette selector streams."""
    reports: list[str] = []
    for batch in court.batches:
        if not batch.selectors:
            continue
        if len(batch.selectors) != batch.vertex_count:
            raise CourtFormatError(
                f"Material {batch.material!r} has {len(batch.selectors)} selectors for "
                f"{batch.vertex_count} vertices."
            )
        if batch.palette_count <= 0:
            raise CourtFormatError(f"Material {batch.material!r} has selectors but no palette.")
        invalid = [value for value in batch.selectors if value >= batch.palette_count]
        if invalid:
            raise CourtFormatError(
                f"Material {batch.material!r} has selector {invalid[0]} outside palette "
                f"0..{batch.palette_count - 1}."
            )
        reports.append(
            f"{batch.mesh_name}/{batch.material}: {batch.vertex_count} selectors, "
            f"palette {batch.palette_count}, range {min(batch.selectors)}..{max(batch.selectors)}"
        )
    return tuple(reports)


def external_variable_groups(court: Court) -> tuple[ExternalVariableGroup, ...]:
    data = court.data
    external_table, mesh_table, string_table = _read(data, "<3I", 24)
    count = _read(data, "<H", 40)[0]
    groups: list[ExternalVariableGroup] = []
    minimum = external_table + count * 24
    for index in range(count):
        offset = external_table + index * 24
        _, _, _, name_offset, relative_links, link_count = _read(data, "<6I", offset)
        links_offset = offset + relative_links
        if links_offset < minimum or links_offset + link_count * 4 > mesh_table:
            raise CourtFormatError(f"External-variable group {index} has invalid runtime bindings.")
        targets = tuple(
            offset + _read(data, "<i", links_offset + item * 4)[0]
            for item in range(link_count)
        )
        if any(not 0 <= target < external_table for target in targets):
            raise CourtFormatError(f"External-variable group {index} points outside EBO geometry.")
        groups.append(
            ExternalVariableGroup(
                _cstring(data, string_table + name_offset),
                offset,
                links_offset,
                targets,
            )
        )
    return tuple(groups)


def validate_material_bindings(court: Court) -> None:
    """Reject EBOs the game cannot bind even if their mesh data can be parsed."""
    groups = external_variable_groups(court)
    if not groups:
        return
    targets: dict[int, list[str]] = {}
    for group in groups:
        for target in group.targets:
            targets.setdefault(target, []).append(group.name)
    missing: list[str] = []
    duplicate: list[str] = []
    for mesh in court.meshes:
        for batch in mesh.batches:
            row = mesh.offset + 104 + batch.batch_index * 48
            bindings = targets.get(row, [])
            if not bindings:
                missing.append(f"{mesh.name}:{batch.material}")
            elif len(bindings) > 1:
                duplicate.append(f"{mesh.name}:{batch.material}")
    if missing or duplicate:
        raise CourtFormatError(
            "EBO material runtime bindings are invalid; "
            f"missing={missing}, duplicate={duplicate}."
        )


def validate_serializer_metadata(court: Court) -> None:
    for mesh in court.meshes:
        first_descriptor = _read(court.data, "<I", mesh.offset + 116)[0]
        metadata = first_descriptor + len(mesh.batches) * 36
        encoded = _read(court.data, "<I", metadata + 20)[0]
        actual = encoded >> 16
        expected = len(mesh.batches) * 9
        if actual != expected:
            raise CourtFormatError(
                f"Object {mesh.name!r} declares {actual} serializer records; "
                f"{len(mesh.batches)} material groups require {expected}."
            )


def validate_stream_headers(court: Court) -> None:
    """Game loaders require the complete template-specific PC buffer headers."""
    for mesh in court.meshes:
        reference = mesh.batches[0]
        for field in ("positions", "uvs", "colors", "indices"):
            reference_buffer = getattr(reference, field)
            expected = reference_buffer.data_offset - reference_buffer.offset
            for batch in mesh.batches:
                buffer = getattr(batch, field)
                actual = buffer.data_offset - buffer.offset
                if actual != expected:
                    raise CourtFormatError(
                        f"Object {mesh.name!r}, material {batch.material!r} has a "
                        f"{actual}-byte {field} header; the game template requires {expected} bytes."
                    )


def mesh_serializer_preambles(court: Court) -> tuple[MeshSerializerPreamble, ...]:
    section = _read(court.data, "<I", 16)[0]
    if not section:
        return ()
    preambles: list[MeshSerializerPreamble] = []
    previous_end = section
    for mesh in court.meshes:
        if previous_end + 76 > mesh.offset:
            raise CourtFormatError(f"Object {mesh.name!r} is missing its outer serializer preamble.")
        encoded = _read(court.data, "<I", previous_end)[0]
        records = encoded >> 16
        expected = len(mesh.batches) * 5 + 3
        declared_batches = _read(court.data, "<I", previous_end + 56)[0]
        expected_size = len(mesh.batches) * 80 + 76
        actual_size = mesh.offset - previous_end
        if records != expected or declared_batches != len(mesh.batches) or actual_size != expected_size:
            raise CourtFormatError(
                f"Object {mesh.name!r} has an invalid outer serializer: "
                f"records={records}/{expected}, batches={declared_batches}/{len(mesh.batches)}, "
                f"bytes={actual_size}/{expected_size}."
            )
        first_descriptor = _read(court.data, "<I", mesh.offset + 116)[0]
        metadata = first_descriptor + len(mesh.batches) * 36
        descriptors = [
            _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            for batch in mesh.batches
        ]
        expected_targets = [
            metadata + 16,
            mesh.offset + 4,
            mesh.offset + 76,
            mesh.offset + 104 + 12,
            descriptors[0] + 12,
            descriptors[0] + 16,
            descriptors[0] + 32,
        ]
        for descriptor in descriptors[1:]:
            expected_targets.extend(
                (descriptor + 4, descriptor + 8, descriptor + 12, descriptor + 16, descriptor + 32)
            )
        expected_targets.append(metadata + 4)
        for record_index, expected_target in enumerate(expected_targets):
            record = previous_end + 16 + record_index * 16
            actual_target = record + _read(court.data, "<I", record)[0]
            if actual_target != expected_target:
                raise CourtFormatError(
                    f"Object {mesh.name!r} outer serializer record {record_index} "
                    f"points to {actual_target}, expected {expected_target}."
                )
        trailer = mesh.offset - 12
        trailer_target = trailer + _read(court.data, "<I", trailer)[0]
        if trailer_target != metadata + 8:
            raise CourtFormatError(
                f"Object {mesh.name!r} outer serializer trailer points to "
                f"{trailer_target}, expected {metadata + 8}."
            )
        preambles.append(MeshSerializerPreamble(mesh.name, previous_end, mesh.offset, records))
        previous_end = metadata + 20 + _read(court.data, "<I", metadata + 36)[0]
    return tuple(preambles)


def normalize_material_strings(court: Court, *, template: Court | None = None) -> Court:
    """Keep known strings intact while aligning newly appended texture names."""
    string_table = _read(court.data, "<I", 32)[0]
    current_strings = court.data[string_table:]
    if template is not None:
        template_table = _read(template.data, "<I", 32)[0]
        template_strings = template.data[template_table:]
        if current_strings.startswith(template_strings):
            data = bytearray(court.data[:string_table] + template_strings)
        else:
            data = bytearray(court.data)
    else:
        data = bytearray(court.data)

    offsets: dict[str, int] = {}
    for mesh in court.meshes:
        for batch in mesh.batches:
            descriptor = _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            original_offset = _read(court.data, "<I", descriptor + 32)[0]
            absolute = string_table + original_offset
            if (
                original_offset % 2 == 0
                and absolute < len(data)
                and _cstring(bytes(data), absolute) == batch.material
            ):
                offsets.setdefault(batch.material, original_offset)
    for mesh in court.meshes:
        for batch in mesh.batches:
            if batch.material not in offsets:
                data.extend(b"\0" * (-len(data) % 2))
                offsets[batch.material] = len(data) - string_table
                data.extend(batch.material.encode("ascii") + b"\0")
            descriptor = _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            _replace(data, descriptor + 32, "<I", offsets[batch.material])
    data.extend(b"\0" * (-len(data) % 4))
    _replace(data, 8, "<I", len(data))
    return parse_court(bytes(data))


def repair_material_bindings(court: Court, *, template: Court | None = None) -> Court:
    """Rebuild game-runtime material links while preserving existing geometry."""
    groups = external_variable_groups(court)
    if not groups:
        raise CourtFormatError("This EBO has no external-variable groups to repair.")

    def row_owners(value: Court) -> dict[int, tuple[str, str]]:
        return {
            mesh.offset + 104 + batch.batch_index * 48: (mesh.name, batch.material)
            for mesh in value.meshes
            for batch in mesh.batches
        }

    rows = row_owners(court)
    template_owners: dict[tuple[str, str], str] = {}
    if template is not None:
        original_rows = row_owners(template)
        for group in external_variable_groups(template):
            for target in group.targets:
                owner = original_rows.get(target)
                if owner is not None:
                    template_owners[owner] = group.name

    current_owners: dict[tuple[str, str], str] = {}
    material_group_names: set[str] = set()
    for group in groups:
        for target in group.targets:
            owner = rows.get(target)
            if owner is not None:
                current_owners[owner] = group.name
                material_group_names.add(group.name)
    if not material_group_names:
        raise CourtFormatError("Cannot identify an EBO game-runtime texture binding group.")
    normal_groups = [
        group.name for group in groups
        if group.name in material_group_names and "scroll" not in group.name.lower()
    ]
    default_group = normal_groups[0] if normal_groups else next(iter(material_group_names))

    desired: dict[str, list[int]] = {group.name: [] for group in groups}
    for group in groups:
        desired[group.name].extend(target for target in group.targets if target not in rows)
    for mesh in court.meshes:
        for batch in mesh.batches:
            owner = mesh.name, batch.material
            group_name = template_owners.get(owner, current_owners.get(owner, default_group))
            if group_name not in desired:
                group_name = default_group
            desired[group_name].append(mesh.offset + 104 + batch.batch_index * 48)

    old_external, old_mesh_table, old_string_table = _read(court.data, "<3I", 24)
    links_start = old_external + len(groups) * 24
    old_links_size = old_mesh_table - links_start
    links = bytearray()
    group_starts: dict[str, int] = {}
    for group in groups:
        group_starts[group.name] = links_start + len(links)
        for target in desired[group.name]:
            links.extend(struct.pack("<i", target - group.offset))
    difference = len(links) - old_links_size
    data = bytearray(court.data[:links_start] + links + court.data[old_mesh_table:])
    _replace(data, 8, "<I", len(data))
    _replace(data, 28, "<I", old_mesh_table + difference)
    _replace(data, 32, "<I", old_string_table + difference)
    for group in groups:
        _replace(data, group.offset + 16, "<I", group_starts[group.name] - group.offset)
        _replace(data, group.offset + 20, "<I", len(desired[group.name]))
    for index, mesh in enumerate(court.meshes):
        location = old_mesh_table + difference + index * 12 + 8
        _replace(data, location, "<i", mesh.offset - location)
        first_descriptor = _read(court.data, "<I", mesh.offset + 116)[0]
        metadata = first_descriptor + len(mesh.batches) * 36
        encoded = _read(court.data, "<I", metadata + 20)[0]
        _replace(data, metadata + 20, "<I", (encoded & 0xFFFF) | (len(mesh.batches) * 9 << 16))
    repaired = parse_court(bytes(data))
    repaired = normalize_material_strings(repaired, template=template)
    validate_material_bindings(repaired)
    validate_serializer_metadata(repaired)
    return repaired


def _number(value: float) -> str:
    # V coordinates are flipped in float64 before being written. Seventeen
    # digits preserve that intermediate value, including tiny source UVs near
    # zero that would otherwise disappear when represented as 1 - v.
    return format(value, ".17g")


def export_obj(court: Court, obj_path: Path, *, flip_v: bool, texture_extension: str) -> None:
    mtl_path = obj_path.with_suffix(".mtl")
    materials = dict.fromkeys(batch.material for batch in court.batches)
    lines = [
        "# NBA Live 2005/2006 court/stadium EBO export",
        "# Use patch for existing vertices, or rebuild after topology changes.",
        "# Vertex lines include the common OBJ RGB vertex-color extension.",
        f"mtllib {mtl_path.name}",
        "",
    ]
    vertex_base = 1
    for mesh in court.meshes:
        lines.extend((f"o {mesh.name}", ""))
        for batch in mesh.batches:
            lines.append(f"g {mesh.name}__batch{batch.batch_index:02d}__{batch.material}")
            for index in range(batch.vertex_count):
                x, y, z = _read(court.data, "<3f", batch.positions.data_offset + index * 12)
                # EBO color buffers store BGRA bytes; OBJ and Blender expect RGB.
                blue, green, red, _ = _read(court.data, "<4B", batch.colors.data_offset + index * 4)
                lines.append(
                    "v " + " ".join(_number(value) for value in (x, y, z))
                    + " " + " ".join(_number(value / 255) for value in (red, green, blue))
                )
            for index in range(batch.vertex_count):
                u, v = _read(court.data, "<2f", batch.uvs.data_offset + index * 8)
                lines.append(f"vt {_number(u)} {_number(1 - v if flip_v else v)}")
            lines.append(f"usemtl {batch.material}")
            for first, second, third in batch.triangles:
                a, b, c = first + vertex_base, second + vertex_base, third + vertex_base
                lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
            lines.append("")
            vertex_base += batch.vertex_count

    obj_path.parent.mkdir(parents=True, exist_ok=True)
    obj_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    mtl_lines = ["# NBA Live material names; put matching textures beside this file.", ""]
    extension = texture_extension if texture_extension.startswith(".") else "." + texture_extension
    for material in materials:
        mtl_lines.extend((f"newmtl {material}", "Ka 1.000000 1.000000 1.000000", "Kd 1.000000 1.000000 1.000000"))
        if texture_extension:
            mtl_lines.append(f"map_Kd {material}{extension}")
        mtl_lines.append("")
    mtl_path.write_text("\n".join(mtl_lines) + "\n", encoding="utf-8")


def _read_obj(path: Path) -> tuple[list[tuple[float, float, float]], list[tuple[float, float] | None], list[tuple[int, int, int] | None]]:
    vertices: list[tuple[float, float, float]] = []
    texture_vertices: list[tuple[float, float]] = []
    colors: list[tuple[int, int, int] | None] = []
    uv_by_vertex: dict[int, tuple[float, float]] = {}

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        fields = raw_line.strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        try:
            if fields[0] == "v":
                vertices.append(tuple(float(value) for value in fields[1:4]))
                if len(vertices[-1]) != 3:
                    raise ValueError("vertex requires three coordinates")
                colors.append(
                    tuple(max(0, min(255, round(float(value) * 255))) for value in fields[4:7])
                    if len(fields) >= 7 else None
                )
            elif fields[0] == "vt":
                texture_vertices.append((float(fields[1]), float(fields[2])))
            elif fields[0] == "f":
                for item in fields[1:]:
                    parts = item.split("/")
                    if len(parts) < 2 or not parts[1]:
                        continue
                    vertex_index = int(parts[0])
                    uv_index = int(parts[1])
                    vertex_index = vertex_index - 1 if vertex_index > 0 else len(vertices) + vertex_index
                    uv_index = uv_index - 1 if uv_index > 0 else len(texture_vertices) + uv_index
                    uv = texture_vertices[uv_index]
                    previous = uv_by_vertex.get(vertex_index)
                    if previous is not None and previous != uv:
                        raise CourtFormatError(
                            f"OBJ vertex {vertex_index + 1} has multiple UV coordinates; "
                            "the original EBO supports one UV per vertex."
                        )
                    uv_by_vertex[vertex_index] = uv
        except (IndexError, ValueError) as exc:
            raise CourtFormatError(f"Invalid OBJ data on line {line_number}: {raw_line}") from exc

    resolved_uvs: list[tuple[float, float] | None] = []
    for index in range(len(vertices)):
        resolved_uvs.append(
            uv_by_vertex.get(index, texture_vertices[index] if len(texture_vertices) == len(vertices) else None)
        )
    return vertices, resolved_uvs, colors


def _replace(data: bytearray, offset: int, fmt: str, *values: float | int) -> bool:
    packed = struct.pack(fmt, *values)
    if data[offset:offset + len(packed)] == packed:
        return False
    data[offset:offset + len(packed)] = packed
    return True


def patch_court(court: Court, obj_path: Path, *, flip_v: bool, update_uvs: bool, update_colors: bool) -> tuple[bytes, int]:
    vertices, uvs, colors = _read_obj(obj_path)
    if len(vertices) != court.vertex_count:
        raise CourtFormatError(
            f"OBJ contains {len(vertices)} vertices; the template requires {court.vertex_count}. "
            "Do not add, remove, or merge vertices."
        )

    data = bytearray(court.data)
    global_index = 0
    changed_vertices = 0
    for mesh in court.meshes:
        mesh_positions: list[tuple[float, float, float]] = []
        positions_changed = False
        for batch in mesh.batches:
            for local_index in range(batch.vertex_count):
                position = vertices[global_index]
                if not all(math.isfinite(value) for value in position):
                    raise CourtFormatError(f"OBJ vertex {global_index + 1} contains a non-finite coordinate.")
                changed = _replace(data, batch.positions.data_offset + local_index * 12, "<3f", *position)
                positions_changed |= changed
                changed_vertices += changed
                mesh_positions.append(position)

                uv = uvs[global_index]
                if update_uvs and uv is not None:
                    u, v = uv
                    if not math.isfinite(u) or not math.isfinite(v):
                        raise CourtFormatError(f"OBJ vertex {global_index + 1} contains a non-finite UV.")
                    _replace(data, batch.uvs.data_offset + local_index * 8, "<2f", u, 1 - v if flip_v else v)

                color = colors[global_index]
                if update_colors and color is not None:
                    alpha = data[batch.colors.data_offset + local_index * 4 + 3]
                    red, green, blue = color
                    _replace(data, batch.colors.data_offset + local_index * 4, "<4B", blue, green, red, alpha)
                global_index += 1

        if positions_changed:
            minimum = tuple(min(position[axis] for position in mesh_positions) for axis in range(3))
            maximum = tuple(max(position[axis] for position in mesh_positions) for axis in range(3))
            center = tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))
            radius = math.sqrt(sum(((maximum[axis] - minimum[axis]) / 2) ** 2 for axis in range(3)))
            _replace(data, mesh.offset + 64, "<10f", *minimum, *maximum, *center, radius)
    return bytes(data), changed_vertices


@dataclass(frozen=True)
class RebuiltBatch:
    positions: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    colors: tuple[tuple[int, int, int, int], ...]
    triangles: tuple[tuple[int, int, int], ...]
    strip: tuple[int, ...]
    selectors: tuple[int, ...] = ()


@dataclass(frozen=True)
class NewMaterialBatch:
    """A material group cloned from a compatible group on the same mesh."""

    mesh_name: str
    material: str
    template_batch_index: int


def validate_material_name(name: str) -> str:
    """EBO strings and FSH image names must remain safe ASCII file basenames."""
    if not isinstance(name, str) or not name or name != name.strip():
        raise CourtFormatError("A material/texture name cannot be empty or contain surrounding whitespace.")
    try:
        encoded = name.encode("ascii")
    except UnicodeEncodeError as exc:
        raise CourtFormatError(f"Material/texture name {name!r} must contain ASCII characters only.") from exc
    if len(encoded) > 255 or any(character in name for character in '/\\:*?"<>|'):
        raise CourtFormatError(f"Material/texture name {name!r} is not a safe PNG/FSH entry name.")
    if any(ord(character) < 32 for character in name) or name in {".", ".."}:
        raise CourtFormatError(f"Material/texture name {name!r} contains an invalid character.")
    return name


def add_material_batches(court: Court, additions: tuple[NewMaterialBatch, ...]) -> Court:
    """Grow decoded mesh/batch/serializer tables using existing batch templates.

    Each new group initially contains a byte-for-byte copy of its source
    geometry. ``rebuild_from_batches`` subsequently substitutes the edited
    Blender geometry using the now-expanded, ordinary EBO template.
    """
    expanded = court
    for addition in additions:
        expanded = _add_material_batch(expanded, addition)
    return expanded


def remove_material_batches(court: Court, removals: tuple[tuple[str, str], ...]) -> Court:
    """Remove uniquely-named groups while preserving shared strings and FSH ownership."""
    reduced = court
    for mesh_name, material in removals:
        reduced = _remove_material_batch(reduced, mesh_name, material=material)
    return reduced


def remove_material_batch_indices(court: Court, removals: tuple[tuple[str, int], ...]) -> Court:
    """Remove concrete material rows by mesh/batch index.

    This is the preferred API when several rows intentionally share one
    texture name but use different runtime bindings. Indices are removed in
    descending order per mesh so earlier indices remain stable.
    """
    reduced = court
    grouped: dict[str, list[int]] = {}
    for mesh_name, batch_index in removals:
        grouped.setdefault(mesh_name, []).append(int(batch_index))
    for mesh_name, indices in grouped.items():
        for batch_index in sorted(set(indices), reverse=True):
            reduced = _remove_material_batch(reduced, mesh_name, batch_index=batch_index)
    return reduced


def _remove_material_batch(
    court: Court,
    mesh_name: str,
    *,
    material: str | None = None,
    batch_index: int | None = None,
) -> Court:
    mesh = next((item for item in court.meshes if item.name == mesh_name), None)
    if mesh is None:
        raise CourtFormatError(f"Cannot remove a material from unknown EBO object {mesh_name!r}.")
    if batch_index is not None:
        matches = [batch for batch in mesh.batches if batch.batch_index == batch_index]
        label = f"batch {batch_index}"
    else:
        if material is None:
            raise CourtFormatError("Material removal needs a name or batch index.")
        matches = [batch for batch in mesh.batches if batch.material == material]
        label = repr(material)
    if len(matches) != 1:
        raise CourtFormatError(f"Object {mesh.name!r} has no unique material group {label}.")
    if len(mesh.batches) <= 1:
        raise CourtFormatError(f"Object {mesh.name!r} must retain at least one EBO material group.")

    removed = matches[0]
    material = removed.material
    count = len(mesh.batches)
    row = mesh.offset + 104 + removed.batch_index * 48
    descriptor = _read(court.data, "<I", row + 12)[0]
    first_descriptor = _read(court.data, "<I", mesh.offset + 116)[0]
    metadata = first_descriptor + count * 36
    inner_group = metadata + 40 + removed.batch_index * 144
    pc_data = _read(court.data, "<I", descriptor + 28)[0]
    geometry_end = pc_data + 32
    if not removed.positions.offset < geometry_end:
        raise CourtFormatError(f"Material {material!r} has an invalid geometry buffer range.")

    groups = external_variable_groups(court)
    preambles = mesh_serializer_preambles(court)
    selected = next((item for item in preambles if item.mesh_name == mesh.name), None)
    ranges: list[tuple[int, int, str]] = [
        (row, row + 48, "row"),
        (descriptor, descriptor + 36, "descriptor"),
        (inner_group, inner_group + 144, "serializer"),
        (removed.positions.offset, geometry_end, "geometry"),
    ]
    if selected is not None:
        ranges.append((selected.end - 92, selected.end - 12, "outer_serializer"))
    deleted_links: set[int] = set()
    for group in groups:
        for index, target in enumerate(group.targets):
            if row <= target < row + 48:
                location = group.links_offset + index * 4
                deleted_links.add(location)
                ranges.append((location, location + 4, "runtime_binding"))
    if groups and not deleted_links:
        raise CourtFormatError(f"Material {material!r} has no removable game-runtime binding.")

    ranges.sort(key=lambda item: item[0])
    parts: list[bytes] = []
    cursor = 0
    for start, end, _ in ranges:
        if start < cursor or end < start:
            raise CourtFormatError("Overlapping EBO material regions prevent safe removal.")
        parts.append(court.data[cursor:start])
        cursor = end
    parts.append(court.data[cursor:])
    data = bytearray(b"".join(parts))

    def moved(offset: int) -> int:
        for start, end, label in ranges:
            if start < offset < end:
                raise CourtFormatError(f"An EBO pointer still enters removed {label} data.")
        return offset - sum(end - start for start, end, _ in ranges if end <= offset)

    _replace(data, 8, "<I", len(data))
    for location in (20, 24, 28, 32):
        _replace(data, location, "<I", moved(_read(court.data, "<I", location)[0]))

    for group in groups:
        new_offset = moved(group.offset)
        remaining_targets = [target for target in group.targets if not row <= target < row + 48]
        _replace(data, new_offset + 16, "<I", moved(group.links_offset) - new_offset)
        _replace(data, new_offset + 20, "<I", len(remaining_targets))
        for index, target in enumerate(group.targets):
            old_link = group.links_offset + index * 4
            if old_link in deleted_links:
                continue
            _replace(data, moved(old_link), "<i", moved(target) - new_offset)

    old_mesh_table = _read(court.data, "<I", 28)[0]
    for mesh_index, current in enumerate(court.meshes):
        kept = [
            batch for batch in current.batches
            if not (current.name == mesh.name and batch.batch_index == removed.batch_index)
        ]
        new_mesh = moved(current.offset)
        _replace(data, new_mesh + 12, "<I", len(kept))
        _replace(data, new_mesh + 16, "<I", new_mesh + 104)
        _replace(data, new_mesh + 52, "<I", moved(_read(court.data, "<I", current.offset + 52)[0]))

        old_first = _read(court.data, "<I", current.offset + 116)[0]
        old_metadata = old_first + len(current.batches) * 36
        old_marker = old_metadata + 20
        old_end = old_marker + _read(court.data, "<I", old_metadata + 36)[0]
        new_metadata = moved(old_metadata)
        _replace(data, new_metadata + 36, "<I", moved(old_end) - moved(old_marker))
        if current.name == mesh.name:
            encoded = _read(court.data, "<I", old_metadata + 20)[0]
            _replace(data, new_metadata + 20, "<I", (encoded & 0xFFFF) | (len(kept) * 9 << 16))

        for batch in kept:
            old_row = current.offset + 104 + batch.batch_index * 48
            old_desc = _read(court.data, "<I", old_row + 12)[0]
            new_desc = moved(old_desc)
            _replace(data, moved(old_row + 12), "<I", new_desc)
            old_pc = _read(court.data, "<I", old_desc + 28)[0]
            streams = (batch.positions, batch.uvs, batch.colors, batch.indices)
            _replace(data, new_desc + 4, "<4I", *(moved(stream.offset) for stream in streams))
            _replace(data, new_desc + 28, "<I", moved(old_pc))
            for stream_index, stream in enumerate(streams):
                _replace(data, moved(stream.offset + 8), "<I", moved(stream.data_offset))
                old_group = old_metadata + 40 + batch.batch_index * 144 + stream_index * 32
                new_group = moved(old_group)
                _replace(data, new_group + 12, "<I", moved(stream.offset) - new_group)
                pointer = stream.offset + (12 if stream_index < 3 else 8)
                _replace(data, new_group + 28, "<I", moved(pointer) - new_group)
            new_pc = moved(old_pc)
            _replace(data, new_pc, "<I", moved(batch.indices.offset))
            _replace(data, new_pc + 20, "<3I", *(moved(stream.offset) for stream in streams[:3]))
            old_pc_group = old_metadata + 40 + batch.batch_index * 144 + 128
            _replace(data, moved(old_pc_group) + 12, "<I", new_pc - moved(old_pc_group))

        table_location = old_mesh_table + mesh_index * 12 + 8
        _replace(data, moved(table_location), "<i", new_mesh - moved(table_location))

        if current.name == mesh.name:
            positions = [
                _read(court.data, "<3f", batch.positions.data_offset + index * 12)
                for batch in kept
                for index in range(batch.vertex_count)
            ]
            minimum = tuple(min(position[axis] for position in positions) for axis in range(3))
            maximum = tuple(max(position[axis] for position in positions) for axis in range(3))
            center = tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))
            radius = math.sqrt(sum(((maximum[axis] - minimum[axis]) / 2) ** 2 for axis in range(3)))
            _replace(data, new_mesh + 64, "<10f", *minimum, *maximum, *center, radius)

    for preamble in preambles:
        current = next(item for item in court.meshes if item.name == preamble.mesh_name)
        kept = [
            batch for batch in current.batches
            if not (current.name == mesh.name and batch.batch_index == removed.batch_index)
        ]
        new_start = moved(preamble.offset)
        new_mesh = moved(current.offset)
        old_first = _read(court.data, "<I", current.offset + 116)[0]
        new_metadata = moved(old_first + len(current.batches) * 36)
        if current.name == mesh.name:
            encoded = _read(court.data, "<I", preamble.offset)[0]
            _replace(data, new_start, "<I", (encoded & 0xFFFF) | ((len(kept) * 5 + 3) << 16))
            _replace(data, new_start + 56, "<I", len(kept))
        descriptors = [
            moved(_read(court.data, "<I", current.offset + 116 + batch.batch_index * 48)[0])
            for batch in kept
        ]
        targets = [
            new_metadata + 16,
            new_mesh + 4,
            new_mesh + 76,
            new_mesh + 116,
            descriptors[0] + 12,
            descriptors[0] + 16,
            descriptors[0] + 32,
        ]
        for item in descriptors[1:]:
            targets.extend((item + 4, item + 8, item + 12, item + 16, item + 32))
        targets.append(new_metadata + 4)
        for index, target in enumerate(targets):
            record = new_start + 16 + index * 16
            _replace(data, record, "<I", target - record)
        trailer = new_mesh - 12
        _replace(data, trailer, "<I", new_metadata + 8 - trailer)

    verified = parse_court(bytes(data))
    validate_material_bindings(verified)
    validate_serializer_metadata(verified)
    validate_stream_headers(verified)
    mesh_serializer_preambles(verified)
    verified_mesh = next(item for item in verified.meshes if item.name == mesh.name)
    if len(verified_mesh.batches) != count - 1:
        raise CourtFormatError(f"Removing material row {material!r} failed EBO structure verification.")
    return verified


def rename_material_batches(court: Court, names: dict[tuple[str, int], str]) -> Court:
    """Append new strings and retarget existing material descriptors safely."""
    if not names:
        return court
    known = {(batch.mesh_name, batch.batch_index) for batch in court.batches}
    unexpected = set(names) - known
    if unexpected:
        raise CourtFormatError(f"Cannot rename unknown EBO material groups: {sorted(unexpected)}.")
    data = bytearray(court.data)
    string_table = _read(court.data, "<I", 32)[0]
    offsets: dict[str, int] = {}
    for mesh in court.meshes:
        for batch in mesh.batches:
            descriptor = _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            offsets.setdefault(batch.material, _read(court.data, "<I", descriptor + 32)[0])
    for mesh in court.meshes:
        resulting_names: list[str] = []
        for batch in mesh.batches:
            name = validate_material_name(names.get((mesh.name, batch.batch_index), batch.material))
            resulting_names.append(name)
            if name not in offsets:
                data.extend(b"\0" * (-len(data) % 2))
                offsets[name] = len(data) - string_table
                data.extend(name.encode("ascii") + b"\0")
            descriptor = _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            _replace(data, descriptor + 32, "<I", offsets[name])
        # Texture names are not material identities. Multiple material rows may
        # intentionally share one texture while using different RMRuntime bindings.
    data.extend(b"\0" * (-len(data) % 4))
    _replace(data, 8, "<I", len(data))
    return parse_court(bytes(data))


def _add_material_batch(court: Court, addition: NewMaterialBatch) -> Court:
    name = validate_material_name(addition.material)
    mesh = next((item for item in court.meshes if item.name == addition.mesh_name), None)
    if mesh is None:
        raise CourtFormatError(f"Cannot add a material to unknown EBO object {addition.mesh_name!r}.")
    if not 0 <= addition.template_batch_index < len(mesh.batches):
        raise CourtFormatError(f"Object {mesh.name!r} has no template material group {addition.template_batch_index}.")
    template = mesh.batches[addition.template_batch_index]
    count = len(mesh.batches)
    batch_table = mesh.offset + 104
    first_descriptor = _read(court.data, "<I", batch_table + 12)[0]
    metadata_start = first_descriptor + count * 36
    group_start = metadata_start + 40
    if template.positions.offset < group_start or mesh.batches[0].positions.offset != group_start + count * 144:
        raise CourtFormatError(f"Object {mesh.name!r} has unsupported material serializer metadata.")
    old_external_table = _read(court.data, "<I", 24)[0]
    old_string_table = _read(court.data, "<I", 32)[0]
    serializer_marker = metadata_start + 20
    serializer_end = serializer_marker + _read(court.data, "<I", metadata_start + 36)[0]
    old_descriptor = _read(court.data, "<I", batch_table + addition.template_batch_index * 48 + 12)[0]
    old_pc_data = _read(court.data, "<I", old_descriptor + 28)[0]
    if not old_pc_data + 32 <= serializer_end <= old_external_table:
        raise CourtFormatError(f"Object {mesh.name!r} has an unsupported serializer boundary.")

    row = court.data[
        batch_table + addition.template_batch_index * 48:
        batch_table + (addition.template_batch_index + 1) * 48
    ]
    descriptor = court.data[old_descriptor:old_descriptor + 36]
    serializer = court.data[
        group_start + addition.template_batch_index * 144:
        group_start + (addition.template_batch_index + 1) * 144
    ]

    payload = bytearray()
    stream_local: list[tuple[int, int, int]] = []
    for stream_index, buffer in enumerate((template.positions, template.uvs, template.colors, template.indices)):
        payload.extend(b"\xdf" * (-len(payload) % 4))
        header_offset = len(payload)
        # Real game assets include additional PC runtime fields after the
        # three values decoded by _buffer: normally 28 bytes for vertex
        # streams and 24 for indices. Preserve the complete source header.
        header_size = buffer.data_offset - buffer.offset
        minimum_header = 16 if stream_index < 3 else 12
        if header_size < minimum_header or header_size % 4:
            raise CourtFormatError(
                f"Template material {template.material!r} has an invalid stream header."
            )
        payload.extend(court.data[buffer.offset:buffer.offset + header_size])
        data_offset = len(payload)
        payload.extend(court.data[buffer.data_offset:buffer.data_offset + buffer.byte_count])
        payload.extend(b"\xdf" * (-len(payload) % 4))
        stream_local.append((header_offset, data_offset, buffer.byte_count))
    pc_local = len(payload)
    payload.extend(court.data[old_pc_data:old_pc_data + 32])

    groups = external_variable_groups(court)
    preambles = mesh_serializer_preambles(court)
    selected_preamble = next((item for item in preambles if item.mesh_name == mesh.name), None)
    template_row = batch_table + addition.template_batch_index * 48
    cloned_bindings: list[tuple[int, int, int]] = []
    for group_index, group in enumerate(groups):
        for target in group.targets:
            if template_row <= target < template_row + 48:
                insertion_index = bisect_right(group.targets, batch_table + count * 48)
                cloned_bindings.append((group_index, target - template_row, insertion_index))
    if groups and not cloned_bindings:
        raise CourtFormatError(
            f"Template material {template.material!r} has no game-runtime texture binding to clone."
        )

    name_padding = (-len(court.data)) % 2
    name_block = b"\0" * name_padding + name.encode("ascii") + b"\0"
    name_block += b"\0" * (-(len(court.data) + len(name_block)) % 4)
    events = [
        (batch_table + count * 48, 0, row, "row"),
        (first_descriptor + count * 36, 1, descriptor, "descriptor"),
        (group_start + count * 144, 2, serializer, "serializer"),
        (serializer_end, 3, bytes(payload), "payload"),
        (len(court.data), 4, name_block, "name"),
    ]
    if selected_preamble is not None:
        records_end = selected_preamble.end - 12
        last_batch_records = court.data[records_end - 80:records_end]
        events.append((records_end, -1, last_batch_records, "preamble"))
    for binding_index, (group_index, _, insertion_index) in enumerate(cloned_bindings):
        group = groups[group_index]
        events.append(
            (
                group.links_offset + insertion_index * 4,
                4 + binding_index,
                b"\0" * 4,
                f"binding_{binding_index}",
            )
        )
    events.sort(key=lambda event: (event[0], event[1]))
    locations: dict[str, int] = {}
    pieces: list[bytes] = []
    cursor = 0
    delta = 0
    for offset, _, block, label in events:
        if offset < cursor:
            raise CourtFormatError("Overlapping EBO material-table insertions prevent a safe rebuild.")
        pieces.append(court.data[cursor:offset])
        locations[label] = offset + delta
        pieces.append(block)
        cursor = offset
        delta += len(block)
    pieces.append(court.data[cursor:])
    data = bytearray(b"".join(pieces))

    def moved(offset: int) -> int:
        return offset + sum(len(block) for point, _, block, _ in events if point <= offset)

    _replace(data, 8, "<I", len(data))
    for location in (20, 24, 28, 32):
        old_value = _read(court.data, "<I", location)[0]
        _replace(data, location, "<I", moved(old_value))

    for preamble in preambles:
        new_preamble = moved(preamble.offset)
        if preamble.mesh_name == mesh.name:
            encoded = _read(court.data, "<I", preamble.offset)[0]
            _replace(data, new_preamble, "<I", (encoded & 0xFFFF) | ((preamble.record_count + 5) << 16))
            _replace(data, new_preamble + 56, "<I", len(mesh.batches) + 1)
        for record_index in range(preamble.record_count):
            old_record = preamble.offset + 16 + record_index * 16
            old_target = old_record + _read(court.data, "<I", old_record)[0]
            new_record = moved(old_record)
            _replace(data, new_record, "<I", moved(old_target) - new_record)
        old_trailer = preamble.end - 12
        old_target = old_trailer + _read(court.data, "<I", old_trailer)[0]
        new_trailer = moved(old_trailer)
        _replace(data, new_trailer, "<I", moved(old_target) - new_trailer)

    old_mesh_table = _read(court.data, "<I", 28)[0]
    for group_index, group in enumerate(groups):
        new_group_offset = moved(group.offset)
        new_links_offset = moved(group.links_offset)
        for binding_index, (bound_group, _, insertion_index) in enumerate(cloned_bindings):
            if bound_group == group_index and insertion_index == 0:
                new_links_offset = min(new_links_offset, locations[f"binding_{binding_index}"])
        _replace(data, new_group_offset + 16, "<I", new_links_offset - new_group_offset)
        added_count = sum(index == group_index for index, _, _ in cloned_bindings)
        _replace(data, new_group_offset + 20, "<I", len(group.targets) + added_count)
        for link_index, target in enumerate(group.targets):
            old_link = group.links_offset + link_index * 4
            _replace(data, moved(old_link), "<i", moved(target) - new_group_offset)

    for mesh_index, current in enumerate(court.meshes):
        new_mesh_offset = moved(current.offset)
        current_count = len(current.batches)
        _replace(data, new_mesh_offset + 12, "<I", current_count + int(current.name == mesh.name))
        _replace(data, new_mesh_offset + 16, "<I", moved(current.offset + 104))
        old_bounds = _read(court.data, "<I", current.offset + 52)[0]
        _replace(data, new_mesh_offset + 52, "<I", moved(old_bounds))
        first = _read(court.data, "<I", current.offset + 116)[0]
        old_metadata = first + current_count * 36
        old_marker = old_metadata + 20
        old_target = old_marker + _read(court.data, "<I", old_metadata + 36)[0]
        _replace(data, moved(old_metadata + 36), "<I", moved(old_target) - moved(old_marker))
        if current.name == mesh.name:
            old_encoded = _read(court.data, "<I", old_metadata + 20)[0]
            _replace(
                data,
                moved(old_metadata + 20),
                "<I",
                (old_encoded & 0xFFFF) | ((current_count + 1) * 9 << 16),
            )

        for current_batch in current.batches:
            old_desc = _read(court.data, "<I", current.offset + 116 + current_batch.batch_index * 48)[0]
            new_desc = moved(old_desc)
            _replace(data, moved(current.offset + 116 + current_batch.batch_index * 48), "<I", new_desc)
            old_pc = _read(court.data, "<I", old_desc + 28)[0]
            streams = (current_batch.positions, current_batch.uvs, current_batch.colors, current_batch.indices)
            _replace(data, new_desc + 4, "<4I", *(moved(stream.offset) for stream in streams))
            _replace(data, new_desc + 28, "<I", moved(old_pc))
            for stream_index, stream in enumerate(streams):
                _replace(data, moved(stream.offset + 8), "<I", moved(stream.data_offset))
                group = old_metadata + 40 + current_batch.batch_index * 144 + stream_index * 32
                _replace(data, moved(group + 12), "<I", moved(stream.offset) - moved(group))
                pointer_field = stream.offset + (12 if stream_index < 3 else 8)
                _replace(data, moved(group + 28), "<I", moved(pointer_field) - moved(group))
            new_pc = moved(old_pc)
            _replace(data, new_pc, "<I", moved(current_batch.indices.offset))
            _replace(data, new_pc + 20, "<3I", *(moved(stream.offset) for stream in streams[:3]))
            pc_group = old_metadata + 40 + current_batch.batch_index * 144 + 128
            _replace(data, moved(pc_group + 12), "<I", new_pc - moved(pc_group))

        table_location = old_mesh_table + mesh_index * 12 + 8
        _replace(data, moved(table_location), "<i", new_mesh_offset - moved(table_location))

    new_row = locations["row"]
    new_descriptor = locations["descriptor"]
    new_group = locations["serializer"]
    new_payload = locations["payload"]
    new_pc = new_payload + pc_local
    streams_absolute = tuple(new_payload + item[0] for item in stream_local)
    _replace(data, new_row + 12, "<I", new_descriptor)
    _replace(data, new_descriptor + 4, "<4I", *streams_absolute)
    _replace(data, new_descriptor + 28, "<I", new_pc)
    _replace(
        data,
        new_descriptor + 32,
        "<I",
        locations["name"] + name_padding - moved(old_string_table),
    )
    for stream_index, (header, stream_data, byte_count) in enumerate(stream_local):
        absolute = new_payload + header
        _replace(data, absolute, "<I", byte_count)
        _replace(data, absolute + 8, "<I", new_payload + stream_data)
        group = new_group + stream_index * 32
        _replace(data, group + 12, "<I", absolute - group)
        # Different Geometry compilers serialize array lengths either as
        # bytes (courts/stadiums) or elements (for example TextureGlowRef).
        # The cloned serializer already contains the template convention.
        _replace(
            data,
            group + 20,
            "<I",
            _read(serializer, "<I", stream_index * 32 + 20)[0],
        )
        pointer_field = absolute + (12 if stream_index < 3 else 8)
        _replace(data, group + 28, "<I", pointer_field - group)
    _replace(data, new_group + 128 + 12, "<I", new_pc - (new_group + 128))
    _replace(data, new_pc, "<I", streams_absolute[3])
    _replace(data, new_pc + 20, "<3I", *streams_absolute[:3])
    if selected_preamble is not None:
        old_final_record = selected_preamble.end - 28
        previous_final_record = moved(old_final_record)
        _replace(data, previous_final_record, "<I", new_descriptor + 4 - previous_final_record)
        inserted_records = locations["preamble"]
        new_metadata = moved(metadata_start)
        targets = (
            new_descriptor + 8,
            new_descriptor + 12,
            new_descriptor + 16,
            new_descriptor + 32,
            new_metadata + 4,
        )
        for record_index, target in enumerate(targets):
            record = inserted_records + record_index * 16
            _replace(data, record, "<I", target - record)
    for binding_index, (group_index, target_offset, _) in enumerate(cloned_bindings):
        new_group_offset = moved(groups[group_index].offset)
        _replace(
            data,
            locations[f"binding_{binding_index}"],
            "<i",
            new_row + target_offset - new_group_offset,
        )

    verified = parse_court(bytes(data))
    expanded_mesh = next(item for item in verified.meshes if item.name == mesh.name)
    new_batch = expanded_mesh.batches[-1]
    if new_batch.material != name or new_batch.triangles != template.triangles:
        raise CourtFormatError(f"New material group {name!r} failed EBO structure verification.")
    validate_material_bindings(verified)
    validate_serializer_metadata(verified)
    validate_stream_headers(verified)
    mesh_serializer_preambles(verified)
    return verified


def _obj_index(value: str, count: int) -> int:
    index = int(value)
    if index == 0:
        raise CourtFormatError("OBJ indices cannot be zero.")
    index = index - 1 if index > 0 else count + index
    if not 0 <= index < count:
        raise CourtFormatError(f"OBJ index {value} is outside the available range.")
    return index


def _triangles_to_strip(triangles: tuple[tuple[int, int, int], ...]) -> tuple[int, ...]:
    if not triangles:
        raise CourtFormatError("Every existing mesh/material group must retain at least one triangle.")
    strip = list(triangles[0])
    for first, second, third in triangles[1:]:
        # Degenerate connector triangles permit arbitrary triangle topology
        # while keeping the EBO's existing triangle-strip rendering mode.
        if (len(strip) + 4) % 2:
            first, second = second, first
        strip.extend((strip[-1], first, first, second, third))
    rebuilt = tuple(strip)
    if _strip_triangles(rebuilt, max(rebuilt) + 1) != triangles:
        raise CourtFormatError("Could not create a valid triangle strip for the edited mesh.")
    return rebuilt


def _oriented_triangle(triangle: tuple[int, int, int]) -> tuple[int, int, int]:
    """Canonicalize cyclic rotations without treating reversed winding as equal."""
    first, second, third = triangle
    return min((first, second, third), (second, third, first), (third, first, second))


def _same_oriented_triangles(
    first: tuple[tuple[int, int, int], ...],
    second: tuple[tuple[int, int, int], ...],
) -> bool:
    # Blender is free to rotate a triangle's starting corner and to return the
    # tessellated faces in a different order.  Neither change alters topology,
    # so preserve the original game strip as long as winding and membership
    # are unchanged.
    return len(first) == len(second) and sorted(map(_oriented_triangle, first)) == sorted(
        map(_oriented_triangle, second)
    )


def _added_triangles(
    original: tuple[tuple[int, int, int], ...],
    edited: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[int, int, int], ...] | None:
    """Return added faces when an edit preserves every original oriented face."""
    remaining = Counter(map(_oriented_triangle, edited))
    for triangle in original:
        key = _oriented_triangle(triangle)
        if not remaining[key]:
            return None
        remaining[key] -= 1
    additions: list[tuple[int, int, int]] = []
    for triangle in edited:
        key = _oriented_triangle(triangle)
        if remaining[key]:
            additions.append(triangle)
            remaining[key] -= 1
    return tuple(additions)


def _append_strip_triangles(
    original_strip: tuple[int, ...],
    additions: tuple[tuple[int, int, int], ...],
    vertex_count: int,
) -> tuple[int, ...]:
    """Attach disconnected faces to an existing strip with degenerate links."""
    strip = list(original_strip)
    original_triangles = _strip_triangles(original_strip, vertex_count)
    for first, second, third in additions:
        if (len(strip) + 4) % 2:
            first, second = second, first
        strip.extend((strip[-1], first, first, second, third))
    rebuilt = tuple(strip)
    if _strip_triangles(rebuilt, vertex_count) != original_triangles + additions:
        raise CourtFormatError("Could not extend the original triangle strip.")
    return rebuilt





def _frontend_triangles_to_strip(
    triangles: tuple[tuple[int, int, int], ...],
    vertex_count: int,
) -> tuple[int, ...]:
    """Build compact strip runs for frontend geometry, including disconnected islands."""
    if not triangles:
        return ()
    remaining = list(triangles)
    runs: list[list[int]] = []
    while remaining:
        first = remaining.pop(0)
        run = [first[0], first[1], first[2]]
        while remaining:
            index = len(run)
            a, b = run[-2], run[-1]
            if index % 2:
                a, b = b, a
            found = value = None
            for i, tri in enumerate(remaining):
                x, y, z = tri
                for u, v, w in ((x, y, z), (y, z, x), (z, x, y)):
                    if u == a and v == b:
                        found, value = i, w
                        break
                if found is not None:
                    break
            if found is None:
                break
            run.append(value)
            remaining.pop(found)
        runs.append(run)

    strip = list(runs[0])
    for run in runs[1:]:
        x, y, *tail = run
        # Degenerate bridge. Adjust orientation for the destination run.
        if (len(strip) + 4) % 2:
            x, y = y, x
        strip.extend((strip[-1], x, x, y, *tail))
    rebuilt = tuple(strip)
    if not _same_oriented_triangles(_strip_triangles(rebuilt, vertex_count), triangles):
        raise CourtFormatError("Could not encode frontend triangles as compact strips.")
    return rebuilt

def _append_frontend_strip_triangles(
    original_strip: tuple[int, ...],
    additions: tuple[tuple[int, int, int], ...],
    vertex_count: int,
) -> tuple[int, ...]:
    """Append frontend faces as connected runs instead of one bridge per face."""
    if not additions:
        return original_strip
    remaining = list(additions)
    runs: list[list[int]] = []
    while remaining:
        first = remaining.pop(0)
        run = [first[0], first[1], first[2]]
        while remaining:
            index = len(run)
            a, b = run[-2], run[-1]
            if index % 2:
                a, b = b, a
            found = None
            value = None
            for i, tri in enumerate(remaining):
                x, y, z = tri
                for u, v, w in ((x, y, z), (y, z, x), (z, x, y)):
                    if u == a and v == b:
                        found, value = i, w
                        break
                if found is not None:
                    break
            if found is None:
                break
            run.append(value)
            remaining.pop(found)
        runs.append(run)

    strip = list(original_strip)
    for run in runs:
        x, y, *tail = run
        # Bridge to the run with degenerates, then continue its strip.
        if (len(strip) + 4) % 2:
            x, y = y, x
        strip.extend((strip[-1], x, x, y, *tail))
    rebuilt = tuple(strip)
    expected = _strip_triangles(original_strip, vertex_count) + additions
    if not _same_oriented_triangles(_strip_triangles(rebuilt, vertex_count), expected):
        raise CourtFormatError("Could not extend frontend triangle strip compactly.")
    return rebuilt

def _edited_specialized_strip(
    original_strip: tuple[int, ...],
    original_triangles: tuple[tuple[int, int, int], ...],
    edited_triangles: tuple[tuple[int, int, int], ...],
    vertex_count: int,
) -> tuple[int, ...]:
    """Prefer EA's original strip; otherwise build adjacency-connected runs.

    Additive edits preserve the original strip byte-for-byte and append only
    the genuinely new faces. Destructive/rewired edits cannot safely retain
    the old strip wholesale, so build long connected runs before inserting a
    degenerate bridge. This avoids the previous five-index bridge per face.
    """
    additions = _added_triangles(original_triangles, edited_triangles)
    if additions is not None:
        return _append_strip_triangles(original_strip, additions, vertex_count)

    remaining = list(edited_triangles)
    if not remaining:
        raise CourtFormatError("Every existing mesh/material group must retain at least one triangle.")

    # Keep Blender's first triangle as the first run seed.  A triangle may be
    # cyclically rotated without changing its winding.
    first = remaining.pop(0)
    strip = [first[0], first[1], first[2]]

    while remaining:
        # Appending one index creates a triangle from the strip's final edge.
        # Find a same-winding triangle that can continue that edge.
        index = len(strip)
        a, b = strip[-2], strip[-1]
        if index % 2:
            a, b = b, a

        found = None
        next_value = None
        for i, tri in enumerate(remaining):
            x, y, z = tri
            for u, v, w in ((x, y, z), (y, z, x), (z, x, y)):
                if u == a and v == b:
                    found = i
                    next_value = w
                    break
            if found is not None:
                break

        if found is not None:
            strip.append(next_value)
            remaining.pop(found)
            continue

        # Start a new disconnected run.  Degenerates make the bridge invisible.
        x, y, z = remaining.pop(0)
        if (len(strip) + 4) % 2:
            x, y = y, x
        strip.extend((strip[-1], x, x, y, z))

    rebuilt = tuple(strip)
    if not _same_oriented_triangles(_strip_triangles(rebuilt, vertex_count), edited_triangles):
        raise CourtFormatError("Could not create a valid compact strip for the edited specialized mesh.")
    return rebuilt

def _parse_rebuild_obj(court: Court, path: Path, *, flip_v: bool) -> dict[tuple[str, int], RebuiltBatch]:
    mesh_names = {mesh.name for mesh in court.meshes}
    batches_by_material = {
        (mesh.name, batch.material): batch
        for mesh in court.meshes for batch in mesh.batches
    }
    if len(batches_by_material) != len(court.batches):
        raise CourtFormatError("A mesh uses the same material more than once; explicit batch groups are required.")

    positions: list[tuple[float, float, float]] = []
    colors: list[tuple[int, int, int] | None] = []
    texture_vertices: list[tuple[float, float]] = []
    owned_vertices: dict[tuple[str, int], list[int]] = {}
    faces: dict[tuple[str, int], list[tuple[tuple[int, int | None], ...]]] = {}
    active_mesh: str | None = None
    active_batch: Batch | None = None
    active_material: str | None = None

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        fields = raw_line.strip().split()
        if not fields or fields[0].startswith("#"):
            continue
        try:
            command = fields[0]
            if command == "o":
                active_mesh = " ".join(fields[1:])
                if active_mesh not in mesh_names:
                    raise CourtFormatError(
                        f"Unknown OBJ object {active_mesh!r}; preserve the original EBO mesh names."
                    )
                active_batch = None
                active_material = None
            elif command == "g":
                group = " ".join(fields[1:])
                active_batch = None
                if "__batch" in group:
                    object_name, remainder = group.rsplit("__batch", 1)
                    index_text, _, material = remainder.partition("__")
                    if object_name in mesh_names and index_text.isdigit():
                        mesh = next(item for item in court.meshes if item.name == object_name)
                        batch_index = int(index_text)
                        if batch_index < len(mesh.batches) and mesh.batches[batch_index].material == material:
                            active_mesh = object_name
                            active_batch = mesh.batches[batch_index]
            elif command == "usemtl":
                active_material = " ".join(fields[1:])
                if active_mesh is None or (active_mesh, active_material) not in batches_by_material:
                    raise CourtFormatError(
                        f"Material {active_material!r} is not an existing material on object {active_mesh!r}."
                    )
                active_batch = batches_by_material[(active_mesh, active_material)]
            elif command == "v":
                position = tuple(float(value) for value in fields[1:4])
                if len(position) != 3 or not all(math.isfinite(value) for value in position):
                    raise CourtFormatError("OBJ vertices require three finite coordinates.")
                positions.append(position)
                colors.append(
                    tuple(max(0, min(255, round(float(value) * 255))) for value in fields[4:7])
                    if len(fields) >= 7 else None
                )
                if active_batch is not None:
                    key = (active_batch.mesh_name, active_batch.batch_index)
                    owned_vertices.setdefault(key, []).append(len(positions) - 1)
            elif command == "vt":
                uv = float(fields[1]), float(fields[2])
                if not all(math.isfinite(value) for value in uv):
                    raise CourtFormatError("OBJ texture coordinates must be finite.")
                texture_vertices.append(uv)
            elif command == "f":
                if active_batch is None:
                    raise CourtFormatError("Every OBJ face must belong to an original object and material.")
                corners: list[tuple[int, int | None]] = []
                for item in fields[1:]:
                    values = item.split("/")
                    vertex_index = _obj_index(values[0], len(positions))
                    uv_index = _obj_index(values[1], len(texture_vertices)) if len(values) > 1 and values[1] else None
                    corners.append((vertex_index, uv_index))
                if len(corners) < 3:
                    raise CourtFormatError("OBJ faces must contain at least three vertices.")
                key = active_batch.mesh_name, active_batch.batch_index
                for index in range(1, len(corners) - 1):
                    faces.setdefault(key, []).append((corners[0], corners[index], corners[index + 1]))
        except (IndexError, ValueError) as exc:
            raise CourtFormatError(f"Invalid OBJ data on line {line_number}: {raw_line}") from exc

    results: dict[tuple[str, int], RebuiltBatch] = {}
    for batch in court.batches:
        key = batch.mesh_name, batch.batch_index
        batch_faces = faces.get(key, [])
        if not batch_faces:
            raise CourtFormatError(
                f"Object {batch.mesh_name!r}, material {batch.material!r} has no faces. "
                "Keep at least one face in every original material group."
            )

        corner_uvs: dict[int, int | None] = {}
        for face in batch_faces:
            for vertex_index, uv_index in face:
                corner_uvs.setdefault(vertex_index, uv_index)

        local_lookup: dict[tuple[int, int | None], int] = {}
        local_positions: list[tuple[float, float, float]] = []
        local_uvs: list[tuple[float, float]] = []
        local_colors: list[tuple[int, int, int, int]] = []

        def add_vertex(vertex_index: int, uv_index: int | None) -> int:
            identity = vertex_index, uv_index
            if identity in local_lookup:
                return local_lookup[identity]
            local_index = len(local_positions)
            if local_index > 65535:
                raise CourtFormatError(
                    f"Object {batch.mesh_name!r}, material {batch.material!r} exceeds 65,536 vertices."
                )
            local_lookup[identity] = local_index
            local_positions.append(positions[vertex_index])
            if uv_index is None:
                if vertex_index < len(texture_vertices):
                    u, v = texture_vertices[vertex_index]
                else:
                    u, v = 0.0, 0.0
            else:
                u, v = texture_vertices[uv_index]
            local_uvs.append((u, 1 - v if flip_v else v))
            color = colors[vertex_index]
            if color is None:
                original_index = min(local_index, batch.vertex_count - 1)
                blue, green, red, alpha = _read(
                    court.data, "<4B", batch.colors.data_offset + original_index * 4
                )
            else:
                red, green, blue = color
                original_index = min(local_index, batch.vertex_count - 1)
                alpha = court.data[batch.colors.data_offset + original_index * 4 + 3]
            local_colors.append((blue, green, red, alpha))
            return local_index

        # Preserve explicit exported group ownership, including occasionally
        # unused source vertices. Blender exports without those groups are
        # reconstructed from the faces and their material assignments instead.
        for vertex_index in owned_vertices.get(key, []):
            if vertex_index in corner_uvs:
                add_vertex(vertex_index, corner_uvs[vertex_index])
            elif len(owned_vertices[key]) == batch.vertex_count:
                fallback_uv = vertex_index if vertex_index < len(texture_vertices) else None
                add_vertex(vertex_index, fallback_uv)

        triangles: list[tuple[int, int, int]] = []
        for face in batch_faces:
            triangle = tuple(add_vertex(vertex_index, uv_index) for vertex_index, uv_index in face)
            if len(set(triangle)) == 3:
                triangles.append(triangle)
        if not triangles:
            raise CourtFormatError(f"Object {batch.mesh_name!r}, material {batch.material!r} has only degenerate faces.")

        triangle_tuple = tuple(triangles)
        if len(local_positions) == batch.vertex_count and _same_oriented_triangles(triangle_tuple, batch.triangles):
            strip = _read(court.data, f"<{batch.primitive_count + 2}H", batch.indices.data_offset)
        else:
            strip = _triangles_to_strip(triangle_tuple)
        results[key] = RebuiltBatch(
            tuple(local_positions), tuple(local_uvs), tuple(local_colors), triangle_tuple, strip
        )
    return results


def rebuild_court(court: Court, obj_path: Path, *, flip_v: bool) -> tuple[bytes, int]:
    edited = _parse_rebuild_obj(court, obj_path, flip_v=flip_v)
    return rebuild_from_batches(court, edited)


def _vertex_normals(
    positions: tuple[tuple[float, float, float], ...],
    triangles: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[float, float, float], ...]:
    accumulated = [[0.0, 0.0, 0.0] for _ in positions]
    for first, second, third in triangles:
        a, b, c = positions[first], positions[second], positions[third]
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        normal = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        for index in (first, second, third):
            for axis in range(3):
                accumulated[index][axis] += normal[axis]
    result = []
    for value in accumulated:
        length = math.sqrt(sum(component * component for component in value))
        result.append(tuple(component / length for component in value) if length else (0.0, 0.0, 1.0))
    return tuple(result)


def _rebuild_specialized_topology(
    court: Court,
    edited: dict[tuple[str, int], RebuiltBatch],
) -> tuple[bytes, int]:
    """Replace specialized streams in native locations and relocate later pointers."""
    updates: list[tuple[Batch, RebuiltBatch, list[tuple[Buffer, bytes, int]]]] = []
    changed = 0
    for mesh in court.meshes:
        for batch in mesh.batches:
            rebuilt = edited[mesh.name, batch.batch_index]
            topology_changed = (
                len(rebuilt.positions) != batch.vertex_count
                or tuple(rebuilt.triangles) != batch.triangles
                or len(rebuilt.strip) != batch.primitive_count + 2
            )
            if not topology_changed:
                continue
            additions = _added_triangles(batch.triangles, rebuilt.triangles)
            # 0.6.2 experimental generalized specialized rebuild. Complete
            # streams are replaced, so original triangles may be removed or
            # rewired instead of requiring append-only topology.
            changed += 1
            count = len(rebuilt.positions)
            if not count or count > 65536:
                raise CourtFormatError(f"Material {batch.material!r} has an unsupported vertex count {count}.")
            if len(rebuilt.uvs) != count or len(rebuilt.colors) != count:
                raise CourtFormatError(f"Material {batch.material!r} has incomplete per-vertex data.")
            if any(index >= count for triangle in rebuilt.triangles for index in triangle):
                raise CourtFormatError(f"Material {batch.material!r} has an out-of-range triangle index.")
            streams: list[tuple[Buffer, bytes, int]] = []
            streams.append((batch.positions, b"".join(struct.pack("<3f", *item) for item in rebuilt.positions), 12))
            if batch.normals is not None:
                normals = _vertex_normals(rebuilt.positions, rebuilt.triangles)
                if len(rebuilt.positions) >= batch.vertex_count and additions is not None:
                    # Purely additive Blender edits retain the imported vertex
                    # indices. Preserve the template's authored normals for
                    # those vertices and calculate normals only for appended
                    # vertices; wholesale regeneration changes lighting across
                    # an otherwise untouched backboard.
                    normal_data = court.data[
                        batch.normals.data_offset:
                        batch.normals.data_offset + batch.vertex_count * 12
                    ] + b"".join(
                        struct.pack("<3f", *item) for item in normals[batch.vertex_count:]
                    )
                else:
                    normal_data = b"".join(struct.pack("<3f", *item) for item in normals)
                streams.append((batch.normals, normal_data, 12))
            if batch.uvs is not None:
                streams.append((batch.uvs, b"".join(struct.pack("<2f", *item) for item in rebuilt.uvs), 8))
            if batch.colors is not None:
                streams.append((batch.colors, b"".join(
                    struct.pack("<4B", item[2], item[1], item[0], item[3]) for item in rebuilt.colors
                ), 4))
            streams.append((batch.indices, struct.pack(f"<{len(rebuilt.strip)}H", *rebuilt.strip), 2))
            if batch.selectors:
                if len(rebuilt.selectors) != count:
                    raise CourtFormatError(
                        f"Material {batch.material!r} has {len(rebuilt.selectors)} transform selectors "
                        f"for {count} vertices."
                    )
                invalid = [value for value in rebuilt.selectors if not 0 <= value < batch.palette_count]
                if invalid:
                    raise CourtFormatError(
                        f"Material {batch.material!r} has selector {invalid[0]} outside palette "
                        f"0..{batch.palette_count - 1}."
                    )
            updates.append((batch, rebuilt, streams))

    replacements: list[tuple[int, int, bytes]] = []
    changed_lengths: dict[int, int] = {}
    changed_strides: dict[int, int] = {}
    changed_batches = {(batch.mesh_name, batch.batch_index): rebuilt for batch, rebuilt, _ in updates}
    for batch, _, streams in updates:
        descriptor = _read(court.data, "<I", next(
            mesh.offset + 116 + batch.batch_index * 48
            for mesh in court.meshes if mesh.name == batch.mesh_name
        ))[0]
        if batch.pcdata_word is None:
            raise CourtFormatError(f"Topology rebuilding is not yet defined for descriptor {batch.profile!r}.")
        old_pc_data = _read(court.data, "<I", descriptor + batch.pcdata_word * 4)[0]
        for buffer, stream_data, stride in streams:
            end = old_pc_data if buffer is batch.indices else buffer.data_offset + buffer.byte_count
            payload = stream_data
            if buffer is batch.indices:
                payload += b"\xdf" * ((-len(payload)) % 4)
            replacements.append((buffer.data_offset, end, payload))
            changed_lengths[buffer.offset] = len(stream_data)
            changed_strides[buffer.offset] = stride
        if batch.selectors and batch.selector_offset is not None:
            old_size = (batch.vertex_count * 2 + 3) & ~3
            rebuilt_selectors = edited[batch.mesh_name, batch.batch_index].selectors
            selector_data = struct.pack(f"<{len(rebuilt_selectors)}H", *rebuilt_selectors)
            selector_payload = selector_data + b"\xdf" * (((-len(selector_data)) % 4))
            replacements.append((batch.selector_offset, batch.selector_offset + old_size, selector_payload))

    replacements.sort(key=lambda item: item[0])
    ends: list[int] = []
    accumulated: list[int] = [0]
    pieces: list[bytes] = []
    cursor = 0
    for start, end, payload in replacements:
        if start < cursor:
            raise CourtFormatError("Overlapping specialized EBO streams prevent safe topology rebuilding.")
        pieces.extend((court.data[cursor:start], payload))
        cursor = end
        ends.append(end)
        accumulated.append(accumulated[-1] + len(payload) - (end - start))
    pieces.append(court.data[cursor:])
    data = bytearray(b"".join(pieces))

    def moved(offset: int) -> int:
        return offset + accumulated[bisect_right(ends, offset)]

    _replace(data, 8, "<I", len(data))
    for location in (20, 24, 28, 32):
        _replace(data, location, "<I", moved(_read(court.data, "<I", location)[0]))

    # Topology growth can occur inside more than one EBO chunk. Rebuild each
    # chunk size from the same piecewise relocation map used for payloads.
    # Then relocate every TOC oData value. oData is relative to the TOC record
    # itself, so the TOC and its target may move by different amounts.
    old_chunk = _read(court.data, "<I", 16)[0]
    chunk_count = _read(court.data, "<H", 36)[0]
    chunk_pairs: list[tuple[int, int, int, int, int]] = []
    for _chunk_index in range(chunk_count):
        old_flags, old_ntocs, old_otocs, old_type, old_ver, old_size = _read(
            court.data, "<HHIIII", old_chunk
        )
        new_chunk = moved(old_chunk)
        new_end = moved(old_chunk + old_size)
        new_size = new_end - new_chunk
        _replace(data, new_chunk + 16, "<I", new_size)
        chunk_pairs.append((old_chunk, new_chunk, old_ntocs, old_otocs, old_size))
        for _toc_index in range(old_ntocs):
            old_toc = old_chunk + old_otocs + _toc_index * 16
            new_toc = moved(old_toc)
            old_odata = _read(court.data, "<I", old_toc + 12)[0]
            old_target = old_toc + old_odata
            new_target = moved(old_target)
            _replace(data, new_toc + 12, "<I", new_target - new_toc)
        old_chunk += old_size

    # Raw i8 TOCs describe serialized byte payloads. Their nStructs values
    # must grow with the actual vertex/index streams; otherwise the game sees
    # the new buffer header length but an old serializer byte count.
    data_length_by_old_target = {
        buffer.data_offset: changed_lengths[buffer.offset]
        for mesh in court.meshes
        for batch in mesh.batches
        for buffer in (batch.positions, batch.normals, batch.uvs, batch.colors, batch.indices)
        if buffer is not None and buffer.offset in changed_lengths
    }
    for old_chunk, new_chunk, old_ntocs, old_otocs, old_size in chunk_pairs:
        new_size = _read(data, "<I", new_chunk + 16)[0]
        for _toc_index in range(old_ntocs):
            old_toc = old_chunk + old_otocs + _toc_index * 16
            new_toc = moved(old_toc)
            flags, usd_index, old_nstructs, aligned_size, old_odata = _read(
                court.data, "<HHIII", old_toc
            )
            old_target = old_toc + old_odata
            if flags == 1 and usd_index == 13 and old_target in data_length_by_old_target:
                _replace(data, new_toc + 4, "<I", data_length_by_old_target[old_target])

        # Specialized phase 1 has one raw i8 TOC spanning its selector/material
        # payload. Its byte count changes by exactly the chunk's net growth.
        if old_ntocs == 1:
            old_toc = old_chunk + old_otocs
            new_toc = moved(old_toc)
            flags, usd_index, old_nstructs, aligned_size, old_odata = _read(
                court.data, "<HHIII", old_toc
            )
            if flags == 1 and usd_index == 13:
                _replace(data, new_toc + 4, "<I", old_nstructs + (new_size - old_size))

    # Every stream retains its complete native header immediately before its
    # payload. Update all headers, descriptors and PCData buffer references.
    header_map: dict[int, int] = {}
    pc_map: dict[int, int] = {}
    descriptor_map: dict[int, int] = {}
    for mesh in court.meshes:
        for batch in mesh.batches:
            old_descriptor = _read(
                court.data, "<I", mesh.offset + 116 + batch.batch_index * 48
            )[0]
            descriptor_map[old_descriptor] = moved(old_descriptor)
            if batch.pcdata_word is None:
                raise CourtFormatError(f"Topology rebuilding is not yet defined for descriptor {batch.profile!r}.")
            old_pc = _read(court.data, "<I", old_descriptor + batch.pcdata_word * 4)[0]
            pc_map[old_pc] = moved(old_pc)
            for buffer in (batch.positions, batch.normals, batch.uvs, batch.colors, batch.indices):
                if buffer is None:
                    continue
                new_header = moved(buffer.offset)
                header_map[buffer.offset] = new_header
                byte_count = changed_lengths.get(buffer.offset, buffer.byte_count)
                stride = changed_strides.get(buffer.offset, buffer.stride)
                _replace(data, new_header, "<3I", byte_count, stride, moved(buffer.data_offset))

    targets = header_map | pc_map
    for mesh in court.meshes:
        new_mesh = moved(mesh.offset)
        _replace(data, new_mesh + 16, "<I", moved(mesh.offset + 104))
        _replace(data, new_mesh + 52, "<I", moved(_read(court.data, "<I", mesh.offset + 52)[0]))
        for batch in mesh.batches:
            row_pointer = mesh.offset + 116 + batch.batch_index * 48
            old_descriptor = _read(court.data, "<I", row_pointer)[0]
            descriptor = descriptor_map[old_descriptor]
            _replace(data, moved(row_pointer), "<I", descriptor)
            # Specialized descriptors contain only a small fixed collection of
            # absolute stream/PCData pointers. Replace exact known targets.
            for word_index in range(20):
                value = _read(court.data, "<I", old_descriptor + word_index * 4)[0]
                if value in targets:
                    _replace(data, descriptor + word_index * 4, "<I", targets[value])
            if batch.selector_offset is not None:
                if batch.selector_word is None:
                    raise CourtFormatError("Selector stream has no structural descriptor field.")
                _replace(data, descriptor + batch.selector_word * 4, "<I", moved(batch.selector_offset))
            if batch.pcdata_word is None:
                raise CourtFormatError(f"Topology rebuilding is not yet defined for descriptor {batch.profile!r}.")
            old_pc = _read(court.data, "<I", old_descriptor + batch.pcdata_word * 4)[0]
            pc_data = moved(old_pc)
            for word_index in range(8):
                value = _read(court.data, "<I", old_pc + word_index * 4)[0]
                if value in header_map:
                    _replace(data, pc_data + word_index * 4, "<I", header_map[value])
            rebuilt = changed_batches.get((mesh.name, batch.batch_index))
            if rebuilt is not None:
                count, primitive_count = len(rebuilt.positions), len(rebuilt.strip) - 2
                if batch.count_word is None or batch.primitive_word != batch.count_word + 1:
                    raise CourtFormatError("Non-adjacent descriptor counts are not yet rebuildable.")
                _replace(data, descriptor + batch.count_word * 4, "<2I", count, primitive_count)
                _replace(data, pc_data + 8, "<I", count)

        positions = [
            item for batch in mesh.batches
            for item in edited[mesh.name, batch.batch_index].positions
        ]
        minimum = tuple(min(item[axis] for item in positions) for axis in range(3))
        maximum = tuple(max(item[axis] for item in positions) for axis in range(3))
        center = tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))
        radius = math.sqrt(sum(((maximum[axis] - minimum[axis]) / 2) ** 2 for axis in range(3)))
        _replace(data, new_mesh + 64, "<10f", *minimum, *maximum, *center, radius)

    for group in external_variable_groups(court):
        new_group = moved(group.offset)
        new_links = moved(group.links_offset)
        _replace(data, new_group + 16, "<I", new_links - new_group)
        for index, target in enumerate(group.targets):
            _replace(data, new_links + index * 4, "<i", moved(target) - new_group)

    # Specialized Geometry uses seven outer relocation records per ordinary
    # backboard material (rather than the static format's five). Their fields
    # are relative to each 16-byte record and can target stream metadata after
    # the expanded payloads. Leaving these displacements unchanged produces an
    # EBO that parses locally but crashes the game loader.
    # Each Geometry export's outer serializer lives at the beginning of the
    # type-1 chunk that contains that Geometry object.  Do not chain from the
    # previous mesh's PCData end: that happened to work for the backboard
    # corpus, but frontend EBOs place successive Geometry exports in separate
    # phase-0 chunks.
    for mesh in court.meshes:
        containing = next(
            (
                (old_chunk, old_size)
                for old_chunk, _new_chunk, _ntocs, _otocs, old_size in chunk_pairs
                if old_chunk <= mesh.offset < old_chunk + old_size
            ),
            None,
        )
        if containing is None:
            raise CourtFormatError(f"Object {mesh.name!r} is not contained in an EBO chunk.")
        preamble_start, _phase0_size = containing
        record_count = _read(court.data, "<I", preamble_start)[0] >> 16
        expected_end = preamble_start + 16 + record_count * 16 + 12
        if expected_end != mesh.offset:
            raise CourtFormatError(
                f"Object {mesh.name!r} has an unsupported outer serializer layout."
            )
        for record_index in range(record_count):
            old_record = preamble_start + 16 + record_index * 16
            old_target = old_record + _read(court.data, "<i", old_record)[0]
            new_record = moved(old_record)
            _replace(data, new_record, "<i", moved(old_target) - new_record)
        old_trailer = mesh.offset - 12
        old_target = old_trailer + _read(court.data, "<i", old_trailer)[0]
        new_trailer = moved(old_trailer)
        _replace(data, new_trailer, "<i", moved(old_target) - new_trailer)

    # The inner PC serializer is a sequence of 16-byte relocation records in
    # the mesh-to-first-stream region. Word 2 is relative to its own field;
    # word 3 identifies the relocation kind. These records reference buffer
    # headers, header pointer fields and PCData blocks, so their displacements
    # must also follow native stream growth.
    relocation_kinds = {0x00080000, 0x000B0000, 0x000C0000, 0x000D0001}
    for mesh in court.meshes:
        first_stream = min(
            buffer.offset
            for batch in mesh.batches
            for buffer in (batch.positions, batch.normals, batch.uvs, batch.colors, batch.indices)
            if buffer is not None
        )
        # These records are 16 bytes wide but are NOT guaranteed to start on a
        # file-global 16-byte boundary.  EA can place a record sequence at a
        # 4-byte-aligned base (clevbbd has a valid record whose relocation field
        # is at 0x2318).  The old global-alignment scan silently skipped it and
        # produced game-crashing files whenever later payloads moved.
        seen_inner_fields: set[int] = set()
        for record in range(mesh.offset, first_stream - 15, 4):
            if _read(court.data, "<I", record + 12)[0] not in relocation_kinds:
                continue
            old_field = record + 8
            if old_field in seen_inner_fields:
                continue
            old_target = old_field + _read(court.data, "<i", old_field)[0]
            if not 0 <= old_target < len(court.data):
                continue
            # Serializer relocation targets observed in PC EBOs are aligned.
            # This rejects accidental kind-looking words inside unrelated data.
            if old_target & 3:
                continue
            seen_inner_fields.add(old_field)
            new_field = moved(old_field)
            _replace(data, new_field, "<i", moved(old_target) - new_field)

    old_mesh_table = _read(court.data, "<I", 28)[0]
    for index, mesh in enumerate(court.meshes):
        old_location = old_mesh_table + index * 12 + 8
        new_location = moved(old_location)
        _replace(data, new_location, "<i", moved(mesh.offset) - new_location)

    verified = parse_court(bytes(data))
    for batch, rebuilt, _ in updates:
        result = verified.meshes[next(
            i for i, mesh in enumerate(verified.meshes) if mesh.name == batch.mesh_name
        )].batches[batch.batch_index]
        if result.vertex_count != len(rebuilt.positions) or result.triangles != rebuilt.triangles:
            raise CourtFormatError(f"Specialized topology rebuild verification failed for material {batch.material!r}.")
        if batch.selectors and result.selectors != rebuilt.selectors:
            raise CourtFormatError(
                f"Transform-selector rebuild verification failed for material {batch.material!r}."
            )
    return bytes(data), changed


def _patch_specialized_batches(
    court: Court,
    edited: dict[tuple[str, int], RebuiltBatch],
) -> tuple[bytes, int]:
    """Patch skinned/specialized streams without moving serializer metadata.

    Ball/accessory EBOs use position, normal, UV and index streams plus a
    different serializer. Keeping vertex count and topology fixed lets us
    preserve every unknown runtime field byte-for-byte.
    """
    data = bytearray(court.data)
    for mesh in court.meshes:
        all_positions: list[tuple[float, float, float]] = []
        positions_changed = False
        for batch in mesh.batches:
            if batch.profile == "STATIC_COLOR":
                raise CourtFormatError("Static and descriptor-driven geometry cannot be rebuilt together yet.")
            rebuilt = edited[mesh.name, batch.batch_index]
            if len(rebuilt.positions) != batch.vertex_count or (
                batch.uvs is not None and len(rebuilt.uvs) != batch.vertex_count
            ):
                raise CourtFormatError(
                    f"Object {mesh.name!r}, material {batch.material!r} must retain "
                    f"exactly {batch.vertex_count} vertices."
                )
            if rebuilt.triangles != batch.triangles or tuple(rebuilt.strip) != tuple(
                _read(court.data, f"<{batch.primitive_count + 2}H", batch.indices.data_offset)
            ):
                raise CourtFormatError(
                    f"Object {mesh.name!r}, material {batch.material!r} must retain its original topology."
                )
            for index, position in enumerate(rebuilt.positions):
                uv = rebuilt.uvs[index] if batch.uvs is not None else (0.0, 0.0)
                if not all(math.isfinite(value) for value in position + uv):
                    raise CourtFormatError("Mesh contains a non-finite coordinate or UV value.")
                positions_changed |= _replace(
                    data, batch.positions.data_offset + index * 12, "<3f", *position
                )
                if batch.uvs is not None:
                    _replace(data, batch.uvs.data_offset + index * 8, "<2f", *uv)
                if batch.colors is not None and len(rebuilt.colors) == batch.vertex_count:
                    rgba = rebuilt.colors[index]
                    _replace(
                        data, batch.colors.data_offset + index * 4, "<4B",
                        rgba[2], rgba[1], rgba[0], rgba[3]
                    )
            all_positions.extend(rebuilt.positions)
        if positions_changed:
            minimum = tuple(min(position[axis] for position in all_positions) for axis in range(3))
            maximum = tuple(max(position[axis] for position in all_positions) for axis in range(3))
            center = tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))
            radius = math.sqrt(sum(((maximum[axis] - minimum[axis]) / 2) ** 2 for axis in range(3)))
            _replace(data, mesh.offset + 64, "<10f", *minimum, *maximum, *center, radius)
    verified = parse_court(bytes(data))
    if tuple(batch.profile for batch in verified.batches) != tuple(batch.profile for batch in court.batches):
        raise CourtFormatError("Specialized geometry profiles were not preserved after export.")
    return bytes(data), 0


def rebuild_from_batches(
    court: Court,
    edited: dict[tuple[str, int], RebuiltBatch],
) -> tuple[bytes, int]:
    expected_keys = {(batch.mesh_name, batch.batch_index) for batch in court.batches}
    if set(edited) != expected_keys:
        missing = sorted(expected_keys - set(edited))
        unexpected = sorted(set(edited) - expected_keys)
        raise CourtFormatError(f"Material groups do not match the EBO template; missing={missing}, unexpected={unexpected}.")
    if any(batch.profile != "STATIC_COLOR" for batch in court.batches):
        topology_changed = any(
            len(edited[batch.mesh_name, batch.batch_index].positions) != batch.vertex_count
            or edited[batch.mesh_name, batch.batch_index].triangles != batch.triangles
            or len(edited[batch.mesh_name, batch.batch_index].strip) != batch.primitive_count + 2
            for batch in court.batches
        )
        if topology_changed:
            unsupported = [batch for batch in court.batches if batch.pcdata_word is None]
            if unsupported:
                kinds = sorted({batch.profile for batch in unsupported})
                raise CourtFormatError(
                    "Topology rebuilding is not yet defined for descriptor representation(s): "
                    + ", ".join(kinds)
                )
            return _rebuild_specialized_topology(court, edited)
        return _patch_specialized_batches(court, edited)
    replacements: list[tuple[int, int, bytes]] = []

    for mesh in court.meshes:
        for batch in mesh.batches:
            rebuilt = edited[batch.mesh_name, batch.batch_index]
            position_data = b"".join(struct.pack("<3f", *item) for item in rebuilt.positions)
            uv_data = b"".join(struct.pack("<2f", *item) for item in rebuilt.uvs)
            color_data = b"".join(struct.pack("<4B", *item) for item in rebuilt.colors)
            index_data = struct.pack(f"<{len(rebuilt.strip)}H", *rebuilt.strip)
            for buffer, payload in (
                (batch.positions, position_data),
                (batch.uvs, uv_data),
                (batch.colors, color_data),
            ):
                replacements.append((buffer.data_offset, buffer.data_offset + buffer.byte_count, payload))

            descriptor = _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            pc_data = _read(court.data, "<I", descriptor + 28)[0]
            padding = b"\xdf" * ((-len(index_data)) % 4)
            replacements.append((batch.indices.data_offset, pc_data, index_data + padding))

    replacements.sort(key=lambda item: item[0])
    ends: list[int] = []
    accumulated: list[int] = [0]
    chunks: list[bytes] = []
    cursor = 0
    for start, end, payload in replacements:
        if start < cursor:
            raise CourtFormatError("Overlapping EBO buffer regions prevent a safe rebuild.")
        chunks.extend((court.data[cursor:start], payload))
        cursor = end
        ends.append(end)
        accumulated.append(accumulated[-1] + len(payload) - (end - start))
    chunks.append(court.data[cursor:])
    data = bytearray(b"".join(chunks))

    def moved(old_offset: int) -> int:
        return old_offset + accumulated[bisect_right(ends, old_offset)]

    # Update file length and the four trailing section locations.
    _replace(data, 8, "<I", len(data))
    for location in (20, 24, 28, 32):
        old_value = _read(court.data, "<I", location)[0]
        _replace(data, location, "<I", moved(old_value))

    for mesh in court.meshes:
        new_mesh_offset = moved(mesh.offset)
        _replace(data, new_mesh_offset + 16, "<I", moved(mesh.offset + 104))
        old_bounds_pointer = _read(court.data, "<I", mesh.offset + 52)[0]
        _replace(data, new_mesh_offset + 52, "<I", moved(old_bounds_pointer))

        first_descriptor = _read(court.data, "<I", mesh.offset + 116)[0]
        metadata_start = first_descriptor + len(mesh.batches) * 36
        if mesh.batches[0].positions.offset - metadata_start != 40 + 144 * len(mesh.batches):
            raise CourtFormatError(f"Unexpected serializer metadata in object {mesh.name!r}.")
        old_total_marker = metadata_start + 20
        old_total_target = old_total_marker + _read(court.data, "<I", metadata_start + 36)[0]
        _replace(
            data,
            moved(metadata_start + 36),
            "<I",
            moved(old_total_target) - moved(old_total_marker),
        )

        all_positions: list[tuple[float, float, float]] = []
        for batch in mesh.batches:
            updated = edited[mesh.name, batch.batch_index]
            all_positions.extend(updated.positions)
            old_descriptor = _read(court.data, "<I", mesh.offset + 116 + batch.batch_index * 48)[0]
            descriptor = moved(old_descriptor)
            old_pc_data = _read(court.data, "<I", old_descriptor + 28)[0]
            _replace(
                data,
                moved(mesh.offset + 116 + batch.batch_index * 48),
                "<I",
                descriptor,
            )

            count = len(updated.positions)
            primitive_count = len(updated.strip) - 2
            _replace(
                data,
                descriptor + 4,
                "<7I",
                moved(batch.positions.offset),
                moved(batch.uvs.offset),
                moved(batch.colors.offset),
                moved(batch.indices.offset),
                count,
                primitive_count,
                moved(old_pc_data),
            )

            streams = (
                (batch.positions, count * 12),
                (batch.uvs, count * 8),
                (batch.colors, count * 4),
                (batch.indices, len(updated.strip) * 2),
            )
            for buffer, byte_count in streams:
                _replace(data, moved(buffer.offset), "<I", byte_count)
                _replace(data, moved(buffer.offset + 8), "<I", moved(buffer.data_offset))

            pc_data = moved(old_pc_data)
            _replace(data, pc_data, "<I", moved(batch.indices.offset))
            _replace(data, pc_data + 8, "<I", count)
            _replace(
                data,
                pc_data + 20,
                "<3I",
                moved(batch.positions.offset),
                moved(batch.uvs.offset),
                moved(batch.colors.offset),
            )

            for stream_index, (buffer, byte_count) in enumerate(streams):
                group = metadata_start + 40 + batch.batch_index * 144 + stream_index * 32
                _replace(data, moved(group + 12), "<I", moved(buffer.offset) - moved(group))
                original_length = _read(court.data, "<I", group + 20)[0]
                original_elements = (
                    batch.vertex_count if stream_index < 3 else batch.primitive_count + 2
                )
                new_elements = count if stream_index < 3 else len(updated.strip)
                if original_length == buffer.byte_count:
                    serialized_length = byte_count
                elif original_length == original_elements:
                    serialized_length = new_elements
                else:
                    raise CourtFormatError(
                        f"Object {mesh.name!r}, material {batch.material!r} has an "
                        f"unknown serializer length convention for stream {stream_index}."
                    )
                _replace(data, moved(group + 20), "<I", serialized_length)
                pointer_field = buffer.offset + (12 if stream_index < 3 else 8)
                _replace(data, moved(group + 28), "<I", moved(pointer_field) - moved(group))
            pc_group = metadata_start + 40 + batch.batch_index * 144 + 128
            _replace(data, moved(pc_group + 12), "<I", pc_data - moved(pc_group))

        minimum = tuple(min(position[axis] for position in all_positions) for axis in range(3))
        maximum = tuple(max(position[axis] for position in all_positions) for axis in range(3))
        center = tuple((minimum[axis] + maximum[axis]) / 2 for axis in range(3))
        radius = math.sqrt(sum(((maximum[axis] - minimum[axis]) / 2) ** 2 for axis in range(3)))
        original_positions_changed = any(
            len(edited[mesh.name, batch.batch_index].positions) != batch.vertex_count
            or any(
                struct.pack("<3f", *position)
                != court.data[
                    batch.positions.data_offset + index * 12:
                    batch.positions.data_offset + index * 12 + 12
                ]
                for index, position in enumerate(edited[mesh.name, batch.batch_index].positions)
            )
            for batch in mesh.batches
        )
        if original_positions_changed:
            _replace(data, new_mesh_offset + 64, "<10f", *minimum, *maximum, *center, radius)

    # External-variable displacements are relative to their group record,
    # not to the link itself. Material rows require one runtime binding each.
    old_mesh_table = _read(court.data, "<I", 28)[0]
    for group in external_variable_groups(court):
        new_group_offset = moved(group.offset)
        _replace(
            data,
            new_group_offset + 16,
            "<I",
            moved(group.links_offset) - new_group_offset,
        )
        for link_index, old_target in enumerate(group.targets):
            old_location = group.links_offset + link_index * 4
            _replace(
                data,
                moved(old_location),
                "<i",
                moved(old_target) - new_group_offset,
            )
    for index, mesh in enumerate(court.meshes):
        old_location = old_mesh_table + index * 12 + 8
        _replace(data, moved(old_location), "<i", moved(mesh.offset) - moved(old_location))

    verified = parse_court(bytes(data))
    validate_material_bindings(verified)
    validate_serializer_metadata(verified)
    validate_stream_headers(verified)
    mesh_serializer_preambles(verified)
    for mesh in verified.meshes:
        for batch in mesh.batches:
            expected = edited[mesh.name, batch.batch_index]
            if batch.vertex_count != len(expected.positions) or batch.triangles != expected.triangles:
                raise CourtFormatError(f"Rebuilt object {mesh.name!r} failed geometry verification.")
    changed_batches = sum(
        len(edited[batch.mesh_name, batch.batch_index].positions) != batch.vertex_count
        or edited[batch.mesh_name, batch.batch_index].triangles != batch.triangles
        for batch in court.batches
    )
    return bytes(data), changed_batches


def print_summary(court: Court) -> None:
    print(f"Meshes: {len(court.meshes)} | Batches: {len(court.batches)} | "
          f"Vertices: {court.vertex_count} | Triangles: {court.triangle_count}")
    for mesh in court.meshes:
        print(f"  {mesh.name}")
        for batch in mesh.batches:
            selector_info = (
                f"  palette={batch.palette_count} selectors={len(batch.selectors)}"
                if batch.selectors else ""
            )
            print(f"    batch {batch.batch_index:02d}  material={batch.material:<5} "
                  f"vertices={batch.vertex_count:>4}  triangles={len(batch.triangles):>4}"
                  f"{selector_info}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect, export, patch, and rebuild NBA Live 2005/2006 court/stadium EBOs.")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="List meshes, materials, vertices, and triangles.")
    inspect_parser.add_argument("ebo", type=Path)

    export_parser = commands.add_parser("export", help="Convert a court or stadium EBO into OBJ and MTL files.")
    export_parser.add_argument("ebo", type=Path)
    export_parser.add_argument("obj", type=Path)
    export_parser.add_argument("--no-flip-v", action="store_true", help="Keep the original top-origin V coordinates.")
    export_parser.add_argument("--texture-extension", default=".png", help="Texture extension in the MTL file; default: .png.")

    patch_parser = commands.add_parser("patch", help="Update vertices and UVs while preserving original topology.")
    patch_parser.add_argument("template", type=Path, help="Original, unmodified EBO.")
    patch_parser.add_argument("obj", type=Path, help="Edited OBJ with the original vertex order and count.")
    patch_parser.add_argument("output", type=Path, help="Destination EBO.")
    patch_parser.add_argument("--no-flip-v", action="store_true", help="Keep the original top-origin V coordinates.")
    patch_parser.add_argument("--positions-only", action="store_true", help="Preserve all original UVs and colors.")
    patch_parser.add_argument("--no-colors", action="store_true", help="Preserve all original vertex colors.")

    rebuild_parser = commands.add_parser("rebuild", help="Rebuild buffers after adding or removing vertices and faces.")
    rebuild_parser.add_argument("template", type=Path, help="Original, unmodified court or stadium EBO.")
    rebuild_parser.add_argument("obj", type=Path, help="Edited OBJ preserving original object and material names.")
    rebuild_parser.add_argument("output", type=Path, help="Destination rebuilt EBO.")
    rebuild_parser.add_argument("--no-flip-v", action="store_true", help="Keep the original top-origin V coordinates.")

    args = parser.parse_args(argv)
    source = args.template if args.command in ("patch", "rebuild") else args.ebo
    try:
        court = parse_court(source.read_bytes())
        if args.command == "inspect":
            print_summary(court)
            selector_reports = validate_transform_selectors(court)
            if selector_reports:
                print("Transform selectors:")
                for report in selector_reports:
                    print(f"  PASS  {report}")
        elif args.command == "export":
            export_obj(court, args.obj, flip_v=not args.no_flip_v, texture_extension=args.texture_extension)
            print_summary(court)
            print(f"Wrote {args.obj} and {args.obj.with_suffix('.mtl')}")
        elif args.command == "patch":
            updated, changed_vertices = patch_court(
                court,
                args.obj,
                flip_v=not args.no_flip_v,
                update_uvs=not args.positions_only,
                update_colors=not args.positions_only and not args.no_colors,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(updated)
            print(f"Wrote {args.output}; changed {changed_vertices} vertex position(s).")
        else:
            updated, changed_batches = rebuild_court(court, args.obj, flip_v=not args.no_flip_v)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(updated)
            print(
                f"Wrote {args.output}; rebuilt {changed_batches} material group(s); "
                f"size {len(court.data)} -> {len(updated)} bytes."
            )
        return 0
    except (CourtFormatError, OSError, struct.error, OverflowError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
