"""Shared scenario definitions for the Compliance Oracle and the baseline.

Centralising the scenarios in a single module guarantees that the Oracle and
the baseline logger consume the exact same input. Any divergence in evaluation
is therefore attributable to the architecture under test, not to differences in
the synthetic events.

Each scenario is a plain dictionary with the fields documented in the evidence
model (see Chapter 3 of the dissertation, Table 3.3). Hash and signature
fields are added downstream by the Compliance Oracle.
"""

from __future__ import annotations

from typing import List


def build_scenarios() -> List[dict]:
    approved_event = {
        "scenario_id": "approved_model",
        "event_type": "approved_model",
        "artifact_id": "credit-scoring-v2.0",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "metrics": {
            "precision": 0.89,
            "demographic_parity_diff": 0.03,
            "drift_score": 0.04,
        },
        "human_approval": True,
        "dataset_used": "s3://bucket/data/train_v7.csv",
    }
    low_precision_event = {
        "scenario_id": "low_precision_rejected",
        "event_type": "low_precision_rejected",
        "artifact_id": "credit-scoring-v2.1",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "metrics": {
            "precision": 0.74,
            "demographic_parity_diff": 0.02,
            "drift_score": 0.05,
        },
        "human_approval": True,
    }
    fairness_event = {
        "scenario_id": "fairness_rejected",
        "event_type": "fairness_rejected",
        "artifact_id": "credit-scoring-v2.2",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "metrics": {
            "precision": 0.86,
            "demographic_parity_diff": 0.09,
            "drift_score": 0.06,
        },
        "human_approval": True,
    }
    human_approval_event = {
        "scenario_id": "missing_human_approval_rejected",
        "event_type": "missing_human_approval_rejected",
        "artifact_id": "credit-scoring-v2.3",
        "artifact_type": "model",
        "pipeline_stage": "deployment",
        "risk_level": "high",
        "metrics": {
            "precision": 0.90,
            "demographic_parity_diff": 0.02,
            "drift_score": 0.03,
        },
        "human_approval": False,
    }
    drift_event = {
        "scenario_id": "drift_detected",
        "event_type": "drift_detected",
        "artifact_id": "credit-scoring-v2.4",
        "artifact_type": "monitoring_report",
        "pipeline_stage": "post_deploy_monitoring",
        "risk_level": "high",
        "metrics": {
            "precision": 0.85,
            "demographic_parity_diff": 0.03,
            "drift_score": 0.22,
        },
        "human_approval": True,
    }
    audit_event = {
        "scenario_id": "audit_query",
        "event_type": "audit_query",
        "artifact_id": "audit-bundle-2026-04",
        "artifact_type": "audit_package",
        "pipeline_stage": "audit",
        "risk_level": "medium",
        "metrics": {
            "precision": 0.99,
            "demographic_parity_diff": 0.0,
            "drift_score": 0.01,
        },
        "human_approval": True,
    }

    return [
        approved_event,
        low_precision_event,
        fairness_event,
        human_approval_event,
        drift_event,
        audit_event,
    ]


def build_incident_scenario() -> List[dict]:
    """Dedicated serious-incident sequence exercising AI Act Art. 73.

    Kept separate from ``build_scenarios()`` — and therefore from the latency
    comparison run — for two reasons. First, post-market incident reporting is
    a distinct concern from the deploy-gate validation scenarios. Second,
    keeping it out of the canonical six-scenario set means this demonstration
    does not perturb the reference latency measurement reported in Chapter 5.

    The sequence walks the Art. 73 lifecycle of a deployed high-risk system:
    detection of a serious incident, a simulated reporting event (Art. 73(2):
    without undue delay and no later than 15 days) and an audit query over the
    resulting trail. Nothing is sent to an authority, and the timestamps are
    the issuer's own. Like the MultiFlow and load-test runs it has a dedicated
    demonstration (``incident_demo.py``); the tests use the scenario as well.
    """
    incident_detected = {
        "scenario_id": "serious_incident_detected",
        "event_type": "serious_incident_detected",
        "artifact_id": "credit-scoring-v2.0",
        "artifact_type": "incident_report",
        "pipeline_stage": "post_deploy_monitoring",
        "risk_level": "high",
        "metrics": {
            "precision": 0.85,
            "demographic_parity_diff": 0.03,
        },
        "human_approval": True,
        "incident": {
            "severity": "serious",
            "category": "fundamental_rights_impact",
            "detected_at": "2026-04-15T09:20:00Z",
            "report_deadline_days": 15,
        },
    }
    incident_reported = {
        "scenario_id": "incident_reported_to_authority",
        "event_type": "incident_reported_to_authority",
        "artifact_id": "credit-scoring-v2.0",
        "artifact_type": "incident_report",
        "pipeline_stage": "post_deploy_monitoring",
        "risk_level": "high",
        "metrics": {
            "precision": 0.85,
            "demographic_parity_diff": 0.03,
        },
        "human_approval": True,
        "incident": {
            "severity": "serious",
            "reported_at": "2026-04-18T11:00:00Z",
            "authority": "market_surveillance_authority",
            "within_deadline": True,
        },
    }
    incident_audit = {
        "scenario_id": "incident_audit_query",
        "event_type": "incident_audit_query",
        "artifact_id": "incident-bundle-2026-04",
        "artifact_type": "audit_package",
        "pipeline_stage": "audit",
        "risk_level": "medium",
        "metrics": {
            "precision": 0.99,
            "demographic_parity_diff": 0.0,
        },
        "human_approval": True,
    }
    return [incident_detected, incident_reported, incident_audit]
