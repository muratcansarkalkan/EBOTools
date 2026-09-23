# NBA Live EBO Tools — Court Models

## Overview

The **Court Models** workflow in NBA Live EBO Tools supports two different ways of working:

1. **Importing, editing, and rebuilding an existing NBA Live court**
2. **Creating a completely new court package from Blender**

A new court does not need to begin from an original EA court EBO.

The dedicated **Stadium / Court EBO** panel can create the court EBO and native FSH texture archives directly from Blender meshes.

Existing NBA Live courts from **NBA Live 2005–08** can also be imported and edited.

The verified scratch court format used by the tool includes:

- NBA Live 2005
- NBA Live 06
- and the NBA Live 06 court format can also be used in NBA Live 07 and NBA Live 08

---

# Requirements

## Software

- **Blender 5.0 or newer**
- **NBA Live EBO Tools** installed and enabled

No external EBO compiler is required.

No external FSH compiler is required for the supported scratch court workflow.

---

# Court Features

The court toolset supports:

- importing existing NBA Live courts
- editing existing court geometry
- exporting rebuilt existing courts
- building new courts from scratch
- multiple Geometry objects
- multiple material groups
- new topology
- vertex editing
- UV editing
- vertex colors
- material renaming
- adding materials
- removing materials
- shared textures
- native FSH generation
- MAIN and `_vram` archives
- DXT1/DXT5 texture compression
- automatic coordinate conversion
- automatic UV-V conversion
- FBX import/export helpers

---

# Supported Workflows

| Workflow | NBA Live 2005 | NBA Live 06 | NBA Live 07 | NBA Live 08 |
|---|---:|---:|---:|---:|
| Import existing court | Yes | Yes | Yes | Yes |
| Edit/rebuild static court geometry | Yes | Yes | Yes | Yes |
| Repack existing FSH archives | Yes | Yes | Yes | Yes |
| Scratch court package | Yes | Yes | Yes via 06-family | Yes via 06-family |

---

# Part I — Creating a Court From Scratch

## 1. Prepare the Court in Blender

The court can be:

- modeled in Blender
- imported from FBX
- imported from OBJ
- converted from another game
- assembled from several mesh objects

The exporter uses selected Blender mesh objects.

Quads and n-gons are allowed in Blender. The exporter triangulates the evaluated mesh when creating the EBO.

---

# 2. Organize the Court Into Geometry Objects

Each selected Blender mesh becomes one NBA Live **Geometry** object.

Known working EA-style names include:

```text
aalogo1Shape
ccskirt1Shape
floor4Shape
```

Typical use:

```text
aalogo1Shape -> merged logos
ccskirt1Shape -> endcourt/skirt geometry
floor4Shape -> main floor
```

These names are useful references but are **not hard requirements** for a scratch court.

A user can create custom object names as long as they are unique and suitable for the intended package.

---

# 3. Geometry Order

Scratch court Geometry is written in a deterministic object-name order.

If draw order becomes important, object names can be prefixed to control sorting.

Example:

```text
a_floor4Shape
b_aalogo1Shape
c_ccskirt1Shape
```

Only use this when necessary.

---

# 4. Coordinates and Object Transforms

The exporter automatically converts Blender coordinates to NBA Live coordinates.

The user should model the court naturally in Blender.

Object world transforms are included in export.

Before final export, verify:

- scale
- floor height
- center position
- basket alignment
- arena alignment

---

# 5. UV Maps

The exporter uses the first UV layer.

The vertical UV coordinate is converted automatically:

```text
game V = 1.0 - Blender V
```

Do not manually flip the UV vertically just to compensate for the EBO format.

If no UV map exists, the exporter writes zero UV coordinates.

For real court artwork, proper UV mapping is recommended.

---

# 6. Vertex Colors

Court geometry supports vertex colors.

The exporter first looks for:

```text
NBA Live Vertex Colors
```

If it is not present, the first compatible POINT or CORNER color attribute is used.

If no usable color data exists, the exporter writes opaque white:

```text
255,255,255,255
```

Vertex colors are optional unless the specific court requires them.

---

# 7. Court Materials

Scratch court materials use:

```text
<texture> [<RMS>]
```

For normal court artwork:

```text
wood [NBACourt]
paint [NBACourt]
logo [NBACourt]
```

