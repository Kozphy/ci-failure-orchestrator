#!/usr/bin/env bash
set -euo pipefail
python -m pip install -e '.[dev]'
pytest
ci-orchestrator rank --pipeline examples/pipeline.json --failures examples/failures.json --audit audit.jsonl
