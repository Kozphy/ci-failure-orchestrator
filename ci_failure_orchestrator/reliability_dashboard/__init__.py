"""Read-only reliability dashboard foundation: catalog, metrics, evidence integrity.

This package does not serve HTTP and does not run repairs. It aggregates local
artifacts already written by ``fix-repo`` and related commands. Values that
cannot be computed from those artifacts are returned as ``None`` with a reason.
"""

from .catalog import RunEvidenceRow, catalog_runs
from .integrity import IntegrityResult, verify_run_integrity, verify_tree_integrity
from .metrics import OverviewMetrics, build_overview_metrics

__all__ = [
    "IntegrityResult",
    "OverviewMetrics",
    "RunEvidenceRow",
    "build_overview_metrics",
    "catalog_runs",
    "verify_run_integrity",
    "verify_tree_integrity",
]
