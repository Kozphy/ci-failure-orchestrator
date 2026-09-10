# Repository-wide analysis

`analyze-repo` inspects a GitHub repository directly without requiring a workflow run ID.

```bash
ci-orchestrator analyze-repo --repo owner/repo
```

For private repositories, provide a token explicitly or through `GITHUB_TOKEN`.

```bash
export GITHUB_TOKEN=...
ci-orchestrator analyze-repo --repo owner/repo
```

The command remains read-only. It uses the GitHub REST API to retrieve repository metadata, a recursive Git tree, and a bounded set of high-signal files such as CI workflows, build manifests, dependency manifests, README, SECURITY.md, CODEOWNERS, Dependabot, and pre-commit configuration.

## Engineering-intelligence output

The result now contains four deterministic analysis layers:

```text
Repository
   ↓
Inventory + controls
   ↓
Architecture / component graph
   ↓
Workflow semantic signals
   ↓
Dependency evidence
   ↓
Transparent risk scoring
   ↓
REPO_HEALTHY / NEEDS_ACTION
```

### Architecture graph

The analyzer classifies source and test files from the repository tree, groups them into structural components, records detected implementation languages, and creates convention-based links between tests and likely source counterparts.

This is a structural graph, not an LLM-generated architecture claim. A `test_service.py` file may be associated with a `service.py` source candidate, but this does not claim runtime coverage or semantic correctness.

### Workflow semantics

Fetched GitHub Actions workflows are inspected for deterministic signals including:

- pull-request and push triggers
- scheduled execution
- recognized test commands
- recognized static-analysis commands
- recognized security scanners
- coverage tooling
- artifact upload steps

Absence means the signal was not detected in the bounded evidence; it does not prove that an equivalent control exists nowhere outside GitHub Actions.

### Dependency evidence

The analyzer extracts dependency names from supported fetched manifests such as `pyproject.toml`, `requirements.txt`, and `package.json`. This is dependency inventory evidence, not a vulnerability scan. Vulnerability status should come from a dedicated advisory or scanner integration.

### Repository risk score

The `engineering_intelligence.risk` section exposes a transparent 0-100 score. Every point is backed by an explicit penalty record with a code and reason.

```text
0-20   LOW
21-45  MODERATE
46-70  HIGH
71-100 CRITICAL
```

Examples of weighted penalties include missing CI, missing tests, incomplete/truncated evidence, CI workflows without detected tests, security or static-analysis signals, and weak convention-based test mapping.

The score is deliberately inspectable rather than model-generated. It is suitable for policy evaluation but should not be treated as a substitute for runtime SLOs, security scanning, code coverage, or production evidence.

## Exit codes

```text
0  REPO_HEALTHY
2  NEEDS_ACTION
```

`REPO_HEALTHY` currently requires no high/medium repository-control findings and a risk score of 20 or below. This makes the command usable as a fail-closed policy gate.

## Evidence completeness

GitHub's recursive tree response can be truncated for very large repositories. When that occurs, the analyzer emits `TREE_TRUNCATED`, applies an incomplete-evidence risk penalty, and refuses to report the repository as healthy.

GitHub documents that recursive tree responses can be truncated and recommends subtree retrieval for complete traversal of very large repositories. This implementation therefore treats truncation as incomplete evidence rather than silently assuming completeness.

The next maturity layers are intentionally separate:

```text
Repository structural intelligence
        ↓
PR semantic analysis
        ↓
static-analysis aggregation
        ↓
dependency vulnerability evidence
        ↓
historical CI reliability metrics
        ↓
runtime / production evidence
```

This separation prevents structural repository heuristics from being misrepresented as production proof.
