# NBA Live EBO Tools

Blender tools and reverse-engineering utilities for working with EA Sports NBA Live PC `.ebo` models.

The project currently targets **NBA Live 2005, NBA Live 06, and NBA Live 08** and is being developed against Blender 5.x. It grew from a fixed-topology EBO importer/exporter into a broader toolkit for PC EBO geometry, specialized models, frontend assets, and player morphs.

> **Status:** Research / alpha software. Keep backups of original game assets.

## Current version

**0.7.0-alpha.15**

This is not a finished general-purpose EBO compiler yet. The capabilities below are based on formats and workflows that have been tested during development.

## What works

### General EBO geometry

EBO Tools can parse and import a growing range of NBA Live PC Geometry EBOs instead of relying only on individual asset-name profiles.

Current work includes:

- EBO v17 file/header parsing.
- Chunk and TOC parsing.
- Export/string table parsing.
- PC Geometry discovery.
- PC vertex and index buffer discovery.
- Position, normal, UV, index, and color stream handling where structurally available.
- Multiple Geometry objects inside one EBO.
- Multiple render batches/material sections.
- Structural descriptor detection across different EBO layouts.

The importer is intended to discover structures from the file rather than maintain a large list of hard-coded model names.

### Fixed-topology model editing

For supported models, existing geometry can be imported into Blender, edited, and written back while preserving the model's required structure.

The most reliable rule is:

**Move or modify existing vertices; do not assume arbitrary topology changes are supported.**

### Specialized topology editing

Topology growth inside already-existing specialized batches has been demonstrated for supported assets, including backboard work.

The serializer can update affected stream data, counts, offsets, TOCs, and relocation-sensitive data for the supported cases.

This does **not** yet mean EBO Tools can create an arbitrary new render batch or material section.

### Backboards

Backboard EBO work includes NBA Live 2005/06-era format differences and specialized stream handling.

Supported/researched capabilities include:

- Geometry import.
- Texture/UV editing.
- Existing material usage.
- Vertex editing.
- Topology growth inside existing supported batches.
- Specialized transform-selector/palette data preservation.

Creating a completely new independent backboard material/render batch remains outside the proven feature set.

### Frontend EBOs

Frontend/APT-related EBO Geometry can be structurally imported.

Tested work includes assets such as scoreboard/frontend geometry using EA render methods including `TextureScaleApt` and `GouraudApt`.

Current capabilities include:

- Frontend Geometry import.
- Position editing.
- Vertex-color editing.
- Preservation of frontend-specific stream layouts.

Arbitrary frontend topology growth is **not currently considered supported**. Experiments could produce files that serialized correctly but crashed in-game.

### Player/base geometry assembly

The tool can load a complete player base such as:

- `base_lodB.ebo`
- `base_lodC.ebo`
- `base_lodD.ebo`

and combine it with a partial player morph EBO.

The base supplies the complete player Geometry. The morph only modifies the targets actually present in that morph file. Geometry with no corresponding morph target remains unchanged.

This makes it possible to view a complete assembled player in Blender rather than isolated morph fragments.

### Player morph decoding

EBO Tools understands the PC morph structure sufficiently to decode and apply coordinate morph streams.

Known morph targets include examples such as:

- BasePlyr
- headAShape / headBShape
- jerseyShape
- shortsShape
- historicShortsShape
- Shoe
- hand poses
- player-name shapes

Morph streams may be dense or EA sparse/RLE encoded.

### EA render-to-logical morph mapping

A major part of the morph work is support for EA's explicit mapping between rendered Geometry vertices and logical morph vertices.

This is important because one logical vertex can have multiple rendered copies at seams or across render batches.

The tool supports both:

- whole-Geometry EA mapping tables, as seen in head geometry;
- per-render-batch EA mapping tables, as seen in BasePlyr and other multi-batch geometry.

This replaced the earlier position-deduplication approximation for targets where authoritative EA tables are available.

### Fixed-topology morph export

The current player workflow is:

```text
Import complete base EBO
        ↓
Import partial/player morph EBO
        ↓
Apply available morph targets
        ↓
Move/scale existing vertices in Blender
        ↓
Export the morph EBO
```

