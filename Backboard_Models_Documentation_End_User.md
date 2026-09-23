# NBA Live EBO Tools — Backboard Models

## Overview

The **Backboard Models** workflow is more specialized than court or stadium editing.

NBA Live backboards combine:

- rigid skin weights
- several package EBO variants
- dynamic game-clock and shot-clock materials
- required Geometry names
- strict validation rules

NBA Live EBO Tools supports:

1. **Editing an existing backboard**
2. **Rebuilding the main backboard EBO**
3. **Creating a complete backboard package from Blender**

The tool provides:

- a dedicated Backboard EBO panel
- rigid weight tools
- shot-clock material tagging
- shot-clock validation
- package export
- native texture generation

The supported backboard format families are:

- NBA Live 2005
- NBA Live 06-family

The NBA Live 06 backboard format also works in NBA Live 07 and NBA Live 08.

---

# Requirements

## Software

- **Blender 5.0 or newer**
- **NBA Live EBO Tools** installed and enabled

## Optional reference files

A reference backboard is optional for the full package exporter but useful when preserving native Geometry flags or FSH data.

Typical files:

```text
<name>.ebo
<name>.fsh
<name>_trans.ebo
<name>_refl.ebo
<name>_refl.fsh
```

NBA Live 2005 additionally uses:

```text
<name>_shad.ebo
```

---

# Supported Workflows

| Workflow | NBA Live 2005 | NBA Live 06 | NBA Live 07 | NBA Live 08 |
|---|---:|---:|---:|---:|
| Import existing backboard | Yes | Yes | Yes | Yes |
| Rebuild main backboard EBO | Yes | Yes | Yes | Yes via 06-family |
| Scratch full package | Yes | Yes | Yes via 06-family | Yes via 06-family |

---

# Open the Backboard Tools

In Blender:

```text
View3D > Sidebar > NBA Live > Backboard EBO
```

Enable:

```text
Backboard Mode
```

The panel contains:

- Existing Imported Backboard
- Rigid Skin Weights
- Dynamic Shot Clock
- Backboard EBO Export
- Backboard Package Export

---

# Main Geometry Names

The main backboard EBO uses exactly two Geometry objects:

```text
BaseBackboard
led
```

These names are important.

The main exporter expects:

- exactly one `BaseBackboard`
- exactly one `led`

Do not rename these objects in an existing-backboard workflow.

---

# Full Package Collections

The full package exporter reads fixed Blender collection names.

## NBA Live 06-family

```text
bbd
bbd_trans
bbd_refl
```

## NBA Live 2005

```text
bbd
bbd_trans
bbd_refl
bbd_shad
```

The `bbd` collection must contain:

```text
BaseBackboard
led
```

The other collections contain the geometry for the matching package variants.

---

# Part I — Rigid Skin Weights

## Weight Groups

Every backboard vertex must belong to exactly one of:

```text
Backboard_Support
Backboard_Board
Backboard_Rim
```

The weight must be exactly:

```text
1.0
```

Partial blending is not supported in this workflow.

---

# Bone Mapping

The tool maps the semantic groups to these rigid bone IDs:

```text
Backboard_Support -> bone 1
Backboard_Board   -> bone 2
Backboard_Rim     -> bone 3
```

The panel displays this mapping directly.

---

# Creating Weight Groups

Use:

```text
Create Backboard Weight Groups
```

This creates the three semantic vertex groups on the selected mesh objects.

---

# Manual Weight Assignment

Select vertices in Blender and use:

```text
Support
Board
Rim
```

The operator removes those vertices from the other semantic groups and assigns the selected group at weight `1.0`.

This keeps the rigid-weight contract valid.

---

# Weight Transfer

Use:

```text
Transfer Rigid Weights
```

to copy a valid donor weighting layout onto target geometry.

This is useful when:

- replacing a backboard mesh
- converting an external model
- keeping the original support/board/rim behavior

The donor must already have valid rigid weights.

---

# Validate Rigid Weights

Use:

```text
Validate Rigid Weights
```

The validator requires every selected vertex to have:

- one semantic group
- weight 1.0
- no duplicate semantic assignment

If validation fails, fix the weights before export.

---

# Mark Existing Weights

Use:

```text
Mark Existing Weights
```

after confirming an imported backboard's current weighting.

This records the existing rigid-weight state for the workflow.

---

# Part II — Dynamic Backboard Clock

The main backboard contains six dynamic clock materials.

This is separate from the stadium jumbotron system.

The native texture asset names are:

```text
time
tnum
```

---

# Clock Channel Layout

The required six channels are:

```text
time -> 0
time -> 1
time -> 2
time -> 3
tnum -> 5
tnum -> 4
```

The tool displays them with readable semantic names.

---

# Semantic Clock Names

The readable names are:

```text
NBAShotClock_GameMinTens
NBAShotClock_GameMinOnes
NBAShotClock_GameSecTens
NBAShotClock_GameSecOnes
NBAShotClock_ShotClockOnes
NBAShotClock_ShotClockTens
```

Typical imported Blender material names look like:

```text
EBO.time [NBAShotClock_GameMinTens]
EBO.time [NBAShotClock_GameMinOnes]
EBO.time [NBAShotClock_GameSecTens]
EBO.time [NBAShotClock_GameSecOnes]

EBO.tnum [NBAShotClock_ShotClockOnes]
EBO.tnum [NBAShotClock_ShotClockTens]
```

The texture name remains `time` or `tnum`.

The bracketed suffix identifies the logical clock channel.

---

# Tag Shot Clock Materials

Use:

```text
Tag Shot Clock Materials
```

This operator:

- finds the four `time` material slots
- finds the two `tnum` material slots
- assigns the correct semantic clock identity
- creates unique per-slot material identity where necessary

This prevents all six clock slots from collapsing into one shared Blender material definition.

---

# Validate Shot Clock

Use:

```text
Validate Shot Clock
```

The tool verifies that the main `BaseBackboard` contains the full six-channel contract.

The exporter also validates the compiled EBO after building it.

The final binary must contain:

```text
time = 0,1,2,3
tnum = 5,4
```

---

# Clock Weight Rule

All six dynamic clock regions should use:

```text
Backboard_Board
```

This keeps the display attached to the board instead of the rim or support.

---

# Recognized Native Material Roles

The existing-backboard preparation tool recognizes these asset names.

## Clock

```text
time
tnum
```

## Rim

```text
orim
rim
```

## Board

```text
ocam
tbbd
shot
slit
ledl
```

These names help identify imported material roles.

---

# Part III — Editing an Existing Backboard

## Prepare Imported Backboard

After importing a native backboard:

1. Select the imported backboard meshes.
2. Open the Backboard EBO panel.
3. Click:
   ```text
   Prepare Imported Backboard
   ```

This prepares the selected objects for the specialized backboard workflow while preserving imported `EBO.*` material names.

---

# Keep Required Object Names

For an imported main backboard, keep:

```text
BaseBackboard
led
```

The exporter uses those identities.

---

# Check the Weights

Run:

```text
Validate Rigid Weights
```

If needed:

- create the semantic groups
- manually assign regions
- transfer weights from a donor

---

# Check the Clock Materials

Run:

```text
Tag Shot Clock Materials
```

then:

```text
Validate Shot Clock
```

Do this before exporting.

---

# Part IV — Main Backboard EBO Export

Use this when only the main EBO is being rebuilt.

The selected scene must contain:

```text
BaseBackboard
led
```

Select exactly one of each.

Then use:

```text
Export Backboard EBO
```

---

# Reference EBO

The main exporter can use a reference EBO.

A reference can provide native Geometry flags for:

```text
BaseBackboard
led
```

If no reference is supplied, the tool uses verified defaults for the selected game family.

---

# Main Export Validation

Before writing the EBO, the exporter checks:

- exactly one `BaseBackboard`
- exactly one `led`
- valid rigid weights
- complete six-channel clock layout
- valid EBO structure
- matching declared file size
- correct compiled clock channel values

---

# Part V — Full Backboard Package Export

Use:

```text
Export Backboard Package
```

when the complete installable set is required.

---

# NBA Live 06-Family Package

Required collections:

```text
bbd
bbd_trans
bbd_refl
```

Output:

```text
<name>.ebo
<name>.fsh
<name>_trans.ebo
<name>_refl.ebo
<name>_refl.fsh
```

This package family can also be used in NBA Live 07 and NBA Live 08.

---

# NBA Live 2005 Package

Required collections:

```text
bbd
bbd_trans
bbd_refl
bbd_shad
```

Output:

```text
<name>.ebo
<name>.fsh
<name>_trans.ebo
<name>_refl.ebo
<name>_refl.fsh
<name>_shad.ebo
```

NBA Live 2005 requires the additional shadow model.

---

# Geometry Flags

The exporter resolves Geometry flags using this priority:

1. object custom property
2. optional reference EBO
3. verified default for the selected game family

