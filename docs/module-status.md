# Module status

Source of truth: [`ci_failure_orchestrator/module_status.py`](../ci_failure_orchestrator/module_status.py). Enforced by `tests/test_module_boundaries.py` (every module classified; canonical modules may not import experimental ones) and `tests/test_cli_groups.py` (experimental commands labeled in `--help`). Plan: [service-v0.1-plan.md](service-v0.1-plan.md).

## Canonical — the v0.1 service path

| Module | Role |
| --- | --- |
| `foundation/` | Control plane: state machine, retry budget, fail-closed policy, evaluator, escalation, persistence, audit, human decisions, benchmark and operations reports |
| `service/` | Service path: failure ingest, prompt building, proposal sources, worktree sandbox adapter, run and apply (Stage 1 split of `repo_fix.py`) |
| `repo_fix.py` | Compatibility shim re-exporting `service` |
| `patch_sandbox.py` | Disposable git worktree: reproduce, apply, verify |
| `provider_adapters.py` | Subprocess provider runner with env allowlist, timeout, output cap |
| `github_client.py` | GitHub Actions REST client (runs, jobs, logs) |
| `classifier.py` | Pure regex error classifier used by `foundation/classifier.py` |
| `module_status.py` | This manifest |

Entrypoint: `cli.py` wires both canonical and experimental commands. Canonical commands: `fix-repo`, `fix-repo-apply`, `foundation-*`. All others are labeled `[experimental]` in `ci-orchestrator --help`.

## Known boundary violations (may only shrink)

| From (canonical) | To (experimental) | Removal |
| --- | --- | --- |
| `foundation.classifier` | `github_repair_adapter` (pulls in `supervisor`, `task_idempotency`) | Stage 3 — classification-aware policy |

## Experimental — kept, not on the service path

Not deleted or moved in v0.1.0. No new service features depend on them.

| Group | Modules |
| --- | --- |
| diagnosis | `affected_tests`, `baselines`, `causal`, `config`, `corpus`, `corpus_benchmark`, `github_actions_collector`, `github_ingest`, `graph`, `models`, `provenance`, `ranker`, `test_selection`, `verification` |
| governed | `governed/` |
| trust | `audit`, `network_discovery`, `trust`, `trust_gateway`, `trust_policy` |
| supervisor | `approval`, `github_repair_adapter`, `repair_state_machine`, `state_machine`, `supervisor`, `task_idempotency` |
| control-plane | `agent_router`, `api`, `control_plane`, `control_plane_run`, `policy`, `production`, `protocol`, `tournament` |
| scripted-repair | `ablation`, `agent_eval`, `agent_executor`, `agent_loop`, `command_agent`, `evaluator`, `repair`, `repair_agents`, `repair_loop`, `repair_planner` |
| execution-stack | `execution`, `git_validation`, `repair_execution`, `test_runner`, `workspace`, `worktree` |
| runtime | `autonomous_runtime`, `distributed_runtime`, `runtime_contracts` |
| platform | `canary`, `dashboard`, `dora_metrics`, `fleet`, `platform`, `slo` |
| evidence | `benchmark`, `benchmark_suite`, `deployment_evidence`, `evidence_signing`, `live_semantic_merge_eval`, `production_evidence`, `production_proof`, `regression_gate`, `release_gates`, `repair_benchmark`, `research_evaluation`, `research_stats`, `statistical_gate` |
| merge-conflict | `merge_conflict_agent`, `merge_conflict_benchmark`, `openai_merge_resolver` |
| memory | `failure_memory`, `memory_aware_planner`, `memory_context`, `sqlite_memory` |
| telemetry | `otel`, `repair_telemetry`, `telemetry` |

Scripts outside the package on non-canonical paths: `scripts/sandbox_repair.py`, `scripts/self_heal_github.py` (used by the manual-only `self-heal.yml`).

## Workflows with write or merge capability

| Workflow | Status (Stage 0) | Plan |
| --- | --- | --- |
| `auto-merge-after-checks.yml` | Manual trigger only and job hard-disabled (`if: false`) | Delete in Stage 9 |
| `self-heal.yml` | Manual trigger only; inert without a `workflow_run` payload | Replace with canonical Action caller in Stage 6 |
| `agent-issue-delivery.yml` | Manual trigger only; inert without an `issues` payload | Evaluate, then remove or replace in Stage 6/9 |

## Planned

`service/dag.py` (Stage 4), `schemas/run.v1.json` and `service-metrics` (Stage 5), reusable Action (Stage 6), GitHub App (after v0.1.0).
