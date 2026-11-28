#!/usr/bin/env bash
# Reproduce the 2026-10-11 audit runs. Runs existing tests and read-only commands only;
# it changes no source, tests, workflows or dependency pins.
# Usage: bash docs/audit/reproduce-audit.sh [output-dir]   (run from the repository root)
set -uo pipefail

OUT="${1:-audit-output}"
mkdir -p "$OUT"

# Isolated environment (same extras the ci.yml "test" job installs).
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[dev,server]'
# Several tests spawn a bare `python`; put the venv first on PATH, as setup-python does in CI.
export PATH="$PWD/.venv/bin:$PATH"
# Run unauthenticated so no ambient token influences tests or the public audit.
unset GITHUB_TOKEN GH_TOKEN

# 1. Focused CI-audit tests (ci_failure_orchestrator/ci_audit).
python -m pytest tests/test_ci_audit.py -v -rA -p no:cacheprovider 2>&1 | tee "$OUT/focused-ci-audit.log"

# 2. Full suite with coverage (same flags as ci.yml "Tests with coverage").
python -m pytest --cov=ci_failure_orchestrator --cov-report=term-missing \
  --cov-report="xml:$OUT/coverage.xml" -rfEsxX -p no:cacheprovider --durations=15 \
  2>&1 | tee "$OUT/full-suite.log"

# 3. Read-only, unauthenticated public audit of this repository (GET requests only).
ci-orchestrator ci-audit-collect --repo Kozphy/ci-failure-orchestrator --days 30 \
  --max-runs 30 --max-logs 5 --output "$OUT/public-audit-export.json" | tee "$OUT/public-audit-collect.log"
ci-orchestrator ci-audit-report "$OUT/public-audit-export.json" \
  --output "$OUT/public-audit-report.md" --json "$OUT/public-audit-analysis.json" | tee "$OUT/public-audit-report.log"
