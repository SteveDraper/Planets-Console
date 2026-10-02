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
    ("games", "*", "*", "analytics", "fleet-evidence", "*"),
    ("games", "*", "*", "turns", "*"),
    ("games", "*", "*", "turns", "*", "analytics", "*"),
    ("games", "*", "*", "turns", "*", "analytics", "fleet", "*"),
    ("credentials", "accounts", "*"),
    ("league-teams", "*"),
    ("meta", "storage-version"),
)

BreakpointPatterns = tuple[tuple[str, ...], ...]


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


def resolve_breakpoint(
    path: str,
    patterns: BreakpointPatterns | None = None,
) -> tuple[str, str | None]:
    """Return ``(breakpoint_path, in_document_suffix)`` for a registered path.

    ``in_document_suffix`` is ``None`` when ``path`` is exactly the breakpoint.
    Raises ``ValidationError`` when the path is not covered by any pattern.
    """
    registry = BREAKPOINT_PATTERNS if patterns is None else patterns
    segments = _path_segments(path)
    if not segments:
        raise ValidationError("Root path is not a registered document path")

    best_pattern: tuple[str, ...] | None = None
    for pattern in registry:
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


def pattern_matches_breakpoint(pattern: tuple[str, ...], breakpoint_path: str) -> bool:
    """Return whether ``breakpoint_path`` matches ``pattern`` segment for segment."""
    return _pattern_matches_path(pattern, _path_segments(breakpoint_path))


def is_registered_path(path: str, patterns: BreakpointPatterns | None = None) -> bool:
    """Return whether ``path`` is covered by a breakpoint pattern."""
    try:
        resolve_breakpoint(path, patterns)
        return True
    except ValidationError:
        return False


def is_navigable_prefix(prefix: str, patterns: BreakpointPatterns | None = None) -> bool:
    """Return whether ``prefix`` may be used with ``list``."""
    registry = BREAKPOINT_PATTERNS if patterns is None else patterns
    if prefix == "":
        return True
    segments = _path_segments(prefix)
    if not segments:
        return True
    if is_registered_path(prefix, registry):
        return True
    return any(_pattern_prefix_matches(pattern, segments) for pattern in registry)


def is_prefix_of_longer_breakpoint(
    path: str,
    patterns: BreakpointPatterns | None = None,
) -> bool:
    """Return whether ``path`` is a strict prefix of a longer breakpoint pattern.

    When true, ``path`` sits between breakpoints (e.g. ``…/turns/N/analytics``
    under the turn document breakpoint but before ``…/analytics/{id}``). File
    ``list`` should enumerate the filesystem there instead of looking up a
    suffix inside the shorter document.
    """
    registry = BREAKPOINT_PATTERNS if patterns is None else patterns
    segments = _path_segments(path)
    if not segments:
        return False
    try:
        breakpoint_path, _suffix = resolve_breakpoint(path, registry)
    except ValidationError:
        return any(
            len(pattern) > len(segments) and _pattern_prefix_matches(pattern, segments)
            for pattern in registry
        )
    matched_len = len(_path_segments(breakpoint_path))
    return any(
        len(pattern) > matched_len and _pattern_prefix_matches(pattern, segments)
        for pattern in registry
    )


def document_relpath(breakpoint_path: str) -> Path:
    """Map a breakpoint path to its relative JSON file path under ``storage_root``."""
    _path_segments(breakpoint_path)
    return Path(f"{breakpoint_path}.json")
