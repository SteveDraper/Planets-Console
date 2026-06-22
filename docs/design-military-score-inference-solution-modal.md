# Design: Military score inference solution detail modal

Player-facing UX for inspecting ranked build-inference explanations from the Scores analytic. **Implementation tracker:** GitHub issue #48. **Parent epic:** #39.

**Related:** [design-military-score-build-inference.md](design-military-score-build-inference.md), [design-military-score-build-inference-implementation.md](design-military-score-build-inference-implementation.md) (sections 7.2--7.3), repo root `CONTEXT.md` (**Inference solution detail modal**, **Inference solution plausibility (display)**).

---

## 1. Purpose

When build inference is enabled and a scoreboard row holds at least one exact explanation, the player opens a modal to compare ranked alternatives: what actions might explain the row's scoreboard deltas, how each alternative sums to the observed military change, and how plausible each alternative is relative to the others.

The modal is **not** a developer diagnostics surface. Equality strings, raw 2× scale, full `accelerated_segments` arrays, priority-point constraint notes, and spectator delta-source notes belong in the Scores diagnostics panel.

---

## 2. When the modal opens

| Row state | Modal |
|-----------|-------|
| `success` or `paused` with **N > 0** | Opens on **inference solution count indicator** click |
| Pending with **N = 0** | Badge disabled; tooltip only |
| Red cross (`failure`, no exact explanation) | No modal; rich `title` / tooltip from row `summary` and diagnostics |
| Stopped (octagon) without held solutions | No modal |
| `no_prior_turn` | No modal |

Closing the modal must **not** reset the Scores **Include build inference** checkbox.

A separate **failure diagnostic modal** for red-cross rows is **out of scope** for #48.

---

## 3. Live updates while search runs

The modal binds to live `inferenceByRow[rowIndex]` state. While `isComplete` is false:

- Held solutions and the badge count **update in place** as stream `solution` events arrive.
- Show a bottom banner: **Search continuing -- more explanations may appear.**
- Do **not** show the amber "stopped before all alternatives were explored" wording during active search.

When **inference global pause** is active:

- Banner: **Search paused -- held explanations are current.**

When the row completes naturally (`isComplete: true`), omit the continuing banner.

---

## 4. Modal chrome (header)

Player-facing only:

- Title: **Build inference**
- Race and player name (from scoreboard row)
- Scoreboard row turn, host-turn deltas line, player id when known
- **Observed constraints** section: military, warship, freighter, and priority-point deltas in **scoreboard units** (integer military change from `militaryDelta2x // 2` -- no 2× parenthetical)

**Omit from the modal:**

