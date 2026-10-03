#!/usr/bin/env python3
"""Standalone demonstration of the serious-incident scenario (AI Act Art. 73).

Runs the ``build_incident_scenario()`` sequence (detection, simulated report
to the authority, audit query) against its own ledger, verifies the chain and exports the
OSCAL pair (full and redacted). It does not touch the canonical ledger or the
reference latency run: it is a separate demonstration, in the same mould as
the load test and the MultiFlow integration, and it is the evidence behind the
``validated`` status of Art. 73 in the traceability matrix.

    python3 incident_demo.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import oscal_exporter
from scenarios import build_incident_scenario
from simulator import ComplianceOracle

from paths import EXPERIMENTS_DIR, run_dir  # noqa: E402
OUT_DIR = run_dir("incident_run", create=True)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ledger_file = OUT_DIR / "ledger.json"

    oracle = ComplianceOracle(ledger_file=ledger_file)
    oracle.reset_ledger()
    for event in build_incident_scenario():
        oracle.process_mlops_event(event)

    ledger = json.loads(ledger_file.read_text(encoding="utf-8"))
    report = oracle.verify_chain()
    chain_ok = report.valid == report.total
    status = "INTACT" if chain_ok else "BROKEN"

    print(f"evidence events   : {len(ledger)}")
    print(f"decisions         : {dict(Counter(r['decision'] for r in ledger))}")
    print(f"Art. 73 covered   : "
          f"{sum('Art.73' in r['requirements_covered'] for r in ledger)}/{len(ledger)}")
    print(f"chain             : {report.valid}/{report.total} {status}")

    full = oscal_exporter.to_oscal_sar(ledger, chain_valid=chain_ok, redacted=False, signatures_verified=chain_ok)
    redacted = oscal_exporter.to_oscal_sar(ledger, chain_valid=chain_ok, redacted=True, signatures_verified=chain_ok)
    (OUT_DIR / "oscal_incident.json").write_text(json.dumps(full, indent=2))
    (OUT_DIR / "oscal_incident_redacted.json").write_text(json.dumps(redacted, indent=2))
    n_find = len(full["assessment-results"]["results"][0]["findings"])
    print(f"OSCAL             : oscal_incident.json + redacted ({n_find} findings)")
    print(f"artifacts in      : {OUT_DIR}")
    return 0 if chain_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
