"""Validate research cases against ``benchmark/research_case.schema.json`` with the standard library.

Implements the JSON Schema subset the case schema uses: ``type``, ``enum``, ``required``,
``properties``, ``additionalProperties`` (boolean or schema), ``items``, ``minItems``,
``minLength``, ``pattern`` and ``format: date-time``. Unknown keywords are ignored, so this is not a
general validator; ``test_research_case_schema`` keeps it honest for this schema.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from functools import lru_cache
from typing import Any

from .paths import SCHEMA_PATH

CURRENT_SCHEMA_VERSION = "1.1"

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


@lru_cache(maxsize=1)
def load_schema() -> dict[str, Any]:
    """Return the research-case schema."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _type_ok(value: Any, expected: str | list[str]) -> bool:
    names = [expected] if isinstance(expected, str) else expected
    for name in names:
        if name in ("integer", "number") and isinstance(value, bool):
            continue
        if isinstance(value, _TYPES[name]):
            return True
    return False


def _date_time_ok(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return "T" in value


def _validate(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    if "type" in schema and not _type_ok(value, schema["type"]):
        errors.append(f"{path}: expected {schema['type']}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")
        if schema.get("format") == "date-time" and not _date_time_ok(value):
            errors.append(f"{path}: not an ISO 8601 date-time")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for idx, item in enumerate(value):
                _validate(item, schema["items"], f"{path}[{idx}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", ()):
            if key not in value:
                errors.append(f"{path}: missing required field '{key}'")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in props:
                _validate(item, props[key], f"{path}.{key}", errors)
            elif extra is False:
                errors.append(f"{path}: unexpected field '{key}'")
            elif isinstance(extra, dict):
                _validate(item, extra, f"{path}.{key}", errors)


def validate_case(case: Any) -> list[str]:
    """Return schema violations for one case; an empty list means valid."""
    errors: list[str] = []
    _validate(case, load_schema(), "$", errors)
    return errors
