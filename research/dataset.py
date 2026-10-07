"""Research dataset: loading, hashing, frozen-split lock, duplicate and leakage checks."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ci_failure_orchestrator.research_evaluation import canonical_json_digest

from .paths import DATASETS_DIR, LOCK_PATH, SPLIT_ALIASES, SPLITS
from .schema import validate_case
from .taxonomy import CANDIDATE_LABELS, WAIVABLE_GATES

NEAR_DUPLICATE_THRESHOLD = 0.9
_REAL_SOURCES = frozenset({"public_real_world", "private_real_world"})


@dataclass(frozen=True)
class Dataset:
    """Cases grouped by frozen split name (``development``, ``test``, ``holdout``)."""

    splits: Mapping[str, tuple[dict[str, Any], ...]]

    def cases(self, names: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Return cases from the named splits (all splits when ``names`` is None), in split order."""
        wanted = list(names) if names is not None else list(SPLITS)
        return [case for name in wanted for case in self.splits.get(name, ())]

    def counts(self) -> dict[str, int]:
        """Return the number of cases per split."""
        return {name: len(self.splits.get(name, ())) for name in SPLITS}


@dataclass
class ValidationReport:
    """Outcome of ``validate_dataset``: errors fail validation, warnings do not."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    hashes: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True when there are no errors."""
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        """Return the report as a JSON-compatible dict."""
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
            "hashes": self.hashes,
        }


def split_path(root: Path, name: str) -> Path:
    """Return the JSONL file for one split."""
    return root / name / "cases.jsonl"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file; a missing file is an empty list."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    """Write rows as canonical (sorted-key) JSONL with LF line endings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in rows)
    path.write_bytes(text.encode("utf-8"))


def load_dataset(root: Path = DATASETS_DIR) -> Dataset:
    """Load every split under ``root``."""
    return Dataset({name: tuple(read_jsonl(split_path(root, name))) for name in SPLITS})


def case_digest(case: Mapping[str, Any]) -> str:
    """SHA-256 of the case's canonical JSON."""
    return canonical_json_digest(dict(case))


def split_digest(cases: Sequence[Mapping[str, Any]]) -> str:
    """SHA-256 over sorted ``case_id:case_digest`` lines; order of cases in the file does not matter."""
    lines = sorted(f"{c['case_id']}:{case_digest(c)}" for c in cases)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def dataset_digest(split_hashes: Mapping[str, str]) -> str:
    """SHA-256 over the per-split digests."""
    return canonical_json_digest({name: split_hashes[name] for name in sorted(split_hashes)})


def compute_hashes(dataset: Dataset) -> dict[str, str]:
    """Return per-split digests plus a ``dataset`` digest."""
    hashes = {name: split_digest(dataset.splits.get(name, ())) for name in SPLITS}
    hashes["dataset"] = dataset_digest(hashes)
    return hashes


def read_lock(path: Path = LOCK_PATH) -> dict[str, Any] | None:
    """Return the lock file, or None when absent."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_lock(dataset: Dataset, *, version: str, frozen_at: str, notes: str = "") -> dict[str, Any]:
    """Build a lock document that freezes the current splits."""
    hashes = compute_hashes(dataset)
    return {
        "dataset_version": version,
        "frozen_at": frozen_at,
        "notes": notes,
        "dataset_sha256": hashes["dataset"],
        "splits": {
            name: {
                "count": len(dataset.splits.get(name, ())),
                "sha256": hashes[name],
                "case_ids": sorted(c["case_id"] for c in dataset.splits.get(name, ())),
            }
            for name in SPLITS
        },
    }


_HEX = re.compile(r"\b[0-9a-f]{7,64}\b")
_NUM = re.compile(r"\d+")


def failure_signature(case: Mapping[str, Any]) -> str:
    """Normalised text of what a system sees about the failure, for duplicate detection."""
    parts = [str(case.get("failure_category", ""))]
    for failure in case.get("observed_failures", ()):
        parts.append(f"{failure.get('stage', '')}|{failure.get('error_type', '')}|{failure.get('log_excerpt') or ''}")
    text = " ".join(parts).lower()
    text = _HEX.sub("h", text)
    text = _NUM.sub("0", text)
    return " ".join(text.split())


def _shingles(text: str, size: int = 3) -> set[str]:
    tokens = text.split()
    if len(tokens) < size:
        return {" ".join(tokens)}
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of token 3-shingles."""
    sa, sb = _shingles(a), _shingles(b)
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


@dataclass(frozen=True)
class DuplicateFinding:
    """A pair of cases that are exact or near duplicates."""

    case_a: str
    split_a: str
    case_b: str
    split_b: str
    kind: str
    score: float


