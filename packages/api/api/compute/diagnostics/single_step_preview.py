"""Single-step target preview for compute diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

SingleStepSource = Literal["held", "would_dispatch"]
SingleStepDisabledReason = Literal[
    "freeze_not_armed",
    "empty_allowlist",
    "nothing_steppable",
]


@dataclass(frozen=True)
class SingleStepPreview:
    """One schedulable compute step that single-step would release next."""

    scope_key: str
    analytic_id: str
    step_kind: str | None
    step_index: int
    priority_band: str | None
    backend: str | None
    source: SingleStepSource


def single_step_preview_to_wire(
    preview: SingleStepPreview | None,
    *,
    disabled_reason: SingleStepDisabledReason | None,
) -> dict[str, Any]:
    """Return camelCase next-single-step block for the diagnostics snapshot."""
    target: dict[str, Any] | None = None
    if preview is not None:
        target = {
            "scopeKey": preview.scope_key,
            "analyticId": preview.analytic_id,
            "stepKind": preview.step_kind,
            "stepIndex": preview.step_index,
            "priorityBand": preview.priority_band,
            "backend": preview.backend,
            "source": preview.source,
        }
    return {
        "target": target,
        "disabledReason": disabled_reason,
    }
