# Design: Homeworld locator analytic

This document captures **game-domain and inference rules** for the **Homeworld locator** **turn analytic**. It supplements the GitHub issues ([#33](https://github.com/SteveDraper/Planets-Console/issues/33) PRD, child slices [#34](https://github.com/SteveDraper/Planets-Console/issues/34)--[#37](https://github.com/SteveDraper/Planets-Console/issues/37)) with the reasoning and constraints from design review. Use **CONTEXT.md** for project vocabulary and [ADR 0002](adr/0002-analytic-persistence.md) for persistence paths.

**Nu help (Starmap):** [Game Setup Customization](https://planets.nu/customization) -- homeworld placement lives under **Starmap**, not classic Host Configuration turn-processing defaults.

Related: [design-adding-a-turn-analytic.md](design-adding-a-turn-analytic.md), [design-analytics-structure.md](design-analytics-structure.md), [vga-planets-domain-context.md](vga-planets-domain-context.md).

---

## 1. Purpose

**TurnInfo** has no homeworld boolean. Each **Player** slot receives one starting **homeworld planet** at map creation. The locator heuristically infers where those planets are (or which regions they must lie in) using:

1. **GameInfo** Starmap settings (layout and local cluster constraints)
2. **Homeworld inference baseline** turn planet data (prefer turn 1)
3. **Homeworld inference evidence** from later turns (perspective-scoped sensor picture)
4. Optional **user-asserted** **homeworld candidate records**

Output: **slot-anchored homeworld candidates**, **orphan homeworld candidates**, **homeworld confidence tier**, map markers, and region overlays.

**Not in scope:** **Officer Homeworld** (planets.nu account metagame UI) -- a different concept entirely.

---

## 2. When the analytic is unavailable

**Homeworld locator availability** is **inactive** (catalog greyed + hint; no compute; no persistence) when traditional homeworld planets do not exist:

| Condition | Meaning |
|-----------|---------|
| `nohomeworld: true` | Game created without homeworld planets |
| `wanderingtribescount > 0` | **Wandering Tribes** -- players start in STF fleets, not on HW planets |
| Scenario overrides | e.g. Disunited Kingdoms, Crazy Intermix, Ashes of the Evil Empire (no normal HW setup). No scenario-name field on **GameSettings** -- detect via recipe heuristics: Ashes `hwdistribution=4`; Crazy Intermix `extraplanets>0` + `extraplanetsrandomloc`; Disunited Kingdoms `extraplanets>0` without random loc. |

Fleet spawn region inference for Wandering Tribes is a future alternate mode, not v1.

---

## 3. Game settings that constrain homeworld layout

These fields are already modeled on **GameSettings** in Core (`GameInfo` / embedded in **TurnInfo**). They come from Planets.nu **Starmap** at game creation.

### 3.1 Inter-player homeworld layout

| UI (Nu help) | API field | Values / default | Role for inference |
|--------------|-----------|------------------|-------------------|
| Homeworld Locations | `hwdistribution` | 1=Random Spaced, **2=Circular (default)**, 3=Left and Right, 4=One vs. Circle | How HW slots are arranged on the map |
| Shuffle Team Positions | `shuffleteampositions` | bool | Randomizes which player slot lands on which HW **position** on the ring/layout |
| Map shape | `mapshape` | 0=Round, 1=Rectangular, 2=Irregular Round | Round maps pair with Circular distribution in standard games |
| Map size | `mapwidth`, `mapheight` | default 2000x2000 | Scale for ring radius and spacing heuristics |

**v1 region geometry:** only **`hwdistribution=2` (Circular)** on **`mapshape=0` (Round)**. Other combinations still run baseline + evidence + manual annotation but **skip sector/ring overlays**.

**Standard round + circular pattern:** homeworlds sit on a ring at roughly equal angular spacing from map center, at similar distance from center and from one another. `shuffleteampositions` permutes slot-to-sector assignment but preserves the ring geometry.

There is **no separate API knob** for minimum LY between player homeworlds; spacing is implied by distribution mode + map size.

### 3.2 Neighborhood (planets near each HW)

| UI | API field | Default | Role for inference |
|----|-----------|---------|-------------------|
| Homeworld Planets < 81 LY | `verycloseplanets` | 2 | Minimum planets within **81 LY** of each HW |
| Homeworld Planets < 162 LY | `closeplanets` | 12 | Minimum planets in the **81--162 LY** band around each HW |
| Other Planets Min Dist | `otherplanetsminhomeworlddist` | 155 LY | Minimum distance for planets outside designated near-HW slots |

Use these to validate cluster structure around candidate planets: a plausible HW should have neighbor counts consistent with settings (within tolerance for map generation variance).

**Planetoids** (`debrisdisk == 1`, colonizable bodies inside debris disks) are **not** counted in either band and are **never** homeworld candidates (baseline profile, ring sites, or cluster orphans).

### 3.3 Starting conditions on the HW planet

| UI | API field | Default | Role for baseline profile |
|----|-----------|---------|---------------------------|
| Homeworld - Has Starbase | `homeworldhasstarbase` | On | Baseline expects starbase on turn 1 when true |
| Homeworld - Clans | `homeworldclans` | 25,000 | Turn-1 starting clans (**not** a floor during play) |
| Homeworld - Resources | `homeworldresources` | High (3) | Affects minerals; not primary HW locator signal in v1 |

**Clan math:** 1 clan = 100 colonists. Default 25,000 clans = **2.5M colonists** at turn 1.

**Population during play:** `homeworldclans` does **not** protect population. RGA (**Rebel Ground Attack**), combat, overpopulation, transfers, etc. can reduce clans below the starting setting. Hence configurable **`min_baseline_clans`** in YAML (intent ~10,000 clans / ~1M colonists) -- below default `homeworldclans` but above casual colony sizes.

### 3.4 Other settings referenced in code (limited help mirror)

| Field | Notes |
|-------|-------|
| `ncircles`, `deadradius` | Present in Console samples; classic map-gen params -- use cautiously until documented for Nu |
| `fixedstartpositions` | May reduce slot permutation ambiguity |
| `extraplanets`, `extraships` | Private-game extras near HW -- can add owned planets with partial populations (Horwasp extras use 2,500 clans) |
| `planetcount`, star clusters, nebulae | Consume map space; extreme combos can fail map creation |

---

## 4. Inference signals

Signals are grouped by when they apply. The engine combines them into **homeworld confidence tier** and slot assignment.

### 4.1 Homeworld inference baseline (prefer turn 1)

**Source:** earliest stored **TurnInfo** for shell **perspective**; **auto-ensure turn 1** when credentials allow. If only later turns exist, use earliest with **baseline degraded** (cautious definite matching; warn in UI).

**Do not** re-run baseline heuristics against the shell's currently selected turn alone -- population, climate, and ownership drift over time.

#### Baseline profile match (strong **definite** signal)

Per **perspective** slot, a planet owned by that slot's **Player** on the baseline turn matches when **all** apply:

| Signal | Rule |
|--------|------|
| Ownership | Planet `ownerid` matches slot |
| Clans | `clans >= min_baseline_clans` (YAML config; default ~10,000) |
| Starbase | Starbase present if `homeworldhasstarbase` |
| Climate | Planet `temp` matches **race climate catalog** preferred temp for slot's race |

**Race climate catalog:**

| Race | Preferred temp | Notes |
|------|----------------|-------|
| Most races | 50 deg W | Optimal for growth/happiness in Nu docs |
| Crystal Confederation | 100 deg W | When **Crystal desert advantage** is on |
| Crystal (advantage off) | 50 deg W | Crystals behave like other races |

**Important caveats:**

- **Do not** use universal temp 50 -- Crystal HWs break that rule.
- Vault does **not** guarantee every Crystal HW is physically 100 deg at map gen; compare to **race expected** temp, not a global constant.
- Turn-1 **physical** temp vs formula BaseTemp can differ in classic hosts; trust planet `temp` from **TurnInfo**.

#### Baseline false positives (treat as possible, not definite)

- Terraformed colonies at 50 deg / 100 deg
- Captured original HWs
- Large mid-game worlds (if baseline degraded to later turn)
- **`extraplanets`** extra starts near HW

#### Baseline false negatives

- Terraformed HWs (climate no longer matches)
- Low custom `homeworldclans` games with threshold set too high
- RGA / combat reduced clans below `min_baseline_clans`

### 4.2 Layout and geometry signals (Circular + round, plus cluster constraints)

**Fog-of-war (common early turns):** full planet details are usually available only for the **viewpoint** slot's own worlds. Rival homeworlds appear as planet positions (and cluster structure) without clans/temp/starbase. **Baseline profile** therefore typically pins at most the viewpoint **homeworld planet** as **definite**; multi-slot inference relies on geometry and cluster constraints.

Apply **homeworld candidate geometry** when `hwdistribution=2` and `mapshape=0`:

| Signal | Use |
|--------|-----|
| Ring from center | HW positions lie on a common-radius ring; infer radius from known definites or player count + map size |
| Angular spacing | ~equal sectors per active **Player**; `shuffleteampositions` permutes slot-to-site assignment |
| Viewpoint pin | When the viewpoint slot has a unique **homeworld baseline profile** match, treat that planet as **definite** slot-anchored and fix ring rotation |
| Other ring HW sites | Remaining geometric HW planets are **orphan homeworld candidates** (**possible**) only when they also meet the **homeworld cluster constraint** (ring geometry AND cluster -- not OR). Do not cross-product bind them to rival slots in v1 baseline |
| Center-distance band | When the layout-asset epic\|standard gate applies (same as sector overlays), drop orphan candidates outside the asset center-distance support `[supportMin, supportMax]` at baseline generation -- they cannot lie in painted sector annuli |
| Co-sector cull | Once a sector has a **definite** homeworld, drop other inferred candidates in that same angular sector (possibles and evidence-promoted orphan definites). Prefer slot-anchored over orphan when choosing which inferred definite to keep; never cull **user-asserted** rows |
| Single planet in sector | **Definite** when baseline weak but geometry leaves no plausible alternative in that slot's arc (stronger once overlays/#35 land) |

**Homeworld cluster constraint** (all map shapes that still have traditional HWs): count **traditional** planets within 81 LY and within 81--162 LY on the **perspective star chart**; compare to `verycloseplanets` and `closeplanets`. Required for circular **ring-site** orphans as well as off-ring / non-circular orphan construction -- geometry alone does not waive the cluster minima. On circular + round epic|standard maps, off-ring cluster orphans are additionally restricted to the layout center-distance support band.

**FoW incompleteness (working rule):** a player's `rst.planets` omits traditional planets outside planet-scan reach (nebulae / reduced `planetscanrange`); they are not present as dark stubs. Cluster known-counts therefore understate map-gen minima near scan-dark annulus. **FoW density credit** ([#275](https://github.com/SteveDraper/Planets-Console/issues/275)): estimate traditional planetary density from the chart (round maps: geometric area `π (D/2)²` with diameter `D` = max traditional planet spacing; rectangular: `mapwidth × mapheight`), debiased by planet-scan observed-area fraction when origins exist; credit `density × unobserved_band_area × multiplier` per band (`api.homeworld_locator.cluster_fow_density_credit_multiplier`, default **1.0**); cap each band's credit at the remaining map-gen deficit; hard-gate orphans on `known + credit ≥ minima`. Planetoids never count. Fully observed bands ⇒ credit ≈ 0 (parity with pre-credit behavior). Empty `scan_origins` (explicit) means no planet-scan coverage model: both cluster bands are treated as fully unobserved (full-band credit before the deficit cap). Baseline algorithm version `HOMEWORLD_BASELINE_ALGORITHM_VERSION` bumps when this candidacy policy changes.

When no planet is pinned for a slot, [#35](https://github.com/SteveDraper/Planets-Console/issues/35) emits **homeworld region overlay** entries on shared **`regionOverlays`** (boundary geometry for equal angular sectors on the circular ring, plus optional 81/162 LY envelope disks). Grill locks for #35 paint:

| Lock | Rule |
|------|------|
| Emission gate | Only when `hwdistribution=2`, `mapshape=0`, game category epic\|standard, and a **viewpoint pin** fixes rotation -- then emit **all** `player_count` sector overlays; otherwise none (markers unchanged) |
| Wire | Shared **map region overlay** boundary primitive ([ADR 0008](adr/0008-shared-map-region-overlays.md)); not a homeworld-only field; not cartography `overlayCircles` |
| Band radii | From **homeworld layout distribution asset** smoothed center-distance support extremes |
| Envelopes | 81 + 162 LY disks when a sector center exists (orphan: layout-prior **most probable** in the sector when annotated, else candidate closest to sector geometric mid; pinned planet when pinned; incomplete + no candidates → geometric band center; fully observed + zero candidates → no disks, error stroke + hover) |
| Sector paint | Stroke-only annular boundaries (no fill); FE display mode filters which sectors show |
| FE display | **Homeworld region display mode** (`off` \| `un-pinned` \| `pinned` \| `all`, default `un-pinned`) |
| Labels | No rival slot labels in #35 (assignment stays #37) |

Candidate geometry itself remains [#34](https://github.com/SteveDraper/Planets-Console/issues/34).

For non-circular or non-round maps: skip ring/sector math; still use baseline profile + **homeworld cluster constraint** + later evidence.

### 4.3 Homeworld inference evidence (later turns)

Split into **location** vs **ownership** (different tickets).

**Source (both):** **TurnInfo** stored at shell **viewpoint** **perspective** only -- not a union across all slots (**homeworld evidence scope**).

#### 4.3.1 Homeworld location evidence ([#36](https://github.com/SteveDraper/Planets-Console/issues/36))

Strengthens **where** a HW is (confidence on existing candidates). Does **not** assign **homeworld owner** from `ship.ownerid`.

| Signal | Rule |
|--------|------|
| Origin distance -- non-gravitonic | Ship near **64 LY** (warp 8) or **81 LY** (pod / warp 9) from an **existing** candidate planet |
| Origin distance -- gravitonic | Gravitonic ships only: **128 LY** (grav warp 8) or **162 LY** (grav warp 9) |
| Match tolerance | Small LY band (~+/-1); reuse `max_travel_distance` in **game concepts**, not YAML lists |
| Origin-distance observations | One durable observation per (**turn**, ship **x**, ship **y**). Match set `M` = candidate planet ids in the origin-distance band. Co-located ships merge by unioning `M`. Observations do **not** flip confidence tier; they feed the soft evidence cost family in layout-prior selection. Persisted as `originDistanceObservations` on the evidence aggregate (replaces per-planet-turn hit rows). |
| Single-starbase new-build | Ship first seen at *T-1* (or fleet `built_turn == T-1`) and owner scoreboard `starbases == 1` -> **immediate** possible->definite on implicated candidate; skip if SB count unknown / Stealth. **Only** automatic hard definite from location evidence. |
| Candidate creation | Distance matches **never** invent new orphans -- only existing candidates |

**Materialize (shared, after refine):** single-SB promote (if recorded) -> **co-sector cull** -> **homeworld definite-neighborhood cull** (asset `neighbor_separation.supportMin`) -> **homeworld ownership evidence** apply (sector owner sets) -> **homeworld layout prior selection** (`isMostProbable`). Origin-distance observations never promote.

#### 4.3.2 Homeworld ownership evidence ([#269](https://github.com/SteveDraper/Planets-Console/issues/269))

Strengthens **homeworld owner** attribution for **homeworld sectors** (whose HW / sector), not location tier. Does **not** invent location candidates and does **not** replace #36 location promotion. Out of scope for #36 / layout-prior / user assertions (#37) / fleet SB-region consumption (#134).

**Unit of attribution:** the **homeworld sector**, not candidate wire `perspective`. Each sector carries a **possible homeworld owner set**: zero or more **Player** slots, each with a **provenance collection** (summaries of why that slot is in the set). Conflicts are retained as multiple members -- the SPA decides display. Motivation: [#37](https://github.com/SteveDraper/Planets-Console/issues/37) can add a **user-asserted** provenance the UI may treat as decisive even when other evidence remains.

| Concern | Rule |
|---------|------|
| Scope | Viewpoint **perspective** TurnInfo only (same **homeworld evidence scope** as location evidence) |
| Persistence | Turn-scoped on the **homeworld evidence aggregate** (durable sector owner sets + provenances through *T*); materialize projects onto sector overlays / candidate bind helpers. Stamp ``evidenceAlgorithmVersion`` (`HOMEWORLD_EVIDENCE_ALGORITHM_VERSION`, currently **3**; absent/0 = pre-version). Satisfaction / ensure refuse stale versions so the self-chain rewalks from the baseline floor; floor rewrite is owned solely by ``ensure_evidence_floor_algorithm_current`` (clears sticky ownership before re-accumulate, then stamps the current version) |
| Location candidates | Never create orphans; never flip `confidence_tier` from ownership alone |
| Candidate `perspective` | Optional bind when a sector has a **unique** possible owner (orphans in that sector may become slot-anchored for layout-prior / pin display). Ambiguous sectors leave orphans unbound. Prose always says **homeworld owner**, not perspective |

**Ship age (travel-turn budget):**

1. Prefer known fleet ledger **`built_turn`** for that ship id when available. Homeworld refine **depends** on **final** fleet ledgers for the shell turn via the compute orchestrator DAG (`ENSURE_DEPENDENCIES`) -- not a soft opportunistic read. Soft-read loses the open-turn race (homeworld often completes before fleet) and nothing would recompute when fleet later finishes.
2. Otherwise assume **maximum age**: earliest scoreboard-history turn *T* where `total_reported_ships >= ship.id` is the earliest possible build turn. Travel-turn budget at shell *S* is `max(0, S - T)`.
3. Incomplete scoreboard history that prevents computing the id-age bound: skip that ship's envelope (do not hard-fail the whole ensure). Ship-limit freeze history remains its own hard-fail path.

**Fleet DAG dependency (required for (1)):**

| Concern | Rule |
|---------|------|
| Edge | `homeworld@N` → `fleet@N` with `quality="final"` (same shell turn; `built_turn` is on that turn's final ledger) |
| Cross-player | Homeworld scope has no `player_id`. Fleet ensure with `player_id=None` is a **no-op** (`is_fleet_export_ensure_satisfied` returns true). Therefore declare / expand to **one final-fleet dependency per roster player** at turn *N* (new `EnsureDependency` fan-out, e.g. `player_id="all"`, or equivalent walk expansion). **All roster players** -- not the visible-ship-owner subset -- so the edge set is stable and every ship id can resolve `built_turn` when its owner's ledger is final. Orchestrator today documents cross-player as caller fan-out -- #269 needs graph-level expansion so a single homeworld node waits on all player fleet nodes. |
| Wire | Orchestrator refine job wire receives final ledger slices (or player→`built_turn` map) via `DependencyOutputs`. Sync export ensure, after fleet ENSURE is satisfied, loads the same ages from final on-disk ledgers (`fleet_built_turns_from_final_ledgers`) -- no live `ensure_fleet_export` inside the refine worker |
| ENSURE fan-out | ``EnsureDependency.player_id="all"`` is implemented in ``dependency_scopes_for`` / ``plan_compute_dag`` (one final-fleet edge per roster player at shell *N*) |
| Invalidation | **#269 stays DAG-only** for open-turn correctness (homeworld waits on final fleet before refine). Ancestor **re-persist** wipe + `force_fresh` wake is **not** implemented here -- tracked as generic orchestrator reverse-ENSURE work ([#280](https://github.com/SteveDraper/Planets-Console/issues/280)), including refactor of scores↔fleet onto that path |
| Baseline | Baseline step does **not** need fleet; only ownership-aware evidence refine / materialize that consumes `built_turn` |

**Travel envelope:**

| Input | Rule |
|-------|------|
| Radius | `travel_turns × (warp² + 1)` LY -- warp-square family plus **1 LY/turn** host rounding / overshoot slack (W9 one-hop ≈ 82 LY, not 81) |
| Engines unknown | Assume warp **9** |
| Gravitonic | Apply 2× range **only** for gravitonic hulls (`hull_has_gravitonic_movement`); rounding slack is still +1 LY/turn on top |
| Hyperdrive | **Ignore** HYP-capable hulls for envelopes (hull ability / known HYP hull set -- not FC=`HYP` alone) |
| Chunnel / tow / wormhole | No special handling in v1 (envelope is the naive warp budget) |

**Sector reduction (ship → owner):** For ship of `ownerid` *X* at (*x*,*y*) with envelope radius *R*, the reachable **homeworld sectors** are those whose **preferred sector HW position** (definite planet if any; else most-probable; else closest-to-mid candidate; else sector annular mid when no candidates) lies within *R* of the ship. Intersect that reachable set into owner *X*'s remaining possible-sector set (initialized to all eligible sectors). When owner *X*'s possible-sector set shrinks to a single sector, add *X* to that sector's possible-owner set with a **ship-travel-envelope** provenance summary (ship id, turn, radius, age source).

**Planetary ownership sightings:**

| Signal | Rule |
|--------|------|
| Preferred candidate HW | Known planetary `ownerid` on the sector's **preferred** HW candidate (definite > most-probable > closest-to-mid) **adds** that slot to the sector's possible-owner set with **preferred-candidate-ownership** provenance |
| Nearby planets | Known `ownerid` on any traditional (non-planetoid) planet within **162 LY** of a sector **candidate** HW planet **adds** that slot to the sector's possible-owner set with **nearby-planet-ownership** provenance (planet id, distance). Cap radius is gravitonic warp-9 travel (162 LY) |

Empty / unknown `ownerid` does not contribute. Ownership sightings **add** to the set; they do not remove other members by themselves (envelope reduction is the narrowing channel for ship-origin sectors).

**Provenance summary (v1 machine facts):** each set member stores one or more `{kind, turn, ...}` records (`ship_travel_envelope` \| `preferred_candidate_ownership` \| `nearby_planet_ownership`; later `user_asserted` from #37). Core emits structured facts only -- no English hover strings (ADR 0008).

**Materialize order:** after location promote + co-sector cull + definite-neighborhood cull; **before** layout prior. Ownership apply updates sector owner sets (and unique-owner orphan bind when applicable); layout prior still keys off candidate tiers / pins.

**Wire / UI (minimal for #269):** sector `regionOverlays` carry possible-owner facts (slot ids, roster labels, provenance kind counts or short machine tags). SPA hover (`formatHomeworldSectorHoverLine`) shows a single owner when `|set|=1`, else **ambiguous** plus the possible owners when `|set|>1`. No new sidebar panel in this ticket.

#### 4.3.3 Homeworld layout prior selection ([#36](https://github.com/SteveDraper/Planets-Console/issues/36), upgraded by [#270](https://github.com/SteveDraper/Planets-Console/issues/270))

Opinionated joint set over **homeworld sectors** (same eligibility gate as sector overlay emission: circular + round + epic|standard + viewpoint pin). Not a third confidence tier.

| Lock | Rule |
|------|------|
| Status | **`isMostProbable`** on possible candidates only; orthogonal to `confidence_tier` |
| Cost | Equal family weight over three means: (1) Normal ``-log`` density of clockwise-neighbor separation, (2) Normal ``-log`` density of center-distance over unpinned members (fitted ``mean``/``std`` from the layout distribution asset), (3) soft origin-distance evidence ``E(S)``. For selection planet set ``S`` (fixed definites + chosen possibles; stand-ins do not absorb credit): per observation ``P(o\|S)=|S∩M|/|M|`` (ε floor if empty); per turn ``e_t=mean(-log P)``; on nonempty turn ``t`` ``E=(E+w(t) e_t)/(1+w(t))`` with ``w(t)=λ^t`` and config ``origin_distance_evidence_lambda`` (default **0.95**); empty turns leave ``E`` unchanged (no evidence ⇒ estimate unchanged); ``E=0`` when the observation list is empty. Soft OD observations stop accruing once the shared ship limit is reached (current-turn scoreboard ship total ≥ ``shiplimit``; ``concepts.ship_limit`` ignores non-current ``score.turn`` rows). On first freeze, sticky ``originDistanceEvidenceThroughTurn`` is ``T_limit - 1`` where ``T_limit`` is the earliest turn in scoreboard history (accelerated ensure floor through shell) at/over the limit -- not merely ``shell - 1``. Incomplete history is a hard ensure failure (same auto-fetch path as the evidence chain). Under-limit shells leave the cutoff unset. Cost evaluation lives outside the replaceable solver. |
| Neighbor metric | Clockwise-neighbor (angle-sorted ring), matching asset sampling -- not true nearest-Euclidean |
| Pinned sectors | Definite is the fixed set member; no most-probable label |
| Empty sectors | **Homeworld layout stand-in**: synthetic position in planet-scan-unobserved band area closes the ring; contributes to both cost families; not a candidate / not drawn. Fully scanned empty sector -> does not participate. After discrete SA, place stand-ins by alternating coordinate descent over unobserved **sample-grid** points (deterministic sector-index sweep order; layout-prior cost; replaceable scored-sample hook for a later launch-consistency term -- not #270; hard iteration safety cap). |
| Solver boundary | Replaceable pure solver: given sector participation + search space + budget, returns chosen planet ids, stand-in positions, and cost/tie metadata. Sector build, eligibility, cost, fingerprint, persist, and annotate stay outside. |
| Search shape (#270) | Discrete-first: greedy init from pinned definites, then seeded time-budgeted simulated annealing over choice-sector planets (cheap/fixed stand-ins during anneal); then sample-grid stand-in refine on the incumbent (outside stop-gate; small hard iter safety cap). **Continuity (facade, deliberate -- not a single warm-started anneal):** for anneal when shell turn ``> 1``, run **two inline solves** at full budget and keep the lower cost (then tie-key). Roles: **this-turn RNG seed** = variation / exploration; **previous-turn RNG seed** = maintains SA dynamics where local evidence is unchanged (same stream as last turn's this-seed solve). Separately, when the previous shell ``mostProbablePlanetIds`` remain a complete admissible assignment under this turn's choice sectors, **score that projection** (refine path; no SA) and prefer it if better than both anneals -- **stability against SA noise**. Enumerate stays a single solve. **Greedy init:** grow from the assigned set (pins + already chosen); when multiple frontier choice sectors are eligible to extend next, prefer the sector with fewest possibles; within that sector pick the planet minimizing full-ring layout-prior cost given the current partial assignment and fixed mid stand-ins. SA legal set = all possibles in the sector; proposal distribution biased toward nearer sector mid (and/or better local cost delta) -- not a hard top-K product cap. Exact global optimum when budget allows is a goal, not mandatory every request. |
| Solver implementations | `#36` capped product + fixed mid stand-in remains as `EnumeratingLayoutPriorSolver` (regression / fixtures / emergency config). Production default is `AnnealingLayoutPriorSolver` (`layout_prior_solver: anneal`). YAML exposes `layout_prior_budget_ms` (default **1000**) + solver selector only. SA temperature follows a **budget-progress** schedule (`T = T0 * (T_final/T0)^progress` from wall-clock or step-gate progress), not per-step geometric multiplies; moves and proposal bias live in code and may be problem-size adaptive; coefficients are chosen via fixtures, not YAML tables. Modules: `layout_prior.py` (facade), `layout_prior_problem.py`, `layout_prior_cost.py`, `layout_prior_solver.py`, `layout_prior_stop_gate.py`, `layout_prior_enumerate.py`, `layout_prior_anneal.py`, `layout_prior_refine.py`. |
| Implementation phases | **Phase 1:** extract pure `LayoutPriorSolver` boundary; move current enumerator behind it; behavior and `LAYOUT_PRIOR_ALGORITHM_VERSION` unchanged (fixture parity). **Phase 2:** add SA + sample-grid refine solver; switch default; bump `LAYOUT_PRIOR_ALGORITHM_VERSION`. Later material changes to solver/cost/stand-in policy (including cooling formulas that change selections) bump again. |
| Anytime / determinism | Configurable computation budget via a pluggable **stop-gate** polled each discrete SA step (production: wall-clock deadline; tests: step count). Continuous/sample stand-in refine runs after SA and is outside the gate (small hard iteration safety cap only). Incumbent cost must not worsen as budget increases under a comparable gate. SA RNG seeded from shell scope + input fingerprint + algorithm version (`game_id`, RNG seed turn, perspective, fingerprint, `LAYOUT_PRIOR_ALGORITHM_VERSION`) so same inputs + version + step gate => same selected planet-id set. Continuity dual-seed solves vary only the RNG seed turn (`shell_turn - 1` then `shell_turn`) by design -- see Search shape continuity rationale. Production default **`layout_prior_budget_ms`** is **1000** per inline solve (enough for budget-progress SA to escape early basins on dense circular maps; not a CI wall-clock lock). |
| Follow-on (not #270) | **Stand-in launch consistency** ([#273](https://github.com/SteveDraper/Planets-Console/issues/273)): bias stand-in sample scores using one-turn / warp² (Grav) ship geometry and optional heading/waypoint back-track -- distinct from **ship origin distance signal** (which only strengthens existing candidate planets). |
| Ties | Lexicographically smaller selected planet-id tuple |
| Wire / UI | Shared map+table field; double-layer dotted ring on map; table cue |
| Persistence | Shell turn only: `layoutPriorSelection` on that turn's evidence aggregate (`algorithmVersion` + `inputFingerprint` of post-promote/cull candidates + `evidenceLambda` from config `origin_distance_evidence_lambda` + `evidenceFingerprint` SHA-256 hex of effective soft OD observations + `mostProbablePlanetIds`). Reuse when algorithm version, candidate fingerprint, λ, and observation fingerprint all match current inputs; recompute+rewrite on any mismatch. Incomplete/legacy selections (any reuse-key field missing) **clear on load** so the aggregate still reads and reuse misses; present-but-invalid field types still fail deserialize. `LAYOUT_PRIOR_ALGORITHM_VERSION` covers solver identity + cost/stand-in/tie-break policy. Intermediate refine turns do not compute or store selection. Evidence rewrite/invalidation clears it. ADR: [0009](../adr/0009-homeworld-layout-prior-budgeted-solver.md). |
| Solver telemetry (#274) | Each materialize-path solver run (not cache-hit reuse) records a structured **homeworld layout prior solver run report**: stop-gate + stop reason, timing splits, step/accept counts, greedy/pre-refine/final costs, problem-size hints, bounded incumbent-vs-step series. Process last-N ring; BFF Diagnostics **Homeworlds** tab. Homeworld-owned -- never mixed into **compute diagnostics**. Continuity **projection wins** (admissible previous selection preferred over both anneals) record a dedicated report with ``stopReason=projected`` whose ``projectedCost`` / ``finalCost`` / ``tieKey`` match the returned selection -- not a reused anneal SA report; anneal-phase ``greedyCost`` / ``preRefineCost`` are null on projection rows. |

**Evidence does not replace baseline;** it adjusts confidence on candidates already hypothesized from baseline + geometry.

### 4.4 User assertion

**User-asserted** records use the same **homeworld candidate record** shape as inferred rows. Promotion to **definite**, **homeworld owner** assignment, or race tag with **user-asserted** attribution always wins over inference until revoked (#37).

---

## 5. Confidence tiers and selection status

| Kind | When |
|------|------|
| **Definite** | Baseline profile match; OR geometry leaves no plausible alternative; OR **single-starbase new-build** promotion; OR **user-asserted** |
| **Possible** | Consistent with settings/spacing/evidence but not unique; default for orphans |
| **Most probable** (`isMostProbable`) | Selection status on one **possible** per unpinned sector under layout prior -- **not** a confidence tier |

Orphans: location-first candidates not yet tied to a **homeworld owner** -- remain **possible** until anchored or confirmed.

---

## 6. Candidate output model

Two parallel output modes (**C** from design review):

1. **Slot-anchored** -- tied to a **homeworld owner** (Player / slot whose HW this is)
2. **Orphan** -- planet or region that looks like a HW; owner not yet assigned

**Homeworld candidate record** (persisted and on the wire):

```
record_id
perspective?          # wire name: homeworld owner slot when slot-anchored (not shell viewpoint)
planet_id?            # when pinned to a planet
region?               # when only sector/envelope known
race_id?              # override or annotation
confidence_tier       # definite | possible
is_most_probable      # view-time selection status (#36); not durable evidence
attribution           # inferred | user-asserted
evidence_summary?     # counts for UI
```

---

## 7. Turn and perspective scope

| Data | Scope |
|------|-------|
| Baseline planet signals | Earliest turn for shell **perspective** (prefer turn 1) |
| Later-turn evidence | Turns stored at current **viewpoint** **perspective** only |
| User assertions | **Homeworld locator state (game-global)** -- shared across viewers |
| Evidence accumulation | **Homeworld locator evidence (perspective)** per slot |

Planet **x/y coordinates** are static; map display can use current shell turn while inference reads baseline + evidence turns.

---

## 8. Persistence and invalidation

See [ADR 0002](adr/0002-analytic-persistence.md) (homeworld example amended with turn-scoped aggregates).

| Document | Path |
|----------|------|
| Game-global state | `games/{gameId}/analytics/homeworld-locator` |
| Evidence aggregate (turn-scoped) | `games/{gameId}/{perspective}/turns/{turn}/analytics/homeworld-locator` |

**Model:** durable **homeworld evidence aggregate** at each turn is refined from game-global inputs + aggregate at *T−1* + observations at *T*. The **homeworld candidate view** (tiers for map/table) is materialized on read from game-global state + aggregate at the shell turn. Shell-turn **layout prior** selection is versioned-persisted on that aggregate (`layoutPriorSelection`); intermediate refine turns do not store it.

**Compute:** [#34](https://github.com/SteveDraper/Planets-Console/issues/34) registers baseline ensure with the **compute orchestrator** and an empty `ENSURE_DEPENDENCIES` (game-global floor; no prior-turn walk). A `turn_delta=-1` self-chain would require every intermediate turn to be stored before degraded→T1 baseline upgrade can run. [#36](https://github.com/SteveDraper/Planets-Console/issues/36) adds the linear self-chain (`homeworld@T` depends on `homeworld@(T−1)`) for shell-turn evidence refine. **Ensure baseline** is turn 1 (or degraded earliest); evidence aggregates refine from the floor through the shell turn (no empty copy-forward). When an intermediate TurnInfo on that path is not stored, export ensure **auto-fetches** missing turns via the login-backed `ensure_turn` hook (same credential path as baseline turn-1 ensure) before refining; if auto-fetch is unavailable or upstream load fails, ensure raises a clear `ValidationError` and records an **ensure failure** on Homeworlds diagnostics.

**Invalidation (inferred state):**

- **TurnInfo** store/replace at *T* clears evidence aggregates at turns `>= T` (fleet-like)
- **GameInfo** re-fetch with changed homeworld-relevant settings invalidates inferred game-global candidates
- Turn 1 newly available after a **baseline degraded** run triggers baseline recompute
- Manual **homeworld locator refresh** (#37)

**User-asserted** records preserved on recompute (#37).

---

## 9. Configuration (YAML, not UI)

Under Core `api` config (**homeworld locator config**):

| Field | Purpose |
|-------|---------|
| `min_baseline_clans` | Floor for baseline profile (~10,000 default intent) |
| `origin_distance_evidence_lambda` | Absolute-turn soft OD weight base λ (`w(t)=λ^t`; default **0.95**; range `(0, 1]`) |
| Soft OD ship-limit freeze | Not a YAML knob: sticky `originDistanceEvidenceThroughTurn = T_limit - 1` at earliest shared scoreboard ship-limit crossing (see §4.3.3) |
| `layout_prior_solver` / `layout_prior_budget_ms` | Anneal vs enumerate; wall-clock SA budget **per inline solve** (turn `> 1` dual-seed ≈ 2×) |

Origin distances (81 LY pod, warp table) and the shared ship-limit gate stay in **game concepts**. Hard definite from location evidence is **single-starbase new-build only** -- there is no evidence-hit promotion threshold.

---

## 10. Map and UI behavior

| Element | Behavior |
|---------|----------|
| **Homeworld map marker** | Decoration on **base map** node -- solid = definite; dashed/light = possible; **most probable** = stronger possible (double-layer dotted ring) via `isMostProbable` |
| **User-asserted definite** | Same definite marker + attribution cue (border/badge) |
| **Homeworld region overlay** | Shared **map region overlay** boundary sectors (+ optional envelopes) for Circular round; filtered by **homeworld region display mode** |
| **Homeworld locator panel** | Sidebar table + refresh + degraded baseline warning |
| Map context menu | Quick **homeworld assertion** |
| Tabular tile | Same rows as panel in main **tabular** **view mode**; show most-probable cue |
| **Homeworld region display mode** | Sidebar expandable control (Cartography pattern); global preference |

---

## 11. Implementation slices (issues)

| Issue | Delivers |
|-------|----------|
| [#34](https://github.com/SteveDraper/Planets-Console/issues/34) | Config, race climate, baseline profile + **candidate geometry** + cluster orphans, orchestrator baseline ensure, persistence, map markers + table, availability; degraded via payload metadata |
| [#35](https://github.com/SteveDraper/Planets-Console/issues/35) | **Homeworld region overlay** paint: shared boundary `regionOverlays`, layout distribution asset, sector emission, display mode + hover ([ADR 0008](adr/0008-shared-map-region-overlays.md)) |
| [#36](https://github.com/SteveDraper/Planets-Console/issues/36) | Location evidence refine through shell turn; origin-distance + single-SB new-build; promotion; definite-neighborhood cull; layout prior **most probable**; FE markers/table cue |
| [#269](https://github.com/SteveDraper/Planets-Console/issues/269) | **Homeworld ownership evidence** (travel envelopes, sector possible-owner sets + provenance, planetary ownership sightings, minimal sector hover) -- not location promotion |
| [#37](https://github.com/SteveDraper/Planets-Console/issues/37) | User assertions, refresh, **homeworld locator panel**, attribution UX (may add decisive `user_asserted` provenance into the same owner set) |

### 11.1 Issue #34 phased plan

Hybrid phases (each independently reviewable):

1. **Pure domain** -- climate catalog (Crystal default 100°W; settings probe later), YAML config both fields, baseline profile matcher, cluster constraint scoring, circular+round candidate geometry (viewpoint definite + orphan ring sites). Unit tests only; no HTTP.
2. **Core wire-up** -- thin shared path helpers + homeworld persistence; game-global + floor evidence aggregate; orchestrator registration (no prior-turn self-chain; #36 adds it); baseline-only ensure; T1 auto-ensure inside baseline step; invalidation; availability; map/table GET materializing candidate view; amend ADR 0002; `configuration.md`.
3. **BFF + FE** -- descriptor/catalog/proxy, OpenAPI regen, enable toggle, definite vs possible markers, tabular tile + degraded note.

**Persistence ownership:** no generic analytic merge service -- thin shared primitives + homeworld-owned persistence (same pattern as scores/fleet).

### 11.2 Issue #35 phased plan

1. **Shared region boundary** -- discriminate `regionOverlays` coverage vs boundary; FE normalize + pane; MapGraph Visibility-pref isolation; ADR 0008; CONTEXT/design grill locks (this section / §4.2).
2. **Layout distribution asset** -- committed Normal mean/std plus empirical support extremes (epic/standard); loader; support extremes for paint band; ``-log`` density cost for layout prior. Shipped at `assets/analytics/homeworld-locator/layout_distributions.json` (schema v2). Regenerate: build gitignored `local/homeworld_distributions.json` from `local/sampled_homeworlds.csv` + `.sampler_data` via `scripts/visualize_homeworld_distributions.py`, then `… distill --report local/homeworld_distributions.json`.
3. **Core sector emission** -- annular sectors + envelopes on map GET when emission gate passes (`regionOverlays` boundary entries; FE display-mode filter is phase 4).
4. **FE display mode + hover** -- preference store, merge/filter, hit-test structured overlay facts; FE formats hover lines.

### 11.3 Issue #36 phased plan

1. **Location evidence domain** -- origin-distance matchers (non-grav 64/81; grav 128/162), location-deduped observations with match sets, single-SB new-build immediate promote; unit tests only.
2. **Evidence refine + orchestrator** -- `turn_delta=-1` self-chain; refine aggregate through shell turn; materialize promotion + co-sector cull + definite-neighborhood cull (`neighbor_separation.supportMin`); docs.
3. **Layout prior + most-probable** -- joint selection, stand-ins, `isMostProbable` on candidate view wire; Core tests (incl. game 680224-style empty nebular sector).
4. **FE markers + table cue** -- Zod `isMostProbable`; double dotted ring; tabular cue.

### 11.4 Issue #270 phased plan

Full plan: [plan-issue-270-layout-prior-budgeted-solver.md](plan-issue-270-layout-prior-budgeted-solver.md). ADR: [0009](adr/0009-homeworld-layout-prior-budgeted-solver.md). Follow-on launch consistency: [#273](https://github.com/SteveDraper/Planets-Console/issues/273).

1. **Encapsulate enumerator** -- `LayoutPriorSolver` boundary; shared cost outside solvers; `EnumeratingLayoutPriorSolver` (#36 behavior); no algorithm version bump; fixture selection parity.
2. **SA + sample-grid refine** -- greedy frontier init; seeded size-aware SA under pluggable stop-gate; alternating sample-grid stand-in refine + #273 scored-sample hook; default switch; bump `LAYOUT_PRIOR_ALGORITHM_VERSION`; tune `layout_prior_budget_ms` on dense maps.

### 11.5 Issue #269 phased plan

Grill locks: §4.3.2 (this doc). CONTEXT: **homeworld ownership evidence**, **homeworld sector owner set**.

1. **Ownership domain** -- ship age (fleet `built_turn` else id/scoreboard max age); travel envelopes (warp² / Grav / ignore HYP); sector reachable-set reduction; planetary preferred + nearby-162 ownership adds; pure helpers + unit tests (envelope pin, sighting merge, ambiguous multi-owner set). No HTTP.
2. **Evidence refine + materialize + fleet DAG** -- durable sector owner sets on the evidence aggregate; refine accumulation; **ENSURE fan-out to final `fleet@N` per roster player** + `DependencyOutputs` built_turn map; materialize apply after culls / before layout prior; unique-owner orphan bind; serialization + Core/orchestrator tests; docs/ADR amend as needed.
3. **Minimal FE** -- extend sector overlay wire facts + `formatHomeworldSectorHoverLine` (single owner vs **ambiguous** + possibles); normalize/tests. No panel.

---

## 12. Known gaps and edge cases

- No export field marks HW; do not assume `masterplanetid` is player HW without verification.
- Player churn: vacant slots, **KillRace**, replacements -- ownership at HW may not match original slot logic.
- Training/practice games: HW locations may differ between runs.
- Classic-only map-gen details may exist in Donovan/PHost docs not yet synthesized into repo docs.
- **`averagedensitypercent`:** documented as no effect on HW minerals; ignore for HW locator.

---

## Changelog

| Date | Note |
|------|------|
| 2026-06-01 | Initial doc from homeworld locator design review (grill session + Starmap settings handoff) |
| 2026-07-25 | Grill-with-docs for #34: orchestrator baseline chain; turn-scoped evidence aggregates + on-read candidate view; candidate geometry + cluster orphans in #34; overlays deferred to #35; phased plan §11.1 |
| 2026-07-25 | Planetoids (`debrisdisk == 1`) excluded from cluster neighbor counts and all homeworld candidacy |
| 2026-07-25 | #34 baseline: empty `ENSURE_DEPENDENCIES`; #36 adds `turn_delta=-1` self-chain for refine-through-T |
| 2026-07-26 | #35 grill locks: shared `regionOverlays` boundary ([ADR 0008](adr/0008-shared-map-region-overlays.md)); display mode; layout asset; §4.2 / §11.2 |
| 2026-07-26 | #35 phase 2: layout distribution asset path + regenerate via visualize/distill (§11.2) |
| 2026-07-26 | #35 phase 3: Core emits pin-oriented sector `regionOverlays` (asset band, planet-scan envelopes/error) on map GET |
| 2026-07-26 | #35: region overlay hover facts on wire (`candidateCount`, `playerLabel`); FE formats tooltip copy (ADR 0008) |
| 2026-07-26 | #36 grill: location vs ownership evidence split; layout prior most-probable + stand-ins; definite-neighborhood cull; phased plan §11.3; **homeworld owner** terminology |
| 2026-07-27 | Layout prior: fixed stand-in + ≤4 choices/sector (map GET hang on dense games); shell-turn versioned `layoutPriorSelection` persistence |
| 2026-07-28 | #270 grill: budgeted anytime layout prior; pure solver boundary; discrete greedy+seeded SA then sample-grid stand-in refine; keep enumerator as alternate impl; phase 1 encapsulate then phase 2 SA; ADR 0009; CONTEXT stand-in/selection updated |
| 2026-07-28 | #274: layout-prior solver run telemetry (homeworld-owned report ring + Diagnostics Homeworlds tab); distinct from compute diagnostics |
| 2026-07-28 | Sparse evidence-chain holes: clear ensure failure + login-backed auto-fetch of missing intermediate turns before refine |
| 2026-07-28 | Orphan sector envelopes center on layout-prior most-probable when annotated (align with markers); else closest-to-sector-mid |
| 2026-07-28 | Baseline: cull orphan candidates outside layout center-distance support band when sector overlays apply |
| 2026-07-28 | Layout-prior cost: Normal ``-log`` density (asset schema v2 mean/std) for neighbor + center; bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 4 |
| 2026-07-28 | Layout-prior SA: budget-progress temperature schedule (replace per-step geometric cool); bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 5 |
| 2026-07-28 | Default `layout_prior_budget_ms` raised to **1000** (dense-map basin escape under budget-progress cooling) |
| 2026-07-28 | SB-only hard definite: remove threshold `possible→definite`; layoutPriorSelection reuse ignores promotion threshold |
| 2026-07-28 | Soft origin-distance evidence: third layout-prior cost family ``E(S)`` with λ=0.8; `origin_distance_evidence_lambda` replaces `evidence_promotion_threshold`; bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 6 |
| 2026-07-29 | Soft evidence: absolute-turn update weights ``w(t)=λ^t`` (empty turns leave ``E`` unchanged); default λ=0.95; bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 7 |
| 2026-07-29 | Soft origin-distance evidence freezes at shared ship limit (scoreboard total ≥ ``shiplimit``); sticky ``originDistanceEvidenceThroughTurn``; bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 8 |
| 2026-07-29 | Ship-limit freeze cutoff from earliest scoreboard-history crossing (``T_limit - 1``), not ``shell - 1`` on late first observe; missing history turns fail ensure |
| 2026-07-29 | Layout-prior anneal continuity: two inline solves (prev-turn RNG seed + this-turn RNG seed), take best by cost/tie-key; bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 9 |
| 2026-07-29 | Layout-prior continuity: score admissible previous selection on current criteria; prefer when better than both anneals; bump `LAYOUT_PRIOR_ALGORITHM_VERSION` to 10 |
| 2026-07-29 | Projection win telemetry: dedicated layout-prior report with ``stopReason=projected`` matching returned cost/tie-key (do not reuse anneal SA report) |
| 2026-07-30 | Projection report honesty: ``projectedCost`` + ``finalCost`` for scored projection; anneal-phase ``greedyCost`` / ``preRefineCost`` null (not stuffed with projected cost) |
| 2026-07-29 | Layout-prior reuse includes config ``evidenceLambda`` with candidate ``inputFingerprint`` (λ retune forces recompute; no algorithm-version bump) |
| 2026-07-29 | Document dual-seed anneal + prior projection as deliberate continuity (this-seed variation, prev-seed dynamics, projection vs SA noise) -- not a single warm-start |
| 2026-07-30 | Layout-prior reuse includes ``evidenceFingerprint`` (SHA-256 of effective soft OD observations); observation identity change forces recompute; no algorithm-version bump |
| 2026-08-02 | #269 grill: sector **possible-owner sets** + provenance collections; ship age = fleet `built_turn` else id/scoreboard max age; envelope = turns×warp² (W9 default, Grav hulls only, ignore HYP); preferred + nearby-162 planet ownership adds; materialize after culls / before layout prior; minimal sector hover (ambiguous when multi); §11.5 |
| 2026-08-02 | #269: retract soft fleet ledger read -- race with open-turn fleet; hard DAG dep on final ``fleet@N`` per **all roster** players (`player_id` fan-out; ``None`` fleet ensure is a no-op) |
| 2026-08-02 | #269 Phase 2: ``player_id="all"`` ENSURE fan-out wired in export walk + compute DAG; ownership refine reads ``built_turn`` from ``DependencyOutputs`` fleet wires |
| 2026-08-02 | #269 invalidation wake deferred: open-turn race = DAG only; reverse-ENSURE invalidate + ``force_fresh`` (and scores/fleet refactor onto it) tracked in [#280](https://github.com/SteveDraper/Planets-Console/issues/280) |
| 2026-08-02 | #269: ``HOMEWORLD_EVIDENCE_ALGORITHM_VERSION`` (1) on evidence aggregates; stale version fails satisfaction and forces floor re-refine / DAG rewalk |
| 2026-08-02 | #269 Phase 3: sector ``possibleOwners`` (+ optional per-slot ``playerLabel``) on wire; FE normalize + hover unique vs **ambiguous** |
| 2026-08-02 | Ownership travel envelope: +1 LY/turn rounding slack (`travel_turns × (warp² + 1)`); bump `HOMEWORLD_EVIDENCE_ALGORITHM_VERSION` to 2 |
| 2026-08-02 | Sync ensure loads fleet `built_turn` from final on-disk ledgers after ENSURE; floor algo rewrite clears sticky ownership before re-accumulate; sole floor-rewrite owner; shared sector partition helper; bump `HOMEWORLD_EVIDENCE_ALGORITHM_VERSION` to 3 |
