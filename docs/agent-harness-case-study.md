# Agent Reliability Harness — Case Study

## Problem

Organizations want AI-assisted incident diagnosis and remediation, but a raw LLM
in the loop tends to:

- hallucinate evidence and incident types
- propose unsafe or unsupported remediation
- escalate confidence without evidence
- bypass policy by sounding confident
- retry without a budget
- self-approve its own proposals

That is unacceptable for network and CI reliability tooling where mutable actions
can affect production state.

## Why direct LLM remediation is unsafe

A model is a text completion engine, not an authority. If the model can:

- emit an incident label the system does not recognize
- invent evidence references
- propose a forbidden or mutative action
- claim high confidence without limitations
- drive execution without policy, preview, verification, rollback, or audit

then the system has handed authority to the model. That breaks the safety
boundary and makes the harness untrustworthy in any portfolio or production
setting.

## Architecture

The harness keeps AI in a bounded proposal layer:

```
Evidence
  ↓
Deterministic classification
  ↓
LLM structured diagnosis (validated)
  ↓
Typed repair proposal (validated)
  ↓
Centralized policy gate
  ↓
Preview / sandbox where possible
  ↓
Verification plan
  ↓
Bounded retry
  ↓
Human escalation object
  ↓
Audit record (append-only / hash-chained)
```

Key properties:

- The model returns structured JSON only.
- Validation rejects unknown incident types, invented evidence refs, malformed
  output, unsupported actions, missing limitations for weak evidence, and
  invalid confidence.
- The model produces a proposal, not an execution permission.
- Every mutable proposal passes one centralized policy decision.
- The system fails closed for ambiguous cases.

## Safety boundaries

1. The model cannot directly mutate OS or CI state.
2. All mutable actions go through controlled remediation paths, not raw
   PowerShell / netsh / registry mutation / firewall reset / adapter reset /
   process termination.
3. Proposed actions are validated against a supported set and a forbidden set.
4. Rollback and verification are required; missing rollback or missing
   verification fails closed.
5. Low confidence with missing limitations triggers human review.
6. Confidence below the policy threshold escalates rather than retries
   indefinitely.

## Evaluation

The harness includes an independent evaluator for repair proposals. It checks:

- proposal validity
- policy safety
- rollback presence
- verification presence
- forbidden action detection
- unsupported action detection
- evidence reference validity
- confirmation requirement correctness
- incident/action mapping correctness

The evaluator does not evaluate itself. Benchmark metrics compare every
model-backed result against the deterministic classification baseline.

Current benchmark status:

- Most metrics are `NOT_YET_MEASURED` because measurements have not yet been
  run against a real model provider.
- The corpus is deterministic and ready for measurement once a provider is
  wired in.

## Retry policy

Retry is bounded and explicit:

```
attempt
  ↓
diagnose
  ↓
plan
  ↓
evaluate
  ↓
verification failure?
  ├─ no → stop
  └─ yes
       ↓
retryable?
       ├─ no → ESCALATE
       └─ yes
            ↓
budget remaining?
            ├─ no → ESCALATE
            └─ yes → retry
```

Tracked metadata includes attempt count, max attempts, elapsed time, model calls,
and reason for retry or stop. There are no infinite loops.

## Human escalation

Human escalation is a first-class result, not a generic exception. The
`HumanEscalation` object contains:

- incident identity
- current diagnosis
- repair proposal
- attempt history
- evidence references
- policy reason
- verification failures
- risk level
- recommended human action

This gives a reviewer enough context to decide without re-deriving incident
state.

## Audit evidence

Significant agent transitions are recorded with:

- timestamp
- incident id
- attempt id
- model / provider
- diagnosis
- repair proposal
- evidence refs
- policy decision
- sandbox result
- verification result
- retry decision
- human-review state
- final disposition

The audit trail is append-only and hash-chained where the repository already
provides that infrastructure. Tokens, passwords, private paths, raw secrets, and
sensitive registry contents are not stored.

## Limitations

- The current demo and benchmarks run against a deterministic fixture model, not
  a live provider. That is intentional so results are reproducible.
- Live model measurements have not been run yet.
- Some network-specific remediation still depends on the underlying toolkit's
  controlled paths and is not executed by the harness directly.
- The harness is bounded by design; it will not auto-promote a proposal.

## Future work

- Wire a real provider adapter behind the provider-neutral model client.
- Extend the benchmark corpus with measured metrics once measurements are run.
- Add more sandbox integration where appropriate.
- Add regression detection checks driven by deterministic verification results.
- Tighten evidence reference validation for additional namespaces.
- Port the harness pattern to other bounded remediation domains in the toolkit.
