from __future__ import annotations

import json
from pathlib import Path

from .models import Failure, Stage


def load_pipeline(path: str | Path) -> list[Stage]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Stage(id=s["id"], depends_on=tuple(s.get("depends_on", [])), criticality=float(s.get("criticality", 0.5))) for s in data["stages"]]


def load_failures(path: str | Path) -> list[Failure]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Failure(**item) for item in data["failures"]]
