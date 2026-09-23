#!/usr/bin/env python3
"""Patch NBA Live Environment Tools so obsolete per-channel Jumbo textures
are omitted from rebuilt FSH archives.

Run:
    py apply_jumbotron_fsh_cleanup_patch.py <addon_folder>

Expected prior state:
- shared jumbotron texture integration is already installed
- blender_addon.py imports jumbotron_shared_texture
- Jumbo* materials are retargeted to the shared texture "jumbo"

This patch:
1. Adds excluded_names= to fsh_archive.repack_archive().
2. Records old per-channel names (jh10, ja10, etc.) when a Jumbo material is
   remapped to "jumbo".
3. Excludes those old names from the final GX staging set.

It DOES NOT delete extracted PNG files from nba_live_textures; it only stops
packing them into the rebuilt FSH.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil


def fail(message: str) -> None:
    raise SystemExit("ERROR: " + message)


def patch_fsh_archive(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = text

    if "excluded_names: frozenset[str]" not in text:
        old = """def repack_archive(
    archive: FshArchive,
    texture_directory: str | Path,
    gx_path: str | Path,
    output_directory: str | Path,
    *,
    required_names: frozenset[str] = frozenset(),
) -> Path:
"""
        new = """def repack_archive(
    archive: FshArchive,
    texture_directory: str | Path,
    gx_path: str | Path,
    output_directory: str | Path,
    *,
    required_names: frozenset[str] = frozenset(),
    excluded_names: frozenset[str] = frozenset(),
) -> Path:
"""
        if old not in text:
            fail("Could not find repack_archive() signature in fsh_archive.py.")
        text = text.replace(old, new, 1)

    old_expected = "    expected = archive.texture_names | required_names\n"
    new_expected = (
        "    # Preserve normal source entries, add newly required textures, and\n"
        "    # deliberately omit source entries that were superseded during export.\n"
        "    expected = (archive.texture_names | required_names) - excluded_names\n"
    )
    if old_expected in text:
        text = text.replace(old_expected, new_expected, 1)
    elif "expected = (archive.texture_names | required_names) - excluded_names" not in text:
        fail("Could not find expected FSH membership calculation in fsh_archive.py.")

    if text != original:
        backup = path.with_name(path.name + ".before_jumbo_cleanup.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        temp = path.with_name(path.name + ".jumbo_cleanup_tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)


def patch_blender_addon(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    original = text

    required_line = (
        '        required: dict[str, set[str]] = '
        '{archive.path.name: set() for archive in archives}\n'
    )
    if "excluded: dict[str, set[str]]" not in text:
        if required_line not in text:
            fail("Could not find FSH required-name table in blender_addon.py.")
        text = text.replace(
            required_line,
            required_line
            + '        excluded: dict[str, set[str]] = '
              '{archive.path.name: set() for archive in archives}\n',
            1,
        )

    old_loop = """        for name, (material, kind) in used_materials.items():
            name = jumbotron_shared_texture.export_texture_name(material, name)
            archive = by_kind.get(kind)
"""
    new_loop = """        for name, (material, kind) in used_materials.items():
            source_name = name
            name = jumbotron_shared_texture.export_texture_name(material, name)
            archive = by_kind.get(kind)
"""
    if "source_name = name" not in text:
        if old_loop not in text:
            fail(
                "Could not find the shared-texture used_materials loop. "
                "Make sure the earlier jumbotron shared-texture patch is installed."
            )
        text = text.replace(old_loop, new_loop, 1)

    anchor = """            if archive is None:
                label = "_vram.fsh" if kind == "VRAM" else ".fsh"
                raise fsh_archive.FshError(
                    f"Texture {name!r} targets {label}, but that source FSH archive was not found."
                )
            canonical_name = fsh_archive.resolve_entry_name(archive, name)
"""
    replacement = """            if archive is None:
                label = "_vram.fsh" if kind == "VRAM" else ".fsh"
                raise fsh_archive.FshError(
                    f"Texture {name!r} targets {label}, but that source FSH archive was not found."
                )

            # Jumbo working names such as jh10/ja10/jper may already exist in
            # the source FSH from an earlier export. Once the material is
            # retargeted to the shared texture "jumbo", omit those old names.
            if source_name != name:
                old_canonical = fsh_archive.resolve_entry_name(archive, source_name)
                excluded[archive.path.name].add(old_canonical)

            canonical_name = fsh_archive.resolve_entry_name(archive, name)
"""
    if "old_canonical = fsh_archive.resolve_entry_name(archive, source_name)" not in text:
        if anchor not in text:
            fail("Could not find archive validation block in blender_addon.py.")
        text = text.replace(anchor, replacement, 1)

    call_anchor = """                    required_names=frozenset(required[archive.path.name]),
                )
"""
    call_replacement = """                    required_names=frozenset(required[archive.path.name]),
                    excluded_names=frozenset(excluded[archive.path.name]),
                )
"""
    if "excluded_names=frozenset(excluded[archive.path.name])" not in text:
        if call_anchor not in text:
            fail("Could not find repack_archive() call in blender_addon.py.")
        text = text.replace(call_anchor, call_replacement, 1)

    if text != original:
        backup = path.with_name(path.name + ".before_jumbo_cleanup.bak")
        if not backup.exists():
            shutil.copy2(path, backup)
        temp = path.with_name(path.name + ".jumbo_cleanup_tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("addon_folder", type=Path)
    args = parser.parse_args()

    root = args.addon_folder.resolve()
    blender = root / "blender_addon.py"
    fsh = root / "fsh_archive.py"

    if not blender.is_file():
        fail(f"Missing {blender}")
    if not fsh.is_file():
        fail(f"Missing {fsh}")
    if not (root / "jumbotron_shared_texture.py").is_file():
        fail(
            "jumbotron_shared_texture.py is missing. "
            "Install the shared-texture integration first."
        )

    patch_fsh_archive(fsh)
    patch_blender_addon(blender)

    print("Patched:", blender)
    print("Patched:", fsh)
    print()
    print("New behavior:")
    print("  - Jumbo* materials keep unique working material names.")
    print('  - Final EBO references the shared texture "jumbo".')
    print('  - Final FSH packs "jumbo" once.')
    print("  - Superseded jh10/ja10/jper/etc. entries are omitted.")
    print("  - Old extracted PNG files are NOT deleted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
