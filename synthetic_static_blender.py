from __future__ import annotations
from pathlib import Path
import re

import bpy
from bpy.props import BoolProperty,StringProperty
from bpy_extras.io_utils import ExportHelper
from . import ebo_synthetic_static, synthetic_fsh
from . import rms_profiles

COLOR_LAYER='NBA Live Vertex Colors'
RMS_SUFFIX_RE=re.compile(r"^(?P<asset>.*?)\s*\[(?P<rms>[A-Za-z0-9_]+)\]\s*$")

def _first_color_layer(mesh):
    preferred=mesh.color_attributes.get(COLOR_LAYER)
    if preferred is not None and preferred.domain in {'POINT','CORNER'}:
        return preferred
    for layer in mesh.color_attributes:
        if layer.domain in {'POINT','CORNER'}:
            return layer
    return None

def _read_color(item):
    vals=tuple(item.color_srgb if hasattr(item,'color_srgb') else item.color)
    vals=[max(0.0,min(1.0,float(x))) for x in vals]
    while len(vals)<4: vals.append(1.0)
    return tuple(round(x*255) for x in vals[:4])

def _color(mesh,layer,vi,li):
    if layer is None:return (255,255,255,255)
    if layer.domain=='POINT':return _read_color(layer.data[vi])
    if layer.domain=='CORNER':return _read_color(layer.data[li])
    return (255,255,255,255)

def _first_uv_layer(mesh):
    return mesh.uv_layers[0] if len(mesh.uv_layers) else None

def _mesh_export_metadata(mesh):
    uv=_first_uv_layer(mesh); col=_first_color_layer(mesh)
    return {
        'uv_name': uv.name if uv is not None else None,
        'color_name': col.name if col is not None else None,
        'color_domain': col.domain if col is not None else None,
    }

def _material_spec_string(mat):
    """Return the current Blender-visible material spec first.

    Copied/imported materials can retain stale NBA Live metadata from the
    source stadium. The visible Blender material name is now authoritative;
    imported metadata is only a fallback if the material has no usable name.
    """
    visible=str(mat.name or '').strip()
    if visible:
        return visible

    try:
        v=mat.nba_live_environment.texture_name.strip()
        if v:return v
    except Exception:
        pass

    return str(mat.get('nba_live_material_name','')).strip()

def _parse_material_spec(raw,default_rms=ebo_synthetic_static.DEFAULT_RMS):
    raw=str(raw).strip()
    if not raw:
        raise ebo_synthetic_static.SyntheticEboError('Material texture name/spec cannot be empty')
    m=RMS_SUFFIX_RE.match(raw)
    if m:
        asset=m.group('asset').strip()
        rms=m.group('rms').strip()
        if not asset:
            raise ebo_synthetic_static.SyntheticEboError(
                f"Material spec {raw!r} is missing the texture name before [RMS]."
            )
    else:
        asset=raw
        rms=default_rms
    try:
        profile=rms_profiles.resolve(rms)
    except KeyError as exc:
        raise ebo_synthetic_static.SyntheticEboError(
            f"Unknown RMS {rms!r}. Known: {', '.join(rms_profiles.names())}"
        ) from exc
    return asset, profile.name

def _texname(mat,default_rms=ebo_synthetic_static.DEFAULT_RMS):
    return _parse_material_spec(_material_spec_string(mat),default_rms)[0]

def _rmsname(mat,default_rms=ebo_synthetic_static.DEFAULT_RMS):
    return _parse_material_spec(_material_spec_string(mat),default_rms)[1]

def _archive(mat):
    try:
        v=mat.nba_live_environment.archive
        if v in {'MAIN','VRAM'}: return v
    except Exception: pass
    return 'VRAM' if str(mat.get('nba_live_fsh_archive','MAIN')).upper()=='VRAM' else 'MAIN'

