# Evidence package

This directory holds **reproducible sample artifacts** for the foundation control plane.

## Honesty labels

| Label | Meaning here |
| --- | --- |
| Synthetic / simulated | Scripted proposals, local sandbox, deterministic policy |
| Evidence level | **E4-simulated** (controlled local runs with retained artifacts) |
| Not included | **E5** production deployments, live incidents, measured fleet SLOs |

Do not cite these samples as production proof.

## Contents

| Path | Purpose |
| --- | --- |
| `manifest.json` | Artifact index, git commit, verify commands |
| `sample-runs/01-approve/` | Policy APPROVE path |
| `sample-runs/02-reject/` | Technical PASS + forbidden path → REJECT |
| `sample-runs/03-escalate/` | Auth change → ESCALATE / AWAITING_HUMAN |
| `sample-runs/04-human-approve/` | M4 slice: AWAITING_HUMAN → `foundation-decide APPROVE` (no primary apply) |
| `.gitkeep` | Keeps directory in empty clones before generation |

Each sample run includes `summary.json`, `runs/<run_id>/state.json`, `events.jsonl`, and stage evidence blobs.

## Reproduce

From repository root:

```bash
pip install -e ".[dev]"
python scripts/generate_sample_evidence.py
```

Verify consistency:

```bash
ci-orchestrator foundation-verify sample-approve --artifacts evidence/sample-runs/01-approve
ci-orchestrator foundation-verify sample-reject --artifacts evidence/sample-runs/02-reject
ci-orchestrator foundation-verify sample-escalate --artifacts evidence/sample-runs/03-escalate
ci-orchestrator foundation-verify sample-human-approve --artifacts evidence/sample-runs/04-human-approve
```

Human decision loop (M4 slice) on an escalated run:

```bash
ci-orchestrator foundation-decide sample-escalate --action APPROVE --reviewer alice \
  --artifacts evidence/sample-runs/03-escalate
```

Golden suite (broader evaluation, not these samples):

```bash
ci-orchestrator foundation-benchmark --required-only --compare-baseline
```
