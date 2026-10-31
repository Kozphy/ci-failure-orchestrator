# EDAS v2.0 research protocol and evaluation matrix

Status: **proposed study; local synthetic regression evidence exists**. No experiment,
customer outcome, independent replication or calibration result is implied by this protocol.
Design and implementation limitations are in [the specification](EDAS_V2_SPECIFICATION.md).

## Questions and preregistered hypotheses

Before accessing a held-out set, publish a dated protocol commit with primary outcomes,
eligibility, exclusions, target domains, stopping rules and planned analysis. An explicit
domain profile and loss model must precede quantitative risk acceptance. Hypotheses:

| ID / question | Falsifiable hypothesis | Baseline / design | Primary outcome |
| --- | --- | --- | --- |
| H1: Does provenance-aware gating reduce unsupported authorization? | EDAS produces fewer unsupported proceed recommendations on the same independently labeled eligible cases | Paired EDAS vs green-only and documented human checklist | Unsupported proceed / all cases labeled non-proceed; paired difference |
| H2: Does it preserve useful decisions? | EDAS meets a predeclared noninferiority margin for eligible safe-proceed recommendations | Matched cases, blinded labels and policy assignments | Missed proceed / all safe-proceed cases; escalation rate by class |
| H3: Do independence checks matter? | Removing dependency-group checks increases unsupported proceed on copied-source cases | Full system vs one ablation on a locked dependency attack subset | Per-case disagreement, attack success / eligible attacks |
| H4: Does revision binding prevent stale advice? | Every injected evidence or policy change invalidates all affected pending approvals | Stateful fault injection vs no-revision-binding ablation | Stale approvals accepted / stale approval attempts |
| H5: Is probabilistic assessment calibrated? | A versioned forecasting component improves a predeclared proper score over base-rate forecasts | Only resolvable labeled forecasts with defensible probability models | Brier/log loss on all forecasts and calibration plots |
| H6: Does decision assistance improve outcomes? | Under a specified loss profile, assignment to EDAS lowers expected observed decision loss | Randomized eligible synthetic incidents; no high-risk real-world interventions | Weighted loss / eligible assigned incidents, plus cost and delay |

H1 is meaningful only with independent labels. Authored tests with expected outputs demonstrate
conformance to those expectations, not validation of the policy. H5 cannot currently be
tested: the MVP does not generate empirical probabilities. H6 requires a specified causal
estimand, outcome window, allocation method, and analysis of interference and attrition.

## Study design

1. Build a versioned generator with known synthetic mechanisms: common-source copying,
   measured observation error, selection/missingness, contradictions, stale evidence, uncertain
   attribution and harmless benign controls. Keep generator seeds and configuration immutable.
   Hold out entire source/dependency/incident families, not just rows from the same story.
2. Develop the policy on training cases. Freeze code, policy, priors/likelihoods, case selection,
   metrics and acceptance criteria before revealing held-out outcomes. An external curator
   should maintain a hidden adversarial set to reduce investigator leakage.
3. Use multiple baselines: permissive green-only (a weak negative control), manual four-step
   checklist, current repository policy where applicable, and a simple transparent rule policy.
   Give them equivalent available evidence, comparable time budgets and explicit permissions.
4. Randomize assignment or order for analyst-in-the-loop trials; block by incident family,
   severity and base rate. Reviewers should not see system identity while adjudicating cases.
   Record disagreements and adjudication rules; unresolved truth cannot be silently excluded.
5. Ablate one mechanism at a time: dependency checks, contradictory-evidence handling,
   revision binding, budget stops and human review. Do not run dangerous ablations on actual
   systems or real personal records. Report all planned variants, including failures.
6. For controlled CI experiments, pin interpreter, dependency lockfile, runner image, CPU/memory
   allocation and tool versions. Reproduce the original failure before applying a patch.
   Use untouched hidden behavioral tests to detect repairs that merely exploit visible tests.
7. Analyze paired outcomes by independent incident/dependency cluster. Use cluster bootstrap or
   an appropriate paired model, and state assumptions. Repeated execution of one fixture is
   a timing sample, not a new policy decision or independent incident.

Sample size follows the smallest practically meaningful loss reduction, anticipated paired
discordance, target error rates and desired interval precision, determined in a pilot without
reusing its data as the final test set. For rare unsafe events, plan upper confidence bounds.
Under independent, identically distributed Bernoulli trials, observing zero events among n
has a one-sided 95% upper bound `1 - 0.05**(1/n)`; cluster dependence invalidates that simple
interpretation. Zero events in authored cases is never a population safety guarantee.

