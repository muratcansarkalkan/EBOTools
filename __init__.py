"""NBA Live 2005/2006 EBO Tools for Blender."""

bl_info = {
    "name": "NBA Live Environment Tools",
    "author": "EBO Tools 2026",
    "version": (1, 4, 8),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > NBA Live",
    "description": (
        "NBA Live stadium/court, backboard, net and EBO environment tools"
    ),
    "category": "Import-Export",
}

from . import blender_addon
from . import synthetic_static_blender
from . import backboard_blender
from . import net_blender
from . import player_morph_blender


def register():
    blender_addon.register()
    synthetic_static_blender.register()
    backboard_blender.register()
    net_blender.register()
    player_morph_blender.register()


def unregister():
    player_morph_blender.unregister()
    net_blender.unregister()
    backboard_blender.unregister()
    synthetic_static_blender.unregister()
    blender_addon.unregister()
