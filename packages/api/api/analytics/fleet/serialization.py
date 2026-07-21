"""JSON codecs for fleet analytic domain types."""

from __future__ import annotations

from typing import Any

from api.analytics.fleet.constants import (
    ANALYTIC_ID,
    FLEET_LEDGERS_KEY,
    FLEET_MATERIALIZATION_VERSION,
)
from api.analytics.fleet.types import (
    FLEET_BOUNDED_OPERATORS,
    FLEET_EVIDENCE_EVENT_KINDS,
    FLEET_SHIP_DISPOSITIONS,
    FleetAcquisitionLedger,
    FleetAlibi,
    FleetBuildOptionSet,
    FleetCountDiscrepancy,
    FleetEvidenceEvent,
    FleetFieldBounded,
    FleetFieldConstraint,
    FleetFieldKnown,
    FleetFieldOptions,
    FleetFieldRegion,
    FleetFieldRegionStarbaseCoord,
    FleetFieldUnknown,
    FleetLastSeen,
    FleetMaterializationProvenance,
    FleetPossiblyLost,
    FleetRowQualifiers,
    FleetShipRecord,
    FleetShipRecordFields,
    FleetTurnSnapshot,
    PersistedFleetLedger,
)
from api.exceptions import ValidationError


def _require_object_list(raw: object, *, field_name: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise ValidationError(f"{field_name} must be a list")
    entries: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValidationError(f"{field_name}[{index}] must be an object")
        entries.append(item)
    return entries


def _require_int_field(data: dict[str, Any], key: str, *, field_name: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValidationError(f"{field_name} {key} must be an int")
    return value


def append_fleet_evidence_event(
    record: FleetShipRecord,
    event: FleetEvidenceEvent,
) -> None:
    """Append one evidence event to a ship record timeline."""
    record.events.append(event)


def fleet_field_constraint_to_json(constraint: FleetFieldConstraint) -> dict[str, Any]:
    if isinstance(constraint, FleetFieldKnown):
        return {"kind": "known", "value": constraint.value}
    if isinstance(constraint, FleetFieldUnknown):
        return {"kind": "unknown"}
    if isinstance(constraint, FleetFieldBounded):
        return {
            "kind": "bounded",
            "operator": constraint.operator,
            "value": constraint.value,
        }
    if isinstance(constraint, FleetFieldOptions):
        return {"kind": "options", "values": list(constraint.values)}
    if isinstance(constraint, FleetFieldRegion):
        payload: dict[str, Any] = {"kind": "region"}
        if constraint.planet_ids:
            payload["planetIds"] = list(constraint.planet_ids)
        if constraint.starbase_coords:
            payload["starbaseCoords"] = [
                {"x": coord.x, "y": coord.y} for coord in constraint.starbase_coords
            ]
        if constraint.overlay_id is not None:
            payload["overlayId"] = constraint.overlay_id
        return payload
    raise TypeError(f"unsupported fleet field constraint: {type(constraint).__name__}")


def fleet_field_constraint_from_json(data: dict[str, Any]) -> FleetFieldConstraint:
    kind = data.get("kind")
    if kind == "known":
        value = data.get("value")
        if not isinstance(value, (int, str, float, bool)):
            raise ValidationError("fleet field constraint known value must be scalar")
        return FleetFieldKnown(value=value)
    if kind == "unknown":
        return FleetFieldUnknown()
    if kind == "bounded":
        operator = data.get("operator")
        value = data.get("value")
        if operator not in FLEET_BOUNDED_OPERATORS:
            raise ValidationError("fleet field constraint bounded operator is invalid")
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValidationError("fleet field constraint bounded value must be numeric")
        return FleetFieldBounded(operator=operator, value=value)
    if kind == "options":
        raw_values = data.get("values")
        if not isinstance(raw_values, list) or not raw_values:
            raise ValidationError("fleet field constraint options requires non-empty values")
        values: list[int | str] = []
        for entry in raw_values:
            if not isinstance(entry, (int, str)) or isinstance(entry, bool):
                raise ValidationError("fleet field constraint options values must be int or str")
            values.append(entry)
        return FleetFieldOptions(values=tuple(values))
    if kind == "region":
        planet_ids_raw = data.get("planetIds", [])
        if not isinstance(planet_ids_raw, list):
            raise ValidationError("fleet field constraint region planetIds must be a list")
        planet_ids: list[int] = []
        for planet_id in planet_ids_raw:
            if not isinstance(planet_id, int) or isinstance(planet_id, bool):
                raise ValidationError("fleet field constraint region planetIds must be integers")
            planet_ids.append(planet_id)

        starbase_coords_raw = data.get("starbaseCoords", [])
        if not isinstance(starbase_coords_raw, list):
            raise ValidationError("fleet field constraint region starbaseCoords must be a list")
        starbase_coords: list[FleetFieldRegionStarbaseCoord] = []
        for coord in starbase_coords_raw:
            if not isinstance(coord, dict):
                raise ValidationError(
                    "fleet field constraint region starbaseCoords entries must be objects"
                )
            x = coord.get("x")
            y = coord.get("y")
            if not isinstance(x, int) or isinstance(x, bool):
                raise ValidationError("fleet field constraint region starbaseCoords x must be int")
            if not isinstance(y, int) or isinstance(y, bool):
                raise ValidationError("fleet field constraint region starbaseCoords y must be int")
            starbase_coords.append(FleetFieldRegionStarbaseCoord(x=x, y=y))

        overlay_id = data.get("overlayId")
        if overlay_id is not None and not isinstance(overlay_id, str):
            raise ValidationError("fleet field constraint region overlayId must be a string")

        if not planet_ids and not starbase_coords and overlay_id is None:
            raise ValidationError("fleet field constraint region requires at least one locator")

        return FleetFieldRegion(
            planet_ids=tuple(planet_ids),
            starbase_coords=tuple(starbase_coords),
            overlay_id=overlay_id,
        )
    raise ValidationError(f"unknown fleet field constraint kind: {kind!r}")


def fleet_build_option_set_to_json(option_set: FleetBuildOptionSet) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "label": option_set.label,
        "solutionRankWeight": option_set.solution_rank_weight,
        "beamCount": option_set.beam_count,
        "launcherCount": option_set.launcher_count,
    }
    if option_set.combo_id is not None:
        payload["comboId"] = option_set.combo_id
    if option_set.hull_id is not None:
        payload["hullId"] = option_set.hull_id
    if option_set.engine_id is not None:
        payload["engineId"] = option_set.engine_id
    if option_set.beam_id is not None:
        payload["beamId"] = option_set.beam_id
    if option_set.torp_id is not None:
        payload["torpId"] = option_set.torp_id
    return payload


def _resolved_fleet_component_id(component_id: int) -> int | None:
    """Map non-positive solver component ids to unknown on fleet option sets."""
    return component_id if component_id > 0 else None


def _resolved_fleet_hull_id(hull_id: int) -> int | None:
    """Preserve generic freighter sentinel; map other non-positive ids to unknown.

    ``GENERIC_FREIGHTER_SENTINEL_HULL_ID`` (0) is a documented fleet/solver
    pseudo-id meaning "some freighter hull" -- not a host catalog id. It must
    survive on fleet option sets so observation match can recognize generic
    freighter inference without relying on the display ``label``.
    """
    from api.concepts.hulls import GENERIC_FREIGHTER_SENTINEL_HULL_ID

    if hull_id == GENERIC_FREIGHTER_SENTINEL_HULL_ID:
        return GENERIC_FREIGHTER_SENTINEL_HULL_ID
    return hull_id if hull_id > 0 else None


def fleet_build_option_set_from_inference_ship_build(
    ship_build: object,
    *,
    solution_rank_weight: int,
) -> FleetBuildOptionSet:
    """Map one inference solution ship build into a fleet build option set."""
    from api.analytics.military_score_inference.models import InferenceSolutionShipBuild

    if not isinstance(ship_build, InferenceSolutionShipBuild):
        raise TypeError(
            f"ship_build must be InferenceSolutionShipBuild, got {type(ship_build).__name__}",
        )
    combo_id = ship_build.combo_id or None
    return FleetBuildOptionSet(
        combo_id=combo_id,
        label=ship_build.label,
        solution_rank_weight=solution_rank_weight,
        hull_id=_resolved_fleet_hull_id(ship_build.hull_id),
        engine_id=_resolved_fleet_component_id(ship_build.engine_id),
        beam_id=_resolved_fleet_component_id(ship_build.beam_id)
        if ship_build.beam_id is not None
        else None,
        torp_id=_resolved_fleet_component_id(ship_build.torp_id)
        if ship_build.torp_id is not None
        else None,
        beam_count=ship_build.beam_count,
        launcher_count=ship_build.launcher_count,
    )


def fleet_build_option_set_from_json(data: dict[str, Any]) -> FleetBuildOptionSet:
    combo_id = data.get("comboId")
    if combo_id is not None and not isinstance(combo_id, str):
        raise ValidationError("fleet build option set comboId must be a string")

    label = data.get("label", "")
    if not isinstance(label, str):
        raise ValidationError("fleet build option set label must be a string")

    solution_rank_weight = data.get("solutionRankWeight", 0)
    if not isinstance(solution_rank_weight, int) or isinstance(solution_rank_weight, bool):
        raise ValidationError("fleet build option set solutionRankWeight must be an int")

    beam_count = data.get("beamCount")
    if beam_count is not None and (not isinstance(beam_count, int) or isinstance(beam_count, bool)):
        raise ValidationError("fleet build option set beamCount must be an int or null")

    launcher_count = data.get("launcherCount")
    if launcher_count is not None and (
        not isinstance(launcher_count, int) or isinstance(launcher_count, bool)
    ):
        raise ValidationError("fleet build option set launcherCount must be an int or null")

    hull_id = data.get("hullId")
    if hull_id is not None and (not isinstance(hull_id, int) or isinstance(hull_id, bool)):
        raise ValidationError("fleet build option set hullId must be an int")

    engine_id = data.get("engineId")
    if engine_id is not None and (not isinstance(engine_id, int) or isinstance(engine_id, bool)):
        raise ValidationError("fleet build option set engineId must be an int")

    beam_id = data.get("beamId")
    if beam_id is not None and (not isinstance(beam_id, int) or isinstance(beam_id, bool)):
        raise ValidationError("fleet build option set beamId must be an int")

    torp_id = data.get("torpId")
    if torp_id is not None and (not isinstance(torp_id, int) or isinstance(torp_id, bool)):
        raise ValidationError("fleet build option set torpId must be an int")

    return FleetBuildOptionSet(
        combo_id=combo_id,
        label=label,
        solution_rank_weight=solution_rank_weight,
        hull_id=hull_id,
        engine_id=engine_id,
        beam_id=beam_id,
        torp_id=torp_id,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def fleet_last_seen_to_json(last_seen: FleetLastSeen) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "turn": last_seen.turn,
        "x": last_seen.x,
        "y": last_seen.y,
    }
    if last_seen.planet_id is not None:
        payload["planetId"] = last_seen.planet_id
    return payload


def fleet_last_seen_from_json(data: dict[str, Any]) -> FleetLastSeen:
    turn = data.get("turn")
    x = data.get("x")
    y = data.get("y")
    if not isinstance(turn, int) or isinstance(turn, bool):
        raise ValidationError("fleet last seen turn must be an int")
    if not isinstance(x, int) or isinstance(x, bool):
        raise ValidationError("fleet last seen x must be an int")
    if not isinstance(y, int) or isinstance(y, bool):
        raise ValidationError("fleet last seen y must be an int")
    planet_id = data.get("planetId")
    if planet_id is not None and (not isinstance(planet_id, int) or isinstance(planet_id, bool)):
        raise ValidationError("fleet last seen planetId must be an int")
    return FleetLastSeen(turn=turn, x=x, y=y, planet_id=planet_id)


def fleet_row_qualifiers_to_json(qualifiers: FleetRowQualifiers) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if qualifiers.possibly_lost is not None:
        payload["possiblyLost"] = {
            "sinceTurn": qualifiers.possibly_lost.since_turn,
            "source": qualifiers.possibly_lost.source,
        }
    if qualifiers.alibi is not None:
        payload["alibi"] = {
            "afterTurn": qualifiers.alibi.after_turn,
            "sightingTurn": qualifiers.alibi.sighting_turn,
            "source": qualifiers.alibi.source,
        }
    return payload


def fleet_row_qualifiers_from_json(data: dict[str, Any]) -> FleetRowQualifiers:
    possibly_lost_raw = data.get("possiblyLost")
    possibly_lost: FleetPossiblyLost | None = None
    if possibly_lost_raw is not None:
        if not isinstance(possibly_lost_raw, dict):
            raise ValidationError("fleet qualifiers possiblyLost must be an object")
        since_turn = possibly_lost_raw.get("sinceTurn")
        if not isinstance(since_turn, int) or isinstance(since_turn, bool):
            raise ValidationError("fleet qualifiers possiblyLost sinceTurn must be an int")
        source = possibly_lost_raw.get("source", "")
        if not isinstance(source, str):
            raise ValidationError("fleet qualifiers possiblyLost source must be a string")
        possibly_lost = FleetPossiblyLost(since_turn=since_turn, source=source)

    alibi_raw = data.get("alibi")
    alibi: FleetAlibi | None = None
    if alibi_raw is not None:
        if not isinstance(alibi_raw, dict):
            raise ValidationError("fleet qualifiers alibi must be an object")
        after_turn = alibi_raw.get("afterTurn")
        sighting_turn = alibi_raw.get("sightingTurn")
        if not isinstance(after_turn, int) or isinstance(after_turn, bool):
            raise ValidationError("fleet qualifiers alibi afterTurn must be an int")
        if not isinstance(sighting_turn, int) or isinstance(sighting_turn, bool):
            raise ValidationError("fleet qualifiers alibi sightingTurn must be an int")
        source = alibi_raw.get("source", "")
        if not isinstance(source, str):
            raise ValidationError("fleet qualifiers alibi source must be a string")
        alibi = FleetAlibi(
            after_turn=after_turn,
            sighting_turn=sighting_turn,
            source=source,
        )

    return FleetRowQualifiers(possibly_lost=possibly_lost, alibi=alibi)


def fleet_evidence_event_to_json(event: FleetEvidenceEvent) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "eventId": event.event_id,
        "kind": event.kind,
        "turn": event.turn,
        "source": event.source,
    }
    if event.payload:
        payload["payload"] = event.payload
    return payload


