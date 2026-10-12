"""Evidence model, schema version 2 (WP2 of the article plan).

Version 2 separates the digest of the event (payload_hash) from the digest of
the artefact file (artifact_hash), commits to where the artefact is kept
(off_chain_ref), records the inputs of the decision and the run it belongs
to, renames the normative field supports_requirements, records an audit query
as "recorded", and signs with the Compliance Policy Engine's own key. A
recorded decision can be re-executed from the record and the archived policy.
"""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from artifact_store import ArtifactStore, verify_ledger_artifacts  # noqa: E402
from canonical import SCHEMA_V1, SCHEMA_V2  # noqa: E402
from keys import load_or_create_key  # noqa: E402
from oscal_exporter import _control_id, to_oscal_sar  # noqa: E402
from reexecution import (  # noqa: E402
    MATCH,
    MISMATCH,
    PAYLOAD_MISMATCH,
    PAYLOAD_REQUIRED,
    POLICY_ALTERED,
    POLICY_MISSING,
    reexecute,
    reexecute_ledger,
)
from scenarios import build_incident_scenario, build_scenarios  # noqa: E402
from simulator import (  # noqa: E402
    ISSUER_ID_V2,
    ComplianceOracle,
    requirements_of,
)
from validate_oscal_schema import SCHEMA_PATH, UnicodeDraft7  # noqa: E402

POLICY = {
    "min_precision": 0.80,
    "max_demographic_parity_diff": 0.05,
    "require_human_approval_for_high_risk": True,
    "drift_alert_threshold": 0.15,
}

V2_FIELDS = {
    "schema_version", "run_id", "payload_hash", "artifact_hash",
    "off_chain_ref", "decision_inputs", "supports_requirements",
}


def _workdir() -> Path:
    d = Path(tempfile.gettempdir()) / f"v2_test_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "policies.json").write_text(json.dumps(POLICY), encoding="utf-8")
    return d


def _oracle(wd: Path, version: int = SCHEMA_V2, **kwargs) -> ComplianceOracle:
    oracle = ComplianceOracle(
        policy_file=wd / "policies.json", ledger_file=wd / "ledger.jsonl",
        schema_version=version, **kwargs,
    )
    oracle.reset_ledger()
    return oracle


def _archive(oracle: ComplianceOracle) -> Path:
    return oracle.policy_file.parent / "policies_archive"


def _event(**overrides) -> dict:
    event = {
        "scenario_id": "v2",
        "event_type": "model_validation",
        "artifact_id": "credit-scoring-v3",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {"precision": 0.91, "demographic_parity_diff": 0.02},
    }
    event.update(overrides)
    return event


# ----------------------------------------------------------------------
# The record
# ----------------------------------------------------------------------


def test_version_2_record_has_the_new_fields_and_the_engine_key():
    wd = _workdir()
    record = _oracle(wd).process_mlops_event(_event(run_id="run-1"))
    assert V2_FIELDS <= set(record)
    assert "requirements_covered" not in record
    assert record["issuer_id"] == ISSUER_ID_V2
    assert record["run_id"] == "run-1"
    assert len(record["payload_hash"]) == 64
    assert record["artifact_hash"] is None and record["off_chain_ref"] is None
    assert record["decision_inputs"] == {
        "risk_level": "high", "human_approval": True, "approval": None}


def test_version_1_record_is_unchanged():
    wd = _workdir()
    record = _oracle(wd, SCHEMA_V1).process_mlops_event(_event(run_id="run-1"))
    # artifact_hash exists in both versions: the payload digest in version 1.
    assert not ((V2_FIELDS - {"artifact_hash"}) & set(record))
    assert "requirements_covered" in record and len(record["artifact_hash"]) == 64
    assert record["issuer_id"] == "compliance-oracle-v1"


def test_audit_query_is_recorded_not_verified():
    wd = _workdir()
    oracle = _oracle(wd)
    audit = next(e for e in build_scenarios() if e["event_type"] == "audit_query")
    assert oracle.process_mlops_event(audit)["decision"] == "recorded"


def test_run_id_groups_the_events_of_a_run():
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(3):
        oracle.process_mlops_event(_event(run_id="run-A", artifact_id=f"a{i}"))
    oracle.process_mlops_event(_event(run_id="run-B"))
    oracle.process_mlops_event(_event())
    assert len(oracle.query_by_run("run-A")) == 3
    assert len(oracle.query_by_run("run-B")) == 1


