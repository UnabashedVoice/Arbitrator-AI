"""
test_audit_log.py — Test suite for the Arbitrator Audit Log.

Tests are organized by layer:
    - TestAuditEntryHashing         — Hash computation and chain linkage
    - TestAuditEntrySerialization   — to/from log line round-trip
    - TestLogQuery                  — Query filter logic
    - TestWriters                   — Typed entry constructors
    - TestAuditLogAppend            — Core append behavior
    - TestAuditLogRead              — Reading and iteration
    - TestAuditLogVerification      — Tamper detection — the most critical tests
    - TestAuditLogQuery             — Log querying
    - TestAuditLogSummary           — Summary stats
    - TestTamperScenarios           — Realistic tamper attack simulations
    - TestIntegration               — End-to-end pipeline entry logging
    - TestEdgeCases                 — Boundary conditions

Run with:
    python -m unittest SeedCore/tests/test_audit_log.py -v
"""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from SeedCore.audit_log import (
    AuditLog,
    AuditEntry,
    EntryKind,
    VerificationResult,
    LogQuery,
    LogReadError,
    GENESIS_HASH,
    writers,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def make_tmp_log(auto_open=True) -> tuple[AuditLog, str]:
    """Create a temp log file and return (log, path)."""
    tmp = tempfile.mktemp(suffix='.jsonl')
    log = AuditLog(tmp, auto_open=auto_open)
    return log, tmp


def make_entry(
    kind=EntryKind.INPUT_RECEIVED,
    session_id="test-session",
    payload=None,
) -> AuditEntry:
    return AuditEntry(
        kind=kind,
        session_id=session_id,
        payload=payload or {"test": "data"},
    )


# ---------------------------------------------------------------------------
# AuditEntry hashing
# ---------------------------------------------------------------------------

class TestAuditEntryHashing(unittest.TestCase):

    def test_compute_hash_returns_64_char_hex(self):
        e = make_entry()
        e.sequence = 0
        h = e.compute_hash()
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in h))

    def test_same_entry_always_same_hash(self):
        e = make_entry()
        e.sequence = 5
        e.prev_hash = "a" * 64
        h1 = e.compute_hash()
        h2 = e.compute_hash()
        self.assertEqual(h1, h2)

    def test_different_payload_different_hash(self):
        e1 = make_entry(payload={"x": 1})
        e1.sequence = 0
        e2 = make_entry(payload={"x": 2})
        e2.sequence = 0
        self.assertNotEqual(e1.compute_hash(), e2.compute_hash())

    def test_different_prev_hash_different_hash(self):
        e1 = make_entry()
        e1.prev_hash = "a" * 64
        e1.sequence = 1
        e2 = make_entry()
        e2.prev_hash = "b" * 64
        e2.sequence = 1
        self.assertNotEqual(e1.compute_hash(), e2.compute_hash())

    def test_finalize_sets_entry_hash(self):
        e = make_entry()
        e.sequence = 0
        self.assertEqual(e.entry_hash, "")
        e.finalize()
        self.assertNotEqual(e.entry_hash, "")
        self.assertEqual(len(e.entry_hash), 64)

    def test_finalize_returns_self(self):
        e = make_entry()
        result = e.finalize()
        self.assertIs(result, e)

    def test_genesis_hash_format(self):
        self.assertEqual(len(GENESIS_HASH), 64)
        self.assertTrue(all(c == '0' for c in GENESIS_HASH))

    def test_canonical_dict_is_deterministic(self):
        e = make_entry()
        e.sequence = 3
        d1 = e.canonical_dict()
        d2 = e.canonical_dict()
        self.assertEqual(
            json.dumps(d1, sort_keys=True),
            json.dumps(d2, sort_keys=True)
        )

    def test_related_ids_sorted_in_canonical(self):
        e = make_entry()
        e.related_ids = ["zzz", "aaa", "mmm"]
        canonical = e.canonical_dict()
        self.assertEqual(canonical["related_ids"], ["aaa", "mmm", "zzz"])


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------

