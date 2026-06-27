"""Tests for export value schema description validation."""

from __future__ import annotations

import pytest
from api.analytics.exports.schema_validation import validate_export_value_schema
from api.analytics.fleet.export_schema import EXPORT_VALUE_SCHEMA
from api.analytics.scores.export_schema import EXPORT_VALUE_SCHEMA as SCORES_EXPORT_VALUE_SCHEMA


def test_scores_export_value_schema_is_fully_described() -> None:
    validate_export_value_schema(SCORES_EXPORT_VALUE_SCHEMA, analytic_id="scores")


def test_fleet_export_value_schema_is_fully_described() -> None:
    validate_export_value_schema(EXPORT_VALUE_SCHEMA, analytic_id="fleet")


def test_validate_export_value_schema_requires_root_description() -> None:
    with pytest.raises(RuntimeError, match="root must include"):
        validate_export_value_schema(
            {"type": "object", "properties": {}},
            analytic_id="bad",
        )


def test_validate_export_value_schema_requires_property_description() -> None:
    with pytest.raises(RuntimeError, match="missing description at \\$\\.label"):
        validate_export_value_schema(
            {
                "type": "object",
                "description": "Root.",
                "properties": {
                    "label": {"type": "string"},
                },
            },
            analytic_id="bad",
        )
