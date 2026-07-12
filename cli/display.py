"""
display.py — Terminal rendering for the Arbitrator CLI.

All display logic lives here. Commands produce data; display.py renders it.
This separation means the rendering can be tested independently and
changed (e.g., to JSON output mode, or a different color scheme) without
touching command logic.

DESIGN:
    - Pure ANSI escape codes, no third-party dependencies
    - Color can be disabled globally via config or --no-color flag
    - Width-aware: wraps to terminal width, defaults to 80 if unavailable
    - Pager support: long output can be paged via 'less -R'
    - Section headers, verdict banners, finding cards, progress lines
"""

from __future__ import annotations

import os
import sys
import textwrap
from typing import Optional


# ---------------------------------------------------------------------------
# ANSI color codes
# ---------------------------------------------------------------------------

class C:
    """ANSI color/style codes. Applied only when color is enabled."""
    RESET     = "\033[0m"
    BOLD      = "\033[1m"
    DIM       = "\033[2m"
    ITALIC    = "\033[3m"

    BLACK     = "\033[30m"
    RED       = "\033[31m"
    GREEN     = "\033[32m"
    YELLOW    = "\033[33m"
    BLUE      = "\033[34m"
    MAGENTA   = "\033[35m"
    CYAN      = "\033[36m"
    WHITE     = "\033[37m"

    BG_RED    = "\033[41m"
    BG_GREEN  = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE   = "\033[44m"


_color_enabled: bool = True


def set_color(enabled: bool) -> None:
    global _color_enabled
    _color_enabled = enabled


def _c(code: str, text: str) -> str:
    if not _color_enabled:
        return text
    return f"{code}{text}{C.RESET}"


def bold(text: str) -> str:       return _c(C.BOLD, text)
def dim(text: str) -> str:        return _c(C.DIM, text)
def red(text: str) -> str:        return _c(C.RED, text)
def green(text: str) -> str:      return _c(C.GREEN, text)
def yellow(text: str) -> str:     return _c(C.YELLOW, text)
def blue(text: str) -> str:       return _c(C.BLUE, text)
def cyan(text: str) -> str:       return _c(C.CYAN, text)
def magenta(text: str) -> str:    return _c(C.MAGENTA, text)


# ---------------------------------------------------------------------------
# Terminal width
# ---------------------------------------------------------------------------

def _width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 80


def _wrap(text: str, indent: int = 0) -> str:
    width = _width() - indent
    prefix = " " * indent
    return textwrap.fill(text, width=width, subsequent_indent=prefix,
                         initial_indent=prefix)


# ---------------------------------------------------------------------------
# Core primitives
# ---------------------------------------------------------------------------

def rule(char: str = "─") -> str:
    return dim(char * min(_width(), 80))


def section(title: str) -> str:
    bar = rule()
    return f"\n{bar}\n  {bold(title)}\n{bar}"


def kv(key: str, value: str, width: int = 22) -> str:
    return f"  {dim(key.ljust(width))} {value}"


def indent_block(text: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.splitlines())


# ---------------------------------------------------------------------------
# Score bars
# ---------------------------------------------------------------------------

def score_bar(value: float, width: int = 20, fill: str = "█", empty: str = "░") -> str:
    if value is None:
        return dim("  [no score]")
    filled = round(value * width)
    bar = fill * filled + empty * (width - filled)
    if value >= 0.7:
        color = red if fill == "█" else green
    elif value >= 0.4:
        color = yellow
    else:
        color = green if fill == "█" else dim
    return color(bar) + f"  {value:.2f}"


def harm_bar(value: float, width: int = 20) -> str:
    return score_bar(value, width, fill="█", empty="░")


def benefit_bar(value: float, width: int = 20) -> str:
    if value is None:
        return dim("  [no score]")
    filled = round(value * width)
    bar = "█" * filled + "░" * (width - filled)
    color_fn = green if value >= 0.5 else yellow if value >= 0.3 else dim
    return color_fn(bar) + f"  {value:.2f}"