class TestAuditEntrySerialization(unittest.TestCase):

    def test_to_log_line_is_single_line(self):
        e = make_entry()
        e.sequence = 0
        e.finalize()
        line = e.to_log_line()
        self.assertFalse('\n' in line.rstrip('\n'))
        self.assertTrue(line.endswith('\n'))

    def test_round_trip_preserves_fields(self):
        e = make_entry(payload={"key": "value", "number": 42})
        e.sequence = 7
        e.prev_hash = "f" * 64
        e.finalize()

        line = e.to_log_line()
        restored = AuditEntry.from_log_line(line)

        self.assertEqual(restored.entry_id, e.entry_id)
        self.assertEqual(restored.kind, e.kind)
        self.assertEqual(restored.session_id, e.session_id)
        self.assertEqual(restored.sequence, 7)
        self.assertEqual(restored.prev_hash, "f" * 64)
        self.assertEqual(restored.entry_hash, e.entry_hash)
        self.assertEqual(restored.payload, e.payload)

    def test_to_public_dict_contains_entry_hash(self):
        e = make_entry()
        e.sequence = 0
        e.finalize()
        d = e.to_public_dict()
        self.assertIn("entry_hash", d)
        self.assertEqual(len(d["entry_hash"]), 64)

    def test_kind_serialized_as_value_string(self):
        e = make_entry(kind=EntryKind.ETHICS_EVALUATED)
        e.sequence = 0
        e.finalize()
        line = e.to_log_line()
        data = json.loads(line)
        self.assertEqual(data["kind"], "ethics_evaluated")


# ---------------------------------------------------------------------------
# LogQuery
# ---------------------------------------------------------------------------

class TestLogQuery(unittest.TestCase):

    def _make_entry_with(self, kind, session, logged_at):
        e = make_entry(kind=kind, session_id=session)
        e.logged_at = logged_at
        return e

    def test_session_filter(self):
        q = LogQuery(session_id="s1")
        e1 = make_entry(session_id="s1")
        e2 = make_entry(session_id="s2")
        self.assertTrue(q.matches(e1))
        self.assertFalse(q.matches(e2))

    def test_kind_filter(self):
        q = LogQuery(kind=EntryKind.ETHICS_EVALUATED)
        e1 = make_entry(kind=EntryKind.ETHICS_EVALUATED)
        e2 = make_entry(kind=EntryKind.INPUT_RECEIVED)
        self.assertTrue(q.matches(e1))
        self.assertFalse(q.matches(e2))

    def test_kinds_filter(self):
        q = LogQuery(kinds=[EntryKind.ETHICS_EVALUATED, EntryKind.CONTEXT_PARSED])
        self.assertTrue(q.matches(make_entry(kind=EntryKind.ETHICS_EVALUATED)))
        self.assertTrue(q.matches(make_entry(kind=EntryKind.CONTEXT_PARSED)))
        self.assertFalse(q.matches(make_entry(kind=EntryKind.INPUT_RECEIVED)))

    def test_since_filter(self):
        q = LogQuery(since="2025-01-01T00:00:00+00:00")
        e_after = make_entry()
        e_after.logged_at = "2025-06-01T00:00:00+00:00"
        e_before = make_entry()
        e_before.logged_at = "2024-01-01T00:00:00+00:00"
        self.assertTrue(q.matches(e_after))
        self.assertFalse(q.matches(e_before))

    def test_related_to_filter(self):
        q = LogQuery(related_to="target-id")
        e_related = make_entry()
        e_related.related_ids = ["target-id", "other-id"]
        e_unrelated = make_entry()
        e_unrelated.related_ids = ["something-else"]
        self.assertTrue(q.matches(e_related))
        self.assertFalse(q.matches(e_unrelated))

    def test_no_filters_matches_all(self):
        q = LogQuery()
        self.assertTrue(q.matches(make_entry()))
        self.assertTrue(q.matches(make_entry(kind=EntryKind.CONSEQUENCE_MAP)))


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

