#!/usr/bin/env python3
"""Print funnel metrics from prospects.csv. No network. No invented totals."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

CSV_PATH = Path(__file__).with_name("prospects.csv")
PRICE_USD = 299
YES = {"yes", "y", "true", "1"}


def is_yes(value: str) -> bool:
    return (value or "").strip().lower() in YES


def is_filled(row: dict[str, str]) -> bool:
    return any((row.get(k) or "").strip() for k in ("company", "repo", "notes"))


def main() -> int:
    if not CSV_PATH.is_file():
        print(f"Missing {CSV_PATH}", file=sys.stderr)
        return 1

    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    active = [r for r in rows if is_filled(r)]
    counts = Counter(
        {
            "rows_with_data": len(active),
            "leads_contacted": sum(1 for r in active if is_yes(r.get("outreach_sent", ""))),
            "replies": sum(1 for r in active if is_yes(r.get("replied", ""))),
            "calls_booked": sum(1 for r in active if is_yes(r.get("call_booked", ""))),
            "paid_audits": sum(1 for r in active if is_yes(r.get("paid", ""))),
        }
    )
    revenue = counts["paid_audits"] * PRICE_USD

    print("BrightPath Global — CI Reliability Audit CRM")
    print(f"Source: {CSV_PATH}")
    print("---")
    print(f"Leads Contacted: {counts['leads_contacted']}")
    print(f"Replies:         {counts['replies']}")
    print(f"Calls Booked:    {counts['calls_booked']}")
    print(f"Paid Audits:     {counts['paid_audits']}")
    print(f"Revenue (est.):  ${revenue}  # confirm in Stripe; {PRICE_USD} × paid")
    print(f"Rows with data:  {counts['rows_with_data']} / {len(rows)} slots")
    print("---")
    if counts["leads_contacted"] == 0:
        print("Next: send outreach. Drafts do not count.")
    elif counts["paid_audits"] == 0:
        print("Next: follow up replies → book fit check → close $299.")
    else:
        print("Next: deliver ≤3 business days; ask testimonial + intro.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
