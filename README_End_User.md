# NBA Live Environment Tools

Blender tools for importing, editing, rebuilding, and creating NBA Live EBO-based models and their related textures.

This package is intended for both first-time modders and advanced users who want to work with NBA Live environment, backboard, net, and player/body models directly in Blender.

The add-on combines several workflows that previously required separate research or manual binary editing:

- stadium editing and scratch stadium creation
- court editing and scratch court creation
- backboard editing and full package creation
- weighted basketball-net editing/export
- player/body morph editing
- native FSH texture extraction and repacking
- jumbotron material creation
- FBX interchange
- Xbox arena-model import

---

# Requirements

## Blender

Recommended:

```text
Blender 5.0 or newer
```

The tools appear in:

```text
3D Viewport > Sidebar > NBA Live
```

## Supported PC games

The main PC workflows are designed for the NBA Live 2005–08 generation.

Different model families use different format profiles, so read the relevant section before exporting.

---

# Installation

1. Open Blender.
2. Open:
   ```text
   Edit > Preferences > Add-ons / Extensions
   ```
3. Install the EBO Tools package ZIP.
4. Enable:
   ```text
   NBA Live Environment Tools
   ```
5. Open the 3D Viewport.
6. Press:
   ```text
   N
   ```
7. Open the:
   ```text
   NBA Live
   ```
   sidebar tab.

Do not extract and rearrange the Python package manually unless maintaining a development copy.

---

# Main Panels

The NBA Live sidebar contains several specialized panels.

```text
NBA Live Environments
Stadium / Court EBO
Backboard EBO
Net EBO
Player / Coach Morph EBO
Xbox Import
```

Each panel is designed for a different model family.

---

# Feature Overview

| Feature | Import | Edit | Export / Create |
|---|---:|---:|---:|
| Existing PC stadiums | Yes | Yes | Yes |
| Scratch stadiums | — | Yes | Yes |
| Existing PC courts | Yes | Yes | Yes |
| Scratch courts | — | Yes | Yes |
| Existing backboards | Yes | Yes | Yes |
| Scratch backboard packages | — | Yes | Yes |
| NBA Live 06 weighted nets | Yes | Yes | Yes |
| Player/body morph EBOs | Yes | Yes | Yes |
| Native FSH textures | Yes | Yes | Yes |
| Jumbotron material set | — | Yes | Yes |
| FBX interchange | Yes | Yes | Yes |
| Xbox VIV/EBO/XSH assets | Yes | Yes in Blender | Import only |

---

# 1. NBA Live Environments

The **NBA Live Environments** panel is the general-purpose importer/exporter for existing EBO environment assets.

It is primarily used for:

- stadiums
- transparent stadium geometry
- courts
- other compatible static Geometry

Use:

```text
Import NBA Live EBO
Export NBA Live EBO
```

---

# Existing EBO Import

The importer reads the EBO structure and creates Blender objects for the decoded Geometry records.

It preserves export metadata so supported files can later be rebuilt.

Typical imported information includes:

- Geometry objects
- material batches
- positions
- UVs
- vertex colors
- material/RMS identity
- original batch identity
- FSH texture references
- specialized transform-selector metadata where present

---

# Existing Static Geometry Editing

Supported static court/stadium Geometry can be edited in Blender.

Typical supported changes include:

- moving vertices
- UV editing
- vertex-color editing
- adding faces
- removing faces
- changing topology
- adding materials
- removing materials
- changing material assignment
- renaming texture identities

Specialized skinned/morph model families have different rules and should use their dedicated panels.

---

# Material Naming

Imported materials use a readable convention:

```text
EBO.<texture> [<RMS type>]
```

Example:

```text
EBO.seat [TextureStadium]
```

For scratch assets, the shorter form is accepted:

```text
seat [TextureStadium]
```

The part before the brackets is the EBO/FSH texture name.

The bracketed value is the RenderMethod/RMS identity.

---

# Shared Textures

Material identity is based on:

```text
(texture, RMS)
```

not texture name alone.

This means one texture can intentionally be used by several RMS types.

Example:

```text
arena_atlas [TextureStadium]
arena_atlas [TextureGlow]
```

The FSH texture only needs to exist once.

---

# Adding Materials

For imported environment assets, new material groups can be created from:

- a known RMS type
- compatible existing render metadata

New materials can then be assigned to selected faces in Blender.

---

# Removing Materials

Original environment material groups can be removed.

The removal tool deletes the assigned faces/material group while preserving the underlying FSH texture unless the archive rebuild determines it is no longer needed.

For template-backed Geometry, at least one original material group must remain.

---

# 2. Native FSH Support

EBO Tools includes native FSH handling.

