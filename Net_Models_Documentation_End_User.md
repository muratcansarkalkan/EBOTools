# NBA Live EBO Tools — Net Models

## Overview

The **Net EBO** tools are designed for editing and replacing the basketball net model used by NBA Live.

Unlike courts and stadiums, the net is a **weighted/skinned model**. Each vertex must be assigned to a specific rigid net section so that the game can animate the net correctly.

The current net workflow is based on the verified **NBA Live 06 net format**.

The tool supports:

- importing an existing net through the general EBO importer
- recovering the stock NBA Live 06 weight layout
- creating the required net weight groups
- manually assigning net weights
- transferring weights from a donor net to a replacement mesh
- validating all rigid weights
- changing net width and length
- exporting a new weighted `netShape` EBO

The net exporter is intended for users who want to modify the original net or replace it with a custom mesh while preserving the game's required weight structure.

---

# Requirements

## Software

- **Blender 5.0 or newer**
- **NBA Live EBO Tools** installed and enabled

## Recommended source files

For a first project, use a known working NBA Live 06 net EBO as a donor/reference.

The standard verified profile uses:

```text
Geometry: netShape
Texture:  tnet
RMS:      gNbaBackboardSkin_RMRuntime
```

---

# Open the Net Tools

In Blender:

```text
View3D > Sidebar > NBA Live > Net EBO
```

The panel contains:

- Existing Stock Net
- Rigid Net Weights
- Net Size
- Export

---

# Verified NBA Live 06 Net Profile

The current exporter uses the verified NBA Live 06 structure:

```text
Geometry name: netShape
Texture name:  tnet
RMS:           gNbaBackboardSkin_RMRuntime
Geometry flags: 0x35121205
```

The verified rigid bone palette order is:

```text
1, 2, 0, 3
```

Users normally do not need to edit this manually.

---

# Net Weight Groups

The net uses four semantic vertex groups:

```text
Net_TopAnchor
Net_Upper
Net_Body
Net_Bottom
```

Every exported vertex must belong to **exactly one** of these groups.

The weight must be:

```text
1.0
```

Partial blending is not supported by this workflow.

---

# Bone Mapping

The semantic groups map to the game bones as:

```text
Net_TopAnchor -> bone 0
Net_Upper     -> bone 1
Net_Body      -> bone 2
Net_Bottom    -> bone 3
```

The exporter converts the semantic Blender groups into the required game palette automatically.

---

# Understanding the Stock Net Layout

The verified stock NBA Live 06 net contains five vertical rings.

From top to bottom:

```text
Ring 1 -> Net_TopAnchor -> bone 0
Ring 2 -> Net_Upper     -> bone 1
Ring 3 -> Net_Body      -> bone 2
Ring 4 -> Net_Body      -> bone 2
Ring 5 -> Net_Bottom    -> bone 3
```

The two middle rings intentionally share the same `Net_Body` group.

---

# Workflow A — Editing the Stock NBA Live 06 Net

## 1. Import the net

Use the normal NBA Live EBO importer:

```text
NBA Live > NBA Live Environments > Import NBA Live EBO
```

Import the original net EBO.

Make the imported net mesh active.

---

# 2. Recover the stock weights

Use:

```text
Recover Stock 06 Net Weights
```

This operator is specifically designed for the original five-ring NBA Live 06 net.

It detects the five vertical Z bands and assigns them automatically:

```text
top
upper
body
body
bottom
```

It also records:

```text
Geometry name = netShape
Geometry flags = 0x35121205
Profile = NBA Live 06
```

## Important

This automatic recovery expects **exactly five vertical bands**.

If the model has custom topology or a different number of rings, use manual assignment or donor weight transfer instead.

---

# 3. Validate the weights

Use:

```text
Validate Net Weights
```

The tool checks every selected vertex.

A valid vertex must have:

- exactly one net semantic group
- weight 1.0

The panel reports the number of vertices assigned to:

```text
Top
Upper
Body
Bottom
```

---

# Workflow B — Replacing the Net With a Custom Mesh

A custom mesh can be used, but it still needs the four rigid net regions.

The easiest method is usually donor weight transfer.

---

# 1. Prepare the replacement mesh

The replacement net may be:

- modeled in Blender
- imported from FBX
- imported from OBJ
- converted from another game

Before weight transfer, align the replacement mesh to the donor net as closely as possible.

Match:

- center position
- top-ring position
- overall width
- overall length

Weight transfer uses spatial proximity, so alignment matters.

---

# 2. Create the weight groups

Select the custom net and click:

```text
Create Net Weight Groups
```

This creates:

```text
Net_TopAnchor
Net_Upper
Net_Body
Net_Bottom
```

---

# 3. Transfer weights from a donor

Select:

- the weighted donor net
- the replacement mesh

Make the **donor net the active object**.

Click:

```text
Transfer Net Weights
```

The tool uses nearest-vertex matching in world space.

Each replacement vertex receives the semantic group of the nearest donor vertex.

This is useful when the replacement mesh has different topology from the stock net.

---

# 4. Validate the replacement mesh

Run:

```text
Validate Net Weights
```

Do not export until all vertices pass validation.

---

# Manual Weight Assignment

For full control, weights can be assigned manually.

## 1. Create the groups

Click:

```text
Create Net Weight Groups
```

## 2. Enter Edit Mode

Select the vertices for one net region.

## 3. Use one of the assignment buttons

```text
Assign Top Anchor
Assign Upper
Assign Body
Assign Bottom
```

When assigning a group, the tool automatically removes the selected vertices from the other net semantic groups.

This prevents accidental double-weighting.

---

# Weight Rules

Every exported vertex must satisfy all of the following:

```text
exactly one semantic group
weight = 1.0
```

Invalid examples include:

```text
no group
Top = 0.5
Upper = 0.5
Top = 1.0 + Upper = 1.0
```

Valid example:

```text
Net_Body = 1.0
```

---

# Changing Net Width and Length

The Net EBO panel includes:

```text
Width Scale
Length Scale
Apply Net Width / Length
```

These controls are useful for quickly adjusting a net to a different rim or visual style.

---

# Width Scale

Width scaling changes the net radially in Blender X/Y space.

Example:

```text
1.00 = unchanged
0.90 = narrower
1.10 = wider
```

The scaling is performed around the net's average horizontal center.

---

# Length Scale

Length scaling changes the vertical distance below the top ring.

Example:

```text
1.00 = unchanged
0.80 = shorter
1.20 = longer
```

The **topmost ring stays vertically anchored**.

This means increasing net length extends the lower portions downward without moving the attachment ring.

---

# Recommended Scale Workflow

1. Align the top ring to the basket rim.
2. Adjust **Width Scale**.
3. Adjust **Length Scale**.
4. Click:
   ```text
   Apply Net Width / Length
   ```
5. Inspect the result.
6. Validate weights.
7. Export.

The scaling operation changes the actual mesh coordinates.

If several experiments are needed, save a backup before applying repeated scaling.

---

# Geometry and Coordinate Conversion

The exporter automatically converts Blender coordinates to the NBA Live coordinate system.

Users should work normally in Blender.

The exported positions use the appropriate game-axis conversion internally.

The exporter also transforms normals correctly.

---

# UV Maps

The exporter uses the first UV map.

The vertical coordinate is converted automatically:

```text
game V = 1.0 - Blender V
```

Do not manually compensate for this unless the texture is genuinely incorrect.

If no UV map exists, the exporter uses:

```text
0, 0
```

for all UV coordinates.

A real net should normally have a valid UV map.

---

# Material Requirements

The current Net EBO exporter expects exactly **one used material slot**.

If several material slots exist but only one is assigned to faces, that is acceptable.

If faces actively use more than one material, export stops.

---

# Texture Name

The verified stock texture is:

```text
tnet
```

If the Blender material contains an explicit NBA Live texture name, the exporter uses it.

Otherwise, it derives the texture name from the Blender material name.

If no usable name is found, the fallback is:

```text
tnet
```

---

# Runtime / RMS

The net exporter uses:

```text
gNbaBackboardSkin_RMRuntime
```

This is fixed by the verified NBA Live 06 net profile.

Users do not need to manually assign the runtime.

---

# Exporting the Net

Make the final weighted net mesh the **active object**.

Open:

```text
NBA Live > Net EBO
```

Then click:

```text
Export Net EBO
```

The active mesh is compiled as:

```text
netShape
```

The exporter writes a new EBO file.

---

# Export Validation

Before writing the net, the tool checks:

- the active object is a mesh
- all vertices have valid rigid weights
- exactly one material is actively used
- usable triangles exist
- the required bone palette can be built

If validation fails, export stops with an error instead of creating an unsafe EBO.

---

# Triangle Handling

The Blender mesh is triangulated for export.

The exporter converts the triangles into a triangle-strip representation required by the EBO structure.

Users do not need to manually create triangle strips.

---

# UV Seams and Output Vertices

The exporter may create additional stream vertices when one Blender vertex has different:

- UV coordinates
- normals
- bone identities

This is expected.

The exported stream-vertex count may therefore differ from the Blender vertex count.

---

# Recommended First-Time Workflow

For a user editing nets for the first time:

1. Import the original NBA Live 06 net.
2. Make `netShape` active.
3. Click:
   ```text
   Recover Stock 06 Net Weights
   ```
4. Click:
   ```text
   Validate Net Weights
   ```
5. Export without geometry edits.
6. Test the EBO in-game.
7. Re-import the original.
8. Make a small width or length change.
9. Export again.
10. Test.
11. Only then replace the full mesh or use donor weight transfer.

This confirms the basic workflow before larger modifications are attempted.

---

# Recommended Custom-Net Workflow

1. Import a working stock donor net.
2. Recover and validate its stock weights.
3. Import or create the replacement net.
4. Align the replacement to the donor.
5. Select both meshes.
6. Make the donor active.
7. Click:
   ```text
   Transfer Net Weights
   ```
8. Hide the donor.
9. Validate the replacement net.
10. Apply width/length scaling if needed.
11. Make the replacement active.
12. Export the new net EBO.
13. Test in-game.

---

# Troubleshooting

## Recover Stock 06 Net Weights reports the wrong number of Z bands

The automatic recovery tool is only for the verified five-ring stock NBA Live 06 net.

For a custom mesh:

- use donor weight transfer
- or assign the four groups manually

---

## Weight validation fails

At least one vertex is:

- unweighted
- assigned to more than one net group
- assigned at a weight other than 1.0

Fix the vertex assignments and validate again.

---

## Transfer Net Weights gives incorrect regions

The replacement mesh was probably not aligned closely enough to the donor.

Before transfer, align:

- center
- top ring
- width
- vertical length

Then transfer again.

---

## Net is detached from the rim

The top ring may have moved.

The top attachment vertices should belong to:

```text
Net_TopAnchor
```

and should be positioned at the rim.

The built-in Length Scale keeps the topmost ring vertically fixed.

---

## Net stretches incorrectly in-game

Check the semantic group layout.

The expected top-to-bottom structure is approximately:

```text
TopAnchor
Upper
Body
Body
Bottom
```

A custom mesh does not need exactly five rings, but its regions should follow the same functional progression.

---

## Export says more than one material is used

The current net exporter supports one used material group.

Assign all net faces to a single material.

---

## Texture appears upside-down

The exporter already converts UV V:

```text
V = 1 - V
```

Do not manually flip the UV twice.

---

# Quick Reference

## Geometry

```text
netShape
```

## Texture

```text
tnet
```

## RMS

```text
gNbaBackboardSkin_RMRuntime
```

## Default Geometry flags

```text
0x35121205
```

## Weight groups

```text
Net_TopAnchor
Net_Upper
Net_Body
Net_Bottom
```

## Bone mapping

```text
TopAnchor -> 0
Upper     -> 1
Body      -> 2
Bottom    -> 3
```

## Stock five-ring layout

```text
Top
Upper
Body
Body
Bottom
```

## Used materials

```text
exactly 1
```

## Export

```text
Active mesh -> netShape EBO
```

---

# Summary

The Net EBO workflow allows a first-time user to modify or replace NBA Live's weighted net without manually editing the binary file.

The essential rules are:

- use the four semantic net weight groups
- give every vertex exactly one weight at 1.0
- keep the top region attached to the rim
- use one material
- validate before export

For the original NBA Live 06 net, the tool can recover the complete stock weight layout automatically.

For custom topology, donor transfer and manual weighting make it possible to build a replacement mesh and export it as a valid `netShape` EBO.
