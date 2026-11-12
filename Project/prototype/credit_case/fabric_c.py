"""Configuration C on the Fabric network: tamper attacks and Q12.

Protocol: ``protocols/tamper_detection.md`` (amendment of 2026-11-12) and
``protocols/wp5_answerability.md``. Input: the folder ``run_wp7.py measure``
writes after anchoring the credit case one record per anchor on the network
(``ledger.jsonl``, the provider's copy; ``onchain_anchors.json``, the
``GetAnchors`` export with the submitting organisation the chaincode
stamped; ``engine.pub.pem``).

C's check is what a third party holding the provider's copy and the on-chain
anchors can verify: B's check of every record, plus the anchors
(``batch_anchor.verify_batches``). The attacks T1–T7b of
the tamper experiment are applied to the provider's copy; T7a and T7b re-sign
with the engine's key, so this runs where that key is (the measurement
machine), right after the export.

    python3 fabric_c.py <credit_case_folder>
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

import credit_case as cc  # noqa: F401  (puts the engine on the path)
import batch_anchor as ba
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from keys import load_or_create_key, public_key_fingerprint
from ledger_store import read_ledger
from simulator import ISSUER_ID_V2
from tamper_experiment import DESCRIPTIONS, attack_ledger

ATTACKS = ("T1", "T2", "T3", "T4", "T5", "T6a", "T6b", "T7a", "T7b")


def _anchors(export: Dict):
    return sorted(export["anchors"], key=lambda a: a["statement"]["first_seq"])


def check(records, anchors, public_key) -> Dict:
    """B's check (every body, hash, link and signature) plus the anchors."""
    from types import SimpleNamespace

    from ablation_arms import verify_signed

    own = verify_signed(records, SimpleNamespace(public_key=public_key))
    anchored = ba.verify_batches(records, anchors, public_key)
    issues = own["issues"] + anchored["issues"]
    return {"valid": not issues, "records": len(records), "anchors": anchored["anchors"],
            "issues": issues}


def evaluate(folder: Path, key=None) -> Dict:
    folder = Path(folder)
    records = read_ledger(folder / "ledger.jsonl")
    export = json.loads((folder / "onchain_anchors.json").read_text(encoding="utf-8"))
    anchors = _anchors(export)
    public = load_pem_public_key((folder / "engine.pub.pem").read_bytes())
    key = key or load_or_create_key(ISSUER_ID_V2)
    signer_ok = public_key_fingerprint(key) == anchors[0]["statement"]["issuer_pubkey_fingerprint"]

    clean = check(records, anchors, public)
    results = {}
    for attack in ATTACKS:
        if attack in ("T7a", "T7b") and not signer_ok:
            results[attack] = {"observed": "not evaluated",
                               "reason": "the engine key here is not the key that signed"}
            continue
        attacked = attack_ledger(attack, records, key, signed=True)
        report = check(attacked, anchors, public)
        results[attack] = {"description": DESCRIPTIONS[attack],
                           "observed": "not detected" if report["valid"] else "detected",
                           "expected": "detected", "issues": report["issues"][:3]}

    submitters = sorted({a.get("submitter_msp") for a in anchors})
    q12 = {
        "answerable": "yes" if all(a.get("submitter_msp") for a in anchors) else "partial",
        "verifiable": "yes" if clean["valid"] else "no",
        "answer": {"organisations": submitters,
                   "records": len(records), "anchors": len(anchors)},
        "note": "submitter_msp is stamped by the chaincode on each anchor, under the AND endorsement policy",
    }
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocols": ["Project/protocols/tamper_detection.md", "Project/protocols/wp5_answerability.md"],
        "configuration": "C (Fabric, every record anchored, N = 1)",
        "clean_check": clean,
        "tamper": results,
        "all_as_expected": all(r.get("observed") == "detected" for r in results.values()),
        "q12": q12,
    }
    (folder / "configuration_c.json").write_text(json.dumps(output, indent=1) + "\n", encoding="utf-8")
    return output


def main(argv) -> int:
    out = evaluate(Path(argv[0]))
    for attack, r in out["tamper"].items():
        print(f"{attack:4} {r['observed']}")
    print(f"all as expected: {out['all_as_expected']}; Q12: {out['q12']['answer']['organisations']}")
    return 0 if out["clean_check"]["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
