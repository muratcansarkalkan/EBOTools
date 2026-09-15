"""Central render-method profile registry for NBA Live EBO Tools.

The old hardcoded whitelist lived in ebo_synthetic_static.py. This module keeps
the user-facing RMS name, runtime import, support status and compiler profile
in one place.

"verified" means game-tested with the generic static 0x24 material-variable
layout used by stadium/court exports.

"experimental" means the runtime is allowed for testing with that same layout,
but its exact per-material variable contract has not yet been reverse-engineered
and game-validated by this tool.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RmsProfile:
    name: str
    runtime: str
    status: str = "verified"
    compiler_profile: str = "STATIC_0X24"


_PROFILES = (
    RmsProfile("TextureStadium", "gTextureStadium_RMRuntime"),
    RmsProfile("TextureStadiumNoZWrite", "gTextureStadiumNoZWrite_RMRuntime"),
    RmsProfile("TextureGlow", "gTextureGlow_RMRuntime"),
    RmsProfile("ScrollTextureDim", "gScrollTextureDim_RMRuntime"),
    RmsProfile("TextureStadiumRef", "gTextureStadiumRef_RMRuntime"),
    RmsProfile("ScrollTextureDimRef", "gScrollTextureDimRef_RMRuntime"),
    RmsProfile("NBACourt", "gNBACourt_RMRuntime"),

    # User-requested experimental stadium RMS.
    # Exact runtime name confirmed by the user. We deliberately allow this
    # through the existing static material compiler for game experimentation,
    # while marking the variable layout as unverified.
    RmsProfile(
        "TextureScaleOffsetUV",
        "gTextureScaleOffsetUV_RMRuntime",
        status="experimental",
        compiler_profile="STATIC_0X24",
    ),
    RmsProfile(
        "JumboTest",
        "gJumboTest_RMRuntime",
        status="experimental",
        compiler_profile="STATIC_0X24",
    ),
)

BY_NAME = {p.name: p for p in _PROFILES}
BY_RUNTIME = {p.runtime: p for p in _PROFILES}


def names() -> tuple[str, ...]:
    return tuple(sorted(BY_NAME))


def verified_names() -> tuple[str, ...]:
    return tuple(sorted(p.name for p in _PROFILES if p.status == "verified"))


def experimental_names() -> tuple[str, ...]:
    return tuple(sorted(p.name for p in _PROFILES if p.status == "experimental"))


def resolve(value: str) -> RmsProfile:
    """Accept either short RMS name or exact g..._RMRuntime import name."""
    value = str(value).strip()
    if value in BY_NAME:
        return BY_NAME[value]
    if value in BY_RUNTIME:
        return BY_RUNTIME[value]
    raise KeyError(value)


def runtime_name(value: str) -> str:
    return resolve(value).runtime


def canonical_name(value: str) -> str:
    return resolve(value).name


def status(value: str) -> str:
    return resolve(value).status
