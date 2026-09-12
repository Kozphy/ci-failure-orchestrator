"""CLI entry point that evaluates normalized review evidence for CI.

Exit code 0 means PR_READY. Any malformed input, missing control, or BLOCK
result exits non-zero, making this suitable for a required GitHub Actions job.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .review_collectors import collect_coderabbit, collect_copilot, collect_sonarqube
from .review_gate import GateDecision, ReviewAggregator, ReviewPolicyEngine, VerificationResult


def _load(path: Path) -> dict[str, Any]:
    """Load one JSON evidence document."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def evaluate_files(evidence_dir: Path) -> dict[str, Any]:
    """Evaluate provider and independent-verification evidence files."""
    cr_path = evidence_dir / "coderabbit.json"
    cp_path = evidence_dir / "copilot.json"
    sq_path = evidence_dir / "sonarqube.json"
    iv_path = evidence_dir / "independent_verification.json"

    coderabbit = collect_coderabbit(_load(cr_path), evidence_ref=str(cr_path))
    copilot = collect_copilot(_load(cp_path), evidence_ref=str(cp_path))
    sonarqube = collect_sonarqube(_load(sq_path), evidence_ref=str(sq_path))
    verification_payload = _load(iv_path)
    refs = verification_payload.get("evidence_refs", ())
    if not isinstance(refs, list) or not all(isinstance(item, str) and item for item in refs):
        refs = []
    verification = VerificationResult(
        passed=verification_payload.get("passed") is True,
        evidence_refs=tuple(refs),
    )

    bundle = ReviewAggregator().aggregate((coderabbit, copilot, sonarqube), verification)
    decision = ReviewPolicyEngine().evaluate(bundle)
    return {
        "decision": decision.decision.value,
        "reasons": list(decision.reasons),
        "finding_count": decision.finding_count,
        "evidence_refs": list(decision.evidence_refs),
    }


def main() -> int:
    """Run the fail-closed gate and emit a machine-readable decision."""
    parser = argparse.ArgumentParser(description="Evaluate multi-review PR evidence")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = evaluate_files(args.evidence_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"decision": GateDecision.BLOCK.value, "reasons": [f"evidence error: {exc}"]}

    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result["decision"] == GateDecision.PR_READY.value else 1


if __name__ == "__main__":
    raise SystemExit(main())
