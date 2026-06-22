"""Validation helpers for analytic export value schemas."""

from __future__ import annotations

from typing import Any


def validate_export_value_schema(
    schema: dict[str, Any],
    *,
    analytic_id: str,
    path: str = "$",
) -> None:
    """Require a non-empty description on every declared schema field."""
    if not isinstance(schema, dict):
        raise RuntimeError(
            f"{analytic_id} export value_schema at {path} must be a JSON Schema object"
        )

    if path == "$":
        description = schema.get("description")
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(
                f"{analytic_id} export value_schema root must include a non-empty description"
            )

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, subschema in properties.items():
            field_path = f"{path}.{key}"
            if not isinstance(subschema, dict):
                raise RuntimeError(
                    f"{analytic_id} export value_schema at {field_path} "
                    "must be a JSON Schema object"
                )
            description = subschema.get("description")
            if not isinstance(description, str) or not description.strip():
                raise RuntimeError(
                    f"{analytic_id} export value_schema missing description at {field_path}"
                )
            validate_export_value_schema(subschema, analytic_id=analytic_id, path=field_path)

    items = schema.get("items")
    if isinstance(items, dict) and items.get("type") == "object" and "properties" in items:
        items_path = f"{path}[]"
        description = items.get("description")
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError(
                f"{analytic_id} export value_schema missing description at {items_path}"
            )
        validate_export_value_schema(items, analytic_id=analytic_id, path=items_path)
