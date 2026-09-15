"""Blender UI for NBA Live player/coach base + multi-Geometry morph workflow."""

from __future__ import annotations

from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper

from . import player_morph_core


BASE_ATTR="nba_live_morph_base_position"
MARKER="nba_live_player_morph_object"
SOURCE_BASE="nba_live_player_morph_base_ebo"
SOURCE_MORPH="nba_live_player_morph_source_ebo"
GEOMETRY_PROP="nba_live_player_morph_geometry"
LOGICAL_PROP="nba_live_player_morph_logical_vertices"
SOURCE_HAS_COORD="nba_live_player_morph_source_has_coord"
SOURCE_CODEC="nba_live_player_morph_source_codec"
LOADED_MORPH_POSITION_ATTR="nba_live_loaded_morph_position"
MORPH_MAPPING="nba_live_player_morph_mapping_available"
SOURCE_MORPH_PRESENT="nba_live_player_morph_source_present"


def _game_to_blender(position):
    x,y,z=map(float,position)
    return (x,-z,y)


def _morph_objects(context):
    return [
        obj for obj in context.scene.objects
        if obj.type=='MESH' and bool(obj.get(MARKER,False))
    ]


def _write_base_attribute(mesh,game_positions):
    attr=mesh.attributes.get(BASE_ATTR)
    if attr is not None:
        mesh.attributes.remove(attr)
    attr=mesh.attributes.new(BASE_ATTR,type='FLOAT_VECTOR',domain='POINT')
    for i,pos in enumerate(game_positions):
        attr.data[i].vector=_game_to_blender(pos)


def _read_base_attribute(mesh):
    attr=mesh.attributes.get(BASE_ATTR)
    if attr is None or attr.domain!='POINT':
        raise player_morph_core.PlayerMorphError(
            "Base position attribute is missing. Reload Base EBO."
        )
    return [tuple(item.vector) for item in attr.data]


def _write_loaded_morph_attribute(mesh):
    attr=mesh.attributes.get(LOADED_MORPH_POSITION_ATTR)
    if attr is not None:
        mesh.attributes.remove(attr)
    attr=mesh.attributes.new(
        LOADED_MORPH_POSITION_ATTR,type='FLOAT_VECTOR',domain='POINT'
    )
    for i,vertex in enumerate(mesh.vertices):
        attr.data[i].vector=tuple(vertex.co)


def _read_loaded_morph_attribute(mesh):
    attr=mesh.attributes.get(LOADED_MORPH_POSITION_ATTR)
    if attr is None or attr.domain!='POINT':
        return None
    return [tuple(item.vector) for item in attr.data]


def _object_edit_status(obj,epsilon=1e-6):
    reference=_read_loaded_morph_attribute(obj.data)
    if reference is None:
        reference=_read_base_attribute(obj.data)

    if len(reference)!=len(obj.data.vertices):
        return "TOPOLOGY CHANGED"

    max_delta2=0.0
    for vertex,ref in zip(obj.data.vertices,reference):
        dx=float(vertex.co.x-ref[0])
        dy=float(vertex.co.y-ref[1])
        dz=float(vertex.co.z-ref[2])
        max_delta2=max(max_delta2,dx*dx+dy*dy+dz*dz)

    return "EDITED" if max_delta2>(epsilon*epsilon) else "unchanged"


def _source_morph_status(obj):
    if bool(obj.get(SOURCE_HAS_COORD,False)):
        codec=str(obj.get(SOURCE_CODEC,"?"))
        if codec=="mapping unavailable":
            return "MORPH DATA PRESENT / mapping unavailable"
        return f"MODIFIED ({codec})"
    if bool(obj.get(SOURCE_MORPH_PRESENT,False)):
        return "MORPH EXPORT / no coord"
    return "NO MORPH EXPORT"


def _reset_object(obj):
    base=_read_base_attribute(obj.data)
    if len(base)!=len(obj.data.vertices):
        raise player_morph_core.PlayerMorphError(
            f"{obj.name}: topology changed after base import."
        )
    for vertex,co in zip(obj.data.vertices,base):
        vertex.co=co
    attr=obj.data.attributes.get(LOADED_MORPH_POSITION_ATTR)
    if attr is not None:
        obj.data.attributes.remove(attr)
    obj.data.update()


def _find_base_record(base_records,geometry_name):
    for item in base_records:
        if item.geometry_name==geometry_name:
            return item
    return None


def _clear_old_objects(context):
    for obj in list(_morph_objects(context)):
        bpy.data.objects.remove(obj,do_unlink=True)


def _ensure_collection(context):
    name="NBA Morph Base"
    col=bpy.data.collections.get(name)
    if col is None:
        col=bpy.data.collections.new(name)
        context.scene.collection.children.link(col)
    return col


