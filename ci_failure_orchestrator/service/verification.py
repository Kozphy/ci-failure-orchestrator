"""Repair verification: evidence beyond "the verify commands passed".

After the policy gate, the candidate patch is checked again in two disposable worktrees,
one at the base commit and one with the patch applied. Nothing touches the target checkout.

- The exact originally failing pytest node IDs must fail before and pass after. If they can
  no longer be found after the patch, the test was deleted or renamed.
- Tests mapped to the changed files, the regression suite, lint, type checking, security,
  build and declared behavioral invariants are compared before vs after, so a check that was
  already failing is told apart from one the patch broke.
- Test counts, skips and coverage are compared to catch disabled verification.

The decision itself is ``foundation.remediation.decide_remediation``; this module only
collects evidence. Commands come from the operator's verification config, never from the
patch, so a repair cannot edit the checks that judge it.
"""

from __future__ import annotations

import platform
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ..foundation.diff_risk import max_level, score_diff_risk
from ..foundation.models import utc_now
from ..foundation.persistence import AuditEventType, FileEvidenceStore, append_operator_event
from ..foundation.remediation import (
    QUALITY_GATES,
    GateStatus,
    RemediationDecision,
    VerificationResult,
    decide_remediation,
)
from ..foundation.test_evidence import (
    PYTEST_NO_TESTS_COLLECTED,
    PYTEST_TESTS_FAILED,
    PYTEST_USAGE_ERROR,
    FailureFingerprint,
    TestRunSummary,
    combine_summaries,
    fingerprint_failure,
    parse_test_output,
    same_failure,
)
from ..foundation.verification_integrity import IntegritySeverity, analyze_patch, is_test_path, parse_unified_diff
from ..patch_sandbox import VerificationStep, WorktreePatchVerifier
from .common import FIX_DIR, REMEDIATION_NAME, git, split_command
from .session import VerifyCommand
from .untrusted import clean_untrusted

WAIVABLE_GATES = frozenset({"coverage", *QUALITY_GATES, "behavioral_invariants"})
_CONFIG_KEYS = frozenset(
    {"regression", *QUALITY_GATES, "invariants", "waive", "affected_tests", "coverage_tolerance", "test_command"}
)
# Remediation states that fix-repo-apply refuses even when the workflow is APPROVED.
BLOCKING_REMEDIATION_STATES = frozenset({"POLICY_REJECTED", "REGRESSION_DETECTED", "NOT_FIXED"})
MAX_TARGET_TESTS = 20
STEP_TAIL_CHARS = 1500
VERIFICATION_SCHEMA = "repair-verification/v1"


@dataclass(frozen=True)
class Invariant:
    """Named behavioral invariant command declared in the verification config."""

    name: str
    command: str


