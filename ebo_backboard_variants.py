"""NBA Live 06 auxiliary backboard EBO writers.

Profiles derived from genuine newybbd_06:
- _trans: gNbaBackboardSkinEnvMap_RMRuntime
          position + normal + UV + rigid skin
- _refl : gTextureAttenuateSkin_RMRuntime
          position + UV + Colour + rigid skin
- _shad : gPlanarShadowSkin_RMRuntime
          position + Colour + rigid skin, no AssetName

All variants export one Geometry named BaseBackboard.
"""

from __future__ import annotations
from dataclasses import dataclass
import math, struct

EBO_MAGIC=0x004F4245
EBO_VERSION=17
HEADER_SIZE=0x60
GEOM_HANDLER="static EaglCore::ExternalVariable &Geometry::GetGeometryExternalVariable(Geometry *, unsigned int i)"
GEOM_TYPE="EaglRend::Geometry"

@dataclass
class VariantBatch:
    texture:str|None
    positions:tuple
    normals:tuple|None
    uvs:tuple|None
    colors:tuple|None
    palette_bones:tuple
    palette_indices:tuple
    strip:tuple

def _pool(strings):
    p=bytearray(b'\0\0\0\0'); off={}
    for s in strings:
        if s in off: continue
        off[s]=len(p); raw=s.encode('ascii')+b'\0'; p+=raw
        if len(raw)&1:p+=b'\0'
    return bytes(p),off

def _align(x,a=16): return (x+a-1)&~(a-1)

def _bounds(batches):
    pts=[p for b in batches for p in b.positions]
    mn=tuple(min(p[i] for p in pts) for i in range(3))
    mx=tuple(max(p[i] for p in pts) for i in range(3))
    c=tuple((mn[i]+mx[i])/2 for i in range(3))
    r=math.sqrt(max(sum((p[i]-c[i])**2 for i in range(3)) for p in pts))
    return mn,mx,c,r

class L: pass

