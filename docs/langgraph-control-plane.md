# LangGraph Control-Plane Adapter

This repository keeps its deterministic CI reliability core independent from any agent framework. The optional LangGraph adapter adds durable, inspectable workflow orchestration without moving policy decisions into the LLM layer.

## Why this exists

The existing repair loop, policy engine, approval boundary, audit layer, and evaluators remain the source of truth. LangGraph is used only for stateful orchestration:

```text
CI failure
   ↓
diagnose
   ↓
deterministic policy
   ├─ BLOCK ───────────────→ audit → END
   ├─ ESCALATE ────────────→ human approval
   ├─ ROLLBACK ────────────→ rollback → audit → END
   └─ RETRY
        ↓
   generate patch
        ↓
      sandbox
        ↓
 independent verify
   ├─ PASS ────────────────→ audit → END
   ├─ regression ──────────→ rollback → audit → END
   ├─ budget available ────→ retry → diagnose
   └─ budget exhausted ────→ human approval
```

This separation is deliberate:

- deterministic policy remains testable without LangGraph;
- the base package has no mandatory LangGraph dependency;
- repair implementations are injected through `LangGraphHooks`;
- graph state is serializable and suitable for checkpointing;
- human approval can use a callback or LangGraph interrupt/resume;
- production persistence can use a durable checkpointer rather than in-memory state.

## Install

Development / local workflow:

```bash
pip install -e '.[langgraph]'
```

Production checkpoint support with PostgreSQL:

```bash
pip install -e '.[langgraph-postgres]'
```

## Minimal integration

```python
from ci_failure_orchestrator.langgraph_runtime import (
    LangGraphHooks,
    build_control_plane_graph,
)

hooks = LangGraphHooks(
    diagnose=lambda state: {
        "failure_class": "flaky_test",
        "confidence": 0.93,
        "retryable": True,
    },
    generate_patch=lambda state: {"patch": "candidate patch"},
    sandbox=lambda state: {"sandbox_passed": True},
    verify=lambda state: {
        "verification_score": 0.95,
        "regression_free": True,
    },
    rollback=lambda state: {"reason": "rolled back"},
    audit=lambda state: {"action": "PASS"},
)

graph = build_control_plane_graph(hooks)
result = graph.invoke(
    {
        "run_id": "ci-123",
        "retry_count": 0,
        "retry_budget": 2,
        "audit_events": [],
    }
)
```

## Human approval

If `LangGraphHooks.approve` is omitted, the approval node uses LangGraph's interrupt mechanism. Compile with a checkpointer and invoke the graph with a stable `thread_id` so the workflow can later resume from the checkpoint.

For deterministic unit tests or an external approval service, inject an approval callback instead:

```python
hooks = LangGraphHooks(
    ...,
    approve=lambda state: {"human_approved": True},
)
```

## Production persistence

Do not treat an in-memory checkpointer as production durability. Use PostgreSQL-backed checkpointing for long-running repair workflows and approval waits.

Example shape:

```python
from langgraph.checkpoint.postgres import PostgresSaver

with PostgresSaver.from_conn_string(DATABASE_URL) as checkpointer:
    checkpointer.setup()
    graph = build_control_plane_graph(hooks, checkpointer=checkpointer)
    graph.invoke(
        initial_state,
        {"configurable": {"thread_id": run_id}},
    )
```

## Next production upgrades

The adapter is intentionally small. The next layer should connect real repository components rather than duplicate them:

1. wire existing failure classifier and repair planner into `diagnose` / `generate_patch`;
2. run candidate patches in an ephemeral container or VM sandbox;
3. feed existing independent evaluation / tournament results into `verify`;
4. persist checkpoints in PostgreSQL;
5. emit OpenTelemetry spans for every graph node and policy route;
6. attach hash-chained audit evidence to each state transition;
7. add dead-letter handling for exhausted retries and infrastructure failures;
8. add model-cost and latency budget fields to workflow state;
9. gate Draft PR creation behind successful verification and policy approval;
10. evaluate the LangGraph path against the existing deterministic baseline.

## Design rule

```text
LLM proposes
Policy decides
Sandbox executes
Verifier checks
Human governs high-risk actions
Audit records everything
```

LangGraph is an orchestration layer, not the security boundary.
