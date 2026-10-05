# Productization audit: from ci-failure-orchestrator to CI Doctor

Date: 2026-10-04. Scope: the whole repository at the working tree that includes the
read-only CI audit (`ci_audit/`). No production code was changed to produce this audit.

This document answers one question: what has to change for a developer who has never
heard of this project to install it, point it at a failed GitHub Actions run, and get a
useful, trustworthy answer in a few minutes? It complements, and does not replace,
[`repository-audit.md`](repository-audit.md) (evidence and maturity) and
[`service-v0.1-plan.md`](service-v0.1-plan.md) (the consolidation plan already in flight).

Section 0 is the commercialization update of 2026-10-05. Sections 1 to 10 are the
original audit of 2026-10-04, kept as written except where marked as corrected.

## 0. Commercialization update (2026-10-05)

Companion documents: [ICP.md](ICP.md) (buyer), [COMMERCIAL_ARCHITECTURE.md](COMMERCIAL_ARCHITECTURE.md)
(workflow and what not to build), [SAFETY_CONTROLS.md](SAFETY_CONTROLS.md) (control status) and
[COMMERCIALIZATION_PLAN.md](COMMERCIALIZATION_PLAN.md) (packaging, pricing, roadmap).

### Existing strengths

- **Verified repair, not "CI went green".** A repair moves through explicit states
  (`POLICY_APPROVED`, `CI_GREEN_BUT_UNVERIFIED`, `VERIFIED_FIXED`, `REGRESSION_DETECTED`, ...).
  A green CI rerun alone never counts as fixed; regression suites, affected tests and real CI
  results are separate evidence.
- **Deterministic authority.** The static policy engine (POL-001 to POL-019) decides; a model
  can only propose a patch through `--provider-cmd`. Default outcome is ESCALATE.
- **Isolated verification.** Every proposal is applied and tested in a disposable git worktree;
  the operator's checkout is never touched.
- **One writer, no merge.** `fix-repo-apply` is the only path that writes to a repository: a new
  branch, optionally pushed, optionally a draft PR. A guard test fails on any merge API string.
- **Evidence per repair.** `fix-repo/evidence-report.json` and `.md` answer what broke, why it
  is believed to have broken, what changed, which tests ran, what evidence supports the fix and
  which risks remain, from stored artifacts only.
- **A golden benchmark** guards classifier and policy behavior; baseline updates are reviewed.

### Existing architecture

Three layers, all in one Python package with one runtime dependency (PyYAML):

| Layer | Modules | Role |
| --- | --- | --- |
| Control plane | `foundation/` | classifier, planner, sandbox, evaluator, policy, retry budget, durable state and audit |
| Service | `service/` | `fix-repo` reproduction, proposal sources, worktree verification, remediation decision, apply, evidence report, metrics |
| Product surface | `doctor/`, `ci_audit/`, `cli.py`, `action.yml` | `actions-doctor` (read-only diagnosis, offline demo, GitHub Action), `ci-orchestrator` (repair and audit commands) |

Experimental modules are fenced off by `module_status.py` and boundary tests. Details and the
14-step workflow map are in [COMMERCIAL_ARCHITECTURE.md](COMMERCIAL_ARCHITECTURE.md).

### Working user flows

Each flow below is exercised by tests in this repository. None has production users yet.

1. **Diagnose a failed run:** `actions-doctor diagnose` (alias of `analyze`) on a GitHub run or a
   saved log; read-only.
2. **Diagnose in CI:** the composite action in `action.yml` on `workflow_run` failures; writes the
   job summary and `diagnosis.json`; `actions: read` only.
3. **Offline demo:** `actions-doctor demo` runs six generated failure scenarios.
4. **Audit CI health:** `ci-orchestrator ci-audit-collect` and `ci-audit-report` over 30 days of runs.
5. **Repair locally:** `ci-orchestrator fix-repo` with `--patch-file` or `--provider-cmd`, then
   `fix-repo-apply` (now with `--dry-run` and rollback commands), `fix-repo-verify-ci` for the
   real CI result, `fix-repo-report` and `fix-repo-metrics`.
6. **End-to-end proof:** `examples/demo-repo/run_demo.py` goes from a failing pytest run to a
   diagnosis, a verified patch, a new branch, a passing CI command and an evidence report. It
   ends at `POLICY_APPROVED`, not `VERIFIED_FIXED`, because no real CI provider runs in the demo.

