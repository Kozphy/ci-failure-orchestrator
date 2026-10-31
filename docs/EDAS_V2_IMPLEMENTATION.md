# EDAS v2.0 implementation and independent execution

The minimum viable implementation is `examples/edas/`, intentionally outside the canonical
service import graph. It is a synthetic, in-memory, single-process advisory kernel. It reuses
the canonical secret-pattern detector instead of introducing another redaction implementation.
It does not change the existing service's product scope or add a hosted dashboard.

## Existing components inspected before design

| Existing path | Compatible mechanism | Reuse decision |
| --- | --- | --- |
| `foundation/models.py` | Explicit missing-check states and heuristic-confidence label | Preserve conceptual separation; do not translate heuristic confidence into a Bayesian prior |
| `foundation/remediation.py` | One deterministic repair verdict from collected evidence | Preserve authority; strengthen predicates with regression tests |
| `foundation/evaluator.py` | Evidence-to-technical-result interface | Correct explicit failed checks being ignored by aggregate pass |
| `foundation/retry.py` | Finite attempts, repetition and no-progress stops | Reuse for canonical tests; EDAS advisory costs/deadlines have their own small policy |
| `foundation/state_machine.py` | Explicit transition graph and terminal automation states | Verify no restart from approval; new EDAS evidence uses revision invalidation |
| `foundation/sanitization.py` | Pattern-based secret detection/redaction | Import detector for synthetic payload rejection; no comprehensive privacy guarantee |
| `foundation/durable.py`, `server/` | Storage protocols, SQL worker/API architecture | Candidate future adapter boundary; no duplicate production persistence layer |
| `service/patches.py`, `foundation/verification_integrity.py` | Structural patch checks and verification-weakening analysis | Retain existing controls; test structural refusals |
| `service/ci_verification.py` | Real CI provider interface, distinction from local evidence | Preserve; required-workflow completeness and commit association need further assurance |
| `research_stats.py` | Wilson intervals and paired binary comparison | Reviewed, not imported: authored cases are not an IID sample justifying a population interval |
| `module_status.py` | Canonical vs experimental manifest | EDAS example remains outside canonical package; no new boundary exception |

## Components, schema and contracts

```text
examples/edas/
  core.py         Claim/Evidence/Case/Policy/Risk/Event, Engine, posterior, audit verification
  cases.json      17 manually specified synthetic decision cases and expected recommendations
  evaluate.py     Per-case evaluation, weak comparator, exact denominators and timing samples
tests/
  test_assurance_regressions.py   Canonical CI adversarial regression tests
  test_edas_reference.py         EDAS boundary/adversarial and 32-combination exhaustive checks
scripts/collect_engineering_evidence.py   Captured commands, outputs, exit codes, source hashes
docs/EDAS_V2_*.md                 Specification, research protocol, implementation and portfolio
evidence/edas-v2/                 Baseline/final outputs and source/CI observation record
```

| Logical module | MVP contract | Later implementation boundary |
| --- | --- | --- |
| Claim Registry | `register(Claim, owner, deadline) -> Case`; unique claim ID, alternatives/falsifier required | Versioned typed registry with domain profiles |
| Evidence Store | `add_evidence(Evidence, actor) -> Case`; frozen bytes, digest/size checks, synthetic-only declaration | Content-addressed encrypted store, acquisition manifest, retention/access policy |
| Provenance Validator | `Evidence.valid`; source/dependency IDs and logical capture time | Authenticated collectors, signatures, instrument validation and lineage graph |
| Hypothesis Evaluator | `posterior(priors, likelihoods, assumption_reference=...) -> mapping`; rejects invalid finite models | Validated model store, sensitivity analysis, selection/dependence modeling |
| Risk Assessment Engine | `Risk(severe, reversible, immediate_hazard)` supplied explicitly | Domain experts supply scenario-specific losses, likelihood bounds and authority |
| Decision Policy Engine | `evaluate(claim_id, risk, now=..., cost=...) -> Case`; versioned policy, budget/time stops | Reviewed configurable profiles; robust decision/VOI analysis |
| Human Review Gateway | `approve(..., reviewer, revision, policy_version, now) -> Case` | Authenticated role/authority service, independent assignment and consent |
| Audit Trail | Immutable `Event` tuples and `verify_audit(events, trusted_tip)` | Transactional append with trusted checkpoint, signing/key custody and replay |
| Evaluation Harness | `python -m examples.edas.evaluate`; nonzero on expectation mismatch | Preregistered hidden datasets, baselines, ablations and replication |
| Reporting Dashboard | JSON evaluation and Markdown evidence report | Read-only rendering of authorized summaries; escape untrusted text and enforce access |

