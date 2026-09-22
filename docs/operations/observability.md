# Foundation observability (Phase 13)

## Architecture

```text
Runtime
  → MetricsRecorder (backend-agnostic)
  → Local Backend (InMemory / JsonMetricsRecorder)
  → Aggregator (rebuild from durable artifacts)
  → SLI
  → SLO
  → Operational Report
```

Metrics **observe** behavior. They do **not** authorize Policy Gate decisions.

## Signals

| Layer | Role |
| --- | --- |
| Logs | Developer/operator diagnostics |
| Metrics | Aggregate operational behavior |
| Audit | Decision/evidence history (authoritative) |

## MetricsRecorder

Protocol methods: `increment`, `observe`, `gauge`.

Implementations:

- `InMemoryMetricsRecorder` — process-local
- `JsonMetricsRecorder` — JSONL under a metrics path
- `SafeMetricsRecorder` — never raises into orchestration
- `NullMetricsRecorder` — no-op default

Telemetry backend failures emit at most a few warnings and do **not** fail runs.
Audit/state persistence failures remain critical (fail-closed).

## Cardinality

Allowed label keys are bounded (`status`, `tool_name`, `policy_outcome`, …).

**Forbidden as labels:** `run_id`, `commit_sha`, `branch`, `file_path`, exception
messages, patch content, secrets. `run_id` may appear in `RunMetricsSummary` files
only.

## Runtime vs benchmark

| Population | `source` label / summary field |
| --- | --- |
| Live foundation runs | `runtime` |
| Phase 12 golden suite | `benchmark` (when configured) |

Do **not** call runtime APPROVE rate “policy accuracy.” Golden accuracy is Phase 12.

## Rebuild path

```bash
python -m ci_failure_orchestrator.cli foundation-operations-report \
  --artifacts artifacts \
  --output artifacts/observability
```

Reads retained `runs/*/metrics-summary.json` (or derives from `state.json`).

Deleting old run artifacts changes locally derived historical metrics.

## Cost / model metrics

`cost metrics not implemented` — no fabricated dollar costs.
Deterministic planners: `model_cost = NOT_APPLICABLE`.

## Optional adapters

Repo root already has optional OpenTelemetry extras and a separate `slo.py` for
platform canaries. Foundation Phase 13 does **not** deploy Prometheus/Grafana/OTel
Collector. Future adapters can implement `MetricsRecorder`.