@dataclass(frozen=True)
class VerificationConfig:
    """Validated operator verification config: gate commands, invariants, waivers and test mapping."""

    regression: tuple[str, ...] = ()
    lint: tuple[str, ...] = ()
    typecheck: tuple[str, ...] = ()
    security: tuple[str, ...] = ()
    build: tuple[str, ...] = ()
    invariants: tuple[Invariant, ...] = ()
    waivers: Mapping[str, str] = field(default_factory=dict)
    affected_tests: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # Percentage points of total coverage that may be lost before it counts as a regression.
    coverage_tolerance: float = 0.5
    test_command: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the config in the mapping shape accepted by ``load_verification_config``."""
        return {
            "regression": list(self.regression),
            **{gate: list(getattr(self, gate)) for gate in QUALITY_GATES},
            "invariants": [{"name": i.name, "command": i.command} for i in self.invariants],
            "waive": dict(self.waivers),
            "affected_tests": {k: list(v) for k, v in self.affected_tests.items()},
            "coverage_tolerance": self.coverage_tolerance,
            "test_command": self.test_command,
        }


class VerificationConfigError(ValueError):
    """Invalid verification config; one error type for type and value problems."""


def _commands(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise VerificationConfigError(f"verification config '{key}' must be a command or a list of commands")
    return tuple(v.strip() for v in value)


def load_verification_config(
    data: Mapping[str, Any] | None = None, *, regression: Sequence[str] = ()
) -> VerificationConfig:
    """Validate a verification config mapping. Unknown keys are errors so typos cannot disable checks."""

    data = dict(data or {})
    unknown = sorted(set(data) - _CONFIG_KEYS)
    if unknown:
        raise VerificationConfigError(f"unknown verification config keys: {unknown}")

    invariants: list[Invariant] = []
    raw_invariants = data.get("invariants") or []
    if not isinstance(raw_invariants, list):
        raise VerificationConfigError("verification config 'invariants' must be a list")
    for idx, item in enumerate(raw_invariants, start=1):
        name = str(item.get("name") or "").strip() if isinstance(item, Mapping) else ""
        command = str(item.get("command") or "").strip() if isinstance(item, Mapping) else ""
        if not name or not command:
            raise VerificationConfigError(f"invariant #{idx} needs a name and a command")
        if any(i.name == name for i in invariants):
            raise VerificationConfigError(f"duplicate invariant name: {name}")
        invariants.append(Invariant(name, command))

    waive = data.get("waive") or {}
    if not isinstance(waive, Mapping):
        raise VerificationConfigError("verification config 'waive' must map a gate to a reason")
    waivers: dict[str, str] = {}
    for gate, reason in waive.items():
        if gate not in WAIVABLE_GATES:
            raise VerificationConfigError(f"cannot waive '{gate}'; waivable gates: {sorted(WAIVABLE_GATES)}")
        if not isinstance(reason, str) or not reason.strip():
            raise VerificationConfigError(f"waiver for '{gate}' needs a reason")
        waivers[gate] = reason.strip()

    affected = data.get("affected_tests") or {}
    if not isinstance(affected, Mapping):
        raise VerificationConfigError("verification config 'affected_tests' must map a source path to test paths")
    affected_map = {str(src): _commands(tests, f"affected_tests.{src}") for src, tests in affected.items()}

    raw_tolerance = data.get("coverage_tolerance", 0.5)
    if isinstance(raw_tolerance, bool) or not isinstance(raw_tolerance, (int, float)) or raw_tolerance < 0:
        raise VerificationConfigError("coverage_tolerance must be a number >= 0")
    tolerance = float(raw_tolerance)
    test_command = data.get("test_command")
    if test_command is not None and (not isinstance(test_command, str) or not test_command.strip()):
        raise VerificationConfigError("test_command must be a command string")

    return VerificationConfig(
        regression=_commands(data.get("regression"), "regression") + tuple(c.strip() for c in regression if c.strip()),
        lint=_commands(data.get("lint"), "lint"),
        typecheck=_commands(data.get("typecheck"), "typecheck"),
        security=_commands(data.get("security"), "security"),
        build=_commands(data.get("build"), "build"),
        invariants=tuple(invariants),
        waivers=waivers,
        affected_tests=affected_map,
        coverage_tolerance=tolerance,
        test_command=test_command.strip() if test_command else None,
    )


def read_verification_config_file(path: Path) -> dict[str, Any]:
    """Read a YAML verification config file; an empty file yields an empty mapping.

    Raises:
        VerificationConfigError: When the file does not contain a YAML mapping.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise VerificationConfigError(f"{path} must contain a YAML mapping")
    return data


@dataclass(frozen=True)
class VerificationReport:
    """Verification result, the remediation decision derived from it, and the supporting evidence."""

    result: VerificationResult
    decision: RemediationDecision
    evidence: dict[str, Any]


def pytest_prefix(argv: Sequence[str]) -> tuple[str, ...] | None:
    """The argv up to and including pytest, e.g. ``python -m pytest``; None for other runners."""
    for idx, token in enumerate(argv):
        name = PurePosixPath(token.replace("\\", "/")).name.lower().removesuffix(".exe")
        if name in ("pytest", "py.test"):
            return tuple(argv[: idx + 1])
        if token == "-m" and idx + 1 < len(argv) and argv[idx + 1] == "pytest":
            return tuple(argv[: idx + 2])
    return None


