"""JSON shape helpers for storage reads."""

from api.errors import ValidationError
from api.storage.base import JSONValue


def require_dict(data: JSONValue, label: str) -> dict:
    if not isinstance(data, dict):
        raise ValidationError(f"Expected JSON object for {label}, got {type(data).__name__}")
    return data
