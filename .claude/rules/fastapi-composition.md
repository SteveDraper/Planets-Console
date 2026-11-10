---
paths:
  - "packages/server/**/*.py"
  - "packages/api/**/*.py"
  - "packages/bff/**/*.py"
  - "packages/mcp_adapter/**/*.py"
---

# Architecture: FastAPI composition

## Preferred FastAPI App Composition

Use one Python process, but structure it as a root FastAPI app plus mounted sub-apps:

- a root app for process-level wiring (middleware, shared startup/shutdown, top-level health endpoints)
- the root app lives in `packages/server/app.py`
- a Core REST API sub-app mounted under `/api`
- a BFF sub-app mounted under `/bff`
- an MCP Streamable HTTP sub-app mounted under `/mcp` (session manager runs in the **root** lifespan)

This keeps deployment simple while giving each layer its own routing and OpenAPI surface. The preferred frontend codegen source is the BFF sub-app schema endpoint, e.g. `/bff/openapi.json`.
