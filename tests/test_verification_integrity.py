"""Patches that make CI green by weakening verification must not be approved."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation.escalation import EscalationReasonCode, build_checklist, map_reason_codes
from ci_failure_orchestrator.foundation.models import (
    CheckStatus,
    EvaluationCheck,
    EvaluationResult,
    FailureClassification,
    RepairProposal,
    new_id,
)
from ci_failure_orchestrator.foundation.policy import (
    POLICY_VERSION,
    RULE_LOW_RISK_AUTO_APPROVE,
    RULE_VERIFICATION_CHANGE_REVIEW,
    RULE_VERIFICATION_WEAKENED,
    PolicyOutcome,
    StaticPolicyEngine,
    build_policy_context,
)
from ci_failure_orchestrator.foundation.verification_integrity import (
    IntegrityCode,
    IntegritySeverity,
    analyze_patch,
    is_test_path,
    parse_unified_diff,
)
from ci_failure_orchestrator.repo_fix import FixRepoConfig, run_fix_repo


def _diff(path: str, removed: list[str] = (), added: list[str] = (), context: list[str] = ()) -> str:
    old = len(context) + len(removed)
    new = len(context) + len(added)
    body = [f" {c}" for c in context] + [f"-{r}" for r in removed] + [f"+{a}" for a in added]
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{old} +1,{new} @@\n" + "\n".join(body) + "\n"
    )


def _deleted(path: str, lines: list[str]) -> str:
    body = "\n".join(f"-{line}" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\ndeleted file mode 100644\n--- a/{path}\n+++ /dev/null\n"
        f"@@ -1,{len(lines)} +0,0 @@\n{body}\n"
    )


def _codes(patch: str) -> set[IntegrityCode]:
    return {f.code for f in analyze_patch(patch)}


# --- diff parsing ---------------------------------------------------------------------------


def test_removed_line_starting_with_dashes_is_not_read_as_a_header() -> None:
    patch = _diff("tests/test_x.py", removed=["-- not a header", "    assert f() == 1"], context=["def test_x():"])
    (diff,) = parse_unified_diff(patch)
    assert diff.path == "tests/test_x.py"
    assert diff.removed == ["-- not a header", "    assert f() == 1"]


def test_deleted_file_and_plain_multi_file_diffs_are_parsed() -> None:
    deleted = parse_unified_diff(_deleted("tests/test_x.py", ["def test_x():", "    assert 1 == 1"]))
    assert [(d.path, d.deleted) for d in deleted] == [("tests/test_x.py", True)]

    plain = (
        "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
        "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-y = 1\n+y = 2\n"
    )
    assert [(d.path, d.added) for d in parse_unified_diff(plain)] == [("a.py", ["x = 2"]), ("b.py", ["y = 2"])]


@pytest.mark.parametrize(
    "path",
    ["tests/test_a.py", "pkg/a_test.go", "web/src/a.test.ts", "web/__tests__/a.js", "src/FooTest.java", "conftest.py"],
)
def test_test_paths_are_recognised_across_languages(path: str) -> None:
    assert is_test_path(path)


@pytest.mark.parametrize("path", ["src/calc.py", "src/testing_utils_impl.go.txt", "web/src/latest.ts"])
def test_non_test_paths_are_not_test_paths(path: str) -> None:
    assert not is_test_path(path)


# --- patches that weaken verification are rejected ------------------------------------------

REJECT_CASES = {
    "test file deleted": (
        _deleted("tests/test_calc.py", ["import calc", "def test_add():", "    assert calc.add(2, 3) == 5"]),
        IntegrityCode.TEST_FILE_DELETED,
    ),
    "failing test removed": (
        _diff(
            "tests/test_calc.py",
            removed=["def test_add():", "    assert calc.add(2, 3) == 5"],
            context=["import calc"],
        ),
        IntegrityCode.TEST_CASE_REMOVED,
    ),
    "go test removed": (
        _diff("calc/calc_test.go", removed=["func TestAdd(t *testing.T) {", '\tt.Fatal("x")', "}"]),
        IntegrityCode.TEST_CASE_REMOVED,
    ),
    "assertion removed": (
        _diff("tests/test_calc.py", removed=["    assert calc.add(2, 3) == 5"], added=["    calc.add(2, 3)"]),
        IntegrityCode.ASSERTION_REMOVED,
    ),
    "equality weakened to not-None": (
        _diff(
            "tests/test_calc.py",
            removed=["    assert result == expected"],
            added=["    assert result is not None"],
        ),
        IntegrityCode.ASSERTION_WEAKENED,
    ),
    "toEqual weakened to toBeDefined": (
        _diff("web/src/sum.test.ts", removed=["  expect(sum(2, 3)).toEqual(5);"], added=["  expect(sum(2, 3)).toBeDefined();"]),
        IntegrityCode.ASSERTION_WEAKENED,
    ),
    "assertion made tautological": (
        _diff("tests/test_calc.py", removed=["    assert result == 5"], added=["    assert result == result"]),
        IntegrityCode.ASSERTION_WEAKENED,
    ),
    "pytest skip marker": (
        _diff("tests/test_calc.py", added=["@pytest.mark.skip(reason='flaky')"], context=["def test_add():"]),
        IntegrityCode.TEST_SKIPPED,
    ),
    "pytest xfail marker": (
        _diff("tests/test_calc.py", added=["@pytest.mark.xfail"], context=["def test_add():"]),
        IntegrityCode.TEST_SKIPPED,
    ),
    "jest it.skip": (
        _diff("web/src/sum.test.ts", removed=["it('adds', () => {"], added=["it.skip('adds', () => {"]),
        IntegrityCode.TEST_SKIPPED,
    ),
    "go t.Skip": (
        _diff("calc/calc_test.go", added=['\tt.Skip("later")'], context=["func TestAdd(t *testing.T) {"]),
        IntegrityCode.TEST_SKIPPED,
    ),
    "junit @Disabled": (
        _diff("src/test/java/CalcTest.java", added=["    @Disabled"], context=["    @Test"]),
        IntegrityCode.TEST_SKIPPED,
    ),
    "jest describe.only": (
        _diff("web/src/sum.test.ts", removed=["describe('sum', () => {"], added=["describe.only('sum', () => {"]),
        IntegrityCode.TEST_FOCUSED,
    ),
    "pytest --deselect": (
        _diff("pytest.ini", removed=["addopts = -q"], added=["addopts = -q --deselect tests/test_calc.py::test_add"]),
        IntegrityCode.TEST_DESELECTED,
    ),
    "collect_ignore in conftest": (
        _diff("tests/conftest.py", added=['collect_ignore = ["test_calc.py"]']),
        IntegrityCode.TEST_DESELECTED,
    ),
    "exit status forced in conftest": (
        _diff(
            "tests/conftest.py",
            added=["def pytest_sessionfinish(session, exitstatus):", "    session.exitstatus = 0"],
        ),
        IntegrityCode.TEST_RESULT_OVERRIDDEN,
    ),
    "coverage fail_under lowered": (
        _diff("pyproject.toml", removed=["fail_under = 90"], added=["fail_under = 60"], context=["[tool.coverage.report]"]),
        IntegrityCode.COVERAGE_THRESHOLD_LOWERED,
    ),
    "--cov-fail-under removed from CI": (
        _diff(
            ".github/workflows/ci.yml",
            removed=["      - run: pytest --cov --cov-fail-under=85"],
            added=["      - run: pytest --cov"],
        ),
        IntegrityCode.COVERAGE_THRESHOLD_LOWERED,
    ),
    "jest coverage threshold lowered": (
        _diff("jest.config.js", removed=["      lines: 80,"], added=["      lines: 20,"]),
        IntegrityCode.COVERAGE_THRESHOLD_LOWERED,
    ),
    "CI test step removed": (
        _diff(".github/workflows/ci.yml", removed=["      - run: python -m pytest -q"], context=["    steps:"]),
        IntegrityCode.CI_CHECK_REMOVED,
    ),
    "CI type check removed": (
        _diff(".gitlab-ci.yml", removed=["    - mypy src"], context=["  script:"]),
        IntegrityCode.CI_CHECK_REMOVED,
    ),
    "CI workflow deleted": (
        _deleted(".github/workflows/ci.yml", ["on: push", "jobs: {}"]),
        IntegrityCode.CI_CONFIG_DELETED,
    ),
    "continue-on-error": (
        _diff(".github/workflows/ci.yml", added=["        continue-on-error: true"], context=["      - run: pytest"]),
        IntegrityCode.CI_FAILURE_IGNORED,
    ),
    "|| true on test command": (
        _diff(".github/workflows/ci.yml", removed=["      - run: pytest"], added=["      - run: pytest || true"]),
        IntegrityCode.CI_FAILURE_IGNORED,
    ),
    "gitlab allow_failure": (
        _diff(".gitlab-ci.yml", added=["  allow_failure: true"], context=["test:"]),
        IntegrityCode.CI_FAILURE_IGNORED,
    ),
    "Makefile ignores lint failure": (
        _diff("Makefile", removed=["\truff check ."], added=["\truff check . || true"]),
        IntegrityCode.CI_FAILURE_IGNORED,
    ),
    "mypy ignore_errors": (
        _diff("mypy.ini", added=["ignore_errors = True"], context=["[mypy]"]),
        IntegrityCode.QUALITY_GATE_DISABLED,
    ),
    "tsconfig strict off": (
        _diff("tsconfig.json", removed=['    "strict": true,'], added=['    "strict": false,']),
        IntegrityCode.QUALITY_GATE_DISABLED,
    ),
    "pre-commit hook removed": (
        _diff(".pre-commit-config.yaml", removed=["      - id: ruff"], context=["    hooks:"]),
        IntegrityCode.QUALITY_GATE_DISABLED,
    ),
    "CODEOWNERS edited": (
        _diff(".github/CODEOWNERS", removed=["* @security-team"]),
        IntegrityCode.REVIEW_CONTROL_MODIFIED,
    ),
    "bare except pass": (
        _diff("src/calc.py", added=["    try:", "        return a / b", "    except:", "        pass"]),
        IntegrityCode.EXCEPTION_SWALLOWED,
    ),
    "except Exception returns None": (
        _diff("src/calc.py", added=["    except Exception as exc:", "        return None"], context=["        x()"]),
        IntegrityCode.EXCEPTION_SWALLOWED,
    ),
    "inline except Exception pass": (
        _diff("src/calc.py", added=["    except Exception: pass"]),
        IntegrityCode.EXCEPTION_SWALLOWED,
    ),
    "empty JS catch": (
        _diff("web/src/sum.ts", added=["  try { run(); } catch (e) {}"]),
        IntegrityCode.EXCEPTION_SWALLOWED,
    ),
    "production code sniffs pytest": (
        _diff(
            "src/calc.py",
            added=['    if "PYTEST_CURRENT_TEST" in os.environ:', "        return 5"],
            context=["def add(a, b):"],
        ),
        IntegrityCode.TEST_ENVIRONMENT_SPECIAL_CASE,
    ),
    "production code sniffs jest": (
        _diff("web/src/sum.ts", added=["  if (process.env.NODE_ENV === 'test') return 5;"]),
        IntegrityCode.TEST_ENVIRONMENT_SPECIAL_CASE,
    ),
}


@pytest.mark.parametrize("patch,code", REJECT_CASES.values(), ids=REJECT_CASES.keys())
def test_weakening_patch_is_flagged_for_rejection(patch: str, code: IntegrityCode) -> None:
    findings = [f for f in analyze_patch(patch) if f.code is code]
    assert findings, f"expected {code.value}, got {_codes(patch)}"
    assert findings[0].severity is IntegritySeverity.REJECT


# --- changes a person must confirm are escalated --------------------------------------------

ESCALATE_CASES = {
    "expected value changed": (
        _diff("tests/test_calc.py", removed=["    assert calc.add(2, 3) == 6"], added=["    assert calc.add(2, 3) == 5"]),
        IntegrityCode.TEST_EXPECTATION_CHANGED,
    ),
    "noqa added": (
        _diff("src/calc.py", removed=["import os"], added=["import os  # noqa: F401"]),
        IntegrityCode.CHECK_SUPPRESSED_INLINE,
    ),
    "type ignore added": (
        _diff("src/calc.py", removed=["    return a + b"], added=["    return a + b  # type: ignore[operator]"]),
        IntegrityCode.CHECK_SUPPRESSED_INLINE,
    ),
    "ts-ignore added": (
        _diff("web/src/sum.ts", added=["  // @ts-ignore"], context=["  return a + b;"]),
        IntegrityCode.CHECK_SUPPRESSED_INLINE,
    ),
    "nosec added": (
        _diff("src/run.py", removed=["    subprocess.run(cmd, shell=True)"], added=["    subprocess.run(cmd, shell=True)  # nosec"]),
        IntegrityCode.CHECK_SUPPRESSED_INLINE,
    ),
    "branch on CI env": (
        _diff("src/calc.py", added=['    if os.getenv("CI"):', "        return cached"]),
        IntegrityCode.CI_ENVIRONMENT_BRANCH,
    ),
}


@pytest.mark.parametrize("patch,code", ESCALATE_CASES.values(), ids=ESCALATE_CASES.keys())
def test_verification_change_is_flagged_for_review(patch: str, code: IntegrityCode) -> None:
    findings = analyze_patch(patch)
    assert code in {f.code for f in findings}
    assert all(f.severity is IntegritySeverity.ESCALATE for f in findings), findings


# --- legitimate repairs are not flagged -----------------------------------------------------

CLEAN_CASES = {
    "production fix": _diff("src/calc.py", removed=["    return a - b"], added=["    return a + b"], context=["def add(a, b):"]),
    "new test added": _diff(
        "tests/test_calc.py",
        added=["def test_add_negative():", "    assert calc.add(-1, -2) == -3"],
        context=["import calc"],
    ),
    "assertion added": _diff("tests/test_calc.py", added=["    assert calc.add(0, 0) == 0"], context=["def test_add():"]),
    "test renamed": _diff("tests/test_calc.py", removed=["def test_addition():"], added=["def test_add():"]),
    "coverage threshold raised": _diff("pyproject.toml", removed=["fail_under = 80"], added=["fail_under = 85"]),
    "CI step added": _diff(".github/workflows/ci.yml", added=["      - run: mypy src"], context=["      - run: pytest"]),
    "CI step reworded": _diff(
        ".github/workflows/ci.yml", removed=["      - run: pytest -q"], added=["      - run: python -m pytest -q -ra"]
    ),
    "narrow except that re-raises": _diff(
        "src/calc.py",
        added=["    except ValueError as exc:", "        raise CalcError(str(exc)) from exc"],
    ),
    "broad except that logs and re-raises": _diff(
        "src/calc.py", added=["    except Exception:", "        log.exception('add failed')", "        raise"]
    ),
    "skip marker removed": _diff("tests/test_calc.py", removed=["@pytest.mark.skip"], context=["def test_add():"]),
    "docs mention pytest.mark.skip": _diff("docs/testing.md", added=["Avoid `pytest.mark.skip` in repairs."]),
}


@pytest.mark.parametrize("patch", CLEAN_CASES.values(), ids=CLEAN_CASES.keys())
def test_legitimate_repair_is_not_flagged(patch: str) -> None:
    assert analyze_patch(patch) == ()


def test_evidence_is_redacted_and_truncated() -> None:
    patch = _diff(
        "src/calc.py",
        added=[f'    except Exception: pass  # token=ghp_{"a" * 40} ' + "x" * 300],
    )
    (finding,) = analyze_patch(patch)
    assert "ghp_" not in finding.evidence
    assert len(finding.evidence) <= 160


# --- policy gate ----------------------------------------------------------------------------


def _passing_eval() -> EvaluationResult:
    return EvaluationResult(
        run_id="r",
        passed=True,
        patch_applied=True,
        target_verification_passed=True,
        regressions_detected=False,
        forbidden_changes_detected=False,
        checks=(EvaluationCheck("TARGET_TEST_PASSED", CheckStatus.PASSED),),
        evidence=(),
    )


def _decide(patch: str):
    files = tuple(d.path for d in parse_unified_diff(patch))
    proposal = RepairProposal(
        proposal_id=new_id("prop"),
        run_id="r",
        files_changed=files,
        patch=patch,
        rationale="r",
        expected_effect="e",
        verification_plan=("target_verification",),
    )
    classification = FailureClassification(
        run_id="r", category="test_failure", evidence=(), confidence=0.9, uncertainty="heuristic"
    )
    context = build_policy_context(proposal=proposal, evaluation=_passing_eval(), classification=classification)
    return context, StaticPolicyEngine().evaluate(context)


def test_policy_rejected_deleted_test_even_though_evaluation_passed() -> None:
    _, decision = _decide(REJECT_CASES["failing test removed"][0])
    assert decision.outcome is PolicyOutcome.REJECT
    assert decision.matched_rules == (RULE_VERIFICATION_WEAKENED,)
    assert "verification_weakened:TEST_CASE_REMOVED" in decision.reasons
    assert any("TEST_CASE_REMOVED tests/test_calc.py" in e for v in decision.violations for e in v.evidence)
    assert decision.policy_version == POLICY_VERSION


def test_policy_rejects_weakened_assertion() -> None:
    _, decision = _decide(REJECT_CASES["equality weakened to not-None"][0])
    assert decision.outcome is PolicyOutcome.REJECT
    assert "verification_weakened:ASSERTION_WEAKENED" in decision.reasons


def test_weakening_is_rejected_even_alongside_a_real_fix() -> None:
    patch = REJECT_CASES["pytest skip marker"][0] + CLEAN_CASES["production fix"]
    _, decision = _decide(patch)
    assert decision.outcome is PolicyOutcome.REJECT


def test_policy_still_approves_a_real_production_fix() -> None:
    _, decision = _decide(CLEAN_CASES["production fix"])
    assert decision.outcome is PolicyOutcome.APPROVE
    assert decision.matched_rules == (RULE_LOW_RISK_AUTO_APPROVE,)


def test_changed_test_expectation_escalates_with_its_own_reason() -> None:
    context, decision = _decide(ESCALATE_CASES["expected value changed"][0])
    assert decision.outcome is PolicyOutcome.ESCALATE
    assert RULE_VERIFICATION_CHANGE_REVIEW in decision.matched_rules
    codes = map_reason_codes(decision, context.file_categories)
    assert EscalationReasonCode.VERIFICATION_CHANGE in codes
    assert any("test expectation was wrong" in item for item in build_checklist(codes))


# --- end to end: CI green is not enough -----------------------------------------------------

BUGGY = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
TESTS = (
    "import calc\n\n\n"
    "def test_sub():\n    assert calc.sub(3, 1) == 2\n\n\n"
    "def test_add():\n    assert calc.add(2, 3) == 5\n"
)
DELETE_TEST_PATCH = (
    "diff --git a/tests/test_calc.py b/tests/test_calc.py\n"
    "--- a/tests/test_calc.py\n"
    "+++ b/tests/test_calc.py\n"
    "@@ -4,6 +4,2 @@ import calc\n"
    " def test_sub():\n"
    "     assert calc.sub(3, 1) == 2\n"
    "-\n"
    "-\n"
    "-def test_add():\n"
    "-    assert calc.add(2, 3) == 5\n"
)
REAL_FIX_PATCH = (
    "diff --git a/calc.py b/calc.py\n"
    "--- a/calc.py\n"
    "+++ b/calc.py\n"
    "@@ -1,5 +1,5 @@\n"
    " def add(a, b):\n"
    "-    return a - b\n"
    "+    return a + b\n"
    " \n"
    " \n"
    " def sub(a, b):\n"
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8")


def _run_with_provider(tmp_path: Path, patch: str) -> dict:
    repo = tmp_path / "target"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "calc.py").write_bytes(BUGGY.encode("utf-8"))
    (repo / "tests" / "test_calc.py").write_bytes(TESTS.encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    provider = tmp_path / "provider.py"
    provider.write_text(
        f"import sys\nsys.stdin.read()\nprint('```diff\\n' + {patch!r} + '```')\n", encoding="utf-8"
    )
    return run_fix_repo(
        FixRepoConfig(
            repo_path=repo,
            verify_commands=[f'"{sys.executable}" -m pytest -q -p no:cacheprovider --rootdir . tests'],
            artifacts_root=tmp_path / "artifacts",
            verify_timeout=120,
            provider_cmd=f'"{sys.executable}" "{provider}"',
            provider_timeout=60,
            max_attempts=1,
        )
    )


def test_deleting_the_failing_test_turns_ci_green_but_is_rejected(tmp_path: Path) -> None:
    outcome = _run_with_provider(tmp_path, DELETE_TEST_PATCH)

    assert outcome["technical_status"] == "PASS", outcome
    assert outcome["outcome"] == "REJECTED", outcome
    assert outcome["policy_outcome"] == "REJECT"
    assert RULE_VERIFICATION_WEAKENED in outcome["policy_rules"]


def test_fixing_the_code_is_approved(tmp_path: Path) -> None:
    outcome = _run_with_provider(tmp_path, REAL_FIX_PATCH)

    assert outcome["technical_status"] == "PASS", outcome
    assert outcome["outcome"] == "APPROVED", outcome
