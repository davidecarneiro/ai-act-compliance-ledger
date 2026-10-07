"""Schema versions of the evidence record (WP0 of the article plan).

Version 1 is the canonical form the dissertation's records use; version 2 is
RFC 8785 (JCS). New records carry ``schema_version: 2``; the verifier reads
the version from each record, so published version 1 ledgers keep verifying
and a ledger may mix both.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
import rfc8785

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical import (  # noqa: E402
    SCHEMA_V1,
    SCHEMA_V2,
    UnsupportedSchemaVersion,
    canonical_v1,
    canonical_v2,
    record_body,
    record_body_bytes,
    schema_version_of,
)
from oscal_exporter import to_oscal_sar, verify_chain_structure  # noqa: E402
from scenarios import build_scenarios  # noqa: E402
from simulator import (  # noqa: E402
    PUBLISHED_LEDGER_FILE,
    LEDGER_FILE,
    ComplianceOracle,
    InvalidPolicyError,
    policy_identity,
    sha256_hex,
)

POLICY = {
    "min_precision": 0.80,
    "max_demographic_parity_diff": 0.05,
    "require_human_approval_for_high_risk": True,
    "drift_alert_threshold": 0.15,
}


def _oracle(schema_version: int, policy: dict | None = None,
            ledger_file: Path | None = None) -> ComplianceOracle:
    workdir = Path(tempfile.gettempdir()) / f"schema_test_{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    policy_file = workdir / "policies.json"
    policy_file.write_text(json.dumps(policy or POLICY), encoding="utf-8")
    oracle = ComplianceOracle(
        policy_file=policy_file,
        ledger_file=ledger_file or workdir / "ledger.json",
        schema_version=schema_version,
    )
    if ledger_file is None:
        oracle.reset_ledger()
    return oracle


def _event(**overrides) -> dict:
    event = {
        "scenario_id": "schema",
        "event_type": "approved_model",
        "artifact_id": "modelo-crédito-v2",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {"precision": 0.91, "demographic_parity_diff": 0.0},
    }
    event.update(overrides)
    return event


# ----------------------------------------------------------------------
# Issuance
# ----------------------------------------------------------------------


def test_version_1_records_are_the_dissertation_form():
    oracle = _oracle(SCHEMA_V1)
    record = oracle.process_mlops_event(_event())
    assert "schema_version" not in record
    assert record["record_hash"] == sha256_hex(canonical_v1(record_body(record)))
    assert b"\\u00e9" in canonical_v1(record_body(record))  # ensure_ascii


def test_version_2_records_are_rfc8785():
    oracle = _oracle(SCHEMA_V2)
    record = oracle.process_mlops_event(_event())
    assert record["schema_version"] == 2
    raw = canonical_v2(record_body(record))
    assert record["record_hash"] == sha256_hex(raw)
    assert raw == rfc8785.dumps(record_body(record))
    assert "crédito".encode("utf-8") in raw  # UTF-8, not \u escapes
    assert oracle.verify_chain().is_valid


def test_an_explicit_unsupported_issuance_version_is_refused():
    for bad in (0, 3, True, "2"):
        with pytest.raises(UnsupportedSchemaVersion):
            _oracle(bad)


def test_zero_point_zero_and_zero_share_one_version_2_form():
    # The 0.0 / 0 defect between Python and Go (Table T11) cannot arise.
    assert canonical_v2({"m": 0.0}) == canonical_v2({"m": 0}) == b'{"m":0}'
    assert canonical_v1({"m": 0.0}) != canonical_v1({"m": 0})


def test_version_2_orders_keys_by_utf16_code_units():
    # U+1F6A8 sorts before U+FB33 in UTF-16 (surrogate D83D < FB33), after it
    # by code point. Version 1 sorts by code point.
    value = {"דּ": 1, "\U0001F6A8": 2}
    assert canonical_v2(value).index("\U0001F6A8".encode()) < canonical_v2(value).index(
        "דּ".encode()
    )


# ----------------------------------------------------------------------
# Verification dispatch
# ----------------------------------------------------------------------


def test_published_version_1_ledger_still_verifies():
    demo_key = ROOT / "keys" / "compliance-oracle-v1.ed25519.pub.pem"
    if not (PUBLISHED_LEDGER_FILE.exists() and demo_key.exists()):
        # The container build copies the code, not the published evidence.
        pytest.skip("published ledger and demonstration key not in this build")
    ledger = json.loads(PUBLISHED_LEDGER_FILE.read_text(encoding="utf-8"))
    assert all(schema_version_of(r) == SCHEMA_V1 for r in ledger)
    report = ComplianceOracle(ledger_file=PUBLISHED_LEDGER_FILE).verify_chain(ledger)
    assert report.valid == report.total == 6


def test_a_ledger_may_mix_versions():
    v1 = _oracle(SCHEMA_V1)
    for event in build_scenarios()[:3]:
        v1.process_mlops_event(event)
    v2 = _oracle(SCHEMA_V2, ledger_file=v1.ledger_file)
    for event in build_scenarios()[3:]:
        v2.process_mlops_event(event)
    ledger = json.loads(v1.ledger_file.read_text(encoding="utf-8"))
    assert [schema_version_of(r) for r in ledger] == [1, 1, 1, 2, 2, 2]
    assert v2.verify_chain().is_valid
    assert verify_chain_structure(ledger)


@pytest.mark.parametrize(
    "mutation,expected_issue",
    [
        (lambda r: r.pop("schema_version"), "record_hash mismatch"),
        (lambda r: r.update(schema_version="2"), "unsupported schema_version"),
        (lambda r: r.update(schema_version=1), "unsupported schema_version"),
        (lambda r: r.update(schema_version=3), "unsupported schema_version"),
        (lambda r: r.update(schema_version=True), "unsupported schema_version"),
    ],
)
def test_tampering_with_the_version_is_detected(mutation, expected_issue):
    oracle = _oracle(SCHEMA_V2)
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(ledger)
    mutation(tampered[2])
    report = oracle.verify_chain(tampered)
    assert not report.is_valid
    assert report.first_invalid_index == 2
    assert expected_issue in report.issues[0]
    assert not verify_chain_structure(tampered)


def test_record_body_bytes_refuses_unknown_versions():
    with pytest.raises(UnsupportedSchemaVersion):
        record_body_bytes({"schema_version": 9, "a": 1})


# ----------------------------------------------------------------------
# The JCS domain: malformed input is recorded, never an exception
# ----------------------------------------------------------------------


def test_metric_beyond_the_jcs_integer_domain_is_rejected_and_recorded():
    oracle = _oracle(SCHEMA_V2)
    event = _event(metrics={"precision": 0.9, "demographic_parity_diff": 0.01,
                            "row_count": 2**53})
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected"
    assert record["rule_id"] == "input.malformed"
    assert "RFC 8785" in record["reason"]
    assert record["metrics"] is None
    assert oracle.verify_chain().is_valid


def test_largest_safe_integer_is_accepted():
    oracle = _oracle(SCHEMA_V2)
    event = _event(metrics={"precision": 0.9, "demographic_parity_diff": 0.01,
                            "row_count": 2**53 - 1})
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "approved"
    assert record["metrics"]["row_count"] == 2**53 - 1


@pytest.mark.parametrize(
    "extra",
    [
        {"note": float("nan")},
        {"note": float("inf")},
        {"note": -(2**70)},
        {"nested": {"a\ud800b": 1}},
        {"nested": {1: "non-string key"}},
    ],
)
def test_payload_outside_the_jcs_domain_still_hashes(extra):
    oracle = _oracle(SCHEMA_V2)
    record = oracle.process_mlops_event(_event(**extra))
    assert len(record["artifact_hash"]) == 64
    assert oracle.verify_chain().is_valid


def test_out_of_domain_payloads_hash_apart_from_lookalikes():
    oracle = _oracle(SCHEMA_V2)
    a = oracle.process_mlops_event(_event(note=float("nan")))
    b = oracle.process_mlops_event(_event(note="nan"))
    c = oracle.process_mlops_event(_event(note={"__unrepresentable__": ["float", "nan"]}))
    assert len({a["artifact_hash"], b["artifact_hash"], c["artifact_hash"]}) == 3


# ----------------------------------------------------------------------
# Policies, OSCAL and output paths
# ----------------------------------------------------------------------


def test_shipped_policy_keeps_its_identifier_under_version_2():
    shipped = json.loads((ROOT / "configs" / "policies.json").read_text())
    assert policy_identity(shipped, SCHEMA_V1) == policy_identity(shipped, SCHEMA_V2)
    assert policy_identity(shipped, SCHEMA_V2)[0] == "pol-c3d1fc49f36e"


def test_policy_without_a_jcs_form_fails_closed():
    with pytest.raises(InvalidPolicyError):
        _oracle(SCHEMA_V2, policy={**POLICY, "comment": 2**60})


def _chain_valid_prop(doc: dict) -> str:
    entries = doc["assessment-results"]["results"][0]["assessment-log"]["entries"]
    for prop in entries[0]["props"]:
        if prop["name"] == "chain_valid":
            return prop["value"]
    raise AssertionError("chain_valid property not present in the assessment log")


def test_oscal_export_of_a_version_2_ledger_verifies_its_chain():
    oracle = _oracle(SCHEMA_V2)
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    assert _chain_valid_prop(to_oscal_sar(ledger)) == "true"
    tampered = copy.deepcopy(ledger)
    tampered[3]["artifact_id"] = "another-model"
    assert _chain_valid_prop(to_oscal_sar(tampered)) == "false"


def test_new_runs_do_not_write_over_published_evidence():
    assert LEDGER_FILE != PUBLISHED_LEDGER_FILE
    env = {k: v for k, v in os.environ.items()
           if k not in {"EXPERIMENTS_DIR", "PUBLISHED_DIR"}}
    out = subprocess.run(
        [sys.executable, "-c",
         "import paths; print(paths.EXPERIMENTS_DIR == paths.PUBLISHED_DIR / 'article')"],
        cwd=ROOT, env=env, capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "True"


def test_a_mistyped_issuance_version_is_refused_at_import():
    env = dict(os.environ, EVIDENCE_SCHEMA_VERSION="v2")
    out = subprocess.run(
        [sys.executable, "-c", "import canonical"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert out.returncode != 0
    assert "EVIDENCE_SCHEMA_VERSION" in out.stderr
