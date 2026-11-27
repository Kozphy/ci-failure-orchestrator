"""Run the read-only MCP server: ``python -m ci_failure_orchestrator.agent_mcp``."""

from .server import main

raise SystemExit(main())