Stop for demonstrated privacy/integrity failures, predeclared budget limits, or planned study
completion. Do not peek repeatedly until significance appears. Report interim rules, deviations
and all exclusion reasons. Consent and applicable ethics/privacy review are prerequisites for
any later human study. Public artifacts remain synthetic; none of the user's private records
belong in the repository.

## Evaluation matrix and measurement contracts

| Measure | Numerator / denominator or definition | Required limitation |
| --- | --- | --- |
| Case agreement | Recommendations matching independently adjudicated labels / all eligible labeled cases | Report unresolved labels and exclusions separately |
| Unsupported proceed | Proceed when label disallows it / all eligible non-proceed cases | Distinguish hard safety violation from benign overconfidence |
| Missed proceed | Unnecessary investigate/review/defer / all eligible safe-proceed cases | Prevent the trivial solution of refusing everything |
| Escalation precision/recall | Appropriate escalations / all escalations; appropriate escalations / all escalation-needed cases | Per-domain definitions and reviewer agreement |
| Decision loss | Sum of predeclared observed losses / all assigned eligible cases | Publish cost model and sensitivity; distinguish projected and realized loss |
| Brier score | Mean `(p-y)^2` across binary forecasts with outcomes | No calculation for vague statements or unlabeled outcomes |
| Log loss | Mean `-y log(p) -(1-y) log(1-p)` | Predeclare clipping or infinities; report impossible-event forecasts |
| Calibration | Observed outcome frequency vs forecast probability; intercept/slope and fixed-bin reliability plot | Publish denominators/intervals per bin; ECE is bin-sensitive |
| Coverage/selective risk | Cases receiving a recommendation / all eligible cases; loss among those receiving one | Report abstention and missingness alongside accuracy |
| Revision response | Invalidated stale approvals / all injected stale approvals | Include pending and already recorded advice |
| Audit integrity | Tamper/truncation cases detected / all injected attacks, plus clean logs falsely rejected / all clean logs | Trusted checkpoint threat model is explicit |
| Cost | Total analyst time, compute and provider spend / all eligible attempts, including failed/time-out attempts | Monetary usage is uninstrumented in the repository's provider loop |
| Latency | End-to-end median and p95/p99 from intake to actionable advice | State hardware, n, cold/warm conditions, concurrency, timeouts and censoring |
| Restoration | Recovered consistent runs / all crash points; RPO/RTO observed | No durable recovery demonstrated by the EDAS example |

Taxonomy: acquisition, provenance, authenticity, measurement, dependency, missingness,
interpretation, causal attribution, numeric/model misspecification, policy, authorization,
state/revision, audit integrity, privacy, resource exhaustion, external side effect and outcome
measurement. Give each failure a stable ID, minimized reproducer, severity, owner and fix link.
Preserve failures; do not edit expected outcomes just to make a regression pass.

## Adversarial review: expected behavior and executable coverage

All names below refer to methods in `tests/test_edas_reference.py`, except the final CI rows in
`tests/test_assurance_regressions.py`. These are empirical checks under the stated assumptions.

