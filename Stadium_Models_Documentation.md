# NBA Live EBO Tools — Stadium Models

## Overview

The stadium workflow in **NBA Live EBO Tools** supports two major use cases:

1. **Importing, editing, and rebuilding an existing NBA Live stadium**
2. **Creating a new stadium package directly from Blender**

A user does not need to begin with an original EA stadium in order to build a new stadium package. The dedicated **Stadium / Court EBO** panel can serialize selected Blender meshes into the NBA Live stadium format and create the required texture archives.

The existing-EBO workflow supports native NBA Live stadium assets from **NBA Live 2005–08**.

The scratch stadium exporter uses the verified newer stadium format used by the current tool. Stadiums created with the **NBA Live 06-family** workflow have also been tested successfully in **NBA Live 07 and NBA Live 08**.

Stadiums are ordinary static environment Geometry, so they are substantially more flexible than specialized models such as player heads or backboards. Supported static stadium geometry can be rebuilt with new topology, new material groups, new textures, UV edits, vertex colors, and new Geometry objects.

---

# Requirements

## Software

- **Blender 5.0 or newer**
- **NBA Live EBO Tools** installed and enabled

No external EBO compiler is required.

No external FSH compiler is required for the supported native stadium package workflow.

---

# Typical Stadium Files

A normal NBA Live stadium commonly uses files such as:

```text
<arena>.ebo
<arena>_trans.ebo
<arena>.fsh
<arena>_vram.fsh
```

Some stadiums additionally use a high-detail reflection model:

```text
<arena>_highref.ebo
```

The exact set can vary between arenas.

The scratch **Export Stadium Package** workflow creates:

```text
<name>.ebo
<name>_trans.ebo
<name>.fsh
<name>_vram.fsh
```

and, when a high-reflection collection is supplied:

```text
<name>_highref.ebo
```

---

# Stadium Features

The stadium toolset supports:

- Importing existing NBA Live 2005–08 stadium EBOs
- Editing existing stadium Geometry
- Exporting rebuilt existing stadiums
- Creating stadiums from scratch
- Multiple Geometry objects
- New Geometry topology
- Vertex-position editing
- UV editing
- Vertex colors
- Multiple material groups
- Adding materials
- Removing materials
- Renaming materials and textures
- Sharing one texture between several RMS/material types
- Opaque stadium geometry
- Transparent stadium geometry
- Optional high-reflection geometry
- Native MAIN and `_vram` FSH generation
- Existing FSH extraction and repacking
- Native DXT1/DXT5 texture generation
- Manual or automatic MAIN/VRAM texture placement
- `TextureStadium`
- `TextureStadiumNoZWrite`
- `TextureGlow`
- `ScrollTextureDim`
- `TextureStadiumRef`
- `ScrollTextureDimRef`
- `TextureScaleOffsetUV` experimental support
- Custom jumbotron RMS materials
- Automatic creation of the complete 69-material jumbotron set
- Shared jumbotron atlas textures
- FBX import/export helpers
- Automatic coordinate conversion
- Automatic UV-V conversion
- Alpha correction for transparent scratch geometry
- Texture deduplication and consistency checks

---

# Supported Workflows

| Workflow | NBA Live 2005 | NBA Live 06 | NBA Live 07 | NBA Live 08 |
|---|---:|---:|---:|---:|
| Import existing stadium | Yes | Yes | Yes | Yes |
| Edit static stadium geometry | Yes | Yes | Yes | Yes |
| Rebuild topology | Yes | Yes | Yes | Yes |
| Add/remove/rename material groups | Yes | Yes | Yes | Yes |
| Repack existing FSH archives | Yes | Yes | Yes | Yes |
| Scratch stadium package | Tool-supported | Yes | Yes via 06-family | Yes via 06-family |

For a first custom stadium project, the newer **06-family stadium workflow** is the recommended starting point when targeting NBA Live 06, 07, or 08.

---

# Two Stadium Workflows

## Workflow A — Build a Stadium From Scratch

Use this when:

- converting a stadium from another game
- modeling a new arena in Blender
- replacing the original arena geometry completely
- building a stadium without an EA donor EBO

The exporter constructs the EBO Geometry, materials, streams, bounds, runtime imports, and FSH archives itself.

## Workflow B — Edit an Existing Stadium

Use this when:

- modifying an original EA arena
- preserving unusual original Geometry or RMS metadata
- making smaller changes
- working from an arena that already has the desired object/material organization
- editing a native 2005–08 stadium with minimal structural changes

Both workflows are covered below.

---

# Part I — Building a Stadium From Scratch

## 1. Prepare the Stadium in Blender

The geometry can come from:

- Blender modeling
- OBJ
- FBX
- a converted model from another game
- another 3D package

The exporter operates on normal Blender mesh objects.

Quads and n-gons are allowed in Blender. The exporter uses Blender's evaluated triangulated mesh when writing the EBO.

Object transforms are baked into exported vertex positions.

---

# 2. Create the Required Collections

Scratch stadium export uses Blender collection names to determine which EBO a mesh belongs to.

The required collections are:

```text
std
std_trans
```

An optional reflection collection is:

```text
std_highref
```

## `std`

Use this collection for normal opaque stadium geometry.

Typical examples might include:

```text
StadiumBase
roof
sideline
seating
walls
scoreboard_structure
```

These names are only examples. The exporter does **not** require those exact Geometry names.

## `std_trans`

Use this collection for geometry that belongs in the transparent stadium pass.

Examples can include:

```text
led
crowd2D
glass
rail_transparency
transparent_signage
```

Again, object names are user-controlled.

## `std_highref`

This collection is optional.

Use it for the stadium's high-detail reflection geometry.

A known native Geometry name is:

```text
StadiumReflect
```

The panel displays this name as a reference, but object naming is not otherwise hard-coded by the exporter.

---

# 3. Select the Stadium Geometry

The scratch Stadium Package exporter uses **selected meshes**.

Before export:

1. Select the intended `std` meshes.
2. Select the intended `std_trans` meshes.
3. Select any optional `std_highref` meshes.
4. Make sure no unrelated mesh is selected.

Every selected mesh must belong to one of:

```text
std
std_trans
std_highref
```

If a selected mesh is outside those collections, the exporter stops and reports it.

At least one selected mesh must exist in:

```text
std
```

and at least one in:

```text
std_trans
```

`std_highref` is optional.

---

# 4. Geometry Object Names

Each selected Blender mesh becomes a separate NBA Live **Geometry** object.

The Blender object name is written as the Geometry name.

Geometry names must therefore be unique.

For scratch stadiums, the names are intentionally user-controlled. A simple arena might use:

```text
StadiumBase
sideline
roof
```

with transparent objects such as:

```text
led
crowd2D
glass
```

The tool does not require an EA stadium's original object names.

This makes it practical to convert external stadiums without rebuilding the original arena's exact internal object list.

---

# 5. Coordinate Conversion

The exporter converts Blender coordinates to NBA Live coordinates automatically.

Internally, scratch stadium positions use:

```text
Blender X -> NBA Live X
Blender Z -> NBA Live Y
Blender Y -> NBA Live -Z
```

A user should therefore model the stadium naturally in Blender rather than manually applying a game-coordinate conversion.

Object world transforms are included during export.

Before producing a final package, verify:

- arena scale
- court center
- floor height
- basket alignment
- crowd position
- roof height
- camera-facing geometry

---

# 6. UV Maps

The exporter uses the **first UV map** on each mesh.

NBA Live and Blender use opposite vertical UV orientation, so the exporter converts V automatically:

```text
game V = 1.0 - Blender V
```

A user should not manually flip V just to compensate for the EBO format.

If an object has no UV map, the exporter writes:

```text
0, 0
```

for its UV coordinates.

For a real stadium, a proper UV map is strongly recommended.

---

# 7. Vertex Colors

Stadium geometry supports vertex colors.

The exporter first looks for:

```text
NBA Live Vertex Colors
```

If that attribute is unavailable, it uses the first compatible color attribute with a:

```text
POINT
```

or:

```text
CORNER
```

domain.

If no usable color layer exists, the exporter writes opaque white:

```text
255, 255, 255, 255
```

Vertex colors can therefore be omitted when the stadium does not require them.

They should be preserved when an imported arena uses them for lighting, tinting, transparency, or material effects.

---

# 8. Transparent Geometry and Alpha

The `std_trans` collection is compiled as the stadium's transparent pass.

A common problem when importing geometry from OBJ or RGB-only workflows is that all vertex alpha values may arrive as zero.

An all-zero alpha channel can make transparent stadium geometry disappear.

