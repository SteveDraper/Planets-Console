"""Communication entity dataclasses (messages, notes, VCRs)."""
from dataclasses import dataclass

from api.models.enums import MessageType


@dataclass
class Message:
    id: int
    ownerid: int
    messagetype: MessageType
    headline: str
    body: str
    target: int
    turn: int
    x: int
    y: int


@dataclass
class Note:
    id: int
    ownerid: int
    body: str
    targetid: int
    targettype: int
    color: str


@dataclass
class VcrSide:
    id: int
    vcrid: int
    objectid: int
    name: str
    side: int
    beamcount: int
    launchercount: int
    baycount: int
    hullid: int
    beamid: int
    torpedoid: int
    shield: int
    damage: int
    crew: int
    mass: int
    raceid: int
    beamkillbonus: int
    beamchargerate: int
    torpchargerate: int
    torpmisspercent: int
    crewdefensepercent: int
    torpedos: int
    fighters: int
    temperature: int
    hasstarbase: bool


@dataclass
class Vcr:
    id: int
    seed: int
    x: int
    y: int
    battletype: int
    leftownerid: int
    rightownerid: int
    turn: int
    left: VcrSide
    right: VcrSide
