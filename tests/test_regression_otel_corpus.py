from pathlib import Path
import sys

from ci_failure_orchestrator.execution import IsolatedWorkspace
from ci_failure_orchestrator.regression_gate import MandatoryRegressionGate
from ci_failure_orchestrator.otel import SpanExporter
from ci_failure_orchestrator.corpus import FailureCorpus


def test_full_regression_gate_is_mandatory(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()
    with IsolatedWorkspace(source) as workspace:
        gate = MandatoryRegressionGate([sys.executable, "-c", "raise SystemExit(0)"])
        result = gate.verify(
            workspace,
            targeted_command=[sys.executable, "-c", "raise SystemExit(0)"],
        )
        assert result.targeted_passed is True
        assert result.full_suite_passed is True
        assert result.releasable is True


def test_targeted_failure_can_never_release(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()
    with IsolatedWorkspace(source) as workspace:
        gate = MandatoryRegressionGate([sys.executable, "-c", "raise SystemExit(0)"])
        result = gate.verify(
            workspace,
            targeted_command=[sys.executable, "-c", "raise SystemExit(1)"],
        )
        assert result.releasable is False


def test_span_exporter_emits_structured_record():
    records = []
    exporter = SpanExporter(records.append)
    with exporter.start("repair.verify", provider="github-actions") as span:
        span.set_attribute("result", "pass")
    assert records[0]["name"] == "repair.verify"
    assert records[0]["status"] == "ok"
    assert records[0]["attributes"]["result"] == "pass"


def test_failure_corpus_is_replayable():
    cases = FailureCorpus.load("benchmarks/corpus/v0.1.jsonl")
    assert len(cases) >= 5
    assert {case.failure_class for case in cases} >= {"DEPENDENCY_ERROR", "SECURITY_ERROR"}
