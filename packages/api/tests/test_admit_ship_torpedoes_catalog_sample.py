"""Sample the turn-12 player-28 admit_ship_torpedoes catalog and stop early.

The local diagnostic row spent about 116 minutes inside that one policy step.
This test builds the catalog from the stored turn, records where combo
enumeration spends time, and aborts the enumeration if it runs long. When
construction finishes, it also runs two bounded searches: the step's effort
cap, then an open search with a short wall fuse. A hard alarm kills the
process if a search ignores that fuse.

Skipped unless PLANETS_CATALOG_SAMPLE=1 and the local game files are present.
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import replace
from pathlib import Path

import pytest
from api.analytics.fleet.serialization import persisted_fleet_ledger_from_json
from api.analytics.military_score_inference.actions import (
    build_action_catalog_from_turn,
    build_inference_problem,
)
from api.analytics.military_score_inference.analytic import build_inference_observation
from api.analytics.military_score_inference.component_eligibility import (
    turn_catalog_context_for_policy_step,
)
from api.analytics.military_score_inference.inference_path import resolve_inference_path
from api.analytics.military_score_inference.inference_stream_orchestration import (
    create_inference_stream_orchestration,
)
from api.analytics.military_score_inference.inference_stream_session import (
    InferenceRowStreamSession,
)
from api.analytics.military_score_inference.models import EffortSolveClip
from api.analytics.military_score_inference.prior_turn_fleet_torp_overlay import (
    resolution_from_fleet_records,
)
from api.analytics.military_score_inference.row_run import RowRun
from api.analytics.military_score_inference.ship_build_combos import (
    ShipBuildEnumerationSample,
    beam_count_options_for_slot_mode,
    launcher_count_options_for_slot_mode,
    ship_build_enumeration_progress,
)
from api.analytics.military_score_inference.solver import (
    ModelConstructionSample,
    _build_model,
    merge_score_equivalent_combos,
    model_construction_progress,
    solve_inference_problem,
)
from api.analytics.military_score_inference.tier_policy import resolve_tier_policies
from api.analytics.scores.compute_orchestration import run_scores_tier_solve
from api.analytics.scores.tier_row_run_registry import clear_row_runs, register_row_run
from api.serialization.turn import turn_info_from_json

_GAME_DIR = Path(__file__).resolve().parents[3] / ".data" / "games" / "686674"
_TURN_DIR = _GAME_DIR / "21" / "turns"
_PLAYER_ID = 28
_TURN_NUMBER = 12
_POLICY_STEP_INDEX = 4
_POLICY_STEP_ID = "admit_ship_torpedoes"
_ENUMERATION_SAMPLE_SECONDS = 90.0
_POST_CATALOG_SAMPLE_SECONDS = 60.0
_HARD_LIMIT_SECONDS = 200.0
_SOLVE_HARD_LIMIT_SECONDS = 90.0
_LONG_RUNG_SECONDS = 10 * 60
_PRODUCTION_MAX_EFFORT = 1.0
_OPEN_SEARCH_WALL_SECONDS = 20.0
_PRINT_INTERVAL_SECONDS = 5.0

pytestmark = pytest.mark.slow


class _SampleAbort(Exception):
    def __init__(self, report: str) -> None:
        super().__init__(report)
        self.report = report


class _HardStop(Exception):
    def __init__(self, where: str = "") -> None:
        super().__init__(where or "inference sample hard stop")


def _on_hard_stop(_signum: int, _frame: object) -> None:
    raise _HardStop()


def _load_turn(turn_number: int):
    info_path = _GAME_DIR / "info.json"
    with open(info_path) as handle:
        settings_defaults = json.load(handle).get("settings")
    with open(_TURN_DIR / f"{turn_number}.json") as handle:
        payload = json.load(handle)
    return turn_info_from_json(payload, settings_defaults=settings_defaults)


def _predicted_candidates(turn, policy_step) -> tuple[int, dict[str, int]]:
    context = turn_catalog_context_for_policy_step(turn, _PLAYER_ID, policy_step)
    engines = len(context.eligible_engine_ids)
    beams = len(context.eligible_beam_ids)
    torpedoes = len(context.eligible_torp_ids)
    total = 0
    for hull_id in context.buildable_hull_ids:
        hull = context.hulls_by_id.get(hull_id)
        if hull is None:
            continue
        for beam_count in beam_count_options_for_slot_mode(hull, policy_step.beam_slot_counts):
            beam_choices = 1 if beam_count == 0 else beams
            if beam_count != 0 and beam_choices == 0:
                continue
            for launcher_count in launcher_count_options_for_slot_mode(
                hull, policy_step.launcher_slot_counts
            ):
                torpedo_choices = 1 if launcher_count == 0 else torpedoes
                if launcher_count != 0 and torpedo_choices == 0:
                    continue
                total += engines * beam_choices * torpedo_choices
    sizes = {
        "hulls": len(context.buildable_hull_ids),
        "engines": engines,
        "beams": beams,
        "torpedoes": torpedoes,
        "candidates": total,
    }
    return total, sizes


def _bucket_report(sample: ShipBuildEnumerationSample, elapsed: float) -> str:
    accounted = (
        sample.seconds_bound
        + sample.seconds_score
        + sample.seconds_weight
        + sample.seconds_construct
    )
    rate = sample.candidates / elapsed if elapsed > 0 else 0.0

    def share(seconds: float) -> str:
        if elapsed <= 0:
            return "n/a"
        return f"{seconds:.1f}s ({100.0 * seconds / elapsed:.0f}% wall)"

    return "\n".join(
        [
            f"candidates={sample.candidates} kept={sample.kept} "
            f"skipped_bound={sample.skipped_bound} skipped_zero_score={sample.skipped_zero_score}",
            f"rate={rate:.0f} candidates/s over {elapsed:.1f}s",
            f"at hull_id={sample.hull_id} engine_id={sample.engine_id}",
            f"bound {share(sample.seconds_bound)}",
            f"score {share(sample.seconds_score)}",
            f"weight {share(sample.seconds_weight)}",
            f"construct {share(sample.seconds_construct)}",
            f"unaccounted {share(max(0.0, elapsed - accounted))}",
        ]
    )


class _EnumerationWatch:
    def __init__(self, predicted: int) -> None:
        self.predicted = predicted
        self.samples: list[tuple[float, ShipBuildEnumerationSample]] = []
        self.entered_at: float | None = None
        self.last_print = 0.0

    def __call__(self, sample: ShipBuildEnumerationSample) -> None:
        now = time.perf_counter()
        if self.entered_at is None:
            self.entered_at = now
        self.samples.append((now, sample))
        elapsed = now - self.entered_at
        if elapsed - self.last_print >= _PRINT_INTERVAL_SECONDS or sample.candidates == 0:
            print(_bucket_report(sample, elapsed), flush=True)
            self.last_print = elapsed
        if sample.candidates > 0 and elapsed >= _ENUMERATION_SAMPLE_SECONDS:
            raise _SampleAbort(self.report(elapsed))

    def report(self, elapsed: float | None = None) -> str:
        if not self.samples or self.entered_at is None:
            return "enumeration produced no progress samples"
        now, sample = self.samples[-1]
        elapsed = now - self.entered_at if elapsed is None else elapsed
        rate = sample.candidates / elapsed if elapsed > 0 else 0.0
        if rate <= 0 or self.predicted <= 0:
            estimate = "unknown"
            estimate_seconds = 0.0
        else:
            estimate_seconds = self.predicted / rate
            estimate = f"{estimate_seconds:.0f}s ({estimate_seconds / 60:.1f} min)"
        return (
            f"enumeration sample\n{_bucket_report(sample, elapsed)}\n"
            f"predicted_candidates={self.predicted} extrapolated={estimate}\n"
            f"estimate_seconds={estimate_seconds:.1f}"
        )

    @property
    def estimate_seconds(self) -> float:
        if not self.samples or self.entered_at is None:
            return 0.0
        now, sample = self.samples[-1]
        elapsed = now - self.entered_at
        if elapsed <= 0 or sample.candidates <= 0 or self.predicted <= 0:
            return 0.0
        return self.predicted / (sample.candidates / elapsed)


class _ModelWatch:
    def __init__(self) -> None:
        self.samples: list[tuple[float, ModelConstructionSample]] = []
        self.started_at = time.perf_counter()
        self.last_print = 0.0

    def __call__(self, sample: ModelConstructionSample) -> None:
        now = time.perf_counter()
        self.samples.append((now, sample))
        elapsed = now - self.started_at
        if elapsed - self.last_print >= _PRINT_INTERVAL_SECONDS or sample.index == 0:
            print(
                f"model phase={sample.phase} index={sample.index} total={sample.total} "
                f"elapsed={elapsed:.1f}s",
                flush=True,
            )
            self.last_print = elapsed
        if elapsed >= _POST_CATALOG_SAMPLE_SECONDS and sample.phase != "done":
            raise _SampleAbort(self.report())

    def report(self) -> str:
        if not self.samples:
            return "model construction produced no progress samples"
        now, sample = self.samples[-1]
        elapsed = now - self.started_at
        return (
            f"model sample phase={sample.phase} index={sample.index}/{sample.total} "
            f"elapsed={elapsed:.1f}s"
        )


def _model_estimate_seconds(watch: _ModelWatch) -> float:
    """Extrapolate combo-var creation. Other phases have no inner rate."""
    combo_samples = [
        item for item in watch.samples if item[1].phase == "combo_vars" and item[1].index > 0
    ]
    if not combo_samples:
        return 0.0
    now, sample = combo_samples[-1]
    elapsed = now - watch.started_at
    if elapsed <= 0 or sample.total <= 0:
        return 0.0
    return sample.total / (sample.index / elapsed)


def _run_bounded_solve(problem, clip: EffortSolveClip, *, label: str):
    print(
        f"solve {label} start effort={clip.max_deterministic_time} "
        f"wall_fuse={clip.hang_fuse_remaining}",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_inference_problem(replace(problem, solve_clip=clip))
    elapsed = time.perf_counter() - started
    diagnostics = result.diagnostics
    print(
        f"solve {label} elapsed={elapsed:.1f}s status={result.status} "
        f"solveWall={diagnostics.get('solveWallSeconds')} "
        f"dtime={diagnostics.get('deterministicTime')} "
        f"stopped={diagnostics.get('stopped_reason')} "
        f"solutions={diagnostics.get('solution_count')} "
        f"structural={diagnostics.get('structural_hit_count')}",
        flush=True,
    )
    return elapsed, result


def test_turn12_player28_admit_ship_torpedoes_construction_is_the_long_rung() -> None:
    if os.environ.get("PLANETS_CATALOG_SAMPLE") != "1":
        pytest.skip("set PLANETS_CATALOG_SAMPLE=1 to sample this catalog")
    turn_path = _TURN_DIR / f"{_TURN_NUMBER}.json"
    prior_path = _TURN_DIR / f"{_TURN_NUMBER - 1}.json"
    if not turn_path.is_file() or not prior_path.is_file():
        pytest.skip(f"local game turns are not at {turn_path}")

    prior_turn = _load_turn(_TURN_NUMBER - 1)
    turn = _load_turn(_TURN_NUMBER)
    score = next(row for row in turn.scores if row.ownerid == _PLAYER_ID)

    def load_scoreboard_turn(turn_number: int):
        if turn_number == prior_turn.settings.turn:
            return prior_turn
        return None

    observation = build_inference_observation(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    policy_step = resolve_tier_policies()[_POLICY_STEP_INDEX]
    assert policy_step.id == _POLICY_STEP_ID
    predicted, sizes = _predicted_candidates(turn, policy_step)
    print(
        f"player={_PLAYER_ID} turn={observation.turn} policy={policy_step.id} "
        f"slots=beam:{policy_step.beam_slot_counts}/launcher:{policy_step.launcher_slot_counts} "
        f"sizes={sizes}",
        flush=True,
    )

    enumeration = _EnumerationWatch(predicted)
    previous_handler = signal.signal(signal.SIGALRM, _on_hard_stop)
    signal.setitimer(signal.ITIMER_REAL, _HARD_LIMIT_SECONDS)
    enumeration_token = ship_build_enumeration_progress.set(enumeration)
    catalog_started = time.perf_counter()
    stage = "catalog"
    try:
        try:
            catalog = build_action_catalog_from_turn(
                observation,
                turn,
                policy_step=policy_step,
                policy_step_index=_POLICY_STEP_INDEX,
            )
        except _SampleAbort as aborted:
            print(aborted.report, flush=True)
            assert enumeration.estimate_seconds >= _LONG_RUNG_SECONDS, aborted.report
            return
        catalog_seconds = time.perf_counter() - catalog_started
        print(
            f"catalog finished in {catalog_seconds:.1f}s "
            f"combos={len(catalog.ship_build_combos)} "
            f"aggregates={len(catalog.aggregate_actions)}",
            flush=True,
        )
        player = next(row for row in turn.players if row.id == _PLAYER_ID)
        problem = build_inference_problem(observation, catalog, race_id=player.raceid)
        merge_started = time.perf_counter()
        merged = merge_score_equivalent_combos(problem.ship_build_combos)
        merge_seconds = time.perf_counter() - merge_started
        print(
            f"merge finished in {merge_seconds:.1f}s merged_combos={len(merged.combos)}",
            flush=True,
        )
        model_watch = _ModelWatch()
        model_token = model_construction_progress.set(model_watch)
        model_started = time.perf_counter()
        try:
            _build_model(problem, merged)
        except _SampleAbort as aborted:
            print(aborted.report, flush=True)
            estimate = _model_estimate_seconds(model_watch)
            detail = (
                f"catalog_seconds={catalog_seconds:.1f} merge_seconds={merge_seconds:.1f}\n"
                f"{aborted.report}\nmodel_estimate_seconds={estimate:.1f}"
            )
            latest = model_watch.samples[-1][1]
            if latest.phase == "combo_vars":
                assert estimate >= _LONG_RUNG_SECONDS, detail
                return
            assert latest.phase != "done", detail
            return
        finally:
            model_construction_progress.reset(model_token)
        model_seconds = time.perf_counter() - model_started
        assert catalog_seconds < 30, enumeration.report()
        assert model_seconds < 30
        stage = "solve-production-effort"
        signal.setitimer(signal.ITIMER_REAL, _SOLVE_HARD_LIMIT_SECONDS)
        production_elapsed, production_result = _run_bounded_solve(
            problem,
            EffortSolveClip(
                max_deterministic_time=_PRODUCTION_MAX_EFFORT,
                hang_fuse_remaining=30.0,
            ),
            label="production-effort",
        )
        stage = "solve-open-search"
        signal.setitimer(signal.ITIMER_REAL, _SOLVE_HARD_LIMIT_SECONDS)
        open_elapsed, open_result = _run_bounded_solve(
            problem,
            EffortSolveClip(
                max_deterministic_time=1_000_000.0,
                hang_fuse_remaining=_OPEN_SEARCH_WALL_SECONDS,
            ),
            label="open-search",
        )
        assert production_elapsed < 45, production_result.diagnostics
        assert open_elapsed <= _OPEN_SEARCH_WALL_SECONDS + 15, open_result.diagnostics
        print(
            "construction is not the 116 minute rung: "
            f"catalog={catalog_seconds:.1f}s merge={merge_seconds:.1f}s "
            f"model={model_seconds:.1f}s "
            f"production_solve={production_elapsed:.1f}s "
            f"status={production_result.status} "
            f"open_solve={open_elapsed:.1f}s status={open_result.status}",
            flush=True,
        )
    except _HardStop:
        setup = stage if "stage" in locals() else "before catalog"
        if enumeration.entered_at is not None:
            setup = f"{setup}\n{enumeration.report()}"
        pytest.fail(f"hard stop during {setup}")
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        ship_build_enumeration_progress.reset(enumeration_token)


def _prior_fleet_resolution(prior_turn):
    ledger_path = _TURN_DIR / "11" / "analytics" / "fleet" / f"{_PLAYER_ID}.json"
    with open(ledger_path) as handle:
        persisted = persisted_fleet_ledger_from_json(json.load(handle))
    return resolution_from_fleet_records(list(persisted.ledger.records), prior_turn=prior_turn)


def test_turn12_player28_stream_rung_matches_the_long_step() -> None:
    """Replay the stream ladder through the rung that spent 6953s expanding labels.

    Held classes are ranked per ship and only the top labelings are summed, so
    this step should finish with the catalog build and the effort-capped solve,
    not a cartesian product. A hard alarm stops a regression that still walks
    the product.
    """
    if os.environ.get("PLANETS_CATALOG_SAMPLE") != "1":
        pytest.skip("set PLANETS_CATALOG_SAMPLE=1 to replay this rung")
    fleet_path = _TURN_DIR / "11" / "analytics" / "fleet" / f"{_PLAYER_ID}.json"
    if not fleet_path.is_file() or not (_TURN_DIR / "12.json").is_file():
        pytest.skip(f"local turn or fleet ledger missing at {fleet_path}")

    prior_turn = _load_turn(_TURN_NUMBER - 1)
    turn = _load_turn(_TURN_NUMBER)
    score = next(row for row in turn.scores if row.ownerid == _PLAYER_ID)

    def load_scoreboard_turn(turn_number: int):
        if turn_number == prior_turn.settings.turn:
            return prior_turn
        return None

    fleet = _prior_fleet_resolution(prior_turn)
    path, segments = resolve_inference_path(
        score,
        turn,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    session = InferenceRowStreamSession(
        player_id=_PLAYER_ID,
        observation=build_inference_observation(
            score,
            turn,
            load_scoreboard_turn=load_scoreboard_turn,
        ),
        turn=turn,
        game_id=686674,
        perspective=21,
        turn_number=turn.settings.turn,
        load_scoreboard_turn=load_scoreboard_turn,
        fleet_torp_overlay=fleet.overlay,
        fleet_torp_input_status=fleet.input_status,
        prior_fleet_max_tech_by_axis=fleet.prior_fleet_max_tech_for_admission(),
        prior_fleet_records=fleet.records,
    )
    orchestration = create_inference_stream_orchestration(
        path,
        score,
        turn,
        segments=segments,
        load_scoreboard_turn=load_scoreboard_turn,
    )
    run = RowRun(session)
    register_row_run(run, orchestration=orchestration)
    print(
        f"path={path} fleet_status={fleet.input_status} "
        f"fleet_records={len(fleet.records)} "
        f"orchestration={orchestration is not None}",
        flush=True,
    )
    from api.analytics.military_score_inference import policy_ladder_tier_step as step_module

    relabel_seconds: list[float] = []
    original_relabel = step_module.relabeled_solutions_for_widened_classes

    def timed_relabel(*args, **kwargs):
        started = time.perf_counter()
        expansions = original_relabel(*args, **kwargs)
        elapsed = time.perf_counter() - started
        relabel_seconds.append(elapsed)
        print(f"relabel wall={elapsed:.3f}s returned={len(expansions)}", flush=True)
        return expansions

    step_module.relabeled_solutions_for_widened_classes = timed_relabel
    previous_handler = signal.signal(signal.SIGALRM, _on_hard_stop)
    signal.setitimer(signal.ITIMER_REAL, _SOLVE_HARD_LIMIT_SECONDS)
    step_elapsed: dict[int, float] = {}
    try:
        state = run.ladder_state
        assert state is not None
        while state.next_step_index <= _POLICY_STEP_INDEX and not state.ladder_complete:
            step_index = state.next_step_index
            step_id = state.policy_steps[step_index].id
            print(
                f"start step {step_index} {step_id} held={len(state.merged_solutions)} "
                f"effort_spent={state.search_effort_spent:.3f} "
                f"search_wall={state.search_wall_seconds:.3f}",
                flush=True,
            )
            started = time.perf_counter()
            result = run_scores_tier_solve({"runId": run.run_id})
            elapsed = time.perf_counter() - started
            step_elapsed[step_index] = elapsed
            emission = state.step_diagnostics[-1] if state.step_diagnostics else {}
            print(
                f"done step {step_index} {step_id} wall={elapsed:.3f}s "
                f"outcome={result.outcome} durationMs={emission.get('durationMs')} "
                f"combos={emission.get('comboCount')} "
                f"held {emission.get('heldCountBefore')}->{emission.get('heldCountAfter')} "
                f"new={emission.get('newlyAdmittedCount')} status={emission.get('lastStatus')} "
                f"skipped={emission.get('skipped')}",
                flush=True,
            )
            if result.outcome != "continue":
                pytest.fail(f"ladder stopped at step {step_index} outcome={result.outcome}")
        admit_elapsed = step_elapsed[_POLICY_STEP_INDEX]
        relabel_elapsed = relabel_seconds[-1] if relabel_seconds else None
        print(
            f"admit_ship_torpedoes wall={admit_elapsed:.3f}s relabel={relabel_elapsed}",
            flush=True,
        )
        assert relabel_seconds, "admit_ship_torpedoes did not relabel held classes"
        assert relabel_seconds[-1] < 5, relabel_seconds
        assert admit_elapsed < 45, step_elapsed
    except _HardStop:
        pytest.fail(
            f"admit_ship_torpedoes still running after {_SOLVE_HARD_LIMIT_SECONDS:.0f}s "
            f"steps={step_elapsed} relabel={relabel_seconds}"
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        step_module.relabeled_solutions_for_widened_classes = original_relabel
        clear_row_runs()
