"""Blender import-only UI for Xbox EA Sports VIV/EBO/XSH assets."""

from __future__ import annotations

import json
from pathlib import Path
import struct

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

from . import blender_addon
from . import ebo_core
from . import fsh_archive
from . import xbox_assets


def _material_rms_types(court: ebo_core.Court) -> dict[tuple[str, int], str]:
    rows = {
        mesh.offset + 104 + batch.batch_index * 48: (mesh.name, batch.batch_index)
        for mesh in court.meshes
        for batch in mesh.batches
    }
    result: dict[tuple[str, int], str] = {}
    for group in ebo_core.external_variable_groups(court):
        if not group.name.startswith("g") or not group.name.endswith("_RMRuntime"):
            continue
        rms = group.name[1:-10]
        for target in group.targets:
            owner = rows.get(target)
            if owner is not None:
                result[owner] = rms
    return result


def _build_xbox_object(collection, court, mesh_record, materials):
    vertices = []
    edges = []
    faces = []
    face_batches = []
    vertex_uvs = []
    vertex_colors = []

    for batch in mesh_record.batches:
        base = len(vertices)

        for index in range(batch.vertex_count):
            position = struct.unpack_from(
                "<3f", court.data, batch.positions.data_offset + index * 12
            )
            u, v = struct.unpack_from(
                "<2f", court.data, batch.uvs.data_offset + index * 8
            )
            vertices.append(blender_addon._game_to_blender(position))
            vertex_uvs.append((u, 1.0 - v))

            if batch.colors is not None:
                blue, green, red, alpha = struct.unpack_from(
                    "<4B", court.data, batch.colors.data_offset + index * 4
                )
                vertex_colors.append(
                    (red / 255.0, green / 255.0, blue / 255.0, alpha / 255.0)
                )
            else:
                vertex_colors.append((1.0, 1.0, 1.0, 1.0))

        for triangle in batch.triangles:
            faces.append(tuple(base + index for index in triangle))
            face_batches.append(batch.batch_index)

    geometry = bpy.data.meshes.new(mesh_record.name)
    geometry.from_pydata(vertices, edges, faces)
    geometry.update()

    obj = bpy.data.objects.new(mesh_record.name, geometry)
    collection.objects.link(obj)
    obj["nba_live_mesh_name"] = mesh_record.name
    obj["nba_live_platform"] = "XBOX"
    obj["nba_live_import_only"] = True
    obj["nba_live_batch_materials"] = json.dumps(
        [batch.material for batch in mesh_record.batches]
    )

    for batch in mesh_record.batches:
        geometry.materials.append(materials[(mesh_record.name, batch.batch_index)])

    for polygon, batch_index in zip(geometry.polygons, face_batches):
        polygon.material_index = batch_index

    if geometry.loops:
        uv_layer = geometry.uv_layers.new(name=blender_addon.UV_LAYER)
        for polygon in geometry.polygons:
            for loop_index in polygon.loop_indices:
                vertex_index = geometry.loops[loop_index].vertex_index
                uv_layer.data[loop_index].uv = vertex_uvs[vertex_index]

    if vertices:
        colors = geometry.color_attributes.new(
            name=blender_addon.COLOR_LAYER,
            type="BYTE_COLOR",
            domain="POINT",
        )
        for index, color in enumerate(vertex_colors):
            blender_addon._write_color(colors.data[index], color)

    return obj


