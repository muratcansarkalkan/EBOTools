"""NBA Live 2005/2006 player heads, environments, and static models for Blender."""

bl_info = {
    "name": "NBA Live EBO Tools",
    "author": "EBO Tools 2026",
    "version": (0, 6, 4),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > NBA Live",
    "description": "Edit NBA Live player heads, environments, static models, EBO materials, and FSH textures",
    "category": "Import-Export",
}

from . import blender_addon
from . import face_tools
from . import body_morph_tools
from . import multi_morph_core
from . import multi_morph_tools


def register():
    blender_addon.register()
    face_tools.register()
    body_morph_tools.register()
    multi_morph_tools.register()


def unregister():
    multi_morph_tools.unregister()
    body_morph_tools.unregister()
    face_tools.unregister()
    blender_addon.unregister()
