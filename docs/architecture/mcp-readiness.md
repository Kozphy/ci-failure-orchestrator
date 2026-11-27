# MCP readiness

## What is MCP-ready today

The governed `ToolRegistry` (`ci_failure_orchestrator/governed/tools.py`) already:

- Names tools explicitly
- Declares JSON-serializable input/output schemas
- Separates handler logic from transport
- Classifies risk / side effects
- Emits auditable call/result records via the pipeline

That is the minimum boundary needed to expose tools through the Model Context Protocol later.

## What the optional adapter implements

`ci_failure_orchestrator/agent_mcp/` is a stdio JSON-RPC process (Content-Length framing, no MCP SDK dependency). It exposes three read-only tools over existing functions: saved-log diagnosis, a local reliability-export summary, and stored repair evidence. It does not call the governed `ToolRegistry`, so `test_runner` and other write/restricted tools stay unreachable. Installation and limits: [docs/agent-mcp.md](../agent-mcp.md).

## What is still not implemented

- No MCP SDK client session and no resources or prompts
- No OAuth or remote tool hosting
- No adapter over the governed `ToolRegistry` (that would include a restricted test runner)
- The stdio server does not collect live GitHub logs or execute verify commands

## Mapping to MCP

| Governed concept | MCP analogue |
| --- | --- |
| `ToolSpec.name` | tool name |
| `ToolSpec.description` | tool description |
| `ToolSpec.input_schema` | `inputSchema` |
| `ToolRegistry.invoke` | `tools/call` |
| Audit `TOOL_CALLED` / `TOOL_COMPLETED` | server-side logging around call |

## Required to expose the registry through MCP

1. Optional dependency on an MCP SDK (kept out of core deps).
2. Adapter that lists `ToolRegistry.list_tools()` as MCP tools.
3. Adapter that forwards `tools/call` → `registry.invoke` with run/correlation IDs.
4. Policy gate before invoking `HUMAN_APPROVAL_REQUIRED` / `RESTRICTED` tools.
5. Integration tests with a local MCP client.

Until then, keep transport out of core orchestration.
