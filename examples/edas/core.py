"""Small assurance kernel. Integrity checks establish consistency, not truth.

Caller-supplied actor identities and source attestations are test inputs, not
authentication. No medical, legal, financial or production decisions are executed.
"""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from enum import Enum

from ci_failure_orchestrator.foundation.sanitization import contains_high_confidence_secret


def identifier(value):
    """Accept synthetic identifiers, never paths, prose or contact details."""
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value) is None:
        raise ValueError("invalid synthetic identifier")
    return value


def finite_nonnegative(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative number required")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class State(str, Enum):
    OPEN = "OPEN"
    READY = "READY"
    REVIEW = "REVIEW"
    DECIDED = "DECIDED"
    REOPENED = "REOPENED"
    UNRESOLVED = "UNRESOLVED"


class Recommendation(str, Enum):
    INVESTIGATE = "INVESTIGATE"
    REVIEW = "REVIEW"
    PROTECT = "PROTECT"
    DEFER = "DEFER"
    PROCEED_REVERSIBLY = "PROCEED_REVERSIBLY"


@dataclass(frozen=True)
class Claim:
    claim_id: str
    statement: str
    scope: str
    hypotheses: tuple[str, ...]
    falsifier: str

    def __post_init__(self):
        identifier(self.claim_id)
        if not all(isinstance(x, str) and x.strip() for x in (self.statement, self.scope, self.falsifier)):
            raise ValueError("statement, scope and falsifier required")
        if not isinstance(self.hypotheses, tuple) or len(set(self.hypotheses)) < 2:
            raise ValueError("at least two distinct hypotheses required")
        for hypothesis in self.hypotheses:
            identifier(hypothesis)


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    claim_id: str
    source_id: str
    dependency_group: str
    payload: bytes
    sha256: str
    stance: str  # supports | contradicts | neutral
    captured_at: float  # synthetic logical clock, not a wall-clock attestation
    attested: bool = False
    synthetic: bool = True

    def __post_init__(self):
        for value in (self.evidence_id, self.claim_id, self.source_id, self.dependency_group):
            identifier(value)
        if type(self.payload) is not bytes or not self.payload or len(self.payload) > 4096:
            raise ValueError("bounded nonempty bytes required")
        if type(self.attested) is not bool or self.synthetic is not True:
            raise ValueError("this example accepts synthetic evidence only")
        if self.stance not in {"supports", "contradicts", "neutral"}:
            raise ValueError("invalid stance")
        finite_nonnegative(self.captured_at)
        if contains_high_confidence_secret(self.payload.decode("utf-8", errors="replace")):
            raise ValueError("secret-shaped payload rejected")
        if not self.valid:
            raise ValueError("digest mismatch")

    @property
    def valid(self):
        return hashlib.sha256(self.payload).hexdigest() == self.sha256


@dataclass(frozen=True)
class Policy:
    version: str = "edas-v2-demo-1"
    max_attempts: int = 3
    max_cost: float = 5.0  # synthetic cost units, not currency
    max_age: float = 20.0

    def __post_init__(self):
        identifier(self.version)
        if type(self.max_attempts) is not int or self.max_attempts < 1:
            raise ValueError("positive integer attempt limit required")
        finite_nonnegative(self.max_cost)
        finite_nonnegative(self.max_age)


@dataclass(frozen=True)
class Risk:
    severe: bool = False
    reversible: bool = True
    immediate_hazard: bool = False

    def __post_init__(self):
        if any(type(x) is not bool for x in asdict(self).values()):
            raise ValueError("explicit Boolean risk inputs required")


@dataclass(frozen=True)
class Case:
    claim: Claim
    owner: str
    deadline: float
    state: State = State.OPEN
    revision: int = 0
    evidence_ids: tuple[str, ...] = ()
    attempts: int = 0
    spent: float = 0.0
    approved_by: str | None = None
    recommendation: Recommendation | None = None
    last_now: float = 0.0


@dataclass(frozen=True)
class Event:
    sequence: int
    case_id: str
    revision: int
    action: str
    state: str
    actor: str
    policy_version: str
    previous_hash: str
    context_hash: str
    event_hash: str


def verify_audit(events, trusted_tip):
    """Verify linkage against a separately retained tip; no signer authenticity implied."""
    previous = "0" * 64
    for sequence, event in enumerate(events, 1):
        body = asdict(event)
        observed = body.pop("event_hash")
        if event.sequence != sequence or event.previous_hash != previous or digest(body) != observed:
            return False
        previous = observed
    return previous == trusted_tip


class Engine:
    """Single-process advisory engine. No public HTTP API, persistence or action executor."""

    def __init__(self, policy=Policy()):
        self.policy = policy
        self._cases = {}
        self._evidence = {}
        self._audit = ()

    @property
    def audit(self):
        return self._audit

    @property
    def tip(self):
        return self._audit[-1].event_hash if self._audit else "0" * 64

    def _record(self, case, action, actor):
        identifier(actor)
        body = dict(sequence=len(self._audit) + 1, case_id=case.claim.claim_id,
                    revision=case.revision, action=action, state=case.state.value,
                    actor=actor, policy_version=self.policy.version, previous_hash=self.tip,
                    context_hash=digest({"case": asdict(case), "evidence": [
                        {key: value for key, value in asdict(self._evidence[e]).items() if key != "payload"}
                        for e in case.evidence_ids
                    ]}))
        self._audit += (Event(**body, event_hash=digest(body)),)
        self._cases[case.claim.claim_id] = case
        return case

    def register(self, claim, owner, deadline):
        identifier(owner)
        finite_nonnegative(deadline)
        if claim.claim_id in self._cases:
            raise ValueError("duplicate claim")
        return self._record(Case(claim, owner, deadline), "REGISTER", owner)

    def case(self, claim_id):
        return self._cases[claim_id]

    def add_evidence(self, evidence, actor):
        case = self.case(evidence.claim_id)
        identifier(actor)
        if actor != case.owner:
            raise PermissionError("only case owner may submit evidence")
        if evidence.evidence_id in self._evidence:
            raise ValueError("duplicate evidence identifier")
        if not evidence.valid:
            raise ValueError("digest mismatch")
        state = State.REOPENED if case.state in {State.DECIDED, State.UNRESOLVED} else State.OPEN
        updated = replace(case, evidence_ids=case.evidence_ids + (evidence.evidence_id,),
                          revision=case.revision + 1, state=state,
                          approved_by=None, recommendation=None)
        self._evidence[evidence.evidence_id] = evidence
        return self._record(updated, "ADD_EVIDENCE", actor)

    def evaluate(self, claim_id, risk, *, now, cost=0.0):
        case = self.case(claim_id)
        finite_nonnegative(now)
        finite_nonnegative(cost)
        if now < case.last_now:
            raise ValueError("logical clock moved backwards")
        if case.state is State.DECIDED and not risk.immediate_hazard:
            raise ValueError("add new evidence before revisiting a decided case")
        if case.state is State.UNRESOLVED and not risk.immediate_hazard:
            return case
        if risk.immediate_hazard:
            state, advice = State.REVIEW, Recommendation.PROTECT
        elif now >= case.deadline or case.attempts >= self.policy.max_attempts or cost > self.policy.max_cost - case.spent:
            state, advice = State.UNRESOLVED, Recommendation.DEFER
        else:
            evidence = tuple(self._evidence[e] for e in case.evidence_ids)
            sound = bool(evidence) and all(e.valid and e.attested and
                                           0 <= now - e.captured_at <= self.policy.max_age for e in evidence)
            conflicting = any(e.stance == "contradicts" for e in evidence)
            independent = len({e.dependency_group for e in evidence}) >= 2
            if conflicting or risk.severe or not risk.reversible:
                state, advice = State.REVIEW, Recommendation.REVIEW
            elif not sound or not independent or not any(e.stance == "supports" for e in evidence):
                state, advice = State.OPEN, Recommendation.INVESTIGATE
            else:
                state, advice = State.READY, Recommendation.PROCEED_REVERSIBLY
        # A refused budget request never consumes more than the configured cap.
        spent = case.spent if advice in {Recommendation.DEFER, Recommendation.PROTECT} else case.spent + cost
        attempts = case.attempts + int(advice not in {Recommendation.DEFER, Recommendation.PROTECT})
        return self._record(replace(case, state=state, recommendation=advice,
                                    revision=case.revision + 1, approved_by=None,
                                    spent=spent, attempts=attempts, last_now=now), "EVALUATE", case.owner)

    def approve(self, claim_id, reviewer, *, revision, policy_version, now):
        case = self.case(claim_id)
        identifier(reviewer)
        finite_nonnegative(now)
        if now < case.last_now:
            raise ValueError("logical clock moved backwards")
        if reviewer == case.owner:
            raise PermissionError("reviewer must differ from proposer")
        if revision != case.revision or policy_version != self.policy.version:
            raise ValueError("stale approval")
        if case.state is not State.READY or now >= case.deadline:
            raise ValueError("not eligible for decision")
        evidence = [self._evidence[e] for e in case.evidence_ids]
        if not evidence or not all(e.valid and e.attested and
                                   0 <= now - e.captured_at <= self.policy.max_age for e in evidence):
            raise ValueError("evidence invalid or stale")
        return self._record(replace(case, state=State.DECIDED, approved_by=reviewer,
                                    revision=case.revision + 1, last_now=now), "APPROVE_ADVICE", reviewer)


def posterior(priors, likelihoods, *, assumption_reference):
    """One supplied likelihood model, not an automatic evidence-to-probability conversion."""
    if not isinstance(assumption_reference, str) or not assumption_reference.strip():
        raise ValueError("prior and likelihood provenance must be documented")
    if not priors or set(priors) != set(likelihoods):
        raise ValueError("matching hypotheses required")
    for value in (*priors.values(), *likelihoods.values()):
        finite_nonnegative(value)
        if value > 1:
            raise ValueError("probability outside [0,1]")
    if not math.isclose(sum(priors.values()), 1.0, abs_tol=1e-12):
        raise ValueError("priors must sum to one")
    weights = {h: priors[h] * likelihoods[h] for h in priors}
    normalizer = sum(weights.values())
    if normalizer <= 0:
        raise ValueError("observation impossible under supplied model")
    return {h: weight / normalizer for h, weight in weights.items()}
