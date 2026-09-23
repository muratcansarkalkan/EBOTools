#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
import math, struct
from pathlib import Path
from typing import Sequence

try:
    from . import rms_profiles
except ImportError:
    import rms_profiles

class SyntheticEboError(ValueError): pass

EBO_MAGIC=0x004F4245
EBO_VERSION=17
HEADER_SIZE=0x60

USD_NAMES=(
    "Geometry","BoundingInfo","Material","i32","ptr","AssetName",
    "PCVertexBuffer","Float3","Float2","Colour","PCIndexBuffer",
    "i16","PCDataBuffers","i8"
)

GEOMETRY_EXTERNAL_VARIABLE=(
    "static EaglCore::ExternalVariable &Geometry::GetGeometryExternalVariable"
    "(Geometry *, unsigned int i)"
)
GEOMETRY_TYPE_NAME="EaglRend::Geometry"
STADIUM_GEOMETRY_FLAGS=0x30021C09

# Backward-compatible public mapping. New code should use rms_profiles.
SUPPORTED_RMS={name:rms_profiles.BY_NAME[name].runtime for name in rms_profiles.BY_NAME}
DEFAULT_RMS="TextureStadium"

@dataclass(frozen=True)
class SyntheticMaterialBatch:
    texture_name:str
    positions:tuple
    uvs:tuple
    colors:tuple
    triangles:tuple
    rms_name:str=DEFAULT_RMS

@dataclass(frozen=True)
class SyntheticGeometry:
    name:str
    materials:tuple[SyntheticMaterialBatch,...]
    geometry_flags:int=STADIUM_GEOMETRY_FLAGS
    aux_chunk_flags:int=0
    raw_toc_flags:int=0

def supported_rms_names()->tuple[str,...]:
    return rms_profiles.names()

def _s(v,label):
    v=str(v).strip()
    if not v: raise SyntheticEboError(f"{label} cannot be empty")
    if "\0" in v: raise SyntheticEboError(f"{label} contains NUL")
    try: v.encode('ascii')
    except UnicodeEncodeError as exc: raise SyntheticEboError(f"{label} must currently be ASCII") from exc
    return v

def _pool(strings):
    p=bytearray(b'\0\0\0\0'); off={}
    for s in strings:
        if s in off: continue
        off[s]=len(p); raw=s.encode('ascii')+b'\0'; p+=raw
        if len(raw)&1: p+=b'\0'
    return bytes(p),off

def _strip(tris):
    if not tris: raise SyntheticEboError('material has no triangles')
    out=list(tris[0])
    for a,b,c in tris[1:]:
        x,y=(b,a) if ((len(out)+2)&1) else (a,b)
        out.extend((out[-1],x,x,y,c))
    return tuple(out)

def _runtime_name(rms_name:str)->str:
    try:
        return rms_profiles.runtime_name(rms_name)
    except KeyError as exc:
        raise SyntheticEboError(
            f"Unknown RMS {rms_name!r}. Known: {', '.join(supported_rms_names())}"
        ) from exc

def _check_batch(b):
    t=_s(b.texture_name,'Texture name')
    rms=_s(getattr(b,'rms_name',DEFAULT_RMS),'RMS name')
    try:
        rms=rms_profiles.canonical_name(rms)
    except KeyError as exc:
        raise SyntheticEboError(
            f"Unknown RMS {rms!r}. Known: {', '.join(supported_rms_names())}"
        ) from exc
    _runtime_name(rms)
    n=len(b.positions)
    if not n or n>65535:
        raise SyntheticEboError(f'{t}: invalid vertex count {n}')
    if len(b.uvs)!=n or len(b.colors)!=n:
        raise SyntheticEboError(f'{t}: stream counts differ')
    tris=[]
    for q in b.triangles:
        q=tuple(map(int,q))
        if len(q)!=3 or min(q)<0 or max(q)>=n:
            raise SyntheticEboError(f'{t}: invalid triangle {q}')
        if len(set(q))==3:
            tris.append(q)
    if not tris:
        raise SyntheticEboError(f'{t}: no usable triangles')
    cols=[tuple(max(0,min(255,int(x))) for x in c) for c in b.colors]
    return SyntheticMaterialBatch(
        t,
        tuple(tuple(map(float,p)) for p in b.positions),
        tuple(tuple(map(float,u)) for u in b.uvs),
        tuple(cols),
        tuple(tris),
        rms
    )

def _check_geo(g):
    name=_s(g.name,'Geometry name')
    if not g.materials:
        raise SyntheticEboError(f'{name}: no materials')
    mats=tuple(_check_batch(x) for x in g.materials)
    identities={(m.texture_name,m.rms_name) for m in mats}
    if len(identities)!=len(mats):
        raise SyntheticEboError(f'{name}: duplicate texture/RMS material identities')
    return SyntheticGeometry(
        name,
        mats,
        int(getattr(g,'geometry_flags',STADIUM_GEOMETRY_FLAGS)) & 0xFFFFFFFF,
        int(getattr(g,'aux_chunk_flags',0)) & 0xFFFF,
        int(getattr(g,'raw_toc_flags',0)) & 0xFFFF,
    )