Examples are Python API contracts, not network routes. `ValueError`, `KeyError` and
`PermissionError` are explicit refusal/missing-reference boundaries. `Case` is immutable;
successful changes increment revisions and emit events. Hypotheses remain separate from
recommendations. Input payloads are never executed, used as paths or passed to a model.

Security boundary: caller identities, source-group labels and attestations are trusted synthetic
inputs. The engine is not an authentication service; a caller can invent two reviewers or
attest a false observation. Neither digest checks nor a distinct-name check detects that.
No public deployment is supported. Private medical, financial, family or security records are
not sample data. A synthetic flag cannot reliably classify arbitrary private information.

## Exact reproducible commands

From a delivered checkout, no network or pytest is needed for these checks when the project's
existing runtime requirement PyYAML is present:

```bash
git rev-parse HEAD
git status --short --branch
python --version
python -m unittest discover -s tests -p test_assurance_regressions.py -v
python -m unittest discover -s tests -p test_edas_reference.py -v
python -m examples.edas.evaluate
python -m ci_failure_orchestrator.cli foundation-benchmark --compare-baseline
python scripts/collect_engineering_evidence.py --label replication
```

The collector intentionally exits nonzero if any required check fails or a tool is unavailable.
Do not convert that into a green status. Each output and exit code is retained in
`evidence/edas-v2/replication/`. The collector refuses to overwrite an existing label; archive
previous results or use a fresh checkout. Timing includes fixture construction and evaluation,
not provider, network, persistence or reviewer latency.

For the full repository checks in a network-enabled environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev,server]'
python -m pytest --cov=ci_failure_orchestrator --cov-report=term-missing
python -m ruff check examples/edas tests/test_edas_reference.py tests/test_assurance_regressions.py scripts/collect_engineering_evidence.py
python -m ruff check --select D101,D102,D103,D106,D417,D419 ci_failure_orchestrator
python -m mypy --version
python -m pip freeze > evidence-dependencies.txt
```

These installation requirements are ranges, not a historical lockfile. The captured local
environment used Python 3.12.14 and PyYAML 6.0.3. Exact full-suite historical reproducibility
requires a reviewed dependency lock and runner/container digest. A mypy version probe only
establishes tool availability, not type correctness; run the specific CI type-check command
in `.github/workflows/ci.yml` and add typed EDAS contracts before claiming static validation.

To reproduce pre-fix failures without undoing changes in the current branch:

```bash
git worktree add --detach ../edas-base 69ba500f53a4f492c876dd26636b9222d7e140ce
cp tests/test_assurance_regressions.py ../edas-base/tests/
cd ../edas-base
python -m unittest discover -s tests -p test_assurance_regressions.py -v
```

Expected baseline: 11 test methods, four failing methods with six assertion failures including
three failed-check subtests. Expected fixed version: 11/11 methods pass. This is a failing
test added to unchanged base source; the original base did not contain this test file.

The local base was reconstructed from GitHub API objects because shell clone/network requests
failed. All 537 file blob hashes, the complete tree hash and original signed commit object
hash matched. Local history is shallow. `evidence/edas-v2/source-and-ci.json` states the recovery
method and inspected ten-commit history window. A normal fresh clone is the preferred external
replication path. Do not confuse reconstruction with a new synthetic base commit.

## CI and quality gates

Existing pytest, coverage, lint/docstring/type gates remain present. The added CI step runs the
two unittest files and evaluation CLI, then uploads the **generated** JSON artifact and refuses
missing output. The CLI exits nonzero on fixture disagreement. It makes no manually asserted
pass artifact. GitHub run [41227967976](https://github.com/Kozphy/ci-failure-orchestrator/actions/runs/41227967976)
passed for implementation commit `8596a3f7f5dc17a53d48d5907eca6a8d95010d1c`: 855 tests,
72 subtests, the new unittest/evaluation step, PostgreSQL and Compose smoke jobs. Its scoped
lint, public-docstring and six-file type checks passed. This was observed separately from
local results; details are in `evidence/edas-v2/remote-ci.json`.

Next gates should enforce a reviewed dependency lock, full tests on supported Python versions,
source/fixture/policy hashes, no weakening of existing expectations, case-level baseline
comparison, unauthorized boundary imports, and a release approval independent of the author.
The existing benchmark baseline was compared, never updated. Process-isolation and actual
timeout-kill tests require a controlled environment; injected timeout flags do not establish
process containment.

Minimum docs for any later extension: threat/domain model, input/output schemas, authority and
privacy boundaries, assumptions, state/side-effect contract, reproducible test commands,
known failure modes, metric denominators, retention plan, rollback/recovery and independent
validation status. Keep dashboards read-only until those boundaries are enforced.
