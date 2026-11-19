"""The OSCAL exporter's redacted mode, field by field."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import oscal_exporter as ox  # noqa: E402

MARKER = "ZZSYNTHETICMARKERZZ"

# Free-text fields the integrator controls and that reach the exporter.
FREE_TEXT_FIELDS = [
    "scenario_id", "event_type", "artifact_id", "artifact_type",
    "pipeline_stage", "reason", "policy_id",
]
# rule_id is NOT in the list above, and the reason was checked: it does not come
# from the event, it comes from the simulator's `_validate_compliance`, out of a
# closed vocabulary ("policy.all_checks_passed", "threshold.precision", ...).
# Injecting text into it is reachable from a test but not through the API. That
# property is what gets verified, in the vocabulary test further down.

# What MAY appear in the redacted document, and why. Leaving this list requires a
# written justification; it is not a matter of the exporter's convenience.
ALLOWED_TO_LEAVE = {
    "evidence_id": "opaque UUID; the anchor tying the SAR to the ledger record",
    "record_hash": "hash; not sensitive and needed for third-party verification",
    "chain_hash": "same",
    "parent_hash": "same",
    "issuer_pubkey_fingerprint": "fingerprint of the issuer's public key",
    "decision": "closed set: approved, rejected, escalated, verified",
    "sig_alg": "closed set",
    "hash_alg": "closed set",
    "rule_id": "written by the engine, closed vocabulary; see the vocabulary test",
}
# policy_hash left the list on 2026-11-19: an unkeyed digest of a policy lets
# anyone who knows the format recover its thresholds by search. Redacted mode
# carries a keyed commitment instead (tests at the end of this file).


def _record(**overrides):
    base = {
        "evidence_id": "ev-0001", "scenario_id": "scenario", "event_type": "model_validation",
        "artifact_id": "m1", "artifact_type": "model", "pipeline_stage": "validation",
        "timestamp": "2026-09-15T00:00:00Z", "decision": "approved", "reason": "ok",
        "artifact_hash": "a" * 64, "requirements_covered": ["Art.15"], "issuer_id": "oracle",
        "issuer_pubkey_fingerprint": "b" * 64, "sig_alg": "Ed25519", "hash_alg": "SHA-256",
        "parent_hash": "0" * 64, "record_hash": "c" * 64, "issuer_signature": "sig",
        "chain_hash": "d" * 64, "metrics": {"precision": 0.95},
        "policy_id": "p1", "policy_hash": "e" * 64, "rule_id": "min_precision",
    }
    base.update(overrides)
    return base


def _paths_containing(doc, needle, path="$"):
    """Every path in the document whose text contains the needle."""
    hits = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            hits += _paths_containing(v, needle, f"{path}.{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            hits += _paths_containing(v, needle, f"{path}[{i}]")
    elif isinstance(doc, str) and needle in doc:
        hits.append(path)
    return hits


def test_no_free_text_field_survives_redacted_mode():
    for field in FREE_TEXT_FIELDS:
        rec = _record(**{field: MARKER})
        sar = ox.to_oscal_sar([rec], chain_valid=True, redacted=True,
                              signatures_verified=True)
        leaks = _paths_containing(sar, MARKER)
        assert not leaks, (
            f"field '{field}' escaped redacted mode at: {leaks}. "
            f"Either suppress it, or add it to ALLOWED_TO_LEAVE with a reason."
        )


def test_normal_mode_still_says_everything():
    """Redaction must not be the default behaviour."""
    rec = _record(scenario_id=MARKER)
    sar = ox.to_oscal_sar([rec], chain_valid=True, redacted=False,
                          signatures_verified=True)
    assert _paths_containing(sar, MARKER), (
        "without redaction the scenario_id has to appear; otherwise information "
        "the fully authorised auditor needs has been lost"
    )


def test_the_linking_anchor_survives():
    """Suppressing text must not break the link between the SAR and the ledger."""
    rec = _record(evidence_id="ev-anchor-42")
    sar = ox.to_oscal_sar([rec], chain_valid=True, redacted=True,
                          signatures_verified=True)
    assert _paths_containing(sar, "ev-anchor-42"), (
        "evidence_id has to stay in the redacted document: it is what lets the "
        "auditor tie each finding back to the ledger record"
    )
    assert "evidence_id" in ALLOWED_TO_LEAVE


def test_rule_id_comes_from_a_closed_vocabulary():
    """This is the justification for letting rule_id out, and it has to hold.

    STATIC verification on purpose: walking scenarios only exercises the rule_id
    values those scenarios trigger, and a new rule_id no scenario triggers would
    go unnoticed. The simulator is read instead, and every label it knows how to
    write is required to be classified in the exporter.
    """
    source = (Path(__file__).resolve().parents[1] / "simulator.py").read_text(
        encoding="utf-8"
    )
    import re

    written = set(
        re.findall(r'"((?:policy|threshold|gate|drift|input|incident)\.[a-z_]+)"', source)
    )
    assert written, "no rule_id found in the simulator: the pattern changed"
    unknown = written - set(ox.TECHNICAL_OBJECTIVES)
    assert not unknown, (
        f"rule_id values the simulator writes and the exporter does not classify: "
        f"{sorted(unknown)}. Either they enter TECHNICAL_OBJECTIVES, or redacted "
        f"mode stops being able to emit them in the clear."
    )


def test_no_derived_identifier_survives_redacted_mode():
    """Suppressing the text is not enough if a digest of it survives."""
    rec = _record(artifact_id=MARKER)
    sar = ox.to_oscal_sar([rec], chain_valid=True, redacted=True,
                          signatures_verified=True)
    derived = ox._uuid_for(MARKER, "subj")
    assert derived not in json.dumps(sar), (
        "the UUID derived from artifact_id survives redacted mode: anyone holding "
        "a candidate confirms it by recomputation"
    )


KEY = bytes(range(32))


def test_policy_digest_does_not_survive_redacted_mode():
    """Neither the digest nor the identifier derived from it may leave."""
    digest = "e" * 64
    rec = _record(policy_hash=digest, policy_id="pol-" + digest[:12])
    sar = ox.to_oscal_sar([rec], chain_valid=True, redacted=True,
                          signatures_verified=True, commitment_key=KEY)
    text = json.dumps(sar)
    assert digest[:12] not in text, "the policy digest, or its prefix, survives redacted mode"


def test_policy_commitment_opens_with_the_key_only():
    digest = "e" * 64
    sar = ox.to_oscal_sar([_record(policy_hash=digest)], chain_valid=True, redacted=True,
                          signatures_verified=True, commitment_key=KEY)
    finding = sar["assessment-results"]["results"][0]["findings"][0]
    value = next(p["value"] for p in finding["props"] if p["name"] == "policy-commitment")
    assert ox.opens_policy_commitment(value, KEY, digest)
    assert not ox.opens_policy_commitment(value, bytes(32), digest)
    assert not ox.opens_policy_commitment(value, KEY, "f" * 64)


def test_policy_commitment_groups_records_within_one_export():
    """A change of policy stays visible inside the export; exports are unlinkable."""
    records = [_record(evidence_id="ev-1", policy_hash="e" * 64),
               _record(evidence_id="ev-2", policy_hash="e" * 64),
               _record(evidence_id="ev-3", policy_hash="f" * 64)]

    def values(key):
        sar = ox.to_oscal_sar(records, chain_valid=True, redacted=True,
                              signatures_verified=True, commitment_key=key)
        return [next(p["value"] for p in f["props"] if p["name"] == "policy-commitment")
                for f in sar["assessment-results"]["results"][0]["findings"]]

    first = values(KEY)
    assert first[0] == first[1] != first[2]
    assert values(bytes(32))[0] != first[0]


def test_search_recovers_a_plain_digest_but_not_a_commitment():
    """The attack the amendment of 2026-11-19 describes, on a small policy."""
    import policy_guess
    from simulator import policy_identity

    policy = {"authorised_approvers": {"approver": "00" * 32}, "drift_alert_threshold": 0.05,
              "max_demographic_parity_diff": 0.01, "metric_threshold_stages": ["validation"],
              "min_precision": 0.02, "require_human_approval_for_high_risk": False,
              "signed_approval_required_for": ["deployment_request"]}
    digest = policy_identity(policy)[1]
    assert policy_guess.search([digest], policy)["recovered"]
    commitment = ox.policy_commitment(digest, KEY)
    template = dict(policy, min_precision=0.5)
    # Searching the commitment over the same small neighbourhood finds nothing.
    near = [dict(template, min_precision=p) for p in (0.01, 0.02, 0.03)]
    assert all(policy_identity(c)[1] != commitment for c in near)
