"""Test of the MultiFlow to Oracle bridge without a Kafka broker.

Simulates the MultiFlow stream (JSON messages carrying `csv_data`, the format the
node service publishes and the Faust apps consume) in two phases: 60 stationary
rows and 40 rows with pronounced drift. Checks that the bridge produces chained
evidence, that drift is escalated and that the chain verifies, and that input
it cannot use is skipped and counted instead of stopping the bridge or
producing evidence. Each test writes to its own temporary folder.

Run:  python3 -m pytest test_bridge.py -q     (from multiflow_bridge/, with
ORACLE_PATH pointing at ../compliance_ledger_sim and a temporary OUT_DIR)
"""

import json
import os
import random
import sys
import tempfile

os.environ["OUT_DIR"] = tempfile.mkdtemp(prefix="bridge_test_")
os.environ.setdefault(
    "ORACLE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "compliance_ledger_sim"),
)
sys.path.insert(0, os.environ["ORACLE_PATH"])

import bridge  # noqa: E402


def fake_stream():
    """60 stationary rows (reference plus two batches) and 40 with strong drift."""
    rng = random.Random(42)
    for _ in range(60):
        yield {"csv_data": ",".join(f"{rng.gauss(10, 1):.3f}" for _ in range(4))}
    for _ in range(40):
        yield {"csv_data": ",".join(f"{rng.gauss(25, 1):.3f}" for _ in range(4))}


def test_bridge_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "OUT_DIR", str(tmp_path))
    oracle = bridge.run(fake_stream())
    ledger = json.load(open(tmp_path / "ledger.json"))

    # 100 rows = 20 reference rows plus four batches of 20
    assert len(ledger) == 4, f"esperados 4 eventos, obtidos {len(ledger)}"

    # stationary batches approved, drifting batches escalated
    decisions = [r["decision"] for r in ledger]
    assert decisions[:2] == ["approved", "approved"], decisions
    assert decisions[2:] == ["escalated", "escalated"], decisions
    assert "drift score" in ledger[2]["reason"]

    # normative coverage of the monitoring event (the articles used in the thesis)
    assert ledger[0]["requirements_covered"] == [
        "Art.10(3)", "Art.12", "Art.14", "Art.15", "Art.72"]

    # intact chain: parent and chain hashes linked, full verification
    assert ledger[1]["parent_hash"] == ledger[0]["chain_hash"]
    report = oracle.verify_chain()
    assert report.valid == report.total == 4

    # MultiFlow provenance recorded in the artefact hash (the source event)
    assert ledger[0]["scenario_id"].startswith("multiflow-phd_kafka-batch-")


def test_invalid_message_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "OUT_DIR", str(tmp_path))
    stats = {}
    oracle = bridge.run(iter([{"csv_data": "this,is,not,numeric"}] * 50), stats)
    assert oracle.verify_chain().total == 0
    assert stats["unusable"] == 50 and stats["batches"] == 0


def test_kafka_payloads_that_are_not_json_do_not_stop_the_consumer():
    """The deserializer runs inside the Kafka consumer, before any other check;
    raising there stopped the bridge on the first non-JSON message."""
    assert bridge.decode_message(b"garbage") is None
    assert bridge.decode_message(b"\xff\xfe") is None
    assert bridge.decode_message(b'{"csv_data": "1,2,3"}') == {"csv_data": "1,2,3"}


def test_malformed_input_is_skipped_not_fatal(tmp_path, monkeypatch):
    """None, a non-object, NaN, infinity, an empty or non-text field and rows of
    the wrong width are interleaved with 60 valid rows. Before the checks, None
    raised AttributeError, a short row raised IndexError, and NaN still produced
    an event."""
    monkeypatch.setattr(bridge, "OUT_DIR", str(tmp_path))
    rng = random.Random(7)
    valid = [{"csv_data": ",".join(f"{rng.gauss(10, 1):.3f}" for _ in range(4))}
             for _ in range(60)]
    bad = [None, "1,2,3,4", {"csv_data": "nan,1,2,3"}, {"csv_data": "1,inf,2,3"},
           {"csv_data": ""}, {"csv_data": ["1", "2"]}, {"csv_data": True}, {}]
    wrong_width = [{"csv_data": "1,2"}, {"csv_data": "1,2,3,4,5"}]
    stream = valid[:25] + bad + valid[25:45] + wrong_width + valid[45:] + valid[:5]

    stats = {}
    oracle = bridge.run(iter(stream), stats)
    ledger = json.load(open(tmp_path / "ledger.json"))

    # 65 valid rows: 20 of reference, two batches of 20, five left over
    assert len(ledger) == 2
    assert stats == {"batches": 2, "unusable": len(bad), "wrong_width": 2,
                     "reference_rows": 20, "left_over": 5}
    report = oracle.verify_chain()
    assert report.valid == report.total == 2
