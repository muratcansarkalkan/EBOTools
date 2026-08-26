# NBA Live EBO Tools v0.5.0 Alpha

Combined Blender add-on for importing, editing, and exporting selected NBA
Live 2005 and NBA Live 06 player heads, environment/static EBO models, and FSH
textures.

This remains an alpha release. Keep backups of every original game file and
test exported assets individually in-game.

## Supported workflows

- NBA Live 2005/06 high-detail player head EBO models
- Bundled 2005 and 2006 head base models
- Player-head vertex-position editing with original EA vertex IDs preserved
- Player-head source-file verification and overwrite protection
- NBA Live 2005/06 court and stadium EBO models
- Transparent stadium parts
- Adding, renaming, and removing stadium EBO material groups
- Adding new stadium texture names
- Selecting the main or `_vram` FSH archive for each new texture
- Championship trophy and NBA Live 2005/06 ball models
- Main, transparent, reflection, shadow, and playground backboard variants
- Existing vertex-position and UV editing
- Topology rebuilding for decoded static court and stadium geometry
- Main and `_vram` FSH extraction and repacking through `gx.exe`
- Slot-qualified FSH names such as `texture0:ball`
- Automatic RGB-to-RGBA PNG conversion before GX packing
- Automatic placeholder PNGs when textures or archives cannot be resolved

## Installation

Install the extension through **Edit > Preferences > Add-ons > Install from
Disk**, then enable **NBA Live EBO Tools**.

Set **GX Executable** in the add-on preferences. The path is stored once and
reused during later imports and exports.

The required player-head templates, `base_lodB_05.ebo` and `base_lodB.ebo`,
are included in the add-on. The preferences contain optional overrides for
research or testing with another compatible base.

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

If an FSH archive is absent, invalid, unsupported by GX, or missing a required
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
RMS render-method type; it is not another texture name.

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
- RGB PNG files are converted to opaque RGBA before GX packing. This prevents
  GX from producing the incompatible `0x7F` format instead of `0x7D`.
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

## Current limitations

- Creating completely new named EBO objects is unsupported.
- Specialized-model topology changes are unsupported.
- Native FSH encoding/decoding is not implemented; GX is still required.
- Nets and player accessories such as goggles, headbands, and hair need
  further sample-based research.
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

The recommended next milestone is native FSH unpacking and repacking. Removing
or reducing reliance on GX would improve every supported asset class and is a
more contained next step than specialized EBO topology reconstruction.
