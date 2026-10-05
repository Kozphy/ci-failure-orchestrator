# Changelog

All notable changes to this repository. Service release plan and stage definitions: [docs/service-v0.1-plan.md](docs/service-v0.1-plan.md).

Versioning (plan §5.4) uses two tracks: the Python package keeps semantic versions in `pyproject.toml` (currently `1.2.0`); the CI failure service is released with `service-v0.x.y` tags, starting at `service-v0.1.0`. Entries below are unreleased.

## [Unreleased]

### A green CI run is no longer treated as a correct fix

- Every `fix-repo` run now ends with a `remediation_state` (outcome fields `remediation_state` and `remediation`). The existing `outcome` and workflow states are unchanged. One deterministic function, `foundation/remediation.py: decide_remediation`, makes the decision. Only `is_verified_fix` can return `VERIFIED_FIXED`, and only when every piece of evidence is present and passing. Evidence that was not collected counts as missing, never as a pass.
- New final states:
  - `POLICY_REJECTED`: verification was weakened, the target test went missing, the test count dropped or skips increased.
  - `NOT_FIXED`: the original failure is still there, or a different error replaced it.
  - `REGRESSION_DETECTED`: a test or gate that passed before the patch fails after it.
  - `HUMAN_REVIEW_REQUIRED`: HIGH-risk diff, policy escalation, or real CI failed.
  - `CI_GREEN_BUT_UNVERIFIED` and `POLICY_APPROVED` (awaiting real CI) cover partial evidence.
- Evidence collected in two disposable worktrees (base and patched; `service/verification.py`):
  - Reproduction: failure fingerprint, compared with the CI log when one is supplied.
  - Exact rerun of the originally failing pytest node IDs.
  - Affected tests mapped from the changed files.
  - Regression suite: test count, skips and coverage before vs after; new failures by node ID.
  - Lint, typecheck, security and build commands, plus behavioral invariants.
  - Diff risk score (`foundation/diff_risk.py`), combined with the policy risk level.
- Configuration:
  - `fix-repo --regression CMD` and `--verification-config FILE` (YAML; unknown keys are errors).
  - Only unconfigured gates can be waived, and each waiver needs a reason. The regression suite cannot be waived.
  - Commands come from the operator config, never from the patch.
- New commands:
  - `fix-repo-verify-ci` reads the real CI result for the applied commit through a `CIProvider` (GitHub Actions adapter) and re-runs the decision. It can request a rerun, but never merges.
  - `fix-repo-metrics` reports Verified Repair Rate as the primary metric, alongside CI Green Rate, False Repair Rate, Regression Rate, Policy Rejection Rate, Human Escalation Rate and mean time to verified repair.
- `fix-repo-apply` refuses runs decided as `POLICY_REJECTED`, `REGRESSION_DETECTED` or `NOT_FIXED`. Runs recorded before this change, which have no `remediation.json`, are still allowed.
- Audit: each decision appends `REPAIR_VERIFICATION_COMPLETED` with the run, the repair attempt, the result and its per-check status. Run consistency still verifies.
- Integrity: `TEST_FILE_RENAMED_OUT_OF_DISCOVERY` (REJECT) flags a test file renamed so that runners stop collecting it (for example `tests/test_calc.py` → `tests/calc_cases.py`).
- Sandbox: `WorktreePatchVerifier(stop_on_failure=False)` runs every command, so before/after gates are all measured.
- Evidence:
  - `tests/test_repair_verification.py` has 77 tests: the seven adversarial cases at decision level, partial outcomes, parsing of real pytest output, diff risk, config validation, the GitHub adapter against recorded response shapes, metrics and the CLI.
  - End-to-end `fix-repo` runs in real git worktrees cover:
    - skip, xfail and file-deletion cheats, all `POLICY_REJECTED`;
    - a real fix with regression, coverage, lint and invariant evidence, which stays `POLICY_APPROVED` until a fake CI provider reports success and then becomes `VERIFIED_FIXED`;
    - the same fix without a regression suite, which ends `CI_GREEN_BUT_UNVERIFIED`;
    - a hidden regression, which ends `REGRESSION_DETECTED` and is refused by apply;
    - an `auth.py` change, which ends `HUMAN_REVIEW_REQUIRED`.
  - Full suite: 747 passed. Benchmark compare: 26 `UNCHANGED_PASS`, 12 `NEW_CASE`; baseline not updated.
