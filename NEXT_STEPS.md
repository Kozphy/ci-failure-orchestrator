# Next steps — first paying customer

Goal: **one cleared US$299 payment** for a GitHub CI Reliability Audit.  
Optimize for revenue, not product features.

Status: **No paid order recorded yet.** Do not mark “done” without evidence (live link, sent message, or payment).

---

## Phase A links (filled)

```text
CAL_URL=https://cal.com/ixsa-z-ce9m2f/ci-reliability-audit-fit-check
STRIPE_URL=https://buy.stripe.com/5kQfZh3Zg9RAbh495Y9Zm00
CONTACT_EMAIL=dbdf0147@gmail.com
```

Cal event page loads publicly (verified). Confirm Stripe shows **US$299** in an **incognito** window before mass outreach.

---

## Definition of done (this week)

```text
[x] Phase A: Cal + Stripe + email URLs recorded (confirm Stripe $299 in incognito)
[x] README / audit docs: booking placeholders replaced
[x] 30 public prospects listed → business/phase-b-prospects.md
[x] 10 free “top 3 findings” starters drafted (workflow-level; logs = NEEDS_MANUAL_CHECK)
[ ] 10 outreach messages sent (not just drafted)
[ ] Tracker updated after each send
[ ] First US$299 received (or refund clock started after delivery)
```

**Real completion** = last box.

---

## Phase A — Open the cash register (you click)

Offer: **CI Reliability Audit**, US$299 one-time, refund if no actionable finding.  
Scope: 1 repo, ≤5 workflows, ≤30 recent runs, report in 3 business days.

### 1. Cal.com (15 min)

- [x] Event live: **CI Reliability Audit — fit check** (15 min)
- [x] `CAL_URL` set
- [ ] Re-verify in **incognito**: slots still bookable

### 2. Stripe Payment Link (US$299)

- [x] `STRIPE_URL` set
- [ ] Confirm in **incognito**: price shows **$299** (not $149)
- [ ] Refund one-liner visible in Stripe product/description if you use one

### 3. Contact email

- [x] `CONTACT_EMAIL` = dbdf0147@gmail.com
- [ ] Send yourself a test; confirm you receive it

### 4. Wire the repo

- [x] Placeholders replaced in README / audit docs / service offer / outreach
- [ ] Search repo for `YOUR-` → **0 hits** (after commit, on the branch you publish)
- [ ] Commit + push when ready (do not claim paid customers)

**Next:** Send top 10 outreach (Phase D). Full tables: [business/phase-b-prospects.md](business/phase-b-prospects.md).

---

## Phase B — 30 prospects

ICP: eng leads at small SaaS (3–30 engineers), GitHub Actions, ideally Python/pytest; also AI-coding teams with red/flaky CI.

**Status: list complete** in [business/phase-b-prospects.md](business/phase-b-prospects.md) (public Actions API, 2026-11-28).

Top send-first (strongest pay-fit judgment):

| # | repo | hook | contacted? |
| ---: | --- | --- | --- |
| 1 | apitally/apitally-py | Recurring **Tests** failures | [ ] |
| 2 | Subscribie/subscribie | Multi-workflow fail same timestamp | [ ] |
| 3 | pneumaticapp/pneumaticworkflow | Playwright trigger failures | [ ] |
| 4 | level09/readykit | Double **Checks** failure | [ ] |
| 5 | letsrevel/revel-backend | Docs + Test red | [ ] |
| 6 | dnotitia/akb | **backend-pytest** failures | [ ] |
| 7 | zmievsa/cadwyn | Package-update CI failing | [ ] |
| 8 | sandbox-quantum/switch | E2E scheduled + PR CI | [ ] |
| 9 | Cygnux-Labs/Tracekit | CI red 3× same day | [ ] |
| 10 | TracecatHQ/tracecat | Python tests failing today | [ ] |

Remaining 11–30 (and pay-fit notes): see prospects file. Spot-check 5 Actions URLs before sending.

---

## Phase C — Top 10 free snapshots

**Status: workflow-level starters done** in [business/phase-b-prospects.md](business/phase-b-prospects.md#phase-c--top-10-snapshot-starters-public-workflow-names-only).  
Deeper log lines still `NEEDS_MANUAL_CHECK` (open linked run URLs).

---

## Phase D — Outreach (must include)

Every message:

- US$299 fixed-scope audit  
- Refund if no actionable finding  
- **No personal access token in chat** (sanitized logs / public data preferred)  
- Soft CTA: reply for scope **or** book `CAL_URL`  
- Keep ~≤120 words  

Drafts live in `business/outreach.md` — personalize; do not send as generic blasts.

Channels: GitHub issue/discussion or email + optional LinkedIn DM.  
Do not spam communities that forbid promotion.

---

## Phase E — Tracker (keep private customer detail out of git)

Copy to a private sheet; update after every send.

| date | repo | channel | sent? | replied? | call? | paid? | notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | |

### Daily targets

| Day | Do | Exit criteria |
| ---: | --- | --- |
| 1 | Finish Phase A + send **10** msgs | 10× `sent?` = yes |
| 2 | Send **+10** | 20 total sent |
| 3 | Send **+10** | 30 total sent |
| 4–7 | Follow-ups + fit calls | ≥3 calls or 1 paid |
| Anytime | First payment → deliver in ≤3 days | Report accepted; ask quote + intro + Fix Sprint upsell |

Delivery SOP: `business/delivery-sop.md`  
Intake: `business/intake.md`  
Public-safe funnel template: `business/pilot-tracker.md`

---

## After first payment

- [ ] Deliver within 3 business days (scope in `business/service-offer.md`)
- [ ] Ask for: (1) one-sentence testimonial, (2) one intro, (3) “implement top 2 for $1–3k?”
- [ ] Log hours + fees (contribution math; not vanity pipeline)
- [ ] Only then consider Fix Sprint / monthly care as real offers

---

## Explicitly do **not** do (until paid demand)

- More LaunchDarkly / browser automation in the product repo  
- Hosted SaaS billing build-out  
- GitLab / multi-CI expansion  
- “CI Fix Sprint” as a public offer before audit demand  

Product repo: https://github.com/Kozphy/ci-failure-orchestrator

---

## Quick self-test (2 minutes)

1. Incognito → `CAL_URL` books  
2. Incognito → `STRIPE_URL` shows $299  
3. Email yourself at `CONTACT_EMAIL`  
4. Repo search `YOUR-` = 0 hits  
5. Tracker shows messages **sent**, not only drafted  

If 1–4 fail → not ready. If 1–4 pass but nothing sent → setup done, **sales not started**.