def fleet_evidence_event_from_json(data: dict[str, Any]) -> FleetEvidenceEvent:
    event_id = data.get("eventId")
    kind = data.get("kind")
    turn = data.get("turn")
    source = data.get("source")
    if not isinstance(event_id, str):
        raise ValidationError("fleet evidence event eventId must be a string")
    if not isinstance(kind, str):
        raise ValidationError("fleet evidence event kind must be a string")
    if kind not in FLEET_EVIDENCE_EVENT_KINDS:
        raise ValidationError("fleet evidence event kind is invalid")
    if not isinstance(turn, int) or isinstance(turn, bool):
        raise ValidationError("fleet evidence event turn must be an int")
    if not isinstance(source, str):
        raise ValidationError("fleet evidence event source must be a string")
    payload = data.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValidationError("fleet evidence event payload must be an object")
    return FleetEvidenceEvent(
        event_id=event_id,
        kind=kind,
        turn=turn,
        source=source,
        payload=payload,
    )


def fleet_ship_record_fields_to_json(fields: FleetShipRecordFields) -> dict[str, Any]:
    return {
        "shipId": fleet_field_constraint_to_json(fields.ship_id),
        "hull": fleet_field_constraint_to_json(fields.hull),
        "engine": fleet_field_constraint_to_json(fields.engine),
        "beams": fleet_field_constraint_to_json(fields.beams),
        "launchers": fleet_field_constraint_to_json(fields.launchers),
        "builtTurn": fleet_field_constraint_to_json(fields.built_turn),
        "location": fleet_field_constraint_to_json(fields.location),
    }


