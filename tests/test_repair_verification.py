"""A green CI run is necessary but not sufficient evidence of a correct repair.

Decision-level cases mirror the adversarial scenarios: a real fix, test deletion, assertion
weakening, a lowered coverage threshold, a hidden regression, real CI green without
regression evidence, and an authentication change. End-to-end cases run ``fix-repo`` against a
throwaway git repository and a fake CI provider.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from pathlib import Path

import pytest

from ci_failure_orchestrator.cli import main
from ci_failure_orchestrator.foundation import test_evidence as te
from ci_failure_orchestrator.foundation.diff_risk import HIGH, LOW, MEDIUM, max_level, score_diff_risk
from ci_failure_orchestrator.foundation.durable import FileAuditStore
from ci_failure_orchestrator.foundation.recovery import verify_run_consistency
from ci_failure_orchestrator.foundation.remediation import (
    GateStatus,
    MergeRequirement,
    RemediationState,
    VerificationResult,
    decide_remediation,
    is_verified_fix,
)
from ci_failure_orchestrator.foundation.verification_integrity import IntegrityCode, analyze_patch
from ci_failure_orchestrator.github_client import GitHubActionsClient
from ci_failure_orchestrator.patch_sandbox import WorktreePatchVerifier
from ci_failure_orchestrator.service import (
    CIRunState,
    CIRunStatus,
    FixRepoConfig,
    GitHubActionsCIProvider,
    VerificationConfig,
    apply_fix,
    compute_remediation_metrics,
    load_remediation_records,
    load_verification_config,
    read_verification_config_file,
    run_fix_repo,
    verify_real_ci,
)
from ci_failure_orchestrator.service.ci_verification import real_ci_passed
from ci_failure_orchestrator.service.verification import affected_test_candidates, pytest_prefix

S = RemediationState


def _diff(path: str, removed: list[str] = (), added: list[str] = (), context: list[str] = ()) -> str:
    old = len(context) + len(removed)
    new = len(context) + len(added)
    body = [f" {c}" for c in context] + [f"-{r}" for r in removed] + [f"+{a}" for a in added]
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,{old} +1,{new} @@\n" + "\n".join(body) + "\n"


def _reject_codes(patch: str) -> tuple[str, ...]:
    return tuple(sorted({f.code.value for f in analyze_patch(patch) if f.severity.value == "REJECT"}))


def _complete(**overrides) -> VerificationResult:
    """Every piece of evidence present and passing, real CI included."""
    base = VerificationResult(
        repair_proposed=True,
        patch_applied=True,
        original_failure_reproduced=True,
        original_failure_resolved=True,
        targeted_test_passed=True,
        affected_tests=GateStatus.PASSED,
        regression_suite=GateStatus.PASSED,
        test_count_decreased=False,
        skipped_tests_increased=False,
        coverage=GateStatus.PASSED,
        lint=GateStatus.PASSED,
        typecheck=GateStatus.PASSED,
        security=GateStatus.PASSED,
        build=GateStatus.WAIVED,
        behavioral_invariants=GateStatus.PASSED,
        policy_outcome="APPROVE",
        real_ci_passed=True,
        risk_level=LOW,
    )
    return dataclasses.replace(base, **overrides)


# --- decision-level adversarial cases ------------------------------------------------------


def test_case1_real_fix_with_full_evidence_is_verified() -> None:
    decision = decide_remediation(_complete())
    assert decision.state is S.VERIFIED_FIXED
    assert decision.verified
    assert decision.missing_evidence == ()
    assert decision.merge_requirement is MergeRequirement.AUTOMATIC_VERIFICATION_ALLOWED
    assert decision.trail[0] is S.FAILURE_RECEIVED and decision.trail[-1] is S.VERIFIED_FIXED
    assert S.REGRESSION_VALIDATION_PASSED in decision.trail


def test_medium_risk_verified_fix_still_needs_human_approval_before_merge() -> None:
    decision = decide_remediation(_complete(risk_level=MEDIUM))
    assert decision.state is S.VERIFIED_FIXED
    assert decision.merge_requirement is MergeRequirement.HUMAN_APPROVAL_BEFORE_MERGE


def test_case2_test_deletion_is_rejected_even_with_green_ci() -> None:
    patch = (
        "diff --git a/tests/test_calc.py b/tests/test_calc.py\ndeleted file mode 100644\n"
        "--- a/tests/test_calc.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-def test_add():\n-    assert add(2, 3) == 5\n"
    )
    codes = _reject_codes(patch)
    assert IntegrityCode.TEST_FILE_DELETED.value in codes
    decision = decide_remediation(_complete(forbidden_diff_detected=True, forbidden_diff_codes=codes))
    assert decision.state is S.POLICY_REJECTED
    assert decision.merge_requirement is MergeRequirement.BLOCKED
    assert "forbidden_diff:TEST_FILE_DELETED" in decision.reasons


def test_case3_assertion_weakening_is_rejected() -> None:
    patch = _diff("tests/test_calc.py", removed=["    assert add(2, 3) == 5"], added=["    assert add(2, 3) is not None"])
    codes = _reject_codes(patch)
    assert IntegrityCode.ASSERTION_WEAKENED.value in codes
    decision = decide_remediation(_complete(forbidden_diff_detected=True, forbidden_diff_codes=codes))
    assert decision.state is S.POLICY_REJECTED


def test_case4_lowered_coverage_threshold_is_rejected() -> None:
    patch = _diff("pyproject.toml", removed=["fail_under = 90"], added=["fail_under = 60"], context=["[tool.coverage.report]"])
    codes = _reject_codes(patch)
    assert IntegrityCode.COVERAGE_THRESHOLD_LOWERED.value in codes
    decision = decide_remediation(_complete(forbidden_diff_detected=True, forbidden_diff_codes=codes))
    assert decision.state is S.POLICY_REJECTED


def test_case5_hidden_regression_is_detected() -> None:
    decision = decide_remediation(
        _complete(regression_suite=GateStatus.FAILED, new_test_failures=("tests/test_sub.py::test_sub",))
    )
    assert decision.state is S.REGRESSION_DETECTED
    assert "new_test_failure:tests/test_sub.py::test_sub" in decision.reasons
    assert decision.merge_requirement is MergeRequirement.BLOCKED


def test_case6_real_ci_green_without_regression_evidence_is_unverified() -> None:
    decision = decide_remediation(_complete(regression_suite=GateStatus.NOT_RUN, test_count_decreased=None))
    assert decision.state is S.CI_GREEN_BUT_UNVERIFIED
    assert "regression_suite:NOT_RUN" in decision.missing_evidence
    assert decision.merge_requirement is MergeRequirement.HUMAN_REVIEW_REQUIRED


def test_case7_authentication_change_requires_human_review() -> None:
    patch = _diff("app/auth/login.py", removed=["    return user.password == pw"], added=["    return True"])
    risk = score_diff_risk(patch)
    assert risk.risk_level == HIGH
    assert any("authentication" in r for r in risk.reasons)

    decision = decide_remediation(_complete(risk_level=risk.risk_level, risk_reasons=risk.reasons))
    assert decision.state is S.HUMAN_REVIEW_REQUIRED
    assert decision.merge_requirement is MergeRequirement.HUMAN_REVIEW_REQUIRED

    approved = decide_remediation(_complete(risk_level=HIGH, human_approved=True))
    assert approved.state is S.VERIFIED_FIXED
    assert approved.merge_requirement is MergeRequirement.HUMAN_APPROVAL_BEFORE_MERGE


# --- precedence and partial outcomes --------------------------------------------------------


def test_default_evidence_is_never_verified() -> None:
    empty = VerificationResult()
    assert not is_verified_fix(empty)
    assert decide_remediation(empty).state is S.NOT_FIXED


@pytest.mark.parametrize(
    "override",
    [
        {"original_failure_reproduced": None},
        {"original_failure_reproduced": False},
        {"original_failure_resolved": None},
        {"targeted_test_passed": None},
        {"affected_tests": GateStatus.NOT_RUN},
        {"affected_tests": GateStatus.FAILED_PREEXISTING},
        {"regression_suite": GateStatus.NOT_RUN},
        {"test_count_decreased": None},
        {"coverage": GateStatus.NOT_RUN},
        {"lint": GateStatus.NOT_RUN},
        {"typecheck": GateStatus.FAILED_PREEXISTING},
        {"security": GateStatus.NOT_RUN},
        {"behavioral_invariants": GateStatus.NOT_RUN},
        {"policy_outcome": None, "human_approved": False},
    ],
)
def test_any_missing_evidence_blocks_verified(override: dict) -> None:
    result = _complete(**override)
    assert not is_verified_fix(result)
    assert decide_remediation(result).state is not S.VERIFIED_FIXED


def test_waived_gate_counts_but_preexisting_failure_does_not() -> None:
    assert is_verified_fix(_complete(lint=GateStatus.WAIVED))
    assert not is_verified_fix(_complete(lint=GateStatus.FAILED_PREEXISTING))


def test_different_error_replacing_the_original_is_not_fixed() -> None:
    decision = decide_remediation(_complete(targeted_test_passed=False, original_failure_resolved=False))
    assert decision.state is S.NOT_FIXED
    assert "targeted_validation_failed" in decision.reasons


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"target_test_missing": True}, "target_test_missing_after_patch"),
        ({"test_count_decreased": True}, "test_count_decreased"),
        ({"skipped_tests_increased": True}, "skipped_tests_increased"),
        ({"policy_outcome": "REJECT"}, "policy_rejected"),
    ],
)
def test_weakened_verification_is_rejected(override: dict, reason: str) -> None:
    decision = decide_remediation(_complete(**override))
    assert decision.state is S.POLICY_REJECTED
    assert reason in decision.reasons


def test_rejection_takes_precedence_over_regression_and_not_fixed() -> None:
    result = _complete(
        forbidden_diff_detected=True,
        forbidden_diff_codes=("TEST_SKIPPED",),
        targeted_test_passed=False,
        regression_suite=GateStatus.FAILED,
    )
    assert decide_remediation(result).state is S.POLICY_REJECTED


def test_local_evidence_before_real_ci_awaits_verification() -> None:
    decision = decide_remediation(_complete(real_ci_passed=None))
    assert decision.state is S.POLICY_APPROVED
    assert decision.reasons == ("awaiting_real_ci_verification",)
    assert decision.missing_evidence == ("real_ci_passed",)


def test_real_ci_failure_after_local_verification_needs_review() -> None:
    decision = decide_remediation(_complete(real_ci_passed=False))
    assert decision.state is S.HUMAN_REVIEW_REQUIRED
    assert "real_ci_failed_after_local_verification" in decision.reasons


def test_uncomparable_ci_failure_cannot_be_verified() -> None:
    decision = decide_remediation(_complete(original_failure_reproduced=None))
    assert decision.state is S.CI_GREEN_BUT_UNVERIFIED
    assert "original_failure_reproduced" in decision.missing_evidence


def test_policy_escalation_without_human_approval_needs_review() -> None:
    decision = decide_remediation(_complete(policy_outcome="ESCALATE"))
    assert decision.state is S.HUMAN_REVIEW_REQUIRED
    assert decide_remediation(_complete(policy_outcome="ESCALATE", human_approved=True)).verified


def test_verification_result_round_trips_through_dict() -> None:
    original = _complete(new_test_failures=("a::b",), risk_reasons=("x",), real_ci_passed=None)
    data = json.loads(json.dumps(original.to_dict()))
    assert data["lint_passed"] is True and data["coverage_regressed"] is False
    assert VerificationResult.from_dict(data) == original


# --- test evidence parsing ------------------------------------------------------------------


def _run_pytest(tmp_path: Path, source: str, *args: str) -> subprocess.CompletedProcess:
    (tmp_path / "test_sample.py").write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, "test_sample.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


SAMPLE_TESTS = (
    "import pytest\n\n"
    "def test_ok():\n    assert 1\n\n"
    "def test_bad():\n    assert 1 + 1 == 3\n\n"
    "@pytest.mark.skip(reason='x')\ndef test_skipped():\n    pass\n\n"
    "@pytest.mark.xfail\ndef test_xfail():\n    assert 0\n\n"
    "def test_error():\n    raise KeyError('missing')\n"
)


def test_real_pytest_output_is_parsed(tmp_path: Path) -> None:
    proc = _run_pytest(tmp_path, SAMPLE_TESTS)
    summary = te.parse_test_output(proc.stdout + proc.stderr)
    assert proc.returncode == te.PYTEST_TESTS_FAILED
    assert summary.parsed
    assert (summary.passed, summary.failed, summary.skipped, summary.xfailed) == (1, 2, 1, 1)
    assert summary.total == 5
    assert summary.failed_ids == {"test_sample.py::test_bad", "test_sample.py::test_error"}

    fp = te.fingerprint_failure(proc.stdout, exit_code=proc.returncode)
    assert fp.failure_class == "TEST_FAILURE"
    assert fp.test == "test_sample.py::test_bad"
    assert fp.exception_type == "AssertionError"


def test_coverage_total_and_ci_timestamps_are_parsed() -> None:
    text = (
        "2026-10-05T10:00:00.1234567Z FAILED tests/test_a.py::test_x - ValueError: bad 0x7f3a\n"
        "2026-10-05T10:00:00.2Z TOTAL      40      4    90%\n"
        "2026-10-05T10:00:00.3Z ======= 1 failed, 3 passed in 0.52s =======\n"
    )
    summary = te.parse_test_output(text)
    assert summary.parsed and summary.failed == 1 and summary.passed == 3
    assert summary.coverage_percent == 90.0
    assert summary.failures[0].exception_type == "ValueError"


def test_result_line_requires_a_duration() -> None:
    assert not te.parse_test_output("we saw 3 passed builds yesterday").parsed
    assert not te.parse_test_output("3 passed").parsed


def test_failure_fingerprints_compare_by_test_then_exception() -> None:
    a = te.fingerprint_failure("FAILED tests/t.py::test_a - assert 1 == 2\n1 failed in 0.1s")
    b = te.fingerprint_failure("FAILED tests/t.py::test_a - assert 3 == 2\n1 failed in 0.2s")
    other = te.fingerprint_failure("FAILED tests/t.py::test_b - KeyError: x\n1 failed in 0.1s")
    assert te.same_failure(a, b) is True
    assert te.same_failure(a, other) is False
    unknown = te.fingerprint_failure("make: *** [all] Error 2", exit_code=2)
    assert te.same_failure(a, unknown) is None
    assert te.fingerprint_failure("", exit_code=124).failure_class == "TIMEOUT"


def test_normalized_message_drops_volatile_parts() -> None:
    one = te.normalize_message("Timeout after 1.5s at 0xdeadbeef in /tmp/run1/file.py")
    two = te.normalize_message("Timeout after 3s at 0x1234 in /var/run2/file.py")
    assert one == two


# --- diff risk -----------------------------------------------------------------------------


def test_small_production_fix_is_low_risk() -> None:
    risk = score_diff_risk(_diff("calc.py", removed=["    return a - b"], added=["    return a + b"]))
    assert risk.risk_level == LOW
    assert risk.factors["production_files"] == ["calc.py"]


def test_authorization_marker_in_changed_lines_forces_high() -> None:
    patch = _diff("app/views.py", removed=["@login_required", "def dashboard(request):"], added=["def dashboard(request):"])
    risk = score_diff_risk(patch)
    assert risk.risk_level == HIGH
    assert risk.factors["authorization"] == ["app/views.py"]


def test_word_matching_avoids_false_positives() -> None:
    risk = score_diff_risk(_diff("src/tokenizer.py", removed=["x = 1"], added=["x = 2"]))
    assert risk.risk_level == LOW


@pytest.mark.parametrize(
    "path",
    ["db/migrations/0004_add_index.py", "billing/charges.py", "config/secrets.yaml", "schema/upgrade.sql"],
)
def test_sensitive_areas_force_high(path: str) -> None:
    assert score_diff_risk(_diff(path, removed=["a"], added=["b"])).risk_level == HIGH


def test_ci_config_change_is_at_least_medium() -> None:
    risk = score_diff_risk(_diff(".github/workflows/ci.yml", removed=["  - run: pytest"], added=["  - run: pytest -q"]))
    assert risk.risk_level in (MEDIUM, HIGH)


def test_unknown_risk_level_fails_safe_to_high() -> None:
    assert max_level(None, "weird") == HIGH
    assert max_level(LOW, MEDIUM) == MEDIUM


# --- integrity: rename out of discovery -----------------------------------------------------


def _rename(old: str, new: str) -> str:
    return f"diff --git a/{old} b/{new}\nsimilarity index 100%\nrename from {old}\nrename to {new}\n"


def test_renaming_a_test_out_of_discovery_is_rejected() -> None:
    codes = {f.code for f in analyze_patch(_rename("tests/test_calc.py", "tests/calc_cases.py"))}
    assert IntegrityCode.TEST_FILE_RENAMED_OUT_OF_DISCOVERY in codes


def test_renaming_a_test_within_discovery_is_allowed() -> None:
    codes = {f.code for f in analyze_patch(_rename("tests/test_calc.py", "tests/test_calculator.py"))}
    assert IntegrityCode.TEST_FILE_RENAMED_OUT_OF_DISCOVERY not in codes


# --- verification config --------------------------------------------------------------------


def test_verification_config_loads_and_appends_cli_regression() -> None:
    config = load_verification_config(
        {
            "regression": "pytest -q",
            "lint": ["ruff check ."],
            "invariants": [{"name": "health", "command": "python -c 'print(1)'"}],
            "waive": {"build": "pure Python, nothing to build"},
            "affected_tests": {"src/calc.py": ["tests/test_calc.py"]},
            "coverage_tolerance": 1,
        },
        regression=["pytest tests/integration"],
    )
    assert config.regression == ("pytest -q", "pytest tests/integration")
    assert config.invariants[0].name == "health"
    assert config.waivers == {"build": "pure Python, nothing to build"}
    assert config.coverage_tolerance == 1.0


@pytest.mark.parametrize(
    "data",
    [
        {"regresion": "pytest"},
        {"waive": {"regression_suite": "slow"}},
        {"waive": {"lint": " "}},
        {"invariants": [{"name": "x"}]},
        {"invariants": [{"name": "x", "command": "a"}, {"name": "x", "command": "b"}]},
        {"coverage_tolerance": -1},
        {"coverage_tolerance": "lots"},
        {"lint": [""]},
        {"test_command": 3},
    ],
)
def test_invalid_verification_config_is_an_error(data: dict) -> None:
    with pytest.raises(ValueError):
        load_verification_config(data)


def test_verification_config_file_must_be_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "verify.yml"
    path.write_text("- pytest\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_verification_config_file(path)


def test_affected_tests_and_pytest_prefix() -> None:
    candidates = affected_test_candidates(["src/pkg/calc.py", "tests/test_other.py"], {})
    assert "tests/test_calc.py" in candidates
    assert "tests/pkg/test_calc.py" in candidates
    assert "tests/test_other.py" in candidates
    assert pytest_prefix(["python", "-m", "pytest", "-q", "tests"]) == ("python", "-m", "pytest")
    assert pytest_prefix(["/usr/bin/pytest.exe", "-x"]) == ("/usr/bin/pytest.exe",)
    assert pytest_prefix(["npm", "test"]) is None


# --- real CI provider (recorded response shapes, not the live API) --------------------------


class RecordedGitHubClient(GitHubActionsClient):
    """Serves recorded GitHub API responses; requests are recorded instead of sent."""

    def __init__(self, responses: dict[str, object]) -> None:
        super().__init__(token="test-token")
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def _request(self, path: str, *, accept: str = "application/vnd.github+json", method: str = "GET") -> bytes:
        self.calls.append((method, path))
        if method == "POST":
            return b""
        return json.dumps(self.responses[path]).encode("utf-8")


REPO = "octo/app"
SHA = "a" * 40
RECORDED = {
    f"/repos/{REPO}/actions/runs?head_sha={SHA}&per_page=100": {
        "total_count": 2,
        "workflow_runs": [{"id": 11, "head_sha": SHA}, {"id": 12, "head_sha": SHA}],
    },
    f"/repos/{REPO}/actions/runs/11": {
        "id": 11, "name": "CI", "status": "completed", "conclusion": "success", "html_url": "https://x/11",
    },
    f"/repos/{REPO}/actions/runs/12": {
        "id": 12, "name": "Lint", "status": "completed", "conclusion": "failure", "html_url": "https://x/12",
    },
    f"/repos/{REPO}/actions/runs/13": {"id": 13, "name": "CI", "status": "in_progress", "conclusion": None},
    f"/repos/{REPO}/actions/runs/14": {"id": 14, "name": "Docs", "status": "completed", "conclusion": "skipped"},
    f"/repos/{REPO}/actions/runs/12/jobs?filter=latest&per_page=100": {
        "jobs": [{"id": 1, "name": "ruff", "conclusion": "failure"}, {"id": 2, "name": "mypy", "conclusion": "success"}],
    },
}


def test_github_adapter_maps_recorded_responses() -> None:
    client = RecordedGitHubClient(RECORDED)
    provider = GitHubActionsCIProvider(REPO, client)
    assert provider.find_runs(SHA) == ["11", "12"]
    assert provider.get_status("11").state is CIRunState.SUCCESS
    assert provider.get_status("12").state is CIRunState.FAILURE
    assert provider.get_status("13").state is CIRunState.PENDING
    assert provider.get_status("14").state is CIRunState.SKIPPED
    assert provider.get_failed_jobs("12") == ["ruff"]
    assert provider.get_test_results("11") is None
    provider.rerun("12")
    assert ("POST", f"/repos/{REPO}/actions/runs/12/rerun") in client.calls
    assert all(method in ("GET", "POST") for method, _ in client.calls)


def test_github_adapter_requires_owner_and_name() -> None:
    with pytest.raises(ValueError):
        GitHubActionsCIProvider("just-a-name", RecordedGitHubClient({}))


def test_real_ci_aggregation_is_fail_safe() -> None:
    ok = CIRunStatus("1", CIRunState.SUCCESS)
    bad = CIRunStatus("2", CIRunState.FAILURE)
    pending = CIRunStatus("3", CIRunState.PENDING)
    skipped = CIRunStatus("4", CIRunState.SKIPPED)
    assert real_ci_passed([]) is None
    assert real_ci_passed([ok, pending]) is None
    assert real_ci_passed([ok, bad]) is False
    assert real_ci_passed([skipped]) is None
    assert real_ci_passed([ok, skipped]) is True


# --- metrics -------------------------------------------------------------------------------


def test_verified_repair_rate_is_the_primary_metric() -> None:
    records = [
        {"state": "VERIFIED_FIXED", "repair_attempted": True, "ci_green": True,
         "failure_received_at": "2026-10-05T10:00:00+00:00", "decided_at": "2026-10-05T10:10:00+00:00"},
        {"state": "POLICY_REJECTED", "repair_attempted": True, "ci_green": True},
        {"state": "REGRESSION_DETECTED", "repair_attempted": True, "ci_green": True},
        {"state": "HUMAN_REVIEW_REQUIRED", "repair_attempted": True, "ci_green": False},
        {"state": "NOT_FIXED", "repair_attempted": False, "ci_green": False},
    ]
    metrics = compute_remediation_metrics(records)
    assert metrics["primary_metric"] == "verified_repair_rate"
    assert metrics["attempted_repairs"] == 4
    assert metrics["verified_repair_rate"] == 0.25
    assert metrics["ci_green_rate"] == 0.75
    assert metrics["false_repair_rate"] == round(2 / 3, 4)
    assert metrics["mean_time_to_verified_repair_seconds"] == 600


# --- end to end ----------------------------------------------------------------------------

PY = f'"{sys.executable}" -m pytest -q -p no:cacheprovider --rootdir .'
BUGGY = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
TEST_ADD = "import calc\n\n\ndef test_add():\n    assert calc.add(2, 3) == 5\n"
TEST_SUB = "import calc\n\n\ndef test_sub():\n    assert calc.sub(3, 1) == 2\n"
FIX_ADD = (
    "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
    "@@ -1,5 +1,5 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n \n \n def sub(a, b):\n"
)
FIX_ADD_BREAK_SUB = (
    "diff --git a/calc.py b/calc.py\n--- a/calc.py\n+++ b/calc.py\n"
    "@@ -1,6 +1,6 @@\n def add(a, b):\n-    return a - b\n+    return a + b\n \n \n def sub(a, b):\n"
    "-    return a - b\n+    return a + b\n"
)
DELETE_TEST_ADD = (
    "diff --git a/tests/test_add.py b/tests/test_add.py\ndeleted file mode 100644\n"
    "--- a/tests/test_add.py\n+++ /dev/null\n@@ -1,5 +0,0 @@\n"
    "-import calc\n-\n-\n-def test_add():\n-    assert calc.add(2, 3) == 5\n"
)


def _mark_test_add(marker: str) -> str:
    return (
        "diff --git a/tests/test_add.py b/tests/test_add.py\n--- a/tests/test_add.py\n+++ b/tests/test_add.py\n"
        "@@ -1,5 +1,7 @@\n+import pytest\n import calc\n \n \n"
        f"+{marker}\n def test_add():\n     assert calc.add(2, 3) == 5\n"
    )


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


def _repo(tmp_path: Path, module: str = "calc") -> Path:
    repo = tmp_path / "target"
    (repo / "tests").mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / f"{module}.py").write_bytes(BUGGY.encode("utf-8"))
    (repo / "tests" / "test_add.py").write_bytes(TEST_ADD.replace("calc", module).encode("utf-8"))
    (repo / "tests" / "test_sub.py").write_bytes(TEST_SUB.replace("calc", module).encode("utf-8"))
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    return repo


def _fix(
    tmp_path: Path,
    repo: Path,
    patch: str,
    verification: VerificationConfig | None = None,
    verify_target: str = "tests/test_add.py",
) -> dict:
    provider = tmp_path / "provider.py"
    provider.write_text(f"import sys\nsys.stdin.read()\nprint('```diff\\n' + {patch!r} + '```')\n", encoding="utf-8")
    return run_fix_repo(
        FixRepoConfig(
            repo_path=repo,
            verify_commands=[f"{PY} {verify_target}"],
            artifacts_root=tmp_path / "artifacts",
            verify_timeout=120,
            provider_cmd=f'"{sys.executable}" "{provider}"',
            provider_timeout=60,
            max_attempts=1,
            verification=verification,
        )
    )


FULL_VERIFICATION = {
    "regression": f"{PY} --cov=calc --cov-report=term tests",
    "lint": f'"{sys.executable}" -m py_compile calc.py',
    "invariants": [{"name": "sub still subtracts", "command": f'"{sys.executable}" -c "import calc; assert calc.sub(3, 1) == 2"'}],
    "waive": {
        "typecheck": "project has no type checker configured",
        "security": "no security scanner configured for this fixture",
        "build": "pure Python, nothing to build",
    },
}


class FakeCI:
    name = "fake-ci"

    def __init__(self, state: CIRunState) -> None:
        self.state = state
        self.commits: list[str] = []

    def find_runs(self, commit_sha: str) -> list[str]:
        self.commits.append(commit_sha)
        return ["101"]

    def rerun(self, run_id: str) -> None:
        raise AssertionError("not requested")

    def get_status(self, run_id: str) -> CIRunStatus:
        return CIRunStatus(run_id, self.state, self.state.value.lower(), "CI")

    def get_failed_jobs(self, run_id: str) -> list[str]:
        return ["tests"] if self.state is CIRunState.FAILURE else []

    def get_test_results(self, run_id: str):
        return None


def _events(artifacts: Path, run_id: str) -> list[dict]:
    path = artifacts / "runs" / run_id / "events.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _remediation(artifacts: Path, run_id: str) -> dict:
    return json.loads((artifacts / "runs" / run_id / "fix-repo" / "remediation.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("patch", "code", "ci_green"),
    [
        (_mark_test_add("@pytest.mark.skip(reason='flaky')"), "TEST_SKIPPED", True),
        (_mark_test_add("@pytest.mark.xfail"), "TEST_SKIPPED", True),
        (DELETE_TEST_ADD, "TEST_FILE_DELETED", False),
    ],
    ids=["skip", "xfail", "delete-file"],
)
def test_e2e_disabling_the_failing_test_is_policy_rejected(tmp_path: Path, patch: str, code: str, ci_green: bool) -> None:
    outcome = _fix(tmp_path, _repo(tmp_path), patch)
    artifacts = tmp_path / "artifacts"

    assert (outcome["technical_status"] == "PASS") is ci_green, outcome
    assert outcome["remediation_state"] == "POLICY_REJECTED", outcome
    assert outcome["remediation"]["merge_requirement"] == "BLOCKED"
    assert f"forbidden_diff:{code}" in outcome["remediation"]["reasons"], outcome["remediation"]["reasons"]
    assert outcome["remediation"]["checks"]["quality_gate_preserved"] == "FAILED"

    events = [e for e in _events(artifacts, outcome["run_id"]) if e["event_type"] == "REPAIR_VERIFICATION_COMPLETED"]
    assert len(events) == 1 and events[0]["metadata"]["result"] == "POLICY_REJECTED"
    assert verify_run_consistency(artifacts_root=artifacts, run_id=outcome["run_id"]).valid
    assert FileAuditStore(artifacts).latest_sequence(outcome["run_id"]) >= events[0]["sequence"]


def test_e2e_real_fix_with_full_evidence_becomes_verified_only_after_real_ci(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    outcome = _fix(tmp_path, repo, FIX_ADD, load_verification_config(FULL_VERIFICATION))
    artifacts = tmp_path / "artifacts"
    run_id = outcome["run_id"]

    assert outcome["outcome"] == "APPROVED", outcome
    assert outcome["remediation_state"] == "POLICY_APPROVED", outcome["remediation"]
    assert outcome["remediation"]["missing_evidence"] == ["real_ci_passed"]
    assert outcome["remediation"]["ci_green_source"] == "sandbox"

    detail = json.loads((artifacts / "runs" / run_id / "fix-repo" / "verification.json").read_text(encoding="utf-8"))
    evidence = detail["evidence"]
    assert evidence["reproduction"]["original_failure_reproduced"] is True
    assert evidence["reproduction"]["failed_test"] == "tests/test_add.py::test_add"
    assert evidence["targeted_validation"]["exact_test_rerun"] == "PASSED"
    assert evidence["regression"]["tests_before"]["total"] == evidence["regression"]["tests_after"]["total"] == 2
    assert evidence["regression"]["coverage_after"] is not None
    assert detail["result"]["behavioral_invariants"] == "PASSED"
    assert detail["result"]["lint"] == "PASSED"
    assert detail["result"]["typecheck"] == "WAIVED"

    applied = apply_fix(artifacts, run_id)
    assert applied.status == "APPLIED", applied

    pending = verify_real_ci(artifacts, run_id, FakeCI(CIRunState.PENDING))
    assert pending["outcome"] == "PENDING"
    assert _remediation(artifacts, run_id)["state"] == "POLICY_APPROVED"

    ci = FakeCI(CIRunState.SUCCESS)
    final = verify_real_ci(artifacts, run_id, ci)
    assert ci.commits == [applied.commit]
    assert final["outcome"] == "VERIFIED_FIXED", final
    summary = _remediation(artifacts, run_id)
    assert summary["state"] == "VERIFIED_FIXED" and summary["verified"] is True
    assert summary["ci_green_source"] == "real_ci"
    assert summary["checks"]["real_ci_validation"] == "PASSED"
    assert summary["merge_requirement"] == "AUTOMATIC_VERIFICATION_ALLOWED"
    assert verify_run_consistency(artifacts_root=artifacts, run_id=run_id).valid

    metrics = compute_remediation_metrics(load_remediation_records(artifacts))
    assert metrics["verified_repair_rate"] == 1.0


def test_e2e_real_ci_green_without_regression_suite_is_unverified(tmp_path: Path) -> None:
    outcome = _fix(tmp_path, _repo(tmp_path), FIX_ADD)
    artifacts = tmp_path / "artifacts"
    run_id = outcome["run_id"]
    assert outcome["remediation_state"] == "POLICY_APPROVED"
    assert "regression_suite:NOT_RUN" in outcome["remediation"]["missing_evidence"]

    assert apply_fix(artifacts, run_id).status == "APPLIED"
    final = verify_real_ci(artifacts, run_id, FakeCI(CIRunState.SUCCESS))
    assert final["outcome"] == "CI_GREEN_BUT_UNVERIFIED", final
    assert final["remediation"]["ci_green"] is True and final["remediation"]["verified"] is False


def test_e2e_hidden_regression_is_detected_and_apply_refuses(tmp_path: Path) -> None:
    config = load_verification_config({"regression": f"{PY} tests"})
    outcome = _fix(tmp_path, _repo(tmp_path), FIX_ADD_BREAK_SUB, config)
    artifacts = tmp_path / "artifacts"

    assert outcome["technical_status"] == "PASS", outcome
    assert outcome["remediation_state"] == "REGRESSION_DETECTED", outcome["remediation"]
    assert "new_test_failure:tests/test_sub.py::test_sub" in outcome["remediation"]["reasons"]

    applied = apply_fix(artifacts, outcome["run_id"])
    assert applied.status == "BLOCKED"
    assert "REGRESSION_DETECTED" in applied.message


def test_e2e_authentication_module_change_requires_human_review(tmp_path: Path) -> None:
    repo = _repo(tmp_path, module="auth")
    config = load_verification_config({"regression": f"{PY} tests"})
    outcome = _fix(tmp_path, repo, FIX_ADD.replace("calc.py", "auth.py"), config)
    assert outcome["remediation_state"] == "HUMAN_REVIEW_REQUIRED", outcome["remediation"]
    assert outcome["remediation"]["risk_level"] == HIGH
    assert outcome["remediation"]["merge_requirement"] == "HUMAN_REVIEW_REQUIRED"


def _cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["actions-doctor", *argv])
    return main()


def test_cli_rejects_invalid_verification_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "verify.yml"
    config.write_text("waive:\n  regression_suite: too slow\n", encoding="utf-8")
    code = _cli(
        monkeypatch,
        "fix-repo", "--repo-path", str(tmp_path), "--verify", "pytest", "--patch-file", str(config),
        "--verification-config", str(config), "--artifacts", str(tmp_path / "a"),
    )
    assert code == 2
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "ERROR" and "cannot waive" in out["message"]


def test_cli_metrics_and_verify_ci_without_local_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _cli(monkeypatch, "fix-repo-metrics", "--artifacts", str(tmp_path)) == 0
    assert json.loads(capsys.readouterr().out)["primary_metric"] == "verified_repair_rate"

    code = _cli(monkeypatch, "fix-repo-verify-ci", "run-missing", "--repository", "octo/app", "--artifacts", str(tmp_path))
    assert code == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "ERROR"


def test_sandbox_keep_going_mode_runs_every_command(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").strip()
    commands = (
        ("first", (sys.executable, "-c", "raise SystemExit(1)")),
        ("second", (sys.executable, "-c", "print('ran')")),
    )
    stop = WorktreePatchVerifier(commands=commands, timeout_seconds=60).reproduce(repo_path=repo, base_ref=head)
    keep = WorktreePatchVerifier(commands=commands, timeout_seconds=60, stop_on_failure=False).reproduce(
        repo_path=repo, base_ref=head
    )
    assert [s.name for s in stop] == ["first"]
    assert [s.name for s in keep] == ["first", "second"]
    assert keep[1].passed
