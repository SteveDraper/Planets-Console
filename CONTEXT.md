# Planets Console

An analytic console for Planets.nu game state. The backend persists domain data through a logical JSON store accessed via hierarchical paths.

## Language

**Logical store path**:
A slash-separated key into the single logical JSON tree (e.g. `games/628580/1/turns/111`). All services read and write via these paths through `StorageBackend`.
_Avoid_: key, URL path (when meaning the storage address)

**StorageBackend**:
The abstract protocol (`get`, `put`, `delete`, `list`) that hides whether data lives in memory or on disk. Services never reference concrete implementations.
_Avoid_: database, file store (when meaning the protocol itself)

**Breakpoint**:
A declared point in the path hierarchy where persistence writes a separate JSON document. Logical paths at or below a breakpoint share that document until a deeper breakpoint splits again.
_Avoid_: shard key, partition (without "breakpoint" context)

**Document** (storage):
One JSON file on disk corresponding to a breakpoint path. Nested logical paths without an intervening breakpoint are stored inside the document, not as separate files.
_Avoid_: node, blob (when persistence boundary is meant)

**Ephemeral backend**:
The in-memory `MemoryAssetBackend` used for tests and dev; mutations do not survive process restart.
_Avoid_: temporary storage (ambiguous with session state)

**Breakpoint registry**:
A code-defined list of path patterns (in `packages/api/api/storage/boundaries.py`, import `api.storage.boundaries`) that declares where JSON documents begin. Kept in sync with service key conventions; not loaded from external config.
_Avoid_: storage schema file, boundaries YAML

**Registered path**:
A logical store path that matches at least one breakpoint pattern (longest matching prefix wins). Only registered paths may be read or written by the file backend; unregistered paths fail fast.
_Avoid_: valid key (too generic)

**V1 breakpoint patterns**:
- `games/*/info` — game info object
- `games/*/*/turns/*` — turn/RST blob per perspective and turn
- `credentials/accounts/*` — account record (e.g. api_key and future fields)

**Document write** (file backend v1):
Persist by writing a temp file in the same directory, then atomic `replace` into place. Assumes single process / single worker; no cross-process file locking in v1.
_Avoid_: sync write (vague)

**Storage backend selection**:
- `ApiConfig` default: `ephemeral` (tests, CI, scripts without config).
- Repo `.config.yaml` uses `file` with `storage_root: ./.data` for local dev persistence.
_Avoid_: persistent mode (use backend id `file`)

**Document delete** (file backend):
Removing a whole document deletes its JSON file, then prunes empty parent directories up to (but not including) `storage_root`. In-document key deletes rewrite the file only; no directory prune.
_Avoid_: cascade delete (ambiguous with game-domain meaning)

**Store root path** (`""`):
`list("")` returns top-level logical segments. `get`, `put`, and `delete` on the root path are rejected (`ValidationError`). All `StorageBackend` implementations must behave the same way.
_Avoid_: whole-store read (no aggregate root document)

**Backend conformance**:
Shared parametrized tests exercise the same `StorageBackend` contract against every implementation (ephemeral and file). Backend-specific tests cover only implementation details (deep copy, atomic write, prune, layout).
_Avoid_: duplicate test modules per backend (for shared semantics)

**Startup seed** (`include_dummy_data`):
When true, seed sample paths only if each target path is missing (`NotFoundError` on get). Never overwrite existing documents. Same behavior for ephemeral and file backends.
_Avoid_: force seed, reset on boot

## Example dialogue

**Dev:** Where does turn 111 for game 628580 live on disk?  
**Expert:** At logical path `games/628580/1/turns/111` — a breakpoint match — so file `./.data/games/628580/1/turns/111.json`. The whole RST blob is that file.
**Dev:** And `games/628580/info/settings`?  
**Expert:** Same document as `games/628580/info` — `info.json`. Settings is nested inside; no separate file.  
**Dev:** Can I `GET /api/v1/store` and get the whole store?  
**Expert:** No. Root is list-only. There is no aggregate root document.
