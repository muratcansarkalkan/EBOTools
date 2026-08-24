"""Blender integration for NBA Live 2005/2006 player head EBO files."""

from pathlib import Path

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import ebo_core


bl_info = {
    "name": "NBA Live EBO Tools",
    "author": "EBO Tools 2026",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > NBA Live",
    "description": "Import and export NBA Live 2005/2006 player head EBO files",
    "category": "Import-Export",
}

EA_VERTEX_ID = "ea_vertex_id"
EA_ORIGINAL_POSITION = "ea_original_position"
PROP_GAME_YEAR = "nba_live_game_year"
PROP_SOURCE_EBO = "nba_live_source_ebo"
PROP_SOURCE_HASH = "nba_live_source_sha256"
PROP_BASE_EBO = "nba_live_base_ebo"


def _preferences(context):
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def resolve_base_path(context, year: str) -> Path:
    preferences = _preferences(context)
    override = ""
    if preferences:
        override = preferences.base_2005_path if year == "2005" else preferences.base_2006_path
    if override:
        path = Path(bpy.path.abspath(override)).expanduser()
        if not path.is_file():
            raise ebo_core.EBOError(f"Configured NBA Live {year} base file does not exist: {path}")
        return path.resolve()

    filename = ebo_core.BASE_FILENAMES[year]
    addon_directory = Path(__file__).resolve().parent
    for candidate in (addon_directory / "bases" / filename, addon_directory / filename):
        if candidate.is_file():
            return candidate.resolve()

    raise ebo_core.EBOError(
        f"Missing NBA Live {year} base model. Put {filename} in the add-on's bases "
        "folder, or configure its location in the add-on preferences."
    )


def _active_ebo_object(context):
    obj = context.active_object
    if obj is None or obj.type != "MESH":
        return None
    if obj.get(PROP_GAME_YEAR) not in ebo_core.GAME_VERTEX_COUNTS:
        return None
    return obj


def _create_head_object(context, player, player_path: Path, base_path: Path):
    mesh = bpy.data.meshes.new(f"{player_path.stem}_Head")
    mesh.from_pydata(player.vertices, [], player.faces)
    mesh.update()

    vertex_ids = mesh.attributes.new(name=EA_VERTEX_ID, type="INT", domain="POINT")
    original_positions = mesh.attributes.new(
        name=EA_ORIGINAL_POSITION,
        type="FLOAT_VECTOR",
        domain="POINT",
    )
    for index, position in enumerate(player.vertices):
        vertex_ids.data[index].value = index
        original_positions.data[index].vector = position

    uv_layer = mesh.uv_layers.new(name="UVMap")
    for polygon in mesh.polygons:
        for loop_index in polygon.loop_indices:
            vertex_index = mesh.loops[loop_index].vertex_index
            uv_layer.data[loop_index].uv = player.uvs[vertex_index]

    obj = bpy.data.objects.new(player_path.stem, mesh)
    context.collection.objects.link(obj)
    obj[PROP_GAME_YEAR] = player.year
    obj[PROP_SOURCE_EBO] = str(player_path.resolve())
    obj[PROP_SOURCE_HASH] = player.source_sha256
    obj[PROP_BASE_EBO] = str(base_path.resolve())

    if context.object and context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj
    return obj


def _ordered_vertex_positions(obj):
    if obj.mode == "EDIT":
        obj.update_from_editmode()

    mesh = obj.data
    year = obj[PROP_GAME_YEAR]
    expected = ebo_core.GAME_VERTEX_COUNTS[year]
    if len(mesh.vertices) != expected:
        raise ebo_core.EBOError(
            f"NBA Live {year} requires exactly {expected} vertices; the mesh now has "
            f"{len(mesh.vertices)}. Do not add, delete, merge, or subdivide vertices."
        )

    ids = mesh.attributes.get(EA_VERTEX_ID)
    originals = mesh.attributes.get(EA_ORIGINAL_POSITION)
    if ids is None or originals is None:
        raise ebo_core.EBOError(
            "Original EA vertex metadata is missing. Reimport the player EBO before editing."
        )

    edited = [None] * expected
    imported = [None] * expected
    for vertex in mesh.vertices:
        original_id = int(ids.data[vertex.index].value)
        if not 0 <= original_id < expected or edited[original_id] is not None:
            raise ebo_core.EBOError(
                f"Invalid or duplicate EA vertex ID {original_id}; original topology must remain unchanged."
            )
        edited[original_id] = tuple(float(value) for value in vertex.co)
        imported[original_id] = tuple(float(value) for value in originals.data[vertex.index].vector)

    if any(row is None for row in edited):
        raise ebo_core.EBOError("One or more original EA vertex IDs are missing from the mesh.")
    return edited, imported


class NBA_LIVE_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    base_2005_path: StringProperty(
        name="NBA Live 2005 Base EBO",
        description="Optional location of base_lodB_05.ebo",
        subtype="FILE_PATH",
    )
    base_2006_path: StringProperty(
        name="NBA Live 2006 Base EBO",
        description="Optional location of base_lodB.ebo",
        subtype="FILE_PATH",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="Set base-file paths, or place them in the add-on's bases folder.")
        layout.prop(self, "base_2005_path")
        layout.prop(self, "base_2006_path")
        layout.label(text=f"Bundled base folder: {Path(__file__).resolve().parent / 'bases'}")


