"""Unit tests for shared inference product-field policy."""

from __future__ import annotations

import pytest
from api.analytics.military_score_inference.inference_api_payload import (
    FUNCTIONAL_LEFTOVER_STATUSES,
    INFERENCE_ADMISSION_SKIP_STATUSES,
    product_payload_fields,
)
from api.analytics.military_score_inference.solver import (
    STATUS_EXACT,
    STATUS_MODERATE_RESIDUAL,
)
from api.analytics.military_score_inference.uncharacterized_roster import (
    STATUS_UNCHARACTERIZED_ROSTER,
)

_ROSTER_LEFTOVER = {"kind": "unknown_loss_bound", "lowerBound2x": 800}
_ROSTER_SIGNATURES = [
    {"shipClass": "warship", "build": {"id": "unknown_military_ship", "count": 1}}
]


@pytest.mark.parametrize("status", sorted(INFERENCE_ADMISSION_SKIP_STATUSES))
def test_skip_strips_leftover_even_if_source_carried_it(status: str):
    product = product_payload_fields(status, leftover=22)
    assert product.status == status
    assert product.unexplained_military_delta_2x is None
    assert product.placeholders == []


@pytest.mark.parametrize("status", sorted(FUNCTIONAL_LEFTOVER_STATUSES))
def test_residual_none_placeholders_emits_empty_list(status: str):
    product = product_payload_fields(status, leftover=22)
    assert product.status == status
    assert product.placeholders == []
    assert product.unexplained_military_delta_2x == 22


@pytest.mark.parametrize("status", sorted(FUNCTIONAL_LEFTOVER_STATUSES))
def test_residual_exposes_zero_leftover(status: str):
    product = product_payload_fields(status, leftover=0)
    assert product.status == status
    assert product.placeholders == []
    assert product.unexplained_military_delta_2x == 0


def test_exact_omits_leftover_and_placeholders_when_source_omits_them():
    product = product_payload_fields(STATUS_EXACT, leftover=22)
    assert product.status == STATUS_EXACT
    assert product.placeholders is None
    assert product.unexplained_military_delta_2x is None


def test_exact_keeps_source_placeholders_and_omits_leftover():
    product = product_payload_fields(STATUS_EXACT, leftover=22, placeholders=[])
    assert product.status == STATUS_EXACT
    assert product.placeholders == []
    assert product.unexplained_military_delta_2x is None
    assert product.leftover is None
    assert product.lattice_signatures is None
    assert product.departure_pins is None


def test_exact_keeps_departure_pins_when_source_carries_them():
    pins = [
        {
            "kind": "exact_set",
            "shipClass": "warship",
            "records": [{"recordId": "r1", "disposition": "lost"}],
        }
    ]
    product = product_payload_fields(STATUS_EXACT, leftover=22, departure_pins=pins)
    assert product.departure_pins == pins
    assert product.unexplained_military_delta_2x is None


def test_roster_keeps_tagged_leftover_and_signatures():
    product = product_payload_fields(
        STATUS_UNCHARACTERIZED_ROSTER,
        leftover=22,
        tagged_leftover=_ROSTER_LEFTOVER,
        lattice_signatures=_ROSTER_SIGNATURES,
    )
    assert product.status == STATUS_UNCHARACTERIZED_ROSTER
    assert product.placeholders == []
    assert product.unexplained_military_delta_2x is None
    assert product.leftover == _ROSTER_LEFTOVER
    assert product.lattice_signatures == _ROSTER_SIGNATURES


def test_residual_drops_tagged_leftover_and_signatures():
    product = product_payload_fields(
        STATUS_MODERATE_RESIDUAL,
        leftover=22,
        tagged_leftover=_ROSTER_LEFTOVER,
        lattice_signatures=_ROSTER_SIGNATURES,
    )
    assert product.unexplained_military_delta_2x == 22
    assert product.leftover is None
    assert product.lattice_signatures is None
