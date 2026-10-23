# Backfill walk stamps the fleet evidence mark without bumping it

Status: accepted

With **Backfill earlier turns** on, one shell-turn walk persists scoreboards and fleet ledgers across many host turns for one player. Under the ordinary rule each of those persists would bump **fleet evidence generation** and discard in-flight work built from the previous prior, which would restart the walk on every hop. The walk is one refresh: it stamps the generation it started with and does not bump. A scoreboard persist outside that walk still bumps.

An absent mark becomes generation 1 with `appliesFromTurn` at the **analytic export ensure baseline** before the first persist. An existing mark keeps its generation, and `appliesFromTurn` moves backward only to the earliest turn that walk refreshes.

## Considered options

- Bump on every hop. Later hops built from the previous generation are discarded, and the shell row returns to subject to revision on each persist.
