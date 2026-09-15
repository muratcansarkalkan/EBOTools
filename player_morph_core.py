"""NBA Live 2005/06 high-detail head base + morph support.

v1.3.0-alpha milestone:
- load base_lodB EBO
- import the high-detail head mesh
- load a face-only B morph EBO
- reset to untouched base before every morph
- apply morph coordinates in-place to the same Blender mesh

Export is intentionally not enabled yet.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import struct

import numpy as np


class PlayerMorphError(ValueError):
    pass


@dataclass(frozen=True)
class HeadBase:
    geometry_name: str
    positions: np.ndarray       # rendered vertex positions, game coordinates
    mapping: np.ndarray         # rendered -> logical morph vertices
    uvs: np.ndarray
    faces: tuple[tuple[int,int,int], ...]
    logical_vertex_count: int
    rendered_vertex_count: int
    game_hint: str | None = None


@dataclass(frozen=True)
class MorphMapSegment:
    record_offset: int
    chunk_offset: int
    logical_vertex_count: int
    rendered_vertex_count: int
    position_ptr: int
    mapping_ptr: int
    vertex_buffer_header: int
    mapping: np.ndarray


@dataclass(frozen=True)
class DisplayGeometry:
    geometry_name: str
    positions: np.ndarray
    uvs: np.ndarray
    faces: tuple[tuple[int,int,int], ...]
    rendered_vertex_count: int
    morph_base: HeadBase | None = None


def _u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def _cstr(data: bytes, off: int) -> str:
    if off < 0 or off >= len(data):
        raise PlayerMorphError("String pointer outside EBO.")
    end = data.find(b"\0", off)
    if end < 0:
        raise PlayerMorphError("Unterminated EBO string.")
    return data[off:end].decode("ascii", "replace")


def _chunk_ranges(data: bytes):
    chunk_offset=_u32(data,16)
    chunk_count=struct.unpack_from("<H",data,36)[0]
    result=[]
    cursor=chunk_offset
    for _ in range(chunk_count):
        if cursor+0x14 > len(data):
            break
        size=_u32(data,cursor+0x10)
        if size < 0x14 or cursor+size > len(data):
            break
        result.append((cursor,cursor+size))
        cursor += size
    return result


def _owning_chunk_offset(data: bytes, file_offset: int):
    for start,end in _chunk_ranges(data):
        if start <= file_offset < end:
            return start
    return -1


def _mapping_candidates(data: bytes):
    """Find coordinate-map records without assuming one stream per Geometry.

    Some coach LODs split one logical morph domain across multiple material
    streams. Each record still contains the total logical count, a rendered
    stream count, source position pointer, mapping pointer and source VB header.
    """
    candidates=[]
    for off in range(0,len(data)-24,4):
        logical_count=_u32(data,off)
        one=_u32(data,off+4)
        rendered_count=_u32(data,off+8)
        position_ptr=_u32(data,off+12)
        mapping_ptr=_u32(data,off+16)
        vb_header=_u32(data,off+20)

        if one != 1:
            continue
        if logical_count < 16 or rendered_count < 3:
            continue
        if logical_count > 100000 or rendered_count > 100000:
            continue
        if mapping_ptr > len(data)-rendered_count*2:
            continue
        if position_ptr > len(data)-rendered_count*12:
            continue
        if vb_header+12 > len(data):
            continue

        vb_size=_u32(data,vb_header)
        vb_stride=_u32(data,vb_header+4)
        vb_ptr=_u32(data,vb_header+8)

        # Coordinate morph maps reference a Float3 source stream.
        if vb_stride != 12:
            continue
        if vb_size != rendered_count*12 or vb_ptr != position_ptr:
            continue

        mapping=np.frombuffer(
            data,dtype="<u2",count=rendered_count,offset=mapping_ptr
        ).copy()
        if len(mapping) != rendered_count:
            continue
        if int(mapping.max()) >= logical_count:
            continue

        candidates.append(
            MorphMapSegment(
                record_offset=off,
                chunk_offset=_owning_chunk_offset(data,off),
                logical_vertex_count=logical_count,
                rendered_vertex_count=rendered_count,
                position_ptr=position_ptr,
                mapping_ptr=mapping_ptr,
                vertex_buffer_header=vb_header,
                mapping=mapping,
            )
        )
    return candidates


def _geometry_exports(data: bytes):
    """Return (name, data_offset, owning_chunk_offset) for Geometry exports."""
    strings_offset=_u32(data,32)
    exports_offset=_u32(data,28)
    export_count=struct.unpack_from("<H",data,42)[0]

    def string_rel(rel):
        if rel == 0:
            return ""
        return _cstr(data,strings_offset+rel)

    result=[]
    for i in range(export_count):
        off=exports_offset+i*12
        type_rel,name_rel,data_rel=struct.unpack_from("<IIi",data,off)
        try:
            type_name=string_rel(type_rel)
            name=string_rel(name_rel)
        except Exception:
            continue
        if type_name != "Geometry":
            continue
        data_offset=off+data_rel
        result.append((name,data_offset,_owning_chunk_offset(data,data_offset)))
    return result


def _group_coordinate_mappings(data: bytes):
    """Group coordinate-map segments by owning Geometry chunk + logical domain."""
    groups={}
    for seg in _mapping_candidates(data):
        key=(seg.chunk_offset,seg.logical_vertex_count)
        groups.setdefault(key,[]).append(seg)

    complete=[]
    for (chunk_offset,logical_count),segments in groups.items():
        union=set()
        for seg in segments:
            union.update(map(int,seg.mapping))
        if len(union) != logical_count:
            continue
        if min(union) != 0 or max(union) != logical_count-1:
            continue
        complete.append((chunk_offset,logical_count,tuple(segments)))
    return complete


def _choose_head_mapping_group(data: bytes):
    groups=_group_coordinate_mappings(data)
    if not groups:
        raise PlayerMorphError(
            "No complete coordinate morph mapping group was found."
        )

    geometry_by_chunk={}
    for name,_data_off,chunk_off in _geometry_exports(data):
        geometry_by_chunk.setdefault(chunk_off,[]).append(name)

    scored=[]
    for chunk_off,logical_count,segments in groups:
        names=geometry_by_chunk.get(chunk_off,[])
        name=names[0] if names else ""
        lower=name.casefold()

        # Explicit head Geometry wins. Coach LODC merges the head into BaseCoach,
        # so BaseCoach is the next preferred morphable target.
        role=0
        if "head" in lower:
            role=3
        elif lower == "basecoach":
            role=2
        elif lower in {"baseplyr","baseplayer"}:
            role=1

        total_rendered=sum(seg.rendered_vertex_count for seg in segments)
        scored.append(
            (role,logical_count,total_rendered,name,chunk_off,segments)
        )

    scored.sort(key=lambda item:(item[0],item[1],item[2]),reverse=True)
    best=scored[0]

    # Only reject truly ambiguous structural candidates.
    if len(scored)>1 and scored[1][:3] == best[:3]:
        raise PlayerMorphError(
            "Two equally plausible primary morph targets were found."
        )

    _role,logical_count,_rendered,name,chunk_off,segments=best
    return name or f"MorphTarget_{logical_count}",logical_count,segments

def _find_position_buffer(data: bytes, rendered_count: int):
    wanted=rendered_count*12
    candidates=[]
    for off in range(0,len(data)-28,4):
        size=_u32(data,off)
        stride=_u32(data,off+4)
        ptr=_u32(data,off+8)
        if size != wanted or stride != 12 or ptr > len(data)-wanted:
            continue
        values=np.frombuffer(
            data,dtype="<f4",count=rendered_count*3,offset=ptr
        ).reshape(rendered_count,3).copy()
        if not np.isfinite(values).all():
            continue
        if float(np.abs(values).mean()) <= 1.0:
            continue
        candidates.append((off,ptr,values))
    if len(candidates) != 1:
        raise PlayerMorphError(
            f"Expected one {rendered_count}-vertex head position buffer; found {len(candidates)}."
        )
    return candidates[0]


def _find_uv_buffer(data: bytes, rendered_count: int):
    wanted=rendered_count*8
    candidates=[]
    for off in range(0,len(data)-28,4):
        size=_u32(data,off)
        stride=_u32(data,off+4)
        ptr=_u32(data,off+8)
        if size != wanted or stride != 8 or ptr > len(data)-wanted:
            continue
        values=np.frombuffer(
            data,dtype="<f4",count=rendered_count*2,offset=ptr
        ).reshape(rendered_count,2).copy()
        if not np.isfinite(values).all():
            continue
        # Mild sanity range only; do not hard-code exact UV range.
        if float(values.min()) < -16.0 or float(values.max()) > 16.0:
            continue
        candidates.append((off,ptr,values))
    if len(candidates) != 1:
        raise PlayerMorphError(
            f"Expected one {rendered_count}-vertex head UV buffer; found {len(candidates)}."
        )
    return candidates[0]


def _find_index_buffer(data: bytes, rendered_count: int):
    candidates=[]
    for off in range(0,len(data)-24,4):
        size=_u32(data,off)
        stride=_u32(data,off+4)
        ptr=_u32(data,off+8)
        if stride != 2 or size < 6 or size % 2 or ptr > len(data)-size:
            continue
        values=np.frombuffer(data,dtype="<u2",count=size//2,offset=ptr).copy()
        if not len(values):
            continue
        if int(values.max()) != rendered_count-1:
            continue
        if len(np.unique(values)) != rendered_count:
            continue
        candidates.append((off,ptr,values))
    if len(candidates) != 1:
        raise PlayerMorphError(
            f"Expected one {rendered_count}-vertex head index buffer; found {len(candidates)}."
        )
    return candidates[0]


def _strip_faces(indices):
    faces=[]
    for i in range(len(indices)-2):
        a,b,c=map(int,indices[i:i+3])
        if a==b or b==c or a==c:
            continue
        if i & 1:
            a,b=b,a
        faces.append((a,b,c))
    return tuple(faces)


def _guess_head_geometry_name(data: bytes, rendered_count: int):
    """Best-effort label only. Structural loading does not depend on this name."""
    for candidate in ("headAShape","headBShape","headShape","Head","head"):
        if candidate.encode("ascii")+b"\0" in data:
            return candidate
    return f"Head_{rendered_count}"


def _legacy_game_hint(logical_count: int, rendered_count: int):
    # Kept only for old .blend compatibility. Base geometry no longer decides
    # the game or morph codec from vertex counts.
    return None


def _find_unique_uv_buffer(data: bytes, rendered_count: int):
    """Find the rendered UV stream for one material segment."""
    wanted=rendered_count*8
    candidates=[]
    for off in range(0,len(data)-28,4):
        size=_u32(data,off)
        stride=_u32(data,off+4)
        ptr=_u32(data,off+8)
        if size != wanted or stride != 8 or ptr > len(data)-wanted:
            continue
        values=np.frombuffer(
            data,dtype="<f4",count=rendered_count*2,offset=ptr
        ).reshape(rendered_count,2).copy()
        if not np.isfinite(values).all():
            continue
        if float(values.min()) < -16.0 or float(values.max()) > 16.0:
            continue
        candidates.append((off,ptr,values))
    if len(candidates) != 1:
        raise PlayerMorphError(
            f"Expected one {rendered_count}-vertex UV stream; found {len(candidates)}."
        )
    return candidates[0]


def _find_unique_index_buffer(data: bytes, rendered_count: int):
    candidates=[]
    for off in range(0,len(data)-24,4):
        size=_u32(data,off)
        stride=_u32(data,off+4)
        ptr=_u32(data,off+8)
        if stride != 2 or size < 6 or size % 2 or ptr > len(data)-size:
            continue
        values=np.frombuffer(
            data,dtype="<u2",count=size//2,offset=ptr
        ).copy()
        if not len(values):
            continue
        if int(values.max()) != rendered_count-1:
            continue
        if len(np.unique(values)) != rendered_count:
            continue
        candidates.append((off,ptr,values))
    if len(candidates) != 1:
        raise PlayerMorphError(
            f"Expected one {rendered_count}-vertex index stream; found {len(candidates)}."
        )
    return candidates[0]


def load_head_base(path: str | Path) -> HeadBase:
    path=Path(path)
    data=path.read_bytes()

    if data[:4] != b"EBO\0":
        raise PlayerMorphError(f"{path.name}: not an EBO file.")
    if _u32(data,4) != 17:
        raise PlayerMorphError(f"{path.name}: expected EBO version 17.")

    geometry_name,logical_count,segments=_choose_head_mapping_group(data)

    positions_parts=[]
    mapping_parts=[]
    uv_parts=[]
    faces=[]
    rendered_base=0

    for seg in segments:
        rendered=seg.rendered_vertex_count

        positions=np.frombuffer(
            data,dtype="<f4",count=rendered*3,offset=seg.position_ptr
        ).reshape(rendered,3).copy()
        if not np.isfinite(positions).all():
            raise PlayerMorphError(
                f"{geometry_name}: non-finite coordinate stream."
            )

        _uv_off,_uv_ptr,uvs=_find_unique_uv_buffer(data,rendered)
        _idx_off,_idx_ptr,strip=_find_unique_index_buffer(data,rendered)

        positions_parts.append(positions)
        mapping_parts.append(seg.mapping)
        uv_parts.append(uvs)

        for a,b,c in _strip_faces(strip):
            faces.append(
                (a+rendered_base,b+rendered_base,c+rendered_base)
            )
        rendered_base += rendered

    positions=np.concatenate(positions_parts,axis=0)
    mapping=np.concatenate(mapping_parts,axis=0)
    uvs=np.concatenate(uv_parts,axis=0)

    return HeadBase(
        geometry_name=geometry_name,
        positions=positions,
        mapping=mapping,
        uvs=uvs,
        faces=tuple(faces),
        logical_vertex_count=logical_count,
        rendered_vertex_count=len(positions),
        game_hint=None,
    )


def _find_coord_stream(data: bytes):
    if data[:4] != b"EBO\0":
        raise PlayerMorphError("Morph file is not an EBO.")
    strings = _u32(data,32)
    chunk = _u32(data,16)

    # Face-only B morph files have a single coord stream close to the start of
    # the first chunk. Keep the validation strict enough to avoid TOC/string
    # coincidences.
    found = []
    for off in range(chunk, min(len(data), chunk+1200)-40, 4):
        rel = _u32(data,off)
        if rel >= 4096 or strings+rel >= len(data):
            continue
        try:
            name = _cstr(data, strings+rel)
        except Exception:
            continue
        if name != "coord":
            continue
        fields = [_u32(data,off+4*i) for i in range(10)]
        size,payload,aux = fields[3:6]
        if fields[2] != 0 or fields[6] != 1 or fields[7] != 0x3F800000:
            continue
        if fields[8] != 0 or fields[9] != 0:
            continue
        if payload > len(data) or size > len(data)-payload:
            continue
        if aux and (aux < 4 or aux > len(data)):
            continue
        found.append((off,fields))

    if len(found) != 1:
        raise PlayerMorphError(
            f"Expected one face coordinate MorphStreamHeader; found {len(found)}. "
            "v1.3.0-alpha currently targets face-only B morph files."
        )
    return found[0]


def _decode_sparse_2005(data: bytes, fields, logical_vertex_count: int = 573) -> np.ndarray:
    size,payload_off,aux_off = fields[3:6]
    if size % 4:
        raise PlayerMorphError("2005 coordinate payload is not float32-aligned.")
    payload = np.frombuffer(data,dtype="<f4",count=size//4,offset=payload_off)

    if aux_off < 4:
        raise PlayerMorphError("2005 sparse coordinate stream has no instruction block.")
    instruction_count = _u32(data, aux_off-4)
    if instruction_count > len(data)-aux_off:
        raise PlayerMorphError("2005 sparse coordinate instruction block exceeds EBO.")

    components = []
    payload_index = 0
    for instruction in data[aux_off:aux_off+instruction_count]:
        if instruction & 0x80:
            count = (instruction & 0x7F) + 1
            if payload_index + count > len(payload):
                raise PlayerMorphError("2005 sparse literal run exceeds coordinate payload.")
            components.extend(payload[payload_index:payload_index+count])
            payload_index += count
        else:
            # EA's sparse head codec stores N omitted zero components followed
            # by one literal float.
            components.extend([0.0] * instruction)
            if payload_index >= len(payload):
                raise PlayerMorphError("2005 sparse run exceeds coordinate payload.")
            components.append(payload[payload_index])
            payload_index += 1

    expected=logical_vertex_count*3
    if len(components) != expected or payload_index != len(payload):
        raise PlayerMorphError(
            f"Sparse face morph decoded {len(components)} components and consumed "
            f"{payload_index}/{len(payload)} floats; expected {expected} components."
        )
    return np.asarray(components,dtype=np.float32).reshape(logical_vertex_count,3)


def inspect_face_morph(path: str | Path, logical_vertex_count: int):
    """Inspect the coordinate stream and identify the codec structurally."""
    path=Path(path)
    data=path.read_bytes()
    _header_off,fields=_find_coord_stream(data)

    size,payload,aux=fields[3:6]
    dense_size=logical_vertex_count*3*4

    if aux == 0 and size == dense_size:
        return {
            "codec":"dense_f32",
            "logical_vertex_count":logical_vertex_count,
            "fields":fields,
            "data":data,
        }

    if aux != 0:
        return {
            "codec":"sparse_f32_rle",
            "logical_vertex_count":logical_vertex_count,
            "fields":fields,
            "data":data,
        }

    raise PlayerMorphError(
        f"{path.name}: unsupported face coord stream: "
        f"size={size}, aux=0x{aux:X}, expected dense size={dense_size}."
    )


def load_face_morph(path: str | Path, logical_vertex_count: int) -> np.ndarray:
    info=inspect_face_morph(path,logical_vertex_count)
    data=info["data"]
    fields=info["fields"]

    if info["codec"] == "dense_f32":
        size,payload,_aux=fields[3:6]
        return np.frombuffer(
            data,dtype="<f4",count=logical_vertex_count*3,offset=payload
        ).reshape(logical_vertex_count,3).copy()

    if info["codec"] == "sparse_f32_rle":
        decoded=_decode_sparse_2005(data,fields,logical_vertex_count)
        if decoded.shape != (logical_vertex_count,3):
            raise PlayerMorphError(
                f"Sparse morph decoded {decoded.shape[0]} logical vertices; "
                f"base requires {logical_vertex_count}."
            )
        return decoded

    raise PlayerMorphError(f"Unsupported morph codec {info['codec']!r}.")

def morphed_render_positions(base: HeadBase, logical_delta: np.ndarray) -> np.ndarray:
    expected=(base.logical_vertex_count,3)
    if logical_delta.shape != expected:
        raise PlayerMorphError(f"Expected {expected} morph delta; got {logical_delta.shape}.")
    return base.positions + logical_delta[base.mapping]


def _blender_to_game(position):
    """Inverse of the Blender import transform: game (x,y,z) -> (x,-z,y)."""
    x,y,z = map(float,position)
    return (x,z,-y)


def logical_delta_from_edited(base: HeadBase, blender_positions):
    """Collapse edited rendered seam vertices back to 573 logical morph vertices.

    Duplicate rendered vertices that map to the same logical morph vertex are
    averaged. max_spread reports how far those duplicates diverged so the UI
    can warn the user about editing only one side of a UV seam.
    """
    if len(blender_positions) != len(base.positions):
        raise PlayerMorphError(
            f"Edited mesh has {len(blender_positions)} vertices; "
            f"base has {len(base.positions)}."
        )

    edited = np.asarray(
        [_blender_to_game(p) for p in blender_positions],
        dtype=np.float32,
    )
    rendered_delta = edited - base.positions

    logical_count=base.logical_vertex_count
    logical = np.zeros((logical_count,3),dtype=np.float32)
    counts = np.zeros(logical_count,dtype=np.int32)
    for rendered_index, logical_index in enumerate(base.mapping):
        li=int(logical_index)
        logical[li] += rendered_delta[rendered_index]
        counts[li] += 1

    if np.any(counts == 0):
        missing=np.where(counts==0)[0]
        raise PlayerMorphError(
            f"Base mapping does not cover logical morph vertices: {missing[:12].tolist()}"
        )
    logical /= counts[:,None]

    max_spread=0.0
    for rendered_index, logical_index in enumerate(base.mapping):
        diff=rendered_delta[rendered_index]-logical[int(logical_index)]
        max_spread=max(max_spread,float(np.linalg.norm(diff)))

    return logical,max_spread


def _all_literal_sparse_stream(values: np.ndarray):
    """Encode the 2005 sparse stream using only valid literal runs.

    2005's face codec accepts high-bit control bytes for literal float runs.
    Using only literal runs intentionally sacrifices a few bytes of compression
    in exchange for allowing every edited XYZ component to become non-zero.
    """
    flat=np.asarray(values,dtype="<f4").reshape(-1)
    controls=bytearray()
    cursor=0
    while cursor < len(flat):
        count=min(128,len(flat)-cursor)
        controls.append(0x80 | (count-1))
        cursor += count
    return flat.tobytes(),bytes(controls)


def _compact_sparse_stream(values: np.ndarray, zero_epsilon: float = 0.0):
    """Encode EA's sparse float stream using zero runs + literal runs.

    Control grammar verified from shipped morphs:
        high bit set: copy (low7 + 1) literal floats
        high bit clear: emit N zero components, then one literal float

    Trailing zero runs use a zero-valued literal so the stream can end cleanly.
    """
    flat=np.asarray(values,dtype=np.float32).reshape(-1)
    payload=[]
    controls=bytearray()
    i=0
    n=len(flat)

    def is_zero(v):
        return abs(float(v)) <= zero_epsilon

    while i < n:
        if is_zero(flat[i]):
            run=0
            while i+run < n and is_zero(flat[i+run]) and run < 127:
                run += 1

            if i+run < n:
                controls.append(run)
                payload.append(flat[i+run])
                i += run + 1
            else:
                # N omitted zeros + one literal zero = N+1 zeros.
                controls.append(run-1)
                payload.append(np.float32(0.0))
                i += run
            continue

        start=i
        while i < n and not is_zero(flat[i]) and i-start < 128:
            i += 1
        count=i-start
        controls.append(0x80 | (count-1))
        payload.extend(flat[start:i])

    payload_bytes=np.asarray(payload,dtype="<f4").tobytes()
    return payload_bytes,bytes(controls)


def _sparse_slot_info(data: bytes, fields):
    """Return the shipped contiguous sparse slot [payload, controls_end)."""
    size,payload,aux=fields[3:6]
    if aux < 4 or payload >= len(data):
        raise PlayerMorphError("Sparse stream has invalid payload/aux pointers.")
    control_count=_u32(data,aux-4)
    end=aux+control_count
    if end > len(data):
        raise PlayerMorphError("Sparse stream instruction block exceeds EBO.")
    # Shipped coordinate streams place payload, u32 control count and controls
    # contiguously. Refuse to overwrite unrelated data if that is not true.
    if aux-4 != payload+size:
        raise PlayerMorphError(
            "Sparse coord payload/instruction layout is not contiguous; "
            "safe in-place export is unavailable for this stream."
        )
    return payload,end,end-payload


def _rebuild_one_chunk_container_with_raw(source_data: bytes, new_chunk_raw: bytes) -> bytes:
    """Rebuild the EBO tables after growing the single morph chunk.

    Face morph samples use one chunk. Appending replacement coord data to the
    end of that chunk leaves all pre-existing chunk-internal absolute offsets
    unchanged; only the container tables/string pool move.
    """
    # Local import keeps player_morph_core usable for base/morph inspection
    # without making generic container code part of the public API.
    try:
        from . import ebo_generic
    except ImportError as exc:
        raise PlayerMorphError("EBO container helper is unavailable.") from exc

    ebo=ebo_generic.parse_ebo(source_data)
    if len(ebo.chunks) != 1:
        raise PlayerMorphError(
            f"2005 face morph export expected one chunk; found {len(ebo.chunks)}."
        )

    chunk=ebo.chunks[0]
    new_chunk=replace(
        chunk,
        size=len(new_chunk_raw),
        raw=bytes(new_chunk_raw),
    )
    rebuilt=replace(
        ebo,
        chunks=(new_chunk,),
        source_data=source_data,
    )
    return ebo_generic.rebuild_container_exact(rebuilt)


def _export_2006_dense(template_data: bytes, logical_delta: np.ndarray) -> bytes:
    header_off,fields=_find_coord_stream(template_data)
    size,payload,aux=fields[3:6]
    expected=np.asarray(logical_delta).shape[0]*3*4
    if size != expected or aux != 0:
        raise PlayerMorphError(
            f"Selected template does not contain the expected dense face coord stream "
            f"({expected} bytes, aux=0)."
        )
    out=bytearray(template_data)
    out[payload:payload+size]=np.asarray(logical_delta,dtype="<f4").reshape(-1).tobytes()
    return bytes(out)


def _export_2005_sparse(template_data: bytes, logical_delta: np.ndarray) -> bytes:
    """Rewrite a sparse face-coordinate stream without assuming an i8 TOC.

    Some shipped player morphs expose the raw sparse area through an i8 TOC.
    Coach morphs can point to the same payload/instruction data directly from
    MorphStreamHeader without any i8 TOC at all. The runtime-relevant contract
    is the MorphStreamHeader pointer pair, not the presence of that raw TOC.
    """
    header_off,fields=_find_coord_stream(template_data)
    _old_size,_old_payload,old_aux=fields[3:6]
    if old_aux == 0:
        raise PlayerMorphError(
            "Selected template does not contain a sparse face coordinate stream."
        )

    try:
        from . import ebo_generic
    except ImportError as exc:
        raise PlayerMorphError("EBO container helper is unavailable.") from exc

    ebo=ebo_generic.parse_ebo(template_data)
    if len(ebo.chunks) != 1:
        raise PlayerMorphError(
            f"Sparse face morph export currently expects one chunk; found {len(ebo.chunks)}."
        )
    chunk=ebo.chunks[0]

    payload_bytes,controls=_all_literal_sparse_stream(logical_delta)

    # Prefer extending an existing raw i8 area when present, preserving the
    # shipped player's layout. Coach morphs commonly have no such TOC; in that
    # case append the replacement sparse block to the end of the morph chunk.
    i8_tocs=[toc for toc in chunk.tocs if toc.type_name=="i8"]

    if len(i8_tocs) > 1:
        raise PlayerMorphError(
            f"Sparse morph contains {len(i8_tocs)} raw i8 TOCs; "
            "cannot choose one safely yet."
        )

    raw_toc=i8_tocs[0] if i8_tocs else None

    if raw_toc is not None:
        insertion_abs=raw_toc.data_offset + raw_toc.struct_count
        insertion_local=insertion_abs - chunk.file_offset
        if not 0 <= insertion_local <= len(chunk.raw):
            raise PlayerMorphError("Sparse raw-stream append location is invalid.")
    else:
        insertion_local=len(chunk.raw)
        insertion_abs=chunk.file_offset + insertion_local

    block=bytearray()
    new_payload_abs=insertion_abs
    block += payload_bytes
    block += len(controls).to_bytes(4,"little")
    new_aux_abs=new_payload_abs + len(payload_bytes) + 4
    block += controls

    before=bytearray(chunk.raw[:insertion_local])
    tail=bytearray(chunk.raw[insertion_local:])
    new_raw=before + block + tail

    # Keep chunk size aligned. The extra alignment bytes are not part of the
    # sparse instruction stream.
    while len(new_raw) & 3:
        new_raw += b"\0"

    local_header=header_off - chunk.file_offset
    struct.pack_into("<I",new_raw,local_header+12,len(payload_bytes))
    struct.pack_into("<I",new_raw,local_header+16,new_payload_abs)
    struct.pack_into("<I",new_raw,local_header+20,new_aux_abs)

    # If a raw i8 TOC exists, extend its element count over the newly inserted
    # bytes. If no i8 TOC exists (coach case), there is nothing to update:
    # MorphStreamHeader owns the payload/aux pointers directly.
    if raw_toc is not None:
        new_i8_count=raw_toc.struct_count + len(block)
        local_toc=raw_toc.file_offset - chunk.file_offset
        struct.pack_into("<I",new_raw,local_toc+4,new_i8_count)

    struct.pack_into("<I",new_raw,0x10,len(new_raw))

    rebuilt=_rebuild_one_chunk_container_with_raw(template_data,bytes(new_raw))

    # Self-check through the same structural decoder before writing the file.
    _off,check_fields=_find_coord_stream(rebuilt)
    check=_decode_sparse_2005(
        rebuilt,check_fields,np.asarray(logical_delta).shape[0]
    )
    if not np.allclose(check,logical_delta,atol=1e-6):
        raise PlayerMorphError("Internal sparse morph export verification failed.")

    return rebuilt


def export_face_morph(
    template_path: str | Path,
    output_path: str | Path,
    logical_delta: np.ndarray,
):
    """Export edited face coordinates using the loaded morph's own codec."""
    template_path=Path(template_path)
    output_path=Path(output_path)

    delta=np.asarray(logical_delta,dtype=np.float32)
    if delta.ndim != 2 or delta.shape[1] != 3:
        raise PlayerMorphError(
            f"Expected (logical_vertex_count,3) morph delta; got {delta.shape}."
        )

    info=inspect_face_morph(template_path,delta.shape[0])
    data=info["data"]

    if info["codec"]=="dense_f32":
        rebuilt=_export_2006_dense(data,delta)
    elif info["codec"]=="sparse_f32_rle":
        rebuilt=_export_2005_sparse(data,delta)
    else:
        raise PlayerMorphError(f"Unsupported export codec {info['codec']!r}.")

    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_bytes(rebuilt)
    return len(rebuilt),info["codec"]