def import_xbox_asset(context, viv_path: str, asset_kind: str, import_textures: bool):
    source = Path(viv_path).resolve()
    viv_data = source.read_bytes()
    assets = xbox_assets.discover_viv_assets(viv_data)

    wanted_suffixes = {
        "STADIUM": ("std",),
        "STADIUM_TRANS": ("std_trans",),
        "COURT": ("crt",),
        "BACKBOARD": ("bbd",),
        "BACKBOARD_TRANS": ("bbd_trans",),
        "STADIUM_SET": ("std", "std_trans"),
        "BACKBOARD_SET": ("bbd", "bbd_trans"),
        "ALL": ("std", "std_trans", "crt", "bbd", "bbd_trans"),
    }[asset_kind]

    selected = [
        (stem, members)
        for stem, members in sorted(assets.items())
        if stem.casefold().endswith(wanted_suffixes)
    ]
    if not selected:
        raise xbox_assets.XboxAssetError(
            f"{source.name} does not contain a matching Xbox {asset_kind.lower()} EBO."
        )

    imported_collections = []
    total_objects = 0
    total_textures = 0

    texture_root = source.parent / "nba_live_xbox_textures" / source.stem

    for stem, members in selected:
        ebo_data = xbox_assets.member_bytes(viv_data, members["ebo"])
        court = xbox_assets.parse_xbox_ebo(ebo_data)
        ebo_core.validate_material_bindings(court)

        texture_paths: dict[str, Path] = {}
        if import_textures:
            for key, member in members.items():
                if key == "ebo":
                    continue
                xsh_data = xbox_assets.member_bytes(viv_data, member)
                folder = texture_root / stem / Path(member.name).stem
                texture_paths.update(xbox_assets.extract_xsh_bytes(xsh_data, folder))

        collection = bpy.data.collections.new(f"{stem} [Xbox]")
        context.scene.collection.children.link(collection)
        collection["nba_live_platform"] = "XBOX"
        collection["nba_live_import_only"] = True
        collection["nba_live_viv_source"] = str(source)
        collection["nba_live_asset_name"] = stem

        rms_types = _material_rms_types(court)
        materials = {}
        shared = {}

        for batch in court.batches:
            key = (batch.mesh_name, batch.batch_index)
            rms = rms_types.get(key, "")
            texture = texture_paths.get(batch.material)
            shared_key = (batch.material, rms, str(texture) if texture else "")
            material = shared.get(shared_key)
            if material is None:
                if texture is None:
                    placeholder = texture_root / stem / "_missing" / (
                        f"{fsh_archive.working_texture_name(batch.material)}.png"
                    )
                    fsh_archive.ensure_placeholder_png(placeholder)
                    texture = placeholder
                    is_placeholder = True
                else:
                    is_placeholder = False

                # Xbox imports are deliberately marked transparent-capable in
                # Blender. This only affects viewport material display; there
                # is no Xbox export path.
                material = blender_addon._material(
                    stem,
                    batch.material,
                    (),
                    texture,
                    transparent=True,
                    rms_type=rms or None,
                    has_vertex_colors=True,
                    extend_uvs=False,
                    textureless=False,
                    placeholder=is_placeholder,
                )
                material["nba_live_platform"] = "XBOX"
                material["nba_live_import_only"] = True
                shared[shared_key] = material
            materials[key] = material

        for mesh_record in court.meshes:
            _build_xbox_object(collection, court, mesh_record, materials)

        imported_collections.append(collection)
        total_objects += len(court.meshes)
        total_textures += len(texture_paths)

    if imported_collections:
        first = next(iter(imported_collections[0].objects), None)
        if first is not None:
            context.view_layer.objects.active = first
        for collection in imported_collections:
            for obj in collection.objects:
                obj.select_set(True)

    return imported_collections, total_objects, total_textures


class NBA_OT_import_xbox_viv(bpy.types.Operator, ImportHelper):
    bl_idname = "nba_live.import_xbox_viv"
    bl_label = "Import Xbox VIV"
    bl_description = (
        "Import Xbox EA Sports stadium/court EBO geometry and supported XSH textures; import only"
    )
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".viv"
    filter_glob: StringProperty(default="*.viv;*.big", options={"HIDDEN"})

    asset_kind: EnumProperty(
        name="Asset",
        items=(
            ("STADIUM", "Stadium (std)", "Import the *std.ebo model"),
            ("STADIUM_TRANS", "Stadium Transparent (std_trans)", "Import the *std_trans.ebo model"),
            ("COURT", "Court (crt)", "Import the *crt.ebo model"),
            ("BACKBOARD", "Backboard (bbd)", "Import the *bbd.ebo model"),
            ("BACKBOARD_TRANS", "Backboard Transparent (bbd_trans)", "Import the *bbd_trans.ebo model"),
            ("STADIUM_SET", "Stadium + Transparent", "Import std and std_trans"),
            ("BACKBOARD_SET", "Backboard + Transparent", "Import bbd and bbd_trans"),
            ("ALL", "All Supported Arena Models", "Import std, std_trans, crt, bbd and bbd_trans"),
        ),
        default="STADIUM",
    )
    import_textures: BoolProperty(
        name="Extract XSH Textures",
        description="Decode supported Xbox XSH textures and assign them in Blender",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "asset_kind")
        layout.prop(self, "import_textures")
        box = layout.box()
        box.label(text="Xbox import only", icon="INFO")
        box.label(text="No Xbox EBO/XSH export or repacking is performed")

    def execute(self, context):
        try:
            collections, objects, textures = import_xbox_asset(
                context,
                self.filepath,
                self.asset_kind,
                self.import_textures,
            )
        except (
            xbox_assets.XboxAssetError,
            ebo_core.CourtFormatError,
            fsh_archive.FshError,
            OSError,
            struct.error,
            UnicodeDecodeError,
        ) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        names = ", ".join(collection.name for collection in collections)
        self.report(
            {"INFO"},
            f"Imported {objects} Xbox objects into {names}; decoded {textures} textures",
        )
        return {"FINISHED"}


class NBA_PT_xbox_import(bpy.types.Panel):
    bl_label = "Xbox Import"
    bl_idname = "NBA_PT_xbox_import"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NBA Live"
    bl_parent_id = "NBA_PT_environment_panel"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.operator("nba_live.import_xbox_viv", icon="IMPORT")
        layout.label(text="NBA Live / NCAA Xbox VIV", icon="INFO")
        layout.label(text="Import only — no Xbox export")


CLASSES = (
    NBA_OT_import_xbox_viv,
    NBA_PT_xbox_import,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