- Limits:
  - The GitHub Actions adapter is not verified against the live API, and GitHub has no generic test-results API, so per-test evidence comes from the local worktrees.
  - The exact rerun and test counts need pytest output. Other runners only get command-level gates.
  - When a CI log is supplied that cannot be compared with the local reproduction, the repair cannot become `VERIFIED_FIXED`.
  - Not detected: a production change that hard-codes a test's expected value (unless it checks for the test runner), and code that is no longer exercised.
  - Each run with verification adds two worktrees and the configured commands to `fix-repo` runtime.

### Reject repairs that make CI green by weakening verification

- New `foundation/verification_integrity.py`: deterministic, line-based analysis of the proposed diff. The policy engine runs it on every evaluation; it does not depend on an LLM.
- `POL-018-VERIFICATION-WEAKENED` (REJECT, checked right after forbidden paths). It fires when a patch does any of the following:
  - deletes test files or test cases
  - adds skip, xfail or `.only` markers, or deselects tests
  - removes assertions or weakens them (`== expected` → `is not None`, `toEqual` → `toBeDefined`, `x == x`)
  - forces the runner's exit status
  - lowers or removes a coverage threshold
  - removes a check command from CI, or deletes a CI file
  - lets a CI step fail (`continue-on-error`, `allow_failure`, `|| true`)
  - disables lint or type checks in configuration, or removes pre-commit hooks
  - edits CODEOWNERS or repository rulesets
  - silently swallows a broad exception in production code
  - has production code detect the test runner (`PYTEST_CURRENT_TEST`, `NODE_ENV === 'test'`)
- `POL-019-VERIFICATION-CHANGE-REVIEW` (ESCALATE, reason code `VERIFICATION_CHANGE`) for changes that are sometimes correct but need a person: an existing test assertion changed, an inline suppression added (`noqa`, `type: ignore`, `@ts-ignore`, `nosec`, ...), or production code branching on the CI environment.
- Policy decisions carry `policy_version` (`2026.10.1`), which is also written to `policy-decision.json`.
- Behaviour change: the `flaky-test` demo is now AWAITING_HUMAN (POL-019) instead of APPROVED, because its fix rewrites the test's assertion. `test_only_the_flaky_test_fix_is_approved` became `test_no_demo_fix_is_auto_approved`.
- Evidence:
  - `tests/test_verification_integrity.py` has 72 tests: 36 weakening patterns across Python, JS/TS, Go, Java and CI/config files, 6 review cases, and 11 legitimate repairs that must not be flagged.
  - It also includes an end-to-end `fix-repo` run in a real git worktree. On the previous gate, a provider that deleted the failing test got pytest green and the run was APPROVED (POL-005). It is now REJECTED (POL-018), while the real code fix is still APPROVED.
  - Full suite: 670 passed. Benchmark compare: 26 `UNCHANGED_PASS`, 12 `NEW_CASE`; baseline not updated.
- Limits:
  - Detection is per line and per file. A weakening hidden in a helper, split across files, or made by widening a numeric tolerance is not detected.
  - Hardcoding a test's expected value in production code is detected only when the code checks for the test runner.
  - A rejected patch ends the run; it is not yet fed back to the provider as a retry.

### Phase 1a: fix defects found in the current-state assessment

