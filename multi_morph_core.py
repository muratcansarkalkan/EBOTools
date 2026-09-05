"""Named multi-target morph assembler for base_lodX + partial morph EBO."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import hashlib, struct
from . import ebo_core

class MultiMorphError(Exception): pass

@dataclass(frozen=True)
class TargetResult:
    name: str
    status: str
    render_vertices: int
    logical_vertices: int
    stored_floats: int = 0

@dataclass(frozen=True)
class AssembledPart:
    name: str
    vertices: tuple[tuple[float,float,float],...]
    uvs: tuple[tuple[float,float],...]
    faces: tuple[tuple[int,int,int],...]
    modified: bool
    logical_count: int
    mapping: tuple[int,...] = ()
    base_vertices: tuple[tuple[float,float,float],...] = ()

@dataclass(frozen=True)
class Assembly:
    parts: tuple[AssembledPart,...]
    results: tuple[TargetResult,...]
    source_sha256: str

def u16(d,o):return struct.unpack_from("<H",d,o)[0]
def u32(d,o):return struct.unpack_from("<I",d,o)[0]
def cstr(d,o):
    e=d.find(b"\0",o)
    return d[o:e].decode("ascii","replace") if e>=0 else ""

def exports(d):
    oe,st,n=u32(d,28),u32(d,32),u16(d,42)
    out=[]
    for i in range(n):
        p=oe+i*12;t,no,rel=struct.unpack_from("<IIi",d,p)
        out.append((cstr(d,st+t),cstr(d,st+no),p+8+rel))
    return out

def target_name(n): return n[:-7] if n.endswith("_morphs") else n

def coord_header_for_export(d, export_offset, next_offset):
    st=u32(d,32)
    end=min(next_offset,st,len(d)-40)
    for off in range(export_offset,end,4):
        no=u32(d,off)
        if no>=4096 or st+no>=len(d):continue
        if cstr(d,st+no)!="coord":continue
        f=struct.unpack_from("<10I",d,off)
        if f[1]==0x666666 and f[2]==0 and f[6:10]==(1,0x3f800000,0,0):
            return off,f
    return None

def decode_coord(d,f):
    size,ptr,aux=f[3:6]
    if size%4 or ptr+size>len(d):raise MultiMorphError("Invalid coord MorphData.")
    payload=struct.unpack_from(f"<{size//4}f",d,ptr)
    if not aux:return tuple(payload),len(payload)
    if aux<4 or aux>=len(d):raise MultiMorphError("Invalid sparse coord instructions.")
    n=u32(d,aux-4); vals=[];pi=0
    for ins in d[aux:aux+n]:
        if ins&0x80:
            c=(ins&0x7f)+1
            if pi+c>len(payload):raise MultiMorphError("Sparse coord run exceeds payload.")
            vals.extend(payload[pi:pi+c]);pi+=c
        else:
            vals.extend([0.0]*ins)
            if pi>=len(payload):raise MultiMorphError("Sparse coord instruction exceeds payload.")
            vals.append(payload[pi]);pi+=1
    if pi!=len(payload):raise MultiMorphError(f"Sparse coord consumed {pi}/{len(payload)} floats.")
    return tuple(vals),len(payload)

def base_part(data,mesh):
    pos=[];uv=[];faces=[];base=0;batch_counts=[]
    for b in mesh.batches:
        batch_counts.append(b.vertex_count)
        r=struct.unpack_from(f"<{b.vertex_count*3}f",data,b.positions.data_offset)
        bp=[tuple(r[i:i+3]) for i in range(0,len(r),3)]
        if b.uvs:
            r=struct.unpack_from(f"<{b.vertex_count*2}f",data,b.uvs.data_offset)
            bu=[tuple(r[i:i+2]) for i in range(0,len(r),2)]
        else:bu=[(0.0,0.0)]*b.vertex_count
        pos.extend(bp);uv.extend(bu)
        faces.extend(tuple(base+i for i in tri) for tri in b.triangles);base+=b.vertex_count
    logical={};mapping=[]
    for p in pos:
        if p not in logical:logical[p]=len(logical)
        mapping.append(logical[p])
    return pos,uv,faces,mapping,len(logical),tuple(batch_counts)

def ea_mapping_records(data, logical_count):
    """Find EA render->logical mapping records for one logical morph space.

    Record layout seen in shipped base LODs:
      +00 logical vertex count
      +04 1
      +08 render vertices covered by this table
      +10 uint16 mapping pointer
    A Geometry target may use one record for the whole mesh (heads) or one
    record per render batch (BasePlyr).
    """
    found=[]
    for off in range(0,len(data)-24,4):
        if u32(data,off)!=logical_count or u32(data,off+4)!=1:
            continue
        render_count=u32(data,off+8)
        if not (1 <= render_count <= 10000):
            continue
        ptr=u32(data,off+16)
        if ptr+render_count*2>len(data):
            continue
        vals=struct.unpack_from(f"<{render_count}H",data,ptr)
        if vals and max(vals)<logical_count:
            found.append((off,render_count,ptr,tuple(vals)))
    return found

def resolve_mapping(data, positions, batch_counts, desired_logical):
    """Resolve EA's authoritative mapping, including per-batch BasePlyr maps."""
    records=ea_mapping_records(data,desired_logical)

    # Whole-mesh mapping (e.g. headAShape/headBShape).
    whole=[r for r in records if r[1]==len(positions)
           and len(set(r[3]))==desired_logical]
    if len(whole)==1:
        return whole[0][3],"EA_TABLE"
    if len(whole)>1:
        maps={r[3] for r in whole}
        if len(maps)==1:
            return whole[0][3],"EA_TABLE_EQUIVALENT"

    # Per-batch mapping (e.g. BasePlyr). Find a consecutive record sequence
    # whose covered render counts exactly match the Geometry batch sequence.
    ordered=sorted(records,key=lambda r:r[0])
    sequences=[]
    n=len(batch_counts)
    for i in range(0,len(ordered)-n+1):
        seq=ordered[i:i+n]
        if tuple(r[1] for r in seq)!=tuple(batch_counts):
            continue
        merged=tuple(v for r in seq for v in r[3])
        if len(merged)!=len(positions):
            continue
        if len(set(merged))==desired_logical and min(merged)==0 and max(merged)==desired_logical-1:
            sequences.append((seq,merged))
    if len(sequences)==1:
        return sequences[0][1],"EA_BATCH_TABLES"
    if len(sequences)>1:
        maps={x[1] for x in sequences}
        if len(maps)==1:
            return sequences[0][1],"EA_BATCH_TABLES_EQUIVALENT"

    # Only use positional collapse when it exactly reproduces the requested
    # logical cardinality. It remains a fallback, never authoritative.
    logical={}; mapping=[]
    for p in positions:
        if p not in logical: logical[p]=len(logical)
        mapping.append(logical[p])
    if len(logical)==desired_logical:
        return tuple(mapping),"POSITION_FALLBACK"
    raise MultiMorphError(
        f"No EA mapping found for batches {batch_counts} -> {desired_logical}; "
        f"position fallback gives {len(logical)} logical vertices."
    )

