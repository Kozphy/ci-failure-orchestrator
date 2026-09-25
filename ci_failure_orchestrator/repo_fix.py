"""fix-repo: verify real patches for another git repository through the foundation.

Composition layer only. The foundation keeps authority over retry, evaluation,
policy and escalation; this module contributes:

* a real proposal source (a patch file or an external provider CLI),
* a sandbox that applies each proposal in a disposable git worktree of the
  target repository and runs explicit verification commands,
* ``apply_fix``: the only code path that writes to the target repository. It
  requires a durable APPROVED workflow (policy or human) and creates a branch
  + commit through a temporary index, never touching the operator's working
  tree or current branch.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from .foundation.models import (
    FailureClassification,
    FailureEvent,
    RepairPlan,
    RepairProposal,
    RunStatus,
    SandboxResult,
    ToolResult,
    new_id,
)
from .foundation.persistence import (
    AuditEventType,
    FileAuditStore,
    FileEvidenceStore,
    FileStateStore,
    append_operator_event,
    verify_run_consistency,
)
from .foundation.policy import FileCategory, classify_file
from .foundation.retry import RetryBudget
from .foundation.runner import AgentExecutionFoundation
from .foundation.sanitization import sanitize_text
from .github_client import GitHubActionsClient
from .patch_sandbox import VerificationStep, WorktreePatchVerifier
from .provider_adapters import ProviderSpec, SandboxRunner

DEFAULT_ENV_ALLOWLIST: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USERPROFILE",
    "TMP",
    "TEMP",
    "SYSTEMROOT",
    "PATHEXT",
    "COMSPEC",
    "APPDATA",
    "LOCALAPPDATA",
)

FIX_DIR = "fix-repo"
METADATA_NAME = "metadata.json"
FINAL_PATCH_NAME = "final.patch"

_MAX_LOG_CHARS = 12_000
_MAX_TRACKED_LISTED = 400
_MAX_RELEVANT_FILES = 6
_MAX_FILE_CHARS = 16_000
_MAX_FEEDBACK_CHARS = 4_000
_SMALL_REPO_FILES = 50

_DIFF_LINE_PREFIXES = (
    "diff ",
    "index ",
    "--- ",
    "+++ ",
    "@@",
    " ",
    "+",
    "-",
    "\\",
    "new file mode",
    "deleted file mode",
    "old mode",
    "new mode",
    "similarity index",
    "dissimilarity index",
    "rename from",
    "rename to",
    "copy from",
    "copy to",
    "Binary files",
)
_FENCE_RE = re.compile(r"```[A-Za-z0-9_-]*[^\n]*\n(.*?)```", re.DOTALL)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+)$")
_GH_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?", re.MULTILINE)
_MESSAGE_RE = re.compile(r"(error|failed|failure|exception|assert|traceback)", re.IGNORECASE)
_SOURCE_PATH_RE = re.compile(
    r"[A-Za-z0-9_.\-/\\:]+\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|go|rs|java|kt|rb|php|cs|c|cc|cpp|h|hpp|swift|scala)\b"
)
_SENSITIVE_CATEGORIES = frozenset({FileCategory.SECURITY})


# --------------------------------------------------------------------------- helpers


def split_command(command: str) -> tuple[str, ...]:
    """Split a command string into argv without shell interpretation.

    Quotes group words; backslashes are kept literally so Windows paths survive.
    The executable is resolved on PATH because commands run with ``shell=False``
    (e.g. ``npm`` -> ``npm.cmd`` on Windows).
    """

    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    argv = list(lexer)
    if not argv:
        raise ValueError("empty command")
    resolved = shutil.which(argv[0])
    if resolved:
        argv[0] = resolved
    return tuple(argv)


def _git(
    repo: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )


def _tail(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[-limit:]


def _decode_patch_bytes(raw: bytes) -> str:
    # PowerShell 5 redirection (`git diff > fix.patch`) writes UTF-16 with a BOM.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _looks_like_diff(text: str) -> bool:
    return ("diff --git " in text or ("--- " in text and "+++ " in text)) and "@@" in text


def _trim_trailing_non_diff(lines: list[str]) -> list[str]:
    end = len(lines)
    while end > 0 and (not lines[end - 1].strip() or not lines[end - 1].startswith(_DIFF_LINE_PREFIXES)):
        end -= 1
    return lines[:end]


def extract_patch(text: str) -> str:
    """Extract a unified diff from free-form text (LLM output or a patch file).

    Prefers a fenced ```diff block; otherwise starts at the first diff header.
    Line endings are normalized to LF and the result ends with a newline.
    Returns "" when no diff is found.
    """

    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    body = ""
    for match in _FENCE_RE.finditer(normalized):
        if _looks_like_diff(match.group(1)):
            body = match.group(1)
            break
    if not body:
        lines = normalized.split("\n")
        for idx, line in enumerate(lines):
            if line.startswith("diff --git ") or (
                line.startswith("--- ") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ ")
            ):
                body = "\n".join(lines[idx:])
                break
    if not body or not _looks_like_diff(body):
        return ""
    kept = _trim_trailing_non_diff(body.split("\n"))
    return "\n".join(kept) + "\n" if kept else ""


def _strip_prefix(path: str, prefix: str) -> str:
    path = path.split("\t", 1)[0].strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    return path.removeprefix(prefix)


def parse_patch_files(patch: str) -> tuple[str, ...]:
    """Files touched by a unified diff, derived from its headers (never trusted from the proposer)."""

    files: dict[str, None] = {}
    lines = patch.split("\n")
    for idx, line in enumerate(lines):
        if line.startswith("diff --git "):
            match = _DIFF_GIT_RE.match(line)
            if match:
                files.setdefault(match.group(1), None)
                files.setdefault(match.group(2), None)
        elif line.startswith("--- ") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ "):
            old = _strip_prefix(line[4:], "a/")
            new = _strip_prefix(lines[idx + 1][4:], "b/")
            for path in (old, new):
                if path and path != "/dev/null":
                    files.setdefault(path, None)
    return tuple(files)


def added_files(patch: str) -> tuple[str, ...]:
    out: list[str] = []
    lines = patch.split("\n")
    for idx, line in enumerate(lines):
        if line.startswith("--- /dev/null") and idx + 1 < len(lines) and lines[idx + 1].startswith("+++ "):
            out.append(_strip_prefix(lines[idx + 1][4:], "b/"))
    return tuple(out)


def _is_unsafe_path(path: str) -> bool:
    p = path.replace("\\", "/")
    return not p or p.startswith("/") or re.match(r"^[A-Za-z]:", p) is not None or ".." in p.split("/")


def summarize_failure_message(log: str) -> str:
    lines = [line.strip() for line in log.splitlines() if line.strip()]
    hits = [line for line in lines if _MESSAGE_RE.search(line)]
    chosen = hits[-1] if hits else (lines[-1] if lines else "")
    return chosen[:300]


def related_tracked_paths(text: str, tracked: Sequence[str], *, limit: int = 8) -> tuple[str, ...]:
    """Tracked repository files mentioned in a log (absolute or relative paths)."""

    tracked_set = set(tracked)
    found: dict[str, None] = {}
    for raw in _SOURCE_PATH_RE.findall(text)[:400]:
        candidate = raw.replace("\\", "/")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        if candidate in tracked_set:
            found.setdefault(candidate, None)
        else:
            for path in tracked:
                if candidate.endswith("/" + path):
                    found.setdefault(path, None)
                    break
        if len(found) >= limit:
            break
    return tuple(found)


# --------------------------------------------------------------------------- failure sources


def failure_from_fixture(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(raw.get("failure", raw))


def failure_from_log_file(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    log = _tail(text, _MAX_LOG_CHARS)
    return {
        "source": "log_file",
        "workflow": "ci",
        "job": "ci",
        "failed_step": "unknown",
        "message": summarize_failure_message(log),
        "log_excerpt": log,
    }


def failure_from_github(
    repository: str,
    run_id: int,
    *,
    token: str | None = None,
    api_url: str = "https://api.github.com",
    timeout: float = 30.0,
) -> dict[str, Any]:
    evidence = GitHubActionsClient(token=token, api_url=api_url, timeout=timeout).collect_run(
        repository, run_id, include_logs=True
    )
    failed_conclusions = {"failure", "timed_out", "cancelled", "action_required"}
    job = next((j for j in evidence.jobs if j.get("conclusion") in failed_conclusions), None)
    if job is None:
        raise ValueError(f"no failed job found in {repository} run {run_id}")
    step = next(
        (s for s in job.get("steps") or [] if s.get("conclusion") in failed_conclusions),
        None,
    )
    job_name = str(job.get("name") or job.get("id"))
    log = _GH_TIMESTAMP_RE.sub("", evidence.logs.get(job_name, ""))
    log = _tail(log, _MAX_LOG_CHARS)
    return {
        "source": "github_actions",
        "repository": repository,
        "workflow": str(job.get("workflow_name") or "ci"),
        "job": job_name,
        "failed_step": str((step or {}).get("name") or "unknown"),
        "message": summarize_failure_message(log) or f"{job_name} failed",
        "commit_sha": str(job.get("head_sha") or ""),
        "branch": str(job.get("head_branch") or ""),
        "log_excerpt": log,
        "raw_log_ref": str(job.get("html_url") or ""),
    }


def failure_from_reproduction(steps: Sequence[VerificationStep], commands: Sequence[VerifyCommand]) -> dict[str, Any]:
    failing = next((s for s in steps if not s.passed), steps[-1])
    display = next((c.display for c in commands if c.name == failing.name), failing.name)
    output = _tail(f"{failing.stdout}\n{failing.stderr}".strip(), _MAX_LOG_CHARS)
    return {
        "source": "local_reproduction",
        "workflow": "local",
        "job": "verify",
        "failed_step": display,
        "message": summarize_failure_message(output) or f"{display} exited {failing.returncode}",
        "exit_code": failing.returncode,
        "log_excerpt": output,
    }


# --------------------------------------------------------------------------- proposal sources


@dataclass(frozen=True)
class VerifyCommand:
    name: str
    display: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class GeneratedText:
    text: str
    error: str | None = None
    detail: str = ""


class ProposalSource(Protocol):
    name: str

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText: ...


class PatchFileSource:
    """Returns the same operator-supplied patch on every attempt."""

    name = "patch-file"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        try:
            return GeneratedText(_decode_patch_bytes(self.path.read_bytes()))
        except OSError as exc:
            return GeneratedText("", "provider_failed", f"cannot read patch file: {exc}")


class ProviderCommandSource:
    """Runs an external CLI (prompt on stdin, empty temp cwd, env allowlist)."""

    name = "provider-cmd"

    def __init__(
        self,
        argv: Sequence[str],
        *,
        timeout_seconds: int = 600,
        env_passthrough: Sequence[str] = (),
    ) -> None:
        self.spec = ProviderSpec(
            name="fix-repo-provider",
            argv=tuple(argv),
            timeout_seconds=timeout_seconds,
            max_output_chars=200_000,
        )
        self.runner = SandboxRunner(env_allowlist=DEFAULT_ENV_ALLOWLIST + tuple(env_passthrough))

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        run = self.runner.run(self.spec, prompt=prompt)
        if run.returncode != 0:
            return GeneratedText(run.stdout, "provider_failed", _tail(run.stderr, 2_000))
        return GeneratedText(run.stdout)


# --------------------------------------------------------------------------- session / factory / sandbox


@dataclass
class FixSession:
    repo: Path
    base_commit: str
    commands: tuple[VerifyCommand, ...]
    failure: dict[str, Any]
    baseline: tuple[VerificationStep, ...]
    tracked_files: tuple[str, ...]
    artifacts_root: Path
    feedback: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None


def _read_base_file(session: FixSession, path: str) -> str | None:
    shown = _git(session.repo, "show", f"{session.base_commit}:{path}")
    if shown.returncode != 0 or "\x00" in shown.stdout:
        return None
    return shown.stdout


def build_prompt(session: FixSession, *, attempt_number: int, changed_paths: Sequence[str]) -> str:
    failure = session.failure
    parts: list[str] = [
        "You are fixing a failing CI check in a git repository.",
        "Respond with exactly one unified diff in git format (paths relative to the repository root,",
        "using a/ and b/ prefixes) inside a single ```diff fenced block, followed by one line that",
        "starts with 'Rationale:'.",
        "Rules: make the smallest change that makes the verification commands pass; context lines must",
        "match the file contents shown below exactly; do not modify CI workflows, secrets, credentials",
        "or dependency manifests unless the failure clearly requires it.",
        "",
        "## Failure",
        f"workflow: {failure.get('workflow', '')}",
        f"job: {failure.get('job', '')}",
        f"failed step: {failure.get('failed_step', '')}",
        f"message: {failure.get('message', '')}",
    ]
    log = str(failure.get("log_excerpt") or "")
    if log:
        parts += ["", "## CI log excerpt (tail)", "```", _tail(log, _MAX_LOG_CHARS), "```"]

    failing_baseline = next((s for s in session.baseline if not s.passed), None)
    if failing_baseline is not None and failure.get("source") != "local_reproduction":
        parts += [
            "",
            f"## Local reproduction at base commit (step {failing_baseline.name}, exit {failing_baseline.returncode})",
            "```",
            _tail(f"{failing_baseline.stdout}\n{failing_baseline.stderr}".strip(), _MAX_FEEDBACK_CHARS),
            "```",
        ]

    parts += ["", "## Verification commands (all must pass after your patch)"]
    parts += [f"- {c.display}" for c in session.commands]

    for item in session.feedback[-2:]:
        parts += [
            "",
            f"## Previous attempt {item['attempt']} failed: {item['reason']}",
            "Do not repeat that patch.",
        ]
        if item.get("output"):
            parts += ["```", item["output"], "```"]

    tracked = session.tracked_files
    listed = tracked[:_MAX_TRACKED_LISTED]
    parts += ["", f"## Tracked files ({len(tracked)} total, first {len(listed)} shown)"]
    parts += list(listed)

    tracked_set = set(tracked)
    candidates: dict[str, None] = {}
    for path in changed_paths:
        normalized = path.replace("\\", "/")
        if normalized in tracked_set:
            candidates.setdefault(normalized, None)
    for item in session.feedback[-1:]:
        for path in related_tracked_paths(item.get("output", ""), tracked):
            candidates.setdefault(path, None)
    if not candidates and len(tracked) <= _SMALL_REPO_FILES:
        for path in tracked:
            if classify_file(path) in (FileCategory.SOURCE, FileCategory.TEST):
                candidates.setdefault(path, None)
    shown = 0
    redacted_any = False
    for path in candidates:
        if shown >= _MAX_RELEVANT_FILES:
            break
        if classify_file(path) in _SENSITIVE_CATEGORIES:
            continue
        content = _read_base_file(session, path)
        if content is None:
            continue
        cleaned, redactions = sanitize_text(content[:_MAX_FILE_CHARS])
        redacted_any = redacted_any or redactions > 0
        truncated = " (truncated)" if len(content) > _MAX_FILE_CHARS else ""
        parts += ["", f"## File: {path}{truncated}", "```", cleaned, "```"]
        shown += 1
    if redacted_any:
        parts += [
            "",
            "Note: lines containing [REDACTED_SECRET] were altered for safety; do not use them as diff context.",
        ]
    parts += ["", f"(attempt {attempt_number})"]
    prompt, _ = sanitize_text("\n".join(parts))
    return prompt


