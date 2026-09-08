from ci_failure_orchestrator.benchmark_suite import BenchmarkResult
from ci_failure_orchestrator.canary import CanaryDecision, CanaryMetrics
from ci_failure_orchestrator.fleet import FleetManager, FleetState, RepositoryPolicy, RepositorySnapshot
from ci_failure_orchestrator.platform import CIRepairPlatform
from ci_failure_orchestrator.production_proof import ProofArtifact, build_production_proof
from ci_failure_orchestrator.slo import SLOObservation


def _benchmark_rows():
    return [
        BenchmarkResult("a", True, True, False, False, 1, 0.05, 1000, True, False),
        BenchmarkResult("b", True, True, False, False, 0, 0.04, 1200, True, False),
    ]


def test_v1_platform_promotes_healthy_canary():
    fleet = FleetManager()
    fleet.register(RepositoryPolicy("org/repo-a"))
    platform = CIRepairPlatform(fleet)

    report = platform.evaluate(
        repositories=[RepositorySnapshot("org/repo-a", open_failures=1)],
        benchmark_results=_benchmark_rows(),
        slo_observation=SLOObservation(
            total_runs=100,
            successful_runs=100,
            successful_repairs=95,
            attempted_repairs=100,
            false_repairs=1,
            p95_repair_latency_ms=10_000,
        ),
        canary_metrics=CanaryMetrics(
            sample_size=20,
            success_rate=0.95,
            regression_rate=0.0,
            false_repair_rate=0.0,
            p95_latency_ms=10_000,
        ),
    )

    assert report.fleet_state == FleetState.DEGRADED
    assert report.canary == CanaryDecision.PROMOTE
    assert report.dashboard.repositories_repairing == 1
    assert report.dashboard.slo_met is True


def test_v1_platform_freezes_on_bad_canary():
    fleet = FleetManager()
    fleet.register(RepositoryPolicy("org/repo-a"))
    platform = CIRepairPlatform(fleet)

    report = platform.evaluate(
        repositories=[RepositorySnapshot("org/repo-a", open_failures=1)],
        benchmark_results=_benchmark_rows(),
        slo_observation=SLOObservation(100, 100, 95, 100, 1, 10_000),
        canary_metrics=CanaryMetrics(20, 0.95, 0.20, 0.0, 10_000),
    )

    assert report.canary == CanaryDecision.ROLLBACK
    assert report.fleet_state == FleetState.FROZEN


def test_production_proof_has_stable_hash_shape():
    proof = build_production_proof(
        repository="org/repo-a",
        run_id="123",
        commit_sha="abc123",
        gate_decision="PASS",
        evaluator_score=0.98,
        regression_free=True,
        canary_decision="promote",
        slo_met=True,
        artifacts=[ProofArtifact("audit", "audit.jsonl", "deadbeef")],
    )

    assert len(proof.proof_hash) == 64
    assert proof.regression_free is True
    assert proof.artifacts[0].kind == "audit"
