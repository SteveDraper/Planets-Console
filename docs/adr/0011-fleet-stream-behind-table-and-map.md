# Fleet stream behind table and map view modes

Status: accepted

## Context

Fleet progressive materialization already runs on a multiplexed NDJSON **fleet stream** (HTTP path `…/fleet/table-stream`) so the SPA can show gap-fill without blocking on a fully ensure-final ledger. Design originally treated **map** as a separate deliverable fed by `GET …/fleet/map` (per-ship nodes). That split reintroduces the incomplete-vs-wait problem the stream solved, and duplicates session ownership between tabular and map **view mode**s.

## Decision

- **One fleet stream owns progressive ledger delivery** for a shell scope. **Fleet table tile**s and the **fleet map layer** are projections of the same demuxed per-player state.
- The SPA holds the stream session **above** table vs map (not only inside the table tile). Enabling fleet in map mode must not require a second NDJSON protocol or a blocking map GET.
- **`GET …/fleet/map` is not the SPA live path.** Map REST may remain a no-op/scaffold for catalog symmetry or be removed; it is not required to populate ship geometry for the console.
- Map paint is **fleet location ring**s aggregated client-side from stream records (`lastSeen` + **fleet ship military estimate**), not per-ship graph nodes from a map wire.

## Consequences

- [#126](https://github.com/SteveDraper/Planets-Console/issues/126) (BFF map wire population) is superseded for the SPA.
- [#128](https://github.com/SteveDraper/Planets-Console/issues/128) consumes the fleet stream, registers map merge/overlay, and does not wait on map REST.
- Design §7.2 / §8.2 should describe stream → projection, not map GET as primary.
- Glossary: **Fleet stream**, **Fleet location ring**, **Fleet ship military estimate**, **Fleet map layer** in [CONTEXT.md](../../CONTEXT.md).

See also: [ADR 0004](0004-fleet-per-player-persistence-and-ensure-provenance.md), [ADR 0004 addendum](0004-addendum-table-stream-session-framework.md), [design-fleet-analytic.md](../design-fleet-analytic.md).
