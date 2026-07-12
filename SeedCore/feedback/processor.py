"""
processor.py — The FeedbackProcessor: main entry point for the Feedback System.

The FeedbackProcessor orchestrates all Feedback System components:
    - FeedbackValidator     (validates incoming submissions)
    - TrustLedger           (manages earned trust per submitter)
    - FeedbackAggregator    (aggregates into FeedbackSummary)
    - AuditLog              (records all activity to tamper-evident log)

It is the only component that external code needs to interact with.
The orchestrator, API layer, and CLI all go through the FeedbackProcessor.

PIPELINE FOR EACH SUBMISSION:

    1. Retrieve or create Submitter from TrustLedger
    2. Construct FeedbackEntry with trust weight from ledger
    3. Validate via FeedbackValidator
       → on failure: log rejection, return rejected result
    4. Update ledger submission count
    5. Write to AuditLog (write_feedback_received)
    6. Integrate into FeedbackAggregator
    7. Check escalation threshold
       → if crossed: write human review request to AuditLog
    8. Return FeedbackResult

HUMAN REVIEW INTEGRATION:

When the processor detects an escalation (escalation_pressure >= threshold),
it writes a HUMAN_REVIEW audit entry with decision="defer" as a trigger
record — indicating that the consequence map is now in deferred state
pending human review. The human reviewer later calls
processor.record_review_decision() to close the loop.

TRUST LOOP:

When a human reviewer makes a decision that validates or refutes a
specific feedback entry, the processor's record_trust_event() method
updates the submitter's earned trust in the ledger. This closes the
trust feedback loop over time.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .models import (
    FeedbackEntry,
    FeedbackRole,
    FeedbackStatus,
    FeedbackSummary,
    FeedbackType,
    Submitter,
)
from .trust_ledger import TrustLedger, TrustEvent
from .validator import FeedbackValidator, ValidationResult
from .aggregator import FeedbackAggregator
from ..audit_log.log import AuditLog
from ..audit_log.writers import write_feedback_received, write_human_review
from ..audit_log.models import EntryKind


# ---------------------------------------------------------------------------
# FeedbackResult
# ---------------------------------------------------------------------------

@dataclass
class FeedbackResult:
    """
    The result of a single feedback submission attempt.

    Returned by FeedbackProcessor.submit(). Contains the outcome
    of validation and integration, plus any triggered actions
    (e.g., escalation).

    Attributes:
        accepted:               True if the submission passed validation
                                and was integrated.
        feedback_id:            The UUID of the accepted entry, or None
                                if rejected.
        validation_failures:    List of reasons for rejection.
        validation_warnings:    Non-fatal issues noted.
        escalation_triggered:   True if this submission pushed the map's
                                escalation pressure over the threshold.
        current_pressure:       Current escalation pressure for this map.
        map_id:                 The map this feedback targeted.
        submitted_at:           UTC timestamp.
    """
    accepted: bool
    map_id: str
    feedback_id: Optional[str] = None
    validation_failures: list[str] = field(default_factory=list)
    validation_warnings: list[str] = field(default_factory=list)
    escalation_triggered: bool = False
    current_pressure: float = 0.0
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "map_id": self.map_id,
            "feedback_id": self.feedback_id,
            "validation_failures": self.validation_failures,
            "validation_warnings": self.validation_warnings,
            "escalation_triggered": self.escalation_triggered,
            "current_pressure": round(self.current_pressure, 4),
            "submitted_at": self.submitted_at,
        }


# ---------------------------------------------------------------------------
# FeedbackProcessor
# ---------------------------------------------------------------------------

class FeedbackProcessor:
    """
    Main entry point for the Feedback System.

    All external feedback submissions pass through this class.
    It owns the validator, ledger, aggregator, and audit log integration.

    Usage:
        processor = FeedbackProcessor(
            audit_log=my_audit_log,
            ledger_path="data/trust_ledger.json",
        )

        result = processor.submit(
            map_id="...",
            session_id="...",
            submitter_id="user-abc",
            role=FeedbackRole.DOMAIN_EXPERT,
            feedback_type=FeedbackType.FINDING_CHALLENGE,
            content="The economic harm score overstates the inflationary risk...",
            target_finding_id="finding-uuid-here",
            target_domain="economic",
            citations=["IMF Working Paper 2023/142"],
        )

        if result.accepted:
            print(f"Feedback accepted: {result.feedback_id}")
        else:
            print(f"Rejected: {result.validation_failures}")
    """

    def __init__(
        self,
        audit_log: Optional[AuditLog] = None,
        ledger_path: Optional[str] = None,
        node_id: str = "local",
    ):
        """
        Args:
            audit_log:      The AuditLog instance to write to.
                            If None, a in-memory log is created (for testing).
            ledger_path:    Path for trust ledger persistence.
                            If None, ledger operates in memory only.
            node_id:        Node identifier for audit entries.
        """
        if audit_log is None:
            import tempfile
            _tmp = tempfile.mktemp(suffix=".jsonl", prefix="arbitrator_feedback_")
            audit_log = AuditLog(path=_tmp)
        self._audit = audit_log
        self._ledger = TrustLedger(path=ledger_path)
        self._validator = FeedbackValidator()
        self._aggregator = FeedbackAggregator()
        self._node_id = node_id

    # ---------------------------------------------------------------------------
    # Primary interface
    # ---------------------------------------------------------------------------

    def submit(
        self,
        map_id: str,
        session_id: str,
        submitter_id: str,
        role: FeedbackRole,
        feedback_type: FeedbackType,
        content: str,
        target_finding_id: Optional[str] = None,
        target_domain: str = "general",
        citations: Optional[list[str]] = None,
        suggested_correction: Optional[str] = None,
        escalation_reason: Optional[str] = None,
        consequence_map: Optional[dict] = None,
        verified: bool = False,
    ) -> FeedbackResult:
        """
        Submit feedback against a published consequence map.

        Args:
            map_id:                 UUID of the consequence map being commented on.
            session_id:             Session that produced the consequence map.
            submitter_id:           Stable pseudonymous identifier for the submitter.
            role:                   The submitter's role.
            feedback_type:          Type of feedback being submitted.
            content:                The feedback text.
            target_finding_id:      For FINDING_CHALLENGE/SUPPORT — the finding UUID.
            target_domain:          Channel domain this feedback primarily addresses.
            citations:              Supporting references.
            suggested_correction:   For DATA_CORRECTION — the corrected value.
            escalation_reason:      For ESCALATION_REQUEST — the grounds.
            consequence_map:        The consequence map dict (for finding validation).
            verified:               Whether this submitter's role is operator-verified.

        Returns:
            FeedbackResult with accepted=True or False.
        """
        citations = citations or []

        # 1. Get or create submitter in ledger
        ledger_record = self._ledger.get_or_create(
            submitter_id=submitter_id,
            role=role,
            verified=verified,
        )
        submitter = Submitter(
            submitter_id=submitter_id,
            role=role,
            earned_trust=dict(ledger_record.domain_modifiers),
            submission_count=ledger_record.submission_count,
            verified=ledger_record.verified,
        )

        # 2. Construct FeedbackEntry (raises PermissionError or ValueError
        #    on structural violations — catch and convert to rejection)
        try:
            entry = FeedbackEntry(
                map_id=map_id,
                session_id=session_id,
                submitter=submitter,
                feedback_type=feedback_type,
                content=content,
                target_finding_id=target_finding_id,
                target_domain=target_domain,
                citations=citations,
                suggested_correction=suggested_correction,
                escalation_reason=escalation_reason,
            )
        except (PermissionError, ValueError) as e:
            return FeedbackResult(
                accepted=False,
                map_id=map_id,
                validation_failures=[str(e)],
            )

        # 3. Validate
        validation = self._validator.validate(entry, consequence_map)
        if not validation.passed:
            entry.status = FeedbackStatus.REJECTED
            return FeedbackResult(
                accepted=False,
                map_id=map_id,
                validation_failures=validation.failures,
                validation_warnings=validation.warnings,
            )

        entry.status = FeedbackStatus.VALIDATED

        # 4. Update ledger submission count
        self._ledger.record_submission(submitter_id)

        # 5. Write to audit log
        audit_entry = write_feedback_received(
            session_id=session_id,
            feedback_dict=entry.to_dict(),
            related_map_id=map_id,
            node_id=self._node_id,
        )
        self._audit.append(audit_entry)

        # 6. Integrate into aggregator
        prev_pressure = self._aggregator.get_summary(map_id)
        prev_pressure_val = (prev_pressure.escalation_pressure
                             if prev_pressure else 0.0)

        summary = self._aggregator.integrate(entry)

        # 7. Check escalation
        escalation_triggered = False
        if (summary.requires_escalation and
                prev_pressure_val < FeedbackSummary.ESCALATION_THRESHOLD):
            escalation_triggered = True
            self._trigger_escalation(summary, session_id)

        return FeedbackResult(
            accepted=True,
            map_id=map_id,
            feedback_id=entry.feedback_id,
            validation_warnings=validation.warnings,
            escalation_triggered=escalation_triggered,
            current_pressure=summary.escalation_pressure,
        )

    def get_summary(self, map_id: str) -> Optional[FeedbackSummary]:
        """Return the current feedback summary for a consequence map."""
        return self._aggregator.get_summary(map_id)

    def maps_requiring_escalation(self) -> list[str]:
        """Return map IDs where escalation has been triggered."""
        return self._aggregator.maps_requiring_escalation()

    # ---------------------------------------------------------------------------
    # Human review integration
    # ---------------------------------------------------------------------------

    def record_review_decision(
        self,
        session_id: str,
        reviewer_id: str,
        map_id: str,
        decision: str,
        rationale: str,
        related_ethics_id: Optional[str] = None,
    ) -> None:
        """
        Record a human reviewer's decision on an escalated map.

        Valid decisions: "approve", "reject", "defer", "amend"

        This writes a HUMAN_REVIEW entry to the audit log, closing
        the escalation loop.

        Args:
            session_id:             The session that produced the map.
            reviewer_id:            The reviewer's identifier.
            map_id:                 The consequence map under review.
            decision:               One of: approve, reject, defer, amend.
            rationale:              Human-readable explanation.
            related_ethics_id:      Optional ethics evaluation ID.
        """
        review_entry = write_human_review(
            session_id=session_id,
            reviewer_id=reviewer_id,
            decision=decision,
            rationale=rationale,
            related_map_id=map_id,
            related_ethics_id=related_ethics_id,
            node_id=self._node_id,
        )
        self._audit.append(review_entry)

    def record_trust_event(
        self,
        submitter_id: str,
        event_delta: float,
        domain: str,
    ) -> None:
        """
        Update a submitter's earned trust based on a review outcome.

        Called by reviewers when a feedback entry is upheld or dismissed.

        Args:
            submitter_id:   The submitter whose trust is being updated.
            event_delta:    The trust delta (use TrustEvent constants).
            domain:         The domain this event applies to.

        Example:
            processor.record_trust_event(
                submitter_id="user-xyz",
                event_delta=TrustEvent.CHALLENGE_UPHELD,
                domain="economic",
            )
        """
        self._ledger.record_event(submitter_id, event_delta, domain)

    def verify_submitter(self, submitter_id: str) -> bool:
        """
        Mark a submitter as operator-verified.
        Returns True if the submitter was found.
        """
        return self._ledger.verify_submitter(submitter_id)

    # ---------------------------------------------------------------------------
    # Queries
    # ---------------------------------------------------------------------------

    def get_feedback_history(self, session_id: str) -> list[dict]:
        """
        Return all feedback audit entries for a session.

        Queries the audit log for FEEDBACK_RECEIVED entries
        linked to the given session_id.
        """
        from ..audit_log.log import LogQuery
        from ..audit_log.models import EntryKind

        query = LogQuery(
            session_id=session_id,
            kind=EntryKind.FEEDBACK_RECEIVED,
        )
        entries = self._audit.query(query)
        return [e.to_public_dict() for e in entries]

    def get_review_history(self, session_id: str) -> list[dict]:
        """
        Return all human review audit entries for a session.
        """
        from ..audit_log.log import LogQuery
        from ..audit_log.models import EntryKind

        query = LogQuery(
            session_id=session_id,
            kind=EntryKind.HUMAN_REVIEW,
        )
        entries = self._audit.query(query)
        return [e.to_public_dict() for e in entries]

    def ledger_summary(self) -> dict:
        """Return summary statistics for the trust ledger."""
        return self._ledger.summary()

    # ---------------------------------------------------------------------------
    # Internal
    # ---------------------------------------------------------------------------

    def _trigger_escalation(
        self,
        summary: FeedbackSummary,
        session_id: str,
    ) -> None:
        """
        Write a HUMAN_REVIEW audit entry when escalation threshold is crossed.

        Uses decision="defer" to signal that the map is pending human review.
        This is a trigger record — not a final decision.
        """
        escalation_reasons = "; ".join(
            e.escalation_reason or e.content[:100]
            for e in summary.escalation_requests
        )
        rationale = (
            f"Feedback escalation threshold reached for map {summary.map_id}. "
            f"Escalation pressure: {summary.escalation_pressure:.2f} "
            f"(threshold: {FeedbackSummary.ESCALATION_THRESHOLD}). "
            f"Grounds: {escalation_reasons}"
        )

        review_entry = write_human_review(
            session_id=session_id,
            reviewer_id="system/escalation",
            decision="defer",
            rationale=rationale,
            related_map_id=summary.map_id,
            node_id=self._node_id,
        )
        self._audit.append(review_entry)
