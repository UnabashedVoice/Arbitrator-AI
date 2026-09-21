"""
trust_ledger.py — Earned trust tracking for feedback submitters.

The trust ledger is how the Feedback System learns over time. Base trust
weights in models.py are static — they reflect the epistemic position of
a role, not the track record of an individual. The trust ledger adds the
track record layer.

HOW EARNED TRUST WORKS:

When a feedback entry is submitted:
    - It is recorded with the submitter's current trust weight
    - It is integrated into the FeedbackSummary

When subsequent evidence arrives (later feedback, re-evaluation, human
review decisions), the ledger may update the submitter's earned_trust:
    - A FINDING_CHALLENGE that is upheld by a human reviewer earns trust
    - A FINDING_CHALLENGE that is dismissed earns negative trust
    - A DATA_CORRECTION that is verified earns trust
    - A DATA_CORRECTION that is found to be false loses trust
    - ESCALATION_REQUESTs that result in meaningful review earn trust
    - Patterns of low-quality submissions accumulate negative modifiers

BOUNDS:
    - Modifiers are bounded to [-0.3, +0.3] per domain
    - The system is not punitive: a single error does not permanently
      reduce a submitter's voice. It takes a consistent pattern to
      significantly reduce trust, and it can be recovered.
    - No submitter can accumulate trust above 1.0 (no single voice
      is absolute, regardless of track record)

PERSISTENCE:
    The ledger persists to a JSON file. It is separate from the audit
    log (which is append-only) because the ledger is mutable state.
    The audit log records what happened; the ledger tracks who to
    weight more carefully.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .models import FeedbackRole, ROLE_DOMAIN_TRUST


# ---------------------------------------------------------------------------
# Trust event types
# ---------------------------------------------------------------------------

class TrustEvent:
    """Named trust modifier events and their deltas."""
    CHALLENGE_UPHELD        =  0.05   # A challenge was validated by review
    CHALLENGE_DISMISSED     = -0.04   # A challenge was found without merit
    DATA_CORRECTION_VERIFIED =  0.07  # A data correction was confirmed accurate
    DATA_CORRECTION_REJECTED = -0.06  # A data correction was found to be wrong
    ESCALATION_PRODUCTIVE    =  0.04  # An escalation led to meaningful review
    ESCALATION_UNPRODUCTIVE  = -0.03  # An escalation was found to be unfounded
    CONSISTENT_QUALITY       =  0.02  # Five consecutive upheld submissions (bonus)
    CONSISTENT_LOW_QUALITY   = -0.03  # Five consecutive dismissed submissions


# ---------------------------------------------------------------------------
# Submitter trust record
# ---------------------------------------------------------------------------

@dataclass
class SubmitterRecord:
    """
    The trust ledger entry for a single submitter.

    Attributes:
        submitter_id:       The submitter's stable identifier.
        role:               Their claimed role.
        domain_modifiers:   domain → earned trust modifier [-0.3, +0.3].
        submission_count:   Total submissions from this submitter.
        upheld_count:       Submissions later verified/upheld.
        dismissed_count:    Submissions later dismissed/refuted.
        last_activity:      UTC timestamp of last submission.
        verified:           Whether role has been operator-verified.
    """
    submitter_id: str
    role: FeedbackRole
    domain_modifiers: dict[str, float] = field(default_factory=dict)
    submission_count: int = 0
    upheld_count: int = 0
    dismissed_count: int = 0
    last_activity: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    verified: bool = False

    MODIFIER_FLOOR: float = -0.30
    MODIFIER_CEILING: float = 0.30

    def get_modifier(self, domain: str) -> float:
        """Get the earned trust modifier for a domain."""
        return self.domain_modifiers.get(domain, 0.0)

    def apply_event(self, event_delta: float, domain: str) -> None:
        """Apply a trust event delta to a specific domain."""
        current = self.domain_modifiers.get(domain, 0.0)
        updated = max(self.MODIFIER_FLOOR, min(self.MODIFIER_CEILING,
                       round(current + event_delta, 4)))
        self.domain_modifiers[domain] = updated
        self.last_activity = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "submitter_id": self.submitter_id,
            "role": self.role.value,
            "domain_modifiers": self.domain_modifiers,
            "submission_count": self.submission_count,
            "upheld_count": self.upheld_count,
            "dismissed_count": self.dismissed_count,
            "last_activity": self.last_activity,
            "verified": self.verified,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubmitterRecord":
        return cls(
            submitter_id=data["submitter_id"],
            role=FeedbackRole(data["role"]),
            domain_modifiers=data.get("domain_modifiers", {}),
            submission_count=data.get("submission_count", 0),
            upheld_count=data.get("upheld_count", 0),
            dismissed_count=data.get("dismissed_count", 0),
            last_activity=data.get("last_activity",
                          datetime.now(timezone.utc).isoformat()),
            verified=data.get("verified", False),
        )


# ---------------------------------------------------------------------------
# TrustLedger
# ---------------------------------------------------------------------------

class TrustLedger:
    """
    Persistent store of earned trust modifiers for all feedback submitters.

    The ledger is thread-safe and persists to a JSON file. It is the
    mechanism by which consistent quality (or consistent low quality)
    is recognized over time.

    Usage:
        ledger = TrustLedger(path="feedback/trust_ledger.json")

        # Register or retrieve a submitter
        record = ledger.get_or_create(submitter_id="abc123", role=FeedbackRole.CITIZEN)

        # Record a trust event after a challenge is upheld
        ledger.record_event(
            submitter_id="abc123",
            event_delta=TrustEvent.CHALLENGE_UPHELD,
            domain="economic",
        )

        # Get current modifier for use in trust weight calculation
        modifier = ledger.get_modifier("abc123", "economic")
    """

    def __init__(self, path: Optional[str] = None):
        """
        Args:
            path:   Path to the JSON persistence file.
                    If None, ledger operates in-memory only.
        """
        self._path = path
        self._records: dict[str, SubmitterRecord] = {}
        self._lock = threading.Lock()

        if path and os.path.exists(path):
            self._load()

    # ---------------------------------------------------------------------------
    # Record management
    # ---------------------------------------------------------------------------

    def get_or_create(
        self,
        submitter_id: str,
        role: FeedbackRole,
        verified: bool = False,
    ) -> SubmitterRecord:
        """
        Return existing record for submitter_id, or create one.

        If the submitter already exists with a different role, the
        existing role is preserved (role changes require operator action).
        """
        with self._lock:
            if submitter_id not in self._records:
                self._records[submitter_id] = SubmitterRecord(
                    submitter_id=submitter_id,
                    role=role,
                    verified=verified,
                )
                self._save()
            return self._records[submitter_id]

    def get(self, submitter_id: str) -> Optional[SubmitterRecord]:
        """Return the record for a submitter, or None if not found."""
        with self._lock:
            return self._records.get(submitter_id)

    def get_modifier(self, submitter_id: str, domain: str) -> float:
        """Return the earned trust modifier for a submitter in a domain."""
        with self._lock:
            record = self._records.get(submitter_id)
            if record is None:
                return 0.0
            return record.get_modifier(domain)

    def record_submission(self, submitter_id: str) -> None:
        """Increment submission count for a submitter."""
        with self._lock:
            record = self._records.get(submitter_id)
            if record:
                record.submission_count += 1
                record.last_activity = datetime.now(timezone.utc).isoformat()
                self._save()

    def record_event(
        self,
        submitter_id: str,
        event_delta: float,
        domain: str,
    ) -> None:
        """
        Apply a trust event to a submitter's domain modifier.

        Args:
            submitter_id:   The submitter being updated.
            event_delta:    The change in trust (use TrustEvent constants).
            domain:         Which domain is affected.
        """
        with self._lock:
            record = self._records.get(submitter_id)
            if record is None:
                return
            record.apply_event(event_delta, domain)

            # Track upheld/dismissed for quality streak detection
            if event_delta > 0:
                record.upheld_count += 1
            elif event_delta < 0:
                record.dismissed_count += 1

            # Check for consistent quality bonus/penalty
            total = record.upheld_count + record.dismissed_count
            if total > 0 and total % 5 == 0:
                quality_rate = record.upheld_count / total
                if quality_rate >= 0.8:
                    record.apply_event(TrustEvent.CONSISTENT_QUALITY, domain)
                elif quality_rate <= 0.2:
                    record.apply_event(TrustEvent.CONSISTENT_LOW_QUALITY, domain)

            self._save()

    def verify_submitter(self, submitter_id: str) -> bool:
        """
        Mark a submitter as operator-verified.
        Returns True if the submitter was found, False otherwise.
        """
        with self._lock:
            record = self._records.get(submitter_id)
            if record is None:
                return False
            record.verified = True
            self._save()
            return True

    def all_submitters(self) -> list[SubmitterRecord]:
        """Return all submitter records."""
        with self._lock:
            return list(self._records.values())

    def summary(self) -> dict:
        """Return summary statistics for the ledger."""
        with self._lock:
            role_counts: dict[str, int] = {}
            for record in self._records.values():
                role_counts[record.role.value] = role_counts.get(
                    record.role.value, 0) + 1
            return {
                "total_submitters": len(self._records),
                "verified_submitters": sum(
                    1 for r in self._records.values() if r.verified
                ),
                "role_counts": role_counts,
                "total_submissions": sum(
                    r.submission_count for r in self._records.values()
                ),
            }

    # ---------------------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------------------

    def _save(self) -> None:
        """Persist ledger to disk. Caller must hold self._lock."""
        if not self._path:
            return
        os.makedirs(os.path.dirname(self._path) if os.path.dirname(self._path)
                    else ".", exist_ok=True)
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {sid: rec.to_dict() for sid, rec in self._records.items()},
                    f, indent=2,
                )
            os.replace(tmp, self._path)
        except OSError:
            pass  # Fail silently — in-memory state is still valid

    def _load(self) -> None:
        """Load ledger from disk. Called at init only (no lock needed)."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for sid, rec_dict in data.items():
                self._records[sid] = SubmitterRecord.from_dict(rec_dict)
        except (OSError, json.JSONDecodeError, KeyError):
            self._records = {}
