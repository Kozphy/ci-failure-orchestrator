"""Build the research dataset deterministically: ``python -m research.build_dataset``.

Development split: cases imported from the legacy corpora (``benchmark/``, ``benchmarks/``) plus four
repair fixtures seeded from ``benchmark/repair_fixture_corpus.v1.json``. These were visible while the
product was built, so they may only be used for development.

Test split: synthetic cases authored in ``research/authored_cases.py`` for this study and frozen in
``research/datasets/dataset.lock.json`` before any system was evaluated on them.

Holdout split: intentionally empty until real-world cases are collected (see DATASET_CARD.md).

Exact duplicates are dropped (first source wins) and every exclusion is written to
``research/datasets/exclusions.json``.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ci_failure_orchestrator.research_evaluation import canonical_json_digest

from . import authored_cases
from .dataset import find_duplicates, write_jsonl
from .paths import DATASETS_DIR, ROOT
from .schema import CURRENT_SCHEMA_VERSION
from .taxonomy import to_research_category

IMPORTED_AT = "2026-10-07T00:00:00+00:00"
SYNTHETIC_REPO = "synthetic/ci-failure-orchestrator-fixtures"
SYNTHETIC_SHA = "synthetic"
LICENSE = "Project-authored synthetic data; repository license (see LICENSE)"

LEGACY_CLASS_LABELS: dict[str, str] = {
    "DEPENDENCY_ERROR": "dependency",
    "FLAKY_TEST": "flaky_or_nondeterministic",
    "TYPE_ERROR": "compilation_or_syntax",
    "SECURITY_ERROR": "security_or_policy",
    "DEPLOYMENT_ERROR": "infrastructure_or_environment",
}

# Log text for the error types in benchmark/ci_failure_corpus.v1.json, which has none. Authored once
# here so the cascade cases have something a log-reading system can read.
CASCADE_LOGS: dict[str, tuple[str, str]] = {
    "TYPE_ERROR": (
        "compilation_or_syntax",
        (
            "src/app/models.py:42: error: Incompatible types in assignment (expression has type \"str\", "
            "variable has type \"int\")  [assignment]\nFound 1 error in 1 file (checked 12 source files)"
        ),
    ),
    "TEST_ASSERTION": (
        "unit_test",
        "FAILED tests/test_orders.py::test_total - AssertionError: assert 41 == 42\n1 failed, 37 passed in 2.10s",
    ),
    "BUILD_ERROR": (
        "compilation_or_syntax",
        "ERROR: Failed building wheel for app\nerror: subprocess-exited-with-error: build backend returned 1",
    ),
    "DEPENDENCY_ERROR": (
        "dependency",
        "ModuleNotFoundError: No module named 'pydantic_settings'\nERROR: dependency resolution failed",
    ),
    "PACKAGE_ERROR": (
        "configuration",
        "error: MANIFEST.in references missing file 'app/schema.json'; packaging aborted",
    ),
    "DEPLOYMENT_ERROR": (
        "infrastructure_or_environment",
        "deploy: rollout failed: readiness probe failed for pod app-7d9 (HTTP 503)",
    ),
}


def _digest(record: Any) -> str:
    return "sha256:" + canonical_json_digest(record)


def _base(case_id: str, split: str, source_uri: str, record: Any, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "case_id": case_id,
        "split": split,
        "source_type": "synthetic",
        "repository": SYNTHETIC_REPO,
        "commit_sha": SYNTHETIC_SHA,
        "provenance": {
            "source_uri": source_uri,
            "license_or_permission": LICENSE,
            "captured_at": IMPORTED_AT,
            "collector": "research.build_dataset",
            "content_digest": _digest(record),
            "author_controlled": True,
            "annotation_status": "labelled",
            **extra,
        },
    }


def _diagnosis_verification(check: str) -> dict[str, Any]:
    return {
        "required_checks": [check],
        "full_regression_required": True,
        "security_gate_required": True,
        "policy_gate_required": True,
        "real_ci_required": True,
    }


def _from_event(case_id: str, uri: str, record: Mapping[str, Any], event: Mapping[str, Any], label: str) -> dict:
    job = str(event.get("job") or "ci")
    log = "\n".join(x for x in (event.get("message"), event.get("log_excerpt")) if x)
    case = _base(case_id, "development", uri, record)
    case.update(
        {
            "tracks": ["diagnosis"],
            "workflow": event.get("workflow"),
            "failed_job": job,
            "failed_step": event.get("failed_step"),
            "failure_category": label,
            "observed_failures": [
                {"stage": job, "error_type": label.upper(), "log_excerpt": log, "order": 1}
            ],
            "failure_time_context": {"changed_paths": list(event.get("changed_paths") or [])},
            "ground_truth": {
                "root_cause": f"Single {label} failure in job '{job}' (legacy synthetic golden).",
                "validation_method": "known_fixture",
                "root_cause_stage": job,
            },
            "verification": _diagnosis_verification(job),
        }
    )
    return case


def legacy_foundation_cases() -> list[dict[str, Any]]:
    """BENCH-CLASS-* classification goldens from ``benchmarks/foundation``."""
    out = []
    for path in sorted((ROOT / "benchmarks" / "foundation" / "cases" / "classification").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        label = to_research_category(record["expected"]["classification"])
        uri = f"repo://ci-failure-orchestrator/{path.relative_to(ROOT).as_posix()}"
        out.append(_from_event(f"dev-{record['case_id'].lower()}", uri, record, record["fixture"]["event"], label))
    return out


def legacy_governed_cases() -> list[dict[str, Any]]:
    """Governed synthetic cases from ``benchmarks/cases``."""
    out = []
    for path in sorted((ROOT / "benchmarks" / "cases").glob("*.json")):
        record = json.loads(path.read_bytes().decode("utf-8"))
        label = to_research_category(record["expected_class"])
        uri = f"repo://ci-failure-orchestrator/{path.relative_to(ROOT).as_posix()}"
        out.append(_from_event(f"dev-governed-{path.stem.replace('_', '-')}", uri, record, record["failure"], label))
    return out


def legacy_corpus_cases() -> list[dict[str, Any]]:
    """Lines of ``benchmarks/corpus/v0.1.jsonl``."""
    path = ROOT / "benchmarks" / "corpus" / "v0.1.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        label = LEGACY_CLASS_LABELS[record["failure_class"]]
        uri = f"repo://ci-failure-orchestrator/benchmarks/corpus/v0.1.jsonl#{record['case_id']}"
        event = {"job": record["stage"], "message": record["message"], "workflow": "ci"}
        case = _from_event(f"dev-corpus-{record['case_id']}", uri, record, event, label)
        case["ground_truth"]["root_cause_stage"] = record["expected_root_stage"]
        out.append(case)
    return out


def legacy_cascade_cases() -> list[dict[str, Any]]:
    """Multi-stage cascades from ``benchmark/ci_failure_corpus.v1.json`` with authored log text."""
    path = ROOT / "benchmark" / "ci_failure_corpus.v1.json"
    corpus = json.loads(path.read_text(encoding="utf-8"))
    stages = [
        {"id": s["id"], "depends_on": list(s.get("depends_on", [])), "criticality": float(s.get("criticality", 0.5))}
        for s in corpus["stages"]
    ]
    depth = {s["id"]: idx for idx, s in enumerate(stages)}
    out = []
    for record in corpus["cases"]:
        failures = []
        for f in sorted(record["failures"], key=lambda f: depth[f["stage"]]):
            failures.append(
                {
                    "stage": f["stage"],
                    "error_type": f["error_type"],
                    "log_excerpt": CASCADE_LOGS[f["error_type"]][1],
                    "order": depth[f["stage"]] + 1,
                    "confidence": f["confidence"],
                    "severity": f["severity"],
                }
            )
        root = record["root_cause"]
        root_type = next(f["error_type"] for f in record["failures"] if f["stage"] == root)
        uri = f"repo://ci-failure-orchestrator/benchmark/ci_failure_corpus.v1.json#{record['id']}"
        case = _base(f"dev-cascade-{record['id']}", "development", uri, record)
        case.update(
            {
                "tracks": ["diagnosis"],
                "workflow": "ci",
                "failed_job": root,
                "failure_category": CASCADE_LOGS[root_type][0],
                "observed_failures": failures,
                "pipeline": {"stages": stages},
                "ground_truth": {
                    "root_cause": f"{root_type} in stage '{root}'; later failures are cascades (synthetic).",
                    "validation_method": "known_fixture",
                    "root_cause_stage": root,
                },
                "verification": _diagnosis_verification(root),
            }
        )
        out.append(case)
    return out


def _fixture_case(spec: Mapping[str, Any], split: str, uri: str, derived_from: str | None) -> dict[str, Any]:
    extra = {"derived_from": derived_from} if derived_from else {}
    case = _base(spec["case_id"], split, uri, spec, **extra)
    fixture = spec["fixture"]
    case.update(
        {
            "tracks": ["repair"],
            "workflow": "ci",
            "failed_job": "tests",
            "failed_step": "pytest",
            "failure_category": spec["failure_category"],
            "observed_failures": [
                {
                    "stage": "tests",
                    "error_type": "TEST_ASSERTION",
                    "log_excerpt": spec["log_excerpt"],
                    "order": 1,
                }
            ],
            "failure_time_context": {"changed_paths": list(spec.get("changed_paths", []))},
            "ground_truth": {
                "root_cause": spec["root_cause"],
                "validation_method": "known_fixture",
                "root_cause_stage": "tests",
                "expected_repair": spec["expected_repair"],
                "repair_constraints": [
                    "visible tests must not be weakened, skipped, deselected or deleted",
                    "hidden oracle tests must pass",
                ],
            },
            "verification": {
                "required_checks": ["tests"],
                "targeted_tests": [spec["failing_test"]],
                "full_regression_required": True,
                "security_gate_required": False,
                "policy_gate_required": True,
                "real_ci_required": False,
                "waived_gates": dict(authored_cases.FIXTURE_WAIVERS),
            },
            "repair_fixture": fixture,
        }
    )
    return case


def build() -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Return ``(splits, exclusions)``."""
    imported = legacy_foundation_cases() + legacy_governed_cases() + legacy_corpus_cases() + legacy_cascade_cases()
    exclusions: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []
    dropped: set[str] = set()
    for dup in find_duplicates([("development", c) for c in imported]):
        if dup.kind == "exact" and dup.case_a not in dropped:
            dropped.add(dup.case_b)
            exclusions.append(
                {
                    "case_id": dup.case_b,
                    "reason": "exact_duplicate",
                    "duplicate_of": dup.case_a,
                    "detail": "identical normalised failure signature; first source kept",
                }
            )
    kept = [c for c in imported if c["case_id"] not in dropped]

    dev_repair = [
        _fixture_case(spec, "development", f"repo://ci-failure-orchestrator/research/authored_cases.py#{spec['case_id']}",
                      "benchmark/repair_fixture_corpus.v1.json")
        for spec in authored_cases.DEV_REPAIR
    ]
    test_repair = [
        _fixture_case(spec, "test", f"repo://ci-failure-orchestrator/research/authored_cases.py#{spec['case_id']}", None)
        for spec in authored_cases.TEST_REPAIR
    ]
    test_diag = []
    for spec in authored_cases.TEST_DIAGNOSIS:
        case = _base(spec["case_id"], "test", f"repo://ci-failure-orchestrator/research/authored_cases.py#{spec['case_id']}", spec)
        case.update({k: v for k, v in spec.items() if k != "case_id"})
        case["tracks"] = ["diagnosis"]
        case["verification"] = _diagnosis_verification(spec["ground_truth"]["root_cause_stage"])
        test_diag.append(case)
    splits = {
        "development": sorted(kept + dev_repair, key=lambda c: c["case_id"]),
        "test": sorted(test_diag + test_repair, key=lambda c: c["case_id"]),
        "holdout": [],
    }
    return splits, exclusions


def main(argv: list[str] | None = None) -> int:
    """Write the split files and the exclusion log."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DATASETS_DIR)
    parser.add_argument("--check", action="store_true", help="fail if the committed files differ from a rebuild")
    args = parser.parse_args(argv)
    splits, exclusions = build()
    rendered = {
        args.out / name / "cases.jsonl": "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
        for name, rows in splits.items()
    }
    rendered[args.out / "exclusions.json"] = json.dumps(exclusions, indent=2, sort_keys=True) + "\n"
    if args.check:
        stale = [str(p) for p, text in rendered.items() if not p.exists() or p.read_bytes().decode("utf-8") != text]
        if stale:
            print("dataset files differ from a rebuild:\n" + "\n".join(stale))
            return 1
        print("dataset files match a rebuild")
        return 0
    for name, rows in splits.items():
        write_jsonl(args.out / name / "cases.jsonl", rows)
    (args.out / "exclusions.json").write_bytes(rendered[args.out / "exclusions.json"].encode("utf-8"))
    print(json.dumps({name: len(rows) for name, rows in splits.items()} | {"excluded": len(exclusions)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
