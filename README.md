# Planets Console

Analytic console for [planets.nu](https://planets.nu) game state (VGA Planets–style). See the [project overview](.cursor/rules/overview.mdc) and [architecture](.cursor/rules/architecture.mdc) for layout and layering.

## Developer setup

### Prerequisites

- **Python 3.12+** — managed with [uv](https://docs.astral.sh/uv/)
- **Node.js 18+** and npm (or pnpm) — for the frontend

### 1. Clone and install backend

```bash
git clone https://github.com/SteveDraper/Planets-Console.git
cd Planets-Console
uv sync
```

This creates a virtual environment and installs the workspace (server, api, bff).

### 2. Install frontend

```bash
cd packages/frontend
npm install
```

## Run locally

**One command (both processes):** from repo root run `./scripts/run_dev.sh`. That starts the backend and the Vite dev server; use **http://localhost:5173**. Ctrl+C stops both.

**Or run the two processes yourself:**

### Terminal 1 — Backend

From the repo root:

```bash
uv run serve
```

- Server listens on **http://127.0.0.1:8000**
- Health: http://127.0.0.1:8000/health  
- Core API: http://127.0.0.1:8000/api  
- BFF (for the SPA): http://127.0.0.1:8000/bff  
- BFF OpenAPI (for frontend codegen): http://127.0.0.1:8000/bff/openapi.json  

Options: `--host`, `--port`, `--reload` (e.g. `uv run serve --reload`).

### Terminal 2 — Frontend

```bash
cd packages/frontend
npm run dev
```

- Dev server runs at **http://localhost:5173**
- Vite proxies `/bff` and `/api` to the backend, so the SPA talks to the BFF without CORS issues.

Open http://localhost:5173 in a browser. You should see the console shell (header, analytics selector, main area) with placeholder analytics.

## Single-server deployment (non-dev)

For staging or production you can run one process: the backend serves the built frontend so the browser loads the app and calls `/bff` on the same origin.

**One command:** build the frontend, then from repo root run `./scripts/run_deploy.sh`. It sets `FRONTEND_DIST` to `packages/frontend/dist` and starts the server. Open **http://127.0.0.1:8000**. You can pass serve options (e.g. `./scripts/run_deploy.sh --host 0.0.0.0`).

**Steps manually:**

1. **Build the frontend** (from repo root):

   ```bash
   cd packages/frontend && npm run build && cd ../..
   ```

   This creates `packages/frontend/dist/` (e.g. `index.html`, `assets/`).

2. **Run the server** from the repo root:

   ```bash
   uv run serve
   ```

   If the directory `packages/frontend/dist` exists, the app will serve it: `/` and all non-API paths return the SPA, and `/assets/*` serve built JS/CSS. No need to set anything.

   To use a different path (e.g. after copying `dist` elsewhere), set:

   ```bash
   FRONTEND_DIST=/path/to/dist uv run serve
   ```

3. Open **http://127.0.0.1:8000** (or your host/port). The console and BFF are on the same server; no second process and no CORS.

## Project layout

```
packages/
  api/      Core REST API (stub for now)
  bff/      Backend-for-Frontend — SPA-shaped endpoints only
  server/   Root FastAPI app; mounts API and BFF
  frontend/ React SPA (Vite, Tailwind, TanStack Query)
```

The frontend **only** calls the BFF; it never calls the Core API directly.

## Documentation

### User documentation

- **[User guide](docs/user-guide.md)** -- full tour of the console UI (header, analytics, tabular and map views, map options, login). Image paths under `docs/images/user-guide/` are placeholders for screenshots.

### Design documentation

These documents describe intended behavior, architecture decisions, and implementation notes for contributors.

- **[Frontend and backend state](docs/design-frontend-and-backend-state.md)** -- Zustand vs TanStack Query, local React state, and stateless backend + storage.
- **[Shell error handling](docs/design-shell-error-handling.md)** -- BFF errors and the shell error bar.
- **[Storage abstraction](docs/design-storage-abstraction-and-crud-api.md)** -- `StorageBackend` and CRUD semantics.
- **[Planets API data model](docs/design-planets-api-data-model.md)** -- data model direction for planets.nu–shaped data.
- **[Base map from Core API](docs/design-issue-10-base-map-from-core.md)** -- base map analytic sourcing.
- **[Login identity](docs/design-issue-12-login-identity.md)** -- login and identity in the shell.
- **[Game selection](docs/design-issue-13-game-selection.md)** -- game selection and refresh flow.
- **[Map planet labels and options](docs/design-map-planet-labels-and-options.md)** -- map labels and display options.
- **[Basic UI framework](docs/implementation-basic-ui-framework.md)** -- shell layout and UI framework notes.

### Additional documentation

- **[Configuration](docs/configuration.md)** -- server and app configuration.
- **[VGA Planets domain context](docs/vga-planets-domain-context.md)** -- game/domain context for the console.
- **[Cursor GitHub setup](docs/cursor-github-setup.md)** -- GitHub integration notes for Cursor.

All Markdown docs live under [`docs/`](docs/).
