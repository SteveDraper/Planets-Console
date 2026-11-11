---
paths:
  - "packages/api/api/analytics/**/*.py"
  - "packages/api/api/compute/**/*.py"
  - "packages/api/api/streaming/**/*.py"
  - "packages/server/server/process_host/**/*.py"
---

# Architecture: turn analytics

## Turn analytics: orchestrator parity

Turn-scoped analytics that run through the **compute orchestrator** (export ensure, table streams, and table/map batch compute) must follow the **same template** for analogous concerns. Fleet ([#199](https://github.com/SteveDraper/Planets-Console/issues/199)) and scores inference ([#200](https://github.com/SteveDraper/Planets-Console/issues/200)) are the reference pair.

| Concern | Shared pattern | Analytic-specific |
|---------|----------------|-------------------|
| **Registration** | `scope_key_spec`, `compute_profile` (`ComputeStepSpec` per `step_kind`), `PersistencePolicy`, wire builders, `run_step` | Step kinds, backends, artifact shape |
| **Submission** | `ComputeRequest(scope, step_kind?, priority_band)`; the band is a standing band (`interactive_ensure` / `background`), and `stream_attached` comes only from the registration's `shell_stream_watch` | Entry step (`materialize` vs `tier_solve`, etc.) |
| **Step outcome** | Result wire declares `continue`, `persist`, `complete`, or `park` | What `persist` writes; reader gates on terminal quality; `park` demotes to `parked` until `force_fresh` wake |
| **Table stream adapter** | Process-wide observer/gate registration on the singleton orchestrator; `register_scope_outcome_listener` for wire events; scope guard + per-row run state; shared `stream_drain`; shared `row_run_admission` vocabulary (`RowRunPhase` / `PersistAdmission` / `RowLifecycleOp`) | Mid-step incremental events (e.g. inference `solution`); scores-only registry + `PersistDecision` + `apply_scores_row_lifecycle` (fleet cancel remains token-only -- [ADR 0006](../../docs/adr/0006-table-stream-lifecycle-invariants.md) §7) |
| **Durable persistence** | `PersistencePolicy.persist` on `persist` outcome only | Fleet `provenance.is_final`; scores durable turn-evidence statuses |
| **Invalidation** | `invalidation_generation` + epoch discard; analytic `invalidate` hook | Cross-analytic triggers (fleet ledger persist invalidates scores row) |
| **Dependencies** | `DependencyOutputs` on job wire; no blocking ensure in workers | `ENSURE_DEPENDENCIES` per export catalog |

Do not reintroduce per-analytic worker pools, adapter-owned durable persistence, or read paths that ignore terminal-quality metadata (e.g. `has_ledger` where `has_final_ledger` is required).

Full specification: [design-compute-orchestrator.md](../../docs/design-compute-orchestrator.md). Glossary: [CONTEXT.md](../../CONTEXT.md).
