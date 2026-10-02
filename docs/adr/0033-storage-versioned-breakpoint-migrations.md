# Storage-versioned breakpoint migrations

Status: accepted

Breakpoint layout is a property of the data directory, not of the analytic that first wrote the document. Both storage backends resolve a logical path to one breakpoint document plus an optional in-document suffix, so a longer breakpoint is never a nested key of the shorter document. The directory carries one storage version at `meta/storage-version`.

An empty directory is stamped with the current version and does not run migrations. A directory at an older supported version runs the remaining steps in order, then stamps the current version. A directory older than the minimum still supported raises an unhandled-format error and is left unchanged. Raising that minimum and deleting the step is how a migration is removed.

A step either re-homes an unchanged logical key onto a longer breakpoint, or calls a structural handler registered by the analytic that owns the document shape. The handler sees JSON documents and keys. Fleet's `players` / `ledgers` turn document becomes per-player `.../analytics/fleet/{playerId}` documents in that handler. After the directory is current, fleet persistence does not probe the old key. Scores `inference_rows/{playerId}` is the shape a later generic re-home would use; this decision does not perform that move. Row-content stamps stay in the analytic.

## Considered options

- **Detect-on-read inside the analytic** -- the fleet service did this, including a delete-before-write so the memory tree matched files. Every new breakpoint would repeat that, and the two backends would keep different meanings of the same put.
- **Per-row version documents** -- the layout change is a property of the directory. A copied-in document from an older breakpoint is unreadable once the directory version has moved past it, rather than being reinterpreted on read.

## Consequences

- New breakpoint splits register a migration keyed by the storage version they introduce. `boundaries.py` holds the pattern, not the document shape.
- Single-process writers (ADR 0001) still apply. The version stamp is not a lock.
- See [design-storage-abstraction-and-crud-api.md](../design-storage-abstraction-and-crud-api.md) §16 and **CONTEXT.md** (**Storage version**, **Document**).
