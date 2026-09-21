"""
validator.py — Validation layer for incoming feedback submissions.

Every FeedbackEntry passes through the validator before it is accepted
into the system. The validator is the first line of epistemic defense.

Validation checks:
    1. Role permission — does this role have permission to submit this type?
       (Already enforced in FeedbackEntry.__post_init__, double-checked here)
    2. Content quality — is the content substantive enough to process?
       Minimum length varies by type. An adversarial challenge needs more
       than five words. A general comment can be brief.
    3. Target validity — if targeting a specific finding, does it exist
       in the consequence map? (Prevents phantom finding submissions)
    4. Citation format — are citations plausibly structured?
       (Not verified for accuracy — just for format sanity)
    5. Escalation grounds — does the escalation reason name a specific
       concern? (Prevents noise escalations)
    6. Rate limiting — is this submitter submitting too fast?
       (Basic abuse prevention)

The validator returns a ValidationResult with a list of failures.
A ValidationResult with no failures is a PASS. Partial rejections
are not supported — a submission either passes or fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import (
    FeedbackEntry,
    FeedbackType,
    FeedbackRole,
    FeedbackStatus,
    can_submit,
)


# ---------------------------------------------------------------------------
# Minimum content lengths by feedback type (characters)
# ---------------------------------------------------------------------------

MIN_CONTENT_LENGTH: dict[FeedbackType, int] = {
    FeedbackType.FINDING_CHALLENGE:     80,   # Must explain why the finding is wrong
    FeedbackType.FINDING_SUPPORT:       40,   # Must explain why the finding is right
    FeedbackType.DATA_CORRECTION:       60,   # Must describe the correction
    FeedbackType.ADVERSARIAL_CHALLENGE: 80,   # Must articulate the challenge
    FeedbackType.MITIGATION_SUGGESTION: 60,   # Must describe the mitigation
    FeedbackType.GENERAL_COMMENT:       20,   # Minimal bar
    FeedbackType.ESCALATION_REQUEST:    60,   # Must state grounds
}

MIN_ESCALATION_REASON_LENGTH: int = 40


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """
    The result of validating a FeedbackEntry.

    Attributes:
        passed:     True if all checks passed.
        failures:   List of human-readable failure reasons.
        warnings:   Non-fatal issues noted but not blocking.
        entry:      The feedback entry that was validated.
    """
    passed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entry: Optional[FeedbackEntry] = None

    def __bool__(self) -> bool:
        return self.passed


# ---------------------------------------------------------------------------
# Rate limiter (in-memory, resets on restart)
# ---------------------------------------------------------------------------

class _RateLimiter:
    """
    Simple in-memory rate limiter per submitter.

    Tracks submission timestamps and rejects if the submitter
    exceeds max_per_window submissions in window_seconds.

    Conservative defaults:
        - 10 submissions per 5 minutes per submitter
        - Reviewers are exempt (they need to process queues)
    """
    def __init__(self, max_per_window: int = 10, window_seconds: int = 300):
        self._max = max_per_window
        self._window = window_seconds
        self._log: dict[str, list[float]] = {}

    def check(self, submitter_id: str, role: FeedbackRole) -> bool:
        """Return True if submission is allowed."""
        import time
        if role == FeedbackRole.REVIEWER:
            return True

        now = time.monotonic()
        window_start = now - self._window
        timestamps = self._log.get(submitter_id, [])
        recent = [t for t in timestamps if t >= window_start]
        self._log[submitter_id] = recent

        if len(recent) >= self._max:
            return False

        self._log[submitter_id].append(now)
        return True


_default_rate_limiter = _RateLimiter()


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class FeedbackValidator:
    """
    Validates incoming FeedbackEntry submissions.

    The validator is stateless with respect to feedback content, but
    maintains a rate limiter for abuse prevention.

    Usage:
        validator = FeedbackValidator()
        result = validator.validate(entry, consequence_map_dict)
        if result.passed:
            # proceed with processing
        else:
            # result.failures contains rejection reasons
    """

    def __init__(self, rate_limiter: Optional[_RateLimiter] = None):
        self._rate_limiter = rate_limiter or _default_rate_limiter

    def validate(
        self,
        entry: FeedbackEntry,
        consequence_map: Optional[dict] = None,
    ) -> ValidationResult:
        """
        Validate a feedback entry.

        Args:
            entry:              The FeedbackEntry to validate.
            consequence_map:    The consequence map dict the feedback targets.
                                If provided, finding IDs are verified.
                                If None, finding ID validation is skipped.

        Returns:
            ValidationResult with passed=True if all checks pass.
        """
        failures = []
        warnings = []

        # 1. Role permission (defensive double-check)
        if not can_submit(entry.submitter.role, entry.feedback_type):
            failures.append(
                f"Role '{entry.submitter.role.value}' may not submit "
                f"'{entry.feedback_type.value}' feedback."
            )

        # 2. Content length
        min_len = MIN_CONTENT_LENGTH.get(entry.feedback_type, 20)
        if len(entry.content.strip()) < min_len:
            failures.append(
                f"Content is too short for '{entry.feedback_type.value}'. "
                f"Minimum {min_len} characters required, "
                f"got {len(entry.content.strip())}."
            )

        # 3. Target finding validation
        if entry.target_finding_id and consequence_map:
            finding_ids = self._extract_finding_ids(consequence_map)
            if entry.target_finding_id not in finding_ids:
                failures.append(
                    f"target_finding_id '{entry.target_finding_id}' "
                    f"does not exist in consequence map '{entry.map_id}'."
                )

        # 4. Citation format sanity
        for i, citation in enumerate(entry.citations):
            if len(citation.strip()) < 10:
                warnings.append(
                    f"Citation {i+1} is very short and may not be useful: "
                    f"'{citation[:50]}'"
                )

        # 5. Escalation reason
        if entry.feedback_type == FeedbackType.ESCALATION_REQUEST:
            if not entry.escalation_reason:
                failures.append(
                    "ESCALATION_REQUEST requires an escalation_reason."
                )
            elif len(entry.escalation_reason.strip()) < MIN_ESCALATION_REASON_LENGTH:
                failures.append(
                    f"escalation_reason must be at least {MIN_ESCALATION_REASON_LENGTH} "
                    f"characters. Got {len(entry.escalation_reason.strip())}."
                )

        # 6. Data correction content
        if entry.feedback_type == FeedbackType.DATA_CORRECTION:
            if not entry.suggested_correction:
                failures.append(
                    "DATA_CORRECTION requires a suggested_correction."
                )
            elif len(entry.suggested_correction.strip()) < 20:
                failures.append(
                    "suggested_correction is too brief to be actionable."
                )

        # 7. Finding challenge/support needs target
        if entry.feedback_type in (
            FeedbackType.FINDING_CHALLENGE, FeedbackType.FINDING_SUPPORT
        ) and not entry.target_finding_id:
            failures.append(
                f"{entry.feedback_type.value} requires a target_finding_id."
            )

        # 8. Rate limiting
        if not self._rate_limiter.check(
            entry.submitter.submitter_id, entry.submitter.role
        ):
            failures.append(
                "Rate limit exceeded. Please wait before submitting again."
            )

        # 9. Domain expert challenges without citations — warn, not fail
        if (
            entry.feedback_type == FeedbackType.FINDING_CHALLENGE
            and entry.submitter.role == FeedbackRole.DOMAIN_EXPERT
            and not entry.citations
        ):
            warnings.append(
                "Domain expert challenges are more effective with citations. "
                "Consider adding references to support your challenge."
            )

        passed = len(failures) == 0
        return ValidationResult(
            passed=passed,
            failures=failures,
            warnings=warnings,
            entry=entry,
        )

    def _extract_finding_ids(self, consequence_map: dict) -> set[str]:
        """
        Extract all finding IDs from a consequence map dict.

        Findings are nested inside channel_outputs → findings.
        Also checks timeframe_impacts and population_impacts for
        finding references.
        """
        ids = set()

        # From channel_outputs (serialized ChannelOutput dicts)
        for channel_output in consequence_map.get("channel_outputs", []):
            for finding in channel_output.get("findings", []):
                fid = finding.get("finding_id")
                if fid:
                    ids.add(fid)

        # From timeframe_impacts (ImpactSummary dicts)
        for impact in consequence_map.get("timeframe_impacts", []):
            for key in ("harm_findings", "benefit_findings", "neutral_findings"):
                for finding in impact.get(key, []):
                    fid = finding.get("finding_id")
                    if fid:
                        ids.add(fid)

        # From population_impacts
        for impact in consequence_map.get("population_impacts", []):
            for key in ("harm_findings", "benefit_findings"):
                for finding in impact.get(key, []):
                    fid = finding.get("finding_id")
                    if fid:
                        ids.add(fid)

        return ids