def _extract_rationale(text: str) -> str:
    for line in reversed(text.replace("\r\n", "\n").split("\n")):
        stripped = line.strip()
        if stripped.lower().startswith("rationale:"):
            return stripped.split(":", 1)[1].strip()[:500]
    return ""


class RepoFixProposalFactory:
    """ProposalFactory for the foundation runner backed by a real proposal source."""

    def __init__(self, session: FixSession, source: ProposalSource) -> None:
        self.session = session
        self.source = source
        self.evidence = FileEvidenceStore(session.artifacts_root)

    def __call__(
        self,
        *,
        run_id: str,
        plan: RepairPlan,
        classification: FailureClassification,
        attempt_number: int,
        paths: tuple[str, ...],
        force_forbidden_path: bool,
    ) -> RepairProposal:
        prompt = build_prompt(self.session, attempt_number=attempt_number, changed_paths=paths)
        generated = self.source.generate(prompt, attempt_number)
        patch = extract_patch(generated.text)
        files = parse_patch_files(patch)
        self.session.last_error = generated.error or (None if patch else "no_patch_extracted")
        if self.source.name == "provider-cmd":
            self.evidence.write_text(run_id, FIX_DIR, prompt, name=f"attempt-{attempt_number:03d}-prompt.txt")
            response = generated.text + (f"\n\n[stderr]\n{generated.detail}" if generated.detail else "")
            self.evidence.write_text(run_id, FIX_DIR, response, name=f"attempt-{attempt_number:03d}-response.txt")
        rationale = _extract_rationale(generated.text) or f"{self.source.name} proposal (attempt {attempt_number})"
        return RepairProposal(
            proposal_id=new_id("prop"),
            run_id=run_id,
            files_changed=files,
            patch=patch,
            rationale=rationale,
            expected_effect="All verification commands pass: " + "; ".join(c.display for c in self.session.commands),
            verification_plan=tuple(c.display for c in self.session.commands),
        )


