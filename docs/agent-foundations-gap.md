# Agent Foundations gap assessment (evidence-based)

Assessed against the local tree at the start of the LangGraph diagnosis work.
`AGENTS.md` did not exist before this change.

## Working (code + tests exist)

| Area | Evidence |
| --- | --- |
| Deterministic classification / policy / repair verification | `ci_failure_orchestrator/foundation/`, `service/`; large pytest suite |
| Local REST API + job queue + lease worker | `server/app.py`, `server/worker.py`, `tests/test_server_*.py` |
| Durable state + audit + evidence | `foundation/persistence.py`, SQL mirrors in `server/sql_store.py` |
| Offline demo without credentials | `examples/demo-repo/run_demo.py` |
| Structured JSON logs (API/worker) | `server/logs.py` |
| Synthetic offline benchmark envelope (on branch `benchmark/offline-evidence`, not necessarily on `main`) | `scripts/run_offline_benchmark.py` when that branch is present |

## Documented / roadmap, not implemented as claimed

| Claim | Reality |
| --- | --- |
| LangGraph / LangChain agent flows | Named only in `docs/AI_AGENT_PRODUCTION_ROADMAP.md` before this change; not a dependency |
| “No hosted service” in README | Accurate as SaaS; a **local** FastAPI + compose stack does exist |
| Production users / success rates | README correctly says none; do not invent them |
| GitLab CI native integration | Explicitly “Not integrated yet” |
| Dependency lockfile for clean-room repro | Missing on `main` (`PyYAML>=6.0` ranges only) |

## Largest gap relevant to GitLab Intermediate Backend / Agent Foundations

Python API, background jobs, evaluations, and observability already exist. The
missing piece that the role names explicitly was a **LangGraph** orchestration
path with checkpointed resume, bounded provider retries, timeout handling, and
structured evidence—without replacing the verified repair pipeline.

That is the single improvement implemented in this change set.
