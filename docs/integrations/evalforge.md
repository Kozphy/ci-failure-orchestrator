# EvalForge evaluation boundary

`ci_failure_orchestrator.governed.evaluation.EvalForgeAdapter` is an injected
submit/fetch contract. It does not prove that a live EvalForge service is deployed.
The default pipeline's `LocalEvaluator` remains a separate local evaluation mode.

When the adapter is selected, independent evaluation is required by default.
Missing submit/fetch callbacks produce a failed result. Explicit
`allow_local_fallback=True` enables local evaluation and labels its evidence
`local_fallback_not_independent`; it must not be counted as an independent gate.

The request carries run ID, proposal ID, SHA-256 of the proposed patch, changed files,
sandbox state and target-check state. Replies must contain exactly:

- `run_id`, `proposal_id`, `proposal_sha256`: matching request identity/digest;
- `passed`, `target_check_passed`, `regression_free`, `policy_safe`: actual booleans;
- `evidence`: 1–64 nonempty strings, each at most 2048 characters;
- optionally `score`: finite numeric value in [0, 1], excluding booleans.

Missing fields, extra fields, string booleans, stale IDs/digests, invalid scores,
contradictory PASS and provider exceptions produce failed evaluation. A remote PASS
cannot override a failed/timed-out local sandbox or failed target check. Exception
messages are not recorded because they may contain credentials.

Provider callbacks must impose transport deadlines; catching `TimeoutError` does not
interrupt an arbitrary hung callable. No retry worker or remote service is introduced
in this P0 contract patch. All new provider-response tests use synthetic replies.

```bash
python -m pytest -q tests/test_evalforge_boundary.py tests/test_governed_pipeline.py
python -m ruff check ci_failure_orchestrator/governed/evaluation.py tests/test_evalforge_boundary.py
python -m mypy --follow-imports=skip ci_failure_orchestrator/governed/evaluation.py
```