def affected_test_candidates(changed: Sequence[str], explicit: Mapping[str, Sequence[str]]) -> list[str]:
    """Return deduplicated candidate test paths for the changed files.

    Includes explicitly mapped tests, changed test files themselves, and conventional
    ``test_<stem>.py`` / ``<stem>_test.py`` locations for changed Python sources. Candidates
    are not checked for existence.
    """
    out: list[str] = []
    for path in changed:
        posix = PurePosixPath(path.replace("\\", "/"))
        out.extend(explicit.get(path, ()))
        if posix.suffix != ".py":
            continue
        if is_test_path(path):
            out.append(str(posix))
            continue
        stem, parent = posix.stem, posix.parent
        rel_parent = PurePosixPath(*parent.parts[1:]) if parent.parts[:1] in (("src",), ("lib",)) else parent
        out += [
            f"tests/test_{stem}.py",
            str(PurePosixPath("tests", *rel_parent.parts, f"test_{stem}.py")),
            str(parent / f"test_{stem}.py"),
            str(parent / "tests" / f"test_{stem}.py"),
            str(parent / f"{stem}_test.py"),
        ]
    return list(dict.fromkeys(c.removeprefix("./") for c in out))


def _tail(step: VerificationStep | None) -> str:
    if step is None:
        return ""
    return clean_untrusted(f"{step.stdout}\n{step.stderr}".strip())[-STEP_TAIL_CHARS:]


def _step_record(step: VerificationStep | None, display: str) -> dict[str, Any]:
    if step is None:
        return {"command": display, "ran": False}
    return {
        "command": display,
        "ran": True,
        "returncode": step.returncode,
        "latency_ms": round(step.latency_ms, 1),
        "output_tail": _tail(step),
    }


def _reproduction(
    baseline: Sequence[VerificationStep], commands: Sequence[VerifyCommand], ci_failure_log: str | None
) -> tuple[bool | None, FailureFingerprint, VerificationStep | None, dict[str, Any]]:
    failing = next((s for s in baseline if not s.passed), None)
    display = next((c.display for c in commands if failing and c.name == failing.name), "")
    local = fingerprint_failure(
        f"{failing.stdout}\n{failing.stderr}" if failing else "",
        exit_code=failing.returncode if failing else None,
        job=display,
    )
    ci = fingerprint_failure(ci_failure_log) if ci_failure_log else None
    if failing is None:
        reproduced: bool | None = False
        basis = "verification commands passed at the base commit"
    elif ci is None:
        reproduced = True
        basis = "local reproduction is the reported failure (no CI log supplied)"
    else:
        reproduced = same_failure(ci, local)
        basis = {
            True: "local reproduction matches the CI failure",
            False: "local reproduction fails differently from the CI failure",
            None: "CI failure could not be compared with the local reproduction",
        }[reproduced]
    evidence = {
        "original_failure_reproduced": reproduced,
        "basis": basis,
        "failed_command": display,
        "failed_test": local.test,
        "failure_signature": local.fingerprint,
        "local_fingerprint": local.to_dict(),
        "ci_fingerprint": ci.to_dict() if ci else None,
        "environment": {
            "python": platform.python_version(),
            "os": platform.system(),
            "note": "interpreter running the orchestrator; verify commands may use another",
        },
    }
    return reproduced, local, failing, evidence


def _risk(patch: str, policy_risk: str | None) -> tuple[str, tuple[str, ...], dict[str, Any]]:
    diff = score_diff_risk(patch)
    policy_level = {"CRITICAL": "HIGH"}.get(policy_risk or "", policy_risk)
    level = max_level(diff.risk_level, policy_level) if policy_level else diff.risk_level
    reasons = diff.reasons + ((f"policy risk {policy_risk}",) if policy_level == "HIGH" else ())
    return level, reasons, {**diff.to_dict(), "policy_risk_level": policy_risk, "combined_risk_level": level}


def _integrity(patch: str) -> tuple[tuple[str, ...], list[str]]:
    findings = analyze_patch(patch)
    codes = tuple(sorted({f.code.value for f in findings if f.severity is IntegritySeverity.REJECT}))
    return codes, [f.describe() for f in findings]


def static_verification(
    *,
    patch: str,
    baseline: Sequence[VerificationStep],
    commands: Sequence[VerifyCommand],
    ci_failure_log: str | None,
    policy_outcome: str | None,
    policy_risk: str | None,
    repair_proposed: bool,
    technical_passed: bool,
    human_approved: bool = False,
) -> VerificationReport:
    """Evidence without running anything, for runs that cannot become verified (rejected or not fixed)."""

    reproduced, _local, _failing, repro = _reproduction(baseline, commands, ci_failure_log)
    codes, findings = _integrity(patch) if patch else ((), [])
    level, reasons, risk = _risk(patch, policy_risk) if patch else ("HIGH", (), {})
    result = VerificationResult(
        repair_proposed=repair_proposed,
        patch_applied=technical_passed,
        original_failure_reproduced=reproduced,
        targeted_test_passed=technical_passed if repair_proposed else None,
        forbidden_diff_detected=bool(codes),
        forbidden_diff_codes=codes,
        policy_outcome=policy_outcome,
        human_approved=human_approved,
        risk_level=level,
        risk_reasons=reasons,
    )
    evidence = {
        "reproduction": repro,
        "targeted_validation": {"verify_commands_passed": technical_passed, "exact_test_rerun": "NOT_RUN"},
        "integrity_findings": findings,
        "diff_risk": risk,
        "skipped": "deeper verification not run: the repair is already rejected or did not pass",
    }
    return VerificationReport(result, decide_remediation(result), evidence)