- Runner: a `PersistenceError` now sets `workflow_status` to `PERSISTENCE_ERROR`, so `persistence_ok` is false in metrics and in `metrics-summary.json`. Classification is fixed to the reported failure for the whole run. Previously a changed failure fingerprint triggered a second classification, which could move the incident into a lower-risk category.
- Policy: escalation-path hits get `POL-016-ESCALATION-PATH` instead of POL-003 security-sensitive, and infrastructure/migration files get `POL-017-INFRASTRUCTURE-OR-MIGRATION` instead of POL-003 or POL-010 broad scope. As a result, escalation packets no longer carry the privilege-boundary or broad-scope checklist for these files. Outcomes are unchanged. A restricted-tool branch that did nothing was removed.
- fix-repo: a provider that exits non-zero or times out yields no patch, even if it printed a diff. Before this change, such a diff was verified and could be approved.
- `PatchVerification.clean_after_apply` now means the verify commands left the worktree unchanged after the patch. Dead code removed from the benchmark's `escalation_accuracy` (value unchanged).
- Evidence: `tests/test_foundation_defect_regressions.py` (6 tests). Each failed on `2380771`, the commit before these fixes. For the two policy cases, the old engine returned POL-003 for `src/infra/settings.py` and `infra/main.tf`. Full suite 598 passed. Benchmark compare: 26 `UNCHANGED_PASS`, 12 `NEW_CASE`, no regressions; the baseline file was not updated. `docs/architecture/current-state.md` §7.1 records the status of each finding, including two that turned out not to be defects (substring path matching over-blocks rather than under-blocks; POL-001 is defense in depth).

### GitHub Action: diagnose failed runs in the job summary

