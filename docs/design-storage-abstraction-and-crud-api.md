# Design: Storage abstraction and CRUD REST API (Enhancement #3)

**Source:** [GitHub Issue #3 – [Feature] Storage abstraction + test implementation + CRUD API](https://github.com/SteveDraper/Planets-Console/issues/3)

This document describes the design for adding a storage abstraction (abstract interface), an asset-backed in-memory test implementation supporting full CRUD, and Core API REST endpoints that expose CRUD over a logical JSON store. **Implementation is out of scope** for this doc; it is a design and acceptance reference only.

---

## 1. Goal (from the issue)

- **Storage abstraction:** Define an abstract interface for the storage API (Python) that supports CRUD over a logical JSON document.
- **Test implementation:** An in-memory backend initialized from a static JSON asset. It supports full CRUD so all operations and semantics can be unit tested without persistence.
- **Core API REST:** Expose CRUD as HTTP endpoints: Create = PUT, Read = GET, Update = POST, Delete = DELETE. Enforce semantics (no create-over-existing, no update/delete of missing nodes, additive merge on update, no type change on update) and map domain errors to appropriate HTTP statuses.

This is a precursor to a real storage implementation and to loading/serving game data from the store.

---

## 2. Scope

| In scope | Out of scope |
|----------|--------------|
| Abstract storage interface (protocol) in `packages/api/storage/` | Real persistence (file/DB) implementation |
| Asset-backed in-memory test implementation (full CRUD) | JsonPath filters/expressions; only literal path access |
| CRUD REST API under Core API (e.g. `/api/v1/store/...`) | BFF or frontend changes |
| New Core API exception types (NotFound, Conflict, Validation, etc.) | Game-domain models or serialization |
| Path model: hierarchical, slash-separated, mapping to nodes in a logical JSON tree | Full JsonPath spec or query language |

---

## 3. Path model and logical store

- The store is viewed as a **single logical JSON document**. Access is by **path**: a hierarchical key (e.g. `planets/sol/earth`, `game/turn/42`).
- **Path format:** Slash-separated segments, no leading slash, lowercase segments recommended for object keys (align with existing [storage.mdc](../.cursor/rules/storage.mdc) key naming). No filters or expressions—literal paths only. A segment may be **`@` followed by an integer** (e.g. `@0`, `@2`, `@-1`) to denote an **array index** at that step; negative indexes have the usual meaning (-1 = last element, etc.). See §11 and §12.
- **Reserved `@` in keys:** Any object key whose **first character is `@`** is reserved and must not be inserted. Create (PUT) or update (POST) payloads that contain such a key anywhere in the nested structure must be rejected with a distinguished validation error (see §6). This implies that insert of a nested JSON structure requires **full traversal** of the payload to validate that no key starts with `@`.
- A **node** is the value at a path: either a JSON object, array, or primitive. Create/read/update/delete operate on a node at a given path.
- **Semantics:**
  - **Create (PUT):** Store a value at the path. The path must not already exist (no overwrite); otherwise treat as error (distinguished, map to 409 or equivalent). If one or more ancestor object paths are missing, they are **created automatically**.
  - **Read (GET):** Return the value at the path. If the path does not exist, raise a distinguished not-found error that maps to 404.
  - **Update (POST):** Additive merge into the existing value at the path. The existing node must exist (else 404). Merge must preserve node type: merging must not change object ↔ array (or primitive). Attempting to change type is a distinguished error (409). **No ancestor auto-creation** applies to update.
  - **Delete (DELETE):** Remove the node at the path. Path must exist (else 404).
  - **Atomicity:** Each CRUD operation is atomic. On failure, the logical store remains unchanged.

All values are JSON-serialisable (dict, list, str, int, float, bool, null). The storage layer works with Python `dict`/list primitives; the REST layer uses JSON on the wire.

---

## 4. Storage abstraction (Python)

- **Location:** `packages/api/storage/` (existing rule in [storage.mdc](../.cursor/rules/storage.mdc)).
- **Protocol:** The existing `StorageBackend` concept (get/put/delete/list) is the abstract interface. It already uses key-based access and JSON-compatible payloads. This enhancement **does not replace** that protocol; it **realises** it (and may extend it if needed for “create only if not exists” or “merge” semantics, or those can be implemented in a service layer above the backend).
- **Type contract:** Storage values use a recursive JSON type alias:

  ```python
  type JSONValue = dict[str, "JSONValue"] | list["JSONValue"] | str | int | float | bool | None
  ```

  The protocol should use this alias for payloads and reads, rather than dict-only signatures.
- **Behaviour:**
  - **get(key)** returns the value (`JSONValue`, including `None` for JSON null). If missing, it raises `NotFoundError` (distinguished domain error), rather than returning `None`.
  - **put(key, value)** stores the value at the path; the service layer enforces create-only (no overwrite) for Create (PUT) by raising `ConflictError` when the path exists.
  - **delete(key)** removes the node at the path; raises `NotFoundError` if the path does not exist.
  - **list(prefix)** returns next-hop segment names under the prefix (object keys or `@0`..`@(n-1)` for array nodes).

If the current protocol’s `put`/`delete` do not distinguish “create only” vs “overwrite”, that can be enforced in a **service layer** that raises `ConflictError` when creating over an existing path. Because CRUD operations must be atomic, the implementation must provide atomic behavior at the service/backend boundary (e.g. backend primitives, transactional support, or equivalent guarded critical section).

---

## 5. REST API (Core API)

- **Base path:** e.g. `/api/v1/store` (or `/api/v1/store/{path:path}`). Path segment(s) identify the node.
- **Operations:**

| HTTP method | Operation | Request body | Success | Errors |
|-------------|-----------|--------------|---------|--------|
| PUT        | Create    | JSON         | 201     | 409 if path exists; 422 if any key starts with `@` |
| GET        | Read      | —            | 200 + JSON (view=full) or 200 + shallow metadata (view=shallow) | 404 if path missing; 422 if query params invalid |
| POST       | Update (merge) | JSON    | 200     | 404 if path missing; 409 if type change; 422 if any key starts with `@` |
| DELETE     | Delete    | —            | 204     | 404 if path missing |

- **Path in URL:** Path is expressed **in the URL path only** (no query param for the resource path). Example: `GET /api/v1/store/planets/sol/earth`. Use a single path parameter (e.g. `{path:path}`) so that multiple segments map to the logical path; implementation must handle encoding.
- **GET query mode (`view`)**:
  - `view=full` (default): returns the full JSON node at the path (existing behavior).
  - `view=shallow`: returns node metadata plus one-level child enumeration, avoiding deep subtree transfer.
  - Invalid `view` values raise `ValidationError` (422).
- **Shallow response shape (`view=shallow`)**:

  ```json
  {
    "path": "planets/sol",
    "node_type": "object",
    "children": ["earth", "mars", "venus"],
    "count": 3
  }
  ```

  - `children` is a list of **next-hop path segments** (strings) that can be appended to `path` with `/`.
  - For object nodes, `children` contains object key names (for example `["earth", "mars"]`).
  - For array nodes, `children` contains **only** `@N` index-segment labels in ascending order from `@0` to `@{len-1}` (for example `["@0", "@1", "@2"]`), and `count` is array length.
  - Numeric index literals without `@` are not allowed in `children`.
  - For primitive or null nodes, `children` is `[]` and `count` is `0`.
  - This mode is intended to map to storage-level shallow enumeration (`list(prefix)`) plus minimal node-type inspection.
- **Merge semantics (POST):** Additive for objects (deep merge). For **arrays:** **replace by default**. An optional **query parameter** (e.g. `merge=append` or `merge=prepend`) switches semantics to append or prepend (exact param and body shape is an implementation detail). If existing node is object and payload is array (or vice versa), return **409 Conflict** and do not change the store.
- **Type-change error:** Use **409 Conflict** when an update would change node type (object ↔ array or primitive).
- **Atomicity:** PUT/POST/DELETE are atomic write operations. On any error, no partial mutation is persisted.
- **All responses** for error cases use the Core API exception hierarchy; the global exception handler maps them to the HTTP status in §7.

---

## 6. Exception hierarchy (Core API)

All new exceptions must inherit from `CoreAPIError` and set `http_error` as appropriate (see [server-exceptions.mdc](../.cursor/rules/server-exceptions.mdc)):

| Exception (proposed name) | Meaning | `http_error` |
|---------------------------|---------|--------------|
| `NotFoundError` | Path does not exist (read/update/delete) | 404 |
| `ConflictError` | Create on existing path; or update would change node type | 409 |
| `ValidationError` | Invalid payload/path semantics; e.g. any object key has first character `@` (reserved), malformed `@N` index segment, or indexing into a non-array parent | 422 |

These live in `api.errors` (or a dedicated module referenced from there). The storage layer and the store service layer raise these so the REST layer does not need to catch built-in exceptions for these cases.

---

## 7. Normative error mapping

The following mapping is normative for implementation and tests:

| Condition | Exception | HTTP |
|-----------|-----------|------|
| Path does not exist on read/update/delete | `NotFoundError` | 404 |
| Create target path already exists | `ConflictError` | 409 |
| Update would change node type | `ConflictError` | 409 |
| Payload contains any object key starting with `@` | `ValidationError` | 422 |
| Path contains malformed index segment (e.g. `@abc`) | `ValidationError` | 422 |
| Index segment used where parent resolves to non-array | `ValidationError` | 422 |
| Array index out of range (including negative out of range) | `NotFoundError` | 404 |
| Invalid query params (e.g. `view=foo`, invalid `merge=`) | `ValidationError` | 422 |

All write errors are fail-fast and preserve atomicity (no partial writes).

---

## 8. Test implementation (asset-backed in-memory backend)

- **Location:** `packages/api/storage/` (e.g. `memory_asset.py`). Not referenced outside the storage subpackage except via the `StorageBackend` protocol and dependency injection (see storage.mdc).
- **Data source:** A **single monolithic JSON file** whose structure defines the initial path space (e.g. top-level keys `game`, `planets`; nested structure gives path segments). Loaded at backend instantiation and deep-copied into an in-memory structure.
- **Behaviour:** Full CRUD. The backend holds a mutable in-memory copy of the initial JSON so that `get`, `put`, `delete`, and `list` are all implemented. This allows all store semantics (create-only, merge, path resolution, reserved `@` validation) to be unit tested without persistence. No writes to disk; mutations affect only the in-memory state.
- **Asset location:** Under `packages/api/storage/assets/` (e.g. `store_test.json`) or similar; the exact path is an implementation detail.

---

## 9. Integration points

- **Config:** A way to select the backend (e.g. `storage_backend: str = "ephemeral"` or `"file"`) so the app uses the desired implementation. Default can be the asset-backed in-memory backend for development and testing. See storage.mdc “Adding a New Implementation”.
- **Core API app:** Register a router for the store (e.g. `routers/store.py`) under `/v1/store` (the Core API app is mounted at `/api`, so the full path is `/api/v1/store`). Router calls a **store service**; the service uses an injected `StorageBackend` and performs create/read/update/delete with the semantics above (including auto-ancestor creation on create only and atomicity), raising the appropriate Core API exceptions.
- **No BFF or frontend changes** in this enhancement.

---

## 10. Deliverables (acceptance)

1. **Abstract interface:** Storage protocol in Python (in `packages/api/storage/`) used for all store access; get/put/delete/list with path-based keys and `JSONValue` payloads.
2. **Test implementation:** In-memory backend initialized from a static JSON asset; full CRUD supported so all operations and semantics can be unit tested.
3. **CRUD REST API:** Core API endpoints for Create (PUT), Read (GET), Update (POST), Delete (DELETE) with path-based resource identification; semantics and error mapping as above. Paths support array indexing via the reserved `@` convention (§11); payloads with any object key starting with `@` are rejected (422); full traversal on insert for validation. Create auto-creates missing ancestor objects; update does not. Write operations are atomic.
4. **Read query modes:** GET supports `view=full|shallow` where `shallow` returns one-level child enumeration and node metadata to avoid full-subtree fetch for hierarchy traversal.
5. **Tests for advanced features and query modes:** Implementation includes unit tests for array-index path resolution, reserved `@` key payload validation (deep traversal), array merge mode behavior (`merge=append`, `merge=prepend`), read query mode behavior (`view=full|shallow`), and atomic failure semantics.

---

## 11. Path resolution rules (normative)

Path resolution is deterministic and evaluated segment by segment:

1. Split path by `/` (no leading slash in logical path).
2. For a normal segment `s`, current node must be an object containing key `s`.
3. For an index segment `@N`:
   - segment syntax must parse as integer `N`, else `ValidationError` (422);
   - current node must be an array, else `ValidationError` (422);
   - resolved index must be in range (including negative-index normalization), else `NotFoundError` (404).
4. If any lookup step fails under these rules, stop and raise the mapped distinguished error.

Examples:

- `planets/sol/earth/@2`: index 2 of array at `planets/sol/earth`
- `planets/sol/earth/@-1`: last element of that array
- `planets/sol/earth/@abc`: invalid segment format -> 422
- `game/turn/@0` when `game/turn` is an object -> 422
- `planets/sol/earth/@10` on a 3-element array -> 404

---

## 12. Array indexing: reserved `@` convention

From the first implementation, paths support **per-element array indexing** via an explicit convention so that an index is never confused with an object key.

**Convention:**

- **Reserved segment form:** A path segment that is **`@` followed by an integer** (e.g. `@0`, `@2`, `@-1`) means “array index at this step.” The parent path must resolve to an array; otherwise the request is a distinguished validation error (422). Example: `planets/sol/earth/@2` is “element at index 2 of the array at `planets/sol/earth`”.
- **Negative indexes:** Allowed with the usual meaning: `@-1` = last element, `@-2` = second-to-last, etc. Out-of-range index (e.g. `@10` on a 3-element array) is a distinguished error (e.g. 404).
- **Literal `@` in object keys:** The character `@` as the **first character of any object key** is **reserved**. Any attempt to **insert** (Create via PUT, or Update via POST) a payload that contains such a key anywhere in its nested structure must be rejected with a **distinguished validation error** (422, see §6 `ValidationError`). This keeps the path model unambiguous: a segment `@2` always means array index, never the object key `"@2"`.
- **Validation on insert:** Because the payload may be a nested JSON structure, the server must **traverse the entire payload** on create/update to ensure no object key starts with `@` before performing the write. If any key does, reject the request with the validation error and do not modify the store.
- **Path resolution:** See the normative algorithm in §11.

---

## 13. Open points for implementation

- **Array merge:** Implemented as query param `merge=append` or `merge=prepend`; for append/prepend the body may be a single value or an array (single value is appended/prepended; array is extended or prepended in order).
- **Read query mode growth:** Whether to add optional `depth`, `limit`, and `offset` parameters in a later enhancement while keeping `view=full|shallow` stable.
- **Router prefix:** Core API router prefix is `/v1/store`; with the Core API app mounted at `/api`, the full path is `/api/v1/store`.

---

## 14. References

- [storage.mdc](../.cursor/rules/storage.mdc) — StorageBackend protocol, key naming, no concrete impl outside storage.
- [core-api.mdc](../.cursor/rules/core-api.mdc) — Routers, services, no storage in routers.
- [server-exceptions.mdc](../.cursor/rules/server-exceptions.mdc) — CoreAPIError hierarchy and HTTP mapping.

---

## Addendum: Summary of storage unit tests

The storage implementation is covered by four test modules under `packages/api/tests/`:

**Path utilities (`test_path_utils.py`)**  
- **Index segment parsing:** Valid `@N` / `@-N` parsing; invalid segments (`@abc`, `@`, `@1.5`) raise `ValidationError`.  
- **Path resolution:** Empty path returns root; object-key traversal; array index traversal (`@0`, `@-1`, etc.); index out of range or missing key raises `NotFoundError`; index segment on non-array or malformed segment raises `ValidationError`.  
- **Children listing:** Objects yield sorted keys; arrays yield `@0`..`@(n-1)`; primitives yield `[]`.  
- **Reserved `@` in payloads:** Payloads with no key starting with `@` are accepted; any key starting with `@` (top-level or nested) raises `ValidationError`.  
- **Deep copy:** `deep_copy_value` returns an independent copy (mutations do not affect the original).

**Ephemeral backend (`test_memory_asset_backend.py`)**  
- **Get:** Root and nested paths; array-index paths; deep copy on read (caller cannot mutate store); missing path raises `NotFoundError`.  
- **Put:** Creates missing object ancestors; overwrites existing node; array append (put at `@len`) and set at existing index.  
- **Delete:** Removes node at path; delete of array element; delete root clears store; missing path raises `NotFoundError`.  
- **List:** Root and prefix listing; array nodes return `@0`..`@(n-1)`; missing prefix raises `NotFoundError`.  
- **Empty initial:** Backend with `{}` accepts put and get.

**Store service (`test_store_service.py`)**  
- **Create:** New path succeeds; existing path raises `ConflictError`; payload with reserved `@` key raises `ValidationError`.  
- **Read:** Existing path returns value; missing path raises `NotFoundError`.  
- **Read shallow:** Object node returns path, `node_type`, children, count; array node returns `@0`..`@(n-1)` and count.  
- **Update:** Deep merge for objects; array replace; array append/prepend via `merge_array`; object↔array or primitive↔object type change raises `ConflictError`; reserved `@` key raises `ValidationError`; missing path raises `NotFoundError`.  
- **Delete:** Removes node; missing path raises `NotFoundError`.

**Store REST API (`test_store_router.py`)**  
- **GET:** `view=full` returns node JSON; `view=shallow` returns path, `node_type`, `children`, `count`; invalid `view` returns 422; missing path returns 404.  
- **PUT:** Create returns 201 and body; existing path returns 409; payload with `@` key returns 422.  
- **POST:** Merge returns 200; `merge=append` / `merge=prepend` for arrays; invalid `merge` returns 422.  
- **DELETE:** Success returns 204; missing path returns 404.  

Tests use a per-test in-memory backend (or service over that backend) so all CRUD behaviour and error mapping are exercised without persistence.
