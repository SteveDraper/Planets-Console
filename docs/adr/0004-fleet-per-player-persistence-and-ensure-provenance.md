# Fleet per-player persistence and ensure provenance

Status: accepted

## Context

**Fleet turn snapshots** today persist all **Player** ledgers in one turn-scoped document (`games/{gameId}/{perspective}/turns/{turn}/analytics/fleet`). **Analytic export ensure** for `fleet@N` treats snapshot existence as satisfied and short-circuits probe walks. **Fleet table** compute calls `get_or_materialize_fleet_snapshot`, which returns any cached snapshot without checking whether the transitive ensure closure was complete for each player.

This produced a functional hole (game 628580, turn 8): dougp314 had refinement-complete rows where `scores@3` and `scores@8` existed, but placeholders for `builtTurn` 4--6 stayed `?` because `scores@5/6/7` were never persisted. The monolithic snapshot was treated as final for all players.

The ensure dependency graph already models the needed closure transitively per `player_id`:

```text
fleet@N  -->  scores@N  -->  fleet@(N-1)  -->  scores@(N-1)  -->  ...
```

The gap is not a missing edge; it is conflating **persisted cache** with **ensure-closed materialization**.

**Scores inference row persistence** (ADR 0002) is already per-player under `.../analytics/scores/inference_rows/{playerId}`. Fleet export paths (`$.composition.*`, `$.players.*`) are already scoped by `player_id`. Persistence and ensure gates should match that grain.

## Decision

### 1. Per-player fleet ledger persistence

Persist each **fleet acquisition ledger** at turn scope under in-document keys (same breakpoint as today):

```text
games/{gameId}/{perspective}/turns/{turn}/analytics/fleet
  ledgers/{playerId}   -->  ledger wire + provenance + materializationVersion
```

- One JSON **document** per `(game, perspective, turn)` breakpoint (ADR 0001 / 0002 unchanged at the path level).
- Each `ledgers/{playerId}` entry is independently readable, writable, and invalidatable.
- **Migration:** on read, accept legacy monolithic snapshot shape (all players at document root) and upgrade in place to per-ledger keys; drop legacy shape after successful upgrade write.

### 2. Materialization provenance (per player, per turn)

Each persisted ledger carries a **fleet materialization provenance** pair:

| Flag | Meaning when `true` |
|------|------------------------|
| `turnEvidenceAtN` | Turn-*N* leg closed: RST@N available; turn-*N* scoreboard ingest and sightings applied for this player; **terminal** `scores@N` evidence for this `player_id` (persisted / terminal admission / functional backfill -- not merely an ensure-admitted in-progress scheduler `RowRun`) |
| `priorLedgerAtNMinus1` | Prior-leg closed: `fleet@(N-1)` for this `player_id` exists and its provenance is `(true, true)`, or *N* = 1 (**fleet ensure baseline**) |

**Final** persisted ledger at `fleet@N` for player P: both flags `true`.

Naming in wire/code may use camelCase (`turnEvidenceAtN`, `priorLedgerAtN`); docs may say "scoreboard@N leg" and "fleet@(N-1) leg" for the same concepts.

Provenance is set **honestly at write time** from actual ensure/materialization inputs -- never inferred optimistically from file existence alone.

### 3. Ensure and probe gates

- `is_fleet_export_persisted` / `is_ensure_satisfied` for `fleet@N` + `player_id` P: `true` only when ledger P exists **and** provenance is `(true, true)`.
- Partial provenance: scope remains on the probe missing-step list; ensure walk continues into the unsatisfied leg (typically `scores@N` or recursive `fleet@(N-1)`).
- **Short-circuit:** both flags true and materialization version current --> skip further ensure work for that player scope.
- **Dedup:** unchanged walk dedup across players and turns; per-player provenance allows accurate missing-step sets.

Fleet table compute and export materialization must not return a partial ledger as final solely because a document exists.

### 4. Per-player materialization chain

Materialize `fleet@N` for player P by:

1. Load P's `fleet@(N-1)` ledger (or baseline at turn 1).
2. Apply turn-*N* evidence for P (scoreboard placeholders, sightings, id bounds).
3. Refine from held `scores` solutions for P (existing `builtTurn` mapping).
4. Persist P's ledger with provenance flags reflecting which legs were closed.

**Shared turn context** (global scoreboard totals for id bounds, accelerated homeworld seeding inputs) is computed once per `(game, perspective, turn)` from RST and read by all per-player materializers. It is not a mutable cross-player ledger.

