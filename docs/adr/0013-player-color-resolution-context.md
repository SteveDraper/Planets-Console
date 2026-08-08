# Player color resolution context

Status: accepted

## Context

**Player color** started as `colorForPlayerId(playerId)` with an override storage port so Settings ([#289](https://github.com/SteveDraper/Planets-Console/issues/289)) could wire persistence without touching paint call sites. **Player color mode** adds a **diplomacy-family** policy that also needs shell **viewpoint**, turn `Relation` inbound grants, **diplomacy color threshold**, and **family base color**. Threading those inputs through every consumer would make fleet rings and future chrome diplomacy-aware at every call site.

## Decision

- Keep consumer entry points as `usePlayerColor(playerId)` / `colorForPlayerId(playerId)`.
- Install a shell-level **player color resolution context** (active **player color mode**, per-player overrides, **diplomacy color threshold**, **family base color**, viewpoint id, inbound relations from the loaded turn) that those entry points consult -- same port pattern as today's override store.
- Expose the minimal turn `Relation` fields to the SPA for membership; do not use host `Relation.color`.

## Consequences

- Call sites stay mode-agnostic; Settings + shell own wiring.
- Missing relations / no viewpoint fall back to the default palette.
- [#289](https://github.com/SteveDraper/Planets-Console/issues/289) owns both modes and the BFF relations slice.

Glossary: **Player color**, **player color mode**, **diplomacy color family**, **diplomacy color threshold**, **family base color** in [CONTEXT.md](../../CONTEXT.md).
