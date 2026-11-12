#!/usr/bin/env python3
"""Generate the batch-anchoring fixtures (WP7) for the Go tests.

    python3 gen_testdata_anchors.py      # from this folder

Writes, next to this script:

* testdata_merkle_vectors.json: Merkle roots and inclusion paths computed by
  the Python implementation (compliance_ledger_sim/merkle.py) for the
  Certificate Transparency reference leaves (sizes 1 to 8, whose roots are
  the published RFC 6962 test values) and for trees of 1 to 33 entries of 32
  bytes. Go must produce the same roots and paths and accept every path.
* testdata_anchors_v2.json: the 16 records of testdata_ledger_v2.json
  anchored in batches of 5 (stream "fixture"; batches of 5, 5, 5 and 1) with
  the demonstration key the Go tests register, and the inclusion proof of
  every record.

The anchors carry a fixed anchored_at, so regeneration is deterministic for
the same ledger fixture.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parents[1] / "compliance_ledger_sim"
sys.path.insert(0, str(SIM))

import batch_anchor  # noqa: E402
import merkle  # noqa: E402
from keys import load_or_create_key  # noqa: E402
from simulator import ISSUER_ID_V1  # noqa: E402

CT_LEAVES = [b"", b"\x00", b"\x10", b"\x20\x21", b"\x30\x31", b"\x40\x41\x42\x43",
             bytes(range(0x50, 0x58)), bytes(range(0x60, 0x70))]
N = 5
STREAM = "fixture"
ANCHORED_AT = "2026-11-12T00:00:00+00:00"


def vectors() -> dict:
    trees = []
    for label, leaves in (
        ("ct", None),
        ("sha256-entries", [hashlib.sha256(str(i).encode()).digest() for i in range(33)]),
    ):
        sizes = range(1, 9) if label == "ct" else range(1, 34)
        for n in sizes:
            entries = CT_LEAVES[:n] if label == "ct" else leaves[:n]
            trees.append({
                "set": label,
                "entries": [e.hex() for e in entries],
                "root": merkle.root(entries).hex(),
                "paths": [[p.hex() for p in merkle.inclusion_path(i, entries)] for i in range(n)],
            })
    return {"definition": "RFC 9162 section 2.1; leaf 0x00, node 0x01, SHA-256", "trees": trees}


def anchors() -> dict:
    records = json.loads((HERE / "testdata_ledger_v2.json").read_text(encoding="utf-8"))
    key = load_or_create_key(ISSUER_ID_V1)
    made = batch_anchor.make_anchors(records, N, STREAM, key, anchored_at=ANCHORED_AT)
    proofs = [batch_anchor.inclusion_proof(records, seq, N, STREAM)
              for seq in range(1, len(records) + 1)]
    report = batch_anchor.verify_batches(records, made, key.public_key)
    assert report["valid"], report
    return {"ledger": "testdata_ledger_v2.json", "n": N, "stream": STREAM,
            "anchors": made, "proofs": proofs}


def main() -> int:
    (HERE / "testdata_merkle_vectors.json").write_text(json.dumps(vectors(), separators=(",", ":")) + "\n",
                                                      encoding="utf-8")
    (HERE / "testdata_anchors_v2.json").write_text(json.dumps(anchors(), indent=1) + "\n",
                                                  encoding="utf-8")
    print("wrote testdata_merkle_vectors.json and testdata_anchors_v2.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
