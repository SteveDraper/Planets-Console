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
    dag_nodes: list[dict] = Field(alias="dagNodes")
    ready_queue: list[dict] = Field(alias="readyQueue")
    completion_history: list[dict] = Field(alias="completionHistory")
    server_streams: list[dict] = Field(alias="serverStreams")


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


class ComputeDiagnosticsSingleStepRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    game_id: int = Field(alias="gameId")
    perspective: int
    turn: int = Field(ge=1)
