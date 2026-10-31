# Engineering evidence report: CI correctness and EDAS v2.0

Audit date: 2026-10-31. Base: [`69ba500f53a4f492c876dd26636b9222d7e140ce`](https://github.com/Kozphy/ci-failure-orchestrator/commit/69ba500f53a4f492c876dd26636b9222d7e140ce).
Work branch: `audit/edas-v2-evidence`. This is an AI-assisted source review and local test
record, **not independent external assurance**. No production effectiveness, customer outcome,
institutional endorsement, compliance certification or formal proof is claimed.

## Scope, provenance and reproducible baseline

The shell could not connect to its configured proxy; two network-permission clone attempts
were cancelled, so no successful clone or package installation is claimed. The connected
GitHub API recovered the pinned source: **537 file blobs** matched their Git SHA-1 object
hashes, the complete tree matched `166b3348aad681f295171219fa33933c701ed87a`, and reconstruction
of the original signed Git commit matched the base SHA. Local history is shallow. This
verifies consistency with retrieved API objects, not independent verification of signer identity.
No `AGENTS.md` appeared in the complete 636-entry recursive tree.

Review concentrated on the canonical models, evaluator, remediation predicate, policy/retry
interfaces, state machine, sanitization, patch refusal, CI verification, existing tests,
module-status boundary manifest, workflow and benchmark contracts, and safety/architecture docs.
The complete source was recovered, but this was not an exhaustive line-by-line review of every
module. Ten recent commit messages and the base commit diff were inspected. History shows
dedicated changes for verification weakening, verified repair states, service safety and SQL
worker/API support; commit messages are evidence of recorded change intent, not proof of effect.
See [source and CI observations](../evidence/edas-v2/source-and-ci.json).

Environment: Linux, Python **3.12.14**, PyYAML **6.0.3**. pytest, Ruff and mypy were absent.
The first executed targeted regressions used unchanged production source, verified against
the recovered base hashes. They ran **11 test methods**: seven passed, four failed, with six
assertion failures (three are subtests of one method). The existing benchmark returned
**38/38** passing cases, including **37/37 required**, before any production changes.

Raw evidence:

- [Baseline checks and source hashes](../evidence/edas-v2/baseline/checks.json),
  [failing regressions](../evidence/edas-v2/baseline/canonical-adversarial.txt).
- [Reviewed checks and source hashes](../evidence/edas-v2/reviewed/checks.json),
  [passing canonical tests](../evidence/edas-v2/reviewed/canonical-adversarial.txt),
  [EDAS tests](../evidence/edas-v2/reviewed/edas-tests.txt).
- [Baseline benchmark summary](../evidence/edas-v2/baseline/foundation-summary.json),
  [reviewed benchmark summary](../evidence/edas-v2/reviewed/foundation-summary.json),
  [reviewed case comparison](../evidence/edas-v2/reviewed/foundation-comparison.json).
- [Prototype safety-boundary failure found during review](../evidence/edas-v2/safety-review-before-fix.txt).
  Intermediate `final/` records are retained; `reviewed/` is the latest executed source version.
- [Remote implementation CI evidence](../evidence/edas-v2/remote-ci.json) and
  [log excerpt](../evidence/edas-v2/remote-ci-excerpt.txt): the published implementation commit
  `8596a3f7f5dc17a53d48d5907eca6a8d95010d1c` passed GitHub CI after local collection completed.
  Later evidence-document changes preserve the tested production, example, test and workflow bytes.

## Justified changes

1. **Aggregate evaluation now respects explicit failed checks.** A successful target command
   could previously coexist with failed lint, typecheck or relevant-test checks and still set
   `passed=True`. The passing predicate now requires no explicit `FAILED` check. Missing optional
   checks retain existing semantics; this does not claim every optional gate was executed.
2. **Unknown skip comparisons cannot verify a repair.** `skipped_tests_increased=None` previously
   passed the predicate. It must now be explicitly false, and the missing comparison is reported.
3. **Verification predicates agree with rejection.** A human flag no longer satisfies policy
   when policy is `REJECT`; forbidden-diff codes also prevent verification even if the summary
   flag disagrees. The central decision already rejected these inputs; its helper now agrees.
4. **Isolated EDAS reference and tests.** A small synthetic advisory kernel demonstrates scoped
   claims, evidence metadata, budget/deadline handling, distinct-name review, revision invalidation
   and audit linkage. It reuses canonical secret detection and sits outside canonical imports.
   A new test exposed safety advice being suppressed after `UNRESOLVED`; precedence was fixed
   and the failing output preserved. It does not add a production decision service.
5. **Reproducible evidence and CI wiring.** Captured commands, source/output hashes and exit
   codes; added unittest/evaluation steps and generated artifact upload without removing any
   existing CI checks. The benchmark expectations and stored baseline were not changed.

## Claim-to-evidence register

Verification status distinguishes locally tested behavior, remote observation, static inspection,
documented intent, proposed mechanisms and blocked checks. Paths are repository-relative.

| Claim | Source Path | Test | Result | Limitations | Verification Status |
| --- | --- | --- | --- | --- | --- |
| Explicit failed relevant/lint/type checks prevent aggregate pass | `foundation/evaluator.py` under `ci_failure_orchestrator/` | `test_evaluator_fails_on_each_explicit_failed_check` | Three subtests failed at base, pass after fix | Synthetic `SandboxResult`; no hostile process containment demonstrated | Demonstrated locally |
| Unknown skipped-test comparison cannot produce verified repair | `foundation/remediation.py` | `test_unknown_skip_comparison_never_verifies` | Failed at base, passes after fix; missing evidence named | Relies on collector truthfulness; no proof that collected summary is complete | Demonstrated locally |
| Policy rejection wins over human flag | `foundation/remediation.py` | `test_human_approval_cannot_override_policy_rejection` | Helper failed at base, passes after fix | Does not authenticate approver or secure stored state | Demonstrated locally |
| Forbidden codes cannot disagree into success | `foundation/remediation.py` | `test_forbidden_codes_and_flag_cannot_disagree_into_success` | Helper failed at base, passes after fix | Other inconsistent input combinations not exhaustively analyzed | Demonstrated locally |
| CI green does not replace original failure or required gates | `foundation/remediation.py` | `test_green_ci_does_not_replace_missing_baseline`, `test_any_missing_gate_blocks_verified_outcome` | Pass at base and after changes | Gate waivers retain existing semantics; a waiver is not a measured pass | Demonstrated for tested inputs |
| Timeouts and missing target checks fail closed | `foundation/evaluator.py` | `test_timeout_and_missing_target_fail_closed` | Pass | Injected timeout flag; no real process termination/reaping measurement | Partially demonstrated |
| Retry budget exhaustion stops further attempts | `foundation/retry.py` | `test_retry_budget_exhaustion_stops` | Pass at one-attempt boundary | Does not measure live provider token/cost ceilings | Demonstrated for tested boundary |
| Unsafe structural patches refused | `service/patches.py` | `test_forbidden_patch_paths_and_symlinks` | Three injected shapes refused | Not exhaustive parser fuzzing or sandbox assurance | Partially demonstrated |
| Terminal automation cannot restart from approval | `foundation/state_machine.py` | `test_terminal_state_cannot_resume_automation` | Rejected transition; state/history unchanged | One tested terminal state, not a proof of all executions | Demonstrated for tested transition |
| Existing golden behavior preserved | `foundation/benchmark/`, `benchmarks/foundation/` | CLI `foundation-benchmark --compare-baseline` | 38/38 before and after; 37/37 required; 0 harness errors | Authored synthetic cases; passing suite missed the discovered defects | Demonstrated synthetic conformance |
| Evidence digest mismatch rejected | `examples/edas/core.py` | `test_evidence_tampering_detected` | Pass | Hash does not prove source authenticity or truth | Demonstrated integrity check only |
| Unattested/missing/dependent evidence does not qualify | `examples/edas/core.py` | Fabricated, missing, copied-source and authority tests | Pass | Attestation and dependency group are caller-provided and forgeable | Partially demonstrated provenance control |
| Contradiction and new evidence invalidate old advice | `examples/edas/core.py` | `test_contradiction_requires_review`, `test_new_contradiction_invalidates_decision` | Pass | Human interpretation of stance is supplied, not validated | Demonstrated state behavior |
| Approval bound to revision, version and distinct ID | `examples/edas/core.py` | `test_stale_or_self_approval_refused` | Pass | No actual IAM, role authorization or independence verification | Partially demonstrated authorization design |
| Audit mutation/reordering/truncation detected against trusted tip | `examples/edas/core.py` | `test_audit_mutation_reorder_and_truncation_detected_against_tip` | Pass | Tip must be retained independently; no external checkpoint/signature implemented | Partially demonstrated |
| Synthetic-only declaration and limited log minimization | `examples/edas/core.py` | Nonsynthetic/secret rejection and public-audit tests | Pass | Flags can be misdeclared; pattern detection is not complete DLP | Partially demonstrated privacy defense |
| Toy Bayesian update computed correctly; invalid numbers rejected | `examples/edas/core.py` | Bayesian example/provenance/nonfinite tests | Pass; illustrative posterior 8/17 | No empirical priors, likelihood validation or probability calibration | Demonstrated arithmetic; inference effectiveness unverified |
| Budgets, deadline and safety-advice precedence | `examples/edas/core.py` | Cost, retries, deadline, immediate-hazard tests | Pass after one prototype regression was found/fixed | Logical inputs; no measured external verification spending or professional safety assessment | Demonstrated advisory transitions |
| Eligibility conjunction across five Boolean controls | `tests/test_edas_reference.py` | `test_bounded_exhaustive_ready_requires_all_controls` | All 32 combinations passed | Finite input grid; not property-based randomized testing or formal proof | Demonstrated bounded enumeration |
| EDAS expected recommendations match authored fixtures | `examples/edas/cases.json`, `evaluate.py` | Evaluation CLI and fixture unittest | 17/17 | Author supplied both policy and expected labels | Demonstrated fixture conformance only |
| Entire local repository suite passed | `pyproject.toml`, existing tests | Captured `python -m pytest --cov=...` | Exit 1: no pytest module | No local full-suite result or coverage result | Blocked |
| Local Ruff and static typing validated | CI/workflow and collector | Captured Ruff command and mypy version probe | Exit 1: modules absent | A mypy version probe would not establish type correctness even if available | Blocked |
| Base GitHub CI jobs succeeded | `.github/workflows/ci.yml`; GitHub run 41179836420 | Retrieved workflow/job/step metadata | `test`, `server-postgres`, `server-image` reported success | Historic base SHA; no local rerun or delivered-branch CI proof; logs/test counts not independently audited | Remotely observed, scoped |
| Published implementation passes full GitHub CI | Commit `8596a3f`, run 41227967976 | Job metadata and fetched test-job log; `remote-ci.json` | 855 tests passed, 1 warning, 72 subtests passed; total coverage 86%; server-postgres and server-image passed | One GitHub runner environment; CI lint/type scopes remain limited; not independent scientific validation | Demonstrated remotely for implementation SHA |
| Production users or general decision-quality improvement | README limitations; EDAS research protocol | No executed representative/independent study | None | No customer outcomes, independent replication, calibration or causal validation | Not demonstrated |
| Research-grade / enterprise-ready / formally assured labels justified | `docs/EDAS_V2_VALIDATION.md` acceptance requirements | No independent study, operational qualification or proof artifacts | None | These are explicit future acceptance criteria | Proposed but untested |

## Benchmarks and denominators

Existing foundation benchmark: **38/38** cases passed before and after changes; **37/37**
required and one optional case. Classification **17/17**, synthetic repair **7/7**, policy
outcome **9/9**, security-control **8/8**, escalation **7/7**, and audit completeness **5/5**
are harness-defined overlapping subsets; they must not be summed into an independent sample.
Its reported false-remediation count **0/38** is fixture-specific, not a production safety rate.
No baseline was updated to obtain these results.

EDAS authored fixtures: **17/17** matching recommendations. The green-only comparator always
recommends proceed and agrees on **2/17**; it is a deliberately weak negative control, not a
competitive baseline. Proceed on a fixture labeled non-proceed: **0/15** for EDAS, **15/15**
for that comparator. Here “unsafe proceed” means disagreement with an authored non-proceed
label, not observed real-world harm. No population accuracy interval is justified.

Reviewed local timing: **1,700 measurements = 17 cases × 100 repetitions**. Median **0.109620 ms**;
p95 nearest-rank **0.152569 ms**, including in-memory fixture creation and evaluation. No I/O,
model, network, durable storage or reviewer latency is included. Repetitions do not increase
the 17-case decision denominator. Provider monetary cost is **not applicable in this example**,
and is not instrumented for the canonical provider repair loop. Raw per-case outputs and timing
method are in [the reviewed evaluation](../evidence/edas-v2/reviewed/edas-evaluation.txt).

## Failures and unverified claims retained

The evidence collector returns exit **1** because the full suite, Ruff and mypy cannot run
locally. That is not a successful all-checks gate. Dependency requirements are version ranges;
there is no new locked full-suite environment. Existing base CI success is relevant historical
evidence; new-code compatibility is separately supported by the successful implementation CI run
linked above. That run also executed the new unittest/evaluation step and uploaded the generated
EDAS artifact. Local tooling failures remain valid records; remote execution does not change them.
Source/document whitespace checks pass. The full staged whitespace check flags one trailing
space in raw baseline unittest output, which is deliberately preserved with its recorded hash.

The CI-verification adapter can aggregate successful observed runs without a configured
required-workflow inventory; skipped ancillary runs coexist with a successful run under existing
semantics. Explicit run IDs and commit/evidence association need stronger binding before broader
real-CI assurance. These paths were inspected but not changed in this bounded patch.
Canonical verification commands still run without container/VM isolation; local audit logs are
not made tamper-evident by the separate EDAS example. The disabled auto-merge workflow remains
disabled. No merge, automatic merge enablement or default-branch update was performed.

## Independent reproduction and external validation

Use [the exact execution commands](EDAS_V2_IMPLEMENTATION.md) for a fresh clone, unchanged-base
failure reproduction and current targeted checks. Match deterministic outcomes rather than
copying timing numbers. Validate output hashes and source manifests. Use the full pytest/lint/
type and PostgreSQL/container jobs in a network-enabled pinned environment; preserve failures.

External validation needed: independent reviewer reproduction; unobserved adversarial cases;
qualified domain/policy review; real source authenticity/IAM assessment; isolation and durable
recovery testing; controlled hidden-set calibration/decision-loss research; and a scoped
operational pilot before deployment claims. No medical/legal/financial professional judgment
is replaced. Public data stays synthetic.

## Required final assessment

| Dimension | Evidence | Gap | Verification | Priority |
| --- | --- | --- | --- | --- |
| Epistemology | Alternatives, falsifier, unknown/unresolved distinctions; specification and field tests | Semantic validity and bias reduction not measured | Partially demonstrated | High |
| Evidence Quality | Digests, freshness and declared dependency-group tests | Authenticity, completeness and selection bias need trusted acquisition | Partially demonstrated | High |
| Bayesian Reasoning | Correct toy posterior, numeric validation and documented assumptions | No empirical priors/likelihoods or calibration | Partially demonstrated | Medium |
| Causal Inference | Explicit confounding DAG and proposed randomized design | No identified causal effect or executed causal study | Proposed but untested | Medium |
| Decision Theory | Deadline/cost/reversibility/high-severity/safety-advice transitions tested | Utility/VOI/loss functions not empirically elicited or implemented generally | Partially demonstrated | High |
| Formal Assurance | Explicit invariants and 32-combination enumeration | No machine-checked proof, model or refinement argument | Not demonstrated as formal assurance | Medium |
| Software Reliability | Four canonical defect regressions fixed; 11/11 targeted methods; 38/38 fixtures; implementation CI 855 tests + 72 subtests passed | Local full tooling blocked; limited lint/type scope; durable operational checks pending | Partially demonstrated operationally; implementation CI demonstrated | High |
| Governance | Version/reviewer-ID tests and current-source conceptual crosswalk | Real IAM, conflicts, retention, operating effectiveness and independent review absent | Partially demonstrated | High |
| Research Reproducibility | Captured commands/source/output hashes, fixture denominators and raw failures | Exact dependency lock, held-out study and external replication absent | Partially demonstrated | High |
| Adversarial Robustness | 25 EDAS methods, 17 decision fixtures and canonical adversarial tests | Same-author cases, no unseen attacks, forged attestations/identities not prevented | Partially demonstrated | High |

For the next three job-application improvements, scoped resume bullets and interview questions,
see [the portfolio roadmap](EDAS_V2_PORTFOLIO.md). For the full acceptance evidence required by
stronger readiness labels, see [the validation protocol](EDAS_V2_VALIDATION.md).
