"""Scores inference-row layout step in the storage migration pipeline.

Generic re-home splits a shared ``.../analytics/scores`` document whose
``inference_rows`` map is keyed by player id into one document per player at
``.../analytics/scores/inference_rows/{playerId}``. The logical key does not
change. An empty remainder deletes the shared document. Row-content upgrade
stays on read in ``upgrade_persisted_inference_row``.
"""

from __future__ import annotations

from api.storage.boundaries import SCORES_INFERENCE_ROW_PATTERN
from api.storage.migrations import StorageMigration


def scores_inference_row_storage_migration() -> StorageMigration:
    """Return the scores step that brings a directory to storage version 2.

    Fleet's layout step is version 1. This step has no structural handler:
    the introduced breakpoint is a longer prefix of the shared scores document.
    """
    return StorageMigration(
        version=2,
        introduced_pattern=SCORES_INFERENCE_ROW_PATTERN,
    )