class WorktreeSandbox:
    """SandboxExecutor that verifies a proposal in a disposable worktree of the target repo."""

    def __init__(self, session: FixSession, verifier: WorktreePatchVerifier) -> None:
        self.session = session
        self.verifier = verifier
        self.attempt = 0

    def _record(self, reason: str, output: str = "") -> None:
        self.session.feedback.append(
            {"attempt": self.attempt, "reason": reason, "output": _tail(output, _MAX_FEEDBACK_CHARS)}
        )

    def execute(
        self,
        proposal: RepairProposal,
        verification_steps: tuple[str, ...],
        *,
        target_should_pass: bool = True,
    ) -> SandboxResult:
        self.attempt += 1
        if not proposal.patch.strip():
            error = self.session.last_error or "no_patch_extracted"
            self._record(error, "No unified diff was found in the response.")
            return SandboxResult(proposal.run_id, proposal.proposal_id, False, False, (), (), error=error, workspace="git-worktree")

        unsafe = [p for p in proposal.files_changed if _is_unsafe_path(p)]
        if unsafe:
            self._record("forbidden_path_outside_repo", ", ".join(unsafe))
            return SandboxResult(
                proposal.run_id, proposal.proposal_id, False, False, (), tuple(unsafe),
                error="forbidden_path_outside_repo", workspace="git-worktree",
            )

        result = self.verifier.verify(
            repo_path=self.session.repo,
            patch_text=proposal.patch,
            base_ref=self.session.base_commit,
        )
        displays = {c.name: c.display for c in self.session.commands}
        command_results: list[ToolResult] = [
            ToolResult(
                tool_name=f"verify:{step.name}",
                success=step.passed,
                exit_code=step.returncode,
                stdout=step.stdout,
                stderr=step.stderr,
                metadata={"command": displays.get(step.name, step.name), "latency_ms": round(step.latency_ms, 1)},
            )
            for step in result.steps
        ]
        failing = next((s for s in result.steps if not s.passed), None)
        if result.applied:
            command_results.append(
                ToolResult(
                    tool_name="test_runner",
                    success=result.passed,
                    exit_code=0 if result.passed else (failing.returncode if failing else 1),
                    stdout=(
                        "all verification commands passed"
                        if result.passed
                        else f"failed: {displays.get(failing.name, failing.name) if failing else 'no commands'}"
                    ),
                    metadata={"steps": len(result.steps), "patch_sha256": result.patch_sha256},
                )
            )
        timeout = any(s.returncode == 124 and "verification_timeout" in s.stderr for s in result.steps)
        error = None if result.applied else (result.reason or "patch_apply_failed")

        if not result.applied:
            self._record(error, "git apply rejected the patch; context lines must match the base files exactly.")
        elif not result.passed:
            label = displays.get(failing.name, failing.name) if failing else "verification"
            output = f"{failing.stdout}\n{failing.stderr}".strip() if failing else ""
            self._record(f"verification command failed: {label}", output)

        changed = tuple(dict.fromkeys((*result.changed_files, *proposal.files_changed)))
        return SandboxResult(
            run_id=proposal.run_id,
            proposal_id=proposal.proposal_id,
            success=result.passed,
            patch_applied=result.applied,
            command_results=tuple(command_results),
            changed_files=changed,
            timeout=timeout,
            error=error,
            workspace="git-worktree",
        )


