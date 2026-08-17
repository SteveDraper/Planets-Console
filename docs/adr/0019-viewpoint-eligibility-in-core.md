# Viewpoint eligibility lives in Core; SPA consumes via BFF

Status: accepted

**MCP visibility ceiling** must match SPA **viewpoint eligibility**, but that allowed-set lived only in the SPA (`deriveShellViewpoints`, `shouldUsePseudoViewpointForLogin`). MCP cannot import SPA code, and a Python copy in `mcp_adapter` would be a second policy plus domain logic in the adapter ([ADR 0015](0015-mcp-adapter-package.md)).

**Viewpoint eligibility** is a Core service next to `GameService` (not `api.concepts/` -- this is console visibility policy, not a host mechanic). Given **GameInfo** and a **login identity**, Core returns the allowed **perspective** set:

- In-progress, login is a player: `{own slot}` only -- not spectator `0`
- In-progress, login is not a player: `{0}` only
- Finished: every player slot `1..N` -- not spectator `0`

That XOR is what the SPA already does. [ADR 0014](0014-mcp-login-identity-and-visibility.md)'s "own slot or spectator" is this XOR, not a free choice for a playing login. MCP calls the service in-process. The SPA consumes the set via the BFF (login-keyed; refetch on **name-only identity switch**) and applies chrome; it does not keep a second predicate. Spectator `0` appears in the dropdown iff `0` is in the set.

**SPA-only:** **storage-only load** (filter by what's on disk), display names, default **viewpoint**, disabled-row chrome, time-machine turn view. Empty login is not a Core eligibility input -- MCP **credential probe**s fail closed; the SPA is storage-only or blocked. Load-all's expected-perspective set stays a different policy (what to bulk-fetch).

## Considered options

- **Core `concepts/`** -- rejected; host-aligned game rules, not console ACL.
- **BFF owns the predicate** -- rejected; MCP cannot import BFF ([ADR 0015](0015-mcp-adapter-package.md)).
- **Keep the SPA as source of truth; reimplement in `mcp_adapter`** -- rejected; two copies, and the adapter would own domain logic.
- **Storage-only eligibility in Core** -- rejected; MCP has no **storage-only load** path ([ADR 0014](0014-mcp-login-identity-and-visibility.md)). Pollutes the domain rule with a SPA-only input.
- **Keep spectator-0-for-non-player in the SPA** -- rejected; MCP would miss the live-spectator branch.
- **In-progress player may also choose `0`** -- rejected; looser than the human app.
- **Finished also includes `0`** -- rejected; the SPA dropdown does not offer spectator on completed games.
- **TypeScript port of the Core predicate** -- rejected; the copy this ticket exists to remove.
- **SPA calls Core HTTP** -- rejected; the frontend talks only to the BFF.
- **Shared JSON decision table** -- rejected; two interpreters for a small predicate.

## Consequences

- Core: `ViewpointEligibilityService.eligible_perspectives(game_info, login_identity) -> frozenset[int]`. Empty login raises `ValidationError`.
- BFF: `GET /games/{game_id}/viewpoint-eligibility?username=` returns `{ "perspectives": [...] }` (sorted slots). The cache key must include login so **name-only identity switch** does not serve a stale set.
- `shouldUsePseudoViewpointForLogin` is not a second policy once the SPA reads the BFF set.
- Glossary: **viewpoint eligibility**, **perspective** (includes spectator `0`) in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [Shared viewpoint eligibility below the SPA for MCP and the shell](https://github.com/SteveDraper/Planets-Console/issues/323).