def _build(batches, *, flags, profile):
    if not batches:
        raise ValueError("Auxiliary backboard Geometry has no material batches.")

    if profile in ("trans","trans05"):
        runtime=(
            "gNbaBackboardSkinEnvMap_RMRuntime"
            if profile=="trans"
            else "gNbaDirectTextureSkinRimLightPerPixel_RMRuntime"
        )
        usd=("Geometry","BoundingInfo","Material","i32","ptr","AssetName","Float4","i16",
             "PCVertexBuffer","Float3","Float2","PCIndexBuffer","PCDataBuffers","i8")
        has_texture=True; streams=("pos","normal","uv"); per_size=0x44
    elif profile=="refl":
        runtime="gTextureAttenuateSkin_RMRuntime"
        usd=("Geometry","BoundingInfo","Material","i32","ptr","AssetName","Float4","i16",
             "PCVertexBuffer","Float3","Float2","Colour","PCIndexBuffer","PCDataBuffers","i8")
        has_texture=True; streams=("pos","uv","color"); per_size=0x40
    elif profile=="shad":
        runtime="gPlanarShadowSkin_RMRuntime"
        usd=("Geometry","BoundingInfo","Material","i32","ptr","Float4","i16",
             "PCVertexBuffer","Float3","Colour","PCIndexBuffer","PCDataBuffers","i8")
        has_texture=False; streams=("pos","color"); per_size=0x38
    else:
        raise ValueError(profile)

    strings=list(usd)+[GEOM_HANDLER,runtime,"BaseBackboard","i8",GEOM_TYPE]
    if has_texture:
        strings += [b.texture for b in batches if b.texture]
    pool,so=_pool(strings); ui={n:i for i,n in enumerate(usd)}

    # chunk 0 metadata
    per_tocs = 7 if profile in ("trans","trans05") else (5 if profile=="refl" else 4)
    nt0=3+per_tocs*len(batches)
    c0=HEADER_SIZE
    go=c0+0x14+nt0*0x10
    bo=go+0x48
    ma=go+0x70
    pos=ma+len(batches)*0x30
    lays=[]
    for b in batches:
        ml=L(); ml.b=b; ml.mo=ma+len(lays)*0x30; ml.per=pos; pos+=per_size; lays.append(ml)
    end0=pos; sz0=end0-c0

    # chunk 1 raw palette/index data
    c1=end0; raw1=c1+0x24; p=raw1
    for ml in lays:
        b=ml.b
        if profile in ("trans","trans05"):
            p=_align(p,16); ml.matcolor=p; p+=16
        p=_align(p,16); ml.palette=p; p+=16*len(b.palette_bones)
        ml.pidx=p; p+=2*len(b.palette_indices)
    end1=p; sz1=end1-c1

    # chunk 2 PC buffers
    c2=end1
    nt2=(9 if profile in ("trans","trans05","refl") else 7)*len(lays)
    p=c2+0x14+nt2*0x10
    for ml in lays:
        b=ml.b
        ml.vp=p; p+=0x1c
        ml.pb=b''.join(struct.pack('<3f',*v) for v in b.positions)
        ml.pd=p; p+=len(ml.pb)

        if profile in ("trans","trans05"):
            ml.v2=p; p+=0x1c
            ml.b2=b''.join(struct.pack('<3f',*v) for v in b.normals)
            ml.d2=p; p+=len(ml.b2)
            ml.v3=p; p+=0x1c
            ml.b3=b''.join(struct.pack('<2f',*v) for v in b.uvs)
            ml.d3=p; p+=len(ml.b3)
        elif profile=="refl":
            ml.v2=p; p+=0x1c
            ml.b2=b''.join(struct.pack('<2f',*v) for v in b.uvs)
            ml.d2=p; p+=len(ml.b2)
            ml.v3=p; p+=0x1c
            ml.b3=b''.join(struct.pack('<4B',*v) for v in b.colors)
            ml.d3=p; p+=len(ml.b3)
        else:
            ml.v2=p; p+=0x1c
            ml.b2=b''.join(struct.pack('<4B',*v) for v in b.colors)
            ml.d2=p; p+=len(ml.b2)

        ml.ib=p; p+=0x18
        ml.ibb=struct.pack('<%dH'%len(b.strip),*b.strip)
        ml.id=p; p+=len(ml.ibb); ml.ipad=(-p)&3; p+=ml.ipad
        ml.db=p; p+=0x20
    end2=p; sz2=end2-c2

    # tables
    ou=end2
    oi=ou+len(usd)*4
    imports=[
        ('ptr',GEOM_HANDLER,[go+0x0c]),
        ('ptr',runtime,[ml.mo for ml in lays]),
    ]
    ia=oi+len(imports)*0x18
    iatn=sum(len(x[2]) for x in imports)
    oe=ia+iatn*4
    os=oe+0x0c
    fs=os+len(pool)
    out=bytearray(fs)

    struct.pack_into('<IIIHHIIIIIHHHHH',out,0,
        EBO_MAGIC,EBO_VERSION,fs,0,0,
        HEADER_SIZE,ou,oi,oe,os,
        3,len(usd),len(imports),1,len(dict.fromkeys(strings))
    )

    # c0
    struct.pack_into('<HHIIII',out,c0,0,nt0,0x14,1,1,sz0)
    specs=[(0,'Geometry',1,0,go),(1,'i8',40,0,bo),(0,'Material',len(lays),0 if len(lays)==1 else 0x30,ma)]
    for ml in lays:
        if profile in ("trans","trans05"):
            specs += [
                (1,'i8',4,0,ml.per),
                (0,'ptr',1,0,ml.per+4),
                (1,'i8',4,0,ml.per+8),
                (0,'ptr',6,4,ml.per+0x0c),
                (1,'i8',24,0,ml.per+0x24),
                (0,'ptr',1,0,ml.per+0x3c),
                (0,'AssetName',1,0,ml.per+0x40),
            ]
        elif profile=="refl":
            specs += [
                (1,'i8',8,0,ml.per),
                (0,'ptr',6,4,ml.per+8),
                (1,'i8',24,0,ml.per+0x20),
                (0,'ptr',1,0,ml.per+0x38),
                (0,'AssetName',1,0,ml.per+0x3c),
            ]
        else:
            specs += [
                (1,'i8',8,0,ml.per),
                (0,'ptr',5,4,ml.per+8),
                (1,'i8',24,0,ml.per+0x1c),
                (0,'ptr',1,0,ml.per+0x34),
            ]
    for ti,(fl,tn,cnt,al,tg) in enumerate(specs):
        to=c0+0x14+ti*0x10
        struct.pack_into('<HHIIi',out,to,fl,ui[tn],cnt,al,tg-to)

    struct.pack_into('<I',out,go,so[GEOM_TYPE])
    struct.pack_into('<I',out,go+0x10,so["BaseBackboard"])
    struct.pack_into('<I',out,go+0x14,len(lays))
    struct.pack_into('<I',out,go+0x18,ma)
    struct.pack_into('<I',out,go+0x38,flags)
    struct.pack_into('<I',out,go+0x3c,bo)
    struct.pack_into('<I',out,go+0x40,0xffffffff)
    mn,mx,c,r=_bounds(batches)
    struct.pack_into('<10f',out,bo,*mn,*mx,*c,r)

    for ml in lays:
        b=ml.b
        struct.pack_into('<I',out,ml.mo+0x0c,ml.per)
        out[ml.mo+0x10:ml.mo+0x28]=b'\xab'*24

        n4=n3=n2=0; n1=len(b.palette_bones)
        if profile in ("trans","trans05"):
            vals=(5,ml.matcolor,len(b.palette_bones),ml.palette,
                  ml.vp,ml.v2,ml.pidx,ml.v3,ml.ib,
                  len(b.positions),len(b.strip)-2,
                  n4,n3,n2,n1,ml.db,so[b.texture])
            struct.pack_into('<17I',out,ml.per,*vals)
        elif profile=="refl":
            vals=(5,len(b.palette_bones),ml.palette,
                  ml.vp,ml.pidx,ml.v2,ml.v3,ml.ib,
                  len(b.positions),len(b.strip)-2,
                  n4,n3,n2,n1,ml.db,so[b.texture])
            struct.pack_into('<16I',out,ml.per,*vals)
        else:
            vals=(5,len(b.palette_bones),ml.palette,
                  ml.vp,ml.pidx,ml.v2,ml.ib,
                  len(b.positions),len(b.strip)-2,
                  n4,n3,n2,n1,ml.db)
            struct.pack_into('<14I',out,ml.per,*vals)

    # c1
    struct.pack_into('<HHIIII',out,c1,1,1,0x14,1,1,sz1)
    to=c1+0x14
    struct.pack_into('<HHIIi',out,to,1,ui['i8'],end1-raw1,0,raw1-to)
    out[raw1:end1]=b'\xdf'*(end1-raw1)
    for ml in lays:
        b=ml.b
        if profile in ("trans","trans05"):
            struct.pack_into('<4f',out,ml.matcolor,0.5,0.5,0.5,1.0)
        for i,bone in enumerate(b.palette_bones):
            struct.pack_into('<I3I',out,ml.palette+i*16,0x3f800000|(int(bone)&0xff),0,0,0)
        if b.palette_indices:
            struct.pack_into('<%dH'%len(b.palette_indices),out,ml.pidx,*b.palette_indices)

    # c2
    struct.pack_into('<HHIIII',out,c2,0,nt2,0x14,3,1,sz2)
    ti=0
    for ml in lays:
        if profile in ("trans","trans05"):
            seq=[
                ('PCVertexBuffer',1,0,ml.vp),('i8',len(ml.pb),0,ml.pd),
                ('PCVertexBuffer',1,0,ml.v2),('i8',len(ml.b2),0,ml.d2),
                ('PCVertexBuffer',1,0,ml.v3),('i8',len(ml.b3),0,ml.d3),
                ('PCIndexBuffer',1,0,ml.ib),('i8',len(ml.ibb),0,ml.id),
                ('PCDataBuffers',1,0,ml.db),
            ]
            buffers=[(ml.vp,ml.pb,12,ml.pd,0xff),(ml.v2,ml.b2,12,ml.d2,0xff),(ml.v3,ml.b3,8,ml.d3,0xf0)]
            vbptrs=(ml.vp,ml.v2,ml.v3)
        elif profile=="refl":
            seq=[
                ('PCVertexBuffer',1,0,ml.vp),('i8',len(ml.pb),0,ml.pd),
                ('PCVertexBuffer',1,0,ml.v2),('i8',len(ml.b2),0,ml.d2),
                ('PCVertexBuffer',1,0,ml.v3),('i8',len(ml.b3),0,ml.d3),
                ('PCIndexBuffer',1,0,ml.ib),('i8',len(ml.ibb),0,ml.id),
                ('PCDataBuffers',1,0,ml.db),
            ]
            buffers=[(ml.vp,ml.pb,12,ml.pd,0xff),(ml.v2,ml.b2,8,ml.d2,0xf0),(ml.v3,ml.b3,4,ml.d3,0xf0)]
            vbptrs=(ml.vp,ml.v2,ml.v3)
        else:
            seq=[
                ('PCVertexBuffer',1,0,ml.vp),('i8',len(ml.pb),0,ml.pd),
                ('PCVertexBuffer',1,0,ml.v2),('i8',len(ml.b2),0,ml.d2),
                ('PCIndexBuffer',1,0,ml.ib),('i8',len(ml.ibb),0,ml.id),
                ('PCDataBuffers',1,0,ml.db),
            ]
            buffers=[(ml.vp,ml.pb,12,ml.pd,0xff),(ml.v2,ml.b2,4,ml.d2,0xf0)]
            vbptrs=(ml.vp,ml.v2)

        for tn,cnt,al,tg in seq:
            toc=c2+0x14+ti*0x10
            struct.pack_into('<HHIIi',out,toc,1 if tn=='i8' else 0,ui[tn],cnt,al,tg-toc)
            ti+=1

        for vo,pay,stride,do,fmt in buffers:
            struct.pack_into('<7I',out,vo,len(pay),stride,do,0,0,fmt,0)
            out[do:do+len(pay)]=pay
        struct.pack_into('<6I',out,ml.ib,len(ml.ibb),2,ml.id,0,0xf0,0)
        out[ml.id:ml.id+len(ml.ibb)]=ml.ibb
        out[ml.id+len(ml.ibb):ml.id+len(ml.ibb)+ml.ipad]=b'\xdf'*ml.ipad

        # PCDataBuffers supports two or three VBs.
        struct.pack_into('<5I',out,ml.db,ml.ib,0,len(ml.b.positions),len(vbptrs),0)
        for i,vp in enumerate(vbptrs):
            struct.pack_into('<I',out,ml.db+0x14+i*4,vp)

    # USD
    for i,n in enumerate(usd):
        struct.pack_into('<I',out,ou+i*4,so[n])

    # imports
    ic=ia
    for ii,(tn,name,fixs) in enumerate(imports):
        imp=oi+ii*0x18
        struct.pack_into('<6I',out,imp,0,0,so[tn],so[name],ic-imp,len(fixs))
        for fx in fixs:
            struct.pack_into('<i',out,ic,fx-imp); ic+=4

    # export
    struct.pack_into('<IIi',out,oe,so['Geometry'],so['BaseBackboard'],go-oe)
    out[os:os+len(pool)]=pool
    return bytes(out)

def build_trans_ebo(batches, flags): return _build(batches,flags=flags,profile="trans")
def build_trans_2005_ebo(batches, flags): return _build(batches,flags=flags,profile="trans05")
def build_refl_ebo(batches, flags): return _build(batches,flags=flags,profile="refl")
def build_shad_ebo(batches, flags): return _build(batches,flags=flags,profile="shad")
