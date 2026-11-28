# Findings — GitHub CI Reliability Audit

| Field | Value |
| --- | --- |
| Repository | `[OWNER/REPO]` |
| Engagement ID | `[ID]` |
| Author | `[YOUR NAME]` |
| Date | `[YYYY-MM-DD]` |

One finding = one evidence-backed problem. Do not invent severity or recurrence.

---

## Finding card (copy per finding)

### F-[N]: `[short title]`

| Field | Value |
| --- | --- |
| Severity | `high` / `medium` / `low` |
| Category | `test_failure` / `flaky_test` / `configuration` / `dependency` / `timeout` / `network` / `environment` / `other` |
| Workflow | `[workflow file or name]` |
| Job / step | `[job]` / `[step]` |
| First seen in sample | `[date or run]` |
| Recurrence in sample | `[count]` of `[N]` runs |
| Actionable | `yes` / `no` |
| Confidence | `high` / `medium` / `low` (human judgment; say why) |

**Evidence (required)**

- Run URL or log file:
- Exact line / message (quote ≤3 lines):
- ```
  [paste]
  ```

**What it means**

[2–4 sentences. Observed behavior only.]

**What it is not**

[Optional. Avoid overclaiming root cause.]

**Suggested validation**

Command or check the client can run locally or in Actions:

```bash
[command or “re-run job X after change Y”]
```

**Validation status:** `not_executed` (default for audit) / `client_confirmed`

---

## JSON export schema (`findings.json`)

Deliver alongside the Markdown report. Fill from cards above; omit inventing fields.

```json
{
  "schema": "ci-reliability-audit.findings.v1",
  "repository": "OWNER/REPO",
  "engagement_id": "",
  "generated_at": "YYYY-MM-DD",
  "runs_reviewed": 0,
  "findings": [
    {
      "id": "F-1",
      "title": "",
      "severity": "medium",
      "category": "test_failure",
      "workflow": "",
      "job": "",
      "step": "",
      "recurrence_in_sample": 0,
      "sample_size": 0,
      "actionable": true,
      "confidence": "medium",
      "evidence": {
        "run_url": "",
        "quote": ""
      },
      "meaning": "",
      "validation_status": "not_executed"
    }
  ]
}
```

---

## Severity guide (use consistently)

| Severity | Use when |
| --- | --- |
| high | Blocks main/release repeatedly in sample, or clear secret/config footgun |
| medium | Recurring waste (reruns, flaky job) or clear fix path |
| low | One-off or cosmetic; still mention if actionable |

## Actionable = refund gate

A finding is **actionable** if the client can change code, workflow, tests, or process based on this evidence without buying more work from you. If `actionable` count is 0 → refund applies.