def _command_gate(names: Sequence[str], before: Mapping[str, VerificationStep], after: Mapping[str, VerificationStep]) -> GateStatus:
    if not names:
        return GateStatus.NOT_RUN
    if any(name not in after for name in names):
        return GateStatus.NOT_RUN
    if all(after[name].passed for name in names):
        return GateStatus.PASSED
    if any(not after[name].passed and name in before and before[name].passed for name in names):
        return GateStatus.FAILED
    return GateStatus.FAILED_PREEXISTING


def _test_gate(
    names: Sequence[str],
    before: Mapping[str, VerificationStep],
    after: Mapping[str, VerificationStep],
    before_sum: TestRunSummary,
    after_sum: TestRunSummary,
    ignore: frozenset[str],
) -> tuple[GateStatus, tuple[str, ...]]:
    status = _command_gate(names, before, after)
    new = tuple(sorted(after_sum.failed_ids - before_sum.failed_ids - ignore))
    if status is GateStatus.FAILED_PREEXISTING and new:
        return GateStatus.FAILED, new
    return status, new if status is GateStatus.FAILED else ()


def _summary(names: Sequence[str], steps: Mapping[str, VerificationStep]) -> TestRunSummary:
    return combine_summaries(parse_test_output(f"{steps[n].stdout}\n{steps[n].stderr}") for n in names if n in steps)


def _run_worktree(
    commands: Sequence[tuple[str, tuple[str, ...]]],
    *,
    repo: Path,
    base_commit: str,
    patch: str | None,
    timeout: int,
    env_allowlist: Sequence[str],
) -> dict[str, VerificationStep] | None:
    if not commands:
        return {}
    verifier = WorktreePatchVerifier(
        commands=commands, timeout_seconds=timeout, env_allowlist=env_allowlist, stop_on_failure=False
    )
    if patch is None:
        steps = verifier.reproduce(repo_path=repo, base_ref=base_commit)
        return None if steps is None else {s.name: s for s in steps}
    verification = verifier.verify(repo_path=repo, patch_text=patch, base_ref=base_commit)
    return {s.name: s for s in verification.steps} if verification.applied else None


