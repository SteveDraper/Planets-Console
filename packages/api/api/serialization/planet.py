"""Planet dataclass to JSON-safe dict for API responses."""

from dataclasses import asdict
from enum import Enum

from api.models.planet import Planet


def planet_to_public_json(planet: Planet) -> dict:
    """Serialize a planet for map nodes and clients. Enums become plain values."""
    raw = asdict(planet)
    out: dict = {}
    for key, value in raw.items():
        if isinstance(value, Enum):
            out[key] = value.value
        else:
            out[key] = value
    return out
