"""
main.py — Arbitrator CLI entry point.

Usage:
    python -m Arbitrator.cli run "Proposed policy text"
    python -m Arbitrator.cli run --verbose "..."
    python -m Arbitrator.cli run --ethics-only "..."
    python -m Arbitrator.cli run --json "..."
    python -m Arbitrator.cli run --output result.txt "..."

    python -m Arbitrator.cli feedback submit \\
        --map-id <map_id> --session-id <session_id> \\
        --submitter-id <id> --role domain_expert \\
        --type finding_challenge \\
        --finding <finding_id> --domain economic \\
        "The harm estimate is overstated because..."

    python -m Arbitrator.cli feedback summary --map-id <map_id>
    python -m Arbitrator.cli feedback list [--session <id>] [--limit 20]
    python -m Arbitrator.cli feedback review \\
        --session-id <id> --map-id <id> \\
        --reviewer-id <id> --decision approve \\
        "Rationale for approval."

    python -m Arbitrator.cli audit verify
    python -m Arbitrator.cli audit summary
    python -m Arbitrator.cli audit log [--kind <kind>] [--limit 40]
    python -m Arbitrator.cli audit session <session_id>
    python -m Arbitrator.cli audit export output.json

    python -m Arbitrator.cli config show
    python -m Arbitrator.cli config set <key> <value>
    python -m Arbitrator.cli config init
    python -m Arbitrator.cli config reset

Exit codes:
    0   Success, partial success, or escalated (analysis produced)
    1   Ethics blocked (hard reject or fail) / feedback rejected
    2   Pipeline failure / invalid arguments / system error
"""

from __future__ import annotations

import argparse
import sys
import os

# Ensure the package root is on the path when invoked directly
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from Arbitrator.cli.config_manager import ConfigManager
from Arbitrator.cli import display


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