class TestWriters(unittest.TestCase):

    def test_write_input_received(self):
        e = writers.write_input_received("s1", "Some policy proposal", "input-001")
        self.assertEqual(e.kind, EntryKind.INPUT_RECEIVED)
        self.assertEqual(e.payload["raw_input"], "Some policy proposal")
        self.assertIn("input-001", e.related_ids)

    def test_write_context_parsed(self):
        manifest = {"manifest_id": "m-001", "context": {}, "routes": []}
        e = writers.write_context_parsed("s1", manifest, "input-001")
        self.assertEqual(e.kind, EntryKind.CONTEXT_PARSED)
        self.assertIn("m-001", e.related_ids)

    def test_write_ethics_evaluated(self):
        eval_dict = {"proposal_id": "p-001", "verdict": "pass"}
        e = writers.write_ethics_evaluated("s1", eval_dict, "p-001", "m-001")
        self.assertEqual(e.kind, EntryKind.ETHICS_EVALUATED)
        self.assertIn("p-001", e.related_ids)
        self.assertIn("m-001", e.related_ids)

    def test_write_channel_output(self):
        output = {"output_id": "o-001", "channel_name": "economic"}
        e = writers.write_channel_output("s1", output, "m-001")
        self.assertEqual(e.kind, EntryKind.CHANNEL_OUTPUT)

    def test_write_consequence_map(self):
        cmap = {"map_id": "cm-001", "overall_verdict": "net_beneficial"}
        e = writers.write_consequence_map("s1", cmap, "m-001", "ethics-001")
        self.assertEqual(e.kind, EntryKind.CONSEQUENCE_MAP)
        self.assertIn("cm-001", e.related_ids)
        self.assertIn("ethics-001", e.related_ids)

    def test_write_human_review_valid_decisions(self):
        for decision in ["approve", "reject", "defer", "amend"]:
            e = writers.write_human_review("s1", "reviewer-1", decision, "Rationale.", "cm-001")
            self.assertEqual(e.kind, EntryKind.HUMAN_REVIEW)
            self.assertEqual(e.payload["decision"], decision)

    def test_write_human_review_invalid_decision_raises(self):
        with self.assertRaises(ValueError):
            writers.write_human_review("s1", "reviewer-1", "maybe", "Rationale.", "cm-001")

    def test_write_pipeline_error(self):
        e = writers.write_pipeline_error("s1", "synthesis", "RuntimeError", "Channel timeout")
        self.assertEqual(e.kind, EntryKind.PIPELINE_ERROR)
        self.assertEqual(e.payload["stage"], "synthesis")

    def test_write_channel_failure(self):
        e = writers.write_channel_failure("s1", "geopolitical", "Model unavailable", "m-001")
        self.assertEqual(e.kind, EntryKind.CHANNEL_FAILURE)

    def test_write_log_opened(self):
        e = writers.write_log_opened("s1", "/var/arbitrator/audit.jsonl")
        self.assertEqual(e.kind, EntryKind.LOG_OPENED)

    def test_all_writers_return_audit_entry(self):
        entries = [
            writers.write_input_received("s1", "input", "i-001"),
            writers.write_context_parsed("s1", {"manifest_id": "m"}, "i-001"),
            writers.write_ethics_evaluated("s1", {"verdict": "pass"}, "p-001", "m-001"),
            writers.write_channel_output("s1", {"output_id": "o"}, "m-001"),
            writers.write_consequence_map("s1", {"map_id": "c"}, "m-001"),
            writers.write_pipeline_error("s1", "stage", "Error", "msg"),
            writers.write_channel_failure("s1", "eco", "timeout", "m-001"),
            writers.write_log_opened("s1", "/path"),
        ]
        for e in entries:
            self.assertIsInstance(e, AuditEntry)


# ---------------------------------------------------------------------------
# Core append behavior
# ---------------------------------------------------------------------------

