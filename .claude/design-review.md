# Design review checklist (Planets Console)

Project-specific input to the `design-ticket` skill. The skill holds the process; this file holds what is particular to this codebase: when a ticket needs a design note, the forms of the design questions here, where background lives, and which rules the design must meet.

## Trigger criteria

A ticket needs a design note when it does any of the following:

- **Compute orchestrator:** changes `packages/api/api/compute/` (submission, ensure, dispatch, pools, root plans, submission opens), or adds a new kind of node or submission.
- **Shared ensure machinery:** changes the dependency walk (`analytics/export_dependency_walk.py`), the export catalog (`analytics/exports/catalog.py`) or registration fields that several analytics use.
- **Evidence and invalidation:** changes evidence marks, generations, stamping or bumping, or invalidation (`analytics/fleet/evidence_mark_store.py`, `analytics/off_mode.py`, `services/inference_invalidation_service.py`).
- **Table streams:** changes stream controllers, registries or the registry catalog under `packages/api/api/streaming/table_stream/`, or a stream's lifetime on the frontend (shell-lived versus tile-lived).
- **Concurrency:** adds threads, locks, listeners, outcome callbacks or background work anywhere.
- **Process-lived state:** adds module-level or class-level mutable state.
- **Cross-analytic rules:** adds a rule that fleet and scores (or any two analytics) must both apply.
- **Settings with side effects:** adds a setting whose change triggers work (for example submitting walks).

Tickets that only add a table column, a frontend control, a BFF reshaping or a self-contained analytic computation usually do not need one.

## Design questions, in this project's terms

Answer these in the note's "Design questions" sections.

1. **New state and its owner.**
   - Is any new state per node (carried on `SubmissionOpen` or the node), per orchestrator, per stream or durable?
   - Process-global or class-level registries need an explicit reason and an eviction story. Prefer state the node already carries.
   - Name who drops each piece of state and when. A waiter or listener must not outlive what it waits on.
2. **Extension points into shared code.**
   - Analytic-specific behaviour belongs in registration (`TurnAnalyticRegistration`, `AnalyticComputeRegistration`, export catalog fields, root-plan hooks), per the orchestrator parity rule.
   - No analytic-id comparisons in the orchestrator, the dependency walk or the stream catalog.
   - If a new hook is needed, say why no existing one fits.
3. **Rule homes.**
   - Each rule gets exactly one home: elimination, "absent mark", widen-backward-only, persist precedence, which analytics walk together, and similar.
   - Mark transitions belong on the mark type.
   - A decision used by two callers that read different inputs is two decisions sharing vocabulary, not one table with ignored inputs.
4. **Threads, locks and ordering.**
   - Name the thread for each new piece of work: request thread, compute worker pool, orchestrator outcome listener, or a new thread.
   - Request threads and outcome listeners must not do turn fetches from Planets.nu or other blocking I/O.
   - State which work runs under the orchestrator lock, and what another thread's dispatch can see between registering nodes and anything the plan writes afterwards.
5. **Durable writes.**
   - For marks, ledgers and rows: when is each written relative to node dispatch and to the first persist that reads it?
   - No write-then-roll-back sequences.
   - Prefer planning against an assumed value and writing once, under the lock that makes the plan visible.
6. **Types at module boundaries.**
   - Use typed protocols or dataclasses at each new boundary: no `getattr` lookups, `Any`, `object` fields narrowed by `isinstance`, or positional tuples that grow.
   - Stand-ins (for example the absent-process orchestrator) are declared against the same protocol as the real thing.
   - The repo has no static type checker, so say how each contract is enforced (protocol plus test, or construction).

## Background sources

- **Design documents** (read before code):
  - Orchestration and ensure: `docs/design-compute-orchestrator.md`, `docs/design-analytic-exports.md`, `docs/design-adding-a-turn-analytic.md`, `docs/design-analytics-structure.md`.
  - Fleet and scores: `docs/design-fleet-analytic.md`, `docs/design-military-score-build-inference.md`, `docs/design-military-score-build-inference-implementation.md`.
  - Other areas: `docs/design-frontend-and-backend-state.md`, `docs/design-player-elimination.md`.
- **ADRs:** `docs/adr/`, especially `0002-analytic-persistence.md`, `0004-fleet-per-player-persistence-and-ensure-provenance.md`, `0004-addendum-table-stream-session-framework.md`, `0005-compute-orchestrator.md` and `0006-table-stream-lifecycle-invariants.md`.
- **Glossary:** `CONTEXT.md`. Grep it for the ticket's terms; it is about 275K, so never read it whole.
- **Game domain:** delegate to the `planets-nu-wiki` sub-agent with the feature and specific questions whenever the design depends on game meaning (elimination, turns, scores, host rules). Do not read the wiki vault directly.

## Rules the design must meet

- `CLAUDE.md`: layer hierarchy and boundaries, "shared primitives live below features", "one policy, one encoding", no backward-compatibility shims.
- `.claude/rules/turn-analytics-orchestrator.md`: orchestrator parity between fleet and scores.
- `.claude/rules/implementation-quality.md`: search before writing, one owner per concept, no parallel ladders, typed boundaries.
- `.claude/rules/core-api.md`, `.claude/rules/storage.md` and `.claude/rules/frontend-react.md` where the ticket touches those layers.
