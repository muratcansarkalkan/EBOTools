# NBA Live Environment Tools v1.5

Blender add-on for editing and creating NBA Live 2005 / NBA Live 06 PC EBO assets and their related FSH textures.

The tools are available in the **NBA Live** tab of the Blender 3D Viewport sidebar. All main panels are collapsed by default.

## Requirements

- Blender 4.2 or newer
- NBA Live 2005 or NBA Live 06 PC assets
- Original game files should always be backed up before editing

No GX/Gimex installation is required. FSH extraction, decoding, creation, and repacking are handled natively by the add-on.

## Installation

1. Open Blender.
2. Go to **Edit > Preferences > Add-ons**.
3. Choose **Install from Disk**.
4. Select the NBA Live Environment Tools ZIP.
5. Enable **NBA Live Environment Tools**.
6. Open the 3D Viewport sidebar and select the **NBA Live** tab.

## Included tools

The add-on is organized into five main panels:

- **NBA Live Environments** — import and export existing court, stadium, and compatible EBO models; manage related FSH textures; FBX bridge.
- **Stadium / Court EBO** — create new stadium and court EBO/FSH packages from Blender geometry.
- **Backboard EBO** — edit or build NBA Live 2005 / 06 backboard packages, including rigid weights and dynamic shot-clock materials.
- **Net EBO** — edit and export the NBA Live 06 weighted net model.
- **Player / Coach Morph EBO** — load a user-selected base player/coach EBO, apply a morph EBO, edit it in Blender, and export the result.

---

# Existing EBO import / export

Use **NBA Live Environments** for existing court, stadium, transparent stadium, and other compatible EBO assets.

## Import

1. Set the FSH/archive directories if required.
2. Enable **Extract FSH on Import** if PNG textures have not already been extracted.
3. Choose **Import NBA Live EBO**.
4. Edit the imported mesh, UVs, vertex colors, and supported material assignments.

The importer preserves the structural metadata required to rebuild supported EBO geometry.

### Important

Do not casually rename or delete imported objects. Their stored metadata and object identity may be required during export.

For model families with specialized serializer data, preserve the source structure unless the dedicated tool explicitly supports rebuilding it.

## Export

Choose **Export NBA Live EBO** from the same panel.

Enable **Repack FSH on Export** when edited PNG textures should be written back into the corresponding FSH archives.

The exporter is designed to reject unsupported or structurally unsafe changes rather than silently produce a damaged EBO.

---

# FSH texture support

FSH handling is native. GX/Gimex is no longer used.

## Native extraction formats

The current decoder supports:

- DXT1 / `0x60`
- DXT3 / `0x61`
- DXT5 / `0x62`
- ARGB4444 / `0x6D`
- RGB565 / `0x78`
- BGRA32 / `0x7D`
- ARGB1555 / `0x7E`
- BGR24 / `0x7F`

Unsupported indexed or unfamiliar FSH formats are reported instead of being decoded incorrectly.

## Native creation

New textures are encoded as:

- **DXT1** when the PNG is fully opaque
- **DXT5** when the PNG contains non-opaque alpha

Some specialized assets may use a dedicated DXT3 path where required by their known game format.

## Working PNG filenames

FSH TextureNames are preserved internally. Characters that are inconvenient in filenames, such as `:`, may be converted to a safe working filename while extracted and restored when the archive is rebuilt.

If a required texture cannot be resolved during import, the add-on may create a visible placeholder texture so the model can still be inspected in Blender.

---

# EBO material naming

Material names carry the texture name and, where applicable, the RenderMethod/RMS type.

Typical imported form:

```text
EBO.<texture> [<RMS type>]
```

Examples:

```text
EBO.gcon [TextureStadium]
EBO.odrn [ScrollTextureDim]
```

For environment editing, the text before the brackets is the FSH TextureName. The value in brackets identifies the RenderMethod profile.

When creating new environment material groups, the extended form can also specify the template and destination archive:

```text
EBO.<new texture>.<template texture or RMS type>.<main|vram>
```

Examples:

```text
EBO.new0.TextureStadium.main
EBO.animated_ad.ScrollTextureDim.vram
```

Use an existing known-good material/RMS as the template whenever possible.

---

# Stadium / Court EBO creator

Use **Stadium / Court EBO** to create new static packages from Blender meshes.

## Stadium

Expected collection roles are:

```text
std
std_trans
std_highref   (optional reflection collection)
```

Select the meshes that should be exported and choose **Stadium** mode.

The exporter creates the EBO and associated native FSH files from the selected Blender geometry and materials.

### Stadium material syntax

Use:

```text
texture [RMS]
```

Example:

```text
0036 [ScrollTextureDim]
```

Supported RMS profiles are derived from the tool's known NBA Live RenderMethod definitions.

## Court

Choose **Court** mode and select NBA Live 2005 or NBA Live 06.

Known working court Geometry names include:

```text
aalogo1Shape
ccskirt1Shape
floor4Shape
```

These names are warnings/recommendations, not destructive automatic requirements. The add-on does not rename your geometry automatically.

The default court RenderMethod is the appropriate NBA court profile for the selected game.

---

# Backboard EBO

The dedicated **Backboard EBO** panel supports NBA Live 2005 and NBA Live 06 backboard workflows.

Backboards contain game-specific skinning, serializer, shot-clock, reflection, transparency, and material behavior. Do not assume a 2005 backboard can be used as a 2006 template or vice versa.

## Existing backboard

For an imported working backboard:

1. Enable **Backboard Mode**.
2. Select the correct game.
3. Use **Prepare Imported Backboard** when needed.
4. Preserve the existing Geometry/material structure unless intentionally rebuilding it.
5. Export with a matching reference EBO when the workflow requires one.