# ===========================================================================
# Multi-Geometry player/coach morph workflow
# ===========================================================================

def _geometry_materials(data: bytes, geometry_data_offset: int):
    """Return material records for a Geometry using the verified 0x30 layout."""
    if geometry_data_offset < 0 or geometry_data_offset + 0x1C > len(data):
        return []
    count=_u32(data,geometry_data_offset+0x14)
    ptr=_u32(data,geometry_data_offset+0x18)
    if count > 256 or ptr > len(data)-count*0x30:
        return []

    result=[]
    for i in range(count):
        mo=ptr+i*0x30
        per_vars=_u32(data,mo+0x0C)
        result.append((i,mo,per_vars))
    return result


def _material_compiled_streams(data: bytes, per_vars: int):
    """Decode the common compiled skin material stream pointers.

    Verified player/coach material variables use:
        +0x10 position PCVertexBuffer*
        +0x1C UV PCVertexBuffer*
        +0x20 PCIndexBuffer*
        +0x24 rendered vertex count
    """
    if per_vars <= 0 or per_vars + 0x2C > len(data):
        return None

    pos_vb=_u32(data,per_vars+0x10)
    uv_vb=_u32(data,per_vars+0x1C)
    index_buffer=_u32(data,per_vars+0x20)
    rendered_count=_u32(data,per_vars+0x24)

    if rendered_count < 3 or rendered_count > 100000:
        return None
    if pos_vb+12 > len(data) or uv_vb+12 > len(data) or index_buffer+12 > len(data):
        return None

    pos_size,pos_stride,pos_ptr=struct.unpack_from("<III",data,pos_vb)
    uv_size,uv_stride,uv_ptr=struct.unpack_from("<III",data,uv_vb)
    idx_size,idx_stride,idx_ptr=struct.unpack_from("<III",data,index_buffer)

    if pos_stride != 12 or pos_size != rendered_count*12:
        return None
    if uv_stride != 8 or uv_size != rendered_count*8:
        return None
    if idx_stride != 2 or idx_size < 6 or idx_size % 2:
        return None
    if pos_ptr > len(data)-pos_size or uv_ptr > len(data)-uv_size or idx_ptr > len(data)-idx_size:
        return None

    return {
        "position_vb":pos_vb,
        "position_ptr":pos_ptr,
        "uv_vb":uv_vb,
        "uv_ptr":uv_ptr,
        "index_buffer":index_buffer,
        "index_ptr":idx_ptr,
        "index_count":idx_size//2,
        "rendered_count":rendered_count,
    }


