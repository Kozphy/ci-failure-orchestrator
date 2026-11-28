# GitHub CI Reliability Audit — Report

| Field | Value |
| --- | --- |
| Client / company | `[CLIENT]` |
| Repository | `[OWNER/REPO]` |
| Engagement ID | `[ID]` |
| Report date | `[YYYY-MM-DD]` |
| Price | US$299 |
| Delivery SLA | 3 business days from complete intake |
| Author | `[YOUR NAME]` · BrightPath Global |
| Refund note | Full refund if this report contains no actionable finding |

**Status:** Draft — do not send until every `[PLACEHOLDER]` is replaced with evidence from this engagement.  
**Not a certification.** Recommendations are not executed unless separately scoped.

---

## 1. Executive summary

In 3–6 sentences:

- What was reviewed (workflows, run count, date window)
- Top reliability risk
- Whether findings are actionable (yes/no — drives refund)
- Recommended next step for the client (fix themselves / optional follow-on)

**Actionable findings count:** `[N]`  
**Refund applicable?** `[yes / no]` — “no” only if ≥1 finding the client can act on without buying more work.

---

## 2. Scope

| Item | Agreed |
| --- | --- |
| Repository | 1: `[OWNER/REPO]` |
| Workflows (≤5) | 1. … 2. … 3. … 4. … 5. … |
| Runs reviewed (≤30) | `[N]` |
| Evaluation window | `[start]` → `[end]` |
| Access method | sanitized logs / public data / fine-grained Actions read-only token |

### Out of scope (this engagement)

- Guaranteed repair, merge, or deploy
- Continuous monitoring
- Security/compliance certification
- Other repositories or CI providers

---

## 3. Evidence sources

List exactly what you inspected (run URLs, log files, export IDs). Treat logs as untrusted data.

1. …
2. …

---

## 4. Findings summary

| ID | Severity | Category | Workflow / job | Actionable? | Evidence pointer |
| --- | --- | --- | --- | --- | --- |
| F-1 | high / medium / low | test / flake / config / deps / timeout / env / other | | yes / no | run URL or log line |
| F-2 | | | | | |

Detail each finding in `FINDINGS_TEMPLATE.md` (or inline appendix). Cap narrative length; prefer evidence over speculation.

---

## 5. Frequency and recurrence

| Pattern | Count in sample | Notes |
| --- | ---: | --- |
| Distinct failing workflows | | |
| Repeated same failure signature | | |
| Cancels / timeouts | | |
| Apparent re-run without fix | | |

Sample size: `[N]` runs. Do not extrapolate beyond the sample.

---

## 6. Recommendations

Link to `RECOMMENDATIONS_TEMPLATE.md`. List at most **five** recommendations, each tied to a finding ID.

| Rec ID | Finding | Action | Owner suggestion | Effort (S/M/L) |
| --- | --- | --- | --- | --- |
| R-1 | F-1 | | | |

---

## 7. What we did not verify

Explicit gaps (missing logs, private jobs, incomplete token scope, language outside tested paths, etc.).

---

## 8. Security and access

- Secrets redacted / not stored by BrightPath beyond delivery needs
- Token (if any): client-created, Actions + Metadata read-only, ≤7 day expiry — revoke after delivery
- No merges performed

---

## 9. Deliverables checklist

- [ ] This Markdown report
- [ ] JSON findings file (`findings.json` from FINDINGS template schema)
- [ ] One written clarification round remaining: `[unused / used]`

---

## 10. Optional next steps (not included in US$299)

Only mention if the client asks or clearly needs execution help. Do not invent upsells as included.

- Implement top 1–2 recommendations (separate quote)
- Second repository audit
- Monthly CI care (only after paid demand)

---

## Appendix A — Run index

| # | Workflow | Run ID / URL | Conclusion | Used in finding |
| ---: | --- | --- | --- | --- |
| 1 | | | | |

## Appendix B — Classifier / tool notes

If `actions-doctor` or similar was used: state that labels are **heuristic**, human-checked for this report.
