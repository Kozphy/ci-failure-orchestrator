# Agent Threat Model

The harness assumes the LLM is an untrusted proposal source. The deterministic
system, policy gate, verification, rollback, human approval, and audit retain
authority.

## 1. Hallucinated evidence

- **Threat:** Model cites evidence that does not exist or misrepresents observed evidence.
- **Mitigation:** Evidence references are validated as non-empty strings and, where
  applicable, checked against expected namespaces. Diagnosis output is validated
  before any proposal is built.
- **Remaining limitation:** Validation cannot prove that a referenced evidence item
  is semantically correct; it only checks structure and known namespaces.
- **Test:** `test_valid_structured_output`, `test_missing_limitations_weak_evidence_fails_closed_via_human_review`.

## 2. Invented incident type

- **Threat:** Model returns an incident label the system does not recognize.
- **Mitigation:** `validate_and_build_diagnosis` rejects unknown `incident_type`
  values and fails closed.
- **Remaining limitation:** Taxonomy must be kept current; new real incident types
  require an explicit update.
- **Test:** `test_unknown_incident_type_fails_closed`.

## 3. Unsupported remediation

- **Threat:** Model recommends an action the harness cannot safely support.
- **Mitigation:** `build_proposal` rejects unknown actions. The policy gate and
  evaluator also reject unsupported mutable actions defensively.
- **Remaining limitation:** Supported action set is curated; new safe actions must
  be added explicitly.
- **Test:** `test_unsupported_action_fails_closed`, `test_policy_blocks_forbidden_action`,
  `test_forbidden_action_detected_by_evaluator`.

## 4. Prompt injection from evidence text

- **Threat:** Evidence text or logs contain instructions that influence model output.
- **Mitigation:** The harness treats model output as untrusted structured data and
  validates it independently of how it was produced. Evidence is passed as data,
  not as instructions that can bypass validation.
- **Remaining limitation:** A provider may still be influenced by prompt injection;
  the harness limits the damage by validating and gating the result.
- **Test:** Deterministic validation tests do not depend on prompt content, only on
  output structure.

## 5. Overconfidence

- **Threat:** Model reports high confidence without adequate basis.
- **Mitigation:** Confidence is range-checked, and low confidence with missing
  limitations forces human review. Policy and evaluator treat weak confidence as
  a reason to escalate.
- **Remaining limitation:** Confidence is self-reported; calibration must be checked
  empirically against measurements.
- **Test:** `test_confidence_out_of_range_fails_closed`, `test_low_confidence_requires_human_review`.

## 6. Unsafe confidence escalation

- **Threat:** Model or harness upgrades confidence across attempts without new evidence.
- **Mitigation:** The harness does not amplify model confidence on its own; policy
  gates and evaluators treat low confidence as an escalation signal, not a retry
  signal.
- **Remaining limitation:** Confidence inflation across multiple model calls must be
  monitored with measurements.
- **Test:** Policy gate behavior is covered by `test_policy_escalates_for_low_confidence`.

## 7. Tool escalation

- **Threat:** Proposal attempts to escalate authority to execute a dangerous action.
- **Mitigation:** The harness never grants execution authority to the model. Mutable
  actions require policy, preview, verification, rollback, and human approval where
  appropriate.
- **Remaining limitation:** If a new dangerous action is added to the supported set
  without corresponding policy, the boundary weakens.
- **Test:** Forbidden action tests cover this class.

## 8. Policy bypass

- **Threat:** Some path in the harness allows a proposal to skip the policy gate.
- **Mitigation:** `BoundedRepairAgentHarness.run` routes proposals through
  `_policy` before any preview/verification path. The policy gate is centralized.
- **Remaining limitation:** Future code paths could bypass the gate if they construct
  results without calling policy.
- **Test:** Demo and harness flow tests assert policy disposition is set.

## 9. Retry loop

- **Threat:** Harness retries indefinitely on failure.
- **Mitigation:** Retry budget is bounded; exceeding it escalates. Loop exit is
  explicit in `agent_loop.py` and related state machine logic.
- **Remaining limitation:** Budget parameters must be chosen carefully for real use.
- **Test:** Retry-state tests in the repository cover bounded retry behavior.

## 10. Verification gaming

- **Threat:** Model or worker claims verification success without actually satisfying
  gates.
- **Mitigation:** Verification is computed from deterministic checks, not from model
  self-report. `VerificationResult` success is defined by canonical predicates.
- **Remaining limitation:** Deterministic checker coverage must be maintained.
- **Test:** Verification and execution tests in the repository cover this contract.

## 11. Agent self-approval

- **Threat:** Model approves its own proposal and treats that as sufficient.
- **Mitigation:** The model is a proposal source only. Approval requires policy,
  verification, and, where required, human confirmation.
- **Remaining limitation:** If a new integration treats model output as approval,
  the boundary is violated.
- **Test:** Harness flow asserts proposals do not execute without policy disposition.

## 12. Audit tampering

- **Threat:** Agent or operator alters the record of what happened.
- **Mitigation:** Audit uses append-only, hash-chained records in the repository's
  existing audit infrastructure. Significant transitions are recorded.
- **Remaining limitation:** Absolute protection depends on storage controls outside
  the harness; the harness avoids storing sensitive material.
- **Test:** Audit record creation is covered by demo and audit tests.

## 13. Sensitive-data leakage in audit

- **Threat:** Audit records capture tokens, passwords, private paths, or secrets.
- **Mitigation:** The harness does not store tokens, passwords, private absolute
  paths, raw secrets, or sensitive registry contents.
- **Remaining limitation:** Callers must avoid passing sensitive data into evidence
  payloads.
- **Test:** Policy is defensive; enforcement ultimately depends on input hygiene.
