# Implementation checklist: Basic UI framework

**Source enhancement:** [#1 – [Feature] Basic UI frameworking](https://github.com/SteveDraper/Planets-Console/issues/1)

This doc is the versioned checklist and acceptance bar for that issue. Update it as work lands (check boxes, notes).

---

## Goal (from the issue)

- Broad-brush **UX framework** only, with placeholder analytics and placeholder data.
- Infrastructure so **Python (BFF/API/server)** and **React** can run locally.
- **Layout** aligned with [project overview](../.cursor/rules/overview.mdc): header, analytics bar, and main area implemented **through the BFF layer**.
- **README** sections: developer setup plus local run/deploy instructions.

Architecture constraints: [.cursor/rules/architecture.mdc](../.cursor/rules/architecture.mdc) (BFF-only from SPA, no business logic in BFF, layered packages).

---

## Checklist

### 1. Workspace & backend skeleton

- [x] Root **uv** workspace + `pyproject.toml` (packages as members if using a monorepo layout).
- [x] **`packages/server`**: root FastAPI app—middleware, health, shared startup; mount Core API under `/api`, BFF under `/bff`.
- [x] **`packages/api`**: minimal Core REST sub-app (can stub routers until real domain exists).
- [x] **`packages/bff`**: BFF sub-app—routers shaped for the SPA; **no business logic**; expose dedicated OpenAPI (e.g. `/bff/openapi.json`) for frontend codegen.
- [x] **CLI** (Typer) to run the server locally with sane defaults.

### 2. Frontend skeleton

- [x] **Vite + React** under `packages/frontend`, wrapped in `BrowserRouter` for future routing expansion.
- [x] **Tailwind CSS** styling for the current shell implementation.
- [x] **Shell layout** matching overview:
  - Header: login identity (refresh icon + "Login:" label; icon opens modal to set/change credentials); **game** control ([issue #13](design-issue-13-game-selection.md)) -- clickable `GameControl`, lists stored games from `GET /bff/games`, session-only add-by-id; **turn** and **viewpoint** remain placeholder "—"; right-aligned tabular/map toggle; and a log-scale map zoom slider that is disabled outside map mode and synchronized with React Flow zoom.
  - Left **analytics selector**: vertical list of selectable analytics (excluding the base map), each with enable/disable, pressed/depressed styling, and greyed-out state when unsupported in the current mode.
  - **Main area**: tabular tiles for enabled analytics, or a React Flow map pane with placeholder data.
- [x] **TanStack Query**—HTTP only to **BFF**, never Core API directly.

### 3. Placeholder analytics & BFF

- [x] BFF routes return **static/placeholder JSON** for analytics the shell can list.
- [x] Tabular mode: stacked sub-tiles per enabled analytic with titles and placeholder table data.
- [x] Map mode: React Flow wired to BFF placeholder data; base map (planets + edges) always included but not shown in the analytics selector; additional map-capable analytics are overlaid on the base map.

### 4. Local run

- [x] Documented commands to run backend + frontend (proxy or CORS so SPA → `/bff`).
- [x] Single place (README or script) for “run the console locally.”

### 5. README

- [x] **Developer setup**: clone, `uv sync`, Node/pnpm (or npm), env if any.
- [x] **Run/deploy locally**: URLs, BFF OpenAPI URL for codegen, any ports.

### 6. Done when

- [x] App runs locally with correct **outline** only.
- [x] BFF endpoints reachable from the SPA; placeholder data flows end-to-end (BFF → UI).
- [x] Issue #1 can be closed or narrowed once this checklist is satisfied; follow-ups get new issues.

---

## Map mode (as implemented)

- **Base map**: A pseudo-analytic of type `base` supplies the core map (planets as nodes, connections as edges). It is always included when map mode is active and is intentionally omitted from the analytics sidebar. User-selectable map analytics add their own nodes and edges on top.
- **Initial view fit**: On first render, the map computes the bounding rectangle of all node centers, centers it in the viewport, and chooses an initial zoom that leaves roughly 10% margin on the constrained dimension.
- **Rendering**: React Flow uses an invisible routing node at each planet center, an external fixed-size dot overlay, and a custom straight-edge renderer. Planet dots stay 8 px on screen regardless of zoom, while edge thickness remains visually about 1 px and edge endpoints stay aligned to the dot centers.
- **Interaction**: The map is read-only. Users can pan by dragging and zoom by scroll wheel, trackpad pinch, or the header scale slider. The header slider uses a logarithmic mapping and stays synchronized with the current map zoom.
- **Coordinate grid and readout**: When zoom exceeds a threshold (about 5 px per map unit), a light grey 1 px grid is overlaid on integer boundaries. A cursor readout in the bottom-left shows floored map coordinates and the current zoom.
- **Data flow stability**: Combined map data is memoized in the main content area, and zoom callbacks are kept stable, so React Flow does not get needlessly reconstructed during zooming.
- **Run scripts**: `scripts/run_dev.sh` runs backend plus Vite dev server. `scripts/run_deploy.sh` serves the built frontend from the backend process.

---

## Optional follow-ups (out of scope for #1)

- Real game state loading and storage.
- Real analytics implementations.
- Production deploy (issue asks for local only for now).