---

# Default Geometry Flags

## NBA Live 2005

```text
main  = 0x0E021C09
trans = 0x0E021C09
refl  = 0x0E021C09
shad  = 0x0E021C09
```

## NBA Live 06-family

```text
main  = 0x22001407
trans = 0x22001407
refl  = 0x22001407
```

---

# Skin RMS

## NBA Live 2005

```text
gNbaDirectTextureSkinRimLightPerPixel_RMRuntime
```

## NBA Live 06-family

```text
gNbaBackboardSkin_RMRuntime
```

---

# Shot Clock RMS

## NBA Live 2005

```text
gShotClock_RMRuntime
```

## NBA Live 06-family

```text
gNbaShotClock_RMRuntime
```

---

# Material Naming

General readable form:

```text
<texture> [<RMS>]
```

Imported form:

```text
EBO.<texture> [<RMS>]
```

Dynamic clock example:

```text
EBO.time [NBAShotClock_GameSecTens]
```

The exact static RMS may depend on the imported backboard or selected profile.

---

# Texture Packaging

The full package exporter builds native FSH archives.

## Main FSH

Contains textures used by:

```text
bbd
bbd_trans
```

## Reflection FSH

Contains textures used by:

```text
bbd_refl
```

and is written as:

```text
<name>_refl.fsh
```

If a required imported texture has no new Blender image, the exporter can preserve the matching entry from a reference FSH where available.

---

# Recommended First-Time Workflow

For a first backboard project:

1. Import an original working backboard.
2. Click **Prepare Imported Backboard**.
3. Verify:
   ```text
   BaseBackboard
   led
   ```
4. Validate rigid weights.
5. Tag shot-clock materials.
6. Validate shot-clock materials.
7. Export the main EBO without geometry edits.
8. Test in-game.
9. Make one small geometry edit.
10. Export again.
11. Test.
12. Only then build a full scratch package or replace larger sections.

---

# Recommended Scratch Package Workflow

1. Create:
   ```text
   bbd
   bbd_trans
   bbd_refl
   ```
2. Add:
   ```text
   bbd_shad
   ```
   if targeting NBA Live 2005.
3. Put `BaseBackboard` and `led` in `bbd`.
4. Create/transfer valid rigid weights.
5. Add the clock materials.
6. Tag and validate the clock.
7. Add real texture images.
8. Optionally choose a reference EBO.
9. Export the package.
10. Test in-game.

For NBA Live 07/08, use the **06-family** profile.

---

# Troubleshooting

## `BaseBackboard` not found

The main object must be named:

```text
BaseBackboard
```

---

## `led` not found

The main backboard also requires:

```text
led
```

---

## Weight validation fails

At least one vertex is:

- unweighted
- weighted to multiple semantic groups
- weighted at a value other than 1.0

Correct the weight assignment and validate again.

---

## Clock validation fails

The main object must contain:

```text
4 x time
2 x tnum
```

with the six native channel identities.

Run:

```text
Tag Shot Clock Materials
Validate Shot Clock
```

---

## Clock digits are duplicated

Older Blender scenes may have shared material datablocks that lost per-slot channel identity.

Re-run the shot-clock tagger and validator before export.

---

## Reflection textures are missing

Check the materials and images inside:

```text
bbd_refl
```

---

## NBA Live 2005 package is incomplete

Make sure:

```text
bbd_shad
```

exists and contains the required shadow model.

---

# Quick Reference

## Main objects

```text
BaseBackboard
led
```

## Weight groups

```text
Backboard_Support
Backboard_Board
Backboard_Rim
```

## Bone IDs

```text
Support = 1
Board   = 2
Rim     = 3
```

## Clock texture names

```text
time
tnum
```

## Clock channels

```text
time = 0,1,2,3
tnum = 5,4
```

## 2005 collections

```text
bbd
bbd_trans
bbd_refl
bbd_shad
```

## 06/07/08 collections

```text
bbd
bbd_trans
bbd_refl
```

## 07/08 note

```text
Use the NBA Live 06-family backboard format.
```

---

# Summary

The Backboard EBO tools are designed to make a specialized asset manageable for a first-time user.

The key rules are:

- keep the required `BaseBackboard` and `led` identities
- use rigid Support/Board/Rim weights
- validate every vertex
- preserve the full six-channel clock layout
- organize package variants into the required collections

Once those rules are satisfied, EBO Tools can rebuild the main backboard or create a complete backboard package for NBA Live 2005 and the 06/07/08 format family.