The optional prefix is also accepted:

```text
EBO.wood [NBACourt]
```

In Court mode, a plain material name defaults to:

```text
NBACourt
```

For clarity, the explicit form is recommended.

---

# 8. Material Slots

Only material slots that have assigned faces are exported.

Within one Geometry object:

- the same texture can be reused with different RMS types
- exact duplicate texture + RMS identities should not be duplicated

At least one face must be assigned to a material for it to appear in the EBO.

---

# 9. Vertex Splitting

Blender can use different UVs or colors on different corners of one vertex.

NBA Live needs concrete output vertices.

The exporter automatically creates extra output vertices when necessary for:

- UV seams
- per-corner colors

The exported vertex count can therefore be higher than the visible Blender vertex count.

This is expected.

---

# 10. Textures

Each scratch court material should use a real PNG image.

The recommended Blender node setup is:

```text
Image Texture -> Principled BSDF Base Color
```

The image file should be saved to disk.

The exporter searches Blender material image nodes automatically.

---

# 11. MAIN and VRAM FSH Archives

A scratch court package contains:

```text
<name>.fsh
<name>_vram.fsh
```

The exporter distributes textures between the two archives automatically.

The default heuristic aims to keep a smaller set in MAIN and place larger artwork in VRAM.

---

# 12. Manual FSH Archive Choice

A material can force its texture to MAIN:

```text
nba_live_fsh_archive = "MAIN"
```

or VRAM:

```text
nba_live_fsh_archive = "VRAM"
```

All uses of one TextureName should agree on the same archive.

---

# 13. Native Texture Compression

The scratch FSH writer chooses:

```text
opaque PNG -> DXT1
PNG with alpha -> DXT5
```

No external texture compiler is required.

---

# 14. FSH Size Limit

Keep each FSH archive below approximately:

```text
16 MiB
```

If an archive becomes too large:

- reduce texture dimensions
- simplify artwork
- move suitable textures between MAIN and VRAM

The exporter stops rather than producing an obviously oversized package.

---

# 15. Scratch Court Export

Open:

```text
View3D > Sidebar > NBA Live > Stadium / Court EBO
```

Choose:

```text
Court
```

Then:

1. Select the court meshes.
2. Choose the correct game profile.
3. Confirm materials and textures.
4. Click:
   ```text
   Export Court Package
   ```
5. Choose the output filename.

The exporter creates:

```text
<name>.ebo
<name>.fsh
<name>_vram.fsh
```

No original court EBO is required.

---

# 16. Scratch Court Game Profiles

## NBA Live 2005

Known default Geometry flags:

```text
0x31011C09
```

Default RMS:

```text
NBACourt
```

## NBA Live 06-family

Known default Geometry flags:

```text
0x22001407
```

Default RMS:

```text
NBACourt
```

The 06-family court format can also be used in NBA Live 07 and NBA Live 08.

---

# Part II — Editing an Existing Court

## 17. Prepare the Original Files

Keep the original court files available:

```text
court.ebo
court.fsh
court_vram.fsh
```

The FSH files should be beside the EBO or supplied through the archive-directory option.

---

# 18. Import the Court

Open:

```text
NBA Live > NBA Live Environments
```

Use:

```text
Import NBA Live EBO
```

The importer reconstructs the court Geometry and keeps the metadata needed for export.

---

# 19. Extract Textures

Enable:

```text
Extract FSH on Import
```

to decode the court's FSH textures to PNG.

If a texture cannot be resolved, the tool can create a visible placeholder so the geometry remains editable.

Replace placeholders before publishing the final court.

---

# 20. Imported Material Names

Imported materials are displayed in readable form:

```text
EBO.<texture> [<RMS>]
```

Example:

```text
EBO.wood [NBACourt]
```

This makes the game texture name and RMS identity visible directly in Blender.

---

# 21. Editing Existing Court Geometry

Supported static court geometry can be edited freely compared with player morph models.

Typical edits include:

- moving vertices
- changing UVs
- editing vertex colors
- adding faces
- deleting faces
- replacing sections of geometry
- changing topology
- adding new material groups
- deleting material groups

---

# 22. Important Existing-EBO Rule

When using the template-backed existing-EBO exporter:

**Do not rename or delete the imported Geometry objects unless the workflow specifically allows it.**