VERSION = "0.1.0"
DESCRIPTION = (
    "Arbitrator — Ethical deliberation and decision-education for policymakers.\n"
    "Analyzes the likely consequences of proposed actions before implementation."
)


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arbitrator",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  arbitrator run \"Proposed carbon tax of $50 per tonne.\"\n"
            "  arbitrator run --verbose --ethics-only \"...\"\n"
            "  arbitrator feedback submit --map-id <id> --session-id <id> \\\n"
            "      --submitter-id me --role domain_expert \\\n"
            "      --type finding_challenge --finding <finding_id> \\\n"
            "      \"The harm estimate overstates the inflationary risk...\"\n"
            "  arbitrator audit verify\n"
            "  arbitrator audit session <session_id>\n"
            "  arbitrator config set backend mock\n"
        ),
    )

    parser.add_argument(
        "--version", action="version", version=f"arbitrator {VERSION}"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable terminal color output"
    )
    parser.add_argument(
        "--config", metavar="PATH",
        help="Path to config file (default: global_config.yaml)"
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    _add_run_parser(subparsers)
    _add_feedback_parser(subparsers)
    _add_audit_parser(subparsers)
    _add_config_parser(subparsers)
    _add_models_parser(subparsers)

    return parser


# ---------------------------------------------------------------------------
# 'run' subcommand
# ---------------------------------------------------------------------------

def _add_run_parser(subparsers):
    p = subparsers.add_parser(
        "run",
        help="Analyze a policy proposal",
        description=(
            "Submit a proposal to the full analysis pipeline.\n\n"
            "The pipeline runs Ethics Core evaluation, invokes relevant\n"
            "specialist channels, synthesizes findings into a consequence\n"
            "map, and presents it for review.\n\n"
            "Use '-' as proposal text to read from stdin."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "proposal",
        help="Proposal text to analyze, or '-' to read from stdin",
    )
    p.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show full findings, ripple effects, and uncertainty register",
    )
    p.add_argument(
        "--ethics-only", action="store_true",
        help="Run only the Ethics Core evaluation (skip channels)",
    )
    p.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output raw JSON result",
    )
    p.add_argument(
        "--output", "-o", metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    p.add_argument(
        "--no-pager", action="store_true",
        help="Disable pager even in verbose mode",
    )


# ---------------------------------------------------------------------------
# 'feedback' subcommand
# ---------------------------------------------------------------------------

def _add_feedback_parser(subparsers):
    p = subparsers.add_parser(
        "feedback",
        help="Submit or review feedback on a consequence map",
        description=(
            "Interact with the trust-weighted feedback system.\n\n"
            "Feedback is role-tiered: different roles have different\n"
            "base trust weights per domain, and different permissions\n"
            "for which feedback types they may submit.\n\n"
            "Roles: citizen, affected_party, domain_expert,\n"
            "       policymaker, ethicist, reviewer\n\n"
            "Types: finding_challenge, finding_support, data_correction,\n"
            "       adversarial_challenge, mitigation_suggestion,\n"
            "       general_comment, escalation_request"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    fsub = p.add_subparsers(dest="feedback_command", metavar="<subcommand>")

    # submit
    fs = fsub.add_parser(
        "submit",
        help="Submit feedback against a consequence map",
    )
    fs.add_argument("content", help="Feedback text")
    fs.add_argument("--map-id", required=True, metavar="ID",
                    help="Map ID from the consequence map")
    fs.add_argument("--session-id", required=True, metavar="ID",
                    help="Session ID from the analysis run")
    fs.add_argument("--submitter-id", required=True, metavar="ID",
                    help="Your stable pseudonymous identifier")
    fs.add_argument("--role", required=True,
                    choices=["citizen", "affected_party", "domain_expert",
                             "policymaker", "ethicist", "reviewer"],
                    help="Your role")
    fs.add_argument("--type", required=True, dest="feedback_type",
                    choices=["finding_challenge", "finding_support",
                             "data_correction", "adversarial_challenge",
                             "mitigation_suggestion", "general_comment",
                             "escalation_request"],
                    help="Type of feedback")
    fs.add_argument("--finding", metavar="FINDING_ID",
                    help="Target finding ID (required for challenge/support)")
    fs.add_argument("--domain", default="general",
                    choices=["general", "economic", "ecological",
                             "social_demographic", "ethical_adversarial",
                             "historical_precedent", "legal_institutional",
                             "geopolitical", "uncertainty_modeling"],
                    help="Domain this feedback primarily addresses")
    fs.add_argument("--citation", action="append", dest="citations",
                    metavar="REFERENCE",
                    help="Supporting reference (repeatable)")
    fs.add_argument("--correction", metavar="TEXT",
                    help="Corrected value (required for data_correction)")
    fs.add_argument("--escalation-reason", metavar="TEXT",
                    help="Grounds for escalation (required for escalation_request)")

    # summary
    fsum = fsub.add_parser(
        "summary",
        help="Show aggregated feedback for a consequence map",
    )
    fsum.add_argument("--map-id", required=True, metavar="ID",
                      help="Map ID to summarize")
    fsum.add_argument("--json", dest="json_output", action="store_true",
                      help="Output raw JSON")

    # list
    flist = fsub.add_parser(
        "list",
        help="List recent feedback entries",
    )
    flist.add_argument("--session", metavar="SESSION_ID",
                       help="Filter to a specific session")
    flist.add_argument("--map-id", metavar="MAP_ID",
                       help="Filter to a specific map")
    flist.add_argument("--limit", type=int, default=20,
                       help="Maximum entries to show (default: 20)")
    flist.add_argument("--json", dest="json_output", action="store_true",
                       help="Output raw JSON")

    # review
    frev = fsub.add_parser(
        "review",
        help="Record a human reviewer decision on an escalated map",
    )
    frev.add_argument("rationale", help="Rationale for the review decision")
    frev.add_argument("--session-id", required=True, metavar="ID")
    frev.add_argument("--map-id", required=True, metavar="ID")
    frev.add_argument("--reviewer-id", required=True, metavar="ID")
    frev.add_argument("--decision", required=True,
                      choices=["approve", "reject", "defer", "amend"],
                      help="Review decision")


# ---------------------------------------------------------------------------
# 'audit' subcommand
# ---------------------------------------------------------------------------

def _add_audit_parser(subparsers):
    p = subparsers.add_parser(
        "audit",
        help="Inspect and verify the audit log",
        description=(
            "The audit log is a tamper-evident append-only hash chain.\n"
            "Every pipeline run, ethics evaluation, channel invocation,\n"
            "feedback submission, and human review decision is recorded.\n\n"
            "The chain is verified by recomputing each entry's hash and\n"
            "checking it against the stored value. Any modification to\n"
            "any entry — or any deletion — breaks the chain."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    asub = p.add_subparsers(dest="audit_command", metavar="<subcommand>")

    # verify
    asub.add_parser("verify", help="Verify audit chain integrity")

    # summary
    asum = asub.add_parser("summary", help="Show audit log statistics")
    asum.add_argument("--json", dest="json_output", action="store_true")

    # log
    alog = asub.add_parser("log", help="Browse audit log entries")
    alog.add_argument("--kind", metavar="KIND",
                      help="Filter to entry kind (e.g. pipeline_run, feedback_received)")
    alog.add_argument("--since", metavar="ISO_TIMESTAMP",
                      help="Show entries after this timestamp")
    alog.add_argument("--limit", type=int, default=40,
                      help="Maximum entries to show (default: 40)")
    alog.add_argument("--json", dest="json_output", action="store_true")

    # session
    ases = asub.add_parser(
        "session", help="Show all entries for a specific session"
    )
    ases.add_argument("session_id", help="Session UUID to inspect")
    ases.add_argument("--verbose", "-v", action="store_true",
                      help="Include full payload for each entry")
    ases.add_argument("--json", dest="json_output", action="store_true")

    # export
    aexp = asub.add_parser("export", help="Export audit log to JSON")
    aexp.add_argument("output_file", help="Output file path")
    aexp.add_argument("--since", metavar="ISO_TIMESTAMP",
                      help="Export entries after this timestamp")
    aexp.add_argument("--session", metavar="SESSION_ID",
                      help="Export entries for a specific session")


# ---------------------------------------------------------------------------
# 'config' subcommand
# ---------------------------------------------------------------------------

def _add_config_parser(subparsers):
    p = subparsers.add_parser(
        "config",
        help="View and manage configuration",
        description=(
            "Manage global_config.yaml.\n\n"
            "Key configuration values:\n"
            "  audit_log_path        Path to the audit log file\n"
            "  feedback_ledger_path  Path to the trust ledger file\n"
            "  backend               Backend to use: auto|anthropic|ollama|mock\n"
            "  node_id               This node's identifier\n"
            "  color                 Enable terminal color: true|false\n"
            "  verbose               Default verbose mode: true|false\n"
            "  pager                 Use pager for long output: true|false\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    csub = p.add_subparsers(dest="config_command", metavar="<subcommand>")

    csub.add_parser("show",  help="Display current configuration")
    csub.add_parser("init",  help="Write default config if none exists")
    csub.add_parser("reset", help="Reset all values to defaults")

    cset = csub.add_parser("set", help="Set a configuration value")
    cset.add_argument("key",   help="Configuration key")
    cset.add_argument("value", help="Value to set")


def _add_models_parser(subparsers):
    p = subparsers.add_parser(
        "models",
        help="Inspect and manage model profiles and selections",
        description=(
            "Inspect model profiles, check backend availability, explain per-channel\n"
            "model selection rankings, and register custom model profiles."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    msub = p.add_subparsers(dest="models_command", metavar="<subcommand>")

    ml = msub.add_parser("list",      help="List all registered model profiles")
    ml.add_argument("--json", action="store_true", help="Output as JSON")

    ma = msub.add_parser("available", help="Show which backends are currently reachable")
    ma.add_argument("--json", action="store_true", help="Output as JSON")

    me = msub.add_parser("explain",   help="Show per-channel model rankings")
    me.add_argument("--channel", metavar="CHANNEL", help="Limit to one channel")
    me.add_argument("--json", action="store_true", help="Output as JSON")

    mr = msub.add_parser("register",  help="Register a custom model profile from JSON file")
    mr.add_argument("profile_file", help="Path to JSON file containing model profile")


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(args: argparse.Namespace, config: ConfigManager) -> int:

    # ── run ──────────────────────────────────────────────────────────────────
    if args.command == "run":
        from Arbitrator.cli.commands.run import run_command
        return run_command(
            proposal=args.proposal,
            config=config,
            verbose=args.verbose,
            ethics_only=args.ethics_only,
            output_file=getattr(args, "output", None),
            json_output=getattr(args, "json_output", False),
        )

    # ── feedback ─────────────────────────────────────────────────────────────
    if args.command == "feedback":
        from Arbitrator.cli.commands import feedback as fb

        sub = getattr(args, "feedback_command", None)
        if sub is None:
            display.error("Specify a feedback subcommand: submit, summary, list, review")
            display.info("Run 'arbitrator feedback --help' for usage.")
            return 2

        if sub == "submit":
            return fb.feedback_submit(
                config=config,
                map_id=args.map_id,
                session_id=args.session_id,
                submitter_id=args.submitter_id,
                role=args.role,
                feedback_type=args.feedback_type,
                content=args.content,
                target_finding_id=getattr(args, "finding", None),
                target_domain=getattr(args, "domain", "general"),
                citations=getattr(args, "citations", None),
                suggested_correction=getattr(args, "correction", None),
                escalation_reason=getattr(args, "escalation_reason", None),
            )

        if sub == "summary":
            return fb.feedback_summary(
                config=config,
                map_id=args.map_id,
                json_output=getattr(args, "json_output", False),
            )

        if sub == "list":
            return fb.feedback_list(
                config=config,
                session_id=getattr(args, "session", None),
                map_id=getattr(args, "map_id", None),
                limit=args.limit,
                json_output=getattr(args, "json_output", False),
            )

        if sub == "review":
            return fb.feedback_review(
                config=config,
                session_id=args.session_id,
                map_id=args.map_id,
                reviewer_id=args.reviewer_id,
                decision=args.decision,
                rationale=args.rationale,
            )

        display.error(f"Unknown feedback subcommand: {sub}")
        return 2

    # ── audit ─────────────────────────────────────────────────────────────────
    if args.command == "audit":
        from Arbitrator.cli.commands import audit as aud

        sub = getattr(args, "audit_command", None)
        if sub is None:
            display.error("Specify an audit subcommand: verify, summary, log, session, export")
            display.info("Run 'arbitrator audit --help' for usage.")
            return 2

        if sub == "verify":
            return aud.audit_verify(config)

        if sub == "summary":
            return aud.audit_summary(
                config,
                json_output=getattr(args, "json_output", False),
            )

        if sub == "log":
            return aud.audit_log_cmd(
                config=config,
                kind=getattr(args, "kind", None),
                since=getattr(args, "since", None),
                limit=args.limit,
                json_output=getattr(args, "json_output", False),
            )

        if sub == "session":
            return aud.audit_session(
                config=config,
                session_id=args.session_id,
                verbose=getattr(args, "verbose", False),
                json_output=getattr(args, "json_output", False),
            )

        if sub == "export":
            return aud.audit_export(
                config=config,
                output_file=args.output_file,
                since=getattr(args, "since", None),
                session_id=getattr(args, "session", None),
            )

        display.error(f"Unknown audit subcommand: {sub}")
        return 2

    # ── config ────────────────────────────────────────────────────────────────
    if args.command == "config":
        from Arbitrator.cli.commands import config as cfg_cmd

        sub = getattr(args, "config_command", None)
        if sub is None:
            display.error("Specify a config subcommand: show, set, init, reset")
            display.info("Run 'arbitrator config --help' for usage.")
            return 2

        if sub == "show":  return cfg_cmd.config_show(config)
        if sub == "set":   return cfg_cmd.config_set(config, args.key, args.value)
        if sub == "init":  return cfg_cmd.config_init(config)
        if sub == "reset": return cfg_cmd.config_reset(config)

        display.error(f"Unknown config subcommand: {sub}")
        return 2

    # ── models ───────────────────────────────────────────────────────────────
    if args.command == "models":
        from Arbitrator.cli.commands.models import (
            models_list, models_available, models_explain, models_register
        )
        sub = getattr(args, "models_command", None)
        if sub is None:
            display.error("Specify a models subcommand: list, available, explain, register")
            display.info("Run 'arbitrator models --help' for usage.")
            return 2

        json_out = getattr(args, "json", False)
        if sub == "list":      return models_list(config, json_output=json_out)
        if sub == "available": return models_available(config, json_output=json_out)
        if sub == "explain":
            channel = getattr(args, "channel", None)
            return models_explain(config, channel=channel, json_output=json_out)
        if sub == "register":  return models_register(config, args.profile_file)

        display.error(f"Unknown models subcommand: {sub}")
        return 2

    # No command
    build_parser().print_help()
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Load config
    config_path = None
    if hasattr(args, "config") and args.config:
        from pathlib import Path
        config_path = Path(args.config)
    config = ConfigManager(config_path=config_path)

    # Apply --no-color (also respect config value)
    use_color = config.get("color", True)
    if getattr(args, "no_color", False):
        use_color = False
    if not sys.stdout.isatty():
        use_color = False
    display.set_color(use_color)

    # No command: print help
    if not args.command:
        parser.print_help()
        return 0

    try:
        return dispatch(args, config)
    except KeyboardInterrupt:
        print()
        display.warn("Interrupted.")
        return 130
    except Exception as e:
        display.error(f"Unexpected error: {e}")
        if config.get("verbose"):
            import traceback
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())
