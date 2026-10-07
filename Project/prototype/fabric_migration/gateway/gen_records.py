#!/usr/bin/env python3
"""gen_records.py — generates N signed evidence records (a valid chain from the
genesis) for the Go Gateway client to submit. The Python simulator holds the
private key and canonical_json, so it does the signing; Go only submits.

    python3 gen_records.py [N] [OUT_DIR]   # default 30, EXPERIMENTS_DIR/fabric_gateway

Writes:  OUT_DIR/records.json  (array of N records)  and  OUT_DIR/pubkey.txt
(public key, hex). The records.json and pubkey.txt next to this script are the
published Gateway measurement (thesis-v1.0) and are no longer written here.
Records are issued under the current schema version (RFC 8785 unless
EVIDENCE_SCHEMA_VERSION=1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parents[1] / "compliance_ledger_sim"
sys.path.insert(0, str(SIM))

from simulator import ComplianceOracle          # noqa: E402
from paths import EXPERIMENTS_DIR               # noqa: E402
from scenarios import build_scenarios           # noqa: E402
from keys import load_or_create_key             # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else EXPERIMENTS_DIR / "fabric_gateway"
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_records_ledger.json"
    oracle = ComplianceOracle(ledger_file=tmp)
    oracle.reset_ledger()
    base = build_scenarios()
    for i in range(n):
        ev = dict(base[i % len(base)])
        ev["scenario_id"] = f"{ev['scenario_id']}-{i:04d}"
        oracle.process_mlops_event(ev)
    records = json.loads(tmp.read_text())[:n]
    (out / "records.json").write_text(json.dumps(records))
    tmp.unlink(missing_ok=True)

    raw = load_or_create_key().public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)
    (out / "pubkey.txt").write_text(raw.hex())
    print(f"wrote {len(records)} records to {out / 'records.json'} and {out / 'pubkey.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
