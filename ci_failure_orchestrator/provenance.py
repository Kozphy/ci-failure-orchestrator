from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path
from typing import Any


class DependencyProvenanceEvaluator:
    """Collects locally available provenance without assigning a trust score."""

    LOCKFILES = ("pyproject.toml", "requirements.txt", "poetry.lock", "uv.lock", "Pipfile.lock")

    def __init__(self, workspace: str | Path = ".") -> None:
        self.workspace = Path(workspace)

    def evaluate(self, package_name: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "package_name": package_name,
            "version": None,
            "source": None,
            "repository": None,
            "license": None,
            "maintainer": None,
            "integrity": {},
            "lockfiles": [],
            "status": "unknown",
        }
        for filename in self.LOCKFILES:
            path = self.workspace / filename
            if path.is_file():
                result["lockfiles"].append(filename)
                result["integrity"][filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            distribution = metadata.distribution(package_name)
        except metadata.PackageNotFoundError:
            return result
        info = distribution.metadata

        def metadata_value(name: str) -> str | None:
            try:
                return info[name]
            except KeyError:
                return None

        direct_url = distribution.read_text("direct_url.json")
        source = "installed_distribution"
        if direct_url:
            try:
                source = json.loads(direct_url).get("url", source)
            except json.JSONDecodeError:
                source = "installed_distribution"
        record = distribution.read_text("RECORD")
        if record:
            result["integrity"]["installed_record_sha256"] = hashlib.sha256(record.encode()).hexdigest()

        result.update(
            version=distribution.version,
            source=source,
            repository=metadata_value("Project-URL"),
            license=metadata_value("License"),
            maintainer=metadata_value("Maintainer") or metadata_value("Author"),
            status="available",
        )
        return result
