# Foundation benchmark metrics

All metrics expose `{numerator, denominator, value}` and treat zero denominators
as `n/a` (not NaN).

Dataset is **SYNTHETIC**; percentages are descriptive of the included fixtures
only.

| Metric | Numerator | Denominator |
| --- | --- | --- |
| `case_pass_rate` | cases with all assertions passing | all executed cases |
| `required_pass_rate` | required cases passing | required cases |
| `classification_accuracy` | classification assertions that match golden labels | cases in `classification` population |
| `repair_success_rate` | repairable cases with `technical_status=PASS` | cases in `repairable` population |
| `retry_rate` | retry-population cases with `retries > 0` | cases in `retry` population |
| `mean_attempts` | sum of observed attempts | cases with attempt observations |
| `policy_outcome_accuracy` | matching `policy_outcome` assertions | cases in `policy` population |
| `security_control_success_rate` | security-population cases that passed | cases in `security` population |
| `escalation_accuracy` | escalation-population cases that passed | cases in `escalation` population |
| `audit_completeness_rate` | cases with passing `audit_completeness` | cases in `audit` population |
| `false_remediation_count` | cases with technical PASS that failed golden expectations | all cases (count metric) |

## Escalation quality

Track both missed escalations and unexpected escalations via policy/escalation
assertion failures — do not optimize solely for maximum escalation.

## Model cost

Deterministic suite: `model_cost = NOT_APPLICABLE`.
