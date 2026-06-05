# Design: Inference corpus (real-turn regression)

Authoritative contract for the **inference corpus** harness (#62–#66 under epic #39). Summary and glossary: [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md) section 11.2, repo root `CONTEXT.md`.

**Related:** [design-military-score-build-inference.md](design-military-score-build-inference.md), [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md).

---

## 1. Layout and imports

| Path | Role |
|------|------|
| `packages/api/tests/inference_corpus/` | Harness package (discovery, classify, coverage, run, report) |
| `packages/api/tests/fixtures/inference_corpus/` | Committed RST slices + `manifest.json` |
| `packages/api/tests/test_inference_corpus_fixed.py` | CI entry (pytest) |
| `scripts/run_inference_corpus.py` | Local Typer runner (#63) |

**Import rule:** Harness code is imported as `from tests.inference_corpus.<module> import ...`. Pytest `pythonpath` for the API package is `.` (`packages/api`); `tests/` is a package (`tests/__init__.py` exists). Do **not** place harness modules under `api/`.

**Production APIs to call:**

- `turn_info_from_json` / `GameService` or `StorageBackend.get` for loads
- `infer_military_score_build(score, turn)` for Tier 1 (#62)
- `build_action_catalog_from_turn`, `build_inference_problem`, `solve_inference_problem` when coverage or constraint re-check needs the catalog (#64+)
- `GameService.player_id_for_perspective(info, perspective, game_id)` to resolve the case player

---

## 2. Case identity

A **inference corpus case** is identified by:

| Field | Meaning |
|-------|---------|
| `gameId` | planets.nu game id |
| `perspective` | 1-based slot `P` (storage path segment) |
| `hostTurn` | Host turn `N` whose builds are explained |
| `playerId` | `GameInfo.players[P - 1].id` unless manifest overrides |

**Turn documents:**

- `priorTurn` = `hostTurn` (`N`) -- inventory ground truth (older snapshot)
- `scoreTurn` = `hostTurn + 1` (`N+1`) -- scoreboard deltas and catalog inputs (newer snapshot)

**Inference call:** Load `TurnInfo` from `scoreTurn` at perspective `P`. Find `Score` where `score.ownerid == playerId`. Call `infer_military_score_build(score, turn)`.

**Do not** run scoreboard inference on `priorTurn` (turn 1 has `no_prior_turn`).

---

## 3. Manifest schema (fixed corpus / CI)

File: `packages/api/tests/fixtures/inference_corpus/manifest.json`

```json
{
  "version": 1,
  "gameInfoPath": "628580/info.json",
  "cases": [
    {
      "id": "628580-p1-host2",
      "gameId": 628580,
      "perspective": 1,
      "hostTurn": 2,
      "playerId": null,
      "priorTurnPath": "628580/1/turns/2.json",
      "scoreTurnPath": "628580/1/turns/3.json",
      "complexity": "minimal",
      "tier": 1,
      "expectedStatus": "exact",
      "requireTopK": false,
      "expectCoverage": false,
      "requiredPerspectives": [],
      "notes": "Seed build case; strict ground truth may be unavailable until combo catalog (#51)"
    },
    {
      "id": "628580-p1-host51",
      "gameId": 628580,
      "perspective": 1,
      "hostTurn": 51,
      "playerId": null,
      "priorTurnPath": "628580/1/turns/51.json",
      "scoreTurnPath": "628580/1/turns/52.json",
      "complexity": "minimal",
      "tier": 1,
      "expectedStatus": "exact",
      "requireTopK": false,
      "expectCoverage": true,
      "requiredPerspectives": [],
      "notes": "Catalog-covered empty ground truth; Tier 1 regression for #64"
    }
  ]
}
```

### Field reference

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Stable case id for logs |
| `gameId` | yes | Must match paths |
| `perspective` | yes | 1-based storage slot |
| `hostTurn` | yes | `N`; `scoreTurn` is `hostTurn + 1` |
| `playerId` | no | Default: slot owner from `gameInfoPath` |
| `priorTurnPath` | yes | Relative to `fixtures/inference_corpus/` |
| `scoreTurnPath` | yes | Relative to `fixtures/inference_corpus/` |
| `gameInfoPath` | no | Once per manifest; used to resolve `playerId` |
| `complexity` | no | Expected label for checks (`minimal` .. `adjunct`) |
| `tier` | no | `1` or `2`; default `1` |
| `expectedStatus` | no | Default `exact` for Tier 1; see section 7 |
| `requireTopK` | no | Default `false`; if `true`, ranking miss is hard fail (#65) |
| `expectCoverage` | no | If `true`, CI hard-fails unless `groundTruthAvailable` and catalog coverage pass (#64) |
| `requiredPerspectives` | no | Other slots required for multi-view (#66) |
| `notes` | no | Human context |

Paths are **rst-shaped JSON** (same object `turn_info_from_json` accepts), not storage breakpoint wrappers.

---

## 4. Fixture authoring

### 4.1 Recommended seed game

Use **game `628580`** for the first CI slice (already referenced in `game_info_sample.json` and local `.data`).

Example host-turn pair for discovery smoke tests: **perspective `1`, hostTurn `2`** (files `turns/2.json` + `turns/3.json` under `.data/games/628580/1/`).

### 4.2 Refresh procedure (from local store)

1. Load-all or ensure turns exist under `.data/games/{gameId}/{perspective}/turns/{N}.json`.
2. Copy rst JSON to `packages/api/tests/fixtures/inference_corpus/{gameId}/{perspective}/turns/`.
3. Trim large arrays (section 4.3) so each turn file stays under ~200 KB if possible.
4. Copy or subset `games/{gameId}/info.json` to `fixtures/inference_corpus/{gameId}/info.json`.
5. Run `infer_military_score_build` locally on the trimmed `scoreTurn`; adjust manifest `expectedStatus` / pick another turn if not `exact`.
6. Add or update `manifest.json` row; run `make test_api`.

Optional helper (implement in #62 or ad hoc):

```bash
cd packages/api
PYTHONPATH=. uv run python -c "
from pathlib import Path
import json, shutil
src = Path('../../.data/games/628580/1/turns')
dst = Path('tests/fixtures/inference_corpus/628580/1/turns')
dst.mkdir(parents=True, exist_ok=True)
for n in (2, 3):
    shutil.copy2(src / f'{n}.json', dst / f'{n}.json')
print('copied; trim before commit')
"
```

### 4.3 Trim guidelines (v1)

Full turn dumps (~800 KB+) are too large for git. Trim **in place** keeping deserialization valid:

**Always keep:** `settings`, `game`, `player`, `players`, `races`, `scores`, `hulls`, `engines`, `beams`, `torpedos`, `ships` (see below), `planets` (only ids/owner/defense/fighters needed for defense deltas), `starbases` if present in payload.

**Ships:** For Tier 1-only fixtures, keeping **all** `ships` is acceptable if under size budget. For smaller files, keep ships where `ownerid == case playerId` plus any hull that appears on a **new** ship id in `scoreTurn` vs `priorTurn` (for ground truth in #64).

**May drop:** `messages`, `events`, large history arrays, `mines`, `fights`, `chartags`, and other fields not read by `turn_info_from_json` for inference (verify with `turn_info_from_json` after trim).

After trim, run `turn_info_from_json` and one `infer_military_score_build` call in a one-off test or REPL.

---

## 5. Local discovery (#63)

Enumerate without a manifest:

1. `StoreService.read_shallow("games")` -- child game ids, or take `--game-id`.
2. For each perspective directory under `games/{id}/` (numeric child names `1`..`11`, skip non-numeric):
   - `read_shallow(f"games/{id}/{p}/turns")` -- turn numbers present.
3. For each consecutive pair `(N, N+1)` in sorted turns, emit a case with `hostTurn=N`, `perspective=p`.

Use `FileStorageBackend` with `ApiConfig(storage_backend="file", storage_root=...)`. Default storage root: load via `api.config.load_config()` (typically repo `.data`).

```bash
# From repo root (requires game turns under .data/games/{id}/)
make inference_corpus GAME_ID=628580

# Or directly:
uv run python scripts/run_inference_corpus.py --game-id 628580

# List discovered cases with ground-truth build summaries (no solver):
uv run python scripts/run_inference_corpus.py discover --game-id 628580 --from-turn 2 --to-turn 10

# Scan every stored game, cap at routine complexity, JSON output:
PYTHONPATH=packages/api uv run python scripts/run_inference_corpus.py \
  --max-complexity routine --json
```

**Finished game:** Script does not require load-all completeness; sparse pairs are valid. Optionally warn if `games/{id}/info.json` missing.

---

## 6. Complexity classification

### 6.1 Levels (ordinal)

| Level | Name | `maxComplexity` cap includes |
|-------|------|------------------------------|
| 0 | `minimal` | yes |
| 1 | `routine` | yes |
| 2 | `heavy` | yes |
| 3 | `adjunct` | only with `--include-adjunct` (future) |

CLI `--max-complexity` accepts names `minimal`, `routine`, `heavy`, `adjunct` or integers `0`–`3`. Skip when `case.level > cap`.

### 6.2 Signals (evaluate in order; highest wins)

Apply to inventory delta for **case `playerId`** between `priorTurn` and `scoreTurn`, using case perspective ships/planets/starbases first, then **multi-perspective merge** (section 8) for adjunct.

**`adjunct` (3)** if any:

- Net **ship count decrease** for owner (ships with `turnkilled` in window or id present at N gone at N+1 without matching build compensation)
- **Starbase or planet count decrease** for owner
- **Trade / capture hint:** hull appears under `playerId` at N+1 with id not in N snapshot, and same `hullid`+similar location existed under **another** `ownerid` at N in a merged perspective
- Scoreboard `militarychange` magnitude exceeds explained build/load delta by more than **500** points (unmodeled loss/combat) after naive build tally

**`heavy` (2)** if not adjunct and any:

- **>= 3** new owned ships (ids in N+1 not in N, `turnkilled == 0`)
- Or sum of new ship construction military value (rough hull MC from `ships` / hull table) implied **> 2000** MC
- Or **>= 51** total aggregate load units (fighters on ships + starbase fighters + defense posts) inferred from score deltas or inventory

**`routine` (1)** if not heavy/adjunct and any:

- **2** new owned ships, or
- **11–50** aggregate load units, or
- **>= 2** distinct aggregate action families (fighters + torps + defense, etc.)

**`minimal` (0):** otherwise (typically <=1 new ship, small loads, no losses).

Document computed `complexity` and `complexityReasons: string[]` on each case result.

### 6.3 Default skips

- `complexity == adjunct` and not `--include-adjunct` -> `skipped_complexity` (reason `adjunct_disabled`)
- Above `--max-complexity` -> `skipped_complexity`

---

## 7. Tier 1 assertions (#62)

For each case (after skips/coverage):

1. Call `infer_military_score_build`.
2. **Status:** Compare to `expectedStatus` (default `exact`). Allowed manifest values: `exact`, `no_exact_solution`, `time_limited`, `invalid_problem`, `solver_error`, `no_prior_turn`.
3. When status is `exact` and `expectedStatus` is `exact`:
   - `solutionCount >= 1`
   - **Constraint re-check** on **top solution** (index 0): rebuild sums from catalog `CandidateAction` entries matching each `actionId` in the serialized solution:

```text
sum(score_delta_2x * count) == observation.military_delta_2x
sum(warship_delta * count) == observation.warship_delta
sum(freighter_delta * count) == observation.freighter_delta
```

   Use `build_inference_observation(score, turn)` for observation. Do **not** assert priority-point equality (diagnostic-only per #50 / design).

4. For `heavy` cases only: allow `time_limited` if `solutionCount >= 1` and constraint re-check passes on top solution.

Implement constraint re-check in `tests/inference_corpus/verify.py` using the same catalog instance built for the run.

---

## 8. Multi-perspective ground truth (#63, #66)

When classifying **adjunct** or running **Tier 2**, merge snapshots for host turn pair `(N, N+1)`:

- Start with perspective `P` ships (and planets/starbases for defense).
- For each other perspective `Q` with both turns stored, append ships/planets visible at N and N+1.

If a trade hypothesis needs slot `Q` and `Q` is missing, set `incomplete_multi_view: true` and **do not** promote to `adjunct` on trade alone.

`requiredPerspectives` in manifest: CI fails fast if listed paths are absent in fixed fixtures.

---

## 9. Ground truth explanation v1 (#64)

### 9.1 Multiset format

```python
# sorted tuple for hashing/compare
GroundTruth = tuple[tuple[str, int], ...]  # (action_id, count) ascending by action_id
```

### 9.2 Extraction scope (v1)

Extract only when **adjunct** is false and complexity <= `heavy`. Otherwise set `groundTruthAvailable: false` and skip coverage/ranking/Tier 2.

**Turn-pair residual scope:** Ground truth is built from inventory deltas between the manifest's `priorTurnPath` and `scoreTurnPath` snapshots (host turn pair). Residual validation compares the explained multiset to **`2 * score.militarychange`** on the score row -- not `build_inference_observation(...).military_delta_2x`. On the first reliable accelerated-start scoreboard row, inference observation is cumulative since homeworld baseline (`observation_deltas_from_score`), while `militarychange` on that row is still the delta for host turn N-1 only. Comparing turn-pair GT to cumulative observation falsely marks explainable cases as `residual_unexplained` (e.g. `628580-p1-host2`). Accelerated-window activity before host turn N-1 is out of scope for turn-pair GT unless extraction is extended to include it explicitly.

**Ship builds (combo catalog, #51+):**

- New ship ids at N+1 not at N, `ownerid == playerId`, `turnkilled == 0`.
- Map each to a factored combo id via `ship_build_combo_id` from fitted hull/engine/beam/torp/count fields.
- If any new ship cannot be mapped, set `groundTruthAvailable: false`.

**Ammo on newly built ships:** do not attribute fighters or torpedoes loaded onto **new** ships to aggregate load actions. Turn snapshots reflect post-order ship state while scoreboard military deltas reflect pre-order totals; client-side build/transfer actions create a systematic mismatch. Loads on **existing** ships still use inventory deltas (with new-ship ids excluded).

**Aggregate loads (score-derived v1):**

When ship builds alone do not explain `militarychange`, allocate residual scaled delta to aggregate action ids in priority order (first fit):

| Action id | When |
|-----------|------|
| `ship_fighters_added_total` | Positive fighter load delta on **existing** ships (new-ship ids excluded) |
| `ship_torps_loaded_{torpedoId}` | Torp load delta on **existing** ships (new-ship ids excluded) |
| `starbase_fighters_added_total` | Starbase fighter remainder |
| `starbase_defense_posts_added_total` | Starbase defense remainder |
| `planet_defense_posts_added_total` | Planet defense remainder |
| `fighters_starbase_to_ship` / `fighters_ship_to_starbase` | Only when inventory shows starbase vs ship fighter counts support transfer |

If residual cannot be assigned without deferred effects, set `groundTruthAvailable: false`.

**Follow-on:** edge cases from other client-side actions (starbase torp builds, transfers) that appear in turn snapshots but not scoreboard deltas -- see tracker issue.

### 9.3 Catalog coverage (v1)

When `groundTruthAvailable: true`, for each `(action_id, count)` in ground truth, check against `build_action_catalog_from_turn(observation, scoreTurn)` at escalating `ship_build_tier` values (0 through max), matching solver tier progression. Ship-build combos such as Missouri may only appear at higher tiers.

When `groundTruthAvailable: true`, for each `(action_id, count)` in ground truth:

- Catalog contains `action_id`
- `count <= action.upper_bound` and `count >= action.lower_bound`

If any fail -> outcome `out_of_search_space`, `coverageReason` from section 9.4, **do not** call solver.

If `groundTruthAvailable: false` -> skip coverage and ranking; still run Tier 1.

Manifest `expectCoverage` is a **CI assertion** only: when `true`, the case must have `groundTruthAvailable: true` and pass catalog coverage (otherwise outcome `failed`, exit code 1). It does **not** gate whether coverage is evaluated; that follows `groundTruthAvailable` only.

### 9.4 `coverageReason` enum (stable strings)

| Reason | Meaning |
|--------|---------|
| `deferred_trade` | Trade/capture implied, not in catalog |
| `deferred_ship_loss` | Ship loss/combat not modeled |
| `deferred_starbase_loss` | Base loss not modeled |
| `deferred_planet_loss` | Planet loss not modeled |
| `deferred_minefield` | Mine/scoop not modeled |
| `combo_not_in_catalog` | Ship build combo not generated (tier too narrow) |
| `action_not_in_catalog` | Unknown action id |
| `count_above_upper_bound` | GT count exceeds catalog cap |
| `ground_truth_unavailable` | Extractor could not build multiset |
| `residual_unexplained` | Military delta not allocatable to v1 actions |

---

## 10. Top-K ranking check (#65)

When `groundTruthAvailable` and catalog coverage passed and Tier 1 status is `exact`:

1. Normalize solver solutions to `GroundTruth` from payload `solutions[i].actions` (`actionId`, `count`; ignore zero counts).
2. Compare to ground truth multiset (order-insensitive).
3. If not found in first `K` solutions (default `K=3`, `--top-k`): emit `ranking_miss`.
4. **Soft** unless manifest `requireTopK: true` or `--fail-on-ranking-miss`.

**Complexity:** soft for `minimal` and `routine`; manifest may harden for `heavy` later.

---

## 11. Tier 2 compatibility (#65)

When `--tier 2` or manifest `tier: 2`:

- Recompute inventory delta rules from section 9.2 without collapsing to aggregates where ship-level detail exists.
- **Pass:** every GT ship build and aggregate count is **compatible** with visible inventory (no requirement that GT equals top solver solution).
- **Fail:** GT implies ships or loads that contradict merged inventory.

Skip Tier 2 when `groundTruthAvailable: false`.

---

## 12. Report and exit codes

### 12.1 Per-case outcomes

`passed` | `failed` | `skipped_complexity` | `skipped_incomplete_multi_view` | `out_of_search_space` | `ranking_miss`

`ranking_miss` does not set exit code 1 unless hard mode (section 10).

### 12.2 Script exit code

- `0` -- no `failed` cases
- `1` -- one or more `failed`

Print summary counts and optional `--json` array of per-case records (`caseId`, `outcome`, `status`, `complexity`, `coverageReason`, ...).

---

## 13. Issue map

| Issue | Spec sections |
|-------|----------------|
| #62 | 1–4, 7, 12; manifest example |
| #63 | 5–6, 8, 12 |
| #64 | 8–9 |
| #65 | 10–11, 12 |
| #66 | 4, 8, manifest `requiredPerspectives` |

**Solver epic ordering:** #62 parallel #50; refresh fixtures after #51/#52; #66 with #49 when trades modeled. UI per-row NDJSON streaming (#71) does not change corpus Tier 1 -- harness keeps calling batch `infer_military_score_build` until stream parity is proven.

---

## 14. Open evolution

- Hybrid CP-SAT coverage probe when mapping says covered but solver returns `no_exact_solution` (section 11.2 parent doc).
- `--include-adjunct` to run adjunct cases instead of skipping.
- Combo-aware ground truth after #51 lands.
