"""Thin re-export: scores cancel is ``RowLifecycleOp.CANCEL``.

Prefer :func:`api.analytics.scores.row_lifecycle.apply_scores_row_lifecycle`
(or :func:`~api.analytics.scores.row_lifecycle.apply_scores_row_cancel`) as the
scores owner path for detach / cancel / retire.
"""

from __future__ import annotations

from api.analytics.scores.row_lifecycle import apply_scores_row_cancel

__all__ = ["apply_scores_row_cancel"]