def find_duplicates(
    labelled: Sequence[tuple[str, Mapping[str, Any]]], threshold: float = NEAR_DUPLICATE_THRESHOLD
) -> list[DuplicateFinding]:
    """Find exact and near duplicates among ``(split, case)`` pairs.

    Exact: identical normalised failure signature and identical repair fixture (if any). Near:
    signature similarity at or above ``threshold``. Repair cases are compared on their fixture too,
    so two different fixtures with the same short failure message are not duplicates.
    """
    sigs = [
        (split, case, failure_signature(case), canonical_json_digest(case.get("repair_fixture") or {}))
        for split, case in labelled
    ]
    out: list[DuplicateFinding] = []
    for i in range(len(sigs)):
        split_a, case_a, sig_a, fix_a = sigs[i]
        for j in range(i + 1, len(sigs)):
            split_b, case_b, sig_b, fix_b = sigs[j]
            if fix_a != fix_b:
                continue
            if sig_a == sig_b:
                out.append(DuplicateFinding(case_a["case_id"], split_a, case_b["case_id"], split_b, "exact", 1.0))
                continue
            score = similarity(sig_a, sig_b)
            if score >= threshold:
                out.append(
                    DuplicateFinding(case_a["case_id"], split_a, case_b["case_id"], split_b, "near", round(score, 3))
                )
    return out


def _diagnosis_inputs(case: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "observed_failures": case.get("observed_failures"),
            "failure_time_context": case.get("failure_time_context"),
            "pipeline": case.get("pipeline"),
            "workflow": case.get("workflow"),
            "failed_job": case.get("failed_job"),
            "failed_step": case.get("failed_step"),
        },
        sort_keys=True,
    ).lower()


def hindsight_leaks(case: Mapping[str, Any]) -> list[str]:
    """Return reasons the diagnosis inputs contain information only known after the fix."""
    problems: list[str] = []
    inputs = _diagnosis_inputs(case)
    prov = case.get("provenance") or {}
    fix_commit = (prov.get("fix_commit") or "").lower()
    if fix_commit:
        if fix_commit == str(case.get("commit_sha", "")).lower():
            problems.append("provenance.fix_commit equals the failing commit_sha")
        if fix_commit[:7] in inputs:
            problems.append("fix commit SHA appears in diagnosis inputs")
    expected = ((case.get("ground_truth") or {}).get("expected_repair") or "").strip().lower()
    if len(expected) >= 20 and expected in inputs:
        problems.append("ground_truth.expected_repair appears verbatim in diagnosis inputs")
    cutoff = prov.get("failure_time_cutoff")
    captured = prov.get("captured_at")
    if case.get("source_type") in _REAL_SOURCES and not cutoff:
        problems.append("real-world case has no provenance.failure_time_cutoff")
    if cutoff and captured and cutoff > captured:
        problems.append("failure_time_cutoff is after captured_at")
    return problems