def _create_object(display,collection,source_path):
    vertices=[_game_to_blender(p) for p in display.positions]
    mesh=bpy.data.meshes.new(display.geometry_name)
    mesh.from_pydata(vertices,[],display.faces)
    mesh.update()

    obj=bpy.data.objects.new(display.geometry_name,mesh)
    collection.objects.link(obj)

    if len(display.uvs)==len(display.positions):
        uv=mesh.uv_layers.new(name="UVMap")
        for polygon in mesh.polygons:
            for li in polygon.loop_indices:
                vi=mesh.loops[li].vertex_index
                uu,vv=display.uvs[vi]
                uv.data[li].uv=(float(uu),1.0-float(vv))

    _write_base_attribute(mesh,display.positions)
    obj[MARKER]=True
    obj[SOURCE_BASE]=str(Path(source_path).resolve())
    obj[GEOMETRY_PROP]=display.geometry_name
    obj["nba_live_player_morph_rendered_vertices"]=display.rendered_vertex_count
    obj[MORPH_MAPPING]=display.morph_base is not None
    obj[SOURCE_HAS_COORD]=False
    obj[SOURCE_CODEC]=""
    obj[SOURCE_MORPH_PRESENT]=False

    if display.morph_base is not None:
        obj[LOGICAL_PROP]=display.morph_base.logical_vertex_count
    else:
        obj[LOGICAL_PROP]=0

    return obj



class NBA_OT_player_morph_load_base(bpy.types.Operator,ImportHelper):
    bl_idname="nba_live.player_morph_load_base"
    bl_label="Load Base EBO"
    bl_description="Load all structurally morphable Geometry from a player/coach base EBO"
    bl_options={'REGISTER','UNDO'}
    filename_ext=".ebo"
    filter_glob:StringProperty(default="*.ebo",options={'HIDDEN'})

    def execute(self,context):
        try:
            displays=player_morph_core.load_all_base_geometry(self.filepath)
            _clear_old_objects(context)
            col=_ensure_collection(context)

            created=[]
            for display in displays:
                created.append(_create_object(display,col,self.filepath))

            context.scene.nba_live_player_morph_base=str(Path(self.filepath).resolve())
            context.scene.nba_live_player_morph_source=""

            # Prefer the head as active; otherwise first morphable object.
            active=next((o for o in created if "head" in o.name.casefold()),created[0])
            for o in created:
                o.select_set(True)
            context.view_layer.objects.active=active

        except (OSError,ValueError,player_morph_core.PlayerMorphError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Loaded {len(created)} Geometry object(s) from "
            f"{Path(self.filepath).name}."
        )
        return {'FINISHED'}


class NBA_OT_player_morph_load_morph(bpy.types.Operator,ImportHelper):
    bl_idname="nba_live.player_morph_load_morph"
    bl_label="Load Morph EBO"
    bl_description="Reset all loaded base objects and apply every matching Morph export"
    bl_options={'REGISTER','UNDO'}
    filename_ext=".ebo"
    filter_glob:StringProperty(default="*.ebo",options={'HIDDEN'})

    def execute(self,context):
        objs=_morph_objects(context)
        if not objs:
            self.report({'ERROR'},"Load Base EBO first.")
            return {'CANCELLED'}

        base_path=context.scene.nba_live_player_morph_base
        if not base_path:
            self.report({'ERROR'},"Base EBO path is missing.")
            return {'CANCELLED'}

        try:
            bases=player_morph_core.load_morphable_bases(base_path)
            data=Path(self.filepath).read_bytes()
            exports=player_morph_core._morph_exports(data)

            for obj in objs:
                _reset_object(obj)
                obj[SOURCE_HAS_COORD]=False
                obj[SOURCE_CODEC]=""
                obj[SOURCE_MORPH_PRESENT]=False
                if SOURCE_MORPH in obj:
                    del obj[SOURCE_MORPH]

            applied=[]
            skipped=[]
            for obj in objs:
                geometry=str(obj.get(GEOMETRY_PROP,obj.name))
                export_name=geometry+"_morphs"
                obj[SOURCE_MORPH_PRESENT]=export_name in exports

                base=_find_base_record(bases,geometry)
                if base is None:
                    # Full visual Geometry is loaded, but without a verified
                    # rendered->logical mapping we preserve its source morph
                    # byte-for-byte and do not pretend it is editable yet.
                    if export_name in exports:
                        _do,cs,ce=exports[export_name]
                        h=player_morph_core._coord_stream_in_chunk(data,cs,ce)
                        if h is not None:
                            obj[SOURCE_HAS_COORD]=True
                            obj[SOURCE_CODEC]="mapping unavailable"
                            skipped.append((geometry,"coord morph preserved; mapping unavailable"))
                        else:
                            skipped.append((geometry,"Morph export has no coord stream"))
                    else:
                        skipped.append((geometry,"no Morph export"))
                    continue

                delta,info=player_morph_core.decode_morph_geometry(
                    data,geometry,base.logical_vertex_count
                )
                if info is None:
                    skipped.append((geometry,"no Morph export"))
                    continue
                if delta is None:
                    skipped.append((geometry,"no coord morph"))
                    continue

                positions=player_morph_core.morphed_render_positions(base,delta)
                if len(positions)!=len(obj.data.vertices):
                    raise player_morph_core.PlayerMorphError(
                        f"{geometry}: rendered vertex count changed."
                    )
                for vertex,position in zip(obj.data.vertices,positions):
                    vertex.co=_game_to_blender(position)
                obj.data.update()
                obj[SOURCE_MORPH]=str(Path(self.filepath).resolve())
                obj[SOURCE_HAS_COORD]=True
                obj[SOURCE_CODEC]=str(info["codec"])
                _write_loaded_morph_attribute(obj.data)
                applied.append(geometry)

            context.scene.nba_live_player_morph_source=str(Path(self.filepath).resolve())

        except (OSError,ValueError,player_morph_core.PlayerMorphError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Applied coord morph to {len(applied)} object(s); "
            f"{len(skipped)} object(s) preserved from base."
        )
        return {'FINISHED'}


