"""Configuration loading for CI failure orchestrator.

This module provides functions to load pipeline configuration and failure data
from JSON files for CI failure analysis and repair planning.
"""

from __future__ import annotations

import json
from pathlib import Path

from .models import Failure, Stage


def load_pipeline(path: str | Path) -> list[Stage]:
    """Load pipeline stages from a JSON configuration file.

    This function reads a JSON file containing pipeline stage definitions
    and converts them into Stage objects for dependency graph construction.

    Args:
        path: Path to the JSON configuration file.

    Returns:
        List of Stage objects with id, dependencies, and criticality.

    Expected Schema:
        {
            "stages": [
                {"id": "stage_name", "depends_on": ["dep1", "dep2"], "criticality": 0.5},
                ...
            ]
        }

    Raises:
        KeyError: If required fields are missing from the JSON.
        json.JSONDecodeError: If the file is not valid JSON.
        FileNotFoundError: If the file does not exist.

    Side Effects:
        - Reads and parses the JSON file.

    Failure Modes:
        - Invalid JSON structure will raise json.JSONDecodeError.
        - Missing stages key will raise KeyError.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Stage(id=s["id"], depends_on=tuple(s.get("depends_on", [])), criticality=float(s.get("criticality", 0.5))) for s in data["stages"]]


def load_failures(path: str | Path) -> list[Failure]:
    """Load failure data from a JSON configuration file.

    This function reads a JSON file containing failure definitions
    and converts them into Failure objects for analysis and repair planning.

    Args:
        path: Path to the JSON configuration file.

    Returns:
        List of Failure objects with stage, error type, message, severity, confidence, and metadata.

    Expected Schema:
        {
            "failures": [
                {"stage": "stage_name", "error_type": "TYPE_ERROR", "message": "...", "severity": 0.5, "confidence": 0.9, "metadata": {...}},
                ...
            ]
        }

    Raises:
        KeyError: If required fields are missing from the JSON.
        json.JSONDecodeError: If the file is not valid JSON.
        FileNotFoundError: If the file does not exist.

    Side Effects:
        - Reads and parses the JSON file.

    Failure Modes:
        - Invalid JSON structure will raise json.JSONDecodeError.
        - Missing failures key will raise KeyError.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Failure(**item) for item in data["failures"]]
