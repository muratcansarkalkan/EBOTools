from pathlib import Path
import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ImportHelper, ExportHelper
from . import body_morph_core as morph
from . import multi_morph_core
P_SOURCE='nba_body_morph_source'; P_BASE='nba_body_morph_base'; P_HASH='nba_body_morph_hash'; A_ID='EA_MORPH_VERTEX_ID'; A_ORIG='EA_MORPH_ORIGINAL'
class LoadBase(bpy.types.Operator,ImportHelper):
 bl_idname='nba_live.load_base_body_morph'; bl_label='Load Base LOD + Morph'; filename_ext='.ebo'; filter_glob:StringProperty(default='*.ebo',options={'HIDDEN'})
 def execute(self,c): c.scene.nba_body_base_path=str(Path(self.filepath).resolve()); bpy.ops.nba_live.load_body_morph('INVOKE_DEFAULT'); return {'FINISHED'}
class LoadMorph(bpy.types.Operator,ImportHelper):
 bl_idname='nba_live.load_body_morph'; bl_label='Choose Player Morph'; filename_ext='.ebo'; filter_glob:StringProperty(default='*.ebo',options={'HIDDEN'})
 def execute(self,c):
  try:
   base=Path(c.scene.nba_body_base_path); src=Path(self.filepath).resolve(); p=morph.import_morph(base,src)
   me=bpy.data.meshes.new(src.stem+'_Morphed'); me.from_pydata(p.vertices,[],p.faces); me.update(); ids=me.attributes.new(name=A_ID,type='INT',domain='POINT'); orig=me.attributes.new(name=A_ORIG,type='FLOAT_VECTOR',domain='POINT')
   for i,v in enumerate(p.vertices): ids.data[i].value=i; orig.data[i].vector=v
   uv=me.uv_layers.new(name='UVMap')
   for poly in me.polygons:
    for li in poly.loop_indices: vi=me.loops[li].vertex_index; uv.data[li].uv=p.uvs[vi]
   o=bpy.data.objects.new(src.stem,me); c.collection.objects.link(o); o[P_SOURCE]=str(src); o[P_BASE]=str(base.resolve()); o[P_HASH]=p.source_sha256; bpy.ops.object.select_all(action='DESELECT'); o.select_set(True); c.view_layer.objects.active=o
   self.report({'INFO'},f'Loaded {len(p.vertices)} render / {p.logical_count} logical vertices'); return {'FINISHED'}
  except Exception as e: self.report({'ERROR'},str(e)); return {'CANCELLED'}
class ExportMorph(bpy.types.Operator,ExportHelper):
 bl_idname='nba_live.export_body_morph'; bl_label='Export Morph EBO'; filename_ext='.ebo'; filter_glob:StringProperty(default='*.ebo',options={'HIDDEN'})
 @classmethod
 def poll(cls,c): return c.active_object is not None and P_SOURCE in c.active_object
 def invoke(self,c,e):
  p=Path(c.active_object[P_SOURCE]); self.filepath=str(p.with_name(p.stem+'_edited.ebo')); return super().invoke(c,e)
 def execute(self,c):
  try:
   o=c.active_object
   if o.mode=='EDIT': o.update_from_editmode()
   ids=o.data.attributes[A_ID]; orig=o.data.attributes[A_ORIG]; n=len(o.data.vertices); ed=[None]*n; old=[None]*n
   for v in o.data.vertices: i=int(ids.data[v.index].value); ed[i]=tuple(v.co); old[i]=tuple(orig.data[v.index].vector)
   src=Path(o[P_SOURCE]); dst=Path(self.filepath).resolve()
   if dst==src.resolve(): raise morph.MorphError('Do not overwrite the original morph EBO.')
   data,count=morph.export_morph(o[P_BASE],src,ed,old,o.get(P_HASH,'')); dst.write_bytes(data); self.report({'INFO'},f'Exported; {count} logical vertices changed'); return {'FINISHED'}
  except Exception as e: self.report({'ERROR'},str(e)); return {'CANCELLED'}
class Panel(bpy.types.Panel):
 bl_label='Player Body Morph'; bl_idname='NBA_PT_body_morph'; bl_space_type='VIEW_3D'; bl_region_type='UI'; bl_category='NBA Live'
 def draw(self,c):
  l=self.layout; l.label(text='1. Base LOD B / C / D'); l.operator(LoadBase.bl_idname,icon='IMPORT')
  if c.scene.nba_body_base_path: l.label(text=Path(c.scene.nba_body_base_path).name,icon='CHECKMARK')
  l.label(text='2. Edit morphed mesh'); l.label(text='Move existing vertices only.',icon='INFO'); l.label(text='3. Export morph only'); l.operator(ExportMorph.bl_idname,icon='EXPORT')
CLASSES=(LoadBase,LoadMorph,ExportMorph,Panel)
def register():
 for x in CLASSES: bpy.utils.register_class(x)
 bpy.types.Scene.nba_body_base_path=StringProperty(default='')
def unregister():
 del bpy.types.Scene.nba_body_base_path
 for x in reversed(CLASSES): bpy.utils.unregister_class(x)
