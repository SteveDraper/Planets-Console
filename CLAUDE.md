# Planets Console

Planets Console is an analytic console onto game states from the game panets.nu.  planets.nu is an implementation of https://vgaplanets.org/index.php?title=Main_Page with a browser front end.

The console will be able to load game state data and perform analytics on it that will highlight useful features and situations to players useng the console to analyze their games.

In overall UI layout the console will be a single page app with the real-estate divided into three main areas:

1. Header bar containing context information that controls where the game state being anlysed comes from.  Elements (laid out horizontally in this bar) will provide:
1.1 Login identity (player name whose login is used to retrieve the data)
1.2 Game (tuple of an id and a name)
1.3 Turn number
1.4 Viewpoint identity (player name for the player whose position is being shown/analyzed)
1.5 Mode toggle (always right-aligned) - two-state toggle between tabular and map views
1.6 A scale slider that is disabled when not in map mode which visually stays with the mode toggle

2. Analytics selector bar - vertical bar left aligned containing a vertical list of sections that define individual analytics.  These will always contain an enable/disable toggle (whether the analytic in question is included in the view or not), using the same checkbox styling and tile chrome on every row.  Any further controls for that analytic (filters, legends, layer toggles) live in a collapsible details pane under that toggle, opened with the row chevron, so the row stays compact until it is expanded.  Each analytic may be able to provide content in eitehr the tabular or the map view modes or display.  Those that do not support the current mode will retain their enablement toggle state but appeared greyed out in the mode they do not support

3. The bulk of the display area (all ut th top bar and the left analytics selector) will contain the output of the analytics.  What this renders depends on the selected mode (tabular vs map):
* In tabular mode this will be tabular output for each selected analytic in vertically stacked sub-tiles (one per enabled analytic with a title conveyign which it is)
* In map mode this will be a rendering of the game map (essentially a graph with planets as nodes and connections as edges).  This map will be draggable and scrollable via the mouse-wheel to recenter and scalable via the scaling slider

## How agent context is organized

- `.claude/rules/` holds conventions that load when a matching file is read. If you are creating a file in a package before reading anything there, read that package's rule first (`bff`, `core-api`, `storage`, `frontend-react`, plus `implementation-quality`).
- `CONTEXT.md` is the domain glossary and is very large (about 275K). Grep it for specific terms; never read it whole or import it here.
- `docs/` holds design documents and ADRs. Consult them before analysing code when planning.

## Game-domain background

Before designing or implementing work that depends on Planets.nu game meaning (analytics semantics, map entities, game state fields, host rules), delegate to the `planets-nu-wiki` subagent with the feature and specific questions, and treat its brief as the game-domain source for the task. Do not read the Personal-wiki vault in the main agent unless the subagent is unavailable or the user asks you to edit the wiki. Skip this for purely structural work.

# Architecture

## Layer Hierarchy

The system is layered so each piece only depends on the layer(s) below it. The **MCP adapter** is a sibling of the BFF (both call Core in-process; only root `server` mounts MCP):

```
┌─────────────────────────────┐
│         Frontend            │  packages/frontend/   React SPA
├──────────────┬──────────────┤
│     BFF      │ MCP adapter  │  packages/bff/  |  packages/mcp_adapter/
├──────────────┴──────────────┤
│       Core REST API         │  packages/api/        Data model + business logic
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│     Storage sub-layer       │  packages/api/storage/  Abstract storage interface + impls
└─────────────────────────────┘
```

| Layer | Package | Responsibility |
|---|---|---|
| Frontend | `packages/frontend` | React SPA. Never calls Core REST API — always via BFF. |
| BFF | `packages/bff` | SPA-optimized endpoints. Aggregates/reshapes Core REST API responses. No business logic. |
| MCP adapter | `packages/mcp_adapter` | Agent Streamable HTTP at `/mcp`. Thin wrap of Core in-process APIs. No domain logic. Import `mcp_adapter`, never `mcp`. |
| Core REST API | `packages/api` | Data model + business logic. No UI semantics. No knowledge of the SPA. |
| Storage | `packages/api/storage/` | Abstract `StorageBackend` protocol + concrete implementations. Instantiated only inside the sub-package and by `api.storage_factory`. |

**Do not leak UI concerns into the Core REST API layer.**
**Do not put business logic in the BFF layer.**
**Do not put business logic in the MCP adapter.** It must not import `bff.*`, `api.storage.*`, Core routers / `api.app`, or `api.handlers.*`. Only `server` may import `mcp_adapter`.
**Do not reference a concrete storage implementation outside `packages/api/storage/`.** The process factory in `api.storage_factory` is the sole exception: it instantiates the configured backend. Routers and services still receive `StorageBackend` via injection.
**Shared primitives live below features.** If two analytics need the same lookup, codec, or scope filter, extract to `concepts/`, `serialization/`, or a dedicated shared module -- never import analytic A from analytic B for convenience.
**One policy, one encoding.** Branching precedence, export classification, and similar policy must not be duplicated in parallel functions; share a decision record or table.

