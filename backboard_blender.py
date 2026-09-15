"""Backboard workflow tools for NBA Live 2005/06.

v0.7.0-alpha establishes the Blender-side semantic contract first:
- rigid backboard skin groups
- donor -> external-model weight transfer
- manual rigid assignment
- validation
- shot-clock material tagging for time[0..3] and tnum[5,4]

The actual synthetic skinned EBO compiler is intentionally kept separate from
these editing tools so the Blender scene contract can be game-tested first.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper
from pathlib import Path
import struct
import re
from . import ebo_backboard, ebo_backboard_variants, synthetic_fsh

GROUP_SUPPORT = "Backboard_Support"
GROUP_BOARD = "Backboard_Board"
GROUP_RIM = "Backboard_Rim"
SEMANTIC_GROUPS = (GROUP_SUPPORT, GROUP_BOARD, GROUP_RIM)

SHOTCLOCK_RMS = {
    "2006": "gNbaShotClock_RMRuntime",
    "2005": "gShotClock_RMRuntime",
}
DEFAULT_GEOMETRY_FLAGS = {
    "2006": {
        "main": 0x22001407,
        "trans": 0x22001407,
        "refl": 0x22001407,
    },
    "2005": {
        "main": 0x0E021C09,
        "trans": 0x0E021C09,
        "refl": 0x0E021C09,
        "shad": 0x0E021C09,
    },
}
SKIN_RMS = {
    "2006": "gNbaBackboardSkin_RMRuntime",
    "2005": "gNbaDirectTextureSkinRimLightPerPixel_RMRuntime",
}


def _backboard_game(context):
    return "2005" if bool(context.scene.nba_live_backboard_2005) else "2006"


def _normalized_material_asset_name(name):
    """Return semantic TextureName from Blender/importer material name.

    Examples:
        EBO.time [NbaShotClock] -> time
        EBO.time.001 [NbaShotClock] -> time
        tnum [ShotClock] -> tnum
    """
    base = str(name).split(" [", 1)[0].strip()
    if base.lower().startswith("ebo."):
        base = base[4:]
    # Blender copy suffixes are datablock names, not EBO AssetNames.
    m = re.match(r"^(.*?)(?:\.\d{3})?$", base)
    return (m.group(1) if m else base).strip().lower()


def _shotclock_slot_occurrences(objs):
    """Return actual object/material-slot occurrences, preserving slot order."""
    time_slots = []
    tnum_slots = []
    for obj in objs:
        for slot_index, slot in enumerate(obj.material_slots):
            mat = slot.material
            if mat is None:
                continue
            asset = _normalized_material_asset_name(mat.name)
            item = (obj, slot_index, mat)
            if asset == "time":
                time_slots.append(item)
            elif asset == "tnum":
                tnum_slots.append(item)
    return time_slots, tnum_slots


def _make_unique_slot_material(obj, slot_index, source_mat, asset_name, ordinal):
    """Copy even a shared material so each dynamic shot-clock batch owns metadata."""
    mat = source_mat.copy()
    # Keep EBO provenance visible, but give each slot a unique readable identity.
    prefix = "EBO." if source_mat.name.lower().startswith("ebo.") else ""
    mat.name = f"{prefix}{asset_name}.sc{ordinal:02d}"
    obj.data.materials[slot_index] = mat
    return mat


def _mesh_objects(context):
    return [o for o in context.selected_objects if o.type == 'MESH']


def _ensure_groups(obj):
    for name in SEMANTIC_GROUPS:
        if obj.vertex_groups.get(name) is None:
            obj.vertex_groups.new(name=name)


def _semantic_weights_for_vertex(obj, vertex_index):
    found = []
    for name in SEMANTIC_GROUPS:
        vg = obj.vertex_groups.get(name)
        if vg is None:
            continue
        try:
            w = vg.weight(vertex_index)
        except RuntimeError:
            continue
        if w > 1.0e-6:
            found.append((name, float(w)))
    return found


def _assign_vertices(obj, group_name, indices):
    _ensure_groups(obj)
    indices = list(indices)
    if not indices:
        return
    # Rigid contract: remove target vertices from every semantic group, then
    # assign exactly 1.0 to the requested group.
    for name in SEMANTIC_GROUPS:
        vg = obj.vertex_groups.get(name)
        if vg:
            try:
                vg.remove(indices)
            except RuntimeError:
                pass
    obj.vertex_groups[group_name].add(indices, 1.0, 'REPLACE')


class NBA_OT_backboard_create_groups(Operator):
    bl_idname = "nba.backboard_create_groups"
    bl_label = "Create Backboard Weight Groups"
    bl_description = "Create Support, Board and Rim semantic vertex groups on selected meshes"

    def execute(self, context):
        objs = _mesh_objects(context)
        if not objs:
            self.report({'ERROR'}, "Select at least one mesh.")
            return {'CANCELLED'}
        for obj in objs:
            _ensure_groups(obj)
        self.report({'INFO'}, f"Backboard groups ready on {len(objs)} mesh(es).")
        return {'FINISHED'}


class _NBA_OT_assign_backboard_group(Operator):
    bl_options = {'REGISTER', 'UNDO'}
    group_name = ""

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Active object must be a mesh.")
            return {'CANCELLED'}
        if obj.mode != 'EDIT':
            self.report({'ERROR'}, "Enter Edit Mode and select vertices first.")
            return {'CANCELLED'}

        # Update edit selection, switch briefly so MeshVertex.select is current.
        bpy.ops.object.mode_set(mode='OBJECT')
        try:
            indices = [v.index for v in obj.data.vertices if v.select]
            if not indices:
                self.report({'ERROR'}, "No vertices selected.")
                return {'CANCELLED'}
            _assign_vertices(obj, self.group_name, indices)
        finally:
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, f"Assigned {len(indices)} vertices to {self.group_name}.")
        return {'FINISHED'}


class NBA_OT_assign_backboard_support(_NBA_OT_assign_backboard_group):
    bl_idname = "nba.assign_backboard_support"
    bl_label = "Assign Support"
    group_name = GROUP_SUPPORT


class NBA_OT_assign_backboard_board(_NBA_OT_assign_backboard_group):
    bl_idname = "nba.assign_backboard_board"
    bl_label = "Assign Board"
    group_name = GROUP_BOARD


class NBA_OT_assign_backboard_rim(_NBA_OT_assign_backboard_group):
    bl_idname = "nba.assign_backboard_rim"
    bl_label = "Assign Rim"
    group_name = GROUP_RIM


class NBA_OT_backboard_transfer_weights(Operator):
    bl_idname = "nba.backboard_transfer_weights"
    bl_label = "Transfer Backboard Weights"
    bl_description = (
        "Transfer rigid Support/Board/Rim assignments from the active donor mesh "
        "to other selected meshes by nearest world-space donor vertex"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        donor = context.active_object
        if donor is None or donor.type != 'MESH':
            self.report({'ERROR'}, "Make the donor backboard mesh the active object.")
            return {'CANCELLED'}

        targets = [o for o in _mesh_objects(context) if o != donor]
        if not targets:
            self.report({'ERROR'}, "Select donor plus at least one target mesh.")
            return {'CANCELLED'}

        from mathutils.kdtree import KDTree

        donor_assignments = {}
        invalid = 0
        kd = KDTree(len(donor.data.vertices))
        for v in donor.data.vertices:
            weights = _semantic_weights_for_vertex(donor, v.index)
            if len(weights) != 1:
                invalid += 1
                continue
            name, weight = weights[0]
            if abs(weight - 1.0) > 1.0e-4:
                invalid += 1
                continue
            world = donor.matrix_world @ v.co
            kd.insert(world, v.index)
            donor_assignments[v.index] = name

        if invalid:
            self.report(
                {'ERROR'},
                f"Donor has {invalid} vertex/vertices without exactly one rigid 1.0 semantic weight."
            )
            return {'CANCELLED'}

        kd.balance()
        transferred = 0
        for target in targets:
            _ensure_groups(target)
            buckets = {name: [] for name in SEMANTIC_GROUPS}
            for v in target.data.vertices:
                world = target.matrix_world @ v.co
                _co, donor_index, _dist = kd.find(world)
                buckets[donor_assignments[donor_index]].append(v.index)

            for name, indices in buckets.items():
                if indices:
                    _assign_vertices(target, name, indices)
                    transferred += len(indices)

        self.report(
            {'INFO'},
            f"Transferred rigid backboard weights to {len(targets)} mesh(es), {transferred} vertices."
        )
        return {'FINISHED'}


class NBA_OT_backboard_validate_weights(Operator):
    bl_idname = "nba.backboard_validate_weights"
    bl_label = "Validate Backboard Weights"
    bl_description = "Require exactly one Support/Board/Rim group at weight 1.0 on every selected vertex"

    def execute(self, context):
        objs = _mesh_objects(context)
        if not objs:
            self.report({'ERROR'}, "Select at least one mesh.")
            return {'CANCELLED'}

        problems = []
        totals = {name: 0 for name in SEMANTIC_GROUPS}
        for obj in objs:
            _ensure_groups(obj)
            bad = 0
            for v in obj.data.vertices:
                weights = _semantic_weights_for_vertex(obj, v.index)
                if len(weights) != 1 or abs(weights[0][1] - 1.0) > 1.0e-4:
                    bad += 1
                else:
                    totals[weights[0][0]] += 1
            if bad:
                problems.append(f"{obj.name}: {bad}")

        if problems:
            self.report({'ERROR'}, "Invalid rigid weights — " + ", ".join(problems[:6]))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            "Rigid weights valid — "
            f"Support {totals[GROUP_SUPPORT]}, Board {totals[GROUP_BOARD]}, Rim {totals[GROUP_RIM]}."
        )
        return {'FINISHED'}


def _tag_material(mat, game, role, uv_index):
    mat["nba_live_backboard_role"] = role
    mat["nba_live_shotclock_uv_index"] = int(uv_index)
    mat["nba_live_rms_runtime"] = SHOTCLOCK_RMS[game]
    mat["nba_live_backboard_bone"] = GROUP_BOARD


class NBA_OT_backboard_tag_shotclock(Operator):
    bl_idname = "nba.backboard_tag_shotclock"
    bl_label = "Tag Shot Clock Materials"
    bl_description = (
        "Split shared imported time/tnum slots into unique Blender materials and "
        "tag the verified six-batch shot-clock contract"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        game = _backboard_game(context)
        objs = _mesh_objects(context)
        if not objs:
            self.report({'ERROR'}, "Select the backboard mesh containing shot-clock materials.")
            return {'CANCELLED'}

        time_slots, tnum_slots = _shotclock_slot_occurrences(objs)

        if len(time_slots) != 4 or len(tnum_slots) != 2:
            self.report(
                {'ERROR'},
                f"Expected 4 time slots + 2 tnum slots; found "
                f"{len(time_slots)} + {len(tnum_slots)}. "
                "EBO. prefixes and shared material datablocks are supported."
            )
            return {'CANCELLED'}

        # The imported EBO may intentionally have four slots pointing to the same
        # Blender material datablock. That loses the per-Material uvIndex contract.
        # Split every dynamic occurrence before attaching metadata.
        for ordinal, ((obj, slot_index, source), uv_index) in enumerate(
            zip(time_slots, (0, 1, 2, 3))
        ):
            mat = _make_unique_slot_material(obj, slot_index, source, "time", ordinal)
            mat["nba_live_texture_name"] = "time"
            _tag_material(mat, game, "time", uv_index)

        for ordinal, ((obj, slot_index, source), uv_index) in enumerate(
            zip(tnum_slots, (5, 4))
        ):
            mat = _make_unique_slot_material(obj, slot_index, source, "tnum", ordinal)
            mat["nba_live_texture_name"] = "tnum"
            _tag_material(mat, game, "tnum", uv_index)

        self.report(
            {'INFO'},
            f"Split/tagged shot clock: time[0,1,2,3], tnum[5,4] for NBA Live {game}."
        )
        return {'FINISHED'}


class NBA_OT_backboard_validate_shotclock(Operator):
    bl_idname = "nba.backboard_validate_shotclock"
    bl_label = "Validate Shot Clock"
    bl_description = "Validate the six dynamic shot-clock materials and Board-bone ownership"

    def execute(self, context):
        game = _backboard_game(context)
        found = []
        for obj in _mesh_objects(context):
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None or "nba_live_shotclock_uv_index" not in mat:
                    continue
                found.append((
                    mat.name,
                    mat.get("nba_live_backboard_role", ""),
                    int(mat.get("nba_live_shotclock_uv_index", -999)),
                    mat.get("nba_live_rms_runtime", ""),
                    mat.get("nba_live_backboard_bone", ""),
                ))

        expected = {
            ("time", 0), ("time", 1), ("time", 2), ("time", 3),
            ("tnum", 5), ("tnum", 4),
        }
        actual = {(role, idx) for _name, role, idx, _rms, _bone in found}
        bad_meta = [
            name for name, role, idx, rms, bone in found
            if rms != SHOTCLOCK_RMS[game] or bone != GROUP_BOARD
        ]

        if actual != expected or len(found) != 6 or bad_meta:
            self.report(
                {'ERROR'},
                f"Shot-clock contract invalid: found {sorted(actual)}"
                + (f"; bad metadata: {', '.join(bad_meta)}" if bad_meta else "")
            )
            return {'CANCELLED'}

        self.report({'INFO'}, "Shot-clock contract valid: time 0-3 + tnum 5/4.")
        return {'FINISHED'}


def _looks_like_existing_backboard(obj):
    name = obj.name.lower()
    return (
        name == "basebackboard"
        or name.startswith("basebackboard.")
        or obj.get("nba_live_geometry_name", "").lower() == "basebackboard"
    )


def _looks_like_led(obj):
    name = obj.name.lower()
    return name == "led" or name.startswith("led.")


def _existing_material_role(mat):
    asset = _normalized_material_asset_name(mat.name)
    if asset in {"time", "tnum"}:
        return "shotclock"
    if asset in {"orim", "rim"}:
        return "rim"
    if asset in {"ocam", "tbbd", "shot", "slit", "ledl"}:
        return "board"
    return "unknown"


def _mark_existing_backboard_metadata(obj, game):
    obj["nba_live_asset_profile"] = "Backboard"
    obj["nba_live_backboard_game"] = game
    if _looks_like_existing_backboard(obj):
        obj["nba_live_geometry_name"] = "BaseBackboard"
    elif _looks_like_led(obj):
        obj["nba_live_geometry_name"] = "led"


class NBA_OT_backboard_prepare_existing(Operator):
    bl_idname = "nba.backboard_prepare_existing"
    bl_label = "Prepare Imported Backboard"
    bl_description = (
        "Prepare an existing EBO-imported BaseBackboard/led scene for editing and "
        "future backboard export without renaming EBO.* materials"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        game = _backboard_game(context)
        objs = _mesh_objects(context)
        if not objs:
            self.report({'ERROR'}, "Select imported backboard mesh object(s).")
            return {'CANCELLED'}

        base = [o for o in objs if _looks_like_existing_backboard(o)]
        led = [o for o in objs if _looks_like_led(o)]
        if not base:
            self.report(
                {'ERROR'},
                "No selected BaseBackboard object found. Keep the imported Geometry name BaseBackboard."
            )
            return {'CANCELLED'}

        for obj in objs:
            _mark_existing_backboard_metadata(obj, game)
            _ensure_groups(obj)

        # Record semantic material identities without changing Blender display names.
        for obj in objs:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None:
                    continue
                asset = _normalized_material_asset_name(mat.name)
                mat["nba_live_texture_name"] = asset
                role = _existing_material_role(mat)
                mat["nba_live_backboard_material_role"] = role
                if role == "shotclock":
                    mat["nba_live_rms_runtime"] = SHOTCLOCK_RMS[game]
                    mat["nba_live_backboard_bone"] = GROUP_BOARD
                elif role in {"board", "rim"}:
                    mat["nba_live_rms_runtime"] = SKIN_RMS[game]

        self.report(
            {'INFO'},
            f"Prepared imported backboard: {len(base)} BaseBackboard, {len(led)} led object(s). "
            "Run/verify weights, then tag the shot clock."
        )
        return {'FINISHED'}


class NBA_OT_backboard_mark_existing_weights(Operator):
    bl_idname = "nba.backboard_mark_existing_weights"
    bl_label = "Mark Existing Weights as Preserved"
    bl_description = (
        "Mark selected imported backboard meshes as using their current semantic "
        "Support/Board/Rim groups for future export"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = _mesh_objects(context)
        if not objs:
            self.report({'ERROR'}, "Select imported backboard mesh object(s).")
            return {'CANCELLED'}

        bad = []
        for obj in objs:
            for v in obj.data.vertices:
                w = _semantic_weights_for_vertex(obj, v.index)
                if len(w) != 1 or abs(w[0][1] - 1.0) > 1.0e-4:
                    bad.append(obj.name)
                    break

        if bad:
            self.report(
                {'ERROR'},
                "Cannot mark preserved; invalid rigid semantic weights on: "
                + ", ".join(sorted(set(bad))[:6])
            )
            return {'CANCELLED'}

        for obj in objs:
            obj["nba_live_backboard_weights_preserved"] = True

        self.report(
            {'INFO'},
            f"Marked current rigid weights as preserved on {len(objs)} mesh(es)."
        )
        return {'FINISHED'}


def _semantic_bone_id(obj, vertex_index):
    weights = _semantic_weights_for_vertex(obj, vertex_index)
    if len(weights) != 1 or abs(weights[0][1] - 1.0) > 1.0e-4:
        raise ValueError(
            f"{obj.name}: vertex {vertex_index} must have exactly one rigid "
            "Backboard_Support/Board/Rim weight at 1.0."
        )
    return {
        GROUP_SUPPORT: 1,
        GROUP_BOARD: 2,
        GROUP_RIM: 3,
    }[weights[0][0]]


def _material_texture_name(mat):
    explicit = mat.get("nba_live_texture_name")
    if explicit:
        return str(explicit)
    return _normalized_material_asset_name(mat.name)


def _material_runtime(mat, game):
    """Choose the runtime for one backboard material.

    Shot-clock materials stay authoritative because they require their
    game-specific skinned runtime. Ordinary backboard materials use the normal
    skin runtime unless the visible material name explicitly requests the
    verified ``[ScrollTextureDim]`` runtime, e.g. ``odrn [ScrollTextureDim]``.

    Imported ``nba_live_rms_runtime`` metadata is intentionally ignored here so
    stale metadata from another game cannot silently override the chosen target.
    """
    role = str(mat.get("nba_live_backboard_role", ""))
    if role in {"time", "tnum"} or "nba_live_shotclock_uv_index" in mat:
        return SHOTCLOCK_RMS[game]

    name = str(mat.name or "").strip()
    match = re.search(r"\[([A-Za-z0-9_]+)\]\s*$", name)
    if match and match.group(1).lower() == "scrolltexturedim":
        return "gScrollTextureDim_RMRuntime"

    return SKIN_RMS[game]


def _corner_normal(mesh, loop_index, vertex_index):
    try:
        n = mesh.corner_normals[loop_index].vector
        return n.copy()
    except Exception:
        return mesh.vertices[vertex_index].normal.copy()


def _strip_from_triangles(tris):
    if not tris:
        raise ValueError("Material slot has no usable triangles.")
    out = list(tris[0])
    for a, b, c in tris[1:]:
        x, y = (b, a) if ((len(out) + 2) & 1) else (a, b)
        out.extend((out[-1], x, x, y, c))
    return tuple(out)


def _compile_backboard_object(obj, game):
    mesh = obj.data
    mesh.calc_loop_triangles()
    uv_layer = mesh.uv_layers[0] if mesh.uv_layers else None
    matrix = obj.matrix_world
    normal_matrix = matrix.to_3x3()

    batches = []
    for slot_index, slot in enumerate(obj.material_slots):
        mat = slot.material
        if mat is None:
            continue
        tris = [t for t in mesh.loop_triangles if t.material_index == slot_index]
        if not tris:
            continue

        texture = _material_texture_name(mat)
        runtime = _material_runtime(mat, game)
        shot = "nba_live_shotclock_uv_index" in mat
        uv_index = int(mat["nba_live_shotclock_uv_index"]) if shot else None

        lookup = {}
        positions = []
        normals = []
        uvs = []
        bones = []
        out_tris = []

        for tri in tris:
            tri_out = []
            for li in tri.loops:
                vi = mesh.loops[li].vertex_index
                bone = _semantic_bone_id(obj, vi)

                if shot and bone != 2:
                    raise ValueError(
                        f"{obj.name}/{mat.name}: shot-clock vertices must use "
                        f"{GROUP_BOARD} (bone 2); vertex {vi} uses bone {bone}."
                    )

                if uv_layer is None:
                    uv = (0.0, 0.0)
                else:
                    raw = uv_layer.data[li].uv
                    uv = (float(raw.x), 1.0 - float(raw.y))

                n = _corner_normal(mesh, li, vi)
                n = normal_matrix @ n
                if n.length_squared > 0.0:
                    n.normalize()

                key = (
                    vi,
                    round(uv[0], 9), round(uv[1], 9),
                    round(float(n.x), 7), round(float(n.y), 7), round(float(n.z), 7),
                    bone,
                )
                oi = lookup.get(key)
                if oi is None:
                    co = matrix @ mesh.vertices[vi].co
                    oi = len(positions)
                    lookup[key] = oi
                    positions.append((float(co.x), float(co.z), -float(co.y)))
                    normals.append((float(n.x), float(n.z), -float(n.y)))
                    uvs.append(uv)
                    bones.append(bone)
                tri_out.append(oi)

            if len(set(tri_out)) == 3:
                out_tris.append(tuple(tri_out))

        if not out_tris:
            continue

        palette = []
        for bone in bones:
            if bone not in palette:
                palette.append(bone)
        local = {bone: i for i, bone in enumerate(palette)}
        palette_indices = tuple(local[b] for b in bones)
        strip = _strip_from_triangles(out_tris)

        batches.append(
            ebo_backboard.BackboardBatch(
                texture=texture,
                positions=tuple(positions),
                normals=tuple(normals),
                uvs=tuple(uvs),
                palette_bones=tuple(palette),
                palette_indices=palette_indices,
                strip=strip,
                runtime=runtime,
                uv_index=uv_index,
            )
        )

    if not batches:
        raise ValueError(f"{obj.name}: no usable material faces.")
    return tuple(batches)


def _reference_geometry_flags(path):
    data = Path(path).read_bytes()
    if len(data) < 0x60 or data[:4] != b"EBO\0":
        raise ValueError("Reference Backboard EBO is not a valid EBO v17 file.")

    (
        _magic, version, declared, _eo, _ec,
        _chunks, _usd, _imports, exports_off, strings_off,
        _nchunks, _nusd, _nimports, export_count, string_count,
    ) = struct.unpack_from("<IIIHHIIIIIHHHHH", data, 0)

    if version != 17 or declared != len(data):
        raise ValueError("Reference Backboard EBO must be a valid version-17 EBO.")

    pos = strings_off + 4
    strings = {}
    for _ in range(string_count):
        end = data.find(b"\0", pos)
        if end < 0:
            raise ValueError("Reference EBO has a broken string table.")
        name = data[pos:end].decode("ascii")
        strings[pos - strings_off] = name
        raw_len = end - pos + 1
        pos = end + 1 + (raw_len & 1)

    flags = {}
    for i in range(export_count):
        off = exports_off + i * 12
        _type_rel, name_rel, data_rel = struct.unpack_from("<IIi", data, off)
        name = strings.get(name_rel)
        geo = off + data_rel
        if name in {"BaseBackboard", "led"} and geo + 0x3C <= len(data):
            flags[name] = struct.unpack_from("<I", data, geo + 0x38)[0]

    if "BaseBackboard" not in flags or "led" not in flags:
        raise ValueError(
            "Reference EBO must export both BaseBackboard and led Geometry."
        )
    return flags


def _validate_export_scene(context):
    objs = _mesh_objects(context)
    base = [o for o in objs if _looks_like_existing_backboard(o)]
    led = [o for o in objs if _looks_like_led(o)]
    if len(base) != 1 or len(led) != 1:
        raise ValueError(
            "Select exactly one BaseBackboard mesh and exactly one led mesh for export."
        )

    # All vertices must satisfy the rigid semantic contract.
    for obj in (base[0], led[0]):
        for v in obj.data.vertices:
            _semantic_bone_id(obj, v.index)

    # BaseBackboard must contain the full six-batch dynamic clock contract.
    found = []
    for slot in base[0].material_slots:
        mat = slot.material
        if mat is None or "nba_live_shotclock_uv_index" not in mat:
            continue
        role = str(mat.get("nba_live_backboard_role", ""))
        idx = int(mat["nba_live_shotclock_uv_index"])
        found.append((role, idx))

    expected = [
        ("time", 0), ("time", 1), ("time", 2), ("time", 3),
        ("tnum", 5), ("tnum", 4),
    ]
    if sorted(found) != sorted(expected) or len(found) != 6:
        raise ValueError(
            "BaseBackboard shot-clock contract is incomplete. "
            "Run Tag Shot Clock Materials and Validate Shot Clock first."
        )
    return base[0], led[0]


class NBA_OT_export_backboard_ebo(Operator, ExportHelper):
    bl_idname = "nba.export_backboard_ebo"
    bl_label = "Export Backboard EBO"
    bl_description = (
        "Compile BaseBackboard + led with rigid skin weights and the six dynamic "
        "shot-clock materials into an NBA Live EBO"
    )
    bl_options = {'REGISTER'}
    filename_ext = ".ebo"
    filter_glob: StringProperty(default="*.ebo", options={'HIDDEN'})

    def invoke(self, context, event):
        base = context.active_object
        name = "backboard"
        if base is not None:
            name = str(base.get("nba_live_output_name", base.name))
            if name.lower().startswith("basebackboard"):
                name = "backboard"
        self.filepath = str(Path(bpy.path.abspath("//")) / f"{name}.ebo")
        return super().invoke(context, event)

    def execute(self, context):
        game = _backboard_game(context)
        reference_raw = context.scene.nba_live_backboard_reference
        if not reference_raw:
            self.report({'ERROR'}, "Choose a Reference Backboard EBO first.")
            return {'CANCELLED'}

        reference = Path(bpy.path.abspath(reference_raw)).resolve()
        if not reference.is_file():
            self.report({'ERROR'}, f"Reference Backboard EBO not found: {reference}")
            return {'CANCELLED'}

        try:
            base_obj, led_obj = _validate_export_scene(context)
            flags = _reference_geometry_flags(reference)

            base_batches = _compile_backboard_object(base_obj, game)
            led_batches = _compile_backboard_object(led_obj, game)

            geos = (
                ebo_backboard.BackboardGeometry(
                    "BaseBackboard", base_batches, flags["BaseBackboard"]
                ),
                ebo_backboard.BackboardGeometry(
                    "led", led_batches, flags["led"]
                ),
            )
            output = ebo_backboard.build_backboard_ebo(geos)

            # Basic output validation before touching the user's destination.
            if output[:4] != b"EBO\0":
                raise ValueError("Internal backboard compiler produced an invalid EBO header.")
            declared = struct.unpack_from("<I", output, 8)[0]
            if declared != len(output):
                raise ValueError(
                    f"Internal backboard compiler size mismatch: {declared} != {len(output)}."
                )

            destination = Path(self.filepath).resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(output)

        except (ValueError, OSError) as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Exported {destination.name}: "
            f"{len(base_batches)} BaseBackboard material(s), "
            f"{len(led_batches)} led material(s), {len(output)} bytes."
        )
        return {'FINISHED'}


def _parse_int_prop(value):
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return int(value.strip(), 0)
    raise ValueError(f"Unsupported integer property value: {value!r}")


def _resolve_geometry_flags(obj, game, profile, reference_path=None):
    """Resolve Geometry flags without requiring a donor EBO.

    Priority:
      1. obj['nba_live_geometry_flags']
      2. optional reference EBO
      3. verified 06 default
    """
    if obj is not None and "nba_live_geometry_flags" in obj:
        return _parse_int_prop(obj["nba_live_geometry_flags"])

    if reference_path:
        rp=Path(reference_path)
        if rp.is_file():
            try:
                if profile=="main":
                    return _reference_geometry_flags(rp)["BaseBackboard"]
                return _geometry_flag_from_reference(rp)
            except Exception:
                pass

    return DEFAULT_GEOMETRY_FLAGS[game][profile]


def _collection_meshes(context, collection_name):
    col=bpy.data.collections.get(collection_name)
    if col is None:
        return []
    return [o for o in col.all_objects if o.type=='MESH']


def _reference_siblings(main_reference):
    main=Path(main_reference)
    stem=main.stem
    return {
        "main": main,
        "trans": main.with_name(stem+"_trans.ebo"),
        "refl": main.with_name(stem+"_refl.ebo"),
        "main_fsh": main.with_suffix(".fsh"),
        "refl_fsh": main.with_name(stem+"_refl.fsh"),
        # NBA Live 2005 additionally uses <stem>_shad.ebo.
        # NBA Live 06 does not.
        "shad": main.with_name(stem+"_shad.ebo"),
    }


def _geometry_flag_from_reference(path, geometry_name="BaseBackboard"):
    data=Path(path).read_bytes()
    if data[:4] != b"EBO\0":
        raise ValueError(f"{Path(path).name}: invalid EBO.")
    (_magic,_ver,_size,_eo,_ec,_chunks,_usd,_imports,exports_off,strings_off,
     _nc,_nu,_ni,export_count,string_count)=struct.unpack_from("<IIIHHIIIIIHHHHH",data,0)
    pos=strings_off+4; strings={}
    for _ in range(string_count):
        end=data.find(b"\0",pos)
        s=data[pos:end].decode("ascii")
        strings[pos-strings_off]=s
        raw=end-pos+1; pos=end+1+(raw&1)
    for i in range(export_count):
        off=exports_off+i*12
        _tr,nr,rel=struct.unpack_from("<IIi",data,off)
        if strings.get(nr)==geometry_name:
            go=off+rel
            return struct.unpack_from("<I",data,go+0x38)[0]
    raise ValueError(f"{Path(path).name}: Geometry {geometry_name!r} not found.")


def _first_color_layer(mesh):
    attrs=getattr(mesh,"color_attributes",None)
    if not attrs:
        return None
    preferred=attrs.get("NBA Live Vertex Colors")
    if preferred is not None:
        return preferred
    for a in attrs:
        if a.domain in {'POINT','CORNER'}:
            return a
    return None


def _vertex_color_byte(mesh, layer, vertex_index, loop_index):
    if layer is None:
        return (255,255,255,255)
    item=layer.data[vertex_index if layer.domain=='POINT' else loop_index]
    c=item.color
    return tuple(max(0,min(255,int(round(float(v)*255.0)))) for v in c[:4])


def _compile_variant_objects(objects, profile):
    batches=[]
    for obj in objects:
        mesh=obj.data
        mesh.calc_loop_triangles()
        uv_layer=mesh.uv_layers[0] if mesh.uv_layers else None
        color_layer=_first_color_layer(mesh)
        matrix=obj.matrix_world
        normal_matrix=matrix.to_3x3()

        for slot_index,slot in enumerate(obj.material_slots):
            mat=slot.material
            if mat is None:
                continue
            tris=[t for t in mesh.loop_triangles if t.material_index==slot_index]
            if not tris:
                continue

            texture=_material_texture_name(mat) if profile!="shad" else None
            lookup={}; positions=[]; normals=[]; uvs=[]; colors=[]; bones=[]; out_tris=[]

            for tri in tris:
                ot=[]
                for li in tri.loops:
                    vi=mesh.loops[li].vertex_index
                    bone=_semantic_bone_id(obj,vi)

                    co=matrix @ mesh.vertices[vi].co
                    pos=(float(co.x),float(co.z),-float(co.y))

                    if uv_layer is None:
                        uv=(0.0,0.0)
                    else:
                        q=uv_layer.data[li].uv
                        uv=(float(q.x),1.0-float(q.y))

                    n=_corner_normal(mesh,li,vi)
                    n=normal_matrix @ n
                    if n.length_squared>0:n.normalize()
                    nor=(float(n.x),float(n.z),-float(n.y))
                    col=_vertex_color_byte(mesh,color_layer,vi,li)

                    if profile=="trans":
                        key=(vi,tuple(round(x,8) for x in uv),tuple(round(x,7) for x in nor),bone)
                    elif profile=="refl":
                        key=(vi,tuple(round(x,8) for x in uv),col,bone)
                    else:
                        key=(vi,col,bone)

                    oi=lookup.get(key)
                    if oi is None:
                        oi=len(positions); lookup[key]=oi
                        positions.append(pos); bones.append(bone)
                        if profile=="trans": normals.append(nor); uvs.append(uv)
                        elif profile=="refl": uvs.append(uv); colors.append(col)
                        else: colors.append(col)
                    ot.append(oi)
                if len(set(ot))==3:
                    out_tris.append(tuple(ot))

            palette=[]
            for bone in bones:
                if bone not in palette: palette.append(bone)
            local={bone:i for i,bone in enumerate(palette)}
            pidx=tuple(local[b] for b in bones)
            strip=_strip_from_triangles(out_tris)

            batches.append(
                ebo_backboard_variants.VariantBatch(
                    texture=texture,
                    positions=tuple(positions),
                    normals=tuple(normals) if profile=="trans" else None,
                    uvs=tuple(uvs) if profile in ("trans","refl") else None,
                    colors=tuple(colors) if profile in ("refl","shad") else None,
                    palette_bones=tuple(palette),
                    palette_indices=pidx,
                    strip=strip,
                )
            )
    if not batches:
        raise ValueError(f"Collection for {profile} produced no material batches.")
    return tuple(batches)


def _material_image_path(mat):
    # Explicit override first.
    raw=mat.get("nba_live_texture_path")
    if raw:
        p=Path(bpy.path.abspath(str(raw))).resolve()
        if p.is_file(): return p

    if mat.use_nodes and mat.node_tree:
        for node in mat.node_tree.nodes:
            if node.type=="TEX_IMAGE" and getattr(node,"image",None):
                raw=node.image.filepath
                if raw:
                    p=Path(bpy.path.abspath(raw)).resolve()
                    if p.is_file(): return p
    return None


def _texture_inputs(objects):
    result={}
    for obj in objects:
        for slot in obj.material_slots:
            mat=slot.material
            if mat is None: continue
            name=_material_texture_name(mat)
            p=_material_image_path(mat)
            if p is None:
                continue
            prev=result.get(name)
            if prev is not None and prev != p:
                raise ValueError(f"TextureName {name!r} maps to two different images.")
            result[name]=p
    return result


def _base_output_name(filepath):
    p=Path(filepath)
    s=p.stem
    for suffix in ("_trans","_refl","_shad"):
        if s.lower().endswith(suffix):
            s=s[:-len(suffix)]
    return s


class NBA_OT_export_backboard_package(Operator, ExportHelper):
    bl_idname="nba.export_backboard_package"
    bl_label="Export Backboard Package"
    bl_description="Export NBA Live 05/06 backboard package plus native FSH files"
    bl_options={'REGISTER'}
    filename_ext=".ebo"
    filter_glob:StringProperty(default="*.ebo",options={'HIDDEN'})

    def invoke(self,context,event):
        self.filepath=str(Path(bpy.path.abspath("//"))/"custombbd.ebo")
        return super().invoke(context,event)

    def execute(self,context):
        game=_backboard_game(context)
        reference_raw=context.scene.nba_live_backboard_reference
        refs=None
        if reference_raw:
            ref_main=Path(bpy.path.abspath(reference_raw)).resolve()
            if ref_main.is_file():
                refs=_reference_siblings(ref_main)

        main_objs=_collection_meshes(context,"bbd")
        trans_objs=_collection_meshes(context,"bbd_trans")
        refl_objs=_collection_meshes(context,"bbd_refl")
        shad_objs=_collection_meshes(context,"bbd_shad") if game=="2005" else []
        missing=[]
        if not main_objs: missing.append("bbd")
        if not trans_objs: missing.append("bbd_trans")
        if not refl_objs: missing.append("bbd_refl")
        if game=="2005" and not shad_objs: missing.append("bbd_shad")
        if missing:
            self.report(
                {'ERROR'},
                "Create/populate collection(s): " + ", ".join(missing)
            )
            return {'CANCELLED'}

        # main needs BaseBackboard + led specifically.
        base=[o for o in main_objs if _looks_like_existing_backboard(o)]
        led=[o for o in main_objs if _looks_like_led(o)]
        if len(base)!=1 or len(led)!=1:
            self.report({'ERROR'},"Collection bbd must contain exactly one BaseBackboard and one led mesh.")
            return {'CANCELLED'}

        try:
            # validate all rigid weights
            for obj in main_objs+trans_objs+refl_objs+shad_objs:
                for v in obj.data.vertices:
                    _semantic_bone_id(obj,v.index)

            ref_main = refs["main"] if refs else None
            main_flag = _resolve_geometry_flags(base[0], game, "main", ref_main)
            led_flag = _resolve_geometry_flags(led[0], game, "main", ref_main)
            main_geos=(
                ebo_backboard.BackboardGeometry(
                    "BaseBackboard",_compile_backboard_object(base[0],game),main_flag
                ),
                ebo_backboard.BackboardGeometry(
                    "led",_compile_backboard_object(led[0],game),led_flag
                ),
            )
            main_data=ebo_backboard.build_backboard_ebo(main_geos)

            trans_batches=_compile_variant_objects(trans_objs,"trans")
            refl_batches=_compile_variant_objects(refl_objs,"refl")
            shad_batches=_compile_variant_objects(shad_objs,"shad") if game=="2005" else ()

            trans_flag = _resolve_geometry_flags(
                trans_objs[0], game, "trans", refs["trans"] if refs else None
            )
            refl_flag = _resolve_geometry_flags(
                refl_objs[0], game, "refl", refs["refl"] if refs else None
            )

            if game=="2005":
                trans_data=ebo_backboard_variants.build_trans_2005_ebo(
                    trans_batches,trans_flag
                )
            else:
                trans_data=ebo_backboard_variants.build_trans_ebo(
                    trans_batches,trans_flag
                )

            refl_data=ebo_backboard_variants.build_refl_ebo(
                refl_batches,refl_flag
            )

            shad_data=None
            if game=="2005":
                shad_flag = _resolve_geometry_flags(
                    shad_objs[0], game, "shad", refs["shad"] if refs else None
                )
                shad_data=ebo_backboard_variants.build_shad_ebo(
                    shad_batches,shad_flag
                )
            outmain=Path(self.filepath).resolve()
            outdir=outmain.parent
            base_name=_base_output_name(outmain)
            main_path=outdir/f"{base_name}.ebo"
            trans_path=outdir/f"{base_name}_trans.ebo"
            refl_path=outdir/f"{base_name}_refl.ebo"
            shad_path=outdir/f"{base_name}_shad.ebo" if game=="2005" else None
            main_path.write_bytes(main_data)
            trans_path.write_bytes(trans_data)
            refl_path.write_bytes(refl_data)
            if shad_path is not None and shad_data is not None:
                shad_path.write_bytes(shad_data)

            # Main FSH owns textures used by main + trans.
            # New Blender images are packed natively. Imported materials with no
            # Blender image (e.g. time/tnum) fall back to the original reference
            # FSH entry and are preserved byte-for-byte.
            main_textures=_texture_inputs(main_objs+trans_objs)
            required_main_names={
                b.texture for g in main_geos for b in g.batches
            } | {
                b.texture for b in trans_batches if b.texture
            }
            synthetic_fsh.create_native_fsh_merged(
                main_textures,
                outdir/f"{base_name}.fsh",
                reference_fsh=(refs["main_fsh"] if refs and refs["main_fsh"].is_file() else None),
                required_names=required_main_names,
            )

            # Reflection FSH follows the actual bbd_refl materials.
            # Real Blender images are preferred. If a refl TextureName matches
            # the newly generated main FSH, preserve/copy that real entry.
            refl_textures=_texture_inputs(refl_objs)
            refl_names={b.texture for b in refl_batches if b.texture}
            synthetic_fsh.create_native_fsh_merged(
                refl_textures,
                outdir/f"{base_name}_refl.fsh",
                reference_fsh=outdir/f"{base_name}.fsh",
                required_names=refl_names,
            )

        except (ValueError,OSError,synthetic_fsh.SyntheticFshError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Created NBA Live {game} {base_name}: main/trans/refl" + (" /shad" if game=="2005" else "") + " EBO + FSH + refl FSH."
        )
        return {'FINISHED'}


class NBA_PT_backboard_tools(Panel):
    bl_label = "Backboard EBO"
    bl_options = {'DEFAULT_CLOSED'}
    bl_idname = "NBA_PT_backboard_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'NBA Live'

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.prop(context.scene, "nba_live_backboard_mode", text="Backboard Mode")
        if not context.scene.nba_live_backboard_mode:
            return

        box.prop(context.scene, "nba_live_backboard_2005", text="NBA Live 2005")
        game = _backboard_game(context)
        box.label(text=f"Target: NBA Live {game}")
        box.label(text=f"Skin RMS: {SKIN_RMS[game]}")
        box.label(text=f"Shot clock RMS: {SHOTCLOCK_RMS[game]}")

        existing = layout.box()
        existing.label(text="Existing Imported Backboard")
        existing.operator(NBA_OT_backboard_prepare_existing.bl_idname)
        existing.label(text="Keeps BaseBackboard/led + EBO.* material names")

        weights = layout.box()
        weights.label(text="Rigid Skin Weights")
        weights.operator(NBA_OT_backboard_create_groups.bl_idname)
        row = weights.row(align=True)
        row.operator(NBA_OT_assign_backboard_support.bl_idname)
        row.operator(NBA_OT_assign_backboard_board.bl_idname)
        row.operator(NBA_OT_assign_backboard_rim.bl_idname)
        weights.operator(NBA_OT_backboard_transfer_weights.bl_idname)
        weights.operator(NBA_OT_backboard_validate_weights.bl_idname)
        weights.operator(NBA_OT_backboard_mark_existing_weights.bl_idname)
        weights.label(text="Support = bone 1")
        weights.label(text="Board/clock = bone 2")
        weights.label(text="Rim = bone 3")

        shot = layout.box()
        shot.label(text="Dynamic Shot Clock")
        shot.operator(NBA_OT_backboard_tag_shotclock.bl_idname)
        shot.operator(NBA_OT_backboard_validate_shotclock.bl_idname)
        shot.label(text="4 x time: UV index 0,1,2,3")
        shot.label(text="2 x tnum: UV index 5,4")
        shot.label(text="All six attach to Backboard_Board")

        export = layout.box()
        export.label(text="Backboard EBO Export")
        export.prop(context.scene, "nba_live_backboard_reference", text="Reference EBO")
        export.label(text="Single EBO: select BaseBackboard + led")
        export.operator(NBA_OT_export_backboard_ebo.bl_idname, icon='EXPORT')

        package = layout.box()
        package.label(text=f"NBA Live {game} Backboard Package")
        if game == "2005":
            package.label(text="Collections: bbd / bbd_trans / bbd_refl / bbd_shad")
            package.label(text="2005 requires the shadow model.", icon='INFO')
        else:
            package.label(text="Collections: bbd / bbd_trans / bbd_refl")
        package.label(text="Reference EBO is optional")
        package.operator(NBA_OT_export_backboard_package.bl_idname, icon='PACKAGE')

        info = layout.box()
        info.label(text="Backboard skin, shot clock and package export")


CLASSES = (
    NBA_OT_export_backboard_package,
    NBA_OT_export_backboard_ebo,
    NBA_OT_backboard_prepare_existing,
    NBA_OT_backboard_mark_existing_weights,
    NBA_OT_backboard_create_groups,
    NBA_OT_assign_backboard_support,
    NBA_OT_assign_backboard_board,
    NBA_OT_assign_backboard_rim,
    NBA_OT_backboard_transfer_weights,
    NBA_OT_backboard_validate_weights,
    NBA_OT_backboard_tag_shotclock,
    NBA_OT_backboard_validate_shotclock,
    NBA_PT_backboard_tools,
)


def register():
    bpy.types.Scene.nba_live_backboard_mode = BoolProperty(
        name="Backboard Mode",
        description="Enable NBA Live backboard skin and shot-clock tools",
        default=False,
    )
    bpy.types.Scene.nba_live_backboard_reference = StringProperty(
        name="Reference Backboard EBO",
        description=(
            "Known-good backboard EBO used for the exact game/stadium Geometry flags. "
            "Use the original backboard when editing/re-exporting an existing asset."
        ),
        subtype='FILE_PATH',
        default="",
    )
    bpy.types.Scene.nba_live_backboard_2005 = BoolProperty(
        name="NBA Live 2005",
        description="Use NBA Live 2005 backboard RMS profiles and require bbd_shad",
        default=False,
    )
    bpy.types.Scene.nba_live_backboard_game = EnumProperty(
        name="Backboard Game",
        items=(
            ('2006', 'NBA Live 06', 'gNbaBackboardSkin + gNbaShotClock'),
            ('2005', 'NBA Live 2005', 'DirectTextureSkin + gShotClock'),
        ),
        default='2006',
    )
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in ("nba_live_backboard_mode", "nba_live_backboard_2005", "nba_live_backboard_game", "nba_live_backboard_reference"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
