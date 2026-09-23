"""Integrated shared-texture support for NBA Live jumbotron RMS materials.

The Blender exporter keeps unique material-group names while it is rebuilding
geometry, then this module retargets only the final serialized texture
references for Jumbo* runtime-bound Material rows to one shared FSH resource.

This preserves:
- 13 distinct Material rows
- 13 distinct gJumbo..._RMRuntime bindings
- one shared texture resource, default name: "jumbo"

It intentionally operates after rebuild_from_batches(), when material rows and
runtime bindings are already stable.
"""

from __future__ import annotations

import struct

JUMBO_PREFIX = "Jumbo"
DEFAULT_SHARED_TEXTURE = "jumbo"


def _validate_name(ebo_core, value: str) -> str:
    return ebo_core.validate_material_name(value)


def _rms_label_from_material(material) -> str:
    """Read RMS type from imported property or any '<name> [<RMS>]' material name."""
    stored = str(material.get("nba_live_rms_type", "") or "").strip()
    if stored:
        return stored

    display_name = str(getattr(material, "name", "") or "").strip()

    # Do not require the optional 'EBO.' prefix. Existing projects may use:
    #   jh10 [JumboHomeTens]
    #   EBO.jh10 [JumboHomeTens]
    # Both should stage the same shared jumbotron texture.
    if display_name.endswith("]") and " [" in display_name:
        return display_name.rsplit(" [", 1)[1][:-1].strip()

    return ""


def export_texture_name(material, fallback: str) -> str:
    """Return the FSH texture name that should be staged for this material."""
    rms = _rms_label_from_material(material)
    if rms.startswith(JUMBO_PREFIX):
        return DEFAULT_SHARED_TEXTURE
    return fallback


def _append_string(data: bytearray, string_table: int, value: str) -> int:
    data.extend(b"\0" * (-len(data) % 2))
    relative = len(data) - string_table
    data.extend(value.encode("ascii") + b"\0")
    return relative


def retarget_ebo_bytes(ebo_core, raw: bytes, texture_name: str = DEFAULT_SHARED_TEXTURE) -> bytes:
    """Retarget every gJumbo*_RMRuntime material row to one texture string.

    Duplicate texture strings are deliberately allowed here. Runtime identity
    is carried by the external-variable/RM binding, not by the texture string.
    """
    texture_name = _validate_name(ebo_core, texture_name)
    court = ebo_core.parse_court(raw)

    # Map each concrete 0x30-byte Material row to its descriptor.
    rows: dict[int, tuple[object, object, int]] = {}
    for mesh in court.meshes:
        for batch in mesh.batches:
            row = mesh.offset + 104 + batch.batch_index * 48
            descriptor = struct.unpack_from("<I", court.data, row + 12)[0]
            rows[row] = (mesh, batch, descriptor)

    selected: list[tuple[str, int]] = []
    for group in ebo_core.external_variable_groups(court):
        if not (group.name.startswith("gJumbo") and group.name.endswith("_RMRuntime")):
            continue
        for target in group.targets:
            owner = rows.get(target)
            if owner is None:
                raise ebo_core.CourtFormatError(
                    f"{group.name} points to 0x{target:X}, which is not a Material row."
                )
            selected.append((group.name, owner[2]))

    if not selected:
        return raw

    data = bytearray(court.data)
    string_table = struct.unpack_from("<I", court.data, 32)[0]

    # Reuse an existing exact string if present.
    relative = None
    for _, _, descriptor in rows.values():
        candidate_relative = struct.unpack_from("<I", court.data, descriptor + 32)[0]
        absolute = string_table + candidate_relative
        if 0 <= absolute < len(court.data):
            end = court.data.find(b"\0", absolute)
            if end >= 0:
                try:
                    candidate = court.data[absolute:end].decode("ascii")
                except UnicodeDecodeError:
                    candidate = ""
                if candidate == texture_name:
                    relative = candidate_relative
                    break

    if relative is None:
        relative = _append_string(data, string_table, texture_name)

    for runtime_name, descriptor in selected:
        struct.pack_into("<I", data, descriptor + 32, relative)

    data.extend(b"\0" * (-len(data) % 4))
    struct.pack_into("<I", data, 8, len(data))

    # Do not call parse_court() as the only validator here: the historical
    # parser treats texture name as material-group identity and older versions
    # reject duplicates. Validate the changed string references directly.
    for runtime_name, descriptor in selected:
        test_relative = struct.unpack_from("<I", data, descriptor + 32)[0]
        absolute = string_table + test_relative
        end = data.find(b"\0", absolute)
        actual = bytes(data[absolute:end]).decode("ascii")
        if actual != texture_name:
            raise ebo_core.CourtFormatError(
                f"Shared jumbotron texture verification failed for {runtime_name}: "
                f"{actual!r} != {texture_name!r}."
            )

    return bytes(data)
