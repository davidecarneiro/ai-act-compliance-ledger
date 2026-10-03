"""Boundary matrix of the evidence contract.

The canonical six scenarios are a positive control: they say what happens on
the happy path, not what the input gate accepts. This module walks the domain
the gate actually admits, because three defects lived in the gap between the
two. A ``scenario_id`` of ``None`` was approved, signed and chained, and then
verified to a different body in Go. A rejection carrying a list or a number in
an identity field could not be decoded by the chaincode at all. And a metrics
mapping that mixed key types raised inside the artefact digest, before any
decision existed, so nothing at all reached the ledger.

The ledger this module builds is written to ``testdata_fronteiras.json`` in the
chaincode directory, where ``TestBoundaryLedgerVerifiesInGo`` re-verifies every
record. Regenerate it by running this module directly.
"""

from __future__ import annotations

import json
import math
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulator import (  # noqa: E402
    ComplianceOracle,
    _canonical_source,
    canonical_json,
    sha256_hex,
)

GO_TESTDATA = (
    ROOT.parents[0] / "fabric_migration" / "chaincode" / "testdata_fronteiras.json"
)

SOUND_METRICS = {
    "precision": 0.95,
    "demographic_parity_diff": 0.01,
    "drift_score": 0.02,
}

BASE_EVENT = {
    "event_type": "model_validation",
    "artifact_type": "model",
    "pipeline_stage": "validation",
    "human_approval": True,
    "risk_level": "high",
}


def _event(**overrides) -> dict:
    event = {**BASE_EVENT, "metrics": dict(SOUND_METRICS)}
    event.update(overrides)
    return event


# (label, event, expected decision, whether metrics survive into the record)
BOUNDARY_MATRIX = [
    ("scenario named", _event(scenario_id="canonical", artifact_id="m1"), "approved", True),
    ("scenario null", _event(scenario_id=None, artifact_id="m2"), "approved", True),
    ("scenario absent", _event(artifact_id="m3"), "approved", True),
    ("scenario empty", _event(scenario_id="", artifact_id="m4"), "approved", True),
    ("scenario unicode", _event(scenario_id="cenário-çã€", artifact_id="m5"), "approved", True),
    ("scenario is a list", _event(scenario_id=["review"], artifact_id="m6"), "rejected", True),
    (
        "scenario with a lone surrogate",
        _event(scenario_id="before\ud800after", artifact_id="m15"),
        "rejected",
        True,
    ),
    (
        "metric name with a lone surrogate",
        _event(
            scenario_id="s16",
            artifact_id="m16",
            metrics={**SOUND_METRICS, "prec\ud800ision": 0.9},
        ),
        "rejected",
        # Metrics ARE suppressed here, and that is the right behaviour: a name
        # that does not encode to UTF-8 is not serialisable in an interoperable
        # way, and kept as it stands it would enter the signed body and make Go
        # rebuild a different digest. Not the case for a threshold rejection,
        # where the numbers are valid and the auditor needs them.
        False,
    ),
    ("artifact id is a number", _event(scenario_id="s7", artifact_id=123), "rejected", True),
    (
        "rejected on precision",
        _event(scenario_id="s8", artifact_id="m8", metrics={**SOUND_METRICS, "precision": 0.5}),
        "rejected",
        True,
    ),
    (
        "rejected on fairness",
        _event(
            scenario_id="s9",
            artifact_id="m9",
            metrics={**SOUND_METRICS, "demographic_parity_diff": 0.09},
        ),
        "rejected",
        True,
    ),
    (
        "rejected on human approval",
        _event(scenario_id="s10", artifact_id="m10", human_approval=False),
        "rejected",
        True,
    ),
    (
        "escalated on drift",
        _event(
            scenario_id="s11",
            artifact_id="m11",
            event_type="drift_detection",
            pipeline_stage="monitoring",
            metrics={**SOUND_METRICS, "drift_score": 0.4},
        ),
        "escalated",
        True,
    ),
    (
        "metric is NaN",
        _event(
            scenario_id="s12",
            artifact_id="m12",
            metrics={**SOUND_METRICS, "precision": math.nan},
        ),
        "rejected",
        False,
    ),
    (
        "metric keys of mixed type",
        _event(scenario_id="s13", artifact_id="m13", metrics={**SOUND_METRICS, 1: 0.5}),
        "rejected",
        False,
    ),
    (
        "metric is text",
        _event(
            scenario_id="s14", artifact_id="m14", metrics={**SOUND_METRICS, "precision": "high"}
        ),
        "rejected",
        False,
    ),
]