def fleet_ship_record_fields_from_json(data: dict[str, Any]) -> FleetShipRecordFields:
    return FleetShipRecordFields(
        ship_id=_required_field_constraint(data, "shipId"),
        hull=_required_field_constraint(data, "hull"),
        engine=_required_field_constraint(data, "engine"),
        beams=_required_field_constraint(data, "beams"),
        launchers=_required_field_constraint(data, "launchers"),
        built_turn=_required_field_constraint(data, "builtTurn"),
        location=_required_field_constraint(data, "location"),
    )


def _required_field_constraint(data: dict[str, Any], key: str) -> FleetFieldConstraint:
    raw = data.get(key)
    if not isinstance(raw, dict):
        raise ValidationError(f"fleet ship record fields {key} must be an object")
    return fleet_field_constraint_from_json(raw)


def fleet_ship_record_to_json(record: FleetShipRecord) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "recordId": record.record_id,
        "disposition": record.disposition,
        "qualifiers": fleet_row_qualifiers_to_json(record.qualifiers),
        "fields": fleet_ship_record_fields_to_json(record.fields),
        "buildOptionSets": [
            fleet_build_option_set_to_json(option_set) for option_set in record.build_option_sets
        ],
        "events": [fleet_evidence_event_to_json(event) for event in record.events],
    }
    if record.display_default_option_set_index is not None:
        payload["displayDefaultOptionSetIndex"] = record.display_default_option_set_index
    if record.last_seen is not None:
        payload["lastSeen"] = fleet_last_seen_to_json(record.last_seen)
    return payload