def _texpath(mat):
    """Resolve the current Blender image first, imported metadata second.

    Priority:
      1. Image Texture feeding Principled BSDF Base Color
      2. Active Image Texture node
      3. Other Image Texture nodes
      4. nba_live_environment.texture_path (legacy/import fallback)
      5. nba_live_texture_path (legacy/import fallback)
    """
    cand=[]

    if mat.use_nodes and mat.node_tree:
        nodes=mat.node_tree.nodes

        # Prefer the image actually connected to a Principled BSDF Base Color.
        for node in nodes:
            if node.type!='BSDF_PRINCIPLED':
                continue
            base=node.inputs.get('Base Color')
            if base is None:
                continue
            for link in base.links:
                src=link.from_node
                if src and src.type=='TEX_IMAGE' and src.image is not None and src.image.filepath:
                    cand.append(Path(bpy.path.abspath(src.image.filepath)))

        # Then prefer Blender's active image node.
        active=nodes.active
        if active is not None and active.type=='TEX_IMAGE' and active.image is not None and active.image.filepath:
            cand.append(Path(bpy.path.abspath(active.image.filepath)))

        # Finally consider any other image nodes in the material.
        for node in nodes:
            if node.type=='TEX_IMAGE' and node.image is not None and node.image.filepath:
                cand.append(Path(bpy.path.abspath(node.image.filepath)))

    # Imported NBA Live metadata is now fallback-only.
    try:
        v=mat.nba_live_environment.texture_path.strip()
        if v:cand.append(Path(bpy.path.abspath(v)))
    except Exception:
        pass

    v=str(mat.get('nba_live_texture_path','')).strip()
    if v:
        cand.append(Path(bpy.path.abspath(v)))

    seen=set()
    for p in cand:
        try:
            p=p.resolve()
        except OSError:
            continue
        key=str(p).casefold()
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            return p
    return None

def _objects(context):
    objs=[o for o in context.selected_objects if o.type=='MESH']
    if not objs: raise ebo_synthetic_static.SyntheticEboError('Select at least one mesh')
    if len({o.name for o in objs})!=len(objs):
        raise ebo_synthetic_static.SyntheticEboError('Geometry names must be unique')
    return objs

def _geometry(context,obj,transparent=False,normalize_zero_alpha=False,default_rms=ebo_synthetic_static.DEFAULT_RMS,geometry_flags=ebo_synthetic_static.STADIUM_GEOMETRY_FLAGS,aux_chunk_flags=0,raw_toc_flags=0):
    dg=context.evaluated_depsgraph_get()
    ev=obj.evaluated_get(dg)
    me=ev.to_mesh(preserve_all_data_layers=True,depsgraph=dg)
    if me is None:
        raise ebo_synthetic_static.SyntheticEboError(f'Could not evaluate {obj.name}')
    try:
        me.calc_loop_triangles()
        uv=_first_uv_layer(me)
        color_layer=_first_color_layer(me)
        matrix=obj.matrix_world
        batches=[]
        for mi,slot in enumerate(obj.material_slots):
            mat=slot.material
            if mat is None: continue
            tris=[t for t in me.loop_triangles if t.material_index==mi]
            if not tris: continue
            texture_name=_texname(mat,default_rms)
            rms_name=_rmsname(mat,default_rms)
            lookup={}; pos=[]; uvs=[]; cols=[]; outtris=[]
            for tri in tris:
                ot=[]
                for li in tri.loops:
                    vi=me.loops[li].vertex_index
                    ruv=(0.0,0.0) if uv is None else (float(uv.data[li].uv.x),1.0-float(uv.data[li].uv.y))
                    rgba=_color(me,color_layer,vi,li)
                    key=(vi,round(ruv[0],9),round(ruv[1],9),*rgba)
                    oi=lookup.get(key)
                    if oi is None:
                        co=matrix@me.vertices[vi].co
                        oi=len(pos); lookup[key]=oi
                        pos.append((float(co.x),float(co.z),-float(co.y)))
                        uvs.append(ruv)
                        cols.append(rgba)
                    ot.append(oi)
                outtris.append(tuple(ot))
            # RGB-only imports/OBJ workflows can leave the Colour alpha byte at 0.
            # Opaque rendering may ignore it, but the stadium _trans pass does not.
            # Treat an entirely-zero material alpha channel as "alpha was absent"
            # and restore the EA/default visible value FF. Users can opt out with
            # material custom property nba_live_keep_zero_alpha=True.
            if (transparent or normalize_zero_alpha) and cols and all(c[3] == 0 for c in cols) and not bool(mat.get('nba_live_keep_zero_alpha', False)):
                cols=[(c[0],c[1],c[2],255) for c in cols]
            batches.append(
                ebo_synthetic_static.SyntheticMaterialBatch(
                    texture_name,tuple(pos),tuple(uvs),tuple(cols),tuple(outtris),rms_name
                )
            )
        if not batches:
            raise ebo_synthetic_static.SyntheticEboError(f'{obj.name}: no usable material faces')
        return ebo_synthetic_static.SyntheticGeometry(obj.name,tuple(batches),geometry_flags,aux_chunk_flags,raw_toc_flags)
    finally:
        ev.to_mesh_clear()

