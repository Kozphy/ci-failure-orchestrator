# Recommendations — GitHub CI Reliability Audit

| Field | Value |
| --- | --- |
| Repository | `[OWNER/REPO]` |
| Engagement ID | `[ID]` |
| Date | `[YYYY-MM-DD]` |
| Max recommendations | 5 |

Recommendations are guidance. **Not executed** in the US$299 audit unless a separate SOW is signed.

---

## Recommendation card (copy per item)

### R-[N]: `[imperative title]`

| Field | Value |
| --- | --- |
| Addresses finding | `F-[N]` |
| Priority | `P0` / `P1` / `P2` |
| Effort | `S` (<2h) / `M` (half day) / `L` (multi-day) |
| Risk if ignored | `[1–2 sentences]` |

**Do this**

1. …
2. …
3. …

**Done when**

- [ ] Observable check (e.g. “workflow X green on next 3 pushes” or “flake quarantined”)

**Do not**

- Weaken tests, skip failures, or lower coverage gates to get green
- Paste PATs into chat or commit secrets

**Optional BrightPath help**

`not offered in this audit` / `available as separate quote` — only after paid demand or explicit client ask.

---

## Priority order (paste into audit report §6)

| Rec | Finding | Priority | Effort | One-line action |
| --- | --- | --- | --- | --- |
| R-1 | F-1 | P0 | S | |
| R-2 | | | | |
| R-3 | | | | |
| R-4 | | | | |
| R-5 | | | | |

---

## Writing rules

- Every recommendation maps to a finding with evidence.
- Prefer the smallest change that reduces reruns or false confidence.
- If unsure, recommend measurement (pin failing test, add retry budget, record flake rate) instead of a speculative rewrite.
- Cap at five. Extra ideas go in “Backlog (not scoped)” below — unlabeled as deliverables.

### Backlog (not scoped)

-
