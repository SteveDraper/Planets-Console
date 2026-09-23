"""Fleet prior selection: DepOutputs vs disk, including skip-disk when final."""

from __future__ import annotations

from api.analytics.fleet.prior_selection import (
    resolve_fleet_prior_persisted,
    select_fleet_prior_persisted,
)
from api.analytics.fleet.types import (
    FleetAcquisitionLedger,
    FleetMaterializationProvenance,
    PersistedFleetLedger,
)


def _persisted(*, name: str, final: bool) -> PersistedFleetLedger:
    return PersistedFleetLedger(
        ledger=FleetAcquisitionLedger(player_id=8, player_name=name),
        provenance=FleetMaterializationProvenance(
            turn_evidence_at_n=final,
            prior_ledger_at_n_minus_1=True,
        ),
    )


def _provenance_is_final(persisted: PersistedFleetLedger) -> bool:
    """Test predicate: these cases assert DepOutputs-vs-disk preference by provenance."""
    return persisted.provenance.is_final


def test_select_prefers_final_dependency_outputs_over_disk():
    deps = _persisted(name="deps", final=True)
    loads: list[int] = []

    def load_from_disk() -> PersistedFleetLedger | None:
        loads.append(1)
        return _persisted(name="disk", final=True)

    selected = select_fleet_prior_persisted(
        from_dependency_outputs=deps,
        load_from_disk=load_from_disk,
        is_ensure_final=_provenance_is_final,
    )
    assert selected is deps
    assert loads == []


def test_select_prefers_final_disk_over_non_final_dependency_outputs():
    deps = _persisted(name="deps", final=False)
    disk = _persisted(name="disk", final=True)
    loads: list[int] = []

    def load_from_disk() -> PersistedFleetLedger | None:
        loads.append(1)
        return disk

    selected = select_fleet_prior_persisted(
        from_dependency_outputs=deps,
        load_from_disk=load_from_disk,
        is_ensure_final=_provenance_is_final,
    )
    assert selected is disk
    assert loads == [1]


def test_resolve_skips_disk_when_dependency_outputs_is_final():
    deps = _persisted(name="deps", final=True)
    loads: list[int] = []

    def load_from_disk() -> PersistedFleetLedger | None:
        loads.append(1)
        return _persisted(name="disk", final=True)

    selected = resolve_fleet_prior_persisted(
        from_dependency_outputs=deps,
        load_from_disk=load_from_disk,
        is_ensure_final=_provenance_is_final,
    )
    assert selected is deps
    assert loads == []


def test_resolve_loads_disk_when_dependency_outputs_is_not_final():
    deps = _persisted(name="deps", final=False)
    disk = _persisted(name="disk", final=True)
    loads: list[int] = []

    def load_from_disk() -> PersistedFleetLedger | None:
        loads.append(1)
        return disk

    selected = resolve_fleet_prior_persisted(
        from_dependency_outputs=deps,
        load_from_disk=load_from_disk,
        is_ensure_final=_provenance_is_final,
    )
    assert selected is disk
    assert loads == [1]


def test_resolve_loads_disk_when_dependency_outputs_is_missing():
    disk = _persisted(name="disk", final=True)
    loads: list[int] = []

    def load_from_disk() -> PersistedFleetLedger | None:
        loads.append(1)
        return disk

    selected = resolve_fleet_prior_persisted(
        from_dependency_outputs=None,
        load_from_disk=load_from_disk,
        is_ensure_final=_provenance_is_final,
    )
    assert selected is disk
    assert loads == [1]