### Missing commercial capabilities

- **No built-in model provider.** Repairs come from a patch file or an operator-supplied
  provider command; there is no packaged LLM integration, prompt tuning or cost reporting.
- **No PR comment or GitHub App.** The Action writes a job summary only.
- **No hosted service:** no accounts, tenancy, dashboard, billing or usage metering.
- **Single repository, single machine.** No queue, no multi-repo view, no shared artifact store.
- **GitHub Actions only** for live ingestion; other CI systems work only through `--log-file`.
- **Not published:** not on PyPI, no tagged product release, no Marketplace listing.
- **No customer evidence:** no production users, case studies or measured outcome rates.

### Technical risks

- **Heuristic classification.** Regex tables with fixed confidence (0.9 on a match, 0.7 from
  step names); `calibrated` is always false. Misclassification changes policy outcomes.
- **Python-centric signals.** Step and log heuristics know pytest, ruff, mypy and pip well;
  other ecosystems mostly fall to `unknown` and escalate (safe, but low automation).
- **Local verification is not CI.** A worktree run can pass where CI fails (OS, secrets,
  services). `VERIFIED_FIXED` therefore requires `fix-repo-verify-ci` on the real CI run.
- **Experimental code still ships** (about 43% of lines, section 5), costing test time and reader focus.

### Security risks

- **Commands run as the operator** without container isolation; a malicious patch can execute
  code during verification (mitigated by worktrees, env allowlist and structural patch refusal).
- **CI logs are untrusted input** fed to a provider command; prompt injection is mitigated by
  neutralization, but the provider's output is only trusted after verification and policy.
- **The fix-repo audit log is not tamper-evident** (append-only JSONL with sequence checks, no
  hash chain; correction to section 3, item 4).
