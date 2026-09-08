# Live Semantic Merge Evaluation

This workflow converts semantic merge-conflict resolution from a capability claim into measured provider evidence.

## Run mode

The workflow is manual (`workflow_dispatch`) and requires the repository secret `OPENAI_API_KEY`. Normal pull-request CI remains deterministic and does not make paid model calls.

Inputs:

- `model` — OpenAI model id
- `trials` — repeated trials per held-out case

## Held-out corpus

`benchmark/live_semantic_merge_corpus.v1.json` contains synthetic semantic conflicts that are intentionally separate from the deterministic merge-conflict corpus. Do not tune prompts against the held-out corpus.

## Metrics

The generated `artifacts/live-semantic-merge-eval.json` records:

- verified resolution rate
- unsafe resolution rate
- escalation rate
- P50/P95 provider latency
- mean input/output tokens
- total tokens
- per-case confidence and resolved text

Dollar cost is deliberately not inferred from hard-coded pricing. Combine provider-reported token evidence with billing/export data if cost per verified resolution is reported externally.

## Claim discipline

This benchmark is live-model evidence over a small held-out synthetic corpus. It is not production incident data. A resolution is considered verified only when it passes deterministic required/forbidden semantic fragments and the confidence/safety admission checks.

The model remains proposal-only: it has no filesystem, shell, git, merge, deployment, or release authority.
