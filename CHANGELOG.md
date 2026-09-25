# Changelog

All notable changes to this repository. Service release plan and stage definitions: [docs/service-v0.1-plan.md](docs/service-v0.1-plan.md).

Versioning (plan §5.4) uses two tracks: the Python package keeps semantic versions in `pyproject.toml` (currently `1.2.0`); the CI failure service is released with `service-v0.x.y` tags, starting at `service-v0.1.0`. Entries below are unreleased.

## [Unreleased]

### Stage 2 — security boundaries on the service path

- Patch guard (`service/patches.py::patch_violation`), enforced in `WorktreeSandbox.execute` before any worktree is created and again in `apply_fix`: rejects symlinks (mode `120000`), submodules (mode `160000` / `Subproject commit`), binary patches, traversal / absolute / drive-letter paths (including `rename`/`copy` headers), `.git/` paths, and added lines containing a high-confidence secret (GitHub token, AWS key, private key). Codes (`forbidden_path_*`, `binary_patch_rejected`, `invalid_patch_contains_secret`) are unrecoverable in `classify_disposition`, so a refused patch stops the run after one attempt.
- Credentials: `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_PAT`, `ACTIONS_*`, `GIT_CONFIG*`, `GIT_ASKPASS`, `SSH_AUTH_SOCK` and similar are refused in `--provider-env` / `--verify-env` (run ends `ERROR`, no artifacts). Ambient values never reach the provider or verification commands (env allowlist).
- Untrusted content (`service/untrusted.py`): ANSI/OSC escapes and control characters are stripped, `::command::` and `##[...]` lines are neutralized, and secrets are redacted at intake (fixture, log file, GitHub, local reproduction) and in verification feedback. Prompt sections holding logs, output and file contents are labeled `UNTRUSTED` inside fences the content cannot close, with a data-only instruction.
- `fix-repo-apply`: PRs are always `--draft`; refuses `main`, `master` and the remote default branch; refuses to push when the branch already exists on the remote; commit message / PR body sanitized.
- Evidence: `tests/test_security_boundaries.py` (41 tests) — including a seeded GitHub token and AWS key in the CI log, verification output and provider response, scanned across every artifact file (`state.json`, `events.jsonl`, `metadata.json`, prompts, responses), provider stdin, the run outcome, the commit message and the PR body; and static AST checks that canonical code contains no merge call and every `gh pr create` argv includes `--draft`. Full suite 438 passed.

### Stage 1b — foundation files split under 1,000 lines (verbatim move)

- `foundation/persistence.py` (1,254 lines) → `durable.py` (schemas, stores, sanitize/JSON helpers; 587), `recovery.py` (assess / verify / inspect / replay / resume), `human_decision.py` (`apply_reviewer_decision`, `append_operator_event`); `persistence.py` keeps `RunPersistence` and re-exports every name, so `foundation.persistence` imports are unchanged.
- `foundation/runner.py` (1,082 lines → 749) → `results.py` (`FoundationResult`), `proposal_factories.py` (`ScriptedProposalFactory`, `default_proposal_factory`, formerly `_default_proposal_factory`), `policy_gate.py` (`PolicyGateMixin._run_policy_gate`, inherited by `AgentExecutionFoundation`); `runner.py` re-exports `FoundationResult`, `ScriptedProposalFactory`, `ProposalFactory`.
- Evidence: an AST comparison of all 50 top-level definitions and runner methods against HEAD found no differences except the one renamed reference; ruff findings in the moved code are the same pre-existing 11 (HEAD had 13; the import-order and unused `typing.Any` findings disappeared with the rewritten import block); full suite 397 passed.
- The oversize caps in `test_canonical_files_stay_under_line_limit` were removed: every canonical file is now ≤ 1,000 lines.

### Stage 1 — `repo_fix.py` split into `service/` (pure move)

- `ci_failure_orchestrator/repo_fix.py` (1,045 lines) moved into `ci_failure_orchestrator/service/`: `common`, `patches`, `session`, `ingest`, `proposals`, `prompt`, `adapters`, `run`, `apply` (largest: `apply.py`, 239 lines). No behavior change; helpers shared across modules lost their leading underscore (`_git` → `git`, `_tail` → `tail`, `_decode_patch_bytes`, `_is_unsafe_path`, `_extract_rationale`).
- `repo_fix.py` is now a compatibility shim re-exporting the same public names; `cli.py` imports from `service`.
- `service` added to the canonical set in `module_status.py`.
- New ratchet `test_canonical_files_stay_under_line_limit`: canonical files ≤ 1,000 lines (pre-existing oversize foundation files were capped until Stage 1b split them).
- Evidence: `tests/test_repo_fix.py` unchanged (`git diff --stat` empty) and passing (12 tests).

### Stage 0 — canonical path marked, risky workflows made safe

- Added `docs/service-v0.1-plan.md` (audit, canonical set, staged plan with acceptance tests, review decisions).
- Added `ci_failure_orchestrator/module_status.py` (machine-readable canonical / entrypoint / experimental classification of every module and CLI command) and `docs/module-status.md`.
- Added `tests/test_module_boundaries.py`: every module classified; manifest entries exist; classification disjoint; canonical modules may not import experimental modules. One pre-existing edge is recorded as a known violation that may only shrink: `foundation.classifier` → `github_repair_adapter` (removal: Stage 3).
- CLI: experimental commands (`classify`, `rank`, `analyze`, `analyze-run`, `trust-run`, `run`, `explain`, `replay`, `benchmark`) are labeled `[experimental]` in `--help`; top-level help names the canonical commands. Test: `tests/test_cli_groups.py`.
- Workflows (`tests/test_workflow_safety.py`):
  - `auto-merge-after-checks.yml`: triggers reduced to `workflow_dispatch` and job hard-disabled (`if: ${{ false }}`), so it cannot merge even when dispatched.
  - `self-heal.yml`: `workflow_run` trigger replaced by `workflow_dispatch` (inert without a `workflow_run` payload).
  - `agent-issue-delivery.yml`: `issues: labeled` trigger replaced by `workflow_dispatch` (inert without an `issues` payload).
  - Static checks: no enabled job contains a merge command; no workflow triggers on `pull_request_target`. Negative check: against the previous workflow files the test fails 3 times.
