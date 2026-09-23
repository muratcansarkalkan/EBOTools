# NBA Live Environment Tools v1.5

Combined Blender add-on for importing, editing, and exporting NBA Live
environment/static EBO models and FSH textures across 2005-08, plus the supported
2005/06 player-head workflows.

Keep backups of original game files and test exported assets individually in-game.

## Supported workflows

- NBA Live 2005/06 high-detail player head EBO models
- Player-head vertex-position editing with original EA vertex IDs preserved
- Player-head source-file verification and overwrite protection
- NBA Live 2005-08 court and stadium EBO models
- Transparent stadium parts
- Adding, renaming, and removing stadium EBO material groups
- Adding new stadium texture names
- Selecting the main or `_vram` FSH archive for each new texture
- Championship trophy and NBA Live 2005/06 ball models
- Main, transparent, reflection, shadow, and playground backboard variants
- Existing vertex-position and UV editing
- Topology rebuilding for decoded static court and stadium geometry
- Native main and `_vram` FSH extraction and repacking
- Slot-qualified FSH names such as `texture0:ball`
- Automatic RGB-to-RGBA PNG conversion before FSH packing
- Automatic placeholder PNGs when textures or archives cannot be resolved

## Installation

Install the extension through **Edit > Preferences > Add-ons > Install from
Disk**, then enable **NBA Live EBO Tools**.

The Player / Coach Morph EBO workflow asks you to choose the base EBO directly.
No base EBO files are bundled with the add-on.

The tools appear under the **NBA Live** tab in the 3D Viewport sidebar.

## Player heads

Use the **EBO Head Tools** panel:

1. Select NBA Live 2005 or NBA Live 2006.
2. Import the original player head EBO.
3. Move existing vertices in Blender.
4. Export to a new EBO filename.

The imported mesh remembers its game version, original player EBO, source-file
hash, base model, original EA vertex IDs, and original vertex positions.

Player heads are deliberately fixed-topology:

- NBA Live 2005 requires 734 rendered vertices and uses a sparse coordinate
  morph stream.
- NBA Live 2006 requires 733 rendered vertices and uses a dense coordinate
  morph stream.
- Do not add, delete, merge, subdivide, or reorder head vertices.
- Export never overwrites the original player EBO.
- NBA Live 2005 edits that require expanding an omitted sparse coordinate are
  rejected instead of resizing and corrupting the file.

## Importing an EBO

1. Keep the EBO beside its corresponding `.fsh` and `_vram.fsh` files, or set
   their directory in the import panel.
2. Enable **Extract FSH on Import** when the PNG files have not already been
   extracted.
3. Import the EBO.
4. Edit the imported objects, UV maps, supported geometry, or materials.

Do not delete or rename imported Blender objects. Their names identify the
original EBO geometry records during export.

If an FSH archive is absent, invalid, unsupported, or missing a required
texture, import continues with a 64×64 magenta-and-black placeholder PNG. The
placeholder is placed in the normal extracted-texture directory and attached
to the Blender material. Existing PNG files are never overwritten.

When the FSH directory supplies a slot-qualified name, the placeholder keeps
its safe working filename. For example, `texture0:ball` becomes
`texture0-ball.png`.

## EBO material naming

Imported materials use:

```text
EBO.<texture> [<RMS type>]
```

Examples:

```text
EBO.gcon [TextureStadium]
EBO.odrn [ScrollTextureDim]
```

The text before the brackets is the texture name. The bracketed text is the
RMS render-method type; it is not another texture name. The `EBO.` prefix is
optional for the bracketed form, so `jumbo [JumboHomeOnes]` is valid too.

Texture names are now independent from material/runtime identity. Several
material rows may intentionally share one FSH texture as long as their RMS
types differ. For example, all jumbotron channels can use one atlas:

```text
jumbo [JumboHomeHundreds]
jumbo [JumboHomeTens]
jumbo [JumboHomeOnes]
jumbo [JumboAwayHundreds]
jumbo [JumboAwayTens]
jumbo [JumboAwayOnes]
jumbo [JumboGameMinTens]
jumbo [JumboGameMinOnes]
jumbo [JumboGameSecTens]
jumbo [JumboGameSecOnes]
jumbo [JumboShotTens]
jumbo [JumboShotOnes]
jumbo [JumboPeriod]
jumbo [JumboHomeTimeouts]
jumbo [JumboAwayTimeouts]
jumbo [JumboHomeTeamFoulsTens]
jumbo [JumboHomeTeamFoulsOnes]
jumbo [JumboAwayTeamFoulsTens]
jumbo [JumboAwayTeamFoulsOnes]
```

The extended active-five channels follow the same pattern and can share the
same atlas too, for example:

```text
jumbo [JumboHomeCourt1NumberTens]
jumbo [JumboHomeCourt1NumberOnes]
jumbo [JumboHomeCourt1PointsTens]
jumbo [JumboHomeCourt1PointsOnes]
jumbo [JumboHomeCourt1Fouls]
jumbo [JumboAwayCourt5NumberTens]
jumbo [JumboAwayCourt5NumberOnes]
jumbo [JumboAwayCourt5PointsTens]
jumbo [JumboAwayCourt5PointsOnes]
jumbo [JumboAwayCourt5Fouls]
```

This naming pattern covers court slots 1-5 for both home and away teams.

When **Repack FSH on Export** is enabled, the shared `jumbo` PNG is packed
once. Old texture names that were explicitly renamed to `jumbo` are omitted
from the rebuilt archive when no final material still references them. The
vertical UV position remains authored in Blender, so different font rows can
share the same atlas while the game plugin changes only the horizontal digit
cell.

For a new stadium material, create a normal Blender material, give it an EBO
name, and assign at least one face. A readable RMS-type form is accepted:

```text
EBO.new0 [TextureStadium]
```

The explicit form selects both a template and destination archive:

```text
EBO.<new texture>.<template texture or RMS type>.<main|vram>
```

Examples:

```text
EBO.new0.TextureStadium.main
EBO.animated_ad.ScrollTextureDim.vram
```

The template may be an existing texture/material-group name on that object or
an RMS type shown in brackets.

Removing every face assigned to an original stadium material removes that
material group during export, provided the object retains at least one
original material group.

## FSH textures

Enable **Repack FSH on Export** to rebuild the asset's archives.

- Main and `_vram` textures are staged separately.
- `:` is replaced with `-` only in working PNG filenames and restored inside
  the repacked archive.
- RGB PNG files are converted to opaque RGBA before FSH packing.
- Each archive is rebuilt from a filtered temporary directory, preventing
  stale PNGs from leaking between main and `_vram` archives.
- Placeholder PNGs may be replaced normally before repacking.

## Specialized models

Balls, trophies, backboards, reflection models, and shadow models contain
specialized runtime and serializer data beyond ordinary static stadium
geometry.

For these models, the add-on currently supports only fixed-topology edits:

- Move existing vertices
- Edit existing UV coordinates
- Preserve the original objects, material groups, vertex counts, and faces

Adding, deleting, or rewiring vertices/faces is deliberately rejected before
an EBO is written. Experimental additive backboard rebuilds either rendered
distorted geometry or crashed NBA Live, even when their visible stream data
and known serializer pointers validated. They are therefore not part of this
release.

Backboard formats confirmed for fixed-topology import/export include normal,
transparent, reflection, shadow, shot-clock, and playground declaration
variants. Playground backboards may use declaration variant `3`; this is a
normal-bearing geometry declaration, not confirmed skeletal weight data.

### Backboard transform-selector diagnostics (0.6.1)

When a specialized descriptor contains a self-validating per-vertex `i16`
local-palette selector, the importer now exposes it as the POINT-domain integer
attribute `eagl_transform_selector`. The corresponding local palette size is
exposed as `eagl_palette_size`. Detection is conservative: the array is accepted
only when it contains exactly one readable value per vertex and every selector
is smaller than the declared palette size. This makes the previously hidden
backboard companion stream inspectable in Blender without changing the stable
fixed-topology writer.

Topology-changing export remains disabled in this release. The new attributes
are diagnostic groundwork for a future writer that can rebuild selector data
safely instead of producing structurally plausible but invalid backboards.

