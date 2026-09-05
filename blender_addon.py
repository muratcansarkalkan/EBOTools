"""Blender UI and direct mesh conversion for NBA Live environment assets."""

import binascii
import json
import math
from pathlib import Path
import struct
import tempfile
import zlib

import bpy
from bpy.props import BoolProperty, EnumProperty, PointerProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper

from . import ebo_core
from . import fsh_archive


COLOR_LAYER = "NBA Live Vertex Colors"
UV_LAYER = "UVMap"
SELECTOR_ATTRIBUTE = "eagl_transform_selector"
PALETTE_ATTRIBUTE = "eagl_palette_size"
SELECTOR_COLOR_ATTRIBUTE = "eagl_selector_debug_color"
COLLECTION_SOURCE = "nba_live_ebo_source"
ARCHIVE_ITEMS = (
    ("MAIN", "Main FSH", "Store the texture in the asset's main .fsh archive"),
    ("VRAM", "VRAM FSH", "Store the texture in the asset's _vram.fsh archive"),
)
_TEMPLATE_ITEMS_CACHE: dict[tuple[str, ...], list[tuple[str, str, str]]] = {}


def _diagnostic(message: str) -> None:
    line = f"[NBA Live] {message}"
    print(line, flush=True)
    try:
        with (Path(tempfile.gettempdir()) / "nba_live_environment_import.log").open(
            "a", encoding="utf-8"
        ) as stream:
            stream.write(line + "\n")
            stream.flush()
    except OSError:
        pass