The base EBO remains an immutable reference. Export writes the edited logical deltas back to the **morph EBO**, not the base.

Vertex topology is intentionally fixed for morph editing.

### Sparse morph repacking

EA frequently omits zero XYZ morph components from its serialized coordinate payload.

0.7.0-alpha.15 can rebuild the sparse membership mask and reuse existing stored-zero slots when an edit makes a previously omitted component non-zero.

This allows substantially more freedom than simply preserving EA's original sparse mask.

## Current limitations

### Morph payload growth

Sparse morph repacking currently preserves the source stream's allocated float capacity.

For example, if a source morph has room for 843 stored components but an edit requires 890 genuinely non-zero components, export stops instead of corrupting the EBO.

Future work needs to resize/rebuild MorphData and relocate the affected serialized data.

### Morph topology

Morph editing is fixed topology.

Do not:

- add vertices;
- delete vertices;
- subdivide the mesh;
- merge/reorder geometry;
- add new faces expecting them to become part of the morph.

The intended operation is movement/scaling of existing vertices.

### Morph mapping edge cases

Some targets—particularly player-name/letter geometry—contain multiple plausible EA mapping tables. These still need stronger structural association before they should be treated as fully editable/exportable.

### New materials and render batches

Existing Geometry/material structures can be preserved and edited in supported workflows.

Creating an entirely new independent material/render batch from nothing is a separate serialization problem and is not yet a general supported feature.

### Frontend topology growth

Frontend vertex/color editing works, but arbitrary topology growth has not been made game-safe.

## Tested game generations

Development samples currently cover:

| Game | Geometry | Specialized models | Player morph research |
| --- | --- | --- | --- |
| NBA Live 2005 | Yes | Yes | Yes |
| NBA Live 06 | Yes | Yes | Yes |
| NBA Live 08 | Yes | Samples/research | Yes |

Support is determined by the actual EBO structure, not simply by game year.

## Technical findings implemented by the project

The project has established several useful pieces of the PC EBO format, including:

- Little-endian EBO v17 containers.
- 0x14-byte chunk headers.
- 0x10-byte chunk TOC records.
- TOC data targets relative to the TOC record.
- 12-byte export records with relative exported-data references.
- PC Geometry vertex/index buffer structures.
- Geometry containing multiple render batches.
- Render-method association and runtime naming behavior.
- Specialized selector/palette streams.
- Morph target exports and MorphStreamHeader structures.
- Dense and sparse coordinate morph streams.
- EA render-vertex to logical-morph mapping tables.
- Per-batch mapping tables for multi-batch Geometry.

The project deliberately treats **PC files and PC game behavior as authoritative**. Information from console/debug-symbol research is useful for identifying concepts and names, but is not assumed to define the PC binary layout.

## Safety / backups

These are reverse-engineered game formats. Always keep untouched copies of:

- the original EBO;
- the base player EBO used for a morph;
- associated FSH/textures;
- any archive (`.viv`, `.big`, etc.) being modified.

Do not overwrite the source morph while testing an exported version.

## Roadmap

Immediate remaining morph work:

1. Resizable sparse MorphData and safe relocation.
2. Full edit/export validation of head, jersey, shorts, shoes, hands, and other targets.
3. Resolve ambiguous mapping-table associations.
4. Stronger topology-integrity validation.
5. Finalize the morph editing UI and reporting.

The next major Geometry milestone is a **from-scratch court exporter**:

```text
Blender mesh
    ↓
EBO Tools serializer
    ↓
new PC Geometry EBO
    ↓
NBA Live
```

The initial goal is a minimal game-loadable court EBO generated by EBO Tools rather than an existing EBO used as a byte template. From there the serializer can expand toward multiple meshes, materials, render batches, and complete custom courts.

## Project philosophy

EBO Tools is moving toward a structural EBO implementation rather than a collection of one-off converters.

Where possible, the tool should discover what an EBO contains, preserve structures it does not need to modify, use EA's own mappings when they exist, and refuse unsafe exports rather than silently producing corrupted files.

---

NBA Live and related names are trademarks of their respective owners. This is an independent reverse-engineering/modding project and is not affiliated with or endorsed by Electronic Arts.
