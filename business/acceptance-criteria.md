# Acceptance criteria — US$149 CI Reliability Audit

A report is **delivered**, not automatically guaranteed to reduce CI failures. For each accepted order the following must be true:

| ID | Required check | Evidence |
| --- | --- | --- |
| AC-01 | Written authority, scope and payment confirmed | Private order record |
| AC-02 | One repository, no more than 5 workflows / 30 runs | Inventory and analyzed counts |
| AC-03 | Only authorized read-only sources accessed | Intake and access record |
| AC-04 | Manual review and classifications labeled appropriately | Report methods + confidence |
| AC-05 | Markdown and JSON reports provided securely | Delivery confirmation |
| AC-06 | Each recommendation linked to a run/log datum or explicitly labeled hypothesis | Evidence references |
| AC-07 | Up to 5 ranked recommendations, including limitations and next step | Report |
| AC-08 | No secrets or personal information exposed in delivered public examples | Redaction review |
| AC-09 | One written clarification round offered for 5 business days | Handoff message |
| AC-10 | Deletion/revocation policy communicated | Closure checklist |

**Non-criteria:** automatic code fixes, production deployments, guaranteed savings, compliance certification, unlimited support, or proof of specific customer outcomes.

**Review and correction:** Client has five business days after delivery to request one written clarification or correction of a factual error. Provider acknowledges within two business days and agrees a reasonable resolution timeline. Silence does not waive statutory rights. See [terms.md](terms.md) for refund and dispute treatment.

**QA signoff:** Operator records PASS/FAIL/NOT_APPLICABLE with rationale for each AC item privately before handoff. Never mark missing evidence as PASS.
