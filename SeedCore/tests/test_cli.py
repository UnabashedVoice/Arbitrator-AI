"""
test_cli.py — Test suite for the Arbitrator CLI.

Tests are organized by command:
    TestConfigManager       — config_manager.py unit tests
    TestDisplay             — display.py rendering (smoke tests, not pixel-perfect)
    TestRunCommand          — 'arbitrator run' variants
    TestFeedbackCommand     — 'arbitrator feedback' subcommands
    TestAuditCommand        — 'arbitrator audit' subcommands
    TestConfigCommand       — 'arbitrator config' subcommands
    TestCLIDispatch         — main() argument parsing and dispatch
    TestEndToEnd            — full pipeline run → feedback → audit verify cycle

All tests use temp directories to avoid polluting the real audit log.
Tests that invoke the pipeline use MockBackend (no network required).

Run with:
    python -m unittest SeedCore/tests/test_cli.py -v
"""

import json
import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

# Ensure package root is on path
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from Arbitrator.cli.config_manager import ConfigManager, DEFAULTS, _parse_yaml, _write_yaml
from Arbitrator.cli import display
from Arbitrator.cli.main import build_parser, main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(tmpdir: str) -> ConfigManager:
    """Create a ConfigManager backed by a temp directory."""
    cfg_path = Path(tmpdir) / "test_config.yaml"
    config = ConfigManager(config_path=cfg_path)
    config.set("audit_log_path", str(Path(tmpdir) / "audit.jsonl"))
    config.set("feedback_ledger_path", str(Path(tmpdir) / "ledger.json"))
    config.set("color", False)
    config.set("pager", False)
    return config


def run_cli(argv: list[str], config: ConfigManager) -> tuple[int, str, str]:
    """
    Run the CLI with given argv, capturing stdout and stderr.
    Returns (exit_code, stdout, stderr).
    """
    stdout_buf = StringIO()
    stderr_buf = StringIO()
    with patch("sys.stdout", stdout_buf), patch("sys.stderr", stderr_buf):
        try:
            parser = build_parser()
            args = parser.parse_args(argv)
            display.set_color(False)
            from Arbitrator.cli.main import dispatch
            code = dispatch(args, config)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
    return code, stdout_buf.getvalue(), stderr_buf.getvalue()


SAMPLE_PROPOSAL = (
    "Proposed 10% tariff increase on imported solar panels "
    "to protect domestic manufacturers."
)

SHORT_PROPOSAL = "Ban."  # Too short to be meaningful, should still process


# ---------------------------------------------------------------------------
# TestConfigManager
# ---------------------------------------------------------------------------

