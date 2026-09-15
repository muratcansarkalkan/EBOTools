"""NBA Live 06 net-model tools.

Verified stock profile from net_06:
- Geometry: netShape
- RMS: gNbaBackboardSkin_RMRuntime
- TextureName: tnet
- stock Geometry flags: 0x35121205
- rigid palette order: [1, 2, 0, 3]
- stock five vertical rings:
    top         -> bone 0
    upper       -> bone 1
    middle x 2  -> bone 2
    bottom      -> bone 3

This module supports:
- recovering the stock 06 net's rigid groups after import;
- manual assignment of the four semantic groups;
- nearest-vertex transfer to replacement meshes;
- width/length scaling while keeping the top ring anchored;
- export of a new skinned netShape EBO.
"""

from __future__ import annotations

from pathlib import Path
import math

import bpy
from bpy.props import BoolProperty, FloatProperty, StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ExportHelper

from . import ebo_backboard


GROUP_TOP = "Net_TopAnchor"
GROUP_UPPER = "Net_Upper"
GROUP_BODY = "Net_Body"
GROUP_BOTTOM = "Net_Bottom"
NET_GROUPS = (GROUP_TOP, GROUP_UPPER, GROUP_BODY, GROUP_BOTTOM)

GROUP_TO_BONE = {
    GROUP_TOP: 0,
    GROUP_UPPER: 1,
    GROUP_BODY: 2,
    GROUP_BOTTOM: 3,
}
BONE_TO_GROUP = {v:k for k,v in GROUP_TO_BONE.items()}

RUNTIME = "gNbaBackboardSkin_RMRuntime"
GEOMETRY_NAME = "netShape"
TEXTURE_NAME = "tnet"
DEFAULT_FLAGS_06 = 0x35121205
CANONICAL_PALETTE_ORDER = (1, 2, 0, 3)


def _mesh_objects(context):
    return [o for o in context.selected_objects if o.type == "MESH"]


def _ensure_groups(obj):
    for name in NET_GROUPS:
        if obj.vertex_groups.get(name) is None:
            obj.vertex_groups.new(name=name)


def _weights(obj, vertex_index):
    found=[]
    for name in NET_GROUPS:
        vg=obj.vertex_groups.get(name)
        if vg is None:
            continue
        try:
            w=float(vg.weight(vertex_index))
        except RuntimeError:
            continue
        if w > 1.0e-6:
            found.append((name,w))
    return found


def _assign(obj, group_name, indices):
    _ensure_groups(obj)
    indices=list(indices)
    if not indices:
        return
    for name in NET_GROUPS:
        vg=obj.vertex_groups.get(name)
        if vg:
            try:
                vg.remove(indices)
            except RuntimeError:
                pass
    obj.vertex_groups[group_name].add(indices,1.0,'REPLACE')


def _bone_id(obj, vertex_index):
    found=_weights(obj,vertex_index)
    if len(found)!=1 or abs(found[0][1]-1.0)>1.0e-4:
        raise ValueError(
            f"{obj.name}: vertex {vertex_index} must have exactly one rigid "
            "Net_TopAnchor/Net_Upper/Net_Body/Net_Bottom weight at 1.0."
        )
    return GROUP_TO_BONE[found[0][0]]


def _material_texture_name(mat):
    explicit=mat.get("nba_live_texture_name")
    if explicit:
        return str(explicit)
    name=mat.name.split(" [",1)[0].strip()
    if name.lower().startswith("ebo."):
        name=name[4:]
    return name


def _corner_normal(mesh,loop_index,vertex_index):
    try:
        return mesh.corner_normals[loop_index].vector.copy()
    except Exception:
        return mesh.vertices[vertex_index].normal.copy()


def _strip_from_triangles(tris):
    if not tris:
        raise ValueError("Net material has no triangles.")
    out=list(tris[0])
    for a,b,c in tris[1:]:
        x,y=(b,a) if ((len(out)+2)&1) else (a,b)
        out.extend((out[-1],x,x,y,c))
    return tuple(out)