- **No executable allowlist** for verification commands. See [SAFETY_CONTROLS.md](SAFETY_CONTROLS.md#known-gaps).

### UX friction

- Two console commands (`actions-doctor`, `ci-orchestrator`) with internal-sounding names
  (`foundation-decide`, `fix-repo-apply`).
- Repair needs a local clone, a reproducible verify command and, for policy approval, a
  classifiable failure log.
- JSON-first output; the Markdown evidence report is new and not yet posted anywhere.
- Opaque run IDs; approval of escalated runs needs `foundation-decide`.

### Deployment blockers

- Package name and description: `pyproject.toml` still describes research features
  (canaries, fleet policy, production proof).
- No release workflow, signed artifacts, SECURITY.md or support policy.
- MIT license: the code can be used commercially by anyone, so revenue must come from service,
  hosting or support rather than license restrictions.

### Recommended MVP scope

Sell a **verified-repair pilot for one GitHub repository**: diagnosis Action on every failed
run, `fix-repo` driven by the customer's own patch or provider command, apply to a draft PR only
after policy approval, evidence report per repair, and a monthly metrics report from
`fix-repo-metrics`. Everything in that scope exists in code today; the missing parts are
packaging, a PR comment and onboarding.

### Features to postpone

GitHub App, hosted dashboard, multi-tenant service, billing integration, non-GitHub live
ingestion, auto-merge of any kind, calibrated confidence models, graph-based root-cause ranking
and container sandboxes. Reasons are in [COMMERCIAL_ARCHITECTURE.md](COMMERCIAL_ARCHITECTURE.md).

## 1. Summary

The engineering core is stronger than the product around it. The deterministic control
plane already does what the CI Doctor positioning promises: classify, propose, verify in
an isolated worktree, gate through policy, escalate to a human, and write an audit trail.
What is missing is the layer a user touches: a single obvious command, readable output, a
GitHub integration that runs without a maintainer, a demo that works offline, and docs
that start from the user's problem instead of the architecture.

Three findings change the plan and need a decision before anything is published:

1. **The name `ci-doctor` is taken on PyPI** by an unrelated project with the same purpose
   ("ci-doctor 0.1.1: CLI to diagnose CI pipeline runs"). Publishing a package or console
   command called `ci-doctor` would collide on install and in search. Free names checked on
   2026-10-04: `cidoctor`, `ci-doctor-cli`, `actions-doctor`, `ci-medic`, `gha-doctor`.
   **Decided 2026-10-04:** the brand stays "CI Doctor"; the package and console command
   are `actions-doctor`.
2. **Diagnosis is rule-based, and confidence is not calibrated.** Classification is a
   regular-expression table with a fixed confidence of 0.9 (`classifier.py`,
   `foundation/classifier.py`; `FailureClassification.calibrated` is always `False`).
   Output such as "Root cause: urllib3 < 2.3, confidence 91%" cannot be produced honestly
   today. The product must show heuristic confidence as heuristic until calibration exists.
3. **The current safety model escalates the very cases the brief shows as auto-repairable.**
   Dependency changes trigger POL-007 (DEPENDENCY-CHANGE) and dependency, network,
   infrastructure and unknown failures trigger POL-014. A "dependency drift, risk LOW,
   apply patch" flow contradicts these rules. This audit recommends keeping the rules: a
   dependency repair is shown as "proposed and verified, needs approval", never as
   automatic.

## 2. Current state

| Area | State |
|---|---|
| Package | `ci-failure-orchestrator` 1.2.0, Python ≥3.10, one runtime dependency (PyYAML). Console script `ci-orchestrator`. |
| Code | 165 modules, ~24k lines. Canonical: 65 modules, 13.2k lines. Experimental: 99 modules, 10.1k lines in 13 groups. Boundaries enforced by `module_status.py` and `tests/test_module_boundaries.py`; no known violations. |
| Tests | 70 files, 510 tests, all passing locally (Python 3.14) and in CI (3.12). Test functions split about evenly between canonical and experimental code. |
| Lint | ruff is clean on changed files; 173 pre-existing findings repo-wide. CI lints only the trust modules. |
| CLI | One argparse entry point with 22 commands: 13 canonical (`fix-repo*`, `foundation-*`, `ci-audit-*`), 9 experimental. |
| Workflows | 17 GitHub workflows. `auto-merge-after-checks.yml` is hard-disabled; `self-heal.yml` and `agent-issue-delivery.yml` are manual-only. |
| Docs | ~60 files in `docs/`, many from earlier research phases (L4.5, L5–L7, production-proof, fleet). README is 255 lines: a buyer section, then engineering documentation. |
| Contributor surface | No Makefile, no CONTRIBUTING, SECURITY or CODE_OF_CONDUCT, no issue or PR templates. `demo.sh` uses an experimental command. `make` is not installed on the maintainer's Windows machine. |
| Real-world validation | `ci-audit-collect` / `ci-audit-report` run against two real repositories (this one and a private 957-run Windows project); `fix-repo` verified a real mypy repair in a worktree. No production users. |

## 3. Strongest assets (keep and build on)

1. **The deterministic control plane** (`foundation/`). Planner, sandbox executor,
   evaluator, policy engine, retry budget and audit store are already Protocols with
   concrete implementations, injected through `AgentExecutionFoundation`. This is the
   Phase 3 interface layer, mostly done.
2. **The policy engine and its rules.** POL-001 to POL-015 encode the safety model: default
   ESCALATE, evaluation PASS is not policy APPROVE, approval is not mutation, forbidden
   paths, CI workflow changes, dependency and auth changes, broad scope, high retry count,
   invalid proposals, engine failures, environment or unknown failures, and low
   classification confidence. Every decision names the rule that made it.
3. **Bounded retries and human escalation.** `RetryBudget` and `RetryDecisionEngine` stop
   retries; escalation writes a reviewable package; `foundation-decide` records a human
   decision; `fix-repo-apply` is the only code path that writes to a repository, and it
   only opens draft pull requests on a new branch.
4. **Durable audit and evidence.** Append-only `events.jsonl` with monotonic sequence numbers
   and unique event IDs, `foundation-verify` to check run consistency, and
   `foundation-resume` for interrupted runs. (Corrected 2026-10-05: the original text said
   "hash-chained events, evidence references with digests". Hash chains exist only in the
   trust-plane `audit.py`, not in the foundation event log.)
5. **Real worktree verification** (`service/`, `repo_fix.py`). Reproduce the failure,
   apply a patch in a git worktree, re-run the command, keep the evidence, and detect
   environment failures (missing tools, missing modules) before blaming the code.
6. **The read-only CI audit** (`ci_audit/`). Already user-facing: it pulls 30 days of
   runs, groups failures, reads failing log sections, refines categories with step
   context, redacts tokens, and writes a Markdown report. It found real bugs in its own
   log handling on real data and is the most "product-shaped" code in the repository.
7. **Security boundaries.** Token redaction, no `pull_request_target`, the token dropped on
   cross-host log redirects, forbidden-path policy, and an LLM held behind
   `ProposalSource` / `OptionalModelPlannerAdapter` so that deterministic checks decide.
8. **A golden benchmark** with a fixed baseline (`benchmarks/`, `foundation-benchmark`)
   that guards classifier and policy behavior against regressions.

## 4. Missing product layers

| Layer | What exists | What is missing |
|---|---|---|
| Entry point | `ci-orchestrator` with 22 commands named after internals (`foundation-decide`, `fix-repo-apply`). | A small user vocabulary: analyze, explain, propose, verify, repair, report. |
| First-run experience | Requires reading the engineering docs. | One command against a run URL or a saved log; an offline mode that needs no token. |
| Output | JSON artifacts and terse text. | A formatted diagnosis: class, evidence with a log location, affected jobs, next step, verification plan, policy preview, audit pointer. |
| Root-cause ranking | Experimental `ranker.py` + `graph.py` tied to the old diagnosis models. Not used by the canonical path. | A canonical ranker over the jobs of one run, using workflow `needs` order (service plan Stage 4). |
| Evidence collection | Ingest functions in `service/ingest.py`, `github_client.py`, `ci_audit/collect.py`. | One `EvidenceCollector` interface with GitHub-API and local-log implementations, and log line-range references instead of bare strings. |
| GitHub integration | `self-heal.yml` (manual, repository-specific). | A reusable Action triggered by `workflow_run`, posting one PR comment (service plan Stage 6). |
| Demo | `demo.sh` on an experimental command. | Offline, deterministic scenarios a reviewer can run in one minute (service plan Stage 7, extended to six failure types). |
| Configuration | `PolicyConfig` built in code; `config/policies.yaml` and `providers.yaml` are read only by the experimental `trust-run`. | One versioned config file for the canonical path (forbidden paths, verification commands, retry budget, approval rules). |
| Domain schema | Dataclasses in `foundation/models.py` and `durable.py`; `service.task.v1` / `service.attempt.v1`. | A shared envelope (id, parent run id, timestamp, provenance, status) and the missing types: `RootCauseCandidate`, `VerificationPlan`, `RunOutcome`. Published JSON Schemas (Stage 5). |
| Contributor and project hygiene | Tests and CI. | Makefile (plus a Windows path), CONTRIBUTING, SECURITY, templates, a short architecture doc. |
| Distribution | Not on PyPI. | A package name that is free, a release workflow, a version for the product line. |

## 5. Technical debt

1. **Duplicate execution paths.** The service plan lists 11: three classifiers, four policy
   engines, four state machines, three GitHub ingest modules, three worktree
   implementations. Stages 0–3 made one of each canonical; the duplicates still ship.
2. **Experimental code is 43% of the package.** The largest groups are `governed` (1.9k
   lines), `evidence` (1.1k), `supervisor` (1.1k), `trust` (0.9k), `control-plane` (0.9k).
   They cost test time, review attention and reader confusion, and two of their command
   names (`analyze`, `explain`) collide with the product vocabulary.
3. **CI checks the wrong things.** `ci.yml` lints only the trust modules and smoke-tests
   the experimental `rank` command, so the canonical path has no lint gate and the smoke
   test protects code the product will not use.
4. **173 ruff findings** outside the files changed recently.
5. **Timeouts are classified as flaky tests.** `classifier.py` maps "timed out" to
   `FLAKY_TEST`. Most CI timeouts are infrastructure or hung processes, not flakes; this
   matters because flaky failures are not escalated by POL-014. Fixed in the policy
   classifier: without an explicit flaky or intermittent marker, a timeout is
   `timeout_failure`, which POL-014 escalates. The shared table is unchanged.
6. **Fixed confidence.** Every regex match reports 0.9. POL-015 (low confidence escalates)
   therefore only fires for `unknown`.
7. **Package metadata over-claims.** The `pyproject.toml` description lists production
   proof, fleet policy and canaries; none of these are product features.
8. **Two benchmark directories** (`benchmark/`, `benchmarks/`) and several legacy top-level
   docs (`LEVEL7.md`, `L45-RELIABILITY-RUNTIME.md` and similar) that describe superseded
   designs.

## 6. User-experience problems

1. **The first screen is about architecture.** A new user has to learn "foundation",
   "governed", "trust", "service" and "control plane" before running anything.
2. **Command names describe the implementation.** `foundation-decide --action APPROVE` is
   the approval step; `fix-repo-apply` is the repair step. Nothing is named after the job
   the user is doing.
3. **No offline path.** Every useful flow needs a GitHub token or a local repository with a
   reproducible failure. A reviewer cannot try the tool in one minute.
4. **Output is for machines.** The canonical commands print JSON paths and status words.
   The only human-readable output is the CI audit report.
5. **Run IDs are opaque** (`run-44d430e01342`). There is no "what happened to my run"
   view; `foundation-inspect` and `foundation-events` print raw state.
6. **Windows friction.** Docs use `&&` and bash; no `make`; PowerShell users hit both.

## 7. Architecture risks

| Risk | Why it matters | Mitigation |
|---|---|---|
| Name collision (`ci-doctor` on PyPI) | Install conflicts, search confusion, possible trademark dispute. | Resolved: publish as `actions-doctor`. Keep the import path `ci_failure_orchestrator` until a separate rename. |
| Over-promising diagnosis | Users trust a confident wrong answer more than an honest "unknown". | Show the evidence line for every claim; label confidence "heuristic"; publish precision per class from the benchmark (Phase 9). |
| Pressure to auto-repair dependency drift | It is the most common real failure and the most dangerous change. | Keep POL-007 and POL-014; make "verified, awaiting approval" a first-class, fast flow. |
| Two GitHub surfaces built at once | Action and App have different trust models. | Action first (service plan §5.1); App only after the Action has users. |
| Product layer bypassing the control plane | A convenient CLI that calls a provider and writes files directly would undo the safety model. | The product CLI calls the same foundation and service code paths; it must not import `fix-repo-apply` internals or write files itself. |
| Rewrite temptation | A rename plus restructure would break 510 tests and the golden baseline. | Additive layer first; renames and deletions in separate, reviewed PRs. |
| Fixture success presented as real success | The benchmark and demos are synthetic. | Every demo and report states its data source; real numbers only from real runs. |

## 8. Decisions

### Preserve unchanged
- `foundation/` control plane, policy rules POL-001..015, retry budget, escalation and the
  `foundation-*` commands (they become the engine behind the product commands).
- `fix-repo-apply` as the only writer; draft pull requests only; no merge path.
- The golden benchmark and its baseline.
- `ci_audit/` and its report format.
- Module boundary enforcement (`module_status.py` + boundary tests).

### Refactor (small, behavior-preserving or test-covered)
- Add a canonical product CLI layer (`ci_failure_orchestrator/doctor/`) that composes
  existing code. No new runtime dependency: argparse plus a small text renderer.
- Extract an `EvidenceCollector` Protocol over the existing ingest functions, with a
  local-log implementation for offline use.
- Make `FailureClassifier` a Protocol with the current regex classifier as the default.
- Port the ranking idea from `ranker.py` into a canonical `RootCauseRanker` over one run's
  jobs (service plan Stage 4) instead of reviving the experimental graph.
- Split "timed out" out of `FLAKY_TEST` into a timeout signal mapped to infrastructure,
  with a benchmark case so the change is measured. Done as its own `timeout_failure`
  category instead of infrastructure: a hung test and a slow runner need different next
  steps, and both escalate (BENCH-CLASS-012, BENCH-POLICY-007).
- Point `ci.yml` lint and smoke tests at the canonical path.
- Rewrite the `pyproject.toml` description to what the tool does.

### Remove (proposed only; each group in its own reviewed PR, after the boundary test
shows no canonical importer)
- Experimental groups not used by any canonical command, starting with the two that own
  commands whose names collide with the product vocabulary (`analyze`, `explain`): `diagnosis`
  and `governed`: the diagnosis commands (`classify`, `rank`, `analyze`, `analyze-run`)
  and the governed commands (`run`, `explain`, `replay`, `benchmark`). Tag the last commit
  that contains them.
