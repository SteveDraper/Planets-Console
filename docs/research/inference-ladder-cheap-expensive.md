# Current inference search tier ladder: cheap vs expensive steps and `no_exact_solution`

Research for [issue #353](https://github.com/SteveDraper/Planets-Console/issues/353). Map: [issue #352](https://github.com/SteveDraper/Planets-Console/issues/352). Related (facts only, not a redesign): [issue #244](https://github.com/SteveDraper/Planets-Console/issues/244).

**Verified:** 2026-08-20 against `assets/analytics/scores/tier_policy.yaml`, `packages/api/api/analytics/military_score_inference/`, `packages/api/api/analytics/scores/`, `packages/frontend/src/analytics/scores/`, [`docs/design-military-score-build-inference-implementation.md`](../design-military-score-build-inference-implementation.md) §8.5, [`docs/adr/0002-analytic-persistence.md`](../adr/0002-analytic-persistence.md), and [`CONTEXT.md`](../../CONTEXT.md) glossary terms.

This note describes **what the production ladder costs and emits today**. It does not propose an **inference expensive-tier abort**, a **hopeless classifier**, or new row statuses.

Glossary terms used as in `CONTEXT.md`: **inference search tier**, **inference tier policy**, **fine-grained slack action**, **tier aggregate allowlist**, **inference score band**, **inference merged top-K**, **inference explanation signature**, **Scores inference row persistence**, **compute step**, `tier_solve`.

---

## Summary for implementers

Production YAML (`assets/analytics/scores/tier_policy.yaml`) is a **10-step** **inference search tier** ladder. Steps 0--3 are **ship-build only** (empty `aggregateAllowlist`). Aggregates start at `admit_ship_torpedoes` (belief-set torp loads). **Fine-grained slack** (planet posts, then starbase posts / fighters / transfers) enters later. The last step is `full_catalog_exact` with `alpha: 0` (no **inference score band** retry).

Each SPA / orchestrator `tier_solve` **compute step** runs **one** YAML step (`run_inference_tier_job` → `run_policy_ladder_tier_step`) and returns `continue` until the ladder completes.

The ladder **stops climbing** (does not enter later YAML steps) when:

1. **Ship-only exact early-stop** fires -- only on steps with `allowShipOnlyExactEarlyStop: true` (`full_components` onward), and only if the best held exact is ship-builds-only with `objectiveValue >= -300`.
2. **No-new-signatures early-stop** fires -- catalog growth was a noop **and** no new exact **inference explanation signature** was admitted **and** the best held exact is `>= -300`.
3. **Cancel** (`InferenceCancelToken` / stream cancel) -- row status `stopped`.
4. **`invalid_problem`** from the solver -- aborts the remaining ladder.

It does **not** stop solely because **inference merged top-K** is full (K=20). **Zero-exact** rows cannot take (1) or (2), so they walk every YAML id unless cancel / invalid-problem / time-budget **skip** cuts remaining `minSeconds: 0` steps without solving them.

`no_exact_solution` is the **row-terminal** status when finalize has **no held exact** that satisfies hard equalities and the run was not cancelled / time-limited-with-empty-or-non-exact. Band residuals stay internal (`best_band_residual_2x` on diagnostics). The SPA table cell is a **red X** (`displayStatus: failure`). Solver JSON lives on the live stream / Scores diagnostics tab, not in durable **Scores inference row persistence**.

There is **no** per-step **entry** gate on held-exact plausibility today. [#244](https://github.com/SteveDraper/Planets-Console/issues/244) would replace the **post-step** ship-only boolean with optional entry thresholds. Other skip/abort hooks (collision-widen skip, prior-fleet tech-raise skip, budget skip, cancel, invalid-problem, no-new-signatures) are separate.

---

## 1. Ordered production ladder

Source of truth: [`assets/analytics/scores/tier_policy.yaml`](../../assets/analytics/scores/tier_policy.yaml) (`steps:`). Loader/validation: [`tier_policy.py`](../../packages/api/api/analytics/military_score_inference/tier_policy.py) (`InferenceTierPolicyStep`, `validate_tier_policy_steps`: later steps are strict supersets; **final step must have `alpha: 0`**; production penultimate step must be `torp_escape_tier` with `alpha > 0`). Design table: implementation doc §8.5.3.

`alpha` is **inference score band** tolerance in **2x** military-score units. Band retry runs only after an infeasible **exact** pass at that step, and only when `alpha > 0` ([`policy_ladder_tier_step.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py); `CONTEXT.md` **Inference score band**). Band hits become `band_seeds` for the **next** step; they are not merged into user-facing top-K.

`beamSlotCounts` / `launcherSlotCounts`: `none` = 0 or max slots only; `partial` = every count in `0..hull.beams` / `0..hull.launchers` ([`ship_build_combos.py`](../../packages/api/api/analytics/military_score_inference/ship_build_combos.py) `beam_count_options_for_slot_mode`). Production YAML stays `none` through `widen_hulls`, then `partial` from `admit_ship_torpedoes` onward.

`evil_empire_free_starbase_fighters` is **not** on the **tier aggregate allowlist**; it is appended when the race/settings allow ([`actions.py`](../../packages/api/api/analytics/military_score_inference/actions.py); implementation doc §8.5.2).

Torp-load members (`ship_torps_loaded_{id}`) materialize from allowlist key `ship_torps_per_type` plus **inference aggregate admission**: early torp steps admit **belief-set ∩ eligible** only (or **none** if the belief set is empty); `torp_escape_tier` and `alpha == 0` (`full_catalog_exact`) admit all eligible ([`fleet_torp_overlay.py`](../../packages/api/api/analytics/military_score_inference/fleet_torp_overlay.py) `admitted_torp_ids_for_policy_step`).

| # | Step id | Ship-build catalog | Aggregates (caps) | `alpha` | `allowShipOnlyExactEarlyStop` | Envelope (s) | Runtime character (declared) |
|---|---------|--------------------|-------------------|---------|-------------------------------|--------------|------------------------------|
| 0 | `early_game_bands` | Hulls tech 1--6, engines all, beams/launchers tech 1--5; `raiseMaxTechFromPriorFleet` on hulls/beams/launchers | none | 50 | false | max 8 | Cheap exact: early tech band, no slack, no partial slots |
| 1 | `widen_launchers` | Launchers tech 1--8 (else same as 0) | none | 50 | false | max 8 | Cheap exact: launcher widen only |
| 2 | `collision_hull_widen` | Same as 1 + runtime twin high-tech hulls when `hullCollisionTwinWiden: true` | none | 50 | false | max 5 | Cheap exact **or skip**: no catalog growth if no twin partners |
| 3 | `widen_hulls` | Hulls `all`; beams/launchers still banded (+ fleet raise) | none | 50 | false | max 8 | Cheap-to-medium exact: full hull set, still no aggregates / still `none` slots |
| 4 | `admit_ship_torpedoes` | Full components + `partial` slots | `ship_torps_per_type: 40` (belief-set types, or none if empty belief) | 30 | false | **min 3** / max 8 | First aggregates; `runDegradeAggregateProbe: true`; funded floor so time-steer cannot starve it |
| 5 | `modest_planet_defense` | Same | + `planet_defense_posts_added_total: 16` | 50 | false | **min 1** / max 5 | First **fine-grained slack** (planet posts); funded floor |
| 6 | `full_components` | Full catalog ship polish; retain prior aggregates | torps 40 + planet posts 16 | 50 | **true** | max 5 | First step that may **ship-only exact early-stop**; still modest slack caps |
| 7 | `admit_starbase_defense_posts` | Same | + SB posts 5, SB fighters 50, ship fighters 20, fighter transfers 50 | 30 | true | max 8 | Heavier aggregates (large-increment fighters + SB posts). Issue #244 names this region as historically expensive |
| 8 | `torp_escape_tier` | Same | Same caps as 7; **all eligible** torp types | 30 | true | max 8 | **Inference torp escape tier** (penultimate, `alpha > 0`) |
| 9 | `full_catalog_exact` | Same | Raised caps: planet posts 100, SB posts 100, torps 200, SB fighters 200, ship fighters 500, transfers 100 | **0** | true | max 8 | Final exact-only pass; no band retry; largest slack volume |

YAML header comment (same file): order is "ship bands first, then high-prior aggregates (belief torps, modest planet defense), then full-catalog ship polish (capped), then heavier aggregates / escape."

`maxSeeds: 5` on every production step. Global `solverThresholds` (same YAML):

- `shipOnlyExactEarlyStopMinPlausibility: -300`
- `noNewExactSignaturesEarlyStopMinPlausibility: -300`
- `nearBestObjectiveThreshold: 250` (within-tier ranking band after first maximize; not a ladder abort)

Implementation doc §8.5.3 still shows an abbreviated table (`…` after `full_components`). The **checked-in YAML is the live 10-step list**.

---

## 2. What one step costs (budget, not CP-SAT wall)

### 2.1 Per-step envelopes

[`policy_ladder_tier_budget.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_budget.py) `tier_step_allowance_seconds`:

- `reserved = sum(minSeconds of later steps)` -- production reserved mass is **4s** until `admit_ship_torpedoes` starts (mins 3+1), then **1s**, then **0**.
- `spendable = max(0, global_remaining - reserved)`
- `steered = min(spendable, maxSeconds)` (all production steps set `maxSeconds`)
- `allowance = max(minSeconds, steered)` -- `minSeconds` is an **absolute floor** (intentional overshoot).

Exhausting a step's allowance **stops that step** (`TierStopKind.TIER_TIME` → `TierStepFinishMode.BUDGET_STOP`) and **continues the ladder**. It does not by itself complete the row. Steps with `minSeconds == 0` and zero spendable **skip** (no catalog solve) ([`policy_ladder_tier_step.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py) entry `peek_stop`; implementation doc §8.5.3).

### 2.2 Soft-global wall vs "SPA has no time budget"

| Path | `time_limit_seconds` | Clock |
|------|----------------------|--------|
| Batch / corpus (`solve_with_policy_ladder`) | Default `DEFAULT_INFERENCE_TIME_LIMIT_SECONDS = 20` ([`actions.py`](../../packages/api/api/analytics/military_score_inference/actions.py)) | One `PolicyLadderState.started_at` for the whole walk |
| SPA table stream (`run_inference_tier_job`) | `stream_tier_time_limit_seconds()` -- env `MILITARY_SCORE_INFERENCE_STREAM_TIER_TIME_LIMIT_SECONDS` or the same **20** default ([`inference_row_runner.py`](../../packages/api/api/analytics/military_score_inference/inference_row_runner.py)) | Same `started_at` on the retained ladder state across `tier_solve` continuations ([`policy_ladder_state.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_state.py); docstring: multi-tier climbs do not get a fresh full limit per step) |

Product/design copy still says SPA searches are **open-ended** / "SPA time budget: none" ([`docs/design-military-score-build-inference.md`](../design-military-score-build-inference.md) streaming paragraph; implementation doc ~§4 / §8.5.4 item 1 vs §8.5.3 envelopes). **Code still passes 20s** as the soft-global steer for stream jobs unless the env override is set.

Consequence for placing later aborts: `full_catalog_exact` has `minSeconds: 0`. If earlier steps consume the 20s steer, that last step **skips** rather than solving. Funded floors on steps 4--5 still run even when remainder is gone.

### 2.3 Work inside a step that *does* run

[`run_policy_ladder_tier_step`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_step.py):

1. Optional skip: collision-twin plan empty, or prior-fleet tech-raise saturation (#227).
2. Build catalog (filters ∩ turn catalog ∩ actives; allowlist; torp admission).
3. Optional **degrade → aggregate probe** when `runDegradeAggregateProbe` and held exacts exist (production: `admit_ship_torpedoes` only). §8.5.3a: cheap rewrite, not a full-catalog retread.
4. Seed progression from prior-step **band** seeds (fix combo counts, neighborhood 0 then 1, then free search), cap `maxSeeds`.
5. **Exact** CP-SAT (`military_score_alpha=0`).
6. If no exact solutions and `alpha > 0`: **band** CP-SAT; keep up to `maxSeeds` as next-step seeds; track `best_band_residual_2x = observed_2x - explained_2x` (minimum residual seen).

Exact solutions admit into **inference merged top-K** incrementally (`make_incremental_admitter`). Band solutions do not.

---

## 3. When the ladder stops vs when it reaches `full_catalog_exact`

Walk loop: [`policy_ladder.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder.py) `solve_with_policy_ladder`; stream equivalent is one YAML step per `run_inference_tier_job` then `enqueue_continuation` until `state.ladder_complete`.

Finish-mode early-stop is applied in [`policy_ladder_tier_finish.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_finish.py) `finish_tier_step`:

| `TierStepFinishMode` | After diagnostics | Ship-only early-stop | No-new-signatures early-stop |
|----------------------|-------------------|----------------------|------------------------------|
| `DIAGNOSTICS_ONLY` | no index advance | no | no |
| `SKIP` (widen / raise skip) | advance | yes | **no** (skip must not look like a catalog noop halt; §8.5.7 / §8.5.8) |
| `COMPLETE` (happy path) | advance | yes | yes |
| `BUDGET_STOP` | advance | **no** | **no** |

### 3.1 Ship-only exact early-stop (`allowShipOnlyExactEarlyStop`)

[`policy_ladder_admission.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_admission.py) `maybe_early_stop_after_step`:

- Step flag must be **true** (production: **false** on steps 0--5, **true** from `full_components`).
- Best held solution has **no aggregate actions** and satisfies exact hard equalities (`_solution_fully_explained_by_ship_builds_only`).
- `objectiveValue >= solverThresholds.shipOnlyExactEarlyStopMinPlausibility` (**-300**).

Sets `ladder_complete`, `ladder_early_stop_reason = "ship_only_exact_early_stop"`. Checked **after** the step, not before the next (this is the mechanism #244 would replace).

A plausible ship-only exact found on `early_game_bands` **does not** stop the ladder; tests require climbing into aggregate steps ([`test_military_score_inference_tier_policy.py`](../../packages/api/tests/test_military_score_inference_tier_policy.py) `test_solve_with_policy_ladder_defers_ship_only_early_stop_past_early_bands`).

### 3.2 No-new-signatures early-stop

`maybe_no_new_exact_signatures_early_stop` (#236; implementation doc §8.5.4 item 9):

- Held exact count **unchanged** this step (and not empty).
- No new ship-build combo ids **and** no new aggregate action ids vs prior catalog.
- Best held `objectiveValue >= -300`.

Reason: `"no_new_exact_signatures"`. Below the floor the ladder **continues** so later aggregate-widening tiers still run (example in the design: empty-belief `admit_ship_torpedoes` must not cut off planet/SB defense).

**Keep separate from #244** (that issue's "Keep separate" section).

### 3.3 Cancel

Cancel token at the walk loop, `peek_stop` `TierStopKind.CANCEL`, or solver `STATUS_STOPPED` → `state.cancelled`, `ladder_complete`. Finalize: status `stopped`, `stopped_reason: cancelled` ([`policy_ladder.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder.py) `finalize_policy_ladder_result`). Stream cancel is disable-inference / scope change / recompute -- **not** client disconnect (detach). Implementation doc ~line 400--426.

### 3.4 Time

Tier allowance exhaustion: **continue** (possibly skipping later `minSeconds: 0` steps). Soft-global remainder alone does not abort a funded in-flight step. Finalize may set `time_limited` if `state.time_limited` and there is no exact held (or held rows fail hard equalities).

### 3.5 `invalid_problem`

Solver validation failure completes the ladder immediately (`_abort_tier_step_on_seed_result` / exact/band `STATUS_INVALID_PROBLEM`).

### 3.6 When `full_catalog_exact` actually solves

All of the following must hold:

- Ship-only early-stop did not fire on steps 6--8 (no qualifying ship-only exact, or none held).
- No-new-signatures did not fire on a prior COMPLETE step.
- Not cancelled / not invalid-problem.
- The step is not **budget-skipped** (`minSeconds: 0` and spendable 0).

**Zero-exact** rows cannot take ship-only or no-new-signatures stops, so they **attempt** every remaining YAML id until cancel/invalid/budget-skip. That is the row class that always pays for late slack tiers when the 20s steer still has spendable.

K-full does **not** stop the climb (`CONTEXT.md` **Inference merged top-K**; §8.5.4 item 5).

---

## 4. How `no_exact_solution` is produced, residual, persist, SPA

### 4.1 Per-solve vs row-terminal

[`solver.py`](../../packages/api/api/analytics/military_score_inference/solver.py) `solve_inference_problem` may return `STATUS_NO_EXACT_SOLUTION` for one catalog pass when:

- race is Horwasp (`reason: horwasp_unsupported`) -- **no CP-SAT**;
- no catalog entries and observation is not idle (`reason: no candidate actions…`);
- CP-SAT finds no solutions and is not time-limited / cancelled.

That per-step status is stored as `state.last_status`. The ladder **does not** treat solver `no_exact_solution` as a row abort; it continues to band retry (if `alpha > 0`) and later steps.

**Row-terminal** status is assigned only in `finalize_policy_ladder_result`:

- `stopped` if cancelled;
- else if any held solution satisfies exact hard equalities against the **final** catalog → `exact`;
- else if `time_limited` → `time_limited`;
- else if held solutions exist but none pass hard equalities → `no_exact_solution`;
- else (empty held) → `time_limited` if flagged, else `state.last_status` (typically `no_exact_solution` after an infeasible last exact pass).

Summary string for `no_exact_solution`: `"No feasible build explanation found"` ([`inference_api_payload.py`](../../packages/api/api/analytics/military_score_inference/inference_api_payload.py) `format_inference_summary`).

### 4.2 Band residual kept

- Per-step diagnostics: `bandResidual2x` ([`policy_ladder_tier_finish.py`](../../packages/api/api/analytics/military_score_inference/policy_ladder_tier_finish.py)).
- Cross-ladder: `state.best_band_residual_2x` (minimum residual from band hits), copied onto finalize diagnostics as `best_band_residual_2x`.
- Band action lists are **not** user-facing explanations (`CONTEXT.md` **Inference score band**; implementation doc §8.5.5).

### 4.3 Persist

**Documented contract** (`CONTEXT.md` **Scores inference row persistence**; [ADR 0002](../adr/0002-analytic-persistence.md) Scores section): write only terminal `complete` with status **`exact` or `no_exact_solution`**. Durable payload: status, summary, solutions, host-turn targets; **not** fat solver `diagnostics`.

**Code constants:**

- `PERSISTABLE_INFERENCE_STATUSES = {exact, no_exact_solution}` ([`export_precedence.py`](../../packages/api/api/analytics/scores/export_precedence.py)) -- used so those statuses map export `search_status` to `complete`.
- Production **write** from orchestrator persist: `persist_row_complete_for_scope` gates on `is_durable_turn_evidence_row_status`, which is the persistable pair **union** `{stopped, time_limited}` **union** `{no_prior_turn, player_not_found, invalid_problem, solver_error}`. `tier_job_outcome_to_step_result` uses the same durable set to choose orchestrator `persist` vs soft-defer ([`compute_orchestration.py`](../../packages/api/api/analytics/scores/compute_orchestration.py)). Tests persist `stopped` (`test_scores_persistence_policy_persists_stopped_terminal_row`).

Codec: [`inference_row_persistence.py`](../../packages/api/api/serialization/inference_row_persistence.py) strips `diagnostics` on write; keeps compact `tierEmissions` (step id/index, durations, held counts, `skipped`, `ladderEarlyStopReason`, budget fields -- [`tier_emission_ledger.py`](../../packages/api/api/analytics/military_score_inference/tier_emission_ledger.py)). `best_band_residual_2x` is **not** a compact ledger key; it is live/wire diagnostics only.

### 4.4 SPA mapping

Stream `complete.status` → [`inferenceRowStreamState.ts`](../../packages/frontend/src/analytics/scores/inferenceRowStreamState.ts) `displayStatusForRow`:

| Wire `status` (typical) | `displayStatus` when complete, 0 solutions |
|-------------------------|--------------------------------------------|
| `exact` (or any complete with solutions) | `success` (count badge) |
| `no_exact_solution` | `failure` |
| `time_limited` (0 solutions) | `failure` |
| `stopped` (0 solutions) | `stopped` (octagon); if N>0, `success` |
| in-flight | `pending` / dashed badge |

Table cell for non-success complete with 0 solutions and not `stopped`: **red X** (`X` icon, `text-red-400`) ([`ScoresTableView.tsx`](../../packages/frontend/src/analytics/scores/ScoresTableView.tsx)). Implementation doc §8.5.5: "Red cross / `no_exact_solution`; diagnostics include best band residual from internal retries."

Clicking the red X **can** open the **inference solution detail modal** (`canOpenInferenceDetail` is true for complete `failure`) -- it shows summary + observed constraints + `Inference no exact solution`; it does **not** render `best_band_residual_2x` as its own field ([`InferenceDetailModal.tsx`](../../packages/frontend/src/analytics/scores/InferenceDetailModal.tsx), [`inferenceStatus.ts`](../../packages/frontend/src/analytics/scores/inferenceStatus.ts)).

Solver / `policy_step_attempts` JSON: Scores **diagnostics modal** tab, filled from live table-stream row `diagnostics` ([`diagnosticsFromTable.ts`](../../packages/frontend/src/analytics/scores/diagnosticsFromTable.ts)). After persist replay, those fat diagnostics are gone.

---

## 5. Existing skip / abort hooks (facts for #244)

[#244](https://github.com/SteveDraper/Planets-Console/issues/244) asks to replace **end-of-step ship-only exact early-stop** with optional **per-step entry** thresholds (`enterUnlessAnyExactAtLeast` / `enterUnlessShipOnlyExactAtLeast`, names illustrative there). It explicitly does **not** fold `no_new_exact_signatures`.

**What exists today (no entry-plausibility gate):**

| Hook | When | Completes ladder? | File |
|------|------|-------------------|------|
| `allowShipOnlyExactEarlyStop` + `maybe_early_stop_after_step` | **After** a COMPLETE/SKIP step | yes (`ship_only_exact_early_stop`) | `policy_ladder_admission.py` |
| `maybe_no_new_exact_signatures_early_stop` | **After** COMPLETE if catalog noop | yes (`no_new_exact_signatures`) | same; **out of #244 scope** |
| `run.peek_stop()` cancel | **Before** work and between sub-solves | yes (`stopped`) | `policy_ladder_tier_budget.py` / `policy_ladder_tier_step.py` |
| `run.peek_stop()` zero tier allowance | **Before** work (`minSeconds==0` and nothing spendable) | no (BUDGET_STOP skip / advance) | same |
| `collision_widen.skipped` | Step entry after twin plan | no (SKIP; no no-new-signatures from the skip) | `policy_ladder_tier_step.py`, `collision_hull_widen.py` |
| `prior_fleet_tech_raise.skipped` | Step entry when applied fleet saturates flagged tech axes | no (SKIP) | `prior_fleet_tech_raise.py` |
| `STATUS_INVALID_PROBLEM` | During seed/exact/band | yes | `policy_ladder_tier_step.py` |
| `runDegradeAggregateProbe` | Start of `admit_ship_torpedoes` after catalog build | no (extra admits, then normal solve) | `degrade_aggregate_probe.py` |

There is **no** YAML field today that refuses **entry** because a held exact is "good enough." The ship-only boolean is evaluated on the step that just finished, so a qualifying exact on `full_components` prevents **entering** `admit_starbase_defense_posts` -- equivalent climb decision, different call site from #244's proposed next-step entry gate.

Issue #244's motivation text still uses the older step nickname `full_components_planet_defense`; production ids from that region are `full_components`, `admit_starbase_defense_posts`, `torp_escape_tier`, `full_catalog_exact`.
