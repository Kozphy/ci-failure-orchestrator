# Toolkit gap matrix

Checked in this session against local trees. EvalForge was not executed. After this slice was added, `python -m pytest -q tests/test_ci_diagnosis_plugin.py` reported 7 passed and `python scripts/demo_ci_diagnosis.py` exited 0 on Python 3.14, Windows. That run is local, not a GitHub Actions result.

| Capability | Repo | Class | Evidence |
| --- | --- | --- | --- |
| CI Doctor offline `diagnose_log` | ci-failure-orchestrator | verified in tree | `doctor/diagnose.py` states it needs no token. This slice calls it. |
| `actions-doctor` and `ci-orchestrator` CLIs | ci-failure-orchestrator | verified in tree | `pyproject.toml` scripts. This slice adds a third script and does not change the other two. |
| Read-only reliability audit (`ci_audit`) | ci-failure-orchestrator | verified in tree, not in this plugin | Analyzer exists. This plugin does not call it. |
| Repair loop, apply, merge | ci-failure-orchestrator | verified in tree, refused here | CLI commands remain. The MCP server returns `approval_required` for those names. |
| Governed `ToolRegistry` including `test_runner` | ci-failure-orchestrator | partial | Schemas exist. Not exposed over MCP. |
| MCP server before this slice | ci-failure-orchestrator | missing on `main` | `docs/architecture/mcp-readiness.md` said no server. This slice adds one tool. |
| LangGraph diagnosis worker | ci-failure-orchestrator | proposed on another branch | `feat/langgraph-diagnosis-flow` is not in this branch. |
| Three-tool MCP adapter | ci-failure-orchestrator | proposed on another branch | Draft PR #17. Not merged. This slice is the one-tool product cut. |
| Billing, paid software tiers | ci-failure-orchestrator | missing | README says planned tiers have no billing system. Booking links are placeholders. |
| Paying users, ROI | both | missing | No customer ledger in either repo. |
| Finance golden set and deterministic graders | EvalForge | documented, not re-run here | README describes them. License is proprietary. Not imported. |
| EvalForge LLM judge | EvalForge | partial | README says simulated offline. |
| EvalForge live model runner | EvalForge | partial | README shows a command that needs an API key. Not used here. |
| AI Governance plugin | toolkit | proposed | Design only in `ARCHITECTURE.md`. No package. |
| FinOps plugin | toolkit | missing | No FinOps engine in these two repos. Design note only. |
