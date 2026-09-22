# MCP readiness

## What is MCP-ready today

The governed `ToolRegistry` (`ci_failure_orchestrator/governed/tools.py`) already:

- Names tools explicitly
- Declares JSON-serializable input/output schemas
- Separates handler logic from transport
- Classifies risk / side effects
- Emits auditable call/result records via the pipeline

That is the minimum boundary needed to expose tools through the Model Context Protocol later.

## What is not implemented

- No MCP server process
- No MCP client session
- No JSON-RPC transport
- No resource/prompt MCP surfaces
- No OAuth or remote tool hosting

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
