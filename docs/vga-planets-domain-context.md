# VGA Planets / Planets.Nu — domain context for analytics

**Purpose:** Consolidated game-domain knowledge to inform analytic features (tabular + map), naming, and data modeling. This doc is **living**: append rows to [Sources](#sources) and short notes to [Changelog](#changelog) as you pull in more web sources over time.

**Primary wiki:** [VGA Planets Wiki — Main Page](https://vgaplanets.org/index.php?title=Main_Page)  
**Game client:** [planets.nu](https://vgaplanets.nu/) (browser implementation of VGA Planets).

---

## 1. Game in brief

- **VGA Planets** (VGAP): Tim Wisseman’s **turn-based** strategy game for **up to 11 players** (1992 BBS door → now email/web).
- **Objective:** Galactic conquest by expanding and holding planets; deep economy, combat, and race-specific abilities.
- **Planets.Nu:** Web implementation; exposes a **JSON API** so tooling can load **turn packages** (see §6). Wiki content is largely aimed at Nu but also applies to Host 3.22 where noted.

---

## 2. Player races (canonical names)

| Race (full) | Short forms | Notes |
|---------------|-------------|--------|
| Solar Federation | Federation, Fed | |
| Lizard Alliance | Lizard, Liz | |
| Empire of the Birds | Bird, Birdman | |
| Fascist Empire | Fascist, Klingon | |
| Privateer Bands | Privateer, Pirate | |
| Cyborg | Cyborg, Borg | |
| Crystal Confederation | Crystal, Tholian | |
| Evil Empire | Empire, EE | |
| Robotic Imperium | Robot, Cylon | |
| Rebel Confederation | Rebel | |
| Missing Colonies of Man | Colonies | Colonials |
| Horwasp Plague | Horwasp, Bugs | |

Use these when labeling viewpoints, diplomacy, or race-scoped analytics.

---

## 3. Core entities (what exists in the world)

Derived from wiki overview + **Load Turn** payload (§6). These are the natural dimensions for analytics.

| Entity | Role | Analytic hooks |
|--------|------|----------------|
| **Planet** | Nodes on the map; economy, colonization, development | Production, stockpiles, structure caps vs population, climate 0–100, **natives** (taxation, race abilities), **gravity/warp wells** (fuel, routing) |
| **Ship** | Movement, combat, missions | Position/track over turns, cargo, mission, cloak, combat outcomes |
| **Starbase** | Build/repair, tech | Queue, stock parts, defense |
| **Minefield** | Area denial | Placement, radius, owner — path risk |
| **Ion storm** | Dynamic hazard | Movement, strength — routing and survival |
| **Nebula / stars** | Map features | Visibility, movement modifiers (with add-ons) |
| **Relations / diplomacy** | Allies/enemies | Trade, combat posture |
| **Messages / notes** | Intel & coordination | Optional text analytics; not always structured |
| **VCR** | Combat recordings | Battle outcomes, ship losses |

**Economy / resources (typical):** megacredits, **minerals** (often tritanium, duranium, molybdenum, neutronium), **fuel**, colonists/clans, fighters, torpedoes. Structures scale with population (mines/factories/defense posts — see wiki *Planets* page for NU vs THOST rounding).

**Map:** Described as a **graph** in product terms: **planets as nodes**, **connections/routes as edges** — draggable, zoomable; scale slider in map mode. The console’s **Connections** analytic implements one-turn reachability (wells + flares) in [design-connections-analytic.md](design-connections-analytic.md).

---

## 4. Mechanic areas → analytic feature ideas

Wiki **Main Page** and **Categories** cluster topics; below maps them to useful console analytics.

| Area | Wiki anchors | Example analytics |
|------|--------------|-------------------|
| **Starships** | Starship Missions, Ship Movement, Ship Components, Ship List | Fleet disposition, mission breakdown, fuel reach, component gaps |
| **Planetary economics** | Planet, Starbases, Starbase Missions | Colonist growth, factory/mine efficiency, native taxation, build queues |
| **Tactics / combat** | VCR side advantage, Ship vs Ship, Mine Laying, Combat Order, Warp Wells, Cloak Intercept, Disguising movement | Threat corridors, mine coverage, intercept windows, warp-well routing |
| **Space hazards** | Ion storms, minefields, (nebular/stellar cartography) | Storm trajectories, safe lanes |
| **Racial abilities** | Race pages, Native Races, Hull Functions | Race-specific alerts (chunnel, hyperdrive, glory device, etc.) |
| **NuHost add-ons** | Artifacts, Wandering Tribes, Production Queue, Campaign, Stellar Cartography, Blitz, Explore Map | Feature flags per game; analytics gated or labeled by add-on |
| **Scores / military** | Military Score, scores in turn payload | Leaderboard-style trends, military vs economy balance |

### 4.1 Mechanic deep notes (condensed from wiki)

Short notes distilled from wiki pages for analytics/UI. Full pages may contain formulas and tables — use wiki links when implementing precise behavior.

#### Ship Movement
- **Fuel + engines:** Movement requires **fuel** and **engines** able to make the journey; fuel use scales with **total mass including cargo**.
- **Gravitonic Accelerator:** Three hulls move at **2×** normal rate; at warp 9 they travel **162 ly/turn** (Meteor BR, Br4 Gunship, Br5 Kaye).
- **Hyperdrive:** Pl21 Probe (EE), B200 Probe (Cyborg), Falcon Escort (Rebel) — **hyperjump** uses fixed-distance jump math (see wiki for ERND rounding).
- **Waypoints:** Shift+Click multiple waypoints; **visible only to self** — route planning analytics are player-private.
- **Fuel formulas:** THOST vs Nu/PHost differ (TRUNC vs ERND); see wiki for fuel-use expressions.
- **Wiki:** [Ship Movement](https://vgaplanets.org/index.php?title=Ship_Movement)

#### Military Score
- Shown on Planets.nu scoreboard; derived from **Autoscore**-style logic.
- **Interpretation:** Indicates what opponents are **building**, **ship size**, and **ammo** (fighters/torpedoes loaded also raise the score).
- **Rule of thumb:** **Larger score increment ⇒ larger ship built that turn** (and/or heavy fighter/torp load).
- **External tools:** Psydev spreadsheet / Python scripts to decode; Onebit Shipyard calculator; PlanetsCon 2021 talk — links on wiki page.
- **Wiki:** [Military Score](https://vgaplanets.org/index.php?title=Military_Score)

#### Mines / minefields
- **Mine Laying** redirects to **Minefields** on the wiki. Some mine-related pages currently **fail HTML render** (Math extension error on the server); use **API wikitext** or category lists if you need raw structure.
- **Mines** disambiguation: **Minefields** (space mines) vs **Planetary Structures** (mineral mines).
- **Load Turn** exposes `minefields` array — map/tabular analytics can layer **known minefields** per turn.
- **Wiki:** [Mines](https://vgaplanets.org/index.php?title=Mines) · [Minefields](https://vgaplanets.org/index.php?title=Minefields) (if HTML errors, use `api.php?action=parse&page=Minefields&prop=wikitext`)

---

## 5. Wiki structure (how to “walk” without crawling everything)

- **Special:AllPages** — alphabetical list of hundreds of pages (ship classes, abbreviations, mechanics).
- **Special:Categories** — curated buckets, e.g.:
  - **Ships** (100+ pages), **Space Objects**, **Space Hazards**, **Resources**, **Tactics**, **Weapons**, **Starship Components**, **Tech Levels**, **Player Races**, **Native Races**, **Racial Abilities**, **Hull Functions**, **Stellar Cartography**, **NuHost Addons**, **NuClient Addons**, **Alchemy Ships**, **Radiation immune ships**, etc.
- **Main Page** sections: Tutorials, Where To Play, Starships, Planetary Economics, Tactics, Mechanics (incl. **Planets.Nu API**), NuHost Add-ons.

Use category pages as **entry points** when adding a new analytic (e.g. “minefields” → Category:Tactics + Mine Laying + Minefields).

### 5.1 Appendix: category member lists (generated)

To **list every page in a category** without scraping HTML, use the repo script (stdlib only):

```bash
python scripts/list_vgaplanets_wiki_category.py --category Tactics
python scripts/list_vgaplanets_wiki_category.py --category Ships --output docs/wiki-category-ships.txt
```

Regenerate after wiki changes. Example **Category:Tactics** members (API snapshot): Disguising Ship Movement, Planetary Attack, Priority Intercept, Tow Capture, Wolfpack.

---

## 6. Planets.Nu API — turn payload (`rst`) for data-driven analytics

**Source:** [Planets.Nu API](https://vgaplanets.org/index.php?title=Planets.Nu_API).  
**Load Turn** returns a result object (`rst`) whose **top-level keys** define what the console can compute against:

| Key | Use for analytics |
|-----|------------------|
| `settings` | Game settings |
| `game` | Game metadata |
| `player` / `players` | Viewpoint + opponents |
| `scores` | Per-player score objects |
| `maps` | Pre-rendered map image URL (per player/turn) |
| `planets` | Planet array — economy, ownership, structures |
| `ships` | Ship array — positions, missions, cargo |
| `ionstorms` | Storm objects |
| `nebulas` | Nebula objects |
| `stars` | Star objects |
| `starbases` | Starbase array |
| `stock` | Loose parts at starbases |
| `minefields` | Minefield array |
| `relations` | Diplomatic relations |
| `messages` / `mymessages` | System + diplomatic messages |
| `notes` | Player notes on planets/ships/bases |
| `vcrs` | Combat recordings |
| `races` | Race definitions for the game |
| `hulls` / `racehulls` | Hull defs + race availability |
| `beams` / `engines` / `torpedos` | Component catalogs |

**Other API surfaces:** Login (apikey), List Games, Load Game Info — use for **header context** (game id/name, turn, schedule). Non-public endpoints exist; wiki notes encoding rules for query strings (`=` → `:::`, `&` → `|||`).

---

## 7. Conventions useful for UI copy

- **Turn**-based: analytics are **per turn** or **over turn range**.
- **Viewpoint** = which player’s fog-of-war / ownership lens (still one shared galaxy).
- **Friendly codes**, **missions**, **hulls** — domain terms appear in API and wiki; keep labels consistent with wiki where possible.

---

## 8. Sources (extensible)

Add one row per external source you incorporate. Keeps provenance for future contributors and AI context.

| Date | Source | What it contributes |
|------|--------|---------------------|
| — | https://vgaplanets.org/index.php?title=Main_Page | Races, game summary, wiki section index |
| — | https://vgaplanets.org/index.php?title=Planets.Nu_API | API surfaces, `rst` keys, object catalogs |
| — | https://vgaplanets.org/index.php?title=Planets | Planets overview, natives, economy formulas, climate |
| — | https://vgaplanets.org/index.php?title=Special:Categories | Category index for targeted deep-dives |
| — | https://vgaplanets.org/index.php?title=Ship_Movement | Fuel, gravitonic 2×, hyperdrive, waypoints |
| — | https://vgaplanets.org/index.php?title=Military_Score | Scoreboard military score interpretation |
| — | https://vgaplanets.org/index.php?title=Mines | Minefields vs planetary mineral mines |
| — | `api.php?action=query&list=categorymembers` | Programmatic category walks (see script) |
| | | *Add rows below* |

---

## 9. Changelog

| Date | Change |
|------|--------|
| 2025-03-12 | Initial doc: wiki main + API + categories + entity/mechanic map |
| 2025-03-12 | §4.1 mechanic notes (Ship Movement, Military Score, mines); §5.1 + script `list_vgaplanets_wiki_category.py` |

---

## 10. How to extend this doc

1. **After reading a wiki page:** add a bullet under the relevant §4 area or §3 entity, or add a one-line summary + URL in §8.
2. **After discovering a new API field:** add to §6 table.
3. **New mechanic add-on:** add under §4 and §8.
4. Keep **§8 Sources** authoritative — avoids stale duplicated prose.

This file is **not** a substitute for the wiki or API docs; it’s a **compressed map** so analytic features stay aligned with game reality and loadable data.