def _parse_int(value):
    if isinstance(value,int):
        return int(value)
    return int(str(value).strip(),0)


def _compile_net(obj):
    mesh=obj.data
    mesh.calc_loop_triangles()
    if len(obj.material_slots) == 0:
        raise ValueError("Net mesh needs one material.")
    used_slots=sorted({t.material_index for t in mesh.loop_triangles})
    if len(used_slots)!=1:
        raise ValueError(
            f"Net Mode currently expects exactly one used material slot; found {len(used_slots)}."
        )
    slot_index=used_slots[0]
    mat=obj.material_slots[slot_index].material
    if mat is None:
        raise ValueError("Net material slot is empty.")
    texture=_material_texture_name(mat)
    if not texture:
        texture=TEXTURE_NAME

    uv_layer=mesh.uv_layers[0] if mesh.uv_layers else None
    matrix=obj.matrix_world
    normal_matrix=matrix.to_3x3()

    lookup={}
    positions=[]
    normals=[]
    uvs=[]
    bones=[]
    out_tris=[]

    for tri in mesh.loop_triangles:
        if tri.material_index != slot_index:
            continue
        ot=[]
        for li in tri.loops:
            vi=mesh.loops[li].vertex_index
            bone=_bone_id(obj,vi)

            co=matrix @ mesh.vertices[vi].co
            pos=(float(co.x),float(co.z),-float(co.y))

            if uv_layer is None:
                uv=(0.0,0.0)
            else:
                raw=uv_layer.data[li].uv
                uv=(float(raw.x),1.0-float(raw.y))

            n=_corner_normal(mesh,li,vi)
            n=normal_matrix @ n
            if n.length_squared>0.0:
                n.normalize()
            nor=(float(n.x),float(n.z),-float(n.y))

            key=(
                vi,
                round(uv[0],9),round(uv[1],9),
                round(nor[0],7),round(nor[1],7),round(nor[2],7),
                bone,
            )
            oi=lookup.get(key)
            if oi is None:
                oi=len(positions)
                lookup[key]=oi
                positions.append(pos)
                normals.append(nor)
                uvs.append(uv)
                bones.append(bone)
            ot.append(oi)

        if len(set(ot))==3:
            out_tris.append(tuple(ot))

    if not out_tris:
        raise ValueError("Net contains no usable triangles.")

    present=set(bones)
    palette=[b for b in CANONICAL_PALETTE_ORDER if b in present]
    for b in bones:
        if b not in palette:
            palette.append(b)
    local={bone:i for i,bone in enumerate(palette)}
    palette_indices=tuple(local[b] for b in bones)

    return ebo_backboard.BackboardBatch(
        texture=texture,
        positions=tuple(positions),
        normals=tuple(normals),
        uvs=tuple(uvs),
        palette_bones=tuple(palette),
        palette_indices=palette_indices,
        strip=_strip_from_triangles(out_tris),
        runtime=RUNTIME,
        uv_index=None,
    )


class NBA_OT_net_create_groups(Operator):
    bl_idname="nba.net_create_groups"
    bl_label="Create Net Weight Groups"
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        objs=_mesh_objects(context)
        if not objs:
            self.report({'ERROR'},"Select at least one net mesh.")
            return {'CANCELLED'}
        for obj in objs:
            _ensure_groups(obj)
        self.report({'INFO'},f"Net groups ready on {len(objs)} mesh(es).")
        return {'FINISHED'}


