"""Replayable CI failure corpus loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class FailureCase:
    case_id: str
    failure_class: str
    stage: str
    message: str
    expected_root_stage: str
    expected_action: str
    tags: tuple[str, ...] = ()


class FailureCorpus:
    @staticmethod
    def load(path: str | Path) -> tuple[FailureCase, ...]:
        cases: list[FailureCase] = []
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                payload = json.loads(line)
                missing = {
                    "case_id",
                    "failure_class",
                    "stage",
                    "message",
                    "expected_root_stage",
                    "expected_action",
                } - payload.keys()
                if missing:
                    raise ValueError(f"corpus line {line_number} missing fields: {sorted(missing)}")
                cases.append(
                    FailureCase(
                        case_id=payload["case_id"],
                        failure_class=payload["failure_class"],
                        stage=payload["stage"],
                        message=payload["message"],
                        expected_root_stage=payload["expected_root_stage"],
                        expected_action=payload["expected_action"],
                        tags=tuple(payload.get("tags", ())),
                    )
                )
        if not cases:
            raise ValueError("failure corpus is empty")
        return tuple(cases)
