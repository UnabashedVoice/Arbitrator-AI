"""
models.py — Data structures for the Arbitrator Audit Log.

Every record appended to the audit log is an AuditEntry. The entry wraps
a payload (the actual data being logged) with metadata that enables:
    - Tamper detection (hash chain)
    - Provenance (what kind of record, when, from which pipeline stage)
    - Querying (by kind, by session, by timestamp range)
    - Cross-linking (entries reference related entries by ID)

The hash chain works as follows:
    - The first entry in the log has prev_hash = GENESIS_HASH (a fixed sentinel)
    - Every subsequent entry has prev_hash = the SHA-256 hash of the
      previous entry's canonical serialization
    - The entry's own hash (entry_hash) is the SHA-256 of its own
      canonical serialization (including prev_hash)
    - Verification walks the chain recomputing hashes; any mismatch
      indicates tampering or corruption

This is not a blockchain — there is no distributed consensus, no proof of
work, no cryptocurrency. It is simply a hash-chained append-only log,
which is sufficient for tamper-evidence in the single-node phase. The
federation layer (Phase 3+) will add cross-node replication and consensus.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The sentinel prev_hash for the very first entry in a log.
# A fixed, well-known value that cannot be confused with a real hash.
GENESIS_HASH = "0" * 64

# The hashing algorithm used throughout.
HASH_ALGORITHM = "sha256"


# ---------------------------------------------------------------------------
# Entry kinds
# ---------------------------------------------------------------------------

class EntryKind(Enum):
    """
    The kind of record being logged.

    Every pipeline stage has its own entry kind. This allows querying
    the log by stage ("show me all Ethics Core evaluations") and makes
    the log self-describing.
    """
    # Pipeline stages
    INPUT_RECEIVED = "input_received"               # Raw user input
    CONTEXT_PARSED = "context_parsed"               # RoutingManifest from Context Parser
    ETHICS_EVALUATED = "ethics_evaluated"           # EthicsEvaluation from Ethics Core
    CHANNEL_OUTPUT = "channel_output"               # Output from a single channel
    CONSEQUENCE_MAP = "consequence_map"             # ConsequenceMap from Synthesizer
    FEEDBACK_RECEIVED = "feedback_received"         # Feedback submission
    HUMAN_REVIEW = "human_review"                   # Human review decision

    # System events
    LOG_OPENED = "log_opened"                       # Log file created/opened
    LOG_VERIFIED = "log_verified"                   # Chain integrity verification run
    VERIFICATION_FAILED = "verification_failed"     # Chain integrity check failed
    NODE_REGISTERED = "node_registered"             # A new node joined (future federation)

    # Error events
    PIPELINE_ERROR = "pipeline_error"               # An error occurred during processing
    CHANNEL_FAILURE = "channel_failure"             # A specific channel failed


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    """
    A single record in the audit log.

    Every record appended to the log is represented as an AuditEntry.
    The entry is immutable after creation — its hash is computed at
    construction time and must not change.

    Attributes:
        kind:           What type of record this is.
        payload:        The actual data being logged. Must be JSON-serializable.
        session_id:     Groups all entries from a single analysis run.
        related_ids:    IDs of related entries (e.g., the input that led to
                        this evaluation). Used for cross-linking in queries.
        node_id:        Identifier of the node that created this entry.
                        "local" for single-node operation.
        prev_hash:      SHA-256 hash of the previous entry's serialization.
                        GENESIS_HASH for the first entry.
        entry_hash:     SHA-256 hash of this entry's canonical serialization.
                        Computed automatically — do not set manually.
        sequence:       Monotonically increasing sequence number within the log.
        entry_id:       UUID for this specific entry.
        logged_at:      UTC timestamp of when this entry was appended.
    """
    kind: EntryKind
    payload: dict
    session_id: str
    related_ids: list[str] = field(default_factory=list)
    node_id: str = "local"
    prev_hash: str = GENESIS_HASH
    entry_hash: str = ""            # Computed on first access / serialization
    sequence: int = 0               # Set by the log when appending
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    logged_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def canonical_dict(self) -> dict:
        """
        Produce the canonical dict used for hashing.

        CRITICAL: This must be deterministic. The same entry must always
        produce the same canonical_dict. Fields are explicitly ordered.
        Do not use **self.__dict__ — field order is not guaranteed.
        """
        return {
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "logged_at": self.logged_at,
            "node_id": self.node_id,
            "prev_hash": self.prev_hash,
            "related_ids": sorted(self.related_ids),  # sorted for determinism
            "payload": self.payload,
        }

    def compute_hash(self) -> str:
        """
        Compute the SHA-256 hash of this entry's canonical serialization.

        Uses `sort_keys=True` and `separators=(',',':')` for a compact,
        deterministic JSON encoding. The same entry always produces the
        same hash.
        """
        canonical = json.dumps(
            self.canonical_dict(),
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=True,
        ).encode('utf-8')
        return hashlib.sha256(canonical).hexdigest()

    def finalize(self) -> "AuditEntry":
        """
        Compute and store the entry_hash. Called by the log before appending.
        Returns self for chaining.
        """
        self.entry_hash = self.compute_hash()
        return self

    def to_log_line(self) -> str:
        """
        Serialize this entry to a single JSON line for the log file.
        Includes entry_hash. Terminated with newline.
        """
        record = self.canonical_dict()
        record["entry_hash"] = self.entry_hash
        return json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + "\n"

    @classmethod
    def from_log_line(cls, line: str) -> "AuditEntry":
        """
        Deserialize an entry from a log file line.
        Does NOT recompute or verify the hash — use AuditLog.verify() for that.
        """
        data = json.loads(line.strip())
        entry = cls(
            kind=EntryKind(data["kind"]),
            payload=data["payload"],
            session_id=data["session_id"],
            related_ids=data.get("related_ids", []),
            node_id=data.get("node_id", "local"),
            prev_hash=data["prev_hash"],
            entry_hash=data.get("entry_hash", ""),
            sequence=data.get("sequence", 0),
            entry_id=data["entry_id"],
            logged_at=data["logged_at"],
        )
        return entry

    def to_public_dict(self) -> dict:
        """
        Produce a human-readable dict suitable for the public audit interface.
        Includes entry_hash. Payload is included verbatim.
        """
        d = self.canonical_dict()
        d["entry_hash"] = self.entry_hash
        d["kind"] = self.kind.value
        return d


# ---------------------------------------------------------------------------
# Verification result
# ---------------------------------------------------------------------------

@dataclass
class VerificationResult:
    """
    The result of a chain integrity verification run.

    Attributes:
        valid:              True if the entire chain is intact.
        entries_checked:    How many entries were verified.
        first_broken_at:    Sequence number of the first broken link, if any.
        broken_entry_id:    Entry ID of the first broken entry, if any.
        error_detail:       Human-readable description of the failure, if any.
        verified_at:        UTC timestamp of the verification run.
    """
    valid: bool
    entries_checked: int
    first_broken_at: Optional[int] = None
    broken_entry_id: Optional[str] = None
    error_detail: Optional[str] = None
    verified_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "entries_checked": self.entries_checked,
            "first_broken_at": self.first_broken_at,
            "broken_entry_id": self.broken_entry_id,
            "error_detail": self.error_detail,
            "verified_at": self.verified_at,
        }


# ---------------------------------------------------------------------------
# Query filters
# ---------------------------------------------------------------------------

@dataclass
class LogQuery:
    """
    A query against the audit log.

    All fields are optional. Omitted fields are not filtered on.
    Results are always returned in sequence order (oldest first).

    Attributes:
        session_id:     Filter to a specific analysis session.
        kind:           Filter to a specific entry kind.
        kinds:          Filter to any of a list of entry kinds.
        since:          Return entries logged after this ISO timestamp.
        until:          Return entries logged before this ISO timestamp.
        limit:          Maximum number of entries to return.
        related_to:     Return entries that reference this ID.
    """
    session_id: Optional[str] = None
    kind: Optional[EntryKind] = None
    kinds: Optional[list[EntryKind]] = None
    since: Optional[str] = None        # ISO 8601 timestamp
    until: Optional[str] = None        # ISO 8601 timestamp
    limit: Optional[int] = None
    related_to: Optional[str] = None   # entry_id or any related_id

    def matches(self, entry: AuditEntry) -> bool:
        """Return True if this entry matches all filter criteria."""
        if self.session_id and entry.session_id != self.session_id:
            return False
        if self.kind and entry.kind != self.kind:
            return False
        if self.kinds and entry.kind not in self.kinds:
            return False
        if self.since and entry.logged_at < self.since:
            return False
        if self.until and entry.logged_at > self.until:
            return False
        if self.related_to:
            if (self.related_to != entry.entry_id and
                    self.related_to not in entry.related_ids):
                return False
        return True