## Current limitations

- Creating completely new named EBO objects is unsupported.
- Specialized-model topology changes are unsupported.
- Existing supported FSH archives and synthetic package output are handled natively.
- Player accessory import/export is not included in this release.
- Unfamiliar EBO or RMS layouts may be rejected rather than exported unsafely.

## Recommended testing sequence

1. Choose the matching game version and import an untouched model.
2. Export without edits.
3. Confirm that it loads in-game.
4. Make one small UV edit and test again.
5. Make one small vertex-position edit and test again.
6. For static courts/stadiums only, proceed to material or topology changes.

If a model fails, retain the original EBO, exported EBO, relevant FSH files,
the `.blend` file, and the exact Blender material names used.

## Suggested next research target

The current environment workflow no longer requires GX for supported FSH extraction/repacking.

### 0.6.1 backboard selector work

- Adds **Visualize Transform Selectors** in the NBA Live sidebar when the active imported mesh contains `eagl_transform_selector`. It creates a temporary point-color diagnostic layer and switches the 3D viewport to vertex colors so local selector groups can be seen directly on the model.
- Specialized additive topology export now carries `eagl_transform_selector` into rebuilt EBO data, validates every value against the material's `eagl_palette_size`, grows the raw i16 selector stream with the vertex stream, relocates its descriptor pointer, and verifies the rebuilt selector stream by reparsing the finished EBO.
- Selector value is part of export vertex identity, preventing Blender UV/color splitting from accidentally merging vertices that have different transform assignments.
- If a selector-bearing material is exported without the selector attribute, or contains an out-of-range selector, export aborts instead of writing a potentially crashing EBO.


### 0.6.2 experimental arbitrary backboard topology

- Removes the appended-faces-only restriction for specialized backboard batches.
- Extrusion, deletion and face rewiring are accepted for controlled testing.
- Rebuilds the current triangle strip from Blender geometry.
- Rebuilds position, normal, UV, index and detected transform-selector payloads.
- Supports stream growth/shrinkage while relocating the known serializer pointers.
- Selector-bearing materials still require a valid `eagl_transform_selector` on every output vertex.
- This remains experimental: test on copies and start with a very small extrusion.


### 0.6.3 specialized topology test routing fix

0.6.2 contained the generalized specialized-topology rebuilder but the public
`rebuild_from_batches()` entry point still had the older safety gate, so Blender
never reached the new code. 0.6.3 removes that stale gate:

- unchanged specialized topology -> conservative in-place patcher;
- changed specialized topology -> selector-aware `_rebuild_specialized_topology()`;
- static-color geometry -> existing static topology writer.

This is still an experimental backboard topology path.


### 0.7.0-alpha.1 strip-preserving topology experiment

- Additive specialized edits preserve EA's original triangle strip exactly and append only new faces.
- Destructive/rewired edits use adjacency-connected strip runs rather than rebuilding every face as an isolated strip.
- Degenerate bridges are inserted only when another triangle cannot continue the current strip edge.
- Selector-aware specialized stream rebuilding from 0.6.3 remains enabled.
- This specifically targets the excessive index-strip growth observed in the crashing topology test.


## 0.7.0-alpha.1 generic descriptor work

The importer now recognizes skinned Geometry from the serialized buffer structure
(position/normal/UV/index headers and strides) instead of limiting palette counts
to a few known backboard signatures. Vertex and primitive counts are derived from
the actual PC vertex/index buffer lengths when parsing these descriptors.

This expands import coverage to the tested NBA Live 2005/2006 face LOD, net, and
2005 backboard samples while retaining the existing 0.6.6 topology/relocation
work. Export of newly discovered model families should still be treated as
experimental until each family's serializer semantics are validated in game.


## 0.7.0-alpha.2 frontend Geometry research

