"""Test suite for the Compliance Oracle prototype.

Covers the three structural guarantees the architecture relies on:

* deterministic policy decisions per scenario (functional contract),
* hash chain integrity and tamper detection (M1),
* Ed25519 signature verification (M5).

The tests use the production code paths (no mocks for hashing or signing) so
that any regression in those primitives surfaces here. The ledger is written
to the standard ``ledger.json`` location and is reset at the start of each
test to keep cases independent.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import uuid
from base64 import b64encode
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenarios import build_incident_scenario, build_scenarios  # noqa: E402
from simulator import (  # noqa: E402
    GENESIS_HASH,
    ComplianceOracle,
    InvalidPolicyError,
    canonical_json,
    sha256_hex,
)


@pytest.fixture()
def oracle() -> ComplianceOracle:
    # Use /tmp instead of pytest's tmp_path because the development mount
    # has chmod restrictions that break tmp_path cleanup.
    workdir = Path(tempfile.gettempdir()) / f"oracle_test_{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    ledger_file = workdir / "ledger.json"
    policy_file = workdir / "policies.json"
    policy_file.write_text(
        json.dumps(
            {
                "min_precision": 0.80,
                "max_demographic_parity_diff": 0.05,
                "require_human_approval_for_high_risk": True,
                "drift_alert_threshold": 0.15,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    oracle = ComplianceOracle(policy_file=policy_file, ledger_file=ledger_file)
    oracle.reset_ledger()
    return oracle


# ----------------------------------------------------------------------
# Functional contract — the right decision for the right scenario
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario_id,expected",
    [
        ("approved_model", "approved"),
        ("low_precision_rejected", "rejected"),
        ("fairness_rejected", "rejected"),
        ("missing_human_approval_rejected", "rejected"),
        ("drift_detected", "escalated"),
        ("audit_query", "verified"),
    ],
)
def test_decision_per_scenario(oracle: ComplianceOracle, scenario_id, expected):
    event = next(s for s in build_scenarios() if s["scenario_id"] == scenario_id)
    record = oracle.process_mlops_event(event)
    assert record["decision"] == expected
    assert record["scenario_id"] == scenario_id


def test_full_run_chain_is_valid(oracle: ComplianceOracle):
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    report = oracle.verify_chain()
    assert report.is_valid is True
    assert report.total == 6
    assert report.invalid == 0
    assert report.first_invalid_index is None


def test_genesis_block_is_first_parent(oracle: ComplianceOracle):
    record = oracle.process_mlops_event(build_scenarios()[0])
    assert record["parent_hash"] == GENESIS_HASH


# ----------------------------------------------------------------------
# Hash chain — tamper detection (M1)
# ----------------------------------------------------------------------


def test_tampering_with_decision_is_detected(oracle: ComplianceOracle):
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    ledger[1]["decision"] = "approved"
    oracle.ledger_file.write_text(json.dumps(ledger), encoding="utf-8")

    report = oracle.verify_chain()
    assert report.is_valid is False
    assert report.first_invalid_index == 1
    issues_text = " | ".join(report.issues)
    assert "record_hash mismatch" in issues_text
    assert "invalid signature" in issues_text
    assert "chain_hash mismatch" in issues_text


def test_tampering_with_artifact_hash_is_detected(oracle: ComplianceOracle):
    oracle.process_mlops_event(build_scenarios()[0])
    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    ledger[0]["artifact_hash"] = "00" * 32
    oracle.ledger_file.write_text(json.dumps(ledger), encoding="utf-8")
    report = oracle.verify_chain()
    assert report.is_valid is False


def test_tampering_with_chain_hash_alone_is_detected(oracle: ComplianceOracle):
    """Forging chain_hash without the private key still fails signature check."""

    oracle.process_mlops_event(build_scenarios()[0])
    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    ledger[0]["chain_hash"] = sha256_hex(b"forged")
    oracle.ledger_file.write_text(json.dumps(ledger), encoding="utf-8")
    report = oracle.verify_chain()
    assert report.is_valid is False
    assert "chain_hash mismatch" in " | ".join(report.issues)


# ----------------------------------------------------------------------
# Signature — Ed25519 (M5)
# ----------------------------------------------------------------------


def test_signature_is_present_and_valid(oracle: ComplianceOracle):
    record = oracle.process_mlops_event(build_scenarios()[0])
    assert record["sig_alg"] == "Ed25519"
    assert record["issuer_signature"]
    assert len(record["issuer_signature"]) > 80  # base64-encoded 64-byte sig


def test_swapped_signature_is_rejected(oracle: ComplianceOracle):
    """Replacing the signature with garbage must be detected."""

    oracle.process_mlops_event(build_scenarios()[0])
    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    ledger[0]["issuer_signature"] = b64encode(b"\x00" * 64).decode("ascii")
    oracle.ledger_file.write_text(json.dumps(ledger), encoding="utf-8")
    report = oracle.verify_chain()
    assert report.is_valid is False
    assert "invalid signature" in " | ".join(report.issues)


# ----------------------------------------------------------------------
# Querying — audit interface basics (M13 partial)
# ----------------------------------------------------------------------


def test_query_by_requirement_returns_matching_records(oracle: ComplianceOracle):
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    art15 = oracle.query_by_requirement("Art.15")
    art72 = oracle.query_by_requirement("Art.72")
    assert len(art15) >= 4  # all metric-bearing scenarios touch Art.15
    assert any(r["scenario_id"] == "drift_detected" for r in art72)


def test_query_by_scenario_returns_single_record(oracle: ComplianceOracle):
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    rows = oracle.query_by_scenario("fairness_rejected")
    assert len(rows) == 1
    assert rows[0]["decision"] == "rejected"


# ----------------------------------------------------------------------
# Determinism of canonical serialization (regression guard)
# ----------------------------------------------------------------------


def test_canonical_json_is_order_independent():
    a = canonical_json({"b": 1, "a": 2})
    b = canonical_json({"a": 2, "b": 1})
    assert a == b




def _valid_event():
    return copy.deepcopy(build_scenarios()[0])


def test_string_false_is_not_an_approval(oracle):
    """Verify string false is not an approval."""
    event = _valid_event()
    event["human_approval"] = "false"
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected"
    assert "human_approval must be a boolean" in record["reason"]


def test_event_without_a_risk_level_is_rejected(oracle):
    """An event that does not declare its risk level must not be approved."""
    event = _valid_event()
    event["human_approval"] = False
    event["risk_level"] = None
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected"
    assert "risk_level must be one of" in record["reason"]


def test_nan_metrics_are_rejected(oracle):
    """NaN compares false against every threshold, so it passed every check."""
    event = _valid_event()
    event["metrics"] = {
        "precision": float("nan"),
        "demographic_parity_diff": float("nan"),
        "drift_score": float("nan"),
    }
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected"
    assert "must be finite" in record["reason"]


def test_metrics_outside_their_domain_are_rejected(oracle):
    """A precision of 999 satisfies a minimum-precision threshold."""
    event = _valid_event()
    event["metrics"] = {
        "precision": 999,
        "demographic_parity_diff": -99,
        "drift_score": -99,
    }
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected"
    assert "must lie in [0,1]" in record["reason"]


def test_a_rejected_input_is_still_recorded_as_evidence(oracle):
    """Rejection is evidence too: it must be chained and verifiable."""
    event = _valid_event()
    event["human_approval"] = "false"
    oracle.process_mlops_event(event)
    report = oracle.verify_chain()
    assert report.valid == report.total


def test_an_unbounded_metric_is_allowed_when_it_is_finite(oracle):
    """A row count is a legitimate metric outside [0,1] and must pass.

    The MultiFlow bridge sends batch_rows alongside the bounded metrics; a
    blanket [0,1] rule would have rejected real industrial events.
    """
    event = _valid_event()
    event["metrics"] = dict(event["metrics"], batch_rows=1440)
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "approved"




@pytest.mark.parametrize(
    "label, patch",
    [
        ("null metrics", {"metrics": None}),
        ("unhashable risk level", {"risk_level": ["high"]}),
        ("integer beyond float range", {"metrics": {"precision": 10**400}}),
        ("metrics as a list", {"metrics": [1, 2, 3]}),
        ("missing artefact identity", {"artifact_id": None}),
    ],
)
def test_every_malformed_event_is_rejected_and_recorded(oracle, label, patch):
    event = _valid_event()
    event.update(patch)
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected", label
    assert record["reason"].startswith("invalid input: "), label
    assert len(oracle._read_ledger()) == 1, label


def test_a_rejected_event_claims_no_coverage_it_did_not_earn(oracle):
    """Coverage is derived from field shapes, so a malformed event earns none."""
    event = _valid_event()
    event["metrics"] = None
    record = oracle.process_mlops_event(event)
    assert record["requirements_covered"] == ["Art.12"]


def test_an_incident_is_classified_before_the_metric_rules(oracle):
    """A reportable incident stays reportable however bad the metrics are."""
    event = copy.deepcopy(build_incident_scenario()[0])
    event["metrics"] = dict(event.get("metrics") or {}, precision=0.01)
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "escalated"
    assert "serious incident" in record["reason"]


@pytest.mark.parametrize(
    "label, body",
    [
        ("NaN threshold", '{"min_precision": NaN}'),
        ("Infinity threshold", '{"drift_alert_threshold": Infinity}'),
        ("threshold as a string", '{"min_precision": "0.8"}'),
        ("threshold out of range", '{"max_demographic_parity_diff": 4.2}'),
        ("flag as a string", '{"require_human_approval_for_high_risk": "yes"}'),
    ],
)
def test_a_malformed_policy_fails_initialisation(label, body):
    """A threshold of NaN compares false against everything, silently
    disabling the rule it belongs to. An Oracle cannot decide under a policy
    it cannot trust, so it refuses to start rather than approve under it."""
    workdir = Path(tempfile.gettempdir()) / f"policy_test_{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    policy_file = workdir / "policies.json"
    policy_file.write_text(body)
    with pytest.raises(InvalidPolicyError):
        ComplianceOracle(
            policy_file=policy_file, ledger_file=workdir / "ledger.json"
        )


def test_the_initial_policy_is_archived_too(oracle):
    """A record names a policy version; that version must have a copy kept.

    The first run wrote the default policy file and returned before
    archiving, so a record could point at a version with nothing preserved.
    """
    archive = oracle.policy_file.parent / "policies_archive"
    assert archive.exists(), "no archive directory after initialisation"
    assert list(archive.glob("pol-*.json")), "policy version not archived"


def test_a_rejected_event_does_not_carry_its_bad_payload(oracle):
    """The rejection is recorded; the offending metrics are not.

    A NaN metric serialises to a token no standard JSON parser accepts, and
    free text in a metric has no business on a shared ledger. The reason
    names what was wrong, which is what an auditor needs.
    """
    event = _valid_event()
    event["metrics"] = {"precision": float("nan")}
    record = oracle.process_mlops_event(event)
    assert record["decision"] == "rejected"
    assert record["metrics"] is None
    assert "must be finite" in record["reason"]
    json.dumps(oracle._read_ledger(), allow_nan=False)


def test_an_approved_event_keeps_its_metrics(oracle):
    """Suppression applies to rejections, not to the evidence that matters."""
    record = oracle.process_mlops_event(_valid_event())
    assert record["decision"] == "approved"
    assert record["metrics"]["precision"] == 0.89
