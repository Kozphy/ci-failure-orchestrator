"""Repository-relative locations used by the research harness."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "research"
SCHEMA_PATH = ROOT / "benchmark" / "research_case.schema.json"
DATASETS_DIR = RESEARCH_DIR / "datasets"
LOCK_PATH = DATASETS_DIR / "dataset.lock.json"
CANDIDATES_DIR = DATASETS_DIR / "candidates"
RESULTS_DIR = RESEARCH_DIR / "results"
RAW_DIR = RESULTS_DIR / "raw"
PROCESSED_DIR = RESULTS_DIR / "processed"
PROMPTS_DIR = RESEARCH_DIR / "prompts"
REGISTRY_PATH = ROOT / "baselines" / "registry.json"
CLAIMS_PATH = RESEARCH_DIR / "CLAIMS.md"
HOLDOUT_LEDGER_PATH = RESULTS_DIR / "holdout_ledger.jsonl"

SPLITS = ("development", "test", "holdout")
SPLIT_ALIASES = {"dev": "development", "development": "development", "test": "test", "holdout": "holdout"}
