from ci_failure_orchestrator.failure_memory import (
    FailureMemoryAgent,
    IncidentMemory,
    InMemoryIncidentStore,
    MemoryQuery,
)


def test_retrieves_similar_successful_incident_first():
    store = InMemoryIncidentStore([
        IncidentMemory(
            incident_id="old-1",
            error_signature="mypy Optional str incompatible assignment",
            failure_class="type_check",
            root_stage="type-check",
            changed_files=("src/foo.py",),
            successful_patch_summary="guard Optional before assignment",
            affected_tests=("tests/test_foo.py",),
            retries=1,
            cost_usd=0.02,
        ),
        IncidentMemory(
            incident_id="old-2",
            error_signature="docker registry timeout",
            failure_class="infra",
            root_stage="build",
            changed_files=("Dockerfile",),
        ),
    ])
    agent = FailureMemoryAgent(store)
    results = agent.retrieve(MemoryQuery(
        error_signature="mypy Optional str assignment error",
        failure_class="type_check",
        root_stage="type-check",
        changed_files=("src/foo.py",),
    ))
    assert results[0].incident.incident_id == "old-1"
    assert results[0].similarity > 0.7


def test_memory_is_advisory_and_preserves_regression_history():
    agent = FailureMemoryAgent(InMemoryIncidentStore())
    agent.remember(IncidentMemory(
        incident_id="regressed",
        error_signature="pytest assertion failure",
        failure_class="test",
        root_stage="unit-test",
        successful_patch_summary="changed assertion",
        regression_detected=True,
    ))
    results = agent.retrieve(MemoryQuery(
        error_signature="pytest assertion failure",
        failure_class="test",
        root_stage="unit-test",
    ))
    assert results[0].incident.regression_detected is True
    assert agent.summarize(results)["successful_matches"] == 0


def test_empty_memory_returns_safe_summary():
    agent = FailureMemoryAgent(InMemoryIncidentStore())
    assert agent.retrieve(MemoryQuery("unknown error", "unknown", "unknown")) == ()
    assert agent.summarize(()) == {
        "matches": 0,
        "successful_matches": 0,
        "mean_similarity": 0.0,
        "mean_retries": 0.0,
        "mean_cost_usd": 0.0,
    }