- `auto-merge-after-checks.yml` (disabled, and contradicts the no-merge invariant).
- `demo.sh` once the new demo exists. For now it runs `actions-doctor demo --all` instead
  of the experimental `rank` command.
- Legacy top-level design docs, moved to `docs/archive/` rather than deleted.

### Do not touch yet
- The GitHub App, the web dashboard, the hosted API and the MCP/agent skill (Phase 10
  extension points only).
- The model-backed planner beyond its existing adapter; no new provider work until the
  deterministic product flow exists.
- Package rename and version line, until the name decision.
- `research-evidence.yml`, `measured-production-evidence.yml` and the other research
  workflows; they are noisy but isolated, and removing them is not user value.

## 9. Reconciliation with the service v0.1 plan

The CI Doctor phases overlap the remaining service-plan stages. One sequence, not two:

| CI Doctor phase | Service plan stage | Order |
|---|---|---|
| Phase 1 audit, Phase 2 spec | (new) | This iteration. |
| Product CLI `analyze` (read-only, offline and GitHub) | uses Stage 0–3 work | Next iteration; smallest user-visible step. |
| Phase 3 interfaces, Phase 4 domain model | Stage 4 (`service/dag.py`), Stage 5 (`schemas/run.v1.json`) | After `analyze`, so the interfaces are shaped by a real consumer. |
| Phase 5 demo | Stage 7 (extended from 3 outcomes to 6 failure types) | Before the Action, because the Action's tests reuse the scenarios. |
| GitHub Action, PR comment | Stage 6 | After the demo. |
| Phase 6–8 README, docs, contributor surface | Stage 9 | Incrementally with each step; full pass before the first release. |
| Phase 9 metrics | Stage 5 (`service-metrics`) + Stage 8 case studies | Engineering metrics from the benchmark first; product metrics after users exist. |
| Phase 11 commercialization | (business) | Document only. Note the price conflict: the brief says US$199–499, the published audit page says a US$149 pilot then US$199. |
| Phase 12 roadmap | Stage 9 release checklist | Written with the spec. |

