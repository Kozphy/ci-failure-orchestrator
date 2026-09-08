from pathlib import Path
import sys

from ci_failure_orchestrator.execution import IsolatedWorkspace
from ci_failure_orchestrator.test_selection import AffectedTestSelector, TestRule
from ci_failure_orchestrator.telemetry import MetricsRegistry, Timer


def test_isolated_workspace_does_not_modify_source(tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "value.txt").write_text("original", encoding="utf-8")

    with IsolatedWorkspace(source) as workspace:
        assert workspace.path is not None
        result = workspace.run([
            sys.executable,
            "-c",
            "from pathlib import Path; Path('value.txt').write_text('patched')",
        ])
        assert result.returncode == 0
        assert (workspace.path / "value.txt").read_text(encoding="utf-8") == "patched"

    assert (source / "value.txt").read_text(encoding="utf-8") == "original"


def test_affected_test_selector_uses_rules_and_safe_fallback():
    selector = AffectedTestSelector([
        TestRule("ci_failure_orchestrator/*.py", ("tests/unit", "tests/control")),
        TestRule("docs/*", ("tests/docs",)),
    ])
    assert selector.select(["ci_failure_orchestrator/policy.py"]) == ("tests/control", "tests/unit")
    assert selector.select(["README.md"]) == ("tests",)


def test_metrics_registry_records_counts_and_latency():
    registry = MetricsRegistry()
    registry.inc("repair_attempts")
    with Timer(registry, "repair_latency_ms"):
        pass
    assert registry.counters["repair_attempts"] == 1
    assert len(registry.observations["repair_latency_ms"]) == 1
    assert registry.observations["repair_latency_ms"][0] >= 0
