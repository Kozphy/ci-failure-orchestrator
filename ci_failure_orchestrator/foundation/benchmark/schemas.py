"""Typed models for the Phase 12 foundation benchmark suite."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

BENCHMARK_SCHEMA_VERSION = "foundation.benchmark.v1"
SUITE_VERSION = "1.0.0"


class BenchmarkCategory(str, Enum):
    CLASSIFICATION = "CLASSIFICATION"
    REPAIR = "REPAIR"
    RETRY = "RETRY"
    POLICY = "POLICY"
    SECURITY = "SECURITY"
    ESCALATION = "ESCALATION"
    AUDIT = "AUDIT"
    RECOVERY = "RECOVERY"
    END_TO_END = "END_TO_END"


class BenchmarkTier(str, Enum):
    TIER1_DETERMINISTIC = "tier1"
    TIER2_INTEGRATION = "tier2"
    TIER3_MODEL = "tier3"


class BenchmarkMode(str, Enum):
    ORCHESTRATOR = "orchestrator"
    CLASSIFY = "classify"
    TOOL = "tool"
    RECOVERY = "recovery"


@dataclass(frozen=True)
class FailureInjectionSpec:
    """TEST/BENCHMARK ONLY — never activate outside benchmark_mode."""

    target: str  # sandbox | evaluator | persistence_state | persistence_audit | tool
    failure: str  # timeout | error | setup_failure | patch_failure | eval_failure | append_failure
    occurrence: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> FailureInjectionSpec | None:
        if not data:
            return None
        return cls(
            target=str(data["target"]),
            failure=str(data["failure"]),
            occurrence=int(data.get("occurrence", 1)),
        )


@dataclass(frozen=True)
class ExpectedResult:
    """Declarative golden expectations (serializable)."""

    classification: str | None = None
    technical_status: str | None = None  # PASS | FAIL
    attempts: int | None = None
    retries: int | None = None
    stop_reason: str | None = None
    policy_outcome: str | None = None  # APPROVE | REJECT | ESCALATE
    workflow_status: str | None = None
    progress_detected: bool | None = None
    duplicate_proposal: bool | None = None
    expected_tool_names: tuple[str, ...] = ()
    forbidden_tool_names: tuple[str, ...] = ()
    expected_security_signals: tuple[str, ...] = ()
    escalation_required: bool | None = None
    escalation_fields: tuple[str, ...] = ()
    audit_completeness: bool | None = None
    artifacts_exist: tuple[str, ...] = ()
    secrets_absent: tuple[str, ...] = ()
    outside_path_absent: str | None = None
    recovery_status: str | None = None
    tool_blocked: bool | None = None
    no_subprocess: bool | None = None
    # Metric populations this case contributes to
    populations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExpectedResult:
        data = data or {}
        return cls(
            classification=data.get("classification"),
            technical_status=data.get("technical_status"),
            attempts=data.get("attempts"),
            retries=data.get("retries"),
            stop_reason=data.get("stop_reason"),
            policy_outcome=data.get("policy_outcome"),
            workflow_status=data.get("workflow_status"),
            progress_detected=data.get("progress_detected"),
            duplicate_proposal=data.get("duplicate_proposal"),
            expected_tool_names=tuple(data.get("expected_tool_names") or ()),
            forbidden_tool_names=tuple(data.get("forbidden_tool_names") or ()),
            expected_security_signals=tuple(data.get("expected_security_signals") or ()),
            escalation_required=data.get("escalation_required"),
            escalation_fields=tuple(data.get("escalation_fields") or ()),
            audit_completeness=data.get("audit_completeness"),
            artifacts_exist=tuple(data.get("artifacts_exist") or ()),
            secrets_absent=tuple(data.get("secrets_absent") or ()),
            outside_path_absent=data.get("outside_path_absent"),
            recovery_status=data.get("recovery_status"),
            tool_blocked=data.get("tool_blocked"),
            no_subprocess=data.get("no_subprocess"),
            populations=tuple(data.get("populations") or ()),
        )


@dataclass(frozen=True)
class CaseFixture:
    event: dict[str, Any] = field(default_factory=dict)
    workspace_files: dict[str, str] = field(default_factory=dict)
    proposals: tuple[dict[str, Any], ...] = ()
    target_pass_schedule: tuple[bool, ...] | None = None
    max_attempts: int = 3
    max_identical_proposals: int | None = None
    max_identical_failures: int | None = None
    max_no_progress_attempts: int | None = None
    enable_persistence: bool = True
    force_forbidden_path: bool = False
    force_target_fail: bool = False
    injection: FailureInjectionSpec | None = None
    # tool mode
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    # recovery mode
    seed_workflow_status: str | None = None
    seed_with_escalation: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> CaseFixture:
        data = data or {}
        schedule = data.get("target_pass_schedule")
        return cls(
            event=dict(data.get("event") or {}),
            workspace_files=dict(data.get("workspace_files") or {}),
            proposals=tuple(data.get("proposals") or ()),
            target_pass_schedule=tuple(schedule) if schedule is not None else None,
            max_attempts=int(data.get("max_attempts", 3)),
            max_identical_proposals=(
                int(data["max_identical_proposals"])
                if data.get("max_identical_proposals") is not None
                else None
            ),
            max_identical_failures=(
                int(data["max_identical_failures"])
                if data.get("max_identical_failures") is not None
                else None
            ),
            max_no_progress_attempts=(
                int(data["max_no_progress_attempts"])
                if data.get("max_no_progress_attempts") is not None
                else None
            ),
            enable_persistence=bool(data.get("enable_persistence", True)),
            force_forbidden_path=bool(data.get("force_forbidden_path", False)),
            force_target_fail=bool(data.get("force_target_fail", False)),
            injection=FailureInjectionSpec.from_dict(data.get("injection")),
            tool_name=data.get("tool_name"),
            tool_arguments=dict(data.get("tool_arguments") or {}),
            seed_workflow_status=data.get("seed_workflow_status"),
            seed_with_escalation=bool(data.get("seed_with_escalation", False)),
        )


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    version: int
    title: str
    description: str
    category: str
    fixture: CaseFixture
    expected: ExpectedResult
    tags: tuple[str, ...] = ()
    required: bool = True
    tier: str = BenchmarkTier.TIER1_DETERMINISTIC.value
    mode: str = BenchmarkMode.ORCHESTRATOR.value
    rationale: str = ""
    synthetic: bool = True
    source: str = "synthetic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
            "required": self.required,
            "tier": self.tier,
            "mode": self.mode,
            "rationale": self.rationale,
            "synthetic": self.synthetic,
            "source": self.source,
            "fixture": {
                "event": self.fixture.event,
                "workspace_files": self.fixture.workspace_files,
                "proposals": list(self.fixture.proposals),
                "target_pass_schedule": (
                    list(self.fixture.target_pass_schedule)
                    if self.fixture.target_pass_schedule is not None
                    else None
                ),
                "max_attempts": self.fixture.max_attempts,
                "enable_persistence": self.fixture.enable_persistence,
                "force_forbidden_path": self.fixture.force_forbidden_path,
                "injection": (
                    self.fixture.injection.to_dict() if self.fixture.injection else None
                ),
                "tool_name": self.fixture.tool_name,
                "tool_arguments": self.fixture.tool_arguments,
                "seed_workflow_status": self.fixture.seed_workflow_status,
                "seed_with_escalation": self.fixture.seed_with_escalation,
            },
            "expected": self.expected.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkCase:
        case_id = str(data.get("case_id") or "").strip()
        if not case_id:
            raise ValueError("BenchmarkCase requires stable case_id")
        return cls(
            case_id=case_id,
            version=int(data.get("version", 1)),
            title=str(data.get("title") or case_id),
            description=str(data.get("description") or ""),
            category=str(data.get("category") or "END_TO_END"),
            fixture=CaseFixture.from_dict(data.get("fixture")),
            expected=ExpectedResult.from_dict(data.get("expected")),
            tags=tuple(data.get("tags") or ()),
            required=bool(data.get("required", True)),
            tier=str(data.get("tier") or BenchmarkTier.TIER1_DETERMINISTIC.value),
            mode=str(data.get("mode") or BenchmarkMode.ORCHESTRATOR.value),
            rationale=str(data.get("rationale") or ""),
            synthetic=bool(data.get("synthetic", True)),
            source=str(data.get("source") or "synthetic"),
        )


@dataclass
class BenchmarkAssertionResult:
    name: str
    passed: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "expected": _safe_repr(self.expected),
            "actual": _safe_repr(self.actual),
            "detail": self.detail,
        }


@dataclass
class ObservedResult:
    """Normalized observation from a case execution."""

    run_id: str | None = None
    classification: str | None = None
    technical_status: str | None = None
    attempts: int | None = None
    retries: int | None = None
    stop_reason: str | None = None
    policy_outcome: str | None = None
    workflow_status: str | None = None
    progress_detected: bool | None = None
    duplicate_proposal: bool | None = None
    tools_used: tuple[str, ...] = ()
    security_signals: tuple[str, ...] = ()
    escalation_present: bool = False
    escalation_fields_present: tuple[str, ...] = ()
    audit_complete: bool | None = None
    artifacts_found: tuple[str, ...] = ()
    secrets_leaked: tuple[str, ...] = ()
    outside_path_exists: bool | None = None
    recovery_status: str | None = None
    tool_blocked: bool | None = None
    subprocess_created: bool | None = None
    artifact_refs: dict[str, str] = field(default_factory=dict)
    harness_error: str | None = None
    evidence_notes: list[str] = field(default_factory=list)


@dataclass
class BenchmarkCaseResult:
    case_id: str
    passed: bool
    duration_ms: float
    assertions: list[BenchmarkAssertionResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    run_id: str | None = None
    failure_reason: str | None = None
    harness_error: str | None = None
    required: bool = True
    category: str = ""
    tags: tuple[str, ...] = ()
    observed: dict[str, Any] = field(default_factory=dict)
    populations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "assertions": [a.to_dict() for a in self.assertions],
            "metrics": self.metrics,
            "run_id": self.run_id,
            "failure_reason": self.failure_reason,
            "harness_error": self.harness_error,
            "required": self.required,
            "category": self.category,
            "tags": list(self.tags),
            "observed": self.observed,
            "populations": list(self.populations),
        }


def _safe_repr(value: Any) -> Any:
    """Avoid echoing synthetic secrets in assertion dumps."""

    if value is None:
        return None
    text = str(value)
    if any(marker in text for marker in ("ghp_", "AKIA", "Bearer ", "password=")):
        return "[REDACTED_FOR_REPORT]"
    if isinstance(value, (str, int, float, bool, list, dict, type(None))):
        if isinstance(value, str) and len(value) > 200:
            return value[:200] + "…"
        return value
    return text[:200]