# ---------------------------------------------------------------------------
# Verdict rendering
# ---------------------------------------------------------------------------

_VERDICT_STYLES: dict[str, tuple[str, str]] = {
    "pass":             ("✓  PASS",          C.GREEN),
    "fail":             ("✗  FAIL",          C.RED),
    "ambiguous":        ("?  AMBIGUOUS",     C.YELLOW),
    "escalate":         ("⚑  ESCALATE",      C.MAGENTA),
    "hard_reject":      ("✗  HARD REJECT",   C.RED + C.BOLD),
    "net_beneficial":   ("↑  NET BENEFICIAL", C.GREEN),
    "net_harmful":      ("↓  NET HARMFUL",   C.RED),
    "mixed":            ("⇄  MIXED",         C.YELLOW),
    "requires_review":  ("⚑  REQUIRES REVIEW", C.MAGENTA),
    "insufficient_data": ("?  INSUFFICIENT DATA", C.DIM),
    "success":          ("✓  SUCCESS",       C.GREEN),
    "partial":          ("~  PARTIAL",       C.YELLOW),
    "ethics_blocked":   ("✗  ETHICS BLOCKED", C.RED),
    "escalated":        ("⚑  ESCALATED",     C.MAGENTA),
    "failed":           ("✗  FAILED",        C.RED),
}


def verdict_badge(verdict: str) -> str:
    label, color = _VERDICT_STYLES.get(
        verdict.lower(), (verdict.upper(), C.DIM)
    )
    if not _color_enabled:
        return f"[ {label} ]"
    return f"{color}{C.BOLD}  {label}  {C.RESET}"


def direction_badge(direction: str) -> str:
    styles = {
        "harm":    (red,     "▼ HARM"),
        "benefit": (green,   "▲ BENEFIT"),
        "neutral": (dim,     "● NEUTRAL"),
        "mixed":   (yellow,  "⇄ MIXED"),
    }
    fn, label = styles.get(direction.lower(), (dim, direction.upper()))
    return fn(label)


def certainty_badge(certainty: str) -> str:
    styles = {
        "high":     (green,  "●●● HIGH"),
        "moderate": (yellow, "●●○ MODERATE"),
        "low":      (red,    "●○○ LOW"),
        "unknown":  (dim,    "○○○ UNKNOWN"),
    }
    fn, label = styles.get(certainty.lower(), (dim, certainty.upper()))
    return fn(label)


# ---------------------------------------------------------------------------
# Consequence map display
# ---------------------------------------------------------------------------

def render_pipeline_result(result: dict, verbose: bool = False) -> str:
    """Render a complete PipelineResult dict as terminal output."""
    lines = []

    # Header
    lines.append("")
    lines.append(bold("  ARBITRATOR ANALYSIS"))
    lines.append(rule())

    status = result.get("status", "unknown")
    session = result.get("session_id", "")[:16]
    duration = result.get("duration_ms")
    dur_str = f"  {dim(f'{duration}ms')}" if duration else ""

    lines.append(kv("Session", dim(session) + dur_str))
    lines.append(kv("Status", verdict_badge(status)))

    # Ethics verdict
    ev = result.get("ethics_verdict")
    if ev:
        lines.append(kv("Ethics verdict", verdict_badge(ev)))

    # Synthesis verdict
    sv = result.get("synthesis_verdict")
    if sv:
        lines.append(kv("Synthesis verdict", verdict_badge(sv)))

    # Channel summary
    invoked = result.get("channels_invoked", [])
    succeeded = result.get("channels_succeeded", [])
    if invoked:
        lines.append(kv("Channels",
            f"{green(str(len(succeeded)))} succeeded / "
            f"{str(len(invoked))} invoked"
        ))

    # Errors
    for err in result.get("errors", []):
        lines.append(f"  {red('ERROR')}  {err}")

    # Warnings
    for warn in result.get("warnings", []):
        lines.append(f"  {yellow('WARN')}   {warn}")

    # Consequence map
    cm = result.get("consequence_map")
    if cm:
        lines.extend(_render_consequence_map(cm, verbose=verbose))

    lines.append("")
    lines.append(rule())
    lines.append(dim(f"  Map ID: {cm.get('map_id', 'N/A') if cm else 'N/A'}"))
    lines.append(dim(f"  Session: {session}"))
    lines.append(dim("  Use 'arbitrator feedback submit' to respond to this analysis."))
    lines.append(dim("  Use 'arbitrator audit verify' to verify the audit chain."))
    lines.append("")

    return "\n".join(lines)


