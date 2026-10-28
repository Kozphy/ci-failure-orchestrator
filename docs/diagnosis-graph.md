# LangGraph CI diagnosis flow

## Problem

The repository already had a durable foundation repair runner and a FastAPI worker,
but no LangGraph graph. For Agent Foundations work, reviewers look for explicit
graph orchestration, checkpointed resume, and clear separation between model
output and deterministic decisions.

## Design

```text
POST /v1/runs  (unchanged)
    → job queue
    → worker (CFO_EXECUTION_MODE=diagnosis_graph)
        → classify          FailureClassifier (deterministic)
        → hypothesize       MockHypothesisProvider (or injectable mock)
                            RetryPolicy on ProviderTransientError
                            wall-clock timeout via ThreadPoolExecutor
        → verify            hypothesis category == classifier category?
        → emit_decision     consequential action at most once per run_id
        → RunPersistence    decision.json evidence + durable checkpoint
```

**Why LangGraph:** `StateGraph` + `MemorySaver` (`thread_id=run_id`) + `RetryPolicy`
give reviewable edges and resume semantics that the ad-hoc foundation loop does
not expose as a graph API. Verified against LangGraph 1.2 docs
([fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance),
[graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)).
Node `timeout=` is async-only in current docs, so the sync mock path uses a
thread-pool deadline instead of claiming native node timeouts.

**What LangGraph does not decide:** the final `decision` field. A matching
hypothesis yields `DIAGNOSIS_CONFIRMED`; a mismatch yields `DIAGNOSIS_ESCALATED`.
Provider hard failure and timeout never become a confirmation.

## Tradeoffs

- Process-local `MemorySaver` and an in-process emit ledger—not a shared
  Postgres checkpointer. Worker multi-process resume of graph state is limited;
  durable `decision.json` still lands in existing artifact storage.
- Diagnosis only: no patch apply, no draft PR. The foundation repair path remains
  the default (`CFO_EXECUTION_MODE=foundation`).
- Optional extra: `pip install -e ".[diagnosis]"` (pins `langgraph>=1.2`).

## Results (local, measured)

```text
python -m pytest -q tests/test_diagnosis_graph.py
# 8 passed (success, hard fail, transient retry, timeout, mismatch escalate,
#           idempotent emit, worker factory selection, settings validation)
```

No production traffic. No paid model calls.

## Limitations

- Not a substitute for `fix-repo` verification.
- Hypothesis categories are mock strings unless you inject another provider.
- Emit idempotency for the graph uses a process-local set plus state flags;
  cross-process exactly-once still relies on not re-enqueueing the same job
  after `COMPLETED` (existing lease/complete fencing).

## Troubleshooting

| Symptom | Structured log `event` | What to check |
| --- | --- | --- |
| Provider keeps failing | `diagnosis_hypothesize_hard_fail` / `diagnosis_verified` with `DIAGNOSIS_PROVIDER_FAILED` | Provider configuration; evidence `diagnosis/decision.json` |
| Slow provider | `diagnosis_hypothesize_timeout` | Lower provider delay or raise timeout only in tests deliberately |
| Unexpected escalate | `diagnosis_verified` with `verification=MISMATCH` | Classifier category vs hypothesis; do not “fix” by trusting the model |
| Duplicate decision fear | `diagnosis_action_skipped_duplicate` | Same `run_id` / `thread_id`; ledger should stay length 1 |
| Worker still runs full repair | (no diagnosis_* events) | Set `CFO_EXECUTION_MODE=diagnosis_graph` on the **worker** process |

## Reproduce

```bash
python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
source .venv/bin/activate
pip install -e ".[dev,diagnosis]"
python -m pytest -q tests/test_diagnosis_graph.py
```

In-process demo (no API server required):

```bash
python -c "from pathlib import Path; from ci_failure_orchestrator.diagnosis_graph import DiagnosisGraphRunner, MockHypothesisProvider; from ci_failure_orchestrator.foundation.models import FailureEvent; from ci_failure_orchestrator.foundation.persistence import RunPersistence; root=Path('artifacts/diagnosis-demo'); p=RunPersistence(root); r=DiagnosisGraphRunner(root, persistence=p, provider=MockHypothesisProvider(category='test_failure')); e=FailureEvent.from_dict({'workflow':'ci','job':'test','failed_step':'pytest','message':'AssertionError: expected True got False','log_excerpt':'FAILED tests/test_app.py::test_login'}, run_id='demo-diag-1'); print(r.run(e).workflow_status, r.action_ledger)"
```
