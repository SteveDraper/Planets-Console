"""Enum types for the Planets.nu data model.

Uses IntEnum for integer-keyed enumerations. Each enum includes an UNKNOWN = -1
sentinel so that unrecognised values from the API deserialize gracefully.
"""

from enum import IntEnum


class MessageType(IntEnum):
    UNKNOWN = -1
    SHIP = 1
    PLANET = 2
    STARBASE = 3
    MINE_SWEEP = 4
    MINEFIELD = 5
    EXPLOSION = 6
    PLANETARY_DEFENSE = 7
    COMBAT = 8
    ALLIANCE = 9
    ION_STORM = 10
    COLONIST = 11
    NATIVES = 12
    SCORE = 13
    METEOR = 14
    SENSOR_SWEEP = 15
    BIOGRAPHICAL = 16
    DIPLOMACY = 17
    HCONFIG = 18
    SPECIAL = 19
    PLAYER = 20
    DISTRESS = 21


class NativeType(IntEnum):
    UNKNOWN = -1
    NONE = 0
    HUMANOID = 1
    BOVINOID = 2
    REPTILIAN = 3
    AVIAN = 4
    AMORPHOUS = 5
    INSECTOID = 6
    AMPHIBIAN = 7
    GHIPSOLDAL = 8
    SILICONOID = 9
    BOTANICAL = 10
    HORWASP = 11


class GameStatus(IntEnum):
    UNKNOWN = -1
    JOINING = 0
    RUNNING = 1
    PAUSED = 2
    FINISHED = 3
