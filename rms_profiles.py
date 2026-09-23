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
    RmsProfile("JumboHomeHundreds", "gJumboHomeHundreds_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeTens",     "gJumboHomeTens_RMRuntime",     "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeOnes",     "gJumboHomeOnes_RMRuntime",     "experimental", "STATIC_0X24"),

    RmsProfile("JumboAwayHundreds", "gJumboAwayHundreds_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayTens",     "gJumboAwayTens_RMRuntime",     "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayOnes",     "gJumboAwayOnes_RMRuntime",     "experimental", "STATIC_0X24"),

    RmsProfile("JumboGameMinTens",  "gJumboGameMinTens_RMRuntime",  "experimental", "STATIC_0X24"),
    RmsProfile("JumboGameMinOnes",  "gJumboGameMinOnes_RMRuntime",  "experimental", "STATIC_0X24"),
    RmsProfile("JumboGameSecTens",  "gJumboGameSecTens_RMRuntime",  "experimental", "STATIC_0X24"),
    RmsProfile("JumboGameSecOnes",  "gJumboGameSecOnes_RMRuntime",  "experimental", "STATIC_0X24"),

    RmsProfile("JumboShotTens",     "gJumboShotTens_RMRuntime",     "experimental", "STATIC_0X24"),
    RmsProfile("JumboShotOnes",     "gJumboShotOnes_RMRuntime",     "experimental", "STATIC_0X24"),

    RmsProfile("JumboPeriod",       "gJumboPeriod_RMRuntime",       "experimental", "STATIC_0X24"),

    RmsProfile("JumboHomeTimeouts",      "gJumboHomeTimeouts_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayTimeouts",      "gJumboAwayTimeouts_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeTeamFoulsTens", "gJumboHomeTeamFoulsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeTeamFoulsOnes", "gJumboHomeTeamFoulsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayTeamFoulsTens", "gJumboAwayTeamFoulsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayTeamFoulsOnes", "gJumboAwayTeamFoulsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt1NumberTens", "gJumboHomeCourt1NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt1NumberOnes", "gJumboHomeCourt1NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt1PointsTens", "gJumboHomeCourt1PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt1PointsOnes", "gJumboHomeCourt1PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt1Fouls",      "gJumboHomeCourt1Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt2NumberTens", "gJumboHomeCourt2NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt2NumberOnes", "gJumboHomeCourt2NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt2PointsTens", "gJumboHomeCourt2PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt2PointsOnes", "gJumboHomeCourt2PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt2Fouls",      "gJumboHomeCourt2Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt3NumberTens", "gJumboHomeCourt3NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt3NumberOnes", "gJumboHomeCourt3NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt3PointsTens", "gJumboHomeCourt3PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt3PointsOnes", "gJumboHomeCourt3PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt3Fouls",      "gJumboHomeCourt3Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt4NumberTens", "gJumboHomeCourt4NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt4NumberOnes", "gJumboHomeCourt4NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt4PointsTens", "gJumboHomeCourt4PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt4PointsOnes", "gJumboHomeCourt4PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt4Fouls",      "gJumboHomeCourt4Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt5NumberTens", "gJumboHomeCourt5NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt5NumberOnes", "gJumboHomeCourt5NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt5PointsTens", "gJumboHomeCourt5PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt5PointsOnes", "gJumboHomeCourt5PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboHomeCourt5Fouls",      "gJumboHomeCourt5Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt1NumberTens", "gJumboAwayCourt1NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt1NumberOnes", "gJumboAwayCourt1NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt1PointsTens", "gJumboAwayCourt1PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt1PointsOnes", "gJumboAwayCourt1PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt1Fouls",      "gJumboAwayCourt1Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt2NumberTens", "gJumboAwayCourt2NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt2NumberOnes", "gJumboAwayCourt2NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt2PointsTens", "gJumboAwayCourt2PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt2PointsOnes", "gJumboAwayCourt2PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt2Fouls",      "gJumboAwayCourt2Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt3NumberTens", "gJumboAwayCourt3NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt3NumberOnes", "gJumboAwayCourt3NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt3PointsTens", "gJumboAwayCourt3PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt3PointsOnes", "gJumboAwayCourt3PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt3Fouls",      "gJumboAwayCourt3Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt4NumberTens", "gJumboAwayCourt4NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt4NumberOnes", "gJumboAwayCourt4NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt4PointsTens", "gJumboAwayCourt4PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt4PointsOnes", "gJumboAwayCourt4PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt4Fouls",      "gJumboAwayCourt4Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt5NumberTens", "gJumboAwayCourt5NumberTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt5NumberOnes", "gJumboAwayCourt5NumberOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt5PointsTens", "gJumboAwayCourt5PointsTens_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt5PointsOnes", "gJumboAwayCourt5PointsOnes_RMRuntime", "experimental", "STATIC_0X24"),
    RmsProfile("JumboAwayCourt5Fouls",      "gJumboAwayCourt5Fouls_RMRuntime",      "experimental", "STATIC_0X24"),
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
