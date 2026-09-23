# NBA Live EBO Tools — Player / Body Models

## Overview

The **Player / Body Models** workflow in NBA Live EBO Tools is designed for users who want to edit NBA Live player meshes in Blender and export them back to the game safely.

This workflow is different from ordinary stadium or court editing.

Player and body models use **morph-based geometry**, and the exporter must preserve the original model's internal structure. That means the tool is intended for **editing an existing player/body model**, not creating a completely new player EBO from an empty Blender scene.

The current workflow supports NBA Live player/body morph models from:

- **NBA Live 2005**
- **NBA Live 06**
- and the same supported player/body format family used by the tool for later titles where applicable

The safest workflow is always:

1. Import a supported player/body EBO.
2. Edit the mesh without changing the required structure.
3. Export through the Player / Body tools.
4. Test the result in-game.

---

# Requirements

## Software

- **Blender 5.0 or newer**
- **NBA Live EBO Tools** installed and enabled

## Files

A typical player/body workflow uses:

```text
player/body morph EBO
base_lodB.ebo
```

The included tool package can provide the required base reference for supported games.

The **player/body EBO** is the file that is actually edited and rebuilt.

The **base EBO** is used as a reference for the model's underlying base geometry.

---

# What This Workflow Is For

Use the Player / Body tools for:

- player head/face morph models
- body morph models
- supported player mesh variations
- vertex-position editing
- UV editing where supported
- preserving morph compatibility
- exporting the edited model back to EBO

This workflow is not intended for:

- rebuilding a player model with completely different topology
- adding arbitrary new vertices
- deleting required vertices
- turning an unrelated mesh into a player EBO from scratch
- player accessories such as separate headband/hair accessory workflows

---

# Important Concept: Base Geometry vs Morph Geometry

NBA Live player models are not stored like ordinary static stadium meshes.

The tool works with two related pieces of information:

## Base geometry

The base geometry provides the original reference vertex layout.

For supported workflows, this comes from the appropriate:

```text
base_lodB.ebo
```

## Morph geometry

The player/body EBO contains the model-specific morph information that changes the base shape into the actual player.

The exporter rebuilds this morph data after the user edits the mesh in Blender.

This is why the original vertex structure must remain compatible.

---

# First-Time Workflow

## 1. Open the Player / Body Tools

In Blender, open:

```text
View3D > Sidebar > NBA Live
```

Find the Player / Body section.

Choose the target game/profile if the panel provides that option.

---

# 2. Import the Player or Body EBO

Use the player/body import operator.

Choose the supported player/body EBO.

The importer reconstructs the visible mesh from:

- the base geometry
- the player's morph data

The result appears as a normal Blender mesh that can be edited.

---

# 3. Apply a Texture in Blender

The imported player mesh may not automatically appear with a useful face/body texture.

For easier editing:

1. Create or select a Blender material.
2. Add the player's texture.
3. Connect it to the Principled BSDF Base Color.
4. Assign it to the imported mesh.

This is only for visual editing convenience unless the workflow explicitly exports that texture separately.

---

# 4. Check the UV Map

Some player/body assets require attention to UV orientation.

When inspecting a player model:

- compare facial features against the texture
- confirm eyes, nose, mouth, ears, and hairline align correctly
- use Blender's UV Editor to inspect the result

If the imported UV appears vertically reversed relative to the texture, correct it in Blender before final export if required by that specific workflow.

Do not make unrelated UV changes unless they are intentional.

---

# 5. Edit the Mesh

The safest edits are vertex-position changes.

Examples:

- facial shape
- nose size
- jaw shape
- cheek shape
- head width
- skull shape
- body proportions
- small silhouette adjustments

The key rule is:

**Keep the original topology compatible with the imported morph model.**

---

# Topology Rules

## Do not casually add or remove vertices

Player/body morph data depends on a stable vertex layout.

Changing the vertex count can break the mapping between:

- the base geometry
- the morph stream
- the exported player model

Unless a future tool version explicitly says otherwise, treat the imported topology as fixed.

## Do not delete required vertices

Deleting vertices can invalidate the morph stream.

## Do not reorder the model through destructive rebuilds

Operations that rebuild the mesh structure can change vertex ordering.

Examples that may be unsafe:

- remesh
- voxel remesh
- decimate
- subdivision followed by destructive apply
- deleting and recreating large mesh sections
- converting the mesh through workflows that do not preserve vertex order

Use non-destructive editing methods whenever possible.

---