def _ensure_placeholder_png(path: Path, *, size: int = 64) -> Path:
    """Create an obvious RGBA checkerboard without depending on FSH helpers."""
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tile = max(1, size // 8)
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for x in range(size):
            rows.extend(
                (255, 0, 255, 255)
                if ((x // tile) + (y // tile)) % 2 == 0
                else (16, 16, 16, 255)
            )

    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )
    return path


def _as_path(value: str) -> Path | None:
    return Path(bpy.path.abspath(value)).resolve() if value else None


def _gx_path(context) -> Path:
    addons = context.preferences.addons
    entry = addons.get(__package__)
    if entry is None:
        entry = addons.get(__package__.split(".")[-1])
    preferences = entry.preferences if entry is not None else None
    path = _as_path(getattr(preferences, "gx_path", ""))
    if path is None:
        raise fsh_archive.FshError(
            "Set GX Executable once in Edit > Preferences > Add-ons > "
            "NBA Live Environment Tools."
        )
    return path


def _game_to_blender(position: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = position
    return x, -z, y


def _blender_to_game(position) -> tuple[float, float, float]:
    return float(position.x), float(position.z), -float(position.y)


def _byte_color(values) -> tuple[int, int, int, int]:
    return tuple(max(0, min(255, round(float(value) * 255))) for value in values[:4])


def _read_color(item) -> tuple[float, float, float, float]:
    return tuple(item.color_srgb if hasattr(item, "color_srgb") else item.color)


def _write_color(item, rgba: tuple[float, float, float, float]) -> None:
    if hasattr(item, "color_srgb"):
        item.color_srgb = rgba
    else:
        item.color = rgba


def _find_texture(
    name: str,
    owners: tuple[str, ...],
    texture_root: Path | None,
    extra_directory: Path | None,
) -> Path | None:
    working_name = fsh_archive.working_texture_name(name)
    candidates: list[Path] = []
    for owner in owners:
        if texture_root:
            candidates.append(texture_root / Path(owner).stem / f"{working_name}.png")
        if extra_directory:
            candidates.append(extra_directory / Path(owner).stem / f"{working_name}.png")
    if extra_directory:
        candidates.append(extra_directory / f"{working_name}.png")
    if texture_root:
        candidates.append(texture_root / f"{working_name}.png")
    # EBO names omit the GX input slot used by FSH directory entries. Resolve
    # ``ball`` to the canonical safe filename ``texture0-ball.png`` instead of
    # creating and attaching a misleading ``ball.png`` alias.
    qualified_matches: list[Path] = []
    for owner in owners:
        for base in (texture_root, extra_directory):
            folder = base / Path(owner).stem if base else None
            if folder and folder.is_dir():
                qualified_matches.extend(folder.glob(f"*-{working_name}.png"))
    unique_matches = list(dict.fromkeys(path.resolve() for path in qualified_matches))
    if len(unique_matches) == 1:
        return unique_matches[0]
    if len(unique_matches) > 1:
        raise fsh_archive.FshError(
            f"Texture {name!r} matches multiple slot-qualified PNG files: "
            + ", ".join(path.name for path in unique_matches)
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for root in (extra_directory, texture_root):
        if root and root.is_dir():
            matches = list(root.rglob(f"{working_name}.png"))
            if matches:
                return matches[0]
    return None


def _material(
    asset_name: str,
    texture_name: str,
    owners: tuple[str, ...],
    texture_path: Path | None,
    *,
    transparent: bool,
    rms_type: str | None = None,
    has_vertex_colors: bool = True,
    extend_uvs: bool = False,
    textureless: bool = False,
    placeholder: bool = False,
):
    display_name = f"EBO.{texture_name}" + (f" [{rms_type}]" if rms_type else "")
    # Never reuse a material datablock from a previous import. Rebuilding its
    # nodes would silently change the texture on the already imported asset.
    material = bpy.data.materials.new(display_name)
    material["nba_live_material_name"] = texture_name
    material["nba_live_original_material_name"] = texture_name
    material["nba_live_rms_type"] = rms_type or ""
    material["nba_live_fsh_archives"] = json.dumps(owners)
    material["nba_live_textureless"] = textureless
    material["nba_live_placeholder_texture"] = placeholder
    if texture_path:
        material["nba_live_texture_path"] = str(texture_path)
    properties = material.nba_live_environment
    properties.texture_name = texture_name
    properties.archive = "VRAM" if owners and all(fsh_archive.archive_kind(owner) == "VRAM" for owner in owners) else "MAIN"
    properties.texture_path = str(texture_path) if texture_path else ""
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    links = material.node_tree.links

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (650, 0)
    shader = nodes.new("ShaderNodeBsdfPrincipled")
    shader.location = (400, 0)
    shader.inputs["Roughness"].default_value = 0.75
    links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    colors = None
    if has_vertex_colors:
        colors = nodes.new("ShaderNodeVertexColor")
        colors.layer_name = COLOR_LAYER
        colors.label = "EBO Vertex Colors"
        colors.location = (-550, -140)

    if texture_path:
        image_node = nodes.new("ShaderNodeTexImage")
        image_node.name = "EBO Texture"
        image_node.label = "Missing EBO Texture" if placeholder else "EBO Texture"
        image_node.location = (-550, 160)
        image_node.image = bpy.data.images.load(str(texture_path), check_existing=True)
        image_node.extension = "EXTEND" if extend_uvs else "REPEAT"
        if colors is not None:
            multiply = nodes.new("ShaderNodeMixRGB")
            multiply.blend_type = "MULTIPLY"
            multiply.inputs[0].default_value = 1.0
            multiply.label = "Texture × Vertex Color"
            multiply.location = (-70, 80)
            links.new(image_node.outputs["Color"], multiply.inputs[1])
            links.new(colors.outputs["Color"], multiply.inputs[2])
            links.new(multiply.outputs["Color"], shader.inputs["Base Color"])

            alpha = nodes.new("ShaderNodeMath")
            alpha.operation = "MULTIPLY"
            alpha.label = "Texture Alpha × Vertex Alpha"
            alpha.location = (-50, -180)
            links.new(image_node.outputs["Alpha"], alpha.inputs[0])
            links.new(colors.outputs["Alpha"], alpha.inputs[1])
            links.new(alpha.outputs["Value"], shader.inputs["Alpha"])
        else:
            links.new(image_node.outputs["Color"], shader.inputs["Base Color"])
            links.new(image_node.outputs["Alpha"], shader.inputs["Alpha"])
    elif colors is not None:
        links.new(colors.outputs["Color"], shader.inputs["Base Color"])
        links.new(colors.outputs["Alpha"], shader.inputs["Alpha"])

    if transparent:
        if hasattr(material, "surface_render_method"):
            material.surface_render_method = "DITHERED"
        elif hasattr(material, "blend_method"):
            material.blend_method = "HASHED"
        if hasattr(material, "use_transparency_overlap"):
            material.use_transparency_overlap = False
    return material


def _build_object(
    collection,
    court: ebo_core.Court,
    mesh_record: ebo_core.Mesh,
    materials: dict[tuple[str, str], object],
):
    _diagnostic(f"Object {mesh_record.name}: decoding {len(mesh_record.batches)} material groups")
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    face_batches: list[int] = []
    vertex_uvs: list[tuple[float, float]] = []
    vertex_colors: list[tuple[float, float, float, float]] = []
    has_vertex_colors = any(batch.colors is not None for batch in mesh_record.batches)
    has_uvs = any(batch.uvs is not None for batch in mesh_record.batches)
    has_selectors = any(batch.selectors for batch in mesh_record.batches)
    vertex_selectors: list[int] = []
    vertex_palette_sizes: list[int] = []

    for batch in mesh_record.batches:
        base = len(vertices)
        for index in range(batch.vertex_count):
            position = struct.unpack_from("<3f", court.data, batch.positions.data_offset + index * 12)
            if batch.uvs is not None:
                u, v = struct.unpack_from("<2f", court.data, batch.uvs.data_offset + index * 8)
            else:
                u = v = 0.0
            if batch.colors is not None:
                blue, green, red, alpha = struct.unpack_from(
                    "<4B", court.data, batch.colors.data_offset + index * 4
                )
            else:
                red = green = blue = alpha = 255
            vertices.append(_game_to_blender(position))
            vertex_uvs.append((u, 1.0 - v))
            vertex_colors.append((red / 255, green / 255, blue / 255, alpha / 255))
            vertex_selectors.append(batch.selectors[index] if batch.selectors else -1)
            vertex_palette_sizes.append(batch.palette_count if batch.selectors else 0)
        for triangle in batch.triangles:
            faces.append(tuple(base + index for index in triangle))
            face_batches.append(batch.batch_index)

    _diagnostic(
        f"Object {mesh_record.name}: creating mesh with {len(vertices)} vertices and {len(faces)} faces"
    )
    geometry = bpy.data.meshes.new(mesh_record.name)
    geometry.from_pydata(vertices, [], faces)
    if len(geometry.polygons) != len(faces):
        raise ebo_core.CourtFormatError(
            f"Blender created {len(geometry.polygons)} polygons for {len(faces)} input faces "
            f"on object {mesh_record.name!r}."
        )
    obj = bpy.data.objects.new(mesh_record.name, geometry)
    collection.objects.link(obj)
    obj["nba_live_mesh_name"] = mesh_record.name
    obj["nba_live_batch_counts"] = json.dumps([batch.vertex_count for batch in mesh_record.batches])
    obj["nba_live_batch_materials"] = json.dumps([batch.material for batch in mesh_record.batches])

    for batch in mesh_record.batches:
        geometry.materials.append(materials[mesh_record.name, batch.material])
    for polygon, material_index in zip(geometry.polygons, face_batches):
        polygon.material_index = material_index

    if has_uvs:
        _diagnostic(f"Object {mesh_record.name}: creating UV layer for {len(geometry.loops)} corners")
        uv_layer = geometry.uv_layers.new(name=UV_LAYER)
        for polygon in geometry.polygons:
            for loop_index in polygon.loop_indices:
                vertex_index = geometry.loops[loop_index].vertex_index
                uv_layer.data[loop_index].uv = vertex_uvs[vertex_index]

    # EBO stores one color per vertex, not one color per face corner. POINT
    # domain avoids unnecessary loop-domain allocation and reduces exposure to
    # Blender 5.0's native color-attribute allocation/update path.
    if has_vertex_colors:
        _diagnostic(f"Object {mesh_record.name}: creating vertex colors for {len(vertices)} points")
        color_layer = geometry.color_attributes.new(name=COLOR_LAYER, type="BYTE_COLOR", domain="POINT")
        if len(color_layer.data) != len(vertices):
            raise ebo_core.CourtFormatError(
                f"Blender allocated {len(color_layer.data)} vertex colors for {len(vertices)} vertices "
                f"on object {mesh_record.name!r}."
            )
        for vertex_index, color in enumerate(vertex_colors):
            _write_color(color_layer.data[vertex_index], color)

    if has_selectors:
        _diagnostic(f"Object {mesh_record.name}: exposing EAGL transform selectors")
        selector_attr = geometry.attributes.new(name=SELECTOR_ATTRIBUTE, type="INT", domain="POINT")
        palette_attr = geometry.attributes.new(name=PALETTE_ATTRIBUTE, type="INT", domain="POINT")
        for index, value in enumerate(vertex_selectors):
            selector_attr.data[index].value = value
            palette_attr.data[index].value = vertex_palette_sizes[index]
    _diagnostic(f"Object {mesh_record.name}: updating mesh")
    geometry.update()
    _diagnostic(f"Object {mesh_record.name}: finished")
    return obj


def import_environment(context, filepath: str, settings) -> tuple[object, int, int]:
    source = Path(filepath).resolve()
    _diagnostic(f"Starting import: {source}")
    court = ebo_core.parse_court(source.read_bytes())
    _diagnostic(
        f"Parsed EBO: {len(court.meshes)} objects, {court.vertex_count} vertices, "
        f"{court.triangle_count} triangles"
    )
    archive_directory = _as_path(settings.archive_directory)
    try:
        archives = fsh_archive.find_archives(source, archive_directory)
    except (fsh_archive.FshError, OSError) as exc:
        archives = ()
        _diagnostic(f"FSH discovery failed; placeholders will be used: {exc}")
    _diagnostic(f"Found FSH archives: {[archive.path.name for archive in archives]}")
    ownership = fsh_archive.texture_ownership(archives)
    texture_root = _as_path(settings.texture_directory)
    if texture_root is None:
        texture_root = source.parent / "nba_live_textures"

    if settings.extract_fsh and archives:
        try:
            gx = _gx_path(context)
            for archive in archives:
                try:
                    _diagnostic(f"Extracting FSH: {archive.path.name}")
                    fsh_archive.extract_archive(archive, gx, texture_root)
                except (fsh_archive.FshError, OSError) as exc:
                    _diagnostic(f"FSH extraction failed for {archive.path.name}: {exc}")
        except (fsh_archive.FshError, OSError) as exc:
            _diagnostic(f"FSH extraction unavailable; placeholders will be used: {exc}")

    asset_name = fsh_archive.asset_base_name(source)
    collection = bpy.data.collections.new(source.stem)
    context.scene.collection.children.link(collection)
    collection[COLLECTION_SOURCE] = str(source)
    collection["nba_live_asset_name"] = asset_name
    collection["nba_live_texture_root"] = str(texture_root)
    collection["nba_live_archives"] = json.dumps([str(archive.path) for archive in archives])
    collection["nba_live_ownership"] = json.dumps(ownership)
    collection["nba_live_transparent"] = source.stem.lower().endswith("_trans")

    extra_directory = _as_path(settings.additional_texture_directory)
    transparent_asset = source.stem.lower().endswith("_trans")
    rms_types = _rms_material_types(court)
    materials: dict[tuple[str, str], object] = {}
    shared_materials: dict[tuple[str, str, tuple[str, ...], bool, bool, bool, bool], object] = {}
    for batch in court.batches:
        key = batch.mesh_name, batch.material
        if key in materials:
            continue
        _diagnostic(f"Creating material: {batch.material}")
        textureless = not batch.texture_names
        owners = () if textureless else ownership.get(batch.material, ())
        placeholder = False
        if textureless:
            texture = None
        else:
            try:
                texture = _find_texture(batch.material, owners, texture_root, extra_directory)
            except (fsh_archive.FshError, OSError) as exc:
                texture = None
                _diagnostic(f"Texture lookup failed for {batch.material}: {exc}")
            if texture is None:
                canonical_name = batch.material
                owner_name = owners[0] if owners else None
                if owner_name:
                    archive = next((item for item in archives if item.path.name == owner_name), None)
                    if archive is not None:
                        try:
                            canonical_name = fsh_archive.resolve_entry_name(archive, batch.material)
                        except fsh_archive.FshError as exc:
                            _diagnostic(f"FSH name lookup failed for {batch.material}: {exc}")
                folder = Path(owner_name).stem if owner_name else asset_name
                placeholder_path = texture_root / folder / f"{fsh_archive.working_texture_name(canonical_name)}.png"
                try:
                    texture = _ensure_placeholder_png(placeholder_path)
                    placeholder = True
                    _diagnostic(f"Created placeholder texture: {texture}")
                except (fsh_archive.FshError, OSError) as exc:
                    _diagnostic(f"Could not create placeholder for {batch.material}: {exc}")
        rms_type = rms_types.get(key, "")
        has_vertex_colors = batch.colors is not None
        extend_uvs = batch.profile == "PLAYER_NORMAL"
        shared_key = batch.material, rms_type, tuple(owners), has_vertex_colors, extend_uvs, textureless, placeholder
        material = shared_materials.get(shared_key)
        if material is None:
            material = _material(
                asset_name,
                batch.material,
                owners,
                texture,
                transparent=transparent_asset,
                rms_type=rms_type or None,
                has_vertex_colors=has_vertex_colors,
                extend_uvs=extend_uvs,
                textureless=textureless,
                placeholder=placeholder,
            )
            shared_materials[shared_key] = material
        materials[key] = material

    for mesh_record in court.meshes:
        _build_object(collection, court, mesh_record, materials)

    context.view_layer.objects.active = next(iter(collection.objects), None)
    for obj in collection.objects:
        obj.select_set(True)
    _diagnostic(f"Import completed: {source.name}")
    return collection, len(court.meshes), sum(
        bool(material.get("nba_live_texture_path")) and not material.get("nba_live_placeholder_texture")
        for material in set(materials.values())
    )


def _active_collection(context):
    obj = context.active_object
    if obj:
        for collection in obj.users_collection:
            if collection.get(COLLECTION_SOURCE):
                return collection
    active = context.view_layer.active_layer_collection.collection
    if active.get(COLLECTION_SOURCE):
        return active
    candidates = [collection for collection in bpy.data.collections if collection.get(COLLECTION_SOURCE)]
    return candidates[0] if len(candidates) == 1 else None


def _ebo_material_spec(material) -> tuple[str, str | None, str]:
    """Return texture, optional template, and archive from an EBO material name.

    Existing group: EBO.<texture> [<RMS type>]
    New group:      EBO.<texture> [<RMS type>]
                    EBO.<texture>.<template>.<main|vram>
    """
    display_name = getattr(material, "name", "")
    if display_name.startswith("EBO."):
        encoded = display_name[4:]
        if encoded.endswith("]") and " [" in encoded:
            texture, rms_label = encoded.rsplit(" [", 1)
            rms_type = rms_label[:-1]
            texture = ebo_core.validate_material_name(texture)
            ebo_core.validate_material_name(rms_type)
            properties = getattr(material, "nba_live_environment", None)
            archive = getattr(properties, "archive", "MAIN") if properties else "MAIN"
            # Imported groups already contain their EBO descriptor and use the
            # bracket only as a readable RMS label. For an ordinary material
            # created in Blender, the same label selects the RMS template to
            # clone, e.g. EBO.new0 [TextureStadium].
            original_name = material.get("nba_live_original_material_name", "")
            template = None if original_name else rms_type
            return texture, template, archive
        parts = encoded.rsplit(".", 2)
        if len(parts) == 3 and parts[2].lower() in {"main", "vram"}:
            texture, template, archive = parts
            texture = ebo_core.validate_material_name(texture)
            template = ebo_core.validate_material_name(template)
            return texture, template, archive.upper()
        texture = ebo_core.validate_material_name(encoded)
        properties = getattr(material, "nba_live_environment", None)
        archive = getattr(properties, "archive", "MAIN") if properties else "MAIN"
        return texture, None, archive

    # Compatibility with scenes imported by versions through 0.3.0. New
    # Blender materials must use the EBO.* naming convention.
    properties = getattr(material, "nba_live_environment", None)
    legacy_name = (
        properties.texture_name
        if properties and properties.texture_name
        else material.get("nba_live_material_name", "")
    )
    if legacy_name:
        template = None
        if material.get("nba_live_new_material"):
            template = "__legacy_template__"
        archive = getattr(properties, "archive", "MAIN") if properties else "MAIN"
        return ebo_core.validate_material_name(legacy_name), template, archive
    raise ebo_core.CourtFormatError(
        f"Material {display_name or '<unnamed>'!r} is not an EBO material. "
        "Rename it EBO.<texture> or EBO.<texture>.<template>.<main|vram>."
    )


def _rms_material_types(court: ebo_core.Court) -> dict[tuple[str, str], str]:
    """Map each material group to its bound RMS render-method type."""
    rows = {
        mesh.offset + 104 + batch.batch_index * 48: (mesh.name, batch.material)
        for mesh in court.meshes
        for batch in mesh.batches
    }
    result: dict[tuple[str, str], str] = {}
    for group in ebo_core.external_variable_groups(court):
        if not group.name.startswith("g") or not group.name.endswith("_RMRuntime"):
            continue
        rms_type = group.name[1:-10]
        for target in group.targets:
            owner = rows.get(target)
            if owner is not None:
                result[owner] = rms_type
    return result


def _resolve_material_template(
    mesh_record: ebo_core.Mesh,
    template_name: str,
    rms_types: dict[tuple[str, str], str],
) -> ebo_core.Batch | None:
    """Resolve either an existing texture name or an RMS type on this object."""
    direct = next((batch for batch in mesh_record.batches if batch.material == template_name), None)
    if direct is not None:
        return direct
    wanted = template_name.casefold()
    return next(
        (
            batch
            for batch in mesh_record.batches
            if rms_types.get((mesh_record.name, batch.material), "").casefold() == wanted
        ),
        None,
    )


def _material_name(obj, polygon) -> str:
    if polygon.material_index >= len(obj.material_slots):
        raise ebo_core.CourtFormatError(f"Object {obj.name!r} has a face without an assigned material.")
    material = obj.material_slots[polygon.material_index].material
    if material is None:
        raise ebo_core.CourtFormatError(f"Object {obj.name!r} has an empty material slot.")
    return _ebo_material_spec(material)[0]


def _material_image_path(material) -> Path | None:
    # The visible Blender image node is the source of truth. This lets users
    # replace a texture through Blender's normal node/image selector.
    if material.use_nodes and material.node_tree:
        for node in material.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image and node.image.filepath:
                return _as_path(node.image.filepath)
    properties = getattr(material, "nba_live_environment", None)
    if properties and properties.texture_path:
        return _as_path(properties.texture_path)
    stored = material.get("nba_live_texture_path")
    return _as_path(stored) if stored else None


def _template_items(self, context):
    obj = context.active_object if context else None
    if obj is None or obj.type != "MESH":
        key = ("__none__",)
        return _TEMPLATE_ITEMS_CACHE.setdefault(key, [("0", "No imported object selected", "")])
    original = json.loads(obj.get("nba_live_batch_materials", "[]"))
    removed = set(json.loads(obj.get("nba_live_removed_materials", "[]")))
    key = (obj.get("nba_live_mesh_name", obj.name), *original, "__removed__", *sorted(removed))
    # Blender keeps references to dynamic EnumProperty strings; retaining the
    # returned tuples prevents native use-after-free crashes during redraw.
    if key not in _TEMPLATE_ITEMS_CACHE:
        _TEMPLATE_ITEMS_CACHE[key] = [
            (str(index), f"{index}: {name}", f"Clone the original {name} material group")
            for index, name in enumerate(original)
            if name not in removed
        ] or [("0", "No material template", "")]
    return _TEMPLATE_ITEMS_CACHE[key]


def _extract_batch_geometry(court: ebo_core.Court, mesh_record: ebo_core.Mesh, obj) -> dict[tuple[str, int], ebo_core.RebuiltBatch]:
    geometry = obj.data
    uv_layer = geometry.uv_layers.active
    color_layer = geometry.color_attributes.get(COLOR_LAYER)
    if color_layer is None and geometry.color_attributes:
        color_layer = geometry.color_attributes.active_color
    geometry.calc_loop_triangles()

    by_batch: dict[int, list[object]] = {batch.batch_index: [] for batch in mesh_record.batches}
    for triangle in geometry.loop_triangles:
        polygon = geometry.polygons[triangle.polygon_index]
        if polygon.material_index >= len(mesh_record.batches):
            raise ebo_core.CourtFormatError(
                f"Object {mesh_record.name!r} uses material slot {polygon.material_index}, "
                "which has no matching EBO batch."
            )
        material_name = _material_name(obj, polygon)
        expected_name = mesh_record.batches[polygon.material_index].material
        if material_name != expected_name:
            raise ebo_core.CourtFormatError(
                f"Object {mesh_record.name!r}, slot {polygon.material_index} uses "
                f"{material_name!r}; the corresponding EBO batch expects {expected_name!r}."
            )
        by_batch[polygon.material_index].append(triangle)

    expected_total = sum(batch.vertex_count for batch in mesh_record.batches)
    ranges: dict[int, tuple[int, int]] = {}
    cursor = 0
    for batch in mesh_record.batches:
        ranges[batch.batch_index] = cursor, cursor + batch.vertex_count
        cursor += batch.vertex_count
    # Topology is independent per EBO batch.  New Blender vertices are normally
    # appended after all imported vertices; do not make that one edited batch
    # force every untouched material group through strip reconstruction.
    batch_original_layout: dict[int, bool] = {}
    batch_preserves_imported_indices: dict[int, bool] = {}
    imported_vertices_still_present = len(geometry.vertices) >= expected_total
    for batch in mesh_record.batches:
        low, high = ranges[batch.batch_index]
        vertices_used = [
            vertex
            for triangle in by_batch[batch.batch_index]
            for vertex in triangle.vertices
        ]
        batch_original_layout[batch.batch_index] = imported_vertices_still_present and all(
            low <= vertex < high
            for vertex in vertices_used
        )
        batch_preserves_imported_indices[batch.batch_index] = imported_vertices_still_present and all(
            low <= vertex < high or vertex >= expected_total
            for vertex in vertices_used
        )

    results: dict[tuple[str, int], ebo_core.RebuiltBatch] = {}
    for batch in mesh_record.batches:
        triangles = by_batch[batch.batch_index]
        original_layout = batch_original_layout[batch.batch_index]
        preserve_imported_indices = batch_preserves_imported_indices[batch.batch_index]
        if not triangles:
            raise ebo_core.CourtFormatError(
                f"Object {mesh_record.name!r}, material {batch.material!r} has no faces. "
                "Keep at least one face in every original material group."
            )

        lookup: dict[tuple, int] = {}
        positions: list[tuple[float, float, float]] = []
        uvs: list[tuple[float, float]] = []
        colors: list[tuple[int, int, int, int]] = []
        selectors: list[int] = []
        selector_layer = geometry.attributes.get(SELECTOR_ATTRIBUTE) if batch.selectors else None
        first_loop: dict[int, int] = {}
        for triangle in triangles:
            for loop_index in triangle.loops:
                first_loop.setdefault(geometry.loops[loop_index].vertex_index, loop_index)

        def add_vertex(vertex_index: int, loop_index: int | None) -> int:
            source_low, source_high = ranges[batch.batch_index]
            is_imported_vertex = preserve_imported_indices and source_low <= vertex_index < source_high
            source_index = vertex_index - source_low if is_imported_vertex else len(positions)
            if loop_index is None:
                uv = (0.0, 0.0)
                rgba = (255, 255, 255, 255)
                if source_index < batch.vertex_count:
                    if batch.uvs is not None:
                        raw_u, raw_v = struct.unpack_from(
                            "<2f", court.data, batch.uvs.data_offset + source_index * 8
                        )
                        uv = (raw_u, raw_v)
                    if batch.colors is not None:
                        blue, green, red, alpha = struct.unpack_from(
                            "<4B", court.data, batch.colors.data_offset + source_index * 4
                        )
                        rgba = red, green, blue, alpha
            else:
                if uv_layer and batch.uvs is not None:
                    item = uv_layer.data[loop_index].uv
                    uv = float(item[0]), 1.0 - float(item[1])
                    if is_imported_vertex and source_index < batch.vertex_count:
                        original_u, original_v = struct.unpack_from(
                            "<2f", court.data, batch.uvs.data_offset + source_index * 8
                        )
                        imported_v = struct.unpack("<f", struct.pack("<f", 1.0 - original_v))[0]
                        if float(item[0]) == original_u and float(item[1]) == imported_v:
                            uv = original_u, original_v
                else:
                    uv = 0.0, 0.0
                if color_layer:
                    color_index = loop_index if color_layer.domain == "CORNER" else vertex_index
                    rgba = _byte_color(_read_color(color_layer.data[color_index]))
                else:
                    rgba = 255, 255, 255, 255

            selector_identity = None
            if batch.selectors:
                if selector_layer is None or selector_layer.domain != "POINT":
                    raise ebo_core.CourtFormatError(
                        f"Material {batch.material!r} requires {SELECTOR_ATTRIBUTE!r} for safe export."
                    )
                selector_identity = int(selector_layer.data[vertex_index].value)
            identity = vertex_index, uv, rgba, selector_identity
            if identity in lookup:
                return lookup[identity]
            local_index = len(positions)
            if local_index > 65535:
                raise ebo_core.CourtFormatError(
                    f"Object {mesh_record.name!r}, material {batch.material!r} exceeds 65,536 vertices."
                )
            world = obj.matrix_world @ geometry.vertices[vertex_index].co
            position = _blender_to_game(world)
            if not all(math.isfinite(component) for component in position + uv):
                raise ebo_core.CourtFormatError("Mesh contains a non-finite coordinate or UV value.")
            red, green, blue, alpha = rgba
            lookup[identity] = local_index
            positions.append(position)
            uvs.append(uv)
            colors.append((red, green, blue, alpha))
            if batch.selectors:
                if selector_layer is None or selector_layer.domain != "POINT":
                    raise ebo_core.CourtFormatError(
                        f"Material {batch.material!r} requires {SELECTOR_ATTRIBUTE!r} for safe export."
                    )
                selector = int(selector_layer.data[vertex_index].value)
                if not 0 <= selector < batch.palette_count:
                    raise ebo_core.CourtFormatError(
                        f"Material {batch.material!r}, vertex {vertex_index} has selector {selector}; "
                        f"valid range is 0..{batch.palette_count - 1}."
                    )
                selectors.append(selector)
            return local_index

        if preserve_imported_indices:
            low, high = ranges[batch.batch_index]
            for vertex_index in range(low, high):
                add_vertex(vertex_index, first_loop.get(vertex_index))

        output_triangles: list[tuple[int, int, int]] = []
        for triangle in triangles:
            values = tuple(
                add_vertex(geometry.loops[loop_index].vertex_index, loop_index)
                for loop_index in triangle.loops
            )
            if len(set(values)) == 3:
                output_triangles.append(values)
        triangle_tuple = tuple(output_triangles)
        if not triangle_tuple:
            raise ebo_core.CourtFormatError(f"Material {batch.material!r} has no nondegenerate triangles.")
        topology_unchanged = len(positions) == batch.vertex_count and ebo_core._same_oriented_triangles(
            triangle_tuple, batch.triangles
        )
        if topology_unchanged:
            strip = struct.unpack_from(
                f"<{batch.primitive_count + 2}H", court.data, batch.indices.data_offset
            )
        else:
            original_strip = struct.unpack_from(
                f"<{batch.primitive_count + 2}H", court.data, batch.indices.data_offset
            )
            if batch.profile == "FRONTEND_COLOR":
                if triangle_tuple == batch.triangles and len(positions) == batch.vertex_count:
                    strip = tuple(original_strip)
                else:
                    strip = ebo_core._frontend_triangles_to_strip(
                        triangle_tuple, len(positions)
                    )
            elif batch.profile != "STATIC_COLOR":
                strip = ebo_core._edited_specialized_strip(
                    tuple(original_strip), batch.triangles, triangle_tuple, len(positions)
                )
            else:
                strip = ebo_core._triangles_to_strip(triangle_tuple)
        results[mesh_record.name, batch.batch_index] = ebo_core.RebuiltBatch(
            tuple(positions), tuple(uvs), tuple(colors), triangle_tuple, tuple(strip), tuple(selectors)
        )
    return results


def export_environment(context, filepath: str, settings) -> tuple[int, list[Path]]:
    collection = _active_collection(context)
    if collection is None:
        raise ebo_core.CourtFormatError("Select an object imported with NBA Live Environment Tools.")
    source = Path(collection[COLLECTION_SOURCE])
    if not source.is_file():
        raise ebo_core.CourtFormatError(f"Original template EBO was not found: {source}")
    court = ebo_core.parse_court(source.read_bytes())
    rms_types = _rms_material_types(court)
    objects = {
        obj.get("nba_live_mesh_name", obj.name): obj
        for obj in collection.objects
        if obj.type == "MESH"
    }
    removals: list[tuple[str, str]] = []
    for mesh_record in court.meshes:
        obj = objects.get(mesh_record.name)
        if obj is None:
            raise ebo_core.CourtFormatError(f"Original EBO object {mesh_record.name!r} is missing.")
        original_names = {batch.material for batch in mesh_record.batches}
        explicitly_removed = set(json.loads(obj.get("nba_live_removed_materials", "[]")))
        unknown_removals = explicitly_removed - original_names
        if unknown_removals:
            name = sorted(unknown_removals)[0]
            raise ebo_core.CourtFormatError(
                f"Removed material {name!r} does not belong to object {mesh_record.name!r}."
            )
        assigned_originals: set[str] = set()
        for polygon in obj.data.polygons:
            if polygon.material_index >= len(obj.material_slots):
                continue
            material = obj.material_slots[polygon.material_index].material
            if material is None:
                continue
            texture_name, template_name, _ = _ebo_material_spec(material)
            original_name = "" if template_name is not None else material.get("nba_live_original_material_name", "")
            if not original_name and template_name is None:
                original_name = texture_name if template_name is None and texture_name in original_names else ""
            if original_name in original_names:
                assigned_originals.add(original_name)
        # The Remove Material operator records the name explicitly. Also infer
        # removal from an original group that no longer owns any faces. This
        # makes removal survive Blender slot changes and older saved projects.
        inferred_removed = original_names - assigned_originals
        requested_removals = explicitly_removed | inferred_removed
        if len(requested_removals) >= len(original_names):
            raise ebo_core.CourtFormatError(
                f"Object {mesh_record.name!r} must retain at least one original material group with faces."
            )
        for name in sorted(requested_removals):
            removals.append((mesh_record.name, name))
    court = ebo_core.remove_material_batches(court, tuple(removals))
    renames: dict[tuple[str, int], str] = {}
    additions: list[ebo_core.NewMaterialBatch] = []
    used_materials: dict[str, tuple[object, str]] = {}
    for mesh_record in court.meshes:
        obj = objects.get(mesh_record.name)
        if obj is None:
            raise ebo_core.CourtFormatError(f"Original EBO object {mesh_record.name!r} is missing.")
        originals = {batch.material: batch for batch in mesh_record.batches}
        assigned: dict[str, object] = {}
        for polygon in obj.data.polygons:
            material = obj.material_slots[polygon.material_index].material
            name, encoded_template, archive_kind = _ebo_material_spec(material)
            previous = used_materials.get(name)
            if previous is not None and previous[0] != material:
                if previous[1] != archive_kind:
                    raise fsh_archive.FshError(
                        f"Texture {name!r} is assigned to both the main and VRAM archives. "
                        "Use one archive choice for each texture name."
                    )
            if not material.get("nba_live_textureless"):
                used_materials[name] = material, archive_kind
            assigned[name] = material
            original_name = "" if encoded_template is not None else material.get("nba_live_original_material_name", "")
            if not original_name and encoded_template is None and name in originals:
                original_name = name
            if original_name in originals and original_name != name:
                renames[mesh_record.name, originals[original_name].batch_index] = name

        resulting_originals = {
            renames.get((mesh_record.name, batch.batch_index), batch.material)
            for batch in mesh_record.batches
        }
        for name, material in assigned.items():
            if name in resulting_originals:
                continue
            _, template_name, _ = _ebo_material_spec(material)
            if template_name == "__legacy_template__":
                template_choices = json.loads(material.get("nba_live_template_batches", "{}"))
                template_index = int(
                    template_choices.get(
                        mesh_record.name,
                        material.get("nba_live_template_batch_index", 0),
                    )
                )
                imported_names = json.loads(obj.get("nba_live_batch_materials", "[]"))
                template_name = imported_names[template_index] if 0 <= template_index < len(imported_names) else None
            if template_name is None:
                raise ebo_core.CourtFormatError(
                    f"New material {name!r} needs a template and archive in its Blender name: "
                    f"EBO.{name}.<template>.<main|vram>."
                )
            template_batch = _resolve_material_template(mesh_record, template_name, rms_types)
            if template_batch is None:
                available_types = sorted(
                    {
                        rms_types[mesh_record.name, batch.material]
                        for batch in mesh_record.batches
                        if (mesh_record.name, batch.material) in rms_types
                    }
                )
                choices = ", ".join(available_types) or "no named RMS types"
                raise ebo_core.CourtFormatError(
                    f"New material {name!r} has no template material or RMS type "
                    f"{template_name!r} on object {mesh_record.name!r}; available RMS types: {choices}."
                )
            additions.append(ebo_core.NewMaterialBatch(mesh_record.name, name, template_batch.batch_index))

    court = ebo_core.rename_material_batches(court, renames)
    court = ebo_core.add_material_batches(court, tuple(additions))
    edited: dict[tuple[str, int], ebo_core.RebuiltBatch] = {}
    for mesh_record in court.meshes:
        obj = objects.get(mesh_record.name)
        if obj is None:
            raise ebo_core.CourtFormatError(f"Original EBO object {mesh_record.name!r} is missing.")
        edited.update(_extract_batch_geometry(court, mesh_record, obj))

    updated, changed_batches = ebo_core.rebuild_from_batches(court, edited)
    changed_batches += len(additions) + len(renames) + len(removals)
    destination = Path(filepath).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    rebuilt_archives: list[Path] = []
    if settings.repack_fsh:
        gx = _gx_path(context)
        root = Path(collection["nba_live_texture_root"])
        archives = tuple(
            fsh_archive.read_fsh(value)
            for value in json.loads(collection.get("nba_live_archives", "[]"))
        )
        by_kind = {fsh_archive.archive_kind(archive.path): archive for archive in archives}
        required: dict[str, set[str]] = {archive.path.name: set() for archive in archives}
        for name, (material, kind) in used_materials.items():
            archive = by_kind.get(kind)
            if archive is None:
                label = "_vram.fsh" if kind == "VRAM" else ".fsh"
                raise fsh_archive.FshError(
                    f"Texture {name!r} targets {label}, but that source FSH archive was not found."
                )
            canonical_name = fsh_archive.resolve_entry_name(archive, name)
            required[archive.path.name].add(canonical_name)
            image = _material_image_path(material)
            destination_image = root / archive.path.stem / f"{fsh_archive.working_texture_name(canonical_name)}.png"
            if image is not None:
                fsh_archive.stage_texture(archive, root, name, image)
            elif not destination_image.is_file():
                raise fsh_archive.FshError(
                    f"Texture {name!r} requires a PNG image for {archive.path.name}. "
                    "Set its image in the NBA Live material panel."
                )
        for archive in archives:
            rebuilt_archives.append(
                fsh_archive.repack_archive(
                    archive,
                    root / archive.path.stem,
                    gx,
                    destination.parent,
                    required_names=frozenset(required[archive.path.name]),
                )
            )
    destination.write_bytes(updated)
    return changed_batches, rebuilt_archives


class NBAEnvironmentPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    gx_path: StringProperty(
        name="GX Executable",
        description="Persistent path to gx.exe, used to extract and rebuild FSH archives",
        subtype="FILE_PATH",
    )
    base_2005_path: StringProperty(
        name="NBA Live 2005 Head Base EBO",
        description="Optional override for the bundled base_lodB_05.ebo",
        subtype="FILE_PATH",
    )
    base_2006_path: StringProperty(
        name="NBA Live 2006 Head Base EBO",
        description="Optional override for the bundled base_lodB.ebo",
        subtype="FILE_PATH",
    )

    def draw(self, context):
        layout = self.layout
        layout.label(text="FSH texture extraction and repacking")
        layout.prop(self, "gx_path")
        layout.separator()
        layout.label(text="Player-head base models (bundled defaults)")
        layout.prop(self, "base_2005_path")
        layout.prop(self, "base_2006_path")


class NBAEnvironmentMaterialSettings(bpy.types.PropertyGroup):
    texture_name: StringProperty(
        name="Texture Name",
        description="ASCII material name stored in the EBO and as the FSH image name, without .png",
    )
    archive: EnumProperty(
        name="FSH Archive",
        description="FSH archive that should contain this material's texture",
        items=ARCHIVE_ITEMS,
        default="MAIN",
    )
    texture_path: StringProperty(
        name="PNG Image",
        description="PNG image copied into the selected FSH archive when textures are repacked",
        subtype="FILE_PATH",
    )


class NBAEnvironmentSettings(bpy.types.PropertyGroup):
    archive_directory: StringProperty(
        name="FSH Directory",
        description="Optional directory containing the main and _vram FSH archives",
        subtype="DIR_PATH",
    )
    texture_directory: StringProperty(
        name="Extracted Textures",
        description="Directory for extracted per-archive PNG folders",
        subtype="DIR_PATH",
    )
    additional_texture_directory: StringProperty(
        name="Extra Texture Folder",
        description="Optional existing PNG folder searched when assigning materials",
        subtype="DIR_PATH",
    )
    extract_fsh: BoolProperty(
        name="Extract FSH on Import",
        description="Use GX to unpack the main and VRAM FSH archives automatically",
        default=True,
    )
    repack_fsh: BoolProperty(
        name="Repack FSH on Export",
        description="Rebuild the original main and VRAM texture archives with GX",
        default=False,
    )
    new_material_name: StringProperty(
        name="New Texture Name",
        description="New ASCII EBO material and FSH texture name, without .png",
    )
    new_material_texture: StringProperty(
        name="PNG Image",
        description="PNG image for the new material and FSH texture",
        subtype="FILE_PATH",
    )
    new_material_archive: EnumProperty(
        name="FSH Archive",
        description="Choose whether the new texture belongs in the main or VRAM archive",
        items=ARCHIVE_ITEMS,
        default="MAIN",
    )
    new_material_template: EnumProperty(
        name="Template Material",
        description="Existing material group whose compatible EBO render metadata will be cloned",
        items=_template_items,
    )


class NBA_OT_add_environment_material(bpy.types.Operator):
    bl_idname = "nba_live.add_environment_material"
    bl_label = "Add NBA Live Material"
    bl_description = "Create a new EBO material using an existing group as its render-metadata template"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and bool(_active_collection(context))

    def execute(self, context):
        settings = context.scene.nba_environment_settings
        obj = context.active_object
        collection = _active_collection(context)
        try:
            name = ebo_core.validate_material_name(settings.new_material_name)
            image = _as_path(settings.new_material_texture)
            if image is None or not image.is_file() or image.suffix.lower() != ".png":
                raise fsh_archive.FshError("Choose an existing PNG image for the new material.")
            for slot in obj.material_slots:
                if slot.material is None:
                    continue
                properties = slot.material.nba_live_environment
                current = properties.texture_name or slot.material.get("nba_live_material_name", slot.material.name)
                if current == name:
                    raise ebo_core.CourtFormatError(f"Object {obj.name!r} already uses material {name!r}.")
            archive_paths = json.loads(collection.get("nba_live_archives", "[]"))
            owner = next(
                (Path(path).name for path in archive_paths if fsh_archive.archive_kind(path) == settings.new_material_archive),
                None,
            )
            if archive_paths and owner is None:
                label = "_vram.fsh" if settings.new_material_archive == "VRAM" else ".fsh"
                raise fsh_archive.FshError(f"The selected {label} archive is not available for this asset.")
            material = _material(
                collection["nba_live_asset_name"],
                name,
                (owner,) if owner else (),
                image,
                transparent=bool(collection.get("nba_live_transparent")),
            )
            material["nba_live_new_material"] = True
            material["nba_live_original_material_name"] = ""
            material["nba_live_template_batch_index"] = int(settings.new_material_template)
            template_choices = json.loads(material.get("nba_live_template_batches", "{}"))
            template_choices[obj.get("nba_live_mesh_name", obj.name)] = int(settings.new_material_template)
            material["nba_live_template_batches"] = json.dumps(template_choices)
            material.nba_live_environment.archive = settings.new_material_archive
            material.nba_live_environment.texture_path = str(image)
            obj.data.materials.append(material)
            obj.active_material_index = len(obj.data.materials) - 1
            if obj.mode == "EDIT":
                bpy.ops.object.material_slot_assign()
            settings.new_material_name = ""
        except (ebo_core.CourtFormatError, fsh_archive.FshError, OSError, ValueError, RuntimeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Added {name}; assign faces to its slot, then export the EBO")
        return {"FINISHED"}


class NBA_OT_remove_environment_material(bpy.types.Operator):
    bl_idname = "nba_live.remove_environment_material"
    bl_label = "Remove EBO Material"
    bl_description = "Delete this material group and all its assigned faces; keep its FSH texture"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return obj is not None and obj.type == "MESH" and obj.active_material is not None and bool(_active_collection(context))

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object
        index = obj.active_material_index
        material = obj.active_material
        original_name = material.get("nba_live_original_material_name", "")
        original_names = json.loads(obj.get("nba_live_batch_materials", "[]"))
        removed = json.loads(obj.get("nba_live_removed_materials", "[]"))
        is_original = not material.get("nba_live_new_material") and original_name in original_names
        remaining = [name for name in original_names if name not in removed and name != original_name]
        if is_original and not remaining:
            self.report({"ERROR"}, "Each EBO object must retain at least one original material group")
            return {"CANCELLED"}

        face_count = sum(polygon.material_index == index for polygon in obj.data.polygons)
        starting_mode = obj.mode
        try:
            if starting_mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")
            if face_count:
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="DESELECT")
                bpy.ops.object.material_slot_select()
                bpy.ops.mesh.delete(type="FACE")
                bpy.ops.object.mode_set(mode="OBJECT")
            obj.data.materials.pop(index=index, update_data=True)

            if is_original:
                removed.append(original_name)
                obj["nba_live_removed_materials"] = json.dumps(removed)
                replacement_index = original_names.index(remaining[0])
                mesh_name = obj.get("nba_live_mesh_name", obj.name)
                removed_index = original_names.index(original_name)
                for slot in obj.material_slots:
                    other = slot.material
                    if other is None or not other.get("nba_live_new_material"):
                        continue
                    choices = json.loads(other.get("nba_live_template_batches", "{}"))
                    selected = int(choices.get(mesh_name, other.get("nba_live_template_batch_index", 0)))
                    if selected == removed_index:
                        choices[mesh_name] = replacement_index
                        other["nba_live_template_batches"] = json.dumps(choices)
                        other["nba_live_template_batch_index"] = replacement_index
            if starting_mode == "EDIT":
                bpy.ops.object.mode_set(mode="EDIT")
        except (ebo_core.CourtFormatError, RuntimeError, ValueError, TypeError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        properties = getattr(material, "nba_live_environment", None)
        name = properties.texture_name if properties and properties.texture_name else original_name or material.name
        self.report({"INFO"}, f"Removed {name} and {face_count} assigned faces; its FSH texture is preserved")
        return {"FINISHED"}


class NBA_OT_import_environment(bpy.types.Operator, ImportHelper):
    bl_idname = "nba_live.import_environment"
    bl_label = "Import NBA Live EBO"
    bl_description = "Import a court, stadium, or transparent stadium EBO"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".ebo"
    filter_glob: StringProperty(default="*.ebo", options={"HIDDEN"})

    def execute(self, context):
        try:
            collection, count, textures = import_environment(
                context, self.filepath, context.scene.nba_environment_settings
            )
        except (ebo_core.CourtFormatError, fsh_archive.FshError, OSError, struct.error) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Imported {count} objects into {collection.name}; matched {textures} textures")
        return {"FINISHED"}


class NBA_OT_export_environment(bpy.types.Operator, ExportHelper):
    bl_idname = "nba_live.export_environment"
    bl_label = "Export NBA Live EBO"
    bl_description = "Rebuild an EBO from the selected imported court or stadium collection"
    filename_ext = ".ebo"
    filter_glob: StringProperty(default="*.ebo", options={"HIDDEN"})

    def invoke(self, context, event):
        collection = _active_collection(context)
        if collection:
            self.filepath = str(Path(collection[COLLECTION_SOURCE]).with_name(collection.name + "_edited.ebo"))
        return super().invoke(context, event)

    def execute(self, context):
        try:
            batches, archives = export_environment(
                context, self.filepath, context.scene.nba_environment_settings
            )
        except (ebo_core.CourtFormatError, fsh_archive.FshError, OSError, struct.error) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported EBO; rebuilt {batches} material groups and {len(archives)} FSH archives")
        return {"FINISHED"}


class NBA_OT_export_fbx(bpy.types.Operator, ExportHelper):
    bl_idname = "nba_live.export_fbx"
    bl_label = "Export NBA Live FBX"
    bl_description = "Export the active imported asset with Blender's FBX exporter"
    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})

    def execute(self, context):
        collection = _active_collection(context)
        if collection is None:
            self.report({"ERROR"}, "Select an imported NBA Live object first.")
            return {"CANCELLED"}
        previous = list(context.selected_objects)
        for obj in previous:
            obj.select_set(False)
        for obj in collection.objects:
            obj.select_set(True)
        try:
            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                use_selection=True,
                path_mode="COPY",
                embed_textures=True,
                colors_type="SRGB",
            )
        except (RuntimeError, TypeError) as exc:
            self.report({"ERROR"}, f"Blender FBX export failed: {exc}")
            return {"CANCELLED"}
        finally:
            for obj in collection.objects:
                obj.select_set(False)
            for obj in previous:
                obj.select_set(True)
        return {"FINISHED"}


class NBA_OT_import_fbx(bpy.types.Operator, ImportHelper):
    bl_idname = "nba_live.import_fbx"
    bl_label = "Import NBA Live FBX"
    bl_description = "Import an FBX model with Blender's FBX importer"
    filename_ext = ".fbx"
    filter_glob: StringProperty(default="*.fbx", options={"HIDDEN"})

    def execute(self, context):
        try:
            bpy.ops.import_scene.fbx(filepath=self.filepath, colors_type="SRGB")
        except TypeError:
            try:
                bpy.ops.import_scene.fbx(filepath=self.filepath)
            except RuntimeError as exc:
                self.report({"ERROR"}, f"Blender FBX import failed: {exc}")
                return {"CANCELLED"}
        except RuntimeError as exc:
            self.report({"ERROR"}, f"Blender FBX import failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, "Imported FBX; assign its geometry to the original EBO objects/materials")
        return {"FINISHED"}


class NBA_OT_visualize_selectors(bpy.types.Operator):
    bl_idname = "nba_live.visualize_selectors"
    bl_label = "Visualize Transform Selectors"
    bl_description = "Color the active mesh by its EAGL transform-selector value"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        return (
            obj is not None and obj.type == "MESH"
            and obj.data.attributes.get(SELECTOR_ATTRIBUTE) is not None
        )

    def execute(self, context):
        obj = context.active_object
        mesh = obj.data
        selector = mesh.attributes.get(SELECTOR_ATTRIBUTE)
        if selector is None or selector.domain != "POINT":
            self.report({"ERROR"}, "Active mesh has no point-domain EAGL selector attribute")
            return {"CANCELLED"}
        existing = mesh.color_attributes.get(SELECTOR_COLOR_ATTRIBUTE)
        if existing is not None:
            mesh.color_attributes.remove(existing)
        colors = mesh.color_attributes.new(
            name=SELECTOR_COLOR_ATTRIBUTE, type="BYTE_COLOR", domain="POINT"
        )
        # High-contrast deterministic diagnostic palette; values beyond the
        # common 0..3 range still receive stable distinct hues.
        palette = (
            (0.90, 0.12, 0.12, 1.0),
            (0.10, 0.55, 0.95, 1.0),
            (0.15, 0.80, 0.25, 1.0),
            (0.95, 0.65, 0.10, 1.0),
            (0.65, 0.20, 0.90, 1.0),
            (0.10, 0.80, 0.80, 1.0),
        )
        for index, item in enumerate(selector.data):
            value = int(item.value)
            rgba = palette[value % len(palette)] if value >= 0 else (0.15, 0.15, 0.15, 1.0)
            _write_color(colors.data[index], rgba)
        mesh.color_attributes.active_color_name = SELECTOR_COLOR_ATTRIBUTE
        for area in context.screen.areas if context.screen else ():
            if area.type == "VIEW_3D":
                for space in area.spaces:
                    if space.type == "VIEW_3D":
                        space.shading.color_type = "VERTEX"
        mesh.update()
        values = [int(item.value) for item in selector.data if int(item.value) >= 0]
        if values:
            self.report({"INFO"}, f"Showing selector groups {min(values)}..{max(values)}")
        return {"FINISHED"}


class NBA_PT_environment_panel(bpy.types.Panel):
    bl_label = "NBA Live Environments"
    bl_idname = "NBA_PT_environment_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "NBA Live"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.nba_environment_settings
        box = layout.box()
        box.label(text="FSH Archives", icon="IMAGE_DATA")
        box.prop(settings, "archive_directory")
        box.prop(settings, "texture_directory")
        box.prop(settings, "additional_texture_directory")
        box.prop(settings, "extract_fsh")
        box.prop(settings, "repack_fsh")

        box = layout.box()
        box.label(text="Court / Stadium EBO", icon="MESH_DATA")
        box.operator("nba_live.import_environment", icon="IMPORT")
        box.operator("nba_live.export_environment", icon="EXPORT")
        box.operator("nba_live.import_fbx", icon="IMPORT")
        box.operator("nba_live.export_fbx", icon="EXPORT")

        collection = _active_collection(context)
        if collection:
            materials = layout.box()
            materials.label(text="Name-driven EBO Materials", icon="MATERIAL")
            materials.label(text="Imported: EBO.<texture> [RMS type]")
            materials.label(text="New: EBO.<texture>.<template or RMS type>.<main|vram>")
            materials.label(text="Use Blender's material slots to add or remove groups", icon="INFO")

            info = layout.box()
            info.label(text=f"Active: {collection.name}", icon="OUTLINER_COLLECTION")
            info.label(text=f"Template: {Path(collection[COLLECTION_SOURCE]).name}")

            obj = context.active_object
            if obj is not None and obj.type == "MESH" and obj.data.attributes.get(SELECTOR_ATTRIBUTE):
                debug = layout.box()
                debug.label(text="Backboard / Skin Diagnostics", icon="SHADING_RENDERED")
                debug.operator("nba_live.visualize_selectors", icon="COLOR")


def _import_menu(self, context):
    self.layout.operator(NBA_OT_import_environment.bl_idname, text="NBA Live Court / Stadium (.ebo)")


def _export_menu(self, context):
    self.layout.operator(NBA_OT_export_environment.bl_idname, text="NBA Live Court / Stadium (.ebo)")


CLASSES = (
    NBAEnvironmentPreferences,
    NBAEnvironmentMaterialSettings,
    NBAEnvironmentSettings,
    NBA_OT_import_environment,
    NBA_OT_export_environment,
    NBA_OT_import_fbx,
    NBA_OT_export_fbx,
    NBA_OT_visualize_selectors,
    NBA_PT_environment_panel,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Material.nba_live_environment = PointerProperty(type=NBAEnvironmentMaterialSettings)
    bpy.types.Scene.nba_environment_settings = PointerProperty(type=NBAEnvironmentSettings)
    bpy.types.TOPBAR_MT_file_import.append(_import_menu)
    bpy.types.TOPBAR_MT_file_export.append(_export_menu)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_export_menu)
    bpy.types.TOPBAR_MT_file_import.remove(_import_menu)
    del bpy.types.Scene.nba_environment_settings
    del bpy.types.Material.nba_live_environment
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