def collect_verification(
    *,
    repo: Path,
    base_commit: str,
    patch: str,
    commands: Sequence[VerifyCommand],
    baseline: Sequence[VerificationStep],
    config: VerificationConfig,
    timeout: int,
    env_allowlist: Sequence[str],
    ci_failure_log: str | None,
    policy_outcome: str | None,
    policy_risk: str | None,
    human_approved: bool = False,
) -> VerificationReport:
    """Run before/after verification for a patch whose verify commands already passed."""

    reproduced, local, failing, repro = _reproduction(baseline, commands, ci_failure_log)
    codes, findings = _integrity(patch)
    level, risk_reasons, risk = _risk(patch, policy_risk)

    tracked = {line for line in git(repo, "ls-tree", "-r", "--name-only", base_commit).stdout.splitlines() if line}
    diffs = [d for d in parse_unified_diff(patch) if d.path]
    removed = {d.path for d in diffs if d.deleted} | {d.renamed_from for d in diffs if d.renamed_from}
    patched_files = (tracked | {d.path for d in diffs if not d.deleted}) - removed

    failing_cmd = next((c for c in commands if failing and c.name == failing.name), None)
    prefix = pytest_prefix(failing_cmd.argv) if failing_cmd else None
    if prefix is None and config.test_command:
        prefix = pytest_prefix(split_command(config.test_command))
    pytest_tail = ("-p", "no:cacheprovider")
    target_ids = [t for t in local.failed_tests if t.split("::", 1)[0] in tracked][:MAX_TARGET_TESTS]
    candidates = affected_test_candidates([d.path for d in diffs], config.affected_tests)
    affected_before = [c for c in candidates if c in tracked]
    affected_after = [c for c in candidates if c in patched_files]

    displays: dict[str, str] = {}
    gate_names: dict[str, list[str]] = {gate: [] for gate in (*QUALITY_GATES, "regression")}
    invariant_names: dict[str, str] = {}
    shared: list[tuple[str, tuple[str, ...]]] = []
    for gate in ("regression", *QUALITY_GATES):
        for idx, cmd in enumerate(getattr(config, gate), start=1):
            name = f"{gate}-{idx}"
            shared.append((name, split_command(cmd)))
            gate_names[gate].append(name)
            displays[name] = cmd
    for idx, inv in enumerate(config.invariants, start=1):
        name = f"invariant-{idx}"
        shared.append((name, split_command(inv.command)))
        invariant_names[name] = inv.name
        displays[name] = inv.command

    before_cmds = list(shared)
    after_cmds = list(shared)
    if prefix and target_ids:
        target_argv = (*prefix, *target_ids, *pytest_tail)
        before_cmds.insert(0, ("target", target_argv))
        after_cmds.insert(0, ("target", target_argv))
        displays["target"] = " ".join(target_argv)
    if prefix and affected_before:
        before_cmds.append(("affected", (*prefix, *affected_before, *pytest_tail)))
    if prefix and affected_after:
        after_cmds.append(("affected", (*prefix, *affected_after, *pytest_tail)))
        displays["affected"] = " ".join((*prefix, *affected_after, *pytest_tail))

    run_args = {"repo": repo, "base_commit": base_commit, "timeout": timeout, "env_allowlist": env_allowlist}
    before = _run_worktree(before_cmds, patch=None, **run_args)
    after = _run_worktree(after_cmds, patch=patch, **run_args)
    worktrees_ok = before is not None and after is not None
    before, after = before or {}, after or {}

    # Exact rerun of the originally failing tests.
    exact = "NOT_AVAILABLE"
    target_missing = False
    if "target" in before and "target" in after:
        b, a = before["target"], after["target"]
        a_sum = parse_test_output(f"{a.stdout}\n{a.stderr}")
        if b.returncode != PYTEST_TESTS_FAILED:
            exact = "NOT_REPRODUCIBLE_IN_ISOLATION"
        elif a.returncode in (PYTEST_USAGE_ERROR, PYTEST_NO_TESTS_COLLECTED) or (a_sum.parsed and a_sum.total == 0):
            exact = "TARGET_MISSING"
            target_missing = True
        elif a.passed and a_sum.passed >= 1:
            exact = "PASSED"
        else:
            exact = "FAILED"
    target_after_fp = (
        fingerprint_failure(f"{after['target'].stdout}\n{after['target'].stderr}", exit_code=after["target"].returncode)
        if exact == "FAILED"
        else None
    )
    targeted_passed = exact != "FAILED"
    resolved = exact not in ("FAILED", "TARGET_MISSING")
    ignore = frozenset(target_ids)

    reg_names = gate_names["regression"]
    reg_before, reg_after = _summary(reg_names, before), _summary(reg_names, after)
    regression, reg_new = _test_gate(reg_names, before, after, reg_before, reg_after, ignore)
    if not worktrees_ok:
        regression = GateStatus.NOT_RUN

    aff_before, aff_after = _summary(["affected"], before), _summary(["affected"], after)
    if "affected" in after and "affected" in before:
        affected, aff_new = _test_gate(["affected"], before, after, aff_before, aff_after, ignore)
    elif "affected" in after:
        affected = GateStatus.PASSED if after["affected"].passed else GateStatus.FAILED
        aff_new = tuple(sorted(aff_after.failed_ids - ignore)) if affected is GateStatus.FAILED else ()
    else:
        affected, aff_new = regression, ()
    new_failures = tuple(sorted(set(reg_new) | set(aff_new)))

    counts_known = bool(reg_names) and worktrees_ok and reg_before.parsed and reg_after.parsed
    test_count_decreased = reg_after.total < reg_before.total if counts_known else None
    skipped_increased = (
        (reg_after.skipped + reg_after.xfailed + reg_after.deselected)
        > (reg_before.skipped + reg_before.xfailed + reg_before.deselected)
        if counts_known
        else None
    )

    def waivable(gate: str, status: GateStatus) -> GateStatus:
        return GateStatus.WAIVED if status is GateStatus.NOT_RUN and gate in config.waivers else status

    if reg_before.coverage_percent is not None and reg_after.coverage_percent is not None and worktrees_ok:
        coverage = (
            GateStatus.FAILED
            if reg_after.coverage_percent < reg_before.coverage_percent - config.coverage_tolerance
            else GateStatus.PASSED
        )
    else:
        coverage = GateStatus.NOT_RUN
    coverage = waivable("coverage", coverage)

    quality = {
        gate: waivable(gate, _command_gate(gate_names[gate], before, after) if worktrees_ok else GateStatus.NOT_RUN)
        for gate in QUALITY_GATES
    }
    invariant_status = {
        name: _command_gate([name], before, after) if worktrees_ok else GateStatus.NOT_RUN for name in invariant_names
    }
    if not invariant_status:
        invariants = GateStatus.NOT_RUN
    elif any(s is GateStatus.FAILED for s in invariant_status.values()):
        invariants = GateStatus.FAILED
    elif all(s is GateStatus.PASSED for s in invariant_status.values()):
        invariants = GateStatus.PASSED
    elif any(s is GateStatus.FAILED_PREEXISTING for s in invariant_status.values()):
        invariants = GateStatus.FAILED_PREEXISTING
    else:
        invariants = GateStatus.NOT_RUN
    invariants = waivable("behavioral_invariants", invariants)

    result = VerificationResult(
        repair_proposed=True,
        patch_applied=True,
        original_failure_reproduced=reproduced,
        original_failure_resolved=resolved,
        targeted_test_passed=targeted_passed,
        target_test_missing=target_missing,
        affected_tests=affected,
        regression_suite=regression,
        new_test_failures=new_failures,
        test_count_decreased=test_count_decreased,
        skipped_tests_increased=skipped_increased,
        coverage=coverage,
        lint=quality["lint"],
        typecheck=quality["typecheck"],
        security=quality["security"],
        build=quality["build"],
        behavioral_invariants=invariants,
        forbidden_diff_detected=bool(codes),
        forbidden_diff_codes=codes,
        policy_outcome=policy_outcome,
        human_approved=human_approved,
        risk_level=level,
        risk_reasons=risk_reasons,
    )

    def enabled(gate: str) -> bool:
        return bool(getattr(config, gate))

    gate_disabled = any("QUALITY_GATE_DISABLED" in f or "CI_CHECK_REMOVED" in f for f in findings)
    evidence = {
        "reproduction": repro,
        "targeted_validation": {
            "original_failure_disappeared": resolved,
            "target_test_passed": targeted_passed,
            "exact_test_rerun": exact,
            "target_tests": target_ids,
            "after_fingerprint": target_after_fp.to_dict() if target_after_fp else None,
            "before": _step_record(before.get("target"), displays.get("target", "")),
            "after": _step_record(after.get("target"), displays.get("target", "")),
        },
        "affected_tests": {
            "status": affected.value,
            "selected": affected_after,
            "source": "changed files" if "affected" in after else "no mapped tests; mirrors the regression suite",
            "affected_tests_total": aff_after.total,
            "affected_tests_passed": aff_after.passed,
            "affected_tests_failed": aff_after.failed + aff_after.errors,
            "after": _step_record(after.get("affected"), displays.get("affected", "")),
        },
        "regression": {
            "status": regression.value,
            "configured": bool(reg_names),
            "tests_before": reg_before.to_dict(),
            "tests_after": reg_after.to_dict(),
            "new_failures": list(new_failures),
            "removed_tests": max(0, reg_before.total - reg_after.total) if counts_known else None,
            "coverage_before": reg_before.coverage_percent,
            "coverage_after": reg_after.coverage_percent,
            "steps_after": [_step_record(after.get(n), displays[n]) for n in reg_names],
        },
        "quality_baseline": {
            "before": {
                "test_count": reg_before.total if counts_known else None,
                "coverage": reg_before.coverage_percent,
                **{f"{g}_enabled": enabled(g) for g in ("lint", "typecheck", "security")},
            },
            "after": {
                "test_count": reg_after.total if counts_known else None,
                "coverage": reg_after.coverage_percent,
                **{f"{g}_enabled": enabled(g) and not gate_disabled for g in ("lint", "typecheck", "security")},
            },
            "gates": {g: quality[g].value for g in QUALITY_GATES} | {"coverage": coverage.value},
            "waivers": dict(config.waivers),
            "steps_after": {
                g: [_step_record(after.get(n), displays[n]) for n in gate_names[g]] for g in QUALITY_GATES
            },
        },
        "behavioral_invariants": [
            {
                "name": invariant_names[n],
                "command": displays[n],
                "status": invariant_status[n].value,
                "before_returncode": before[n].returncode if n in before else None,
                "after_returncode": after[n].returncode if n in after else None,
            }
            for n in invariant_names
        ],
        "integrity_findings": findings,
        "diff_risk": risk,
        "worktrees_ok": worktrees_ok,
    }
    return VerificationReport(result, decide_remediation(result), evidence)


