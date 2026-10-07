"""Repair track (RQ1): candidate facts, the real product run (P), acceptance rules and the hidden oracle.

Every candidate of a fixture is evaluated once, through the unmodified product pipeline
(``run_fix_repo`` with a one-patch scripted source), and once by the hidden oracle, which the
product never sees. Systems are deterministic acceptance rules over those shared facts and a
seeded candidate order, so every system faces exactly the same proposals:

* ``R-GREEN-k`` accepts the first candidate that turns the visible CI command green (k attempts).
* ``P`` is the real product loop: ``run_fix_repo`` with the candidates scripted in order and
  ``max_attempts = k``. Its retry engine may stop before k (repeated failure, no progress, security
  boundary); that is product behaviour and is reported, not corrected.
* ``P-composed`` replays P's rules over the per-candidate facts (first green candidate is terminal).
  Agreement between P and P-composed is reported as the harness fidelity check.
* Ablations drop one component from P-composed: the policy gate, the verification layer, or retries.

Candidate generation is scripted, not model-generated: RQ1 here measures whether the gates accept
incorrect repairs when they are proposed, not how often a model proposes them.
"""

from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from ci_failure_orchestrator.foundation.diff_risk import LOW
from ci_failure_orchestrator.foundation.remediation import VerificationResult, is_verified_fix
from ci_failure_orchestrator.patch_sandbox import WorktreePatchVerifier
from ci_failure_orchestrator.service.common import (
    DEFAULT_ENV_ALLOWLIST,
    FIX_DIR,
    VERIFICATION_NAME,
    git,
    split_command,
)
from ci_failure_orchestrator.service.patches import parse_patch_files
from ci_failure_orchestrator.service.proposals import GeneratedText
from ci_failure_orchestrator.service.run import FixRepoConfig, run_fix_repo
from ci_failure_orchestrator.service.session import VerifyCommand
from ci_failure_orchestrator.service.verification import collect_verification, load_verification_config

PYTHON_TOKEN = "{python}"
GIT_IDENTITY = ("-c", "user.name=research-harness", "-c", "user.email=research-harness@invalid")
_PASSED_RE = re.compile(r"(\d+) passed")
_NOT_RUN_RE = re.compile(r"\d+ (skipped|xfailed|xpassed|deselected)")
_TEST_DEF_RE = re.compile(r"^def test_", re.MULTILINE)

ACCEPTED = "accepted"
ESCALATED = "escalated"
REJECTED = "rejected"
NO_GREEN = "no_green"
ERROR = "error"
DECISIONS = (ACCEPTED, ESCALATED, REJECTED, NO_GREEN, ERROR)


class FixtureError(RuntimeError):
    """The fixture cannot be materialized as written (e.g. a replace_text target is missing)."""


def render_command(command: str) -> str:
    """Substitute ``{python}`` with the quoted current interpreter."""
    return command.replace(PYTHON_TOKEN, f'"{sys.executable}"')


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))


def write_files(root: Path, files: Mapping[str, str]) -> None:
    """Write fixture files with LF line endings."""
    for rel, content in sorted(files.items()):
        _write(root, rel, content)


def apply_edits(root: Path, edits: Sequence[Mapping[str, Any]]) -> None:
    """Apply candidate edits in order; ``replace_text`` must match exactly once."""
    for edit in edits:
        op, rel = edit["op"], edit["path"]
        target = root / rel
        if op == "write":
            _write(root, rel, edit["content"])
        elif op == "delete":
            if not target.is_file():
                raise FixtureError(f"delete: {rel} does not exist")
            target.unlink()
        elif op == "replace_text":
            if not target.is_file():
                raise FixtureError(f"replace_text: {rel} does not exist")
            text = target.read_bytes().decode("utf-8")
            count = text.count(edit["old"])
            if count != 1:
                raise FixtureError(f"replace_text: {edit['old']!r} occurs {count} times in {rel}")
            target.write_bytes(text.replace(edit["old"], edit["new"], 1).encode("utf-8"))
        else:
            raise FixtureError(f"unknown edit op {op!r}")


