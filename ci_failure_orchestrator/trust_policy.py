from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from .trust import TrustContext


class TrustDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"


@dataclass(frozen=True)
class PolicyResult:
    decision: TrustDecision
    rule_id: str
    reason: str
    severity: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["decision"] = self.decision.value
        return value


class TrustPolicyEngine:
    def __init__(self, rules: list[dict[str, Any]], settings: dict[str, Any] | None = None) -> None:
        self.rules = rules
        self.settings = settings or {}

    @classmethod
    def from_file(cls, path: str | Path) -> TrustPolicyEngine:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        rules = raw.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ValueError("policy configuration must contain ordered rules")
        return cls(rules, raw.get("settings"))

    def evaluate(self, context: TrustContext) -> PolicyResult:
        facts = {
            "provider_known": context.provider_known,
            "classification": context.data_classification.value,
            "external_provider": context.external_provider,
            "data_leaves_host": context.data_leaves_host,
            "operation": context.requested_operation,
            "destructive": context.destructive,
            "network_ready": context.network_ready,
            "jurisdictions": context.jurisdictions,
            "data_residency": context.data_residency,
            "destination_country": context.destination_country,
            "residency_aligned": (
                context.destination_country == context.data_residency
                if context.destination_country is not None and context.data_residency is not None
                else None
            ),
        }
        for rule in self.rules:
            conditions = rule.get("when", {})
            if self._matches(facts, conditions):
                configured = rule.get("decision")
                if configured is None:
                    setting_name = rule.get("decision_from_setting")
                    configured = self.settings.get(setting_name) if isinstance(setting_name, str) else None
                if configured is None:
                    raise ValueError(f"policy rule has no decision: {rule.get('id')}")
                decision = TrustDecision(configured)
                if decision is TrustDecision.REQUIRE_APPROVAL and context.human_approved:
                    return PolicyResult(
                        TrustDecision.ALLOW,
                        f"{rule['id']}_APPROVED",
                        "Human approval satisfies the protected policy decision.",
                        rule.get("severity", "medium"),
                        {**facts, "approval_for_rule": rule["id"], "human_approved": True},
                    )
                return PolicyResult(
                    decision,
                    rule["id"],
                    rule["reason"],
                    rule.get("severity", "medium"),
                    facts,
                )
        raise RuntimeError("policy configuration has no matching default rule")

    @staticmethod
    def _matches(facts: dict[str, Any], conditions: dict[str, Any]) -> bool:
        for key, expected in conditions.items():
            if key.endswith("_in"):
                if facts.get(key[:-3]) not in expected:
                    return False
            elif facts.get(key) != expected:
                return False
        return True
