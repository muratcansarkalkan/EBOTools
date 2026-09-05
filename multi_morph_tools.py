"""Blender multi-target player morph importer."""
from pathlib import Path
import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper
from . import multi_morph_core

class NBA_OT_LoadMultiMorph(bpy.types.Operator,ImportHelper):
    bl_idname="nba_live.load_multi_morph_base";bl_label="Load Base LOD + Partial Morph"
    filename_ext=".ebo";filter_glob:StringProperty(default="*.ebo",options={"HIDDEN"})
    def execute(self,context):
        context.scene.nba_multi_base=str(Path(self.filepath).resolve())
        bpy.ops.nba_live.choose_partial_morph("INVOKE_DEFAULT")
        return {"FINISHED"}

class NBA_OT_ChoosePartialMorph(bpy.types.Operator,ImportHelper):
    bl_idname="nba_live.choose_partial_morph";bl_label="Choose Morph EBO"
    filename_ext=".ebo";filter_glob:StringProperty(default="*.ebo",options={"HIDDEN"})
    def execute(self,context):
        try:
            base=Path(context.scene.nba_multi_base);src=Path(self.filepath).resolve()
            a=multi_morph_core.assemble(base,src)
            col=bpy.data.collections.new(src.stem+"_assembled")
            context.scene.collection.children.link(col)
            for part in a.parts:
                me=bpy.data.meshes.new(part.name);me.from_pydata(part.vertices,[],part.faces);me.update()
                if part.uvs:
                    layer=me.uv_layers.new(name="UVMap")
                    for poly in me.polygons:
                        for li in poly.loop_indices:
                            vi=me.loops[li].vertex_index
                            if vi<len(part.uvs):layer.data[li].uv=part.uvs[vi]
                ob=bpy.data.objects.new(part.name,me);col.objects.link(ob)
                ob["nba_morph_modified"]=part.modified
                ob["nba_morph_logical_count"]=part.logical_count
                ob["nba_morph_source"]=str(src); ob["nba_morph_base"]=str(base.resolve())
                ob["nba_morph_hash"]=a.source_sha256; ob["nba_morph_original_count"]=len(part.vertices)
                if part.modified:
                    attr=me.attributes.new(name="EA_MORPH_ORIGINAL",type="FLOAT_VECTOR",domain="POINT")
                    for i,p in enumerate(part.vertices):attr.data[i].vector=p
            context.scene.nba_multi_collection=col.name
            applied=[r.name for r in a.results if r.status.startswith("APPLIED")]
            context.scene.nba_multi_report="\n".join(
                f"{r.name}: {r.status} | {r.render_vertices} render / {r.logical_vertices} logical"
                + (f" / {r.stored_floats} stored floats" if r.stored_floats else "")
                for r in a.results)
            self.report({"INFO"},f"Imported complete base ({len(a.parts)} parts); morph modified {len(applied)}: "+", ".join(applied))
            return {"FINISHED"}
        except Exception as e:self.report({"ERROR"},str(e));return {"CANCELLED"}

class NBA_OT_ExportMultiMorph(bpy.types.Operator,ExportHelper):
    bl_idname="nba_live.export_multi_morph";bl_label="Export Morph EBO"
    filename_ext=".ebo";filter_glob:StringProperty(default="*.ebo",options={"HIDDEN"})
    def invoke(self,context,event):
        col=bpy.data.collections.get(context.scene.nba_multi_collection)
        if col:
            for ob in col.objects:
                if ob.get("nba_morph_source"):
                    p=Path(ob["nba_morph_source"]);self.filepath=str(p.with_name(p.stem+"_edited.ebo"));break
        return super().invoke(context,event)
    def execute(self,context):
        try:
            col=bpy.data.collections.get(context.scene.nba_multi_collection)
            if not col:raise multi_morph_core.MultiMorphError("Imported morph collection not found.")
            edited={};base=src=sha=None
            for ob in col.objects:
                if not ob.get("nba_morph_modified"):continue
                if ob.mode=="EDIT":ob.update_from_editmode()
                if len(ob.data.vertices)!=int(ob.get("nba_morph_original_count",-1)):
                    raise multi_morph_core.MultiMorphError(f"{ob.name}: topology changed.")
                attr=ob.data.attributes.get("EA_MORPH_ORIGINAL")
                if not attr:raise multi_morph_core.MultiMorphError(f"{ob.name}: original metadata missing.")
                edited[ob.name]={"vertices":[tuple(v.co) for v in ob.data.vertices],
                                 "original":[tuple(x.vector) for x in attr.data]}
                base=ob["nba_morph_base"];src=ob["nba_morph_source"];sha=ob["nba_morph_hash"]
            dst=Path(self.filepath).resolve()
            if dst==Path(src).resolve():raise multi_morph_core.MultiMorphError("Do not overwrite the original morph.")
            out,changed=multi_morph_core.export_fixed_morph(base,src,edited,sha)
            dst.write_bytes(out)
            self.report({"INFO"},"Exported: "+(", ".join(changed) if changed else "no changed targets"))
            return {"FINISHED"}
        except Exception as e:self.report({"ERROR"},str(e));return {"CANCELLED"}

class NBA_PT_MultiMorph(bpy.types.Panel):
    bl_label="Multi-Part Player Morph";bl_idname="NBA_PT_multi_morph"
    bl_space_type="VIEW_3D";bl_region_type="UI";bl_category="NBA Live"
    def draw(self,context):
        l=self.layout;l.operator(NBA_OT_LoadMultiMorph.bl_idname,icon="IMPORT")
        if context.scene.nba_multi_report:
            l.separator();l.label(text="Morph target report:")
            for line in context.scene.nba_multi_report.splitlines():
                l.label(text=line[:120],icon="CHECKMARK" if ": APPLIED" in line else "INFO")
            l.separator();l.label(text="Move existing vertices only.",icon="INFO")
            l.operator(NBA_OT_ExportMultiMorph.bl_idname,icon="EXPORT")

CLASSES=(NBA_OT_LoadMultiMorph,NBA_OT_ChoosePartialMorph,NBA_OT_ExportMultiMorph,NBA_PT_MultiMorph)
def register():
    for c in CLASSES:bpy.utils.register_class(c)
    bpy.types.Scene.nba_multi_base=StringProperty(default="")
    bpy.types.Scene.nba_multi_report=StringProperty(default="")
    bpy.types.Scene.nba_multi_collection=StringProperty(default="")
def unregister():
    del bpy.types.Scene.nba_multi_collection;del bpy.types.Scene.nba_multi_report;del bpy.types.Scene.nba_multi_base
    for c in reversed(CLASSES):bpy.utils.unregister_class(c)