## Rigid backboard weights

The tool uses semantic rigid groups:

```text
Support  -> bone 1
Board    -> bone 2
Rim      -> bone 3
```

The panel provides tools to create, assign, transfer, preserve, and validate these weights.

## Dynamic shot clock

The tool supports the six dynamic shot-clock materials used by the backboard:

- four `time` materials
- two `tnum` materials

The dedicated tagging and validation tools assign the expected UV indices and Board ownership.

## Backboard package export

NBA Live 06 package collections:

```text
bbd
bbd_trans
bbd_refl
```

NBA Live 2005 additionally requires:

```text
bbd_shad
```

The package exporter can create the model set and associated FSH archives.

## ScrollTextureDim

Backboard materials may use the same bracketed RMS convention as stadium materials.

Example:

```text
odrn [ScrollTextureDim]
```

This exports the material with:

```text
gScrollTextureDim_RMRuntime
```

Shot-clock-specific materials retain their required game-specific runtime and take precedence over the generic tag.

---

# Net EBO

The **Net EBO** panel currently targets the NBA Live 06 weighted basketball net.

The workflow supports:

- recovering stock net weights
- creating semantic net groups
- assigning Top / Upper / Body / Bottom regions
- transferring and validating rigid weights
- width and length scaling
- exporting the rebuilt `netShape`

The known texture name is `tnet` and the exporter uses the NBA Live 06 net/backboard skin runtime expected by the game.

---

# Player / Coach Morph EBO

This workflow does not use bundled base models.

The user selects the correct **base EBO** directly in the **Player / Coach Morph EBO** panel.

Typical workflow:

1. Choose **Base Model** and select the correct original player/coach EBO.
2. Load the morph/source EBO.
3. Edit the loaded geometry directly in Blender.
4. Keep topology and vertex order unchanged.
5. Export the edited morph EBO.

The panel reports which Geometry objects are mapped, which source Geometry contains morph data, and which objects have been edited in Blender.

### Important limitations

- Keep vertex order unchanged.
- Do not add/delete/reorder vertices unless a particular workflow explicitly supports it.
- Player accessory import/export is intentionally not included in v1.5.

---

# FBX bridge

The **NBA Live Environments** panel also exposes Blender's FBX import/export as a convenience when moving geometry through an external modeling workflow.

FBX does not replace the EBO metadata stored by the native importer. When editing an existing NBA Live asset, preserve the original imported collection and metadata needed for final EBO export.

---

# Vertex colors, UVs, transparency, and topology

For supported environment/static Geometry, the tools preserve and rebuild the data needed by the tested NBA Live EBO formats, including:

- positions
- normals where present
- UV coordinates
- vertex colors where present
- material groups
- triangle/index data
- transparent geometry
- known descriptor and relocation metadata

Topology changes are supported where the relevant model family has a validated rebuild path. Specialized/skinned model families may impose stricter rules.

When the exporter rejects a topology or serializer change, treat that as a safety check rather than bypassing it.

---

# Transform-selector diagnostics

Some skinned/specialized EBO Geometry contains a per-vertex transform selector used with a local bone palette.

When available, the importer exposes this information as Blender metadata and the **Visualize Transform Selectors** operator can color the mesh by selector group for inspection.

This is primarily a diagnostic feature for specialized models and should not be treated as a generic material/color layer.

---

# Recommended workflow

For an unfamiliar model:

1. Keep an untouched backup of the original EBO and FSH files.
2. Import the model.
3. Export it once without edits.
4. Test the untouched round-trip in-game.
5. Make one small change at a time.
6. Test again before making larger topology or material changes.

For known supported creators such as stadiums, courts, backboards, and the NBA Live 06 net, use the dedicated panel rather than forcing the asset through a generic workflow.

---

# Known limitations

- The primary tested game targets are NBA Live 2005 and NBA Live 06 PC.
- Player accessory import/export is not included.
- Some uncommon/paletted FSH formats are not yet decoded natively.
- Unknown EBO descriptor or serializer layouts may be rejected.
- Specialized model families can have stricter topology/weight requirements than ordinary static environment Geometry.
- Game memory limits are outside the scope of this Blender add-on. A structurally valid large EBO/FSH package can still exceed NBA Live's runtime memory limits.

---

# Troubleshooting

## Model imports but textures are missing

Check that the relevant `.fsh` and `_vram.fsh` archives are available and that the archive/texture directories in **NBA Live Environments** point to the correct location.

## Exported model crashes the game

First test an untouched import/export round-trip. If that works, reapply edits incrementally. Large textures and large model packages can also hit game-side memory limits even when the exported file itself is structurally valid.

## Material does not use the expected effect

Check the material name and RMS tag. For example:

```text
odrn [ScrollTextureDim]
```

is different from a normal stadium texture using `TextureStadium`.

## FSH format is reported unsupported

Keep the original FSH file. The native decoder deliberately stops on unknown formats instead of guessing and producing incorrect textures.

---

# v1.5 release notes

v1.5 is the cleaned release of the combined NBA Live EBO/environment toolset.

Highlights:

- consolidated environment, stadium/court, backboard, net, and player/coach workflows
- native FSH extraction and repacking
- no GX/Gimex dependency
- native FSH generation for new packages
- cleaned package with obsolete experimental modules and bundled base models removed
- player accessories intentionally removed from the release workflow
- all main NBA Live sidebar panels collapsed by default
- backboard `ScrollTextureDim` material support
- current stable static-model, UV, vertex-color, transparency, material, topology, weight, and morph workflows retained

