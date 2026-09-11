from __future__ import annotations

import json
from pathlib import Path

from ci_failure_orchestrator.langgraph_adapters import (
    JsonlDeadLetterSink,
    draft_pr_gate_hook,
    provider_patch_hook,
    verification_passthrough_hook,
)
from ci_failure_orchestrator.provider_adapters import ProviderRun, ProviderSpec


class FakeRunner:
    def run(self, spec, *, prompt, repo_path=None, extra_env=None):
        return ProviderRun(
            provider=spec.name,
            returncode=0,
            stdout="""analysis\ndiff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n""",
            stderr="",
            latency_ms=12.5,
            command=spec.argv,
            sandbox="fake",
        )


def test_provider_patch_hook_extracts_serializable_patch() -> None:
    hook = provider_patch_hook(
        FakeRunner(),
        ProviderSpec(name="codex", argv=("codex", "exec")),
    )

    result = hook(
        {
            "failure_class": "TEST_ASSERTION",
            "diagnosis": "failing assertion",
            "failure_message": "expected 1 got 2",
            "repo_path": "/tmp/repo",
        }
    )

    assert result["provider"] == "codex"
    assert result["provider_returncode"] == 0
    assert result["patch"].startswith("diff --git")
    assert result["provider_command"] == ["codex", "exec"]


def test_draft_pr_gate_fails_closed_without_verification() -> None:
    result = draft_pr_gate_hook(
        {
            "sandbox_passed": False,
            "regression_free": False,
            "verification_score": 0.2,
        }
    )

    assert result["draft_pr_allowed"] is False
    assert "sandbox_not_passed" in result["delivery_gate_reasons"]
    assert "regression_detected" in result["delivery_gate_reasons"]


def test_draft_pr_gate_allows_verified_candidate() -> None:
    result = draft_pr_gate_hook(
        {
            "sandbox_passed": True,
            "regression_free": True,
            "verification_score": 0.97,
            "dead_lettered": False,
        }
    )

    assert result == {"draft_pr_allowed": True, "delivery_gate_reasons": []}


def test_verification_passthrough_is_deterministic() -> None:
    result = verification_passthrough_hook(
        {"verification_score": 0.91, "regression_free": True}
    )
    assert result == {"verification_score": 0.91, "regression_free": True}


def test_jsonl_dead_letter_sink_persists_bounded_metadata(tmp_path: Path) -> None:
    target = tmp_path / "dlq" / "events.jsonl"
    sink = JsonlDeadLetterSink(target)

    result = sink.hook(
        {
            "run_id": "run-1",
            "repository": "org/repo",
            "failure_class": "NETWORK_ERROR",
            "retry_count": 3,
            "ai_calls": 5,
            "ai_cost_usd": 0.42,
            "reason": "budget exhausted",
            "provider_stdout": "SECRET SHOULD NOT BE PERSISTED",
            "patch": "SECRET PATCH",
        }
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["reason"] == "budget exhausted"
    assert "provider_stdout" not in payload
    assert "patch" not in payload
    assert result["dead_letter_reason"] == "budget exhausted"
