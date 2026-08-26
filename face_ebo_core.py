"""Dependency-free readers and byte-preserving writers for NBA Live head EBOs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import hashlib
import math
import struct


LOGICAL_VERTICES = 573
LOGICAL_COMPONENTS = LOGICAL_VERTICES * 3
GAME_VERTEX_COUNTS = {"2005": 734, "2006": 733}
BASE_FILENAMES = {"2005": "base_lodB_05.ebo", "2006": "base_lodB.ebo"}
SPARSE_ZERO_TOLERANCE = 1e-7


class EBOError(Exception):
    """A malformed EBO, unsupported edit, or incompatible game/base selection."""


@dataclass(frozen=True)
class BaseModel:
    year: str
    positions: tuple[tuple[float, float, float], ...]
    mapping: tuple[int, ...]
    uvs: tuple[tuple[float, float], ...]
    faces: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class CoordinateStream:
    offset: int
    size: int
    values: tuple[float, ...]
    stored_mask: tuple[bool, ...]


@dataclass(frozen=True)
class PlayerModel:
    year: str
    vertices: tuple[tuple[float, float, float], ...]
    uvs: tuple[tuple[float, float], ...]
    faces: tuple[tuple[int, int, int], ...]
    source_sha256: str


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _float32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _validate_ebo(data: bytes, description: str) -> None:
    if len(data) < 40 or data[:4] != b"EBO\0":
        raise EBOError(f"{description} is not a valid EBO file.")
    if _u32(data, 4) != 17:
        raise EBOError(f"{description} uses unsupported EBO version {_u32(data, 4)}.")
    if _u32(data, 8) != len(data):
        raise EBOError(f"{description} has an incorrect EBO file-size header.")


def _string(data: bytes, offset: int) -> str:
    if not 0 <= offset < len(data):
        raise ValueError("String offset is outside the EBO.")
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("Unterminated EBO string.")
    return data[offset:end].decode("ascii")


def _float_rows(data: bytes, offset: int, count: int, width: int):
    values = struct.unpack_from(f"<{count * width}f", data, offset)
    return tuple(tuple(values[i:i + width]) for i in range(0, len(values), width))


def _unique_candidate(name: str, candidates: list, year: str):
    if len(candidates) != 1:
        raise EBOError(
            f"Expected one {name} in the NBA Live {year} base model; "
            f"found {len(candidates)}. Check the selected base EBO."
        )
    return candidates[0]


@lru_cache(maxsize=8)
def _parse_base_cached(path_text: str, year: str, size: int, modified_ns: int) -> BaseModel:
    del size, modified_ns
    data = Path(path_text).read_bytes()
    _validate_ebo(data, "Base model")
    vertex_count = GAME_VERTEX_COUNTS[year]
    positions = []
    mappings = []
    uvs = []
    indices = []

    for offset in range(0, len(data) - 28, 4):
        byte_count = _u32(data, offset)
        stride = _u32(data, offset + 4)
        pointer = _u32(data, offset + 8)

        if byte_count == LOGICAL_VERTICES and stride == 1 and pointer == vertex_count:
            mapping_pointer = _u32(data, offset + 16)
            mapping_size = vertex_count * 2
            if mapping_pointer <= len(data) and mapping_size <= len(data) - mapping_pointer:
                mapping = struct.unpack_from(f"<{vertex_count}H", data, mapping_pointer)
                if max(mapping) == LOGICAL_VERTICES - 1 and len(set(mapping)) == LOGICAL_VERTICES:
                    mappings.append(mapping)

        if pointer > len(data) or byte_count > len(data) - pointer:
            continue

        if byte_count == vertex_count * 12 and stride == 12:
            rows = _float_rows(data, pointer, vertex_count, 3)
            flat = tuple(value for row in rows for value in row)
            if all(math.isfinite(value) for value in flat):
                if sum(abs(value) for value in flat) / len(flat) > 1.0:
                    positions.append(rows)

        elif byte_count == vertex_count * 8 and stride == 8:
            rows = _float_rows(data, pointer, vertex_count, 2)
            flat = tuple(value for row in rows for value in row)
            if all(math.isfinite(value) and -0.01 <= value <= 1.01 for value in flat):
                uvs.append(rows)

        elif stride == 2 and byte_count % 2 == 0 and 1000 <= byte_count <= 10000:
            candidate = struct.unpack_from(f"<{byte_count // 2}H", data, pointer)
            if candidate and max(candidate) == vertex_count - 1 and len(set(candidate)) == vertex_count:
                indices.append(candidate)

    position_rows = _unique_candidate("head position buffer", positions, year)
    mapping = _unique_candidate("render-to-logical vertex mapping", mappings, year)
    uv_rows = _unique_candidate("head UV buffer", uvs, year)
    strip = _unique_candidate("head triangle-strip index buffer", indices, year)

    faces = []
    for index in range(len(strip) - 2):
        a, b, c = strip[index:index + 3]
        if a == b or b == c or a == c:
            continue
        if index & 1:
            a, b = b, a
        faces.append((a, b, c))

    return BaseModel(year, position_rows, tuple(mapping), uv_rows, tuple(faces))


def parse_base(path: str | Path, year: str) -> BaseModel:
    if year not in GAME_VERTEX_COUNTS:
        raise EBOError(f"Unsupported NBA Live year: {year!r}.")
    base_path = Path(path).expanduser().resolve()
    try:
        stat = base_path.stat()
    except OSError as error:
        raise EBOError(f"Cannot open NBA Live {year} base model: {base_path}") from error
    return _parse_base_cached(str(base_path), year, stat.st_size, stat.st_mtime_ns)


def _find_coordinate_header(data: bytes) -> tuple[int, int, int]:
    chunk = _u32(data, 16)
    strings = _u32(data, 32)
    if chunk > len(data) - 40 or strings >= len(data):
        raise EBOError("Player EBO has invalid chunk or string-table offsets.")

    for offset in range(chunk, min(len(data), chunk + 800) - 40, 4):
        name_offset = _u32(data, offset)
        if name_offset >= 4096:
            continue
        try:
            if _string(data, strings + name_offset) != "coord":
                continue
        except (UnicodeDecodeError, ValueError):
            continue

        fields = struct.unpack_from("<10I", data, offset)
        byte_count, pointer, auxiliary = fields[3:6]
        if fields[1] != 0x666666 or fields[2] != 0:
            continue
        if fields[6:10] != (1, 0x3F800000, 0, 0):
            continue
        if pointer > len(data) or byte_count > len(data) - pointer:
            continue
        if auxiliary and (auxiliary < 4 or auxiliary > len(data)):
            continue
        return byte_count, pointer, auxiliary

    raise EBOError("Player EBO coordinate morph stream was not found.")


def parse_coordinate_stream(data: bytes, year: str) -> CoordinateStream:
    _validate_ebo(data, "Player model")
    byte_count, pointer, auxiliary = _find_coordinate_header(data)
    if byte_count % 4:
        raise EBOError("Player coordinate payload does not contain complete float32 values.")
    payload = struct.unpack_from(f"<{byte_count // 4}f", data, pointer)

    if year == "2006":
        if auxiliary or len(payload) != LOGICAL_COMPONENTS:
            raise EBOError("Selected NBA Live 2006, but the player EBO has no compatible dense coordinate stream.")
        return CoordinateStream(pointer, byte_count, payload, (True,) * LOGICAL_COMPONENTS)

    if year != "2005":
        raise EBOError(f"Unsupported NBA Live year: {year!r}.")
    if not auxiliary:
        raise EBOError("Selected NBA Live 2005, but the player EBO has no compatible sparse coordinate stream.")

    instruction_count = _u32(data, auxiliary - 4)
    if instruction_count > len(data) - auxiliary:
        raise EBOError("Sparse coordinate instructions extend beyond the player EBO.")

    values = []
    stored = []
    payload_index = 0
    for instruction in data[auxiliary:auxiliary + instruction_count]:
        if instruction & 0x80:
            count = (instruction & 0x7F) + 1
            if payload_index + count > len(payload):
                raise EBOError("Sparse coordinate run extends beyond its float payload.")
            values.extend(payload[payload_index:payload_index + count])
            stored.extend((True,) * count)
            payload_index += count
        else:
            values.extend((0.0,) * instruction)
            stored.extend((False,) * instruction)
            if payload_index >= len(payload):
                raise EBOError("Sparse coordinate instruction extends beyond its float payload.")
            values.append(payload[payload_index])
            stored.append(True)
            payload_index += 1

    if len(values) != LOGICAL_COMPONENTS or payload_index != len(payload):
        raise EBOError(
            f"Invalid sparse player coordinates: decoded {len(values)} components "
            f"and consumed {payload_index}/{len(payload)} floats."
        )
    return CoordinateStream(pointer, byte_count, tuple(values), tuple(stored))


def import_player(base_path: str | Path, player_path: str | Path, year: str) -> PlayerModel:
    base = parse_base(base_path, year)
    try:
        source = Path(player_path).read_bytes()
    except OSError as error:
        raise EBOError(f"Cannot open original player EBO: {player_path}") from error
    stream = parse_coordinate_stream(source, year)

    vertices = []
    for render_index, logical_index in enumerate(base.mapping):
        start = logical_index * 3
        vertices.append(tuple(
            _float32(base.positions[render_index][axis] + stream.values[start + axis])
            for axis in range(3)
        ))

    return PlayerModel(year, tuple(vertices), base.uvs, base.faces, hashlib.sha256(source).hexdigest())


def export_player(
    base_path: str | Path,
    source_path: str | Path,
    year: str,
    edited_vertices,
    original_vertices,
    *,
    expected_sha256: str | None = None,
) -> tuple[bytes, int]:
    base = parse_base(base_path, year)
    try:
        source = Path(source_path).read_bytes()
    except OSError as error:
        raise EBOError(f"Cannot open original player EBO: {source_path}") from error

    if expected_sha256 and hashlib.sha256(source).hexdigest() != expected_sha256:
        raise EBOError("The original player EBO changed after import. Reimport it before exporting.")

    vertex_count = GAME_VERTEX_COUNTS[year]
    edited = tuple(tuple(_float32(float(component)) for component in row) for row in edited_vertices)
    originals = tuple(tuple(_float32(float(component)) for component in row) for row in original_vertices)
    if len(edited) != vertex_count or len(originals) != vertex_count:
        raise EBOError(f"NBA Live {year} requires exactly {vertex_count} original render vertices.")
    if any(len(row) != 3 or any(not math.isfinite(value) for value in row) for row in edited):
        raise EBOError("Edited vertex positions must contain three finite coordinate values each.")

    stream = parse_coordinate_stream(source, year)
    updated = list(stream.values)
    groups = [[] for _ in range(LOGICAL_VERTICES)]
    changed_logical = set()

    for index, logical_index in enumerate(base.mapping):
        groups[logical_index].append(index)
        if edited[index] != originals[index]:
            changed_logical.add(logical_index)

    for logical_index in changed_logical:
        ids = groups[logical_index]
        for axis in range(3):
            edited_mean = sum(edited[index][axis] for index in ids) / len(ids)
            base_mean = sum(base.positions[index][axis] for index in ids) / len(ids)
            value = _float32(edited_mean - base_mean)
            component = logical_index * 3 + axis
            if not stream.stored_mask[component]:
                if abs(value) > SPARSE_ZERO_TOLERANCE:
                    axis_name = "XYZ"[axis]
                    raise EBOError(
                        f"NBA Live 2005 logical vertex {logical_index} changes its omitted "
                        f"{axis_name} coordinate. This would resize the original EBO; undo "
                        "that coordinate edit or choose another player/base face."
                    )
                continue
            updated[component] = value

    payload_values = [value for value, stored in zip(updated, stream.stored_mask) if stored]
    payload = struct.pack(f"<{len(payload_values)}f", *payload_values)
    if len(payload) != stream.size:
        raise EBOError("Refusing to change the original coordinate payload size.")

    result = bytearray(source)
    result[stream.offset:stream.offset + stream.size] = payload
    return bytes(result), len(changed_logical)

