# Repository-wide analysis

`analyze-repo` inspects a GitHub repository directly without cloning it.

```bash
ci-orchestrator analyze-repo --repo Kozphy/ci-failure-orchestrator
```

For a private repository, set `GITHUB_TOKEN` or pass `--token`. To inspect a non-default branch or ref:

```bash
ci-orchestrator analyze-repo \
  --repo owner/repository \
  --ref feature/my-branch \
  --audit artifacts/repository-audit.jsonl
```

## Evidence model

The command deliberately uses bounded evidence collection:

```text
GitHub repository
       ↓
repository metadata
       ↓
recursive Git tree inventory
       ↓
high-signal evidence files
 ├─ GitHub Actions workflows
 ├─ dependency/build manifests
 ├─ README / SECURITY
 ├─ CODEOWNERS
 ├─ Dependabot
 └─ pre-commit configuration
       ↓
deterministic repository policy
       ↓
findings + recommendations
       ↓
REPO_HEALTHY / NEEDS_ACTION
```

The recursive tree is used for file inventory; source files are not bulk-downloaded. This keeps the scan bounded and auditable. If GitHub reports the tree as truncated, the analyzer fails closed with `TREE_TRUNCATED` instead of claiming the repository was fully inspected.

## Current controls

The first repository policy checks for:

- at least one CI workflow;
- conventional automated tests;
- a recognized build/dependency manifest;
- README documentation;
- `SECURITY.md`;
- `CODEOWNERS`;
- Dependabot configuration;
- pre-commit configuration.

High and medium findings produce `NEEDS_ACTION`. The CLI exits with status `2` for `NEEDS_ACTION`, making the command usable as a future CI policy gate. A clean result exits with status `0` and reports `REPO_HEALTHY`.

## Scope and limitations

This is repository **control-health analysis**, not yet semantic review of every source file. The next layers should add PR-aware changed-code analysis, workflow semantic checks, dependency vulnerability evidence, static-analysis provider aggregation, and historical CI reliability metrics. These should remain separate evidence providers feeding the same policy engine rather than weakening the bounded repository collector.
