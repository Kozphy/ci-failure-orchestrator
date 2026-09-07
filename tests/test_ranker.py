from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.models import Failure, Stage
from ci_failure_orchestrator.ranker import RootCauseRanker


def test_upstream_causal_failure_ranks_first():
    graph = PipelineGraph([
        Stage("build"),
        Stage("typecheck", ("build",)),
        Stage("test", ("typecheck",)),
        Stage("deploy", ("test",)),
    ])
    failures = [
        Failure("typecheck", "TYPE_ERROR", confidence=0.95),
        Failure("test", "TEST_ASSERTION", confidence=0.7),
        Failure("deploy", "DEPLOYMENT_ERROR", severity=1.0, confidence=0.4),
    ]
    ranked = RootCauseRanker(graph).rank(failures)
    assert ranked[0].failure.stage == "typecheck"
