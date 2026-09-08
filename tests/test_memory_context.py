from ci_failure_orchestrator.failure_memory import FailureMemoryAgent, IncidentMemory, MemoryQuery
from ci_failure_orchestrator.memory_context import build_memory_context
from ci_failure_orchestrator.sqlite_memory import SQLiteIncidentStore


def test_sqlite_store_round_trip(tmp_path):
    db = tmp_path / "incidents.db"
    store = SQLiteIncidentStore(db)
    store.add(IncidentMemory(
        incident_id="i1",
        error_signature="mypy optional assignment",
        failure_class="type_check",
        root_stage="type-check",
        changed_files=("src/foo.py",),
        successful_patch_summary="guard optional before assignment",
        affected_tests=("tests/test_foo.py",),
    ))
    rows = tuple(SQLiteIncidentStore(db).all())
    assert rows[0].incident_id == "i1"
    assert rows[0].affected_tests == ("tests/test_foo.py",)


def test_memory_context_caps_historical_influence(tmp_path):
    store = SQLiteIncidentStore(tmp_path / "incidents.db")
    store.add(IncidentMemory(
        incident_id="good",
        error_signature="mypy optional assignment",
        failure_class="type_check",
        root_stage="type-check",
        changed_files=("src/foo.py",),
        successful_patch_summary="guard optional before assignment",
        affected_tests=("tests/test_foo.py",),
    ))
    store.add(IncidentMemory(
        incident_id="old-regression",
        error_signature="mypy optional assignment",
        failure_class="type_check",
        root_stage="type-check",
        successful_patch_summary="historical alternative",
        regression_detected=True,
    ))
    retrieved = FailureMemoryAgent(store).retrieve(MemoryQuery(
        error_signature="mypy optional assignment",
        failure_class="type_check",
        root_stage="type-check",
        changed_files=("src/foo.py",),
    ))
    context = build_memory_context(retrieved, max_adjustment=0.15)
    assert 0.0 < context.confidence_adjustment <= 0.15
    assert context.suggested_repairs == ("guard optional before assignment",)
    assert context.affected_tests == ("tests/test_foo.py",)
    assert context.warnings


def test_empty_memory_is_neutral():
    context = build_memory_context(())
    assert context.confidence_adjustment == 0.0
    assert context.evidence_count == 0
