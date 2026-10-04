"""actions-doctor demo: every scenario runs failure -> diagnosis -> verification -> policy -> evidence.

The full runs create real git repositories and verify the recorded fix in a disposable
worktree, so they also prove each scenario fails at its base commit and passes with the fix.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ci_failure_orchestrator.ci_audit.collect import failing_section, failure_message
from ci_failure_orchestrator.doctor.cli import main
from ci_failure_orchestrator.doctor.demo import recorded_patch, run_scenario
from ci_failure_orchestrator.doctor.diagnose import diagnose_log
from ci_failure_orchestrator.doctor.scenarios import SCENARIOS
from ci_failure_orchestrator.foundation.classifier import intermittent_tests


def test_the_brief_s_six_failure_types_are_covered():
    assert set(SCENARIOS) == {
        "dependency-drift",
        "flaky-test",
        "network-failure",
        "timeout",
        "configuration-error",
        "environment-mismatch",
    }


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_saved_log_diagnoses_to_the_expected_category(name):
    scenario = SCENARIOS[name]
    top = diagnose_log(scenario.ci_log, job=scenario.job, step=scenario.step).findings[0]
    assert top.policy_category == scenario.expected_category
    assert top.category == scenario.expected_category
    assert top.evidence_line is not None


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_recorded_patch_touches_only_the_fix_files(name):
    scenario = SCENARIOS[name]
    patch = recorded_patch(scenario)
    touched = {line[len("+++ b/") :].strip() for line in patch.splitlines() if line.startswith("+++ b/")}
    assert touched == set(scenario.fix)
    assert not any(line.rstrip() != line for line in patch.splitlines() if line.startswith("+"))


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_scenario_runs_end_to_end_with_the_expected_decision(name, tmp_path):
    scenario = SCENARIOS[name]
    result, lines = run_scenario(scenario, tmp_path)

    assert result.as_expected, "\n".join(lines)
    assert result.outcome == scenario.expected_outcome
    artifacts = Path(result.artifacts)
    assert artifacts.is_dir() and artifacts.parent.parent == tmp_path / "artifacts"
    if name == "network-failure":
        escalation = json.loads((artifacts / "fix-repo" / "environment-escalation.json").read_text("utf-8"))
        assert escalation["provider_called"] is False
        assert escalation["finding"]["kind"] == "network"
        assert result.rules == ()
    else:
        decision = json.loads((artifacts / "policy" / "policy-decision.json").read_text("utf-8"))
        assert tuple(decision["matched_rules"]) == result.rules
        assert (artifacts / "fix-repo" / "final.patch").read_text("utf-8") == recorded_patch(scenario)
    assert any(line.startswith("6 Evidence") for line in lines)


def test_no_demo_fix_is_auto_approved():
    # flaky-test was approved until POL-019: its fix rewrites the test's assertion.
    approved = [s.name for s in SCENARIOS.values() if s.expected_outcome == "APPROVED"]
    assert approved == []


def test_demo_cli_lists_scenarios(capsys):
    assert main(["demo", "--list"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in SCENARIOS)


def test_demo_cli_needs_one_scenario_or_all(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["demo"])
    assert exc.value.code == 2


def test_demo_cli_refuses_a_non_empty_workdir(tmp_path, capsys):
    (tmp_path / "keep.txt").write_text("user data", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["demo", "configuration-error", "--workdir", str(tmp_path)])
    assert exc.value.code == 2
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "user data"


def test_demo_cli_runs_one_scenario(tmp_path, capsys):
    assert main(["demo", "configuration-error", "--workdir", str(tmp_path / "demo")]) == 0
    out = capsys.readouterr().out
    assert "POL-006-DEFAULT-ESCALATION" in out
    assert "matched" in out


def test_same_test_passing_and_failing_in_one_run_is_intermittent():
    log = (
        "tests/test_a.py::test_x[1-3] PASSED       [ 33%]\n"
        "tests/test_a.py::test_x[2-3] FAILED       [ 66%]\n"
        "tests/test_a.py::test_y[1-3] FAILED       [100%]\n"
    )
    assert intermittent_tests(log) == ("tests/test_a.py::test_x",)


def test_different_parameters_are_not_repeats():
    log = "tests/test_a.py::test_x[small] PASSED\ntests/test_a.py::test_x[large] FAILED\n"
    assert intermittent_tests(log) == ()


def test_unittest_message_is_the_exception_not_the_test_header():
    section = (
        "##[group]Run python -m unittest\n"
        "##[endgroup]\n"
        "ERROR: test_client (unittest.loader._FailedTest.test_client)\n"
        "----------------------------------------------------------------------\n"
        "ImportError: Failed to import test module: test_client\n"
        "Traceback (most recent call last):\n"
        '  File "/w/tests/test_client.py", line 1, in <module>\n'
        "    from fakelib import parse\n"
        "ImportError: cannot import name 'parse' from 'fakelib'\n"
        "FAILED (errors=1)\n"
        "##[error]Process completed with exit code 1."
    )
    assert failure_message(failing_section(section)) == "ImportError: cannot import name 'parse' from 'fakelib'"


def test_pytest_collection_error_summary_is_the_message():
    section = (
        "##[group]Run python -m pytest -q\n"
        "##[endgroup]\n"
        "E   ModuleNotFoundError: No module named 'yaml'\n"
        "=========================== short test summary info ============================\n"
        "ERROR tests/test_cfg.py - ModuleNotFoundError: No module named 'yaml'\n"
        "1 error in 0.05s\n"
        "##[error]Process completed with exit code 2."
    )
    assert failure_message(section) == "ERROR tests/test_cfg.py - ModuleNotFoundError: No module named 'yaml'"
