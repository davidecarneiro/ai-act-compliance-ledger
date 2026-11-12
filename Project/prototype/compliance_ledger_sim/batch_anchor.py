"""Batch anchoring of evidence records (WP7 of the article plan).

The issuer chains its records locally (as arm B of the WP3 ablation) and,
every N records, anchors one signed statement on the ledger instead of N
records: the Merkle root (RFC 9162, ``merkle.py``) over the batch's
``record_hash`` values, the batch's place in the stream (first and last
sequence numbers) and the ``chain_hash`` of its last record. The chaincode's
``AnchorBatch`` checks the signature against the issuer registry and that
batches follow one another; ``VerifyInclusion`` checks that a record, with the
proof the issuer hands out, is in an anchored batch at the position claimed.

N = 1 per-record submission (``SubmitEvidence``) is kept for comparison.

Statement (signed by the issuer over its RFC 8785 form)::

    {"type": "evidence-batch-anchor", "stream": "<name>",
     "first_seq": 1, "last_seq": 50, "size": 50,
     "merkle_root": "<64 hex>", "head_chain_hash": "<64 hex>",
     "issuer_pubkey_fingerprint": "<64 hex>", "tree": "rfc9162-sha256",
     "anchored_at": "<ISO 8601>"}

Sequence numbers start at 1 and are positions in the issuer's ledger.

What an anchor establishes: that the issuer committed, before the anchor's
commit on the ledger, to exactly these records in this order. Records after
the last anchor are not covered (the window of the B+ arm), and a record never
written is not covered at all.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import merkle
from canonical import canonical_v2, record_body_bytes
from keys import public_key_fingerprint
from simulator import sha256_hex

ANCHOR_TYPE = "evidence-batch-anchor"
TREE = "rfc9162-sha256"


def entries(records: Sequence[dict]) -> List[bytes]:
    return [bytes.fromhex(r["record_hash"]) for r in records]


def anchor_statement(stream: str, first_seq: int, batch: Sequence[dict], fingerprint: str,
                     anchored_at: Optional[str] = None) -> dict:
    if not batch:
        raise ValueError("a batch holds at least one record")
    return {
        "type": ANCHOR_TYPE,
        "stream": stream,
        "first_seq": first_seq,
        "last_seq": first_seq + len(batch) - 1,
        "size": len(batch),
        "merkle_root": merkle.root(entries(batch)).hex(),
        "head_chain_hash": batch[-1]["chain_hash"],
        "issuer_pubkey_fingerprint": fingerprint,
        "tree": TREE,
        "anchored_at": anchored_at or datetime.now(timezone.utc).isoformat(),
    }


def sign_statement(statement: dict, key) -> dict:
    signature = key.sign(canonical_v2(statement))
    return {"statement": statement, "signature": base64.b64encode(signature).decode("ascii")}


def make_anchors(records: Sequence[dict], n: int, stream: str, key,
                 anchored_at: Optional[str] = None) -> List[dict]:
    """One signed anchor per batch of n consecutive records (the last batch may
    be shorter)."""
    if n < 1:
        raise ValueError("n must be at least 1")
    fingerprint = public_key_fingerprint(key)
    return [
        sign_statement(anchor_statement(stream, start + 1, records[start:start + n],
                                        fingerprint, anchored_at), key)
        for start in range(0, len(records), n)
    ]


def inclusion_proof(records: Sequence[dict], seq: int, n: int, stream: str) -> dict:
    """The proof the issuer hands out for record ``seq`` (1-based) when the
    stream is anchored in batches of n."""
    start = ((seq - 1) // n) * n
    batch = records[start:start + n]
    index = seq - 1 - start
    return {
        "stream": stream,
        "first_seq": start + 1,
        "leaf_index": index,
        "tree_size": len(batch),
        "path": [h.hex() for h in merkle.inclusion_path(index, entries(batch))],
    }


def proof_size_bytes(proof: dict) -> int:
    """Size of the proof as handed out (compact JSON)."""
    return len(json.dumps(proof, separators=(",", ":")).encode("ascii"))


# ----------------------------------------------------------------------
# Verification (what an auditor holding the records and the anchors can do)
# ----------------------------------------------------------------------

def verify_anchor_signature(anchor: dict, public_key) -> bool:
    try:
        public_key.verify(base64.b64decode(anchor["signature"]), canonical_v2(anchor["statement"]))
        return True
    except Exception:
        return False


def verify_batches(records: Sequence[dict], anchors: Iterable[dict], public_key) -> Dict:
    """Every anchor's signature, contiguity, Merkle root and head against the
    local ledger. Truncation below an anchored sequence number is reported."""
    issues: List[str] = []
    expected_first = 1
    count = 0
    for anchor in anchors:
        count += 1
        s = anchor["statement"]
        label = f"anchor [{s['first_seq']}, {s['last_seq']}]"
        if not verify_anchor_signature(anchor, public_key):
            issues.append(f"{label}: signature does not verify")
        if s["first_seq"] != expected_first:
            issues.append(f"{label}: does not follow the previous batch")
        expected_first = s["last_seq"] + 1
        if s["last_seq"] > len(records):
            issues.append(f"{label}: the ledger has only {len(records)} records (truncated)")
            continue
        batch = records[s["first_seq"] - 1:s["last_seq"]]
        if merkle.root(entries(batch)).hex() != s["merkle_root"]:
            issues.append(f"{label}: Merkle root differs from the records")
        if batch[-1]["chain_hash"] != s["head_chain_hash"]:
            issues.append(f"{label}: head chain_hash differs")
    return {"valid": not issues, "anchors": count, "issues": issues}


def verify_record_inclusion(record: dict, proof: dict, anchor_statement_: dict) -> Dict:
    """What the chaincode's VerifyInclusion checks, minus the issuer
    signature: the record's body recomputes to its record_hash, its chain_hash
    recomputes, and the proof leads to the anchored root."""
    record_hash = sha256_hex(record_body_bytes(record))
    if record_hash != record.get("record_hash"):
        return {"included": False, "reason": "record_hash does not match the body"}
    if sha256_hex((record["parent_hash"] + record_hash).encode("utf-8")) != record.get("chain_hash"):
        return {"included": False, "reason": "chain_hash does not recompute"}
    s = anchor_statement_
    if proof["first_seq"] != s["first_seq"] or proof["tree_size"] != s["size"]:
        return {"included": False, "reason": "proof names another batch"}
    ok = merkle.verify_inclusion(bytes.fromhex(record_hash), proof["leaf_index"], proof["tree_size"],
                                 [bytes.fromhex(p) for p in proof["path"]],
                                 bytes.fromhex(s["merkle_root"]))
    if not ok:
        return {"included": False, "reason": "proof does not lead to the anchored root"}
    return {"included": True, "seq": s["first_seq"] + proof["leaf_index"]}


def write_jsonl(path: Path, items: Iterable[dict]) -> None:
    path.write_text("".join(json.dumps(i, separators=(",", ":")) + "\n" for i in items),
                    encoding="utf-8")
