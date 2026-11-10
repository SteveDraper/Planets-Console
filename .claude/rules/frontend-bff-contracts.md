---
paths:
  - "packages/frontend/**/*.{ts,tsx}"
  - "packages/bff/**/*.py"
---

# Architecture: frontend/BFF contracts

## Frontend BFF contracts: OpenAPI codegen and Zod

See [docs/adr/0003-frontend-bff-contract-codegen.md](../../docs/adr/0003-frontend-bff-contract-codegen.md) for the full decision (filtered OpenAPI dumps, router-aligned slices, per-analytic feature typing).

The BFF OpenAPI schema (`/bff/openapi.json`) is the default source of frontend TypeScript types for **router-stable REST**. Generated output lives in `packages/frontend/src/api/schema-<slice>.ts` modules (e.g. `schema-games.ts`, `schema-shell.ts`) produced from **filtered OpenAPI dumps** per BFF mount prefix, each with full component closure for that slice -- not one monolithic `schema.ts` (see `.claude/rules/bff.md` and `.claude/rules/frontend-react.md` for regeneration). Import the smallest slice a file needs; use `bff.ts` as the HTTP facade. CI fails if monolithic `src/api/schema.ts` reappears (`make check_frontend_api_no_monolithic_schema`, part of `make ci`). Use `components['schemas'][...]` or `paths[...]` from the appropriate slice for ordinary REST JSON: single request bodies, single JSON responses, and query-shaped reads.

**Turn analytic** table/map payloads are **not** central-codegen-owned by default: type them under `src/analytics/<analytic_id>/` because BFF `GET /analytics/{analytic_id}/table|map` responses are handler-specific `dict`s (OpenAPI `unknown`). Promote an analytic to explicit OpenAPI models only when a strict shared contract justifies it.

**Prefer Zod as the single source of types and runtime validation** when the frontend must validate untrusted wire data before use, especially:

- **NDJSON or other line/stream protocols** where each chunk is parsed independently (e.g. load-all progress streams).
- **Discriminated unions consumed incrementally** where duplicating the same shapes in OpenAPI types and a second validator would drift.
- **Client-only or partially typed payloads** where `response.json()` or stream bytes are not fully described by one OpenAPI response model.

In those cases:

1. Define Zod schemas in a dedicated module under `src/api/` (e.g. `loadAllStreamEventSchema.ts`), colocated with the parser.
2. Export shared TypeScript types with `z.infer<typeof ...>` from that module -- not from `schema.ts` and not as hand-written duplicates.
3. Parse through `safeParse` (or equivalent), map failures to stable user-facing messages in one place, and re-export types from a thin parser module if convenient (`parseLoadAllStreamEvent.ts`).
4. Keep using the relevant `schema-<slice>.ts` module for the rest of the feature (status endpoints, request bodies, non-stream responses).

Do **not** maintain the same wire shape in both `components['schemas'][...]` imports and parallel Zod objects. Pick one owner per shape. The BFF may still document stream event variants in OpenAPI for contract visibility; the frontend stream path treats the Zod module as authoritative for types and validation.

**Adding a new Zod-owned contract:** extend the BFF OpenAPI when the route should appear in the spec, add Zod schemas + parser under `src/api/`, wire the BFF client to the parser, and add unit tests on parse success and failure. Regenerate only the OpenAPI-owned slice(s) for types that stay in codegen.
