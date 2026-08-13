# MCP 2026-07-28 in-process FastAPI hosting

Research for [issue #311](https://github.com/SteveDraper/Planets-Console/issues/311). Map: [issue #310](https://github.com/SteveDraper/Planets-Console/issues/310).

**Spec:** [MCP 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28)  
**Python SDK:** [`mcp` 2.0.0](https://pypi.org/project/mcp/2.0.0/) ([docs](https://py.sdk.modelcontextprotocol.io/))  
**Verified:** 2026-08-13

## Summary for implementers

Mount **Streamable HTTP** (not stdio) on the existing Planets Console root FastAPI app as a third ASGI sub-app beside `/api` and `/bff`. The protocol requires a single POST-capable MCP endpoint, per-request `_meta` metadata, and `server/discover`. Declare only the server capabilities you implement (tools, resources, prompts); all are optional beyond discovery. **OAuth 2.1 is optional** for a local single-user console; skip it unless the endpoint is reachable beyond localhost. Use **`mcp` 2.0.0** with `MCPServer.streamable_http_app()` and wire `mcp.session_manager.run()` into the **root** app lifespan. Nothing in the spec forces a separate OS process when using Streamable HTTP.

---

## Streamable HTTP vs stdio

### What the spec defines

MCP 2026-07-28 defines two standard transports ([transports overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports)):

| Transport | Binding | Fit for Planets Console |
|-----------|---------|-------------------------|
| **stdio** | Client launches server as a **subprocess**; newline-delimited JSON-RPC on stdin/stdout ([stdio](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)) | **Poor fit.** Inherently a second process, not "same FastAPI process, new endpoints." |
| **Streamable HTTP** | Server exposes one **MCP endpoint** (POST); each JSON-RPC message is its own HTTP request; replies are JSON or request-scoped SSE ([Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)) | **Correct fit** for in-process hosting on the existing uvicorn/FastAPI process. |

Protocol semantics are identical on every transport; only framing differs.

### 2026-07-28 Streamable HTTP requirements (server)

From [Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http):

1. **Single MCP endpoint** -- one URL path accepting HTTP POST (e.g. `/mcp`).
2. **Per-request model** -- no connection-scoped `initialize` handshake and no protocol-level HTTP sessions (2026-07-28 removed the GET stream endpoint and session IDs used in 2025-03-26 through 2025-11-25).
3. **Request handling:**
   - Accept POST with a single JSON-RPC request or notification.
   - For requests: respond with `application/json` (one object) or `text/event-stream` (SSE scoped to that request).
   - For accepted notifications: `202 Accepted` with no body.
4. **Required HTTP headers** on every POST (mirrored from body; body is source of truth):
   - `MCP-Protocol-Version` (must match `_meta.io.modelcontextprotocol/protocolVersion`)
   - `Mcp-Method` (JSON-RPC `method`)
   - `Mcp-Name` (for `tools/call`, `resources/read`, `prompts/get`)
   - Client `Accept` must list both `application/json` and `text/event-stream`.
5. **`server/discover`** -- servers **MUST** implement it ([Discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)).
6. **Security (Streamable HTTP):**
   - **MUST** validate `Origin` (reject invalid with 403).
   - **SHOULD** bind to localhost when running locally.
   - **SHOULD** implement authentication (not MUST).

Cancellation on Streamable HTTP: client closes the SSE response stream (no `notifications/cancelled`).

Long-lived change notifications: optional `subscriptions/listen` SSE stream ([subscriptions](https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions)).

### Mounting beside `/api` and `/bff`

Current root app ([`packages/server/server/app.py`](../../packages/server/server/app.py)):

```python
app = FastAPI(...)
app.mount("/api", api_app)
app.mount("/bff", bff_app)
```

**Parallel pattern for MCP:** mount a Starlette ASGI sub-app returned by the Python SDK.

Official SDK integration ([Add to an existing app](https://py.sdk.modelcontextprotocol.io/run/asgi/)):

```python
from mcp.server import MCPServer

mcp = MCPServer("Planets Console MCP")
# register tools/resources/prompts ...

# Public URL: http://host/mcp  (not /mcp/mcp)
mcp_asgi = mcp.streamable_http_app(streamable_http_path="/")

app.mount("/mcp", mcp_asgi)
```

**Critical lifespan rule:** a mounted sub-app's lifespan does **not** run. The **root** `FastAPI` lifespan must enter `mcp.session_manager.run()` (combine with existing `run_startup_seed_if_configured()` via `AsyncExitStack` or nested `async with`).

**Route ordering:** if using `Mount("/")` for MCP, place explicit routes (`/health`, SPA fallback) **before** the catch-all mount.

**DNS rebinding:** SDK defaults to localhost-only; behind a real hostname, requests get `421 Misdirected Request` until `transport_security=TransportSecuritySettings(...)` is configured ([Deploy & scale](https://py.sdk.modelcontextprotocol.io/run/deploy/)).

**CORS:** only needed for browser-based MCP clients; must allow `Mcp-*` request headers and expose response headers if used.

---

## Tools vs resources vs prompts vs Tasks extension

### Core server primitives (all optional except discover)

Servers **MAY** implement any subset. Capabilities are advertised in `server/discover` ([server overview](https://modelcontextprotocol.io/specification/2026-07-28/server/index)):

| Primitive | Purpose | Control model | Implement if... |
|-----------|---------|---------------|-----------------|
| **Tools** | Executable functions the model can call ([tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)) | Model-controlled (with human-in-the-loop expected) | Agent needs to *do* things (query analytics, fetch game state). Likely **primary** surface for Planets Console. |
| **Resources** | URI-identified context data ([resources](https://modelcontextprotocol.io/specification/2026-07-28/server/resources)) | Application-controlled | Agent needs browseable/readable context (files, schemas, static reference data). Optional if tools return sufficient structured data. |
| **Prompts** | Pre-defined prompt templates ([prompts](https://modelcontextprotocol.io/specification/2026-07-28/server/prompts)) | User-controlled (slash commands, menus) | Exposing curated workflows users pick explicitly. Easy to **skip** for a dev console focused on tool calls. |

If a capability is declared, the server **MUST** respond to its list/read methods (`tools/list`, `resources/list`, `prompts/list`, etc.). Empty lists are valid.

Optional per-capability features (`listChanged`, `subscribe`) only matter if you want push notifications via `subscriptions/listen`.

### Tasks extension (optional)

[Tasks](https://modelcontextprotocol.io/extensions/tasks/overview) is an **opt-in extension** (`io.modelcontextprotocol/tasks`), not core protocol. It lets long-running `tools/call` (etc.) return a durable `taskId` for polling instead of blocking.

**Skip for v1** unless tools routinely exceed client/proxy timeouts or need crash-resumable handles. Requires both client and server to negotiate the extension.

### What a local single-user console can skip

| Feature | Skip? | Notes |
|---------|-------|-------|
| Prompts | Yes | Unless product wants slash-command templates. |
| Resources | Likely | If tools expose query-shaped reads; resources add URI discovery UX. |
| Tasks extension | Yes | Until long-running tool calls need it. |
| `subscriptions/listen` / `listChanged` | Yes | Polling `tools/list` is enough for static catalogs. |
| Client features (elicitation, sampling, roots) | N/A on server | Sampling and roots are **deprecated** in 2026-07-28 ([deprecated](https://modelcontextprotocol.io/specification/2026-07-28/deprecated)). |
| Logging utility | Yes | Deprecated; use stderr / OpenTelemetry instead. |
| MCP Apps / Skills extensions | Yes | Separate opt-in extensions. |

---

## Authorization: local single-user vs OAuth 2.1

### What the spec requires

From [Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization):

> Authorization is **OPTIONAL** for MCP implementations.

When supported:

- HTTP-based transports **SHOULD** conform to the MCP OAuth 2.1 resource-server profile.
- **stdio** transports **SHOULD NOT** follow this spec; credentials come from the environment.
- A protected HTTP server **MUST** implement OAuth 2.0 Protected Resource Metadata (RFC 9728), token validation, 401/403 with `WWW-Authenticate`, etc.

For an **unauthenticated local** Streamable HTTP server:

- OAuth, `/.well-known/oauth-protected-resource/...`, authorization-server discovery, PKCE, and client registration are **not required**.
- Streamable HTTP still **SHOULD** validate `Origin` and **SHOULD** bind to localhost.
- Application-level trust (only Cursor on the same machine can reach the port) is outside the protocol.

### Practical split for Planets Console

| Deployment | Auth approach |
|------------|---------------|
| Local dev, localhost only | No `token_verifier` / `auth=` on `MCPServer`. Rely on bind address + SDK transport security defaults. |
| LAN or remote | Implement OAuth 2.1 resource server **or** a simpler bearer-token `TokenVerifier` plus network controls. Full OAuth is spec-**SHOULD** for HTTP, not MUST. |

SDK note ([Authorization](https://py.sdk.modelcontextprotocol.io/run/authorization/)): `token_verifier` and `auth=AuthSettings(...)` apply only to HTTP transports; stdio and in-memory clients never consult them. `@mcp.custom_route()` endpoints are **never authenticated** by the SDK.

---

## Official Python SDK (2026-07-28)

### Package and version

| Field | Value |
|-------|-------|
| PyPI package | [`mcp`](https://pypi.org/project/mcp/) |
| Version implementing 2026-07-28 | **2.0.0** (released **2026-07-28**) |
| Python requirement | `>=3.10` (compatible with repo's 3.14) |
| Protocol pin | v2 SDK targets [2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28); v1.x is `mcp<2` |

**Dependency cooldown:** repo policy is >=7 days since release when pinning ([`docs/design-account-api-key-and-silent-login.md`](../design-account-api-key-and-silent-login.md)). As of 2026-08-13, `mcp==2.0.0` is **16 days old** and satisfies cooldown.

Suggested pin: `mcp>=2.0.0,<3` (or exact `mcp==2.0.0`).

Key dependencies (from PyPI): `starlette>=0.48.0` (Python 3.14), `sse-starlette>=3.0.0`, `pydantic>=2.12.0`, `mcp-types==2.0.0`.

### FastAPI / Starlette integration

FastAPI is Starlette-based; mount the SDK's ASGI app:

1. Create `MCPServer("...")` and register handlers (`@mcp.tool()`, etc.).
2. `mcp_subapp = mcp.streamable_http_app(streamable_http_path="/")` -- returns a **Starlette** application.
3. `app.mount("/mcp", mcp_subapp)` on the root FastAPI app in `packages/server/server/app.py` (or a dedicated module imported there).
4. Extend root `lifespan` to `async with mcp.session_manager.run():`.
5. For non-localhost deploys, pass `transport_security=TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`.

Alternative: `mcp.run("streamable-http")` starts its **own** uvicorn -- avoid this; it would bypass the unified Planets Console process.

The SDK implements Streamable HTTP headers, `server/discover`, SSE, and optional OAuth resource-server routes. Handlers should be `async` where they call into existing FastAPI/Core services.

---

## What would force a standalone process

| Factor | Forces separate process? |
|--------|--------------------------|
| **stdio transport** | **Yes** -- client spawns a subprocess by design. Not the chosen approach. |
| **Streamable HTTP** | **No** -- spec describes an independent *logical* server, not a separate OS process. Same uvicorn worker is valid. |
| **SDK session manager** | **No** -- in-process; needs lifespan wiring only. |
| **OAuth authorization server** | **No** for resource-server-only -- use external IdP; SDK publishes protected-resource metadata on the MCP app. |
| **CPU-heavy tool work** | **No** (protocol) -- operational choice to offload to workers, not a spec requirement. |
| **localhost / DNS rebinding defaults** | **No** -- configuration (`transport_security`, bind address), not a second process. |

**Conclusion:** Same-host, in-process FastAPI mounting is fully aligned with MCP 2026-07-28. The only standard transport that *requires* a separate process is stdio.

---

## Base protocol checklist (all transports)

From [basic overview](https://modelcontextprotocol.io/specification/2026-07-28/basic/index):

**MUST implement:**

- JSON-RPC 2.0 messages with `resultType` on results
- Per-request `_meta` fields (`io.modelcontextprotocol/protocolVersion`, `clientInfo`, `clientCapabilities`)
- Message patterns: request/response, MRTR (`InputRequiredResult`), cancellation rules
- `server/discover`

**MAY implement:** resources, prompts, tools, utilities (pagination, caching, completion), extensions.

**Deprecated in 2026-07-28 (do not adopt):** roots, sampling, logging utility, HTTP+SSE (2024-11-05), connection-scoped `initialize` handshake for new servers.

---

## References

- [MCP 2026-07-28 specification](https://modelcontextprotocol.io/specification/2026-07-28)
- [Documentation index](https://modelcontextprotocol.io/llms.txt)
- [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)
- [Authorization](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization)
- [server/discover](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)
- [Tasks extension](https://modelcontextprotocol.io/extensions/tasks/overview)
- [MCP Python SDK docs](https://py.sdk.modelcontextprotocol.io/)
- [Python SDK: Add to an existing app](https://py.sdk.modelcontextprotocol.io/run/asgi/)
- [Python SDK: Authorization](https://py.sdk.modelcontextprotocol.io/run/authorization/)
- [mcp 2.0.0 on PyPI](https://pypi.org/project/mcp/2.0.0/)
