# CI Reliability Audit — Delivery SOP (pilot v1.0)

**Owner:** Kozphy operator. **Scope:** US$149, one authorized GitHub repository, up to 5 named workflows and 30 recent runs. **Target:** 3 Taiwan business days after confirmed payment, approved scope and usable data. No emergency SLA.

## Gate 0 — qualify before payment
- Identify a permitted point of contact and confirm repository ownership or written audit authorization.
- Confirm GitHub Actions usage, up to five workflows, available 30 runs, requested outcome, and access method.
- Prefer public metadata or client-generated **sanitized** logs / `ci-audit.export.v1`. No public issue uploads or credential sharing.
- Confirm terms, refund policy, local legal provider identity, capacity, and approved secure payment channel. Do not solicit payment until these are ready.
- Record order identifier privately; never record customer names, contact details, secrets or private repository URLs in a public tracker.

## Day 0 — accept order
- Record written scope acceptance, payment confirmation, secure data-sharing consent and delivery channel.
- Start the 3-business-day clock only when the above and usable data are present; otherwise explain missing prerequisites and agree revised start.
- Check that any third-party analysis or AI processing is explicitly authorized; default **no external LLM upload of customer code/logs**.

## Day 1 — intake and analysis
1. Inventory the permitted repository, workflow names, run IDs and date interval.
2. Record data provenance, missing runs, exclusions and limitations.
3. Redact secrets before storage or analysis and inspect samples manually; avoid copying full logs where possible.
4. Perform read-only categorization and reliability review. Never run customer-supplied executable code, `verify` commands, or untrusted CI steps on the operator workstation.

## Day 2 — interpret and validate
- Manually validate classifications and findings against supporting evidence. A flaky indicator is not a proven flaky root cause.
- Avoid claiming GitHub billed savings from estimated runner minutes; distinguish duration estimates from invoices.
- Give no more than five prioritized recommendations with risk, effort, confidence, evidence reference and owner suggestion.
- Label unknown or incomplete evidence; do not convert missing evidence into a PASS.

## Day 3 — QA and secure handoff
- Produce Markdown and structured JSON deliverables; review for sensitive strings and confidential repository identifiers.
- Check totals, denominator, timezones, classification uncertainty, links/run IDs, scope and limitations.
- Deliver over agreed private secure channel. Obtain delivery acknowledgment; offer one written clarification round.

## Acceptance and cleanup
- Apply the criteria in [acceptance-criteria.md](acceptance-criteria.md) and [terms.md](terms.md).
- Correct material factual errors or address refund eligibility; preserve support notes without confidential payloads.
- Revoke temporary access promptly after use. Delete raw customer data 14 calendar days after acceptance or clarification-window closure (whichever is later), unless lawful retention or written agreement requires otherwise.
- Do not publish client proof, testimonials or company names without express written permission.

## Exceptions / stop work
Pause immediately if credentials appear in logs, authority is unclear, permission is greater than read-only, data appears compromised, or confidential data would be transferred without approval. Notify the client via agreed secure channel and agree a safe path or refund. Never promise production-safe automated remediation.