def test_bias_metric_supports_art_10_2_f_under_version_2():
    wd = _workdir()
    v2 = _oracle(wd).process_mlops_event(_event())
    assert "Art.10(2)(f)" in requirements_of(v2) and "Art.10(3)" not in requirements_of(v2)
    v1 = _oracle(_workdir(), SCHEMA_V1).process_mlops_event(_event())
    assert "Art.10(3)" in requirements_of(v1)


# ----------------------------------------------------------------------
# Artefacts off the ledger
# ----------------------------------------------------------------------


def test_artefact_digest_and_reference_are_committed_and_recomputable():
    wd = _workdir()
    store = ArtifactStore(wd / "store")
    dataset = wd / "train.csv"
    dataset.write_bytes(b"age,amount,label\n23,1000,1\n41,2500,0\n")
    stored = store.put(dataset)
    oracle = _oracle(wd)
    record = oracle.process_mlops_event(_event(
        event_type="data_ingested", artifact_type="dataset", pipeline_stage="ingestion",
        artifact_sha256=stored.digest, off_chain_ref=stored.ref,
    ))
    assert record["artifact_hash"] == stored.digest
    assert record["off_chain_ref"] == stored.ref
    assert record["payload_hash"] != record["artifact_hash"]
    assert {"Art.10(3)", "Art.11"} <= set(requirements_of(record))
    assert [r["status"] for r in verify_ledger_artifacts(oracle._read_ledger(), store)] == ["ok"]


def test_altered_or_missing_artefact_is_reported():
    wd = _workdir()
    store = ArtifactStore(wd / "store")
    stored = store.put_bytes(b"model weights v3")
    oracle = _oracle(wd)
    oracle.process_mlops_event(_event(artifact_sha256=stored.digest, off_chain_ref=stored.ref))
    stored.path.chmod(0o644)
    stored.path.write_bytes(b"model weights v3, retrained")
    assert verify_ledger_artifacts(oracle._read_ledger(), store)[0]["status"] == "content-mismatch"
    stored.path.unlink()
    assert verify_ledger_artifacts(oracle._read_ledger(), store)[0]["status"] == "missing"


def test_storing_the_same_bytes_twice_is_idempotent():
    store = ArtifactStore(_workdir() / "store")
    a = store.put_bytes(b"same")
    b = store.put_bytes(b"same")
    assert a == b and len(list((store.root / "sha256").iterdir())) == 1


@pytest.mark.parametrize(
    "patch",
    [
        {"run_id": ["run"]},
        {"run_id": "  "},
        {"artifact_sha256": "ABC"},
        {"artifact_sha256": "A" * 64},  # upper case is not the canonical form
        {"off_chain_ref": "store/sha256/" + "0" * 64},  # reference without digest
        {"artifact_sha256": "1" * 64, "off_chain_ref": "store/sha256/" + "2" * 64},
        {"artifact_sha256": "1" * 64, "off_chain_ref": 7},
    ],
)
def test_malformed_version_2_fields_are_rejected_and_recorded(patch):
    wd = _workdir()
    oracle = _oracle(wd)
    record = oracle.process_mlops_event(_event(**patch))
    assert record["decision"] == "rejected" and record["rule_id"] == "input.malformed"
    assert record["artifact_hash"] is None and record["off_chain_ref"] is None
    assert record["run_id"] is None
    assert requirements_of(record) == ["Art.12"]
    assert oracle.verify_chain().is_valid


def test_reference_outside_the_store_is_accepted_with_its_digest():
    wd = _workdir()
    record = _oracle(wd).process_mlops_event(
        _event(artifact_sha256="3" * 64, off_chain_ref="s3://models/credit-v3.joblib")
    )
    assert record["decision"] == "approved"
    assert record["off_chain_ref"] == "s3://models/credit-v3.joblib"


# ----------------------------------------------------------------------
# Re-execution
# ----------------------------------------------------------------------


def _events_for_reexecution(store: ArtifactStore) -> list:
    stored = store.put_bytes(b"dataset bytes")
    return build_scenarios() + build_incident_scenario() + [
        _event(run_id="r1", artifact_type="dataset", artifact_sha256=stored.digest,
               off_chain_ref=stored.ref),
        _event(run_id="r1", human_approval=None, risk_level="low"),
        _event(scenario_id="", metrics={}),
        _event(risk_level="high", human_approval=False),
    ]