def _case_semantics(case: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    tracks = case.get("tracks") or ["diagnosis"]
    stages = {f.get("stage") for f in case.get("observed_failures", ())}
    pipeline = case.get("pipeline")
    if pipeline:
        ids = [s["id"] for s in pipeline["stages"]]
        if len(ids) != len(set(ids)):
            problems.append("pipeline has duplicate stage ids")
        known = set(ids)
        for stage in pipeline["stages"]:
            for dep in stage.get("depends_on", ()):
                if dep not in known:
                    problems.append(f"pipeline stage {stage['id']} depends on unknown stage {dep}")
        for stage in stages:
            if stage not in known:
                problems.append(f"observed failure stage {stage} is not in the pipeline")
    gt = case.get("ground_truth") or {}
    if "diagnosis" in tracks:
        root = gt.get("root_cause_stage")
        if not root:
            problems.append("diagnosis case needs ground_truth.root_cause_stage")
        elif root not in stages and not (pipeline and root in {s["id"] for s in pipeline["stages"]}):
            problems.append(f"root_cause_stage {root} is neither an observed stage nor a pipeline stage")
    verification = case.get("verification") or {}
    waived = verification.get("waived_gates") or {}
    for gate in waived:
        if gate not in WAIVABLE_GATES:
            problems.append(f"verification.waived_gates: {gate} is not waivable")
    if verification.get("security_gate_required", True) and "security" in waived:
        problems.append("security gate is required but waived")
    if "repair" in tracks:
        fixture = case.get("repair_fixture")
        if not fixture:
            problems.append("repair case needs repair_fixture")
        else:
            ids = [c["candidate_id"] for c in fixture["candidates"]]
            if len(ids) != len(set(ids)):
                problems.append("repair_fixture has duplicate candidate ids")
            for cand in fixture["candidates"]:
                if cand["label"] not in CANDIDATE_LABELS:
                    problems.append(f"candidate {cand['candidate_id']} has unknown label")
                if cand["label"] == "fake_fix" and not cand.get("fake_fix_kind"):
                    problems.append(f"fake_fix candidate {cand['candidate_id']} needs fake_fix_kind")
            overlap = set(fixture["files"]) & set(fixture["hidden_oracle"]["files"])
            if overlap:
                problems.append(f"hidden oracle files collide with visible files: {sorted(overlap)}")
    prov = case.get("provenance") or {}
    if case.get("schema_version") == "1.1" and not str(prov.get("content_digest") or "").startswith("sha256:"):
        problems.append("schema 1.1 case needs provenance.content_digest (sha256:...)")
    source = case.get("source_type")
    if source in _REAL_SOURCES:
        if not str(prov.get("source_uri", "")).startswith("https://"):
            problems.append("real-world case needs an https source_uri")
        if gt.get("validation_method") == "known_fixture":
            problems.append("real-world case cannot use validation_method known_fixture")
        if gt.get("validation_method") == "patch_verified" and not prov.get("fix_commit"):
            problems.append("patch_verified case needs provenance.fix_commit")
    if source in ("synthetic", "fixture") and gt.get("validation_method") not in ("known_fixture", "other"):
        problems.append("synthetic/fixture case must use validation_method known_fixture or other")
    if prov.get("annotation_status", "labelled") != "labelled":
        problems.append("only labelled cases may be placed in an evaluation split")
    return problems


def validate_dataset(
    dataset: Dataset,
    *,
    lock: Mapping[str, Any] | None = None,
    require_lock: bool = True,
) -> ValidationReport:
    """Check schema, IDs, duplicates, cross-split leakage, provenance, labels, verification and hashes."""
    report = ValidationReport(counts=dataset.counts(), hashes=compute_hashes(dataset))
    labelled: list[tuple[str, Mapping[str, Any]]] = []
    seen_ids: dict[str, str] = {}
    seen_runs: dict[tuple[str, str, str], tuple[str, str]] = {}
    seen_uris: dict[str, tuple[str, str]] = {}

    for split in SPLITS:
        for case in dataset.splits.get(split, ()):
            cid = str(case.get("case_id", "<missing>"))
            for err in validate_case(case):
                report.errors.append(f"{split}/{cid}: schema {err}")
            declared = case.get("split")
            if declared is not None and SPLIT_ALIASES.get(declared, declared) != split:
                report.errors.append(f"{split}/{cid}: declares split {declared!r} but is stored in {split}")
            if cid in seen_ids:
                report.errors.append(f"{split}/{cid}: duplicate case_id (also in {seen_ids[cid]})")
            seen_ids[cid] = split
            if case.get("schema_version", "1.0") not in ("1.0", "1.1"):
                report.errors.append(f"{split}/{cid}: unsupported schema_version")
            if case.get("run_id") is not None:
                key = (str(case.get("repository")), str(case.get("commit_sha")), str(case.get("run_id")))
                if key in seen_runs:
                    other_split, other_id = seen_runs[key]
                    kind = "cross-split leakage" if other_split != split else "duplicate"
                    report.errors.append(f"{split}/{cid}: {kind}: same repository/commit/run as {other_split}/{other_id}")
                seen_runs[key] = (split, cid)
            uri = (case.get("provenance") or {}).get("source_uri")
            if uri:
                if uri in seen_uris:
                    other_split, other_id = seen_uris[uri]
                    kind = "cross-split leakage" if other_split != split else "duplicate"
                    report.errors.append(f"{split}/{cid}: {kind}: same source_uri as {other_split}/{other_id}")
                seen_uris[uri] = (split, cid)
            for problem in _case_semantics(case):
                report.errors.append(f"{split}/{cid}: {problem}")
            for problem in hindsight_leaks(case):
                report.errors.append(f"{split}/{cid}: hindsight leakage: {problem}")
            labelled.append((split, case))

    for dup in find_duplicates(labelled):
        where = f"{dup.split_a}/{dup.case_a} ~ {dup.split_b}/{dup.case_b} ({dup.kind}, {dup.score})"
        if dup.split_a != dup.split_b:
            report.errors.append(f"cross-split near-duplicate leakage: {where}")
        elif dup.kind == "exact":
            report.errors.append(f"exact duplicate within split: {where}")
        else:
            report.warnings.append(f"near-duplicate within split: {where}")

    if lock is None:
        if require_lock:
            report.errors.append("dataset.lock.json is missing; run with --write-lock to freeze the splits")
    else:
        if lock.get("dataset_sha256") != report.hashes["dataset"]:
            report.errors.append(
                "dataset hash does not match dataset.lock.json; frozen splits changed. "
                "Bump dataset_version and re-freeze deliberately (see research/DATASET_CARD.md)."
            )
        for split in SPLITS:
            entry = (lock.get("splits") or {}).get(split) or {}
            if entry.get("sha256") != report.hashes[split]:
                report.errors.append(f"{split}: hash differs from dataset.lock.json")
            ids = sorted(c["case_id"] for c in dataset.splits.get(split, ()))
            if entry.get("case_ids") is not None and entry["case_ids"] != ids:
                report.errors.append(f"{split}: case IDs differ from dataset.lock.json")
    return report
