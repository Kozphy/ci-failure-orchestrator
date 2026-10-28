# Agent notes for this repository

## What this project is

A Python CI reliability control plane: diagnose failures, verify candidate fixes
deterministically, gate by policy, and keep humans in charge of merges. Optional
local FastAPI API + SQL worker. Optional LangGraph diagnosis flow.

## Do

- Prefer extending `foundation/`, `service/`, `server/`, or `diagnosis_graph/`.
- Keep model/provider output separate from verification and policy decisions.
- Add tests for success, failure, timeout, and idempotent consequential actions.
- Use the mock provider path (`MockHypothesisProvider`) when no credentials are allowed.
- Record evidence under the existing `RunPersistence` / artifact layout.

## Do not

- Claim production users, customer outcomes, or unreproduced performance numbers.
- Treat synthetic benchmark scores as external validation.
- Merge PRs, push, deploy, or spend API money unless the human explicitly asks.
- Disable or weaken coverage, security, or evidence gates to make CI green.
- Invent LangGraph capabilities; check https://docs.langchain.com/oss/python/langgraph/

## Key commands

```bash
pip install -e ".[dev,server,diagnosis]"
python -m pytest -q tests/test_diagnosis_graph.py
python examples/demo-repo/run_demo.py
```

## Execution modes (worker)

- `CFO_EXECUTION_MODE=foundation` (default): existing `AgentExecutionFoundation` repair path.
- `CFO_EXECUTION_MODE=diagnosis_graph`: LangGraph diagnose → hypothesize → verify → emit.
  `POST /v1/runs` request/response shape is unchanged.