def _render_consequence_map(cm: dict, verbose: bool = False) -> list[str]:
    lines = []

    # Scores
    lines.append(section("CONSEQUENCE MAP"))
    harm = cm.get("overall_harm_score")
    benefit = cm.get("overall_benefit_score")
    net = cm.get("net_score")
    confidence = cm.get("synthesis_confidence")

    lines.append(kv("Harm",     harm_bar(harm) if harm is not None else dim("N/A")))
    lines.append(kv("Benefit",  benefit_bar(benefit) if benefit is not None else dim("N/A")))
    if net is not None:
        net_color = green if net > 0.1 else red if net < -0.1 else yellow
        lines.append(kv("Net score", net_color(f"{net:+.2f}")))
    if confidence is not None:
        lines.append(kv("Confidence", dim(f"{confidence:.2f}")))

    # Executive summary
    summary = cm.get("executive_summary", "")
    if summary:
        lines.append("")
        lines.append(f"  {bold('Summary')}")
        for para in summary.split(". "):
            if para.strip():
                lines.append(_wrap(para.strip() + ".", indent=4))

    # Findings by channel
    channel_outputs = cm.get("channel_outputs", [])
    successful = [co for co in channel_outputs if co.get("status") == "success"]
    if successful:
        lines.append(section("FINDINGS BY CHANNEL"))
        for co in successful:
            lines.extend(_render_channel_output(co, verbose=verbose))

    # Timeframe impacts
    timeframes = cm.get("timeframe_impacts", [])
    if timeframes and verbose:
        lines.append(section("TIMEFRAME IMPACTS"))
        for tf in timeframes:
            lines.extend(_render_timeframe(tf))

    # Population impacts
    populations = cm.get("population_impacts", [])
    if populations:
        lines.append(section("POPULATION IMPACTS"))
        for pop in populations[:8]:  # cap at 8 to keep readable
            lines.extend(_render_population_impact(pop))

    # Adversarial challenges
    challenges = cm.get("adversarial_challenges", [])
    if challenges:
        lines.append(section("ADVERSARIAL CHALLENGES"))
        for i, ch in enumerate(challenges, 1):
            lines.append(f"  {yellow(str(i) + '.')} {_wrap(ch, indent=5).lstrip()}")

    # Ripple effects
    ripples = cm.get("ripple_effects", [])
    if ripples and verbose:
        lines.append(section("RIPPLE EFFECTS"))
        for r in ripples:
            desc = r.get("description", "")
            direction = r.get("direction", "neutral")
            lines.append(f"  {direction_badge(direction)}  {_wrap(desc, indent=5).lstrip()}")
            note = r.get("certainty_note", "")
            if note:
                lines.append(f"      {dim(note)}")

    # Uncertainty register
    uncertainty = cm.get("uncertainty_register", [])
    if uncertainty and verbose:
        lines.append(section("UNCERTAINTY REGISTER"))
        for note in uncertainty:
            desc = note.get("description", "")
            mag = note.get("magnitude", 0)
            lines.append(f"  {_wrap(desc, indent=4).lstrip()}")
            lines.append(f"      {dim(f'Magnitude: {mag:.2f}')}")

    # Recommended mitigations
    mitigations = cm.get("recommended_mitigations", [])
    if mitigations:
        lines.append(section("RECOMMENDED MITIGATIONS"))
        for m in mitigations:
            lines.append(f"  {cyan('→')} {_wrap(m, indent=4).lstrip()}")

    # Data gaps
    gaps = cm.get("data_gaps", [])
    failed = cm.get("channels_failed", [])
    if gaps or failed:
        lines.append(section("DATA GAPS"))
        for gap in gaps:
            lines.append(f"  {yellow('△')} {_wrap(gap, indent=4).lstrip()}")

    return lines