## Repo Structure

```
planets-console/
├── packages/
│   ├── api/          # Core REST API layer (routers, models, services, storage/)
│   ├── bff/          # BFF layer (FastAPI routers shaped for the SPA)
│   ├── mcp_adapter/  # MCP adapter (Streamable HTTP at /mcp)
│   ├── server/       # Root FastAPI app that mounts api, bff, and mcp
│   └── frontend/     # React SPA (Vite)
├── scripts/          # Auxiliary scripts (Typer CLI)
├── pyproject.toml    # Root uv workspace config
├── .claude/          # Claude Code rules, skills, and agents
└── .cursor/          # Cursor rules and agents
```

## Backend Tech Stack

- **Runtime**: Python 3.14, managed with `uv`
- **Framework**: FastAPI — single process composed from mounted sub-apps: one Core REST API app and one BFF app, with the BFF exposing its own OpenAPI schema endpoint for frontend codegen
- **CLI**: Typer for service launch args and auxiliary scripts
- **Config**: OmegaConf with plain dataclasses (no Pydantic for config)
- **Data model**: Plain dataclasses with explicit codecs for persistence of non-JSON-native field types

## Frontend Tech Stack

- **Bundler**: Vite · **Routing**: React Router · **Components**: shadcn/ui · **Styling**: Tailwind CSS
- **Server state**: TanStack Query · **Client state**: Zustand (see [docs/design-frontend-and-backend-state.md](docs/design-frontend-and-backend-state.md) for what belongs in each, plus backend statelessness and storage)
- **Graphs**: React Flow · **Tables**: TanStack Table · **Tests**: Vitest + RTL

## Adding New Features

1. Define the data model in `packages/api/models/` as dataclasses
2. Add codecs in `packages/api/serialization/` when persisted fields are not JSON-native
3. Add storage access via the `StorageBackend` interface in `packages/api/storage/`
4. Implement business logic and expose via Core REST API router (`/api/v1/...`) — no UI semantics
5. Add BFF router endpoint (`/bff/...`) shaped for what the frontend needs and include it in the dedicated BFF OpenAPI schema used by the frontend
6. Implement frontend: TanStack Query hook → feature component using shadcn/ui + Tailwind
7. **Features must have unit tests.** Add tests for new behaviour and ensure they are run by the package’s test target (see below).

## Unit tests, linting, and Makefile

- **Features should always have unit tests.** New or changed behaviour must be covered by tests in the appropriate package.
- **Run linting for all changes.** Backend (Python) linting is provided by Ruff; run `make lint` to check all backend packages and scripts. The top-level `test` target depends on `lint`, so `make test` runs lint then all package tests — use it before committing or in CI.
- **Each package that has tests has its own Makefile target.** For example: `test_bff`, `test_api`, `test_mcp_adapter`, `test_frontend`, `test_scripts` (auxiliary scripts under `scripts/`). The target runs that package’s test suite (e.g. `cd packages/<pkg> && uv run pytest` for Python packages).
- **When adding a new package that has unit tests, add a corresponding `test_<package>` target to the Makefile** and wire it so the package’s tests run from that package directory (or equivalent).
- **The top-level `test` target in the Makefile must run every package’s tests.** It should depend on `lint` and all per-package test targets (e.g. `test: lint test_bff test_api test_server test_mcp_adapter test_scripts test_frontend`) so that `make test` runs the full suite.

# General Guidelines

## Coding Standards

- Prefer clarity over cleverness.
- Keep functions focused on a single responsibility.
- Add comments only when the code cannot speak for itself.
- **Comments describe current state, not history.** Never reference ticket IDs, past bugs, or previous implementations in code comments (`// Fixed SOA-123`, `// Was broken before`, `// Old approach was X`). That context belongs in git history and commit messages. A comment should be true forever -- if it describes why the code exists today, it's a good comment. If it describes what it used to do or why it changed, delete it.
- **Never write a TODO comment without discussing it with the user first.** A TODO is an admission that something is incomplete or wrong. The agent does not decide unilaterally to defer work -- that is a scope decision. When you encounter something that could be a TODO, stop and ask: should we fix it now, ticket it, or explicitly accept it as-is? If the user decides to ticket it, create the ticket. If they decide to accept it, leave no comment at all. A `// TODO` with no ticket is just technical debt with extra steps.

## Naming

