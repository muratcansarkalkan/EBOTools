"""Synthetic/reference-profiled NBA Live 2005/06 backboard EBO compiler.

Specialized profile:
- BaseBackboard + led Geometry
- rigid skin palette/index stream
- position + normal + UV PC buffers
- gNbaBackboardSkin / 2005 DirectTextureSkin runtime
- six dynamic shot-clock batches with uvIndex variables

The binary layout was round-tripped against:
- NBA Live 2005 mempbbd.ebo
- NBA Live 2006 newybbd.ebo
- NBA Live 2006 minnbbd_06.ebo
and reproduces the same total serialized size when rebuilt from their original
material/stream data.
"""

from __future__ import annotations
from dataclasses import dataclass
import struct, math
from pathlib import Path

EBO_MAGIC=0x004F4245; EBO_VERSION=17; HEADER_SIZE=0x60
USD_NAMES=("Geometry","BoundingInfo","Material","i32","ptr","AssetName","Float4","i16","PCVertexBuffer","Float3","Float2","PCIndexBuffer","PCDataBuffers","i8")
GEOM_HANDLER="static EaglCore::ExternalVariable &Geometry::GetGeometryExternalVariable(Geometry *, unsigned int i)"
GEOM_TYPE="EaglRend::Geometry"

@dataclass
class BackboardBatch:
 texture:str; positions:tuple; normals:tuple; uvs:tuple; palette_bones:tuple; palette_indices:tuple; strip:tuple; runtime:str; uv_index:int|None=None
@dataclass
class BackboardGeometry:
 name:str; batches:tuple; flags:int


def _pool(strings):
 p=bytearray(b'\0\0\0\0'); off={}
 for s in strings:
  if s in off: continue
  off[s]=len(p); raw=s.encode()+b'\0'; p+=raw
  if len(raw)&1:p+=b'\0'
 return bytes(p),off

def _bounds(g):
 pts=[p for b in g.batches for p in b.positions]
 mn=tuple(min(p[i] for p in pts) for i in range(3)); mx=tuple(max(p[i] for p in pts) for i in range(3)); c=tuple((mn[i]+mx[i])/2 for i in range(3)); r=math.sqrt(max(sum((p[i]-c[i])**2 for i in range(3)) for p in pts)); return mn,mx,c,r

def _align(x,a=16):return (x+a-1)&~(a-1)

class L: pass