def _render_channel_output(co: dict, verbose: bool = False) -> list[str]:
    lines = []
    name = co.get("channel_name", "unknown").replace("_", " ").title()
    confidence = co.get("confidence")
    conf_str = f"  {dim(f'confidence: {confidence:.2f}')}" if confidence else ""
    lines.append(f"\n  {bold(name)}{conf_str}")

    # Domain summary
    summary = co.get("domain_summary", "")
    if summary and verbose:
        lines.append(_wrap(summary, indent=4))

    # Findings
    findings = co.get("findings", [])
    for f in findings:
        lines.extend(_render_finding(f, verbose=verbose))

    return lines


def _render_finding(f: dict, verbose: bool = False, indent: int = 4) -> list[str]:
    lines = []
    direction = f.get("direction", "neutral")
    summary = f.get("summary", "")
    magnitude = f.get("magnitude", 0)
    certainty = f.get("certainty", "unknown")
    timeframe = f.get("timeframe", "").replace("_", " ")
    groups = f.get("affected_groups", [])
    reversible = f.get("reversible")

    pad = " " * indent
    lines.append(
        f"{pad}{direction_badge(direction)}  "
        f"{_wrap(summary, indent=indent+12).lstrip()}"
    )
    meta_parts = [
        f"magnitude: {magnitude:.2f}",
        certainty_badge(certainty),
        dim(timeframe),
    ]
    if reversible is False:
        meta_parts.append(red("IRREVERSIBLE"))
    elif reversible is True:
        meta_parts.append(dim("reversible"))
    lines.append(f"{pad}{'  ' * 2}{'  '.join(meta_parts)}")

    if groups:
        lines.append(f"{pad}{'  ' * 2}{dim('affects: ' + ', '.join(groups[:4]))}")

    if verbose:
        detail = f.get("detail", "")
        if detail and detail != summary:
            lines.append(_wrap(detail, indent=indent + 4))

    return lines


def _render_timeframe(tf: dict) -> list[str]:
    lines = []
    name = tf.get("timeframe", "").replace("_", " ").title()
    direction = tf.get("net_direction", "neutral")
    magnitude = tf.get("net_magnitude", 0)
    summary = tf.get("summary_text", "")

    lines.append(
        f"  {bold(name)}: {direction_badge(direction)} "
        f"{dim(f'({magnitude:.2f})')}"
    )
    if summary:
        lines.append(_wrap(summary, indent=4))
    return lines


def _render_population_impact(pop: dict) -> list[str]:
    lines = []
    population = pop.get("population", "unknown")
    direction = pop.get("net_direction", "neutral")
    magnitude = pop.get("net_magnitude", 0)
    summary = pop.get("summary_text", "")

    lines.append(
        f"  {bold(population)}  {direction_badge(direction)} "
        f"{dim(f'{magnitude:.2f}')}"
    )
    if summary:
        lines.append(_wrap(summary, indent=4))
    return lines


# ---------------------------------------------------------------------------
# Ethics evaluation display
# ---------------------------------------------------------------------------