def load_morphable_bases(path: str | Path):
    """Load every complete coordinate-morph Geometry from a player/coach base EBO."""
    path=Path(path)
    data=path.read_bytes()
    if data[:4] != b"EBO\0":
        raise PlayerMorphError(f"{path.name}: not an EBO file.")
    if _u32(data,4) != 17:
        raise PlayerMorphError(f"{path.name}: expected EBO version 17.")

    exports=_geometry_exports(data)
    groups=_group_coordinate_mappings(data)

    # Geometry lookup by owning chunk.
    geo_by_chunk={}
    geo_data_by_name={}
    for name,data_off,chunk_off in exports:
        geo_by_chunk.setdefault(chunk_off,[]).append(name)
        geo_data_by_name[name]=data_off

    result=[]
    for chunk_off,logical_count,segments in groups:
        names=geo_by_chunk.get(chunk_off,[])
        if not names:
            continue
        geometry_name=names[0]
        geometry_data=geo_data_by_name[geometry_name]

        # Associate each coordinate mapping segment with the material whose
        # position PCVertexBuffer pointer is identical.
        materials=[]
        for _mi,_mo,per_vars in _geometry_materials(data,geometry_data):
            streams=_material_compiled_streams(data,per_vars)
            if streams is not None:
                materials.append(streams)

        material_by_posvb={m["position_vb"]:m for m in materials}

        positions_parts=[]
        mapping_parts=[]
        uv_parts=[]
        faces=[]
        rendered_base=0
        matched=0

        for seg in segments:
            streams=material_by_posvb.get(seg.vertex_buffer_header)
            if streams is None:
                continue

            rendered=seg.rendered_vertex_count
            if streams["rendered_count"] != rendered:
                continue

            positions=np.frombuffer(
                data,dtype="<f4",count=rendered*3,offset=streams["position_ptr"]
            ).reshape(rendered,3).copy()
            uvs=np.frombuffer(
                data,dtype="<f4",count=rendered*2,offset=streams["uv_ptr"]
            ).reshape(rendered,2).copy()
            strip=np.frombuffer(
                data,dtype="<u2",count=streams["index_count"],offset=streams["index_ptr"]
            ).copy()

            positions_parts.append(positions)
            mapping_parts.append(seg.mapping)
            uv_parts.append(uvs)
            for a,b,c in _strip_faces(strip):
                faces.append((a+rendered_base,b+rendered_base,c+rendered_base))
            rendered_base += rendered
            matched += 1

        if matched != len(segments) or not positions_parts:
            # Do not emit a partial morph object.
            continue

        positions=np.concatenate(positions_parts,axis=0)
        mapping=np.concatenate(mapping_parts,axis=0)
        uvs=np.concatenate(uv_parts,axis=0)

        result.append(
            HeadBase(
                geometry_name=geometry_name,
                positions=positions,
                mapping=mapping,
                uvs=uvs,
                faces=tuple(faces),
                logical_vertex_count=logical_count,
                rendered_vertex_count=len(positions),
                game_hint=None,
            )
        )

    if not result:
        raise PlayerMorphError(
            f"{path.name}: no complete morphable Geometry objects could be reconstructed."
        )
    return tuple(result)


