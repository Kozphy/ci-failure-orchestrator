# Production Definition of Done

A change is **DONE** only when it is not merely implemented, but proven ready for safe production use.

> **DONE = implemented + verified + documented + safe + observable + operable + reversible + reproducible + auditable + CI green.**

## Canonical gate

```text
DONE =
FUNCTIONALLY_CORRECT
AND VERIFIED
AND SAFE
AND DOCUMENTED
AND OPERABLE
AND OBSERVABLE
AND REVERSIBLE
AND REPRODUCIBLE
AND AUDITABLE
AND CI_GREEN
```

## Expanded definition

### FUNCTIONALLY_CORRECT

```text
requirements satisfied
AND acceptance criteria verified
AND implementation complete
AND no known critical TODO/FIXME blockers
```

### VERIFIED

```text
unit tests pass
AND integration tests pass
AND end-to-end/system tests pass where applicable
AND regression tests pass
AND failure-path tests pass
AND edge-case tests pass
AND lint passes
AND type checks pass
AND static analysis passes
```

### SAFE

```text
dependency/vulnerability checks pass
AND secrets scan passes
AND safety invariants verified
AND important safety behavior documented
AND no unresolved critical/high-risk findings
```

For autonomous repair, safety additionally requires:

- repair agents cannot self-approve release;
- unknown failures fail closed and escalate;
- model output cannot directly obtain unrestricted filesystem, shell, git, merge, or release authority;
- regression detection blocks release;
- bounded retry, cost, latency, concurrency, and error-budget policies remain authoritative.

### DOCUMENTED

```text
public API documented
AND docstrings updated
AND configuration documented
AND environment variables documented
AND migration/schema changes documented
AND architecture docs updated
AND ADRs updated when architectural decisions changed
AND runbook updated
AND troubleshooting docs updated
AND important safety behavior documented
AND known limitations documented
```

### OPERABLE

```text
deployment procedure exists
AND configuration is documented
AND operational runbook exists
AND troubleshooting path exists
AND ownership/escalation path exists where applicable
```

### OBSERVABLE

```text
meaningful logs exist
AND key metrics exist
AND important failure modes are observable
AND tracing exists where applicable
AND alerts/SLO impact reviewed
```

### REVERSIBLE

```text
rollback is possible
AND migration changes have rollback or forward-fix strategy
AND risky changes use staged/canary rollout where appropriate
AND rollback procedure is tested or explicitly documented
```

### REPRODUCIBLE

```text
dependencies locked
AND builds reproducible
AND tests reproducible
AND environment reproducible
AND artifacts traceable to source revision
AND provenance/version information available
```

### AUDITABLE

```text
issue linked
AND branch/commits traceable
AND PR linked
AND test evidence recorded
AND CI evidence recorded
AND review/approval recorded
AND deployment version traceable
AND material decisions produce machine-readable evidence
```

Preferred evidence chain:

```text
issue
  ↓
branch
  ↓
commits
  ↓
tests
  ↓
PR
  ↓
CI
  ↓
review/policy gate
  ↓
deployment
  ↓
production verification
  ↓
production proof
```

### CI_GREEN

```text
all required checks pass
AND required reviews are satisfied
AND branch/repository policy is satisfied
AND no required gate is bypassed
```

## Completion maturity levels

```text
CODE_COMPLETE
    ↓
ENGINEERING_COMPLETE
    ↓
PRODUCTION_DONE
```

### CODE_COMPLETE

Implementation is finished.

### ENGINEERING_COMPLETE

```text
code complete
+ tests
+ documentation
+ review
+ CI green
```

### PRODUCTION_DONE

```text
engineering complete
+ security
+ observability
+ deployment readiness
+ rollback readiness
+ audit evidence
+ production verification
```

Only `PRODUCTION_DONE` should be treated as final completion for release-capable autonomous workflows.

## Machine-enforced policy model

Agents must not be allowed to self-declare completion. A policy engine should derive `DONE` from evidence.

```yaml
definition_of_done:
  requirements:
    acceptance_criteria: pass

  code:
    complete: true
    lint: pass
    typecheck: pass
    static_analysis: pass

  tests:
    unit: pass
    integration: pass
    regression: pass
    failure_paths: pass
    e2e: not_applicable_or_pass

  docs:
    public_api: updated_or_not_applicable
    docstrings: updated
    architecture: updated_or_not_applicable
    safety: updated_or_not_applicable
    runbook: updated_or_not_applicable
    limitations: documented_or_none

  security:
    secrets_scan: pass
    dependency_scan: pass
    vulnerability_scan: pass
    safety_invariants: pass

  operations:
    observability: verified
    rollback: verified_or_documented
    deployment: verified_or_not_applicable
    canary: verified_or_not_applicable

  reproducibility:
    dependencies_locked: true
    build_reproducible: true
    test_environment_reproducible: true
    artifact_provenance: recorded

  governance:
    issue_linked: true
    pr_linked: true
    review_satisfied: true
    audit_evidence: generated
    high_risk_findings: 0

  ci:
    required_checks: pass
    policy_gate: pass

  final_gate:
    status: DONE
```

## Autonomous software factory rule

The software factory should distinguish between an agent saying "I finished coding" and the control plane proving "this change is ready."

```text
agent proposes completion
        ↓
evidence collector
        ↓
tests + security + docs + architecture + observability
        ↓
policy engine
        ↓
risk classification
        ↓
required review / canary / rollback gate
        ↓
all required evidence satisfied?
   ├─ no  → NOT_DONE / repair / escalate
   └─ yes → PRODUCTION_DONE
```

`DONE` is therefore a **derived, evidence-backed system state**, not an agent assertion.
