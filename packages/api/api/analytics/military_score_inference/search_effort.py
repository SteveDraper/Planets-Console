"""Stream-ladder inference search effort and the hang fuse.

Calibration on the dev host, 2026-09-24, ``num_workers=1``. Each sample is a
weighted-permutation CP-SAT search that returned FEASIBLE because it ran out
the wall cap (not an early stop). Deterministic time per wall second was not
stable across slice lengths, so each length is its own product:

- 1s wall -> 2.981060 deterministic time
- 3s wall -> 9.891221
- 5s wall -> 17.398859
- 8s wall -> 28.152574
- 20s wall -> 74.972095

YAML ``minEffort`` / ``maxEffort`` and the row allowance use those products
rounded to 3 decimal places. Zero stays zero.
"""

from __future__ import annotations

import os

# Soft-global row allowance: the effort a 20s wall slice spent on this host.
DEFAULT_STREAM_ROW_SEARCH_EFFORT = 74.972

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
