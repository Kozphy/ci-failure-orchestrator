# Productization audit: from ci-failure-orchestrator to CI Doctor

Date: 2026-10-04. Scope: the whole repository at the working tree that includes the
read-only CI audit (`ci_audit/`). No production code was changed to produce this audit.

This document answers one question: what has to change for a developer who has never
heard of this project to install it, point it at a failed GitHub Actions run, and get a
useful, trustworthy answer in a few minutes? It complements, and does not replace,
[`repository-audit.md`](repository-audit.md) (evidence and maturity) and
[`service-v0.1-plan.md`](service-v0.1-plan.md) (the consolidation plan already in flight).

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
4. **Durable audit and evidence.** Append-only `events.jsonl` with hash-chained events,
   evidence references with digests, `foundation-verify` to check integrity, and
   `foundation-resume` for interrupted runs.
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
   matters because flaky failures are not escalated by POL-014.
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
  with a benchmark case so the change is measured.
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
- `demo.sh` once the new demo exists.
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

1. Commit the pending `ci_audit` work as its own change, so the product layer starts from
   a clean base.
2. Published name: decided, `actions-doctor` (see section 1).
3. Add `actions-doctor analyze` as a read-only command: GitHub run or local log
   in, formatted diagnosis out, with evidence line references and a policy preview. Reuses
   `github_client`, `ci_audit.collect` and the foundation classifier; no writes, no
   provider. Tests use saved logs.
