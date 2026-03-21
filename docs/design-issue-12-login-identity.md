# Design: Issue #12 - Login identity

**Source:** [GitHub Issue #12 - [Feature] Add login identity](https://github.com/SteveDraper/Planets-Console/issues/12)

This document describes the design for adding login identity to the console: a consistent header control (refresh icon + "Login:" label), a modal to collect name and password, and in-session state only (no persistence of credentials). **Implementation is out of scope** for this doc; it is a design and acceptance reference only.

---

## 1. Goal

- Replace the static "Login: —" in the top bar with a **consistent appearance** independent of login state:
  - A **refresh icon** (e.g. RefreshCw) to the left of "Login:" that is always present and acts as a button to open the login modal (log in or change login).
  - **"Login:"** is always a label; the value shown is the current login name or "—" when none is set.
- There is no requirement to re-establish a logged-out state; the control is only for changing login identity.
- Store credentials only in session state (in-memory). **Password must never be persisted** (localStorage, cookies, URL, or any durable store).
- Prepare for future use: credentials will be needed to call the planets.nu API; this issue only adds the UI and in-memory state.

---

## 2. Current state

**Living reference for client state:** [design-frontend-and-backend-state.md](design-frontend-and-backend-state.md) (Zustand session and shell stores, TanStack Query, local React state).

### 2.1 Header

- `packages/frontend/src/components/Header.tsx` renders the top bar.
- Login identity is a static label: `Login: —` (em dash).
- Header receives `viewMode`, `onViewModeChange`, `mapZoom`, `onMapZoomSliderChange` from `ConsoleShell` in `App.tsx`.

### 2.2 App state

- `packages/frontend/src/App.tsx`: `ConsoleShell` holds view mode, map zoom, enabled analytics, and shell error rows in React `useState`.
- **Session:** `packages/frontend/src/stores/session.ts` (Zustand) -- login name and password in memory only.
- **Shell context (game, turn, perspective):** `packages/frontend/src/stores/shell.ts` (Zustand).
- **BFF-backed data:** TanStack Query (see the design doc above).

### 2.3 UI stack

- Frontend uses Tailwind; architecture mentions shadcn/ui but there is no `components/ui` layer yet (no existing Dialog/Modal).

---

## 3. Scope

### In scope

- Replace the static "Login: —" with a **refresh icon** (always visible) plus **"Login:"** label showing current name or "—". Clicking the icon opens the login modal (to log in or change identity). No separate "Log out" control; appearance is consistent in all states.
- Modal dialog: title, name field, password field (masked), submit and cancel. Submitting sets session state; cancel or closing clears nothing (user can try again).
- Session state: login name and password held in memory only in a Zustand store. State is lost on full page reload.
- Rule or doc: add an explicit rule that **passwords must never be persisted** (and where to enforce it), so future work cannot accidentally add persistence.
- Unit tests for the new UI behavior (e.g. login flow, display of name, no persistence of password).
- Minimal doc updates: any README or dev docs that describe the header should mention the login control.

### Out of scope (for this issue)

- Calling the planets.nu API or any backend with the credentials.
- Remembering login across reloads (e.g. tokens, refresh).
- BFF or Core API changes for authentication.
- Game/turn/viewpoint wiring that will consume login context (covered elsewhere, e.g. Issue #10 design).

---

## 4. Proposed design

### 4.1 Session state: Zustand store

- Add a small Zustand store (e.g. `sessionStore` or `loginStore`) with `name: string | null`, `password: string | null`, and setters (e.g. `setCredentials(name, password)`, `clearSession()`). No persistence middleware.
- Header and the login modal import the store: Header reads `name` and displays it (or "—"); the modal writes credentials on submit. The refresh icon opens the modal to log in or change identity; there is no separate log-out control.

### 4.2 Header behavior

- Header subscribes to the session store (e.g. `useStore(store, s => s.name)`). **Consistent layout:** a refresh icon button (e.g. lucide-react `RefreshCw`) to the left of the text "Login: &lt;name or —&gt;". The icon is always present and opens the login modal (aria-label e.g. "Change login"). "Login:" is always a label; the value is `name ?? '—'`. No conditional button/label or "Log out" button.

### 4.3 Login modal

- **Trigger:** Refresh icon (change-login) button in the header.
- **Content:**
  - Title: e.g. "Log in to planets.nu".
  - Input: login name (text).
  - Input: password (type `password`).
  - Buttons: "Log in" (submit), "Cancel" (close without saving).
- **On submit:** validate non-empty name (and optionally password); then call the session store's setter with name and password, and close the modal. Do not persist to localStorage, cookies, or URL.
- **Accessibility:** focus trap, dismiss on Escape, and focus return to the change-login button when closed.

If shadcn/ui is introduced in this codebase, use the shadcn `Dialog` primitive for the modal. Otherwise, implement a minimal accessible dialog (e.g. role="dialog", aria-modal, focus trap) or add the shadcn Dialog as part of this work.

### 4.4 Password non-persistence rule

- Add a rule that **passwords must never be persisted** (no localStorage, sessionStorage, cookies, URL parameters, or any durable storage). Only in-memory session state is allowed.
- Suggested location: a short subsection in `.cursor/rules/general.mdc`, or a dedicated `.cursor/rules/security.mdc` if the project wants a separate security/credentials rule file.
- The rule should be explicit so that future features (e.g. "remember me", token refresh) do not accidentally persist the password.

### 4.5 Data flow (conceptual)

```
User clicks refresh (change-login) icon → Modal opens
User enters name + password → Clicks "Log in"
  → Modal validates (e.g. name non-empty)
  → Session store updated (name + password in memory only)
  → Close modal
  → Header re-renders (subscribed to store) with "Login: <name>"
```

To change identity later: user clicks the same refresh icon again and submits new credentials; no log-out step.

---

## 5. Phases (implementation plan)

Phases are small and independently reviewable/mergeable.

### Phase 1: Refresh icon, label, modal, and session state

- **Scope:** Replace static "Login: —" with a refresh icon (always visible) + "Login:" label showing name or "—"; icon opens the login modal; add a Zustand session store; add modal with name + password that writes to the store; Header reads from the store. No "Log out" control; same appearance in all states.
- **Tests:** Unit tests (e.g. Vitest + RTL): (1) change-login (refresh) button is present and opens the modal; (2) submitting with a name updates the header to show the name; (3) no password or credential is written to localStorage/sessionStorage. Test that the store is in-memory only (no persistence).
- **Docs:** Add the password non-persistence rule to the chosen rules file. Update any doc that describes the header to mention the login control.
- **Cleanup:** Ensure the new components have clear props and no dead code; follow existing naming and structure.

### Phase 2 (future, not part of #12)

- Use session credentials in API calls (e.g. BFF or frontend calling planets.nu). Not in scope for this issue.

---

## 6. Acceptance criteria (for #12)

- [x] Top bar shows a refresh (change-login) icon to the left of "Login:" and the current name or "—"; appearance is consistent regardless of login state.
- [x] Clicking the refresh icon opens a modal with name and password fields; password is masked.
- [x] After submitting valid name (and password), the modal closes and the top bar shows "Login: &lt;name&gt;".
- [x] Password is never persisted (no localStorage, sessionStorage, cookies, URL). Only in-memory session state.
- [x] A rule or doc states that passwords must never be persisted.
- [x] User can change login identity by clicking the refresh icon again and submitting new credentials (no separate log-out).
- [x] New behavior is covered by unit tests; lint and existing tests pass.

---

## 7. File-level checklist (for implementer)

| Area | Action |
|------|--------|
| `packages/frontend/src/components/Header.tsx` | Subscribe to session store; refresh icon + "Login: &lt;name or —&gt;" (consistent); icon opens modal. |
| New: session store | Add Zustand store under `packages/frontend/src/` (e.g. `stores/session.ts`): name, password (in memory), setters, clear. No persistence. |
| New: login modal component | e.g. `LoginModal.tsx` or `LoginDialog.tsx`; name + password inputs, submit/cancel; on submit call store setter. |
| New (optional): shadcn Dialog | If adding shadcn: install and add Dialog primitive; use for modal. |
| `.cursor/rules/general.mdc` or `security.mdc` | Add password non-persistence rule. |
| Tests | New tests for login flow and no password persistence. |