The exporter uses imported object identity to match Blender objects back to the original EBO records.

This restriction does not apply to the scratch court exporter.

---

# 23. Adding Materials

A new imported-court material can use:

```text
EBO.newtexture [NBACourt]
```

The explicit template/archive form is also available:

```text
EBO.newtexture.NBACourt.main
EBO.newlogo.NBACourt.vram
```

Assign at least one face to the new material.

---

# 24. Renaming Materials

Example:

```text
EBO.oldwood [NBACourt]
```

can be renamed to:

```text
EBO.newwood [NBACourt]
```

If FSH repacking is enabled, the rebuilt archive follows the final texture naming.

---

# 25. Removing Materials

Remove all faces assigned to the material group.

The exporter tracks concrete material batches rather than relying only on texture names.

For imported/template-backed Geometry, at least one original material group should remain so compatible source metadata is available.

---

# 26. Exporting the Edited Court

Select an object in the imported court collection.

Use:

```text
Export NBA Live EBO
```

Enable:

```text
Repack FSH on Export
```

when textures were changed, renamed, added, or removed.

This workflow is appropriate for original NBA Live 2005–08 courts.

---

# 27. Existing FSH Repacking

The repacker supports:

- MAIN archive
- `_vram` archive
- texture replacement
- new textures
- renamed textures
- removed textures
- shared textures
- stale-name cleanup
- safe filename handling for unusual FSH slot names

---

# 28. FBX Workflow

The NBA Live Environments panel includes:

```text
Import NBA Live FBX
Export NBA Live FBX
```

Use FBX when:

- transferring a court between Blender files
- editing geometry externally
- converting a court from another game
- archiving decoded geometry

For a scratch court, the imported FBX meshes can be used directly as final court Geometry objects.

---

# Recommended First-Time Scratch Court

A simple court can begin with:

```text
floor4Shape
aalogo1Shape
ccskirt1Shape
```

Example materials:

```text
wood [NBACourt]
paint [NBACourt]
lines [NBACourt]
centerlogo [NBACourt]
```

Then:

1. UV-map the meshes.
2. Add real PNG textures.
3. Select the court objects.
4. Open **Stadium / Court EBO**.
5. Choose **Court**.
6. Export the package.
7. Test in-game.
8. Add more complexity only after the basic court works.

---

# Recommended Testing Procedure

For a new user:

1. Import an untouched original court.
2. Export without edits.
3. Test in-game.
4. Make one small edit.
5. Export again.
6. Test.
7. Only then begin major topology/material changes.

For a scratch court:

1. Start with simple geometry.
2. Use a small number of textures.
3. Export.
4. Test scale, UVs, and placement.
5. Add details incrementally.

---

# Troubleshooting

## Textures are missing

Check:

- the material has a real image
- the image file exists
- the texture name before `[NBACourt]` is correct
- both generated FSH files were installed

---

## Court appears in the wrong place

Check:

- Blender scale
- object transforms
- floor height
- center alignment
- arena alignment

The exporter already handles coordinate conversion.

---

## UVs are upside-down

The exporter already converts:

```text
V = 1 - V
```

Do not compensate twice.

---

## Exported vertex count is larger

UV seams and per-corner colors can split output vertices.

This is normal.

---

## A duplicate material error appears

Do not create the exact same:

```text
texture + RMS
```

identity twice on the same Geometry object.

---

# Quick Reference

## Scratch output

```text
court.ebo
court.fsh
court_vram.fsh
```

## Standard RMS

```text
NBACourt
```

## Material syntax

```text
texture [NBACourt]
```

## Known Geometry-name references

```text
aalogo1Shape
ccskirt1Shape
floor4Shape
```

## 2005 Geometry flags

```text
0x31011C09
```

## 06-family Geometry flags

```text
0x22001407
```

## 07/08 scratch courts

```text
Use the NBA Live 06-family court format.
```

---

# Summary

NBA Live EBO Tools supports both **existing-court editing** and **true scratch court creation**.

A first-time user can build ordinary Blender meshes, assign `NBACourt` materials and PNG textures, and export a complete court package without needing an original donor EBO.

Existing NBA Live 2005–08 courts can also be imported, modified, rebuilt, and repacked using the general environment workflow.
