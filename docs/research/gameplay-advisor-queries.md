# Gameplay-shaped advisor query families

Research for [issue #312](https://github.com/SteveDraper/Planets-Console/issues/312). Sources: Personal-wiki vault (`Personal-wiki/Personal-wiki/wiki/`), preferring Planets.nu over classic. This document lists **candidate query-shaped capabilities** -- not a v1 MCP catalog.

## Why not raw TurnInfo JSON?

Turn snapshots are necessary but a poor sole interface for an advisor or playing agent. Many decisions depend on **geometry, host order, and table lookups** that are cheap and exact in code but error-prone in LLM reasoning: rounding movement endpoints, nebula-modulated visibility, minefield FC precedence, queue-type identification, and same-turn interaction chains (move → glory → chunnel → combat). Query families below expose **derived facts** the host already implies from turn data plus static catalogs (hulls, engines, beams).

---

## 1. Map geometry and reachability

**Game facts**

- Map coordinates use **light-year** Euclidean distance (`wiki/concepts/planets-nu/Light year (Planets.nu).md`).
- **One-turn movement** is not a simple `warp²` disk: HOST-family rounding yields **exact** and **inexact** (overshot waypoint) arrivals slightly past the nominal cap; Nu matches classic for this geometry (`wiki/concepts/planets-nu/Evasion points (Planets.nu).md`, `raw/Authoritative/planets-nu-movement-geometry-matches-classic.md`). Stefan Reuther HOST 3.22.046 tables in `raw/stefan-reuther-movement-host322046/` enumerate relative `(dx,dy)` → `(mx,my)` outcomes.
- **Evasion points / flares**: long-move waypoints in ~80–86 ly bands (warp 9 normal; ~2× for Gravitonic) expose three candidate endpoints (outer/middle/inner) used to break tow or evade co-located intercept (`wiki/concepts/planets-nu/Evasion points (Planets.nu).md`).
- **Planet pair reachability** for logistics: direct travel within `warp²` ly plus optional **flare-chain** connections when waypoints fall in flare annuli (`wiki/concepts/planets-nu/Map (Planets.nu).md` via Connections concept).
- **Warp wells**: 3 ly radius pull when a **traveling** ship ends inside; **warp 1** movement exempt; hyperjump uses a **±2 ly box** not the full circle (`wiki/concepts/planets-nu/Warp wells (Planets.nu).md`). Wells checked per ship after tow, normal move, and intercept substeps -- before glory devices (`wiki/concepts/planets-nu/Host (Planets.nu).md`).
- **Stellar Cartography** adds route modifiers: black-hole ergosphere warp caps and hyperjump bending, neutron-cluster movement bonuses, star-cluster lethal halos, wormholes (`wiki/concepts/planets-nu/Stellar Cartography (Planets.nu).md`, `wiki/concepts/planets-nu/Black holes (Planets.nu).md`, `wiki/concepts/planets-nu/Neutron star clusters (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `distance_ly(a, b)` | How far apart are these two map points? |
| `movement_endpoints(origin, warp, engine_class)` | Where can this ship end this turn (exact/inexact set)? |
| `flare_points(origin, warp, gravitonic?)` | What evasion endpoints exist for break-tow / intercept dodge? |
| `reachable_planets(origin, warp, options)` | Which planets are one-turn reachable (direct + flare depth)? |
| `in_warp_well(planet, point, well_kind)` | Is this cell in normal vs hyperjump well geometry? |
| `warp_well_cells(planet)` | Enumerate well cells for overlay / path checks |
| `terrain_sample_at(x, y)` | Stack SC features, radiation, neutrino bonus, BH warp cap at cell |
| `safe_warp_through(point, route)` | Max warp allowed through BH ergosphere segment |

**Console overlap**

- `api/concepts/warp_well.py` -- point-in-well, cell enumeration, debris-disk exceptions.
- `api/concepts/planet_connections/` -- pair reachability, flare BFS, annuli.
- `api/concepts/flare_points.py` -- static evasion tables (regular vs gravitonic).
- `api/concepts/stellar_cartography/` -- `sample_at`, `turn_summary`, `black_holes`, `star_clusters`, `nebula_visibility.distance_ly`.
- Turn concept HTTP: warp-well coordinate/cells, stellar-cartography sample/summary.

**Gaps**

- Full **multi-segment route planning** with terrain (BH bend, wormhole transit, ion push) not unified in one concept module.
- **Wormhole** endpoint pairing and detection rules thin in vault (`wiki/concepts/planets-nu/Wormholes (Planets.nu).md` not deeply synthesized).

---

## 2. Visibility, scan, and fog of war

**Game facts**

- **Explore Map** (when enabled) limits default planet/ship visibility until explored (`wiki/concepts/planets-nu/Explore Map (Planets.nu).md`).
- **Nebulae** impose per-cell visibility factor `V(P)` from summed density; cloaking decloak rules; bioscan/sensor caveats; mine **detection** range is **not** reduced by nebula fog (`wiki/concepts/planets-nu/Nebulae (Planets.nu).md`, `raw/planets-nu-help/nebulas/body.html`).
- **Sensor Sweep** / bioscan missions and default **minefield detect** ranges (~200 ly defaults in Console code; host settings may override).
- **Share Intel** / Full Alliance extends visibility to partner empires (`api/concepts/diplomacy.py`, visibility analytic).
- **Cloaked** ships hidden unless decloaked or within scan range; many decloak triggers (Loki, ion, nebula, glory timing) (`wiki/concepts/planets-nu/Cloaking (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `nebula_density(x, y)` / `visibility_ly(x, y)` | What scan range applies at this cell? |
| `can_see_ship(viewer, ship_id)` | Is this ship visible to viewpoint (scan + diplomacy)? |
| `can_see_planet(viewer, planet_id)` | Planet visible or nebula-fogged? |
| `sensor_sweep_coverage(ship)` | Disk if ship runs sensor sweep this turn |
| `minefield_detect_coverage(ship)` | Ideal disk for lay-mines / sweep detect mission |
| `intel_partners(viewpoint)` | Whose units count as friendly for scan overlays |
| `decloak_risk(ship, route)` | Nebula/ion/storm cells on path that force decloak |

**Console overlap**

- `api/concepts/stellar_cartography/nebula_visibility.py` -- density, `V(P)` formula (4000/(density+1), cap 250 ly).
- `api/concepts/visibility_coverage.py` -- hybrid overlays: ship-scan, sensor-sweep, minefield-detect kinds; nebula modulation; disk-only mine detect.
- `api/analytics/visibility.py` -- wires coverage for Visibility analytic.
- Turn concept: stellar-cartography `sample_at` includes nebula visibility tooltip math.

**Gaps**

- Vault lacks a single **canonical scan-range table** per hull/scanner type; Explore Map old vs new defaults only summarized.
- **Per-ship passive scan radius** from hull/scanner not clearly documented in vault pages reviewed.

---

## 3. Movement, fuel, and towing

**Game facts**

- Movement requires fuel + engines; burn scales with **total mass** (hull + cargo); Nu behaves like PHost vs THost truncation (`wiki/concepts/planets-nu/Fuel (Planets.nu).md`, `wiki/concepts/planets-nu/Ship movement (Planets.nu).md`).
- Client fuel estimates can diverge (towing mass, cloak fuel, multi-waypoint, foreign interactions) (`raw/planets-nu-help/FuelEstimateErrors/body.html`).
- **Towing**: ≥2 engines; ID order for contested tow; towed ship forced warp 0; break tow needs ≥25 kt fuel (can arrive same turn), long waypoint **strictly > warp²** ly, warp ≥ tower (`wiki/concepts/planets-nu/Towing (Planets.nu).md`). Gravitonic doubles warp for **establishing** tow lock, not breaking.
- **Hyperjump (HYP)**: specific hulls + FC `HYP` + warp>0 + waypoint >20 ly + ≥50 kt fuel; landing ~350 ly along course or exact if waypoint 340–360 ly (`wiki/concepts/planets-nu/Hyperdrive (Planets.nu).md`; Console `hyperjump.py`).
- **Host order** after movement: intercept → glory → chunnel → … → ship combat (`wiki/concepts/planets-nu/Host (Planets.nu).md`, `raw/planets-nu-help/host-order/body.html`). Advisors must not chain "move then chunnel" without this ordering.
- **Out of fuel** resets missions and immobilizes (`wiki/concepts/planets-nu/Out of Fuel (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `fuel_to_move(ship, route, warp)` | Host-aligned burn for planned movement |
| `can_reach_with_fuel(ship, waypoint)` | Feasible after fuel math |
| `tow_break_feasible(towed, tower, warp)` | Long waypoint + fuel + warp vs tower warp/Gravitonic |
| `tow_conflict_resolution(towers, target)` | Which tower wins by ID |
| `hyperjump_landing(ship)` | Estimated HYP endpoint before well pull |
| `movement_phase_outcome(orders)` | Ordered substeps: tow lock, move, intercept, well pull |
| `host_order_slice(mech)` | When does glory/chunnel/combat relative to this action? |

**Console overlap**

- `api/concepts/hyperjump.py` -- HYP activation checks, landing estimate.
- `api/concepts/hull_abilities.py` -- Gravitonic movement, hyperjump hull flag.
- `api/concepts/planet_connections/` -- `max_travel_distance`, well-aware pairing.
- Fleet motion wire uses movement concepts; fuel burn formula **not** centralized in `concepts/` yet.

**Gaps**

- **Authoritative fuel burn** codec in `concepts/` -- vault documents formula family but Console does not expose a single fuel-query helper.
- **Ion storm push** displacement on movement -- forum nuance, not vault-canonical tables.
- **Firecloud chunnel** pairing rules -- referenced in host order but no dedicated vault atomic page in spotlight set.

---

## 4. Minefields and web mines

**Game facts**

- Laying: torpedo tech splits torpedoes into mines; radius from count; allied merge; `miX` lays under another identity (`wiki/concepts/planets-nu/Minefields (Planets.nu).md`).
- **FC**: field FC follows **nearest planet** to center; global `MFx` from **highest planet ID** among owner's `MFx` planets (`wiki/concepts/planets-nu/Friendly codes (Planets.nu).md`).
- Matching FC → **no mine hits** while moving; cannot beam-sweep enemy field with matching FC.
- Overlapping **normal** hostile fields: default **mines destroy mines**; **not** for web overlap (`raw/planets/wiki/Host Configuration__143.mediawiki`).
- Triggers: per-ly traveled; lower if cloaked; damage scales with hull mass; web mines higher trigger + stuck/fuel themes (`wiki/concepts/planets-nu/Web mines (Planets.nu).md`).
- **Ion storms**: scoop may work inside storm when beam sweep blocked; storm center on field can hide/block sweep (forum + Donovan; verify per game) (`wiki/concepts/planets-nu/Ion storms (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `minefield_radius(count, tech)` | Field extent from mine count |
| `mine_hit_risk(route, fields, ship_fc, cloak?)` | Expected hits per ly traveled |
| `effective_field_fc(field, planets)` | Resolved FC including MFx global rule |
| `safe_passage_fc(owner, ally_id)` | FC needed to transit without hits |
| `countermine_overlap(enemy_field, lay_plan)` | Net mine destruction from overlap |
| `sweep_rate(ship, field_type)` | Beam/fighter sweep capacity |
| `web_stuck_risk(ship, route)` | Web trigger exposure |

**Console overlap**

- Visibility analytic: minefield **detect** disks (not hit simulation).
- Homeworld / inference code references mine patterns; no dedicated minefield geometry concept module.

**Gaps**

- Vault documents behaviors but **numeric trigger/hit formulas** live in export wikitext (`raw/planets/wiki/Minefields__565.mediawiki`) -- not extracted into vault summary tables.
- No in-process **mine hit simulator** in Console `concepts/`.

---

## 5. Ion storms and moving hazards

**Game facts**

- Stellar Cartography: storms are non-circular, voltage varies within, less frequent (`wiki/concepts/planets-nu/Ion storms (Planets.nu).md`, `raw/planets/wiki/Stellar Cartography__407.mediawiki`).
- Storms move **before ships**; push, decloak, damage phases (`raw/planets.flarum/Tactics/61-use-of-ion-storms/` -- player-tested; confirm vs `help.planets.nu`).
- Star cluster contact destroys storm; nebula weakens storm intensity (`wiki/concepts/planets-nu/Star clusters (Planets.nu).md`, Nebulae page).
- Priority Intercept Attack **not blocked** by ion storms or nebulae (`raw/planets/wiki/Priority Intercept__51.mediawiki`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `ion_voltage_at(x, y, turn)` | Voltage at cell (cloudy vs simple model) |
| `storm_cells_at(turn)` | Occupied cells / forecast position |
| `ion_decloak_risk(ship)` | Starts/ends in storm effect |
| `minesweep_blocked(ship, storm)` | Beam sweep vs scoop inside storm |
| `storm_minefield_interaction(field, storm)` | Hidden center / unsweepable cases |

**Console overlap**

- `api/concepts/stellar_cartography/sample_at.py` -- ion voltage at cell, storm class names.
- `api/concepts/stellar_cartography/turn_summary.py` -- ion storm count / mode flags.
- Turn concept: stellar-cartography summary endpoint.

**Gaps**

- **Storm movement forecast** (next-turn position) not in Console.
- Phase timing vs cloak missions -- forum-heavy; vault marks as verify against host docs.

---

## 6. Combat and battle assessment

**Game facts**

- **VCR** playback is post-hoc; fights are 1v1 in recorder (`wiki/concepts/planets-nu/VCR (Planets.nu).md`).
- Phase order: fighters launch → beams vs fighters → torpedoes vs ships/planets → beams vs ships/planets; **left/right** side advantages for carriers vs torpedo ships (`raw/planets/wiki/VCR__686.mediawiki`).
- **Ground combat** separate from VCR: clan assault vs defence posts; race multipliers (Lizard, Fascist exceptions) (`wiki/concepts/planets-nu/Ground combat (Planets.nu).md`).
- **Imperial Assault** (SSD hull) and multi-ship drop ordering by ship ID (`wiki/concepts/planets-nu/Imperial Assault (Planets.nu).md`).
- Matching FC usually avoids combat except `MKT`, `NTP`, `LFM` (ships) and `ATT`, `NUK` (planets) (`wiki/concepts/planets-nu/Friendly codes (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `combat_will_occur(ship_a, ship_b, fcs)` | FC exceptions to no-combat rule |
| `ground_assault_outcome(clans, def, race_mult)` | Ground combat resolution inputs |
| `vcr_side_advantage(hull_a, hull_b)` | Left/right carrier vs torp bias |
| `battle_odds(ship_a, ship_b, context)` | Win probability / expected damage |
| `construction_value(hull, fit)` | Military economic weight of a build |

**Console overlap**

- `api/concepts/ship_build_military.py` -- construction value, warship vs freighter scoreboard classification.
- Military score inference analytics use military deltas; not full combat simulation.
- `api/concepts/races.py`, `hull_abilities.py` -- race/hull combat-adjacent rules (fighters, intercept interference).

**Gaps**

- Vault is **thin on deterministic battle odds** -- no AutoBattle-style formula pages synthesized. Combat resolution math remains in export combat articles, not vault-ready query tables.
- **Full VCR simulation** would be a large host-aligned subsystem; not present in Console.

---

## 7. Economy, builds, and planetary development

**Game facts**

- Four queue families: **PBP** (hard limit), **PQ** (soft 500), **PPQ** (default Standard 2021+, planet-share regular builds), **PLS** (per-player caps) -- identify from game settings (`wiki/concepts/planets-nu/Build queues (Planets.nu).md`).
- Queue FCs: `pbN` priority order; PPQ `RB#` for regular-build starbase targeting.
- **Ship limit** hard vs soft; Horwasp exceptions; PLS per-player (`wiki/concepts/planets-nu/Ship limit (Planets.nu).md`).
- **Tech tracks** (hull/engine/beam/torpedo) gate components at starbases (`wiki/concepts/planets-nu/Tech levels (Planets.nu).md`).
- **Overpopulation**: supplies burn, structure decay at 3/turn (`wiki/concepts/planets-nu/Planetary development (Planets.nu).md`, `raw/planets-nu-help/Overpopulation/body.html`).
- Neutron-cluster halo: **−1 PP** for priority builds at starbases inside neutrino radiation (`wiki/concepts/planets-nu/Neutron star clusters (Planets.nu).md`).
- Starbase types: standard vs debris-disk vs radiation-shielded costs (`wiki/concepts/planets-nu/Stellar Cartography (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `queue_type(settings)` | PBP / PQ / PPQ / PLS from settings fields |
| `pp_cost(starbase, hull, terrain?)` | Priority build PP including neutron bonus |
| `regular_build_eligibility(starbase, queue_type)` | Will this base get a regular build slot? |
| `ship_limit_headroom(player)` | Slots remaining under active limit model |
| `tech_unlocks(starbase_levels)` | What hulls/components can this base build |
| `build_cost(hull, components, base_type)` | MC + minerals for ship or base upgrade |
| `terraform_steps(planet, target_temp)` | Turns/cost to reach climate goal |
| `overpopulation_risk(planet)` | Supply burn / structure decay trajectory |
| `native_tax_revenue(planet, rate_mode)` | MC from natives under tax mode |

**Console overlap**

- `api/concepts/ship_limit.py`, `homeworld_ship_limit_soft_evidence` tests.
- `api/concepts/accelerated_scoreboard.py` -- accelerated start floors.
- `api/concepts/ship_build_military.py` -- construction value for inference.
- `api/concepts/game_category.py` -- campaign vs standard category.
- Analytics: homeworld locator, military score inference -- economy-adjacent but not general build planner.

**Gaps**

- **PP earning rates** and lottery weights for PQ/PPQ -- help pages cited in vault but not tabulated for query API.
- **Planet-side MC/mineral income** formulas -- primarily in `raw/planets/wiki/Planets__623.mediawiki`, not distilled into vault query tables.
- **Starbase component build** mineral/MC tables not in `concepts/`.

---

## 8. Diplomacy, friendly codes, and special missions

**Game facts**

- FC drives mine scoop (`msc`), lay-as-other (`miX`), mine global FC (`MFx`), queue control (`pbN`, `RB#`), HYP, glory `POP`/`TRG`, `NUK` fuelless take, `BUM` cloaker bait with floor-split rounding (`wiki/concepts/planets-nu/Friendly codes (Planets.nu).md`, `raw/Authoritative/planets-nu-bum-floor-split-rounding.md`).
- **Super Spy Deluxe**: Bird FC change on enemy planet; ion pulse risk with defence posts (`wiki/concepts/planets-nu/Super Spy Deluxe (Planets.nu).md`).
- **Race missions** gated on native hull lists, not arbitrary captured hulls (`wiki/concepts/planets-nu/Race missions and hull eligibility (Planets.nu).md`).
- **Hull abilities** survive trade/capture unlike pure racial rules (`wiki/concepts/planets-nu/Hull abilities (Planets.nu).md`).

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `fc_behavior(code)` | What does this FC do on ship/planet/base? |
| `mission_eligible(ship, mission)` | Race + hull list + ability gates |
| `bum_detects_cloakers(planet, foreign_ships)` | Floor-split MC beam per foreign ship |
| `spy_deluxe_effects(bird_ships, target_planet)` | FC change + ion pulse risk |
| `share_intel_partners(viewpoint)` | Diplomatic visibility partners |

**Console overlap**

- `api/concepts/diplomacy.py` -- share intel partner IDs.
- `api/concepts/ship_missions.py` -- mission classification helpers.
- `api/concepts/hull_abilities.py` -- hull-stamped capabilities.

**Gaps**

- No unified **FC catalog query** surfacing help-mirror semantics.
- Race mission eligibility matrix not exposed as concept API.

---

## 9. Host order and same-turn interaction chains

**Game facts**

- Nu help host-order list is vault-primary for tactical inference (`wiki/concepts/planets-nu/Host (Planets.nu).md`).
- Critical chains: warp-well pull per move → glory before chunnel → combat after specials; tow lock timing vs cloak; ground combat in cargo-drop stage with Imperial Assault ordering.

**Candidate queries**

| Query shape | Example question |
|-------------|------------------|
| `host_order_index(phase_name)` | Relative ordering of two mechanisms |
| `same_turn_valid(plan)` | Does "move + chunnel + escape combat" work this turn? |
| `glory_pop_timing(target, interceptor)` | W1 well dodge vs W2+ intercept strand |

**Console overlap**

- Documented in vault cross-links; **no** `api/concepts/host_order.py` module.

**Gaps**

- Host order as **queryable timeline** would help advisors most; entirely missing from Console concepts.

---

## Cross-cutting priorities for advisors

Ordered by "LLM gets this wrong often" and vault + Console readiness:

1. **Movement endpoints + evasion + wells** -- high tactical value; strong Console foundation.
2. **Visibility / nebula V(P) + mine detect** -- fog-of-war reasoning; partial Console coverage.
3. **Minefield FC resolution + safe passage** -- cheap graph logic; weak Console mine simulation.
4. **Fuel burn + tow break feasibility** -- high value; fuel math gap in concepts.
5. **Queue type + PP/ship-limit headroom** -- economic planning; partial via ship_limit.
6. **Host order chains** -- prevents invalid multi-step plans; vault-only today.
7. **Combat odds** -- high advisor demand; vault and Console both thin.

---

## References (vault paths)

| Topic | Wiki path |
|-------|-----------|
| Hub | `wiki/concepts/planets-nu/Planets.nu.md` |
| Map / LY | `wiki/concepts/planets-nu/Map (Planets.nu).md`, `wiki/concepts/planets-nu/Light year (Planets.nu).md` |
| Movement | `wiki/concepts/planets-nu/Ship movement (Planets.nu).md`, `wiki/concepts/planets-nu/Long move (Planets.nu).md`, `wiki/concepts/planets-nu/Evasion points (Planets.nu).md` |
| Wells | `wiki/concepts/planets-nu/Warp wells (Planets.nu).md` |
| Towing | `wiki/concepts/planets-nu/Towing (Planets.nu).md` |
| Fuel | `wiki/concepts/planets-nu/Fuel (Planets.nu).md` |
| HYP | `wiki/concepts/planets-nu/Hyperdrive (Planets.nu).md` |
| Stellar Cartography | `wiki/concepts/planets-nu/Stellar Cartography (Planets.nu).md`, Nebulae, Black holes, Ion storms, Neutron star clusters pages |
| Visibility | `wiki/concepts/planets-nu/Nebulae (Planets.nu).md`, `wiki/concepts/planets-nu/Explore Map (Planets.nu).md`, `wiki/concepts/planets-nu/Cloaking (Planets.nu).md` |
| Mines | `wiki/concepts/planets-nu/Minefields (Planets.nu).md`, `wiki/concepts/planets-nu/Web mines (Planets.nu).md` |
| Combat | `wiki/concepts/planets-nu/VCR (Planets.nu).md`, `wiki/concepts/planets-nu/Ground combat (Planets.nu).md` |
| Economy | `wiki/concepts/planets-nu/Economy (Planets.nu).md`, `wiki/concepts/planets-nu/Build queues (Planets.nu).md`, `wiki/concepts/planets-nu/Ship limit (Planets.nu).md`, `wiki/concepts/planets-nu/Tech levels (Planets.nu).md`, `wiki/concepts/planets-nu/Planetary development (Planets.nu).md` |
| FC / diplomacy | `wiki/concepts/planets-nu/Friendly codes (Planets.nu).md`, `wiki/concepts/planets-nu/Super Spy Deluxe (Planets.nu).md` |
| Host order | `wiki/concepts/planets-nu/Host (Planets.nu).md` |
| Authoritative | `raw/Authoritative/planets-nu-movement-geometry-matches-classic.md`, `raw/Authoritative/planets-nu-bum-floor-split-rounding.md` |
