"""Run the read-only diagnosis server: ``python -m ci_failure_orchestrator.agent_mcp``."""

from .server import main

raise SystemExit(main())