- **Priority point constraint note** (`priorityPointConstraintNote`) -- Scores diagnostics panel only (#50 diagnostic-only mode)
- **Spectator delta-source note** when `scoreboardDeltaSource` is `prior_row_total_diff` -- Scores diagnostics panel only
- `detail.summary` body text (remains on badge tooltip)
- `appliedEqualities` bullets
- Developer-oriented solver internals beyond status label and wall time

**Status line:** overall inference status (row `status`, not last sub-pass `solver_status`) and `wall_time_seconds` when present.

---

## 5. Accelerated start (internal segments)

Accelerated-start inference may solve multiple **inference accelerated segments** internally (accel window vs reported host turn). The SPA must **not** render a multi-segment layout or accelerated-start explanatory copy.

Core already promotes the segment relevant to the **scoreboard row being displayed** to the top-level row payload:

- First reliable accelerated row: top-level `solutions` and `constraints` come from the `reported_host_turn` segment (`is_streaming_target`).
- Accelerated backfill rows: segment selected by `hostTurn` matching the row's host turn.
- Normal rows: standard policy-ladder payload.

The modal always renders `detail.solutions` and `diagnostics.constraints` like any other row. Full `diagnostics.accelerated_segments` remains for the Scores diagnostics panel only.

---

## 6. Ranked solutions list

- Show **all** held top-K solutions (up to K = 20) in descending **inference solution rank weight** order (`objectiveValue` on the wire).
- Modal scrolls within `max-h` (~90vh); no collapse or pruning in #48.
- **Follow-on:** relative probability pruning and tail collapse -- see issue #88.

---

## 7. Per-solution layout

Each solution is one block:

### 7.1 Header

`Solution {n} · Plausibility {objectiveValue}`

**Plausibility** is the UI label for wire field `objectiveValue` (**inference solution rank weight** in the glossary). Higher integer means more plausible. Treat it as **plausibility on a pseudo log-likelihood scale**: prior bin and combo weights are derived from `SCALE * log(p)` at catalog build, then summed (with ranking heuristics) into one integer rank score -- monotonic with prior support, but **not** a percentage, calibrated probability, or exact joint log-likelihood. Optional tooltip: *Composite rank score from action priors and parsimony penalties -- not a percentage.*

Do not show raw solver sub-status strings (e.g. per-pass `INFEASIBLE`).

### 7.2 Action table

One table per solution. **One row per line item** from `militaryScoreArithmetic.lineItems` (aggregate actions and ship builds share the same row shape).

| Column | Content |
|--------|---------|
| **Icon** | See section 8 |
| **Description** | Core `label` (includes count in prose where applicable, e.g. `2x Planet defense post`, `Build Missouri: 2x Transwarp Drive, ...`) |
| **Military** | Line **subtotal** (`militaryChangeSubtotal`, signed integer scoreboard units) |

Column headers: **Icon** (visually empty or aria-only), **Action**, **Military**.

### 7.3 Footer (reconciliation)

Slim footer below the table:

- **Explained military change** -- sum of line subtotals (`explainedMilitaryChange`)
- **Observed military change** -- from arithmetic payload (`observedMilitaryChange`)
- Amber warning when `matchesObserved` is false

---

## 8. Row icons

Icons are **presentation only**; no Core concept route or inference payload extension.

### 8.1 Ship builds

- Implement `hullImageUrl(hullId, options?)` in the frontend (`packages/frontend/src/concepts/`), mirroring Planets.nu client `hullImg` / CDN path rules (`https://mobile.planets.nu`, 3D portrait `_p.png` default). Vitest golden cases cover normalization (race-variant ids), 3D vs classic, beam suffix on hulls 65 and 71.
- Resolve icon from `shipBuilds[].hullId` when present; else infer hull from `comboId` on the line item when needed.
- **Generic freighter** builds: use the LDSF hull id constant until a dedicated freighter glyph exists.

### 8.2 Aggregate actions

Map by `actionId` prefix / family to **Lucide** category glyphs until Planets.nu assets exist:

- Torpedo loads (`ship_torps_loaded_*`)
- Fighters (starbase, ship, transfers)
- Defense posts (planet, starbase)
- Unknown: neutral placeholder

**Follow-on:** Planets.nu art for aggregate families -- issue #89.

### 8.3 Accessibility

Fixed-width icon column (~32--40px). Decorative hull images use `alt=""`; description column carries readable text.

---

## 9. Wire contract (consumer notes)

- Parse `shipBuilds` in `readInferenceSolution` so stream events retain `hullId` for icons.
- `militaryScoreArithmetic.lineItems` may use `actionId` or `comboId`; both are valid row keys.
- Modal does not branch on `diagnostics.accelerated_segments` for layout.

---

## 10. Testing (#48)

Frontend tests (`InferenceDetailModal.test.tsx` and helpers):

- Modal open/close and focus trap (existing)
- Observed constraints in modal; PP note and spectator delta-source note **not** in modal (Scores diagnostics panel only)
- Per-solution table: labels, military subtotals, footer reconciliation
- Plausibility header from `objectiveValue`
- No accelerated-segment multi-section UI
- No `appliedEqualities` or `detail.summary` body
- In-progress vs paused banner wording
- `hullImageUrl` unit tests (golden URLs)

---

## 11. Issue map

| Issue | Scope |
|-------|-------|
| **#48** | This modal UX (icon table, plausibility header, live updates, accelerated segment UI removal) |
| **#53** | Scores **diagnostics panel** combo/tier presentation (not modal) |
| **#88** | Relative plausibility field + solution-list pruning |
| **#89** | Planets.nu aggregate-action icons (replace Lucide fallbacks) |
