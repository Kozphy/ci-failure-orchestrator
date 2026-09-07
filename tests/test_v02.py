from ci_failure_orchestrator.models import Stage, Failure
from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.causal import infer_causal_edges
from ci_failure_orchestrator.verification import plan_verification
from ci_failure_orchestrator.github_ingest import stages_from_jobs, failures_from_jobs


def test_causal_edges_and_verification():
    graph = PipelineGraph([Stage("typecheck"), Stage("unit", ("typecheck",)), Stage("deploy", ("unit",))])
    failures = [Failure("typecheck", "TYPE_ERROR", confidence=0.9), Failure("unit", "TEST_ASSERTION", confidence=0.8), Failure("deploy", "DEPLOYMENT_ERROR", confidence=0.7)]
    edges = infer_causal_edges(graph, failures)
    assert any(edge.source == "typecheck" and edge.target == "unit" for edge in edges)
    plan = plan_verification(graph, "typecheck", {"typecheck", "unit", "deploy"})
    assert [step.stage for step in plan] == ["typecheck", "unit", "deploy", "*"]


def test_github_ingest():
    jobs = [{"id": 1, "name": "typecheck", "conclusion": "failure", "needs": []}, {"id": 2, "name": "unit", "conclusion": "failure", "needs": ["typecheck"]}, {"id": 3, "name": "deploy", "conclusion": "success", "needs": ["unit"]}]
    stages = stages_from_jobs(jobs)
    assert stages[1].depends_on == ("typecheck",)
    failures = failures_from_jobs(jobs, {"typecheck": "mypy incompatible type", "unit": "AssertionError tests failed"})
    assert [failure.error_type for failure in failures] == ["TYPE_ERROR", "TEST_ASSERTION"]