- Adds structural recognition for APT/frontend Geometry using position (12-byte), Colour (4-byte), and index (2-byte) PC buffers.
- Tested parser coverage now includes `score.ebo`, `slctjrsy.ebo`, `lc_l.ebo`, and `ANNOCIO.ebo`.
- Handles the observed compound frontend material record sufficiently to import its first structural draw without asset-name special cases.
- Frontend UV placement remains RenderMethod-driven; these descriptors do not carry the ordinary 8-byte UV buffer used by stadium/backboard geometry.
- Existing 2005/2006 face, net, backboard and stadium parser regressions remain covered.
- `dunkstd` research samples expose TextureStadium, TextureGlow (2005), TextureScaleOffsetUV, and ScrollTextureDim RenderMethods; no special parser branch was added for them.

Frontend export should be treated as experimental until RenderMethod-driven frontend placement and compound-draw serialization are fully mapped.


## 0.7.0-alpha.8 structural descriptor metadata

Exporter-side descriptor fields are now carried by each parsed batch as structural
metadata (PCData, count, primitive, palette and selector word positions) instead of
being recovered from a profile-name switch. This keeps binary relocation/rebuild
logic independent from model names and RenderMethod labels.

Frontend position and BGRA colour streams can now be patched safely when topology is
unchanged. Frontend topology growth is deliberately rejected until its serializer
registration is mapped; existing skinned/topology-capable representations retain the
0.6.6 relocation path. Stadium TextureGlow, TextureScaleOffsetUV and ScrollTextureDim
samples remain ordinary static Geometry and are included as regression material.


## 0.7.0-alpha.8 frontend topology fix

Frontend `Position + Colour + Index` descriptors now discover their PCDataBuffers
field structurally. Compound frontend draw records can place this pointer at
different descriptor words, so it is no longer selected from a profile-name map.
Frontend vertex-count and primitive-count fields are recorded directly from the
descriptor. This removes the `FRONTEND_COLOR` topology-rebuild KeyError and lets
the generic relocation path operate on frontend stream growth.

Frontend colour streams remain BGRA byte streams and are rebuilt alongside
positions and indices.


## 0.7.0-alpha.8 outer serializer discovery

Topology rebuilding now locates each Geometry export's outer relocation serializer
from the type-1 EBO chunk that actually contains that Geometry object. Frontend
EBOs commonly store successive Geometry exports in separate phase-0 chunks, so
the older backboard-derived method of chaining from the previous PCData end was
invalid for files such as score.ebo.

A synthetic frontend topology-growth regression (21 -> 24 vertices, 11 -> 12
triangles) now rebuilds and reparses successfully.


## 0.7.0-alpha.8 frontend strip/color probe

Frontend additive topology now joins adjacent new triangles into compact triangle-strip
runs before bridging them to the original EA strip. This avoids the backboard-oriented
five-index bridge for every added face. Vertex-color extraction was also corrected so
RebuiltBatch keeps RGBA and the EBO writer performs the single required BGRA conversion.


## 0.7.0-alpha.8 frontend topology encoding

The alpha.6 compact append path could be bypassed when Blender re-ordered or
re-oriented imported triangles, causing fallback to the older per-triangle
backboard strip builder. Frontend topology changes now always rebuild all
triangles into compact connected strip runs. Fixed-topology frontend exports
continue preserving the original EA strip byte-for-byte.


## 0.7.0-alpha.8 — Morph groundwork

Adds `morph_probe.py`, a read-only structural probe for the next generalized
morph workflow. It accepts an arbitrary base LOD EBO plus a player morph EBO,
uses the existing generic Geometry parser for the base, inventories Morph
exports, and locates known MorphStreamHeader records without hard-coding a
year, LOD, player name, or vertex count.

Target workflow under implementation:
1. Load base_lodB/C/D EBO.
2. Load a matching player/body morph EBO.
3. Decode logical morph streams and map them onto rendered Geometry vertices.
4. Edit the displayed morphed mesh in Blender.
5. Collapse edited render copies back to logical morph vertices.
6. Rewrite the original morph EBO while leaving the base EBO unchanged.

The older head editor remains intact in this alpha; the generalized body-morph
UI is not enabled until the render-to-logical mapping and sparse stream writer
validate across the supplied 2005/2006/2008 corpus.


## 0.7.0-alpha.10 — Named morph target pairing

