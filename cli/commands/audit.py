"""
commands/audit.py — The 'arbitrator audit' command family.

Subcommands:
    arbitrator audit verify     — Verify the audit log hash chain
    arbitrator audit summary    — Show audit log statistics
    arbitrator audit log        — Browse audit log entries
    arbitrator audit session    — Show all entries for a specific session
    arbitrator audit export     — Export audit log to JSON

The audit log is a tamper-evident append-only chain. Every pipeline run,
ethics evaluation, channel invocation, feedback submission, and human review
decision is recorded. The chain is verified by recomputing each entry's
hash and checking it against the stored value.
"""

from __future__ import annotations

import json
import sys
from typing import Optional

from ..config_manager import ConfigManager
from .. import display


def _open_audit(config: ConfigManager):
    """Open the audit log, returning (log, None) or (None, error_msg)."""
    sys.path.insert(0, "/home/claude/arbitrator")
    from Arbitrator.SeedCore.audit_log.log import AuditLog

    path = config.get("audit_log_path")
    try:
        return AuditLog(path=path), None
    except FileNotFoundError:
        return None, (
            f"Audit log not found: {path}\n"
            "Run 'arbitrator run' to create an audit log."
        )
    except Exception as e:
        return None, f"Failed to open audit log: {e}"


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def audit_verify(config: ConfigManager) -> int:
    """Verify the integrity of the audit log hash chain."""
    audit, err = _open_audit(config)
    if err:
        display.error(err)
        return 2

    display.status("Verifying audit chain integrity...")
    try:
        valid = audit.verify()
    except Exception as e:
        display.error(f"Verification failed with error: {e}")
        return 2

    if valid:
        summary = audit.summary()
        display.success(
            f"Chain integrity verified. "
            f"{summary.get('total_entries', 0)} entries, "
            f"chain tip: {summary.get('current_chain_tip', 'N/A')[:16]}..."
        )
        return 0
    else:
        display.error(
            "Chain integrity check FAILED. "
            "The audit log may have been tampered with or corrupted."
        )
        display.info("Run 'arbitrator audit log' to inspect entries.")
        return 1


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

def audit_summary(config: ConfigManager, json_output: bool = False) -> int:
    """Show audit log statistics."""
    audit, err = _open_audit(config)
    if err:
        display.error(err)
        return 2

    summary = audit.summary()

    if json_output:
        print(json.dumps(summary, indent=2))
        return 0

    print(display.render_audit_summary(summary))
    return 0


# ---------------------------------------------------------------------------
# log
# ---------------------------------------------------------------------------

def audit_log_cmd(
    config: ConfigManager,
    kind: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 40,
    json_output: bool = False,
) -> int:
    """Browse audit log entries with optional filtering."""
    audit, err = _open_audit(config)
    if err:
        display.error(err)
        return 2

    sys.path.insert(0, "/home/claude/arbitrator")
    from Arbitrator.SeedCore.audit_log.log import LogQuery
    from Arbitrator.SeedCore.audit_log.models import EntryKind

    kind_enum = None
    if kind:
        try:
            kind_enum = EntryKind(kind)
        except ValueError:
            valid = [e.value for e in EntryKind]
            display.error(
                f"Unknown entry kind '{kind}'.\n"
                f"Valid kinds: {', '.join(valid)}"
            )
            return 2

    query = LogQuery(kind=kind_enum, since=since, limit=limit)
    entries = audit.query(query)

    if not entries:
        display.info("No entries found matching the filter.")
        return 0

    if json_output:
        print(json.dumps([e.to_public_dict() for e in entries], indent=2))
        return 0

    print(display.section(f"AUDIT LOG  ({len(entries)} entries shown)"))
    print()

    for entry in entries:
        print(display.render_audit_entry(entry.to_public_dict()))
        print()

    return 0


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------

def audit_session(
    config: ConfigManager,
    session_id: str,
    verbose: bool = False,
    json_output: bool = False,
) -> int:
    """Show all audit entries for a specific session."""
    audit, err = _open_audit(config)
    if err:
        display.error(err)
        return 2

    entries = audit.get_session(session_id)

    if not entries:
        display.info(f"No entries found for session: {session_id}")
        return 0

    if json_output:
        print(json.dumps([e.to_public_dict() for e in entries], indent=2))
        return 0

    print(display.section(f"SESSION  {display.dim(session_id[:24])}"))
    print(display.dim(f"  {len(entries)} entries"))
    print()

    for entry in entries:
        d = entry.to_public_dict()
        print(display.render_audit_entry(d))

        if verbose:
            payload = d.get("payload", {})
            if payload:
                print(
                    display.indent_block(
                        json.dumps(payload, indent=2)[:500], spaces=6
                    )
                )
        print()

    return 0


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

def audit_export(
    config: ConfigManager,
    output_file: str,
    since: Optional[str] = None,
    session_id: Optional[str] = None,
) -> int:
    """Export audit log entries to a JSON file."""
    audit, err = _open_audit(config)
    if err:
        display.error(err)
        return 2

    sys.path.insert(0, "/home/claude/arbitrator")
    from Arbitrator.SeedCore.audit_log.log import LogQuery

    query = LogQuery(since=since, session_id=session_id)
    entries = audit.query(query)

    data = [e.to_public_dict() for e in entries]

    try:
        from pathlib import Path
        Path(output_file).write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )
        display.success(
            f"Exported {len(data)} entries to {output_file}"
        )
        return 0
    except OSError as e:
        display.error(f"Failed to write export file: {e}")
        return 2
