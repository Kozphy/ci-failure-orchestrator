from __future__ import annotations

"""Hash-chained audit logging for CI repair platform.

This module provides an append-only audit log where each entry contains
a hash of its content plus the hash of the previous entry, creating a
tamper-evident chain. This is used for critical path logging where
integrity verification is required.

Module responsibility:
    - Write audit log entries with hash chain
    - Auto-create parent directories
    - Maintain chain integrity across log restarts

Key invariants:
    - Each entry's hash depends on its content and the previous entry's hash
    - Log file is append-only; entries are never modified or deleted
    - Previous hash is read from the last line of the file on initialization

Safety boundaries:
    - Parent directories are created automatically
    - Empty or non-existent file uses "GENESIS" as the previous hash
    - Hash is computed from canonical JSON (sorted keys, compact separators)

Audit Notes:
    - Each log entry contains: ts (ISO 8601), event, payload, prev_hash, hash
    - Hash chain allows detection of any modification to any entry
    - Previous hash linking means modifying one entry invalidates all subsequent entries
    - append() returns the complete record including the computed hash
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HashChainedAuditLog:
    """Append-only audit log with tamper-evident hash chain.

    Writes audit entries to a JSONL file where each entry contains a
    SHA-256 hash of its canonical representation plus the hash of the
    previous entry. This creates a chain that makes any tampering detectable.

    Responsibility:
        - Write audit entries with hash chain
        - Auto-create parent directories
        - Read previous hash from existing file

    Invariants:
        - Entries are appended, never modified or deleted
        - Hash chain is maintained across log file restarts
        - Canonical JSON serialization ensures deterministic hashing

    Usage:
        log = HashChainedAuditLog("/path/to/audit.jsonl")
        record = log.append("repair_started", {"case_id": "abc123"})
        record = log.append("repair_completed", {"score": 0.95})

    Side effects:
        - Creates parent directories if they don't exist
        - Appends entries to the log file

    Audit Notes:
        - Hash chain provides tamper-evidence for all logged events
        - Previous hash is read from the last file line on initialization
        - Empty or missing file starts chain with "GENESIS"
    """

    def __init__(self, path: str | Path):
        """Initialize with audit log file path.

        Args:
            path: Path to the audit log JSONL file

        Side effects:
            Creates parent directories if they don't exist.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        """Read the hash of the last entry in the log.

        Returns:
            Hash of the last entry, or "GENESIS" if file is empty or doesn't exist
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "GENESIS"
        last_line = self.path.read_text(encoding="utf-8").strip().splitlines()[-1]
        return json.loads(last_line)["hash"]

    def append(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append an audit entry with hash chain.

        Creates a record with timestamp, event, payload, previous hash,
        and the computed hash of this record. Then appends it to the log.

        Args:
            event: Event type/name (e.g., "repair_started", "gate_evaluated")
            payload: Arbitrary dict containing event-specific audit data

        Returns:
            Complete record dict including the computed hash

        Side effects:
            Appends a new entry to the audit log file

        Audit Notes:
            - Each entry's hash is computed from canonical JSON
            - Previous hash links to the last entry's hash
            - Returned record can be used for immediate processing
        """
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