The morph layer now inventories every `Morph` export in the selected partial
morph EBO and maps `<target>_morphs` to Geometry `<target>` in the selected
`base_lodX.ebo`. Missing targets are intentionally left as unchanged base
geometry.

Examples include `BasePlyr_morphs -> BasePlyr`, `headAShape_morphs ->
headAShape`, `jerseyShape_morphs -> jerseyShape`, and `shortsShape_morphs ->
shortsShape`.

This alpha keeps the proven BasePlyr editor/export path active while exposing
the complete target inventory needed to bind the remaining targets to their
individual MorphStreamHeaders and EA render-to-logical mappings. It does not
silently apply an unmatched stream to BasePlyr.


## 0.7.0-alpha.13 — EA per-batch morph mappings

BasePlyr no longer relies on position deduplication when the shipped base EBO
provides EA's mapping records. The mapping representation can cover an entire
Geometry target (such as 734->573 head shapes) or individual render batches.

Confirmed examples:
- 2005 BasePlyr: 144 + 506 render vertices -> 592 logical vertices.
- 2006 BasePlyr: 144 + 144 + 583 -> 798 logical vertices.
- 2008 BasePlyr: 144 + 144 + 578 -> 798 logical vertices.

The per-batch tables collectively cover every logical index exactly once
(allowing expected render duplicates). The importer reports
`APPLIED [EA_BATCH_TABLES]` when this authoritative path is used.


## 0.7.0-alpha.15 — Sparse morph repacking

Fixed-topology export can now move a coordinate that was omitted by the source
sparse morph. The writer reassigns EA's existing explicitly-stored zero slots,
rebuilds the sparse instruction mask, and rewrites it in place while preserving
the original MorphData allocation. No EBO relocation is required for ordinary
vertex edits that fit the source stream's fixed sparse capacity.

Regression-tested by deliberately editing omitted BasePlyr components in the
supplied 2005 Oliver Miller, 2005 skinny, and 2008 Badavis morphs. All rendered
copies belonging to the edited logical vertex were moved together, then the
morph was exported and re-imported; all three round trips reproduced the edit.


## Xbox VIV Import (Experimental, Import Only)

The Blender addon can import Xbox EA Sports arena assets directly from a
`.viv`/BIGF archive. This path is intentionally **import only**; it does not
export or repack Xbox EBO/XSH data.

In the **NBA Live > Xbox Import** panel choose **Import Xbox VIV**, then select:

- **Stadium (std)** to import the archive's `*std.ebo`
- **Court (crt)** to import the archive's `*crt.ebo`
- **Stadium + Court** to import both

The importer currently preserves/imports:

- Geometry object names
- Material groups
- Triangle-strip stadium/court geometry
- Xbox court-line geometry as Blender edges
- UV coordinates
- BGRA vertex colors
- RMS runtime labels
- XSH texture names and automatic Blender material assignment
- DXT1/DXT3/DXT5 Xbox textures
- Xbox swizzled P8 textures with BGRA palettes

Xbox VIV members are RefPack-decoded in memory. Extracted PNG files are placed
beside the VIV under `nba_live_xbox_textures/<viv>/<asset>/`.

Current validation samples:

- NBA Live Xbox: Atlanta `atla_xb.viv`
- NCAA March Madness 06 Xbox: `scal.viv`

The same importer handles both tested games because they use the same EBO v17 /
RMS-family architecture.

Some unusual XSH formats outside the tested DXT and P8 cases may currently
fall back to placeholder textures. Such a texture does not prevent the model
from importing.


### v1.5.2 Xbox import notes

Xbox import now supports:

- `*std.ebo`
- `*std_trans.ebo`
- `*crt.ebo`
- `*bbd.ebo`
- `*bbd_trans.ebo`

The court importer intentionally ignores Xbox descriptor-type-2 source line
records. The corresponding rendered `*ShapeGeo` geometry is already present
as ordinary type-6 geometry; importing both caused duplicate black line
"spider web" geometry in Blender.

Backboard imports support the tested Xbox normal-bearing stream layout
(position + UV + normal + skin/auxiliary data + triangle-strip indices).
Xbox export remains intentionally unsupported.