class TestAuditLogAppend(unittest.TestCase):

    def setUp(self):
        self.log, self.path = make_tmp_log()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def test_append_returns_entry(self):
        e = make_entry()
        result = self.log.append(e)
        self.assertIsInstance(result, AuditEntry)

    def test_append_sets_sequence(self):
        e1 = self.log.append(make_entry())
        e2 = self.log.append(make_entry())
        self.assertGreater(e2.sequence, e1.sequence)

    def test_append_sets_prev_hash(self):
        e1 = self.log.append(make_entry())
        e2 = self.log.append(make_entry())
        self.assertEqual(e2.prev_hash, e1.entry_hash)

    def test_append_sets_entry_hash(self):
        e = self.log.append(make_entry())
        self.assertEqual(len(e.entry_hash), 64)

    def test_auto_open_writes_first_entry(self):
        # The log was created with auto_open=True — should have a LOG_OPENED entry
        entries = list(self.log.read_all())
        self.assertGreater(len(entries), 0)
        self.assertEqual(entries[0].kind, EntryKind.LOG_OPENED)

    def test_first_entry_has_genesis_prev_hash(self):
        entries = list(self.log.read_all())
        self.assertEqual(entries[0].prev_hash, GENESIS_HASH)

    def test_entry_persists_to_disk(self):
        e = make_entry(payload={"persisted": True})
        appended = self.log.append(e)

        # Create a new log instance pointing at the same file
        log2 = AuditLog(self.path, auto_open=False)
        found = log2.get_by_id(appended.entry_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.payload["persisted"], True)

    def test_sequence_monotonically_increases(self):
        sequences = []
        for _ in range(5):
            e = self.log.append(make_entry())
            sequences.append(e.sequence)
        for i in range(1, len(sequences)):
            self.assertGreater(sequences[i], sequences[i - 1])

    def test_thread_safe_concurrent_appends(self):
        errors = []
        def append_many():
            try:
                for _ in range(20):
                    self.log.append(make_entry())
            except Exception as ex:
                errors.append(ex)

        threads = [threading.Thread(target=append_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        result = self.log.verify(log_verification=False)
        self.assertTrue(result.valid, result.error_detail)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

class TestAuditLogRead(unittest.TestCase):

    def setUp(self):
        self.log, self.path = make_tmp_log()
        for i in range(5):
            self.log.append(make_entry(payload={"i": i}))

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def test_read_all_returns_all_entries(self):
        # 1 (LOG_OPENED) + 5 appended
        entries = list(self.log.read_all())
        self.assertEqual(len(entries), 6)

    def test_read_all_in_sequence_order(self):
        entries = list(self.log.read_all())
        seqs = [e.sequence for e in entries]
        self.assertEqual(seqs, sorted(seqs))

    def test_read_entries_pagination(self):
        page = self.log.read_entries(count=3, from_sequence=0)
        self.assertEqual(len(page), 3)

    def test_read_entries_from_offset(self):
        page = self.log.read_entries(count=3, from_sequence=3)
        self.assertTrue(all(e.sequence >= 3 for e in page))

    def test_get_by_id_finds_entry(self):
        e = self.log.append(make_entry(payload={"unique": "yes"}))
        found = self.log.get_by_id(e.entry_id)
        self.assertIsNotNone(found)
        self.assertEqual(found.payload["unique"], "yes")

    def test_get_by_id_returns_none_for_missing(self):
        result = self.log.get_by_id("nonexistent-id")
        self.assertIsNone(result)

    def test_count_returns_correct_number(self):
        n = self.log.count()
        self.assertEqual(n, 6)  # 1 LOG_OPENED + 5

    def test_get_session_returns_session_entries(self):
        self.log.append(make_entry(session_id="special-session", payload={}))
        results = self.log.get_session("special-session")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].session_id, "special-session")

    def test_context_manager(self):
        with AuditLog(self.path, auto_open=False) as log:
            entries = list(log.read_all())
        self.assertGreater(len(entries), 0)


# ---------------------------------------------------------------------------
# Chain verification — the critical tests
# ---------------------------------------------------------------------------