def _base(out):
    s=out.stem
    return s[:-6] if s.lower().endswith('_trans') else s

def _textures(objs):
    d={'MAIN':{},'VRAM':{}}
    for o in objs:
        for s in o.material_slots:
            m=s.material
            if m is None:continue
            name=_texname(m)
            p=_texpath(m)
            if p is None:continue
            archive=_archive(m)
            prev=d[archive].get(name)
            if prev is not None and prev != p:
                raise synthetic_fsh.SyntheticFshError(
                    f'Texture {name!r} in {archive} maps to two different images.'
                )
            d[archive][name]=p
    return d


def _objects_in_named_collection(selected, name):
    return [
        obj for obj in selected
        if obj.type == 'MESH' and any(col.name == name for col in obj.users_collection)
    ]


def _stadium_selected_groups(context):
    selected=[o for o in context.selected_objects if o.type=='MESH']
    std=_objects_in_named_collection(selected,'std')
    trans=_objects_in_named_collection(selected,'std_trans')
    highref=_objects_in_named_collection(selected,'std_highref')
    other=[
        o.name for o in selected
        if o not in std and o not in trans and o not in highref
    ]
    if other:
        raise ebo_synthetic_static.SyntheticEboError(
            'Stadium mode requires selected meshes to belong to collection '
            'std, std_trans, or std_highref. Outside selection: ' + ', '.join(other)
        )
    if not std:
        raise ebo_synthetic_static.SyntheticEboError(
            'Stadium mode requires at least one selected mesh in collection "std".'
        )
    if not trans:
        raise ebo_synthetic_static.SyntheticEboError(
            'Stadium mode requires at least one selected mesh in collection "std_trans".'
        )
    return std,trans,highref


def _all_unique_texture_sources(objs):
    textures={}
    explicit={}
    for obj in objs:
        for slot in obj.material_slots:
            mat=slot.material
            if mat is None:
                continue
            name=_texname(mat)
            path=_texpath(mat)
            if path is None:
                raise synthetic_fsh.SyntheticFshError(
                    f'{obj.name}/{name}: texture PNG path is missing.'
                )
            previous=textures.get(name)
            if previous is not None and previous != path:
                raise synthetic_fsh.SyntheticFshError(
                    f'TextureName {name!r} is used with two different PNG files.'
                )
            textures[name]=path
            override=str(mat.get('nba_live_fsh_archive','')).upper().strip()
            if override in {'MAIN','VRAM'}:
                old=explicit.get(name)
                if old is not None and old != override:
                    raise synthetic_fsh.SyntheticFshError(
                        f'TextureName {name!r} has conflicting MAIN/VRAM overrides.'
                    )
                explicit[name]=override
    return textures,explicit



def _balanced_texture_inputs(objs):
    alltex,explicit=_all_unique_texture_sources(objs)
    return alltex,explicit


def _auto_split_stadium_textures(objs):
    """Share textures across std/std_trans and keep main FSH relatively light.

    Explicit material custom property nba_live_fsh_archive=MAIN/VRAM wins.
    Remaining textures are split by source PNG byte size: roughly the lightest
    30 percent goes to MAIN and larger textures go to VRAM.
    """
    alltex,explicit=_all_unique_texture_sources(objs)
    result={'MAIN':{},'VRAM':{}}

    for name,where in explicit.items():
        result[where][name]=alltex[name]

    undecided=[(name,path,path.stat().st_size) for name,path in alltex.items() if name not in explicit]
    undecided.sort(key=lambda item:(item[2],item[0]))

    if undecided:
        total=sum(size for _,_,size in undecided)
        target=max(1,int(total*0.30))
        running=0
        # When there are >=2 automatic textures, ensure at least one remains for VRAM.
        for idx,(name,path,size) in enumerate(undecided):
            remaining=len(undecided)-idx
            if running < target and not (remaining == 1 and not result['VRAM'] and len(undecided) > 1):
                result['MAIN'][name]=path
                running+=size
            else:
                result['VRAM'][name]=path

    # If explicit choices or tiny sets left one archive empty, rebalance one
    # automatically assigned texture so a normal stadium package gets both files.
    if len(alltex) >= 2:
        if not result['MAIN']:
            candidates=[(p.stat().st_size,n,p) for n,p in result['VRAM'].items() if n not in explicit]
            if candidates:
                _,n,p=min(candidates)
                del result['VRAM'][n]; result['MAIN'][n]=p
        if not result['VRAM']:
            candidates=[(p.stat().st_size,n,p) for n,p in result['MAIN'].items() if n not in explicit]
            if candidates:
                _,n,p=max(candidates)
                del result['MAIN'][n]; result['VRAM'][n]=p

    return result