def fleet_ship_record_from_json(data: dict[str, Any]) -> FleetShipRecord:
    record_id = data.get("recordId")
    disposition = data.get("disposition", "active")
    if not isinstance(record_id, str):
        raise ValidationError("fleet ship record recordId must be a string")
    if disposition not in FLEET_SHIP_DISPOSITIONS:
        raise ValidationError("fleet ship record disposition is invalid")

    qualifiers_raw = data.get("qualifiers", {})
    if not isinstance(qualifiers_raw, dict):
        raise ValidationError("fleet ship record qualifiers must be an object")

    fields_raw = data.get("fields")
    if not isinstance(fields_raw, dict):
        raise ValidationError("fleet ship record fields must be an object")

    build_option_sets = [
        fleet_build_option_set_from_json(option_set)
        for option_set in _require_object_list(
            data.get("buildOptionSets", []),
            field_name="fleet ship record buildOptionSets",
        )
    ]

    events = [
        fleet_evidence_event_from_json(event)
        for event in _require_object_list(
            data.get("events", []),
            field_name="fleet ship record events",
        )
    ]

    display_default_option_set_index = data.get("displayDefaultOptionSetIndex")
    if display_default_option_set_index is not None and (
        not isinstance(display_default_option_set_index, int)
        or isinstance(display_default_option_set_index, bool)
    ):
        raise ValidationError("fleet ship record displayDefaultOptionSetIndex must be an int")
    if display_default_option_set_index is not None:
        if not build_option_sets:
            raise ValidationError(
                "fleet ship record displayDefaultOptionSetIndex requires buildOptionSets"
            )
        if not 0 <= display_default_option_set_index < len(build_option_sets):
            raise ValidationError("fleet ship record displayDefaultOptionSetIndex is out of range")

    last_seen_raw = data.get("lastSeen")
    last_seen: FleetLastSeen | None = None
    if last_seen_raw is not None:
        if not isinstance(last_seen_raw, dict):
            raise ValidationError("fleet ship record lastSeen must be an object")
        last_seen = fleet_last_seen_from_json(last_seen_raw)

    return FleetShipRecord(
        record_id=record_id,
        disposition=disposition,
        qualifiers=fleet_row_qualifiers_from_json(qualifiers_raw),
        fields=fleet_ship_record_fields_from_json(fields_raw),
        build_option_sets=build_option_sets,
        display_default_option_set_index=display_default_option_set_index,
        last_seen=last_seen,
        events=events,
    )


