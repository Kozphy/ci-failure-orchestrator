# Demo: a broken CI run, repaired with evidence

`releasekit` is a tiny Python package with a real bug. `is_newer("1.10.0", "1.9.0")` returns
`False` because versions are compared as strings, so a release script would refuse to publish
1.10.0. The test suite catches it and CI goes red.

`run_demo.py` takes that repository through the whole CI Doctor loop with the same commands a
customer runs:

| Step | Command | What you see |
|---|---|---|
| 1. CI fails | `python -m pytest -q` (the job in `project/.github/workflows/ci.yml`) | `FAILED tests/test_versions.py::test_is_newer_handles_double_digit_minor` |
| 2. Diagnosis | `actions-doctor diagnose --log ci-failure.log` | Failure class, the evidence line, the next step. Read-only. |
| 3. Verified repair | `ci-orchestrator fix-repo --patch-file fix.diff --verification-config verify.yml` | The failure reproduced at the base commit, the failing test passing with the patch, the regression suite, build and invariant unchanged, and a policy decision. |
| 4. Apply | `ci-orchestrator fix-repo-apply <run_id>` | A new local branch with the fix. `main` is untouched; nothing is pushed or merged. |
| 5. Green CI command | `python -m pytest -q` on the fix branch | Exit 0. |
| 6. Evidence | `ci-orchestrator fix-repo-report <run_id>` | `evidence-report.md` and `.json`: what broke, why, what changed, which tests ran, what shows it is safe, and what risk remains. |

## Run it

From the repository root, with the package installed (`pip install -e .`) and pytest available:

```bash
python examples/demo-repo/run_demo.py
```

It takes under a minute, needs no token, network or model, and writes only to a new temporary
directory (or `--workdir DIR`).

## What it does not prove

- **The fix comes from `fix.diff`, a recorded teammate patch.** CI Doctor verifies a patch; this
  demo does not show a model writing one. Use `--provider-cmd` to verify a model's patch instead.
- **Real CI does not run.** The final state is `POLICY_APPROVED`, not `VERIFIED_FIXED`. After you
  push the branch, `ci-orchestrator fix-repo-verify-ci <run_id> --repository <owner/name>` reads
  the GitHub Actions run for that commit and records the final state.
- One repository and one bug class (a failing assertion in pytest) are a demonstration, not a
  benchmark. No success rate should be inferred from it.

## Files

- `project/`: the repository at the failing commit, including its CI workflow
- `fix.diff`: the candidate fix (one line in `releasekit/versions.py`; no test is changed)
- `verify.yml`: what "safe to merge" means here: the regression suite, a build check, one behavioral invariant and the affected-test map
- `run_demo.py`: the runner; `tests/test_demo_repo.py` runs it in CI
