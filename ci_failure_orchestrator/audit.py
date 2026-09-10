"""Hash-chained audit logging for tamper-evident event records.

This module provides a hash-chained audit log that records events with SHA-256
hashes for tamper detection. Each record includes a reference to the previous
record's hash, creating an immutable chain that any modification invalidates.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class HashChainedAuditLog:
    """Hash-chained audit log for tamper-evident event recording.

    This class provides append-only audit logging with SHA-256 hash chaining.
    Each record contains a reference to the previous record's hash, creating
    an immutable chain where any modification invalidates all subsequent hashes.
    This provides tamper-evidence for critical decision paths and state mutations.

    Attributes:
        path: Filesystem path to the audit log file.

    Audit Notes:
        - Audit log file corruption or tampering breaks the hash chain.
        - Missing or modified log entries invalidate subsequent hash verification.
        - Recovery: Maintain backup copies and verify hash chain integrity periodically.
        - Evidence: All records include timestamps, event types, payloads, and hash chain for audit.

    Engineering Notes:
        - Trade-off: Hash chaining provides tamper-evidence but adds computational overhead.
        - Design: Genesis hash ("GENESIS") anchors the chain for the first record.
        - Performance: SHA-256 is fast enough for most audit logging use cases.
    """

    def __init__(self, path: str | Path):
        """Initialize the hash-chained audit log.

        Args:
            path: Filesystem path to the audit log file. Creates parent directories if needed.

        Side Effects:
            - Creates parent directories if they don't exist.
        """
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _last_hash(self) -> str:
        """Retrieve the hash of the last record in the audit log.

        Returns:
            Hash of the last record, or "GENESIS" if the log is empty or doesn't exist.

        Raises:
            json.JSONDecodeError: If the last line is not valid JSON.
        """
        if not self.path.exists() or self.path.stat().st_size == 0:
            return "GENESIS"
        last_line = self.path.read_text(encoding="utf-8").strip().splitlines()[-1]
        return json.loads(last_line)["hash"]

    def append(self, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Append an event record to the hash-chained audit log.

        This method creates a tamper-evident record with timestamp, event type,
        payload, and hash chain reference. The record is hashed with SHA-256 using
        the previous record's hash, creating an immutable chain.

        Args:
            event: Event type identifier (e.g., "root_cause_ranked", "candidate_evaluated").
            payload: Event payload data as a dictionary.

        Returns:
            Complete audit record with hash, timestamp, event, payload, and prev_hash.

        Side Effects:
            - Appends the record to the audit log file.
            - Creates the audit log file if it doesn't exist.

        Record Structure:
            - ts: UTC timestamp in ISO 8601 format.
            - event: Event type identifier.
            - payload: Event payload data.
            - prev_hash: Hash of the previous record (or "GENESIS" for first record).
            - hash: SHA-256 hash of the canonical record for tamper detection.

        Idempotency:
            - Each append creates a new record; duplicate events produce separate records.
            - Hash chain ensures records cannot be modified after writing.
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
