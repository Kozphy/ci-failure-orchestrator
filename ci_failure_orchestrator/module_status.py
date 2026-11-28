"""Machine-readable module and CLI status for the control-plane cut.

Source of truth for which code is on the canonical service path. Enforced by
``tests/test_module_boundaries.py`` and ``tests/test_cli_groups.py``; the human
view is ``docs/module-status.md``.

Entries name top-level modules or packages of ``ci_failure_orchestrator``. A
package entry covers every module inside it.
"""

from __future__ import annotations

CANONICAL: frozenset[str] = frozenset(
    {
        "__init__",
        "module_status",
        "foundation",
        "service",
        # Compatibility shim re-exporting service.
        "repo_fix",
        "patch_sandbox",
        "provider_adapters",
        "github_client",
        # Pure regex classifier used by foundation.classifier.
        "classifier",
        # Tamper-evident JSONL audit used by governed pipelines.
        "audit",
        # Read-only GitHub Actions reliability audit (GTM wedge).
        "ci_audit",
        # CI Doctor product CLI (actions-doctor); read-only GTM wedge.
        "doctor",
        # HTTP API + worker over the foundation with SQL durable state.
        "server",
        # Promoted control-plane surfaces (agents are untrusted proposers).
        "governed",
        "governed_agent",
        "agent_mcp",
        "agent_router",
        "approval",
    }
)

ENTRYPOINTS: frozenset[str] = frozenset({"cli"})

# Experimental surface removed in the control-plane cut. Kept empty so boundary
# helpers and docs remain stable; do not reintroduce agent/repair theater here.
EXPERIMENTAL: dict[str, frozenset[str]] = {}

# Canonical -> experimental imports that already exist. The boundary test fails
# on any new edge and on any listed edge that no longer exists, so this set can
# only shrink. Empty since Stage 3.
KNOWN_BOUNDARY_VIOLATIONS: frozenset[tuple[str, str]] = frozenset()

CANONICAL_COMMANDS: frozenset[str] = frozenset(
    {
        "ci-audit-collect",
        "ci-audit-report",
        "fix-repo",
        "fix-repo-apply",
        "fix-repo-task",
        "fix-repo-verify-ci",
        "fix-repo-metrics",
        "fix-repo-report",
        "foundation-run",
        "foundation-inspect",
        "foundation-events",
        "foundation-resume",
        "foundation-decide",
        "foundation-verify",
        "foundation-benchmark",
        "foundation-operations-report",
        "foundation-slo-check",
        "governed-run",
        "governed-explain",
        "governed-replay",
        "governed-benchmark",
    }
)

EXPERIMENTAL_COMMANDS: frozenset[str] = frozenset()

EXPERIMENTAL_LABEL = "[experimental] "


def experimental_group(top_level: str) -> str | None:
    """Return the experimental group that lists a top-level module, or None."""
    for group, members in EXPERIMENTAL.items():
        if top_level in members:
            return group
    return None


def status_of(top_level: str) -> str | None:
    """Return ``"canonical"``, ``"entrypoint"`` or ``"experimental"`` for a top-level module, or None if unlisted."""
    if top_level in CANONICAL:
        return "canonical"
    if top_level in ENTRYPOINTS:
        return "entrypoint"
    if experimental_group(top_level) is not None:
        return "experimental"
    return None
