# Design: Shell error handling and display

This document describes how the Planets Console SPA surfaces failures from the BFF (and how the BFF client shapes messages). It is the reference for extending error reporting without scattering one-off UI.

---

## 1. Goals

- **One obvious place** for user-visible errors: a full-width bar between the header and main content, not tiny text beside individual controls.
- **Multiple concurrent errors**: each failure adds a row; rows are independent.
- **User control**: each row can be dismissed; when none remain, the bar is hidden.
- **Actionable text**: generic HTTP or gateway failures should include **which BFF endpoint** failed so logs and support can correlate quickly.
- **Layering**: the SPA continues to talk **only to the BFF**; error text ultimately reflects BFF JSON (`detail`) or transport-level status when the body is not useful.

---

## 2. Non-goals

- Replacing server-side logging or structured error codes from Core/BFF.
- Global toast systems or modal stacks for routine failures (the shell bar is the primary pattern for now).
- Persisting dismissed errors across reloads.

---

## 3. UI: `ShellErrorBar`

**Location:** `packages/frontend/src/components/ShellErrorBar.tsx`

**Placement:** Rendered in `ConsoleShell` (`App.tsx`) **immediately below** `Header` and **above** the flex row that contains `AnalyticsBar` and `MainArea`.

**Behaviour:**

| State | UI |
|--------|-----|
| `errors.length === 0` | Renders nothing (no reserved height). |
| One or more items | Full-width strip with stacked rows; height follows content. |

**Each row:**

- Plain-text message (wraps with `break-words`).
- Dismiss control with an **X** icon, `aria-label="Dismiss error"`.
- Removing the last row hides the bar.

**Accessibility:** Container uses `role="alert"` and `aria-live="polite"` so screen readers are notified when new errors appear.

**Data shape:** `ShellErrorItem { id: string; message: string }`. `id` is a client-generated UUID so lists remain stable when messages duplicate.

---

## 4. Shell state and producers

**Where state lives (see [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md)):** **Zustand** holds session and shell context (game, turn, perspective). **TanStack Query** holds BFF GET responses. **`ConsoleShell`** in `packages/frontend/src/App.tsx` keeps **local** `shellErrors` and exposes:

- `addShellError(message: string)` -- appends a new row.
- `dismissShellError(id: string)` -- removes one row.

**Who calls `addShellError` today:**

1. **Game info refresh (mutation)**  
   `useMutation` `onError` for `refreshGameInfo`. Client-side validation (e.g. missing login name) throws before fetch; that also flows through `onError` as an `Error` message.

2. **Analytics list (query)**  
   `useEffect` on `useQuery` for `['bff', 'analytics']`. A **ref** (`analyticsFailureSeen`) ensures **one** bar row per continuous failure spell, so a stuck failed query does not append a new row on every render. When the query leaves the error state, the ref resets so a later failure can add a row again.

3. **Games list (query)**  
   `GameControl` receives `reportShellError` (same as `addShellError` from the shell). When the popover opens and `fetchGames` fails, a similar **ref** pattern avoids duplicate rows while `isError` stays true.

**Header / GameControl:** Inline error text next to the game control was **removed** in favour of the bar; the games popover may show a short neutral hint pointing at the bar when the list fails.

**Analytics:** The previous full-page "Failed to load analytics" block was removed; the shell still renders `MainArea` after loading completes, and the bar carries the failure message.

**TanStack Query retries (queries):** Failed **queries** use bespoke retry rules so obvious client or upstream errors surface quickly (e.g. **502** from planets.nu for forbidden perspective is **not** retried). Full table and rationale: [design-frontend-and-backend-state.md §2](design-frontend-and-backend-state.md#2-frontend-tanstack-query-server-state) (`queryRetry.ts`). **Mutations** remain **`retry: false`**.

---

## 5. BFF client: messages and generic server errors

**Module:** `packages/frontend/src/api/bff.ts`

All BFF `fetch` helpers throw `Error` with a **string message** derived from:

1. JSON body `detail` when present and parseable (FastAPI style), else  
2. `response.statusText`, else  
3. `String(response.status)`.

**Generic server errors:** Some responses carry little information (`Internal Server Error`, bare `500`, common 502/503/504 phrases). For those, the client appends a **static endpoint label** so the bar shows e.g.:

`Internal Server Error (POST /bff/games/663307/info)`

**Rules (see `isGenericServerErrorMessage` and `withEndpointIfGeneric`):**

- Treated as generic: empty message, `internal server error`, `bad gateway`, `service unavailable`, `gateway timeout`, or a message that is **only** a three-digit **5xx** code.
- **Not** decorated: specific API text such as validation or auth messages (e.g. `Login credentials are required.`).
- If the message already contains the endpoint label, it is **not** duplicated.

Endpoint labels are method plus path only (no host), e.g. `GET /bff/games`, `POST /bff/games/{id}/info`, `GET /bff/analytics/{id}/map`.

---

## 6. Architecture alignment

- **Frontend never calls Core REST** directly; all errors originate from BFF calls or pre-fetch validation in the SPA.
- Improving user-visible text for **unhandled** server exceptions is primarily a **BFF/Core** concern (return a structured `detail`). The shell bar displays whatever message the client builds; generic decoration is a **client-side** supplement only.

---

## 7. Tests

- `packages/frontend/src/components/ShellErrorBar.test.tsx` -- empty vs rows, dismiss callback.
- `packages/frontend/src/api/bff.test.ts` -- generic vs specific messages and endpoint suffix behaviour.

---

## 8. Future extensions

- **Retry** actions per row (e.g. "Retry refresh") keyed by error source.
- **Correlation id** if BFF adds `X-Request-Id` or similar; append to message or subtitle.
- **Central registry** of `addShellError` via context if deep subtrees need to report without prop drilling (today `reportShellError` is passed through `Header` to `GameControl` only where needed).

---

## 9. File index

| Piece | Path |
|--------|------|
| State split (Zustand, TanStack Query, backend) | [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md) |
| Error bar UI | `packages/frontend/src/components/ShellErrorBar.tsx` |
| Shell error list and wiring | `packages/frontend/src/App.tsx` |
| BFF client and generic suffix | `packages/frontend/src/api/bff.ts` |
| Query retry policy (TanStack default) | `packages/frontend/src/lib/queryRetry.ts` |
| Games list reporting | `packages/frontend/src/components/GameControl.tsx` |
