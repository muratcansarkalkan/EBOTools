# NBA Live EBO Tools 0.1.0

Blender 5.0 add-on for importing, editing, and exporting NBA Live 2005 and 2006
high-detail player head EBO files.

## Install

In Blender, open **Edit > Preferences > Get Extensions**, open the menu in the
upper-right corner, select **Install from Disk**, and choose the add-on ZIP.
Enable the extension if Blender does not enable it automatically.

You can also set either base-file path in **Edit > Preferences > Add-ons > NBA
Live EBO Tools**; this avoids modifying the installed extension directory.

## Use

1. Open the 3D Viewport sidebar with **N** and choose the **NBA Live** tab.
2. Select **NBA Live 2005** or **NBA Live 2006**.
3. Click **Import Player EBO** and select an original player head EBO.
4. Apply the player's face texture and correct its UV orientation as described
   below. This makes the face much easier to recognize and edit.
5. Edit the head by moving existing vertices.
6. Select the imported head and click **Export Edited EBO**.
7. Choose the destination filename. The original source EBO is never overwritten.

Each imported object remembers its game year, base model, original player file,
original vertex positions, and permanent EA vertex IDs. Multiple players and
both game years can coexist in the same Blender scene.

## Apply the face texture

The imported head does not automatically include its face texture. To see the
player's face while editing:

1. Select the imported head mesh.
2. Open the **Shading** workspace.
3. Create a material with **New** if the mesh does not already have one.
4. Add an **Image Texture** node with **Shift + A > Texture > Image Texture**.
5. Click **Open** on that node and select the player's face texture image.
6. Connect the Image Texture node's **Color** output to the Principled BSDF
   node's **Base Color** input.
7. Switch the 3D Viewport to **Material Preview** to display the texture.

## Correct the UV map orientation

Imported EBO UV coordinates use a different vertical orientation from Blender,
so the face texture may initially appear upside down or incorrectly aligned.
Flip the UV map on the Y axis:

1. Select the head mesh and press **Tab** to enter **Edit Mode**.
2. Press **A** to select all mesh vertices.
3. Open the **UV Editing** workspace.
4. Move the mouse over the **UV Editor** and press **A** to select all UVs.
5. Press **S**, then **Y**, then type **-1**, and press **Enter**.
6. If the UV map moves outside the image tile, press **G**, then **Y**, then
   type **1** or **-1** as needed to place it back over the texture.

The vertically flipped UV map is for viewing and editing the face in Blender.
Version 0.1 does not export UV edits: the original EBO UV data is preserved
unchanged when exporting the edited head.

## Version 0.1 limitations

- Vertex position edits only. Original UV, normal, colour, metadata, and all
  non-coordinate bytes are preserved exactly.
- Do not add, remove, merge, subdivide, or otherwise change mesh topology.
- NBA Live 2005 edits cannot activate coordinate components that the original
  sparse player stream omitted; such edits are rejected instead of generating
  an unsafe EBO.
- Object-level transforms are not baked into exported vertex coordinates.
- Keep the original player EBO and selected base EBO accessible when exporting.
