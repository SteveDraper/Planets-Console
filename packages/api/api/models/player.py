"""Player-related entity dataclasses."""

from dataclasses import dataclass


@dataclass
class Player:
    id: int
    status: int
    statusturn: int
    accountid: int
    username: str
    email: str
    raceid: int
    teamid: int
    prioritypoints: int
    joinrank: int
    finishrank: int
    turnjoined: int
    turnready: bool
    turnreadydate: str
    turnstatus: int
    turnsmissed: int
    turnsmissedtotal: int
    turnsholiday: int
    turnsearly: int
    turn: int
    timcontinuum: int
    savekey: str
    tutorialid: int
    tutorialtaskid: int
    megacredits: int
    duranium: int
    tritanium: int
    molybdenum: int
    leagueteamid: int
    activehulls: str
    activeadvantages: str
    activeengines: str
    activebeams: str
    activetorps: str


@dataclass
class Score:
    id: int
    dateadded: str
    ownerid: int
    accountid: int
    capitalships: int
    freighters: int
    planets: int
    starbases: int
    militaryscore: int
    inventoryscore: int
    prioritypoints: int
    turn: int
    percent: float
    victoryscore: int
    victorybonuses: str
    technologicalaccumulator: int
    widestreach: int
    greatestwarrior: int
    happybeings: int
    shipchange: int
    freighterchange: int
    planetchange: int
    starbasechange: int
    militarychange: int
    inventorychange: int
    prioritypointchange: int
    percentchange: float
    victoryscorechange: int


@dataclass
class Relation:
    id: int
    playerid: int
    playertoid: int
    relationto: int
    relationfrom: int
    conflictlevel: int
    color: str


@dataclass
class Advantage:
    id: int
    name: str
    description: str
    value: int
    isbase: bool
    locked: bool
    dur: int
    tri: int
    mol: int
    mc: int


@dataclass
class Badge:
    id: int
    raceid: int
    badgelevel: int
    badgetype: int
    forrank: int
    endturn: int
    achievement: int
    dur: int
    tri: int
    mol: int
    mc: int
    planets: int
    ships: int
    starbases: int
    military: int
    battleswon: int
    name: str
    description: str
    completed: bool


@dataclass
class Race:
    id: int
    name: str
    shortname: str
    adjective: str
    baseadvantages: str
    advantages: str
    basehulls: str
    hulls: str
