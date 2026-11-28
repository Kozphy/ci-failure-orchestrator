# BrightPath Global — lightweight CRM (CSV)

**Purpose:** Track leads for the GitHub CI Reliability Audit (US$299).  
**Stack:** One CSV. No database. No SaaS CRM required.

**Rules:** Do not invent customers, replies, calls, payments, or case studies. Empty cells mean unknown / not done. Only mark `yes` when you have evidence.

Offer links (keep in sync with README / service-offer):

- Fit check: https://cal.com/ixsa-z-ce9m2f/ci-reliability-audit-fit-check
- Pay: https://buy.stripe.com/5kQfZh3Zg9RAbh495Y9Zm00
- Email: dbdf0147@gmail.com

Prospect research (not the CRM): `business/phase-b-prospects.md`. Copy a repo into `prospects.csv` when you decide to contact it.

---

## Files

| File | Role |
| --- | --- |
| `prospects.csv` | Lead pipeline (edit in Excel, Google Sheets, or any editor) |
| `metrics.py` | Prints today's funnel counts from the CSV |
| `DAILY_METRICS.md` | Manual scoreboard — update after running `metrics.py` or counting by hand |
| `../templates/` | Delivery + case-study templates (fill only after a real engagement) |

---

## Column definitions

| Column | Allowed values | Meaning |
| --- | --- | --- |
| `company` | text | Org / product name (may match GitHub org) |
| `repo` | `owner/name` | Exact GitHub repository |
| `engineering_manager` | text or blank | Buyer name if known; leave blank if unknown |
| `github_actions_used` | `yes` / `no` / `unknown` | Confirmed GHA usage |
| `contact_method` | `github_issue` / `email` / `linkedin` / `other` | How you reached them |
| `outreach_sent` | `yes` / `no` | Message actually sent (drafts stay `no`) |
| `replied` | `yes` / `no` | They replied to you |
| `call_booked` | `yes` / `no` | Fit-check on Cal.com (or equivalent) booked |
| `paid` | `yes` / `no` | Stripe payment cleared (not “clicked pay”) |
| `notes` | text | Hook, date sent, next follow-up — no secrets / no PATs |

Use lowercase `yes` / `no`. Blank = not set.

---

## Daily workflow (10 minutes)

1. Open `prospects.csv`.
2. Fill one row per lead you will contact (or copy from Phase B list).
3. After sending: set `outreach_sent=yes` and add date in `notes`.
4. When they reply / book / pay: flip the matching column to `yes` the same day.
5. Run metrics:

```bash
python business/crm/metrics.py
```

6. Copy the printed totals into `DAILY_METRICS.md` under today's date.

---

## Success metrics (baseline)

| Metric | Formula in CSV | Current target |
| --- | --- | --- |
| Leads Contacted | count `outreach_sent=yes` | 10 today → 30 this week |
| Replies | count `replied=yes` | any > 0 |
| Calls Booked | count `call_booked=yes` | ≥ 1 this week |
| Paid Audits | count `paid=yes` | first `yes` = first customer |
| Revenue | `paid=yes` × US$299 (manual; confirm in Stripe) | first US$299 |

Stars, features, and agents do not count.

---

## Privacy

- Prefer a **private** copy of this CSV (Google Sheet / local only) for real names and emails.
- If this folder is public on GitHub: keep rows empty of PII; store private CRM outside the repo.
- Never paste personal access tokens into `notes`.

---

## What not to do

- Do not build a database, dashboard app, or CRM integration before first paid audit.
- Do not mark `paid=yes` without a cleared Stripe payment.
- Do not fill case-study templates with hypothetical customers.
