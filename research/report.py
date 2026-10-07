"""Processed tables and manuscript sections, regenerated from one raw experiment directory.

``python -m research.report [--raw research/results/raw/<id>] [--manuscript research/paper/manuscript.md]``

Processed files are derived data and may be overwritten; raw files are only read. Manuscript tables are
replaced between ``<!-- BEGIN GENERATED:<name> -->`` and ``<!-- END GENERATED:<name> -->`` markers.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .paths import PROCESSED_DIR, RAW_DIR, ROOT

REPAIR_RATES = (
    "acceptance_rate", "verified_repair_rate", "green_but_wrong_rate", "unsafe_remediation_rate",
    "regression_rate", "green_but_unverified_rate", "ci_green_rate", "policy_rejection_rate",
    "verification_rejection_rate", "human_escalation_rate", "missed_correct_repair_rate",
    "retry_budget_exhaustion_rate", "repair_attempt_rate",
)
ABLATIONS = {
    "P-no-policy": "policy gate",
    "P-no-verification": "verification layer",
    "P-no-retry": "retry budget (k=1)",
}
NOT_MEASURED = "NOT YET MEASURED"


def _csv(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})
    return buf.getvalue()


def _fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _ci(record: Mapping[str, Any] | None) -> str:
    if not record or record.get("estimate") is None:
        return "n/a"
    k_n = f" ({record['k']}/{record['n']})" if "k" in record else ""
    return f"{_fmt(record['estimate'])} [{_fmt(record.get('low'))}, {_fmt(record.get('high'))}]{k_n}"


def load_raw(raw_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read manifest.json and metrics.json from a raw experiment directory."""
    manifest = json.loads((raw_dir / "manifest.json").read_text(encoding="utf-8"))
    metrics = json.loads((raw_dir / "metrics.json").read_text(encoding="utf-8"))
    return manifest, metrics


def latest_raw_dir(raw_root: Path = RAW_DIR) -> Path:
    """The raw experiment directory with the latest manifest timestamp."""
    dirs = [p for p in raw_root.iterdir() if (p / "manifest.json").is_file()] if raw_root.is_dir() else []
    if not dirs:
        raise FileNotFoundError(f"no raw experiments under {raw_root}")
    return max(dirs, key=lambda p: (json.loads((p / "manifest.json").read_text(encoding="utf-8"))["timestamp"], p.name))


