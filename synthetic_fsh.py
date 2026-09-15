#!/usr/bin/env python3
"""Native NBA Live ShpF writer for synthetic stadium/court packages.

Native package creation:
- opaque RGBA PNG -> DXT1 / FSH type 0x60
- PNG with non-opaque alpha -> DXT5 / FSH type 0x62

The ShpF layout is based on the native test that loaded successfully in NBA Live.
"""

from __future__ import annotations

from pathlib import Path
import io
import json
import shutil
import tempfile

import struct

try:
    from .texture_names import validate_texture_name, TextureNameError
except ImportError:
    from texture_names import validate_texture_name, TextureNameError

try:
    import bpy
except ImportError:
    bpy = None


class SyntheticFshError(ValueError):
    pass


MAX_SAFE_FSH_BYTES = 16 * 1024 * 1024
TARGET_SAFE_FSH_BYTES = int(15.5 * 1024 * 1024)

# Known native DirectX-compressed FSH types used by EA ShpF.
FSH_DXT1 = 0x60
FSH_DXT5 = 0x62

_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')


def _validate_asset_name(name: str) -> str:
    try:
        return validate_texture_name(name)
    except TextureNameError as exc:
        raise SyntheticFshError(str(exc)) from exc



def _load_png_rgba_stdlib(path: str | Path):
    """Load a conventional 8-bit RGB/RGBA PNG using only the Python stdlib."""
    import zlib

    path = Path(path).resolve()
    data = path.read_bytes()
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise SyntheticFshError(f"Texture image is not a valid PNG: {path.name}")

    pos = len(signature)
    ihdr = None
    idat = bytearray()
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        end = pos + 12 + length
        if end > len(data):
            raise SyntheticFshError(f"PNG contains a truncated chunk: {path.name}")
        kind = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            ihdr = payload
        elif kind == b"IDAT":
            idat += payload
        elif kind == b"IEND":
            break
        pos = end

    if ihdr is None or len(ihdr) != 13:
        raise SyntheticFshError(f"PNG is missing a valid IHDR chunk: {path.name}")
    width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", ihdr
    )
    if width <= 0 or height <= 0:
        raise SyntheticFshError(f"Invalid texture dimensions for {path.name}: {width}x{height}")
    if bit_depth != 8 or compression != 0 or filtering != 0 or interlace != 0:
        raise SyntheticFshError(
            f"Standalone FSH packing supports non-interlaced 8-bit PNGs only: {path.name}"
        )
    if color_type not in (2, 6):
        raise SyntheticFshError(
            f"Standalone FSH packing supports RGB/RGBA PNGs only: {path.name} "
            f"(PNG color type {color_type})."
        )

    channels = 4 if color_type == 6 else 3
    stride = width * channels
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise SyntheticFshError(f"Could not decode PNG pixel data for {path.name}: {exc}") from exc
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise SyntheticFshError(
            f"Unexpected PNG scanline data size for {path.name}: {len(raw)} != {expected}."
        )

    prev = bytearray(stride)
    rows = []
    cursor = 0
    bpp = channels
    for _y in range(height):
        filter_type = raw[cursor]
        filtered = raw[cursor + 1:cursor + 1 + stride]
        cursor += stride + 1
        row = bytearray(stride)
        for i, value in enumerate(filtered):
            left = row[i - bpp] if i >= bpp else 0
            above = prev[i]
            upper_left = prev[i - bpp] if i >= bpp else 0
            if filter_type == 0:
                predictor = 0
            elif filter_type == 1:
                predictor = left
            elif filter_type == 2:
                predictor = above
            elif filter_type == 3:
                predictor = (left + above) // 2
            elif filter_type == 4:
                estimate = left + above - upper_left
                pa = abs(estimate - left)
                pb = abs(estimate - above)
                pc = abs(estimate - upper_left)
                predictor = left if pa <= pb and pa <= pc else above if pb <= pc else upper_left
            else:
                raise SyntheticFshError(
                    f"Unsupported PNG filter {filter_type} in {path.name}."
                )
            row[i] = (value + predictor) & 0xFF
        rows.append(bytes(row))
        prev = row

    rgba = bytearray(width * height * 4)
    # Preserve the same orientation used by the Blender path: flip vertically once.
    for y in range(height):
        src = rows[height - 1 - y]
        for x in range(width):
            s = x * channels
            d = (y * width + x) * 4
            rgba[d:d + 3] = src[s:s + 3]
            rgba[d + 3] = src[s + 3] if channels == 4 else 255
    return {"width": width, "height": height, "rgba": bytes(rgba)}


