# Stage A — Dashboard capability matrix

Baseline: `origin/main` inspected 2026-11-08 before PR 1. No React/HTML UI files were present.

| Capability | Implemented | File path | Tested | Gap |
| --- | --- | --- | --- | --- |
| CI diagnosis | Yes | `ci_failure_orchestrator/doctor/`, `action.yml` | Yes (existing doctor tests) | Not a dashboard |
| Repair verification | Yes | `foundation/remediation.py`, `service/` | Yes (`test_repair_verification.py`) | States exist; no UI |
| Policy engine | Yes | `foundation/policy.py` | Yes | No dashboard binding |
| Audit evidence | Yes | `service/evidence_report.py`, `FileEvidenceStore` | Yes | No explorer UI |
| Metrics aggregation | Partial | `service/remediation_metrics.py`, fleet `dashboard.py` | Partial | Fleet dashboard is SLO/fleet, not CI history UI. Repair metrics exist via CLI |
| Dashboard UI | No | none | No | No frontend package |

Notes:

- `ci_failure_orchestrator/dashboard.py` builds a fleet/SLO/benchmark snapshot. It is not an interactive CI reliability product UI.
- CI failure rate cannot be derived from repair artifacts alone. PR 1 therefore returns N/A unless a `ci-audit.export.v1` path is supplied.
- This document is inspection evidence, not a claim that the interactive dashboard is complete.