## 10. Recommended next iterations

1. Done. Commit the pending `ci_audit` work as its own change, so the product layer starts
   from a clean base.
2. Published name: decided, `actions-doctor` (see section 1).
3. Done. Add `actions-doctor analyze` as a read-only command: GitHub run or local log
   in, formatted diagnosis out, with evidence line references and a policy preview. Reuses
   `github_client`, `ci_audit.collect` and the foundation classifier; no writes, no
   provider. Tests use saved logs.
4. Done. Running `analyze` on real runs showed the policy engine's classifier calling a
   gitleaks finding `lint_failure` (eligible for repair) and a ruff failure
   `dependency_failure` (escalated). The classifier now has a `security_scan_failure`
   category that POL-014 escalates, and a linter, formatter or type-checker step whose
   output quotes source is no longer read as an environment failure. Benchmark cases
   BENCH-CLASS-007..011 and BENCH-POLICY-006 hold both fixes and their guards.
5. Done. `actions-doctor demo` runs six offline scenarios (dependency drift, flaky test,
   network failure, timeout, configuration error, environment mismatch) through `analyze`
   and `fix-repo`. Each is a real failure in a generated repository: its verify command
   fails at the base commit and passes with the recorded fix. The classifier gained the
   categories the scenarios need (debt item 5 included) and a flaky signal that a single
   log can carry (one test both passed and failed in the same repeated run). Only the
   flaky-test fix is approved; the other five escalate, which is the policy's intent.
6. Done (diagnosis only). `action.yml` at the repository root: a composite action that
   installs the package into a virtual environment and runs `doctor/action.py` on the run
   that triggered a `workflow_run` event, writing the diagnosis to the job log, the job
   summary, `diagnosis.json` and two outputs. Read-only (`actions: read`); it never checks
   out the failed run's code. `.github/workflows/ci-doctor.yml` runs it on this
   repository's own `ci` failures. Tests use a fake GitHub reader, not the demo logs.
7. Next: a Markdown renderer for the summary (it is the text report in a code block today),
   then one PR comment updated in place (`pull-requests: write`), then a `v1` release and
   Marketplace listing.
