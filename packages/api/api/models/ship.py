"""Ship entity dataclasses."""
from dataclasses import dataclass, field


@dataclass
class Waypoint:
    x: int
    y: int


@dataclass
class ShipHistory:
    x: int
    y: int


@dataclass
class Ship:
    id: int
    friendlycode: str
    name: str
    warp: int
    x: int
    y: int
    beams: int
    bays: int
    torps: int
    mission: int
    mission1target: int
    mission2target: int
    enemy: int
    damage: int
    crew: int
    clans: int
    neutronium: int
    tritanium: int
    duranium: int
    molybdenum: int
    supplies: int
    ammo: int
    megacredits: int
    transferclans: int
    transferneutronium: int
    transferduranium: int
    transfertritanium: int
    transfermolybdenum: int
    transfersupplies: int
    transferammo: int
    transfermegacredits: int
    transfertargetid: int
    transfertargettype: int
    targetx: int
    targety: int
    mass: int
    heading: int
    turn: int
    turnkilled: int
    beamid: int
    engineid: int
    hullid: int
    ownerid: int
    torpedoid: int
    experience: int
    infoturn: int
    podhullid: int
    podcargo: int
    goal: int
    goaltarget: int
    goaltarget2: int
    waypoints: list[Waypoint] = field(default_factory=list)
    history: list[ShipHistory] = field(default_factory=list)
    iscloaked: bool = False
    readystatus: int = 0
