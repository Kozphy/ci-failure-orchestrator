from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HashChainedAuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "GENESIS"
        last_line = self.path.read_text(encoding="utf-8").strip().splitlines()[-1]
        return json.loads(last_line)["hash"]

    def append(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "payload": payload,
            "prev_hash": self._last_hash(),
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        record["hash"] = hashlib.sha256(canonical).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record
