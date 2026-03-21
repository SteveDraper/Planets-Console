# Design: Planets API data model and Core API routes (Enhancement #7)

**Source:** [GitHub Issue #7 – [Feature] Add data model for Planets API](https://github.com/SteveDraper/Planets-Console/issues/7)

This document describes the design for adding Python dataclass models for the entities returned by the Planets.nu public API, serialization/deserialization codecs, and Core API routes to serve game and turn data. **Implementation is out of scope** for this doc; it is a design and acceptance reference only.

---

## 1. Goal (from the issue)

- Model all data returned by the **Load Game Info** and **Load Turn Data** APIs (defined in the [Planets.nu API wiki](https://vgaplanets.org/index.php/Planets.Nu_API)).
- Define Python `@dataclass` classes for every entity, using `Enum` types where values come from a known finite set.
- Provide serialization/deserialization via `dacite` with explicit codecs for non-JSON-native fields.
- Model the **Load Game Info** response as `GameInfo` and the **Load Turn Data** result object (`rst`) as `TurnInfo`.
- Add Core API routes: `/api/v1/games/{id}/info` (returns `GameInfo`) and `/api/v1/games/{id}/{perspective}/turns/{number}` (returns `TurnInfo`).
- For now, routes serve **dummy data** loaded from static JSON assets to avoid polluting application code.

---

## 2. Scope

| In scope | Out of scope |
|----------|--------------|
| Dataclass models for all Planets API entities | Fetching live data from planets.nu servers |
| Enum types for known finite-value fields | BFF or frontend changes |
| Serialization codecs in `packages/api/serialization/` | Analytics or derived computations |
| Core API routes for game info and turn data | Real storage persistence (entities stored via the existing store) |
| Static JSON assets for dummy responses | Authentication or API key handling |
| Unit tests for models, codecs, and routes | Load Game Info fetching (only the response shape) |

---

## 3. Data sources and field inference

The authoritative sources for entity schemas are:

1. **Planets.nu API wiki:** [Planets.Nu_API#References](https://vgaplanets.org/index.php/Planets.Nu_API#References) — documents entity fields, types, and semantics.
2. **Example payload:** `assets/turn.json` — a real `rst` object from game 628580 turn 111, providing ground-truth field names and types where the wiki is incomplete or ambiguous.

Where the wiki omits a field or leaves its type unclear, the implementation should infer from the example payload. Fields present in the payload but absent from the wiki should still be modelled (the payload is the contract).

---

## 4. Top-level response models

### 4.1 `GameInfo`

Models the response of **Load Game Info** (`GET /game/loadinfo?gameid=...`).

```python
@dataclass
class GameInfo:
    game: Game
    players: list[Player]
    relations: list[Relation]
    settings: GameSettings
    schedule: str
    timetohost: str
    wincondition: str
    yearfrom: int
    yearto: int
```

### 4.2 `TurnInfo`

Models the `rst` object returned by **Load Turn Data** (`POST /game/loadturn`). This is the primary data structure for analytics.

```python
@dataclass
class TurnInfo:
    settings: GameSettings
    game: Game
    player: Player
    players: list[Player]
    scores: list[Score]
    maps: list[str]
    planets: list[Planet]
    ships: list[Ship]
    ionstorms: list[IonStorm]
    nebulas: list[Nebula]
    stars: list[Star]
    starbases: list[Starbase]
    stock: list[StockItem]
    minefields: list[Minefield]
    relations: list[Relation]
    messages: list[Message]
    mymessages: list[Message]
    notes: list[Note]
    vcrs: list[Vcr]
    races: list[Race]
    hulls: list[Hull]
    racehulls: list[int]
    beams: list[Beam]
    engines: list[Engine]
    torpedos: list[Torpedo]
    advantages: list[Advantage]
    activebadges: list[Badge]
    badgechange: bool
```

Additional collections visible in the payload but empty in the sample (`blackholes`, `artifacts`, `wormholes`, `cutscenes`) should also be modelled with placeholder dataclasses or typed as `list[dict]` initially, upgraded to full dataclasses when real data becomes available.

---

## 5. Entity dataclasses

All dataclasses go in `packages/api/models/`. One file per logical group is preferred (e.g. `game.py`, `planet.py`, `ship.py`, `components.py`) with an `__init__.py` that re-exports all public types.

### 5.1 File organization

| Module | Contains |
|--------|----------|
| `game.py` | `Game`, `GameSettings`, `GameInfo`, `TurnInfo` |
| `player.py` | `Player`, `Score`, `Relation`, `Badge`, `Advantage` |
| `planet.py` | `Planet` |
| `ship.py` | `Ship`, `ShipHistory` |
| `starbase.py` | `Starbase`, `StockItem` |
| `components.py` | `Hull`, `Beam`, `Engine`, `Torpedo` |
| `space.py` | `IonStorm`, `Minefield`, `Nebula`, `Star` |
| `comms.py` | `Message`, `Note`, `Vcr`, `VcrSide` |
| `enums.py` | All `Enum` types (see §6) |

### 5.2 Entity field specifications

Fields are derived from the example payload (`assets/turn.json`) cross-referenced with the wiki. Type annotations use Python 3.14 native syntax (`int | None` not `Optional[int]`).

#### `GameSettings`

All fields from the `settings` key of the `rst` object. This is a large dataclass (~200 fields). Key fields:

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | Settings ID |
| `name` | `str` | Game name |
| `turn` | `int` | Current turn |
| `mapwidth` | `int` | Map width |
| `mapheight` | `int` | Map height |
| `numplanets` | `int` | Planet count |
| `shiplimit` | `int` | Ship limit |
| `planetscanrange` | `int` | Planet scan range |
| `shipscanrange` | `int` | Ship scan range |
| `hoststart` | `str` | Host start time (kept as string — see §7) |
| `hostcompleted` | `str` | Host completed time |
| `nexthost` | `str` | Next host time |
| ... | ... | ~180 additional boolean/int/float/str config fields |

**Implementation note:** Because this dataclass has many fields, enumerate them all from the payload sample. Every field in the sample must appear in the dataclass.

#### `Game`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | Game ID |
| `name` | `str` | |
| `description` | `str` | |
| `shortdescription` | `str` | |
| `status` | `GameStatus` | Enum (see §6) |
| `datecreated` | `str` | |
| `dateended` | `str` | |
| `maptype` | `int` | |
| `gametype` | `int` | |
| `wincondition` | `int` | |
| `difficulty` | `float` | |
| `turn` | `int` | |
| `slots` | `int` | |
| `hostdays` | `str` | e.g. `"__T_T_S"` |
| `hosttime` | `str` | e.g. `"22:21"` |
| `nexthost` | `str` | |
| `allturnsin` | `bool` | |
| `ishosting` | `bool` | |
| `isprivate` | `bool` | |
| `turnstatus` | `str` | e.g. `"x___xxx_xx_"` |
| `statusname` | `str` | e.g. `"Finished"` |
| ... | ... | Remaining fields from payload |

#### `Player`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | Player ID |
| `username` | `str` | |
| `raceid` | `int` | Race ID (1-based) |
| `status` | `int` | |
| `prioritypoints` | `int` | |
| `turnjoined` | `int` | |
| `turnready` | `bool` | |
| `turnstatus` | `int` | |
| `activehulls` | `str` | Comma-separated hull IDs |
| `activeadvantages` | `str` | Comma-separated advantage IDs |
| ... | ... | Remaining fields from payload |

#### `Planet`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | Planet ID |
| `name` | `str` | |
| `x` | `int` | X coordinate |
| `y` | `int` | Y coordinate |
| `ownerid` | `int` | 0 = unowned |
| `friendlycode` | `str` | 3-character code |
| `temp` | `int` | Temperature (0–100, or -1 unknown) |
| `clans` | `int` | Colonist clans |
| `mines` | `int` | Mineral mines |
| `factories` | `int` | |
| `defense` | `int` | |
| `megacredits` | `int` | |
| `supplies` | `int` | |
| `neutronium` | `int` | Surface minerals |
| `duranium` | `int` | |
| `molybdenum` | `int` | |
| `tritanium` | `int` | |
| `groundneutronium` | `int` | Underground minerals |
| `groundduranium` | `int` | |
| `groundmolybdenum` | `int` | |
| `groundtritanium` | `int` | |
| `densityneutronium` | `int` | Mineral density |
| `densityduranium` | `int` | |
| `densitymolybdenum` | `int` | |
| `densitytritanium` | `int` | |
| `nativeclans` | `int` | |
| `nativetype` | `NativeType` | Enum (see §6) |
| `nativeracename` | `str` | |
| `nativegovernment` | `int` | |
| `nativegovernmentname` | `str` | |
| `nativehappypoints` | `int` | |
| `nativetaxrate` | `int` | |
| `colonisthappypoints` | `int` | |
| `colonisttaxrate` | `int` | |
| `infoturn` | `int` | Turn this info was last updated |
| `img` | `str` | Planet image URL |
| ... | ... | Remaining fields (build targets, checks, flags, etc.) |

#### `Ship`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | Ship ID |
| `name` | `str` | |
| `x` | `int` | X coordinate |
| `y` | `int` | Y coordinate |
| `ownerid` | `int` | |
| `hullid` | `int` | |
| `friendlycode` | `str` | |
| `warp` | `int` | Warp speed |
| `heading` | `int` | |
| `beamid` | `int` | Beam type ID |
| `beams` | `int` | Beam count |
| `torpedoid` | `int` | |
| `torps` | `int` | Launcher count |
| `engineid` | `int` | |
| `bays` | `int` | Fighter bays |
| `crew` | `int` | |
| `damage` | `int` | |
| `mass` | `int` | |
| `neutronium` | `int` | Fuel |
| `duranium` | `int` | Cargo |
| `tritanium` | `int` | |
| `molybdenum` | `int` | |
| `supplies` | `int` | |
| `megacredits` | `int` | |
| `ammo` | `int` | Torpedoes or fighters |
| `clans` | `int` | Clans in cargo |
| `mission` | `int` | Mission ID |
| `mission1target` | `int` | |
| `mission2target` | `int` | |
| `enemy` | `int` | Primary enemy |
| `iscloaked` | `bool` | |
| `targetx` | `int` | Waypoint target |
| `targety` | `int` | |
| `infoturn` | `int` | |
| `experience` | `int` | |
| `history` | `list[ShipHistory]` | Position history |
| `waypoints` | `list` | Waypoint list |
| ... | ... | Transfer fields, pod fields, etc. |

#### `ShipHistory`

```python
@dataclass
class ShipHistory:
    x: int
    y: int
```

#### `Starbase`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `planetid` | `int` | |
| `defense` | `int` | |
| `damage` | `int` | |
| `fighters` | `int` | |
| `enginetechlevel` | `int` | |
| `hulltechlevel` | `int` | |
| `beamtechlevel` | `int` | |
| `torptechlevel` | `int` | |
| `mission` | `int` | |
| `shipmission` | `int` | |
| `isbuilding` | `bool` | |
| `buildbeamid` | `int` | Build queue |
| `buildengineid` | `int` | |
| `buildtorpedoid` | `int` | |
| `buildhullid` | `int` | |
| `buildbeamcount` | `int` | |
| `buildtorpcount` | `int` | |
| `raceid` | `int` | |
| `infoturn` | `int` | |
| ... | ... | Tech-up fields, starbasetype, etc. |

#### `StockItem`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `starbaseid` | `int` | |
| `stocktype` | `int` | Item category |
| `stockid` | `int` | Item type ID |
| `amount` | `int` | Quantity |
| `builtamount` | `int` | |

#### `Hull`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | |
| `cost` | `int` | MC cost |
| `tritanium` | `int` | |
| `duranium` | `int` | |
| `molybdenum` | `int` | |
| `fueltank` | `int` | |
| `crew` | `int` | |
| `engines` | `int` | Engines required |
| `mass` | `int` | |
| `techlevel` | `int` | |
| `cargo` | `int` | |
| `fighterbays` | `int` | |
| `launchers` | `int` | |
| `beams` | `int` | |
| `cancloak` | `bool` | |
| `special` | `str` | Special abilities description |
| `description` | `str` | |
| `advantage` | `int` | |
| `isbase` | `bool` | |
| ... | ... | Short resource names, parentid, academy |

#### `Beam`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | |
| `cost` | `int` | |
| `tritanium` | `int` | |
| `duranium` | `int` | |
| `molybdenum` | `int` | |
| `mass` | `int` | |
| `techlevel` | `int` | |
| `crewkill` | `int` | |
| `damage` | `int` | |

#### `Engine`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | |
| `cost` | `int` | |
| `tritanium` | `int` | |
| `duranium` | `int` | |
| `molybdenum` | `int` | |
| `techlevel` | `int` | |
| `warp1` through `warp9` | `int` | Fuel factors per warp |

#### `Torpedo`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | |
| `torpedocost` | `int` | Ammo cost |
| `launchercost` | `int` | Launcher cost |
| `tritanium` | `int` | |
| `duranium` | `int` | |
| `molybdenum` | `int` | |
| `mass` | `int` | |
| `techlevel` | `int` | |
| `crewkill` | `int` | |
| `damage` | `int` | |
| `combatrange` | `int` | Present in payload but not documented in wiki |

**Note:** The payload uses a `fullid` field that is distinct from `id`. Include both.

#### `IonStorm`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `x` | `int` | |
| `y` | `int` | |
| `radius` | `int` | |
| `voltage` | `int` | Strength |
| `warp` | `int` | Speed |
| `heading` | `int` | |
| `isgrowing` | `bool` | |
| `parentid` | `int` | |

#### `Minefield`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `x` | `int` | |
| `y` | `int` | |
| `ownerid` | `int` | |
| `radius` | `int` | |
| `units` | `int` | |
| `isweb` | `bool` | |
| `ishidden` | `bool` | Present in payload |
| `friendlycode` | `str` | |
| `infoturn` | `int` | |

#### `Star`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | |
| `x` | `int` | |
| `y` | `int` | |
| `temp` | `int` | |
| `radius` | `int` | |
| `mass` | `int` | |
| `planets` | `int` | Associated planet count |

#### `Nebula`

Not populated in the sample payload. Define as:

```python
@dataclass
class Nebula:
    id: int
    x: int
    y: int
```

Additional fields can be added when real data is available.

#### `Message`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `ownerid` | `int` | |
| `messagetype` | `MessageType` | Enum (see §6) |
| `headline` | `str` | |
| `body` | `str` | May contain HTML |
| `target` | `int` | Subject entity ID |
| `turn` | `int` | |
| `x` | `int` | |
| `y` | `int` | |

#### `Note`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `ownerid` | `int` | |
| `body` | `str` | |
| `targetid` | `int` | |
| `targettype` | `int` | |
| `color` | `str` | Hex colour |

#### `Vcr`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `seed` | `int` | RNG seed |
| `x` | `int` | |
| `y` | `int` | |
| `battletype` | `int` | |
| `leftownerid` | `int` | |
| `rightownerid` | `int` | |
| `turn` | `int` | |
| `left` | `VcrSide` | Left combatant |
| `right` | `VcrSide` | Right combatant |

#### `VcrSide`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `vcrid` | `int` | |
| `objectid` | `int` | Ship or planet ID |
| `name` | `str` | |
| `side` | `int` | |
| `hullid` | `int` | |
| `beamid` | `int` | |
| `torpedoid` | `int` | |
| `beamcount` | `int` | |
| `launchercount` | `int` | |
| `baycount` | `int` | |
| `shield` | `int` | |
| `damage` | `int` | |
| `crew` | `int` | |
| `mass` | `int` | |
| `raceid` | `int` | |
| `beamkillbonus` | `int` | |
| `beamchargerate` | `int` | |
| `torpchargerate` | `int` | |
| `torpmisspercent` | `int` | |
| `crewdefensepercent` | `int` | |
| `torpedos` | `int` | |
| `fighters` | `int` | |
| `temperature` | `int` | |
| `hasstarbase` | `bool` | |

#### `Score`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `ownerid` | `int` | |
| `turn` | `int` | |
| `planets` | `int` | |
| `starbases` | `int` | |
| `capitalships` | `int` | |
| `freighters` | `int` | |
| `militaryscore` | `int` | |
| `inventoryscore` | `int` | |
| `prioritypoints` | `int` | |
| `percent` | `float` | |
| `victoryscore` | `int` | |
| ... | ... | Change fields, bonus fields from payload |

#### `Relation`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `playerid` | `int` | |
| `playertoid` | `int` | |
| `relationto` | `int` | |
| `relationfrom` | `int` | |
| `conflictlevel` | `int` | |
| `color` | `str` | |

#### `Race`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | Full name |
| `shortname` | `str` | |
| `adjective` | `str` | |
| `baseadvantages` | `str` | |
| `advantages` | `str` | |
| `basehulls` | `str` | |
| `hulls` | `str` | |

#### `Advantage`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `name` | `str` | |
| `description` | `str` | |
| `value` | `int` | |
| `isbase` | `bool` | |
| `locked` | `bool` | |
| `dur` | `int` | |
| `tri` | `int` | |
| `mol` | `int` | |
| `mc` | `int` | |

#### `Badge`

| Field | Type | Notes |
|-------|------|-------|
| `id` | `int` | |
| `raceid` | `int` | |
| `badgelevel` | `int` | |
| `badgetype` | `int` | |
| `forrank` | `int` | |
| `endturn` | `int` | |
| `achievement` | `int` | |
| `dur` | `int` | |
| `tri` | `int` | |
| `mol` | `int` | |
| `mc` | `int` | |
| `planets` | `int` | |
| `ships` | `int` | |
| `starbases` | `int` | |
| `military` | `int` | |
| `battleswon` | `int` | |
| `name` | `str` | |
| `description` | `str` | |
| `completed` | `bool` | |

---

## 6. Enum types

Define in `packages/api/models/enums.py`. Use `IntEnum` for integer-keyed enumerations and `StrEnum` for string-keyed ones. Where the full set of values is known from the wiki, enumerate all members. Where only a subset is observed in sample data, enumerate the known values and use a permissive deserialization strategy (see §7.2).

### 6.1 `MessageType` (IntEnum)

From the [Planets.nu API wiki](https://vgaplanets.org/index.php/Planets.Nu_API):

| Value | Meaning |
|-------|---------|
| 1 | Ship messages |
| 2 | Planet messages |
| 3 | Starbase messages |
| 4 | Mine sweep messages |
| 5 | Minefield messages |
| 6 | Explosion messages |
| 7 | Planetary defense messages |
| 8 | Combat messages |
| 9 | Alliance messages |
| 10 | Ion storm messages |
| 11 | Colonist messages |
| 12 | Natives messages |
| 13 | Score messages |
| 14 | Meteor messages |
| 15 | Sensor sweep messages |
| 16 | Biographical messages |
| 17 | Diplomacy messages |
| 18 | Hconfig messages |
| 19 | Special messages |
| 20 | Player messages |
| 21 | Distress messages |

### 6.2 `NativeType` (IntEnum)

From the wiki and domain knowledge:

| Value | Name |
|-------|------|
| 0 | None |
| 1 | Humanoid |
| 2 | Bovinoid |
| 3 | Reptilian |
| 4 | Avian |
| 5 | Amorphous |
| 6 | Insectoid |
| 7 | Amphibian |
| 8 | Ghipsoldal |
| 9 | Siliconoid |
| 10 | Botanical |
| 11 | Horwasp |

### 6.3 `GameStatus` (IntEnum)

Observed in sample data and inferred from wiki:

| Value | Name |
|-------|------|
| 0 | Joining |
| 1 | Running |
| 2 | Paused |
| 3 | Finished |

### 6.4 Extensibility

Additional enums (e.g. `Mission`, `NativeGovernment`, `StockType`) can be added in later enhancements as analytics require them. The serialization layer should handle unknown enum values gracefully (see §7.2).

---

## 7. Serialization and deserialization

### 7.1 Location and pattern

Codecs live in `packages/api/serialization/`. Following the established convention from `core-api.mdc`:

- **dict → dataclass**: `dacite.from_dict()` with a custom `dacite.Config` that handles enum coercion and optional fields.
- **dataclass → dict**: `dataclasses.asdict()` with post-processing for enums.

Provide codec functions at the entity-group level:

```python
# packages/api/serialization/turn.py
def turn_info_from_json(data: dict) -> TurnInfo: ...
def turn_info_to_json(obj: TurnInfo) -> dict: ...

# packages/api/serialization/game.py
def game_info_from_json(data: dict) -> GameInfo: ...
def game_info_to_json(obj: GameInfo) -> dict: ...
```

### 7.2 Non-JSON-native field handling

| Field type | JSON representation | Codec strategy |
|------------|-------------------|----------------|
| `IntEnum` | `int` | `dacite` cast hook: `int → EnumType(value)` |
| `bool` | `bool` | Native — no codec needed |
| Date/time strings | `str` | **Keep as `str`** for now. The API returns non-ISO formats (e.g. `"6/23/2025 2:51:28 PM"`). Parsing to `datetime` deferred to a later enhancement when analytics require it. |

**Enum resilience:** The `dacite` config should use a cast hook that falls back gracefully when an integer value does not match any enum member. Two acceptable strategies:

1. **Lenient cast:** Try `EnumType(value)`, and on `ValueError` store the raw `int` (requires the field type to be `MessageType | int` or similar union).
2. **`UNKNOWN` sentinel:** Add an `UNKNOWN = -1` member to each enum and map unrecognised values to it.

Strategy (2) is preferred for simplicity and type safety. The `dacite` `Config` should include a `cast` list for all enum types.

### 7.3 Nested object deserialization

`dacite.from_dict()` handles nested dataclasses natively. The `Config` must include:

- `cast = [MessageType, NativeType, GameStatus, ...]` for all enum types.
- `strict = False` to allow extra keys in the payload that are not modelled (forward-compatibility with API changes).

---

## 8. Core API routes

### 8.1 Route definitions

| Route | Method | Response type | Description |
|-------|--------|---------------|-------------|
| `/api/v1/games/{game_id}/info` | GET | `GameInfo` | Return game info for the given game |
| `/api/v1/games/{game_id}/{perspective}/turns/{turn_number}` | GET | `TurnInfo` | Return turn data for the given game, player perspective, and turn |

### 8.2 Router

New router at `packages/api/routers/games.py`:

```python
router = APIRouter(prefix="/v1/games", tags=["games"])

@router.get("/{game_id}/info")
def get_game_info(
    game_id: int,
    svc: GameService = Depends(get_game_service),
) -> GameInfo: ...

@router.get("/{game_id}/{perspective}/turns/{turn_number}")
def get_turn_info(
    game_id: int,
    perspective: int,
    turn_number: int,
    svc: GameService = Depends(get_game_service),
) -> TurnInfo: ...
```

Register in `packages/api/app.py`:

```python
from api.routers import games
app.include_router(games.router)
```

### 8.3 Service

New service at `packages/api/services/game_service.py`:

```python
class GameService:
    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def get_game_info(self, game_id: int) -> GameInfo:
        data = self._storage.get(f"games/{game_id}/info")
        return game_info_from_json(data)

    def get_turn_info(self, game_id: int, perspective: int, turn_number: int) -> TurnInfo:
        data = self._storage.get(f"games/{game_id}/{perspective}/turns/{turn_number}")
        return turn_info_from_json(data)
```

The service reads from the storage backend and deserializes. If the path does not exist, the storage layer raises `NotFoundError`, which the global exception handler maps to 404.

### 8.4 Dummy data via static assets

For now, routes return dummy data loaded from static JSON files. Following the issue guidance:

- Place static assets under `packages/api/storage/assets/` (e.g. `game_info_sample.json`, `turn_sample.json`).
- On app startup (or lazily on first request), seed the in-memory store with the dummy data at the expected paths (e.g. `games/628580/info`, `games/628580/1/turns/111`).
- The seeding logic lives in a startup hook or a helper in the service layer — not in router code.
- The `assets/turn.json` file provides the source for `turn_sample.json`. A trimmed version should be used as the asset (subset of entities to keep the file manageable while still exercising all dataclass types).

---

## 9. Error handling

Reuse the existing exception hierarchy from `api.errors`:

| Condition | Exception | HTTP |
|-----------|-----------|------|
| Game not found | `NotFoundError` | 404 |
| Turn not found | `NotFoundError` | 404 |

No new exception types are needed for this enhancement.

---

## 10. Testing

### 10.1 Model tests (`test_models.py`)

- **Instantiation:** Each dataclass can be constructed with representative field values.
- **Enum members:** All defined enum values resolve correctly; `UNKNOWN` sentinel works for unrecognised values.

### 10.2 Serialization tests (`test_serialization.py`)

- **Round-trip:** `turn_info_to_json(turn_info_from_json(data)) == data` (modulo enum representation) for a representative payload.
- **Enum deserialization:** Integer values in JSON map to correct enum members.
- **Unknown enum values:** Integers not in the enum map to `UNKNOWN` sentinel.
- **Extra keys:** Payload with additional unknown keys deserializes without error (`strict=False`).
- **Nested objects:** `Ship.history` deserializes as `list[ShipHistory]`; `Vcr.left`/`Vcr.right` deserialize as `VcrSide`.

### 10.3 Router tests (`test_games_router.py`)

- **GET `/api/v1/games/{id}/info`:** Returns 200 with valid `GameInfo` JSON; returns 404 for unknown game ID.
- **GET `/api/v1/games/{id}/{perspective}/turns/{number}`:** Returns 200 with valid `TurnInfo` JSON; returns 404 for unknown game, perspective slice, or turn.
- **Response structure:** Key fields are present and correctly typed in the JSON response.

### 10.4 Service tests (`test_game_service.py`)

- **`get_game_info`:** Reads from storage, deserializes correctly.
- **`get_turn_info`:** Reads from storage, deserializes correctly.
- **Missing data:** Raises `NotFoundError` when path not in store.

---

## 11. Deliverables (acceptance)

1. **Dataclass models** for all entities in the Planets API `GameInfo` and `TurnInfo` responses, defined in `packages/api/models/`.
2. **Enum types** for `MessageType`, `NativeType`, `GameStatus` (and others as needed), with `UNKNOWN` sentinels for forward-compatibility.
3. **Serialization codecs** in `packages/api/serialization/` using `dacite` for JSON ↔ dataclass conversion, with enum cast hooks and lenient unknown-key handling.
4. **Core API routes** at `/api/v1/games/{id}/info` and `/api/v1/games/{id}/{perspective}/turns/{number}` returning `GameInfo` and `TurnInfo` respectively.
5. **Game service** in `packages/api/services/game_service.py` reading from `StorageBackend` and deserializing.
6. **Dummy data** from static JSON assets seeded into the store, so routes return realistic responses without any external API calls.
7. **Unit tests** covering models, serialization (including round-trips, enum handling, nested objects), service logic, and router HTTP contracts.

---

## 12. Implementation order

The recommended implementation sequence, respecting layer dependencies:

| Step | What | Depends on |
|------|------|------------|
| 1 | `packages/api/models/enums.py` — all enum types | — |
| 2 | `packages/api/models/*.py` — all entity dataclasses | Step 1 |
| 3 | `packages/api/serialization/` — codec functions | Steps 1–2 |
| 4 | `packages/api/services/game_service.py` — service class | Steps 2–3 |
| 5 | `packages/api/routers/games.py` — router + registration in `app.py` | Step 4 |
| 6 | Static assets + store seeding | Steps 2–3 |
| 7 | Unit tests (models, serialization, service, router) | Steps 1–6 |

Steps 1–3 can proceed without any changes to existing files. Steps 4–5 add new files and a single line in `app.py`. Step 6 adds asset files and a startup hook.

---

## 13. Open points

- **`GameSettings` field completeness:** The settings object has ~200 fields. The implementation should enumerate all fields from the sample payload rather than selectively modelling a subset. This ensures analytics can access any game configuration parameter.
- **Date/time parsing:** Deferred. The API uses a non-standard format (`M/d/yyyy h:mm:ss tt`). A future enhancement can add `datetime` fields with codec support when analytics need temporal computations.
- **Stub entities:** `Nebula`, `Blackhole`, `Artifact`, `Wormhole`, `Cutscene` are empty in the sample. Define minimal dataclasses (at least `id`, `x`, `y` where applicable) to be fleshed out when real data is available.
- **`activehulls` / `activeadvantages` as comma-separated strings:** The API returns these as strings. A future enhancement could parse them to `list[int]` with a custom codec. For now, keep as `str` to match the wire format.
- **Large payload trimming for assets:** The full `turn.json` is ~2.7 MB. The static asset should be a trimmed version (e.g. fewer planets, ships, stock items) that still exercises every entity type.

---

## 14. References

- [GitHub Issue #7](https://github.com/SteveDraper/Planets-Console/issues/7)
- [Planets.Nu API wiki](https://vgaplanets.org/index.php/Planets.Nu_API)
- [core-api.mdc](../.cursor/rules/core-api.mdc) — data model, serialization, router conventions
- [storage.mdc](../.cursor/rules/storage.mdc) — StorageBackend protocol
- [server-exceptions.mdc](../.cursor/rules/server-exceptions.mdc) — exception hierarchy
- [Design: Storage abstraction and CRUD REST API](design-storage-abstraction-and-crud-api.md) — storage layer design
- [VGA Planets domain context](vga-planets-domain-context.md) — entity overview and API payload keys