class NBA_OT_player_morph_export(bpy.types.Operator,ExportHelper):
    bl_idname="nba_live.player_morph_export"
    bl_label="Export Morph EBO"
    bl_description="Export edits for every matching Morph Geometry in the loaded template"
    bl_options={'REGISTER'}
    filename_ext=".ebo"
    filter_glob:StringProperty(default="*.ebo",options={'HIDDEN'})

    def invoke(self,context,event):
        source=context.scene.nba_live_player_morph_source
        if source:
            src=Path(source)
            self.filepath=str(src.with_name(src.stem+"_edit.ebo"))
        return super().invoke(context,event)

    def execute(self,context):
        objs=_morph_objects(context)
        if not objs:
            self.report({'ERROR'},"Load Base EBO first.")
            return {'CANCELLED'}

        source=context.scene.nba_live_player_morph_source
        base_path=context.scene.nba_live_player_morph_base
        if not source:
            self.report({'ERROR'},"Load a Morph EBO first; it is the export template.")
            return {'CANCELLED'}

        try:
            bases=player_morph_core.load_morphable_bases(base_path)
            deltas={}
            max_spread=0.0
            edited_names=[]
            source_modified_names=[]
            preserved_names=[]

            for obj in objs:
                geometry=str(obj.get(GEOMETRY_PROP,obj.name))
                base=_find_base_record(bases,geometry)
                if base is None:
                    preserved_names.append(geometry)
                    continue

                if bool(obj.get(SOURCE_HAS_COORD,False)):
                    source_modified_names.append(geometry)

                status=_object_edit_status(obj)
                if status=="TOPOLOGY CHANGED":
                    raise player_morph_core.PlayerMorphError(
                        f"{geometry}: topology changed; morph export requires "
                        "the original vertex count/order."
                    )

                # Preserve the template exactly unless BOTH are true:
                #   1) the source morph already had a supported coord morph
                #   2) the user actually edited this object in Blender
                # We never create a new morph stream merely because the base
                # Geometry exists.
                if status!="EDITED":
                    preserved_names.append(geometry)
                    continue
                if not bool(obj.get(MORPH_MAPPING,False)):
                    preserved_names.append(geometry)
                    continue
                codec=str(obj.get(SOURCE_CODEC,""))
                if not bool(obj.get(SOURCE_HAS_COORD,False)) or codec=="mapping unavailable":
                    preserved_names.append(geometry)
                    continue

                blender_positions=[tuple(v.co) for v in obj.data.vertices]
                logical_delta,spread=player_morph_core.logical_delta_from_edited(
                    base,blender_positions
                )
                deltas[geometry]=logical_delta
                max_spread=max(max_spread,spread)
                edited_names.append(geometry)

            result=player_morph_core.export_multi_morph(
                source,self.filepath,deltas
            )

            context.scene.nba_live_player_morph_last_export=(
                "Edited: " + (", ".join(edited_names) if edited_names else "none") +
                " | Source morph coord: " +
                (", ".join(source_modified_names) if source_modified_names else "none") +
                " | Preserved/unchanged: " +
                (", ".join(preserved_names) if preserved_names else "none")
            )

        except (OSError,ValueError,player_morph_core.PlayerMorphError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        message=(
            f"Exported {Path(self.filepath).name}: "
            f"{len(edited_names)} Blender-edited object(s), "
            f"{len(result['changed'])} coord stream(s) written"
        )
        if result["skipped"]:
            message += f"; {len(result['skipped'])} template object(s) preserved"
        if max_spread > 0.001:
            self.report(
                {'WARNING'},
                message + f". UV-seam duplicate delta spread up to {max_spread:.6f}."
            )
        else:
            self.report({'INFO'},message)
        return {'FINISHED'}


class NBA_OT_player_morph_reset(bpy.types.Operator):
    bl_idname="nba_live.player_morph_reset"
    bl_label="Reset All to Base"
    bl_description="Restore every loaded morphable object to untouched base positions"
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        objs=_morph_objects(context)
        if not objs:
            self.report({'ERROR'},"No loaded morph base objects found.")
            return {'CANCELLED'}
        try:
            for obj in objs:
                _reset_object(obj)
                if SOURCE_MORPH in obj:
                    del obj[SOURCE_MORPH]
                obj[SOURCE_HAS_COORD]=False
                obj[SOURCE_CODEC]=""
                obj[SOURCE_MORPH_PRESENT]=False
            context.scene.nba_live_player_morph_source=""
            context.scene.nba_live_player_morph_last_export=""
        except player_morph_core.PlayerMorphError as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}
        self.report({'INFO'},f"Restored {len(objs)} object(s) to base.")
        return {'FINISHED'}


