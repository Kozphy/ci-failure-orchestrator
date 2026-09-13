from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SENSITIVE_KEYS = re.compile(r"(api[_-]?key|authorization|cookie|password|secret|token)", re.IGNORECASE)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_KEYS.search(str(key)) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [REDACTED]", value)
        value = re.sub(
            r"(?i)(api[_-]?key|password|secret|token)(\s*[:=]\s*)[^\s,;]+",
            r"\1\2[REDACTED]",
            value,
        )
    return value


class HashChainedAuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "GENESIS"
        last_line = self.path.read_text(encoding="utf-8").strip().splitlines()[-1]
        return json.loads(last_line)["hash"]

    def append(
        self,
        event: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "ts": timestamp,
            "timestamp": timestamp,
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id,
            "event": event,
            "event_type": event,
            "payload": redact(payload),
            "prev_hash": self._last_hash(),
        }
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
        record["hash"] = hashlib.sha256(canonical).hexdigest()
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return record