# --------------------------------------------------------------------------- run


@dataclass
class FixRepoConfig:
    repo_path: Path
    verify_commands: Sequence[str]
    patch_file: Path | None = None
    provider_cmd: str | None = None
    provider_env: Sequence[str] = ()
    provider_timeout: int = 600
    verify_env: Sequence[str] = ()
    verify_timeout: int = 600
    base_ref: str = "HEAD"
    max_attempts: int = 3
    artifacts_root: Path = Path("artifacts")
    failure: dict[str, Any] | None = None


def _outcome(**values: Any) -> dict[str, Any]:
    values.setdefault("primary_workspace_mutated", False)
    return values


def _build_commands(raw: Sequence[str]) -> tuple[VerifyCommand, ...]:
    commands = tuple(
        VerifyCommand(name=f"step-{idx}", display=cmd.strip(), argv=split_command(cmd))
        for idx, cmd in enumerate(raw, start=1)
        if cmd.strip()
    )
    if not commands:
        raise ValueError("at least one --verify command is required")
    return commands


def _build_source(config: FixRepoConfig) -> ProposalSource:
    if bool(config.patch_file) == bool(config.provider_cmd):
        raise ValueError("exactly one of --patch-file or --provider-cmd is required")
    if config.patch_file:
        return PatchFileSource(config.patch_file)
    return ProviderCommandSource(
        split_command(str(config.provider_cmd)),
        timeout_seconds=config.provider_timeout,
        env_passthrough=config.provider_env,
    )


