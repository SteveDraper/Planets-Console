# Uncharacterized roster closes the count lattice without a military SAT

When a **count-lattice signal** has no **departure pin** on a class that can move military, leftover is not a point mine residual and a last-turn unique-fill is not a hull. **Decision:** refuse military SAT, persist **uncharacterized roster** with **placeholder departure**s and tagged **unknown-loss leftover**, and put idle-dock class alternatives on **lattice signature**s -- not `solutions[]`, not `exact`.

**Considered:** reuse `no_exact_solution` / `moderate_residual` (wrong claim: we refused search); reuse `exact` with a fake hull (unique-fill occupancy); put class pairs in `solutions[]` (SAT signature merge/stream); copy a construction envelope onto the placeholder (next-turn decrease candidate).

Glossary: **Count-lattice signal**, **departure pin**, **known spec**, **placeholder departure**, **unknown-loss leftover**, **lattice signature**, **uncharacterized roster** in [CONTEXT.md](../../CONTEXT.md). Contract: [design-military-score-build-inference.md](../design-military-score-build-inference.md) §3.12. Ticket: [#483](https://github.com/SteveDraper/Planets-Console/issues/483). Implementation: [#486](https://github.com/SteveDraper/Planets-Console/issues/486)–[#491](https://github.com/SteveDraper/Planets-Console/issues/491).
