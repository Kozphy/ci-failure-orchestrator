from scripts.sandbox_repair import validate_scope


def test_accepts_small_source_only_change():
    accepted, reason = validate_scope(("ci_failure_orchestrator/classifier.py",), 40)
    assert accepted is True
    assert "bounded scope" in reason


def test_rejects_workflow_mutation():
    accepted, reason = validate_scope((".github/workflows/ci.yml",), 20)
    assert accepted is False
    assert "protected paths" in reason


def test_rejects_too_many_changed_files():
    files = tuple(f"src/file_{i}.py" for i in range(6))
    accepted, reason = validate_scope(files, 60)
    assert accepted is False
    assert "limit" in reason


def test_rejects_oversized_patch():
    accepted, reason = validate_scope(("src/app.py",), 501)
    assert accepted is False
    assert "diff" in reason
