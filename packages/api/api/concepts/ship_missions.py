"""Ship mission wire ids used across analytics.

Confirmed from the official Nu client ``ShipMissions`` enum
(``app.planets.nu``). Bioscan is not a separate mission id: bioscan-capable
hulls use ``SENSOR_SWEEP`` and the client renames the mission in the UI.
"""

from __future__ import annotations

# Nu ``ShipMissions.MineSweep``.
MINE_SWEEP_MISSION = 1

# Nu ``ShipMissions.SensorSweep``.
SENSOR_SWEEP_MISSION = 4


def is_mine_sweep_mission(mission: int) -> bool:
    """True when the ship is on Mine Sweep this turn."""
    return mission == MINE_SWEEP_MISSION


def is_sensor_sweep_or_bioscan_mission(mission: int) -> bool:
    """True when the ship is on Sensor Sweep / Bioscan this turn."""
    return mission == SENSOR_SWEEP_MISSION
