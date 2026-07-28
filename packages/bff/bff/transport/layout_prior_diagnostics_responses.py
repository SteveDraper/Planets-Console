"""BFF transport models for homeworld layout-prior / refine diagnostics (#274)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LayoutPriorDiagnosticsShellContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)


class LayoutPriorReportsResponse(BaseModel):
    """Homeworld diagnostics: layout-prior reports plus refine/baseline timing."""

    model_config = ConfigDict(populate_by_name=True)

    shell: LayoutPriorDiagnosticsShellContext
    reports: list[dict[str, Any]]
    evidence_refine_reports: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="evidenceRefineReports",
    )
    evidence_refine_summary: dict[str, Any] = Field(
        default_factory=dict,
        alias="evidenceRefineSummary",
    )
    baseline_reports: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="baselineReports",
    )
    ensure_failures: list[dict[str, Any]] = Field(
        default_factory=list,
        alias="ensureFailures",
    )