def run_fix_repo(config: FixRepoConfig) -> dict[str, Any]:
    repo = Path(config.repo_path).resolve()
    artifacts_root = Path(config.artifacts_root).resolve()
    if not (repo / ".git").exists():
        return _outcome(outcome="ERROR", message=f"not a git repository: {repo}")

    try:
        commands = _build_commands(config.verify_commands)
        source = _build_source(config)
    except ValueError as exc:
        return _outcome(outcome="ERROR", message=str(exc))

    rev = _git(repo, "rev-parse", "--verify", f"{config.base_ref}^{{commit}}")
    if rev.returncode != 0:
        return _outcome(outcome="ERROR", message=f"cannot resolve base ref {config.base_ref!r}: {rev.stderr.strip()}")
    base_commit = rev.stdout.strip()

    verifier = WorktreePatchVerifier(
        commands=[(c.name, c.argv) for c in commands],
        timeout_seconds=config.verify_timeout,
        env_allowlist=DEFAULT_ENV_ALLOWLIST + tuple(config.verify_env),
    )
    baseline = verifier.reproduce(repo_path=repo, base_ref=base_commit)
    if baseline is None:
        return _outcome(outcome="ERROR", message="could not create a disposable worktree at the base commit")
    if baseline and all(step.passed for step in baseline):
        return _outcome(
            outcome="NO_FAILURE",
            repo_path=str(repo),
            base_commit=base_commit,
            message=(
                "All verification commands already pass at the base commit, so no patch can be shown to fix "
                "anything. Use --verify commands that reproduce the CI failure locally."
            ),
        )

    failure = dict(config.failure) if config.failure else failure_from_reproduction(baseline, commands)
    tracked = tuple(
        line for line in _git(repo, "ls-tree", "-r", "--name-only", base_commit).stdout.splitlines() if line
    )
    if not failure.get("changed_paths"):
        failure["changed_paths"] = list(
            related_tracked_paths(str(failure.get("log_excerpt") or "") + "\n" + str(failure.get("message") or ""), tracked)
        )

    run_id = new_id("run")
    failure.setdefault("source", "fix-repo")
    failure["commit_sha"] = failure.get("commit_sha") or base_commit
    failure["repository"] = failure.get("repository") or str(repo)
    event = FailureEvent.from_dict(failure, run_id=run_id)

    session = FixSession(
        repo=repo,
        base_commit=base_commit,
        commands=commands,
        failure=failure,
        baseline=baseline,
        tracked_files=tracked,
        artifacts_root=artifacts_root,
    )
    foundation = AgentExecutionFoundation(
        sandbox=WorktreeSandbox(session, verifier),
        proposal_factory=RepoFixProposalFactory(session, source),
        workspace_root=repo,
        artifacts_root=artifacts_root,
        enable_persistence=True,
        retry_budget=RetryBudget(max_attempts=max(1, config.max_attempts)),
    )
    result = foundation.run(event)
    workflow = result.workflow_status or result.status.value
    proposal = result.run.proposal

    patch_path: Path | None = None
    files_changed: tuple[str, ...] = ()
    if result.technical_status == "PASS" and proposal is not None:
        files_changed = parse_patch_files(proposal.patch)
        fix_root = artifacts_root / "runs" / run_id / FIX_DIR
        fix_root.mkdir(parents=True, exist_ok=True)
        patch_path = fix_root / FINAL_PATCH_NAME
        patch_path.write_bytes(proposal.patch.encode("utf-8"))
        FileEvidenceStore(artifacts_root).write_json(
            run_id,
            FIX_DIR,
            {
                "repo_path": str(repo),
                "base_ref": config.base_ref,
                "base_commit": base_commit,
                "patch_sha256": sha256(proposal.patch.encode("utf-8")).hexdigest(),
                "files_changed": list(files_changed),
                "verify_commands": [c.display for c in commands],
                "proposal_id": proposal.proposal_id,
                "proposal_source": source.name,
                "failure_message": str(failure.get("message") or "")[:300],
            },
            name=METADATA_NAME,
        )

    next_steps: list[str] = []
    if workflow == RunStatus.APPROVED.value:
        next_steps.append(f"python -m ci_failure_orchestrator.cli fix-repo-apply {run_id} --artifacts {config.artifacts_root}")
    elif workflow == RunStatus.AWAITING_HUMAN.value:
        next_steps.append(f"Review {patch_path} and the escalation package, then:")
        next_steps.append(
            f"python -m ci_failure_orchestrator.cli foundation-decide {run_id} --action APPROVE "
            f"--reviewer <you> --artifacts {config.artifacts_root}"
        )
        next_steps.append(f"python -m ci_failure_orchestrator.cli fix-repo-apply {run_id} --artifacts {config.artifacts_root}")
    else:
        next_steps.append(f"Inspect artifacts under {artifacts_root / 'runs' / run_id}")

    return _outcome(
        outcome=workflow,
        run_id=run_id,
        workflow_status=workflow,
        technical_status=result.technical_status,
        policy_outcome=result.policy_outcome.value if result.policy_outcome else None,
        policy_rules=list(result.policy_decision.matched_rules) if result.policy_decision else [],
        attempts=result.attempts,
        stop_reason=result.stop_reason.value if result.stop_reason else None,
        repo_path=str(repo),
        base_commit=base_commit,
        files_changed=list(files_changed),
        patch_path=str(patch_path) if patch_path else None,
        feedback=session.feedback,
        artifacts=str(artifacts_root / "runs" / run_id),
        next_steps=next_steps,
    )


