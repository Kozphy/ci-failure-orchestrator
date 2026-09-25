"""Deterministic proposal factories (scripted tests and the heuristic default)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .models import FailureClassification, RepairPlan, RepairProposal, new_id

ProposalFactory = Callable[..., RepairProposal]


class ScriptedProposalFactory:
    """Yields predetermined patches / proposals for deterministic retry/policy tests."""

    def __init__(self, patches: Sequence[str] | Sequence[RepairProposal]) -> None:
        self._items = list(patches)
        self._index = 0

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
        if not self._items:
            raise RuntimeError("ScriptedProposalFactory has no items")
        idx = min(self._index, len(self._items) - 1)
        self._index += 1
        item = self._items[idx]
        if isinstance(item, RepairProposal):
            return RepairProposal(
                proposal_id=new_id("prop"),
                run_id=run_id,
                files_changed=item.files_changed,
                patch=item.patch,
                rationale=item.rationale,
                expected_effect=item.expected_effect,
                verification_plan=item.verification_plan or plan.verification_steps,
            )
        use_paths = ("secrets/token",) if force_forbidden_path else paths[:5]
        return RepairProposal(
            proposal_id=new_id("prop"),
            run_id=run_id,
            files_changed=use_paths,
            patch=item,
            rationale=f"Scripted proposal attempt={attempt_number} ({classification.category})",
            expected_effect="Restore targeted verification without broadening scope",
            verification_plan=plan.verification_steps,
        )


def default_proposal_factory(
    *,
    run_id: str,
    plan: RepairPlan,
    classification: FailureClassification,
    attempt_number: int,
    paths: tuple[str, ...],
    force_forbidden_path: bool,
) -> RepairProposal:
    use_paths = (
        ("secrets/token",)
        if force_forbidden_path
        else paths[:5] or ("src/module.py",)
    )
    return RepairProposal(
        proposal_id=new_id("prop"),
        run_id=run_id,
        files_changed=use_paths,
        patch=(
            f"--- a/{use_paths[0]}\n+++ b/{use_paths[0]}\n"
            f"@@\n+# foundation repair for {classification.category} attempt={attempt_number}\n"
        ),
        rationale=(
            f"Minimal scoped proposal for {classification.category} "
            f"(heuristic confidence={classification.confidence:.2f}; attempt={attempt_number})"
        ),
        expected_effect="Restore targeted verification without broadening scope",
        verification_plan=plan.verification_steps,
    )
