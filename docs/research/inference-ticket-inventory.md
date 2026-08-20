# Open military score build inference ticket inventory

Research for [issue #355](https://github.com/SteveDraper/Planets-Console/issues/355). Map: [issue #352](https://github.com/SteveDraper/Planets-Console/issues/352) (*Military score build inference: next quality bar*). Parent epic: [issue #39](https://github.com/SteveDraper/Planets-Console/issues/39).

**Verified:** 2026-08-20 against GitHub (`gh issue view` / `gh issue list`) and current `main` (`d9ef0453`). This note does **not** decide ticket fates; that is [issue #361](https://github.com/SteveDraper/Planets-Console/issues/361).

## Lens (#352)

Destination (plan and tracker rewrite, not implementation): hopeless / high-slack rows must not burn expensive **inference search tiers**; **no-solution**, **inference moderate residual**, and **mine-score residual** get distinct product contracts (not only exact-or-red-X), including a count-constrained **unknown military ship** placeholder; **score-decreasing** ship loss, gift, and trade are exact-modeled this bar; remaining open inference tickets are closed, restated, or subsumed to match that plan.

Standing constraints used as the classification lens: no observed/unobserved minefield split; no unconstrained negative mine slack; cheap exact tiers always run; expensive-tier abort only after a strict **hopeless classifier**; no user-facing inexact action list for moderate residual; **unknown military ship** is the warship analogue of **generic freighter combo**; exact-model this bar is loss/gift/trade only (not mines, ammo spend, negative defense, or planet/SB loss); **inference admission skip** is separate from the hopeless classifier.

Out of scope for the map (hygiene may still restate): observed vs unobserved mines; mine decay/sweep/mutual elimination as catalog families; unconstrained negative slack; inexact action lists; fighter/torp spend, negative defense, planet/SB loss as this bar's modeling promise; fleet/MCP/orchestrator redesign except when an inference ticket is actually an orchestrator bug; [issue #89](https://github.com/SteveDraper/Planets-Console/issues/89) icons; carrying implementation on the map.

GitHub has **no** native sub-issue graph on #39 (`trackedIssues` empty). Parent / blocked-by below are from issue bodies and comments, not GitHub "blocked by" edges.

## Candidate buckets (evidence only)

| Bucket | Meaning in this note |
|--------|----------------------|
| still-relevant | Ask is still unmet and still sits in the leftover #39 surface. |
| likely-restate | Ask is partly shipped or the quality bar changes the contract; wording would need a rewrite. |
| likely-subsumed-by-this-map | Ask is already a #352 child ticket or is named in the destination. |
| likely-operational-leftover | Orchestrator / stream / persistence bug, not a quality-bar product decision. |
| likely-out-of-scope-for-this-map | Named in #352 Out of scope, or ranking/UI polish the destination does not take. |

## Gist table

| # | Title | State | Candidate bucket |
|---|-------|-------|------------------|
| [39](https://github.com/SteveDraper/Planets-Console/issues/39) | Military score build inference (epic) | OPEN | likely-restate (stale checklist; map owns leftover rewrite) |
| [302](https://github.com/SteveDraper/Planets-Console/issues/302) | Do not run pointless scoreboard inference | OPEN | likely-subsumed-by-this-map (#356) |
| [49](https://github.com/SteveDraper/Planets-Console/issues/49) | Extended action families | OPEN | likely-restate (loss/gift/trade → #359; rest out of this bar) |
| [104](https://github.com/SteveDraper/Planets-Console/issues/104) | Negative defense GT + remaining client-side edges | OPEN | likely-out-of-scope-for-this-map (hygiene may restate) |
| [53](https://github.com/SteveDraper/Planets-Console/issues/53) | Combo diagnostics and solution presentation | OPEN | still-relevant leftover UI; likely-out-of-scope-for-this-map |
| [88](https://github.com/SteveDraper/Planets-Console/issues/88) | Relative plausibility and solution-list pruning | OPEN | likely-out-of-scope-for-this-map |
| [89](https://github.com/SteveDraper/Planets-Console/issues/89) | Planets.nu icons for aggregate actions | OPEN | likely-out-of-scope-for-this-map (named) |
| [156](https://github.com/SteveDraper/Planets-Console/issues/156) | Fleet-informed component tech-gap prior | OPEN | likely-out-of-scope-for-this-map (ranking leftover) |
| [66](https://github.com/SteveDraper/Planets-Console/issues/66) | Adjunct multi-perspective CI fixtures | OPEN | still-relevant corpus leftover |
| [97](https://github.com/SteveDraper/Planets-Console/issues/97) | Scores analytic exports (solution + searchStatus) | OPEN | likely-restate (#111 shipped tree; #360 will change statuses) |
| [244](https://github.com/SteveDraper/Planets-Console/issues/244) | Unify ladder early-stop into per-tier entry gates | OPEN | likely-subsumed-by-this-map or likely-restate (#352 not-yet-specified vs #357) |
| [241](https://github.com/SteveDraper/Planets-Console/issues/241) | Hydrate `PersistencePolicy.satisfied_result_wire` | OPEN | likely-operational-leftover |
| [245](https://github.com/SteveDraper/Planets-Console/issues/245) | Cancel fences grow unbounded | OPEN | likely-operational-leftover (body stale vs compact per-scope admission) |
| [216](https://github.com/SteveDraper/Planets-Console/issues/216) | Queue inference reschedule when stream detached | OPEN | likely-operational-leftover |
| [295](https://github.com/SteveDraper/Planets-Console/issues/295) | Cross-game scores CP-SAT saturates pool | OPEN | likely-out-of-scope-for-this-map (orchestrator cancel) |

Open #39 checklist rows that GitHub already closed: **#65**, **#73**, **#92**, **#200** (stale epic text, 2026-07-20 comment still listed several of these).

Map-owned open tickets (not leftovers): #352, #353, #354, #355, #356–#361. See [Map children](#map-352-children-not-leftovers).

---

## #39 leftover checklist vs GitHub

Epic body still treats these as open leftover work. GitHub state on 2026-08-20:

| Listed on #39 as open | GitHub | Notes |
|-----------------------|--------|-------|
| #53 combo diagnostics | OPEN | |
| #92 mine prior assets | **CLOSED** 2026-06-14 | Miner/schema shipped; #352 still lists prior-mining changes for *new* families as not-yet-specified |
| #156 tech-gap prior | OPEN | YAML knob commented; ranking not applied |
| #65 top-K ranking / Tier 2 | **CLOSED** 2026-06-17 | Epic Phase 1J table still says open |
| #88 relative plausibility | OPEN | |
| #89 icons | OPEN | |
| #49 extended families | OPEN | |
| #66 adjunct fixtures | OPEN | |
| #73 client-side GT edges | **CLOSED** 2026-06-17 | Follow-on is #104 |
| #200 scores orchestrator migrate | **CLOSED** 2026-08-09 | Epic still says leftover acceptance |
| #241 satisfied_result_wire | OPEN | |
| #244 per-tier entry gates | OPEN | |
| #245 cancel-fence eviction | OPEN | |

#352 says do not treat this epic's stale phase list as the route.

---

## Leftover and named tickets

### [#39](https://github.com/SteveDraper/Planets-Console/issues/39) Military score build inference

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Epic. No GitHub children. Comments: corpus plan (2026-06-03), corpus spec pointer, AI triage checklist refresh (2026-07-20).
- **Asked vs shipped:** Full pipeline epic (CP-SAT exact feasibility, ranking, Scores integration). Phase 1 / 1G / 1H / 1I vertical slice, streaming, YAML ladder, modal (#48), persist (#83), ranking primitives (#85/#86/#87) are marked done in the epic. Remaining checkboxes mix real open work with closed tickets (#65/#73/#92/#200).
- **Candidate:** likely-restate -- tracker rewrite is a #352 destination item; the phase list is not the quality-bar route.

### [#302](https://github.com/SteveDraper/Planets-Console/issues/302) Do not run pointless scoreboard inference

- **State / labels:** OPEN · none
- **Parent / blocked-by:** None in body. Named in #352 Related open ideas and in #356.
- **Asked vs shipped:** Skip viewpoint-owner and dead-player rows (wasted compute). Code path `resolve_inference_path` only short-circuits `no_prior_turn` / accelerated backfill; `get_scores_row_inference` only returns `player_not_found` when the scoreboard row is missing. No owner/dead/Stealth **inference admission skip** before inspecting the delta ([`inference_path.py`](../../packages/api/api/analytics/military_score_inference/inference_path.py), [`inference.py`](../../packages/api/api/analytics/scores/inference.py)).
- **Candidate:** likely-subsumed-by-this-map -- this is the charting seed for **inference admission skip** (#356).

### [#49](https://github.com/SteveDraper/Planets-Console/issues/49) Military score inference: extended action families

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Parent **#39**. Body blocked-by **#52** (CLOSED), **#50** (CLOSED). Comment: remains Phase 6 bucket after 1G split.
- **Asked vs shipped:** After ship-build combos, add deferred families: queue PP, mine laying/scooping, trades/captures, planet/SB losses, inventory bounds, per-location defense/fighters, fleet-histogram priors. Catalog today is additive aggregates only (`planet_defense_posts_added_total`, starbase defense, fighters, `ship_torps_loaded_*`, fighter transfers) plus ship-build combos -- no loss/gift/trade decrease actions ([`aggregate_action_registry.py`](../../packages/api/api/analytics/military_score_inference/aggregate_action_registry.py)).
- **Candidate:** likely-restate -- #352 exact-models ship loss/gift/trade this bar (#359); mines, ammo spend, negative defense, planet/SB loss stay out of this map (hygiene may restate the leftover bucket).

### [#104](https://github.com/SteveDraper/Planets-Console/issues/104) Inference corpus: negative defense GT solver support + remaining client-side action edge cases

- **State / labels:** OPEN · none
- **Parent / blocked-by:** Follow-up from **#73** (CLOSED). Named in #352 Related / Out of scope.
- **Asked vs shipped:** Allow negative defense-post catalog variables; re-enable coverage/ranking for `negative_defense_gt_pending_solver`; stop fold-to-zero mining; plus remaining client-side GT audit. #73 records negative nets in GT; miner still does `histogram_key = 0 if delta <= 0 else delta` ([`accumulation.py`](../../packages/api/api/analytics/military_score_inference/prior_mining/accumulation.py)); harness still skips those cases ([`ground_truth.py`](../../packages/api/tests/inference_corpus/ground_truth.py) `NEGATIVE_DEFENSE_GT_PENDING_SOLVER`).
- **Candidate:** likely-out-of-scope-for-this-map -- #352 will not model negative defense this bar; hygiene may restate.

### [#53](https://github.com/SteveDraper/Planets-Console/issues/53) Military score inference: combo diagnostics and solution presentation

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Parent **#39**. Blocked-by **#51** (CLOSED), **#52** (CLOSED). Modal UX is **#48** (CLOSED), not this ticket.
- **Asked vs shipped:** Diagnostics tab should show structured `shipBuildCombos`, eligible components, tier fields (`shipBuildTier`, `tiersAttempted`, `comboCount`), PP diagnostic-only notes, `accelerated_segments`. Core payload includes `shipBuildCombos` and `accelerated_segments`; stream events carry `comboCount`; Scores diagnostics tab dumps `actionCatalog` as JSON, not a dedicated combo/tier presentation ([`DiagnosticsScoresTab.tsx`](../../packages/frontend/src/components/diagnostics/DiagnosticsScoresTab.tsx)). Durable persist still strips full catalogs ([CONTEXT.md](../../CONTEXT.md) **Scores inference row persistence**).
- **Candidate:** still-relevant as leftover diagnostics polish; likely-out-of-scope-for-this-map (destination does not take SPA/diagnostics layout beyond placeholder/status contract).

### [#88](https://github.com/SteveDraper/Planets-Console/issues/88) Military score inference: relative plausibility and solution-list pruning

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Parent **#39**. Blocked-by **#48** (CLOSED).
- **Asked vs shipped:** Probability-only field (exclude parsimony/heuristics) plus SPA relative-ratio pruning. Wire still exposes mixed `objectiveValue` / **inference solution rank weight** only; no relative-plausibility field or prune threshold in frontend parsers.
- **Candidate:** likely-out-of-scope-for-this-map -- ranking/list UX, not the residual/placeholder/decrease-family bar.

### [#89](https://github.com/SteveDraper/Planets-Console/issues/89) Military score inference: Planets.nu icons for aggregate inference actions

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Parent **#39**. Blocked-by **#48** (CLOSED).
- **Asked vs shipped:** Replace Lucide fallbacks for torps/fighters/defense with Planets.nu artwork. Modal still uses `inferenceActionAggregateIcon` Lucide map; hulls still `hullImageUrl()` ([`inferenceActionFamily.ts`](../../packages/frontend/src/analytics/scores/inferenceActionFamily.ts)).
- **Candidate:** likely-out-of-scope-for-this-map -- named in #352 Out of scope.

### [#156](https://github.com/SteveDraper/Planets-Console/issues/156) Military score inference: fleet-informed component tech-gap prior

- **State / labels:** OPEN · none
- **Parent / blocked-by:** Parent **#39**. Blocked-by **#87** (CLOSED). Listed as remaining Phase 1J-B2 on the epic.
- **Asked vs shipped:** Log penalty per tech level above prior-turn fleet ceiling on ship combos. YAML still has `# componentTechGapLogPenaltyPerLevel: <int>   # #156` commented ([`tier_policy.yaml`](../../assets/analytics/scores/tier_policy.yaml)). Ceiling derivation already feeds **admission** tech raise (#227); ranking penalty itself is documented as not yet enabled ([CONTEXT.md](../../CONTEXT.md) **Inference component tech-gap prior**).
- **Candidate:** likely-out-of-scope-for-this-map -- optional ranking polish, not the quality-bar residual contract. Still an #39 leftover until hygiene.

### [#66](https://github.com/SteveDraper/Planets-Console/issues/66) Inference corpus: adjunct multi-perspective CI fixtures

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Parent **#39**. Blocked-by **#64** (CLOSED). Aligns with **#49** when trade enters the catalog.
- **Asked vs shipped:** Committed multi-perspective adjunct fixture (`requiredPerspectives`, `complexity: adjunct`); default CI skip. Manifest schema and skip-by-default exist; fixed corpus rows all have `requiredPerspectives: []` and `complexity: minimal` ([`manifest.json`](../../packages/api/tests/fixtures/inference_corpus/manifest.json)). No two-perspective adjunct fixture is committed.
- **Candidate:** still-relevant as corpus leftover (becomes essential if #359 models trade).

### [#97](https://github.com/SteveDraper/Planets-Console/issues/97) Scores / military score build inference analytic exports

- **State / labels:** OPEN · `ready-for-agent`
- **Parent / blocked-by:** Parent **#93**. Blocked-by **#95** (CLOSED). Implementation slice **#111** is CLOSED (2026-06-22).
- **Asked vs shipped:** `ctx.query("scores", …)` with `$.meta.searchStatus`, `$.solution.ships` / aggregates / diagnostics, `$.hullCatalogMask`. Shipped tree uses **`$.solutions`** (array, `shipBuilds` on each item), `$.meta.searchStatus` with the five generic lifecycle values, `$.diagnostics`, `$.hullCatalogMask` ([`export_schema.py`](../../packages/api/api/analytics/scores/export_schema.py)). Tests in `test_scores_exports.py`. Ticket AC still uses the pre-ship `$.solution.ships` path names.
- **Candidate:** likely-restate -- catalog exists; #360's new product statuses would change persist/export contracts. Not a greenfield export build.

### [#244](https://github.com/SteveDraper/Planets-Console/issues/244) Scores inference: unify ladder early-stop into optional per-tier entry gates

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** None in body. Related #226, #236. #352 **Not yet specified**: whether this is the **inference expensive-tier abort** mechanism or a parallel leftover.
- **Asked vs shipped:** Replace post-step `allowShipOnlyExactEarlyStop` with optional per-step any-exact / ship-only **entry** thresholds. YAML and parser still use `allowShipOnlyExactEarlyStop` (true from `full_components` onward) plus global `shipOnlyExactEarlyStopMinPlausibility: -300` ([`tier_policy.yaml`](../../assets/analytics/scores/tier_policy.yaml), [`tier_policy.py`](../../packages/api/api/analytics/military_score_inference/tier_policy.py)). No `enterUnlessAnyExactAtLeast` fields.
- **Candidate:** likely-subsumed-by-this-map **or** likely-restate -- same mechanism question #352 leaves open for #357. Do not treat as decided.

### [#241](https://github.com/SteveDraper/Planets-Console/issues/241) Scores: hydrate PersistencePolicy.satisfied_result_wire

- **State / labels:** OPEN · `enhancement`
- **Parent / blocked-by:** Follow-on from **#209**, epic **#190**. Related **#200** (CLOSED).
- **Asked vs shipped:** Fleet hydrates `satisfied_result_wire`; scores should too, then drop empty-complete → admission stand-in. `ScoresPersistencePolicy.satisfied_result_wire` still returns `None` with docstring "stream uses admission" ([`compute_orchestration.py`](../../packages/api/api/analytics/scores/compute_orchestration.py)).
- **Candidate:** likely-operational-leftover -- orchestrator/stream parity, not a quality-bar product status. #352 Out of scope for orchestrator redesign unless hygiene treats it as an inference bug.

### [#245](https://github.com/SteveDraper/Planets-Console/issues/245) Scores: cancel fences grow unbounded

- **State / labels:** OPEN · `bug`
- **Parent / blocked-by:** None. Listed on #39 orchestrator leftovers. Origin: DAG_optimization review.
- **Asked vs shipped:** Unbounded `_cancel_fence_run_ids` set; reject FIFO; evict only after thread-backend worker actually returns. Current registry is **compact cancelled admission keyed by scores scope** (`_cancelled_admissions` / `_cancelled_run_by_scope`), documented as O(outstanding cancel scopes), not an unbounded UUID FIFO ([`tier_row_run_registry.py`](../../packages/api/api/analytics/scores/tier_row_run_registry.py)). Ticket body still describes the old set. Proposed pool completion-tracking has not been added as specified.
- **Candidate:** likely-operational-leftover -- leftover vs rewritten fence; body is stale. Not a #352 product decision.

### [#216](https://github.com/SteveDraper/Planets-Console/issues/216) Backend: queue inference reschedule when scores stream controller detached

- **State / labels:** OPEN · `bug`, `ready-for-agent`
- **Parent / blocked-by:** Body says none. Related #212, #213–#215.
- **Asked vs shipped:** If fleet persist invalidates scores while no table stream is attached, enqueue `(scope, player_id)` and drain on next attach. `reschedule_inference_row` still returns `False` immediately when `controller_for_scope` is `None` ([`inference_table_stream_registry.py`](../../packages/api/api/analytics/military_score_inference/inference_table_stream_registry.py)).
- **Candidate:** likely-operational-leftover -- detached-controller gap, not the residual/placeholder bar.

### [#295](https://github.com/SteveDraper/Planets-Console/issues/295) Cross-game compute continues after shell change; scores CP-SAT saturates pool

- **State / labels:** OPEN · `bug`
- **Parent / blocked-by:** None. Title is scores/inference-related; not on the #39 checklist.
- **Asked vs shipped:** Leaving a heavy game must cancel or demote prior-game `stream_attached` `tier_solve`. Out of scope in the ticket: fixing CP-SAT model hardness. Matches #352 Out of scope for orchestrator redesign (hygiene only if this is treated as an inference bug).
- **Candidate:** likely-out-of-scope-for-this-map / likely-operational-leftover.

---

## Map #352 children (not leftovers)

These are the map's own research/grilling tickets. Included because titles are inference-related; they are **not** #39 leftovers to close-or-subsume except via #361 after this inventory.

| # | Title | Labels | Blocked-by (body) | Role vs leftovers |
|---|-------|--------|-------------------|-------------------|
| [352](https://github.com/SteveDraper/Planets-Console/issues/352) | Next quality bar (map) | `enhancement`, `wayfinder:map` | -- | Destination / lens |
| [353](https://github.com/SteveDraper/Planets-Console/issues/353) | Current inference ladder: cheap vs expensive tiers and `no_exact_solution` | `wayfinder:research` | -- | Facts for abort cut; do not redesign |
| [354](https://github.com/SteveDraper/Planets-Console/issues/354) | Generic freighter placeholder and count constraints | `wayfinder:research` | -- | Pattern for #358 |
| [355](https://github.com/SteveDraper/Planets-Console/issues/355) | This inventory | `wayfinder:research` | -- | This note |
| [356](https://github.com/SteveDraper/Planets-Console/issues/356) | Inference admission skip set | `wayfinder:grilling` | -- | Consumes #302 |
| [357](https://github.com/SteveDraper/Planets-Console/issues/357) | Mine-score residual likelihood and expensive-tier abort | `wayfinder:grilling` | #353 | May consume or parallel #244 |
| [358](https://github.com/SteveDraper/Planets-Console/issues/358) | Unknown military ship placeholder contract | `wayfinder:grilling` | #354 | New product contract |
| [359](https://github.com/SteveDraper/Planets-Console/issues/359) | Ship loss, gift, and trade as exact families | `wayfinder:grilling` | #354 | Splits #49 |
| [360](https://github.com/SteveDraper/Planets-Console/issues/360) | Inference product-status persist and stream contract | `wayfinder:grilling` | #356 #357 #358 #359 | Touches persist (`exact` / `no_exact_solution` today) and #97 |
| [361](https://github.com/SteveDraper/Planets-Console/issues/361) | Hygiene: remaining inference tickets vs this quality bar | `wayfinder:grilling` | #355 | Decides fates; this note is input only |

---

## Persist / skip facts the map will reuse

Cited so #360 / #356 do not re-litigate current code:

- **Functional persist (modal row):** `PERSISTABLE_INFERENCE_STATUSES = {exact, no_exact_solution}` ([`export_precedence.py`](../../packages/api/api/analytics/scores/export_precedence.py)).
- **Turn-evidence persist:** `DURABLE_TURN_EVIDENCE_ROW_STATUSES` also includes `stopped`, `time_limited`, `no_prior_turn`, `player_not_found`, `invalid_problem`, `solver_error`. Ensure tests persist `no_prior_turn` / `player_not_found` so evidence can close. [CONTEXT.md](../../CONTEXT.md) **Scores inference row persistence** still says those immediate terminals are *not* written -- glossary vs code drift.
- **Admission-like skips today:** `no_prior_turn` (including unfinished accelerated window) and missing scoreboard row (`player_not_found`). Not owner, dead, or Stealth.
- **User-facing no-exact:** SPA maps `no_exact_solution` to a red X (`ScoresTableView`); band residual is diagnostics-only -- the gap #352 wants distinct contracts for.

## Sources

- GitHub: issues #39, #49, #53, #66, #88, #89, #97, #104, #156, #216, #241, #244, #245, #302, #295, #352–#361; closed #48, #51, #52, #64, #65, #73, #87, #92, #95, #111, #200.
- [CONTEXT.md](../../CONTEXT.md) glossary: military score build inference, score-decreasing effect, mine-score residual, inference moderate residual, inference admission skip, hopeless classifier, inference expensive-tier abort, generic freighter combo, unknown military ship, scores inference row persistence.
- Code/assets cited inline above.