# --------------------------------------------------------------------------- apply


@dataclass
class ApplyResult:
    status: str  # APPLIED | BLOCKED | PARTIAL
    run_id: str
    message: str
    repo_path: str = ""
    branch: str = ""
    commit: str = ""
    pushed: bool = False
    pr_url: str = ""
    next_steps: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _commit_message(metadata: dict[str, Any], run_id: str, approval: str) -> str:
    summary = str(metadata.get("failure_message") or "repair failing CI check").splitlines()[0][:60]
    lines = [
        f"fix(ci): {summary}",
        "",
        f"Verified by ci-failure-orchestrator run {run_id}.",
        f"Approval: {approval}",
        "Verification commands:",
        *[f"  - {cmd}" for cmd in metadata.get("verify_commands") or []],
        f"Patch sha256: {metadata.get('patch_sha256', '')}",
    ]
    return "\n".join(lines) + "\n"


def apply_fix(
    artifacts_root: Path,
    run_id: str,
    *,
    repo_path: Path | None = None,
    branch: str | None = None,
    remote: str = "origin",
    push: bool = False,
    open_pr: bool = False,
    actor: str = "operator",
) -> ApplyResult:
    """Commit an APPROVED fix-repo patch onto a new branch of the target repository.

    Uses a temporary index (read-tree / apply --cached / commit-tree), so the
    operator's working tree, index and current branch are left untouched.
    """

    artifacts_root = Path(artifacts_root)
    run_root = artifacts_root / "runs" / run_id
    fix_root = run_root / FIX_DIR

    def blocked(message: str) -> ApplyResult:
        return ApplyResult("BLOCKED", run_id, message)

    try:
        state = FileStateStore(artifacts_root).load_run(run_id)
    except Exception as exc:  # noqa: BLE001
        return blocked(f"cannot load run: {exc}")
    report = verify_run_consistency(artifacts_root=artifacts_root, run_id=run_id, state=state)
    if not report.valid:
        return blocked("run is inconsistent: " + "; ".join(i.message for i in report.issues))
    if state.workflow_status != RunStatus.APPROVED.value:
        return blocked(
            f"fix-repo-apply requires workflow APPROVED, found {state.workflow_status}. "
            "Escalated runs need `foundation-decide --action APPROVE` first."
        )

    metadata_path = fix_root / METADATA_NAME
    patch_file = fix_root / FINAL_PATCH_NAME
    if not metadata_path.is_file() or not patch_file.is_file():
        return blocked("not a fix-repo run (fix-repo/metadata.json or final.patch missing)")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    patch_bytes = patch_file.read_bytes()
    if sha256(patch_bytes).hexdigest() != metadata.get("patch_sha256"):
        return blocked("final.patch does not match the verified patch hash")
    patch_text = patch_bytes.decode("utf-8")
    files = parse_patch_files(patch_text)
    if list(files) != list(metadata.get("files_changed") or []):
        return blocked("final.patch files do not match the verified file list")

    events, _ = FileAuditStore(artifacts_root).read_events_tolerant(run_id)
    if any(e.event_type == AuditEventType.TARGET_PATCH_APPLIED.value for e in events):
        return blocked("this run's patch was already applied to the target repository")

    repo = Path(repo_path or metadata.get("repo_path") or "").resolve()
    if not (repo / ".git").exists():
        return blocked(f"not a git repository: {repo}")
    base_commit = str(metadata.get("base_commit") or "")
    if _git(repo, "cat-file", "-e", f"{base_commit}^{{commit}}").returncode != 0:
        return blocked(f"base commit {base_commit} not found in {repo}")

    branch_name = branch or f"ci-orchestrator/fix-{run_id}"
    if _git(repo, "check-ref-format", "--branch", branch_name).returncode != 0:
        return blocked(f"invalid branch name: {branch_name}")
    if _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch_name}").returncode == 0:
        return blocked(f"branch already exists: {branch_name}")

    approval = (
        f"human APPROVE ({state.stop_reason})" if state.stop_reason == "human_approve" else "policy APPROVE"
    )

    with tempfile.TemporaryDirectory(prefix="ci-orchestrator-apply-") as temp_dir:
        tmp = Path(temp_dir)
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(tmp / "index")
        (tmp / "fix.patch").write_bytes(patch_bytes)
        (tmp / "message.txt").write_bytes(_commit_message(metadata, run_id, approval).encode("utf-8"))

        steps = (
            ("read-tree", ("read-tree", base_commit)),
            ("apply", ("apply", "--cached", "--whitespace=nowarn", str(tmp / "fix.patch"))),
        )
        for label, args in steps:
            done = _git(repo, *args, env=env)
            if done.returncode != 0:
                return blocked(f"git {label} failed: {done.stderr.strip()[:500]}")
        tree = _git(repo, "write-tree", env=env)
        if tree.returncode != 0:
            return blocked(f"git write-tree failed: {tree.stderr.strip()[:500]}")
        commit = _git(repo, "commit-tree", tree.stdout.strip(), "-p", base_commit, "-F", str(tmp / "message.txt"), env=env)
        if commit.returncode != 0:
            return blocked(f"git commit-tree failed (is user.name/user.email configured?): {commit.stderr.strip()[:500]}")
    commit_sha = commit.stdout.strip()

    diff_names = {
        line for line in _git(repo, "diff", "--name-only", base_commit, commit_sha).stdout.splitlines() if line
    }
    if not diff_names or not diff_names <= set(files):
        return blocked(f"commit contents do not match the verified patch: {sorted(diff_names)}")

    created = _git(repo, "update-ref", f"refs/heads/{branch_name}", commit_sha, "")
    if created.returncode != 0:
        return blocked(f"could not create branch {branch_name}: {created.stderr.strip()[:500]}")

    evidence = FileEvidenceStore(artifacts_root)
    apply_ref = evidence.write_json(
        run_id,
        "target",
        {
            "repo_path": str(repo),
            "branch": branch_name,
            "commit": commit_sha,
            "base_commit": base_commit,
            "files": sorted(diff_names),
            "approval": approval,
            "working_tree_touched": False,
        },
        name="apply.json",
    )
    append_operator_event(
        artifacts_root,
        run_id,
        AuditEventType.TARGET_PATCH_APPLIED,
        actor=actor,
        component="fix_repo_apply",
        evidence_refs=(apply_ref,),
        metadata={"branch": branch_name, "commit": commit_sha, "repo_path": str(repo)},
    )

    result = ApplyResult(
        "APPLIED",
        run_id,
        f"Created branch {branch_name} at {commit_sha[:12]}; working tree and current branch untouched.",
        repo_path=str(repo),
        branch=branch_name,
        commit=commit_sha,
    )

    if push or open_pr:
        pushed = _git(repo, "push", "--set-upstream", remote, f"refs/heads/{branch_name}:refs/heads/{branch_name}", timeout=300)
        if pushed.returncode != 0:
            result.status = "PARTIAL"
            result.message += f" Push failed: {pushed.stderr.strip()[:500]}"
            result.next_steps = [f"git -C {repo} push --set-upstream {remote} {branch_name}"]
            return result
        result.pushed = True
        append_operator_event(
            artifacts_root, run_id, AuditEventType.TARGET_BRANCH_PUSHED,
            actor=actor, component="fix_repo_apply", metadata={"branch": branch_name, "remote": remote},
        )

    if open_pr:
        gh = shutil.which("gh")
        if gh is None:
            result.status = "PARTIAL"
            result.message += " GitHub CLI (gh) not found; PR not opened."
            result.next_steps = [f"gh pr create --head {branch_name} --fill"]
            return result
        title = _commit_message(metadata, run_id, approval).splitlines()[0]
        body = _commit_message(metadata, run_id, approval)
        pr = subprocess.run(
            [gh, "pr", "create", "--head", branch_name, "--title", title, "--body", body],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, timeout=300,
        )
        if pr.returncode != 0:
            result.status = "PARTIAL"
            result.message += f" gh pr create failed: {pr.stderr.strip()[:500]}"
            return result
        result.pr_url = pr.stdout.strip().splitlines()[-1] if pr.stdout.strip() else ""
        append_operator_event(
            artifacts_root, run_id, AuditEventType.TARGET_PR_OPENED,
            actor=actor, component="fix_repo_apply", metadata={"branch": branch_name, "url": result.pr_url},
        )

    if not result.pushed:
        result.next_steps = [f"git -C {repo} switch {branch_name}", f"git -C {repo} push --set-upstream {remote} {branch_name}"]
    return result
