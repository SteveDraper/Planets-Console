# Backfill walk stamps the fleet evidence mark without bumping it

Status: accepted

With **Backfill earlier turns** on, one shell-turn walk persists scoreboards and fleet ledgers across many host turns for one player. Under the ordinary rule each of those persists would bump **fleet evidence generation** and discard in-flight work built from the previous prior, which would restart the walk on every hop. The walk is one refresh: it stamps the generation it started with and does not bump. A scoreboard persist bumps only when it belongs to no in-flight on-walk for that player. Two open shell turns can each have a walk; a persist that belongs to either of them stamps, so the walks do not discard each other.

An absent mark becomes generation 1 with `appliesFromTurn` at the **analytic export ensure baseline** before the first persist. An existing mark keeps its generation, and `appliesFromTurn` moves backward only to the earliest turn that walk refreshes.

## Considered options

- Bump on every hop. Later hops built from the previous generation are discarded, and the shell row returns to subject to revision on each persist.
- Bump when a persist is outside one walk even if another in-flight on-walk for that player submitted it. The other walk is discarded and the two open turns restart each other.
