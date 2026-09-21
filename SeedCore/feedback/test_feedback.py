"""
test_feedback.py — Test suite for the Arbitrator Feedback System.

Tests are organized by component:
    TestFeedbackModels          — roles, trust matrix, permissions, core dataclasses
    TestTrustLedger             — earned trust tracking, persistence, events
    TestFeedbackValidator       — validation rules by type and role
    TestFeedbackAggregator      — aggregation, finding signals, net sentiment
    TestFeedbackProcessor       — full pipeline integration
    TestEscalation              — escalation threshold mechanics
    TestTrustLoop               — trust event → weight update feedback loop
    TestAuditIntegration        — audit log entries from feedback events
    TestEndToEnd                — complete realistic submission scenarios

Run with:
    python -m unittest SeedCore/tests/test_feedback.py -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.feedback import (
    FeedbackRole, FeedbackType, FeedbackStatus,
    FeedbackEntry, FeedbackSummary, FindingSignal,
    Submitter, get_trust_weight, can_submit,
    ROLE_DOMAIN_TRUST, ROLE_PERMISSIONS,
    TrustLedger, TrustEvent, SubmitterRecord,
    FeedbackValidator, ValidationResult,
    FeedbackAggregator,
    FeedbackProcessor, FeedbackResult,
)
from SeedCore.audit_log.log import AuditLog
from SeedCore.audit_log.models import EntryKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_submitter(
    role: FeedbackRole = FeedbackRole.CITIZEN,
    sid: str = "user-001",
    verified: bool = False,
    earned_trust: dict = None,
) -> Submitter:
    return Submitter(
        submitter_id=sid,
        role=role,
        earned_trust=earned_trust or {},
        verified=verified,
    )


def make_expert(sid: str = "expert-001", domain: str = "economic") -> Submitter:
    return Submitter(
        submitter_id=sid,
        role=FeedbackRole.DOMAIN_EXPERT,
        domain_expertise=[domain],
    )


def make_challenge(
    map_id: str = "map-001",
    session_id: str = "sess-001",
    submitter: Submitter = None,
    finding_id: str = "finding-abc",
    domain: str = "economic",
    content: str = None,
) -> FeedbackEntry:
    if submitter is None:
        submitter = make_expert()
    return FeedbackEntry(
        map_id=map_id,
        session_id=session_id,
        submitter=submitter,
        feedback_type=FeedbackType.FINDING_CHALLENGE,
        content=content or (
            "The harm estimate is overstated because the underlying "
            "model does not account for substitution effects that "
            "mitigate price pressure in this sector."
        ),
        target_finding_id=finding_id,
        target_domain=domain,
        citations=["Acemoglu & Robinson (2012)", "IMF WP 2023/142"],
    )


def make_support(
    map_id: str = "map-001",
    session_id: str = "sess-001",
    submitter: Submitter = None,
    finding_id: str = "finding-abc",
) -> FeedbackEntry:
    if submitter is None:
        submitter = make_expert(sid="expert-002")
    return FeedbackEntry(
        map_id=map_id,
        session_id=session_id,
        submitter=submitter,
        feedback_type=FeedbackType.FINDING_SUPPORT,
        content="This finding aligns with our independent analysis and "
                "the documented empirical literature on this mechanism.",
        target_finding_id=finding_id,
        target_domain="economic",
    )


def make_escalation(
    map_id: str = "map-001",
    session_id: str = "sess-001",
    submitter: Submitter = None,
) -> FeedbackEntry:
    if submitter is None:
        submitter = make_submitter(role=FeedbackRole.AFFECTED_PARTY, sid="ap-001")
    return FeedbackEntry(
        map_id=map_id,
        session_id=session_id,
        submitter=submitter,
        feedback_type=FeedbackType.ESCALATION_REQUEST,
        content=(
            "This consequence map has significant omissions regarding "
            "the impact on indigenous land rights that require urgent "
            "human review before any decision proceeds."
        ),
        escalation_reason=(
            "The analysis omits documented treaty obligations and "
            "indigenous land rights impacts that fundamentally alter "
            "the ethical verdict."
        ),
        target_domain="legal_institutional",
    )


def make_processor() -> FeedbackProcessor:
    """Create a FeedbackProcessor with a temp audit log."""
    tmp = tempfile.mktemp(suffix=".jsonl", prefix="test_feedback_")
    audit = AuditLog(path=tmp)
    return FeedbackProcessor(audit_log=audit)


# A minimal realistic consequence map dict for validator tests
SAMPLE_MAP = {
    "map_id": "map-001",
    "overall_verdict": "mixed",
    "channel_outputs": [
        {
            "channel_name": "economic",
            "findings": [
                {"finding_id": "finding-abc", "summary": "Inflation risk."},
                {"finding_id": "finding-def", "summary": "Labor displacement."},
            ],
        },
        {
            "channel_name": "ecological",
            "findings": [
                {"finding_id": "finding-ghi", "summary": "Carbon reduction."},
            ],
        },
    ],
    "timeframe_impacts": [],
    "population_impacts": [],
}


# ---------------------------------------------------------------------------
# TestFeedbackModels
# ---------------------------------------------------------------------------

class TestFeedbackModels(unittest.TestCase):

    def test_all_roles_have_trust_matrix(self):
        for role in FeedbackRole:
            self.assertIn(role.value, ROLE_DOMAIN_TRUST,
                          f"Role {role.value} missing from trust matrix")

    def test_all_roles_have_domain_general_entry(self):
        for role in FeedbackRole:
            weights = ROLE_DOMAIN_TRUST[role.value]
            self.assertIn("general", weights,
                          f"Role {role.value} missing 'general' trust entry")

    def test_reviewer_has_highest_base_trust(self):
        for domain in ["economic", "ecological", "social_demographic"]:
            reviewer_trust = ROLE_DOMAIN_TRUST[FeedbackRole.REVIEWER.value][domain]
            for role in FeedbackRole:
                if role == FeedbackRole.REVIEWER:
                    continue
                other_trust = ROLE_DOMAIN_TRUST[role.value].get(domain,
                              ROLE_DOMAIN_TRUST[role.value]["general"])
                self.assertGreaterEqual(reviewer_trust, other_trust,
                                        f"Reviewer trust should be >= {role.value} in {domain}")

    def test_citizen_has_lowest_base_trust(self):
        citizen_general = ROLE_DOMAIN_TRUST[FeedbackRole.CITIZEN.value]["general"]
        for role in FeedbackRole:
            if role == FeedbackRole.CITIZEN:
                continue
            other = ROLE_DOMAIN_TRUST[role.value]["general"]
            self.assertLessEqual(citizen_general, other,
                                 f"Citizen general trust should be <= {role.value}")

    def test_ethicist_highest_trust_in_adversarial_domain(self):
        ethicist = ROLE_DOMAIN_TRUST[FeedbackRole.ETHICIST.value]["ethical_adversarial"]
        for role in FeedbackRole:
            if role in (FeedbackRole.ETHICIST, FeedbackRole.REVIEWER):
                continue
            other = ROLE_DOMAIN_TRUST[role.value].get("ethical_adversarial",
                    ROLE_DOMAIN_TRUST[role.value]["general"])
            self.assertGreaterEqual(ethicist, other,
                                    f"Ethicist should have >= trust in adversarial vs {role.value}")

    def test_affected_party_elevated_trust_in_social(self):
        affected = ROLE_DOMAIN_TRUST[FeedbackRole.AFFECTED_PARTY.value]["social_demographic"]
        citizen = ROLE_DOMAIN_TRUST[FeedbackRole.CITIZEN.value]["social_demographic"]
        self.assertGreater(affected, citizen)

    def test_get_trust_weight_returns_valid_range(self):
        for role in FeedbackRole:
            for domain in ["economic", "ecological", "general"]:
                weight = get_trust_weight(role, domain)
                self.assertGreaterEqual(weight, 0.05)
                self.assertLessEqual(weight, 1.0)

    def test_earned_trust_modifier_applied(self):
        base = get_trust_weight(FeedbackRole.CITIZEN, "economic", 0.0)
        boosted = get_trust_weight(FeedbackRole.CITIZEN, "economic", 0.2)
        self.assertGreater(boosted, base)

    def test_earned_trust_modifier_clamped_to_1(self):
        weight = get_trust_weight(FeedbackRole.REVIEWER, "economic", 0.3)
        self.assertLessEqual(weight, 1.0)

    def test_earned_trust_modifier_clamped_to_005(self):
        weight = get_trust_weight(FeedbackRole.CITIZEN, "economic", -0.5)
        self.assertGreaterEqual(weight, 0.05)

    def test_role_permissions_cover_all_roles(self):
        for role in FeedbackRole:
            self.assertIn(role, ROLE_PERMISSIONS)

    def test_reviewer_can_submit_all_types(self):
        for ftype in FeedbackType:
            self.assertTrue(can_submit(FeedbackRole.REVIEWER, ftype))

    def test_citizen_cannot_submit_finding_challenge(self):
        self.assertFalse(can_submit(FeedbackRole.CITIZEN, FeedbackType.FINDING_CHALLENGE))

    def test_citizen_can_submit_general_comment(self):
        self.assertTrue(can_submit(FeedbackRole.CITIZEN, FeedbackType.GENERAL_COMMENT))

    def test_citizen_can_submit_escalation_request(self):
        self.assertTrue(can_submit(FeedbackRole.CITIZEN, FeedbackType.ESCALATION_REQUEST))

    def test_domain_expert_can_submit_all_types(self):
        for ftype in FeedbackType:
            self.assertTrue(can_submit(FeedbackRole.DOMAIN_EXPERT, ftype))

    def test_submitter_trust_in_uses_domain(self):
        sub = make_expert(domain="economic")
        trust_econ = sub.trust_in("economic")
        trust_general = sub.trust_in("general")
        self.assertGreater(trust_econ, trust_general)

    def test_verified_submitter_gets_bonus(self):
        unverified = make_submitter(role=FeedbackRole.DOMAIN_EXPERT, verified=False)
        verified = make_submitter(role=FeedbackRole.DOMAIN_EXPERT, verified=True)
        self.assertGreater(verified.trust_in("economic"), unverified.trust_in("economic"))

    def test_feedback_entry_trust_weight_frozen_at_creation(self):
        entry = make_challenge()
        original_weight = entry.trust_weight
        # Modifying submitter earned_trust after creation should not change entry weight
        entry.submitter.earned_trust["economic"] = 0.3
        self.assertEqual(entry.trust_weight, original_weight)

    def test_feedback_entry_rejects_wrong_role_for_type(self):
        citizen = make_submitter(role=FeedbackRole.CITIZEN)
        with self.assertRaises(PermissionError):
            FeedbackEntry(
                map_id="map-001",
                session_id="sess-001",
                submitter=citizen,
                feedback_type=FeedbackType.FINDING_CHALLENGE,
                content="This is a challenge." * 5,
                target_finding_id="finding-abc",
            )

    def test_feedback_entry_requires_target_for_challenge(self):
        with self.assertRaises(ValueError):
            FeedbackEntry(
                map_id="map-001",
                session_id="sess-001",
                submitter=make_expert(),
                feedback_type=FeedbackType.FINDING_CHALLENGE,
                content="The finding is wrong for these reasons." * 3,
                target_finding_id=None,  # Missing
            )

    def test_feedback_entry_requires_correction_for_data_correction(self):
        with self.assertRaises(ValueError):
            FeedbackEntry(
                map_id="map-001",
                session_id="sess-001",
                submitter=make_expert(),
                feedback_type=FeedbackType.DATA_CORRECTION,
                content="The GDP growth rate used is incorrect." * 2,
                suggested_correction=None,  # Missing
            )

    def test_feedback_entry_requires_escalation_reason(self):
        with self.assertRaises(ValueError):
            FeedbackEntry(
                map_id="map-001",
                session_id="sess-001",
                submitter=make_submitter(),
                feedback_type=FeedbackType.ESCALATION_REQUEST,
                content="Please escalate this." * 3,
                escalation_reason=None,  # Missing
            )

    def test_feedback_entry_requires_non_empty_content(self):
        with self.assertRaises(ValueError):
            FeedbackEntry(
                map_id="map-001",
                session_id="sess-001",
                submitter=make_submitter(),
                feedback_type=FeedbackType.GENERAL_COMMENT,
                content="   ",  # Whitespace only
            )

    def test_feedback_entry_to_dict_serializable(self):
        entry = make_challenge()
        d = entry.to_dict()
        json.dumps(d)  # Should not raise

    def test_finding_signal_net_signal(self):
        sig = FindingSignal(finding_id="f-001")
        sig.support_weight = 0.8
        sig.challenge_weight = 0.3
        self.assertAlmostEqual(sig.net_signal, 0.5, places=4)

    def test_finding_signal_is_contested(self):
        sig = FindingSignal(finding_id="f-001")
        sig.challenge_weight = 0.7
        sig.challenge_count = 3
        self.assertTrue(sig.is_contested)

    def test_finding_signal_is_not_contested_below_threshold(self):
        sig = FindingSignal(finding_id="f-001")
        sig.challenge_weight = 0.3  # Below 0.5
        sig.challenge_count = 1
        self.assertFalse(sig.is_contested)

    def test_finding_signal_is_corroborated(self):
        sig = FindingSignal(finding_id="f-001")
        sig.support_weight = 0.8
        sig.support_count = 2
        self.assertTrue(sig.is_corroborated)

    def test_feedback_summary_requires_escalation_at_threshold(self):
        summary = FeedbackSummary(map_id="m", session_id="s")
        summary.escalation_pressure = FeedbackSummary.ESCALATION_THRESHOLD
        self.assertTrue(summary.requires_escalation)

    def test_feedback_summary_does_not_escalate_below_threshold(self):
        summary = FeedbackSummary(map_id="m", session_id="s")
        summary.escalation_pressure = 0.9
        self.assertFalse(summary.requires_escalation)

    def test_feedback_summary_to_dict_serializable(self):
        summary = FeedbackSummary(map_id="m", session_id="s")
        json.dumps(summary.to_dict())


# ---------------------------------------------------------------------------
# TestTrustLedger
# ---------------------------------------------------------------------------

class TestTrustLedger(unittest.TestCase):

    def make_ledger(self) -> TrustLedger:
        return TrustLedger(path=None)  # In-memory

    def test_get_or_create_creates_record(self):
        ledger = self.make_ledger()
        record = ledger.get_or_create("user-001", FeedbackRole.CITIZEN)
        self.assertEqual(record.submitter_id, "user-001")
        self.assertEqual(record.role, FeedbackRole.CITIZEN)

    def test_get_or_create_returns_existing(self):
        ledger = self.make_ledger()
        r1 = ledger.get_or_create("user-001", FeedbackRole.CITIZEN)
        r2 = ledger.get_or_create("user-001", FeedbackRole.DOMAIN_EXPERT)
        # Role should not change on second call
        self.assertIs(r1, r2)

    def test_get_returns_none_for_unknown(self):
        ledger = self.make_ledger()
        self.assertIsNone(ledger.get("unknown"))

    def test_get_modifier_returns_zero_for_new_submitter(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.CITIZEN)
        self.assertEqual(ledger.get_modifier("user-001", "economic"), 0.0)

    def test_record_event_applies_delta(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.DOMAIN_EXPERT)
        ledger.record_event("user-001", TrustEvent.CHALLENGE_UPHELD, "economic")
        self.assertGreater(ledger.get_modifier("user-001", "economic"), 0.0)

    def test_record_event_negative_delta(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.DOMAIN_EXPERT)
        ledger.record_event("user-001", TrustEvent.CHALLENGE_DISMISSED, "economic")
        self.assertLess(ledger.get_modifier("user-001", "economic"), 0.0)

    def test_modifier_clamped_to_floor(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.CITIZEN)
        for _ in range(20):
            ledger.record_event("user-001", -0.1, "economic")
        modifier = ledger.get_modifier("user-001", "economic")
        self.assertGreaterEqual(modifier, SubmitterRecord.MODIFIER_FLOOR)

    def test_modifier_clamped_to_ceiling(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.CITIZEN)
        for _ in range(20):
            ledger.record_event("user-001", 0.1, "economic")
        modifier = ledger.get_modifier("user-001", "economic")
        self.assertLessEqual(modifier, SubmitterRecord.MODIFIER_CEILING)

    def test_record_submission_increments_count(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.CITIZEN)
        ledger.record_submission("user-001")
        ledger.record_submission("user-001")
        record = ledger.get("user-001")
        self.assertEqual(record.submission_count, 2)

    def test_verify_submitter(self):
        ledger = self.make_ledger()
        ledger.get_or_create("user-001", FeedbackRole.DOMAIN_EXPERT)
        result = ledger.verify_submitter("user-001")
        self.assertTrue(result)
        self.assertTrue(ledger.get("user-001").verified)

    def test_verify_unknown_returns_false(self):
        ledger = self.make_ledger()
        self.assertFalse(ledger.verify_submitter("unknown"))

    def test_summary_returns_correct_counts(self):
        ledger = self.make_ledger()
        ledger.get_or_create("u1", FeedbackRole.CITIZEN)
        ledger.get_or_create("u2", FeedbackRole.DOMAIN_EXPERT)
        ledger.get_or_create("u3", FeedbackRole.CITIZEN)
        s = ledger.summary()
        self.assertEqual(s["total_submitters"], 3)
        self.assertEqual(s["role_counts"]["citizen"], 2)

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "ledger.json")
            ledger1 = TrustLedger(path=path)
            ledger1.get_or_create("user-001", FeedbackRole.DOMAIN_EXPERT)
            ledger1.record_event("user-001", TrustEvent.CHALLENGE_UPHELD, "economic")

            # Load fresh instance from same path
            ledger2 = TrustLedger(path=path)
            modifier = ledger2.get_modifier("user-001", "economic")
            self.assertAlmostEqual(modifier, TrustEvent.CHALLENGE_UPHELD, places=4)

    def test_consistency_bonus_applied_at_five_upheld(self):
        """Five consecutive upheld submissions should trigger a bonus."""
        ledger = self.make_ledger()
        ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)
        # Simulate 5 upheld
        for _ in range(5):
            ledger.record_event("expert-001", TrustEvent.CHALLENGE_UPHELD, "economic")
        modifier = ledger.get_modifier("expert-001", "economic")
        # Should be > 5 * CHALLENGE_UPHELD due to consistency bonus
        expected_min = 5 * TrustEvent.CHALLENGE_UPHELD
        self.assertGreater(modifier, expected_min)

    def test_record_event_on_unknown_submitter_is_noop(self):
        ledger = self.make_ledger()
        ledger.record_event("nonexistent", 0.1, "economic")  # Should not raise


# ---------------------------------------------------------------------------
# TestFeedbackValidator
# ---------------------------------------------------------------------------

class TestFeedbackValidator(unittest.TestCase):

    def setUp(self):
        from SeedCore.feedback.validator import _RateLimiter
        # Use a generous rate limiter for most tests
        self.validator = FeedbackValidator(rate_limiter=_RateLimiter(max_per_window=1000))

    def test_valid_challenge_passes(self):
        entry = make_challenge()
        result = self.validator.validate(entry, SAMPLE_MAP)
        self.assertTrue(result.passed)

    def test_valid_support_passes(self):
        entry = make_support()
        result = self.validator.validate(entry)
        self.assertTrue(result.passed)

    def test_valid_escalation_passes(self):
        entry = make_escalation()
        result = self.validator.validate(entry)
        self.assertTrue(result.passed)

    def test_content_too_short_for_challenge_fails(self):
        expert = make_expert()
        entry = FeedbackEntry(
            map_id="map-001", session_id="sess-001",
            submitter=expert,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="Too short.",
            target_finding_id="finding-abc",
        )
        result = self.validator.validate(entry)
        self.assertFalse(result.passed)
        self.assertTrue(any("too short" in f.lower() for f in result.failures))

    def test_nonexistent_finding_id_fails_with_map(self):
        entry = make_challenge(finding_id="nonexistent-finding-id")
        result = self.validator.validate(entry, SAMPLE_MAP)
        self.assertFalse(result.passed)
        self.assertTrue(any("does not exist" in f for f in result.failures))

    def test_valid_finding_id_passes_with_map(self):
        entry = make_challenge(finding_id="finding-abc")
        result = self.validator.validate(entry, SAMPLE_MAP)
        self.assertTrue(result.passed, f"Failures: {result.failures}")

    def test_escalation_reason_too_short_fails(self):
        submitter = make_submitter(role=FeedbackRole.AFFECTED_PARTY)
        entry = FeedbackEntry(
            map_id="map-001", session_id="sess-001",
            submitter=submitter,
            feedback_type=FeedbackType.ESCALATION_REQUEST,
            content="Please escalate this analysis for review." * 2,
            escalation_reason="Too short.",  # Under minimum length
        )
        result = self.validator.validate(entry)
        self.assertFalse(result.passed)

    def test_data_correction_without_correction_fails(self):
        """FeedbackEntry itself catches this, validator double-checks."""
        # The FeedbackEntry constructor catches this first, so test at entry level
        with self.assertRaises(ValueError):
            FeedbackEntry(
                map_id="map-001", session_id="sess-001",
                submitter=make_expert(),
                feedback_type=FeedbackType.DATA_CORRECTION,
                content="The GDP growth figure used is incorrect." * 2,
                suggested_correction=None,
            )

    def test_domain_expert_challenge_without_citations_warns(self):
        entry = FeedbackEntry(
            map_id="map-001", session_id="sess-001",
            submitter=make_expert(),
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate is overstated for the following "
                    "technical reasons relating to demand elasticity and "
                    "market substitution effects that were not modeled.",
            target_finding_id="finding-abc",
            citations=[],  # No citations
        )
        result = self.validator.validate(entry)
        self.assertTrue(result.passed)
        self.assertTrue(any("citation" in w.lower() for w in result.warnings))

    def test_rate_limit_rejects_after_threshold(self):
        from SeedCore.feedback.validator import _RateLimiter, FeedbackValidator
        strict_limiter = _RateLimiter(max_per_window=2, window_seconds=3600)
        validator = FeedbackValidator(rate_limiter=strict_limiter)

        submitter = make_submitter(role=FeedbackRole.DOMAIN_EXPERT, sid="rate-test-user")
        for i in range(3):
            entry = FeedbackEntry(
                map_id="map-001", session_id="sess-001",
                submitter=submitter,
                feedback_type=FeedbackType.FINDING_SUPPORT,
                content="This finding is well-supported and aligns with "
                        "our independent research on this mechanism.",
                target_finding_id="finding-abc",
            )
            result = validator.validate(entry)
            if i < 2:
                self.assertTrue(result.passed, f"Should pass on attempt {i+1}")
            else:
                self.assertFalse(result.passed, "Should fail on attempt 3+")

    def test_reviewer_exempt_from_rate_limit(self):
        from SeedCore.feedback.validator import _RateLimiter, FeedbackValidator
        strict_limiter = _RateLimiter(max_per_window=1, window_seconds=3600)
        validator = FeedbackValidator(rate_limiter=strict_limiter)

        reviewer = make_submitter(role=FeedbackRole.REVIEWER, sid="reviewer-001")
        for _ in range(5):
            entry = FeedbackEntry(
                map_id="map-001", session_id="sess-001",
                submitter=reviewer,
                feedback_type=FeedbackType.GENERAL_COMMENT,
                content="Reviewer general comment on this consequence map.",
            )
            result = validator.validate(entry)
            self.assertTrue(result.passed, "Reviewer should be exempt from rate limiting")

    def test_validation_result_bool(self):
        entry = make_challenge()
        result = self.validator.validate(entry, SAMPLE_MAP)
        self.assertTrue(bool(result))


# ---------------------------------------------------------------------------
# TestFeedbackAggregator
# ---------------------------------------------------------------------------

class TestFeedbackAggregator(unittest.TestCase):

    def test_integrate_creates_summary(self):
        agg = FeedbackAggregator()
        entry = make_challenge()
        summary = agg.integrate(entry)
        self.assertIsNotNone(summary)
        self.assertEqual(summary.map_id, "map-001")

    def test_integrate_increments_total_submissions(self):
        agg = FeedbackAggregator()
        agg.integrate(make_challenge())
        agg.integrate(make_support())
        summary = agg.get_summary("map-001")
        self.assertEqual(summary.total_submissions, 2)

    def test_finding_signal_created_on_challenge(self):
        agg = FeedbackAggregator()
        agg.integrate(make_challenge(finding_id="finding-abc"))
        summary = agg.get_summary("map-001")
        self.assertIn("finding-abc", summary.finding_signals)

    def test_challenge_increases_challenge_weight(self):
        agg = FeedbackAggregator()
        entry = make_challenge(finding_id="finding-abc")
        agg.integrate(entry)
        signal = agg.get_summary("map-001").finding_signals["finding-abc"]
        self.assertAlmostEqual(signal.challenge_weight, entry.trust_weight, places=4)

    def test_support_increases_support_weight(self):
        agg = FeedbackAggregator()
        entry = make_support(finding_id="finding-abc")
        agg.integrate(entry)
        signal = agg.get_summary("map-001").finding_signals["finding-abc"]
        self.assertAlmostEqual(signal.support_weight, entry.trust_weight, places=4)

    def test_net_signal_positive_when_more_support(self):
        agg = FeedbackAggregator()
        # Two supports vs one challenge
        for i in range(2):
            agg.integrate(make_support(finding_id="f-001",
                          submitter=make_expert(sid=f"sup-{i}")))
        agg.integrate(make_challenge(finding_id="f-001",
                      submitter=make_expert(sid="chal-1")))
        signal = agg.get_summary("map-001").finding_signals["f-001"]
        self.assertGreater(signal.net_signal, 0)

    def test_contested_finding_detected(self):
        agg = FeedbackAggregator()
        # Add enough challenge weight
        for i in range(3):
            submitter = make_expert(sid=f"expert-{i}")
            challenge = FeedbackEntry(
                map_id="map-001", session_id="sess-001",
                submitter=submitter,
                feedback_type=FeedbackType.FINDING_CHALLENGE,
                content="The finding is contested on these grounds: "
                        "the model specification is flawed in its "
                        "core elasticity assumptions.",
                target_finding_id="finding-xyz",
                target_domain="economic",
            )
            agg.integrate(challenge)
        summary = agg.get_summary("map-001")
        self.assertIn("finding-xyz", summary.contested_findings)

    def test_escalation_pressure_accumulates(self):
        agg = FeedbackAggregator()
        entry = make_escalation()
        agg.integrate(entry)
        summary = agg.get_summary("map-001")
        self.assertGreater(summary.escalation_pressure, 0)
        self.assertAlmostEqual(summary.escalation_pressure, entry.trust_weight, places=4)

    def test_adversarial_challenges_accumulated(self):
        agg = FeedbackAggregator()
        expert = make_expert()
        entry = FeedbackEntry(
            map_id="map-001", session_id="sess-001",
            submitter=expert,
            feedback_type=FeedbackType.ADVERSARIAL_CHALLENGE,
            content="The analysis does not account for the fact that "
                    "the primary beneficiary of this policy is also "
                    "the primary author of the proposal, creating "
                    "a clear conflict of interest.",
        )
        agg.integrate(entry)
        summary = agg.get_summary("map-001")
        self.assertEqual(len(summary.adversarial_challenges), 1)

    def test_mitigation_suggestions_accumulated(self):
        agg = FeedbackAggregator()
        expert = make_expert()
        entry = FeedbackEntry(
            map_id="map-001", session_id="sess-001",
            submitter=expert,
            feedback_type=FeedbackType.MITIGATION_SUGGESTION,
            content="A revenue recycling mechanism with income-indexed "
                    "rebates would significantly reduce the regressive "
                    "distributional impact identified in finding-abc.",
        )
        agg.integrate(entry)
        summary = agg.get_summary("map-001")
        self.assertEqual(len(summary.mitigation_suggestions), 1)

    def test_role_breakdown_tracked(self):
        agg = FeedbackAggregator()
        agg.integrate(make_challenge(submitter=make_expert(sid="e1")))
        agg.integrate(make_support(submitter=make_expert(sid="e2")))
        agg.integrate(make_escalation(submitter=make_submitter(
            role=FeedbackRole.AFFECTED_PARTY, sid="ap1")))
        summary = agg.get_summary("map-001")
        self.assertEqual(summary.role_breakdown.get("domain_expert", 0), 2)
        self.assertEqual(summary.role_breakdown.get("affected_party", 0), 1)

    def test_net_sentiment_negative_when_challenged(self):
        agg = FeedbackAggregator()
        # High-trust challenge, no support
        challenge = make_challenge(finding_id="f-001",
                                   submitter=make_expert(sid="e1"))
        agg.integrate(challenge)
        summary = agg.get_summary("map-001")
        self.assertLess(summary.net_sentiment, 0)

    def test_net_sentiment_zero_with_no_finding_signals(self):
        agg = FeedbackAggregator()
        expert = make_expert()
        entry = FeedbackEntry(
            map_id="map-001", session_id="sess-001",
            submitter=expert,
            feedback_type=FeedbackType.GENERAL_COMMENT,
            content="Very thorough analysis.",
        )
        agg.integrate(entry)
        summary = agg.get_summary("map-001")
        self.assertEqual(summary.net_sentiment, 0.0)

    def test_maps_requiring_escalation(self):
        agg = FeedbackAggregator()
        # Submit escalation from reviewer (trust weight ~0.9 >= threshold 1.0? No.)
        # Need pressure >= 1.0 — reviewer has 0.9 in general. Need 2 escalations.
        for i, role in enumerate([FeedbackRole.REVIEWER, FeedbackRole.ETHICIST]):
            submitter = make_submitter(role=role, sid=f"esc-{i}")
            entry = FeedbackEntry(
                map_id="map-esc", session_id="sess-001",
                submitter=submitter,
                feedback_type=FeedbackType.ESCALATION_REQUEST,
                content="This map requires urgent human review "
                        "due to significant omissions in the analysis.",
                escalation_reason="Critical ethical violations have been "
                                  "identified that are not captured in the "
                                  "current consequence map.",
            )
            agg.integrate(entry)
        self.assertIn("map-esc", agg.maps_requiring_escalation())

    def test_get_summary_returns_none_for_unknown_map(self):
        agg = FeedbackAggregator()
        self.assertIsNone(agg.get_summary("nonexistent"))

    def test_entry_status_set_to_integrated(self):
        agg = FeedbackAggregator()
        entry = make_challenge()
        agg.integrate(entry)
        self.assertEqual(entry.status, FeedbackStatus.INTEGRATED)


# ---------------------------------------------------------------------------
# TestFeedbackProcessor
# ---------------------------------------------------------------------------

class TestFeedbackProcessor(unittest.TestCase):

    def test_submit_valid_challenge_accepted(self):
        proc = make_processor()
        result = proc.submit(
            map_id="map-001",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate is significantly overstated. "
                    "The demand elasticity coefficient used is three times "
                    "higher than the empirically observed value for this sector.",
            target_finding_id="finding-abc",
            target_domain="economic",
            citations=["Journal of Economic Policy 2023"],
            consequence_map=SAMPLE_MAP,
        )
        self.assertTrue(result.accepted)
        self.assertIsNotNone(result.feedback_id)

    def test_submit_invalid_role_permission_rejected(self):
        proc = make_processor()
        result = proc.submit(
            map_id="map-001",
            session_id="sess-001",
            submitter_id="citizen-001",
            role=FeedbackRole.CITIZEN,
            feedback_type=FeedbackType.FINDING_CHALLENGE,  # Not allowed for citizens
            content="This finding is wrong." * 5,
            target_finding_id="finding-abc",
        )
        self.assertFalse(result.accepted)
        self.assertGreater(len(result.validation_failures), 0)

    def test_submit_too_short_content_rejected(self):
        proc = make_processor()
        result = proc.submit(
            map_id="map-001",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="Wrong.",  # Too short
            target_finding_id="finding-abc",
        )
        self.assertFalse(result.accepted)

    def test_submit_writes_to_audit_log(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        proc.submit(
            map_id="map-001",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate overstates the inflationary risk "
                    "by failing to account for substitution effects "
                    "documented in the recent empirical literature.",
            target_finding_id="finding-abc",
            target_domain="economic",
        )

        history = proc.get_feedback_history("sess-001")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], EntryKind.FEEDBACK_RECEIVED.value)

    def test_submit_updates_ledger(self):
        proc = make_processor()
        proc.submit(
            map_id="map-001",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate significantly overstates the "
                    "inflationary risk by failing to account for the "
                    "current capacity utilization levels in this sector.",
            target_finding_id="finding-abc",
            target_domain="economic",
        )
        modifier = proc._ledger.get_modifier("expert-001", "economic")
        # Modifier still 0 — trust only updates after review decision
        self.assertEqual(modifier, 0.0)
        # But submission count should be incremented
        record = proc._ledger.get("expert-001")
        self.assertEqual(record.submission_count, 1)

    def test_get_summary_returns_summary_after_submit(self):
        proc = make_processor()
        proc.submit(
            map_id="map-002",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The finding is overstated because the model "
                    "specification fails to account for substitution "
                    "effects and cross-price elasticities.",
            target_finding_id="finding-abc",
            target_domain="economic",
        )
        summary = proc.get_summary("map-002")
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_submissions, 1)

    def test_get_summary_returns_none_before_submissions(self):
        proc = make_processor()
        self.assertIsNone(proc.get_summary("map-nobody-submitted-to"))

    def test_record_review_decision_writes_to_audit_log(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        proc.record_review_decision(
            session_id="sess-001",
            reviewer_id="reviewer-001",
            map_id="map-001",
            decision="approve",
            rationale="After reviewing all submitted feedback, the "
                      "consequence map accurately represents the "
                      "available evidence. Approved for publication.",
        )

        history = proc.get_review_history("sess-001")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["kind"], EntryKind.HUMAN_REVIEW.value)

    def test_record_trust_event_updates_ledger(self):
        proc = make_processor()
        proc._ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)
        proc.record_trust_event("expert-001", TrustEvent.CHALLENGE_UPHELD, "economic")
        self.assertAlmostEqual(
            proc._ledger.get_modifier("expert-001", "economic"),
            TrustEvent.CHALLENGE_UPHELD, places=4
        )

    def test_verify_submitter(self):
        proc = make_processor()
        proc._ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)
        result = proc.verify_submitter("expert-001")
        self.assertTrue(result)

    def test_ledger_summary_accessible(self):
        proc = make_processor()
        s = proc.ledger_summary()
        self.assertIn("total_submitters", s)

    def test_feedback_result_to_dict(self):
        proc = make_processor()
        result = proc.submit(
            map_id="map-001",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate is significantly overstated due to "
                    "incorrect elasticity assumptions that do not reflect "
                    "the current empirical literature in this domain.",
            target_finding_id="finding-abc",
        )
        d = result.to_dict()
        json.dumps(d)  # Should not raise


# ---------------------------------------------------------------------------
# TestEscalation
# ---------------------------------------------------------------------------

class TestEscalation(unittest.TestCase):

    def test_single_reviewer_escalation_triggers(self):
        """A single reviewer escalation (trust ~0.9) is just below threshold.
        Two reviewers should cross it."""
        proc = make_processor()
        for i in range(2):
            result = proc.submit(
                map_id="esc-map-001",
                session_id="sess-001",
                submitter_id=f"reviewer-{i}",
                role=FeedbackRole.REVIEWER,
                feedback_type=FeedbackType.ESCALATION_REQUEST,
                content="This consequence map requires immediate human review "
                        "due to significant ethical violations that the "
                        "automated analysis has failed to flag.",
                escalation_reason="The map ignores treaty obligations under "
                                  "international law that fundamentally change "
                                  "the ethical verdict of this analysis.",
            )

        # After two reviewer escalations, pressure should exceed threshold
        summary = proc.get_summary("esc-map-001")
        self.assertGreaterEqual(summary.escalation_pressure,
                                FeedbackSummary.ESCALATION_THRESHOLD)
        self.assertTrue(summary.requires_escalation)

    def test_escalation_writes_human_review_to_audit(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        # Submit two reviewer escalations to cross threshold
        for i in range(2):
            proc.submit(
                map_id="esc-map-002",
                session_id="sess-esc",
                submitter_id=f"reviewer-{i}",
                role=FeedbackRole.REVIEWER,
                feedback_type=FeedbackType.ESCALATION_REQUEST,
                content="This requires human review due to "
                        "unresolved fundamental ethical questions "
                        "about the proposal's distributive impact.",
                escalation_reason="Unresolved conflict with prior treaty "
                                  "obligations that the legal channel did "
                                  "not adequately address.",
            )

        review_history = proc.get_review_history("sess-esc")
        self.assertGreater(len(review_history), 0)
        # The system-triggered review should have decision="defer"
        system_reviews = [r for r in review_history
                          if r["payload"].get("decision") == "defer"]
        self.assertGreater(len(system_reviews), 0)

    def test_escalation_only_triggers_once(self):
        """Escalation trigger audit entry should only be written once
        even if more escalation requests come in after threshold."""
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        # Cross threshold
        for i in range(2):
            proc.submit(
                map_id="esc-map-003",
                session_id="sess-once",
                submitter_id=f"reviewer-{i}",
                role=FeedbackRole.REVIEWER,
                feedback_type=FeedbackType.ESCALATION_REQUEST,
                content="Requires human review for ethical violations "
                        "not captured by the automated analysis system.",
                escalation_reason="The consequence map fails to account "
                                  "for documented treaty rights that "
                                  "materially affect the ethical verdict.",
            )

        # Third escalation — should NOT trigger another audit entry
        proc.submit(
            map_id="esc-map-003",
            session_id="sess-once",
            submitter_id="reviewer-2",
            role=FeedbackRole.REVIEWER,
            feedback_type=FeedbackType.ESCALATION_REQUEST,
            content="Additional escalation after threshold was crossed "
                    "for the same map to test deduplication behavior.",
            escalation_reason="Continued concerns about the analysis "
                              "validity that require sustained review.",
        )

        review_history = proc.get_review_history("sess-once")
        defer_entries = [r for r in review_history
                         if r["payload"].get("decision") == "defer"]
        self.assertEqual(len(defer_entries), 1,
                         "Escalation should only fire once")

    def test_low_trust_submitters_require_more_for_escalation(self):
        """Citizens have low trust — need many to cross escalation threshold."""
        proc = make_processor()
        # Single citizen escalation should not trigger
        result = proc.submit(
            map_id="map-citizen-esc",
            session_id="sess-001",
            submitter_id="citizen-001",
            role=FeedbackRole.CITIZEN,
            feedback_type=FeedbackType.ESCALATION_REQUEST,
            content="I believe this map needs human review because "
                    "it does not reflect the reality faced by our "
                    "community and should be re-examined.",
            escalation_reason="The analysis ignores the documented harm "
                              "to our community that is well-established "
                              "in local impact assessments.",
        )
        self.assertFalse(result.escalation_triggered)

        summary = proc.get_summary("map-citizen-esc")
        self.assertFalse(summary.requires_escalation)


# ---------------------------------------------------------------------------
# TestTrustLoop
# ---------------------------------------------------------------------------

class TestTrustLoop(unittest.TestCase):

    def test_upheld_challenge_increases_future_weight(self):
        """After a challenge is upheld, the submitter's future weight increases."""
        proc = make_processor()

        # Record initial trust
        proc._ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)
        initial_modifier = proc._ledger.get_modifier("expert-001", "economic")

        # Reviewer upholds the challenge
        proc.record_trust_event("expert-001", TrustEvent.CHALLENGE_UPHELD, "economic")

        new_modifier = proc._ledger.get_modifier("expert-001", "economic")
        self.assertGreater(new_modifier, initial_modifier)

    def test_dismissed_challenge_decreases_future_weight(self):
        proc = make_processor()
        proc._ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)

        proc.record_trust_event("expert-001", TrustEvent.CHALLENGE_DISMISSED, "economic")
        modifier = proc._ledger.get_modifier("expert-001", "economic")
        self.assertLess(modifier, 0.0)

    def test_verified_data_correction_increases_trust(self):
        proc = make_processor()
        proc._ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)
        proc.record_trust_event("expert-001", TrustEvent.DATA_CORRECTION_VERIFIED, "ecological")
        modifier = proc._ledger.get_modifier("expert-001", "ecological")
        self.assertAlmostEqual(modifier, TrustEvent.DATA_CORRECTION_VERIFIED, places=4)

    def test_accumulated_trust_affects_future_entry_weight(self):
        """After trust is earned, new submissions from same user carry more weight."""
        proc = make_processor()
        proc._ledger.get_or_create("expert-001", FeedbackRole.DOMAIN_EXPERT)

        # Get baseline weight
        base_submitter = Submitter(
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            earned_trust={},
        )
        base_weight = base_submitter.trust_in("economic")

        # Earn trust via ledger
        for _ in range(3):
            proc.record_trust_event("expert-001", TrustEvent.CHALLENGE_UPHELD, "economic")

        # Next submission will reflect earned trust
        record = proc._ledger.get("expert-001")
        boosted_submitter = Submitter(
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            earned_trust=dict(record.domain_modifiers),
        )
        boosted_weight = boosted_submitter.trust_in("economic")

        self.assertGreater(boosted_weight, base_weight)


