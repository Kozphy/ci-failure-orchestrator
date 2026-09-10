from ci_failure_orchestrator.baselines import (
    dependency_graph_baseline,
    latest_visible_baseline,
    run_baseline,
)


def tiny_corpus():
    return {
        "version": "test",
        "stages": [
            {"id": "lint", "depends_on": [], "criticality": 0.4},
            {"id": "test", "depends_on": ["lint"], "criticality": 0.8},
            {"id": "build", "depends_on": ["test"], "criticality": 0.9},
        ],
        "cases": [
            {
                "id": "cascade",
                "root_cause": "test",
                "failures": [
                    {"stage": "test", "error_type": "TEST_ASSERTION", "confidence": 0.95, "severity": 0.8},
                    {"stage": "build", "error_type": "BUILD_ERROR", "confidence": 0.7, "severity": 0.7},
                ],
                "failed_before": ["test", "build"],
                "failed_after_fix": [],
            }
        ],
    }


def test_latest_visible_baseline_returns_case_level_prediction():
    result = latest_visible_baseline(tiny_corpus())
    assert len(result) == 1
    assert result[0].case_id == "cascade"
    assert result[0].prediction == "build"
    assert result[0].correct is False


def test_dependency_graph_baseline_returns_prediction():
    result = dependency_graph_baseline(tiny_corpus())
    assert len(result) == 1
    assert result[0].prediction in {"test", "build"}
    assert result[0].truth == "test"


def test_registry_rejects_unimplemented_baseline():
    try:
        run_baseline("B1", tiny_corpus())
    except ValueError as exc:
        assert "Unsupported executable baseline" in str(exc)
    else:
        raise AssertionError("B1 must remain fail-closed until an LLM runner is implemented")