def audit_checks(result: VerificationResult) -> dict[str, Any]:
    """Summarize a verification result as per-check statuses for the audit trail.

    Returns:
        A dict with ``original_failure_reproduced``, ``targeted_validation``,
        ``regression_validation``, ``quality_gate_preserved``, ``security_validation`` and
        ``real_ci_validation`` entries.
    """
    if result.targeted_test_passed is False or result.original_failure_resolved is False or result.target_test_missing:
        targeted = "FAILED"
    elif result.targeted_test_passed and result.original_failure_resolved:
        targeted = "PASSED"
    else:
        targeted = "NOT_RUN"
    regression = "FAILED" if result.new_test_failures else result.regression_suite.value
    weakened = (
        result.forbidden_diff_detected
        or result.test_count_decreased
        or result.skipped_tests_increased
        or any(getattr(result, g) is GateStatus.FAILED for g in ("coverage", *QUALITY_GATES))
    )
    complete = all(getattr(result, g).satisfied for g in ("coverage", *QUALITY_GATES))
    return {
        "original_failure_reproduced": result.original_failure_reproduced,
        "targeted_validation": targeted,
        "regression_validation": regression,
        "quality_gate_preserved": "FAILED" if weakened else "PASSED" if complete else "INCOMPLETE",
        "security_validation": result.security.value,
        "real_ci_validation": {True: "PASSED", False: "FAILED", None: "PENDING"}[result.real_ci_passed],
    }


