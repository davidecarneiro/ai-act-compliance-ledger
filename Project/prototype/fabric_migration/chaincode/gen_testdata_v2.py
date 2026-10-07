#!/usr/bin/env python3
"""Generate the schema version 2 (RFC 8785) fixtures for the Go tests.

    python3 gen_testdata_v2.py          # from this folder, simulator venv active

Writes three files next to this script:

* testdata_ledger_v2.json: a version 2 chain issued by the Python Compliance
  Policy Engine with the demonstration key: the six canonical scenarios plus
  events whose text and numbers exercise the canonical form (non-ASCII, HTML
  characters, an astral-plane character, 0.0 next to 0, a malformed event).
* testdata_v2_extra_fields.json: a two-record version 2 chain whose bodies
  carry members the Go struct does not declare (run_id, decision_inputs). It
  checks that version 2 hashes and stores what was signed, whatever the struct
  knows about.
* testdata_jcs_vectors.json: JSON texts and the bytes Python's RFC 8785
  implementation produces for them, for the Go implementation to reproduce.

The ledgers are fixtures: regenerating them changes evidence_id and timestamp
values, and the Go tests read whatever is committed.
"""
from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parents[1] / "compliance_ledger_sim"
sys.path.insert(0, str(SIM))

from canonical import SCHEMA_V2, canonical_v2  # noqa: E402
from keys import load_or_create_key  # noqa: E402
from scenarios import build_scenarios  # noqa: E402
from simulator import GENESIS_HASH, ComplianceOracle, sha256_hex  # noqa: E402


def tricky_events() -> list[dict]:
    base = {
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
    }
    return [
        {**base, "scenario_id": "v2-texto-não-ASCII-çã€",
         "event_type": "approved_model", "artifact_id": "modelo-crédito-v2",
         "metrics": {"precision": 0.91, "demographic_parity_diff": 0.0}},
        {**base, "scenario_id": "v2-html-<a&b>",
         "event_type": "approved_model", "artifact_id": "m<1>&\"q\"",
         "metrics": {"precision": 1.0, "demographic_parity_diff": 0}},
        {**base, "scenario_id": "v2-astral-\U0001F6A8",
         "event_type": "approved_model", "artifact_id": "m- -\x7f",
         "metrics": {"precision": 0.85, "demographic_parity_diff": 1e-7,
                     "drift_score": 0.30000000000000004}},
        {**base, "scenario_id": "v2-malformed",
         "event_type": "approved_model", "artifact_id": "m-bad",
         # An unbounded metric beyond 2**53 - 1: outside the JCS number domain,
         # so the event is rejected and recorded, and its payload is hashed
         # through the envelope instead of raising.
         "metrics": {"precision": 0.9, "demographic_parity_diff": 0.01,
                     "row_count": 2**60}},
    ]


def issue_ledger() -> list[dict]:
    with tempfile.TemporaryDirectory() as d:
        oracle = ComplianceOracle(
            ledger_file=Path(d) / "ledger.json", schema_version=SCHEMA_V2
        )
        oracle.reset_ledger()
        for event in build_scenarios() + tricky_events():
            oracle.process_mlops_event(event)
        ledger = json.loads((Path(d) / "ledger.json").read_text(encoding="utf-8"))
        report = oracle.verify_chain()
        assert report.valid == report.total == len(ledger), report.issues
        return ledger


def resign_with_extra_fields(ledger: list[dict]) -> list[dict]:
    """Re-issue the first two records with members the Go struct lacks."""
    key = load_or_create_key()
    out, parent = [], GENESIS_HASH
    for i, record in enumerate(ledger[:2]):
        body = {k: v for k, v in record.items()
                if k not in {"record_hash", "issuer_signature", "chain_hash"}}
        body["parent_hash"] = parent
        body["run_id"] = "run-0001"
        body["decision_inputs"] = {"risk_level": "high", "human_approval": i == 0,
                                   "note": "não declarado no struct Go"}
        raw = canonical_v2(body)
        record_hash = sha256_hex(raw)
        chain_hash = sha256_hex((parent + record_hash).encode("utf-8"))
        out.append({**body, "record_hash": record_hash,
                    "issuer_signature": base64.b64encode(key.sign(raw)).decode("ascii"),
                    "chain_hash": chain_hash})
        parent = chain_hash
    return out


def jcs_vectors() -> list[dict]:
    values = {
        "keys_utf16_order": {"\U0001F6A8": 1, "דּ": 2, "€": 3, "a": 4, "B": 5, "": 6},
        "numbers": [0.0, -0.0, 1.0, 1e21, 1e-7, 0.1 + 0.2, 5e-324,
                    1.7976931348623157e308, 2**53 - 1, -(2**53 - 1), 100, 1e20, 123.456],
        "strings": ["<a&b>", "\x7f", "  ", "\x01\x1f", "\"\\/",
                    "\U0001F6A8", "çã€", "\t\n\r\b\f"],
        "nested": {"z": [{"b": None, "a": True}, [], {}], "a": {"y": False, "x": "1"}},
    }
    vectors = []
    for label, value in values.items():
        # Python's own JSON text, with non-ASCII escaped, is the input Go reads:
        # the canonical output must not depend on how the input was written.
        text = json.dumps(value, ensure_ascii=True, indent=1)
        expected = canonical_v2(value)
        vectors.append({
            "label": label,
            "input": text,
            "expected_b64": base64.b64encode(expected).decode("ascii"),
            "sha256": sha256_hex(expected),
        })
    return vectors


def main() -> int:
    ledger = issue_ledger()
    (HERE / "testdata_ledger_v2.json").write_text(
        json.dumps(ledger, indent=2), encoding="utf-8")
    (HERE / "testdata_v2_extra_fields.json").write_text(
        json.dumps(resign_with_extra_fields(ledger), indent=2), encoding="utf-8")
    (HERE / "testdata_jcs_vectors.json").write_text(
        json.dumps(jcs_vectors(), indent=2), encoding="utf-8")
    print(f"testdata_ledger_v2.json: {len(ledger)} records")
    print("testdata_v2_extra_fields.json: 2 records")
    print("testdata_jcs_vectors.json: written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
