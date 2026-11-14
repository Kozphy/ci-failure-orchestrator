# Evidence to metric mapping

| Dashboard field | Source | When N/A |
| --- | --- | --- |
| Total CI runs | `analyze_export(...).totals.completed` from optional `ci-audit.export.v1` | No export, bad schema, or unreadable file |
| Failed CI runs | `totals.failed` from that export | Same |
| CI failure rate | `totals.failure_rate` | Same |
| Verified repair rate | `compute_remediation_metrics` → `verified_repair_rate` | No attempted `remediation.json` |
| Policy rejection rate | `policy_rejection_rate` | No attempted repairs |
| Human review required | `human_escalation_rate` and count of `HUMAN_REVIEW_REQUIRED` | No attempted repairs |
| Evidence completeness rate | Share of runs with `evidence-report.json` whose `remaining_risks` is empty | No evidence reports |
| Average verification duration | Mean `failure_received_at` → `decided_at` for `VERIFIED_FIXED`; else mean `metrics-summary` duration with an explicit note | Neither duration exists |

Integrity:

- `file_sha256` = SHA-256 of raw bytes.
- `canonical_json_sha256` = SHA-256 of `canonical_json(parsed)` from `foundation.durable`.
- A hash mismatch means the file bytes changed relative to a recorded digest. It is not a third-party provenance proof.

`POLICY_APPROVED` is never counted as `VERIFIED_FIXED`.