def coord_stream_for_target(data, export_offset, next_offset):
    h=coord_header_for_export(data,export_offset,next_offset)
    if not h:return None
    _,f=h; size,ptr,aux=f[3:6]; vals,stored=decode_coord(data,f)
    if not aux: mask=(True,)*len(vals)
    else:
        n=u32(data,aux-4); mask=[]
        for ins in data[aux:aux+n]:
            if ins&0x80: mask.extend([True]*((ins&0x7f)+1))
            else: mask.extend([False]*ins); mask.append(True)
    if len(mask)!=len(vals):raise MultiMorphError("Sparse coord mask mismatch.")
    return size,ptr,tuple(vals),tuple(mask)

def _encode_sparse_mask(mask):
    """Encode an arbitrary stored/omitted component mask using EA's instruction format."""
    out=bytearray(); i=0; n=len(mask)
    while i<n:
        if mask[i]:
            run=1
            while i+run<n and mask[i+run] and run<128: run+=1
            out.append(0x80 | (run-1)); i+=run
        else:
            skip=0
            while i+skip<n and not mask[i+skip] and skip<128: skip+=1
            if i+skip>=n:
                # A sparse stream cannot terminate with omitted components alone.
                return None
            if skip>127:
                return None
            out.append(skip); i+=skip+1  # instruction also stores the following component
    return bytes(out)

def _repack_sparse_fixed(values, old_mask, old_instruction_size, eps=1e-7):
    """Rebuild sparse membership without resizing the EBO.

    EA morphs contain many explicitly stored zero components. Those slots can
    be reassigned to newly non-zero coordinates while preserving the exact
    float payload size. The instruction stream is rewritten in place and may
    shrink, but never grows beyond its original allocation.
    """
    old_count=sum(old_mask)
    required={i for i,v in enumerate(values) if abs(float(v))>eps}
    if len(required)>old_count:
        raise MultiMorphError(
            f"Edit needs {len(required)} stored components but source sparse stream "
            f"has only {old_count} fixed slots.")
    mask=list(old_mask)
    for i in required: mask[i]=True
    need_remove=sum(mask)-old_count
    removable=[i for i,m in enumerate(mask) if m and i not in required and abs(float(values[i]))<=eps]
    if len(removable)<need_remove:
        raise MultiMorphError("Not enough zero-valued sparse slots to repack this edit.")

    # Greedily remove zero slots that produce the shortest valid instruction stream.
    for _ in range(need_remove):
        best=None
        for i in removable:
            if not mask[i]: continue
            mask[i]=False
            enc=_encode_sparse_mask(mask)
            mask[i]=True
            if enc is not None:
                score=(len(enc),i)
                if best is None or score<best[0]: best=(score,i,enc)
        if best is None:
            raise MultiMorphError("Sparse mask cannot be repacked in the existing instruction layout.")
        mask[best[1]]=False
    enc=_encode_sparse_mask(mask)
    if enc is None or len(enc)>old_instruction_size:
        raise MultiMorphError(
            f"Repacked sparse instructions need {len(enc) if enc else 'more'} bytes; "
            f"source allocation is {old_instruction_size}.")
    return tuple(mask),enc