def _load_rgba_png(path: str | Path):
    """Load PNG through Blender when available, otherwise use the stdlib decoder."""
    path = Path(path).resolve()
    if not path.is_file():
        raise SyntheticFshError(f"Texture image was not found: {path}")
    if path.suffix.lower() != ".png":
        raise SyntheticFshError(f"Native FSH input must be PNG: {path.name}")
    if bpy is None:
        return _load_png_rgba_stdlib(path)

    img = None
    try:
        img = bpy.data.images.load(str(path), check_existing=False)
        w, h = int(img.size[0]), int(img.size[1])
        if w <= 0 or h <= 0:
            raise SyntheticFshError(f"Invalid texture dimensions for {path.name}: {w}x{h}")

        px = list(img.pixels[:])
        if len(px) < w * h * 4:
            raise SyntheticFshError(
                f"Blender returned incomplete RGBA pixel data for {path.name}."
            )

        rgba = bytearray(w * h * 4)
        for y in range(h):
            src_y = h - 1 - y
            for x in range(w):
                src = (src_y * w + x) * 4
                dst = (y * w + x) * 4
                for c in range(4):
                    v = float(px[src + c])
                    if v <= 0.0:
                        rgba[dst + c] = 0
                    elif v >= 1.0:
                        rgba[dst + c] = 255
                    else:
                        rgba[dst + c] = int(v * 255.0 + 0.5)

        return {"width": w, "height": h, "rgba": bytes(rgba)}
    except SyntheticFshError:
        raise
    except Exception as exc:
        raise SyntheticFshError(f"Could not read PNG {path.name}: {exc}") from exc
    finally:
        if img is not None:
            try:
                bpy.data.images.remove(img)
            except Exception:
                pass

def _has_real_alpha(image) -> bool:
    rgba = image["rgba"]
    return any(rgba[i] < 255 for i in range(3, len(rgba), 4))