class NBA_LIVE_OT_ImportPlayer(bpy.types.Operator, ImportHelper):
    bl_idname = "nba_live.import_player_ebo"
    bl_label = "Import Player EBO"
    bl_description = "Import an original NBA Live player head EBO as an editable mesh"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".ebo"
    filter_glob: StringProperty(default="*.ebo", options={"HIDDEN"})

    def execute(self, context):
        try:
            year = context.scene.nba_live_game_year
            base_path = resolve_base_path(context, year)
            player_path = Path(self.filepath).expanduser().resolve()
            player = ebo_core.import_player(base_path, player_path, year)
            obj = _create_head_object(context, player, player_path, base_path)
        except (ebo_core.EBOError, OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report(
            {"INFO"},
            f"Imported {obj.name}: NBA Live {year}, {len(player.vertices)} vertices, "
            f"{len(player.faces)} triangles",
        )
        return {"FINISHED"}


class NBA_LIVE_OT_ExportPlayer(bpy.types.Operator, ExportHelper):
    bl_idname = "nba_live.export_player_ebo"
    bl_label = "Export Edited EBO"
    bl_description = "Export the selected head using its remembered original player EBO"
    bl_options = {"REGISTER"}

    filename_ext = ".ebo"
    filter_glob: StringProperty(default="*.ebo", options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return _active_ebo_object(context) is not None

    def invoke(self, context, event):
        obj = _active_ebo_object(context)
        if obj and not self.filepath:
            original = Path(obj[PROP_SOURCE_EBO])
            self.filepath = str(original.with_name(f"{original.stem}_edited.ebo"))
        return super().invoke(context, event)

    def execute(self, context):
        try:
            obj = _active_ebo_object(context)
            if obj is None:
                raise ebo_core.EBOError("Select an imported NBA Live player head first.")

            year = obj[PROP_GAME_YEAR]
            source_path = Path(obj[PROP_SOURCE_EBO]).expanduser().resolve()
            base_path = Path(obj[PROP_BASE_EBO]).expanduser().resolve()
            destination = Path(self.filepath).expanduser().resolve()
            if destination == source_path:
                raise ebo_core.EBOError("Choose a different filename; the original player EBO cannot be overwritten.")

            edited, originals = _ordered_vertex_positions(obj)
            output, changed_count = ebo_core.export_player(
                base_path,
                source_path,
                year,
                edited,
                originals,
                expected_sha256=obj.get(PROP_SOURCE_HASH, ""),
            )
            destination.write_bytes(output)
        except (ebo_core.EBOError, OSError, ValueError) as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}

        self.report({"INFO"}, f"Exported {destination.name}; changed {changed_count} logical vertices")
        return {"FINISHED"}


class NBA_LIVE_PT_EBOTools(bpy.types.Panel):
    bl_label = "EBO Head Tools"
    bl_idname = "NBA_LIVE_PT_ebo_tools"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NBA Live"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        import_box = layout.box()
        import_box.label(text="Import Player Head", icon="IMPORT")
        import_box.prop(scene, "nba_live_game_year", text="Game")
        try:
            base_path = resolve_base_path(context, scene.nba_live_game_year)
            import_box.label(text=f"Base: {base_path.name}", icon="CHECKMARK")
        except ebo_core.EBOError:
            import_box.label(text="Base model not configured", icon="ERROR")
        import_box.operator(NBA_LIVE_OT_ImportPlayer.bl_idname, icon="IMPORT")

        export_box = layout.box()
        export_box.label(text="Export Edited Head", icon="EXPORT")
        obj = _active_ebo_object(context)
        if obj:
            export_box.label(text=f"Game: NBA Live {obj[PROP_GAME_YEAR]}")
            export_box.label(text=f"Original: {Path(obj[PROP_SOURCE_EBO]).name}")
            export_box.label(text=f"Vertices: {len(obj.data.vertices)}")
            export_box.operator(NBA_LIVE_OT_ExportPlayer.bl_idname, icon="EXPORT")
        else:
            export_box.label(text="Select an imported player head", icon="INFO")

        layout.label(text="Move existing vertices only.", icon="INFO")


def _import_menu(self, context):
    self.layout.operator(NBA_LIVE_OT_ImportPlayer.bl_idname, text="NBA Live Player Head (.ebo)")


def _export_menu(self, context):
    self.layout.operator(NBA_LIVE_OT_ExportPlayer.bl_idname, text="NBA Live Player Head (.ebo)")


CLASSES = (
    NBA_LIVE_Preferences,
    NBA_LIVE_OT_ImportPlayer,
    NBA_LIVE_OT_ExportPlayer,
    NBA_LIVE_PT_EBOTools,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.nba_live_game_year = EnumProperty(
        name="NBA Live Game",
        description="Game format used by the player EBO and bundled base model",
        items=(
            ("2005", "NBA Live 2005", "734 rendered head vertices; sparse coordinate morph"),
            ("2006", "NBA Live 2006", "733 rendered head vertices; dense coordinate morph"),
        ),
        default="2005",
    )
    bpy.types.TOPBAR_MT_file_import.append(_import_menu)
    bpy.types.TOPBAR_MT_file_export.append(_export_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_export_menu)
    bpy.types.TOPBAR_MT_file_import.remove(_import_menu)
    del bpy.types.Scene.nba_live_game_year
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