# Safe Editing Operations

Generally safe operations include:

- moving vertices
- proportional editing
- sculpting that preserves topology
- smooth/relax operations that do not add/remove vertices
- UV adjustment
- material assignment for Blender preview

Always keep a backup before major edits.

---

# Rendered Vertices vs Logical Vertices

A player/body EBO may internally represent geometry in a way that differs from the simple visible vertex count in Blender.

The importer may reconstruct a clean editable mesh while the exporter still needs to preserve the original morph-stream structure.

This is normal.

The user should edit the imported Blender object rather than trying to manually reconstruct the binary layout.

---

# Morph Stream Types

NBA Live player/body files can contain different morph encoding styles.

The tool handles the supported formats internally.

Users do not need to manually choose a morph codec in normal use.

The important requirement is to preserve the mesh structure expected by the imported file.

---

# Game Selection

When exporting, use the correct game/profile.

The tool uses game-specific base/reference information where required.

A model intended for NBA Live 2005 should be exported using the 2005 profile.

A model intended for NBA Live 06 should use the 06 profile.

Do not mix base references from different games unless the tool explicitly supports that conversion.

---

# Exporting the Edited Model

When editing is complete:

1. Select the imported player/body mesh.
2. Open the Player / Body section.
3. Confirm the correct game/profile.
4. Choose the export option.
5. Save the rebuilt EBO.

The exporter calculates the morph differences required to reproduce the edited Blender mesh from the correct base model.

---

# What the Exporter Preserves

The player/body exporter is designed to preserve the original model's required structural data while updating the edited shape.

Depending on the file, this includes:

- original morph organization
- stream metadata
- base-geometry relationship
- compatible vertex ordering
- model-specific morph data

The tool rebuilds the edited morph data rather than treating the player as a generic static EBO.

---

# Accessories

Separate player accessories are not part of the current supported player/body workflow.

Examples include:

- headbands
- separate hair accessory EBOs
- other accessory-specific models

These should not be assumed to use the same export path as the main player/body morph model.

If an accessory imports separately, keep it separate unless a dedicated accessory workflow is documented.

---

# Recommended Test Procedure

For a new user, use this sequence:

1. Import an untouched player/body EBO.
2. Export it without edits.
3. Test it in-game.
4. Re-import the original.
5. Move one or two vertices slightly.
6. Export again.
7. Test in-game.
8. Only then make larger edits.

This confirms that:

- the correct game profile is selected
- the base model is correct
- the file is supported
- the export path works before a large amount of editing is done

---

# Troubleshooting

## Export says the base model is missing

The exporter needs the appropriate base reference for that game/model family.

Confirm the required `base_lodB.ebo` is available through the add-on or configured workflow.

---

## The model imports but looks distorted

Check:

- the correct game/profile
- the correct player/body EBO
- the correct base reference
- whether the file is actually a supported morph model

Do not try to compensate for a wrong base model by manually reshaping the mesh.

---

## The model exports but crashes the game

Common causes include:

- changed vertex count
- destroyed vertex ordering
- unsupported topology changes
- wrong game profile
- wrong base reference
- using a non-player EBO in the player workflow

Return to the original imported topology and test again.

---

## UVs look wrong

Use the UV Editor and compare the mesh against the actual player texture.

If the model is vertically reversed relative to the texture, correct the UV map carefully.

Avoid changing UVs if the model already maps correctly in-game.

---

## The exported model looks different from Blender

Check whether the edit changed only vertex positions or also changed topology.

Player/body export is designed around preserving the morph structure, not converting an arbitrary Blender mesh.

---

# Quick Reference

## Use this workflow for

```text
existing NBA Live player/body morph models
```

## Main rule

```text
Preserve topology and vertex structure.
```

## Safe edits

```text
move vertices
sculpt without remeshing
adjust UVs
preview with Blender materials
```

## Avoid

```text
adding vertices
deleting vertices
remeshing
decimation
destructive topology rebuilds
```

## Base reference

```text
base_lodB.ebo
```

## Final output

```text
edited player/body .ebo
```

---

# Summary

The Player / Body workflow is intended for **editing an existing NBA Live morph model safely**.

Unlike courts and stadiums, player models should not be treated as freely rebuildable static geometry.

A first-time user should think of the imported player mesh as a structured morph model:

- edit the shape
- preserve the topology
- keep the correct base reference
- export with the correct game profile

Following those rules allows the tool to rebuild the player/body EBO while preserving the internal morph structure required by the game.
