# Frontend BFF contract codegen slices

Status: accepted

The SPA types its BFF calls from generated TypeScript (`openapi-typescript`) plus targeted runtime validators. A single `schema.ts` from the full BFF OpenAPI document crossed 1k lines and regrew on unrelated route changes (games, concepts, load-all REST). Future work is **analytics-heavy**, but today `GET /analytics/{analytic_id}/table|map` responses are **`unknown` in OpenAPI** -- handlers return `dict` and the SPA already types table/map per analytic in `src/analytics/<id>/` and `bff.ts`. Splitting generated code **by analytic id** would not match how the BFF is shaped unless we add per-analytic response models later.

We split **central** codegen by **regeneration boundary** aligned with BFF router mounts, using **filtered OpenAPI dumps** (v1): one full dump from `bff.app`, then `scripts/filter_bff_openapi.py` subsets paths by prefix (e.g. `/games`, `/shell`, `/diagnostics`, `/analytics`) and embeds **full transitive `$ref` closure** per slice (duplicate schemas such as `HTTPValidationError` across slice JSON files are acceptable). `openapi-typescript` emits one `schema-<slice>.ts` per subset. Root `/health` rides with the shell slice (or a tiny misc slice). No separate `schema-shared` until cross-slice TypeScript imports justify it. `make generate` / `npm run generate:api` runs dump → filter → per-slice codegen.

**Turn analytic wire contracts** (table/map JSON for a given `analytic_id`) default to the owning feature under `src/analytics/<analytic_id>/` (hand types, Zod, normalizers) -- not to per-analytic generated files. **NDJSON streams** (e.g. load-all progress) use Zod + `z.infer` in `src/api/`; OpenAPI may document them for spec visibility but the parser module is authoritative.

**Imports:** application code imports the **smallest** generated slice it needs (`schema-games`, `schema-shared`, ...). `bff.ts` stays the HTTP facade. Do **not** reintroduce a barrel `schema.ts` that re-exports every slice.

## Considered options

- **Single monolithic `schema.ts`** -- simple codegen; every BFF OpenAPI change rewrites the whole file and review noise scales with unrelated domains.
- **Split by line count** -- arbitrary boundaries; same full regeneration from one dump.
- **One generated file per analytic** -- fits product growth narrative but mismatches generic analytics routes and untyped responses today; would require per-analytic OpenAPI models or dedicated paths first.
- **Redocly-only multi-output (no filter script)** -- viable later; deferred for v1 to stay aligned with existing Python `generate:api:dump`.
- **Multiple live BFF OpenAPI endpoints per router** -- enforces slices in FastAPI but adds mount/schema drift risk.
- **Re-export barrel `schema.ts`** -- convenient imports but recreates a monolith in git and obscures which slice regened.

## Consequences

- Add and maintain `scripts/filter_bff_openapi.py` (Python) to subset the dump before `openapi-typescript`; extend `npm run generate:api` / `make generate` to run dump → filter → per-slice codegen.
- **Migration (done):** `bff.ts` and `bffCartographyTypes.ts` import the smallest slice (`schema-games` for current paths); monolithic `src/api/schema.ts` is removed. `generate:api` emits slices only.
- **CI:** `make ci` runs `make check_frontend_api_slices` (`openapi-typescript --check` per slice after dump + filter). A follow-up guard fails CI if monolithic `src/api/schema.ts` reappears (issue #60).
- When adding BFF routes, know which slice regens (games vs shell, etc.).
- New **turn analytics**: type payloads in `src/analytics/<id>/`; only promote to OpenAPI + a generated slice when a strict shared contract is worth the cost.
- New **streams** or line protocols: Zod-owned module, not a new OpenAPI monolith.
- `architecture.mdc`, `frontend-react.mdc`, and **CONTEXT.md** (**BFF contract codegen slice**, **Filtered OpenAPI dump**, **Generated schema import rule**, **Turn analytic wire contract**) are the operational references. `make generate` / `npm run generate:api` runs dump → filter → per-slice codegen only.

See also: [CONTEXT.md](../../CONTEXT.md), [architecture.mdc](../../.cursor/rules/architecture.mdc) (Frontend BFF contracts), [ADR 0002](0002-analytic-persistence.md) (homeworld and other persisted analytics).
