# Homeworld ownership reads on-disk fleet ages

Status: accepted

The homeworld locator waited on an ensure-final fleet ledger for every roster player at each refine turn. That edge is the **Backfill earlier turns** walk, which the locator does not start. A read with no later rerun was already refused: the locator can finish before fleet and then never notice a better ledger.

Each refine step reads that turn's on-disk ledger for every roster player, including an **approximate fleet**, and declares no fleet ENSURE dependency. A known `built_turn` keeps the existing ship-travel envelope strength. The **homeworld evidence aggregate** stores a **fleet-age input stamp**: the per-player known `ship_id → built_turn` map, with a missing file as its own value. The stamp records which ages that turn's refine used. It is not compared to the files when deciding whether a turn is satisfied.

A durable **fleet-age stale marker** decides satisfaction. Fleet persistence reports each create, remove, or edit of a roster player's build-turn map. The homeworld store records the earliest affected turn as `staleFromTurn` and increments a monotonic `generation`. A save that leaves the build-turn identity unchanged reports nothing. A stored aggregate is satisfied when its baseline and evidence algorithm version match and its turn is before `staleFromTurn`. That check reads one aggregate and one marker. It does not read ledger files and does not walk lower turns.

Aggregates on or above the frontier stay stored, and on screen, until a refine replaces them. Re-refine runs from the frontier through the shell being ensured. A refine reads `generation` before it reads ledger stamps and advances `staleFromTurn` past the refined turn only when the stored `generation` has not moved, so a ledger save that lands during a refine stays marked. When the frontier passes every stored aggregate, `staleFromTurn` is cleared and `generation` is kept. Turns after the shown shell are not ensured until shown.

The marker document also keeps a bounded log of recent `(generation, turn)` changes. An enabled locator polls the notice built from that log (`epoch` is the generation, `fromTurn` is the earliest turn changed after the client's epoch) and refetches its map query when the shown shell turn is at or after `fromTurn`. A client epoch ahead of the stored generation, or a log that no longer holds every change after the client epoch, answers `fromTurn = 1`, so the shown shell refetches. The poll never ensures homeworld or fleet. The document lives at `games/{gameId}/{perspective}/analytics/homeworld-locator` ([ADR 0002](0002-analytic-persistence.md)), so notices and the frontier survive a restart.

The approximate file is not ensure-final.

## Considered options

- Keep the final-fleet ENSURE edge. Opening the locator would start the backfill walk.
- Mark a ledger only as approximate or final. A later save at the same **fleet evidence generation** can change `built_turn` values and stay short of ensure-final.
- Record that flag on each ownership provenance. Satisfaction does not read those rows, and a stamp only on the shell leaves the prior turn satisfied, so the next step refines from the old prior.
- Compare each turn's stamp to the ledger files on every satisfaction check, walking from the shell down to the baseline. A satisfaction check at turn *T* would parse every roster player's ledger at every turn at or below *T*, and the self-chain checks each lower turn in turn, so the cost grows with turns squared times players. The marker moves that cost to the rare ledger save.
- Link each aggregate to the prior aggregate it was refined from (stamp or revision counter). The marker already invalidates every turn above the changed one, so the links add stored fields without adding a case the marker misses.
- Keep refetch notices in process memory. Epochs restart at zero with the process, so a client holding a later epoch would miss changes made before the next one.
