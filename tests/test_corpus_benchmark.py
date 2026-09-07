import json
from pathlib import Path

from ci_failure_orchestrator.corpus_benchmark import evaluate_corpus


def load_corpus():
    return json.loads(Path("benchmark/ci_failure_corpus.v1.json").read_text(encoding="utf-8"))


def test_corpus_is_nonempty_and_versioned():
    corpus = load_corpus()
    assert corpus["version"] == "1.0"
    assert len(corpus["cases"]) >= 8
    assert len(corpus["stages"]) >= 5


def test_causal_ranker_beats_latest_visible_baseline_on_corpus():
    metrics = evaluate_corpus(load_corpus())
    assert metrics.cases >= 8
    assert 0.0 <= metrics.top1_accuracy <= 1.0
    assert 0.0 <= metrics.top3_accuracy <= 1.0
    assert metrics.top1_accuracy >= metrics.latest_visible_top1_accuracy
    assert metrics.causal_uplift_vs_latest_visible >= 0.0


def test_cascade_elimination_is_bounded():
    metrics = evaluate_corpus(load_corpus())
    assert 0.0 <= metrics.mean_cascade_elimination <= 1.0