| Scenario | Expected safe behavior | Executable test / remaining gap |
| --- | --- | --- |
| Fabricated observation without attestation | Cannot qualify as ready | `test_fabricated_unattested_evidence_does_not_qualify`; forged attestation is not detected |
| No evidence | Unknown; investigate or eventually defer, never infer wrongdoing | `test_missing_evidence_is_unknown_not_wrongdoing` |
| Contradictory observation | Preserve and require review | `test_contradiction_requires_review` |
| Misleading correlation / copied reports | One dependency group cannot count as independent corroboration | `test_correlated_copies_count_as_one_group`; no causal inference engine |
| Confirmation bias | Require alternatives and falsifier | `test_confirmation_bias_requires_alternatives_and_falsifier`; quality of alternatives still needs a reviewer |
| Authority bias | Prestigious name gives no independent corroboration | `test_authority_label_does_not_replace_independent_sources` |
| Overconfidence | Reject probabilities outside [0,1] and nonfinite values | `test_extreme_and_nonfinite_probability_inputs_rejected` |
| Poor probability calibration | Require documented assumptions; do not label numerical validity calibration | `test_unsupported_likelihood_provenance_rejected`; empirical calibration study pending |
| Evidence tampering | Reject digest mismatch | `test_evidence_tampering_detected`; authenticity needs trusted acquisition |
| Privacy leakage | Refuse declared nonsynthetic and known secret-shaped payloads; keep prose out of logs | `test_non_synthetic_and_secret_shaped_payloads_refused`, `test_public_audit_contains_no_claim_or_payload_text`; mislabeled private data can bypass demo flags |
| False accusation / irreversible high harm | Require qualified review, never automated authorization | `test_high_stakes_accusation_never_automatically_authorized` |
| Unnecessary escalation | A clean low-risk control remains eligible for reversible advice | `test_low_risk_positive_control_avoids_unnecessary_escalation` |
| Excessive investigation cost | Stop without overspending | `test_excessive_cost_defers_without_spending` |
| Incorrect automated approval / stale or self approval | Block; no external execution endpoint | `test_stale_or_self_approval_refused` |
| Failure to revise after contradiction | Invalidate approval, reopen and review | `test_new_contradiction_invalidates_decision` |
| Truncated, reordered or modified audit | Detect against separately retained expected tip | `test_audit_mutation_reorder_and_truncation_detected_against_tip` |
| Retry exhaustion / repeated investigation | Leave unresolved with retained budget | `test_retry_exhaustion_defers` |
| Deadline, future/stale evidence or backward time | No ordinary approval; reject backward clock | `test_deadline_boundary_and_missing_evidence_never_pass`, `test_stale_future_and_backward_clock_inputs_refused` |
| Immediate safety hazard with incomplete proof | Recommend proportionate protection; no truth claim | `test_immediate_safety_action_does_not_require_proof` |
| Invalid mutation / unauthorized evidence submission | No state or log change | `test_rejected_mutations_do_not_append_audit_or_change_revision` |
| False-green repair with missing evidence | CI green cannot substitute for baseline/gates/skip comparison | `test_unknown_skip_comparison_never_verifies`, `test_green_ci_does_not_replace_missing_baseline`, `test_any_missing_gate_blocks_verified_outcome` |
| Explicit failed relevant/lint/type gate | Evaluation cannot pass | `test_evaluator_fails_on_each_explicit_failed_check` |
| Unsafe patch | Reject outside-repo paths, `.git` paths and symlinks | `test_forbidden_patch_paths_and_symlinks`; not exhaustive patch-parser assurance |
| Timeout / missing target | Fail closed | `test_timeout_and_missing_target_fail_closed`; synthetic result injection, not a process-kill test |
| State inconsistency | Rejection wins over human flag; forbidden codes block verification; terminal automation stays stopped | `test_human_approval_cannot_override_policy_rejection`, `test_forbidden_codes_and_flag_cannot_disagree_into_success`, `test_terminal_state_cannot_resume_automation` |

## Reproduction and independent replication

See [implementation commands](EDAS_V2_IMPLEMENTATION.md). A successful replication needs:

- A fresh clone pinned to the delivered commit; run source and artifact hash checks before tests.
- An independently created environment with declared OS/interpreter/dependency versions and
  no private data or inherited local artifacts. Retrieve the pinned base for before/after tests.
- Original commands, complete exit codes/stdout/stderr, fixture and policy hashes, exclusions,
  failed collection attempts and environment metadata retained under a new replication label.
- Same deterministic per-case decisions and invariant results, including the expected failing
  pre-fix tests. Latencies may differ; they require a separately matched measurement protocol.
- A reviewer other than the implementation author who can reproduce without unstated steps,
  inspect all denominators, challenge labels and add unseen cases. Passing the same authored
  cases is repeatability; independent replication of policy usefulness requires new cases.

## Evidence required before using stronger labels

| Label | Necessary evidence before making the claim | Evidence currently missing |
| --- | --- | --- |
| Research-grade **study** | Dated preregistration; precise questions/estimands; independently curated held-out cases; defensible sample-size and uncertainty analysis; meaningful baselines/ablations; blinded adjudication; complete failure/exclusion data; frozen code/data/policy/environment; reproducible analysis and independent replication | All population-level experiments and independent replication; current results are regression fixtures |
| Enterprise-ready **for a stated use and deployment** | Threat model and independent review; real IAM/segregation; durable transactional state and outbox; trusted evidence acquisition/checkpoints; privacy/retention controls; dependency/build provenance; load/soak/fault tests meeting approved SLOs; tested restore/rollback and incident playbooks; restricted canary with accountable risk acceptance; support/change controls and operation over a relevant period | Most controls absent from EDAS reference; existing CI server components were inspected but not validated locally as enterprise controls |
| Formally assured **property under assumptions** | Formal state/data specification and threat/environment assumptions; explicit safety/liveness properties; checked proof or model-checking artifacts with tool versions/bounds; reproducible commands and independent proof review; traceability/refinement from model to deployed implementation; clear residual unproved properties | No formal specification/proof tool artifacts or refinement argument |

These labels are scoped statements, not awards from a single score or test count. Even a
correct proof of a model cannot prove a source truthful, a utility model ethical, or real-world
decisions beneficial. The present implementation qualifies as a tested synthetic prototype.