External GX/FSH conversion tools are not required for supported workflows.

---

# FSH Extraction

Enable:

```text
Extract FSH on Import
```

The importer can decode supported:

```text
DXT1
DXT3
DXT5
```

textures to PNG.

The panel supports:

```text
FSH Directory
Extracted Textures
Extra Texture Folder
```

---

# FSH Repacking

Enable:

```text
Repack FSH on Export
```

to rebuild the original texture archives when exporting an edited environment.

Supported operations include:

- replacing textures
- adding textures
- renaming textures
- removing obsolete renamed entries
- preserving unrelated original entries
- MAIN archive handling
- `_vram` archive handling
- unusual slot-qualified texture names
- shared texture reuse

---

# Scratch FSH Generation

The Stadium/Court and Backboard package exporters can generate native FSH files directly from Blender materials and PNG images.

Typical compression selection:

```text
opaque image -> DXT1
image with alpha -> DXT5
```

---

# FSH Size Guidance

A practical safe target is:

```text
under approximately 16 MiB per FSH archive
```

Large archives can cause problems in the game.

When needed:

- reduce texture dimensions
- remove unnecessary alpha
- move textures between MAIN and VRAM
- avoid duplicate artwork

---

# 3. Stadium Models

Stadiums can be edited from existing EBO files or created from scratch.

The scratch workflow uses:

```text
NBA Live > Stadium / Court EBO
```

and requires the collections:

```text
std
std_trans
```

Optional:

```text
std_highref
```

---

# Scratch Stadium Output

The package exporter creates:

```text
<name>.ebo
<name>_trans.ebo
<name>.fsh
<name>_vram.fsh
```

When reflection geometry is supplied:

```text
<name>_highref.ebo
```

---

# Stadium RMS Types

Registered stadium-related RMS types include:

```text
TextureStadium
TextureStadiumNoZWrite
TextureGlow
ScrollTextureDim
TextureStadiumRef
ScrollTextureDimRef
TextureScaleOffsetUV
```

`TextureScaleOffsetUV` should be treated as experimental compared with the established stadium RMS profiles.

---

# Transparent Stadium Geometry

Place transparent-pass meshes in:

```text
std_trans
```

The scratch exporter also protects against a common imported-model problem where every vertex alpha value is accidentally zero.

If all alpha values for a transparent material are zero, the exporter treats that as missing alpha and restores opaque vertex alpha.

To preserve intentional zero alpha, set:

```text
nba_live_keep_zero_alpha = True
```

on the material.

---

# 4. Court Models

Courts support both:

- existing-EBO editing
- scratch package creation

Scratch courts are exported from:

```text
NBA Live > Stadium / Court EBO
```

Choose:

```text
Court
```

---

# Scratch Court Output

```text
<name>.ebo
<name>.fsh
<name>_vram.fsh
```

The normal court RMS is:

```text
NBACourt
```

Example:

```text
wood [NBACourt]
```

---

# Court Game Profiles

The tool contains dedicated profiles for:

```text
NBA Live 2005
NBA Live 06
```

The NBA Live 06 court format also works in NBA Live 07 and NBA Live 08.

Known Geometry-name references include:

```text
aalogo1Shape
ccskirt1Shape
floor4Shape
```

These are useful references, not mandatory names for scratch courts.

---

# 5. Backboard Models

The **Backboard EBO** panel handles the game's specialized weighted backboard format.

It supports:

- imported-backboard preparation
- rigid skin weighting
- donor weight transfer
- shot-clock material tagging
- shot-clock validation
- main EBO export
- full package export

---

# Main Backboard Objects

The main backboard requires:

```text
BaseBackboard
led
```

---

# Backboard Weight Groups

```text
Backboard_Support
Backboard_Board
Backboard_Rim
```

Bone mapping:

```text
Support -> 1
Board   -> 2
Rim     -> 3
```

Every vertex must have exactly one rigid weight at `1.0`.

---

# Backboard Package Collections

NBA Live 06-family:

```text
bbd
bbd_trans
bbd_refl
```

NBA Live 2005 additionally requires:

```text
bbd_shad
```

---

# Backboard Dynamic Clock

The native six-channel clock layout uses:

```text
time x4
tnum x2
```

Readable semantic names include:

```text
NBAShotClock_GameMinTens
NBAShotClock_GameMinOnes
NBAShotClock_GameSecTens
NBAShotClock_GameSecOnes
NBAShotClock_ShotClockOnes
NBAShotClock_ShotClockTens
```

The tool can tag and validate these automatically.

---

# Backboard Compatibility

The NBA Live 06 backboard package family also works in:

```text
NBA Live 07
NBA Live 08
```

---

# 6. Net Models