def build_backboard_ebo(geos):
 # strings
 runt=[]; strings=list(USD_NAMES)+[GEOM_HANDLER,GEOM_TYPE]+[g.name for g in geos]
 for g in geos:
  for b in g.batches:
   strings.append(b.texture)
   if b.runtime not in runt:runt.append(b.runtime)
 strings+=runt
 sp,so=_pool(strings); ui={n:i for i,n in enumerate(USD_NAMES)}
 out=bytearray(HEADER_SIZE); cur=HEADER_SIZE; chunk_layouts=[]
 for g in geos:
  gl=L(); gl.g=g; gl.c0=cur
  # chunk0 metadata size computed from TOCs: geom + bounds + material + per-material tocs
  nt=3+sum(7 if b.uv_index is None else 7 for b in g.batches) # actually both 7: i8,ptr(s),i8,ptr6,i8,ptr,asset
  # skin: i8,ptr1,i8,ptr6,i8,ptr1,asset=7; shot ptr2 likewise 7
  gl.nt0=nt; data0=cur+0x14+nt*0x10
  gl.go=data0; gl.bo=gl.go+0x48; gl.ma=gl.go+0x70; pos=gl.ma+len(g.batches)*0x30
  gl.ms=[]
  for b in g.batches:
   ml=L(); ml.b=b; ml.mo=gl.ma+len(gl.ms)*0x30; ml.per=pos; ml.per_size=0x48 if b.uv_index is not None else 0x44; pos+=ml.per_size; gl.ms.append(ml)
  gl.end0=pos; gl.sz0=gl.end0-gl.c0; cur=gl.end0
  # chunk1 single raw i8; build data with align16 components
  gl.c1=cur; gl.raw1=gl.c1+0x24; p=gl.raw1
  # raw starts maybe unaligned; pad inside raw until align16
  for ml in gl.ms:
   p=_align(p,16); ml.color=p; p+=16
   if ml.b.uv_index is not None: ml.uv4=p; p+=16
   ml.palette=p; p+=16*len(ml.b.palette_bones)
   ml.pidx=p; p+=2*len(ml.b.palette_indices)
  gl.end1=p; gl.sz1=gl.end1-gl.c1; cur=gl.end1
  # chunk2 9 tocs per mat
  gl.c2=cur; gl.nt2=9*len(gl.ms); p=gl.c2+0x14+gl.nt2*0x10
  for ml in gl.ms:
   b=ml.b
   ml.vp=p; p+=0x1c; ml.pd=p; ml.pb=b''.join(struct.pack('<3f',*x) for x in b.positions); p+=len(ml.pb)
   ml.vn=p; p+=0x1c; ml.nd=p; ml.nb=b''.join(struct.pack('<3f',*x) for x in b.normals); p+=len(ml.nb)
   ml.vu=p; p+=0x1c; ml.ud=p; ml.ub=b''.join(struct.pack('<2f',*x) for x in b.uvs); p+=len(ml.ub)
   ml.ib=p; p+=0x18; ml.id=p; ml.ibb=struct.pack('<%dH'%len(b.strip),*b.strip); p+=len(ml.ibb); ml.ipad=(-p)&3; p+=ml.ipad
   ml.db=p; p+=0x20
  gl.end2=p; gl.sz2=gl.end2-gl.c2; cur=gl.end2; chunk_layouts.append(gl)
 # tables
 ou=cur; oi=ou+len(USD_NAMES)*4
 import_specs=[('ptr',GEOM_HANDLER,[gl.go+0xc for gl in chunk_layouts])]
 for rn in runt:
  fix=[ml.mo for gl in chunk_layouts for ml in gl.ms if ml.b.runtime==rn]; import_specs.append(('ptr',rn,fix))
 ia=oi+len(import_specs)*0x18; iatn=sum(len(x[2]) for x in import_specs); oe=ia+iatn*4; os=oe+len(geos)*0xc; fs=os+len(sp)
 out.extend(b'\0'*(fs-len(out)))
 # header
 struct.pack_into('<IIIHHIIIIIHHHHH',out,0,EBO_MAGIC,EBO_VERSION,fs,0,0,HEADER_SIZE,ou,oi,oe,os,len(geos)*3,len(USD_NAMES),len(import_specs),len(geos),len(dict.fromkeys(strings)))
 # chunks
 for gl in chunk_layouts:
  g=gl.g
  # c0
  struct.pack_into('<HHIIII',out,gl.c0,0,gl.nt0,0x14,1,1,gl.sz0)
  specs=[(0,'Geometry',1,0,gl.go),(1,'i8',40,0,gl.bo),(0,'Material',len(gl.ms),0 if len(gl.ms)==1 else 0x30,gl.ma)]
  for ml in gl.ms:
   if ml.b.uv_index is None:
    specs += [(1,'i8',4,0,ml.per),(0,'ptr',1,0,ml.per+4),(1,'i8',4,0,ml.per+8),(0,'ptr',6,4,ml.per+0xc),(1,'i8',24,0,ml.per+0x24),(0,'ptr',1,0,ml.per+0x3c),(0,'AssetName',1,0,ml.per+0x40)]
   else:
    specs += [(1,'i8',4,0,ml.per),(0,'ptr',2,4,ml.per+4),(1,'i8',4,0,ml.per+0xc),(0,'ptr',6,4,ml.per+0x10),(1,'i8',24,0,ml.per+0x28),(0,'ptr',1,0,ml.per+0x40),(0,'AssetName',1,0,ml.per+0x44)]
  for ti,(fl,tn,cnt,al,tg) in enumerate(specs):
   to=gl.c0+0x14+ti*0x10; struct.pack_into('<HHIIi',out,to,fl,ui[tn],cnt,al,tg-to)
  # geometry
  struct.pack_into('<I',out,gl.go,so[GEOM_TYPE]); struct.pack_into('<I',out,gl.go+0x10,so[g.name]); struct.pack_into('<I',out,gl.go+0x14,len(gl.ms)); struct.pack_into('<I',out,gl.go+0x18,gl.ma); struct.pack_into('<I',out,gl.go+0x38,g.flags); struct.pack_into('<I',out,gl.go+0x3c,gl.bo); struct.pack_into('<I',out,gl.go+0x40,0xffffffff)
  mn,mx,c,r=_bounds(g); struct.pack_into('<10f',out,gl.bo,*mn,*mx,*c,r)
  # materials and per blocks
  for ml in gl.ms:
   b=ml.b; struct.pack_into('<I',out,ml.mo+0xc,ml.per); out[ml.mo+0x10:ml.mo+0x28]=b'\xab'*24
   # chunk1 data
   struct.pack_into('<4f',out,ml.color,0.5,0.5,0.5,1.0)
   if b.uv_index is not None: struct.pack_into('<4f',out,ml.uv4,float(b.uv_index),0.0,0.0,0.0)
   for i,bone in enumerate(b.palette_bones): struct.pack_into('<I3I',out,ml.palette+i*16,0x3f800000 | (int(bone)&0xff),0,0,0)
   if b.palette_indices: struct.pack_into('<%dH'%len(b.palette_indices),out,ml.pidx,*b.palette_indices)
   n4=n3=n2=0; n1=len(b.palette_bones)
   if b.uv_index is None:
    vals=(5,ml.color,len(b.palette_bones),ml.palette,ml.vp,ml.vn,ml.pidx,ml.vu,ml.ib,len(b.positions),len(b.strip)-2,n4,n3,n2,n1,ml.db,so[b.texture])
    struct.pack_into('<17I',out,ml.per,*vals)
   else:
    vals=(5,ml.color,ml.uv4,len(b.palette_bones),ml.palette,ml.vp,ml.vn,ml.pidx,ml.vu,ml.ib,len(b.positions),len(b.strip)-2,n4,n3,n2,n1,ml.db,so[b.texture])
    struct.pack_into('<18I',out,ml.per,*vals)
  # c1
  struct.pack_into('<HHIIII',out,gl.c1,1,1,0x14,1,1,gl.sz1); to=gl.c1+0x14; struct.pack_into('<HHIIi',out,to,1,ui['i8'],gl.end1-gl.raw1,0,gl.raw1-to); out[gl.raw1:gl.end1]=b'\xdf'*(gl.end1-gl.raw1)
  # rewrite actual component data after fill
  for ml in gl.ms:
   b=ml.b; struct.pack_into('<4f',out,ml.color,0.5,0.5,0.5,1.0)
   if b.uv_index is not None: struct.pack_into('<4f',out,ml.uv4,float(b.uv_index),0,0,0)
   for i,bone in enumerate(b.palette_bones): struct.pack_into('<I3I',out,ml.palette+i*16,0x3f800000|(int(bone)&0xff),0,0,0)
   if b.palette_indices: struct.pack_into('<%dH'%len(b.palette_indices),out,ml.pidx,*b.palette_indices)
  # c2
  struct.pack_into('<HHIIII',out,gl.c2,0,gl.nt2,0x14,3,1,gl.sz2); ti=0
  for ml in gl.ms:
   for tn,cnt,al,tg in [('PCVertexBuffer',1,0,ml.vp),('i8',len(ml.pb),0,ml.pd),('PCVertexBuffer',1,0,ml.vn),('i8',len(ml.nb),0,ml.nd),('PCVertexBuffer',1,0,ml.vu),('i8',len(ml.ub),0,ml.ud),('PCIndexBuffer',1,0,ml.ib),('i8',len(ml.ibb),0,ml.id),('PCDataBuffers',1,0,ml.db)]:
    to=gl.c2+0x14+ti*0x10; struct.pack_into('<HHIIi',out,to,1 if tn=='i8' else 0,ui[tn],cnt,al,tg-to); ti+=1
   for vo,pay,stride,do in [(ml.vp,ml.pb,12,ml.pd),(ml.vn,ml.nb,12,ml.nd),(ml.vu,ml.ub,8,ml.ud)]:
    struct.pack_into('<7I',out,vo,len(pay),stride,do,0,0,0xff if stride==12 else 0xf0,0); out[do:do+len(pay)]=pay
   struct.pack_into('<6I',out,ml.ib,len(ml.ibb),2,ml.id,0,0xf0,0); out[ml.id:ml.id+len(ml.ibb)]=ml.ibb; out[ml.id+len(ml.ibb):ml.id+len(ml.ibb)+ml.ipad]=b'\xdf'*ml.ipad
   struct.pack_into('<8I',out,ml.db,ml.ib,0,len(ml.b.positions),3,0,ml.vp,ml.vn,ml.vu)
 # USD
 for i,n in enumerate(USD_NAMES): struct.pack_into('<I',out,ou+i*4,so[n])
 # imports/IAT
 ic=ia
 for ii,(tn,name,fixs) in enumerate(import_specs):
  imp=oi+ii*0x18; struct.pack_into('<6I',out,imp,0,0,so[tn],so[name],ic-imp,len(fixs))
  for fx in fixs: struct.pack_into('<i',out,ic,fx-imp); ic+=4
 # exports
 for i,gl in enumerate(chunk_layouts):
  ex=oe+i*12; struct.pack_into('<IIi',out,ex,so['Geometry'],so[gl.g.name],gl.go-ex)
 out[os:os+len(sp)]=sp
 return bytes(out)

