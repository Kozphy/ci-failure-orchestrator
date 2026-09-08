from ci_failure_orchestrator.live_semantic_merge_eval import (
    run_live_semantic_case,
    summarize_live_semantic_runs,
)
from ci_failure_orchestrator.merge_conflict_agent import SemanticResolution


class FakeProvider:
    def __init__(self, text: str, confidence: float = 0.95):
        self.text = text
        self.confidence = confidence
        self.last_latency_seconds = 0.25
        self.last_input_tokens = 100
        self.last_output_tokens = 25

    def resolve_conflict(self, **kwargs):
        return SemanticResolution(self.text, self.confidence, "test")


def _case():
    return {
        "id": "case",
        "path": "policy.py",
        "ours": "return BLOCK\n",
        "theirs": "audit()\nreturn BLOCK\n",
        "required_fragments": ["audit()", "return BLOCK"],
        "forbidden_fragments": ["return RELEASE"],
    }


def test_verified_live_semantic_run_records_provider_telemetry():
    run = run_live_semantic_case(
        _case(),
        FakeProvider("audit()\nreturn BLOCK\n"),
        trial=1,
    )
    assert run.accepted is True
    assert run.verified is True
    assert run.input_tokens == 100
    assert run.output_tokens == 25


def test_low_confidence_or_unsafe_output_escalates():
    low = run_live_semantic_case(_case(), FakeProvider("audit()\nreturn BLOCK\n", 0.4), trial=1)
    unsafe = run_live_semantic_case(_case(), FakeProvider("return RELEASE\n"), trial=2)
    assert low.accepted is False
    assert unsafe.unsafe is True
    metrics = summarize_live_semantic_runs([low, unsafe])
    assert metrics.escalation_rate == 1.0
    assert metrics.unsafe_resolution_rate == 0.5
    assert metrics.total_tokens == 250
