"""
commands/feedback.py — The 'arbitrator feedback' command family.

Subcommands:
    arbitrator feedback submit  — Submit feedback against a consequence map
    arbitrator feedback summary — Show aggregated feedback for a map
    arbitrator feedback list    — List recent feedback entries from audit log

The feedback system is trust-weighted and role-tiered. See models.py
for the full role/trust matrix and permission table.
"""

from __future__ import annotations

import sys
from typing import Optional

from ..config_manager import ConfigManager
from .. import display


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------

def feedback_submit(
    config: ConfigManager,
    map_id: str,
    session_id: str,
    submitter_id: str,
    role: str,
    feedback_type: str,
    content: str,
    target_finding_id: Optional[str] = None,
    target_domain: str = "general",
    citations: Optional[list[str]] = None,
    suggested_correction: Optional[str] = None,
    escalation_reason: Optional[str] = None,
) -> int:
    """Submit a feedback entry against a published consequence map."""
    import sys
    sys.path.insert(0, "/home/claude/arbitrator")

    from Arbitrator.SeedCore.feedback import (
        FeedbackProcessor, FeedbackRole, FeedbackType
    )
    from Arbitrator.SeedCore.audit_log.log import AuditLog

    # Validate role
    try:
        role_enum = FeedbackRole(role)
    except ValueError:
        valid = [r.value for r in FeedbackRole]
        display.error(f"Invalid role '{role}'. Valid roles: {', '.join(valid)}")
        return 2

    # Validate feedback type
    try:
        type_enum = FeedbackType(feedback_type)
    except ValueError:
        valid = [t.value for t in FeedbackType]
        display.error(f"Invalid feedback type '{feedback_type}'.\nValid types: {', '.join(valid)}")
        return 2

    # Build processor
    try:
        audit = AuditLog(path=config.get("audit_log_path"))
        processor = FeedbackProcessor(
            audit_log=audit,
            ledger_path=config.get("feedback_ledger_path"),
            node_id=config.get("node_id"),
        )
    except Exception as e:
        display.error(f"Failed to initialize feedback processor: {e}")
        return 2

    display.status(
        f"Submitting {feedback_type} as {role} "
        f"against map {map_id[:16]}..."
    )

    result = processor.submit(
        map_id=map_id,
        session_id=session_id,
        submitter_id=submitter_id,
        role=role_enum,
        feedback_type=type_enum,
        content=content,
        target_finding_id=target_finding_id,
        target_domain=target_domain,
        citations=citations or [],
        suggested_correction=suggested_correction,
        escalation_reason=escalation_reason,
    )

    if result.accepted:
        display.success(f"Feedback accepted. ID: {result.feedback_id}")
        if result.validation_warnings:
            for w in result.validation_warnings:
                display.warn(w)
        if result.escalation_triggered:
            display.warn(
                "Escalation threshold crossed. "
                "This map has been flagged for human review."
            )
            display.warn(
                f"Use 'arbitrator feedback review' to record a review decision."
            )
        return 0
    else:
        display.error("Feedback rejected:")
        for failure in result.validation_failures:
            display.error(f"  {failure}")
        return 1


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def feedback_summary(
    config: ConfigManager,
    map_id: str,
    json_output: bool = False,
) -> int:
    """Display aggregated feedback for a consequence map."""
    import sys
    sys.path.insert(0, "/home/claude/arbitrator")

    from Arbitrator.SeedCore.feedback import FeedbackProcessor
    from Arbitrator.SeedCore.audit_log.log import AuditLog, LogQuery
    from Arbitrator.SeedCore.audit_log.models import EntryKind

    try:
        audit = AuditLog(path=config.get("audit_log_path"))
        processor = FeedbackProcessor(
            audit_log=audit,
            ledger_path=config.get("feedback_ledger_path"),
            node_id=config.get("node_id"),
        )
    except Exception as e:
        display.error(f"Failed to initialize feedback processor: {e}")
        return 2

    # Replay all FEEDBACK_RECEIVED entries for this map to rebuild summary
    try:
        query = LogQuery(kind=EntryKind.FEEDBACK_RECEIVED)
        entries = audit.query(query)
    except Exception as e:
        display.error(f"Failed to query audit log: {e}")
        return 2

    # Filter to this map and replay into processor
    map_entries = [
        e for e in entries
        if map_id in (e.related_ids or []) or
           e.payload.get("map_id") == map_id
    ]

    if not map_entries:
        display.info(f"No feedback found for map {map_id[:24]}")
        display.info("Submit feedback with: arbitrator feedback submit ...")
        return 0

    from Arbitrator.SeedCore.feedback.models import (
        FeedbackRole, FeedbackType, FeedbackEntry, Submitter
    )

    for entry_log in map_entries:
        payload = entry_log.payload
        try:
            role = FeedbackRole(payload.get("submitter_role", "citizen"))
            submitter = Submitter(
                submitter_id=payload.get("submitter_id", "unknown"),
                role=role,
            )
            ftype = FeedbackType(payload.get("feedback_type", "general_comment"))
            entry = FeedbackEntry(
                map_id=payload.get("map_id", map_id),
                session_id=payload.get("session_id", ""),
                submitter=submitter,
                feedback_type=ftype,
                content=payload.get("content", ""),
                target_finding_id=payload.get("target_finding_id"),
                target_domain=payload.get("target_domain", "general"),
                citations=payload.get("citations", []),
                suggested_correction=payload.get("suggested_correction"),
                escalation_reason=payload.get("escalation_reason"),
            )
            processor._aggregator.integrate(entry)
        except Exception:
            continue  # Skip malformed entries

    summary = processor.get_summary(map_id)
    if not summary:
        display.info(f"No valid feedback could be aggregated for map {map_id[:24]}")
        return 0

    if json_output:
        import json
        print(json.dumps(summary.to_dict(), indent=2))
        return 0

    print(display.render_feedback_summary(summary.to_dict()))
    return 0


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def feedback_list(
    config: ConfigManager,
    session_id: Optional[str] = None,
    map_id: Optional[str] = None,
    limit: int = 20,
    json_output: bool = False,
) -> int:
    """List recent feedback entries from the audit log."""
    import sys, json
    sys.path.insert(0, "/home/claude/arbitrator")

    from Arbitrator.SeedCore.audit_log.log import AuditLog, LogQuery
    from Arbitrator.SeedCore.audit_log.models import EntryKind

    try:
        audit = AuditLog(path=config.get("audit_log_path"))
    except Exception as e:
        display.error(f"Failed to open audit log: {e}")
        return 2

    query = LogQuery(
        kind=EntryKind.FEEDBACK_RECEIVED,
        session_id=session_id,
        limit=limit,
    )
    entries = audit.query(query)

    if map_id:
        entries = [
            e for e in entries
            if map_id in (e.related_ids or []) or
               e.payload.get("map_id") == map_id
        ]

    if not entries:
        display.info("No feedback entries found.")
        if session_id:
            display.info(f"Session: {session_id}")
        return 0

    if json_output:
        print(json.dumps([e.to_public_dict() for e in entries], indent=2))
        return 0

    print(display.section(f"FEEDBACK ENTRIES ({len(entries)})"))
    for e in entries:
        payload = e.payload
        ftype = payload.get("feedback_type", "unknown")
        role = payload.get("submitter_role", "unknown")
        mid = payload.get("map_id", "")[:16]
        weight = payload.get("trust_weight", 0)
        content_preview = payload.get("content", "")[:80]
        logged = e.logged_at[:19]

        print(
            f"\n  {display.bold(ftype.replace('_', ' ').upper())}"
            f"  {display.dim('[' + role + ']')}"
            f"  {display.dim('weight: ' + str(round(weight, 3)))}"
        )
        print(f"  {display.dim('map: ' + mid + '  ' + logged)}")
        print(f"  {display.dim(content_preview)}")

    return 0