The **Net EBO** panel provides the verified NBA Live 06 weighted-net workflow.

Verified profile:

```text
Geometry: netShape
Texture: tnet
RMS: gNbaBackboardSkin_RMRuntime
```

---

# Net Weight Groups

```text
Net_TopAnchor
Net_Upper
Net_Body
Net_Bottom
```

Bone mapping:

```text
TopAnchor -> 0
Upper     -> 1
Body      -> 2
Bottom    -> 3
```

Every vertex must have one rigid weight at `1.0`.

---

# Stock Net Weight Recovery

The tool can automatically recover the stock NBA Live 06 five-ring layout:

```text
Top
Upper
Body
Body
Bottom
```

Use:

```text
Recover Stock 06 Net Weights
```

---

# Net Weight Transfer

A weighted donor net can transfer its semantic regions to a custom replacement mesh using nearest-vertex matching.

This allows a custom topology to be exported without manually assigning every vertex.

---

# Net Size Controls

The panel provides:

```text
Width Scale
Length Scale
```

The width is scaled around the net center.

The length is scaled downward while keeping the topmost ring vertically anchored.

---

# Net Export

The active mesh is compiled as:

```text
netShape
```

The current exporter expects exactly one used material.

---

# 7. Player / Coach Morph EBO

The **Player / Coach Morph EBO** panel handles supported player/body morph models.

This workflow is different from static stadium/court editing.

Player/body models depend on:

- a base model
- logical morph vertices
- rendered Geometry mappings
- stable topology and vertex order

---

# Player Morph Workflow

Typical sequence:

1. Load the correct base model.
2. Load the player/body morph EBO.
3. Edit mapped Blender Geometry.
4. Keep topology and vertex order unchanged.
5. Export the edited morph EBO.

The panel shows which Geometry targets are:

```text
mapped
visual/base only
modified by source morph
edited in Blender
```

---

# Important Player Morph Rule

Do not treat a player/body model like a freely rebuildable static stadium mesh.

Avoid:

- remeshing
- adding vertices
- deleting vertices
- destructive topology changes
- reordering the mesh

Direct vertex editing is the intended workflow.

---

# Reset Morph

The player morph panel can restore loaded Geometry back to the selected base model.

This is useful for restarting an edit without re-importing everything.

---

# 8. Jumbotron Materials

The Environment panel contains:

```text
Jumbotron Materials
```

and:

```text
Create Full Jumbotron Set
```

Choose one source material and the tool creates/appends the complete **69-channel** jumbotron material set to the active mesh.

---

# Shared Jumbotron Texture

All 69 jumbotron materials can share one atlas texture.

Example:

```text
jumbo [JumboHomeOnes]
jumbo [JumboAwayOnes]
jumbo [JumboPeriod]
jumbo [JumboHomeCourt1PointsOnes]
```

The texture remains:

```text
jumbo
```

while each material has a different RMS identity.

---

# Jumbotron Data Channels

The 69 channels cover:

- home score
- away score
- game clock
- shot clock
- period / OT
- home timeouts
- away timeouts
- home team fouls
- away team fouls
- five active home players
- five active away players
- player jersey number
- player points
- player fouls

---

# Jumbotron Runtime Requirement

The Blender/EBO tool creates the material definitions.

Live in-game values require the compatible **NBA Live Launcher/runtime plugin** that publishes the custom `Jumbo...` runtimes.

The EBO material alone does not supply live game data.

---

# 9. FBX Interchange

The Environment panel includes:

```text
Import NBA Live FBX
Export NBA Live FBX
```

Use FBX for:

- transferring decoded assets to another Blender project
- working in another 3D tool
- conversion workflows
- preserving Blender-readable geometry

FBX is an interchange feature, not a replacement for the specialized EBO exporters.

---

# 10. Transform Selector Diagnostics

Some imported skinned/specialized Geometry includes an:

```text
eagl_transform_selector
```

attribute.

When present, the Environment panel exposes:

```text
Visualize Transform Selectors
```

This creates a temporary diagnostic vertex-color layer so selector groups can be inspected visually in the 3D viewport.

This is useful when researching or editing specialized weighted Geometry.

---

# 11. Xbox Import

The **Xbox Import** panel supports import-only workflows for supported Xbox EA Sports VIV assets.

It can discover and import:

```text
std
std_trans
crt
bbd
bbd_trans
```

from supported Xbox VIV/BIG containers.

---

# Xbox Import Modes

Available choices include:

```text
Stadium
Stadium Transparent
Court
Backboard
Backboard Transparent
Stadium + Transparent
Backboard + Transparent
All Supported Arena Models
```

---

# Xbox XSH Textures

Enable:

```text
Extract XSH Textures
```