def fleet_count_discrepancy_to_json(discrepancy: FleetCountDiscrepancy) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hostTurn": discrepancy.host_turn,
        "activeRowCount": discrepancy.active_row_count,
        "scoreboardImpliedCount": discrepancy.scoreboard_implied_count,
    }
    if discrepancy.report_refs:
        payload["reportRefs"] = list(discrepancy.report_refs)
    return payload


def fleet_count_discrepancy_from_json(data: dict[str, Any]) -> FleetCountDiscrepancy:
    host_turn = data.get("hostTurn")
    active_row_count = data.get("activeRowCount")
    scoreboard_implied_count = data.get("scoreboardImpliedCount")
    if not isinstance(host_turn, int) or isinstance(host_turn, bool):
        raise ValidationError("fleet count discrepancy hostTurn must be an int")
    if not isinstance(active_row_count, int) or isinstance(active_row_count, bool):
        raise ValidationError("fleet count discrepancy activeRowCount must be an int")
    if not isinstance(scoreboard_implied_count, int) or isinstance(scoreboard_implied_count, bool):
        raise ValidationError("fleet count discrepancy scoreboardImpliedCount must be an int")

    report_refs_raw = data.get("reportRefs", [])
    if not isinstance(report_refs_raw, list):
        raise ValidationError("fleet count discrepancy reportRefs must be a list")
    report_refs: list[str] = []
    for report_ref in report_refs_raw:
        if not isinstance(report_ref, str):
            raise ValidationError("fleet count discrepancy reportRefs entries must be strings")
        report_refs.append(report_ref)

    return FleetCountDiscrepancy(
        host_turn=host_turn,
        active_row_count=active_row_count,
        scoreboard_implied_count=scoreboard_implied_count,
        report_refs=tuple(report_refs),
    )


