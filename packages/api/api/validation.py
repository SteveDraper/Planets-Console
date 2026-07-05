"""Shared validation helpers for Core API registration and configuration."""


def require_non_empty_string(
    value: str,
    *,
    field: str,
    analytic_id: str | None = None,
    subject: str = "catalog entry",
) -> None:
    """Raise RuntimeError when value is empty or whitespace-only."""
    if value and value.strip():
        return
    prefix = f"Turn analytic {analytic_id!r} " if analytic_id is not None else "Turn analytic "
    raise RuntimeError(f"{prefix}{subject} {field} must be a non-empty string, got {value!r}")
