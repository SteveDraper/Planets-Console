"""Unit tests for race climate catalog homeworld preferred temperatures."""

from api.concepts.races import (
    CRYSTAL_DESERT_PREFERRED_HOMEWORLD_TEMP_W,
    CRYSTAL_RACE_ID,
    DEFAULT_PREFERRED_HOMEWORLD_TEMP_W,
    PRIVATEER_RACE_ID,
    is_privateer,
    preferred_homeworld_temp_w,
)


def test_crystal_race_id_is_seven() -> None:
    assert CRYSTAL_RACE_ID == 7


def test_privateer_race_id_is_five() -> None:
    assert PRIVATEER_RACE_ID == 5
    assert is_privateer(5) is True
    assert is_privateer(7) is False


def test_preferred_homeworld_temp_crystal_defaults_to_desert_peak() -> None:
    assert preferred_homeworld_temp_w(CRYSTAL_RACE_ID) == CRYSTAL_DESERT_PREFERRED_HOMEWORLD_TEMP_W
    assert preferred_homeworld_temp_w(7) == 100


def test_preferred_homeworld_temp_other_races_default_to_fifty() -> None:
    assert preferred_homeworld_temp_w(1) == DEFAULT_PREFERRED_HOMEWORLD_TEMP_W
    assert preferred_homeworld_temp_w(8) == 50
    assert preferred_homeworld_temp_w(12) == 50
