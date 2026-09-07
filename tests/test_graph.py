from ci_failure_orchestrator.graph import PipelineGraph
from ci_failure_orchestrator.models import Stage


def test_depth_and_descendants():
    graph = PipelineGraph([
        Stage("build"),
        Stage("test", ("build",)),
        Stage("deploy", ("test",)),
    ])
    assert graph.depth("deploy") == 2
    assert graph.descendants("build") == {"test", "deploy"}