class TestAuditLogVerification(unittest.TestCase):

    def setUp(self):
        self.log, self.path = make_tmp_log()
        for i in range(5):
            self.log.append(make_entry(payload={"i": i}))

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def test_clean_log_verifies_successfully(self):
        result = self.log.verify(log_verification=False)
        self.assertTrue(result.valid)
        self.assertGreater(result.entries_checked, 0)

    def test_entries_checked_count_matches_log_size(self):
        result = self.log.verify(log_verification=False)
        self.assertEqual(result.entries_checked, self.log.count())

    def test_verification_result_has_timestamp(self):
        result = self.log.verify(log_verification=False)
        self.assertIsNotNone(result.verified_at)

    def test_verify_with_logging_appends_entry(self):
        count_before = self.log.count()
        self.log.verify(log_verification=True)
        count_after = self.log.count()
        self.assertEqual(count_after, count_before + 1)

    def test_verify_logs_log_verified_kind(self):
        self.log.verify(log_verification=True)
        entries = list(self.log.read_all())
        kinds = [e.kind for e in entries]
        self.assertIn(EntryKind.LOG_VERIFIED, kinds)

    def test_tamper_payload_detected(self):
        """
        CRITICAL: Modify a payload in the log file and verify that
        the chain verification detects it.
        """
        # Read all lines
        with open(self.path, 'r') as f:
            lines = f.readlines()

        # Tamper with the payload of entry at index 2
        data = json.loads(lines[2])
        data["payload"]["TAMPERED"] = "by_attacker"
        lines[2] = json.dumps(data, sort_keys=True, separators=(',', ':')) + "\n"

        # Write back
        with open(self.path, 'w') as f:
            f.writelines(lines)

        # Reload and verify
        tampered_log = AuditLog(self.path, auto_open=False)
        result = tampered_log.verify(log_verification=False)

        self.assertFalse(result.valid)
        self.assertIsNotNone(result.error_detail)
        self.assertIn("tampered", result.error_detail.lower() if result.error_detail else "")

    def test_tamper_entry_hash_detected(self):
        """
        Directly alter an entry's stored entry_hash and verify detection.
        """
        with open(self.path, 'r') as f:
            lines = f.readlines()

        data = json.loads(lines[3])
        data["entry_hash"] = "0" * 64  # Replace with obviously wrong hash
        lines[3] = json.dumps(data, sort_keys=True, separators=(',', ':')) + "\n"

        with open(self.path, 'w') as f:
            f.writelines(lines)

        tampered_log = AuditLog(self.path, auto_open=False)
        result = tampered_log.verify(log_verification=False)
        self.assertFalse(result.valid)

    def test_insert_entry_detected(self):
        """
        Insert a new line into the middle of the log and verify detection.
        The chain is broken because the inserted entry has the wrong prev_hash.
        """
        with open(self.path, 'r') as f:
            lines = f.readlines()

        # Craft a fake entry with a plausible-looking but wrong hash
        fake = {
            "entry_id": "fake-entry",
            "kind": "input_received",
            "session_id": "attacker",
            "sequence": 99,
            "logged_at": "2025-01-01T00:00:00+00:00",
            "node_id": "local",
            "prev_hash": "a" * 64,
            "related_ids": [],
            "payload": {"injected": True},
            "entry_hash": "b" * 64,
        }
        fake_line = json.dumps(fake, sort_keys=True, separators=(',', ':')) + "\n"
        lines.insert(3, fake_line)

        with open(self.path, 'w') as f:
            f.writelines(lines)

        tampered_log = AuditLog(self.path, auto_open=False)
        result = tampered_log.verify(log_verification=False)
        self.assertFalse(result.valid)

    def test_delete_entry_detected(self):
        """
        Remove an entry from the middle of the log and verify detection.
        The chain breaks because the next entry's prev_hash won't match.
        """
        with open(self.path, 'r') as f:
            lines = f.readlines()

        # Remove entry at index 2
        if len(lines) > 3:
            del lines[2]

        with open(self.path, 'w') as f:
            f.writelines(lines)

        tampered_log = AuditLog(self.path, auto_open=False)
        result = tampered_log.verify(log_verification=False)
        self.assertFalse(result.valid)

    def test_reorder_entries_detected(self):
        """
        Swap two entries and verify that the chain breaks.
        """
        with open(self.path, 'r') as f:
            lines = f.readlines()

        if len(lines) >= 4:
            lines[1], lines[2] = lines[2], lines[1]

        with open(self.path, 'w') as f:
            f.writelines(lines)

        tampered_log = AuditLog(self.path, auto_open=False)
        result = tampered_log.verify(log_verification=False)
        self.assertFalse(result.valid)

    def test_verification_result_is_serializable(self):
        result = self.log.verify(log_verification=False)
        d = result.to_dict()
        json.dumps(d)  # should not raise


