# Implementation checklist: Basic UI framework

**Source enhancement:** [#1 – [Feature] Basic UI frameworking](https://github.com/SteveDraper/Planets-Console/issues/1)

This doc is the versioned checklist and acceptance bar for that issue. Update it as work lands (check boxes, notes).

---

## Goal (from the issue)

- Broad-brush **UX framework** only—no real game/analytics content yet.
- Infrastructure so **Python (BFF/API/server)** and **React** can run locally.
- **Layout** aligned with [project overview](../.cursor/rules/overview.mdc) (header, analytics bar, main area), implemented **through the BFF layer** with **placeholder analytics** and **placeholder data**.
- **README** sections: developer setup + how to run/deploy locally.

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

- [x] **Vite + React + React Router** under `packages/frontend`.
- [x] **Tailwind + shadcn/ui** per stack convention.
- [x] **Shell layout** matching overview:
  - Header: placeholders for login identity, game, turn, viewpoint, mode toggle (right-aligned), scale slider (disabled when not in map mode).
  - Left **analytics selector**: vertical list with enable/disable; optional collapsed “details”; greyed when analytic doesn’t support current mode (can stub).
  - **Main area**: tabular vs map mode—placeholder content only.
- [x] **TanStack Query**—HTTP only to **BFF**, never Core API directly.

### 3. Placeholder analytics & BFF

- [x] BFF routes return **static/placeholder JSON** for analytics the shell can list.
- [x] Tabular mode: stacked sub-tiles per enabled analytic with titles (placeholder tables/data).
- [x] Map mode: React Flow wired to BFF placeholder data; base map (planets + edges) always shown; analytics add on top; pan, zoom, coordinate grid when zoomed in, fixed-size node dots, cursor readout (x, y, zoom).

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

- **Base map**: A pseudo-analytic of type `base` supplies the core map (planets as nodes, connections as edges). It is always included and not shown in the analytics sidebar. Selectable analytics add elements on top.
- **Rendering**: React Flow with custom node type (dot + label) and custom edges. Planet dots are drawn in **screen space** via `FixedSizeDotsOverlay` so they stay 8px regardless of zoom; edges are 1px in screen space. Node layout uses flow coordinates; edges connect to cell centers (half-integer alignment with grid).
- **Interaction**: Pan (drag), zoom (scroll/pinch). Read-only (no add/move/delete). Default cursor in map pane (no grab hand).
- **Coordinate grid**: When zoom is above a threshold (~5 px per unit), a light grey 1px grid is overlaid on integer boundaries. Cursor readout shows floor(x), floor(y) and current zoom so coordinates align with the grid.
- **Run scripts**: `scripts/run_dev.sh` (backend + Vite dev server); `scripts/run_deploy.sh` (single process with built frontend).

---

## Optional follow-ups (out of scope for #1)

- Real game state loading and storage.
- Real analytics implementations.
- Production deploy (issue asks for local only for now).