def test_every_valid_record_reexecutes_to_the_same_decision():
    wd = _workdir()
    oracle = _oracle(wd)
    for event in _events_for_reexecution(ArtifactStore(wd / "store")):
        oracle.process_mlops_event(event)
    summary = reexecute_ledger(oracle._read_ledger(), _archive(oracle))
    assert summary["counts"] == {MATCH: summary["total"]}, [
        (r.evidence_id, r.status, r.differences) for r in summary["results"]
    ]
    decisions = {r["decision"] for r in oracle._read_ledger()}
    assert {"approved", "rejected", "escalated", "recorded"} <= decisions


def test_malformed_record_needs_its_payload_and_then_reexecutes():
    wd = _workdir()
    oracle = _oracle(wd)
    payload = _event(metrics={"precision": "high"})
    record = oracle.process_mlops_event(payload)
    assert reexecute(record, _archive(oracle)).status == PAYLOAD_REQUIRED
    assert reexecute(record, _archive(oracle), payload=payload).status == MATCH
    other = _event(metrics={"precision": "low"})
    assert reexecute(record, _archive(oracle), payload=other).status == PAYLOAD_MISMATCH


def test_version_1_record_reexecutes_only_with_its_payload():
    wd = _workdir()
    oracle = _oracle(wd, SCHEMA_V1)
    payload = _event()
    record = oracle.process_mlops_event(payload)
    assert reexecute(record, _archive(oracle)).status == PAYLOAD_REQUIRED
    assert reexecute(record, _archive(oracle), payload=payload).status == MATCH


def test_a_changed_decision_does_not_reexecute():
    wd = _workdir()
    oracle = _oracle(wd)
    record = oracle.process_mlops_event(_event(metrics={"precision": 0.5,
                                                        "demographic_parity_diff": 0.01}))
    forged = copy.deepcopy(record)
    forged["decision"], forged["rule_id"] = "approved", "policy.all_checks_passed"
    result = reexecute(forged, _archive(oracle))
    assert result.status == MISMATCH
    assert set(result.differences) == {"decision", "rule_id"}


def test_an_altered_or_missing_archived_policy_is_reported():
    wd = _workdir()
    oracle = _oracle(wd)
    record = oracle.process_mlops_event(_event())
    archived = _archive(oracle) / f"{record['policy_id']}.json"
    policy = json.loads(archived.read_text())
    policy["min_precision"] = 0.95
    archived.write_text(json.dumps(policy))
    assert reexecute(record, _archive(oracle)).status == POLICY_ALTERED
    archived.unlink()
    assert reexecute(record, _archive(oracle)).status == POLICY_MISSING


# ----------------------------------------------------------------------
# Keys, OSCAL
# ----------------------------------------------------------------------


def test_record_of_an_untrusted_issuer_is_reported_as_such():
    wd = _workdir()
    other = load_or_create_key("another-issuer", keys_dir=wd / "keys")
    oracle = _oracle(wd, issuer_key=other)
    oracle.process_mlops_event(_event())
    verifier = _oracle(_workdir())
    report = verifier.verify_chain(oracle._read_ledger())
    assert not report.is_valid and "unknown issuer key" in report.issues[0]
    verifier.trust(other)
    assert verifier.verify_chain(oracle._read_ledger()).is_valid


def test_article_points_map_to_distinct_control_ids():
    assert _control_id("Art.12") == "aia-12"
    assert _control_id("Art.10(3)") == "aia-10-3"
    assert _control_id("Art.10(2)(f)") == "aia-10-2-f"


@pytest.mark.parametrize("redacted", [False, True])
def test_version_2_ledger_exports_valid_oscal(redacted):
    wd = _workdir()
    oracle = _oracle(wd)
    for event in _events_for_reexecution(ArtifactStore(wd / "store")):
        oracle.process_mlops_event(event)
    document = to_oscal_sar(oracle._read_ledger(), redacted=redacted)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(UnicodeDraft7(schema).iter_errors(document))
    assert not errors, [e.message for e in errors[:3]]
    text = json.dumps(document)
    assert "aia-10-2-f" in text and "aia-11" in text
