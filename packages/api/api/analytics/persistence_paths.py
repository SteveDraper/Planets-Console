"""Thin shared builders for analytic persistence document keys (ADR 0002)."""

from __future__ import annotations


def game_global_analytic_document_key(game_id: int, analytic_id: str) -> str:
    """``games/{gameId}/analytics/{analytic_id}`` breakpoint document."""
    return f"games/{game_id}/analytics/{analytic_id}"


def turn_scoped_analytic_document_key(
    game_id: int,
    perspective: int,
    turn_number: int,
    analytic_id: str,
) -> str:
    """``games/{gameId}/{perspective}/turns/{turn}/analytics/{analytic_id}`` document."""
    return f"games/{game_id}/{perspective}/turns/{turn_number}/analytics/{analytic_id}"
