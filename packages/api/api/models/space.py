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


@dataclass
class Artifact:
    id: int


@dataclass
class Wormhole:
    id: int
    x: int
    y: int


@dataclass
class Cutscene:
    id: int