to decode supported Xbox XSH textures and assign them in Blender.

This includes support for the swizzled Xbox texture layouts handled by the current importer.

---

# Xbox Limitation

Xbox support is currently:

```text
IMPORT ONLY
```

The tool does not currently:

- export Xbox EBO
- rebuild Xbox XSH
- repack Xbox VIV

Imported Xbox models are marked accordingly in Blender.

---

# 12. Coordinate and UV Conversion

Supported EBO workflows automatically convert between NBA Live and Blender coordinate systems.

Users should normally work in standard Blender coordinates.

The importer/exporter also handles the game's vertical UV orientation.

For normal static workflows:

```text
V -> 1 - V
```

is handled automatically.

Do not manually apply the same conversion twice.

---

# 13. Vertex Colors

Supported environment assets preserve/import vertex colors where present.

The standard color attribute name is:

```text
NBA Live Vertex Colors
```

When building scratch geometry, the exporter can also use another compatible POINT/CORNER color attribute.

If no color layer exists, suitable static workflows default to opaque white.

---

# 14. Recommended First-Time Testing Procedure

For any existing model family:

1. Keep a backup of the original files.
2. Import an untouched asset.
3. Export without edits.
4. Test it in-game.
5. Make one small edit.
6. Export again.
7. Test again.
8. Only then make major changes.

This makes it much easier to identify the cause of a problem.

---

# 15. Which Panel Should Be Used?

## Existing court or stadium

Use:

```text
NBA Live Environments
```

## New stadium or court

Use:

```text
Stadium / Court EBO
```

## Backboard

Use:

```text
Backboard EBO
```

## Basketball net

Use:

```text
Net EBO
```

## Player/body morph

Use:

```text
Player / Coach Morph EBO
```

## Xbox source model

Use:

```text
Xbox Import
```

---

# 16. Documentation

For detailed instructions, use the model-specific documentation:

```text
Player_Body_Models_Documentation_End_User.md
Court_Models_Documentation_End_User.md
Backboard_Models_Documentation_End_User.md
Stadium_Models_Documentation.md
Net_Models_Documentation_End_User.md
```

These guides explain each workflow in more detail than this README.

---

# 17. Known Workflow Boundaries

The tool intentionally rejects files or edits when the required serializer/layout is not known safely.

Important examples:

- player/body morph topology should remain fixed
- net export currently expects one used material
- backboards require valid rigid semantic weights
- backboards require the full six-channel native clock contract
- Xbox support is import-only
- unfamiliar or unsupported RMS layouts may be rejected
- custom jumbotron materials require the matching runtime plugin in-game

An export error is preferable to writing a structurally unsafe EBO.

---

# 18. Recommended Project Backups

Before editing, keep copies of:

```text
original EBO
original FSH
original _vram FSH
original reflection/shadow files
Blender .blend
edited PNG textures
```

For difficult bugs, these files make it much easier to compare a working asset against the edited result.

---

# Quick Start — Existing Stadium/Court

```text
1. Import NBA Live EBO
2. Extract FSH textures
3. Edit mesh / UV / materials
4. Enable Repack FSH on Export if textures changed
5. Export NBA Live EBO
6. Test in-game
```

# Quick Start — Scratch Stadium

```text
1. Create std + std_trans collections
2. Add meshes
3. Assign texture [RMS] materials
4. Connect PNG images
5. Select meshes
6. Stadium / Court EBO > Stadium
7. Export Stadium Package
```

# Quick Start — Scratch Court

```text
1. Build/select court meshes
2. Assign texture [NBACourt]
3. Stadium / Court EBO > Court
4. Choose game profile
5. Export Court Package
```

# Quick Start — Backboard

```text
1. Prepare BaseBackboard + led
2. Create/validate rigid weights
3. Tag/validate shot clock
4. Export main EBO or full package
```

# Quick Start — Net

```text
1. Import stock net or custom replacement
2. Recover/transfer/assign weights
3. Validate
4. Adjust width/length if needed
5. Export Net EBO
```

# Quick Start — Player Morph

```text
1. Load base model
2. Load morph EBO
3. Edit mapped vertices
4. Keep topology unchanged
5. Export morph EBO
```

---

# Summary

NBA Live Environment Tools provides one Blender-based workflow for the major EBO model families used by the NBA Live 2005–08 generation.

The add-on can:

- decode existing NBA Live assets
- preserve and rebuild static Geometry
- generate scratch courts and stadiums
- build specialized backboard packages
- export weighted nets
- edit player/body morph models
- manage native FSH textures
- create the full jumbotron material system
- exchange geometry through FBX
- import supported Xbox arena assets

Users should begin with the relevant model-specific guide and always test a no-edit round trip before making major changes.