def load_all_base_geometry(path: str | Path):
    """Load every reconstructable Geometry for a complete visual player/coach.

    Geometry with a verified logical morph mapping carries morph_base.
    Ordinary Geometry (hands, shoes, etc.) is still imported visually but
    remains display-only until its rendered->logical morph mapping is decoded.
    """
    path=Path(path)
    data=path.read_bytes()
    if data[:4] != b"EBO\0":
        raise PlayerMorphError(f"{path.name}: not an EBO file.")

    try:
        mapped={item.geometry_name:item for item in load_morphable_bases(path)}
    except PlayerMorphError:
        # Accessory EBOs such as hair/headbands/goggles can be ordinary
        # Geometry-only files with no logical morph mapping at all.
        mapped={}
    result=[]

    for name,gdo,_chunk in _geometry_exports(data):
        if name in mapped:
            base=mapped[name]
            result.append(DisplayGeometry(
                geometry_name=name,
                positions=base.positions,
                uvs=base.uvs,
                faces=base.faces,
                rendered_vertex_count=base.rendered_vertex_count,
                morph_base=base,
            ))
            continue

        positions_parts=[]
        uv_parts=[]
        faces=[]
        rendered_base=0

        for _mi,_mo,per_vars in _geometry_materials(data,gdo):
            streams=_material_compiled_streams(data,per_vars)
            if streams is None:
                continue
            rendered=streams["rendered_count"]

            positions=np.frombuffer(
                data,dtype="<f4",count=rendered*3,offset=streams["position_ptr"]
            ).reshape(rendered,3).copy()
            uvs=np.frombuffer(
                data,dtype="<f4",count=rendered*2,offset=streams["uv_ptr"]
            ).reshape(rendered,2).copy()
            strip=np.frombuffer(
                data,dtype="<u2",count=streams["index_count"],offset=streams["index_ptr"]
            ).copy()

            positions_parts.append(positions)
            uv_parts.append(uvs)
            for a,b,c in _strip_faces(strip):
                faces.append((a+rendered_base,b+rendered_base,c+rendered_base))
            rendered_base += rendered

        if not positions_parts:
            continue

        result.append(DisplayGeometry(
            geometry_name=name,
            positions=np.concatenate(positions_parts,axis=0),
            uvs=np.concatenate(uv_parts,axis=0),
            faces=tuple(faces),
            rendered_vertex_count=rendered_base,
            morph_base=None,
        ))

    if not result:
        raise PlayerMorphError(f"{path.name}: no reconstructable Geometry found.")
    return tuple(result)


