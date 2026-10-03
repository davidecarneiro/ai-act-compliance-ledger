#!/usr/bin/env python3
"""gen_records.py — generates N signed evidence records (a valid chain from the
genesis) for the Go Gateway client to submit. The Python simulator holds the
private key and canonical_json, so it does the signing; Go only submits.

    python3 gen_records.py [N]   # default 30

Writes:  records.json  (array of N records)  and  pubkey.txt  (public key, hex).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parents[1] / "compliance_ledger_sim"
sys.path.insert(0, str(SIM))

from simulator import ComplianceOracle          # noqa: E402
from scenarios import build_scenarios           # noqa: E402
from keys import load_or_create_key             # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    tmp = HERE / "_records_ledger.json"
    oracle = ComplianceOracle(ledger_file=tmp)
    oracle.reset_ledger()
    base = build_scenarios()
    for i in range(n):
        ev = dict(base[i % len(base)])
        ev["scenario_id"] = f"{ev['scenario_id']}-{i:04d}"
        oracle.process_mlops_event(ev)
    records = json.loads(tmp.read_text())[:n]
    (HERE / "records.json").write_text(json.dumps(records))
    tmp.unlink(missing_ok=True)

    raw = load_or_create_key().public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    (HERE / "pubkey.txt").write_text(raw.hex())
    print(f"wrote {len(records)} records to records.json and pubkey.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
