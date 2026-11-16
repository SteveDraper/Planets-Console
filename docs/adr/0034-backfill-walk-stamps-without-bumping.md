# Backfill walk stamps the fleet evidence mark without bumping it

Status: accepted

With **Backfill earlier turns** on, one shell-turn walk persists scoreboards and fleet ledgers across many host turns for one player. Under the ordinary rule each of those persists would bump **fleet evidence generation** and discard in-flight work built from the previous prior, which would restart the walk on every hop. The walk is one refresh: it stamps the generation it started with and does not bump. A scoreboard persist bumps only when no on-walk execution for that player produced it. Two open shell turns can each have a walk; a persist produced by an execution of either walk stamps, so the walks do not discard each other.

An absent mark becomes generation 1 with `appliesFromTurn` at the **analytic export ensure baseline** before the first persist. An existing mark keeps its generation, and `appliesFromTurn` moves backward only to the earliest turn that walk refreshes.

When a persist does bump, under either setting, the bump restarts that player's live walks and nothing else. It aborts the player's in-flight fleet and scoreboard work, so the old walk submits no further hop and stamps nothing, except, with the setting off, a step already executing off the walk on a turn a live row shows. It publishes the new mark and epoch in the same orchestrator lock hold as that settle, so no plan registers against the old mark. It then reschedules the player's live rows at the bumped turn and later, and any live row whose own work it stopped. Each rescheduled row re-admits with the current setting, so with the setting on it submits the replacement walk. A turn no live row shows keeps its old generation until it is opened.

## Considered options

- Bump on every hop. Later hops built from the previous generation are discarded, and the shell row returns to Provisional on each persist.
- Bump when a persist is outside one walk even if an on-walk execution of another walk for that player produced it. The other walk is discarded and the two open turns restart each other.
- On a bump, keep and wake submission-root turns, or every known turn with the setting on. Roots outlive their streams, so off-screen work kept stamping the new mark and turns no one was looking at were recomputed.
- On a bump, let running walk work finish without stamping. A doomed solve then runs to the end, and a joiner inherits its refusal; aborting gives the same outcome sooner.
