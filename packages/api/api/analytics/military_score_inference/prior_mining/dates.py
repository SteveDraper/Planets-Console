"""Parse Planets.nu host date strings for prior mining discovery."""

from __future__ import annotations

from datetime import date, datetime

_HOST_DATE_FORMATS = (
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_planets_host_date(value: str) -> date:
    """Parse a Planets.nu date string into a calendar date."""
    normalized = value.strip()
    if not normalized:
        raise ValueError("empty date string")
    for fmt in _HOST_DATE_FORMATS:
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported Planets.nu date format: {value!r}")


def parse_iso_calendar_date(value: str) -> date:
    return date.fromisoformat(value)