def diagnosis_rows(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per diagnosis system."""
    rows = []
    for system, m in sorted((metrics.get("diagnosis") or {}).items()):
        acc = m.get("accuracy_ci") or {}
        f1 = m.get("macro_f1_ci") or {}
        root = m.get("root_stage_accuracy_multi_failure") or {}
        rows.append({
            "system": system, "status": m.get("status"), "claim_eligible": m.get("claim_eligible"),
            "n_cases": m.get("n_cases"), "n_scored": m.get("n_scored"), "n_not_run": m.get("n_not_run"),
            "accuracy": acc.get("estimate"), "accuracy_low": acc.get("low"), "accuracy_high": acc.get("high"),
            "macro_f1": f1.get("estimate"), "macro_f1_low": f1.get("low"), "macro_f1_high": f1.get("high"),
            "root_stage_accuracy_multi": root.get("estimate"), "root_low": root.get("low"),
            "root_high": root.get("high"), "root_n": root.get("n"),
            "reason": m.get("reason"),
        })
    return rows


def repair_rows(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One row per repair system with every rate and its Wilson interval."""
    rows = []
    for system, m in sorted((metrics.get("repair") or {}).items()):
        row: dict[str, Any] = {"system": system, "n_cases": m.get("n_cases"), "retry_budget": m.get("retry_budget"),
                               "mean_attempts": m.get("mean_attempts")}
        for rate in REPAIR_RATES:
            rec = m.get(rate) or {}
            row[rate] = rec.get("estimate")
            row[f"{rate}_low"] = rec.get("low")
            row[f"{rate}_high"] = rec.get("high")
            row[f"{rate}_k"] = rec.get("k")
        rows.append(row)
    return rows


def ablation_rows(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Each ablation against P: apparent repair rate, incorrect acceptance and the paired difference."""
    repair = metrics.get("repair") or {}
    comparisons = (metrics.get("comparisons") or {}).get("repair") or {}
    rows = []
    for system, removed in ABLATIONS.items():
        if system not in repair or "P" not in repair:
            continue
        cmp = comparisons.get(f"P vs {system}") or {}
        inc = cmp.get("incorrect_acceptance") or {}
        boot = inc.get("paired_bootstrap") or {}
        rows.append({
            "ablation": system,
            "removed_component": removed,
            "apparent_repair_rate": (repair[system].get("acceptance_rate") or {}).get("estimate"),
            "apparent_repair_rate_P": (repair["P"].get("acceptance_rate") or {}).get("estimate"),
            "green_but_wrong_rate": (repair[system].get("green_but_wrong_rate") or {}).get("estimate"),
            "green_but_wrong_rate_P": (repair["P"].get("green_but_wrong_rate") or {}).get("estimate"),
            "unsafe_remediation_rate": (repair[system].get("unsafe_remediation_rate") or {}).get("estimate"),
            "verified_repair_rate": (repair[system].get("verified_repair_rate") or {}).get("estimate"),
            "verified_repair_rate_P": (repair["P"].get("verified_repair_rate") or {}).get("estimate"),
            "diff_incorrect_P_minus_ablation": boot.get("estimate"),
            "diff_low": boot.get("low"),
            "diff_high": boot.get("high"),
            "mcnemar_p": (inc.get("mcnemar") or {}).get("p_value"),
            "n_pairs": cmp.get("n_pairs"),
        })
    return rows


def results_rows(metrics: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Long-format table of every headline estimate with its interval."""
    rows = []
    for r in diagnosis_rows(metrics):
        for metric in ("accuracy", "macro_f1"):
            rows.append({"track": "diagnosis", "system": r["system"], "metric": metric, "estimate": r[metric],
                         "low": r[f"{metric}_low"], "high": r[f"{metric}_high"], "n": r["n_scored"],
                         "status": r["status"]})
        rows.append({"track": "diagnosis", "system": r["system"], "metric": "root_stage_accuracy_multi",
                     "estimate": r["root_stage_accuracy_multi"], "low": r["root_low"], "high": r["root_high"],
                     "n": r["root_n"], "status": r["status"]})
    for r in repair_rows(metrics):
        for rate in REPAIR_RATES:
            rows.append({"track": "repair", "system": r["system"], "metric": rate, "estimate": r[rate],
                         "low": r[f"{rate}_low"], "high": r[f"{rate}_high"], "n": r["n_cases"], "status": "RUN"})
    return rows


def summary(manifest: Mapping[str, Any], metrics: Mapping[str, Any], raw_dir: Path) -> dict[str, Any]:
    """Compact pointer to the latest run: provenance, scope and caveats. Not a claim."""
    try:
        source = raw_dir.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source = raw_dir.as_posix()
    return {
        "experiment_id": manifest["experiment_id"],
        "timestamp": manifest["timestamp"],
        "git_commit": manifest.get("git_commit"),
        "git_dirty": manifest.get("git_dirty"),
        "dataset_version": manifest.get("dataset_version"),
        "dataset_sha256": manifest.get("dataset_sha256"),
        "splits_evaluated": manifest.get("splits_evaluated"),
        "n_cases": {k: len(v) for k, v in (manifest.get("case_ids") or {}).items()},
        "model_provider": (manifest.get("model") or {}).get("provider"),
        "model_claim_eligible": (manifest.get("model") or {}).get("claim_eligible"),
        "diagnosis": {r["system"]: {"status": r["status"], "accuracy": r["accuracy"], "macro_f1": r["macro_f1"],
                                    "root_stage_accuracy_multi": r["root_stage_accuracy_multi"]}
                      for r in diagnosis_rows(metrics)},
        "repair": {r["system"]: {"green_but_wrong_rate": r["green_but_wrong_rate"],
                                 "verified_repair_rate": r["verified_repair_rate"],
                                 "acceptance_rate": r["acceptance_rate"],
                                 "human_escalation_rate": r["human_escalation_rate"]}
                   for r in repair_rows(metrics)},
        "fidelity": metrics.get("fidelity"),
        "annotation_issues": (metrics.get("annotation") or {}).get("count"),
        "raw_results": source,
        "caveats": [
            "All evaluated cases are synthetic or fixture cases authored by the system developer.",
            "Repair candidates are scripted, not model-generated.",
            "Local verification only; no real CI run confirms fixture repairs.",
            "External validation level: E0/E1 (see research/EXTERNAL_VALIDATION.md).",
        ],
    }


def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def manuscript_tables(manifest: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, str]:
    """Markdown tables keyed by manuscript marker name."""
    stamp = (f"_Generated from experiment `{manifest['experiment_id']}` (dataset {manifest.get('dataset_version')}, "
             f"splits {', '.join(manifest.get('splits_evaluated') or [])}, commit "
             f"`{(manifest.get('git_commit') or 'unknown')[:12]}`). Synthetic cases only._\n\n")
    diag = metrics.get("diagnosis") or {}
    diag_rows = []
    for system in ("B0", "B1", "B2", "B3", "B4"):
        m = diag.get(system)
        if not m:
            diag_rows.append([system, "not configured", "", "", ""])
        elif m.get("status") == "NOT_RUN":
            diag_rows.append([system, f"NOT RUN ({m.get('reason')})", "", "", ""])
        else:
            eligible = "" if m.get("claim_eligible") else " (not claim-eligible)"
            diag_rows.append([system + eligible, str(m.get("n_scored")), _ci(m.get("accuracy_ci")),
                              _ci(m.get("macro_f1_ci")), _ci(m.get("root_stage_accuracy_multi_failure"))])
    repair = metrics.get("repair") or {}
    rep_rows = [
        [system, str(m.get("n_cases")), _ci(m.get("green_but_wrong_rate")), _ci(m.get("unsafe_remediation_rate")),
         _ci(m.get("verified_repair_rate")), _ci(m.get("human_escalation_rate")), _ci(m.get("acceptance_rate"))]
        for system, m in sorted(repair.items())
    ]
    abl = [
        [r["ablation"], r["removed_component"], _fmt(r["apparent_repair_rate"]), _fmt(r["green_but_wrong_rate"]),
         f"{_fmt(r['diff_incorrect_P_minus_ablation'])} [{_fmt(r['diff_low'])}, {_fmt(r['diff_high'])}]",
         _fmt(r["mcnemar_p"])]
        for r in ablation_rows(metrics)
    ]
    gates = (metrics.get("candidate_gates") or {}).get("gates") or {}
    gate_rows = [
        [gate, _ci(g.get("accepted_incorrect")), _ci(g.get("rejected_correct"))]
        for gate, g in gates.items()
    ]
    taxonomy = [
        [r["error_class"], str(r["count"]), _fmt(r["percent_of_outcomes"], 1), ", ".join(r["systems"]) or "-",
         ", ".join(r["representative_case_ids"]) or "-"]
        for r in metrics.get("error_taxonomy") or [] if r["count"]
    ]
    fid = metrics.get("fidelity") or {}
    return {
        "diagnosis": stamp + _md_table(["System", "N scored", "Class accuracy [95% CI]", "Macro-F1 [95% CI]",
                                        "Root-stage accuracy, multi-failure [95% CI]"], diag_rows),
        "repair": stamp + (_md_table(["System", "N", "Incorrect acceptance", "Unsafe (fake fix) acceptance",
                                      "Verified repair", "Escalated", "Accepted"], rep_rows) if rep_rows else NOT_MEASURED)
        + (f"\n\nFidelity check (real P loop vs replayed rules): {fid.get('agree')}/{fid.get('checked')} cases agree."
           if fid else ""),
        "ablation": stamp + (_md_table(["Ablation", "Removed", "Apparent repair rate", "Incorrect acceptance",
                                        "P minus ablation, incorrect acceptance [95% CI]", "McNemar p"], abl)
                             if abl else NOT_MEASURED),
        "gates": stamp + (_md_table(["Acceptance rule", "Accepts incorrect green candidates", "Rejects correct ones"],
                                    gate_rows) if gate_rows else NOT_MEASURED),
        "errors": stamp + (_md_table(["Error class", "Count", "% of outcomes", "Systems", "Example cases"], taxonomy)
                           if taxonomy else "No classified errors."),
    }


def update_manuscript(path: Path, tables: Mapping[str, str]) -> list[str]:
    """Replace generated sections in the manuscript; return the names that were replaced."""
    text = path.read_text(encoding="utf-8")
    replaced = []
    for name, body in tables.items():
        pattern = re.compile(
            rf"(<!-- BEGIN GENERATED:{re.escape(name)} -->\n).*?(\n<!-- END GENERATED:{re.escape(name)} -->)", re.DOTALL
        )
        if pattern.search(text):
            text = pattern.sub(lambda m, body=body: m.group(1) + body + m.group(2), text)
            replaced.append(name)
    path.write_bytes(text.encode("utf-8"))
    return replaced


def write_processed(raw_dir: Path, processed_dir: Path = PROCESSED_DIR) -> dict[str, Path]:
    """Regenerate every processed file from one raw experiment directory."""
    manifest, metrics = load_raw(raw_dir)
    processed_dir.mkdir(parents=True, exist_ok=True)
    diag, rep, abl = diagnosis_rows(metrics), repair_rows(metrics), ablation_rows(metrics)
    tax = metrics.get("error_taxonomy") or []
    files = {
        "latest_summary.json": json.dumps(summary(manifest, metrics, raw_dir), indent=2, sort_keys=True) + "\n",
        "results_table.csv": _csv(results_rows(metrics), ["track", "system", "metric", "estimate", "low", "high", "n", "status"]),
        "diagnosis_metrics.csv": _csv(diag, list(diag[0]) if diag else ["system"]),
        "repair_metrics.csv": _csv(rep, list(rep[0]) if rep else ["system"]),
        "ablation_results.csv": _csv(abl, list(abl[0]) if abl else ["ablation"]),
        "error_taxonomy.csv": _csv(
            [{**r, "systems": ";".join(r["systems"]), "representative_case_ids": ";".join(r["representative_case_ids"])}
             for r in tax],
            ["error_class", "count", "percent_of_outcomes", "systems", "representative_case_ids", "mitigation"],
        ),
        "tables.md": "\n\n".join(f"## {name}\n\n{body}" for name, body in manuscript_tables(manifest, metrics).items()) + "\n",
    }
    written = {}
    for name, text in files.items():
        path = processed_dir / name
        path.write_bytes(text.encode("utf-8"))
        written[name] = path
    return written


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, help="raw experiment directory (default: latest)")
    parser.add_argument("--processed", type=Path, default=PROCESSED_DIR)
    parser.add_argument("--manuscript", type=Path, help="update generated sections of this manuscript")
    args = parser.parse_args(argv)
    raw_dir = args.raw or latest_raw_dir()
    written = write_processed(raw_dir, args.processed)
    print("\n".join(str(p) for p in written.values()))
    if args.manuscript:
        manifest, metrics = load_raw(raw_dir)
        names = update_manuscript(args.manuscript, manuscript_tables(manifest, metrics))
        print(f"manuscript sections updated: {', '.join(names) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
