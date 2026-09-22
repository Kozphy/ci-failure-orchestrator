# CI Failure Orchestrator

**Deterministic, policy-gated CI failure control plane** — classify → plan → sandbox → evaluate → retry budget → policy → escalate → durable audit → synthetic evaluation.

Maturity: **M3 (Evaluated System)** with an **M4 human-decision slice**. See [docs/repository-audit.md](docs/repository-audit.md).

## Why this exists

CI auto-repair is unsafe if technical “green” silently becomes permission to change code, workflows, or auth. This repository investigates whether an **explicit control plane** can separate:

```text
technical evaluation  ≠  policy approval  ≠  primary workspace mutation
```

Default foundation paths use **scripted/heuristic proposals** and **local sandbox simulation**. They are not a production multi-provider coding agent.

## What this is / is not

| Is | Is not |
| --- | --- |
| Tested foundation orchestrator (Phases 2–13) | Live LLM auto-repair in production |
| Fail-closed policy + finite retry + escalation packages | Proof that APPROVE applies patches to your main tree |
| Golden synthetic benchmarks + baseline CI gate | Measured fleet SLOs / E5 production evidence |
| Local durable run artifacts + sample evidence | Cryptographic tamper-proof foundation audit |
| Adjacent diagnosis / trust / release-predicate libraries | One unified ingest→PRODUCTION_SUCCESS product CLI |

## System model (canonical: foundation)

```text
FailureEvent
  → context (sanitized)
  → classify → plan → tools → proposal
  → sandbox (temp copy; stub/schedule verification allowed)
  → evaluate (fail-closed without target verification)
  → retry budget (finite; fingerprint / no-progress stops)
  → policy gate (APPROVE | REJECT | ESCALATE; default ≠ APPROVE)
  → escalate package (local artifacts; no auto-decide)
  → durable state + append-oriented audit (when artifacts_root set)
  → metrics / SLI / SLO rebuild (observability never authorizes)
```

**Policy APPROVE does not apply the patch to the primary workspace.**

Parallel stacks (governed, trust gateway, diagnosis, release predicates) exist as **adjacent libraries**. Portfolio claims should center on `ci_failure_orchestrator/foundation/`. See [docs/control-authority-map.md](docs/control-authority-map.md).

## Evidence

Committed sample runs (synthetic, E4-simulated — **not E5**):

| Sample | Outcome | Verify |
| --- | --- | --- |
| `evidence/sample-runs/01-approve` | APPROVE | `ci-orchestrator foundation-verify sample-approve --artifacts evidence/sample-runs/01-approve` |
| `evidence/sample-runs/02-reject` | REJECT | `ci-orchestrator foundation-verify sample-reject --artifacts evidence/sample-runs/02-reject` |
| `evidence/sample-runs/03-escalate` | ESCALATE → AWAITING_HUMAN | `ci-orchestrator foundation-verify sample-escalate --artifacts evidence/sample-runs/03-escalate` |
| `evidence/sample-runs/04-human-approve` | ESCALATE → human APPROVE (no primary apply) | `ci-orchestrator foundation-verify sample-human-approve --artifacts evidence/sample-runs/04-human-approve` |

Manifest: [evidence/manifest.json](evidence/manifest.json) · How-to: [evidence/README.md](evidence/README.md)

Regenerate:

```bash
python scripts/generate_sample_evidence.py
```

## Quick start

Requirements: **Python 3.10+**.

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
ci-orchestrator --help
```

### Foundation (recommended demo)

```bash
ci-orchestrator foundation-run \
  --fixture benchmarks/cases/01_unit_test_failure.json \
  --artifacts artifacts

ci-orchestrator foundation-benchmark --required-only --compare-baseline
```

### Diagnosis (example fixtures)

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json
```

### Governed simulation (dry-run character)

```bash
ci-orchestrator run --fixture benchmarks/cases/01_unit_test_failure.json
ci-orchestrator benchmark --cases benchmarks/cases
```

## Reproduce evaluation

```bash
pytest tests/test_foundation_phases_2_6.py \
  tests/test_foundation_phase_7_retry.py \
  tests/test_foundation_phase_8_policy.py \
  tests/test_foundation_phase_9_escalation.py \
  tests/test_foundation_phase_10_persistence.py \
  tests/test_foundation_phase_12_benchmark.py \
  tests/test_foundation_phase_13_observability.py -q

ci-orchestrator foundation-benchmark --required-only --compare-baseline
```

Synthetic benchmarks demonstrate governance behavior. Targets in `config/slo.json` are **EXAMPLE_TARGET / provisional**, not production SLOs.

## Engineering invariants (foundation)

1. Illegal state transitions raise.
2. Retry budget is finite; identical proposal / no-progress / security boundary stop retries.
3. Policy default cannot be APPROVE; engine errors → ESCALATE.
4. Evaluation PASS is technical only; policy is a separate decision.
5. Observability metrics never authorize orchestration decisions.
6. Escalation builds a review package and stops; it does not auto-approve.
7. Human `foundation-decide APPROVE` records durable approval but **still does not** mutate the primary workspace.

## Reliability & governance (honest scope)

- **Reliability model:** finite retries + fail-closed evaluation + local audit reconstruction.
- **Governance controls:** path/category policy rules, forbidden-path reject, auth/CI escalation, human package for ESCALATE.
- **Residual risk:** stubbed sandbox verification, scripted proposals, no reviewer notification channel, no E5 production proof.

## Documentation map

| Doc | Purpose |
| --- | --- |
| [docs/repository-audit.md](docs/repository-audit.md) | Implementation truth, maturity, credibility gaps |
| [docs/control-authority-map.md](docs/control-authority-map.md) | Which stack owns policy, execution, audit, success terms |
| [docs/architecture/current-state.md](docs/architecture/current-state.md) | What exists today |
| [docs/architecture/agent-execution-foundation.md](docs/architecture/agent-execution-foundation.md) | Foundation design |
| [docs/adr/](docs/adr/) | ADRs 0001–0007 |
| [docs/operations/sli-slo.md](docs/operations/sli-slo.md) | Provisional SLI/SLO |
| [docs/security/threat-model.md](docs/security/threat-model.md) | Threat model |

Adjacent / aspirational modules (tournaments, fleet, canary, REPAIR/RELEASE/PRODUCTION predicates, hash-chained `audit.py`) are documented under deeper `docs/` paths. Treat them as **library capabilities**, not the default executable product path, unless you compose them yourself.

## Limitations

- Default proposals are heuristic or scripted — not live multi-provider repair.
- Sandbox may use scheduled/stub target verification in benches.
- Human escalation is a **local artifact package** plus optional `foundation-decide`; not a notification/approval workflow channel.
- Foundation durable audit is **append-oriented**, not cryptographically tamper-proof.
- No production deployment evidence in this repository.

## Research question (working)

Does policy-gated orchestration with a finite retry budget reduce unsafe auto-approvals relative to an ungated / unlimited-retry baseline on the golden synthetic failure suite?

## License / package

Python package `ci-failure-orchestrator` · CLI entrypoint `ci-orchestrator` · version in `pyproject.toml`.