def _morph_exports(data: bytes):
    """Return morph export name -> (data_offset, owning chunk start/end)."""
    strings_offset=_u32(data,32)
    exports_offset=_u32(data,28)
    export_count=struct.unpack_from("<H",data,42)[0]
    ranges=_chunk_ranges(data)

    result={}
    for i in range(export_count):
        off=exports_offset+i*12
        type_rel,name_rel,data_rel=struct.unpack_from("<IIi",data,off)
        try:
            type_name=_cstr(data,strings_offset+type_rel)
            name=_cstr(data,strings_offset+name_rel)
        except Exception:
            continue
        if type_name != "Morph":
            continue
        data_offset=off+data_rel
        for start,end in ranges:
            if start <= data_offset < end:
                result[name]=(data_offset,start,end)
                break
    return result


def _coord_stream_in_chunk(data: bytes, chunk_start: int, chunk_end: int):
    """Find the coord MorphStreamHeader inside one Morph chunk."""
    strings=_u32(data,32)
    found=[]
    # Morph headers live near the start, but scan the whole chunk conservatively.
    for off in range(chunk_start,chunk_end-40,4):
        rel=_u32(data,off)
        if rel >= 0x10000 or strings+rel >= len(data):
            continue
        try:
            name=_cstr(data,strings+rel)
        except Exception:
            continue
        if name != "coord":
            continue
        fields=[_u32(data,off+4*i) for i in range(10)]
        size,payload,aux=fields[3:6]
        if payload > len(data) or size > len(data)-payload:
            continue
        if fields[6] != 1 or fields[7] != 0x3F800000:
            continue
        found.append((off,fields))

    if not found:
        return None
    if len(found) != 1:
        raise PlayerMorphError(
            f"Morph chunk at 0x{chunk_start:X} contains {len(found)} coord streams."
        )
    return found[0]


