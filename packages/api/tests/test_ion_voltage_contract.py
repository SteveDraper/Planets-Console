"""Cross-layer contract: Core ion voltage vs test-fixtures/ion_voltage_contract.json.

Host-aligned math per docs/design-stellar-cartography-map-rendering.md and
api/concepts/stellar_cartography/sample_at.py (_ion_voltage_at).
"""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from api.analytics.stellar_cartography import ion_storm_class
from api.concepts.stellar_cartography.sample_at import (
    ION_CLASS_NAMES,
    _ion_voltage_at,
    sample_at,
)
from api.models.space import IonStorm

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "test-fixtures" / "ion_voltage_contract.json"


@pytest.fixture(scope="module")
def contract_fixture() -> dict:
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def _circles_as_ion_storms(circles: list[dict]) -> list[IonStorm]:
    return [
        IonStorm(
            id=index + 1,
            x=circle["x"],
            y=circle["y"],
            radius=circle["radius"],
            voltage=circle["voltage"],
            warp=0,
            heading=0,
            isgrowing=False,
            parentid=0,
        )
        for index, circle in enumerate(circles)
    ]


def _ion_storms_from_case(case: dict) -> list[IonStorm]:
    storms = case.get("storms")
    if storms is None:
        return _circles_as_ion_storms(case["circles"])
    return [IonStorm(**storm) for storm in storms]


def _turn_for_case(stellar_cartography_turn, case: dict):
    turn = deepcopy(stellar_cartography_turn)
    turn.settings.nuionstorms = case["cloudy"]
    turn.ionstorms = _ion_storms_from_case(case)
    return turn


class TestIonVoltageContractDirect:
    def test_ion_voltage_at_matches_fixture(self, contract_fixture):
        tolerance = contract_fixture["tolerance"]
        for case in contract_fixture["cases"]:
            group = _circles_as_ion_storms(case["circles"])
            for sample in case["samples"]:
                got = _ion_voltage_at(group, sample["x"], sample["y"], cloudy=case["cloudy"])
                assert abs(got - sample["expectedVoltage"]) <= tolerance, case["id"]


class TestIonVoltageContractSampleAt:
    @pytest.fixture
    def stellar_cartography_turn(self):
        import json as json_mod
        from pathlib import Path as PathMod

        from api.serialization.turn import turn_info_from_json

        assets = PathMod(__file__).resolve().parent.parent / "api" / "storage" / "assets"
        with open(assets / "turn_stellar_cartography_sample.json") as f:
            return turn_info_from_json(json_mod.load(f))

    def test_sample_at_voltage_and_class(self, contract_fixture, stellar_cartography_turn):
        for case in contract_fixture["cases"]:
            turn = _turn_for_case(stellar_cartography_turn, case)
            for sample in case["samples"]:
                data = sample_at(turn, sample["x"], sample["y"])
                ion_entries = [entry for entry in data["entries"] if entry["layer"] == "ion-storms"]
                expected_voltage = sample["expectedVoltage"]
                if expected_voltage <= 0:
                    assert ion_entries == [], case["id"]
                    continue

                assert len(ion_entries) == 1, case["id"]
                mev = int(round(expected_voltage))
                expected_class = sample.get("expectedClass", ion_storm_class(mev))
                class_name = ION_CLASS_NAMES[expected_class]
                assert ion_entries[0]["lines"] == [
                    f"Class {expected_class} {class_name}",
                    f"{mev} V",
                ], case["id"]
