# Homeworld ownership reads on-disk fleet ages

Status: accepted

The homeworld locator waited on an ensure-final fleet ledger for every roster player at each refine turn. That edge is the **Backfill earlier turns** walk, which the locator does not start. A read with no later rerun was already refused: the locator can finish before fleet and then never notice a better ledger.

Each refine step reads that turn's on-disk ledger for every roster player, including an **approximate fleet**, and declares no fleet ENSURE dependency. A known `built_turn` keeps the existing ship-travel envelope strength. The **homeworld evidence aggregate** stores a **fleet-age input stamp**: the per-player known `ship_id → built_turn` map, with a missing file as its own value. Satisfaction fails from that turn upward when the stamp no longer matches, and an enabled locator refetches a shown shell at or after that turn. Re-refine from the last satisfied prior can add or remove envelopes. The approximate file is not ensure-final.

## Considered options

- Keep the final-fleet ENSURE edge. Opening the locator would start the backfill walk.
- Mark a ledger only as approximate or final. A later save at the same **fleet evidence generation** can change `built_turn` values and stay short of ensure-final.
- Record that flag on each ownership provenance. Satisfaction does not read those rows, and a stamp only on the shell leaves the prior turn satisfied, so the next step refines from the old prior.
