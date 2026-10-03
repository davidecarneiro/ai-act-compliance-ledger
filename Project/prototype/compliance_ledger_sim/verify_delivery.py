#!/usr/bin/env python3
"""Verify the seven evidence chains included in the dissertation delivery.

Recompute record hashes, parent links, chain hashes and Ed25519 signatures
using the delivered public key. The inventory requires 1,831 records.
Missing, empty, unreadable or incorrectly sized chains fail verification.

This command does not initialise the Oracle or rewrite evidence and key
files. Run: python3 verify_delivery.py."""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from paths import EXPERIMENTS_DIR, run_dir
from simulator import GENESIS_HASH, canonical_json, sha256_hex

AQUI = Path(__file__).resolve().parent
PUBLIC_KEY = AQUI / "keys" / "compliance-oracle-v1.ed25519.pub.pem"
DERIVED = {"record_hash", "issuer_signature", "chain_hash"}

# Required inventory: seven chains containing 1,831 records.
# Missing or incorrectly sized chains fail rather than reducing coverage.
# The last field is the final chain_hash of the published chain. Several scripts
# (simulator.py, compare_oracle_vs_baseline.py, sensitivity.py, incident_demo.py,
# gen_records.py, 02_submit_and_measure.py) write new records over these files.
# The new chain is valid and signed with the same demonstration key, so only the
# anchor tells it apart from the evidence the dissertation reports. The anchor is
# kept in this folder, so it catches regeneration, not a deliberate forgery.
INVENTORY = [
    ("canonical ledger (6 scenarios)", lambda: AQUI / "ledger.json", 6,
     "77760bb60f55ab893a69b53eef6ebd38593e27ca18b47f2f0d64e377f9442673"),
    ("Art. 73 incident", lambda: run_dir("incident_run") / "ledger.json", 3,
     "bdf9d4a57a1dc1ee619c0863221b9cbcf54c7f729f2cdb574647d0ef4d595bca"),
    ("MultiFlow, first run", lambda: run_dir("multiflow_run") / "ledger.json", 8,
     "3b84ae0beb5c133d937d48402c7c2864c521256484ba4b4ef4f68a52afe8c935"),
    ("MultiFlow, real data", lambda: run_dir("multiflow_run_real") / "ledger.json", 29,
     "7a4658c4b43d55f7141c425f83d2e03f24d2775aad9e15bf6a4783fca5942b6b"),
    ("MultiFlow, Steel load test", lambda: run_dir("multiflow_run_steel") / "ledger.json", 1750,
     "0701f66dcf4827d9e2d3cec0bae5e4bb1d5534017cb8ec9547f821f5945fd6e6"),
    ("Fabric, chain submitted", lambda: run_dir("fabric_run") / "_gen_ledger.json", 5,
     "5fb1ecf7c40f0971c95efee712323e0b3a4b6f598c00026177e07292af85969d"),
    ("Fabric, Gateway measurement", lambda: AQUI.parent / "fabric_migration" / "gateway" / "records.json", 30,
     "73dcfa19a639aa2f8a15fc7016629d28fdda81cffc1e15ea11cb9440938c5c6f"),
]


def load_public_key() -> Ed25519PublicKey:
    if not PUBLIC_KEY.exists():
        sys.exit(f"ERROR: the public key is missing: {PUBLIC_KEY}\n"
                 f"It ships with the dissertation and this command will not create one.")
    try:
        key = serialization.load_pem_public_key(PUBLIC_KEY.read_bytes())
    except Exception as e:                       # noqa: BLE001
        sys.exit(f"ERROR: {PUBLIC_KEY} is not a readable PEM public key ({e}).")
    if not isinstance(key, Ed25519PublicKey):
        sys.exit(f"ERROR: {PUBLIC_KEY} is not an Ed25519 public key.")
    return key


def read_chain(path: Path):
    """The chains were written along three paths and have three shapes."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    for key in ("records", "ledger", "entries"):
        if isinstance(data.get(key), list):
            return data[key]
    raise ValueError("no list of records found in the file")


def verify_chain(records: list, pub: Ed25519PublicKey):
    """Recompute every hash, link and signature. Returns (valid, issues)."""
    issues, valid, previous = [], 0, GENESIS_HASH
    for index, record in enumerate(records):
        body = {k: v for k, v in record.items() if k not in DERIVED}
        raw = canonical_json(body)
        recomputed = sha256_hex(raw)
        local = []
        if record.get("parent_hash") != previous:
            local.append("parent_hash mismatch")
        if recomputed != record.get("record_hash"):
            local.append("record_hash mismatch")
        try:
            pub.verify(base64.b64decode(record.get("issuer_signature", "")), raw)
        except (InvalidSignature, Exception):    # noqa: BLE001
            local.append("invalid signature")
        expected = sha256_hex((previous + recomputed).encode("utf-8"))
        if expected != record.get("chain_hash"):
            local.append("chain_hash mismatch")
        if local:
            issues.append(f"#{index} ({record.get('scenario_id')}): " + ", ".join(local))
        else:
            valid += 1
        previous = record.get("chain_hash", expected)
    return valid, issues


def main() -> int:
    pub = load_public_key()
    print("Public key: %s" % PUBLIC_KEY)
    print("%-34s %8s %8s %8s  %s" % ("chain", "expected", "found", "valid", "status"))

    total = total_valid = 0
    failed = False
    regenerated = False
    for label, locate, expected, anchor in INVENTORY:
        path = locate()
        if not path.exists():
            print("%-34s %8d %8s %8s  MISSING (%s)" % (label, expected, "-", "-", path))
            failed = True
            continue
        try:
            records = read_chain(path)
        except Exception as e:                   # noqa: BLE001
            print("%-34s %8d %8s %8s  UNREADABLE (%s)" % (label, expected, "-", "-", e))
            failed = True
            continue
        if not records:
            print("%-34s %8d %8d %8s  EMPTY" % (label, expected, 0, "-"))
            failed = True
            continue
        valid, issues = verify_chain(records, pub)
        estado = "OK" if valid == len(records) == expected else "FAILED"
        if estado == "OK" and records[-1].get("chain_hash") != anchor:
            estado = "NOT PUBLISHED"
            regenerated = True
        if estado != "OK":
            failed = True
        print("%-34s %8d %8d %8d  %s" % (label, expected, len(records), valid, estado))
        for issue in issues[:3]:
            print("        %s" % issue)
        if len(records) != expected:
            print("        the chain has %d records and the inventory expects %d"
                  % (len(records), expected))
        total += len(records)
        total_valid += valid

    print("\n%d records over %d chains; %d verify." % (total, len(INVENTORY), total_valid))
    if regenerated:
        print("NOT PUBLISHED: a chain is valid but ends on a different chain_hash from the one\n"
              "published with the dissertation. It was regenerated in this folder (by\n"
              "simulator.py, a demonstration script or a measurement), so it is not the\n"
              "evidence the dissertation reports. Restore the folder from the delivered copy.")
    if failed:
        print("VERIFICATION FAILED. A chain is missing, empty, short, does not verify,\n"
              "or is not the published one.")
        return 1
    print("Every signature was checked against the public key above, and nothing was written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