Gap-fill coordinator ([#161](https://github.com/SteveDraper/Planets-Console/issues/161)) singleflight is keyed per `(gameId, perspective, playerId)` ([#179](https://github.com/SteveDraper/Planets-Console/issues/179)). A perspective-wide lock that batch-materializes all roster players when one player is requested is **not** acceptable: it violates per-player ensure scope and the [compute orchestrator](../design-compute-orchestrator.md) scope model.

### 5. Per-player invalidation

| Event | Invalidation |
|-------|----------------|
| Held-solution admission for player P | Bump the in-memory invalidation epoch for P only. Do not write the durable **fleet evidence generation** mark or open/delete ledger files. |
| Durable scores evidence for player P at host *H* (row persist or hull-mask clear) | Bump P's evidence mark from host *H* (`evidenceGeneration` / `appliesFromTurn`). Leave ledger files in place; mismatched generation is not ensure-final but stays readable. |
| Turn document replace at *T* | Delete fleet ledger files at turns `>= T` (same perspective). |

**Invalidation generation:** A monotonic in-memory counter per `(gameId, perspective, playerId)` -- the same grain as the gap-fill coordinator ([#179](https://github.com/SteveDraper/Planets-Console/issues/179)). The counter bumps on scores invalidation for P (held admission or durable evidence), stale `materializationVersion` prune on read, or turn document replace clearing P's stored ledgers. Gap-fill coordinators record the generation at chain start and abort multi-turn materialization when the counter advances for that player, then retry from a fresh anchor. Per-player scores invalidation bumps only P; turn document replace bumps every player who had ledgers cleared at affected turns. Durable scores evidence bumps the **fleet evidence generation** mark and does not drop ledger files; only turn replace deletes them. Invalidation does not block on in-flight gap-fill work.

### 6. Fleet table NDJSON stream (scores-shaped)

Add a per-scope fleet table stream (Core scheduler + BFF route), modeled on **scores table inference stream**:

- Connect with explicit `playerIds` (visible **fleet player visibility** set).
- Stream events per player: e.g. `ledger_updated`, `record_refined`, `provenance`, `complete`, `error`.
- Ensure / gap-fill work triggered by stream connect and export ensure orchestration ([#109](https://github.com/SteveDraper/Planets-Console/issues/109)) shares the same per-player provenance gates.
- Frontend: each **fleet table tile** subscribes to its player's events; retire coarse whole-table refetch via `scoresInferenceRevision` when stream covers refinement updates ([#143](https://github.com/SteveDraper/Planets-Console/issues/143) follow-on).

### 7. Truncated pseudo-baseline unwind

Still **out of scope** for v1 of this ADR. Per-player provenance enables a future fast mode (stop unwind at *N-K* with explicit `priorLedgerAtNMinus1: false` or a third "truncation" marker). Design that extension when product asks for it; do not implement truncated unwind in the initial F7 slices.

## Considered options

- **Provenance flags on monolithic snapshot only (per-player map inside one file, no ensure gate change)** -- smaller diff but compute path still materializes all players together; ensure probe unchanged at root; does not enable per-player streams or invalidation.
- **Separate breakpoint per player** (`.../analytics/fleet/{playerId}` files) -- adopted by [#531](https://github.com/SteveDraper/Planets-Console/issues/531). See the amendment below. In-document `ledgers/{playerId}` was the v1 layout.
- **Re-refine on every cache hit without provenance** -- fixes some stale refinement without storage model change; does not fix ensure lying about closure or per-player partial state.
- **Keep monolithic persistence; rely on export ensure orchestration only** -- does not fix fleet table compute bypassing ensure; 628580-class holes remain on direct compute path.

## Consequences

- Implementation slices: [#163](https://github.com/SteveDraper/Planets-Console/issues/163) (epic), [#164](https://github.com/SteveDraper/Planets-Console/issues/164)--[#169](https://github.com/SteveDraper/Planets-Console/issues/169) (F7.1--F7.6). See [design-fleet-analytic.md](../design-fleet-analytic.md) section 15.
- Update [design-fleet-analytic.md](../design-fleet-analytic.md) persistence, exports, and stream sections; [design-analytic-exports.md](../design-analytic-exports.md) provenance deferral; **CONTEXT.md** glossary entries.
- ADR 0002 gains a fleet ledger persistence cross-reference (monolithic path superseded for new writes).
- Tests: per-player provenance gates on probe/ensure; partial persist --> not final; migration from legacy snapshot; invalidation per player; stream event contracts.
- **#143** neutral revision bump may shrink or close once fleet stream owns refinement-driven tile updates.
- **#161** coordinator provides singleflight and forward unwind; **#179** narrows scope to per-player materialization and ensure paths.
- **Table-stream session framework** (scores + fleet multiplex connect): [ADR 0004 addendum](0004-addendum-table-stream-session-framework.md) ([#175](https://github.com/SteveDraper/Planets-Console/issues/175)).

See also: [ADR 0002](0002-analytic-persistence.md), [design-fleet-analytic.md](../design-fleet-analytic.md), [design-analytic-exports.md](../design-analytic-exports.md), **CONTEXT.md** (**Fleet ledger persistence**, **Fleet materialization provenance**, **Fleet evidence generation**, **Analytic export ensure provenance**).

## Amendment: per-player files and evidence generation ([#531](https://github.com/SteveDraper/Planets-Console/issues/531))

Scores-evidence invalidation was deleting or rewriting the shared turn document for every admitted solution. That walked `turns/` and rewrote every player in the file.

### Layout

One ledger file per player:

```text
games/{gameId}/{perspective}/turns/{turn}/analytics/fleet/{playerId}
```

`put_ledger` and a clear of that player replace or unlink only that file. A legacy shared `.../analytics/fleet` document is split into these files on read, then removed.

### Fleet evidence generation

One mark document per `(game, perspective, player)`:

```text
games/{gameId}/{perspective}/analytics/fleet-evidence/{playerId}
```

It stores a monotonic `evidenceGeneration` and `appliesFromTurn`. Each ledger records the generation it was written under.

A ledger at turn T is ensure-final only when the file exists, provenance is `(true, true)`, the materialization version is current, and either T is before `appliesFromTurn` or the ledger generation equals the mark. A generation mismatch is the same recalc signal as a missing ledger. The file stays readable.

`appliesFromTurn` keeps turns before the invalidated host turn final, so a scores persist at H+1 does not rebuild fleet@H. It does not move forward across a gap of turns that have not been rewritten. After a final `put_ledger` of the bound turn, the bound advances by one. That write does not clear the generation. A crash before the advance leaves the new ledger matching the generation and later turns unmatched.

Held-solution admission bumps the in-memory player epoch only. It does not write the mark or open ledger files. The durable generation advances when scores evidence is persisted (row persist or hull-mask clear).

Turn-document replace still deletes ledger files at turns `>= T`. That path may list stored turns. Scores invalidation of player P does not.
