# Player color resolution context

Status: accepted

## Context

**Player color** started as `colorForPlayerId(playerId)` with an override storage port so Settings ([#289](https://github.com/SteveDraper/Planets-Console/issues/289)) could wire persistence without touching paint call sites. **Player color mode** adds a **diplomacy-family** policy with two families (**diplomacy color family** and **non-diplomacy color family**) that also needs shell **viewpoint**, turn `Relation` inbound grants, **diplomacy color threshold**, **family base color**, **out-of-circle base color**, and the current game roster. Threading those inputs through every consumer would make fleet rings and future chrome diplomacy-aware at every call site.

## Decision

- Keep consumer entry points as `usePlayerColor(playerId)` / `colorForPlayerId(playerId)`.
- Install a shell-level **player color paint snapshot** (built from resolution inputs) that those entry points consult -- same port pattern as today's override store. Inputs:
  - active **player color mode**
  - per-player overrides
  - **diplomacy color threshold**
  - **family base color** (in-circle)
  - **out-of-circle base color** (non-diplomacy family)
  - viewpoint id
  - inbound relations from the loaded turn (`relationfrom` by other player id)
  - roster player ids (for out-of-circle membership)
- In **diplomacy-family** mode:
  - **Diplomacy color family**: viewpoint is always a member (implicit self-ally, brightest tone) plus others with inbound `relationfrom >= threshold`; members share **family base color** with tonal variants.
  - **Non-diplomacy color family**: every roster player not in the diplomacy circle; members share **out-of-circle base color** with tonal variants (no special brightest member).
  - Fall back to the default per-player palette only when viewpoint (and thus family membership) is unavailable -- not for out-of-circle players when families are active.
- Expose the minimal turn `Relation` fields to the SPA for membership; do not use host `Relation.color`.

## Consequences

- Call sites stay mode-agnostic; Settings + shell own wiring.
- Out-of-circle players stay in the second family; they do not revert to the default preset while diplomacy-family mode has a viewpoint.
- [#289](https://github.com/SteveDraper/Planets-Console/issues/289) owns both modes, both family bases, and the BFF relations slice.

Glossary: **Player color**, **player color mode**, **diplomacy color family**, **non-diplomacy color family**, **diplomacy color threshold**, **family base color**, **out-of-circle base color** in [CONTEXT.md](../../CONTEXT.md).
