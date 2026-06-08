"""BFF OpenAPI models for scores inference NDJSON stream events."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class InferenceStreamSolutionEvent(BaseModel):
    type: Literal["solution"]
    solution: dict[str, Any]


class InferenceStreamProgressEvent(BaseModel):
    type: Literal["progress"]
    policyStepId: str | None = None
    comboCount: int | None = None
    heldCount: int | None = None
    solverStatus: str | None = None
    elapsedSeconds: float | None = None


class InferenceStreamCompleteEvent(BaseModel):
    type: Literal["complete"]
    status: str
    summary: str
    solutionCount: int
    isComplete: bool = True
    diagnostics: dict[str, Any] | None = None


class InferenceStreamErrorEvent(BaseModel):
    type: Literal["error"]
    detail: str


__all__ = [
    "InferenceStreamCompleteEvent",
    "InferenceStreamErrorEvent",
    "InferenceStreamProgressEvent",
    "InferenceStreamSolutionEvent",
]
