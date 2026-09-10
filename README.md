# CI Failure Orchestrator

**v1.2 agentic CI reliability control plane** for dependency-aware diagnosis, bounded autonomous repair, multi-provider worker routing, candidate tournaments, persistent failure memory, independent evaluation, fleet policy, SLO/error-budget control, canary rollout, benchmarking, dashboard telemetry, human escalation, and tamper-evident production proof.

## Repository engineering intelligence

Direct repository analysis is available with:

```bash
ci-orchestrator analyze-repo --repo Kozphy/ci-failure-orchestrator
```

The command produces deterministic repository engineering evidence:

```text
Repository inventory
       ↓
Control-health checks
       ↓
Architecture / component graph
       ↓
Workflow semantic signals
       ↓
Dependency evidence
       ↓
Transparent risk score
       ↓
REPO_HEALTHY / NEEDS_ACTION
```

`engineering_intelligence` includes structural component and language counts, convention-based test-to-source mappings, GitHub Actions quality/security signals, dependency inventory, and a transparent 0-100 repository risk score with explicit penalty records.

Structural test mapping is not runtime code coverage, dependency inventory is not vulnerability scanning, and repository health is not production proof. See `docs/analyze-repo.md` for the evidence model and limitations.

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

Analyze the repository directly:

```bash
ci-orchestrator analyze-repo --repo Kozphy/ci-failure-orchestrator
```

Analyze the included GitHub Actions example:

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json \
  --audit audit.jsonl
```

Analyze a live workflow run:

```bash
ci-orchestrator analyze-run --repo Kozphy/ci-failure-orchestrator --run-id <RUN_ID>
```

The result gives you actionable diagnosis and repository-risk evidence. A diagnosis is not permission to merge: repair candidates must still pass the independent gates required by `REPAIR_SUCCESS`.

### What success looks like

```text
Repository / PR / commit
    ↓
repository engineering intelligence
    ↓
GitHub Actions failure
    ↓
analyze-run
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

The orchestrator therefore acts as a **CI reliability and repository engineering control plane**, not merely an AI code fixer. Diagnosis and repair generation are separated from verification and release authority.

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

```bash
bash demo.sh
```

### 3. Classify a CI error

```bash
ci-orchestrator classify "ModuleNotFoundError: No module named 'requests'"
```

### 4. Rank probable root causes

```bash
ci-orchestrator rank \
  --pipeline examples/pipeline.json \
  --failures examples/failures.json
```

### 5. Analyze normalized GitHub Actions jobs and logs

```bash
ci-orchestrator analyze \
  --jobs examples/github_jobs.json \
  --logs examples/github_logs.json
```

### 6. Analyze a live GitHub Actions workflow run

```bash
ci-orchestrator analyze-run --repo owner/repository --run-id <RUN_ID>
```

### 7. Analyze a GitHub repository directly

```bash
ci-orchestrator analyze-repo --repo owner/repository
```

To analyze another ref:

```bash
ci-orchestrator analyze-repo --repo owner/repository --ref feature/branch
```

The command exits `0` for `REPO_HEALTHY` and `2` for `NEEDS_ACTION`, allowing it to be used as a fail-closed policy gate.

### 8. Run the test suite before making changes

```bash
pytest
```

For coverage:

```bash
pytest --cov=ci_failure_orchestrator --cov-report=term-missing
```

A local green test run is useful, but it is **not** equivalent to this project's `REPAIR_SUCCESS`, `RELEASE_READY`, or `PRODUCTION_SUCCESS` gates.

## Canonical success gates

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

Agent self-report is never sufficient for success. Telemetry, benchmarks, release promotion, and production proof consume verified outcomes rather than inventing separate success definitions.

## Control-plane flow

```text
GitHub repositories
        ↓
Repository engineering intelligence
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

Example, fixture, synthetic, simulated, or mock metrics must never be promoted as measured production proof.

```text
DELIVERY_HEALTH =
DEPLOYMENT_FREQUENCY_MEASURED
AND LEAD_TIME_MEASURED
AND CHANGE_FAIL_RATE_MEASURED
AND RECOVERY_TIME_MEASURED_WHEN_FAILURES_EXIST
AND ROLLBACK_RATE_MEASURED
```

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
