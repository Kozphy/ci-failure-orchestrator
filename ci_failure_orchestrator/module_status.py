"""Machine-readable module and CLI status for the v0.1 CI failure service.

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
    }
)

ENTRYPOINTS: frozenset[str] = frozenset({"cli"})

EXPERIMENTAL: dict[str, frozenset[str]] = {
    "diagnosis": frozenset(
        {
            "affected_tests",
            "baselines",
            "causal",
            "config",
            "corpus",
            "corpus_benchmark",
            "github_actions_collector",
            "github_ingest",
            "graph",
            "models",
            "provenance",
            "ranker",
            "test_selection",
            "verification",
        }
    ),
    "governed": frozenset({"governed"}),
    "trust": frozenset({"audit", "network_discovery", "trust", "trust_gateway", "trust_policy"}),
    "supervisor": frozenset(
        {
            "approval",
            "github_repair_adapter",
            "repair_state_machine",
            "state_machine",
            "supervisor",
            "task_idempotency",
        }
    ),
    "control-plane": frozenset(
        {
            "agent_router",
            "api",
            "control_plane",
            "control_plane_run",
            "policy",
            "production",
            "protocol",
            "tournament",
        }
    ),
    "scripted-repair": frozenset(
        {
            "ablation",
            "agent_eval",
            "agent_executor",
            "agent_loop",
            "command_agent",
            "evaluator",
            "repair",
            "repair_agents",
            "repair_loop",
            "repair_planner",
        }
    ),
    "execution-stack": frozenset(
        {"execution", "git_validation", "repair_execution", "test_runner", "workspace", "worktree"}
    ),
    "runtime": frozenset({"autonomous_runtime", "distributed_runtime", "runtime_contracts"}),
    "platform": frozenset({"canary", "dashboard", "dora_metrics", "fleet", "platform", "slo"}),
    "evidence": frozenset(
        {
            "benchmark",
            "benchmark_suite",
            "deployment_evidence",
            "evidence_signing",
            "live_semantic_merge_eval",
            "production_evidence",
            "production_proof",
            "regression_gate",
            "release_gates",
            "repair_benchmark",
            "research_evaluation",
            "research_stats",
            "statistical_gate",
        }
    ),
    "merge-conflict": frozenset(
        {"merge_conflict_agent", "merge_conflict_benchmark", "openai_merge_resolver"}
    ),
    "memory": frozenset({"failure_memory", "memory_aware_planner", "memory_context", "sqlite_memory"}),
    "telemetry": frozenset({"otel", "repair_telemetry", "telemetry"}),
}

# Canonical -> experimental imports that already exist. The boundary test fails
# on any new edge and on any listed edge that no longer exists, so this set can
# only shrink. Removal is scheduled for Stage 3 (classification-aware policy).
KNOWN_BOUNDARY_VIOLATIONS: frozenset[tuple[str, str]] = frozenset(
    {("foundation.classifier", "github_repair_adapter")}
)

CANONICAL_COMMANDS: frozenset[str] = frozenset(
    {
        "fix-repo",
        "fix-repo-apply",
        "foundation-run",
        "foundation-inspect",
        "foundation-events",
        "foundation-resume",
        "foundation-decide",
        "foundation-verify",
        "foundation-benchmark",
        "foundation-operations-report",
        "foundation-slo-check",
    }
)

EXPERIMENTAL_COMMANDS: frozenset[str] = frozenset(
    {
        "classify",
        "rank",
        "analyze",
        "analyze-run",
        "trust-run",
        "run",
        "explain",
        "replay",
        "benchmark",
    }
)

EXPERIMENTAL_LABEL = "[experimental] "


def experimental_group(top_level: str) -> str | None:
    for group, members in EXPERIMENTAL.items():
        if top_level in members:
            return group
    return None


def status_of(top_level: str) -> str | None:
    if top_level in CANONICAL:
        return "canonical"
    if top_level in ENTRYPOINTS:
        return "entrypoint"
    if experimental_group(top_level) is not None:
        return "experimental"
    return None
