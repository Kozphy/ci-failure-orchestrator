# CI Failure Orchestrator

**v1.2 agentic CI reliability control plane** for dependency-aware diagnosis, bounded autonomous repair, multi-provider worker routing, candidate tournaments, persistent failure memory, independent evaluation, fleet policy, SLO/error-budget control, canary rollout, benchmarking, dashboard telemetry, human escalation, and tamper-evident production proof.

## 5-minute quick start

This is the shortest path from a fresh clone to a useful CI diagnosis.

```bash
git clone https://github.com/Kozphy/ci-failure-orchestrator.git
cd ci-failure-orchestrator
python -m venv .venv
```

Activate the environment and install the project:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

```bash
# macOS / Linux
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
```

Verify the installation:

```bash
ci-orchestrator --help
pytest
```

Now analyze the included GitHub Actions example:

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json \
  --audit audit.jsonl
```

On PowerShell, run the same command on one line:

```powershell
ci-orchestrator analyze --jobs examples/github_jobs.json --logs examples/github_logs.json --audit audit.jsonl
```

The result gives you four actionable outputs:

```text
failed CI evidence
       ↓
probable root cause
       ↓
ranked candidate causes
       ↓
causal dependency edges
       ↓
verification plan
```

Use the verification plan to decide which checks to run next. A diagnosis is not permission to merge: repair candidates must still pass the independent gates required by `REPAIR_SUCCESS`.

### What success looks like

For a real pull request, the intended operating model is:

```text
PR / commit
    ↓
GitHub Actions failure
    ↓
collect jobs + logs
    ↓
ci-orchestrator analyze
    ↓
root-cause hypothesis
    ↓
bounded repair candidate
    ↓
targeted tests
    ↓
full regression
    ↓
security + policy gates
    ↓
independent verification
    ↓
REPAIR_SUCCESS
    ↓
release gates
    ↓
RELEASE_READY
    ↓
canary + runtime evidence
    ↓
PRODUCTION_SUCCESS
```

The orchestrator therefore acts as a **CI reliability control plane**, not merely an AI code fixer. Diagnosis and repair generation are separated from verification and release authority.

## How to use

### 1. Clone and install

Requirements: **Python 3.10+**.

```bash
git clone https://github.com/Kozphy/ci-failure-orchestrator.git
cd ci-failure-orchestrator
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install the project and development dependencies:

```bash
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Optional integrations can be installed when needed:

```bash
pip install -e ".[openai]"
pip install -e ".[observability]"
```

After installation, the CLI is available as:

```bash
ci-orchestrator --help
```

### 2. Run the included demo

The repository includes sample pipeline, failure, GitHub Actions job, and log data under `examples/`.

```bash
bash demo.sh
```

On Windows, you can run the equivalent CLI commands shown below directly from PowerShell.

### 3. Classify a CI error

Use `classify` when you have a raw error message and want a normalized failure type plus confidence score.

```bash
ci-orchestrator classify "ModuleNotFoundError: No module named 'requests'"
```

This is useful as the first step before deciding which repair worker or verification path should handle a failure.

### 4. Rank probable root causes

Use `rank` when you already have a normalized pipeline graph and a set of failures.

```bash
ci-orchestrator rank \
  --pipeline examples/pipeline.json \
  --failures examples/failures.json
```

To also create a tamper-evident audit trail:

```bash
ci-orchestrator rank \
  --pipeline examples/pipeline.json \
  --failures examples/failures.json \
  --audit artifacts/audit.jsonl
```

The command ranks failures by probable root cause instead of assuming that the last red job is the real cause.

### 5. Analyze normalized GitHub Actions jobs and logs

Use `analyze` for an end-to-end diagnosis over normalized GitHub Actions job metadata and optional logs.

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json
```

With audit logging enabled:

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json \
  --audit artifacts/audit.jsonl
```

The analysis returns the most likely `root_cause`, ranked candidate causes, inferred causal edges, and a verification plan describing what should be checked next.

### 6. Run the test suite before making changes

```bash
pytest
```

For coverage:

```bash
pytest --cov=ci_failure_orchestrator --cov-report=term-missing
```

A local green test run is useful, but it is **not** equivalent to this project's `REPAIR_SUCCESS`, `RELEASE_READY`, or `PRODUCTION_SUCCESS` gates. Those require the independent checks defined below.

### 7. Typical workflow

```text
CI fails
   ↓
Collect / normalize failed jobs and logs
   ↓
ci-orchestrator analyze
   ↓
Rank probable root cause
   ↓
Generate or select a bounded repair candidate
   ↓
Run targeted tests
   ↓
Run full regression + security + policy gates
   ↓
REPAIR_SUCCESS
   ↓
Release-readiness gates
   ↓
RELEASE_READY
   ↓