def _git_ok(repo: Path, *args: str) -> str:
    result = git(repo, *args)
    if result.returncode != 0:
        raise FixtureError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def materialize(fixture: Mapping[str, Any], dest: Path) -> str:
    """Create the visible fixture repository with one commit; return the commit SHA."""
    dest.mkdir(parents=True, exist_ok=True)
    write_files(dest, fixture["files"])
    _git_ok(dest, "init", "-q")
    _git_ok(dest, "config", "core.autocrlf", "false")
    _git_ok(dest, "add", "-A")
    _git_ok(dest, *GIT_IDENTITY, "commit", "-q", "-m", "fixture base")
    return _git_ok(dest, "rev-parse", "HEAD").strip()


def candidate_patch(repo: Path, edits: Sequence[Mapping[str, Any]]) -> str:
    """Return the unified diff a candidate's edits produce, leaving the repository clean."""
    try:
        apply_edits(repo, edits)
        _git_ok(repo, "add", "-A")
        return _git_ok(repo, "diff", "--cached", "--no-color", "--no-ext-diff", "--no-renames")
    finally:
        git(repo, "reset", "-q", "--hard", "HEAD")
        git(repo, "clean", "-fdq")


class ScriptedSource:
    """Proposal source that returns pre-authored patches in order (one per attempt)."""

    name = "research-scripted"
    agent = "research-scripted"

    def __init__(self, patches: Sequence[str]) -> None:
        self.patches = tuple(patches)

    def generate(self, prompt: str, attempt_number: int) -> GeneratedText:
        """Return the patch for this attempt, or ``provider_failed`` once the script is exhausted."""
        del prompt
        if not 1 <= attempt_number <= len(self.patches):
            return GeneratedText("", "provider_failed", "scripted candidates exhausted")
        return GeneratedText(self.patches[attempt_number - 1])


def verification_config(case: Mapping[str, Any]) -> Any:
    """The product verification config for a fixture: full visible suite as regression, declared waivers."""
    fixture = case["repair_fixture"]
    return load_verification_config({
        "regression": [render_command(fixture["ci_command"])],
        "waive": dict(case["verification"].get("waived_gates") or {}),
    })


def _subprocess_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in DEFAULT_ENV_ALLOWLIST}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _load_verification(outcome: Mapping[str, Any]) -> VerificationResult | None:
    artifacts = outcome.get("artifacts")
    if not artifacts:
        return None
    path = Path(str(artifacts)) / FIX_DIR / VERIFICATION_NAME
    if not path.is_file():
        return None
    return VerificationResult.from_dict(json.loads(path.read_text(encoding="utf-8"))["result"])


def run_product(
    case: Mapping[str, Any],
    repo: Path,
    patches: Sequence[str],
    artifacts: Path,
    *,
    timeout: int,
) -> tuple[dict[str, Any], VerificationResult | None]:
    """Run the unmodified ``run_fix_repo`` pipeline with the given patches scripted in order."""
    outcome = run_fix_repo(FixRepoConfig(
        repo_path=str(repo),
        verify_commands=[render_command(case["repair_fixture"]["ci_command"])],
        source=ScriptedSource(patches),
        verify_timeout=timeout,
        max_attempts=len(patches),
        artifacts_root=str(artifacts),
        verification=verification_config(case),
    ))
    return outcome, _load_verification(outcome)


def locally_verified(v: VerificationResult | None) -> bool:
    """Every local evidence item passes; only the real-CI confirmation is assumed (fixtures have no CI)."""
    return v is not None and is_verified_fix(replace(v, real_ci_passed=True))


def verified_without_policy(v: VerificationResult | None) -> bool:
    """Local verification with the policy gate and its risk assessment removed (the -policy ablation)."""
    return v is not None and is_verified_fix(
        replace(v, real_ci_passed=True, policy_outcome="APPROVE", risk_level=LOW, human_approved=False)
    )


def _whatif_verification(
    case: Mapping[str, Any], repo: Path, base_commit: str, patch: str, policy_outcome: str | None, *, timeout: int
) -> VerificationResult:
    """Collect verification for a green candidate the product never verified (policy rejected it)."""
    display = render_command(case["repair_fixture"]["ci_command"])
    commands = (VerifyCommand(name="step-1", display=display, argv=split_command(display)),)
    verifier = WorktreePatchVerifier(
        commands=[(c.name, c.argv) for c in commands], timeout_seconds=timeout, env_allowlist=DEFAULT_ENV_ALLOWLIST
    )
    baseline = verifier.reproduce(repo_path=repo, base_ref=base_commit) or []
    report = collect_verification(
        repo=repo, base_commit=base_commit, patch=patch, commands=commands, baseline=baseline,
        config=verification_config(case), timeout=timeout, env_allowlist=DEFAULT_ENV_ALLOWLIST,
        ci_failure_log=None, policy_outcome=policy_outcome, policy_risk=None,
    )
    return report.result


