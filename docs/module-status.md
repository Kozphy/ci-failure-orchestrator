# Module status

Source of truth: [`ci_failure_orchestrator/module_status.py`](../ci_failure_orchestrator/module_status.py).
Enforced by `tests/test_module_boundaries.py` and `tests/test_cli_groups.py`.
Architecture: [CONTROL_PLANE.md](CONTROL_PLANE.md).

## Canonical — control plane + GTM wedge

| Module | Role |
| --- | --- |
| `foundation/` | Control plane: state machine, retry budget, fail-closed policy, evaluator, escalation, persistence, audit, human decisions |
| `service/` | Verify untrusted candidates, apply draft branches, evidence reports, real-CI check |
| `repo_fix.py` | Compatibility shim re-exporting `service` |
| `patch_sandbox.py` | Disposable git worktree: reproduce, apply, verify |
| `provider_adapters.py` | Subprocess runner for external agent CLIs (env allowlist, timeout) |
| `ci_audit/` | Read-only CI reliability audit (GTM) |
| `doctor/` | CI Doctor CLI (`actions-doctor`); read-only diagnosis (GTM) |
| `server/` | FastAPI `/v1` + worker with SQL durable state |
| `github_client.py` | GitHub Actions REST client (read-oriented) |
| `classifier.py` | Pure regex error classifier |
| `audit.py` | Hash-chained JSONL audit log |
| `governed/` | Governed pipeline package (policy, sandbox, store) |
| `governed_agent/` | Deterministic task-contract scope gate for agent diffs |
| `agent_mcp/` | Read-only MCP adapter |
| `agent_router` | Route/select external workers; never grants merge |
| `approval` | Human approval gate |
| `module_status.py` | This manifest |

Entrypoint: `cli.py`. Canonical commands: `ci-audit-*`, `fix-repo*`, `foundation-*`, `governed-*`.

## Experimental

Empty after the control-plane cut. Do not reintroduce autonomous repair loops here.

## Known boundary violations

None.

## Removed workflows

`self-heal.yml`, `agent-issue-delivery.yml`, `auto-merge-after-checks.yml`, and
repair/research/production-proof workflows were deleted; they encoded agent-repair
and auto-merge theater.