def inspect_morph_geometry(
    data: bytes,
    geometry_name: str,
    logical_vertex_count: int,
):
    exports=_morph_exports(data)
    key=geometry_name+"_morphs"
    item=exports.get(key)
    if item is None:
        return None

    _data_off,chunk_start,chunk_end=item
    header=_coord_stream_in_chunk(data,chunk_start,chunk_end)
    if header is None:
        return {
            "geometry_name":geometry_name,
            "export_name":key,
            "chunk_start":chunk_start,
            "chunk_end":chunk_end,
            "codec":"none",
            "header":None,
        }

    header_off,fields=header
    size,payload,aux=fields[3:6]
    dense_size=logical_vertex_count*3*4

    if aux == 0 and size == dense_size:
        codec="dense_f32"
    elif aux != 0:
        codec="sparse_f32_rle"
    else:
        raise PlayerMorphError(
            f"{key}: coord size={size}, aux=0x{aux:X}; "
            f"expected dense size={dense_size}."
        )

    return {
        "geometry_name":geometry_name,
        "export_name":key,
        "chunk_start":chunk_start,
        "chunk_end":chunk_end,
        "codec":codec,
        "header":header,
    }


def decode_morph_geometry(data: bytes, geometry_name: str, logical_vertex_count: int):
    info=inspect_morph_geometry(data,geometry_name,logical_vertex_count)
    if info is None or info["codec"]=="none":
        return None,info

    _header_off,fields=info["header"]
    if info["codec"]=="dense_f32":
        _size,payload,_aux=fields[3:6]
        delta=np.frombuffer(
            data,dtype="<f4",count=logical_vertex_count*3,offset=payload
        ).reshape(logical_vertex_count,3).copy()
    else:
        delta=_decode_sparse_2005(data,fields,logical_vertex_count)
    return delta,info


