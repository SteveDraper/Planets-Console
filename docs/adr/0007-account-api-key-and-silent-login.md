# Account API key durability and silent login restore

Status: accepted

Planets Console needs Planets.nu upstream access without re-entering a password on every browser refresh, while still never persisting passwords. We already store per-login **account API key** material under the `credentials/accounts/*` **breakpoint**; today that key is plaintext and is created lazily on the first authenticated operational call. We adopt an explicit credential model: **login exchange** (password → key), **credential probe** + **silent login restore** (name-only when a decryptable key exists), **machine-bound obfuscation** of keys at rest, and unfinished-game **game info refresh** after identity is established.

## Decision

- **Passwords** remain client-only for the moment of **login exchange** (or non-SPA operational fallback). After a successful exchange the SPA drops the password from **session credentials** and keeps the name. Passwords are never durable on client or server.
- **Account API keys** live in existing `credentials/accounts/{name}` **documents**. At rest they use **machine-bound obfuscation**: AES-GCM via the `cryptography` package, with a 256-bit key from HKDF over the OS native machine id (Windows `MachineGuid`, macOS `IOPlatformUUID`, Linux `/etc/machine-id`) by default, plus an optional configured secret override and a fixed app salt. The machine id is obtained by a small first-party Core helper (not `py-machineid`). A copied account file alone must not decrypt on another machine. Legacy plaintext values are accepted on read and rewritten obfuscated (**lazy credential migrate**).
- **Login exchange** always calls Planets.nu when a password is provided and replaces any stored key for that name. That is the SPA’s primary key-write path. Operational endpoints (refresh, ensure, load-all) from the SPA send username only; they may still accept a password from non-SPA clients and write/replace keys under the same rules.
- **Credential probe** checks for a decryptable stored key without calling Planets.nu. **Silent login restore** uses the remembered last login name + successful probe; on probe failure the login modal opens prefilled. Mid-session upstream auth failure triggers **account API key invalidation** (delete key material from the account document) and opens the modal.
- **Name-only identity switch** (modal submit with empty password, or silent restore) succeeds only when probe succeeds for that name.
- **Log out** clears client session and the remembered name (so silent restore does not run). By default the server key remains; the user may optionally **account API key drop**.
- Page load applies stored game selection first, then silent login restore, then unfinished **game info refresh** if logged in. Selected turn does not auto-advance when the host turn increases.

## Considered options

- **Password every page load** — safer, but rejects the usability goal that motivated durable keys.
- **Optimistic silent restore without probe** — surfaces “logged in” until the first upstream failure; rejected in favor of probe-then-adopt.
- **Live Planets.nu validate on every probe** — stronger freshness, slower and brittle on refresh; rejected in favor of storage probe + invalidation on auth failure.
- **New breakpoint or per-key document** — unnecessary; `credentials/accounts/*` already yields one file per login name.
- **Home-rolled XOR / storage-root-only wrapping** — undershoots “encrypt” or stays portable with a copied tree; rejected for AES-GCM + HKDF (`cryptography`) over OS machine id.
- **Fernet or PyNaCl instead of AES-GCM/`cryptography`** — workable, but Fernet is an older construction and PyNaCl adds a second crypto stack for no gain on Mac/Windows wheels.
- **`py-machineid` for OS machine id** — convenient, but unnecessary given fixed OS sources; rejected for a small first-party reader (Mac/Windows primary; Linux best-effort fail-closed).
- **Reject legacy plaintext keys** — forces needless re-login for existing `.data`; rejected for lazy migrate.
- **Hard rule: only login exchange may write keys** — cleaner boundary, harsher on scripts/migration; rejected for SPA-primary exchange with optional password on operational endpoints for non-SPA clients.
- **No log out control** (issue #12) — incompatible with silent restore; rejected for explicit log out with optional key drop.

## Consequences

- Issue #12 / design-issue-12 “client-only login, no server call” is superseded for submit: modal success performs **login exchange** (or name-only switch via probe).
- `CredentialService.ensure_api_key_for_user` must align with exchange-always-when-password, obfuscated persistence, probe, invalidation, and drop.
- Shell startup gains probe → silent restore → unfinished game info refresh; game switch refresh behavior for unfinished games stays aligned.
- Operators who copy `.data` to a new host must expect credential probe failure and a fresh **login exchange** (unless they also move a configured secret and matching derivation inputs intentionally).
- Glossary terms live in [CONTEXT.md](../../CONTEXT.md): **session credentials**, **silent login restore**, **credential probe**, **login exchange**, **name-only identity switch**, **account API key**, **machine-bound obfuscation**, **lazy credential migrate**, **account API key invalidation**, **account API key drop**, **log out**, **game info refresh**.

See also: [design-account-api-key-and-silent-login.md](../design-account-api-key-and-silent-login.md) (implementation brief), [ADR 0001](0001-breakpoint-file-storage.md), [design-issue-12-login-identity.md](../design-issue-12-login-identity.md), [design-frontend-and-backend-state.md](../design-frontend-and-backend-state.md).