def fleet_acquisition_ledger_to_json(ledger: FleetAcquisitionLedger) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "playerId": ledger.player_id,
        "playerName": ledger.player_name,
        "records": [fleet_ship_record_to_json(record) for record in ledger.records],
    }
    if ledger.discrepancy is not None:
        payload["discrepancy"] = fleet_count_discrepancy_to_json(ledger.discrepancy)
    return payload


def fleet_acquisition_ledger_from_json(data: dict[str, Any]) -> FleetAcquisitionLedger:
    player_id = data.get("playerId")
    if not isinstance(player_id, int) or isinstance(player_id, bool):
        raise ValidationError("fleet acquisition ledger playerId must be an int")

    player_name = data.get("playerName", "")
    if not isinstance(player_name, str):
        raise ValidationError("fleet acquisition ledger playerName must be a string")

    discrepancy_raw = data.get("discrepancy")
    discrepancy: FleetCountDiscrepancy | None = None
    if discrepancy_raw is not None:
        if not isinstance(discrepancy_raw, dict):
            raise ValidationError("fleet acquisition ledger discrepancy must be an object")
        discrepancy = fleet_count_discrepancy_from_json(discrepancy_raw)

    return FleetAcquisitionLedger(
        player_id=player_id,
        player_name=player_name,
        records=[
            fleet_ship_record_from_json(record)
            for record in _require_object_list(
                data.get("records", []),
                field_name="fleet acquisition ledger records",
            )
        ],
        discrepancy=discrepancy,
    )


def _fleet_turn_snapshot_players_to_json(
    snapshot: FleetTurnSnapshot,
) -> list[dict[str, Any]]:
    return [fleet_acquisition_ledger_to_json(player_ledger) for player_ledger in snapshot.players]


def is_legacy_fleet_turn_document(data: dict[str, Any]) -> bool:
    """Return whether ``data`` uses the monolithic ``players`` array wire shape."""
    return FLEET_LEDGERS_KEY not in data and "players" in data