def export_fixed_morph(base_path,source_path,edited_parts,expected_sha256=""):
    bd=Path(base_path).read_bytes(); md=Path(source_path).read_bytes()
    if expected_sha256 and hashlib.sha256(md).hexdigest()!=expected_sha256:
        raise MultiMorphError("Original morph EBO changed after import.")
    meshes={m.name:m for m in ebo_core.parse_court(bd).meshes}
    mex=[x for x in exports(md) if x[0]=="Morph"]; targets={}
    for i,(_,name,off) in enumerate(mex):
        targets[target_name(name)]=(off,mex[i+1][2] if i+1<len(mex) else u32(md,28))
    out=bytearray(md); changed=[]
    for name,edit in edited_parts.items():
        if name not in targets or name not in meshes:continue
        pos,_,_,_,_,batch_counts=base_part(bd,meshes[name])
        stream=coord_stream_for_target(md,*targets[name])
        if not stream:continue
        size,ptr,values,mask=stream
        if len(values)%3:raise MultiMorphError(f"{name}: invalid coordinate stream.")
        logical=len(values)//3
        mapping,_=resolve_mapping(bd,pos,batch_counts,logical)
        edited=edit["vertices"]; original=edit["original"]
        if len(edited)!=len(pos) or len(original)!=len(pos):
            raise MultiMorphError(f"{name}: topology changed; vertex count must remain fixed.")
        groups=[[] for _ in range(logical)]
        for ri,li in enumerate(mapping):groups[li].append(ri)
        vals=list(values); target_changed=False
        for li,ids in enumerate(groups):
            if not any(tuple(edited[i])!=tuple(original[i]) for i in ids):continue
            target_changed=True
            for axis in range(3):
                ci=li*3+axis
                value=sum(float(edited[i][axis])-float(pos[i][axis]) for i in ids)/len(ids)
                vals[ci]=value
        if target_changed:
            # Dense streams need no mask rewrite. Sparse streams are repacked
            # into the source file's existing float/instruction allocations.
            h=coord_header_for_export(md,*targets[name])
            aux=h[1][5] if h else 0
            write_mask=mask
            if aux:
                old_n=u32(md,aux-4)
                write_mask,instructions=_repack_sparse_fixed(vals,mask,old_n)
                struct.pack_into("<I",out,aux-4,len(instructions))
                out[aux:aux+old_n]=instructions + b"\0"*(old_n-len(instructions))
            payload=struct.pack(f"<{sum(write_mask)}f",*[v for v,m in zip(vals,write_mask) if m])
            if len(payload)!=size:raise MultiMorphError(f"{name}: sparse repack changed MorphData size.")
            out[ptr:ptr+size]=payload; changed.append(name)
    return bytes(out),tuple(changed)

def assemble(base_path,morph_path):
    bd=Path(base_path).read_bytes();md=Path(morph_path).read_bytes()
    court=ebo_core.parse_court(bd)
    mex=[x for x in exports(md) if x[0]=="Morph"]
    byname={}
    for i,(typ,name,off) in enumerate(mex):
        nxt=mex[i+1][2] if i+1<len(mex) else u32(md,28)
        byname[target_name(name)]=(name,off,nxt)
    parts=[];results=[]
    for mesh in court.meshes:
        pos,uv,faces,_approx_mapping,approx_logical,batch_counts=base_part(bd,mesh)
        logical=approx_logical
        modified=False;stored=0
        if mesh.name in byname:
            _,off,nxt=byname[mesh.name]
            h=coord_header_for_export(md,off,nxt)
            if h:
                vals,stored=decode_coord(md,h[1])
                if len(vals)%3:
                    results.append(TargetResult(mesh.name,f"INVALID COORD COUNT ({len(vals)})",len(pos),logical,stored))
                else:
                    desired=len(vals)//3
                    try:
                        mapping,map_source=resolve_mapping(bd,pos,batch_counts,desired)
                        logical=desired
                        out=[]
                        for ri,li in enumerate(mapping):
                            j=li*3
                            out.append(tuple(pos[ri][a]+vals[j+a] for a in range(3)))
                        base_positions=tuple(pos); applied_mapping=tuple(mapping)
                        pos=out;modified=True
                        results.append(TargetResult(mesh.name,f"APPLIED [{map_source}]",len(pos),logical,stored))
                    except MultiMorphError as exc:
                        results.append(TargetResult(mesh.name,f"MAPPING ERROR: {exc}",len(pos),logical,stored))
            else:
                results.append(TargetResult(mesh.name,"MORPH PRESENT / NO COORD",len(pos),logical,0))
        parts.append(AssembledPart(mesh.name,tuple(pos),tuple(uv),tuple(faces),modified,logical,
            applied_mapping if modified else (), base_positions if modified else tuple(pos)))
    base_names={m.name for m in court.meshes}
    for target in byname:
        if target not in base_names:results.append(TargetResult(target,"NOT IN BASE",0,0,0))
    return Assembly(tuple(parts),tuple(results),hashlib.sha256(md).hexdigest())