- **Name for the domain, not the implementation** -- `activeStudents`, not `queryResult`; name what it *is*, not how it works.
- **One name per concept, one concept per name** -- pick a term and use it everywhere; don't use "classroom" in one place and "section" in another.
- **Booleans read as yes/no questions** -- `isActive`, `hasEnrollments`, `canEdit`; not bare `active` or `enrollments`.
- **Functions: return functions describe what, action functions describe the action** -- `getDisplayName()`, `syncEnrollments()`; use the simplest verb (`get` over `fetch` over `retrieve`).
- **No abbreviations unless universal** -- `URL`, `ID`, `API` are fine; `enr`, `cls`, `usr` are not.
- **No generic names** -- `data`, `result`, `temp`, `info`, `manager`, `handler`, `utils` are placeholders, not names.
- **Names must be searchable** -- if you can't grep for it meaningfully, it's too short or generic.
- **Consistent pairs** -- `start`/`end`, `add`/`remove`, `create`/`delete`; don't mix synonyms across a codebase.
- **Match team vocabulary** -- use the same terms as in tickets, meetings, and domain conversations.

## No Tech Debt by Default

**Fix things right, even when it's harder.** Tech debt is a cost that compounds -- a shortcut taken today becomes a bigger problem tomorrow. The default is always to implement the correct solution.

- **If the right fix requires a significant refactor, discuss it with the user first** rather than taking a shortcut. Present the scope, explain why the shortcut is a problem, and let the user decide. They may greenlight the refactor, defer it to a separate ticket, or make a conscious tradeoff -- but that is their call, not yours.
- **Never introduce tech debt silently.** A hack with no comment, a workaround that papers over a real problem, or a "temporary" fix that will never be revisited are all worse than stopping to discuss. If you can't do it right right now, surface it.
- **Never add backward-compatibility shims unless explicitly asked.** Backward compatibility locks in old patterns and adds complexity. Use the current best approach. If you're unsure whether compatibility is required, ask.
- **Move forward, not sideways.** When making a change, don't replicate the old pattern in a new location. Fix the pattern.
- **Search, reuse, extract.** Before adding logic, follow `.claude/rules/implementation-quality.md` (grep for existing helpers, respect layer boundaries, extract shared code in the same PR). "Move forward, not sideways" includes not leaving duplicate helpers for review to find later.

## Collaboration

- **Stop at decision points.** When something unexpected comes up mid-task (an error, a missing piece, an ambiguous direction), stop and report back rather than plowing through. The user wants to stay in the loop.
- **Don't chain unrelated actions silently.** Completing one task and then immediately starting the next without checking is not collaborative. Finish a thing, summarize, and wait.
- **Errors are decision points.** When a command fails or behavior is unexpected, report what happened and what the options are -- don't immediately start trying fixes.
- **The todo list does not override collaboration.** Having open todos does not mean ignoring the user and plowing through. Todos track progress; they do not grant permission to skip check-ins. Stop and collaborate whenever the situation calls for it, even mid-task.
- **Ask when you need access.** If a task requires a tool, credential, API key, permission, or environment you don't have -- stop and ask the user. Never try to work around missing access by substituting a different approach, guessing at credentials, or skipping the step silently. The user is a collaborator and can provide what's needed. "I need X to do Y -- can you provide it?" is always the right move.
- **Don't poll CI.** After a push, stop and let the user report back when reviews are ready.

## Credentials and passwords

- **Passwords must never be persisted.** Do not store login passwords in localStorage, sessionStorage, cookies, URL parameters, or any durable storage. In-app session state (e.g. a Zustand store or React state) that holds a password in memory for the duration of the session is allowed; the password must be lost on full page reload or process exit. Any feature that adds "remember me", token refresh, or similar must not persist the raw password.

## Certainty and Verification

- When you catch yourself using hedging language like "may", "probably", "likely", "should work", "I think" -- pause and ask whether you actually know or are guessing. If guessing, verify first: read the file, run the command, check the config.
- High confidence is earned by reading code, running tests, and checking output -- not by pattern matching against training data. If the codebase does something unexpected, trust the code over your expectations.
- When specifying package APIs, module paths, or config values, verify against the installed version or docs. Training data may be outdated or wrong.
- If you can't verify, be transparent about the uncertainty. Distinguish between what you've confirmed and what you're inferring.

## Communication

- Be direct. Say what you know, what you don't know, and what you're about to do.
- Don't over-explain simple things or under-explain complex ones.
- When presenting options, briefly explain the tradeoffs rather than just listing choices.
- Always display URLs as clickable markdown links: `[label](url)`. Never paste a bare URL on its own line.
- **Use ASCII dashes, not em-dashes.** In code, comments, commit messages, shell scripts, config files, and file content you write: use `--` (double hyphen) or `-` (single hyphen) as separators. Never use `—` (U+2014 em-dash). Exception: UI-facing placeholder text (e.g. empty value indicators like "Login: —") may use em-dash when that is the intended design.
