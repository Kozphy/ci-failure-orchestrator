"""Phase 13 — observability / SLI / SLO tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ci_failure_orchestrator.foundation import (
    AgentExecutionFoundation,
    FailureEvent,
    RunStatus,
    ScriptedProposalFactory,
)
from ci_failure_orchestrator.foundation.models import new_id
from ci_failure_orchestrator.foundation.observability.aggregator import (
    build_metrics_from_runs,
    build_snapshot,
)
from ci_failure_orchestrator.foundation.observability.metrics import (
    FORBIDDEN_LABEL_KEYS,
    InMemoryMetricsRecorder,
    SafeMetricsRecorder,
    sanitize_labels,
)
from ci_failure_orchestrator.foundation.observability.report import write_operations_report
from ci_failure_orchestrator.foundation.observability.sli import compute_slis
from ci_failure_orchestrator.foundation.observability.slo import (
    SLODefinition,
    SLOStatus,
    evaluate_error_budget,
    evaluate_slo,
    evaluate_slos,
)
from ci_failure_orchestrator.foundation.observability.stats import percentile, summarize_distribution
from ci_failure_orchestrator.foundation.observability.summary import RunMetricsSummary
from ci_failure_orchestrator.foundation.retry import RetryBudget


def _event(**kwargs) -> FailureEvent:
    base = dict(
        event_id=new_id("evt"),
        run_id=new_id("run"),
        source="synthetic",
        workflow="ci",
        job="test",
        failed_step="pytest",
        message="AssertionError: expected True",
        changed_paths=("src/app.py",),
        log_excerpt="FAILED tests/test_app.py::test_x",
        exit_code=1,
    )
    base.update(kwargs)
    return FailureEvent(**base)


def test_sanitize_labels_drops_run_id() -> None:
    clean = sanitize_labels({"run_id": "abc", "policy_outcome": "APPROVE", "bad": "x"})
    assert "run_id" not in clean
    assert clean["policy_outcome"] == "APPROVE"
    assert "run_id" in FORBIDDEN_LABEL_KEYS


def test_inmemory_counter_observe_gauge() -> None:
    m = InMemoryMetricsRecorder()
    m.increment("orchestrator_runs_total", labels={"source": "runtime"})
    m.observe("orchestrator_run_duration_seconds", 1.5, labels={"source": "runtime"})
    m.gauge("orchestrator_audit_completeness", 1.0, labels={"source": "runtime"})
    snap = m.snapshot()
    assert m.counter_total("orchestrator_runs_total") == 1
    assert snap["observations"]["orchestrator_run_duration_seconds"]


def test_safe_metrics_isolates_backend_failure() -> None:
    class Boom:
        def increment(self, metric, value=1, labels=None):
            raise RuntimeError("boom")

        def observe(self, metric, value, labels=None):
            raise RuntimeError("boom")

        def gauge(self, metric, value, labels=None):
            raise RuntimeError("boom")

    safe = SafeMetricsRecorder(Boom())
    safe.increment("x")
    safe.observe("y", 1.0)
    assert safe.failures >= 2


def test_percentile_nearest_rank() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(vals, 50) == 3.0
    assert percentile(vals, 95) == 5.0
    assert percentile([], 50) is None
    d = summarize_distribution(vals)
    assert d.count == 5 and d.median == 3.0 and d.p95 == 5.0


def test_error_budget_formula() -> None:
    # target 99%, 1000 obs, 5 bad => allowed 10, remaining 5
    budget = evaluate_error_budget(target=0.99, numerator=995, denominator=1000)
    assert budget is not None
    assert budget.allowed_bad_events == pytest.approx(10.0)
    assert budget.observed_bad_events == pytest.approx(5.0)
    assert budget.remaining_budget == pytest.approx(5.0)


def test_slo_met_missed_insufficient() -> None:
    from ci_failure_orchestrator.foundation.observability.sli import SLIResult

    sli_ok = SLIResult("SLI-005", "x", 10, 10, 1.0, False)
    sli_bad = SLIResult("SLI-008", "y", 90, 100, 0.9, False)
    sli_empty = SLIResult("SLI-007", "z", 0, 0, None, True)
    slo = SLODefinition("SLO-001", "SLI-005", 1.0, minimum_samples=1)
    assert evaluate_slo(slo, sli_ok).status is SLOStatus.MET
    assert evaluate_slo(
        SLODefinition("SLO-002", "SLI-008", 0.99, minimum_samples=1), sli_bad
    ).status is SLOStatus.MISSED
    assert evaluate_slo(
        SLODefinition("SLO-004", "SLI-007", 1.0, minimum_samples=1), sli_empty
    ).status is SLOStatus.INSUFFICIENT_DATA


def test_sli_zero_denominator() -> None:
    results = compute_slis([])
    by_id = {r.sli_id: r for r in results}
    assert by_id["SLI-001"].denominator == 0
    assert by_id["SLI-001"].value is None
    assert by_id["SLI-001"].insufficient_data


def test_approved_run_metrics(tmp_path: Path) -> None:
    metrics = InMemoryMetricsRecorder()
    agent = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        metrics=metrics,
        metrics_source="runtime",
        proposal_factory=ScriptedProposalFactory(
            ["--- a/src/app.py\n+++ b/src/app.py\n@@\n+# fix\n"]
        ),
        target_pass_schedule=(True,),
        retry_budget=RetryBudget(max_attempts=2),
    )
    result = agent.run(_event())
    assert result.status is RunStatus.APPROVED
    assert metrics.counter_total("orchestrator_runs_total") == 1
    assert metrics.counter_total("orchestrator_runs_succeeded_total") == 1
    assert metrics.counter_total("orchestrator_attempts_total") == 1
    assert metrics.counter_total("orchestrator_policy_decisions_total") == 1
    summary_path = tmp_path / "runs" / result.run.run_id / "metrics-summary.json"
    assert summary_path.is_file()


def test_retry_metrics(tmp_path: Path) -> None:
    metrics = InMemoryMetricsRecorder()
    agent = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        metrics=metrics,
        proposal_factory=ScriptedProposalFactory(
            [
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#1\n",
                "--- a/src/app.py\n+++ b/src/app.py\n@@\n+#2\n",
            ]
        ),
        target_pass_schedule=(False, True),
        retry_budget=RetryBudget(max_attempts=3),
    )
    result = agent.run(_event())
    assert result.attempts == 2
    assert result.retries == 1
    assert metrics.counter_total("orchestrator_retries_total") == 1
    assert metrics.counter_total("orchestrator_runs_with_retry_total") == 1


def test_escalation_metrics(tmp_path: Path) -> None:
    from ci_failure_orchestrator.foundation.models import RepairProposal

    metrics = InMemoryMetricsRecorder()
    agent = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        metrics=metrics,
        proposal_factory=ScriptedProposalFactory(
            [
                RepairProposal(
                    proposal_id=new_id("prop"),
                    run_id="r",
                    files_changed=("auth/permissions.py",),
                    patch="--- a/auth/permissions.py\n+++ b/auth/permissions.py\n@@\n+#x\n",
                    rationale="r",
                    expected_effect="e",
                    verification_plan=("target_verification",),
                )
            ]
        ),
        target_pass_schedule=(True,),
    )
    result = agent.run(_event(changed_paths=("auth/permissions.py",)))
    assert result.status is RunStatus.AWAITING_HUMAN
    assert metrics.counter_total("orchestrator_runs_escalated_total") == 1
    assert metrics.counter_total("orchestrator_escalations_total") == 1


def test_security_block_metrics(tmp_path: Path) -> None:
    metrics = InMemoryMetricsRecorder()
    agent = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        metrics=metrics,
        force_forbidden_path=True,
        retry_budget=RetryBudget(max_attempts=2),
    )
    result = agent.run(_event())
    assert result.technical_status == "FAIL"
    assert metrics.counter_total("orchestrator_security_findings_total") >= 1
    assert metrics.counter_total("orchestrator_security_blocks_total") >= 1


def test_rebuild_from_artifacts(tmp_path: Path) -> None:
    metrics = InMemoryMetricsRecorder()
    agent = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        metrics=metrics,
        proposal_factory=ScriptedProposalFactory(
            ["--- a/src/app.py\n+++ b/src/app.py\n@@\n+# fix\n"]
        ),
        target_pass_schedule=(True,),
    )
    agent.run(_event())
    summaries, rebuilt, issues = build_metrics_from_runs(tmp_path, source="runtime")
    assert len(summaries) == 1
    assert rebuilt.counter_total("orchestrator_runs_total") == 1
    snap = build_snapshot(tmp_path, source="runtime")
    assert snap.run_count == 1
    paths = write_operations_report(snap, tmp_path / "observability")
    assert paths["report"].is_file()
    assert "Operational Observability Report" in paths["report"].read_text(encoding="utf-8")


def test_benchmark_source_separated(tmp_path: Path) -> None:
    metrics = InMemoryMetricsRecorder()
    agent = AgentExecutionFoundation(
        artifacts_root=tmp_path,
        metrics=metrics,
        metrics_source="benchmark",
        proposal_factory=ScriptedProposalFactory(
            ["--- a/src/app.py\n+++ b/src/app.py\n@@\n+# fix\n"]
        ),
        target_pass_schedule=(True,),
    )
    agent.run(_event())
    runtime = build_metrics_from_runs(tmp_path, source="runtime")[0]
    bench = build_metrics_from_runs(tmp_path, source="benchmark")[0]
    assert len(runtime) == 0
    assert len(bench) == 1


def test_sli_from_summaries() -> None:
    summaries = [
        RunMetricsSummary(
            schema_version="foundation.observability.v1",
            run_id="a",
            source="runtime",
            technical_status="PASS",
            workflow_status="APPROVED",
            policy_outcome="APPROVE",
            failure_category="test_failure",
            attempts=1,
            retries=0,
            stop_reason="SUCCESS",
            duration_seconds=1.2,
            tool_calls=1,
            tool_failures=0,
            sandbox_runs=1,
            sandbox_failures=0,
            evaluations=1,
            evaluation_failures=0,
            security_findings=0,
            security_blocks=0,
            secret_redactions=0,
            escalated=False,
            evidence_status=None,
            audit_complete=True,
            persistence_ok=True,
            eligible_repair=True,
        ),
        RunMetricsSummary(
            schema_version="foundation.observability.v1",
            run_id="b",
            source="runtime",
            technical_status="PASS",
            workflow_status="AWAITING_HUMAN",
            policy_outcome="ESCALATE",
            failure_category="test_failure",
            attempts=2,
            retries=1,
            stop_reason="SUCCESS",
            duration_seconds=2.0,
            tool_calls=2,
            tool_failures=0,
            sandbox_runs=2,
            sandbox_failures=0,
            evaluations=2,
            evaluation_failures=1,
            security_findings=0,
            security_blocks=0,
            secret_redactions=0,
            escalated=True,
            evidence_status="COMPLETE",
            audit_complete=True,
            persistence_ok=True,
            eligible_repair=True,
        ),
    ]
    slis = {s.sli_id: s for s in compute_slis(summaries)}
    assert slis["SLI-001"].numerator == 2
    assert slis["SLI-004"].numerator == 1
    assert slis["SLI-005"].numerator == 1
    assert slis["SLI-008"].value == 1.0
    slos = evaluate_slos(
        [
            SLODefinition("SLO-001", "SLI-005", 1.0, minimum_samples=1),
            SLODefinition("SLO-002", "SLI-008", 0.99, minimum_samples=1),
        ],
        list(slis.values()),
    )
    assert all(s.status is SLOStatus.MET for s in slos)
