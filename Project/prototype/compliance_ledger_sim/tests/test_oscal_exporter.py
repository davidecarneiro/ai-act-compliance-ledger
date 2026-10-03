"""Tests for the OSCAL Assessment Results exporter (M23).

Verifies that the document produced by ``to_oscal_sar`` (a) carries the
required OSCAL 1.1.2 metadata, (b) has one observation per ledger record,
(c) has one finding per recognised decision, and (d) records the
chain-verification outcome in the assessment log.
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

from oscal_exporter import to_oscal_sar  # noqa: E402
from scenarios import build_scenarios  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402


@pytest.fixture()
def ledger() -> list[dict]:
    workdir = Path(tempfile.gettempdir()) / f"oscal_{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    oracle = ComplianceOracle(
        ledger_file=workdir / "ledger.json",
        policy_file=workdir / "policies.json",
    )
    oracle.reset_ledger()
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    return json.loads(oracle.ledger_file.read_text(encoding="utf-8"))


def test_document_has_required_oscal_metadata(ledger):
    doc = to_oscal_sar(ledger)
    ar = doc["assessment-results"]
    assert ar["metadata"]["oscal-version"] == "1.1.2"
    assert "uuid" in ar
    assert ar["metadata"]["title"]
    assert ar["metadata"]["last-modified"]
    assert ar["metadata"]["version"]
    # parties block must include at least the issuer
    assert len(ar["metadata"]["parties"]) >= 1


def test_one_observation_per_ledger_record(ledger):
    doc = to_oscal_sar(ledger)
    observations = doc["assessment-results"]["results"][0]["observations"]
    assert len(observations) == len(ledger)
    for obs in observations:
        assert "uuid" in obs
        assert "AUTOMATED" in obs["methods"]
        assert obs["relevant-evidence"]


def test_findings_reference_observations(ledger):
    doc = to_oscal_sar(ledger)
    findings = doc["assessment-results"]["results"][0]["findings"]
    obs_uuids = {
        o["uuid"]
        for o in doc["assessment-results"]["results"][0]["observations"]
    }
    for finding in findings:
        related = finding["related-observations"]
        assert any(r["observation-uuid"] in obs_uuids for r in related)


def test_findings_carry_satisfied_or_not_satisfied(ledger):
    doc = to_oscal_sar(ledger)
    states = {
        f["target"]["status"]["state"]
        for f in doc["assessment-results"]["results"][0]["findings"]
    }
    assert states.issubset({"satisfied", "not-satisfied"})


def test_assessment_log_has_chain_verification_entry(ledger):
    doc = to_oscal_sar(ledger)
    entries = doc["assessment-results"]["results"][0]["assessment-log"]["entries"]
    titles = [e["title"] for e in entries]
    assert "Ledger integrity verification" in titles


def test_uuids_are_deterministic_for_same_evidence_id(ledger):
    """UUID v5 derivation guarantees stable IDs across runs/exports."""

    doc1 = to_oscal_sar(ledger)
    doc2 = to_oscal_sar(ledger)
    obs1 = {
        o["uuid"]
        for o in doc1["assessment-results"]["results"][0]["observations"]
    }
    obs2 = {
        o["uuid"]
        for o in doc2["assessment-results"]["results"][0]["observations"]
    }
    assert obs1 == obs2


def test_control_ids_map_to_aia_namespace(ledger):
    doc = to_oscal_sar(ledger)
    findings = doc["assessment-results"]["results"][0]["findings"]
    for f in findings:
        for prop in f.get("props", []):
            if prop["name"] == "supports-requirement":
                assert prop["value"].startswith("aia-")


# ----------------------------------------------------------------------
# Redaction (AI Act Art. 78) — confidentiality / trade secrets
# ----------------------------------------------------------------------


REDACTED_TOKEN = "[REDACTED — AI Act Art. 78 confidentiality]"


def test_redacted_output_hides_free_text_descriptions(ledger):
    redacted = to_oscal_sar(ledger, redacted=True)
    obs = redacted["assessment-results"]["results"][0]["observations"]
    findings = redacted["assessment-results"]["results"][0]["findings"]
    for o in obs:
        assert o["description"] == REDACTED_TOKEN
        # The "reason" prop is also redacted in observations.
        reason_prop = next(p for p in o["props"] if p["name"] == "reason")
        assert reason_prop["value"] == REDACTED_TOKEN
        # Marker prop is set so a downstream verifier knows redaction was applied.
        marker = next(p for p in o["props"] if p["name"] == "redaction_applied")
        assert marker["value"] == "true"
    for f in findings:
        assert f["description"] == REDACTED_TOKEN


def test_redacted_output_preserves_chain_anchors(ledger):
    """Redaction must not break third-party integrity verification:
    relevant-evidence (record_hash, chain_hash, signature_alg) must remain."""

    redacted = to_oscal_sar(ledger, redacted=True)
    obs = redacted["assessment-results"]["results"][0]["observations"]
    for o in obs:
        ev = o["relevant-evidence"][0]["description"]
        assert "record_hash=" in ev
        assert "chain_hash=" in ev
        assert "signature_alg=" in ev


def test_redacted_output_preserves_control_ids(ledger):
    """The mapping AI Act article -> aia-<id> must remain intact in
    the redacted version, so the auditor can still verify which
    requirements were exercised."""

    redacted = to_oscal_sar(ledger, redacted=True)
    findings = redacted["assessment-results"]["results"][0]["findings"]
    seen_controls = set()
    for f in findings:
        for prop in f.get("props", []):
            if prop["name"] == "supports-requirement":
                assert prop["value"].startswith("aia-")
                seen_controls.add(prop["value"])
    assert len(seen_controls) >= 3


def test_redacted_output_preserves_state_satisfied_or_not(ledger):
    """The state of the technical objective (satisfied / not-satisfied)
    must remain visible in the redacted version. It is the outcome of
    the configured check, not a legal compliance verdict."""

    redacted = to_oscal_sar(ledger, redacted=True)
    findings = redacted["assessment-results"]["results"][0]["findings"]
    states = {f["target"]["status"]["state"] for f in findings}
    assert states.issubset({"satisfied", "not-satisfied"})
    assert states  # not empty


def test_full_and_redacted_have_same_uuids(ledger):
    """Determinism guarantee: the same ledger produces identical UUIDs
    in both redacted and full mode, so an auditor receiving the
    redacted version can later ask for the unredacted one and
    confirm it is the same set of evidence."""

    full = to_oscal_sar(ledger, redacted=False)
    redacted = to_oscal_sar(ledger, redacted=True)
    full_obs = {
        o["uuid"] for o in full["assessment-results"]["results"][0]["observations"]
    }
    red_obs = {
        o["uuid"] for o in redacted["assessment-results"]["results"][0]["observations"]
    }
    assert full_obs == red_obs


def _chain_valid_prop(doc: dict) -> str:
    """Read the chain_valid property out of the assessment-log entry."""
    entries = doc["assessment-results"]["results"][0]["assessment-log"]["entries"]
    for prop in entries[0]["props"]:
        if prop["name"] == "chain_valid":
            return prop["value"]
    raise AssertionError("chain_valid property not present in the assessment log")


def test_chain_valid_is_computed_not_assumed(ledger):
    """An intact ledger must report chain_valid=true, and it must be computed.

    Before this check existed the exporter defaulted the property to true, so a
    document could assert integrity that had never been verified.
    """
    assert _chain_valid_prop(to_oscal_sar(ledger)) == "true"


def test_tampered_ledger_exports_chain_valid_false(ledger):
    """A modified record body must surface as chain_valid=false in the export.

    This is the negative case the earlier suite did not cover: the document is
    the artefact an auditor receives, so a tampered chain must not be exported
    with an integrity claim attached to it.
    """
    tampered = json.loads(json.dumps(ledger))
    tampered[2]["decision"] = "approved"
    assert _chain_valid_prop(to_oscal_sar(tampered)) == "false"


def test_caller_may_supply_a_full_verification_result(ledger):
    """A caller that verified signatures too can override the key-free result."""
    assert _chain_valid_prop(to_oscal_sar(ledger, chain_valid=False)) == "false"


def test_finding_targets_a_technical_objective_not_an_article(ledger):
    """A finding asserts a technical fact, not a verdict on an article.

    Publishing satisfied/not-satisfied against aia-72 made a drift alert read
    as a breach of the monitoring duty, when raising it is that duty working.
    The article is now carried as a requirement the evidence supports.
    """
    doc = to_oscal_sar(ledger)
    findings = doc["assessment-results"]["results"][0]["findings"]
    targets = {
        record["scenario_id"]: finding["target"]["target-id"]
        for record, finding in zip(ledger, findings)
    }
    assert targets["low_precision_rejected"] == "obj-precision-threshold"
    assert targets["fairness_rejected"] == "obj-fairness-threshold"
    assert targets["missing_human_approval_rejected"] == (
        "obj-human-approval-recorded"
    )
    assert targets["drift_detected"] == "obj-drift-alert-raised"
    assert len(set(targets.values())) > 1, "objectives must not collapse to one"
    for finding in findings:
        assert not finding["target"]["target-id"].startswith("aia-")


def test_a_raised_alert_is_a_satisfied_objective(ledger):
    """Detecting drift and escalating is the monitoring working.

    The earlier mapping turned every escalation into not-satisfied, so a
    correctly raised alert was exported as a failure.
    """
    doc = to_oscal_sar(ledger)
    states = {
        record["scenario_id"]: finding["target"]["status"]["state"]
        for record, finding in zip(
            ledger, doc["assessment-results"]["results"][0]["findings"]
        )
    }
    assert states["drift_detected"] == "satisfied"
    assert states["audit_query"] == "satisfied"
    assert states["low_precision_rejected"] == "not-satisfied"


def test_every_finding_states_that_no_legal_assessment_was_made(ledger):
    """The document must not be read as a compliance verdict."""
    doc = to_oscal_sar(ledger)
    for finding in doc["assessment-results"]["results"][0]["findings"]:
        props = {p["name"]: p["value"] for p in finding["props"]}
        assert props["legal-assessment"] == "not-performed"
        assert props["objectives-version"]
        assert props["objective-proposition"]


def test_the_objective_comes_from_the_rule_id_not_from_prose(ledger):
    """Deriving the objective from the reason text made wording protocol.

    Editing a message changed the exported article. The rule identifier is
    written by the engine and carries no prose.
    """
    doc = to_oscal_sar(ledger)
    for record, finding in zip(
        ledger, doc["assessment-results"]["results"][0]["findings"]
    ):
        props = {p["name"]: p["value"] for p in finding["props"]}
        assert props["rule-id"] == record["rule_id"]

    reworded = json.loads(json.dumps(ledger))
    for record in reworded:
        record["reason"] = "wording that mentions no rule at all"
    after = to_oscal_sar(reworded)
    assert [f["target"]["target-id"] for f in after["assessment-results"]["results"][0]["findings"]] == [
        f["target"]["target-id"] for f in doc["assessment-results"]["results"][0]["findings"]
    ]


def _prop(doc, name):
    """Read one property out of the assessment-log entry."""
    entries = doc["assessment-results"]["results"][0]["assessment-log"]["entries"]
    for prop in entries[0]["props"]:
        if prop["name"] == name:
            return prop["value"]
    raise AssertionError(f"{name} property not present in the assessment log")


def _log_description(doc):
    entries = doc["assessment-results"]["results"][0]["assessment-log"]["entries"]
    return entries[0]["description"]


def test_signatures_are_reported_separately_from_the_chain(ledger):
    """The two checks are distinct, so the document must not merge them.

    Before this check the assessment log stated, on every export, that all
    three integrity signals had been validated. That sentence was fixed text:
    it was emitted even when no signature had been looked at.
    """
    doc = to_oscal_sar(ledger)
    assert _prop(doc, "chain_valid") == "true"
    assert _prop(doc, "signatures_verified") == "true"


def test_mutated_signature_is_reported_even_though_the_chain_holds(ledger):
    """A forged signature leaves the hash chain intact; the document must say so."""
    mutated = json.loads(json.dumps(ledger))
    signature = mutated[0]["issuer_signature"]
    mutated[0]["issuer_signature"] = ("B" if signature[0] != "B" else "C") + signature[1:]

    doc = to_oscal_sar(mutated)
    assert _prop(doc, "chain_valid") == "true"
    assert _prop(doc, "signatures_verified") == "false"
    assert "failed verification" in _log_description(doc)


def test_description_never_claims_an_unperformed_signature_check(ledger):
    """With no public key reachable, the log must say the check did not run."""
    doc = to_oscal_sar(ledger, signatures_verified=None)
    if _prop(doc, "signatures_verified") == "not-checked":
        assert "were not checked" in _log_description(doc)
    else:
        assert "verified against the issuer's public key" in _log_description(doc)


def test_caller_may_declare_that_it_verified_signatures(ledger):
    """A caller that ran the full verify_chain() can state it in the document.

    The document must attribute the result to the caller rather than narrate
    it as a local execution: presenting someone else's assertion in the
    language of an execution this exporter performed would misstate who
    checked what.
    """
    doc = to_oscal_sar(ledger, chain_valid=True, signatures_verified=True)
    assert _prop(doc, "signatures_verified") == "true"
    assert _prop(doc, "chain_verification_source") == "supplied-by-caller"
    assert _prop(doc, "signature_verification_source") == "supplied-by-caller"
    assert "the caller reports" in _log_description(doc)
    assert "recomputed each record_hash" not in _log_description(doc)


def test_a_computed_result_is_attributed_to_the_exporter(ledger):
    """The default path does run the checks, and says so."""
    doc = to_oscal_sar(ledger)
    assert _prop(doc, "chain_verification_source") == "computed-by-exporter"
    assert _prop(doc, "signature_verification_source") == "computed-by-exporter"
    assert "recomputed each record_hash" in _log_description(doc)


def test_the_results_description_reflects_the_ledger_exported(ledger):
    """Verify the results description reflects the ledger exported."""
    one = to_oscal_sar(ledger[:1])
    description = one["assessment-results"]["results"][0]["description"]
    assert "1 evidence record" in description
    assert "Six canonical scenarios" not in description


def test_an_unknown_issuer_is_not_reported_as_a_forgery(ledger):
    """A key the exporter cannot resolve is not the same as a bad signature.

    Reporting both as false would let an unknown issuer read as a forgery.
    The distinction matters to an auditor deciding what the document proves.
    """
    foreign = json.loads(json.dumps(ledger))
    for record in foreign:
        record["issuer_id"] = "an-issuer-with-no-key-on-disk"
    assert _prop(to_oscal_sar(foreign), "signatures_verified") == "not-checked"


def test_a_key_that_does_not_match_the_recorded_fingerprint_is_not_used(ledger):
    """Each record names the key it was signed with; a mismatch is unresolved."""
    mismatched = json.loads(json.dumps(ledger))
    mismatched[0]["issuer_pubkey_fingerprint"] = "0" * 64
    assert _prop(to_oscal_sar(mismatched), "signatures_verified") == "not-checked"


def test_a_forged_signature_from_a_known_issuer_is_reported_false(ledger):
    """The resolvable-issuer case must still surface a real forgery."""
    forged = json.loads(json.dumps(ledger))
    signature = forged[0]["issuer_signature"]
    forged[0]["issuer_signature"] = (
        "B" if signature[0] != "B" else "C"
    ) + signature[1:]
    assert _prop(to_oscal_sar(forged), "signatures_verified") == "false"


def test_a_caller_supplied_signature_result_is_never_narrated_as_local(ledger):
    """Provenance is per property: the chain may be computed here and the
    signature result come from elsewhere. Deriving one from the other let a
    caller's assertion be published in the language of a local execution,
    with the signature verifier never called."""
    doc = to_oscal_sar(ledger, signatures_verified=True)
    assert _prop(doc, "chain_verification_source") == "computed-by-exporter"
    assert _prop(doc, "signature_verification_source") == "supplied-by-caller"
    assert "the caller reports" in _log_description(doc)
    assert "verified against the issuer's public key" not in _log_description(doc)


def test_signatures_not_attempted_are_not_blamed_on_key_resolution(ledger):
    """A caller-supplied chain result leaves signatures unchecked."""
    doc = to_oscal_sar(ledger, chain_valid=True)
    assert _prop(doc, "signature_verification_source") == "not-attempted"
    assert "not checked at all" in _log_description(doc)
    assert "could not resolve" not in _log_description(doc)


def test_an_unexportable_identifier_never_reaches_the_ledger(ledger):
    """A record the exporter cannot read is not evidence.

    A list in scenario_id passed the gate, was signed and chained, and then
    made the whole export fail, because the exporter groups records by that
    value.
    """
    for value in (["a"], {"name": "a"}):
        event = copy.deepcopy(build_scenarios()[0])
        event["scenario_id"] = value
        oracle = ComplianceOracle(
            ledger_file=Path(tempfile.gettempdir())
            / f"scen_{uuid.uuid4().hex[:8]}.json"
        )
        oracle.reset_ledger()
        record = oracle.process_mlops_event(event)
        assert record["decision"] == "rejected"
        assert "scenario_id must be a string" in record["reason"]
        to_oscal_sar(oracle._read_ledger())