For the scratch transparent pass, EBO Tools detects a material whose vertex colors are entirely alpha `0` and automatically changes them to:

```text
alpha = 255
```

This treats an all-zero alpha channel as "alpha was absent."

## Keeping intentional zero alpha

If the zero alpha values are intentional, add this Blender material custom property:

```text
nba_live_keep_zero_alpha = True
```

The exporter will then preserve the zero alpha values.

---

# 9. Materials

Scratch stadium materials use a simple readable naming convention:

```text
<texture> [<RMS type>]
```

For example:

```text
concrete [TextureStadium]
dorna [ScrollTextureDim]
light [TextureGlow]
glass [TextureStadiumNoZWrite]
```

The optional `EBO.` prefix is also accepted:

```text
EBO.concrete [TextureStadium]
```

The part before the brackets is the **texture name stored in the EBO/FSH**.

The bracketed value is the **RenderMethod/RMS type**.

If no `[RMS]` suffix is supplied in scratch stadium mode, the default is:

```text
TextureStadium
```

---

# 10. Verified Stadium RMS Types

The current tool knows these stadium-related RMS names:

```text
TextureStadium
TextureStadiumNoZWrite
TextureGlow
ScrollTextureDim
TextureStadiumRef
ScrollTextureDimRef
```

It also exposes:

```text
TextureScaleOffsetUV
```

as an experimental static-layout RMS.

## `TextureStadium`

Normal opaque stadium surface.

Example:

```text
seat [TextureStadium]
```

## `TextureStadiumNoZWrite`

Stadium texture material using the no-Z-write runtime.

Example:

```text
glass [TextureStadiumNoZWrite]
```

## `TextureGlow`

Glow/emissive-style stadium material.

Example:

```text
light [TextureGlow]
```

## `ScrollTextureDim`

Animated/dynamic scrolling stadium material.

This is commonly useful for stadium signage such as dorna/LED surfaces.

Example:

```text
odrn [ScrollTextureDim]
```

## `TextureStadiumRef`

Reflection stadium material.

This is the default RMS used for scratch `std_highref` geometry when no explicit RMS is supplied.

## `ScrollTextureDimRef`

Reflection-side scrolling/dynamic material.

## `TextureScaleOffsetUV`

Available for experimentation with the static material compiler.

Its exact per-material variable contract is not considered as fully validated as the verified stadium RMS types.

---

# 11. Shared Texture Names With Different RMS Types

Material identity is:

```text
(texture name, RMS type)
```

not texture name alone.

This means one texture can intentionally be used by multiple material rows.

For example:

```text
arena_atlas [TextureStadium]
arena_atlas [TextureGlow]
```

is valid because the RMS identities are different.

Likewise, all custom jumbotron materials can share one atlas texture.

An exact duplicate pair on the same Geometry is not valid:

```text
arena_atlas [TextureStadium]
arena_atlas [TextureStadium]
```

The scratch compiler rejects duplicate texture/RMS identities.

---

# 12. Blender Vertex Splitting

Blender can store different UV/color values on different corners of the same logical vertex.

NBA Live's exported streams need concrete per-output-vertex values.

The scratch exporter automatically splits output vertices when required by:

- UV seams
- different corner UVs
- different corner vertex colors

As a result, the exported vertex count may be larger than the visible Blender vertex count.

This is normal.

---

# 13. Stadium Textures

Each scratch stadium texture must resolve to a real image file.

The exporter searches Blender materials in this order:

1. Image Texture connected to the Principled BSDF **Base Color**
2. Active Image Texture node
3. Other Image Texture nodes
4. Imported NBA Live texture-path metadata

The recommended setup is:

```text
Image Texture -> Principled BSDF Base Color
```

Save the image to disk before export.

If a required stadium material has no resolvable image, scratch package export stops instead of creating an incomplete package.

---

# 14. Texture Name Consistency

One NBA Live texture name must represent one image.

For example, if several materials use:

```text
seat
```

they must all resolve to the same source image.

The exporter rejects cases where the same TextureName maps to two different PNG files.

This prevents ambiguous FSH packages.

---

# 15. MAIN and VRAM FSH Archives

The scratch stadium exporter creates:

```text
<name>.fsh
<name>_vram.fsh
```

Textures used by all selected:

```text
std
std_trans
std_highref
```

objects are deduplicated before packing.

---

