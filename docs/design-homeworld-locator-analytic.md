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
| Other ring HW sites | Remaining geometric HW planets are **orphan homeworld candidates** (**possible**) -- do not cross-product bind them to rival slots in v1 baseline |
| Co-sector cull | Once a sector has a **definite** homeworld, drop other (inferred) possibles in that same angular sector; keep orphans in other sectors; never cull **user-asserted** rows |
| Single planet in sector | **Definite** when baseline weak but geometry leaves no plausible alternative in that slot's arc (stronger once overlays/#35 land) |

**Homeworld cluster constraint** (all map shapes that still have traditional HWs): count planets within 81 LY and within 81--162 LY; compare to `verycloseplanets` and `closeplanets`. Use this to construct **orphan** HW-like sites even when ring/sector math does not apply.

When no planet is pinned for a slot, [#35](https://github.com/SteveDraper/Planets-Console/issues/35) emits **homeworld region overlay** entries on shared **`regionOverlays`** (boundary geometry for equal angular sectors on the circular ring, plus optional 81/162 LY envelope disks). Grill locks for #35 paint:

| Lock | Rule |
|------|------|
| Emission gate | Only when `hwdistribution=2`, `mapshape=0`, game category epic\|standard, and a **viewpoint pin** fixes rotation -- then emit **all** `player_count` sector overlays; otherwise none (markers unchanged) |
| Wire | Shared **map region overlay** boundary primitive ([ADR 0008](adr/0008-shared-map-region-overlays.md)); not a homeworld-only field; not cartography `overlayCircles` |
| Band radii | From **homeworld layout distribution asset** smoothed center-distance support extremes |
| Envelopes | 81 + 162 LY disks when a sector center exists (candidate closest to sector geometric center = mid-angle at mid-radius; pinned planet when pinned; incomplete + no candidates → geometric band center; fully observed + zero candidates → no disks, error stroke + hover) |
| Sector paint | Stroke-only annular boundaries (no fill); FE display mode filters which sectors show |
| FE display | **Homeworld region display mode** (`off` \| `un-pinned` \| `pinned` \| `all`, default `un-pinned`) |
| Labels | No rival slot labels in #35 (assignment stays #37) |

Candidate geometry itself remains [#34](https://github.com/SteveDraper/Planets-Console/issues/34).

For non-circular or non-round maps: skip ring/sector math; still use baseline profile + **homeworld cluster constraint** + later evidence.

### 4.3 Homeworld inference evidence (later turns)

**Source:** **TurnInfo** stored at shell **viewpoint** **perspective** only -- not a union across all slots (**homeworld evidence scope**).

Append incrementally when new turns are stored beyond cached evidence horizon.

| Signal | Rule |
|--------|------|
| First ship sighting | Player's ships first seen near a cluster implicates that region as their HW area |
| Origin distance -- pod hop | Ship position **~81 LY** from a planet (standard pod range) suggests recent departure from that planet or an adjacent hop point |
| Origin distance -- warp | Ship **~warp 8 travel range** from planet (host-aligned; ~64 LY) -- same "just left home" intuition |
| Repeated independent hits | Multiple distinct evidence events promote **possible -> definite** when count >= YAML promotion threshold |

**Origin distances:** implement as **game concepts** (host physics), not YAML lists. Reuse movement geometry constants where they already exist in Core.

**Evidence does not replace baseline;** it adjusts confidence on candidates already hypothesized from baseline + geometry.

### 4.4 User assertion

**User-asserted** records use the same **homeworld candidate record** shape as inferred rows. Promotion to **definite**, slot assignment, or race tag with **user-asserted** attribution always wins over inference until revoked.

---

## 5. Confidence tiers

| Tier | When |
|------|------|
| **Definite** | Baseline profile match; OR geometry leaves no plausible alternative in allowed region; OR evidence promotion threshold met; OR **user-asserted** |
| **Possible** | Consistent with settings/spacing/evidence but not unique; default for **orphan homeworld candidates** |

Orphans: location-first candidates not yet tied to a **perspective** slot -- remain **possible** until anchored or confirmed.

---

## 6. Candidate output model

Two parallel output modes (**C** from design review):

1. **Slot-anchored** -- one candidate (planet and/or region) per **perspective** slot from **GameInfo**
2. **Orphan** -- planet or region that looks like a HW under heuristics but slot assignment is ambiguous

**Homeworld candidate record** (persisted and on the wire):

```
record_id
perspective?          # slot when slot-anchored
planet_id?            # when pinned to a planet
region?               # when only sector/envelope known
race_id?              # override or annotation
confidence_tier       # definite | possible
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

**Model:** durable **homeworld evidence aggregate** at each turn is refined from game-global inputs + aggregate at *T−1* + observations at *T*. The **homeworld candidate view** (tiers for map/table) is materialized on read from game-global state + aggregate at the shell turn -- not the primary durable artifact.

**Compute:** [#34](https://github.com/SteveDraper/Planets-Console/issues/34) registers baseline ensure with the **compute orchestrator** and an empty `ENSURE_DEPENDENCIES` (game-global floor; no prior-turn walk). A `turn_delta=-1` self-chain would require every intermediate turn to be stored before degraded→T1 baseline upgrade can run. [#36](https://github.com/SteveDraper/Planets-Console/issues/36) adds the linear self-chain (`homeworld@T` depends on `homeworld@(T−1)`) when shell-turn evidence refine/copy-forward is in scope. **Ensure baseline** is turn 1 (or degraded earliest); [#34](https://github.com/SteveDraper/Planets-Console/issues/34) does **not** copy-forward empty aggregates through the shell turn.

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
| Evidence promotion threshold | Independent evidence hits required for **possible -> definite** |

Origin distances (81 LY pod, warp table) stay in **game concepts**.

---

## 10. Map and UI behavior

| Element | Behavior |
|---------|----------|
| **Homeworld map marker** | Decoration on **base map** node -- solid = definite, dashed/light = possible |
| **User-asserted definite** | Same definite marker + attribution cue (border/badge) |
| **Homeworld region overlay** | Shared **map region overlay** boundary sectors (+ optional envelopes) for Circular round; filtered by **homeworld region display mode** |
| **Homeworld locator panel** | Sidebar table + refresh + degraded baseline warning |
| Map context menu | Quick **homeworld assertion** |
| Tabular tile | Same rows as panel in main **tabular** **view mode** |
| **Homeworld region display mode** | Sidebar expandable control (Cartography pattern); global preference |

---

## 11. Implementation slices (issues)

| Issue | Delivers |
|-------|----------|
| [#34](https://github.com/SteveDraper/Planets-Console/issues/34) | Config, race climate, baseline profile + **candidate geometry** + cluster orphans, orchestrator baseline ensure, persistence, map markers + table, availability; degraded via payload metadata |
| [#35](https://github.com/SteveDraper/Planets-Console/issues/35) | **Homeworld region overlay** paint: shared boundary `regionOverlays`, layout distribution asset, sector emission, display mode + hover ([ADR 0008](adr/0008-shared-map-region-overlays.md)) |
| [#36](https://github.com/SteveDraper/Planets-Console/issues/36) | Evidence aggregate refine through shell turn, origin-distance signals, promotion |
| [#37](https://github.com/SteveDraper/Planets-Console/issues/37) | User assertions, refresh, **homeworld locator panel**, attribution UX |

### 11.1 Issue #34 phased plan

Hybrid phases (each independently reviewable):

1. **Pure domain** -- climate catalog (Crystal default 100°W; settings probe later), YAML config both fields, baseline profile matcher, cluster constraint scoring, circular+round candidate geometry (viewpoint definite + orphan ring sites). Unit tests only; no HTTP.
2. **Core wire-up** -- thin shared path helpers + homeworld persistence; game-global + floor evidence aggregate; orchestrator registration (no prior-turn self-chain; #36 adds it); baseline-only ensure; T1 auto-ensure inside baseline step; invalidation; availability; map/table GET materializing candidate view; amend ADR 0002; `configuration.md`.
3. **BFF + FE** -- descriptor/catalog/proxy, OpenAPI regen, enable toggle, definite vs possible markers, tabular tile + degraded note.

**Persistence ownership:** no generic analytic merge service -- thin shared primitives + homeworld-owned persistence (same pattern as scores/fleet).

### 11.2 Issue #35 phased plan

1. **Shared region boundary** -- discriminate `regionOverlays` coverage vs boundary; FE normalize + pane; MapGraph Visibility-pref isolation; ADR 0008; CONTEXT/design grill locks (this section / §4.2).
2. **Layout distribution asset** -- committed smoothed percentile tables (epic/standard); loader; support extremes for paint band. Shipped at `assets/analytics/homeworld-locator/layout_distributions.json`. Regenerate: build gitignored `local/homeworld_distributions.json` from `local/sampled_homeworlds.csv` + `.sampler_data` via `scripts/visualize_homeworld_distributions.py`, then `… distill --report local/homeworld_distributions.json` (Laplace on trimmed 10 LY bins → percentile grid + `supportMin`/`supportMax`).
3. **Core sector emission** -- annular sectors + envelopes on map GET when emission gate passes (`regionOverlays` boundary entries; FE display-mode filter is phase 4).
4. **FE display mode + hover** -- preference store, merge/filter, hit-test `hoverSummary`.

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