- New `action.yml` (composite) at the repository root. Inputs: `run-id` (default: the run behind a `workflow_run` event), `repository`, `github-token` (default `github.token`), `python-version`. It sets up Python without changing the caller's environment (`update-environment: false`), installs the package from the action's own checkout into a virtual environment, and runs `python -m ci_failure_orchestrator.doctor.action`. Outputs: `failure-class` (`none` when no job failed) and `diagnosis-file`.
- `doctor/action.py` reads every input from environment variables, so no input value is interpolated into a shell script. It validates the repository and run ID before any API call, prints the report with workflow commands neutralized, appends it to `GITHUB_STEP_SUMMARY` in a code block whose fence the log text cannot close, and writes `diagnosis.json` under `RUNNER_TEMP`. Errors are one escaped `::error::` annotation without the token. Exit codes match `analyze`: 0, 2 usage, 3 GitHub error. `GITHUB_API_URL` is honored.
- `.github/workflows/ci-doctor.yml` runs the action on failed `ci` runs of this repository (and by `workflow_dispatch` with a run ID). Permissions are `actions: read` and `contents: read`; it checks out the default branch only, never the failed run's code.
- `service/untrusted.py`: the fence logic of `untrusted_block` is now the public `fenced()`, shared with the summary.
- `LICENSE` (MIT) added.
- Evidence: `tests/test_doctor_action.py` (7 tests: summary, outputs and diagnosis file; a run with no failures; a log line carrying `::add-mask::` and four backticks; malformed inputs rejected before any API call; an API error as one annotation without the token; no `${{ }}` inside any `run:` script of `action.yml`; the self-test workflow's trigger, permissions and checkout). Live check: the package installed from the repository path into a fresh virtual environment and the entry point run against this repository's failed `ci` run 35718565691 reported `lint_failure` with ruff's `I001` line, and wrote the summary, both outputs and `diagnosis.json`. Full suite 592 passed; benchmark 38/38 with the 26 baseline results unchanged. The workflow itself runs only once this change is on the default branch.

### `actions-doctor demo`: six offline failure scenarios, end to end

- New command `actions-doctor demo <scenario> | --all | --list [--workdir DIR]`. Scenarios (`doctor/scenarios.py`): dependency drift, flaky test, network failure, timeout, configuration error, environment mismatch. Each builds a one-commit git repository in the work directory (fixed author and date, `core.autocrlf=false`), diagnoses its saved CI log with the same code as `analyze`, writes the recorded fix as a unified diff (generated with `difflib`), and runs `fix-repo` with that patch and the engine's own failure record (`ci_audit.collect.failure_event_fields`, now shared with `classify_failure`). The report prints failure (job, step, log line, message) → diagnosis → proposal → verification → policy decision → key evidence files, a "next" line (approval only allows a draft PR), and whether the result matched the scenario's expected category, outcome and rules. Exit code 1 if any scenario does not match. No network, token or model; nothing is written outside the work directory, and `--workdir` must be empty.
- Every scenario is a real failure, not a canned result: its verify command fails at the base commit and passes with the fix, in a disposable worktree. Outcomes: dependency drift ESCALATE (POL-014, POL-007), flaky test APPROVED (POL-005, a test-only fix checked over 30 seeds), network failure AWAITING_HUMAN at reproduction with no patch evaluated (the repository blocks host name lookups the way the runner failed), timeout ESCALATE (POL-014; the unpatched suite hits a 5-second verify limit), configuration error ESCALATE (POL-006, configuration files are not auto-approved), environment mismatch ESCALATE (POL-014, POL-004).
- Policy classifier: timeouts without an explicit flaky marker are `timeout_failure`; new fallback classes behind the shared table (which experimental modules also use and which is unchanged) for host name resolution wording, `cannot import name … from …`, runtime version mismatches (`environment_failure`: pip's "requires a different Python", npm EBADENGINE, Java class version) and configuration errors. `timeout_failure` and `environment_failure` are added to POL-014's escalation list. A test reported both PASSED and FAILED in one log (pytest-repeat style `[2-3]` suffixes; different parameters do not count) is `flaky_failure`, with the test named in the evidence.
- Log handling: the failure message prefers the last bare Python exception line (unittest prints `ERROR: test_x (...)` above it) and recognizes pytest's collection-error summary (`ERROR tests/x.py - ImportError: …`); previously such a run was summarized as `1 error in 0.08s`. `analyze --log` accepts `--step`. Next-step text for timeout and environment failures, and flaky advice that says to make the test deterministic.
- `demo.sh` runs the new demo instead of the experimental `rank` command.
- Evidence: `tests/test_demo_scenarios.py` (28 tests: the six full runs, each saved log's category, patch hygiene, CLI guards including refusing a non-empty work directory, the repeat signal, both message rules) and `tests/test_classifier_failure_types.py` (15 tests). Benchmark: BENCH-CLASS-012..016 and BENCH-POLICY-007, 38/38 passing with the 26 baseline results unchanged; all six fail on the previous commit. Full suite 585 passed. The baseline file is not updated; that is left for review.

### Policy classifier: security scans escalate; linters quoting source are not environment failures

- Classifier (`foundation/classifier.py`): new category `security_scan_failure`, chosen before every other branch when the workflow, job or failing step names a scanner (gitleaks, trufflehog, CodeQL, trivy, bandit, semgrep, snyk, grype, secret scan) or the message or log reports findings ("leaks detected", "secrets detected", "N vulnerabilities found"). Clean-scan lines ("no leaks found", "No known vulnerabilities found", "0 vulnerabilities found") do not match. The `SECURITY_ERROR` message class, previously mapped to `configuration_failure`, now maps here too.
- Classifier: when the failing step's own name is a lint, format or type-check step, the message has no environment signal, and the environment pattern appears only in the log excerpt, the step category wins at confidence 0.7 (evidence `log=<class>:quoted_source`). Job names never trigger this; test steps never trigger this (a `ModuleNotFoundError` in pytest output stays `dependency_failure`), and a message with an environment signal or an empty message keeps the environment category.
- Policy (`foundation/policy.py`): `security_scan_failure` added to `escalation_failure_categories`, so POL-014 escalates it even when a patch passes verification.
- `ci_audit.collect` uses the classifier's scanner patterns instead of its own copy. The audit's report-only refinement stays for the case it still covers: a tool named only in the step's `Run` header, which the classifier does not see.
- Effect on real runs of this repository (`actions-doctor analyze`, before → after): gitleaks run 36405950411 went from engine `lint_failure`, policy preview ELIGIBLE, to `security_scan_failure`, ESCALATE (POL-014); ruff run 35718565691 went from `dependency_failure`, ESCALATE, to `lint_failure`, ELIGIBLE. The report and the policy engine now agree on both, so `analyze` no longer prints the "policy gate sees" line for them.
- Evidence: `tests/test_classifier_step_and_security.py` (14 tests: both fixes, four environment guards, six scanner shapes, clean-scan lines, and a passing patch for a gitleaks failure escalating under POL-014). Benchmark: six new cases, 32/32 passing, no change to the 26 existing results. Run against the code before this change, BENCH-CLASS-007, BENCH-CLASS-010 and BENCH-POLICY-006 fail (POLICY-006 uses an excerpt trimmed from the real gitleaks run, and the old code would have let its patch through); the three guard cases pass on both. Two existing tests updated to the agreeing categories. Full suite 542 passed. The baseline file is not updated; that is left for review.

### `actions-doctor analyze`: read-only diagnosis of one failed run or saved log

- New canonical package `doctor/` and console script `actions-doctor` (also `python -m ci_failure_orchestrator.doctor`). `analyze --url <run URL>`, `--repo owner/name --run ID [--attempt N] [--job NAME]`, or `--log FILE` (offline, no token). Output: failure class with a heuristic high / medium / low label (no percentages; rules are not calibrated), the evidence line number in the downloaded log, the failing command, affected jobs, failed jobs ranked by recognized cause then run order, a fixed next-step sentence per class, the re-run command, and a policy preview computed from the engine's own `PolicyConfig` (POL-014, POL-015). When the report category differs from the category the policy engine sees, both are shown. `--json` / `--out` write `actions-doctor.diagnosis.v1`. Exit codes: 0 diagnosis, 2 usage, 3 GitHub or input error. Nothing is written to a repository and no model is called.
- Shared log handling (`ci_audit.collect`, so the audit report improves too): when the only `##[error]` is the generic exit-code line, the message is the first explicit tool error (`ERROR:`, `error:`, `FAILED `, `: error:`, ruff/flake8 rule codes) instead of the last line mentioning "error" (which was pip's help URL or ruff's "Found 1 error."). Step refinement now uses the failing step and its `Run` header, falling back to the job name only when both are missing; a job named "tests" failing in `pip install` was reported as a test failure.
- `github_client.get_run`; `ci_audit.collect.job_record` and `log_lines` made public; audit failure records carry `policy_category` / `policy_confidence`.
- Evidence: `tests/test_doctor.py` (17 tests) and one new `test_ci_audit.py` test. Checked against three real failed runs of this repository: a ruff failure now cites `I001 [*] Import block is un-sorted…` at its log line with the full, un-truncated command (an earlier 200-character cap cut it); a gitleaks `uses:` step is no longer offered as a command to re-run. The runs also show the policy engine's own classifier calling the ruff failure `dependency_failure` (a quoted `import DependencyProvenanceEvaluator`) and the gitleaks failure `lint_failure`; the preview reports that rather than hiding it.

### CI Doctor productization: audit and product spec (docs only)

- [docs/productization-audit.md](docs/productization-audit.md): current state measured (165 modules; experimental code is 99 modules / 10.1k lines against 65 canonical / 13.2k), assets to keep, missing product layers, debt, UX problems, risks, and preserve / refactor / remove / do-not-touch lists, mapped onto service plan Stages 4–9. Flags that `ci-doctor` is already taken on PyPI by a project with the same purpose (decision: brand "CI Doctor", package and command `actions-doctor`), that confidence is heuristic (fixed 0.9), and that POL-007 / POL-014 escalate dependency repairs by design.
- [docs/product-spec.md](docs/product-spec.md): `actions-doctor` CLI (`analyze`, `explain`, `propose`, `verify`, `repair`, `report` as thin wrappers over existing commands), Action-first GitHub integration with least-privilege jobs and label or `workflow_dispatch` approval (comments cannot hold buttons), and a dashboard concept with metric definitions. No code changed.

### CI reliability audit (read-only) and README positioning

- `ci_audit/` (canonical): `collect.py` pulls up to `--max-runs` workflow runs from the last `--days`, their jobs from every attempt (`filter=all`) and the newest `--max-logs` failed-job logs. Each failure is reduced to one scrubbed line (`clean_untrusted`, ≤300 chars) and classified with the foundation `FailureClassifier`; full logs are never stored. `analyze.py` (pure) computes failure and rerun rates, flaky indicators (rerun turned green, fail then pass on the same commit), duplicate push + pull_request runs, OS-weighted minute estimates, per-workflow p50/p90 and queue time, and ranked findings with minimum sample sizes. `report.py` renders the 13-section Markdown report with reviewer markers.
- Log handling: classification and the failure message use only the failing step's output (from its `##[group]Run` header to the first `##[error]` block), without the echoed step script or post-job cleanup. The message prefers a specific `##[error]` line over `Process completed with exit code N`, then the last `##[warning]` when there is no error line.
- Report-only category refinement (`refine_category`; the policy gate never sees it): secret and security scanners (gitleaks, CodeQL, trivy, …) get `security_scan_failure`; when the step that ran names a lint, type or test tool and the error line itself has no environment signal, the tool category replaces an environment category matched elsewhere in the log. Each failure records `classified_by` (`classifier` or `step`). The foundation classifier is unchanged.
- CLI: canonical read-only commands `ci-audit-collect --repo owner/name` and `ci-audit-report <export>`.
- `github_client.py`: `list_workflow_runs`, `list_run_jobs`, `job_log`. **Fix:** the job-logs endpoint redirects to blob storage and `urllib` forwarded the GitHub `Authorization` header there (the blob host rejected it with 401). A redirect handler now drops the token whenever the redirect changes host. This also applies to the existing `collect_run`.
- README: buyer-facing top section (problem, audience, what it does, evidence, outcomes, CTA); engineering docs kept below. New service page [docs/ci-reliability-audit.md](docs/ci-reliability-audit.md) and a [sample report](docs/sample-audit-report.md) generated from this repository's public Actions history.
- Evidence: `tests/test_ci_audit.py` (17 tests) — real-shaped log sectioning (script echo, cleanup and a quoted `import DependencyX` no longer decide the category), a genuine `No module named` still classifies as `dependency_failure`, fake-reader collection skips in-progress runs, a seeded GitHub token in a log never reaches the export or report, the log cap fetches only the newest failures, log download failures surface as a warning and do not trigger `F-SIGNAL`, metrics on a hand-computed fixture (rates, flaky kinds, Windows 2x minutes, duplicate and rerun minutes), severity ordering, all 13 report sections, client pagination and cap, cross-host redirect drops the token, CLI round trip and error exit. A real run against this repository (359 runs, 424 jobs) found the log redirect bug, Dependabot run-name clutter, a misleading `F-SIGNAL`, and messages taken from cleanup output (the runner path `ci-failure-…` matched the word "failure"); all are fixed and covered. On its three real failure types the categories went from lint / dependency / dependency (all wrong) to security scan / unknown / lint.

### Stage 3 — escalate environment, dependency, unknown and low-confidence failures

- Policy (`foundation/policy.py`): the failure classification now gates approval. `dependency_failure`, `infrastructure_failure`, `network_failure` and `unknown` escalate even when a small source patch passes verification (`POL-014-ENVIRONMENT-OR-UNKNOWN-FAILURE`); confidence below `min_classification_confidence` (default 0.6) or a missing classification escalates (`POL-015-LOW-CLASSIFICATION-CONFIDENCE`). Category and confidence appear in the decision evidence. Hard rejects (failed evaluation, forbidden paths) still take precedence.
- Classifier (`foundation/classifier.py`): dependency / network / package / deployment patterns in the message or log excerpt outrank job and step names (a `test` job failing on `No module named 'requests'` was `test_failure`, now `dependency_failure`). The CI-step heuristic moved in as `classify_ci_step`, removing the last canonical → experimental import (`foundation.classifier` → `github_repair_adapter`); `KNOWN_BOUNDARY_VIOLATIONS` is now empty.
- Reproduce-time detection (`service/environment.py`): when the unpatched reproduction fails because a command is missing, a third-party module is missing (a module that exists in the repository does not count), dependency resolution fails, the network is unreachable or resources are exhausted, `fix-repo` returns `AWAITING_HUMAN` with `provider_called: false` and `attempts: 0`, writes `runs/<run_id>/fix-repo/environment-escalation.json` and a task run entry, and never calls the provider. No foundation run is created for these, so `foundation-decide` does not apply and `fix-repo-apply` refuses the run.
- Golden baseline: `foundation-benchmark --compare-baseline` before and after — 26/26 pass both times, and a field-by-field diff of every case's observed classification, policy outcome and workflow status shows no changes; the baseline file was not updated.
- Evidence: `tests/test_stage3_escalation.py` (38 tests) — acceptance case (dependency failure + source-only patch that passes verification → `AWAITING_HUMAN`, `POL-014`, reason `failure_category:dependency_failure` in `policy-decision.json`); code failures with confident classification still auto-approve; low and missing confidence escalate; three end-to-end environment failures (missing module, missing command, DNS) escalate while a spy provider is never invoked; detector kinds and non-matches (`calc.sub`, relative Node imports, `Connection refused`); evidence and command text redacted. One Stage 2b test changed expectation: a failure message matching no pattern now escalates instead of approving. Full suite 493 passed; ruff findings unchanged at the pre-existing 173, none in changed files.

### Stage 2b — Task / Run / Attempt records (roadmap Phase 1)

- `service/records.py`: a **Task** (`service.task.v1`: `task_id`, repository, trigger, sanitized objective) groups the runs aimed at one CI failure; each fix-repo invocation is a **Run** (the existing foundation run — durable state, events and retry schemas are unchanged); each proposal checked in the worktree is an **Attempt** (`service.attempt.v1`: number, agent, proposal source, status `NO_PATCH` / `REFUSED` / `PATCH_REJECTED` / `VERIFICATION_FAILED` / `VERIFIED`, error, patch SHA-256, files, timing).
- Files: `tasks/<task_id>/task.json` (atomic, sanitized), `tasks/<task_id>/runs.jsonl` (append-only; run id, statuses, policy outcome, risk level, attempts, stop reason, agent), `runs/<run_id>/fix-repo/attempt-NNN.json`. `metadata.json` and the run outcome carry `task_id` and `agent`.
- Agent identity per attempt: `patch-file` for operator patches; for `--provider-cmd`, the executable name (or the script an interpreter runs, e.g. `python fake_provider.py` → `fake_provider`).
- CLI: `fix-repo --task-id` records a run under an existing task (unknown or malformed ids end `ERROR` before any worktree); new read-only canonical command `fix-repo-task <task_id>` prints the task with its runs and attempts.
- Not included (deferred, see [docs/roadmap-agent-control-plane.md](docs/roadmap-agent-control-plane.md)): resuming a task from its last attempt, cost/token budgets (Stage 5), multiple agents within one run.
- Evidence: `tests/test_task_run_attempt.py` (17 tests) — patch-file run produces matching task / run / attempt records and the attempt hash equals `metadata.json`; a provider retry yields `PATCH_REJECTED` then `VERIFIED` attributed to the provider; two runs under one `--task-id` accumulate; a `.git/` patch is recorded `REFUSED`; unknown / traversal ids are rejected; `NO_FAILURE` creates no task; a seeded token in the failure message never reaches task files. Full suite 455 passed; ruff reports no findings in changed files.

### Stage 2 — security boundaries on the service path

- Patch guard (`service/patches.py::patch_violation`), enforced in `WorktreeSandbox.execute` before any worktree is created and again in `apply_fix`: rejects symlinks (mode `120000`), submodules (mode `160000` / `Subproject commit`), binary patches, traversal / absolute / drive-letter paths (including `rename`/`copy` headers), `.git/` paths, and added lines containing a high-confidence secret (GitHub token, AWS key, private key). Codes (`forbidden_path_*`, `binary_patch_rejected`, `invalid_patch_contains_secret`) are unrecoverable in `classify_disposition`, so a refused patch stops the run after one attempt.
- Credentials: `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_PAT`, `ACTIONS_*`, `GIT_CONFIG*`, `GIT_ASKPASS`, `SSH_AUTH_SOCK` and similar are refused in `--provider-env` / `--verify-env` (run ends `ERROR`, no artifacts). Ambient values never reach the provider or verification commands (env allowlist).
- Untrusted content (`service/untrusted.py`): ANSI/OSC escapes and control characters are stripped, `::command::` and `##[...]` lines are neutralized, and secrets are redacted at intake (fixture, log file, GitHub, local reproduction) and in verification feedback. Prompt sections holding logs, output and file contents are labeled `UNTRUSTED` inside fences the content cannot close, with a data-only instruction.
- `fix-repo-apply`: PRs are always `--draft`; refuses `main`, `master` and the remote default branch; refuses to push when the branch already exists on the remote; commit message / PR body sanitized.
- Evidence: `tests/test_security_boundaries.py` (41 tests) — including a seeded GitHub token and AWS key in the CI log, verification output and provider response, scanned across every artifact file (`state.json`, `events.jsonl`, `metadata.json`, prompts, responses), provider stdin, the run outcome, the commit message and the PR body; and static AST checks that canonical code contains no merge call and every `gh pr create` argv includes `--draft`. Full suite 438 passed.

### Stage 1b — foundation files split under 1,000 lines (verbatim move)

- `foundation/persistence.py` (1,254 lines) → `durable.py` (schemas, stores, sanitize/JSON helpers; 587), `recovery.py` (assess / verify / inspect / replay / resume), `human_decision.py` (`apply_reviewer_decision`, `append_operator_event`); `persistence.py` keeps `RunPersistence` and re-exports every name, so `foundation.persistence` imports are unchanged.
- `foundation/runner.py` (1,082 lines → 749) → `results.py` (`FoundationResult`), `proposal_factories.py` (`ScriptedProposalFactory`, `default_proposal_factory`, formerly `_default_proposal_factory`), `policy_gate.py` (`PolicyGateMixin._run_policy_gate`, inherited by `AgentExecutionFoundation`); `runner.py` re-exports `FoundationResult`, `ScriptedProposalFactory`, `ProposalFactory`.
- Evidence: an AST comparison of all 50 top-level definitions and runner methods against HEAD found no differences except the one renamed reference; ruff findings in the moved code are the same pre-existing 11 (HEAD had 13; the import-order and unused `typing.Any` findings disappeared with the rewritten import block); full suite 397 passed.
- The oversize caps in `test_canonical_files_stay_under_line_limit` were removed: every canonical file is now ≤ 1,000 lines.

### Stage 1 — `repo_fix.py` split into `service/` (pure move)

- `ci_failure_orchestrator/repo_fix.py` (1,045 lines) moved into `ci_failure_orchestrator/service/`: `common`, `patches`, `session`, `ingest`, `proposals`, `prompt`, `adapters`, `run`, `apply` (largest: `apply.py`, 239 lines). No behavior change; helpers shared across modules lost their leading underscore (`_git` → `git`, `_tail` → `tail`, `_decode_patch_bytes`, `_is_unsafe_path`, `_extract_rationale`).
- `repo_fix.py` is now a compatibility shim re-exporting the same public names; `cli.py` imports from `service`.
- `service` added to the canonical set in `module_status.py`.
- New ratchet `test_canonical_files_stay_under_line_limit`: canonical files ≤ 1,000 lines (pre-existing oversize foundation files were capped until Stage 1b split them).
- Evidence: `tests/test_repo_fix.py` unchanged (`git diff --stat` empty) and passing (12 tests).

### Stage 0 — canonical path marked, risky workflows made safe

- Added `docs/service-v0.1-plan.md` (audit, canonical set, staged plan with acceptance tests, review decisions).
- Added `ci_failure_orchestrator/module_status.py` (machine-readable canonical / entrypoint / experimental classification of every module and CLI command) and `docs/module-status.md`.
- Added `tests/test_module_boundaries.py`: every module classified; manifest entries exist; classification disjoint; canonical modules may not import experimental modules. One pre-existing edge is recorded as a known violation that may only shrink: `foundation.classifier` → `github_repair_adapter` (removal: Stage 3).
- CLI: experimental commands (`classify`, `rank`, `analyze`, `analyze-run`, `trust-run`, `run`, `explain`, `replay`, `benchmark`) are labeled `[experimental]` in `--help`; top-level help names the canonical commands. Test: `tests/test_cli_groups.py`.
- Workflows (`tests/test_workflow_safety.py`):
  - `auto-merge-after-checks.yml`: triggers reduced to `workflow_dispatch` and job hard-disabled (`if: ${{ false }}`), so it cannot merge even when dispatched.
  - `self-heal.yml`: `workflow_run` trigger replaced by `workflow_dispatch` (inert without a `workflow_run` payload).
  - `agent-issue-delivery.yml`: `issues: labeled` trigger replaced by `workflow_dispatch` (inert without an `issues` payload).
  - Static checks: no enabled job contains a merge command; no workflow triggers on `pull_request_target`. Negative check: against the previous workflow files the test fails 3 times.
