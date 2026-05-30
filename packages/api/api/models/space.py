"""Spatial entity dataclasses (ion storms, minefields, nebulas, stars)."""

from dataclasses import dataclass


@dataclass
class IonStorm:
    id: int
    x: int
    y: int
    radius: int
    voltage: int
    warp: int
    heading: int
    isgrowing: bool
    parentid: int


@dataclass
class Minefield:
    id: int
    ownerid: int
    isweb: bool
    ishidden: bool
    units: int
    infoturn: int
    friendlycode: str
    x: int
    y: int
    radius: int


@dataclass
class Nebula:
    id: int
    x: int
    y: int
    name: str = ""
    radius: int = 0
    intensity: int = 0
    gas: int = 0


@dataclass
class Star:
    id: int
    name: str
    x: int
    y: int
    temp: int
    radius: int
    mass: int
    planets: int


@dataclass
class Blackhole:
    id: int
    x: int
    y: int
    name: str = ""
    coreradius: int = 0
    bandradius: int = 0


@dataclass
class Artifact:
    id: int


@dataclass
class Wormhole:
    id: int
    x: int
    y: int
    name: str = ""
    targetx: int = 0
    targety: int = 0
    stability: int = 0
    turn: int = 0


@dataclass
class Cutscene:
    id: int
