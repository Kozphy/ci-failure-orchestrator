"""SHA-256 integrity checks for stored run artifacts.

Two digests are reported for each JSON file:

- ``file_sha256``: SHA-256 of the raw file bytes.
- ``canonical_json_sha256``: SHA-256 of ``canonical_json(parsed)`` after UTF-8 decode.

A mismatch between the on-disk bytes and a recorded ``file_sha256`` means the file changed.
Canonical digests are for cross-platform comparison after JSON parse; they do not prove
independent provenance or a third-party signature.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..foundation.durable import canonical_json
from ..service.common import FIX_DIR, REMEDIATION_NAME
from ..service.evidence_report import EVIDENCE_REPORT_JSON

EXPECTED_OPTIONAL = (
    f"{FIX_DIR}/{REMEDIATION_NAME}",
    f"{FIX_DIR}/{EVIDENCE_REPORT_JSON}",
    "input/failure-event.json",
    "classification/classification.json",
    "policy/policy-decision.json",
    "metrics-summary.json",
)


@dataclass(frozen=True)
class FileDigest:
    relative_path: str
    present: bool
    file_sha256: str | None
    canonical_json_sha256: str | None
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntegrityResult:
    run_id: str
    status: str
    files: tuple[FileDigest, ...] = ()
    missing: tuple[str, ...] = ()
    mismatches: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["files"] = [digest.to_dict() for digest in self.files]
        return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(path: Path) -> tuple[str | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
        payload = json.loads(text)
    except (OSError, UnicodeError) as exc:
        return None, f"read_error:{type(exc).__name__}"
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(payload, (dict, list)):
        return None, "json_not_object_or_array"
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest(), None


def digest_file(run_root: Path, relative: str) -> FileDigest:
    path = run_root / relative
    if not path.is_file():
        return FileDigest(relative_path=relative, present=False, file_sha256=None, canonical_json_sha256=None)
    file_hash = _file_sha256(path)
    canonical_hash, error = _canonical_sha256(path)
    return FileDigest(
        relative_path=relative,
        present=True,
        file_sha256=file_hash,
        canonical_json_sha256=canonical_hash,
        parse_error=error,
    )


def verify_run_integrity(
    artifacts_root: Path,
    run_id: str,
    *,
    expected_file_sha256: dict[str, str] | None = None,
) -> IntegrityResult:
    """Check expected paths for one run. Compare against ``expected_file_sha256`` when provided."""
    run_root = Path(artifacts_root) / "runs" / run_id
    notes = [
        "file_sha256 hashes raw bytes",
        "canonical_json_sha256 hashes canonical_json(parsed); not a provenance certificate",
    ]
    if not run_root.is_dir():
        return IntegrityResult(
            run_id=run_id,
            status="missing_run",
            missing=("runs/" + run_id,),
            notes=tuple(notes),
        )
    digests = tuple(digest_file(run_root, relative) for relative in EXPECTED_OPTIONAL)
    missing = tuple(item.relative_path for item in digests if not item.present)
    mismatches: list[str] = []
    if expected_file_sha256:
        for item in digests:
            expected = expected_file_sha256.get(item.relative_path)
            if expected is None or not item.present:
                continue
            if item.file_sha256 != expected:
                mismatches.append(item.relative_path)
    if mismatches:
        status = "hash_mismatch"
    elif not any(item.present for item in digests):
        status = "empty_run"
    elif missing and any(item.present for item in digests):
        status = "partial"
    else:
        status = "ok"
    return IntegrityResult(
        run_id=run_id,
        status=status,
        files=digests,
        missing=missing,
        mismatches=tuple(mismatches),
        notes=tuple(notes),
    )


def verify_tree_integrity(
    artifacts_root: Path,
    *,
    expected_by_run: dict[str, dict[str, str]] | None = None,
) -> list[IntegrityResult]:
    """Verify every run directory under the artifacts root."""
    root = Path(artifacts_root) / "runs"
    if not root.is_dir():
        return []
    results: list[IntegrityResult] = []
    for run_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        expected = None if expected_by_run is None else expected_by_run.get(run_dir.name)
        results.append(verify_run_integrity(artifacts_root, run_dir.name, expected_file_sha256=expected))
    return results