def record_verification(
    artifacts_root: Path,
    run_id: str,
    report: VerificationReport,
    *,
    stage: str,
    record_name: str,
    repair_attempt: int,
    failure_received_at: str,
    ci_green: bool,
    ci_green_source: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Store the evidence, refresh the current remediation summary, and append the audit event."""

    store = FileEvidenceStore(artifacts_root)
    decided_at = utc_now()
    detail_ref = store.write_json(
        run_id,
        FIX_DIR,
        {
            "schema": VERIFICATION_SCHEMA,
            "run_id": run_id,
            "stage": stage,
            "result": report.result.to_dict(),
            "decision": report.decision.to_dict(),
            "evidence": report.evidence,
            **dict(extra or {}),
            "created_at": decided_at,
        },
        name=record_name,
    )
    summary = {
        "schema": VERIFICATION_SCHEMA,
        "run_id": run_id,
        "stage": stage,
        "state": report.decision.state.value,
        "verified": report.decision.verified,
        "reasons": list(report.decision.reasons),
        "missing_evidence": list(report.decision.missing_evidence),
        "merge_requirement": report.decision.merge_requirement.value,
        "risk_level": report.result.risk_level,
        "repair_attempted": report.result.repair_proposed,
        "repair_attempt": repair_attempt,
        "ci_green": ci_green,
        "ci_green_source": ci_green_source,
        "checks": audit_checks(report.result),
        "failure_received_at": failure_received_at,
        "decided_at": decided_at,
        "evidence_ref": detail_ref.ref,
    }
    summary_ref = store.write_json(run_id, FIX_DIR, summary, name=REMEDIATION_NAME)
    append_operator_event(
        artifacts_root,
        run_id,
        AuditEventType.REPAIR_VERIFICATION_COMPLETED,
        actor="orchestrator",
        component="repair_verification",
        evidence_refs=(detail_ref, summary_ref),
        metadata={
            "run_id": run_id,
            "repair_attempt": repair_attempt,
            "stage": stage,
            "result": report.decision.state.value,
            "checks": audit_checks(report.result),
        },
    )
    return summary
