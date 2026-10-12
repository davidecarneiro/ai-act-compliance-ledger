"""Signed human approval (WP6 of the article plan).

Acceptance: an approval that is forged, signed with an unauthorised key or
issued for another artefact is rejected and recorded, each with its own test.
A valid approval is recorded whole and re-verifies from the record and the
archived policy.
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

from approvals import APPROVAL_DENIED, APPROVAL_INVALID, sign_approval  # noqa: E402
from canonical import SCHEMA_V1, SCHEMA_V2  # noqa: E402
from keys import load_or_create_key, public_key_hex  # noqa: E402
from reexecution import MATCH, MISMATCH, reexecute  # noqa: E402
from simulator import ComplianceOracle, InvalidPolicyError, requirements_of  # noqa: E402

ARTEFACT = "a" * 64
OTHER_ARTEFACT = "b" * 64


@pytest.fixture()
def setting():
    wd = Path(tempfile.gettempdir()) / f"approval_test_{uuid.uuid4().hex[:8]}"
    wd.mkdir(parents=True, exist_ok=True)
    alice = load_or_create_key("approver-alice", keys_dir=wd / "keys")
    mallory = load_or_create_key("approver-mallory", keys_dir=wd / "keys")
    policy = {
        "min_precision": 0.80,
        "max_demographic_parity_diff": 0.05,
        "require_human_approval_for_high_risk": True,
        "drift_alert_threshold": 0.15,
        "authorised_approvers": {"approver-alice": public_key_hex(alice)},
        "signed_approval_required_for": ["deployment_request"],
    }
    (wd / "policies.json").write_text(json.dumps(policy), encoding="utf-8")

    def oracle(version=SCHEMA_V2):
        o = ComplianceOracle(policy_file=wd / "policies.json",
                             ledger_file=wd / f"ledger-v{version}.jsonl",
                             schema_version=version)
        o.reset_ledger()
        return o

    return {"wd": wd, "alice": alice, "mallory": mallory, "oracle": oracle}


def _deployment(approval=None, **overrides) -> dict:
    event = {
        "scenario_id": "deploy",
        "event_type": "deployment_request",
        "artifact_id": "credit-scoring-v3",
        "artifact_type": "model",
        "pipeline_stage": "deployment",
        "risk_level": "high",
        "run_id": "run-0001",
        "artifact_sha256": ARTEFACT,
        "metrics": {"precision": 0.9, "demographic_parity_diff": 0.02},
    }
    if approval is not None:
        event["approval"] = approval
    event.update(overrides)
    return event


def _archive(oracle) -> Path:
    return oracle.policy_file.parent / "policies_archive"


def test_valid_signed_approval_allows_deployment_and_is_recorded(setting):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["alice"], "approver-alice", ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(approval))
    assert record["decision"] == "approved", record["reason"]
    assert record["decision_inputs"]["approval"] == approval
    assert "Art.14" in requirements_of(record)
    assert reexecute(record, _archive(oracle)).status == MATCH


def test_missing_signed_approval_is_rejected_even_with_the_boolean(setting):
    oracle = setting["oracle"]()
    record = oracle.process_mlops_event(_deployment(human_approval=True))
    assert record["decision"] == "rejected"
    assert record["rule_id"] == "oversight.approval_missing"


def test_forged_approval_is_rejected_and_recorded(setting):
    # Mallory signs but claims to be Alice: the signature does not verify
    # against Alice's key in the policy.
    oracle = setting["oracle"]()
    forged = sign_approval(setting["mallory"], "approver-alice", ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(forged))
    assert (record["decision"], record["rule_id"]) == ("rejected", APPROVAL_INVALID)
    assert "does not verify" in record["reason"]
    assert oracle.verify_chain().is_valid


def test_approval_by_an_unauthorised_key_is_rejected(setting):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["mallory"], "approver-mallory", ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(approval))
    assert (record["decision"], record["rule_id"]) == ("rejected", APPROVAL_INVALID)
    assert "not authorised" in record["reason"]


def test_approval_for_another_artefact_is_rejected(setting):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["alice"], "approver-alice", OTHER_ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(approval))
    assert (record["decision"], record["rule_id"]) == ("rejected", APPROVAL_INVALID)
    assert "another artefact" in record["reason"]


def test_approval_for_another_run_is_rejected(setting):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["alice"], "approver-alice", ARTEFACT, "run-0002")
    record = oracle.process_mlops_event(_deployment(approval))
    assert (record["decision"], record["rule_id"]) == ("rejected", APPROVAL_INVALID)
    assert "another run" in record["reason"]


def test_statement_altered_after_signing_is_rejected(setting):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["alice"], "approver-alice", OTHER_ARTEFACT, "run-0001")
    approval["statement"]["artifact_sha256"] = ARTEFACT  # retargeted after signing
    record = oracle.process_mlops_event(_deployment(approval))
    assert (record["decision"], record["rule_id"]) == ("rejected", APPROVAL_INVALID)
    assert "does not verify" in record["reason"]


def test_signed_denial_is_recorded_as_a_denial(setting):
    oracle = setting["oracle"]()
    denial = sign_approval(setting["alice"], "approver-alice", ARTEFACT, "run-0001",
                           decision="deny")
    record = oracle.process_mlops_event(_deployment(denial))
    assert (record["decision"], record["rule_id"]) == ("rejected", APPROVAL_DENIED)


@pytest.mark.parametrize(
    "mangle",
    [
        lambda a: "approved",
        lambda a: {**a, "extra": 1},
        lambda a: {**a, "statement": {**a["statement"], "type": "other"}},
        lambda a: {**a, "statement": {**a["statement"], "decision": "maybe"}},
        lambda a: {**a, "signature": "not base64!"},
        lambda a: {**a, "signature": "AAAA"},
    ],
)
def test_malformed_approval_makes_the_event_malformed(setting, mangle):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["alice"], "approver-alice", ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(mangle(approval)))
    assert (record["decision"], record["rule_id"]) == ("rejected", "input.malformed")
    assert record["decision_inputs"]["approval"] is None
    assert oracle.verify_chain().is_valid


def test_recorded_approval_cannot_be_swapped_without_detection(setting):
    oracle = setting["oracle"]()
    approval = sign_approval(setting["alice"], "approver-alice", ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(approval))
    # Remove the approval from a copy and keep the decision: re-execution
    # disagrees, and the altered record no longer matches its signature.
    tampered = copy.deepcopy(record)
    tampered["decision_inputs"]["approval"] = None
    assert reexecute(tampered, _archive(oracle)).status == MISMATCH
    assert not oracle.verify_chain([tampered]).is_valid


def test_events_not_requiring_signed_approval_keep_the_boolean_rule(setting):
    oracle = setting["oracle"]()
    validation = _deployment(event_type="model_validation", pipeline_stage="validation",
                             human_approval=True)
    assert oracle.process_mlops_event(validation)["decision"] == "approved"


def test_version_1_ignores_the_approval_field(setting):
    oracle = setting["oracle"](SCHEMA_V1)
    approval = sign_approval(setting["mallory"], "approver-mallory", ARTEFACT, "run-0001")
    record = oracle.process_mlops_event(_deployment(approval, human_approval=True))
    assert record["decision"] == "approved"


@pytest.mark.parametrize(
    "bad",
    [
        {"authorised_approvers": ["approver-alice"]},
        {"authorised_approvers": {"approver-alice": "not-hex"}},
        {"signed_approval_required_for": "deployment_request"},
    ],
)
def test_malformed_approval_policy_fails_closed(setting, bad):
    policy = json.loads((setting["wd"] / "policies.json").read_text())
    policy.update(bad)
    path = setting["wd"] / "bad_policy.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(InvalidPolicyError):
        ComplianceOracle(policy_file=path, ledger_file=setting["wd"] / "x.jsonl")


def test_approval_outcomes_export_to_valid_oscal(setting):
    from oscal_exporter import to_oscal_sar
    from validate_oscal_schema import SCHEMA_PATH, UnicodeDraft7

    oracle = setting["oracle"]()
    alice, mallory = setting["alice"], setting["mallory"]
    oracle.process_mlops_event(_deployment(
        sign_approval(alice, "approver-alice", ARTEFACT, "run-0001")))
    oracle.process_mlops_event(_deployment(
        sign_approval(mallory, "approver-alice", ARTEFACT, "run-0001")))
    oracle.process_mlops_event(_deployment(
        sign_approval(alice, "approver-alice", ARTEFACT, "run-0001", decision="deny")))
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    for redacted in (False, True):
        document = to_oscal_sar(oracle._read_ledger(), redacted=redacted)
        assert not list(UnicodeDraft7(schema).iter_errors(document))
        text = json.dumps(document)
        assert "obj-human-approval-verified" in text and "obj-human-approval-granted" in text