class NBA_OT_net_recover_stock_weights(Operator):
    bl_idname="nba.net_recover_stock_weights"
    bl_label="Recover Stock 06 Net Weights"
    bl_description=(
        "Recover the verified stock NBA Live 06 five-ring rigid weight layout "
        "from the active imported netShape"
    )
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        obj=context.active_object
        if obj is None or obj.type!='MESH':
            self.report({'ERROR'},"Make the imported netShape mesh active.")
            return {'CANCELLED'}

        # The EBO importer maps game Y to Blender Z. The stock 06 net has five
        # distinct vertical bands. Group them from highest to lowest:
        # bone0, bone1, bone2, bone2, bone3.
        bands={}
        for v in obj.data.vertices:
            key=round(float(v.co.z),4)
            bands.setdefault(key,[]).append(v.index)
        levels=sorted(bands,reverse=True)

        if len(levels)!=5:
            self.report(
                {'ERROR'},
                f"Stock 06 recovery expects exactly 5 Z bands; found {len(levels)}. "
                "Use manual assignment or donor transfer for custom topology."
            )
            return {'CANCELLED'}

        _ensure_groups(obj)
        mapping=(
            (GROUP_TOP,levels[0]),
            (GROUP_UPPER,levels[1]),
            (GROUP_BODY,levels[2]),
            (GROUP_BODY,levels[3]),
            (GROUP_BOTTOM,levels[4]),
        )
        for group,level in mapping:
            _assign(obj,group,bands[level])

        obj["nba_live_geometry_name"]=GEOMETRY_NAME
        obj["nba_live_geometry_flags"]=DEFAULT_FLAGS_06
        obj["nba_live_net_profile"]="NBA Live 06"

        counts={name:0 for name in NET_GROUPS}
        for v in obj.data.vertices:
            w=_weights(obj,v.index)
            if len(w)==1:
                counts[w[0][0]]+=1

        self.report(
            {'INFO'},
            "Recovered stock net weights — "
            f"Top {counts[GROUP_TOP]}, Upper {counts[GROUP_UPPER]}, "
            f"Body {counts[GROUP_BODY]}, Bottom {counts[GROUP_BOTTOM]}."
        )
        return {'FINISHED'}


class _NBA_OT_assign_net_group(Operator):
    bl_options={'REGISTER','UNDO'}
    group_name=""

    def execute(self,context):
        obj=context.active_object
        if obj is None or obj.type!='MESH':
            self.report({'ERROR'},"Active object must be a net mesh.")
            return {'CANCELLED'}
        if obj.mode!='EDIT':
            self.report({'ERROR'},"Enter Edit Mode and select vertices first.")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='OBJECT')
        try:
            indices=[v.index for v in obj.data.vertices if v.select]
            if not indices:
                self.report({'ERROR'},"No vertices selected.")
                return {'CANCELLED'}
            _assign(obj,self.group_name,indices)
        finally:
            bpy.ops.object.mode_set(mode='EDIT')
        self.report({'INFO'},f"Assigned {len(indices)} vertices to {self.group_name}.")
        return {'FINISHED'}


class NBA_OT_net_assign_top(_NBA_OT_assign_net_group):
    bl_idname="nba.net_assign_top"
    bl_label="Assign Top Anchor"
    group_name=GROUP_TOP

class NBA_OT_net_assign_upper(_NBA_OT_assign_net_group):
    bl_idname="nba.net_assign_upper"
    bl_label="Assign Upper"
    group_name=GROUP_UPPER

class NBA_OT_net_assign_body(_NBA_OT_assign_net_group):
    bl_idname="nba.net_assign_body"
    bl_label="Assign Body"
    group_name=GROUP_BODY

class NBA_OT_net_assign_bottom(_NBA_OT_assign_net_group):
    bl_idname="nba.net_assign_bottom"
    bl_label="Assign Bottom"
    group_name=GROUP_BOTTOM


