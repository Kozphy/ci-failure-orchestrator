# ADR-0002: Typed tool permission model

## Status

Accepted

## Context

Unrestricted shell access from model output is a primary agent risk.

## Decision

All agent side effects go through `ToolRegistry` with explicit schemas and `ToolRiskLevel`.

## Consequences

- MCP exposure becomes an adapter problem later.
- New capabilities require registering a tool, not inventing ad-hoc exec.