def _rgb565(r, g, b):
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def _rgb_from_565(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    return (
        (r << 3) | (r >> 2),
        (g << 2) | (g >> 4),
        (b << 3) | (b >> 2),
    )


def _block_pixels(image, bx, by):
    w, h, rgba = image["width"], image["height"], image["rgba"]
    out = []
    for yy in range(4):
        y = min(h - 1, by + yy)
        for xx in range(4):
            x = min(w - 1, bx + xx)
            o = (y * w + x) * 4
            out.append((rgba[o], rgba[o+1], rgba[o+2], rgba[o+3]))
    return out


def _dist3(a, b):
    dr = a[0] - b[0]
    dg = a[1] - b[1]
    db = a[2] - b[2]
    return dr*dr + dg*dg + db*db


def _choose_rgb_endpoints(pixels):
    # Simple, deterministic endpoint selection based on maximum RGB range.
    rgbs = [(p[0], p[1], p[2]) for p in pixels]
    rmin = min(p[0] for p in rgbs); rmax = max(p[0] for p in rgbs)
    gmin = min(p[1] for p in rgbs); gmax = max(p[1] for p in rgbs)
    bmin = min(p[2] for p in rgbs); bmax = max(p[2] for p in rgbs)
    axis = max(((rmax-rmin,0),(gmax-gmin,1),(bmax-bmin,2)))[1]
    lo = min(rgbs, key=lambda p: p[axis])
    hi = max(rgbs, key=lambda p: p[axis])
    c0 = _rgb565(*hi)
    c1 = _rgb565(*lo)
    if c0 == c1:
        # force four-color mode where possible
        if c0 < 0xFFFF:
            c0 += 1
        elif c1 > 0:
            c1 -= 1
    if c0 < c1:
        c0, c1 = c1, c0
    return c0, c1


def _encode_dxt_color_block(pixels):
    c0, c1 = _choose_rgb_endpoints(pixels)
    p0 = _rgb_from_565(c0)
    p1 = _rgb_from_565(c1)
    p2 = tuple((2*p0[i] + p1[i]) // 3 for i in range(3))
    p3 = tuple((p0[i] + 2*p1[i]) // 3 for i in range(3))
    palette = (p0, p1, p2, p3)

    bits = 0
    for i, p in enumerate(pixels):
        rgb = p[:3]
        idx = min(range(4), key=lambda j: _dist3(rgb, palette[j]))
        bits |= idx << (2*i)
    return struct.pack("<HHI", c0, c1, bits)


def _encode_dxt1(image):
    out = bytearray()
    for by in range(0, image["height"], 4):
        for bx in range(0, image["width"], 4):
            out += _encode_dxt_color_block(_block_pixels(image, bx, by))
    return bytes(out)


def _alpha_palette(a0, a1):
    if a0 > a1:
        return [
            a0, a1,
            (6*a0 + 1*a1) // 7,
            (5*a0 + 2*a1) // 7,
            (4*a0 + 3*a1) // 7,
            (3*a0 + 4*a1) // 7,
            (2*a0 + 5*a1) // 7,
            (1*a0 + 6*a1) // 7,
        ]
    return [
        a0, a1,
        (4*a0 + 1*a1) // 5,
        (3*a0 + 2*a1) // 5,
        (2*a0 + 3*a1) // 5,
        (1*a0 + 4*a1) // 5,
        0, 255,
    ]


def _encode_dxt5_alpha_block(pixels):
    vals = [p[3] for p in pixels]
    a0 = max(vals)
    a1 = min(vals)
    if a0 == a1:
        if a0 == 0:
            a1 = 0
            a0 = 1
        else:
            a1 = max(0, a0 - 1)
    palette = _alpha_palette(a0, a1)

    bits = 0
    for i, a in enumerate(vals):
        idx = min(range(8), key=lambda j: abs(a - palette[j]))
        bits |= idx << (3*i)

    packed = bits.to_bytes(6, "little")
    return bytes((a0, a1)) + packed


def _encode_dxt5(image):
    out = bytearray()
    for by in range(0, image["height"], 4):
        for bx in range(0, image["width"], 4):
            pixels = _block_pixels(image, bx, by)
            out += _encode_dxt5_alpha_block(pixels)
            out += _encode_dxt_color_block(pixels)
    return bytes(out)


def _encode_native_texture(path: str | Path):
    image = _load_rgba_png(path)
    if _has_real_alpha(image):
        fmt_name = "DXT5"
        fmt_code = FSH_DXT5
        payload = _encode_dxt5(image)
    else:
        fmt_name = "DXT1"
        fmt_code = FSH_DXT1
        payload = _encode_dxt1(image)

    return {
        "format_name": fmt_name,
        "format_code": fmt_code,
        "payload": payload,
        "width": image["width"],
        "height": image["height"],
    }

def _native_block(encoded) -> bytes:
    payload = encoded["payload"]
    hdr = bytearray(32)
    hdr[0] = encoded["format_code"]
    hdr[1] = 1
    # Matches the successful native test / common ShpF image block form.
    hdr[8:12] = (0x20).to_bytes(4, "little")
    hdr[12:16] = len(payload).to_bytes(4, "little")
    hdr[24:28] = int(encoded["width"]).to_bytes(4, "little")
    hdr[28:32] = int(encoded["height"]).to_bytes(4, "little")
    block = bytes(hdr) + payload
    block += b"\0" * ((-len(block)) & 0xF)
    return block


def _archive_size_for_blocks(blocks: dict[str, bytes]) -> int:
    names = sorted(blocks)
    count = len(names)
    dir_end = 16 + sum(9 + len(_validate_asset_name(name).encode('ascii')) for name in names)
    meta_len = 8
    first = (dir_end + meta_len + 15) & ~15
    return first + sum(len(blocks[name]) for name in sorted(blocks))


def _build_native_shpf_from_blocks(
    blocks: dict[str, bytes],
    output_path: str | Path,
) -> Path:
    if not blocks:
        raise SyntheticFshError("Cannot build an empty FSH archive.")
    names = sorted(blocks)
    for name in names:
        _validate_asset_name(name)

    count = len(names)
    dir_end = 16 + sum(9 + len(name.encode('ascii')) for name in names)
    meta = b"G427\0\0\0\0"
    first = (dir_end + len(meta) + 15) & ~15
    pad_len = first - (dir_end + len(meta))
    pad = (b"Buy " * ((pad_len + 3) // 4))[:pad_len]

    directory = bytearray()
    cursor = first
    for name in names:
        block = blocks[name]
        directory += cursor.to_bytes(4, "big")
        directory += len(block).to_bytes(4, "big")
        directory += name.encode("ascii")
        directory += b"\0"
        cursor += len(block)

    out = bytearray()
    out += b"ShpF"
    out += cursor.to_bytes(4, "little")
    out += count.to_bytes(4, "big")
    out += (dir_end + 8).to_bytes(4, "big")
    out += directory
    out += meta
    out += pad
    if len(out) != first:
        raise SyntheticFshError("Internal native FSH directory alignment error.")
    for name in names:
        out += blocks[name]

    if len(out) != cursor:
        raise SyntheticFshError("Internal native FSH size mismatch.")
    if len(out) >= MAX_SAFE_FSH_BYTES:
        raise SyntheticFshError(
            f"{Path(output_path).name} would be {len(out)/(1024*1024):.2f} MiB, "
            "which is at/above the observed 16 MiB crash boundary."
        )

    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(out)
    return output


def _prepare_native_textures(textures: dict[str, str | Path]):
    encoded = {}
    blocks = {}
    paths = {}
    for raw_name, raw_path in textures.items():
        name = _validate_asset_name(raw_name)
        path = Path(raw_path).resolve()
        previous = paths.get(name)
        if previous is not None and previous != path:
            raise SyntheticFshError(
                f"TextureName {name!r} maps to two different PNG files."
            )
        paths[name] = path
        e = _encode_native_texture(path)
        encoded[name] = e
        blocks[name] = _native_block(e)
    return paths, encoded, blocks


def _partition_native_blocks(
    textures: dict[str, Path],
    blocks: dict[str, bytes],
    explicit: dict[str, str] | None = None,
):
    """Deterministic two-bin partition using exact native block sizes."""
    explicit = explicit or {}
    bins = {"MAIN": {}, "VRAM": {}}

    for name, where in explicit.items():
        if name in textures and where in bins:
            bins[where][name] = blocks[name]

    remaining = [n for n in textures if n not in explicit]
    remaining.sort(key=lambda n: len(blocks[n]), reverse=True)

    # Largest automatic textures naturally gravitate toward VRAM.
    for name in remaining:
        candidates = []
        for where in ("MAIN", "VRAM"):
            trial = dict(bins[where])
            trial[name] = blocks[name]
            size = _archive_size_for_blocks(trial)
            # Bias MAIN slightly upward so VRAM accepts more of the largest art.
            bias = 65536 if where == "MAIN" else 0
            overflow = MAX_SAFE_FSH_BYTES if size >= TARGET_SAFE_FSH_BYTES else 0
            candidates.append((overflow + size + bias, where))
        _, where = min(candidates)
        bins[where][name] = blocks[name]

    if len(textures) >= 2:
        if not bins["MAIN"]:
            movable = [n for n in bins["VRAM"] if explicit.get(n) != "VRAM"]
            if movable:
                n = min(movable, key=lambda x: len(blocks[x]))
                bins["MAIN"][n] = bins["VRAM"].pop(n)
        if not bins["VRAM"]:
            movable = [n for n in bins["MAIN"] if explicit.get(n) != "MAIN"]
            if movable:
                n = max(movable, key=lambda x: len(blocks[x]))
                bins["VRAM"][n] = bins["MAIN"].pop(n)

    main_size = _archive_size_for_blocks(bins["MAIN"]) if bins["MAIN"] else 0
    vram_size = _archive_size_for_blocks(bins["VRAM"]) if bins["VRAM"] else 0

    if main_size >= MAX_SAFE_FSH_BYTES or vram_size >= MAX_SAFE_FSH_BYTES:
        raise SyntheticFshError(
            f"Native compressed textures still cannot fit safely into two FSH files "
            f"(MAIN={main_size/(1024*1024):.2f} MiB, "
            f"VRAM={vram_size/(1024*1024):.2f} MiB). "
            "Reduce texture dimensions/sizes or adjust MAIN/VRAM overrides."
        )
    return bins, {"MAIN": main_size, "VRAM": vram_size}


def create_native_fsh_pair(
    textures: dict[str, str | Path],
    main_path: str | Path,
    vram_path: str | Path,
    explicit: dict[str, str] | None = None,
):
    if len(textures) < 2:
        raise SyntheticFshError(
            "Native MAIN/VRAM pair currently requires at least two distinct textures."
        )

    paths, encoded, blocks = _prepare_native_textures(textures)
    bins, predicted = _partition_native_blocks(paths, blocks, explicit)

    main_final = _build_native_shpf_from_blocks(bins["MAIN"], main_path)
    vram_final = _build_native_shpf_from_blocks(bins["VRAM"], vram_path)

    result = {
        "MAIN": main_final,
        "VRAM": vram_final,
        "main_textures": tuple(sorted(bins["MAIN"])),
        "vram_textures": tuple(sorted(bins["VRAM"])),
        "formats": {n: encoded[n]["format_name"] for n in sorted(encoded)},
        "final_sizes": {
            "MAIN": main_final.stat().st_size,
            "VRAM": vram_final.stat().st_size,
        },
    }
    return result


# Compatibility alias used by older package code.
def prepare_newfsh_workspace(
    textures: dict[str, dict[str, str | Path]],
    output_directory: str | Path,
    base_name: str,
) -> Path:
    outdir = Path(output_directory).resolve()
    work = outdir / f"{base_name}_newfsh_workspace"
    if work.exists():
        shutil.rmtree(work)
    (work / "main_pngs").mkdir(parents=True, exist_ok=True)
    (work / "vram_pngs").mkdir(parents=True, exist_ok=True)
    manifest={"base_name":base_name,"archives":{"MAIN":{},"VRAM":{}}}
    for archive,folder in (("MAIN","main_pngs"),("VRAM","vram_pngs")):
        for raw_name,raw_path in textures.get(archive,{}).items():
            name=_validate_asset_name(raw_name)
            source=Path(raw_path).resolve()
            dest=work/folder/f"{name}.png"
            shutil.copy2(source,dest)
            manifest["archives"][archive][name]=str(dest.relative_to(work))
    (work/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    return work


def create_native_fsh(textures, output_path):
    """Build one native ShpF archive from TextureName -> PNG path."""
    if not textures:
        raise SyntheticFshError("Cannot build an FSH with no textures.")
    _paths, encoded, blocks = _prepare_native_textures(textures)
    final = _build_native_shpf_from_blocks(blocks, output_path)
    return {
        "path": final,
        "textures": tuple(sorted(blocks)),
        "formats": {n: encoded[n]["format_name"] for n in sorted(encoded)},
        "size": final.stat().st_size,
    }


def _encode_dxt3_constant_rgba(r, g, b, a=255):
    """Encode one 4x4 constant-color DXT3 block."""
    # 4-bit alpha repeated for 16 pixels.
    an = max(0, min(15, int(round(a / 17.0))))
    alpha64 = 0
    for i in range(16):
        alpha64 |= an << (i * 4)
    alpha = alpha64.to_bytes(8, "little")

    c = _rgb565(r, g, b)
    # Four-color mode needs c0 > c1. Constant image can use c and neighbor.
    c0 = c
    c1 = c - 1 if c > 0 else 0
    if c0 <= c1:
        c0 = min(0xFFFF, c1 + 1)
    color = struct.pack("<HHI", c0, c1, 0)
    return alpha + color


def create_backboard_refl_fsh(texture_names, output_path, rgba=(255,255,255,255)):
    """Create the NBA Live backboard reflection-map FSH.

    Genuine 06 backboards use one 16x16 DXT3 (0x61) map per TextureName.
    The default is opaque white; users may later replace these reflection masks.
    """
    names=sorted({_validate_asset_name(n) for n in texture_names})
    if not names:
        raise SyntheticFshError("Reflection FSH needs at least one TextureName.")

    r,g,b,a=(int(x) for x in rgba)
    block4=_encode_dxt3_constant_rgba(r,g,b,a)
    payload=block4 * 16  # 16x16 = sixteen 4x4 blocks

    blocks={}
    for name in names:
        hdr=bytearray(32)
        hdr[0]=0x61  # DXT3
        hdr[1]=1
        hdr[8:12]=(0x20).to_bytes(4,'little')
        hdr[12:16]=len(payload).to_bytes(4,'little')
        hdr[24:28]=(16).to_bytes(4,'little')
        hdr[28:32]=(16).to_bytes(4,'little')
        block=bytes(hdr)+payload
        block += b'\0' * ((-len(block)) & 0xF)
        blocks[name]=block

    final=_build_native_shpf_from_blocks(blocks,output_path)
    return {
        "path": final,
        "textures": tuple(names),
        "format": "DXT3/0x61",
        "dimensions": (16,16),
        "size": final.stat().st_size,
    }


def read_shpf_blocks(path):
    """Read raw image blocks from an existing ShpF archive.

    Returns TextureName -> complete native image block bytes. Existing entries
    can therefore be preserved byte-for-byte without decoding/recompressing.
    """
    path=Path(path).resolve()
    data=path.read_bytes()
    if data[:4] != b"ShpF":
        raise SyntheticFshError(f"{path.name}: not a ShpF archive.")
    if len(data) < 16:
        raise SyntheticFshError(f"{path.name}: truncated ShpF header.")

    count=int.from_bytes(data[8:12],"big")
    pos=16
    result={}
    for i in range(count):
        if pos+9 > len(data):
            raise SyntheticFshError(f"{path.name}: truncated directory entry {i}.")
        start=int.from_bytes(data[pos:pos+4],"big")
        size=int.from_bytes(data[pos+4:pos+8],"big")
        name_start=pos+8
        name_end=data.find(b"\0",name_start,min(len(data),name_start+64))
        if name_end < 0:
            raise SyntheticFshError(
                f"{path.name}: unterminated TextureName in directory entry {i}."
            )
        try:
            name=data[name_start:name_end].decode("ascii")
        except UnicodeDecodeError as exc:
            raise SyntheticFshError(
                f"{path.name}: non-ASCII TextureName in directory entry {i}."
            ) from exc
        _validate_asset_name(name)
        if start < 0 or size <= 0 or start+size > len(data):
            raise SyntheticFshError(
                f"{path.name}: invalid block bounds for {name!r}: "
                f"0x{start:X}+0x{size:X}."
            )
        result[name]=bytes(data[start:start+size])
        pos=name_end+1
    return result


def create_native_fsh_merged(
    textures,
    output_path,
    *,
    reference_fsh=None,
    required_names=(),
):
    """Build FSH using Blender PNGs plus untouched fallback entries.

    Blender PNGs take priority. Any required TextureName lacking a Blender image
    may be copied byte-for-byte from reference_fsh.
    """
    textures=dict(textures or {})
    blocks={}
    encoded={}

    if reference_fsh:
        ref=Path(reference_fsh).resolve()
        if ref.is_file():
            blocks.update(read_shpf_blocks(ref))

    if textures:
        _paths,enc,new_blocks=_prepare_native_textures(textures)
        blocks.update(new_blocks)
        encoded.update(enc)

    required={str(n) for n in required_names if n}
    missing=sorted(required-set(blocks))
    if missing:
        raise SyntheticFshError(
            "No Blender image and no matching reference FSH entry for TextureNames: "
            + ", ".join(missing)
        )

    # Do not carry unrelated reference textures into a newly named package.
    if required:
        blocks={n:blocks[n] for n in sorted(required)}

    final=_build_native_shpf_from_blocks(blocks,output_path)
    return {
        "path":final,
        "textures":tuple(sorted(blocks)),
        "replaced_from_blender":tuple(sorted(textures)),
        "preserved_from_reference":tuple(
            sorted(set(blocks)-set(textures))
        ),
        "formats":{
            n:encoded[n]["format_name"] for n in sorted(encoded)
        },
        "size":final.stat().st_size,
    }
