import json
from pathlib import Path

from ci_failure_orchestrator.merge_conflict_benchmark import (
    evaluate_merge_conflict_case,
    summarize_merge_conflict_results,
)


def _corpus():
    return json.loads(Path("benchmark/merge_conflict_corpus.v1.json").read_text(encoding="utf-8"))


def test_deterministic_cases_resolve_and_semantic_cases_escalate():
    results = [evaluate_merge_conflict_case(case) for case in _corpus()["cases"]]
    by_id = {result.case_id: result for result in results}

    assert by_id["identical-sides"].resolved is True
    assert by_id["one-sided-addition"].resolved is True
    assert by_id["strict-superset"].resolved is True
    assert by_id["semantic-policy"].escalated is True
    assert by_id["semantic-implementation"].escalated is True


def test_summary_reports_fail_closed_semantic_behavior():
    results = [evaluate_merge_conflict_case(case) for case in _corpus()["cases"]]
    metrics = summarize_merge_conflict_results(results)

    assert metrics.cases == 5
    assert metrics.auto_resolution_rate == 0.6
    assert metrics.escalation_rate == 0.4
    assert metrics.semantic_escalation_precision == 1.0
    assert metrics.unsafe_output_rate == 0.0
