# Claim registry

Every research claim this repository makes is listed here. Anything not listed here is not claimed.
`python -m research.claims` checks each row against the committed raw results and fails if a row
is inconsistent with them. CI runs it with `--require-committed`.

## Statuses

| Status | Meaning |
| --- | --- |
| SUPPORTED | Measured, within the stated scope, on the frozen test split, from a clean-tree run whose raw outputs are committed. Every number in the claim is a machine check. |
| PARTIALLY_SUPPORTED | The data point in the claimed direction, but the evidence is weaker than the claim: too few discordant cases, synthetic only, or only part of the hypothesis was observed. |
| PENDING | Not yet measured. The experiment that would test it is described. |
| UNSUPPORTED | Measured, and the data do not support it, or a counter-example was observed. |

**Scope of every claim below.** Unless a row says otherwise, the cases are synthetic or fixture
cases written by the system's developer, the repair candidates are scripted rather than
model-generated, verification is local (no real CI run confirms a fixture repair), and the external
validation level is E0/E1 (`EXTERNAL_VALIDATION.md`). None of these claims is production evidence.
Confidence values produced by the classifier are ordinal levels, not calibrated probabilities.

## Registry

Experiment `rq1-rq2-test-20261007T123008Z-6a88f15b` is the clean-tree rerun of the first default run.
`python -m research.compare_runs` shows the two runs agree on every non-volatile output (see
`RESEARCH_PLAN.md`, deviations log).

