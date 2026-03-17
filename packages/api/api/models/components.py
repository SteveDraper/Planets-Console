"""Component entity dataclasses (hulls, beams, engines, torpedoes)."""
from dataclasses import dataclass


@dataclass
class Hull:
    id: int
    name: str
    tritanium: int
    duranium: int
    molybdenum: int
    fueltank: int
    crew: int
    engines: int
    mass: int
    techlevel: int
    cargo: int
    fighterbays: int
    launchers: int
    beams: int
    cancloak: bool
    cost: int
    special: str
    description: str
    advantage: int
    isbase: bool
    dur: int
    tri: int
    mol: int
    mc: int
    parentid: int
    academy: bool


@dataclass
class Beam:
    id: int
    name: str
    cost: int
    tritanium: int
    duranium: int
    molybdenum: int
    mass: int
    techlevel: int
    crewkill: int
    damage: int


@dataclass
class Engine:
    id: int
    name: str
    cost: int
    tritanium: int
    duranium: int
    molybdenum: int
    techlevel: int
    warp1: int
    warp2: int
    warp3: int
    warp4: int
    warp5: int
    warp6: int
    warp7: int
    warp8: int
    warp9: int


@dataclass
class Torpedo:
    id: int
    fullid: int
    name: str
    torpedocost: int
    launchercost: int
    tritanium: int
    duranium: int
    molybdenum: int
    mass: int
    techlevel: int
    crewkill: int
    damage: int
    combatrange: int
