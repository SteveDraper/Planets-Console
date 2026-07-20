# Design: Account API key durability, silent login restore, and unfinished game info refresh

**Status:** Ready for implementation  
**Issue:** [#247](https://github.com/SteveDraper/Planets-Console/issues/247)  
**ADR:** [ADR 0007](adr/0007-account-api-key-and-silent-login.md)  
**Glossary:** [CONTEXT.md](../CONTEXT.md) (terms under Login and shell controls)  
**Supersedes (partially):** [design-issue-12-login-identity.md](design-issue-12-login-identity.md) — modal submit is no longer client-only; **log out** is now in scope. Password non-persistence still holds.

This document is the implementation brief for a new agent. Prefer CONTEXT + ADR 0007 for *why*; this doc for *what to build* and *where to touch*.

---

## 1. Goals

1. **Usability after browser refresh:** restore login without typing a password when this server already has a decryptable **account API key** for the remembered name (**silent login restore**).
2. **Never persist passwords** (client or server). Persist only Planets.nu **account API keys**, **machine-bound obfuscated** at rest.
3. **Proactive login exchange:** modal submit with a password always exchanges with Planets.nu and replaces the stored key; SPA then drops the password from memory.
4. **Unfinished selected game:** after identity is established (silent restore or login exchange), run the same **game info refresh** as game switch so host turn / metadata catch up. Do **not** auto-advance the viewed turn.

---

## 2. Current code (baseline)

### Client

| Area | Location | Today |
|------|----------|--------|
| Session | `packages/frontend/src/stores/session.ts` | In-memory `name` / `password` / `credentialsRevision`; no persist |
| Login UI | `packages/frontend/src/components/LoginModal.tsx` | Writes session only; remembers last username in `localStorage` (`planetsConsoleLastLoginUsername`); **no server call** |
| Game switch refresh | `packages/frontend/src/shell/useShellGameSelection.ts` | `refreshGameInfo` POST when committing game selection |
| Startup game restore | `packages/frontend/src/App.tsx` + `shell/shellGameBootstrap.ts` | GET stored game info only; **no** Planets.nu refresh |
| Finished check | `packages/frontend/src/lib/gameInfoShell.ts` | `isGameFinishedFromGameInfo` (status 3 / statusname Finished) |
| Turn on same-game refresh | `packages/frontend/src/stores/shell.ts` `applyGameInfoRefresh` | Keeps selected turn if within new cap; does not jump to latest |

### Server

| Area | Location | Today |
|------|----------|--------|
| Credentials | `packages/api/api/services/credential_service.py` | `credentials/accounts/{user}/api_key` plaintext; `ensure_api_key_for_user` only logs in when key **missing** |
| Breakpoint | `packages/api/api/storage/boundaries.py` | `credentials/accounts/*` already one document per name |
| Game refresh | `GameService.refresh_game_info` | Uses `ensure_api_key_for_user` |
| Config | `packages/api/api/config.py` | No credential-secret field yet |

---

## 3. Domain terms (use these names)

Do not invent synonyms. Definitions: CONTEXT.md.

- **Session credentials** — in-memory name + optional password  
- **Silent login restore** / **Credential probe** / **Login exchange** / **Name-only identity switch**  
- **Account API key** / **Machine-bound obfuscation** / **Lazy credential migrate**  
- **Account API key invalidation** / **Account API key drop** / **Log out**  
- **Game info refresh**

---

## 4. Behavioral contracts

### 4.1 Page load (remembered username + persisted selected game)

1. Hydrate shell from storage (existing bootstrap/restore) — paint immediately.  
2. **Credential probe** for remembered username (no password).  
3. On probe **success:** set session name (no password) → if selected game unfinished → **game info refresh** (same path as game switch). Selected turn does **not** auto-advance.  
4. On probe **failure:** auto-open login modal, name prefilled; session stays logged out until exchange or name-only switch succeeds.

### 4.2 Login modal submit

| Submit | Behavior |
|--------|----------|
| Name + **password** | **Login exchange** → always Planets.nu login → store obfuscated key → set session name → **drop password from client memory** → remember username in localStorage → unfinished-game refresh if applicable |
| Name + **empty password** | **Name-only identity switch:** probe; on success set session name only; on failure show error (require password) |
| Cancel | No session change |

### 4.3 Log out

- Clear session credentials and clear remembered username (`localStorage`).  
- Default: leave server **account API key** in place.  
- Optional user control: also **account API key drop** for the current name.  
- Suggested UI: controls on the login modal (or adjacent header menu) — exact chrome is implementer choice; must be discoverable.

### 4.4 Mid-session auth failure

When an upstream call fails because the stored API key is rejected:

1. **Account API key invalidation** — delete key material from the account document (same durable outcome as drop for that field).  
2. Clear or demote session as needed so the user is not “falsely logged in.”  
3. Open login modal (name prefilled from last name if still known).

### 4.5 Operational Planets.nu calls (refresh / ensure / load-all)

- **SPA:** after exchange or name-only switch, send **username only** (no password).  
- **Non-SPA / fallback:** endpoints may still accept optional password; when provided, apply the same always-replace key write rules as login exchange (obfuscated store).

### 4.6 Credential probe semantics

- Succeeds iff a decryptable **account API key** exists for the name.  
- Does **not** call Planets.nu.  
- Decrypt failure ≡ missing key (probe fails).  
- Legacy plaintext → treat as present, **lazy credential migrate** (rewrite obfuscated on access).

---

## 5. Storage and crypto

### 5.1 Path

Reuse breakpoint `credentials/accounts/*` → file `credentials/accounts/{username}.json`.

Suggested document shape (versioned; adjust field names only if a cleaner scheme is needed, but keep one document per user):

```json
{
  "api_key": {
    "v": 1,
    "nonce": "<base64>",
    "ciphertext": "<base64>"
  }
}
```

Legacy: `"api_key": "<plaintext string>"` — accept on read, rewrite to `v: 1` form.

### 5.2 Key derivation and AEAD

- Library: **`cryptography`** (pyca). Respect dependency cooldown (≥7 days since release when pinning).  
- Construction: **HKDF** → 256-bit key → **AES-GCM**.  
- HKDF IKM / info inputs:
  - OS native machine id (required for default path)
  - Optional configured secret override (when set, include in derivation as decided in implementation — must be documented in code comments briefly; recommend: HKDF salt or info includes both machine id and secret so either changing breaks old ciphertext)
  - Fixed app salt / info string, e.g. `planets-console-account-api-key-v1`
- Machine id reader: **first-party** Core helper (no `py-machineid`):
  - **Windows:** `MachineGuid` under `HKLM\SOFTWARE\Microsoft\Cryptography`
  - **macOS:** `IOPlatformUUID`
  - **Linux:** `/etc/machine-id` (best-effort; fail closed if unreadable)
- Primary platforms: **macOS and Windows 10+**. Linux secondary.

### 5.3 Config

Add optional Core config field (name bikeshed OK if consistent), e.g.:

- `api.credentials_obfuscation_secret: string | null` (default `null`)

Document in [configuration.md](configuration.md). Wire through amalgamated server config like other `ApiConfig` fields.

---

## 6. HTTP surface (SPA via BFF)

SPA must not call Core directly. Add BFF routes that delegate to Core credential service. Exact paths may follow existing BFF style; suggested:

| Operation | Suggested BFF | Body / params | Result |
|-----------|---------------|---------------|--------|
| Login exchange | `POST /bff/credentials/exchange` | `{ username, password }` | 200 when key stored; errors on bad Planets.nu login |
| Credential probe | `GET /bff/credentials/probe?username=` or `POST .../probe` | username | `{ "present": true \| false }` |
| Account API key drop | `DELETE /bff/credentials/{username}` or POST with operation | username | 204/200 |

Regenerate the relevant frontend OpenAPI slice after BFF OpenAPI changes (see ADR 0003 / frontend rules). Prefer Zod only if the contract is stream-shaped; these are ordinary REST — codegen slice is enough.

Core may expose `/api/v1/credentials/...` mirrors used only by BFF.

Align `CredentialService` APIs roughly as:

- `probe(username) -> bool`
- `exchange(username, password, planets) -> None` (always login + store obfuscated)
- `drop(username) -> None`
- `ensure_api_key_for_user(...)` — if password provided: exchange semantics; if not: decrypt stored or raise `LoginCredentialsRequiredError`; on upstream auth failure callers trigger invalidation

Detect Planets.nu auth failures in one place and call invalidation so refresh/ensure/load-all share behavior.

---

## 7. Frontend implementation notes

### 7.1 Session store

- After successful **login exchange**, set name and set password to `null` (and bump `credentialsRevision`).  
- **Silent login restore** / name-only switch: set name only.  
- **Log out:** `clearSession()` + remove `LAST_LOGIN_USERNAME_STORAGE_KEY`.

### 7.2 Startup orchestration (`App.tsx` / shell hooks)

Recommended order (already decided):

1. Existing storage game bootstrap/restore  
2. Silent login restore (probe) when remembered name exists  
3. Unfinished **game info refresh** via existing `refreshGameMutation` / shared helper (do not fork a third refresh stack)

Gate unfinished refresh on `gameInfoContext` present and `!isGameFinished`.

Avoid double refresh: user-initiated game switch already refreshes; startup refresh is only for restore/login paths.

### 7.3 Login modal

- On submit with password → call exchange endpoint, then update session (drop password).  
- On submit without password → probe (or rely on exchange endpoint rejecting empty password and a dedicated probe).  
- Support log out + optional drop.  
- Auto-open when silent restore probe fails.

### 7.4 Errors

Use **shell error bar** for failed exchange/refresh; modal-local validation for empty name / probe-failed-needs-password.

---

## 8. Tests (minimum)

### Core

- HKDF/AES-GCM round-trip; wrong machine-id material fails decrypt.  
- Lazy migrate plaintext → obfuscated on read/ensure.  
- `exchange` always calls Planets.nu login when password set (mock client); replaces prior key.  
- `probe` true/false; undecryptable → false.  
- `drop` / invalidation remove key material; subsequent probe false.  
- Machine-id helper unit-tested with mocks per platform branch.

### BFF

- Exchange / probe / drop HTTP contracts and error mapping.

### Frontend

- Silent restore: remembered name + probe true → session name set, no modal; unfinished game triggers refresh.  
- Probe false → modal opens prefilled.  
- Exchange success → password cleared from session store; localStorage name set.  
- Name-only switch with probe true works; false shows error.  
- Log out clears remember-me; optional drop called when selected.  
- Password never written to localStorage/sessionStorage (existing invariant).  
- Unfinished refresh does not change selected turn when still ≤ new turn cap (assert against `applyGameInfoRefresh` behavior).

---

## 9. Suggested implementation phases (single PR OK if small; else split)

| Phase | Deliverable | Demo / verify |
|-------|-------------|---------------|
| 1 | Crypto helper + machine id + CredentialService obfuscation, probe, exchange, drop, lazy migrate + Core/BFF routes + tests | curl probe/exchange; plaintext migrate |
| 2 | SPA login exchange + drop password + name-only switch + log out (+ optional drop) | Manual login/refresh browser |
| 3 | Silent login restore + auto-open modal on probe fail | Refresh browser with remembered user |
| 4 | Unfinished game info refresh after identity | Host advances turn; refresh + silent restore updates turn cap |

Phases 2–4 can merge if the agent keeps PRs reviewable.

---

## 10. Out of scope

- Persisting passwords anywhere.  
- Server-side HTTP session cookies / JWT login.  
- Auto-advancing selected turn to latest host turn.  
- Refreshing **finished** games on startup (unless already done by user re-select).  
- Changing breakpoint layout away from `credentials/accounts/*`.  
- Hardware fingerprinting beyond OS native machine id.

---

## 11. Acceptance criteria (issue-level)

- [ ] Password never persisted; after login exchange client password is cleared from memory.  
- [ ] Account API keys stored obfuscated (AES-GCM) under `credentials/accounts/*`; plaintext legacy migrates lazily.  
- [ ] Copied account document alone does not decrypt on another machine (OS machine id binding); optional config secret documented.  
- [ ] Credential probe + silent login restore work on Mac/Windows; Linux best-effort.  
- [ ] Login exchange always refreshes key when password provided.  
- [ ] Name-only identity switch via probe.  
- [ ] Log out clears remember-me; optional account API key drop.  
- [ ] Auth failure invalidates stored key and prompts re-login.  
- [ ] After silent restore or login exchange, unfinished selected game runs game info refresh; selected turn does not auto-jump to latest.  
- [ ] SPA operational calls use username-only after identity established.  
- [ ] Unit tests cover crypto, credential service, and primary SPA flows.  
- [ ] Docs: this design, ADR 0007, CONTEXT terms, configuration.md secret field.

---

## 12. Key file touch list ( Orienting, not exhaustive)

**Core:** `credential_service.py`, new crypto/machine-id modules under `api/`, `config.py`, credentials router, `game_service` / turn load / load-all ensure paths, tests.  
**BFF:** credentials router + `core_client` methods + OpenAPI.  
**Frontend:** `LoginModal`, `session` store, `App.tsx` / `useShellGameSelection`, `bff.ts` + schema slice regen, tests.  
**Docs:** `configuration.md`, optionally a one-line supersession note on design-issue-12.