Canary + SLO + observability checks
   ↓
PRODUCTION_SUCCESS
```

For a quick local diagnosis, start with:

```bash
ci-orchestrator analyze --jobs examples/github_jobs.json --logs examples/github_logs.json
```

For production-oriented use, feed the orchestrator normalized evidence from your actual CI environment and keep repair generation separate from independent verification and release approval.

## Canonical success gates

The control plane uses three layered fail-closed predicates. A later stage can never report success unless every required condition in the previous stage is already satisfied.

```text
REPAIR_SUCCESS =
CI_GREEN
AND TARGETED_TESTS_PASS
AND FULL_REGRESSION_PASS
AND SECURITY_GATE_PASS
AND POLICY_GATE_PASS
AND NO_TEST_WEAKENING
AND NO_REGRESSION

RELEASE_READY =
REPAIR_SUCCESS
AND ARTIFACT_INTEGRITY_PASS
AND DEPENDENCY_GATE_PASS
AND DEPLOYMENT_VALIDATION_PASS
AND REQUIRED_APPROVALS_PASS
AND ROLLBACK_READY

PRODUCTION_SUCCESS =
RELEASE_READY
AND CANARY_HEALTHY
AND SLO_PASS
AND ERROR_BUDGET_OK
AND OBSERVABILITY_HEALTHY
AND NO_PRODUCTION_REGRESSION
```

These definitions are implemented as canonical code predicates. Agent self-report is never sufficient for success. Telemetry, benchmarks, release promotion, and production proof should consume these verified outcomes rather than inventing separate success definitions.

## Control-plane flow

```text
GitHub repositories
        ↓
Workflow runs / jobs / logs
        ↓
Failure Dependency Graph
        ↓
Root-cause classification + ranking
        ↓
Failure Memory Agent + SQLiteIncidentStore
        ↓
Memory-Aware Repair Planner
        ↓
SupervisorPolicy
        ↓
AgentTask contract
        ↓
Agent Router
 ├─ Copilot / coding agent
 ├─ OpenAI worker
 └─ local/custom worker
        ↓
Bounded Agent Executor
        ↓
Isolated Git Worktree / Sandbox
        ↓
Candidate patches
        ↓
Independent gates
 ├─ targeted tests
 ├─ full regression
 ├─ security
 └─ policy
        ↓
Candidate Tournament
        ↓
Best safe candidate
        ↓
Repair State Machine
        ↓
REPAIR_SUCCESS
        ↓
Artifact / dependency / deployment / approval / rollback gates
        ↓
RELEASE_READY
        ↓
Canary / SLO / error budget / observability / production regression gates
        ↓
PRODUCTION_SUCCESS
        ↓
Production proof
```

## Operational evidence maturity

The repository distinguishes implementation from proof:

```text
DESIGNED_CAPABILITY
      ↓
SIMULATED_VALIDATION
      ↓
MEASURED_STAGING_EVIDENCE
      ↓
MEASURED_PRODUCTION_EVIDENCE
      ↓
CONTROLLED_FAILURE_AND_RECOVERY_PROOF
```

Example, fixture, synthetic, simulated, or mock metrics must never be promoted as measured production proof. The measured-production evidence gate requires provenance-bearing runtime evidence including a deployment ID, commit SHA, immutable artifact digest, telemetry source, canary health, observability health, rollback readiness, and regression status.

DORA-style operational metrics are computed from deployment history rather than declared manually:

```text
DELIVERY_HEALTH =
DEPLOYMENT_FREQUENCY_MEASURED
AND LEAD_TIME_MEASURED
AND CHANGE_FAIL_RATE_MEASURED
AND RECOVERY_TIME_MEASURED_WHEN_FAILURES_EXIST
AND ROLLBACK_RATE_MEASURED
```

A repository-level production claim is intentionally stricter:

```text
LEVEL6_OPERATIONAL_PROOF =
MEASURED_PRODUCTION_EVIDENCE
AND IMMUTABLE_ARTIFACT_PROVENANCE
AND CANARY_RESULT_RECORDED
AND SLO_EVALUATED_FROM_RUNTIME_TELEMETRY
AND ROLLBACK_READY
AND FAILURE_RECOVERY_EXERCISED
AND RECOVERY_TIME_RECORDED
AND EVIDENCE_TAMPER_EVIDENT
```

Until those conditions are backed by real runtime measurements, the project describes the controls as implemented or validated rather than production-proven at scale. See `docs/operational-evidence.md`.

## Safety principle

Repair workers may propose changes, but they cannot approve their own release. Evaluation, regression checks, repository policy, release-readiness gates, production-health gates, canary health, fleet policy, SLOs, and human approval retain release authority.

Unsafe candidates can never win a provider tournament, and a green CI signal alone can never be promoted directly to release or production success.