class NBA_OT_net_transfer_weights(Operator):
    bl_idname="nba.net_transfer_weights"
    bl_label="Transfer Net Weights"
    bl_description="Transfer four rigid net groups from active donor to other selected meshes"
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        donor=context.active_object
        if donor is None or donor.type!='MESH':
            self.report({'ERROR'},"Make the weighted donor net active.")
            return {'CANCELLED'}
        targets=[o for o in _mesh_objects(context) if o!=donor]
        if not targets:
            self.report({'ERROR'},"Select donor plus at least one target mesh.")
            return {'CANCELLED'}

        from mathutils.kdtree import KDTree
        kd=KDTree(len(donor.data.vertices))
        donor_group={}
        for v in donor.data.vertices:
            try:
                bone=_bone_id(donor,v.index)
            except ValueError as exc:
                self.report({'ERROR'},str(exc))
                return {'CANCELLED'}
            kd.insert(donor.matrix_world @ v.co,v.index)
            donor_group[v.index]=BONE_TO_GROUP[bone]
        kd.balance()

        total=0
        for target in targets:
            _ensure_groups(target)
            buckets={name:[] for name in NET_GROUPS}
            for v in target.data.vertices:
                _co,idx,_dist=kd.find(target.matrix_world @ v.co)
                buckets[donor_group[idx]].append(v.index)
            for name,indices in buckets.items():
                _assign(target,name,indices)
                total+=len(indices)

        self.report({'INFO'},f"Transferred net weights to {len(targets)} target(s), {total} vertices.")
        return {'FINISHED'}


class NBA_OT_net_validate_weights(Operator):
    bl_idname="nba.net_validate_weights"
    bl_label="Validate Net Weights"

    def execute(self,context):
        objs=_mesh_objects(context)
        if not objs:
            self.report({'ERROR'},"Select at least one net mesh.")
            return {'CANCELLED'}
        bad=[]
        counts={name:0 for name in NET_GROUPS}
        for obj in objs:
            _ensure_groups(obj)
            nb=0
            for v in obj.data.vertices:
                w=_weights(obj,v.index)
                if len(w)!=1 or abs(w[0][1]-1.0)>1.0e-4:
                    nb+=1
                else:
                    counts[w[0][0]]+=1
            if nb:
                bad.append(f"{obj.name}: {nb}")
        if bad:
            self.report({'ERROR'},"Invalid rigid net weights — "+", ".join(bad[:6]))
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Net weights valid — Top {counts[GROUP_TOP]}, Upper {counts[GROUP_UPPER]}, "
            f"Body {counts[GROUP_BODY]}, Bottom {counts[GROUP_BOTTOM]}."
        )
        return {'FINISHED'}


class NBA_OT_net_scale(Operator):
    bl_idname="nba.net_scale_geometry"
    bl_label="Apply Net Width / Length"
    bl_description=(
        "Scale selected net geometry radially and downward while keeping the "
        "topmost ring fixed vertically"
    )
    bl_options={'REGISTER','UNDO'}

    def execute(self,context):
        settings=context.scene.nba_live_net_settings
        width=float(settings.width_scale)
        length=float(settings.length_scale)
        objs=_mesh_objects(context)
        if not objs:
            self.report({'ERROR'},"Select the net mesh.")
            return {'CANCELLED'}
        if width<=0 or length<=0:
            self.report({'ERROR'},"Scale values must be greater than zero.")
            return {'CANCELLED'}

        for obj in objs:
            verts=obj.data.vertices
            if not verts:
                continue
            cx=sum(v.co.x for v in verts)/len(verts)
            cy=sum(v.co.y for v in verts)/len(verts)
            top=max(v.co.z for v in verts)
            for v in verts:
                v.co.x=cx+(v.co.x-cx)*width
                v.co.y=cy+(v.co.y-cy)*width
                v.co.z=top+(v.co.z-top)*length
            obj.data.update()

        self.report(
            {'INFO'},
            f"Applied net scale: width {width:.3f}x, length {length:.3f}x."
        )
        return {'FINISHED'}


