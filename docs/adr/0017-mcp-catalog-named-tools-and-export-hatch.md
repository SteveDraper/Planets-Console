# MCP catalog is named gameplay tools plus an export query hatch

Status: accepted

The agent MCP surface needs a catalog philosophy: named gameplay tools vs generic JSONPath vs MCP resources vs hybrid ([MCP catalog shape: named gameplay tools vs generic query vs resources](https://github.com/SteveDraper/Planets-Console/issues/317)). Tools are already the primary MCP primitive ([MCP 2026-07-28 protocol and Python SDK for an in-process host](https://github.com/SteveDraper/Planets-Console/issues/311)); this ADR records how those tools are shaped and which protocol capabilities v1 declares.

v1 is a **hybrid**. Advisor questions are **MCP named gameplay tool**s: gameplay-shaped names and arguments (the question the agent asks), wrapping Core concepts underneath -- not 1:1 BFF/Core HTTP twins, not family mega-tools with a `kind` enum. The only generic escape hatch is the **MCP export query hatch** (JSONPath + scope over an **analytic export catalog**). That hatch includes an MCP **tool** that returns the catalog (**analytic export value schema**, path-prefix rules, ordering semantics) so an agent that already understands Planets.nu can see that e.g. `$.solutions[0]` is the top scores explanation -- schema retrieval is not optional, not baked solely into the query tool's description, and not an MCP resource. v1 declares **tools only** (`server/discover`): no `resources`, no `prompts`. Every tool `description` plus input schema is written for a game-literate agent: what question it answers, when to prefer it over **MCP TurnInfo fallback**, when it does not apply.

## Considered options

- **Named tools only, no hatch** -- rejected; a named tool per **analytic export path** ignores the self-describing export catalogs.
- **Generic query only** -- rejected; geometry and concept questions would become JSONPath over dumps, which [ADR 0016](0016-mcp-turninfo-fallback-and-disk-proximity.md) forbids.
- **Resources as the catalog** -- rejected; resources are application-controlled, advisors need model-controlled calls. Schema-as-URI duplicates the hatch describe tool and makes TurnInfo-as-URI tempting.
- **HTTP-twin tools** -- rejected; [ADR 0015](0015-mcp-adapter-package.md) is information parity, not BFF JSON. Descriptions would leak adapter paths.
- **Family mega-tools with kind enums** -- rejected; a generic query in disguise; weaker per-question descriptions.
- **Prompts in v1** -- rejected; user-picked slash templates are not how Cursor agents call this server. Add later if wanted.
- **Query-only hatch** (schema only in the query tool description) -- rejected; the agent cannot know catalog ordering and path meaning without retrieving the **analytic export catalog**.

## Consequences

- Exact named-tool list: [Exact v1 named gameplay tool list](https://github.com/SteveDraper/Planets-Console/issues/324). Wrap vs new Core helpers: [ADR 0021](0021-mcp-v1-wrap-existing-gated-fills.md).
- Hatch tool names, ensure vs persisted, and no MCP streams: [ADR 0020](0020-mcp-export-hatch-describe-query-ensure.md).
- Glossary: **MCP named gameplay tool**, **MCP export query hatch** in [CONTEXT.md](../../CONTEXT.md). Design index: [design-mcp.md](../design-mcp.md). Export Future MCP: [design-analytic-exports.md](../design-analytic-exports.md).

Map: [Epic: agent MCP surface for game state and analytics](https://github.com/SteveDraper/Planets-Console/issues/310). Ticket: [MCP catalog shape: named gameplay tools vs generic query vs resources](https://github.com/SteveDraper/Planets-Console/issues/317).
