# ADR-0007: MCP-ready tool boundary without MCP runtime

## Status

Accepted

## Context

MCP is useful for tool exposure but not required for local orchestration correctness.

## Decision

Keep tools transport-agnostic and document MCP mapping; do not add MCP server deps to core.

## Consequences

- Optional adapter can be introduced later without redesigning tools.
