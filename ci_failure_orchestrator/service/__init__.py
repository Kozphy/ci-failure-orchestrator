"""Canonical CI failure service path (fix-repo / fix-repo-apply).

Composition layer only. The foundation keeps authority over retry, evaluation,
policy and escalation; this package contributes:

* failure ingest (fixture, log file, GitHub Actions run, local reproduction),
* real proposal sources (a patch file or an external provider CLI),
* a sandbox that applies each proposal in a disposable git worktree of the
  target repository and runs explicit verification commands,
* ``apply_fix``: the only code path that writes to the target repository,
* Task / Attempt records linking runs of one objective and naming the agent per attempt,
* repair verification (targeted, regression, quality and real-CI evidence) feeding the
  deterministic remediation decision in ``foundation.remediation``,
* one evidence report per repair (``fix-repo/evidence-report.json`` and ``.md``).
"""

from .adapters import RepoFixProposalFactory, WorktreeSandbox
from .apply import ApplyResult, apply_fix
from .ci_verification import CIProvider, CIRunState, CIRunStatus, GitHubActionsCIProvider, verify_real_ci
from .common import DEFAULT_ENV_ALLOWLIST, FINAL_PATCH_NAME, FIX_DIR, METADATA_NAME, split_command
from .evidence_report import build_repair_evidence, render_repair_evidence_markdown, write_repair_evidence
from .ingest import (
    failure_from_fixture,
    failure_from_github,
    failure_from_log_file,
    failure_from_reproduction,
    related_tracked_paths,
    summarize_failure_message,
)
from .patches import added_files, extract_patch, parse_patch_files
from .prompt import build_prompt
from .proposals import GeneratedText, PatchFileSource, ProposalSource, ProviderCommandSource
from .records import Attempt, AttemptStatus, Task, TaskStore, read_attempts, task_summary
from .remediation_metrics import (
    compute_operational_metrics,
    compute_remediation_metrics,
    load_remediation_records,
    load_run_measurements,
)
from .run import FixRepoConfig, run_fix_repo
from .session import FixSession, VerifyCommand
from .verification import VerificationConfig, load_verification_config, read_verification_config_file

__all__ = [
    "DEFAULT_ENV_ALLOWLIST",
    "FINAL_PATCH_NAME",
    "FIX_DIR",
    "METADATA_NAME",
    "ApplyResult",
    "Attempt",
    "AttemptStatus",
    "CIProvider",
    "CIRunState",
    "CIRunStatus",
    "FixRepoConfig",
    "FixSession",
    "GeneratedText",
    "GitHubActionsCIProvider",
    "PatchFileSource",
    "ProposalSource",
    "ProviderCommandSource",
    "RepoFixProposalFactory",
    "Task",
    "TaskStore",
    "VerificationConfig",
    "VerifyCommand",
    "WorktreeSandbox",
    "added_files",
    "apply_fix",
    "build_prompt",
    "build_repair_evidence",
    "compute_operational_metrics",
    "compute_remediation_metrics",
    "extract_patch",
    "failure_from_fixture",
    "failure_from_github",
    "failure_from_log_file",
    "failure_from_reproduction",
    "load_remediation_records",
    "load_run_measurements",
    "load_verification_config",
    "parse_patch_files",
    "read_attempts",
    "read_verification_config_file",
    "related_tracked_paths",
    "render_repair_evidence_markdown",
    "run_fix_repo",
    "split_command",
    "summarize_failure_message",
    "task_summary",
    "verify_real_ci",
    "write_repair_evidence",
]
