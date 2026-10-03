"""Test pseudonym determinism, organisation separation, rotation and replay.

The integration test checks that a configured identifier is absent from
the serialised ledger. It does not prove general irreversibility or anonymity."""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pseudonymizer import Pseudonymizer  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402


def _fresh_dir() -> Path:
    p = Path(tempfile.gettempdir()) / f"pseudo_{uuid.uuid4().hex[:8]}"
    p.mkdir(parents=True, exist_ok=True)
    return p


@pytest.fixture()
def org_a() -> Pseudonymizer:
    return Pseudonymizer(org_id="org-A", keys_dir=_fresh_dir())


@pytest.fixture()
def org_b() -> Pseudonymizer:
    return Pseudonymizer(org_id="org-B", keys_dir=_fresh_dir())


def test_pseudonym_is_deterministic_within_org(org_a: Pseudonymizer):
    a1 = org_a.pseudonymize("subject-42")
    a2 = org_a.pseudonymize("subject-42")
    assert a1["pseudonym"] == a2["pseudonym"]


def test_pseudonyms_differ_across_orgs(
    org_a: Pseudonymizer, org_b: Pseudonymizer
):
    a = org_a.pseudonymize("subject-42")
    b = org_b.pseudonymize("subject-42")
    assert a["pseudonym"] != b["pseudonym"]


def test_pseudonyms_differ_across_key_versions(org_a: Pseudonymizer):
    before = org_a.pseudonymize("subject-42")
    org_a.rotate_key()
    after = org_a.pseudonymize("subject-42")
    assert before["pseudonym"] != after["pseudonym"]
    assert after["key_version"] == before["key_version"] + 1


def test_replay_with_old_key_version_works(org_a: Pseudonymizer):
    before = org_a.pseudonymize("subject-42")
    org_a.rotate_key()
    replayed = org_a.pseudonymize_with_version("subject-42", before["key_version"])
    assert replayed["pseudonym"] == before["pseudonym"]


def test_pseudonym_is_64_hex_chars(org_a: Pseudonymizer):
    p = org_a.pseudonymize("subject-42")
    assert len(p["pseudonym"]) == 64
    int(p["pseudonym"], 16)  # raises if not hex


def test_apply_to_event_replaces_sensitive_fields(org_a: Pseudonymizer):
    event = {
        "scenario_id": "approved_model",
        "subject_id": "subject-42",
        "metrics": {"precision": 0.9},
        "nested": {"user_id": "user-7"},
    }
    out = org_a.apply_to_event(event)
    assert isinstance(out["subject_id"], dict)
    assert out["subject_id"]["alg"] == "HMAC-SHA256"
    assert isinstance(out["nested"]["user_id"], dict)
    assert out["scenario_id"] == "approved_model"  # unchanged
    assert out["metrics"]["precision"] == 0.9  # unchanged


def test_apply_to_event_preserves_non_sensitive_payload(org_a: Pseudonymizer):
    event = {"scenario_id": "x", "metrics": {"a": 1}}
    out = org_a.apply_to_event(event)
    assert out == event


def test_oracle_with_pseudonymizer_records_pseudonyms_only():
    work = _fresh_dir()
    pseudo = Pseudonymizer(org_id="org-X", keys_dir=work)
    oracle = ComplianceOracle(
        ledger_file=work / "ledger.json",
        policy_file=work / "policies.json",
        pseudonymizer=pseudo,
    )
    oracle.reset_ledger()
    record = oracle.process_mlops_event(
        {
            "scenario_id": "approved_model",
            "event_type": "approved_model",
            "artifact_id": "model-v1",
            "artifact_type": "model",
            "pipeline_stage": "validation",
            "risk_level": "high",
            "metrics": {
                "precision": 0.95,
                "demographic_parity_diff": 0.02,
                "drift_score": 0.01,
            },
            "human_approval": True,
            "subject_id": "subject-42",
        }
    )
    # The record's artifact_hash commits to the pseudonymized payload, so
    # the plaintext "subject-42" is absent from the serialised ledger.
    import json

    ledger = json.loads(oracle.ledger_file.read_text(encoding="utf-8"))
    serialised = json.dumps(ledger)
    assert "subject-42" not in serialised
    # The chain remains valid end-to-end.
    report = oracle.verify_chain()
    assert report.is_valid
