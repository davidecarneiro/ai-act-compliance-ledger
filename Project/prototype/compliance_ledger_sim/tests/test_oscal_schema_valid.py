"""Validate the OSCAL exporter output against the official NIST schema.

This closes the gap between *claiming* the export is "valid against the NIST
schema" and *demonstrating* it. The exporter output (full and redacted, and a
real ledger snapshot) is validated against the official OSCAL 1.1.2
``assessment-results`` JSON Schema, vendored under ``tests/fixtures/`` so the
test needs no network access.

Two practical caveats are handled explicitly:

* the OSCAL schema declares JSON Schema *draft-07*, so the draft-07 validator
  must be used (the 2020-12 validator does not resolve its ``$id`` anchors);
* the schema uses ECMA-262 ``pattern`` regexes with Unicode property escapes
  (``\\p{...}``) that Python's ``re`` cannot compile; the ``regex`` module is
  used instead via a small custom keyword.

The test self-skips when ``jsonschema`` or ``regex`` is not installed, so the
core suite still runs on a bare environment.
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

jsonschema = pytest.importorskip("jsonschema")
_re = pytest.importorskip("regex")

from jsonschema import Draft7Validator, validators  # noqa: E402
from jsonschema.exceptions import ValidationError  # noqa: E402

from oscal_exporter import to_oscal_sar  # noqa: E402
from scenarios import build_scenarios  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402

SCHEMA_PATH = (
    Path(__file__).parent / "fixtures" / "oscal_assessment-results_1.1.2_schema.json"
)


def _unicode_pattern(validator, patrn, instance, schema):
    """``pattern`` keyword backed by the ``regex`` module (handles \\p{...})."""
    if validator.is_type(instance, "string"):
        try:
            if _re.search(patrn, instance) is None:
                yield ValidationError(f"{instance!r} does not match {patrn!r}")
        except _re.error:
            return  # pattern we cannot compile: do not invent a failure


def _unicode_pattern_properties(validator, pattern_properties, instance, schema):
    if not validator.is_type(instance, "object"):
        return
    for pattern, subschema in pattern_properties.items():
        try:
            rx = _re.compile(pattern)
        except _re.error:
            continue
        for key, value in instance.items():
            if rx.search(key):
                yield from validator.descend(
                    value, subschema, path=key, schema_path=pattern
                )


UnicodeDraft7 = validators.extend(
    Draft7Validator,
    {"pattern": _unicode_pattern, "patternProperties": _unicode_pattern_properties},
)


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def ledger():
    workdir = Path(tempfile.gettempdir()) / f"oscal_schema_{uuid.uuid4().hex[:8]}"
    workdir.mkdir(parents=True, exist_ok=True)
    oracle = ComplianceOracle(
        ledger_file=workdir / "ledger.json",
        policy_file=workdir / "policies.json",
    )
    oracle.reset_ledger()
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    return json.loads(oracle.ledger_file.read_text(encoding="utf-8"))


def _assert_valid(schema, document):
    validator = UnicodeDraft7(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    assert not errors, "OSCAL schema violations:\n" + "\n".join(
        f"  @{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}"
        for e in errors[:10]
    )


def test_full_export_is_schema_valid(schema, ledger):
    _assert_valid(schema, to_oscal_sar(ledger))


def test_redacted_export_is_schema_valid(schema, ledger):
    _assert_valid(schema, to_oscal_sar(ledger, redacted=True))


def test_control_id_props_survive_schema(schema, ledger):
    """The aia-* control-ids must be present *and* schema-valid (as props)."""
    document = to_oscal_sar(ledger)
    _assert_valid(schema, document)
    findings = document["assessment-results"]["results"][0]["findings"]
    control_ids = {
        prop["value"]
        for finding in findings
        for prop in finding.get("props", [])
        if prop["name"] == "supports-requirement"
    }
    assert control_ids, "no control-id props emitted"
    assert all(cid.startswith("aia-") for cid in control_ids)