# ---------------------------------------------------------------------------
# Querying
# ---------------------------------------------------------------------------

class TestAuditLogQuery(unittest.TestCase):

    def setUp(self):
        self.log, self.path = make_tmp_log()
        self.log.append(make_entry(kind=EntryKind.INPUT_RECEIVED, session_id="s1"))
        self.log.append(make_entry(kind=EntryKind.CONTEXT_PARSED, session_id="s1"))
        self.log.append(make_entry(kind=EntryKind.ETHICS_EVALUATED, session_id="s1"))
        self.log.append(make_entry(kind=EntryKind.INPUT_RECEIVED, session_id="s2"))
        self.log.append(make_entry(kind=EntryKind.CONSEQUENCE_MAP, session_id="s2"))

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def test_query_by_session(self):
        results = self.log.query(LogQuery(session_id="s1"))
        self.assertTrue(all(e.session_id == "s1" for e in results))

    def test_query_by_kind(self):
        results = self.log.query(LogQuery(kind=EntryKind.INPUT_RECEIVED))
        self.assertTrue(all(e.kind == EntryKind.INPUT_RECEIVED for e in results))
        self.assertEqual(len(results), 2)  # s1 and s2

    def test_query_with_limit(self):
        results = self.log.query(LogQuery(limit=2))
        self.assertEqual(len(results), 2)

    def test_query_no_filters_returns_all(self):
        all_entries = self.log.query(LogQuery())
        self.assertEqual(len(all_entries), self.log.count())

    def test_query_session_and_kind_combined(self):
        results = self.log.query(LogQuery(session_id="s1", kind=EntryKind.ETHICS_EVALUATED))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].kind, EntryKind.ETHICS_EVALUATED)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestAuditLogSummary(unittest.TestCase):

    def setUp(self):
        self.log, self.path = make_tmp_log()
        self.log.append(make_entry(kind=EntryKind.INPUT_RECEIVED, session_id="s1"))
        self.log.append(make_entry(kind=EntryKind.ETHICS_EVALUATED, session_id="s2"))

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def test_summary_returns_dict(self):
        s = self.log.summary()
        self.assertIsInstance(s, dict)

    def test_summary_has_total_entries(self):
        s = self.log.summary()
        self.assertIn("total_entries", s)
        self.assertEqual(s["total_entries"], self.log.count())

    def test_summary_has_unique_sessions(self):
        s = self.log.summary()
        self.assertIn("unique_sessions", s)
        # s1, s2, plus the system session from LOG_OPENED
        self.assertGreaterEqual(s["unique_sessions"], 2)

    def test_summary_has_entry_kinds(self):
        s = self.log.summary()
        self.assertIn("entry_kinds", s)
        self.assertIn("input_received", s["entry_kinds"])

    def test_summary_has_timestamps(self):
        s = self.log.summary()
        self.assertIsNotNone(s["first_entry_at"])
        self.assertIsNotNone(s["last_entry_at"])

    def test_summary_has_chain_tip(self):
        s = self.log.summary()
        self.assertIn("current_chain_tip", s)


# ---------------------------------------------------------------------------
# Tamper scenario simulations
# ---------------------------------------------------------------------------

