# Toolkit roadmap

v0.1 is this branch: one CI diagnosis skill, one read-only tool, local tests, and an optional activation log.

## v0.2 candidates

These are not started.

1. Decide whether draft PR #17's extra read-only tools (reliability export summary and stored evidence) should join this plugin. They must stay read-only.
2. A host test that launches Cursor or another MCP client. This slice only drives stdio from pytest.
3. AI Governance plugin: a separate package that calls EvalForge graders. Requires a license decision because EvalForge is proprietary, plus a fresh EvalForge test run. Do not start it from this branch.
4. FinOps plugin: no cost engine exists in ci-failure-orchestrator or EvalForge for CI minutes. Do not add a plugin until a measured data source exists.
5. Replace placeholder booking links before any public paid offer. That is documentation, not this server.

No item above is a claim that a customer, a revenue number, or a production deployment exists.