# 16. Automatic MAIN/VRAM Split

When no manual archive choice is supplied, the exporter divides textures by source-file size.

The default heuristic aims to place approximately:

```text
30% of source PNG bytes -> MAIN
larger/remainder         -> VRAM
```

The algorithm prefers lighter textures for MAIN and larger textures for VRAM.

When there are at least two automatically assigned textures, it also attempts to keep both archives populated.

---

# 17. Manual MAIN/VRAM Override

A material can force its texture archive using:

```text
nba_live_fsh_archive = "MAIN"
```

or:

```text
nba_live_fsh_archive = "VRAM"
```

An explicit setting overrides the automatic split.

Every material using the same TextureName must agree on the archive location.

Conflicting MAIN/VRAM instructions for the same TextureName are rejected.

---

# 18. Native Texture Compression

The package builder creates native FSH textures directly.

The texture codec is selected automatically:

```text
opaque image            -> DXT1
image with useful alpha -> DXT5
```

No external FSH compiler is required.

---

# 19. FSH Size Protection

NBA Live has practical FSH size limits.

The tool protects against oversized native archives rather than silently creating a likely-crashing package.

A useful working limit is approximately:

```text
16 MiB per FSH archive
```

If an archive becomes too large:

- reduce texture dimensions
- reduce unnecessary alpha
- move suitable textures between MAIN and VRAM
- simplify duplicated artwork

---

# 20. Optional High-Reflection Stadium EBO

If selected objects exist in:

```text
std_highref
```

the exporter creates:

```text
<name>_highref.ebo
```

For this model:

- the default RMS is `TextureStadiumRef`
- known reflection Geometry flags are used
- reflection auxiliary/TOC flags are enabled
- zero alpha normalization is also applied when appropriate

A known native Geometry name is:

```text
StadiumReflect
```

The tool does not force every object to use that name, but it is a useful reference when reconstructing a native-style reflection model.

---

# 21. Exporting a Scratch Stadium Package

In Blender:

1. Create/populate:
   ```text
   std
   std_trans
   ```
2. Optionally create:
   ```text
   std_highref
   ```
3. Assign materials and textures.
4. Select the meshes to export.
5. Open:
   ```text
   NBA Live > Stadium / Court EBO
   ```
6. Enable:
   ```text
   Stadium
   ```
7. Make sure **Court** is not enabled at the same time.
8. Review the panel's selected Geometry/material/UV/color summary.
9. Click:
   ```text
   Export Stadium Package
   ```
10. Choose the output filename.

The exporter creates the complete stadium package.

Example:

```text
customstd.ebo
customstd_trans.ebo
customstd.fsh
customstd_vram.fsh
```

and, when supplied:

```text
customstd_highref.ebo
```

If the chosen output filename ends with `_trans`, the exporter automatically removes that suffix when determining the package base name.

---

# Part II — Editing an Existing Stadium

## 22. Existing Stadium Import

Existing NBA Live stadiums can be imported through the main environment importer.

Open:

```text
NBA Live > NBA Live Environments
```

and use:

```text
Import NBA Live EBO
```

For best results, keep the stadium's FSH files available beside the EBO or point the tool to their archive directory.

The importer preserves the information needed for a template-backed rebuild.

---

# 23. Texture Extraction During Import

Enable:

```text
Extract FSH on Import
```

to decode available FSH textures to PNG.

The tool supports native MAIN and `_vram` archives.

When a texture cannot be resolved, the importer can create a visible placeholder image so geometry remains inspectable in Blender.

A placeholder should be replaced with the intended real texture before publishing the stadium.

---

# 24. Imported Material Names

Imported stadium materials are displayed in readable form:

```text
EBO.<texture> [<RMS type>]
```

Examples:

```text
EBO.gcon [TextureStadium]
EBO.odrn [ScrollTextureDim]
```

This exposes both the actual texture name and the RenderMethod identity.

---

# 25. Editing Existing Static Stadium Geometry

For decoded static stadium Geometry, the tool supports:

- moving vertices
- editing UVs
- editing vertex colors
- changing topology
- adding faces
- deleting faces
- adding material groups
- deleting material groups
- renaming texture/material names

This is one of the important differences between stadiums and specialized assets such as player heads or many backboard structures.

---

# 26. Existing Stadium Topology Rebuild

The general environment exporter can rebuild supported static stadium topology.

A user can therefore:

- convert triangles to different topology in Blender
- add or remove vertices
- replace portions of an arena
- import external mesh parts
- reorganize material assignment

The rebuilt EBO updates the necessary static geometry streams.

A clean no-edit round trip should still be tested before making major changes to a new arena.

---

# 27. Adding a Material to an Existing Stadium

A new material group can be created using a readable RMS form:

```text
EBO.newtexture [TextureStadium]
```

or the explicit template/archive form:

```text
EBO.<new texture>.<template texture or RMS type>.<main|vram>
```

Examples:

```text
EBO.new0.TextureStadium.main
EBO.animated_ad.ScrollTextureDim.vram
```

The template may be:

- an existing material/texture group on that object
- a known RMS type

At least one face must be assigned to the material for it to be exported.

---

# 28. Renaming Existing Stadium Materials

An imported material can be renamed.

Example:

```text
EBO.oldseat [TextureStadium]
```

to:

```text
EBO.newseat [TextureStadium]
```

When FSH repacking is enabled, the tool removes obsolete transitional texture names from the rebuilt archive when they are no longer referenced.

---

# 29. Removing an Existing Stadium Material

To remove an original material group, remove all faces assigned to it.

The exporter tracks concrete material batches rather than relying only on texture names.

For a template-backed imported Geometry, at least one original material group must remain so compatible source metadata is still available for the rebuild.

---

# 30. Repacking Existing Stadium FSH Archives

Enable:

```text
Repack FSH on Export
```

when the texture archives should be rebuilt together with the EBO.

The repacker supports:

- MAIN archive staging
- `_vram` archive staging
- renamed textures
- new textures
- deleted textures
- shared textures
- automatic RGB PNG to opaque RGBA conversion where required
- filtering stale entries
- restoring game-side slot-qualified names

---

# 31. Slot-Qualified FSH Names

Some FSH entries can contain names that are inconvenient as normal filenames, for example:

```text
texture0:ball
```

The working PNG filename is sanitized as needed.

The actual game-side texture identity is restored inside the rebuilt FSH.

Users generally do not need to manually compensate for this.

---

# 32. Material Identity in Existing Stadiums

The existing exporter also treats material identity as:

```text
(texture, RMS)
```

This is important for advanced stadiums where the same image is intentionally used by several runtime types.

A shared texture does not need to be duplicated in the FSH simply because it is used by several RMS rows.

---

# 33. FBX Workflow

The **NBA Live Environments** panel includes:

```text
Import NBA Live FBX
Export NBA Live FBX
```

## Export NBA Live FBX

This is useful for:

- moving an imported arena to another Blender file
- external mesh cleanup
- conversion work
- archiving the decoded stadium

## Import NBA Live FBX

This can be used to bring external stadium geometry into Blender.

For a scratch stadium, the imported meshes can be organized directly into:

```text
std
std_trans
std_highref
```

For an existing-EBO workflow, the user should preserve the imported NBA Live collection/object metadata needed by the template-backed exporter.

---

# Part III — Stadium Jumbotron Materials

## 34. Jumbotron Support

EBO Tools contains dedicated RMS profiles for custom stadium jumbotron displays.

These are stadium materials, but their live values are supplied by the companion NBA Live runtime/plugin.

The EBO tool handles:

- material creation
- texture/RMS identity
- EBO serialization
- shared atlas texture use

The runtime plugin handles:

- score values
- clocks
- period
- fouls
- timeouts
- active-player values

---

# 35. Jumbotron Atlas

All jumbotron materials can use one shared texture atlas.

For example:

```text
jumbo [JumboHomeOnes]
jumbo [JumboAwayOnes]
jumbo [JumboGameSecOnes]
```

all refer to the same FSH texture:

```text
jumbo
```

but use different RMS identities.

The runtime changes the horizontal U offset while the vertical UV coordinate remains authored in Blender.

This allows several font rows to exist in one atlas.

---

# 36. Jumbotron Atlas Layout

The current runtime uses 16 equal horizontal cells:

```text
0-9  digits
10   blank
11   OT
12-15 reserved
```

A common atlas design is:

```text
U -> 0 1 2 3 4 5 6 7 8 9 BL OT ...
V
|
+-- Font row A
+-- Font row B
+-- Font row C
```

The Blender mesh chooses the vertical row.

The runtime chooses the horizontal digit cell.

---