def render_ethics_evaluation(ee: dict) -> str:
    lines = []
    lines.append(section("ETHICS EVALUATION"))
    verdict = ee.get("verdict", "unknown")
    lines.append(kv("Verdict", verdict_badge(verdict)))
    lines.append(kv("Confidence", dim(f"{ee.get('confidence', 0):.2f}")))

    wh = ee.get("weighted_harm")
    wb = ee.get("weighted_benefit")
    if wh is not None:
        lines.append(kv("Weighted harm",    harm_bar(wh)))
    if wb is not None:
        lines.append(kv("Weighted benefit", benefit_bar(wb)))

    constraints = ee.get("hard_constraints_triggered", [])
    if constraints:
        lines.append(f"\n  {bold(red('HARD CONSTRAINTS TRIGGERED:'))}")
        for c in constraints:
            lines.append(f"    {red('✗')} {c}")

    flags = ee.get("flags", [])
    if flags:
        lines.append(f"\n  {bold(yellow('FLAGS:'))}")
        for fl in flags:
            lines.append(f"    {yellow('⚑')} {fl}")

    justification = ee.get("justification", "")
    if justification:
        lines.append(f"\n  {bold('Justification')}")
        lines.append(_wrap(justification, indent=4))

    mitigations = ee.get("mitigation_notes", [])
    if mitigations:
        lines.append(f"\n  {bold('Required mitigations')}")
        for m in mitigations:
            lines.append(f"    {cyan('→')} {m}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feedback display
# ---------------------------------------------------------------------------

def render_feedback_summary(summary: dict) -> str:
    lines = []
    lines.append(section("FEEDBACK SUMMARY"))
    lines.append(kv("Map ID", dim(summary.get("map_id", "")[:24])))
    lines.append(kv("Total submissions", str(summary.get("total_submissions", 0))))

    sentiment = summary.get("net_sentiment", 0.0)
    sent_color = green if sentiment > 0.1 else red if sentiment < -0.1 else dim
    lines.append(kv("Net sentiment", sent_color(f"{sentiment:+.2f}")))

    pressure = summary.get("escalation_pressure", 0)
    if pressure > 0:
        pcolor = red if summary.get("requires_escalation") else yellow
        lines.append(kv("Escalation pressure", pcolor(f"{pressure:.2f}")))
        if summary.get("requires_escalation"):
            lines.append(f"  {red(bold('⚑ ESCALATION REQUIRED — awaiting human review'))}")

    # Role breakdown
    role_breakdown = summary.get("role_breakdown", {})
    if role_breakdown:
        lines.append(f"\n  {bold('Submissions by role')}")
        for role, count in sorted(role_breakdown.items(), key=lambda x: -x[1]):
            lines.append(f"    {dim(role.replace('_', ' ').ljust(20))} {count}")

    # Contested findings
    contested = summary.get("contested_findings", [])
    if contested:
        lines.append(f"\n  {bold(yellow(f'Contested findings ({len(contested)}):'))}")
        for fid in contested[:5]:
            lines.append(f"    {yellow('⇄')} {dim(fid[:36])}")

    # Corroborated findings
    corroborated = summary.get("corroborated_findings", [])
    if corroborated:
        lines.append(f"\n  {bold(green(f'Corroborated findings ({len(corroborated)}):'))}")
        for fid in corroborated[:5]:
            lines.append(f"    {green('✓')} {dim(fid[:36])}")

    # Adversarial challenges from feedback
    adversarial = summary.get("adversarial_challenges", [])
    if adversarial:
        lines.append(f"\n  {bold('Human adversarial challenges:')}")
        for entry in adversarial[:5]:
            content = entry.get("content", "")[:120]
            role = entry.get("submitter_role", "")
            lines.append(f"    {yellow('⚑')} [{dim(role)}] {_wrap(content, indent=6).lstrip()}")

    # Mitigation suggestions
    mitigations = summary.get("mitigation_suggestions", [])
    if mitigations:
        lines.append(f"\n  {bold('Mitigation suggestions:')}")
        for entry in mitigations[:5]:
            content = entry.get("content", "")[:120]
            lines.append(f"    {cyan('→')} {_wrap(content, indent=6).lstrip()}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Audit display
# ---------------------------------------------------------------------------

def render_audit_summary(summary: dict) -> str:
    lines = []
    lines.append(section("AUDIT LOG"))
    lines.append(kv("Log path",         summary.get("log_path", "unknown")))
    lines.append(kv("Total entries",    str(summary.get("total_entries", 0))))
    lines.append(kv("Unique sessions",  str(summary.get("unique_sessions", 0))))
    lines.append(kv("First entry",      dim(summary.get("first_entry_at", "N/A")[:19])))
    lines.append(kv("Last entry",       dim(summary.get("last_entry_at", "N/A")[:19])))
    lines.append(kv("Chain tip",        dim(summary.get("current_chain_tip", "N/A")[:16] + "...")))

    kinds = summary.get("entry_kinds", {})
    if kinds:
        lines.append(f"\n  {bold('Entry kinds')}")
        for kind, count in sorted(kinds.items(), key=lambda x: -x[1]):
            lines.append(f"    {dim(kind.replace('_', ' ').ljust(28))} {count}")

    return "\n".join(lines)


def render_audit_entry(entry: dict) -> str:
    lines = []
    kind = entry.get("kind", "unknown")
    seq = entry.get("sequence", "?")
    logged = entry.get("logged_at", "")[:19]
    session = entry.get("session_id", "")[:16]

    lines.append(f"  {dim(f'#{seq}')}  {bold(kind.replace('_', ' ').upper())}"
                 f"  {dim(logged)}")
    if session:
        lines.append(f"       {dim('session: ' + session)}")

    payload = entry.get("payload", {})
    if payload and isinstance(payload, dict):
        for k, v in list(payload.items())[:4]:
            if isinstance(v, str) and len(v) > 60:
                v = v[:57] + "..."
            lines.append(f"       {dim(k + ':')} {v}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Progress / status messages
# ---------------------------------------------------------------------------

def status(msg: str) -> None:
    """Print a dim status message to stderr."""
    print(f"  {dim('→')} {msg}", file=sys.stderr)


def success(msg: str) -> None:
    print(f"  {green('✓')} {msg}")


def error(msg: str) -> None:
    print(f"  {red('✗')} {msg}", file=sys.stderr)


def warn(msg: str) -> None:
    print(f"  {yellow('△')} {msg}", file=sys.stderr)


def info(msg: str) -> None:
    print(f"  {cyan('i')} {msg}")


# ---------------------------------------------------------------------------
# Output / paging
# ---------------------------------------------------------------------------

def print_output(text: str, pager: bool = False) -> None:
    """Print output, optionally through a pager."""
    if pager and sys.stdout.isatty():
        import subprocess
        try:
            proc = subprocess.Popen(
                ["less", "-R", "-F", "-X"],
                stdin=subprocess.PIPE,
            )
            proc.communicate(input=text.encode("utf-8", errors="replace"))
            return
        except (OSError, FileNotFoundError):
            pass  # Fall through to direct print if less unavailable
    print(text)


def render_finding_list(findings: list[dict], verbose: bool = False) -> str:
    """Render a standalone list of findings (for feedback targeting)."""
    lines = []
    for f in findings:
        fid = f.get("finding_id", "")
        summary = f.get("summary", "")
        direction = f.get("direction", "neutral")
        channel = next((t for t in f.get("tags", [])
                        if t in ("economic", "ecological", "social_demographic",
                                 "ethical_adversarial", "historical_precedent",
                                 "legal_institutional", "geopolitical",
                                 "uncertainty_modeling")), "")
        lines.append(
            f"  {dim(fid[:8])}  {direction_badge(direction)}  "
            f"{dim('[' + channel + ']')}  {summary[:80]}"
        )
    return "\n".join(lines)
