# Trust Control Plane Design

## Current architecture

The repository already separates repair proposal, disposable execution, independent evaluation, approval, bounded retries, state transitions, and hash-chained evidence. `RepairControlPlane` and `RepairCoordinator` govern CI repair and release decisions; `IsolatedWorkspace` and `SandboxRepairExecutor` provide temporary-copy execution; `HashChainedAuditLog` provides append-only evidence. Provider adapters can invoke real model/CLI providers, but privileged tool requests do not yet pass through a unified trust, data-boundary, and network-aware authorization gate.

## Proposed architecture

`TrustToolGateway` is the single entry point for privileged tool proposals. An `LLMClient` proposes a structured `RepairProposal`; a `TrustContextBuilder` resolves provider metadata, explicit data classification, jurisdiction/residency, layered network evidence, and local dependency provenance. `TrustPolicyEngine` evaluates ordered configuration rules and returns `ALLOW`, `DENY`, or `REQUIRE_APPROVAL` with evidence. Allowed actions execute through a disposable-copy sandbox, then pass distinct evaluation and verification stages. Failed attempts consume bounded time/cost/attempt budgets, must materially change before retry, and are policy-checked again. Terminal failures produce a human decision packet. Every lifecycle event is correlated, redacted, and hash chained.

This trust gate complements the existing delivery policy: the trust gate authorizes whether a tool may execute; the delivery policy determines whether a verified repair may progress toward release.

## Trust boundaries

- Model boundary: model output is untrusted input and carries no authorization.
- Context boundary: missing provider, classification, provenance, or network facts remain explicitly unknown.
- Policy boundary: only the gateway may turn a proposal into an executor call.
- Sandbox boundary: execution occurs in a temporary copy without `.git`; this protects the source tree but is not a container, syscall filter, or network namespace.
- Approval boundary: protected execution is paused until approval is supplied and recorded; explicit denies cannot be overridden.
- Verification boundary: process completion, evaluation, and target-condition verification are separate claims.
- Evidence boundary: structured metadata is redacted before append-only persistence; callers must not put raw sensitive content in proposals.

## Data flow

1. A real-provider adapter or deterministic test client emits a structured tool proposal.
2. The context builder validates classification and operation metadata, resolves provider configuration, probes network layers when applicable, and gathers dependency provenance.
3. Ordered policy rules evaluate data boundary, operation risk, provider knowledge, jurisdiction/residency constraints, and network evidence.
4. Denied actions terminate. Approval decisions pause unless prior human approval is present. Allowed actions enter a disposable workspace.
5. The executor performs the proposed action; an evaluator measures execution evidence; a verifier tests the target condition.
6. A retry requires remaining budget and a materially different proposal. Every retry rebuilds context and re-runs policy.
7. Verified success terminates; exhaustion or non-retryable failure emits a human-review packet.

## Assumptions

- Provider metadata and policy files are operator-controlled configuration.
- Data classification is supplied by the caller or remains `UNKNOWN`; it is never inferred downward from content.
- Jurisdictions are factual processing/residency inputs, not trust scores.
- Network probes are diagnostic only and never bypass access, authentication, or routing controls.
- The initial executor supports an allowlisted file-repair tool. Additional privileged tools must implement the executor protocol and remain gateway-owned.

## Non-goals

- Country-based allow/deny classification.
- Full IAM, distributed policy services, containers, network namespaces, SBOM/CVE/Sigstore/SLSA verification, or production secret storage.
- Authorization by the LLM or success based only on a zero exit code.
- Circumvention of censorship, authentication, enterprise controls, or legal restrictions.

## Migration plan

1. Introduce the trust gateway and use it for new privileged tool paths.
2. Adapt existing model providers to the `LLMClient` proposal contract.
3. Wrap existing repair executors behind the gateway while retaining delivery/release policy gates.
4. Expand provider and policy configuration under review, then add stronger sandbox and provenance backends as operational requirements justify them.
5. Deprecate direct privileged executor entry points after all callers have migrated and enforcement tests cover them.