def _stadium_base_from_path(path):
    stem=Path(path).stem
    if stem.lower().endswith('_trans'):
        stem=stem[:-6]
    return stem


class NBA_OT_create_stadium_package(bpy.types.Operator,ExportHelper):
    bl_idname='nba_live.create_stadium_package'
    bl_label='Export Stadium Package'
    bl_options={'REGISTER'}
    filename_ext='.ebo'
    filter_glob:StringProperty(default='*.ebo',options={'HIDDEN'})

    def execute(self,context):
        try:
            std_objs,trans_objs,highref_objs=_stadium_selected_groups(context)
            basepath=Path(self.filepath).resolve()
            base=_stadium_base_from_path(basepath)
            outdir=basepath.parent
            outdir.mkdir(parents=True,exist_ok=True)

            std_geos=tuple(_geometry(context,o,transparent=False) for o in std_objs)
            trans_geos=tuple(_geometry(context,o,transparent=True) for o in trans_objs)

            std_ebo=outdir/f'{base}.ebo'
            trans_ebo=outdir/f'{base}_trans.ebo'
            std_ebo.write_bytes(ebo_synthetic_static.build_texture_stadium_ebo(std_geos))
            trans_ebo.write_bytes(ebo_synthetic_static.build_texture_stadium_ebo(trans_geos))

            highref_ebo=None
            if highref_objs:
                # Genuine highref stadiums use StadiumReflect + reflection RMSes.
                # We keep object names user-controlled, but default materials to
                # TextureStadiumRef and use the verified reflection Geometry flags.
                highref_geos=tuple(
                    _geometry(
                        context,o,
                        transparent=False,
                        normalize_zero_alpha=True,
                        default_rms='TextureStadiumRef',
                        geometry_flags=0x1F001407,
                        aux_chunk_flags=1,
                        raw_toc_flags=1,
                    )
                    for o in highref_objs
                )
                highref_ebo=outdir/f'{base}_highref.ebo'
                highref_ebo.write_bytes(
                    ebo_synthetic_static.build_texture_stadium_ebo(highref_geos)
                )

            texture_objs=std_objs+trans_objs+highref_objs
            alltex,explicit=_balanced_texture_inputs(texture_objs)
            packed=synthetic_fsh.create_native_fsh_pair(
                alltex,
                outdir/f'{base}.fsh',
                outdir/f'{base}_vram.fsh',
                explicit,
            )
            main_fsh=packed['MAIN']
            vram_fsh=packed['VRAM']

        except (ebo_synthetic_static.SyntheticEboError,synthetic_fsh.SyntheticFshError,OSError,ValueError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        created=[std_ebo.name,trans_ebo.name]
        if highref_ebo is not None:
            created.append(highref_ebo.name)
        created.extend([main_fsh.name,vram_fsh.name])
        self.report({'INFO'},'Created stadium package: ' + ', '.join(created))
        return {'FINISHED'}


class NBA_OT_create_synthetic_package(bpy.types.Operator,ExportHelper):
    bl_idname='nba_live.create_synthetic_package'
    bl_label='Create Synthetic EBO + NEWFSH Workspace'
    bl_options={'REGISTER'}
    filename_ext='.ebo'
    filter_glob:StringProperty(default='*.ebo',options={'HIDDEN'})
    prepare_newfsh_workspace:BoolProperty(name='Prepare .newfsh Workspace',default=True)

    def execute(self,context):
        try:
            objs=_objects(context)
            geos=tuple(_geometry(context,o) for o in objs)
            out=Path(self.filepath).resolve()
            out.parent.mkdir(parents=True,exist_ok=True)
            out.write_bytes(ebo_synthetic_static.build_texture_stadium_ebo(geos))
            workspace=None
            if self.prepare_newfsh_workspace:
                tx=_textures(objs)
                workspace=synthetic_fsh.prepare_newfsh_workspace(tx,out.parent,_base(out))
        except (ebo_synthetic_static.SyntheticEboError,synthetic_fsh.SyntheticFshError,OSError,ValueError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}
        extra=f', workspace={workspace.name}' if workspace else ''
        self.report({'INFO'},f'Created {len(geos)} Geometry object(s), {sum(len(g.materials) for g in geos)} material(s){extra}')
        return {'FINISHED'}


COURT_FLAGS={
    '2005':0x31011C09,
    '2006':0x22001407,
}

def _selected_meshes(context):
    objs=[o for o in context.selected_objects if o.type=='MESH']
    if not objs:
        raise ebo_synthetic_static.SyntheticEboError('Select at least one court mesh.')
    # Court Geometry serialization order affects rendering. Sorting by Blender
    # object name makes user prefixes (a_, b_, c_...) deterministic.
    return sorted(objs,key=lambda o:o.name.casefold())

def _court_textures(objs):
    """Court FSH pair uses all selected court material textures, deduplicated."""
    alltex,explicit=_all_unique_texture_sources(objs)
    result={'MAIN':{},'VRAM':{}}

    # User archive overrides always win.
    for name,where in explicit.items():
        result[where][name]=alltex[name]

    undecided=[(name,path,path.stat().st_size) for name,path in alltex.items() if name not in explicit]
    undecided.sort(key=lambda item:(item[2],item[0]))

    # Court convention: keep MAIN relatively light, with larger artwork in VRAM.
    # Use ~30% of source PNG bytes for MAIN as an initial heuristic.
    if undecided:
        total=sum(size for _,_,size in undecided)
        target=max(1,int(total*0.30))
        running=0
        for idx,(name,path,size) in enumerate(undecided):
            remaining=len(undecided)-idx
            if running < target and not (remaining == 1 and not result['VRAM'] and len(undecided)>1):
                result['MAIN'][name]=path
                running+=size
            else:
                result['VRAM'][name]=path

    if len(alltex)>=2:
        if not result['MAIN']:
            candidates=[(p.stat().st_size,n,p) for n,p in result['VRAM'].items() if n not in explicit]
            if candidates:
                _,n,p=min(candidates); del result['VRAM'][n]; result['MAIN'][n]=p
        if not result['VRAM']:
            candidates=[(p.stat().st_size,n,p) for n,p in result['MAIN'].items() if n not in explicit]
            if candidates:
                _,n,p=max(candidates); del result['MAIN'][n]; result['VRAM'][n]=p

    return result

class NBA_OT_create_court_package(bpy.types.Operator,ExportHelper):
    bl_idname='nba_live.create_court_package'
    bl_label='Export Court Package'
    bl_options={'REGISTER'}
    filename_ext='.ebo'
    filter_glob:StringProperty(default='*.ebo',options={'HIDDEN'})

    def execute(self,context):
        try:
            objs=_selected_meshes(context)
            game=context.scene.nba_live_court_game
            flags=COURT_FLAGS[game]

            # Genuine 05/06 Boston courts use:
            # - gNBACourt_RMRuntime
            # - aux chunk flags 1
            # - raw PC i8 TOC flags 1
            geos=tuple(
                _geometry(
                    context,o,
                    transparent=False,
                    default_rms='NBACourt',
                    geometry_flags=flags,
                    aux_chunk_flags=1,
                    raw_toc_flags=1,
                )
                for o in objs
            )

            requested=Path(self.filepath).resolve()
            base=requested.stem
            if base.lower().endswith('.ebo'):
                base=base[:-4]
            outdir=requested.parent
            outdir.mkdir(parents=True,exist_ok=True)

            ebo_path=outdir/f'{base}.ebo'
            ebo_path.write_bytes(ebo_synthetic_static.build_texture_stadium_ebo(geos))

            alltex,explicit=_balanced_texture_inputs(objs)
            packed=synthetic_fsh.create_native_fsh_pair(
                alltex,
                outdir/f'{base}.fsh',
                outdir/f'{base}_vram.fsh',
                explicit,
            )
            main_fsh=packed['MAIN']
            vram_fsh=packed['VRAM']

        except (ebo_synthetic_static.SyntheticEboError,synthetic_fsh.SyntheticFshError,OSError,ValueError) as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}

        self.report(
            {'INFO'},
            f'Created NBA Live {game} court: {ebo_path.name}, '
            f'{main_fsh.name}, {vram_fsh.name}'
        )
        return {'FINISHED'}