| ID | Claim | Status | Experiment | Checks | Scope and caveats |
| --- | --- | --- | --- | --- | --- |
| C1 | On the 10 test-split repair cases, P accepted an incorrect repair in 3 cases; R-GREEN-k and R-GREEN-1 (accept the first candidate that turns CI green) each did so in 5. | SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `repair/P/n_cases == 10; repair/P/green_but_wrong_rate/k == 3; repair/R-GREEN-k/green_but_wrong_rate/k == 5; repair/R-GREEN-1/green_but_wrong_rate/k == 5` | Descriptive counts on synthetic fixtures with scripted candidates. Wilson 95% intervals overlap widely (P 0.11-0.60, R-GREEN-k 0.24-0.76). |
| C2 | H1: P accepts fewer incorrect repairs than a CI-green acceptance rule, at the cost of more human escalations. | PARTIALLY_SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `comparisons/repair/P vs R-GREEN-k/incorrect_acceptance/paired_bootstrap/estimate == -0.2; comparisons/repair/P vs R-GREEN-k/incorrect_acceptance/mcnemar/discordant == 2; comparisons/repair/P vs R-GREEN-k/incorrect_acceptance/mcnemar/p_value == 0.5; repair/P/human_escalation_rate/k == 0` | Direction only. Two discordant cases, McNemar p = 0.5, paired bootstrap interval [-0.5, 0.0] includes zero. The escalation half of H1 was not observed: no system escalated any case. Synthetic only. |
| C3 | Of the 19 incorrect candidates that turned the visible CI command green, a CI-green-only rule accepts all 19 and P's acceptance rule (policy APPROVE and local verification) accepts 8; neither rejects any of the 10 correct green candidates. | SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `candidate_gates/gates/ci_green_only/accepted_incorrect/k == 19; candidate_gates/gates/ci_green_only/accepted_incorrect/n == 19; candidate_gates/gates/policy_and_verification/accepted_incorrect/k == 8; candidate_gates/gates/policy_and_verification/rejected_correct/k == 0; candidate_gates/gates/policy_and_verification/rejected_correct/n == 10; candidate_gates/gates/ci_green_only/rejected_correct/k == 0` | Candidate-level, order-independent view over scripted candidates written by the developer, including the fake-fix shapes. Candidates are not independent (several per case). Says nothing about how often a model would propose such candidates. |
| C4 | Visible CI turning green is not sufficient evidence of a correct repair. | SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `candidate_gates/green_incorrect == 19; candidate_gates/n_green_candidates == 29` | Existence claim: 19 of 29 green candidates fail the hidden oracle or are fake fixes. The proportion reflects how the candidates were written, not a real-world rate. |
| C5 | H2 (case level): removing the policy gate or the verification layer from P raises the incorrect-acceptance rate. | UNSUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `repair/P-no-policy/green_but_wrong_rate/k == 3; repair/P-no-verification/green_but_wrong_rate/k == 3; repair/P/green_but_wrong_rate/k == 3` | No case-level difference was observed. Each removal does accept more incorrect candidates when candidates are scored independently (C6), but with the first green candidate terminal and this candidate order, the remaining gate stopped the same cases. Not evidence that either layer is useless. |
| C6 | Candidate level: each of the policy gate and the verification layer rejects incorrect green candidates that the other accepts. | SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `candidate_gates/gates/policy_only/accepted_incorrect/k == 9; candidate_gates/gates/verification_only/accepted_incorrect/k == 12; candidate_gates/gates/policy_and_verification/accepted_incorrect/k == 8` | Policy alone accepts 9 of 19 incorrect green candidates, verification alone 12, both together 8. Small counts; scripted candidates. |
| C7 | H2 (retry): removing the retry budget lowers the verified-repair rate. | PARTIALLY_SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `repair/P-no-retry/verified_repair_rate/k == 4; repair/P/verified_repair_rate/k == 5` | One case differs (4/10 vs 5/10). The size of the effect depends on the seeded candidate order. |
| C8 | P's acceptance rule can accept a fake fix: it accepted a candidate that swallows the exception behind the failing test. | SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `repair/P/unsafe_remediation_rate/k == 1` | Counter-example to "policy and verification block every fake fix" (`test-repair-port-default`, kind `exception_swallowed`). Reported, not fixed after evaluation; see `analysis/error_analysis.md`. |
| C9 | H3: on multi-failure cascades, dependency-graph ranking (B3) identifies the root-cause stage more often than the latest visible failure (B0): 11 of 13 versus 0 of 13. | PARTIALLY_SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `diagnosis/B3/root_stage_accuracy_multi_failure/k == 11; diagnosis/B3/root_stage_accuracy_multi_failure/n == 13; diagnosis/B0/root_stage_accuracy_multi_failure/k == 0; comparisons/diagnosis/B3 vs B0/root_correct_multi_failure/mcnemar/p_value < 0.01` | Large difference on authored cascades, but in every multi-failure test case the root is the earliest failed stage, which B3's graph ordering favours and B0 by definition ignores. Construct-validity threat; real cascades are needed. |
| C10 | B3 assigns the correct failure class more often than B0 on the 16 diagnosis test cases (7 versus 2). | PARTIALLY_SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `comparisons/diagnosis/B3 vs B0/class_correct/rate_a == 0.4375; comparisons/diagnosis/B3 vs B0/class_correct/rate_b == 0.125; comparisons/diagnosis/B3 vs B0/class_correct/mcnemar/p_value == 0.0625` | Five discordant cases, all favouring B3; McNemar p = 0.0625. Both use the same rule-based classifier, which cannot predict `integration_test` or `cross_job_dependency`. |
| C11 | H4: bounded repository context (B2) or dependency information (B4) improves a log-only model (B1). | PENDING | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `diagnosis/B1/status == "NOT_RUN"; diagnosis/B2/status == "NOT_RUN"; diagnosis/B4/status == "NOT_RUN"` | NOT YET MEASURED. Needs a claim-eligible model run (provider `command` or `recorded`, with model name and version in the manifest). The harness, prompts and parsers exist. |
| C12 | The repair harness reproduces the real product loop: replaying P's rules over per-candidate facts gives the same decision as running P. | SUPPORTED | `rq1-rq2-test-20261007T123008Z-6a88f15b` | `fidelity/checked == 10; fidelity/agree == 10; annotation/count == 0` | Harness-validity claim, not a performance claim. 10 of 10 cases agree; fixture QA found no annotation issues. |
| C13 | Any of the above holds on real CI failures from this repository or public open-source projects. | PENDING | - | - | REQUIRES EXTERNAL VALIDATION. No real-world case has been labelled or frozen (`DATASET_CARD.md`). |
| C14 | A maintainer, external user or pilot organisation has confirmed a diagnosis or repair. | PENDING | - | - | REQUIRES EXTERNAL VALIDATION. No external event is recorded in `external_validation_registry.json`. |
| C15 | Cost and latency of model-based diagnosis or repair. | PENDING | - | - | NOT YET MEASURED. No model was called. Harness latencies in `metrics.json` are local fixture timings, not production CI latency. |

## Rules for changing this file

- A status may move only when a new committed experiment supports the move; cite it in the row.
- Do not delete a claim that turned out UNSUPPORTED. Change its status and keep the row.
- A claim that rests on development-split or holdout-tuned results cannot be SUPPORTED.
- When a baseline changes after evaluation, record a new version in `baselines/registry.json` and
  rerun; do not edit numbers here by hand.
