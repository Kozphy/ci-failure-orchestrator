# Software Engineering Development Framework — 從 AI 輔助開發到可驗證工程

> Updated: 2026-10-31  
> Repository: https://github.com/Kozphy/ci-failure-orchestrator  
> Career goals: Software Engineer / Technology Risk / AI Governance / Reliability Engineering

## 1. Core workflow

**Spec → Tests → Implementation → Adversarial Review → Evidence → Human Decision → Iteration**

**規格定義 → 測試設計 → 程式實作 → 對抗性審查 → 證據驗證 → 人工決策 → 迭代改善**

This is a composite workflow, not an officially standardized framework.

**Claim → Evidence → Verification → Decision.** A green CI run alone does not prove a correct repair; AI suggestions do not replace deterministic tests or human accountability.

| Stage | Key question | Deliverable |
| --- | --- | --- |
| Spec | What observable behavior is required? | Spec and acceptance criteria |
| Tests | How can we falsify the claim? | Regression and negative tests |
| Implementation | What minimal change solves the problem? | Reviewed source changes |
| Adversarial Review | How might this fail or be bypassed? | Threats and edge-case findings |
| Evidence | Can someone else reproduce the result? | Commands, SHA, logs, results |
| Human Decision | Are the remaining risks acceptable? | PR review and explicit decision |
| Iteration | What should be improved next? | Next prioritized work item |

### Definition of Done

- [ ] Requirements and acceptance criteria are explicit
- [ ] Failure or missing invariant is reproducible
- [ ] Minimal implementation or documented existing control
- [ ] Relevant regression and negative tests completed
- [ ] Security implications reviewed
- [ ] Environment, commit SHA, commands, exit codes and results recorded
- [ ] Remaining risks documented
- [ ] Human review completed; no automatic merge

## 2. Free learning resources

1. **Spec-Driven Development — GitHub Spec Kit:** https://github.github.com/spec-kit/  
   Requirements, acceptance criteria, plans and tasks.
2. **Test-Driven Development — pytest:** https://docs.pytest.org/en/stable/  
   Red → Green → Refactor; fixtures, parameterization, regression tests.
3. **Property-Based / Stateful Testing — Hypothesis:** https://hypothesis.readthedocs.io/en/latest/stateful.html  
   State-machine invariants, retries, order-sensitive behavior.
4. **Adversarial Review — OWASP Threat Modeling:** https://owasp.org/www-community/Threat_Modeling  
   Identify assets, trust boundaries, threats and mitigations. Also see https://owasp.org/www-project-web-security-testing-guide/ (primarily Web-focused).
5. **Evidence & Reliability — Google SRE Workbook:** https://sre.google/workbook/table-of-contents/  
   SLIs, SLOs, error budgets, reliability measurement.
6. **Human Decision — GitHub PR review:** https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests
7. **Iteration — Microsoft Learn DevOps:** https://learn.microsoft.com/en-us/training/browse/?terms=DevOps

## 3. Six-week hands-on roadmap

Time suggestion: 5–7 hours weekly, adjustable to pace.

### Week 1 — Specification
- [ ] Read Spec Kit quickstart
- [ ] Choose a narrowly scoped CI Failure Orchestrator improvement
- [ ] Define five testable acceptance criteria
- [ ] Document three failure scenarios
- [ ] Deliver a small SPEC.md

### Week 2 — TDD
- [ ] Learn pytest fixtures and assertions
- [ ] Write a failing regression test, when a defect exists
- [ ] Reproduce the original problem
- [ ] Implement the smallest justified fix
- [ ] Run regression checks and record results

### Week 3 — State machines
- [ ] Learn Hypothesis stateful testing
- [ ] Define three safety invariants
- [ ] Test retry exhaustion and invalid transitions
- [ ] Check repeated and out-of-order operations

### Week 4 — Security review
- [ ] Draw trust boundaries
- [ ] Identify untrusted patches, inputs and commands
- [ ] Review potential policy bypasses
- [ ] Run adversarial tests **only in an appropriately isolated environment**
- [ ] Record residual security limits