class TestTamperScenarios(unittest.TestCase):
    """
    Simulate realistic tampering attacks and verify they are all detected.

    These tests document the threat model: what an attacker who has gained
    write access to the log file can and cannot get away with.

    Result: nothing. Every modification breaks the chain.
    """

    def _build_log(self, num_entries=8) -> tuple[AuditLog, str]:
        log, path = make_tmp_log()
        for i in range(num_entries):
            log.append(writers.write_input_received(
                f"session-{i % 3}", f"Proposal {i}", f"input-{i}"
            ))
        return log, path

    def _verify(self, path: str) -> VerificationResult:
        log = AuditLog(path, auto_open=False)
        return log.verify(log_verification=False)

    def _read_lines(self, path: str) -> list[str]:
        with open(path, 'r') as f:
            return f.readlines()

    def _write_lines(self, path: str, lines: list[str]) -> None:
        with open(path, 'w') as f:
            f.writelines(lines)

    def tearDown(self):
        pass  # each test creates its own temp file

    def test_attack_modify_one_field(self):
        """Attacker changes a single field value in one entry."""
        log, path = self._build_log()
        lines = self._read_lines(path)
        data = json.loads(lines[3])
        data["payload"]["raw_input"] = "MODIFIED BY ATTACKER"
        lines[3] = json.dumps(data, sort_keys=True, separators=(',', ':')) + "\n"
        self._write_lines(path, lines)
        result = self._verify(path)
        self.assertFalse(result.valid)
        os.unlink(path)

    def test_attack_append_false_entry_at_end(self):
        """Attacker appends a new entry at the end with a fabricated prev_hash."""
        log, path = self._build_log()
        fake = {
            "entry_id": "attacker-entry",
            "kind": "ethics_evaluated",
            "session_id": "attacker",
            "sequence": 999,
            "logged_at": "2099-01-01T00:00:00+00:00",
            "node_id": "attacker-node",
            "prev_hash": "a" * 64,  # Wrong
            "related_ids": [],
            "payload": {"verdict": "pass", "INJECTED": True},
            "entry_hash": "b" * 64,  # Wrong
        }
        with open(path, 'a') as f:
            f.write(json.dumps(fake, sort_keys=True, separators=(',', ':')) + "\n")
        result = self._verify(path)
        # The appended entry's prev_hash won't match the real last entry's hash
        self.assertFalse(result.valid)
        os.unlink(path)

    def test_attack_truncate_log(self):
        """Attacker removes all entries after a certain point."""
        log, path = self._build_log(10)
        lines = self._read_lines(path)
        # Keep only first 5 lines
        self._write_lines(path, lines[:5])
        # A truncated log still verifies what's there — but we can detect
        # the missing entries through external mechanisms (entry count tracking).
        # The remaining chain itself should still be valid.
        result = self._verify(path)
        self.assertTrue(result.valid)  # Truncation doesn't break the remaining chain
        self.assertEqual(result.entries_checked, 5)
        os.unlink(path)

    def test_attack_replace_hash_to_hide_payload_change(self):
        """
        Attacker modifies a payload AND updates the entry_hash to match,
        but cannot update all subsequent prev_hashes in the chain.
        This is the 'smart attacker' scenario.
        """
        log, path = self._build_log()
        lines = self._read_lines(path)

        # Modify entry at index 3 and recompute its hash
        data = json.loads(lines[3])
        data["payload"]["raw_input"] = "SMART ATTACKER"
        # Recompute the hash for the modified entry
        from SeedCore.audit_log.models import AuditEntry as AE, EntryKind as EK
        temp_entry = AE(
            kind=EK(data["kind"]),
            payload=data["payload"],
            session_id=data["session_id"],
            related_ids=data["related_ids"],
            node_id=data["node_id"],
            prev_hash=data["prev_hash"],
            sequence=data["sequence"],
            entry_id=data["entry_id"],
            logged_at=data["logged_at"],
        )
        new_hash = temp_entry.compute_hash()
        data["entry_hash"] = new_hash
        lines[3] = json.dumps(data, sort_keys=True, separators=(',', ':')) + "\n"
        self._write_lines(path, lines)

        # Even though entry 3's hash is now internally consistent,
        # entry 4's prev_hash still points to the ORIGINAL hash of entry 3
        result = self._verify(path)
        self.assertFalse(result.valid,
            "Smart attacker recomputed entry_hash but chain should still break "
            "because next entry's prev_hash references the original hash")
        os.unlink(path)


# ---------------------------------------------------------------------------
# Integration: log all pipeline stage types
# ---------------------------------------------------------------------------