class NBA_OT_export_net_ebo(Operator,ExportHelper):
    bl_idname="nba.export_net_ebo"
    bl_label="Export Net EBO"
    bl_description="Compile the active weighted mesh as NBA Live 06 netShape"
    bl_options={'REGISTER'}
    filename_ext=".ebo"
    filter_glob:StringProperty(default="*.ebo",options={'HIDDEN'})

    def invoke(self,context,event):
        self.filepath=str(Path(bpy.path.abspath("//"))/"net.ebo")
        return super().invoke(context,event)

    def execute(self,context):
        obj=context.active_object
        if obj is None or obj.type!='MESH':
            self.report({'ERROR'},"Make the net mesh active.")
            return {'CANCELLED'}

        try:
            for v in obj.data.vertices:
                _bone_id(obj,v.index)
            batch=_compile_net(obj)
            flags=_parse_int(obj.get("nba_live_geometry_flags",DEFAULT_FLAGS_06))
            geo=ebo_backboard.BackboardGeometry(
                GEOMETRY_NAME,
                (batch,),
                flags,
            )
            data=ebo_backboard.build_backboard_ebo((geo,))
            dest=Path(self.filepath).resolve()
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_bytes(data)
        except (ValueError,OSError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f"Exported {dest.name}: {len(batch.positions)} stream vertices, "
            f"{len(batch.strip)-2} primitives, palette {list(batch.palette_bones)}."
        )
        return {'FINISHED'}


class NBALiveNetSettings(bpy.types.PropertyGroup):
    width_scale:FloatProperty(
        name="Width Scale",
        default=1.0,
        min=0.10,
        max=4.0,
        soft_min=0.75,
        soft_max=1.50,
    )
    length_scale:FloatProperty(
        name="Length Scale",
        default=1.0,
        min=0.10,
        max=4.0,
        soft_min=0.75,
        soft_max=1.75,
    )


class NBA_PT_net_tools(Panel):
    bl_label="Net EBO"
    bl_options = {'DEFAULT_CLOSED'}
    bl_idname="NBA_PT_net_tools"
    bl_space_type="VIEW_3D"
    bl_region_type="UI"
    bl_category="NBA Live"

    def draw(self,context):
        layout=self.layout
        settings=context.scene.nba_live_net_settings

        profile=layout.box()
        profile.label(text="NBA Live 06 Net",icon="MESH_DATA")
        profile.label(text="Geometry: netShape")
        profile.label(text="RMS: gNbaBackboardSkin_RMRuntime")
        profile.label(text="TextureName: tnet")

        setup=layout.box()
        setup.label(text="Existing Stock Net")
        setup.operator(NBA_OT_net_recover_stock_weights.bl_idname)
        setup.operator(NBA_OT_net_create_groups.bl_idname)

        weights=layout.box()
        weights.label(text="Rigid Net Weights")
        row=weights.row(align=True)
        row.operator(NBA_OT_net_assign_top.bl_idname)
        row.operator(NBA_OT_net_assign_upper.bl_idname)
        row=weights.row(align=True)
        row.operator(NBA_OT_net_assign_body.bl_idname)
        row.operator(NBA_OT_net_assign_bottom.bl_idname)
        weights.operator(NBA_OT_net_transfer_weights.bl_idname)
        weights.operator(NBA_OT_net_validate_weights.bl_idname)

        scale=layout.box()
        scale.label(text="Net Size")
        scale.prop(settings,"width_scale")
        scale.prop(settings,"length_scale")
        scale.operator(NBA_OT_net_scale.bl_idname)

        export=layout.box()
        export.label(text="Export")
        export.label(text="Active mesh -> netShape")
        export.operator(NBA_OT_export_net_ebo.bl_idname,icon='EXPORT')

        info=layout.box()
        info.label(text="NBA Live 06 weighted net export")


CLASSES=(
    NBALiveNetSettings,
    NBA_OT_net_create_groups,
    NBA_OT_net_recover_stock_weights,
    NBA_OT_net_assign_top,
    NBA_OT_net_assign_upper,
    NBA_OT_net_assign_body,
    NBA_OT_net_assign_bottom,
    NBA_OT_net_transfer_weights,
    NBA_OT_net_validate_weights,
    NBA_OT_net_scale,
    NBA_OT_export_net_ebo,
    NBA_PT_net_tools,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.nba_live_net_settings=bpy.props.PointerProperty(type=NBALiveNetSettings)


def unregister():
    if hasattr(bpy.types.Scene,"nba_live_net_settings"):
        del bpy.types.Scene.nba_live_net_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
