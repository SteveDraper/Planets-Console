"""Breakpoint registry for durable file storage.

Patterns use ``*`` for a single path segment. Longest matching breakpoint wins.
"""

from __future__ import annotations

from pathlib import Path

from api.errors import ValidationError

# V1 patterns aligned with service store paths (ADR 0001).
BREAKPOINT_PATTERNS: tuple[tuple[str, ...], ...] = (
    ("games", "*", "info"),
    ("games", "*", "analytics", "*"),
    ("games", "*", "*", "analytics", "*"),
    ("games", "*", "*", "turns", "*"),
    ("games", "*", "*", "turns", "*", "analytics", "*"),
    ("credentials", "accounts", "*"),
)


def _validate_path_segment(segment: str) -> None:
    """Reject segments that could escape ``storage_root`` when joined as paths."""
    if segment in (".", ".."):
        raise ValidationError(f"Invalid path segment: {segment!r}")
    if "\\" in segment:
        raise ValidationError("Store path must use forward slashes only")
    if segment == "":
        raise ValidationError("Path must not contain empty segments")


def _path_segments(path: str) -> list[str]:
    if "\\" in path:
        raise ValidationError("Store path must use forward slashes only")
    parts = path.split("/")
    if any(part == "" for part in parts):
        raise ValidationError("Path must not contain empty segments")
    for part in parts:
        _validate_path_segment(part)
    return parts


def _pattern_matches_path(pattern: tuple[str, ...], segments: list[str]) -> bool:
    if len(segments) != len(pattern):
        return False
    for pat_seg, path_seg in zip(pattern, segments, strict=True):
        if pat_seg == "*":
            continue
        if pat_seg != path_seg:
            return False
    return True


def _pattern_prefix_matches(pattern: tuple[str, ...], segments: list[str]) -> bool:
    if len(segments) > len(pattern):
        return False
    for pat_seg, path_seg in zip(pattern, segments, strict=False):
        if pat_seg == "*":
            continue
        if pat_seg != path_seg:
            return False
    return True


def resolve_breakpoint(path: str) -> tuple[str, str | None]:
    """Return ``(breakpoint_path, in_document_suffix)`` for a registered path.

    ``in_document_suffix`` is ``None`` when ``path`` is exactly the breakpoint.
    Raises ``ValidationError`` when the path is not covered by any pattern.
    """
    segments = _path_segments(path)
    if not segments:
        raise ValidationError("Root path is not a registered document path")

    best_pattern: tuple[str, ...] | None = None
    for pattern in BREAKPOINT_PATTERNS:
        if len(segments) < len(pattern):
            continue
        if _pattern_matches_path(pattern, segments[: len(pattern)]):
            if best_pattern is None or len(pattern) > len(best_pattern):
                best_pattern = pattern

    if best_pattern is None:
        raise ValidationError(f"Unregistered store path: {path!r}")

    breakpoint_path = "/".join(segments[: len(best_pattern)])
    suffix_segments = segments[len(best_pattern) :]
    suffix = "/".join(suffix_segments) if suffix_segments else None
    return breakpoint_path, suffix


def is_registered_path(path: str) -> bool:
    """Return whether ``path`` is covered by a breakpoint pattern."""
    try:
        resolve_breakpoint(path)
        return True
    except ValidationError:
        return False


def is_navigable_prefix(prefix: str) -> bool:
    """Return whether ``prefix`` may be used with ``list``."""
    if prefix == "":
        return True
    segments = _path_segments(prefix)
    if not segments:
        return True
    if is_registered_path(prefix):
        return True
    return any(_pattern_prefix_matches(pattern, segments) for pattern in BREAKPOINT_PATTERNS)


def document_relpath(breakpoint_path: str) -> Path:
    """Map a breakpoint path to its relative JSON file path under ``storage_root``."""
    _path_segments(breakpoint_path)
    return Path(f"{breakpoint_path}.json")