def fleet_materialization_provenance_from_json(
    data: dict[str, Any],
) -> FleetMaterializationProvenance:
    turn_evidence_at_n = data.get("turnEvidenceAtN", False)
    prior_ledger_at_n_minus_1 = data.get("priorLedgerAtNMinus1", False)
    if not isinstance(turn_evidence_at_n, bool):
        raise ValidationError("fleet materialization provenance turnEvidenceAtN must be a bool")
    if not isinstance(prior_ledger_at_n_minus_1, bool):
        raise ValidationError(
            "fleet materialization provenance priorLedgerAtNMinus1 must be a bool",
        )
    return FleetMaterializationProvenance(
        turn_evidence_at_n=turn_evidence_at_n,
        prior_ledger_at_n_minus_1=prior_ledger_at_n_minus_1,
    )


def fleet_materialization_provenance_to_json(
    provenance: FleetMaterializationProvenance,
) -> dict[str, bool]:
    return {
        "turnEvidenceAtN": provenance.turn_evidence_at_n,
        "priorLedgerAtNMinus1": provenance.prior_ledger_at_n_minus_1,
    }


def persisted_fleet_ledger_from_json(data: dict[str, Any]) -> PersistedFleetLedger:
    ledger_wire = data.get("ledger")
    if not isinstance(ledger_wire, dict):
        raise ValidationError("persisted fleet ledger ledger must be an object")
    provenance_wire = data.get("provenance", {})
    if not isinstance(provenance_wire, dict):
        raise ValidationError("persisted fleet ledger provenance must be an object")
    return PersistedFleetLedger(
        ledger=fleet_acquisition_ledger_from_json(ledger_wire),
        provenance=fleet_materialization_provenance_from_json(provenance_wire),
        materialization_version=fleet_materialization_version_from_json(data),
    )


def persisted_fleet_ledger_to_json(persisted: PersistedFleetLedger) -> dict[str, Any]:
    return {
        "ledger": fleet_acquisition_ledger_to_json(persisted.ledger),
        "provenance": fleet_materialization_provenance_to_json(persisted.provenance),
        "materializationVersion": persisted.materialization_version,
    }


def upgrade_legacy_fleet_turn_document(data: dict[str, Any]) -> dict[str, Any]:
    """Upgrade monolithic ``players`` wire to in-document ``ledgers/{playerId}`` keys.

    Migrated entries use default (non-final) provenance: the monolithic path never
    recorded materialization closure, so migration must not claim ensure-closed legs.
    """
    version = fleet_materialization_version_from_json(data)
    ledgers: dict[str, Any] = {}
    for player_wire in _require_object_list(
        data.get("players", []),
        field_name="fleet turn snapshot players",
    ):
        ledger = fleet_acquisition_ledger_from_json(player_wire)
        ledgers[str(ledger.player_id)] = persisted_fleet_ledger_to_json(
            PersistedFleetLedger(
                ledger=ledger,
                provenance=FleetMaterializationProvenance(),
                materialization_version=version,
            ),
        )
    return {
        "analyticId": data.get("analyticId", ANALYTIC_ID),
        "gameId": _require_int_field(data, "gameId", field_name="fleet turn snapshot"),
        "perspective": _require_int_field(data, "perspective", field_name="fleet turn snapshot"),
        "turn": _require_int_field(data, "turn", field_name="fleet turn snapshot"),
        FLEET_LEDGERS_KEY: ledgers,
    }


def _fleet_turn_snapshot_ledgers_to_json(snapshot: FleetTurnSnapshot) -> dict[str, Any]:
    ledgers: dict[str, Any] = {}
    for player_ledger in snapshot.players:
        ledgers[str(player_ledger.player_id)] = persisted_fleet_ledger_to_json(
            PersistedFleetLedger(
                ledger=player_ledger,
                provenance=FleetMaterializationProvenance(),
                materialization_version=snapshot.materialization_version,
            ),
        )
    return ledgers


