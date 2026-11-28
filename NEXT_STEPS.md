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
[ ] 30 public prospects listed
[ ] 10 free “top 3 findings” snapshots drafted
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

**Next:** Phase B — 30 prospects.

---

## Phase B — 30 prospects

ICP: eng leads at small SaaS (3–30 engineers), GitHub Actions, ideally Python/pytest; also AI-coding teams with red/flaky CI.

Rules: public info only; no fake metrics; mark **unsure** when needed.

| # | repo | why it fits | likely buyer role | public Actions URL | channel | hook | contacted? |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | [ ] |
| 2 | | | | | | | [ ] |
| 3 | | | | | | | [ ] |
| 4 | | | | | | | [ ] |
| 5 | | | | | | | [ ] |
| 6 | | | | | | | [ ] |
| 7 | | | | | | | [ ] |
| 8 | | | | | | | [ ] |
| 9 | | | | | | | [ ] |
| 10 | | | | | | | [ ] |
| 11 | | | | | | | [ ] |
| 12 | | | | | | | [ ] |
| 13 | | | | | | | [ ] |
| 14 | | | | | | | [ ] |
| 15 | | | | | | | [ ] |
| 16 | | | | | | | [ ] |
| 17 | | | | | | | [ ] |
| 18 | | | | | | | [ ] |
| 19 | | | | | | | [ ] |
| 20 | | | | | | | [ ] |
| 21 | | | | | | | [ ] |
| 22 | | | | | | | [ ] |
| 23 | | | | | | | [ ] |
| 24 | | | | | | | [ ] |
| 25 | | | | | | | [ ] |
| 26 | | | | | | | [ ] |
| 27 | | | | | | | [ ] |
| 28 | | | | | | | [ ] |
| 29 | | | | | | | [ ] |
| 30 | | | | | | | [ ] |

Spot-check: open 5 Actions URLs. If 2+ are dead → fix the list before sending.

---

## Phase C — Top 10 free snapshots

For each: ≤3 findings from **public** data only, or `NEEDS_MANUAL_CHECK` + exact URL to open.

| # | repo | finding 1 | finding 2 | finding 3 | status |
| ---: | --- | --- | --- | --- | --- |
| 1 | | | | | draft / sent / NEEDS_MANUAL_CHECK |
| 2 | | | | | |
| 3 | | | | | |
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |
| 7 | | | | | |
| 8 | | | | | |
| 9 | | | | | |
| 10 | | | | | |

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
