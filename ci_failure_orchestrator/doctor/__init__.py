"""CI Doctor product layer (``actions-doctor``): thin, read-only wrappers over the canonical engine."""

from .diagnose import Diagnosis, Finding, PolicyPreview, diagnose_log, diagnose_run
from .render import render_text

__all__ = ["Diagnosis", "Finding", "PolicyPreview", "diagnose_log", "diagnose_run", "render_text"]
