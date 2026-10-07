"""Validate the research dataset: ``python -m research.validate_dataset``.

Exit code 0 means every check passed. ``--write-lock --dataset-version X`` freezes the current
splits; do that only deliberately, because it changes what "the test split" means.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .dataset import build_lock, load_dataset, read_lock, validate_dataset
from .paths import DATASETS_DIR, LOCK_PATH


def main(argv: list[str] | None = None) -> int:
    """Run validation and print a JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--datasets", type=Path, default=DATASETS_DIR)
    parser.add_argument("--lock", type=Path, default=LOCK_PATH)
    parser.add_argument("--write-lock", action="store_true", help="freeze the current splits into the lock file")
    parser.add_argument("--dataset-version", help="version recorded in the lock file (required with --write-lock)")
    parser.add_argument("--notes", default="")
    args = parser.parse_args(argv)

    dataset = load_dataset(args.datasets)
    if args.write_lock:
        if not args.dataset_version:
            parser.error("--write-lock requires --dataset-version")
        pre = validate_dataset(dataset, lock=None, require_lock=False)
        if not pre.ok:
            print(json.dumps(pre.to_dict(), indent=2))
            print("refusing to freeze a dataset that fails validation", file=sys.stderr)
            return 1
        frozen_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        lock = build_lock(dataset, version=args.dataset_version, frozen_at=frozen_at, notes=args.notes)
        args.lock.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = validate_dataset(dataset, lock=read_lock(args.lock))
    print(json.dumps(report.to_dict(), indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
