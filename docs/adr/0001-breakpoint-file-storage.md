# Breakpoint-based file storage

Status: accepted

Planets Console persists game info, turn blobs, and credentials through a logical JSON store (`StorageBackend`). Issue #3 delivered an ephemeral in-memory backend and CRUD API; durable persistence maps that same protocol to JSON files on disk without one-file-per-path-segment bloat.

We persist **documents** at **breakpoints** declared in a code registry (`packages/api/api/storage/boundaries.py`). A breakpoint is a path pattern (e.g. `games/*/info`); the matching prefix is one JSON file; nested logical paths without a deeper breakpoint live inside that file. Longest matching breakpoint wins. Unregistered paths fail fast (`ValidationError`). Writes use temp-file-then-atomic-replace; v1 assumes single process / single worker (no cross-process locking). Document delete removes the file and prunes empty parent directories up to `storage_root`. The store root path (`""`) supports `list` only — `get`, `put`, and `delete` on root are rejected on **all** backends for semantic invariance.

## Considered options

- **One JSON file per path segment** — simple mapping but splits objects that are always accessed together and multiplies files for shallow paths.
- **Single monolithic JSON file** — every write rewrites the whole store; unacceptable for multi-MB turn blobs.
- **Database (SQLite/Postgres)** — deferred; file storage matches current scale and keeps the existing path protocol.
- **Catch-all breakpoint (`*`)** — rejected; typos would create orphan files and hide registry gaps.

## Consequences

- New entity types need a registry pattern before services can persist them on the file backend.
- `ApiConfig` default remains `ephemeral` (tests/CI); repo `.config.yaml` uses `file` + `storage_root: ./.data` (`.data/` is gitignored).
- `include_dummy_data` seeds only missing paths (idempotent skip-if-present).
- Shared parametrized conformance tests must pass for every `StorageBackend` implementation.
- Multi-worker uvicorn on one `storage_root` may need advisory file locking in a follow-up ADR.

See also: [CONTEXT.md](../../CONTEXT.md), [design-storage-abstraction-and-crud-api.md](../design-storage-abstraction-and-crud-api.md) §15.