def _fleet_turn_snapshot_from_ledgers_document(data: dict[str, Any]) -> FleetTurnSnapshot:
    analytic_id = data.get("analyticId", ANALYTIC_ID)
    if not isinstance(analytic_id, str):
        raise ValidationError("fleet turn snapshot analyticId must be a string")

    game_id = _require_int_field(data, "gameId", field_name="fleet turn snapshot")
    perspective = _require_int_field(data, "perspective", field_name="fleet turn snapshot")
    turn = _require_int_field(data, "turn", field_name="fleet turn snapshot")
    ledgers_wire = data.get(FLEET_LEDGERS_KEY, {})
    if not isinstance(ledgers_wire, dict):
        raise ValidationError("fleet turn snapshot ledgers must be an object")

    persisted_ledgers = [
        persisted_fleet_ledger_from_json(ledger_wire)
        for ledger_wire in ledgers_wire.values()
        if isinstance(ledger_wire, dict)
    ]
    materialization_version = 0
    if persisted_ledgers:
        materialization_version = persisted_ledgers[0].materialization_version

    return FleetTurnSnapshot(
        analytic_id=analytic_id,
        game_id=game_id,
        perspective=perspective,
        turn=turn,
        materialization_version=materialization_version,
        players=[persisted.ledger for persisted in persisted_ledgers],
    )


def fleet_turn_snapshot_to_compute_wire(snapshot: FleetTurnSnapshot) -> dict[str, Any]:
    """Turn-analytic compute response shape (analytic id + per-player ledgers)."""
    return {
        "analyticId": snapshot.analytic_id,
        "players": _fleet_turn_snapshot_players_to_json(snapshot),
    }


def fleet_materialization_version_from_json(data: dict[str, Any]) -> int:
    """Return stored materialization version, or 0 when absent (legacy / unstamped)."""
    raw = data.get("materializationVersion", 0)
    if not isinstance(raw, int) or isinstance(raw, bool):
        return 0
    return raw


def materialization_version_from_fleet_compute_result_wire(
    result_wire: object | None,
) -> int | None:
    """Read materialization version from one fleet orchestrator result wire."""
    if not isinstance(result_wire, dict):
        return None
    persisted_wire = result_wire.get("persistedLedgerWire")
    if not isinstance(persisted_wire, dict):
        return None
    if "materializationVersion" not in persisted_wire:
        return None
    return fleet_materialization_version_from_json(persisted_wire)


def is_current_fleet_materialization_version(version: int) -> bool:
    return version == FLEET_MATERIALIZATION_VERSION


def fleet_turn_snapshot_to_json(snapshot: FleetTurnSnapshot) -> dict[str, Any]:
    return {
        "analyticId": snapshot.analytic_id,
        "gameId": snapshot.game_id,
        "perspective": snapshot.perspective,
        "turn": snapshot.turn,
        FLEET_LEDGERS_KEY: _fleet_turn_snapshot_ledgers_to_json(snapshot),
    }


def fleet_turn_snapshot_from_json(data: dict[str, Any]) -> FleetTurnSnapshot:
    if is_legacy_fleet_turn_document(data):
        analytic_id = data.get("analyticId", ANALYTIC_ID)
        if not isinstance(analytic_id, str):
            raise ValidationError("fleet turn snapshot analyticId must be a string")

        game_id = _require_int_field(data, "gameId", field_name="fleet turn snapshot")
        perspective = _require_int_field(data, "perspective", field_name="fleet turn snapshot")
        turn = _require_int_field(data, "turn", field_name="fleet turn snapshot")

        return FleetTurnSnapshot(
            analytic_id=analytic_id,
            game_id=game_id,
            perspective=perspective,
            turn=turn,
            materialization_version=fleet_materialization_version_from_json(data),
            players=[
                fleet_acquisition_ledger_from_json(player_ledger)
                for player_ledger in _require_object_list(
                    data.get("players", []),
                    field_name="fleet turn snapshot players",
                )
            ],
        )

    return _fleet_turn_snapshot_from_ledgers_document(data)
