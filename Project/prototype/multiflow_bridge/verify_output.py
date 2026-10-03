#!/usr/bin/env python3
"""
verify_output.py — verification and OSCAL export of the ledger the bridge produced.

Runs inside the container (or locally with ORACLE_PATH set):
  docker exec compliance_bridge python3 /bridge/verify_output.py

Reports the number of events and decisions, runs full chain verification
(recomputing hashes and Ed25519 signatures) and exports the OSCAL pair (complete
and Art. 78 redacted) to the output directory, next to the ledger.
"""

import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.getenv("ORACLE_PATH", "/oracle"))
from simulator import ComplianceOracle  # noqa: E402
import oscal_exporter  # noqa: E402

OUT_DIR = Path(os.getenv("OUT_DIR", "/out"))
LEDGER = OUT_DIR / "ledger.json"


def main() -> int:
    if not LEDGER.exists():
        print(f"no ledger at {LEDGER}: the bridge has not processed any batch yet")
        return 1
    ledger = json.loads(LEDGER.read_text())
    if not isinstance(ledger, list) or not ledger:
        print(f"{LEDGER} holds no records: there is nothing to verify")
        return 1
    print(f"evidence events      : {len(ledger)}")
    print(f"decisions            : {dict(Counter(r['decision'] for r in ledger))}")
    print(f"origin               : {ledger[0]['scenario_id']} … {ledger[-1]['scenario_id']}")

    oracle = ComplianceOracle(ledger_file=LEDGER)
    report = oracle.verify_chain()
    status = "INTACT ✅" if report.valid == report.total else "BROKEN ❌"
    print(f"chain                : {report.valid}/{report.total} {status}")
    for issue in report.issues[:5]:
        print(f"  issue: {issue}")

    chain_ok = report.valid == report.total
    completo = oscal_exporter.to_oscal_sar(ledger, chain_valid=chain_ok, redacted=False, signatures_verified=chain_ok)
    redigido = oscal_exporter.to_oscal_sar(ledger, chain_valid=chain_ok, redacted=True, signatures_verified=chain_ok)
    f1 = OUT_DIR / "oscal_multiflow.json"
    f2 = OUT_DIR / "oscal_multiflow_redacted.json"
    f1.write_text(json.dumps(completo, indent=2))
    f2.write_text(json.dumps(redigido, indent=2))
    n_find = len(completo["assessment-results"]["results"][0]["findings"])
    print(f"OSCAL                : {f1.name} + {f2.name} ({n_find} findings)")
    return 0 if report.valid == report.total else 2


if __name__ == "__main__":
    sys.exit(main())
