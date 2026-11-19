"""The published JSON Schema of version 2 records (Supplementary Material S1)."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT = Path(__file__).resolve().parents[3]
SCHEMA = json.loads((PROJECT / "schemas" / "evidence_record_v2.schema.json").read_text(encoding="utf-8"))
LEDGER = PROJECT / "experiments" / "article" / "wp4" / "run_20261012T145744Z" / "ledger.jsonl"


@pytest.fixture(scope="module")
def records():
    return [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_schema_is_valid_draft_2020_12():
    Draft202012Validator.check_schema(SCHEMA)


def test_every_record_of_the_credit_case_validates(records):
    validator = Draft202012Validator(SCHEMA)
    assert records and all(validator.is_valid(r) for r in records)


@pytest.mark.parametrize("change", [
    lambda r: r.pop("payload_hash"),
    lambda r: r.update(rule_id="threshold.unknown"),
    lambda r: r.update(schema_version=1),
    lambda r: r.update(submitter_msp="Org1MSP"),
    lambda r: r.update(policy_id="client-x-policy"),
    lambda r: r.update(supports_requirements=["covers Art. 12"]),
])
def test_schema_rejects_records_outside_the_model(records, change):
    record = copy.deepcopy(records[0])
    change(record)
    assert not Draft202012Validator(SCHEMA).is_valid(record)
