#!/usr/bin/env bash
# ==============================================================================
# CI Failure Orchestrator Demo Script
# ==============================================================================
# Purpose: Install dependencies, run tests, and execute a demo CI failure analysis
#
# Required Privileges: Standard user (no elevated privileges required)
# Inputs: None (uses example files in examples/ directory)
# Outputs: Test results to stdout, audit log to audit.jsonl
# Side Effects:
#   - Installs Python package in development mode
#   - Creates/overwrites audit.jsonl file
#   - Executes pytest which may create temporary test artifacts
#
# Safety Boundaries:
#   - Only reads from examples/ directory (no user filesystem writes except audit.jsonl)
#   - Uses pip install -e which only modifies current environment
#   - No network operations (uses local package)
#   - No system configuration changes
#
# Idempotency: Safe to run multiple times (pip install -e is idempotent)
#
# Recovery Notes:
#   - If pip install fails: Check Python environment and dependencies
#   - If pytest fails: Review test output for failures
#   - If ci-orchestrator fails: Check example files exist and are valid JSON
#
# Example Usage:
#   ./demo.sh
# ==============================================================================

set -euo pipefail
python -m pip install -e '.[dev]'
pytest
ci-orchestrator rank --pipeline examples/pipeline.json --failures examples/failures.json --audit audit.jsonl