# 37. Create Full Jumbotron Set

The **NBA Live Environments** panel includes a **Jumbotron Materials** section.

A user can:

1. Create one source Blender material.
2. Assign the jumbotron atlas texture.
3. Choose that material as the source.
4. Click:
   ```text
   Create Full Jumbotron Set
   ```

The tool duplicates the source setup and appends all **69** jumbotron RMS material slots to the active mesh.

This avoids manually creating and renaming every display material.

---

# 38. Jumbotron Score and Clock Materials

The original 13 channels are:

```text
JumboHomeHundreds
JumboHomeTens
JumboHomeOnes

JumboAwayHundreds
JumboAwayTens
JumboAwayOnes

JumboGameMinTens
JumboGameMinOnes
JumboGameSecTens
JumboGameSecOnes

JumboShotTens
JumboShotOnes

JumboPeriod
```

---

# 39. Team-Level Jumbotron Materials

The extended team channels are:

```text
JumboHomeTimeouts
JumboAwayTimeouts

JumboHomeTeamFoulsTens
JumboHomeTeamFoulsOnes

JumboAwayTeamFoulsTens
JumboAwayTeamFoulsOnes
```

---

# 40. Active-Five Jumbotron Materials

Each side has five live court slots:

```text
Court1
Court2
Court3
Court4
Court5
```

Each court slot exposes:

```text
NumberTens
NumberOnes
PointsTens
PointsOnes
Fouls
```

Example:

```text
JumboHomeCourt1NumberTens
JumboHomeCourt1NumberOnes
JumboHomeCourt1PointsTens
JumboHomeCourt1PointsOnes
JumboHomeCourt1Fouls
```

The same set exists for:

```text
Home Court1-Court5
Away Court1-Court5
```

`Court1` through `Court5` are live lineup slots, not fixed basketball positions such as center or point guard.

When substitutions occur, the incoming player inherits the outgoing player's court slot.

---

# 41. Jumbotron Material Naming

If the shared texture is named:

```text
jumbo
```

a generated material looks like:

```text
jumbo [JumboHomeCourt1PointsOnes]
```

The texture name stays `jumbo`.

Only the bracketed RMS identity changes.

This is intentional and is supported by the shared-texture material system.

---

# 42. Jumbotron Runtime Requirement

Static stadium materials such as `TextureStadium` work with the game normally.

The custom `Jumbo...` materials require the corresponding **NBA Live Launcher/runtime plugin** that publishes those RMS runtimes and supplies live game values.

Without that runtime component, the custom jumbotron material family should not be expected to animate correctly.

---

# Part IV — Recommended First-Time Workflow

## 43. Creating a Simple New Stadium

A first-time user can start with this structure:

```text
Collection: std
    StadiumBase
    roof
    sideline

Collection: std_trans
    led
    crowd2D
```

Optional:

```text
Collection: std_highref
    StadiumReflect
```

Example materials:

```text
concrete [TextureStadium]
seat [TextureStadium]
dorna [ScrollTextureDim]
glass [TextureStadiumNoZWrite]
reflection [TextureStadiumRef]
```

Then:

1. UV-map all meshes.
2. Add vertex colors if required.
3. Connect real PNG images to the Blender materials.
4. Select the stadium meshes.
5. Enable **Stadium** in the **Stadium / Court EBO** panel.
6. Click **Export Stadium Package**.
7. Install the generated EBO/FSH files.
8. Test in-game before adding more complexity.

---

# 44. Recommended Conversion Workflow

When converting a stadium from another game:

1. Import the source model into Blender.
2. Fix scale and orientation.
3. Split opaque and transparent geometry.
4. Place opaque objects in `std`.
5. Place transparent objects in `std_trans`.
6. Place reflection-only objects in `std_highref`, if required.
7. Reduce/organize materials.
8. Create UV maps.
9. Preserve or recreate vertex colors.
10. Assign NBA Live RMS types.
11. Connect PNG textures.
12. Export the package.
13. Test.
14. Add animated signage, reflections, or jumbotron channels only after the basic arena works.

---

# 45. Recommended Existing-Stadium Workflow

For an original EA stadium:

1. Keep a backup of the original EBO and FSH files.
2. Import the stadium.
3. Extract FSH textures.
4. Export once without edits.
5. Test the rebuilt file.
6. Make a small UV or vertex edit.
7. Test again.
8. Proceed to:
   - topology changes
   - new material groups
   - texture renames
   - animated materials
   - jumbotron additions

