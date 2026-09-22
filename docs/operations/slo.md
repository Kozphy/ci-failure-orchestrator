# Example SLOs (design targets)

These are **example measurable targets** for a governed CI repair agent.
They are not measured production performance for this repository.

| SLI | Example SLO | Measurement method |
| --- | --- | --- |
| % eligible failures classified | ≥ 95% of fixture/live ingest events emit a class | Count `FAILURE_CLASSIFIED` / runs |
| Safe remediation success rate | ≥ 70% of auto-eligible lint/type/test cases reach `SUCCEEDED` on synthetic suite | `ci-orchestrator benchmark` |
| False remediation rate | ≤ 5% of `SUCCEEDED` later fail independent verification | Track verify-after-approve |
| Policy violation escape rate | 0 escapes on golden unsafe fixtures | Golden cases with `forbid_success` |
| Mean remediation latency | Track p50/p95 locally | `PipelineMetrics.latencies_ms` |
| Human escalation rate | Track; interpret by failure class | `agent_runs_escalated_total` |
| Audit completeness | 100% runs have `RUN_STARTED` and `RUN_COMPLETED` | Store/audit event query |

## Distinction

- **SLI**: measured indicator
- **SLO**: target on that indicator
- **Capability**: implemented control (may exist without meeting SLO)
- **Evidence**: benchmark/CI artifacts actually produced