class NBA_PT_player_morph(bpy.types.Panel):
    bl_label="Player / Coach Morph EBO"
    bl_options = {'DEFAULT_CLOSED'}
    bl_idname="NBA_PT_player_morph"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='NBA Live'

    def draw(self,context):
        layout=self.layout
        objs=_morph_objects(context)

        base=layout.box()
        base.label(text="Base Model")
        base.operator(NBA_OT_player_morph_load_base.bl_idname,icon='FILE_FOLDER')
        if objs:
            morphable=sum(1 for o in objs if bool(o.get(MORPH_MAPPING,False)))
            base.label(text=f"Geometry: {len(objs)} total / {morphable} mapped")
            for obj in objs[:14]:
                if bool(obj.get(MORPH_MAPPING,False)):
                    detail=f"{obj.get(LOGICAL_PROP,'?')} logical"
                else:
                    detail="visual/base only"
                base.label(
                    text=f"{obj.name}: {len(obj.data.vertices)} rendered / {detail}"
                )
            if len(objs)>14:
                base.label(text=f"... +{len(objs)-14} more")


        morph=layout.box()
        morph.label(text="Morph")
        morph.operator(NBA_OT_player_morph_load_morph.bl_idname,icon='SHAPEKEY_DATA')
        morph.operator(NBA_OT_player_morph_reset.bl_idname)

        source=context.scene.nba_live_player_morph_source
        if source:
            morph.label(text=Path(source).name)
            morph.operator(NBA_OT_player_morph_export.bl_idname,icon='EXPORT')

            contents=layout.box()
            contents.label(text="Source Morph Contents")
            for obj in objs:
                contents.label(text=f"{obj.name}: {_source_morph_status(obj)}")

            edits=layout.box()
            edits.label(text="Current Blender Edits")
            for obj in objs:
                edits.label(text=f"{obj.name}: {_object_edit_status(obj)}")

        export_summary=getattr(context.scene,"nba_live_player_morph_last_export","")
        if export_summary:
            summary=layout.box()
            summary.label(text="Last Export")
            for section in export_summary.split(" | "):
                summary.label(text=section)

        edit=layout.box()
        edit.label(text="Direct vertex editing")
        edit.label(text="MODIFIED = source morph changes this Geometry.")
        edit.label(text="EDITED = Blender differs from loaded morph state.")
        edit.label(text="Keep topology and vertex order unchanged.")


CLASSES=(
    NBA_OT_player_morph_load_base,
    NBA_OT_player_morph_load_morph,
    NBA_OT_player_morph_export,
    NBA_OT_player_morph_reset,
    NBA_PT_player_morph,
)


def register():
    bpy.types.Scene.nba_live_player_morph_base=StringProperty(
        name="Player Morph Base EBO",subtype='FILE_PATH',default=""
    )
    bpy.types.Scene.nba_live_player_morph_source=StringProperty(
        name="Player Morph EBO",subtype='FILE_PATH',default=""
    )
    bpy.types.Scene.nba_live_player_morph_last_export=StringProperty(
        name="Player Morph Last Export",default=""
    )
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in (
        "nba_live_player_morph_base",
        "nba_live_player_morph_source",
        "nba_live_player_morph_last_export",
    ):
        if hasattr(bpy.types.Scene,name):
            delattr(bpy.types.Scene,name)
