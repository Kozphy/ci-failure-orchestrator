# Research-Grade Upgrade Roadmap

This document defines the evidence required to evolve CI Failure Orchestrator from a strong engineering portfolio project into a reproducible research artifact suitable for research-oriented graduate applications and external review.

> This roadmap does not claim or guarantee admission to MIT, Cambridge, Oxford, or any other institution. It defines project-level research evidence only.

## Research thesis

**Theme:** Reliable autonomous diagnosis and repair of CI failures under independent verification.

### Research questions

- **RQ1 — Diagnosis:** Does dependency-aware failure analysis improve root-cause identification over log-only and rule-based baselines?
- **RQ2 — Memory:** Does persistent failure memory improve repair success and reduce repeated unsuccessful repair attempts?
- **RQ3 — Verification:** Does independent verification reduce unsafe or regression-inducing AI repairs?
- **RQ4 — Efficiency:** What reliability, latency, and cost trade-offs arise from single-agent versus multi-agent repair?

## Research-ready predicate

```text
RESEARCH_READY =
RQ_DEFINED
AND PRIOR_ART_REVIEWED
AND NOVELTY_JUSTIFIED
AND BENCHMARK_PUBLIC
AND DATA_PROVENANCE_COMPLETE
AND STRONG_BASELINES_IMPLEMENTED
AND EXPERIMENTS_REPRODUCIBLE
AND STATISTICAL_VALIDATION_COMPLETE
AND ABLATIONS_COMPLETE
AND FAILURE_ANALYSIS_COMPLETE
AND LIMITATIONS_DOCUMENTED
AND MANUSCRIPT_COMPLETE
AND INDEPENDENT_REPRODUCTION_RECORDED
```

`RESEARCH_READY` is fail-closed. Architecture diagrams, implementation claims, synthetic examples, or agent self-reports do not satisfy evidence gates by themselves.

## Benchmark design

Create a versioned benchmark of real or provenance-traceable CI failures. Start with 200–500 carefully validated cases before optimizing for dataset size.

Recommended taxonomy:

```text
CI_FAILURE
├── dependency
├── compilation / syntax
├── lint / formatting
├── unit test
├── integration test
├── configuration
├── security / policy
├── flaky / nondeterministic
├── timeout / resource
└── cross-job dependency
```

Each benchmark case should record:

- repository and commit identifier
- workflow/run metadata
- failed job/step
- bounded failure-log evidence
- normalized failure category
- independently validated root cause
- expected repair or repair constraints where available
- affected tests
- verification requirements
- provenance/license metadata

Do not mix training examples and final evaluation cases without an explicit split and contamination analysis.

## Baselines

The proposed system must be compared against meaningful alternatives rather than only against previous versions of itself.

```text
B0  Rule / keyword classifier
B1  LLM + raw failure log
B2  LLM + repository context
B3  Dependency graph without memory
B4  Dependency graph + LLM
P   Dependency graph + memory + bounded agent + independent verification
```

Pin model/provider/version, prompts, decoding parameters, context policy, retry budget, and tool permissions for every experiment.

## Primary metrics

### Diagnosis

- root-cause top-1 accuracy
- top-k accuracy
- precision / recall / F1 by failure class
- calibration where probabilistic confidence is exposed

### Repair

- repair success rate
- first-attempt repair success
- attempts to successful repair
- false-repair rate
- regression rate
- test-weakening rate

### Operations

- time to diagnosis
- time to verified repair
- token/API cost
- agent invocations
- latency
- escalation rate

### Safety

- unsafe candidate rejection rate
- policy violation rate
- security-gate failure rate
- verifier false-accept / false-reject rate where ground truth permits measurement

## Experimental protocol

Every benchmark run must emit an immutable experiment manifest containing at least:

```text
experiment_id
benchmark_version
benchmark_split
repo_commit_sha
orchestrator_version
baseline_or_method
model_and_provider
prompt_version
configuration_digest
random_seed
runtime_environment
started_at
finished_at
raw_result_digest
```

Recommended workflow:

```text
Benchmark
   ↓
Frozen split
   ↓
Baselines + proposed method
   ↓
Raw immutable results
   ↓
Deterministic metric computation
   ↓
Statistical analysis
   ↓
Ablation
   ↓
Failure analysis
   ↓
Figures / tables
   ↓
Manuscript
```

## Statistical validation

Report uncertainty rather than only point estimates.

Minimum target:

- 95% confidence intervals for primary metrics
- paired comparisons where methods run on the same benchmark cases
- effect sizes in addition to p-values
- multiple-comparison correction when many hypotheses are tested
- explicit treatment of failed/missing runs
- repeated trials for stochastic methods

Choose statistical tests according to the metric and experimental design; do not hard-code one test for every comparison.

## Ablation study

At minimum evaluate:

```text
FULL
-GRAPH
-MEMORY
-INDEPENDENT_VERIFICATION
-CANDIDATE_TOURNAMENT
-SUPERVISOR_POLICY
-SINGLE_AGENT / MULTI_AGENT comparison
```

The goal is to establish which components produce measurable benefit, which mainly increase cost, and which primarily improve safety.

## Failure analysis

Maintain a public failure taxonomy such as:

```text
RESEARCH_FAILURE
├── incorrect diagnosis
├── insufficient evidence
├── hallucinated dependency
├── invalid patch
├── test weakening
├── hidden regression
├── flaky verification
├── policy violation
├── security violation
├── budget exhaustion
└── verifier disagreement
```

Publish representative failures and aggregate rates. Negative results must not be removed merely because they weaken the headline result.

## Reproducibility contract

A clean environment should be able to execute a documented path equivalent to:

```bash
make setup
make benchmark
make baselines
make experiments
make analysis
make paper
```

Expected outputs:

```text
artifacts/research/
├── manifests/
├── raw/
├── processed/
├── tables/
├── figures/
├── statistics/
└── provenance/
```

The reproduction path must pin dependencies and record the exact Git commit and benchmark version.

## Independent evaluation

The component that generates a repair must not be the sole authority deciding whether that repair succeeded.

```text
Repair Agent
     ↓
Candidate Patch
     ↓
Independent Evaluator
├── targeted tests
├── full regression
├── security gate
├── policy gate
├── no-test-weakening check
└── benchmark scoring
     ↓
PASS / FAIL
```

EvalForge can be integrated as an evaluation layer, but deterministic repository tests and policy/security gates remain authoritative for claims they can directly verify.

## Manuscript structure

```text
Abstract
1. Introduction
2. Related Work
3. Research Questions and Hypotheses
4. Benchmark and Dataset
5. Method
6. Experimental Setup
7. Results
8. Statistical Analysis
9. Ablation Study
10. Failure Analysis
11. Discussion
12. Threats to Validity
13. Limitations and Ethics
14. Conclusion
```

Recommended repository structure:

```text
research/
├── questions.md
├── hypotheses.md
├── related-work.md
├── methodology.md
├── threats-to-validity.md
└── ethics.md

benchmark/
baselines/
experiments/
analysis/
paper/
reproduction/
```

## Evidence maturity

```text
RESEARCH_IDEA
    ↓
PROTOCOL_DEFINED
    ↓
BENCHMARK_VERSIONED
    ↓
BASELINES_REPRODUCED
    ↓
EXPERIMENTS_COMPLETED
    ↓
STATISTICALLY_VALIDATED
    ↓
ABLATIONS_COMPLETED
    ↓
FAILURES_ANALYZED
    ↓
MANUSCRIPT_COMPLETE
    ↓
INDEPENDENTLY_REPRODUCED
```

No later state may be claimed unless the evidence for every earlier state is available and traceable.

## Application boundary

Project research readiness is only one component of graduate admissions readiness.

```text
APPLICATION_READY =
RESEARCH_READY
AND ACADEMIC_REQUIREMENTS_MET
AND STRONG_REFERENCES
AND FACULTY_AND_PROGRAM_FIT
AND STRONG_STATEMENT_OF_PURPOSE
AND PROGRAM_SPECIFIC_RESEARCH_PROPOSAL_WHERE_REQUIRED
```

The repository can provide evidence for `RESEARCH_READY`. It cannot by itself establish academic eligibility, recommendation quality, faculty fit, or admission probability.

## Recommended implementation order

1. Freeze RQ1–RQ4 and hypotheses.
2. Add `benchmark/` schema and provenance rules.
3. Build B0–B4 baseline runners.
4. Add experiment manifests and immutable raw-result storage.
5. Add deterministic metric computation.
6. Add confidence intervals and paired statistical comparisons.
7. Implement ablation runner.
8. Add failure taxonomy and failure-analysis report generator.
9. Integrate independent evaluation / EvalForge where appropriate.
10. Produce a reproducible paper-style report.
11. Ask an external person to reproduce at least one benchmark result and record the reproduction evidence.

The highest-priority milestone is not another architecture feature. It is a small, versioned benchmark plus reproducible baseline experiment that can falsify or support RQ1.