This makes it much easier to identify which modification caused a problem.

---

# Troubleshooting

## Stadium export says selected objects are outside the required collections

Every selected scratch-stadium mesh must belong to:

```text
std
std_trans
std_highref
```

Move or deselect the listed object.

---

## Stadium export says `std` is missing

At least one selected opaque stadium mesh must belong to:

```text
std
```

---

## Stadium export says `std_trans` is missing

At least one selected transparent-pass mesh must belong to:

```text
std_trans
```

Even if the stadium contains very little transparency, the current package workflow expects the trans EBO.

---

## A transparent object is invisible

Check:

- the object is in `std_trans`
- its RMS is appropriate
- its PNG has the intended alpha
- its vertex alpha is not unintentionally zero

The scratch exporter automatically repairs a completely-zero alpha channel unless:

```text
nba_live_keep_zero_alpha = True
```

is set.

---

## A texture is missing

Verify:

- the material has an Image Texture
- the image file exists on disk
- the TextureName before `[RMS]` is correct
- the generated `.fsh` and `_vram.fsh` were installed
- all materials using the same TextureName point to the same image

---

## The same texture name causes an export error

The same TextureName is mapped to two different PNG files.

NBA Live needs one consistent image per texture identity.

Rename one texture or make both materials use the same image.

---

## MAIN/VRAM archive conflict

Several materials using the same TextureName have contradictory:

```text
nba_live_fsh_archive
```

values.

All uses of one TextureName must agree on MAIN or VRAM.

---

## Stadium geometry appears rotated or mirrored

Do not manually apply a second game-coordinate conversion.

The scratch exporter already converts Blender coordinates and UV V orientation.

Check the original source model's Blender orientation first.

---

## UVs are upside-down

The exporter already performs:

```text
V = 1 - V
```

Do not manually compensate twice.

---

## Exported vertex count is unexpectedly high

UV seams and per-corner colors can cause the exporter to split output vertices.

This is normal.

---

## A new RMS is rejected

Only registered RMS names can be used by the scratch material compiler.

Use a known RMS such as:

```text
TextureStadium
TextureStadiumNoZWrite
TextureGlow
ScrollTextureDim
TextureStadiumRef
ScrollTextureDimRef
```

or one of the registered custom jumbotron RMS types.

---

## Jumbotron material exports but does not update in-game

The EBO material alone is not enough.

The custom `Jumbo...` material family requires the corresponding launcher/runtime implementation.

---

# Quick Reference

## Required scratch collections

```text
std
std_trans
```

Optional:

```text
std_highref
```

## Known highref Geometry name

```text
StadiumReflect
```

## Standard material format

```text
texture [RMS]
```

## Default stadium RMS

```text
TextureStadium
```

## Common RMS types

```text
TextureStadium
TextureStadiumNoZWrite
TextureGlow
ScrollTextureDim
TextureStadiumRef
ScrollTextureDimRef
TextureScaleOffsetUV   (experimental)
```

## Scratch output

```text
<name>.ebo
<name>_trans.ebo
<name>.fsh
<name>_vram.fsh
```

Optional:

```text
<name>_highref.ebo
```

## Jumbotron generator

```text
Create Full Jumbotron Set
69 RMS material types
```

## Transparent alpha override

```text
nba_live_keep_zero_alpha = True
```

## Manual archive override

```text
nba_live_fsh_archive = "MAIN"
nba_live_fsh_archive = "VRAM"
```

## Recommended 07/08 scratch workflow

```text
Use the NBA Live 06-family stadium format.
```

---

# Summary

NBA Live EBO Tools provides both a traditional **import/edit/rebuild** stadium workflow and a true **scratch stadium package builder**.

A first-time user can create ordinary Blender meshes, organize them into `std` and `std_trans`, assign NBA Live RMS material names and PNG textures, and export an installable stadium package without needing an original EA stadium EBO as a structural donor.

More advanced users can also work with:

- high-reflection stadium geometry
- animated `ScrollTextureDim` surfaces
- glow/no-Z-write materials
- shared RMS textures
- full FSH repacking
- topology rebuilding
- and the 69-channel custom jumbotron material system.

For NBA Live 07 and 08, the tested **NBA Live 06-family arena format** can be used for scratch stadiums as well.
