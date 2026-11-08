# Reliability dashboard — PR 1

Foundation only. No HTTP API and no React UI yet.

```text
ci_failure_orchestrator/reliability_dashboard/
  catalog.py      # index runs/*/ artifacts
  metrics.py      # executive overview with null/N/A reasons
  integrity.py    # SHA-256 file and canonical JSON digests
```

Reuse, do not replace: `load_remediation_records`, `compute_remediation_metrics`, `load_run_measurements`, `compute_operational_metrics`, `analyze_export`, `canonical_json`.

## Local check

```bash
pip install -e ".[dev]"
python -m pytest -q tests/test_reliability_dashboard_metrics.py
```

## Later PRs

- PR 2: localhost-bound FastAPI read-only endpoints over these functions.
- PR 3: React UI.
- PR 4: screenshots, accessibility, and demo packaging.
