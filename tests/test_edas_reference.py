"""Adversarial, boundary and bounded exhaustive tests of the synthetic example."""

import hashlib
import itertools
import json
import math
import unittest
from dataclasses import replace

from examples.edas.core import (
    Claim, Engine, Evidence, Policy, Recommendation, Risk, State, posterior, verify_audit,
)
from examples.edas.evaluate import CASES, run_case


def evidence(eid="e1", group="g1", **changes):
    payload = b"synthetic measurement"
    values = dict(evidence_id=eid, claim_id="c1", source_id="source1", dependency_group=group,
                  payload=payload, sha256=hashlib.sha256(payload).hexdigest(), stance="supports",
                  captured_at=1.0, attested=True)
    values.update(changes)
    return Evidence(**values)


def engine(policy=Policy(), *, full=False):
    result = Engine(policy)
    result.register(Claim("c1", "Synthetic repair preserves behavior", "fixture build",
                          ("repair", "test_gap", "other"), "target regresses"), "owner", 100)
    if full:
        result.add_evidence(evidence(), "owner")
        result.add_evidence(evidence("e2", "g2"), "owner")
    return result


class EDASAdversarialTests(unittest.TestCase):
    def test_authored_evaluation_cases(self):
        for case in json.loads(CASES.read_text(encoding="utf-8")):
            with self.subTest(case_id=case["id"]):
                self.assertEqual(run_case(case).recommendation.value, case["expected"])

    def test_fabricated_unattested_evidence_does_not_qualify(self):
        e = engine()
        e.add_evidence(evidence(attested=False), "owner")
        e.add_evidence(evidence("e2", "g2"), "owner")
        self.assertEqual(e.evaluate("c1", Risk(), now=2).recommendation, Recommendation.INVESTIGATE)

    def test_missing_evidence_is_unknown_not_wrongdoing(self):
        e = engine()
        self.assertEqual(e.evaluate("c1", Risk(), now=2).recommendation, Recommendation.INVESTIGATE)
        with self.assertRaises(ValueError):
            e.approve("c1", "reviewer", revision=e.case("c1").revision, policy_version=e.policy.version, now=2)

    def test_contradiction_requires_review(self):
        e = engine(full=True)
        e.add_evidence(evidence("e3", "g3", stance="contradicts"), "owner")
        self.assertEqual(e.evaluate("c1", Risk(), now=2).recommendation, Recommendation.REVIEW)

    def test_correlated_copies_count_as_one_group(self):
        e = engine()
        for eid in ("e1", "e2", "e3"):
            e.add_evidence(evidence(eid, "same_group"), "owner")
        self.assertEqual(e.evaluate("c1", Risk(), now=2).state, State.OPEN)

    def test_confirmation_bias_requires_alternatives_and_falsifier(self):
        for hypotheses, falsifier in ((("favorite",), "counterexample"), (("a", "b"), "")):
            with self.subTest(hypotheses=hypotheses, falsifier=falsifier), self.assertRaises(ValueError):
                Claim("c1", "synthetic", "fixture", hypotheses, falsifier)

    def test_authority_label_does_not_replace_independent_sources(self):
        e = engine()
        e.add_evidence(evidence(source_id="prestigious_authority"), "owner")
        self.assertEqual(e.evaluate("c1", Risk(), now=2).state, State.OPEN)

    def test_extreme_and_nonfinite_probability_inputs_rejected(self):
        for bad in (1.2, -0.1, math.nan, math.inf, True):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                posterior({"a": bad, "b": 0.5}, {"a": 0.7, "b": 0.1}, assumption_reference="synthetic")

    def test_unsupported_likelihood_provenance_rejected(self):
        with self.assertRaises(ValueError):
            posterior({"a": 0.5, "b": 0.5}, {"a": 0.9, "b": 0.1}, assumption_reference="")

    def test_bayesian_example_and_impossible_observation(self):
        result = posterior({"regression": 0.1, "transient": 0.9},
                           {"regression": 0.8, "transient": 0.1}, assumption_reference="synthetic worked example")
        self.assertAlmostEqual(result["regression"], 8 / 17)
        self.assertAlmostEqual(sum(result.values()), 1)
        with self.assertRaises(ValueError):
            posterior({"a": 1.0}, {"a": 0.0}, assumption_reference="synthetic")

    def test_evidence_tampering_detected(self):
        with self.assertRaises(ValueError):
            replace(evidence(), payload=b"tampered")

    def test_non_synthetic_and_secret_shaped_payloads_refused(self):
        with self.assertRaises(ValueError):
            evidence(synthetic=False)
        payload = ("ghp_" + "a" * 40).encode()
        with self.assertRaises(ValueError):
            evidence(payload=payload, sha256=hashlib.sha256(payload).hexdigest())

    def test_public_audit_contains_no_claim_or_payload_text(self):
        e = engine(full=True)
        self.assertNotIn("synthetic measurement", repr(e.audit))
        self.assertNotIn("Synthetic repair", repr(e.audit))

    def test_high_stakes_accusation_never_automatically_authorized(self):
        e = engine(full=True)
        self.assertEqual(e.evaluate("c1", Risk(severe=True, reversible=False), now=2).state, State.REVIEW)

    def test_low_risk_positive_control_avoids_unnecessary_escalation(self):
        e = engine(full=True)
        self.assertEqual(e.evaluate("c1", Risk(), now=2).state, State.READY)

    def test_excessive_cost_defers_without_spending(self):
        e = engine(full=True)
        case = e.evaluate("c1", Risk(), now=2, cost=6)
        self.assertEqual((case.state, case.spent, case.attempts), (State.UNRESOLVED, 0, 0))

    def test_retry_exhaustion_defers(self):
        e = engine(Policy(max_attempts=1))
        self.assertEqual(e.evaluate("c1", Risk(), now=2).state, State.OPEN)
        self.assertEqual(e.evaluate("c1", Risk(), now=3).state, State.UNRESOLVED)

    def test_deadline_boundary_and_missing_evidence_never_pass(self):
        e = engine(full=True)
        self.assertEqual(e.evaluate("c1", Risk(), now=100).state, State.UNRESOLVED)

    def test_immediate_safety_action_does_not_require_proof(self):
        e = engine()
        self.assertEqual(e.evaluate("c1", Risk(immediate_hazard=True), now=100).recommendation,
                         Recommendation.PROTECT)
        self.assertIsNone(e.case("c1").approved_by)
        # Reaching an ordinary investigation stop must not suppress later safety advice.
        e = engine()
        self.assertEqual(e.evaluate("c1", Risk(), now=100).state, State.UNRESOLVED)
        self.assertEqual(e.evaluate("c1", Risk(immediate_hazard=True), now=101).recommendation,
                         Recommendation.PROTECT)

    def test_stale_or_self_approval_refused(self):
        e = engine(full=True)
        c = e.evaluate("c1", Risk(), now=2)
        with self.assertRaises(PermissionError):
            e.approve("c1", "owner", revision=c.revision, policy_version=e.policy.version, now=2)
        for revision, version in ((c.revision - 1, e.policy.version), (c.revision, "old_policy")):
            with self.subTest(revision=revision, version=version), self.assertRaises(ValueError):
                e.approve("c1", "reviewer", revision=revision, policy_version=version, now=2)

    def test_new_contradiction_invalidates_decision(self):
        e = engine(full=True)
        c = e.evaluate("c1", Risk(), now=2)
        self.assertEqual(e.approve("c1", "reviewer", revision=c.revision,
                                  policy_version=e.policy.version, now=2).state, State.DECIDED)
        c = e.add_evidence(evidence("e3", "g3", stance="contradicts"), "owner")
        self.assertEqual(c.state, State.REOPENED)
        self.assertIsNone(c.approved_by)
        self.assertEqual(e.evaluate("c1", Risk(), now=3).state, State.REVIEW)

    def test_audit_mutation_reorder_and_truncation_detected_against_tip(self):
        e = engine(full=True)
        self.assertTrue(verify_audit(e.audit, e.tip))
        self.assertFalse(verify_audit(e.audit[:-1], e.tip))
        self.assertFalse(verify_audit(tuple(reversed(e.audit)), e.tip))
        self.assertFalse(verify_audit((replace(e.audit[0], actor="attacker"), *e.audit[1:]), e.tip))

    def test_stale_future_and_backward_clock_inputs_refused(self):
        for captured in (0, 100):
            e = engine()
            e.add_evidence(evidence(captured_at=captured), "owner")
            e.add_evidence(evidence("e2", "g2", captured_at=captured), "owner")
            self.assertEqual(e.evaluate("c1", Risk(), now=30).state, State.OPEN)
        e = engine(full=True)
        c = e.evaluate("c1", Risk(), now=2)
        with self.assertRaises(ValueError):
            e.approve("c1", "reviewer", revision=c.revision, policy_version=e.policy.version, now=30)
        with self.assertRaises(ValueError):
            e.evaluate("c1", Risk(), now=1)

    def test_rejected_mutations_do_not_append_audit_or_change_revision(self):
        e = engine(full=True)
        previous = e.case("c1"), e.tip, e.audit
        for bad in (math.nan, -1, math.inf):
            with self.assertRaises(ValueError):
                e.evaluate("c1", Risk(), now=2, cost=bad)
        with self.assertRaises(ValueError):
            e.add_evidence(evidence(), "owner")
        with self.assertRaises(PermissionError):
            e.add_evidence(evidence("e3", "g3"), "attacker")
        self.assertEqual(previous, (e.case("c1"), e.tip, e.audit))

    def test_bounded_exhaustive_ready_requires_all_controls(self):
        # 2^5 = 32 combinations; independent oracle, no random seed or sampling claim.
        for attested, independent, contradicts, severe, reversible in itertools.product((False, True), repeat=5):
            e = engine()
            e.add_evidence(evidence(attested=attested), "owner")
            e.add_evidence(evidence("e2", "g2" if independent else "g1",
                                    attested=attested, stance="contradicts" if contradicts else "supports"), "owner")
            c = e.evaluate("c1", Risk(severe=severe, reversible=reversible), now=2)
            expected = attested and independent and not contradicts and not severe and reversible
            with self.subTest(inputs=(attested, independent, contradicts, severe, reversible)):
                self.assertEqual(c.state is State.READY, expected)
                self.assertLessEqual(c.attempts, e.policy.max_attempts)
                self.assertLessEqual(c.spent, e.policy.max_cost)
                self.assertTrue(verify_audit(e.audit, e.tip))


if __name__ == "__main__":
    unittest.main()
