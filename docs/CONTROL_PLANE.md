# Control plane architecture

Date: 2026-11-28. This document describes what remains after the control-plane cut:
coding agents got better at writing patches; this repository governs whether those
patches are safe to propose as draft PRs.

## Invariant

Agents propose diffs. This system verifies, scores risk, applies policy, records
evidence, and may open a **draft** PR. It never merges. A green CI result is not
equivalent to `VERIFIED_FIXED`.

## Survivors

| Layer | Modules | Role |
| --- | --- | --- |
| Control plane | `foundation/`, `governed/`, `approval`, `agent_router`, `governed_agent/` | Decide: classify, risk, policy, escalation, human gate |
| Verification | `service/`, `patch_sandbox.py` | Reproduce, apply candidate, run verify/regression/gates |
| Untrusted ingest | `provider_adapters.py`, `--patch-file` / `--provider-cmd` | Accept diffs from any external agent CLI |
| Evidence | `audit.py`, `service/evidence_report.py`, durable events | Append-only / hash-chained trail |
| GTM wedge | `doctor/`, `ci_audit/` | Read-only diagnosis and reliability audits ($299 offer) |
| Hosted sketch | `server/` | SQL durable state + API; not expanded in this cut |
| Agent interface | `agent_mcp/` | Read-only MCP tools; no shell, no merge |

## Deleted on purpose

Experimental agent loops, autonomous runtimes, merge-conflict agents, DORA/fleet
dashboards, self-heal workflows, and “production proof” theater. Those compete
with OpenHands / Devin / Copilot / Cursor on patch generation. They do not survive
a world where those products are 10× better.

## Flow

```text
CI failure or log
  → doctor / service ingest
  → risk + classify
  → agent_router (optional; selects external worker)
  → external agent produces untrusted diff
  → verification (reproduce → tests → gates)
  → policy engine (default ESCALATE)
  → approval workflow when required
  → draft PR only
  → evidence + audit store
  → real CI observe → VERIFIED_FIXED or not
```

## Extension point for external agents

Point `--provider-cmd` at OpenHands, Claude Code, Cursor agents, or any CLI that
reads a prompt on stdin and prints a unified diff. The control plane does not
embed those products; it treats their output as untrusted input.

See also: [module-status.md](module-status.md), [COMMERCIAL_ARCHITECTURE.md](COMMERCIAL_ARCHITECTURE.md).
