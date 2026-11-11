# Governed Autonomous Engineer — P0 scope gate (experimental)

The `governed_agent.contract` module is an **additive, deterministic preflight
scope check** for an autonomous coding workflow. It is not yet connected to the
production repair runner and is **not** an autonomous software engineer.

## Trusted-host usage

1. A human or trusted controller issues a `TaskContract` with repository-relative
   allowed path patterns, acceptance commands, and bounded attempt/file budgets.
2. Run the coding agent only in a separate disposable sandbox or worktree.
3. Read changed filenames from the host's VCS diff, **not** from agent output.
4. Call `validate_changes(contract, changed_paths, attempt=n)`.
5. Reject when `allowed=False`. A positive result permits only the next stage;
   it is **not** permission to merge, push, deploy, or skip tests.
6. Independently run baseline reproduction, targeted tests, regression checks,
   secure command allowlists, and policy/evidence integrity checks.
7. Require human review for final acceptance.

## Example

```python
from ci_failure_orchestrator.governed_agent import TaskContract, validate_changes

contract = TaskContract(
    task_id="issue-123",
    allowed_paths=("ci_failure_orchestrator/doctor/**",),
    acceptance_commands=("python -m pytest -q",),
    max_attempts=3,
)
result = validate_changes(
    contract,
    ["ci_failure_orchestrator/doctor/example.py"],  # trusted diff path
    attempt=1,
)
assert result.allowed
```

## Known boundaries

- Scope/path checks do not enforce filesystem isolation or network restrictions.
- Symlink targets, renamed paths, and file modes must be independently validated.
- The acceptance command strings are contract metadata; this module never executes
  them and does not make arbitrary commands safe.
- No integration with EvalForge, no provenance signing, no independently verified
  test run, no dashboard, and no cross-repository orchestration in this change.
- No push, merge, production deploy, or automatic repair is executed by this module.

## Verification

Run `python -m pytest -q tests/test_governed_agent_contract.py` in an environment
with the repository dev dependencies installed. Passing these tests checks only
the deterministic scope gate, not the full autonomous engineering system.