def _string_pool(strings, prefix):
    pool=bytearray(prefix)
    offsets={}
    for value in strings:
        if value in offsets:
            continue
        offsets[value]=len(pool)
        raw=value.encode("ascii")+b"\0"
        pool += raw
        if len(raw)&1:
            pool += b"\0"
    return bytes(pool),offsets


def _rebuild_container_with_blob(
    source_data: bytes,
    patched_chunk_bytes: bytes,
    blob: bytes,
):
    """Preserve all chunks at their original absolute addresses and move only tables.

    This is ideal for multi-Morph export: sparse replacement streams can live
    in an external data area between the last chunk and the rebuilt EBO tables,
    while every existing chunk-internal base-relative pointer remains valid.
    """
    try:
        from . import ebo_generic
    except ImportError as exc:
        raise PlayerMorphError("EBO container helper is unavailable.") from exc

    ebo=ebo_generic.parse_ebo(source_data)
    if not ebo.chunks:
        raise PlayerMorphError("Morph EBO has no chunks.")

    last_end=max(c.file_offset+c.size for c in ebo.chunks)
    if len(patched_chunk_bytes) != last_end:
        raise PlayerMorphError("Internal patched chunk area size mismatch.")

    pool,string_offsets=_string_pool(ebo.strings,ebo.string_prefix)

    cursor=last_end+len(blob)
    cursor=(cursor+3)&~3
    usd_offset=cursor
    imports_offset=usd_offset+len(ebo.usd_types)*4
    iat_count=sum(len(item.fixup_field_offsets) for item in ebo.imports)
    iat_offset=imports_offset+len(ebo.imports)*0x18
    exports_offset=(iat_offset+iat_count*4+3)&~3
    strings_offset=(exports_offset+len(ebo.exports)*0x0C+3)&~3
    final_size=strings_offset+len(pool)

    out=bytearray(final_size)
    # Header
    struct.pack_into(
        "<IIIHHIIIIIHHHHH",out,0,
        0x004F4245,
        ebo.header.version,
        final_size,
        ebo.header.endian_original,
        ebo.header.endian_current,
        0x60,
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
    out[struct.calcsize("<IIIHHIIIIIHHHHH"):0x60]=ebo.header.tail_bytes
    out[0x60:last_end]=patched_chunk_bytes[0x60:last_end]
    out[last_end:last_end+len(blob)]=blob

    for i,type_name in enumerate(ebo.usd_types):
        struct.pack_into("<I",out,usd_offset+i*4,string_offsets[type_name])

    iat_cursor=iat_offset
    for i,item in enumerate(ebo.imports):
        off=imports_offset+i*0x18
        struct.pack_into(
            "<IIIIII",out,off,
            0,0,
            string_offsets[item.type_name],
            string_offsets[item.name],
            iat_cursor-off,
            len(item.fixup_field_offsets),
        )
        for field_offset in item.fixup_field_offsets:
            struct.pack_into("<i",out,iat_cursor,field_offset-off)
            iat_cursor += 4

    for i,item in enumerate(ebo.exports):
        off=exports_offset+i*0x0C
        struct.pack_into(
            "<IIi",out,off,
            string_offsets[item.type_name],
            string_offsets[item.name],
            item.data_offset-off,
        )

    out[strings_offset:strings_offset+len(pool)]=pool
    return bytes(out)


def export_multi_morph(
    template_path: str | Path,
    output_path: str | Path,
    logical_deltas: dict[str,np.ndarray],
):
    """Export multiple edited Geometry morphs without relocating Morph chunks.

    Dense coord streams are rewritten in place.

    Sparse coord streams are compactly re-encoded and rewritten only inside
    their original shipped payload/control slot. If an edited sparse stream
    no longer fits that slot, export stops with a clear error rather than
    producing an EBO whose pointers leave the owning Morph chunk.
    """
    template_path=Path(template_path)
    output_path=Path(output_path)
    source=template_path.read_bytes()
    patched=bytearray(source)

    changed=[]
    skipped=[]
    sparse_stats=[]

    for geometry_name,raw_delta in logical_deltas.items():
        delta=np.asarray(raw_delta,dtype=np.float32)
        if delta.ndim != 2 or delta.shape[1] != 3:
            raise PlayerMorphError(
                f"{geometry_name}: expected (logical_count,3), got {delta.shape}."
            )
        if not np.isfinite(delta).all():
            raise PlayerMorphError(
                f"{geometry_name}: edited morph contains NaN/Inf coordinates."
            )

        info=inspect_morph_geometry(source,geometry_name,delta.shape[0])
        if info is None:
            skipped.append((geometry_name,"no Morph export"))
            continue
        if info["codec"]=="none":
            skipped.append((geometry_name,"Morph has no coord stream"))
            continue

        header_off,fields=info["header"]

        if info["codec"]=="dense_f32":
            size,payload,_aux=fields[3:6]
            raw=np.asarray(delta,dtype="<f4").reshape(-1).tobytes()
            if len(raw) != size:
                raise PlayerMorphError(
                    f"{geometry_name}: dense replacement size mismatch."
                )
            patched[payload:payload+size]=raw
            changed.append((geometry_name,"dense_f32"))
            continue

        # Sparse: stay entirely inside the original stream's allocated slot.
        old_payload,old_end,capacity=_sparse_slot_info(source,fields)
        payload_bytes,controls=_compact_sparse_stream(delta)
        required=len(payload_bytes)+4+len(controls)

        if required > capacity:
            raise PlayerMorphError(
                f"{geometry_name}: edited sparse morph needs {required} bytes, "
                f"but its original safe slot is {capacity} bytes. "
                f"Reduce the edited area for now; this exporter will not relocate "
                f"later Morph chunks because that can crash EAGL traversal."
            )

        new_aux=old_payload+len(payload_bytes)+4
        struct.pack_into("<I",patched,header_off+12,len(payload_bytes))
        struct.pack_into("<I",patched,header_off+16,old_payload)
        struct.pack_into("<I",patched,header_off+20,new_aux)

        cursor=old_payload
        patched[cursor:cursor+len(payload_bytes)]=payload_bytes
        cursor += len(payload_bytes)
        struct.pack_into("<I",patched,cursor,len(controls))
        cursor += 4
        patched[cursor:cursor+len(controls)]=controls
        cursor += len(controls)

        if cursor < old_end:
            patched[cursor:old_end]=b"\0"*(old_end-cursor)

        changed.append((geometry_name,"sparse_f32_rle"))
        sparse_stats.append((geometry_name,required,capacity))

    rebuilt=bytes(patched)

    # Self-check every changed stream from the exact bytes that will be written.
    for geometry_name,codec in changed:
        expected=np.asarray(logical_deltas[geometry_name],dtype=np.float32)
        decoded,info=decode_morph_geometry(
            rebuilt,geometry_name,expected.shape[0]
        )
        if decoded is None or not np.allclose(decoded,expected,atol=1e-6):
            raise PlayerMorphError(
                f"{geometry_name}: internal multi-morph export verification failed."
            )

    output_path.parent.mkdir(parents=True,exist_ok=True)
    output_path.write_bytes(rebuilt)
    return {
        "size":len(rebuilt),
        "changed":tuple(changed),
        "skipped":tuple(skipped),
        "sparse_stats":tuple(sparse_stats),
    }
