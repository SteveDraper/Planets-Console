"""Serializable job and result wire types for compute leaf steps."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Orchestration plane: scope + dependency outputs -> serializable job payload.
BuildStepJobWireFn = Callable[..., Any]

# Compute plane: job payload -> serializable result payload.
RunStepFn = Callable[[Any], Any]
