"""Shared export tree meta branch builders."""

from __future__ import annotations

from api.analytics.scores.export_precedence import SearchStatus


def build_export_meta_branch(
    *,
    host_turn: int,
    search_status: SearchStatus | None = None,
    solutions_held: int = 0,
) -> dict[str, object]:
    meta: dict[str, object] = {"hostTurn": host_turn}
    if search_status is not None:
        meta["searchStatus"] = search_status
    if solutions_held > 0:
        meta["solutionsHeld"] = solutions_held
    return meta
