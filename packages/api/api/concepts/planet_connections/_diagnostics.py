"""Mutable diagnostics for connection-route BFS and lattice cache builds."""

from __future__ import annotations

from dataclasses import dataclass, field

from api.diagnostics import DiagnosticNode


@dataclass
class _FlareBfsMetrics:
    """Mutable counters for optional diagnostics (avoids per-pair child nodes in the BFS)."""

    bfs_runs: int = 0
    bfs_dequeues: int = 0
    bfs_enqueues: int = 0


@dataclass
class _FlareBfsHotspotTimings:
    """Cumulative wall-time (``perf_counter``) across BFS work for one eligibility layer.

    Sub-timers (``well_index`` / ``dest_well``) are included inside normal/flare loop totals.
    """

    distance_prune_sec: float = 0.0
    normal_branch_sec: float = 0.0
    flare_branch_sec: float = 0.0
    well_index_sec: float = 0.0
    dest_well_test_sec: float = 0.0

    def add_to_diagnostics(self, d: DiagnosticNode) -> None:
        d.values["bfsCumulativeHotspotDistancePruneSec"] = self.distance_prune_sec
        d.values["bfsCumulativeHotspotNormalBranchSec"] = self.normal_branch_sec
        d.values["bfsCumulativeHotspotFlareBranchSec"] = self.flare_branch_sec
        d.values["bfsCumulativeHotspotWellIndexSec"] = self.well_index_sec
        d.values["bfsCumulativeHotspotDestWellTestSec"] = self.dest_well_test_sec


@dataclass
class _LatticeBuildDiagnostics:
    """Records each **cache miss** in :func:`_get_lattice_angular_row` (build + store)."""

    builds: list[dict[str, int | float | bool]] = field(default_factory=list)

    def add_to_diagnostics(self, d: DiagnosticNode) -> None:
        d.values["latticeBuildEventCount"] = len(self.builds)
        d.values["latticeBuildCumulativeSec"] = (
            sum(float(b["buildSec"]) for b in self.builds) if self.builds else 0.0
        )
        d.values["latticeBuilds"] = list(self.builds)
