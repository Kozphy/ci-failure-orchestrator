# Foundation SLI / SLO (Phase 13)

All targets in `config/slo.json` are **EXAMPLE_TARGET / provisional**.
They are **not** measured production SLOs.

## Window semantics

Default window: `retained_local_runs` (optionally last N).

Do not claim a “30-day SLO” if only a few days of artifacts exist.

## SLI catalog

| ID | Name | Numerator | Denominator | Eligibility |
| --- | --- | --- | --- | --- |
| SLI-001 | automated_run_success_rate | technical PASS | eligible runtime repair runs | `source=runtime` and `eligible_repair` |
| SLI-002 | safe_approval_rate | PASS+APPROVE | PASS with policy decision | descriptive only |
| SLI-003 | escalation_rate | AWAITING_HUMAN | policy-reviewed runs | operational load |
| SLI-004 | retry_rate | retries≥1 | eligible runs | Phase 7 semantics |
| SLI-005 | bounded_retry_compliance | bounded stop reasons | runs with retries≥1 | control correctness |
| SLI-006 | policy_execution_coverage | PASS with policy decision | technical PASS | coverage ≠ accuracy |
| SLI-007 | security_containment_compliance | security_blocks | security_findings | after detection only |
| SLI-008 | audit_completeness | audit_complete | runs with audit assessed | Phase 12 definition |
| SLI-009 | persistence_reliability | persistence_ok | all runtime runs | critical persistence |
| SLI-010 | run_latency | distribution | timed runs | local timing only |

Zero denominators → `INSUFFICIENT_DATA` / `n/a` — never 100%.

## SLO catalog (EXAMPLE)

| SLO | SLI | Target | Min samples | Notes |
| --- | --- | --- | --- | --- |
| SLO-001 | SLI-005 | ≥100% | 1 | bounded retry |
| SLO-002 | SLI-008 | ≥99% | 5 | audit completeness |
| SLO-003 | SLI-006 | ≥100% | 1 | policy coverage |
| SLO-004 | SLI-007 | ≥100% | 1 | security blocks |
| SLO-005 | SLI-009 | ≥99% | 5 | persistence |

Do **not** set blind repair-success ≥99% as a production objective.

## Error budget

For `>=` ratio SLOs:

```text
allowed_bad = (1 - target) * denominator
observed_bad = denominator - numerator
remaining = allowed_bad - observed_bad
```

Not applied to descriptive rates (e.g. escalation rate) unless an explicit SLO exists.

## CLI

```bash
python -m ci_failure_orchestrator.cli foundation-operations-report
python -m ci_failure_orchestrator.cli foundation-slo-check
```

Exit codes for `foundation-slo-check`:

- `0` — no MISSED
- `1` — at least one MISSED
- `3` — INSUFFICIENT_DATA when `--fail-insufficient`
