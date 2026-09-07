from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Mapping, Sequence


@dataclass(frozen=True)
class VerificationStep:
    name: str
    returncode: int
    stdout: str
    stderr: str
    latency_ms: float

    @property
    def passed(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class PatchVerification:
    applied: bool
    clean_after_apply: bool
    passed: bool
    patch_sha256: str
    changed_files: tuple[str, ...]
    steps: tuple[VerificationStep, ...]
    total_latency_ms: float
    reason: str | None = None


class WorktreePatchVerifier:
    """Apply and verify an agent-generated unified diff in a disposable git worktree.

    The verifier never mutates the caller's checkout. It creates a detached
    worktree from a trusted base ref, applies a patch with git apply, executes
    an explicit verification command allowlist, captures bounded output, and
    removes the worktree when finished.
    """

    def __init__(
        self,
        *,
        commands: Sequence[tuple[str, Sequence[str]]],
        timeout_seconds: int = 180,
        max_output_chars: int = 20_000,
        env_allowlist: Sequence[str] = ("PATH", "HOME", "USERPROFILE", "TMP", "TEMP", "SYSTEMROOT"),
    ) -> None:
        self.commands = tuple((name, tuple(argv)) for name, argv in commands)
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self.env_allowlist = tuple(env_allowlist)

    def _env(self, extra_env: Mapping[str, str] | None) -> dict[str, str]:
        env = {key: os.environ[key] for key in self.env_allowlist if key in os.environ}
        if extra_env:
            env.update(extra_env)
        return env

    def _run(self, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(argv), cwd=cwd, env=dict(env), text=True, capture_output=True,
            timeout=self.timeout_seconds, shell=False, check=False,
        )

    def verify(
        self,
        *,
        repo_path: str | Path,
        patch_text: str,
        base_ref: str = "HEAD",
        extra_env: Mapping[str, str] | None = None,
    ) -> PatchVerification:
        from hashlib import sha256

        repo = Path(repo_path).resolve()
        if not (repo / ".git").exists() and not (repo / ".git").is_file():
            raise ValueError(f"not a git repository: {repo}")
        if not patch_text.strip():
            return PatchVerification(False, True, False, sha256(b"").hexdigest(), (), (), 0.0, "empty_patch")

        env = self._env(extra_env)
        patch_hash = sha256(patch_text.encode("utf-8")).hexdigest()
        total_started = perf_counter()

        with tempfile.TemporaryDirectory(prefix="ci-orchestrator-worktree-") as temp_dir:
            worktree = Path(temp_dir) / "repo"
            add = self._run(("git", "worktree", "add", "--detach", str(worktree), base_ref), cwd=repo, env=env)
            if add.returncode != 0:
                return PatchVerification(False, True, False, patch_hash, (), (), (perf_counter() - total_started) * 1000.0, "worktree_create_failed")

            try:
                patch_file = Path(temp_dir) / "agent.patch"
                patch_file.write_text(patch_text, encoding="utf-8")
                check = self._run(("git", "apply", "--check", str(patch_file)), cwd=worktree, env=env)
                if check.returncode != 0:
                    return PatchVerification(False, True, False, patch_hash, (), (), (perf_counter() - total_started) * 1000.0, "patch_check_failed")

                apply = self._run(("git", "apply", "--whitespace=error", str(patch_file)), cwd=worktree, env=env)
                if apply.returncode != 0:
                    return PatchVerification(False, True, False, patch_hash, (), (), (perf_counter() - total_started) * 1000.0, "patch_apply_failed")

                diff = self._run(("git", "diff", "--name-only"), cwd=worktree, env=env)
                changed_files = tuple(line.strip() for line in diff.stdout.splitlines() if line.strip())
                steps: list[VerificationStep] = []

                for name, argv in self.commands:
                    started = perf_counter()
                    try:
                        completed = self._run(argv, cwd=worktree, env=env)
                        latency_ms = (perf_counter() - started) * 1000.0
                        step = VerificationStep(
                            name=name,
                            returncode=completed.returncode,
                            stdout=completed.stdout[-self.max_output_chars :],
                            stderr=completed.stderr[-self.max_output_chars :],
                            latency_ms=latency_ms,
                        )
                    except subprocess.TimeoutExpired as exc:
                        latency_ms = (perf_counter() - started) * 1000.0
                        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
                        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
                        step = VerificationStep(name, 124, stdout[-self.max_output_chars :], (stderr + "\nverification_timeout")[-self.max_output_chars :], latency_ms)
                    steps.append(step)
                    if not step.passed:
                        break

                status = self._run(("git", "status", "--porcelain"), cwd=worktree, env=env)
                clean_after_apply = bool(status.stdout.strip())
                passed = bool(steps) and all(step.passed for step in steps)
                return PatchVerification(
                    applied=True,
                    clean_after_apply=clean_after_apply,
                    passed=passed,
                    patch_sha256=patch_hash,
                    changed_files=changed_files,
                    steps=tuple(steps),
                    total_latency_ms=(perf_counter() - total_started) * 1000.0,
                    reason=None if passed else "verification_failed",
                )
            finally:
                subprocess.run(("git", "worktree", "remove", "--force", str(worktree)), cwd=repo, env=env, text=True, capture_output=True, shell=False, check=False)
                subprocess.run(("git", "worktree", "prune"), cwd=repo, env=env, text=True, capture_output=True, shell=False, check=False)
