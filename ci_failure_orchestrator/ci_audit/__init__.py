"""Read-only GitHub Actions reliability audit.

``collect`` pulls run and job metadata over a time window and writes a sanitized
export (no full logs). ``analyze`` turns an export into metrics and ranked
findings. ``report`` renders the findings as a Markdown audit report.

Nothing here writes to GitHub or to the audited repository.
"""

from .analyze import analyze_export
from .collect import EXPORT_SCHEMA, collect_export
from .report import render_report

__all__ = ["EXPORT_SCHEMA", "analyze_export", "collect_export", "render_report"]
