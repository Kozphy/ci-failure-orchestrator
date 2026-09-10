from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from .control_plane import Evaluation
from .patch_sandbox import PatchVerification, WorktreePatchVerifier
from .provider_adapters import ProviderRun


_DIFF_RE = re.compile(
    r"(?ms)^diff --git a/.+? b/.+?(?=^diff --git a/|^```|\Z)"
)


def extract_unified_diff(text: str) -> str:
    """Extract a git-style unified diff from provider output.

    Providers often wrap patches in markdown fences or explanation text. Only
    explicit `diff --git` blocks are accepted; ambiguous prose is rejected.
    """
    matches = _DIFF_RE.findall(text)
    return "\n".join(match.rstrip() for match in matches).strip()


@dataclass(frozen=True)
class RepairExecutionEvidence:
    provider: str
    provider_returncode: int
    provider_latency_ms: float
    patch_found: bool
    patch_sha256: str | None
    applied: bool
    verification_passed: bool
    changed_files: tuple[str, ...]
    verification_latency_ms: float
    score: float
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class VerificationResultEvaluator:
    """Convert deterministic sandbox verification into a provider-neutral score."""

    def evaluate(self, verification: PatchVerification | None, provider_run: ProviderRun) -> Evaluation:
        reasons: list[str] = []
        if provider_run.returncode != 0:
            reasons.append("provider_failed")
        if verification is None:
            reasons.append("no_patch")
            return Evaluation(False, False, 0.0, tuple(reasons))
        if not verification.applied:
            reasons.append(verification.reason or "patch_not_applied")
        failed_steps = [step.name for step in verification.steps if not step.passed]
        if failed_steps:
            reasons.extend(f"failed:{name}" for name in failed_steps)

        passed = provider_run.returncode == 0 and verification.applied and verification.passed
        regression_free = passed
        if passed:
            score = 1.0
        elif verification.applied:
            total = max(1, len(verification.steps))
            passed_steps = sum(step.passed for step in verification.steps)
            score = round(0.25 + 0.5 * (passed_steps / total), 4)
        else:
            score = 0.0
        return Evaluation(passed, regression_free, score, tuple(reasons))


class RepairExecutionPipeline:
    """Bridge provider output to isolated patch verification and durable evidence."""

    def __init__(
        self,
        verifier: WorktreePatchVerifier,
        *,
        evaluator: VerificationResultEvaluator | None = None,
    ) -> None:
        self.verifier = verifier
        self.evaluator = evaluator or VerificationResultEvaluator()

    def run(
        self,
        provider_run: ProviderRun,
        *,
        repo_path: str | Path,
        base_ref: str = "HEAD",
    ) -> tuple[Evaluation, RepairExecutionEvidence]:
        patch_text = extract_unified_diff(provider_run.stdout)
        verification: PatchVerification | None = None
        if provider_run.returncode == 0 and patch_text:
            verification = self.verifier.verify(
                repo_path=repo_path,
                patch_text=patch_text,
                base_ref=base_ref,
            )

        evaluation = self.evaluator.evaluate(verification, provider_run)
        evidence = RepairExecutionEvidence(
            provider=provider_run.provider,
            provider_returncode=provider_run.returncode,
            provider_latency_ms=provider_run.latency_ms,
            patch_found=bool(patch_text),
            patch_sha256=verification.patch_sha256 if verification else None,
            applied=bool(verification and verification.applied),
            verification_passed=bool(verification and verification.passed),
            changed_files=verification.changed_files if verification else (),
            verification_latency_ms=verification.total_latency_ms if verification else 0.0,
            score=evaluation.score,
            reasons=evaluation.reasons,
        )
        return evaluation, evidence


def write_execution_evidence(path: str | Path, evidence: Sequence[RepairExecutionEvidence]) -> None:
    """Persist benchmark/dashboard-ready evidence as deterministic JSON."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = [item.to_dict() for item in evidence]
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
