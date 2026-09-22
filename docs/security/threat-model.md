# Threat model (lightweight)

Scope: governed CI repair agent operating on repository evidence and optional tools.

## Assets

- Source code and CI configuration
- Secrets in logs, env, and audit artifacts
- Integrity of policy/audit decisions
- Developer machines / CI runners

## Threats and controls

| Threat | Control in this repo |
| --- | --- |
| Prompt injection via logs/issues | Context builder redaction + bounded excerpts; no free-form shell from model text |
| Malicious repository content | Path sanitization; sandbox dry-run; policy escalate on sensitive paths |
| Arbitrary command execution | Typed tool registry; allowlisted/stub runners; no unrestricted shell tool |
| Secrets exposure | `audit.redact`, context secret scrubbing, avoid logging raw tokens |
| Tool misuse | Risk levels (`READ_ONLY`…`HUMAN_APPROVAL_REQUIRED`) + policy gate |
| Path traversal | Reject `..` and absolute paths in tools/sandbox |
| Patch escaping allowed scope | Proposal file list checked; sensitive markers escalate |
| Dependency poisoning | Out of band; provenance helpers exist under trust stack — treat as partial |
| Audit log leakage | Redaction on append; restrict artifact retention in ops |
| Compromised external tool responses | Prefer structured results; EvalForge adapter is injectable and optional |

## Residual risk

LLM providers (when enabled) remain an external trust boundary. Do not send secrets in prompts. Treat model output as untrusted until sandbox + policy + verification pass.