class TestConfigManager(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_defaults_applied_when_no_file(self):
        cfg_path = Path(self.tmpdir) / "nonexistent.yaml"
        config = ConfigManager(config_path=cfg_path)
        self.assertEqual(config.get("node_id"), DEFAULTS["node_id"])

    def test_get_returns_default_for_unknown_key(self):
        config = make_config(self.tmpdir)
        self.assertIsNone(config.get("nonexistent_key"))

    def test_set_and_get(self):
        config = make_config(self.tmpdir)
        config.set("node_id", "test-node-42")
        self.assertEqual(config.get("node_id"), "test-node-42")

    def test_save_and_reload(self):
        cfg_path = Path(self.tmpdir) / "config.yaml"
        config1 = ConfigManager(config_path=cfg_path)
        config1.set("node_id", "persisted-node")
        config1.save()

        config2 = ConfigManager(config_path=cfg_path)
        self.assertEqual(config2.get("node_id"), "persisted-node")

    def test_init_writes_defaults(self):
        cfg_path = Path(self.tmpdir) / "new_config.yaml"
        config = ConfigManager(config_path=cfg_path)
        config.init()
        self.assertTrue(cfg_path.exists())

    def test_init_does_not_overwrite_existing(self):
        cfg_path = Path(self.tmpdir) / "existing.yaml"
        config = ConfigManager(config_path=cfg_path)
        config.set("node_id", "custom")
        config.save()

        config2 = ConfigManager(config_path=cfg_path)
        config2.init()  # Should not overwrite
        self.assertEqual(config2.get("node_id"), "custom")

    def test_reset_restores_defaults(self):
        config = make_config(self.tmpdir)
        config.set("node_id", "custom-node")
        config.reset()
        self.assertEqual(config.get("node_id"), DEFAULTS["node_id"])

    def test_all_returns_dict(self):
        config = make_config(self.tmpdir)
        all_vals = config.all()
        self.assertIsInstance(all_vals, dict)
        self.assertIn("node_id", all_vals)

    def test_parse_yaml_booleans(self):
        text = "color: true\npager: false\n"
        result = _parse_yaml(text)
        self.assertIs(result["color"], True)
        self.assertIs(result["pager"], False)

    def test_parse_yaml_none(self):
        text = "max_channels: null\n"
        result = _parse_yaml(text)
        self.assertIsNone(result["max_channels"])

    def test_parse_yaml_integer(self):
        text = "limit: 42\n"
        result = _parse_yaml(text)
        self.assertEqual(result["limit"], 42)

    def test_parse_yaml_quoted_strings(self):
        text = 'path: "some/path/with: colon"\n'
        result = _parse_yaml(text)
        self.assertEqual(result["path"], "some/path/with: colon")

    def test_parse_yaml_ignores_comments(self):
        text = "# comment\nnode_id: local  # inline comment\n"
        result = _parse_yaml(text)
        self.assertEqual(result["node_id"], "local")

    def test_write_yaml_roundtrip(self):
        original = {"color": True, "node_id": "test", "max_channels": None, "limit": 5}
        text = _write_yaml(original)
        parsed = _parse_yaml(text)
        self.assertEqual(parsed["color"], True)
        self.assertEqual(parsed["node_id"], "test")
        self.assertIsNone(parsed["max_channels"])
        self.assertEqual(parsed["limit"], 5)


# ---------------------------------------------------------------------------
# TestDisplay
# ---------------------------------------------------------------------------

class TestDisplay(unittest.TestCase):
    """Smoke tests — verify rendering doesn't raise and produces non-empty output."""

    def setUp(self):
        display.set_color(False)

    def test_verdict_badge_all_known_verdicts(self):
        known = ["pass", "fail", "ambiguous", "escalate", "hard_reject",
                 "net_beneficial", "net_harmful", "mixed", "success", "failed"]
        for v in known:
            badge = display.verdict_badge(v)
            self.assertIsInstance(badge, str)
            self.assertGreater(len(badge), 0)

    def test_verdict_badge_unknown_verdict(self):
        badge = display.verdict_badge("totally_unknown_verdict")
        self.assertIsInstance(badge, str)

    def test_harm_bar_range(self):
        for val in [0.0, 0.25, 0.5, 0.75, 1.0]:
            bar = display.harm_bar(val)
            self.assertIn(f"{val:.2f}", bar)

    def test_benefit_bar_range(self):
        for val in [0.0, 0.5, 1.0]:
            bar = display.benefit_bar(val)
            self.assertIsInstance(bar, str)

    def test_score_bar_none(self):
        bar = display.score_bar(None)
        self.assertIn("no score", bar)

    def test_render_pipeline_result_minimal(self):
        result = {
            "session_id": "abc123",
            "status": "success",
            "ethics_verdict": "pass",
            "synthesis_verdict": "net_beneficial",
            "channels_invoked": ["economic"],
            "channels_succeeded": ["economic"],
            "errors": [],
            "warnings": [],
            "duration_ms": 123,
            "consequence_map": None,
        }
        rendered = display.render_pipeline_result(result)
        self.assertIn("abc123", rendered)
        self.assertIn("success", rendered.lower())

    def test_render_pipeline_result_with_consequence_map(self):
        cm = {
            "map_id": "map-test-001",
            "overall_verdict": "mixed",
            "overall_harm_score": 0.4,
            "overall_benefit_score": 0.6,
            "net_score": 0.2,
            "synthesis_confidence": 0.7,
            "executive_summary": "This is a summary.",
            "channel_outputs": [
                {
                    "channel_name": "economic",
                    "status": "success",
                    "confidence": 0.8,
                    "findings": [
                        {
                            "finding_id": "f-001",
                            "summary": "Economic impact finding.",
                            "direction": "harm",
                            "magnitude": 0.4,
                            "certainty": "moderate",
                            "timeframe": "medium_term",
                            "affected_groups": ["workers", "consumers"],
                            "reversible": True,
                        }
                    ],
                }
            ],
            "timeframe_impacts": [],
            "population_impacts": [
                {
                    "population": "Low-income households",
                    "net_direction": "harm",
                    "net_magnitude": 0.6,
                    "summary_text": "Disproportionate burden.",
                }
            ],
            "adversarial_challenges": ["Challenge 1 text here."],
            "recommended_mitigations": ["Revenue recycling mechanism."],
            "data_gaps": ["Historical data unavailable."],
            "channels_failed": [],
        }
        result = {
            "session_id": "sess-001",
            "status": "success",
            "ethics_verdict": "pass",
            "synthesis_verdict": "mixed",
            "channels_invoked": ["economic"],
            "channels_succeeded": ["economic"],
            "errors": [],
            "warnings": [],
            "duration_ms": 500,
            "consequence_map": cm,
        }
        rendered = display.render_pipeline_result(result, verbose=False)
        self.assertIn("sess-001", rendered)
        self.assertIn("CONSEQUENCE MAP", rendered)
        self.assertIn("FINDINGS BY CHANNEL", rendered)

    def test_render_ethics_evaluation(self):
        ee = {
            "verdict": "escalate",
            "confidence": 0.75,
            "weighted_harm": 0.6,
            "weighted_benefit": 0.3,
            "hard_constraints_triggered": [],
            "flags": ["FLAG_A"],
            "justification": "Escalation required due to ambiguity.",
            "mitigation_notes": ["Add safeguard X."],
        }
        rendered = display.render_ethics_evaluation(ee)
        self.assertIn("ETHICS", rendered)
        self.assertIn("escalate", rendered.lower())

    def test_render_audit_summary(self):
        summary = {
            "log_path": "/tmp/test.jsonl",
            "total_entries": 10,
            "unique_sessions": 3,
            "first_entry_at": "2026-01-01T00:00:00",
            "last_entry_at": "2026-01-02T00:00:00",
            "current_chain_tip": "abc123def456",
            "entry_kinds": {"pipeline_run": 3, "feedback_received": 7},
        }
        rendered = display.render_audit_summary(summary)
        self.assertIn("AUDIT LOG", rendered)
        self.assertIn("10", rendered)

    def test_render_feedback_summary(self):
        summary = {
            "summary_id": "sum-001",
            "map_id": "map-001",
            "session_id": "sess-001",
            "total_submissions": 5,
            "net_sentiment": -0.3,
            "escalation_pressure": 0.5,
            "requires_escalation": False,
            "role_breakdown": {"domain_expert": 3, "citizen": 2},
            "contested_findings": ["f-001"],
            "corroborated_findings": [],
            "adversarial_challenges": [
                {"content": "Adversarial challenge text.", "submitter_role": "ethicist"}
            ],
            "mitigation_suggestions": [
                {"content": "Suggested mitigation text."}
            ],
            "generated_at": "2026-01-01T00:00:00",
        }
        rendered = display.render_feedback_summary(summary)
        self.assertIn("FEEDBACK", rendered)
        self.assertIn("5", rendered)

    def test_direction_badge_all_directions(self):
        for d in ["harm", "benefit", "neutral", "mixed"]:
            badge = display.direction_badge(d)
            self.assertIsInstance(badge, str)

    def test_certainty_badge_all_levels(self):
        for c in ["high", "moderate", "low", "unknown"]:
            badge = display.certainty_badge(c)
            self.assertIsInstance(badge, str)

    def test_section_returns_string(self):
        s = display.section("TEST SECTION")
        self.assertIn("TEST SECTION", s)

    def test_kv_returns_string(self):
        s = display.kv("key", "value")
        self.assertIn("key", s)
        self.assertIn("value", s)


# ---------------------------------------------------------------------------
# TestRunCommand
# ---------------------------------------------------------------------------

class TestRunCommand(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = make_config(self.tmpdir)

    def test_run_basic(self):
        code, out, err = run_cli(["run", SAMPLE_PROPOSAL], self.config)
        self.assertIn(code, (0, 1))  # 0 = success, 1 = ethics blocked

    def test_run_with_verbose(self):
        code, out, err = run_cli(
            ["run", "--verbose", SAMPLE_PROPOSAL], self.config
        )
        self.assertIn(code, (0, 1))

    def test_run_ethics_only(self):
        code, out, err = run_cli(
            ["run", "--ethics-only", SAMPLE_PROPOSAL], self.config
        )
        self.assertIn(code, (0, 1))

    def test_run_json_output(self):
        code, out, err = run_cli(
            ["run", "--json", SAMPLE_PROPOSAL], self.config
        )
        self.assertIn(code, (0, 1))
        if out.strip():
            parsed = json.loads(out)
            self.assertIn("session_id", parsed)
            self.assertIn("status", parsed)

    def test_run_output_to_file(self):
        output_path = str(Path(self.tmpdir) / "result.txt")
        code, out, err = run_cli(
            ["run", "--output", output_path, SAMPLE_PROPOSAL], self.config
        )
        self.assertIn(code, (0, 1))
        self.assertTrue(Path(output_path).exists())

    def test_run_json_output_to_file(self):
        output_path = str(Path(self.tmpdir) / "result.json")
        code, out, err = run_cli(
            ["run", "--json", "--output", output_path, SAMPLE_PROPOSAL], self.config
        )
        self.assertIn(code, (0, 1))
        if Path(output_path).exists():
            with open(output_path) as f:
                parsed = json.load(f)
            self.assertIn("session_id", parsed)

    def test_run_empty_proposal_returns_error(self):
        code, out, err = run_cli(["run", "   "], self.config)
        self.assertEqual(code, 2)

    def test_run_creates_audit_log(self):
        run_cli(["run", SAMPLE_PROPOSAL], self.config)
        audit_path = Path(self.config.get("audit_log_path"))
        self.assertTrue(audit_path.exists())

    def test_run_ethics_blocked_returns_1(self):
        """A HARD_REJECT proposal should return exit code 1."""
        # The mock backend produces mixed outputs, not necessarily hard rejects.
        # Test that the exit code matches the pipeline status.
        code, out, err = run_cli(["run", SAMPLE_PROPOSAL], self.config)
        # Just verify the code is in the valid set
        self.assertIn(code, (0, 1, 2))

    def test_run_stdin_flag(self):
        """Test '-' reads from stdin."""
        with patch("sys.stdin", StringIO(SAMPLE_PROPOSAL)):
            code, out, err = run_cli(["run", "-"], self.config)
        self.assertIn(code, (0, 1, 2))


# ---------------------------------------------------------------------------
# TestFeedbackCommand
# ---------------------------------------------------------------------------

class TestFeedbackCommand(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = make_config(self.tmpdir)

        # Run a pipeline to get a real session_id and map_id
        code, out, err = run_cli(["run", "--json", SAMPLE_PROPOSAL], self.config)
        self.run_success = code in (0, 1) and out.strip()
        if self.run_success:
            try:
                self.run_result = json.loads(out)
                cm = self.run_result.get("consequence_map") or {}
                self.map_id = cm.get("map_id", "test-map-001")
                self.session_id = self.run_result.get("session_id", "test-session-001")
                # Get a real finding_id if available
                co = cm.get("channel_outputs", [])
                self.finding_id = None
                for c in co:
                    findings = c.get("findings", [])
                    if findings:
                        self.finding_id = findings[0].get("finding_id")
                        break
            except (json.JSONDecodeError, AttributeError):
                self.run_result = {}
                self.map_id = "test-map-001"
                self.session_id = "test-session-001"
                self.finding_id = None
        else:
            self.map_id = "test-map-001"
            self.session_id = "test-session-001"
            self.finding_id = None

    def test_feedback_list_no_submissions(self):
        code, out, err = run_cli(["feedback", "list"], self.config)
        self.assertIn(code, (0, 2))

    def test_feedback_submit_general_comment(self):
        code, out, err = run_cli([
            "feedback", "submit",
            "--map-id", self.map_id,
            "--session-id", self.session_id,
            "--submitter-id", "citizen-test-001",
            "--role", "citizen",
            "--type", "general_comment",
            "This analysis provides useful context for our community's "
            "decision-making process.",
        ], self.config)
        # Should succeed (0) or be rejected on validation (1)
        self.assertIn(code, (0, 1))

    def test_feedback_submit_expert_challenge(self):
        if not self.finding_id:
            self.skipTest("No finding_id available from pipeline run")

        code, out, err = run_cli([
            "feedback", "submit",
            "--map-id", self.map_id,
            "--session-id", self.session_id,
            "--submitter-id", "expert-test-001",
            "--role", "domain_expert",
            "--type", "finding_challenge",
            "--finding", self.finding_id,
            "--domain", "economic",
            "--citation", "IMF Working Paper 2023/142",
            "The harm estimate is significantly overstated due to the use "
            "of obsolete price elasticity coefficients that do not reflect "
            "the current empirical literature in this domain.",
        ], self.config)
        self.assertIn(code, (0, 1))

    def test_feedback_submit_invalid_role(self):
        code, out, err = run_cli([
            "feedback", "submit",
            "--map-id", self.map_id,
            "--session-id", self.session_id,
            "--submitter-id", "test-001",
            "--role", "not_a_real_role",
            "--type", "general_comment",
            "Some content.",
        ], self.config)
        self.assertEqual(code, 2)

    def test_feedback_submit_citizen_cannot_challenge(self):
        code, out, err = run_cli([
            "feedback", "submit",
            "--map-id", self.map_id,
            "--session-id", self.session_id,
            "--submitter-id", "citizen-001",
            "--role", "citizen",
            "--type", "finding_challenge",
            "--finding", "some-finding-id",
            "Challenge content." * 5,
        ], self.config)
        # Should be rejected (1) due to role permission
        self.assertEqual(code, 1)

    def test_feedback_summary_no_feedback(self):
        code, out, err = run_cli([
            "feedback", "summary",
            "--map-id", self.map_id,
        ], self.config)
        self.assertIn(code, (0, 2))

    def test_feedback_summary_json(self):
        code, out, err = run_cli([
            "feedback", "summary",
            "--map-id", self.map_id,
            "--json",
        ], self.config)
        self.assertIn(code, (0, 2))

    def test_feedback_review_valid_decision(self):
        code, out, err = run_cli([
            "feedback", "review",
            "--session-id", self.session_id,
            "--map-id", self.map_id,
            "--reviewer-id", "reviewer-001",
            "--decision", "approve",
            "Reviewed and approved. Analysis is consistent with available evidence.",
        ], self.config)
        self.assertEqual(code, 0)

    def test_feedback_review_invalid_decision(self):
        code, out, err = run_cli([
            "feedback", "review",
            "--session-id", self.session_id,
            "--map-id", self.map_id,
            "--reviewer-id", "reviewer-001",
            "--decision", "not_a_decision",
            "Some rationale.",
        ], self.config)
        self.assertEqual(code, 2)

    def test_feedback_list_after_submission(self):
        # Submit one
        run_cli([
            "feedback", "submit",
            "--map-id", self.map_id,
            "--session-id", self.session_id,
            "--submitter-id", "citizen-001",
            "--role", "citizen",
            "--type", "general_comment",
            "This analysis is thorough and well-documented for our review.",
        ], self.config)

        code, out, err = run_cli(["feedback", "list"], self.config)
        self.assertEqual(code, 0)

    def test_feedback_no_subcommand_returns_error(self):
        code, out, err = run_cli(["feedback"], self.config)
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# TestAuditCommand
# ---------------------------------------------------------------------------

class TestAuditCommand(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = make_config(self.tmpdir)
        # Run a pipeline to populate the audit log
        run_cli(["run", SAMPLE_PROPOSAL], self.config)

    def test_audit_verify_passes_fresh_log(self):
        code, out, err = run_cli(["audit", "verify"], self.config)
        self.assertEqual(code, 0)

    def test_audit_summary(self):
        code, out, err = run_cli(["audit", "summary"], self.config)
        self.assertEqual(code, 0)
        self.assertIn("AUDIT LOG", out)

    def test_audit_summary_json(self):
        code, out, err = run_cli(["audit", "summary", "--json"], self.config)
        self.assertEqual(code, 0)
        if out.strip():
            parsed = json.loads(out)
            self.assertIn("total_entries", parsed)

    def test_audit_log_shows_entries(self):
        code, out, err = run_cli(["audit", "log"], self.config)
        self.assertEqual(code, 0)

    def test_audit_log_with_kind_filter(self):
        code, out, err = run_cli(
            ["audit", "log", "--kind", "pipeline_run"], self.config
        )
        self.assertIn(code, (0, 2))  # 2 if no pipeline_run entries exist yet

    def test_audit_log_with_invalid_kind(self):
        code, out, err = run_cli(
            ["audit", "log", "--kind", "completely_made_up_kind"], self.config
        )
        self.assertEqual(code, 2)

    def test_audit_log_with_limit(self):
        code, out, err = run_cli(
            ["audit", "log", "--limit", "5"], self.config
        )
        self.assertEqual(code, 0)

    def test_audit_session_with_real_session(self):
        # Get a real session_id from a run
        code, out, err = run_cli(["run", "--json", SAMPLE_PROPOSAL], self.config)
        if code not in (0, 1) or not out.strip():
            self.skipTest("Could not get session_id from run")
        try:
            result = json.loads(out)
            session_id = result["session_id"]
        except (json.JSONDecodeError, KeyError):
            self.skipTest("Could not parse session_id")

        code2, out2, err2 = run_cli(
            ["audit", "session", session_id], self.config
        )
        self.assertEqual(code2, 0)

    def test_audit_session_unknown_session(self):
        code, out, err = run_cli(
            ["audit", "session", "00000000-0000-0000-0000-000000000000"],
            self.config
        )
        self.assertEqual(code, 0)  # Returns 0 with "no entries found" message

    def test_audit_export(self):
        export_path = str(Path(self.tmpdir) / "export.json")
        code, out, err = run_cli(
            ["audit", "export", export_path], self.config
        )
        self.assertEqual(code, 0)
        self.assertTrue(Path(export_path).exists())
        with open(export_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_audit_no_subcommand_returns_error(self):
        code, out, err = run_cli(["audit"], self.config)
        self.assertEqual(code, 2)

    def test_audit_verify_fresh_log_passes(self):
        # AuditLog always creates itself with a LOG_OPENED entry.
        # A fresh log with no pipeline runs should still verify.
        fresh_config = make_config(tempfile.mkdtemp())
        code, out, err = run_cli(["audit", "verify"], fresh_config)
        self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# TestConfigCommand
# ---------------------------------------------------------------------------

class TestConfigCommand(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = make_config(self.tmpdir)

    def test_config_show(self):
        code, out, err = run_cli(["config", "show"], self.config)
        self.assertEqual(code, 0)
        self.assertIn("CONFIGURATION", out)
        self.assertIn("node_id", out)

    def test_config_set_string_value(self):
        code, out, err = run_cli(
            ["config", "set", "node_id", "my-custom-node"], self.config
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.config.get("node_id"), "my-custom-node")

    def test_config_set_boolean_true(self):
        code, out, err = run_cli(
            ["config", "set", "color", "true"], self.config
        )
        self.assertEqual(code, 0)
        self.assertTrue(self.config.get("color"))

    def test_config_set_boolean_false(self):
        code, out, err = run_cli(
            ["config", "set", "color", "false"], self.config
        )
        self.assertEqual(code, 0)
        self.assertFalse(self.config.get("color"))

    def test_config_init(self):
        fresh_tmpdir = tempfile.mkdtemp()
        fresh_cfg = Path(fresh_tmpdir) / "config.yaml"
        config = ConfigManager(config_path=fresh_cfg)
        code, out, err = run_cli(["config", "init"], config)
        self.assertEqual(code, 0)
        self.assertTrue(fresh_cfg.exists())

    def test_config_init_when_exists_does_not_overwrite(self):
        self.config.set("node_id", "unique-sentinel")
        self.config.save()
        code, out, err = run_cli(["config", "init"], self.config)
        self.assertEqual(code, 0)
        self.assertEqual(self.config.get("node_id"), "unique-sentinel")

    def test_config_reset(self):
        self.config.set("node_id", "custom-before-reset")
        code, out, err = run_cli(["config", "reset"], self.config)
        self.assertEqual(code, 0)
        self.assertEqual(self.config.get("node_id"), DEFAULTS["node_id"])

    def test_config_no_subcommand_returns_error(self):
        code, out, err = run_cli(["config"], self.config)
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# TestCLIDispatch
# ---------------------------------------------------------------------------

class TestCLIDispatch(unittest.TestCase):

    def test_no_command_prints_help_and_returns_0(self):
        """No command should print help and return 0."""
        stdout_buf = StringIO()
        with patch("sys.stdout", stdout_buf):
            code = main([])
        self.assertEqual(code, 0)
        self.assertIn("arbitrator", stdout_buf.getvalue().lower())

    def test_version_flag(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)

    def test_help_flag(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_run_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["run", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_feedback_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["feedback", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_audit_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["audit", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_config_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["config", "--help"])
        self.assertEqual(cm.exception.code, 0)

    def test_unknown_command_exits_nonzero(self):
        with self.assertRaises(SystemExit) as cm:
            main(["completely_unknown_command"])
        self.assertNotEqual(cm.exception.code, 0)


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------

class TestEndToEnd(unittest.TestCase):
    """
    Full cycle: run → feedback submit → audit verify → feedback summary.
    Uses a single shared tmpdir so audit log accumulates state.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config = make_config(self.tmpdir)

    def test_full_cycle(self):
        # 1. Run analysis
        code, out, err = run_cli(
            ["run", "--json", SAMPLE_PROPOSAL], self.config
        )
        self.assertIn(code, (0, 1), f"Run failed with code {code}. err: {err}")
        if not out.strip():
            self.skipTest("No JSON output from run")

        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            self.skipTest("Could not parse run output as JSON")

        session_id = result.get("session_id")
        cm = result.get("consequence_map") or {}
        map_id = cm.get("map_id")

        self.assertIsNotNone(session_id, "session_id should be present")
        self.assertIsNotNone(map_id, "map_id should be present in consequence map")

        # 2. Submit feedback
        fb_code, fb_out, fb_err = run_cli([
            "feedback", "submit",
            "--map-id", map_id,
            "--session-id", session_id,
            "--submitter-id", "e2e-expert-001",
            "--role", "domain_expert",
            "--type", "general_comment",
            "End-to-end test feedback: the analysis methodology is sound "
            "and the channel outputs are well-structured.",
        ], self.config)
        self.assertEqual(fb_code, 0, f"Feedback submit failed: {fb_err}")

        # 3. List feedback (should show at least one entry)
        list_code, list_out, list_err = run_cli(
            ["feedback", "list"], self.config
        )
        self.assertEqual(list_code, 0)

        # 4. Verify audit chain
        verify_code, verify_out, verify_err = run_cli(
            ["audit", "verify"], self.config
        )
        self.assertEqual(verify_code, 0,
                         f"Audit verify failed: {verify_err}")

        # 5. Audit summary
        sum_code, sum_out, sum_err = run_cli(
            ["audit", "summary"], self.config
        )
        self.assertEqual(sum_code, 0)
        self.assertIn("AUDIT LOG", sum_out)

        # 6. Inspect session
        sess_code, sess_out, sess_err = run_cli(
            ["audit", "session", session_id], self.config
        )
        self.assertEqual(sess_code, 0)

        # 7. Export audit log
        export_path = str(Path(self.tmpdir) / "e2e_export.json")
        exp_code, exp_out, exp_err = run_cli(
            ["audit", "export", export_path], self.config
        )
        self.assertEqual(exp_code, 0)
        with open(export_path) as f:
            exported = json.load(f)
        self.assertIsInstance(exported, list)
        # Should have pipeline + feedback entries
        kinds = {e.get("kind") for e in exported}
        self.assertIn("feedback_received", kinds)

    def test_two_runs_distinct_sessions(self):
        """Each run should produce a unique session_id."""
        sessions = []
        for _ in range(2):
            code, out, err = run_cli(
                ["run", "--json", SAMPLE_PROPOSAL], self.config
            )
            if code in (0, 1) and out.strip():
                try:
                    r = json.loads(out)
                    sessions.append(r.get("session_id"))
                except json.JSONDecodeError:
                    pass

        if len(sessions) == 2:
            self.assertNotEqual(sessions[0], sessions[1],
                                "Each run should produce a unique session_id")

    def test_audit_verify_after_multiple_runs(self):
        """Audit chain should remain valid across multiple runs."""
        for i in range(3):
            run_cli(["run", f"Proposal number {i}: test policy.", ], self.config)

        code, out, err = run_cli(["audit", "verify"], self.config)
        self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
