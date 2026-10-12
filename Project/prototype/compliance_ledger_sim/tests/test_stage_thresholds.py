"""Metric thresholds by pipeline stage (policy field metric_threshold_stages).

The dissertation's policy applies the precision and fairness thresholds to
every event, so an event that carries no metrics (data ingestion, training)
is rejected on precision. A version 2 policy may name the stages at which the
thresholds apply; at those stages the metrics stay mandatory.
"""

from __future__ import annotations

import json
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canonical import SCHEMA_V1, SCHEMA_V2  # noqa: E402
from reexecution import MATCH, reexecute  # noqa: E402
from simulator import (  # noqa: E402
    METRIC_THRESHOLD_STAGES,
    ComplianceOracle,
    InvalidPolicyError,
    evaluate_event,
    policy_identity,
)

BASE_POLICY = {
    "min_precision": 0.75,
    "max_demographic_parity_diff": 0.10,
    "require_human_approval_for_high_risk": False,
    "drift_alert_threshold": 0.25,
}
STAGED = {**BASE_POLICY, METRIC_THRESHOLD_STAGES: ["validation", "deployment"]}


def _event(stage: str, event_type: str, metrics=None) -> dict:
    event = {
        "event_type": event_type,
        "artifact_id": "credit-model",
        "artifact_type": "model",
        "pipeline_stage": stage,
        "risk_level": "high",
        "run_id": "run-1",
    }
    if metrics is not None:
        event["metrics"] = metrics
    return event


GOOD = {"precision": 0.80, "demographic_parity_diff": 0.05}


@pytest.mark.parametrize(
    "stage,event_type",
    [("data_preparation", "data_ingested"), ("training", "model_trained")],
)
def test_events_without_metrics_outside_gated_stages_are_approved(stage, event_type):
    decision, _, rule = evaluate_event(_event(stage, event_type), STAGED, SCHEMA_V2)
    assert (decision, rule) == ("approved", "policy.all_checks_passed")


def test_without_the_field_the_dissertation_behaviour_is_kept():
    decision, _, rule = evaluate_event(
        _event("data_preparation", "data_ingested"), BASE_POLICY, SCHEMA_V2
    )
    assert (decision, rule) == ("rejected", "threshold.precision")


def test_version_1_ignores_the_field():
    decision, reason, rule = evaluate_event(
        _event("data_preparation", "data_ingested"), STAGED, SCHEMA_V1
    )
    assert (decision, rule) == ("rejected", "threshold.precision")
    assert reason == "precision None below threshold 0.75"


@pytest.mark.parametrize(
    "metrics,rule,word",
    [
        ({"demographic_parity_diff": 0.05}, "threshold.precision", "missing"),
        ({"precision": 0.80}, "threshold.fairness", "missing"),
        ({"precision": 0.70, "demographic_parity_diff": 0.05}, "threshold.precision", "below"),
        ({"precision": 0.80, "demographic_parity_diff": 0.20}, "threshold.fairness", "above"),
    ],
)
@pytest.mark.parametrize("stage", ["validation", "deployment"])
def test_gated_stages_require_the_metrics_and_apply_the_thresholds(stage, metrics, rule, word):
    decision, reason, got = evaluate_event(_event(stage, "x", metrics), STAGED, SCHEMA_V2)
    assert (decision, got) == ("rejected", rule)
    assert word in reason


def test_gated_stage_with_passing_metrics_is_approved():
    decision, _, rule = evaluate_event(_event("validation", "model_validation", GOOD),
                                       STAGED, SCHEMA_V2)
    assert (decision, rule) == ("approved", "policy.all_checks_passed")


def test_monitoring_is_held_to_the_drift_rule_only():
    low_precision = {"precision": 0.10, "demographic_parity_diff": 0.90}
    calm = evaluate_event(_event("post_deploy_monitoring", "monitoring_batch",
                                 {**low_precision, "drift_score": 0.10}), STAGED, SCHEMA_V2)
    drift = evaluate_event(_event("post_deploy_monitoring", "monitoring_batch",
                                  {"drift_score": 0.40}), STAGED, SCHEMA_V2)
    assert calm[0] == "approved"
    assert (drift[0], drift[2]) == ("escalated", "monitoring.drift_alert")


def test_incidents_still_come_first():
    decision, _, rule = evaluate_event(
        _event("validation", "serious_incident_detected"), STAGED, SCHEMA_V2
    )
    assert (decision, rule) == ("escalated", "incident.reportable")


@pytest.mark.parametrize("bad", [[], "validation", [1], [""], {"validation": True}])
def test_malformed_stage_list_fails_closed(bad):
    wd = Path(tempfile.gettempdir()) / f"stages_{uuid.uuid4().hex[:8]}"
    wd.mkdir(parents=True)
    path = wd / "policies.json"
    path.write_text(json.dumps({**BASE_POLICY, METRIC_THRESHOLD_STAGES: bad}), encoding="utf-8")
    with pytest.raises(InvalidPolicyError):
        ComplianceOracle(policy_file=path, ledger_file=wd / "ledger.jsonl")


def test_the_stage_list_is_part_of_the_policy_identity():
    assert policy_identity(STAGED, SCHEMA_V2) != policy_identity(BASE_POLICY, SCHEMA_V2)


def test_staged_decisions_reexecute():
    wd = Path(tempfile.gettempdir()) / f"stages_{uuid.uuid4().hex[:8]}"
    wd.mkdir(parents=True)
    (wd / "policies.json").write_text(json.dumps(STAGED), encoding="utf-8")
    oracle = ComplianceOracle(policy_file=wd / "policies.json",
                              ledger_file=wd / "ledger.jsonl", schema_version=SCHEMA_V2)
    oracle.reset_ledger()
    events = [
        _event("data_preparation", "data_ingested"),
        _event("training", "model_trained"),
        _event("validation", "model_validation", GOOD),
        _event("validation", "model_validation", {"precision": 0.80}),
        _event("post_deploy_monitoring", "monitoring_batch", {"drift_score": 0.40}),
    ]
    records = [oracle.process_mlops_event(e) for e in events]
    assert [r["decision"] for r in records] == [
        "approved", "approved", "approved", "rejected", "escalated"]
    assert oracle.verify_chain().is_valid
    archive = wd / "policies_archive"
    assert all(reexecute(r, archive).status == MATCH for r in records)
