## diagnosis

_Generated from experiment `rq1-rq2-test-20261007T123008Z-6a88f15b` (dataset 1.0.0, splits test, commit `ab5f471410b6`). Synthetic cases only._

| System | N scored | Class accuracy [95% CI] | Macro-F1 [95% CI] | Root-stage accuracy, multi-failure [95% CI] |
|---|---|---|---|---|
| B0 | 16 | 0.125 [0.000, 0.312] | 0.125 [0.000, 0.225] | 0.000 [0.000, 0.228] (0/13) |
| B1 | NOT RUN (no model provider configured (provider: none)) |  |  |  |
| B2 | NOT RUN (no model provider configured (provider: none)) |  |  |  |
| B3 | 16 | 0.438 [0.188, 0.688] | 0.296 [0.135, 0.495] | 0.846 [0.578, 0.957] (11/13) |
| B4 | NOT RUN (no model provider configured (provider: none)) |  |  |  |

## repair

_Generated from experiment `rq1-rq2-test-20261007T123008Z-6a88f15b` (dataset 1.0.0, splits test, commit `ab5f471410b6`). Synthetic cases only._

| System | N | Incorrect acceptance | Unsafe (fake fix) acceptance | Verified repair | Escalated | Accepted |
|---|---|---|---|---|---|---|
| P | 10 | 0.300 [0.108, 0.603] (3/10) | 0.100 [0.018, 0.404] (1/10) | 0.500 [0.237, 0.763] (5/10) | 0.000 [0.000, 0.278] (0/10) | 0.800 [0.490, 0.943] (8/10) |
| P-composed | 10 | 0.300 [0.108, 0.603] (3/10) | 0.100 [0.018, 0.404] (1/10) | 0.500 [0.237, 0.763] (5/10) | 0.000 [0.000, 0.278] (0/10) | 0.800 [0.490, 0.943] (8/10) |
| P-no-policy | 10 | 0.300 [0.108, 0.603] (3/10) | 0.100 [0.018, 0.404] (1/10) | 0.500 [0.237, 0.763] (5/10) | 0.000 [0.000, 0.278] (0/10) | 0.800 [0.490, 0.943] (8/10) |
| P-no-retry | 10 | 0.300 [0.108, 0.603] (3/10) | 0.100 [0.018, 0.404] (1/10) | 0.400 [0.168, 0.687] (4/10) | 0.000 [0.000, 0.278] (0/10) | 0.700 [0.397, 0.892] (7/10) |
| P-no-verification | 10 | 0.300 [0.108, 0.603] (3/10) | 0.100 [0.018, 0.404] (1/10) | 0.500 [0.237, 0.763] (5/10) | 0.000 [0.000, 0.278] (0/10) | 0.800 [0.490, 0.943] (8/10) |
| R-GREEN-1 | 10 | 0.500 [0.237, 0.763] (5/10) | 0.300 [0.108, 0.603] (3/10) | 0.400 [0.168, 0.687] (4/10) | 0.000 [0.000, 0.278] (0/10) | 0.900 [0.596, 0.982] (9/10) |
| R-GREEN-k | 10 | 0.500 [0.237, 0.763] (5/10) | 0.300 [0.108, 0.603] (3/10) | 0.500 [0.237, 0.763] (5/10) | 0.000 [0.000, 0.278] (0/10) | 1.000 [0.722, 1.000] (10/10) |

Fidelity check (real P loop vs replayed rules): 10/10 cases agree.

## ablation

_Generated from experiment `rq1-rq2-test-20261007T123008Z-6a88f15b` (dataset 1.0.0, splits test, commit `ab5f471410b6`). Synthetic cases only._

| Ablation | Removed | Apparent repair rate | Incorrect acceptance | P minus ablation, incorrect acceptance [95% CI] | McNemar p |
|---|---|---|---|---|---|
| P-no-policy | policy gate | 0.800 | 0.300 | 0.000 [0.000, 0.000] | n/a |
| P-no-verification | verification layer | 0.800 | 0.300 | 0.000 [0.000, 0.000] | n/a |
| P-no-retry | retry budget (k=1) | 0.700 | 0.300 | 0.000 [0.000, 0.000] | n/a |

## gates

_Generated from experiment `rq1-rq2-test-20261007T123008Z-6a88f15b` (dataset 1.0.0, splits test, commit `ab5f471410b6`). Synthetic cases only._

| Acceptance rule | Accepts incorrect green candidates | Rejects correct ones |
|---|---|---|
| ci_green_only | 1.000 [0.832, 1.000] (19/19) | 0.000 [0.000, 0.278] (0/10) |
| policy_and_verification | 0.421 [0.231, 0.637] (8/19) | 0.000 [0.000, 0.278] (0/10) |
| policy_only | 0.474 [0.273, 0.683] (9/19) | 0.000 [0.000, 0.278] (0/10) |
| verification_only | 0.632 [0.410, 0.809] (12/19) | 0.000 [0.000, 0.278] (0/10) |

## errors

_Generated from experiment `rq1-rq2-test-20261007T123008Z-6a88f15b` (dataset 1.0.0, splits test, commit `ab5f471410b6`). Synthetic cases only._

| Error class | Count | % of outcomes | Systems | Example cases |
|---|---|---|---|---|
| wrong_failure_class | 7 | 6.9 | B0, B3 | test-diag-artifact-name, test-diag-integration-api, test-diag-migration-column |
| wrong_root_cause | 13 | 12.7 | B0 | test-diag-assertion-loud-deploy, test-diag-disk-full, test-diag-dns-checkout |
| insufficient_evidence | 16 | 15.7 | B0, B3 | test-diag-assertion-loud-deploy, test-diag-disk-full, test-diag-dns-checkout |
| dependency_reasoning_failure | 2 | 2.0 | B3 | test-diag-flaky-websocket, test-diag-secret-leak |
| unsafe_repair | 11 | 10.8 | P, P-composed, P-no-policy, P-no-retry, P-no-verification, R-GREEN-1, R-GREEN-k | test-repair-date-window, test-repair-port-default, test-repair-slugify |
| policy_false_negative | 4 | 3.9 | P, P-composed, P-no-retry, P-no-verification | test-repair-port-default |
| verification_gap | 14 | 13.7 | P, P-composed, P-no-policy, P-no-retry, P-no-verification, R-GREEN-1, R-GREEN-k | test-repair-backoff, test-repair-discount |
| flaky_or_nondeterministic | 2 | 2.0 | B0, B3 | test-diag-flaky-websocket |
