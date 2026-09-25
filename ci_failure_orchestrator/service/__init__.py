"""Canonical CI failure service path (fix-repo / fix-repo-apply).

Composition layer only. The foundation keeps authority over retry, evaluation,
policy and escalation; this package contributes:

* failure ingest (fixture, log file, GitHub Actions run, local reproduction),
* real proposal sources (a patch file or an external provider CLI),
* a sandbox that applies each proposal in a disposable git worktree of the
  target repository and runs explicit verification commands,
* ``apply_fix``: the only code path that writes to the target repository.
"""

from .adapters import RepoFixProposalFactory, WorktreeSandbox
from .apply import ApplyResult, apply_fix
from .common import DEFAULT_ENV_ALLOWLIST, FINAL_PATCH_NAME, FIX_DIR, METADATA_NAME, split_command
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
from .run import FixRepoConfig, run_fix_repo
from .session import FixSession, VerifyCommand

__all__ = [
    "DEFAULT_ENV_ALLOWLIST",
    "FINAL_PATCH_NAME",
    "FIX_DIR",
    "METADATA_NAME",
    "ApplyResult",
    "FixRepoConfig",
    "FixSession",
    "GeneratedText",
    "PatchFileSource",
    "ProposalSource",
    "ProviderCommandSource",
    "RepoFixProposalFactory",
    "VerifyCommand",
    "WorktreeSandbox",
    "added_files",
    "apply_fix",
    "build_prompt",
    "extract_patch",
    "failure_from_fixture",
    "failure_from_github",
    "failure_from_log_file",
    "failure_from_reproduction",
    "parse_patch_files",
    "related_tracked_paths",
    "run_fix_repo",
    "split_command",
    "summarize_failure_message",
]
