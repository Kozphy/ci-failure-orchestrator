# MVP

Product hypothesis: a developer can diagnose one saved GitHub Actions log, or one failed run, without an LLM key, and can read a report that separates evidence from recommendations.

This is not a measured reduction in investigation time.

## A new user can

1. Read `docs/productization/install-github-action.md`.
2. Add the composite action.
3. Grant `contents: read` for a saved log, or `actions: read` plus `contents: read` for a run id.
4. Point `log-path` at a failed job log, or pass `run-id`.
5. Read `diagnosis-status` and `failure-category`.
6. Read the classified line and the heuristic confidence in the Markdown report.
7. See the evidence line number when the doctor found one.
8. Read a remediation that the report marks `not_executed`.
9. Run the same entry point locally with `CI_DOCTOR_LOG_PATH`.
10. Delete the workflow and revoke a token if one was created.

## Explicitly unsupported

Dashboards, billing, a database, auto-merge, push, patch apply, `pull_request_target`, logs over 2 MB, turning redaction off, multi-run frequency inside this Action, and any claim of a lower failure rate.