def _fresh_oracle() -> ComplianceOracle:
    workdir = Path(tempfile.gettempdir()) / f"oracle_bounds_{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
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
    return ComplianceOracle(policy_file=policy_file, ledger_file=workdir / "ledger.json")


def build_boundary_ledger() -> list:
    oracle = _fresh_oracle()
    for _label, event, _decision, _keeps in BOUNDARY_MATRIX:
        oracle.process_mlops_event(event)
    return json.loads(oracle.ledger_file.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def boundary_ledger() -> list:
    return build_boundary_ledger()


def test_every_admitted_input_produces_a_record(boundary_ledger):
    """No input the gate admits may escape as an exception."""
    assert len(boundary_ledger) == len(BOUNDARY_MATRIX)


def test_decisions_match_the_matrix(boundary_ledger):
    for record, (label, _event, decision, _keeps) in zip(boundary_ledger, BOUNDARY_MATRIX):
        assert record["decision"] == decision, label


def test_threshold_rejections_keep_their_metrics(boundary_ledger):
    """A rejection by threshold is where the measured value matters most.

    Suppressing the metrics of every rejection threw away valid numbers and
    made the reason string the only record of what failed.
    """
    for record, (label, _event, _decision, keeps) in zip(boundary_ledger, BOUNDARY_MATRIX):
        if keeps:
            assert record["metrics"] is not None, label
        else:
            assert record["metrics"] is None, label


def test_identity_fields_stay_within_the_string_domain(boundary_ledger):
    """Required identity fields are strings even when the input was not.

    The chaincode declares them as strings, so a rejection that copied a list
    or a number verbatim could not be decoded at the destination at all.
    """
    for record in boundary_ledger:
        for field in ("event_type", "artifact_id", "artifact_type", "pipeline_stage"):
            assert isinstance(record[field], str)
        assert record["scenario_id"] is None or isinstance(record["scenario_id"], str)


def test_chain_verifies_over_the_whole_matrix(boundary_ledger):
    oracle = _fresh_oracle()
    report = oracle.verify_chain(boundary_ledger)
    assert report.total == len(BOUNDARY_MATRIX)
    assert report.valid == report.total
    assert report.first_invalid_index is None


def test_go_testdata_is_current(boundary_ledger):
    """The Go boundary test must run against this matrix, not an older one.

    Only the shape is compared: evidence ids and timestamps differ on every
    run, so requiring byte equality would fail for the wrong reason.
    """
    # Not a skip: this test is what guarantees the Go side runs against the
    # current matrix, and the interoperability claim leans on it. Skipping when
    # the file is missing would turn the absence of the proof into a green run.
    assert GO_TESTDATA.exists(), (
        f"{GO_TESTDATA} is missing; regenerate it with "
        f"`python3 tests/test_fronteiras.py` so the Go boundary test has the "
        f"current matrix to verify")
    stored = json.loads(GO_TESTDATA.read_text(encoding="utf-8"))
    assert len(stored) == len(BOUNDARY_MATRIX)
    assert [r["decision"] for r in stored] == [d for _l, _e, d, _k in BOUNDARY_MATRIX]
    assert [r["metrics"] is not None for r in stored] == [
        k for _l, _e, _d, k in BOUNDARY_MATRIX
    ]


if __name__ == "__main__":
    ledger = build_boundary_ledger()
    GO_TESTDATA.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    print(f"testdata_fronteiras.json regenerated: {len(ledger)} records")


def test_normalisation_does_not_merge_distinct_inputs():
    """Verify normalisation does not merge distinct inputs."""
    a = {"metrics": {1: 0.1, "1": 0.2}}
    b = {"metrics": {1: 0.9, "1": 0.2}}
    ha = sha256_hex(canonical_json(_canonical_source(a)))
    hb = sha256_hex(canonical_json(_canonical_source(b)))
    assert ha != hb, (
        "two distinct inputs collapsed onto the same digest: normalisation is "
        "losing information again"
    )


def test_normalisation_is_the_identity_for_well_formed_events():
    """The fix above must not move the digest of any historical record."""
    well_formed = {
        "scenario_id": "s",
        "event_type": "model_validation",
        "metrics": {"precision": 0.9, "demographic_parity_diff": 0.01},
        "nested": {"a": [1, 2, {"b": "c"}]},
    }
    assert _canonical_source(well_formed) == well_formed


def test_the_record_of_a_unicode_rejection_is_interoperable():
    """The rejection has to be readable at the destination, not repeat the problem."""
    import json as _json

    oracle = _fresh_oracle()
    record = oracle.process_mlops_event(
        _event(scenario_id="before\ud800after", artifact_id="m-uni")
    )
    assert record["decision"] == "rejected"
    # The whole record has to serialise and encode: had the character been
    # copied across, this would raise UnicodeEncodeError.
    _json.dumps(record, ensure_ascii=True).encode("utf-8")
    assert "\ud800" not in record["scenario_id"], (
        "the surrogate was copied into the signed record: the rejection kept "
        "the very problem it rejected"
    )


def test_sanitisation_preserves_valid_text_in_the_same_value():
    """Verify sanitisation preserves valid text in the same value."""
    import json as _json

    cases = {
        "ASCII context": "before\ud800after",
        "accented text": "ação\ud800fim",
        "astral plane and surrogate": "😀\ud800fim",
        "low surrogate": "a\udfffb",
    }
    oracle = _fresh_oracle()
    for label, value in cases.items():
        record = oracle.process_mlops_event(
            _event(scenario_id=value, artifact_id=f"m-{len(label)}")
        )
        assert record["decision"] == "rejected", label
        _json.dumps(record, ensure_ascii=True).encode("utf-8")
    assert oracle.verify_chain().is_valid


def test_valid_unicode_text_still_passes():
    """The domain excludes lone surrogates, not accents or the astral plane."""
    oracle = _fresh_oracle()
    for value in ("cenário-çã€", "emoji 😀 ok", "surrogate pair a𐀀b"):
        record = oracle.process_mlops_event(_event(scenario_id=value, artifact_id="m-ok"))
        assert record["decision"] != "rejected" or "surrogate" not in (record.get("reason") or "")
        assert record["scenario_id"] == value, "valid text was altered by sanitisation"


def test_normalisation_preserves_the_key_value_association():
    """Swapping values between keys of different types has to remain visible."""
    a = {"metrics": {1: 0.1, "1": 0.2}}
    b = {"metrics": {1: 0.2, "1": 0.1}}
    ha = sha256_hex(canonical_json(_canonical_source(a)))
    hb = sha256_hex(canonical_json(_canonical_source(b)))
    assert ha != hb, "swapping values between key types became invisible"


def test_the_malformed_input_envelope_cannot_be_imitated():
    """A normal object carrying the marker key must not pass for an envelope."""
    imitation = {"metrics": {"__unrepresentable__": [["int", "1", 0.1]]}}
    real = {"metrics": {1: 0.1}}
    ha = sha256_hex(canonical_json(_canonical_source(imitation)))
    hb = sha256_hex(canonical_json(_canonical_source(real)))
    assert ha != hb