# ---------------------------------------------------------------------------
# review
# ---------------------------------------------------------------------------

def feedback_review(
    config: ConfigManager,
    session_id: str,
    map_id: str,
    reviewer_id: str,
    decision: str,
    rationale: str,
) -> int:
    """Record a human reviewer's decision on an escalated map."""
    import sys
    sys.path.insert(0, "/home/claude/arbitrator")

    valid_decisions = {"approve", "reject", "defer", "amend"}
    if decision not in valid_decisions:
        display.error(
            f"Invalid decision '{decision}'. "
            f"Valid decisions: {', '.join(sorted(valid_decisions))}"
        )
        return 2

    from Arbitrator.SeedCore.feedback import FeedbackProcessor
    from Arbitrator.SeedCore.audit_log.log import AuditLog

    try:
        audit = AuditLog(path=config.get("audit_log_path"))
        processor = FeedbackProcessor(
            audit_log=audit,
            ledger_path=config.get("feedback_ledger_path"),
            node_id=config.get("node_id"),
        )
    except Exception as e:
        display.error(f"Failed to initialize feedback processor: {e}")
        return 2

    processor.record_review_decision(
        session_id=session_id,
        reviewer_id=reviewer_id,
        map_id=map_id,
        decision=decision,
        rationale=rationale,
    )

    display.success(
        f"Review decision '{decision}' recorded for map {map_id[:16]}."
    )
    return 0