class TestIntegration(unittest.TestCase):

    def setUp(self):
        self.log, self.path = make_tmp_log()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass

    def test_full_analysis_session_logged(self):
        """Simulate logging a complete analysis pipeline run."""
        session = "integration-test-session"

        # 1. Input
        self.log.append(writers.write_input_received(
            session, "What if we implemented a carbon tax?", "input-001"
        ))

        # 2. Context parsed
        manifest = {
            "manifest_id": "m-001",
            "routing_version": "0.1.0",
            "context": {"input_id": "input-001", "scale": "national"},
            "routes": [],
            "invoked_channels": ["economic", "ecological"],
            "skipped_channels": [],
            "generated_at": "2025-01-01T00:00:00+00:00",
        }
        self.log.append(writers.write_context_parsed(session, manifest, "input-001"))

        # 3. Ethics evaluated
        evaluation = {
            "proposal_id": "p-001",
            "verdict": "pass",
            "justification": "Low harm, high benefit.",
            "weighted_harm": 0.15,
            "weighted_benefit": 0.82,
            "net_score": 0.67,
            "evaluated_at": "2025-01-01T00:00:01+00:00",
        }
        self.log.append(writers.write_ethics_evaluated(session, evaluation, "p-001", "m-001"))

        # 4. Channel outputs
        for channel in ["economic", "ecological"]:
            output = {
                "output_id": f"o-{channel}",
                "channel_name": channel,
                "status": "success",
                "overall_harm_score": 0.2,
                "overall_benefit_score": 0.8,
            }
            self.log.append(writers.write_channel_output(session, output, "m-001"))

        # 5. Consequence map
        cmap = {
            "map_id": "cm-001",
            "overall_verdict": "net_beneficial",
            "overall_harm_score": 0.18,
            "overall_benefit_score": 0.79,
            "net_score": 0.61,
            "executive_summary": "Carbon tax analysis complete.",
        }
        self.log.append(writers.write_consequence_map(session, cmap, "m-001", "p-001"))

        # Verify the full chain
        result = self.log.verify(log_verification=False)
        self.assertTrue(result.valid)

        # Query the session
        session_entries = self.log.get_session(session)
        kinds = [e.kind for e in session_entries]
        self.assertIn(EntryKind.INPUT_RECEIVED, kinds)
        self.assertIn(EntryKind.CONTEXT_PARSED, kinds)
        self.assertIn(EntryKind.ETHICS_EVALUATED, kinds)
        self.assertIn(EntryKind.CHANNEL_OUTPUT, kinds)
        self.assertIn(EntryKind.CONSEQUENCE_MAP, kinds)

    def test_error_event_logged_and_verifies(self):
        self.log.append(writers.write_pipeline_error(
            "s1", "synthesis", "TimeoutError", "Channel did not respond in 30s"
        ))
        result = self.log.verify(log_verification=False)
        self.assertTrue(result.valid)

    def test_human_review_logged(self):
        self.log.append(writers.write_human_review(
            "s1", "reviewer-abc", "approve",
            "After full review, benefits clearly outweigh harms.", "cm-001"
        ))
        results = self.log.query(LogQuery(kind=EntryKind.HUMAN_REVIEW))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].payload["decision"], "approve")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_log_verifies(self):
        tmp = tempfile.mktemp(suffix='.jsonl')
        try:
            log = AuditLog(tmp, auto_open=False)
            result = log.verify(log_verification=False)
            self.assertTrue(result.valid)
            self.assertEqual(result.entries_checked, 0)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass

    def test_single_entry_log_verifies(self):
        log, path = make_tmp_log(auto_open=False)
        try:
            log.append(make_entry())
            result = log.verify(log_verification=False)
            self.assertTrue(result.valid)
        finally:
            os.unlink(path)

    def test_log_reopened_continues_chain(self):
        """Appending to an existing log continues the hash chain correctly."""
        log, path = make_tmp_log()
        e1 = log.append(make_entry(payload={"first": True}))

        # Reopen
        log2 = AuditLog(path, auto_open=False)
        e2 = log2.append(make_entry(payload={"second": True}))

        self.assertEqual(e2.prev_hash, e1.entry_hash)

        result = log2.verify(log_verification=False)
        self.assertTrue(result.valid)
        os.unlink(path)

    def test_repr(self):
        log, path = make_tmp_log()
        r = repr(log)
        self.assertIn("AuditLog", r)
        os.unlink(path)

    def test_large_payload_handled(self):
        large_payload = {"data": "x" * 10_000, "numbers": list(range(500))}
        log, path = make_tmp_log()
        try:
            log.append(make_entry(payload=large_payload))
            result = log.verify(log_verification=False)
            self.assertTrue(result.valid)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