### Week 5 — Evidence & reliability
- [ ] Capture exact commands and exit codes
- [ ] Record Python version, dependency versions and commit SHA
- [ ] Compare baseline and final behavior
- [ ] Label PASS / FAIL / BLOCKED / NOT TESTED
- [ ] Document benchmark sample size and limitations

### Week 6 — Code review & interview
- [ ] Open a reviewable pull request
- [ ] Inspect the diff and CI evidence
- [ ] Write an Architecture Decision Record
- [ ] Explain root cause, design trade-offs and limits without relying on AI
- [ ] Review next iteration priorities

## 4. Applied exercise: Prevent Invalid Repair Approval

**Repository:** https://github.com/Kozphy/ci-failure-orchestrator

**Invariant:** A patch must not be applied using verification evidence produced for a different patch or verification configuration.

### Spec
Define the exact patch identity, base commit, verification config and acceptance criteria.

### Tests
Test these scenarios:
1. Original patch passes verification.
2. Patch bytes are changed after verification.
3. Patch hash mismatch is detected.
4. Stale or mismatched evidence does not authorize apply.
5. Rejection reason is preserved in an auditable result.

### Implementation
Inspect existing patch-hash, evidence and apply controls **before** adding code. Add regression coverage where the control already exists; change production logic only if a verified gap is found.

### Adversarial review
Consider swapped patches, reused evidence, changed verification config, interruption and duplicate requests. Do not execute untrusted commands on an unrestricted host.

### Evidence
Capture commit SHA, test environment, exact commands, exit codes, actual observed results and remaining limitations.

### Human decision
Review code diff, tests, security implications and residual risks before deciding whether to merge.

### Iteration
Choose the next improvement from verified findings.

## 5. Two-agent review, human-controlled

- **Builder Agent:** inspect code, define tests, implement small changes and report evidence.
- **Reviewer Agent:** independently challenge assumptions, inspect diff, identify bypasses and missing tests.
- **Human Engineer:** define risk appetite, understand the change, verify evidence and decide about merging.

Agreement between two AI agents is not independent validation.

## 6. Codex prompt

```text
You are a senior software engineer and independent code reviewer.

Repository: https://github.com/Kozphy/ci-failure-orchestrator

Use the workflow:
Spec → Tests → Implementation → Adversarial Review → Evidence → Human Decision → Iteration.

Inspect existing source code, tests, CI and architecture before making claims.
Select one high-risk, verifiable engineering gap.

1. SPEC: Define the problem, acceptance criteria and safety invariants.
2. TESTS: Reproduce the defect or missing property with regression tests.
3. IMPLEMENTATION: Make the smallest correct change, if needed.
4. ADVERSARIAL REVIEW: Investigate bypasses, edge cases, TOCTOU, crash recovery and security regressions.
5. EVIDENCE: Run checks and record versions, commit SHA, commands, exit codes, results and limitations.
6. HUMAN DECISION: Prepare a PR-ready review package; never push or merge automatically.
7. ITERATION: Recommend the next improvement based on the evidence.

Do not fabricate results, weaken tests, bypass policy gates or claim production readiness.
Run unsafe payloads only with appropriate isolation. Mark unverified steps BLOCKED or NOT TESTED.
Return changes, tests, evidence, trade-offs, residual risks and a review summary.
```

## 7. Interview self-check

- [ ] Can I explain the architecture without AI?
- [ ] Can I identify the root cause and navigate to the responsible code?
- [ ] Can I run and interpret the regression tests?
- [ ] Can I implement a change independently?
- [ ] Can I explain algorithmic complexity where relevant?
- [ ] Can I explain security boundaries and engineering trade-offs?
- [ ] Can another engineer reproduce my evidence?

## Final principle

**Don't just generate code. Engineer verifiable systems.**

Specification → Testing → Implementation → Review → Verification → Decision → Iteration

**Trust, but verify.**
