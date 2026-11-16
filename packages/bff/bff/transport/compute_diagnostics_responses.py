"""BFF transport models for compute diagnostics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ComputeDiagnosticsShellContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)


class ComputeDiagnosticsSnapshotResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    shell: ComputeDiagnosticsShellContext
    freeze_armed: bool = Field(alias="freezeArmed")
    allowlisted_player_ids: list[int] = Field(alias="allowlistedPlayerIds")
    pool_queue: list[dict] = Field(alias="poolQueue")
    in_flight: list[dict] = Field(alias="inFlight")
    dag_nodes: list[dict] = Field(alias="dagNodes")
    ready_queue: list[dict] = Field(alias="readyQueue")
    next_single_step: dict = Field(alias="nextSingleStep")
    completion_history: list[dict] = Field(alias="completionHistory")
    recent_failures: list[dict] = Field(alias="recentFailures")
    server_streams: list[dict] = Field(alias="serverStreams")
    remote_pool: dict = Field(alias="remotePool")
    live_occupancy: dict = Field(alias="liveOccupancy")
    concurrency_timeline: list[dict] = Field(alias="concurrencyTimeline")
    concurrency_rollup: dict = Field(alias="concurrencyRollup")


class ComputeDiagnosticsFreezeStatusResponse(BaseModel):
    """Thin freeze control signal (no pool/DAG/history payload)."""

    model_config = ConfigDict(populate_by_name=True)

    shell: ComputeDiagnosticsShellContext
    freeze_armed: bool = Field(alias="freezeArmed")
    allowlisted_player_ids: list[int] = Field(alias="allowlistedPlayerIds")


class ComputeDiagnosticsFreezeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)
    freeze_armed: bool = Field(alias="freezeArmed")


class ComputeDiagnosticsAllowlistRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)
    player_ids: list[int] = Field(alias="playerIds")


class ComputeDiagnosticsSingleStepResponse(ComputeDiagnosticsSnapshotResponse):
    """The snapshot after a single-step, and whether a step was released.

    ``released`` is True when the target was dispatched, or, for a held pool
    item, when its dequeue grant was armed (a worker takes it when one is
    free). It is False when nothing was armed, or when another dispatch gate
    (for example inference global pause) refused the target, so Run can tell a
    step that did nothing from one that advanced or is waiting for a worker.
    """

    released: bool


class ComputeDiagnosticsSingleStepRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)
