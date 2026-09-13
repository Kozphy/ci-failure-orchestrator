from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class DataClassification(str, Enum):
    UNKNOWN = "UNKNOWN"
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"

    @classmethod
    def parse(cls, value: str | None) -> DataClassification:
        if value is None or not value.strip():
            return cls.UNKNOWN
        try:
            return cls(value.strip().upper())
        except ValueError as exc:
            raise ValueError(f"unsupported data classification: {value}") from exc


@dataclass(frozen=True)
class ProviderMetadata:
    provider: str
    company: str | None
    service_type: str | None
    jurisdictions: tuple[str, ...]
    data_residency_configurable: bool | None
    external_provider: bool | None
    data_leaves_host: bool | None
    known_endpoints: tuple[str, ...]
    known: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProviderRegistry:
    def __init__(self, providers: dict[str, ProviderMetadata]) -> None:
        self._providers = providers

    @classmethod
    def from_file(cls, path: str | Path) -> ProviderRegistry:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        configured = raw.get("providers")
        if not isinstance(configured, dict):
            raise TypeError("provider registry must contain a providers object")
        providers: dict[str, ProviderMetadata] = {}
        for name, value in configured.items():
            if not isinstance(value, dict):
                raise TypeError(f"provider metadata must be an object: {name}")
            jurisdictions = value.get("jurisdictions", ())
            endpoints = value.get("known_endpoints", ())
            if not isinstance(jurisdictions, list) or not all(isinstance(item, str) for item in jurisdictions):
                raise TypeError(f"provider jurisdictions must be a string list: {name}")
            if not isinstance(endpoints, list) or not all(isinstance(item, str) for item in endpoints):
                raise TypeError(f"provider endpoints must be a string list: {name}")
            for field_name in ("data_residency_configurable", "external_provider", "data_leaves_host"):
                if value.get(field_name) is not None and not isinstance(value[field_name], bool):
                    raise TypeError(f"provider {field_name} must be boolean or null: {name}")
            providers[name] = ProviderMetadata(
                provider=name,
                company=value.get("company"),
                service_type=value.get("service_type"),
                jurisdictions=tuple(jurisdictions),
                data_residency_configurable=value.get("data_residency_configurable"),
                external_provider=value.get("external_provider"),
                data_leaves_host=value.get("data_leaves_host"),
                known_endpoints=tuple(endpoints),
            )
        return cls(providers)

    def resolve(self, name: str) -> ProviderMetadata:
        return self._providers.get(
            name,
            ProviderMetadata(name, None, None, (), None, None, None, (), known=False),
        )


@dataclass(frozen=True)
class TrustContext:
    provider: str
    provider_type: str | None
    provider_known: bool
    jurisdictions: tuple[str, ...]
    data_residency: str | None
    data_classification: DataClassification
    destination_host: str | None
    destination_country: str | None
    external_provider: bool | None
    data_leaves_host: bool | None
    network_capabilities: dict[str, Any]
    dependency_provenance: dict[str, Any]
    requested_tool: str
    requested_operation: str
    destructive: bool
    human_approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["data_classification"] = self.data_classification.value
        return result

    @property
    def network_ready(self) -> bool:
        if self.external_provider is False:
            return True
        if self.external_provider is not True:
            return False
        required = ("dns", "tcp", "tls", "http")
        return all(self.network_capabilities.get(name) == "pass" for name in required)


@dataclass(frozen=True)
class ContextRequest:
    provider: str
    tool: str
    operation: str
    data_classification: str | None = None
    data_residency: str | None = None
    destination_host: str | None = None
    destination_country: str | None = None
    destructive: bool = False
    package_name: str | None = None
    human_approved: bool = False


@dataclass
class TrustContextBuilder:
    registry: ProviderRegistry
    network_discovery: Any
    provenance_evaluator: Any

    DESTRUCTIVE_OPERATIONS = frozenset({"delete", "destroy", "drop", "force_push", "terminate"})

    def build(self, request: ContextRequest) -> TrustContext:
        if not request.provider.strip() or not request.tool.strip() or not request.operation.strip():
            raise ValueError("provider, tool, and operation are required")
        provider = self.registry.resolve(request.provider)
        destination = request.destination_host
        if destination is None and len(provider.known_endpoints) == 1:
            destination = provider.known_endpoints[0]
        network = self.network_discovery.discover(destination) if destination else {"status": "unknown"}
        provenance = self.provenance_evaluator.evaluate(request.package_name or request.tool)
        return TrustContext(
            provider=request.provider,
            provider_type=provider.service_type,
            provider_known=provider.known,
            jurisdictions=provider.jurisdictions,
            data_residency=request.data_residency,
            data_classification=DataClassification.parse(request.data_classification),
            destination_host=destination,
            destination_country=request.destination_country,
            external_provider=provider.external_provider,
            data_leaves_host=provider.data_leaves_host,
            network_capabilities=network,
            dependency_provenance=provenance,
            requested_tool=request.tool,
            requested_operation=request.operation.lower(),
            destructive=request.destructive or request.operation.lower() in self.DESTRUCTIVE_OPERATIONS,
            human_approved=request.human_approved,
        )