class NBA_PT_synthetic_static_creator(bpy.types.Panel):
    bl_label='Stadium / Court EBO'
    bl_options = {'DEFAULT_CLOSED'}
    bl_idname='NBA_PT_synthetic_static_creator'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='NBA Live'

    def draw(self,context):
        b=self.layout.box()
        b.label(text='Stadium / Court Export',icon='MESH_CUBE')
        objs=[o for o in context.selected_objects if o.type=='MESH']
        b.label(text=f'Selected Geometry: {len(objs)}')
        for o in objs[:6]:
            b.label(text=f'{o.name}: {len([s for s in o.material_slots if s.material])} material(s)')
            meta=_mesh_export_metadata(o.data)
            b.label(text=f"  UV: {meta['uv_name'] or 'none -> (0,0)'}")
            if meta['color_name']:
                b.label(text=f"  Color: {meta['color_name']} [{meta['color_domain']}]")
            else:
                b.label(text='  Color: none -> white')
            for s in o.material_slots[:4]:
                m=s.material
                if m is None: continue
                try:
                    asset,rms=_parse_material_spec(_material_spec_string(m))
                    b.label(text=f'  {asset} [{rms}]')
                except Exception:
                    b.label(text=f'  {m.name}')
        package=self.layout.box()
        package.label(text='Mode')
        package.prop(context.scene,'nba_live_stadium_mode',text='Stadium')
        package.prop(context.scene,'nba_live_court_mode',text='Court')
        if context.scene.nba_live_stadium_mode and context.scene.nba_live_court_mode:
            package.label(text='Choose Stadium OR Court, not both',icon='ERROR')
        elif context.scene.nba_live_stadium_mode:
            package.label(text='Collections: std + std_trans')
            package.label(text='Optional reflection collection: std_highref')
            package.label(text='Highref known Geometry name: StadiumReflect')
            package.label(text='Select meshes from the collections to export')
            package.operator(NBA_OT_create_stadium_package.bl_idname,icon='PACKAGE')
        elif context.scene.nba_live_court_mode:
            package.prop(context.scene,'nba_live_court_game',text='Game')
            package.label(text='Default RMS: NBACourt')
            warn=package.box()
            warn.label(text='Court naming warning',icon='INFO')
            warn.label(text='Known working Geometry names:')
            warn.label(text='  logos merged -> aalogo1Shape')
            warn.label(text='  endcourt     -> ccskirt1Shape')
            warn.label(text='  floor        -> floor4Shape')
            warn.label(text='Names are not enforced.')
            package.operator(NBA_OT_create_court_package.bl_idname,icon='PACKAGE')
        else:
            package.label(text='Choose Stadium or Court.',icon='INFO')
        n=self.layout.box()
        n.label(text='Material: texture [RMS], e.g. 0036 [ScrollTextureDim]')
        n.label(text='Stadium: std + std_trans, optional std_highref')
        n.label(text='Court: NBA Live 2005 / 2006')
        n.label(text='Native DXT1/DXT5 FSH generation')

CLASSES=(NBA_OT_create_stadium_package,NBA_OT_create_court_package,NBA_PT_synthetic_static_creator)

def register():
    from bpy.props import EnumProperty
    bpy.types.Scene.nba_live_stadium_mode=BoolProperty(
        name='Stadium Package',
        description='Export selected std/std_trans collections as one stadium package',
        default=False,
    )
    bpy.types.Scene.nba_live_court_mode=BoolProperty(
        name='Court Package',
        description='Export selected meshes using the NBA court profile',
        default=False,
    )
    bpy.types.Scene.nba_live_court_game=EnumProperty(
        name='Court Game',
        items=(
            ('2006','NBA Live 06','Use the NBA Live 06 court Geometry profile'),
            ('2005','NBA Live 2005','Use the NBA Live 2005 court Geometry profile'),
        ),
        default='2006',
    )
    for cls in CLASSES: bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(CLASSES): bpy.utils.unregister_class(cls)
    for name in ('nba_live_stadium_mode','nba_live_court_mode','nba_live_court_game'):
        if hasattr(bpy.types.Scene,name):
            delattr(bpy.types.Scene,name)
