#!/usr/bin/env python3
"""Structural NBA Live Morph/Base EBO probe.

This is deliberately read-only. It inventories Geometry batches in a base LOD
and Morph exports/stream headers in a player morph without assuming a year,
LOD, player name, or fixed vertex count.
"""
from __future__ import annotations
import argparse, struct
from pathlib import Path
import ebo_core

def u32(d,o): return struct.unpack_from("<I",d,o)[0]
def u16(d,o): return struct.unpack_from("<H",d,o)[0]
def cstr(d,o):
    e=d.find(b"\0",o)
    return d[o:e].decode("ascii","replace") if e>=0 else ""

def exports(d):
    ot, st = u32(d,28), u32(d,32)
    n=u16(d,42)
    out=[]
    for i in range(n):
        p=ot+i*12
        kind,name,rel=struct.unpack_from("<IIi",d,p)
        typ="Geometry" if kind==4 else cstr(d,st+kind)
        out.append((typ,cstr(d,st+name),p+8+rel))
    return out

def morph_headers(d):
    st=u32(d,32)
    names={"coord","normal","uv","colour","color"}
    hits=[]
    for off in range(u32(d,16),len(d)-40,4):
        no=u32(d,off)
        if no>=4096 or st+no>=len(d): continue
        name=cstr(d,st+no)
        if name not in names: continue
        f=struct.unpack_from("<10I",d,off)
        # Known MorphStreamHeader signature from shipped player/head files.
        if f[1]==0x666666 and f[2]==0 and f[6:10]==(1,0x3f800000,0,0):
            hits.append((off,name,f))
    return hits

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("morph")
    a=ap.parse_args()
    bd=Path(a.base).read_bytes(); md=Path(a.morph).read_bytes()
    court=ebo_core.parse_court(bd)
    print("BASE GEOMETRY")
    for m in court.meshes:
        print(f"  {m.name}:")
        for b in m.batches:
            print(f"    batch {b.batch_index}: {b.vertex_count} verts, "
                  f"{len(b.triangles)} tris, profile={b.profile}, palette={b.palette_count}")
    print("\nMORPH EXPORTS")
    for typ,name,off in exports(md):
        print(f"  {typ:16} {name:28} @ 0x{off:x}")
    print("\nMORPH STREAM HEADERS")
    for off,name,f in morph_headers(md):
        print(f"  0x{off:x} {name:8} words="+" ".join(f"{x:08x}" for x in f))
if __name__=="__main__": main()
