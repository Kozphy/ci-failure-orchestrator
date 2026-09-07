# Level 7: Ecosystem Roadmap

The project does not claim Level 7 today. Level 7 is an adoption outcome, not a code-completeness label.

## North star

Make CI failure intelligence, repair evaluation, and production evidence portable across CI providers and coding agents.

## L4 — usable open-source product

Exit criteria:
- real GitHub Actions adapter and isolated patch/worktree executor
- affected-test selection and rollback
- one-command local demo
- versioned releases and migration policy
- OpenTelemetry traces/metrics
- security threat model and least-privilege execution
- production SLOs and documented recovery procedures

## L5 — reproducible research/benchmark platform

Exit criteria:
- public, replayable CI failure corpus
- deterministic and agentic baselines
- protocol-versioned benchmark runner
- root-cause accuracy, repair success, false-repair, regression, escalation, retry, cost and latency metrics
- repeated runs, confidence intervals and failure taxonomy
- reproducibility package and technical report

## L6 — shared infrastructure

Exit criteria:
- GitHub Actions plus at least two additional CI provider adapters
- multiple repair-agent adapters
- stable Python/HTTP interfaces
- external integrations and contributors
- downstream projects depending on the protocol or evaluator
- public compatibility matrix

## L7 — ecosystem / de facto standard

Evidence required:
- independent organizations adopt the failure/evidence protocol or benchmark
- independent benchmark submissions and reproductions
- multiple external maintainers or governance participants
- protocol evolution via public RFCs
- compatibility/conformance tests used outside this repository
- citations, integrations, or production deployments that demonstrate ecosystem dependence

## Protocol boundary

Provider -> FailureEnvelope -> Orchestrator -> RepairEnvelope -> Evaluator -> EvaluationEnvelope -> Policy -> EvidenceEnvelope

No provider or model vendor owns the core schema. Agents propose; independent evaluation and policy decide.

## Non-goals

- claiming autonomy without bounded budgets and rollback
- allowing an agent to approve its own release
- optimizing benchmark scores at the expense of regression safety
- calling repository size, star count, or architecture diagrams Level 7 evidence