def _bounds(g):
    pts=[p for m in g.materials for p in m.positions]
    mn=tuple(min(p[a] for p in pts) for a in range(3))
    mx=tuple(max(p[a] for p in pts) for a in range(3))
    c=tuple((mn[a]+mx[a])/2 for a in range(3))
    r=math.sqrt(sum(((mx[a]-mn[a])/2)**2 for a in range(3)))
    return mn,mx,c,r

@dataclass
class ML:
    mo:int
    vo:int
    runtime_name:str
    vp:int=0
    pd:int=0
    vu:int=0
    ud:int=0
    vc:int=0
    cd:int=0
    ib:int=0
    id:int=0
    db:int=0
    strip:tuple=()
    pb:bytes=b''
    ub:bytes=b''
    cb:bytes=b''
    ibb:bytes=b''
    pad:bytes=b''

@dataclass
class GL:
    sc:int
    ss:int
    go:int
    bo:int
    mats:list
    ac:int
    pc:int
    ps:int

def build_texture_stadium_ebo(geometries:Sequence[SyntheticGeometry])->bytes:
    gs=tuple(_check_geo(g) for g in geometries)
    if not gs:
        raise SyntheticEboError('At least one Geometry required')
    if len({g.name for g in gs})!=len(gs):
        raise SyntheticEboError('Geometry names must be unique')

    runtime_names=[]
    strings=list(USD_NAMES[:-1])+[GEOMETRY_EXTERNAL_VARIABLE]+[g.name for g in gs]+['i8',GEOMETRY_TYPE_NAME]
    for g in gs:
        for m in g.materials:
            rn=_runtime_name(m.rms_name)
            if rn not in runtime_names:
                runtime_names.append(rn)
            strings.append(m.texture_name)
    strings.extend(runtime_names)

    pool,so=_pool(strings)
    ui={n:i for i,n in enumerate(USD_NAMES)}

    cur=HEADER_SIZE
    lays=[]
    for g in gs:
        mc=len(g.materials)
        tc=3+5*mc
        ds=cur+0x14+tc*0x10
        go=ds
        bo=go+0x48
        ma=go+0x70
        vs=ma+mc*0x30
        se=vs+mc*0x24
        sc=cur
        mats=[ML(ma+i*0x30,vs+i*0x24,_runtime_name(m.rms_name)) for i,m in enumerate(g.materials)]
        cur=se
        ac=cur
        cur+=0x14
        pc=cur
        pcur=pc+0x14+(9*mc)*0x10

        for m,l in zip(g.materials,mats):
            st=_strip(m.triangles)
            pb=b''.join(struct.pack('<3f',*x) for x in m.positions)
            ub=b''.join(struct.pack('<2f',*x) for x in m.uvs)
            cb=b''.join(struct.pack('<4B',b,g_,r,a) for r,g_,b,a in m.colors)
            ibb=struct.pack(f'<{len(st)}H',*st)
            pad=b'\xDF'*((-len(ibb))&3)

            l.vp=pcur; pcur+=0x1C
            l.pd=pcur; pcur+=len(pb)
            l.vu=pcur; pcur+=0x1C
            l.ud=pcur; pcur+=len(ub)
            l.vc=pcur; pcur+=0x1C
            l.cd=pcur; pcur+=len(cb)
            l.ib=pcur; pcur+=0x18
            l.id=pcur; pcur+=len(ibb)+len(pad)
            l.db=pcur; pcur+=0x20
            l.strip=st; l.pb=pb; l.ub=ub; l.cb=cb; l.ibb=ibb; l.pad=pad

        lays.append(GL(sc,se-sc,go,bo,mats,ac,pc,pcur-pc))
        cur=pcur

    uo=cur
    io=uo+len(USD_NAMES)*4

    geometry_fixups=[l.go+0x0C for l in lays]
    runtime_fixups={}
    for l in lays:
        for m in l.mats:
            runtime_fixups.setdefault(m.runtime_name, []).append(m.mo)

    import_specs=[('ptr',GEOMETRY_EXTERNAL_VARIABLE,geometry_fixups)]
    for rn in runtime_names:
        import_specs.append(('ptr',rn,runtime_fixups.get(rn,[])))

    ia=io+len(import_specs)*0x18
    iat_count=sum(len(fixs) for _,_,fixs in import_specs)
    eo=ia+4*iat_count
    sto=eo+len(gs)*0x0C
    fs=sto+len(pool)
    out=bytearray(fs)

    struct.pack_into(
        '<IIIHHIIIIIHHHHH',
        out,0,
        EBO_MAGIC,EBO_VERSION,fs,0,0,
        HEADER_SIZE,uo,io,eo,sto,
        len(gs)*3,len(USD_NAMES),len(import_specs),len(gs),len(dict.fromkeys(strings))
    )

    for g,l in zip(gs,lays):
        mc=len(g.materials)
        struct.pack_into('<HHIIII',out,l.sc,0,3+5*mc,0x14,1,1,l.ss)
        specs=[(0,'Geometry',1,0,l.go),(1,'i8',40,0,l.bo),(0,'Material',mc,0 if mc==1 else 0x30,l.mats[0].mo)]
        for ml in l.mats:
            specs += [
                (1,'i8',4,0,ml.vo),
                (0,'ptr',4,4,ml.vo+4),
                (1,'i8',8,0,ml.vo+20),
                (0,'ptr',1,0,ml.vo+28),
                (0,'AssetName',1,0,ml.vo+32),
            ]
        for ti,(fl,tn,cnt,al,tg) in enumerate(specs):
            to=l.sc+0x14+ti*0x10
            struct.pack_into('<HHIIi',out,to,fl,ui[tn],cnt,al,tg-to)

        struct.pack_into('<I',out,l.go,so[GEOMETRY_TYPE_NAME])
        struct.pack_into('<I',out,l.go+0x10,so[g.name])
        struct.pack_into('<I',out,l.go+0x14,mc)
        struct.pack_into('<I',out,l.go+0x18,l.mats[0].mo)
        struct.pack_into('<I',out,l.go+0x38,g.geometry_flags)
        struct.pack_into('<I',out,l.go+0x3C,l.bo)
        struct.pack_into('<I',out,l.go+0x40,0xFFFFFFFF)

        mn,mx,c,r=_bounds(g)
        struct.pack_into('<10f',out,l.bo,*mn,*mx,*c,r)

        for m,ml in zip(g.materials,l.mats):
            struct.pack_into('<I',out,ml.mo+0x0C,ml.vo)
            out[ml.mo+0x10:ml.mo+0x28]=b'\xAB'*24
            struct.pack_into('<9I',out,ml.vo,5,ml.vp,ml.vu,ml.vc,ml.ib,len(m.positions),len(ml.strip)-2,ml.db,so[m.texture_name])

        struct.pack_into('<HHIIII',out,l.ac,g.aux_chunk_flags,0,0x14,1,1,0x14)
        struct.pack_into('<HHIIII',out,l.pc,0,9*mc,0x14,3,1,l.ps)
        ti=0
        for m,ml in zip(g.materials,l.mats):
            ps=[
                ('PCVertexBuffer',1,0,ml.vp),('i8',len(ml.pb),0,ml.pd),
                ('PCVertexBuffer',1,0,ml.vu),('i8',len(ml.ub),0,ml.ud),
                ('PCVertexBuffer',1,0,ml.vc),('i8',len(ml.cb),0,ml.cd),
                ('PCIndexBuffer',1,0,ml.ib),('i8',len(ml.ibb),0,ml.id),
                ('PCDataBuffers',1,0,ml.db)
            ]
            for tn,cnt,al,tg in ps:
                to=l.pc+0x14+ti*0x10
                toc_flags = g.raw_toc_flags if tn == 'i8' else 0
                struct.pack_into('<HHIIi',out,to,toc_flags,ui[tn],cnt,al,tg-to)
                ti+=1
            for off,pay,stride,do in [(ml.vp,ml.pb,12,ml.pd),(ml.vu,ml.ub,8,ml.ud),(ml.vc,ml.cb,4,ml.cd)]:
                struct.pack_into('<7I',out,off,len(pay),stride,do,0,0,0xF0,0)
            out[ml.pd:ml.pd+len(ml.pb)]=ml.pb
            out[ml.ud:ml.ud+len(ml.ub)]=ml.ub
            out[ml.cd:ml.cd+len(ml.cb)]=ml.cb
            struct.pack_into('<6I',out,ml.ib,len(ml.ibb),2,ml.id,0,0xF0,0)
            out[ml.id:ml.id+len(ml.ibb)]=ml.ibb
            out[ml.id+len(ml.ibb):ml.id+len(ml.ibb)+len(ml.pad)]=ml.pad
            struct.pack_into('<8I',out,ml.db,ml.ib,0,len(m.positions),3,0,ml.vp,ml.vu,ml.vc)

    for i,n in enumerate(USD_NAMES):
        struct.pack_into('<I',out,uo+i*4,so[n])

    ic=ia
    for ii,(tn,name,fixs) in enumerate(import_specs):
        imp=io+ii*0x18
        struct.pack_into('<6I',out,imp,0,0,so[tn],so[name],ic-imp,len(fixs))
        for fx in fixs:
            struct.pack_into('<i',out,ic,fx-imp)
            ic+=4

    for i,(g,l) in enumerate(zip(gs,lays)):
        ex=eo+i*0x0C
        struct.pack_into('<IIi',out,ex,so['Geometry'],so[g.name],l.go-ex)

    out[sto:]=pool
    return bytes(out)

def write_texture_stadium_ebo(path,geometries):
    Path(path).write_bytes(build_texture_stadium_ebo(geometries))
