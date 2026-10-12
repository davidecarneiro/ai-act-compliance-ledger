"""The arms of the WP3 ablation and their verifiers.

Protocol: ``Project/protocols/wp3_ablation.md``. Each arm takes an event,
decides with ``simulator.evaluate_event`` under the same policy and persists
the outcome durably; the arms differ only in what they persist:

* ``A``  — one SQLite row (``BaselineLogger.record``);
* ``B0`` — the engine's version 2 record, hashed and chained, append-only,
  without the signature;
* ``B``  — the engine as it is (signed);
* ``Bplus`` — B, plus a signed head appended every K records to an external
  anchor file (a stand-in for a transparency log).

The verifiers are what a third party holding the arm's output (and, for B and
B+, the issuer's public key; for B+, the anchor file) can check. They are used
by the tamper-detection experiment (section 4.4 of the article plan).
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from baseline_logger import BaselineLogger
from canonical import SCHEMA_V2, canonical_v2, record_body_bytes
from keys import IssuerKey, load_or_create_key, public_key_fingerprint
from ledger_store import GENESIS_HASH, read_ledger
from simulator import ComplianceOracle, sha256_hex

ARM_NAMES = ("A", "B0", "B", "Bplus")
ANCHOR_INTERVAL = 100


class _UnsignedEngine(ComplianceOracle):
    """The engine with its signing step removed (arm B0)."""

    def _sign(self, body_bytes: bytes):
        return None


class Arm:
    name = "?"

    def process(self, event: dict) -> dict:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SQLiteArm(Arm):
    """Arm A."""

    name = "A"

    def __init__(self, workdir: Path, policies: dict) -> None:
        self.db_file = Path(workdir) / "A.sqlite"
        self.logger = BaselineLogger(db_file=self.db_file, policies=policies,
                                     schema_version=SCHEMA_V2)

    def process(self, event: dict) -> dict:
        return self.logger.record(event)

    def close(self) -> None:
        self.logger.close()

    def settings(self) -> Dict[str, object]:
        c = self.logger.connection
        return {
            "sqlite_version": sqlite3.sqlite_version,
            "journal_mode": c.execute("PRAGMA journal_mode").fetchone()[0],
            "synchronous": c.execute("PRAGMA synchronous").fetchone()[0],
        }


class EvidenceArm(Arm):
    """Arms B0 and B: the engine writing a ``.jsonl`` ledger with fsync."""

    def __init__(self, name: str, workdir: Path, policy_file: Path, key: IssuerKey) -> None:
        self.name = name
        engine_class = _UnsignedEngine if name == "B0" else ComplianceOracle
        self.ledger_file = Path(workdir) / f"{name}.jsonl"
        self.engine = engine_class(policy_file=policy_file, ledger_file=self.ledger_file,
                                   issuer_key=key, schema_version=SCHEMA_V2)
        self.engine.reset_ledger()

    def process(self, event: dict) -> dict:
        # process_mlops_event without its timing, bookkeeping and log line.
        return self.engine.store.append_with(
            lambda _seq, parent: self.engine._build_record(event, parent))


class AnchoredArm(EvidenceArm):
    """Arm B+: B, plus a signed head every ``interval`` records."""

    def __init__(self, workdir: Path, policy_file: Path, key: IssuerKey,
                 anchor_dir: Optional[Path] = None, interval: int = ANCHOR_INTERVAL) -> None:
        super().__init__("Bplus", workdir, policy_file, key)
        self.key = key
        self.interval = interval
        self.anchor_file = Path(anchor_dir or Path(workdir) / "external") / "anchors.jsonl"
        self.anchor_file.parent.mkdir(parents=True, exist_ok=True)
        self.anchor_file.write_bytes(b"")
        self.count = 0
        self.anchor_ns: List[int] = []

    def process(self, event: dict) -> dict:
        record = super().process(event)
        self.count += 1
        if self.count % self.interval == 0:
            import time
            t0 = time.perf_counter_ns()
            publish_anchor(self.anchor_file, self.key, self.count, record["chain_hash"])
            self.anchor_ns.append(time.perf_counter_ns() - t0)
        return record


def anchor_statement(seq: int, chain_hash: str, anchored_at: str, fingerprint: str) -> dict:
    return {"seq": seq, "chain_hash": chain_hash, "anchored_at": anchored_at,
            "issuer_pubkey_fingerprint": fingerprint}


def publish_anchor(anchor_file: Path, key: IssuerKey, seq: int, chain_hash: str) -> dict:
    """Append the signed head to the external anchor file, fsynced."""
    from datetime import datetime, timezone

    statement = anchor_statement(seq, chain_hash, datetime.now(timezone.utc).isoformat(),
                                 public_key_fingerprint(key))
    entry = {"statement": statement,
             "signature": base64.b64encode(key.sign(canonical_v2(statement))).decode("ascii")}
    line = (json.dumps(entry, separators=(",", ":")) + "\n").encode("ascii")
    fd = os.open(anchor_file, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return entry


def make_arms(workdir: Path, policy_file: Path, policies: dict, key: IssuerKey,
              interval: int = ANCHOR_INTERVAL) -> Dict[str, Arm]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    return {
        "A": SQLiteArm(workdir, policies),
        "B0": EvidenceArm("B0", workdir, policy_file, key),
        "B": EvidenceArm("B", workdir, policy_file, key),
        "Bplus": AnchoredArm(workdir, policy_file, key, interval=interval),
    }


# ----------------------------------------------------------------------
# Verifiers: what a third party can check on each arm's output
# ----------------------------------------------------------------------

def verify_sqlite(db_file: Path) -> Dict:
    """Arm A has no integrity mechanism. The only internal check available is
    that row identifiers run 1..n without gaps, which an attacker with write
    access to the database restores at will."""
    connection = sqlite3.connect(str(db_file))
    try:
        ids = [r[0] for r in connection.execute("SELECT id FROM events ORDER BY id")]
    finally:
        connection.close()
    contiguous = ids == list(range(1, len(ids) + 1))
    return {"valid": contiguous, "records": len(ids),
            "issues": [] if contiguous else ["row identifiers are not contiguous"]}


def verify_hash_chain(records: Iterable[dict]) -> Dict:
    """Arm B0: every body recomputes to its record_hash and links to its parent."""
    issues, parent, n = [], GENESIS_HASH, 0
    for i, r in enumerate(records):
        n += 1
        try:
            record_hash = sha256_hex(record_body_bytes(r))
        except Exception as exc:  # no canonical form
            issues.append(f"record {i}: body has no canonical form ({exc})")
            parent = r.get("chain_hash", "")
            continue
        if record_hash != r.get("record_hash"):
            issues.append(f"record {i}: body does not match record_hash")
        if r.get("parent_hash") != parent:
            issues.append(f"record {i}: parent_hash does not link to the previous record")
        if sha256_hex((str(r.get("parent_hash")) + str(r.get("record_hash"))).encode("utf-8")) != r.get("chain_hash"):
            issues.append(f"record {i}: chain_hash does not recompute")
        parent = r.get("chain_hash", "")
    return {"valid": not issues, "records": n, "issues": issues}


def verify_signed(records: List[dict], key: IssuerKey) -> Dict:
    """Arm B: the hash chain and every signature, against the issuer key."""
    report = verify_hash_chain(records)
    public = key.public_key
    for i, r in enumerate(records):
        try:
            public.verify(base64.b64decode(r["issuer_signature"]), record_body_bytes(r))
        except Exception:
            report["issues"].append(f"record {i}: signature does not verify")
    report["valid"] = not report["issues"]
    return report


def verify_anchored(records: List[dict], key: IssuerKey, anchor_file: Path) -> Dict:
    """Arm B+: B, plus every anchored head must be in the ledger."""
    report = verify_signed(records, key)
    anchors = [json.loads(line) for line in Path(anchor_file).read_text(encoding="utf-8").splitlines()
               if line.strip()]
    for entry in anchors:
        statement = entry["statement"]
        try:
            key.public_key.verify(base64.b64decode(entry["signature"]), canonical_v2(statement))
        except Exception:
            report["issues"].append(f"anchor {statement.get('seq')}: signature does not verify")
            continue
        seq = statement["seq"]
        if seq > len(records):
            report["issues"].append(
                f"anchor {seq}: the ledger has only {len(records)} records (truncated)")
        elif records[seq - 1].get("chain_hash") != statement["chain_hash"]:
            report["issues"].append(f"anchor {seq}: chain_hash differs from the anchored head")
    report["anchors"] = len(anchors)
    report["valid"] = not report["issues"]
    return report


def verify_arm(name: str, workdir: Path, key: IssuerKey) -> Dict:
    workdir = Path(workdir)
    if name == "A":
        return verify_sqlite(workdir / "A.sqlite")
    records = read_ledger(workdir / f"{name}.jsonl")
    if name == "B0":
        return verify_hash_chain(records)
    if name == "B":
        return verify_signed(records, key)
    return verify_anchored(records, key, workdir / "external" / "anchors.jsonl")


def bench_key(workdir: Path) -> IssuerKey:
    """An issuer key of its own for a benchmark or experiment folder."""
    return load_or_create_key("ablation-issuer", keys_dir=Path(workdir) / "keys")
