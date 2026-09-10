# Live GitHub Actions run analysis

`ci-orchestrator analyze-run` collects a workflow run directly from the GitHub REST API and sends the evidence through the same root-cause ranking, causal analysis, and verification planning pipeline used by local JSON analysis.

## Authentication

For public repositories, unauthenticated requests may work but are rate-limited. For private repositories or normal CI usage, provide a token through `GITHUB_TOKEN` rather than placing it in shell history.

### PowerShell

```powershell
$env:GITHUB_TOKEN = "<token>"
ci-orchestrator analyze-run --repo OWNER/REPO --run-id RUN_ID --audit artifacts/audit.jsonl
```

### macOS / Linux

```bash
export GITHUB_TOKEN="<token>"
ci-orchestrator analyze-run --repo OWNER/REPO --run-id RUN_ID --audit artifacts/audit.jsonl
```

The client is read-only. It requests the latest-attempt jobs for the run and downloads logs only for failed, timed-out, cancelled, or action-required jobs.

## Example

```bash
ci-orchestrator analyze-run \
  --repo Kozphy/ci-failure-orchestrator \
  --run-id 123456789 \
  --audit artifacts/run-123456789.jsonl
```

Use `--no-logs` when job metadata is sufficient or log access is unavailable:

```bash
ci-orchestrator analyze-run --repo OWNER/REPO --run-id RUN_ID --no-logs
```

For GitHub Enterprise-compatible endpoints, override the API base URL:

```bash
ci-orchestrator analyze-run \
  --repo OWNER/REPO \
  --run-id RUN_ID \
  --api-url https://github.example.com/api/v3
```

## Output

The command emits JSON containing:

- `root_cause`
- ranked failure candidates
- inferred causal edges
- a verification plan

When `--audit` is set, the result is appended to the hash-chained audit log as `github_workflow_run_analyzed`.

## Trust boundary

Live ingestion changes the source of evidence, not the success policy. A diagnosis does not grant merge or deployment authority. Repair candidates must still satisfy the repository's independent `REPAIR_SUCCESS`, `RELEASE_READY`, and `PRODUCTION_SUCCESS` gates.

The current collector reads up to 100 jobs from the latest workflow-run attempt. Pagination and workflow-YAML enrichment of job dependencies are future extensions; the GitHub jobs REST response itself does not expose the workflow `needs` graph.