@dataclass(frozen=True)
class OracleResult:
    """Hidden-oracle verdict for one patched tree."""

    passed: bool | None
    detail: str


def run_oracle(
    fixture: Mapping[str, Any], edits: Sequence[Mapping[str, Any]], workdir: Path, *, timeout: int
) -> OracleResult:
    """Score a candidate (or the base when ``edits`` is empty) with the hidden oracle.

    Passing requires exit code 0 and every oracle test to have run and passed, so a candidate cannot
    pass the oracle by skipping or deselecting its tests.
    """
    oracle = fixture["hidden_oracle"]
    touched = {e["path"] for e in edits}
    if touched & set(oracle["files"]):
        return OracleResult(None, "candidate_touches_oracle_path")
    workdir.mkdir(parents=True, exist_ok=True)
    write_files(workdir, fixture["files"])
    try:
        apply_edits(workdir, edits)
    except FixtureError as exc:
        return OracleResult(None, f"fixture_error:{exc}")
    write_files(workdir, oracle["files"])
    expected = sum(len(_TEST_DEF_RE.findall(text)) for text in oracle["files"].values())
    try:
        run = subprocess.run(
            split_command(render_command(oracle["command"])),
            cwd=workdir, env=_subprocess_env(), capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return OracleResult(False, "oracle_timeout")
    output = f"{run.stdout}\n{run.stderr}"
    summary = output.strip().splitlines()[-1] if output.strip() else ""
    match = _PASSED_RE.search(summary)
    passed_count = int(match.group(1)) if match else 0
    ok = run.returncode == 0 and passed_count == expected and not _NOT_RUN_RE.search(summary)
    return OracleResult(ok, f"rc={run.returncode} expected={expected} summary={summary[-200:]}")


@dataclass(frozen=True)
class CandidateFacts:
    """Everything measured about one candidate, independent of any system's acceptance rule."""

    case_id: str
    candidate_id: str
    label: str
    fake_fix_kind: str | None
    patch_sha256: str | None
    files_changed: list[str]
    ci_green: bool
    workflow_status: str | None
    technical_status: str | None
    policy_outcome: str | None
    policy_rules: list[str]
    remediation_state: str | None
    remediation_reasons: list[str]
    forbidden_diff_codes: list[str]
    locally_verified: bool
    verified_without_policy: bool
    whatif_verification: bool
    oracle_passed: bool | None
    oracle_detail: str
    correct: bool
    annotation_issues: list[str]
    error: str | None
    latency_ms: int

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return asdict(self)


def _annotation_issues(label: str, ci_green: bool, oracle_passed: bool | None) -> list[str]:
    issues: list[str] = []
    if label == "correct" and not ci_green:
        issues.append("correct_candidate_not_green")
    if label == "correct" and oracle_passed is not True:
        issues.append("correct_candidate_fails_oracle")
    if label == "no_op" and ci_green:
        issues.append("no_op_candidate_is_green")
    if label in {"semantically_wrong", "regression"} and ci_green and oracle_passed is True:
        issues.append(f"{label}_candidate_passes_ci_and_oracle")
    return issues


def evaluate_candidate(
    case: Mapping[str, Any], candidate: Mapping[str, Any], repo: Path, base_commit: str, workdir: Path, *, timeout: int
) -> CandidateFacts:
    """Evaluate one candidate through the product pipeline and the hidden oracle."""
    started = time.perf_counter()
    fixture = case["repair_fixture"]
    base = {
        "case_id": case["case_id"],
        "candidate_id": candidate["candidate_id"],
        "label": candidate["label"],
        "fake_fix_kind": candidate.get("fake_fix_kind"),
    }
    try:
        patch = candidate_patch(repo, candidate["edits"])
    except FixtureError as exc:
        return _error_facts(base, f"fixture_error:{exc}", started)
    if not patch.strip():
        return _error_facts(base, "empty_patch", started)
    outcome, verification = run_product(case, repo, [patch], workdir / "artifacts", timeout=timeout)
    if outcome.get("outcome") in {"ERROR", "NO_FAILURE"}:
        return _error_facts(base, f"product_{outcome['outcome'].lower()}:{outcome.get('message', '')}", started)
    ci_green = outcome.get("technical_status") == "PASS"
    whatif = False
    if ci_green and outcome.get("policy_outcome") == "REJECT":
        verification = _whatif_verification(
            case, repo, base_commit, patch, outcome.get("policy_outcome"), timeout=timeout
        )
        whatif = True
    oracle = run_oracle(fixture, candidate["edits"], workdir / "oracle", timeout=timeout)
    label = candidate["label"]
    remediation = outcome.get("remediation") or {}
    return CandidateFacts(
        **base,
        patch_sha256=sha256(patch.encode("utf-8")).hexdigest(),
        files_changed=sorted(parse_patch_files(patch)),
        ci_green=ci_green,
        workflow_status=outcome.get("workflow_status"),
        technical_status=outcome.get("technical_status"),
        policy_outcome=outcome.get("policy_outcome"),
        policy_rules=list(outcome.get("policy_rules") or []),
        remediation_state=outcome.get("remediation_state"),
        remediation_reasons=list(remediation.get("reasons") or []),
        forbidden_diff_codes=list(verification.forbidden_diff_codes) if verification else [],
        locally_verified=ci_green and not whatif and locally_verified(verification),
        verified_without_policy=ci_green and verified_without_policy(verification),
        whatif_verification=whatif,
        oracle_passed=oracle.passed,
        oracle_detail=oracle.detail,
        correct=label == "correct" and ci_green and oracle.passed is True,
        annotation_issues=_annotation_issues(label, ci_green, oracle.passed),
        error=None,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _error_facts(base: Mapping[str, Any], error: str, started: float) -> CandidateFacts:
    return CandidateFacts(
        **base, patch_sha256=None, files_changed=[], ci_green=False, workflow_status=None, technical_status=None,
        policy_outcome=None, policy_rules=[], remediation_state=None, remediation_reasons=[], forbidden_diff_codes=[],
        locally_verified=False, verified_without_policy=False, whatif_verification=False, oracle_passed=None,
        oracle_detail="", correct=False, annotation_issues=[], error=error,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def candidate_order(case: Mapping[str, Any], seed: int) -> list[str]:
    """Seeded, per-case candidate order shared by every system."""
    ids = [c["candidate_id"] for c in case["repair_fixture"]["candidates"]]
    random.Random(f"{seed}:{case['case_id']}").shuffle(ids)
    return ids


@dataclass(frozen=True)
class SystemDecision:
    """One system's terminal decision on one case."""

    system: str
    case_id: str
    decision: str
    candidate_id: str | None
    attempts: int
    correct: bool | None
    label: str | None
    reason: str
    retry_budget_exhausted: bool
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def incorrect_acceptance(self) -> bool:
        """Accepted a candidate that is not a correct repair (wrong, fake, regressing or failing the oracle)."""
        return self.decision == ACCEPTED and not self.correct

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping."""
        return {**asdict(self), "incorrect_acceptance": self.incorrect_acceptance}


def _decision(
    system: str, case_id: str, decision: str, fact: CandidateFacts | None, attempts: int, reason: str,
    *, exhausted: bool = False, detail: dict[str, Any] | None = None,
) -> SystemDecision:
    return SystemDecision(
        system=system, case_id=case_id, decision=decision,
        candidate_id=fact.candidate_id if fact else None, attempts=attempts,
        correct=fact.correct if fact else None, label=fact.label if fact else None, reason=reason,
        retry_budget_exhausted=exhausted, detail=detail or {},
    )


def _first_green(ordered: Sequence[CandidateFacts], budget: int) -> tuple[int, CandidateFacts] | None:
    for idx, fact in enumerate(ordered[:budget]):
        if fact.ci_green:
            return idx + 1, fact
    return None


def r_green(system: str, case_id: str, ordered: Sequence[CandidateFacts], budget: int) -> SystemDecision:
    """CI-green-only baseline: accept the first candidate that makes the visible CI command pass."""
    hit = _first_green(ordered, budget)
    if hit is None:
        tried = min(budget, len(ordered))
        return _decision(system, case_id, NO_GREEN, None, tried, "no_green_candidate", exhausted=tried >= budget)
    attempts, fact = hit
    return _decision(system, case_id, ACCEPTED, fact, attempts, "ci_green")


def p_composed(
    system: str,
    case_id: str,
    ordered: Sequence[CandidateFacts],
    budget: int,
    *,
    policy: bool = True,
    verification: bool = True,
) -> SystemDecision:
    """P's acceptance rules replayed over candidate facts; the first green candidate is terminal."""
    hit = _first_green(ordered, budget)
    if hit is None:
        tried = min(budget, len(ordered))
        return _decision(system, case_id, NO_GREEN, None, tried, "no_green_candidate", exhausted=tried >= budget)
    attempts, fact = hit
    if policy:
        if fact.policy_outcome == "REJECT":
            return _decision(system, case_id, REJECTED, fact, attempts, "policy_rejected")
        if fact.policy_outcome != "APPROVE":
            return _decision(system, case_id, ESCALATED, fact, attempts, f"policy_{(fact.policy_outcome or 'missing').lower()}")
    if not verification:
        return _decision(system, case_id, ACCEPTED, fact, attempts, "policy_approved" if policy else "ci_green")
    if policy:
        if fact.locally_verified:
            return _decision(system, case_id, ACCEPTED, fact, attempts, "locally_verified")
        state = fact.remediation_state or "missing"
        if state == "HUMAN_REVIEW_REQUIRED":
            return _decision(system, case_id, ESCALATED, fact, attempts, "verification_human_review")
        return _decision(system, case_id, REJECTED, fact, attempts, f"verification_{state.lower()}")
    if fact.verified_without_policy:
        return _decision(system, case_id, ACCEPTED, fact, attempts, "locally_verified_without_policy")
    return _decision(system, case_id, REJECTED, fact, attempts, "verification_failed")


def p_real(
    case: Mapping[str, Any],
    ordered: Sequence[CandidateFacts],
    candidates: Mapping[str, Mapping[str, Any]],
    repo: Path,
    workdir: Path,
    budget: int,
    *,
    timeout: int,
    system: str = "P",
) -> SystemDecision:
    """Run the real product loop over the ordered candidates and map its outcome to a decision."""
    case_id = case["case_id"]
    usable = [f for f in ordered if f.error is None][:budget]
    if not usable:
        return _decision(system, case_id, ERROR, None, 0, "no_usable_candidates")
    patches = [candidate_patch(repo, candidates[f.candidate_id]["edits"]) for f in usable]
    outcome, verification = run_product(case, repo, patches, workdir / "artifacts-p", timeout=timeout)
    if outcome.get("outcome") in {"ERROR", "NO_FAILURE"}:
        return _decision(system, case_id, ERROR, None, 0, f"product_{outcome['outcome'].lower()}")
    attempts = int(outcome.get("attempts") or 0)
    detail = {"stop_reason": outcome.get("stop_reason"), "workflow_status": outcome.get("workflow_status"),
              "remediation_state": outcome.get("remediation_state"), "policy_rules": outcome.get("policy_rules")}
    if outcome.get("technical_status") != "PASS":
        reason = f"no_green_candidate:{outcome.get('stop_reason')}"
        return _decision(system, case_id, NO_GREEN, None, attempts, reason, exhausted=attempts >= budget, detail=detail)
    patch_path = outcome.get("patch_path")
    digest = sha256(Path(patch_path).read_bytes()).hexdigest() if patch_path else None
    fact = next((f for f in usable if f.patch_sha256 == digest), None)
    if fact is None:
        return _decision(system, case_id, ERROR, None, attempts, "accepted_patch_not_attributable", detail=detail)
    if outcome.get("policy_outcome") == "REJECT":
        return _decision(system, case_id, REJECTED, fact, attempts, "policy_rejected", detail=detail)
    state = outcome.get("remediation_state")
    if state == "POLICY_APPROVED" and locally_verified(verification):
        return _decision(system, case_id, ACCEPTED, fact, attempts, "locally_verified", detail=detail)
    if outcome.get("workflow_status") == "AWAITING_HUMAN" or state == "HUMAN_REVIEW_REQUIRED":
        return _decision(system, case_id, ESCALATED, fact, attempts, "human_review", detail=detail)
    return _decision(system, case_id, REJECTED, fact, attempts, f"verification_{(state or 'missing').lower()}", detail=detail)


@dataclass
class CaseRun:
    """All repair-track output for one case."""

    case_id: str
    order: list[str]
    facts: list[CandidateFacts]
    decisions: list[SystemDecision]
    fidelity: dict[str, Any]
    base_checks: dict[str, Any]
    latency_ms: int


SYSTEMS_DOC = {
    "R-GREEN-1": "accept the first candidate that turns visible CI green; one attempt",
    "R-GREEN-k": "accept the first candidate that turns visible CI green; k attempts",
    "P": "real run_fix_repo loop (retry engine, policy gate, verification layer); k attempts",
    "P-composed": "P's rules replayed over candidate facts (fidelity check only)",
    "P-no-policy": "ablation: P-composed without the policy gate",
    "P-no-verification": "ablation: P-composed without the verification layer",
    "P-no-retry": "ablation: P-composed with a single attempt",
}


def base_checks(case: Mapping[str, Any], repo: Path, workdir: Path, *, timeout: int) -> dict[str, Any]:
    """Fixture sanity at the base commit: visible CI must fail and the hidden oracle must fail."""
    display = render_command(case["repair_fixture"]["ci_command"])
    run = subprocess.run(
        split_command(display), cwd=repo, env=_subprocess_env(), capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    oracle = run_oracle(case["repair_fixture"], [], workdir / "oracle-base", timeout=timeout)
    issues = []
    if run.returncode == 0:
        issues.append("visible_ci_passes_at_base")
    if oracle.passed is not False:
        issues.append("oracle_does_not_fail_at_base")
    return {"visible_ci_returncode": run.returncode, "oracle_passed_at_base": oracle.passed, "issues": issues}


def run_case(
    case: Mapping[str, Any], *, seed: int, budget: int, timeout: int, scratch: Path | None = None,
    systems: Sequence[str] = tuple(SYSTEMS_DOC),
) -> CaseRun:
    """Evaluate every candidate of a case and every requested system."""
    started = time.perf_counter()
    root = Path(tempfile.mkdtemp(prefix="rq1-", dir=scratch))
    try:
        repo = root / "repo"
        base_commit = materialize(case["repair_fixture"], repo)
        checks = base_checks(case, repo, root, timeout=timeout)
        candidates = {c["candidate_id"]: c for c in case["repair_fixture"]["candidates"]}
        order = candidate_order(case, seed)
        facts_by_id = {
            cid: evaluate_candidate(case, candidates[cid], repo, base_commit, root / f"cand-{idx}", timeout=timeout)
            for idx, cid in enumerate(order)
        }
        ordered = [facts_by_id[cid] for cid in order]
        cid = case["case_id"]
        decisions: list[SystemDecision] = []
        composed = p_composed("P-composed", cid, ordered, budget)
        for system in systems:
            if system == "R-GREEN-1":
                decisions.append(r_green(system, cid, ordered, 1))
            elif system == "R-GREEN-k":
                decisions.append(r_green(system, cid, ordered, budget))
            elif system == "P":
                decisions.append(p_real(case, ordered, candidates, repo, root, budget, timeout=timeout))
            elif system == "P-composed":
                decisions.append(composed)
            elif system == "P-no-policy":
                decisions.append(p_composed(system, cid, ordered, budget, policy=False))
            elif system == "P-no-verification":
                decisions.append(p_composed(system, cid, ordered, budget, verification=False))
            elif system == "P-no-retry":
                decisions.append(p_composed(system, cid, ordered, 1))
            else:
                raise ValueError(f"unknown repair system {system!r}")
        real = next((d for d in decisions if d.system == "P"), None)
        fidelity: dict[str, Any] = {"checked": real is not None}
        if real is not None:
            fidelity.update(
                agree=(real.decision, real.candidate_id) == (composed.decision, composed.candidate_id),
                real=[real.decision, real.candidate_id, real.reason],
                composed=[composed.decision, composed.candidate_id, composed.reason],
            )
        return CaseRun(cid, order, ordered, decisions, fidelity, checks, int((time.perf_counter() - started) * 1000))
    finally:
        shutil.rmtree(root, ignore_errors=True)