# ---------------------------------------------------------------------------
# TestAuditIntegration
# ---------------------------------------------------------------------------

class TestAuditIntegration(unittest.TestCase):

    def test_every_accepted_submission_in_audit_log(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        for i in range(3):
            proc.submit(
                map_id="map-001",
                session_id="sess-audit",
                submitter_id=f"expert-{i}",
                role=FeedbackRole.DOMAIN_EXPERT,
                feedback_type=FeedbackType.FINDING_CHALLENGE,
                content="The estimate is overstated because the model "
                        "specification fails to account for empirically "
                        "documented substitution effects in this sector.",
                target_finding_id="finding-abc",
                target_domain="economic",
            )

        history = proc.get_feedback_history("sess-audit")
        self.assertEqual(len(history), 3)

    def test_rejected_submission_not_in_audit_log(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        # Citizen cannot submit FINDING_CHALLENGE — will be rejected
        proc.submit(
            map_id="map-001",
            session_id="sess-audit",
            submitter_id="citizen-001",
            role=FeedbackRole.CITIZEN,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="This finding is wrong." * 5,
            target_finding_id="finding-abc",
        )

        history = proc.get_feedback_history("sess-audit")
        self.assertEqual(len(history), 0)

    def test_audit_entry_contains_feedback_payload(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        proc.submit(
            map_id="map-payload-test",
            session_id="sess-payload",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate is significantly overstated due to "
                    "the incorrect application of demand-side elasticity "
                    "coefficients in the wrong market context.",
            target_finding_id="finding-abc",
            target_domain="economic",
        )

        history = proc.get_feedback_history("sess-payload")
        self.assertEqual(len(history), 1)
        payload = history[0]["payload"]
        self.assertEqual(payload["map_id"], "map-payload-test")
        self.assertEqual(payload["feedback_type"], "finding_challenge")

    def test_human_review_audit_entry_correct_structure(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        proc.record_review_decision(
            session_id="sess-review",
            reviewer_id="reviewer-001",
            map_id="map-001",
            decision="reject",
            rationale="The consequence map contains material errors in "
                      "the economic domain that require correction before "
                      "this analysis can be considered reliable.",
        )

        history = proc.get_review_history("sess-review")
        self.assertEqual(len(history), 1)
        payload = history[0]["payload"]
        self.assertEqual(payload["decision"], "reject")
        self.assertEqual(payload["reviewer_id"], "reviewer-001")

    def test_audit_chain_integrity_after_feedback(self):
        tmp = tempfile.mktemp(suffix=".jsonl")
        audit = AuditLog(path=tmp)
        proc = FeedbackProcessor(audit_log=audit)

        proc.submit(
            map_id="map-001",
            session_id="sess-chain",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The harm estimate is significantly overstated due to "
                    "the use of obsolete elasticity coefficients that have "
                    "been superseded by more recent empirical research.",
            target_finding_id="finding-abc",
        )

        proc.record_review_decision(
            session_id="sess-chain",
            reviewer_id="reviewer-001",
            map_id="map-001",
            decision="approve",
            rationale="Reviewed and approved.",
        )

        self.assertTrue(audit.verify())


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):

    def test_full_carbon_tax_feedback_scenario(self):
        """
        Realistic scenario: a carbon tax consequence map receives feedback
        from multiple stakeholders across roles. Tests the full pipeline
        from submission through aggregation to summary.
        """
        proc = make_processor()

        # 1. Domain expert challenges the inflation finding
        r1 = proc.submit(
            map_id="carbon-tax-map",
            session_id="sess-carbon",
            submitter_id="economist-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The 1.5% CPI impact estimate is overstated. Current "
                    "capacity utilization is below 78%, well under the "
                    "threshold at which demand-pull inflation historically "
                    "activates. The empirical literature supports a 0.3-0.6% "
                    "range for this policy design.",
            target_finding_id="inflation-finding",
            target_domain="economic",
            citations=["Blanchard & Galí (2007)", "Fed Capacity Report 2024"],
            consequence_map={"map_id": "carbon-tax-map",
                             "channel_outputs": [{"channel_name": "economic",
                             "findings": [{"finding_id": "inflation-finding",
                             "summary": "Inflation risk."}]}],
                             "timeframe_impacts": [], "population_impacts": []},
        )
        self.assertTrue(r1.accepted)

        # 2. Affected party from a coal region
        r2 = proc.submit(
            map_id="carbon-tax-map",
            session_id="sess-carbon",
            submitter_id="worker-rep-001",
            role=FeedbackRole.AFFECTED_PARTY,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The social demographic analysis significantly "
                    "underestimates transition timeline impacts on "
                    "communities with 40%+ employment in fossil fuel "
                    "extraction. The 5-year phase-in is inadequate for "
                    "retraining 50,000 workers in our region.",
            target_finding_id="labor-finding",
            target_domain="social_demographic",
        )
        self.assertTrue(r2.accepted)

        # 3. Another economist supports the ecological findings
        r3 = proc.submit(
            map_id="carbon-tax-map",
            session_id="sess-carbon",
            submitter_id="ecologist-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_SUPPORT,
            content="The carbon reduction projections are consistent with "
                    "our modelling and the IPCC AR6 literature. The "
                    "ecological findings are well-grounded.",
            target_finding_id="carbon-finding",
            target_domain="ecological",
        )
        self.assertTrue(r3.accepted)

        # 4. Ethicist raises adversarial challenge
        r4 = proc.submit(
            map_id="carbon-tax-map",
            session_id="sess-carbon",
            submitter_id="ethicist-001",
            role=FeedbackRole.ETHICIST,
            feedback_type=FeedbackType.ADVERSARIAL_CHALLENGE,
            content="The dividend redistribution mechanism is structurally "
                    "identical to prior proposals that were consistently "
                    "weakened by industry capture during implementation. "
                    "The analysis does not address the lock-in risk from "
                    "provisions that allow industry to propose alternative "
                    "compliance mechanisms.",
        )
        self.assertTrue(r4.accepted)

        # 5. Citizen submits mitigation suggestion
        r5 = proc.submit(
            map_id="carbon-tax-map",
            session_id="sess-carbon",
            submitter_id="citizen-001",
            role=FeedbackRole.CITIZEN,
            feedback_type=FeedbackType.MITIGATION_SUGGESTION,
            content="The transition timeline for coal communities should "
                    "be extended to 10 years with mandatory community "
                    "benefit agreements tied to the dividend mechanism.",
        )
        self.assertTrue(r5.accepted)

        # Validate summary
        summary = proc.get_summary("carbon-tax-map")
        self.assertIsNotNone(summary)
        self.assertEqual(summary.total_submissions, 5)
        self.assertGreater(len(summary.finding_signals), 0)
        self.assertEqual(len(summary.adversarial_challenges), 1)
        self.assertEqual(len(summary.mitigation_suggestions), 1)
        self.assertFalse(summary.requires_escalation)

        # Summary should be serializable
        json.dumps(summary.to_dict())

    def test_summary_to_dict_complete(self):
        proc = make_processor()
        proc.submit(
            map_id="map-complete",
            session_id="sess-001",
            submitter_id="expert-001",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The estimate is substantially overstated due to "
                    "flawed modelling assumptions that do not reflect "
                    "current empirical evidence in this domain.",
            target_finding_id="finding-xyz",
            target_domain="economic",
        )
        summary = proc.get_summary("map-complete")
        d = summary.to_dict()
        expected_keys = [
            "summary_id", "map_id", "session_id", "total_submissions",
            "finding_signals", "contested_findings", "corroborated_findings",
            "adversarial_challenges", "mitigation_suggestions", "general_comments",
            "escalation_pressure", "escalation_requests", "data_corrections",
            "net_sentiment", "role_breakdown", "requires_escalation", "generated_at",
        ]
        for key in expected_keys:
            self.assertIn(key, d, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
