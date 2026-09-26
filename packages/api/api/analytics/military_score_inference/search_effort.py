"""Stream-ladder inference search effort and the hang fuse.

Row allowance is the p90 deterministic time one ladder spent under the old
20s wall clock, 8 workers, game 683364 turn 27 (2026-09-25). Per-tier caps
live in the YAML and use the same run. Zero stays zero.
"""

from __future__ import annotations

import os

# Soft-global row allowance: p90 deterministic time of one wall-budgeted ladder.
DEFAULT_STREAM_ROW_SEARCH_EFFORT = 4.097

# Wall bound for a search that will not return. Not the search allowance.
INFERENCE_SEARCH_HANG_FUSE_SECONDS = 900.0

_STREAM_SEARCH_EFFORT_ENV = "MILITARY_SCORE_INFERENCE_STREAM_SEARCH_EFFORT"


class InferenceSearchHangFuse(RuntimeError):
    """The row's search wall hit the hang fuse. Fail the step closed."""


def stream_row_search_effort() -> float:
    """Row inference search effort allowance for one stream ladder.

    Same role as the old 20s soft-global steer, in deterministic-time units.
    """
    raw = os.environ.get(_STREAM_SEARCH_EFFORT_ENV)
    if raw is not None:
        return float(raw)
    return DEFAULT_STREAM_ROW_SEARCH_EFFORT
