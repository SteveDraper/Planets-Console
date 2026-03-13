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

- [ ] Root **uv** workspace + `pyproject.toml` (packages as members if using a monorepo layout).
- [ ] **`packages/server`**: root FastAPI app—middleware, health, shared startup; mount Core API under `/api`, BFF under `/bff`.
- [ ] **`packages/api`**: minimal Core REST sub-app (can stub routers until real domain exists).
- [ ] **`packages/bff`**: BFF sub-app—routers shaped for the SPA; **no business logic**; expose dedicated OpenAPI (e.g. `/bff/openapi.json`) for frontend codegen.
- [ ] **CLI** (Typer) to run the server locally with sane defaults.

### 2. Frontend skeleton

- [ ] **Vite + React + React Router** under `packages/frontend`.
- [ ] **Tailwind + shadcn/ui** per stack convention.
- [ ] **Shell layout** matching overview:
  - Header: placeholders for login identity, game, turn, viewpoint, mode toggle (right-aligned), scale slider (disabled when not in map mode).
  - Left **analytics selector**: vertical list with enable/disable; optional collapsed “details”; greyed when analytic doesn’t support current mode (can stub).
  - **Main area**: tabular vs map mode—placeholder content only.
- [ ] **TanStack Query**—HTTP only to **BFF**, never Core API directly.

### 3. Placeholder analytics & BFF

- [ ] BFF routes return **static/placeholder JSON** for analytics the shell can list.
- [ ] Tabular mode: stacked sub-tiles per enabled analytic with titles (placeholder tables/data).
- [ ] Map mode: placeholder surface (drag/scroll/scale can be stubbed) until React Flow or similar is wired to real data.

### 4. Local run

- [ ] Documented commands to run backend + frontend (proxy or CORS so SPA → `/bff`).
- [ ] Single place (README or script) for “run the console locally.”

### 5. README

- [ ] **Developer setup**: clone, `uv sync`, Node/pnpm (or npm), env if any.
- [ ] **Run/deploy locally**: URLs, BFF OpenAPI URL for codegen, any ports.

### 6. Done when

- [ ] App runs locally with correct **outline** only.
- [ ] BFF endpoints reachable from the SPA; placeholder data flows end-to-end (BFF → UI).
- [ ] Issue #1 can be closed or narrowed once this checklist is satisfied; follow-ups get new issues.

---

## Optional follow-ups (out of scope for #1)

- Real game state loading and storage.
- Real analytics implementations.
- Production deploy (issue asks for local only for now).
