"""Starbase and stock item entity dataclasses."""
from dataclasses import dataclass


@dataclass
class Starbase:
    id: int
    defense: int
    builtdefense: int
    damage: int
    enginetechlevel: int
    hulltechlevel: int
    beamtechlevel: int
    torptechlevel: int
    hulltechup: int
    enginetechup: int
    beamtechup: int
    torptechup: int
    fighters: int
    builtfighters: int
    shipmission: int
    mission: int
    mission1target: int
    planetid: int
    raceid: int
    targetshipid: int
    buildbeamid: int
    buildengineid: int
    buildtorpedoid: int
    buildhullid: int
    buildbeamcount: int
    buildtorpcount: int
    isbuilding: bool
    starbasetype: int
    infoturn: int
    readystatus: int


@dataclass
class StockItem:
    id: int
    starbaseid: int
    stocktype: int
    stockid: int
    amount: int
    builtamount: int
