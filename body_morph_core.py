"""Generic fixed-layout BasePlyr morph support for NBA Live EBOs."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib, math, struct
from . import ebo_core

EPS = 1e-7

class MorphError(Exception):
    pass

@dataclass(frozen=True)
class BaseBody:
    positions: tuple[tuple[float,float,float], ...]
    mapping: tuple[int, ...]
    uvs: tuple[tuple[float,float], ...]
    faces: tuple[tuple[int,int,int], ...]
    logical_count: int

@dataclass(frozen=True)
class MorphStream:
    offset: int
    size: int
    values: tuple[float, ...]
    stored_mask: tuple[bool, ...]
    sparse: bool

@dataclass(frozen=True)
class MorphedBody:
    vertices: tuple[tuple[float,float,float], ...]
    uvs: tuple[tuple[float,float], ...]
    faces: tuple[tuple[int,int,int], ...]
    mapping: tuple[int, ...]
    logical_count: int
    source_sha256: str

def _u32(d,o): return struct.unpack_from("<I",d,o)[0]
def _f32(v): return struct.unpack("<f",struct.pack("<f",float(v)))[0]
def _cstr(d,o):
    e=d.find(b"\0",o)
    if e<0: raise MorphError("Unterminated EBO string.")
    return d[o:e].decode("ascii","replace")

def parse_base(path: str|Path, mesh_name="BasePlyr") -> BaseBody:
    data=Path(path).read_bytes()
    court=ebo_core.parse_court(data)
    try: mesh=next(m for m in court.meshes if m.name==mesh_name)
    except StopIteration: raise MorphError(f"Base EBO has no {mesh_name} Geometry export.")
    positions=[]; uvs=[]; faces=[]; mapping=[]; logical={}
    base_index=0
    for batch in mesh.batches:
        raw=struct.unpack_from(f"<{batch.vertex_count*3}f",data,batch.positions.data_offset)
        batch_pos=[tuple(raw[i:i+3]) for i in range(0,len(raw),3)]
        if batch.uvs:
            uvraw=struct.unpack_from(f"<{batch.vertex_count*2}f",data,batch.uvs.data_offset)
            batch_uv=[tuple(uvraw[i:i+2]) for i in range(0,len(uvraw),2)]
        else: batch_uv=[(0.0,0.0)]*batch.vertex_count
        # EA's body morph space collapses render duplicates by identical base position.
        for p in batch_pos:
            if p not in logical: logical[p]=len(logical)
            mapping.append(logical[p])
        positions.extend(batch_pos); uvs.extend(batch_uv)
        faces.extend(tuple(base_index+i for i in tri) for tri in batch.triangles)
        base_index += batch.vertex_count
    return BaseBody(tuple(positions),tuple(mapping),tuple(uvs),tuple(faces),len(logical))

def _coord_header(data: bytes):
    if data[:4]!=b"EBO\0": raise MorphError("Morph file is not an EBO.")
    chunk,strings=_u32(data,16),_u32(data,32)
    # First coord stream belongs to the first Morph export (BasePlyr_morphs in supplied corpus).
    for off in range(chunk,min(strings,len(data)-40),4):
        no=_u32(data,off)
        if no>=4096 or strings+no>=len(data): continue
        try: name=_cstr(data,strings+no)
        except Exception: continue
        if name!="coord": continue
        f=struct.unpack_from("<10I",data,off)
        if f[1]==0x666666 and f[2]==0 and f[6:10]==(1,0x3f800000,0,0):
            size,pointer,aux=f[3:6]
            if pointer+size<=len(data): return off,size,pointer,aux
    raise MorphError("BasePlyr coordinate MorphStreamHeader was not found.")

def parse_stream(data: bytes, logical_count: int) -> MorphStream:
    _,size,pointer,aux=_coord_header(data)
    if size%4: raise MorphError("Coordinate MorphData is not float32 aligned.")
    payload=struct.unpack_from(f"<{size//4}f",data,pointer)
    expected=logical_count*3
    if not aux:
        if len(payload)!=expected:
            raise MorphError(f"Dense morph has {len(payload)} components; base requires {expected}.")
        return MorphStream(pointer,size,tuple(payload),(True,)*expected,False)
    if aux<4 or aux>=len(data): raise MorphError("Sparse morph instruction pointer is invalid.")
    n=_u32(data,aux-4)
    if aux+n>len(data): raise MorphError("Sparse morph instructions extend beyond the EBO.")
    vals=[]; mask=[]; pi=0
    for ins in data[aux:aux+n]:
        if ins&0x80:
            count=(ins&0x7f)+1
            if pi+count>len(payload): raise MorphError("Sparse run exceeds MorphData.")
            vals.extend(payload[pi:pi+count]); mask.extend([True]*count); pi+=count
        else:
            vals.extend([0.0]*ins); mask.extend([False]*ins)
            if pi>=len(payload): raise MorphError("Sparse instruction exceeds MorphData.")
            vals.append(payload[pi]); mask.append(True); pi+=1
    if len(vals)!=expected or pi!=len(payload):
        raise MorphError(
            f"Invalid sparse player coordinates: decoded {len(vals)} components "
            f"(base requires {expected}) and consumed {pi}/{len(payload)} floats."
        )
    return MorphStream(pointer,size,tuple(vals),tuple(mask),True)

def import_morph(base_path, morph_path) -> MorphedBody:
    base=parse_base(base_path)
    source=Path(morph_path).read_bytes()
    stream=parse_stream(source,base.logical_count)
    verts=[]
    for ri,li in enumerate(base.mapping):
        j=li*3
        verts.append(tuple(_f32(base.positions[ri][a]+stream.values[j+a]) for a in range(3)))
    return MorphedBody(tuple(verts),base.uvs,base.faces,base.mapping,base.logical_count,
                       hashlib.sha256(source).hexdigest())

def export_morph(base_path, source_path, edited_vertices, original_vertices, expected_sha256=""):
    base=parse_base(base_path); source=Path(source_path).read_bytes()
    if expected_sha256 and hashlib.sha256(source).hexdigest()!=expected_sha256:
        raise MorphError("Original morph EBO changed after import.")
    if len(edited_vertices)!=len(base.positions):
        raise MorphError(f"Expected {len(base.positions)} rendered vertices.")
    stream=parse_stream(source,base.logical_count)
    groups=[[] for _ in range(base.logical_count)]
    for ri,li in enumerate(base.mapping): groups[li].append(ri)
    updated=list(stream.values); changed=0
    for li,ids in enumerate(groups):
        if not any(tuple(edited_vertices[i])!=tuple(original_vertices[i]) for i in ids): continue
        changed+=1
        for axis in range(3):
            value=_f32(sum(float(edited_vertices[i][axis]) for i in ids)/len(ids)
                       -sum(base.positions[i][axis] for i in ids)/len(ids))
            ci=li*3+axis
            if not stream.stored_mask[ci] and abs(value)>EPS:
                raise MorphError(
                    f"Logical vertex {li} changes an omitted {'XYZ'[axis]} sparse component. "
                    "This alpha preserves the original sparse layout; edit another axis/vertex "
                    "or use a denser morph. Sparse-layout rebuilding is the next exporter step."
                )
            if stream.stored_mask[ci]: updated[ci]=value
    packed=[v for v,m in zip(updated,stream.stored_mask) if m]
    payload=struct.pack(f"<{len(packed)}f",*packed)
    if len(payload)!=stream.size: raise MorphError("Refusing to resize MorphData.")
    out=bytearray(source); out[stream.offset:stream.offset+stream.size]=payload
    return bytes(out),changed
