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

import pytest

os.environ["OUT_DIR"] = tempfile.mkdtemp(prefix="bridge_test_")
os.environ.setdefault(
    "ORACLE_PATH",
    os.path.join(os.path.dirname(__file__), "..", "compliance_ledger_sim"),
)
sys.path.insert(0, os.environ["ORACLE_PATH"])

import bridge  # noqa: E402
from ledger_store import read_ledger  # noqa: E402


def _ledger(folder):
    return read_ledger(folder / bridge.LEDGER_FILE)


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
    ledger = _ledger(tmp_path)

    # 100 rows = 20 reference rows plus four batches of 20
    assert len(ledger) == 4, f"esperados 4 eventos, obtidos {len(ledger)}"

    # stationary batches approved, drifting batches escalated
    decisions = [r["decision"] for r in ledger]
    assert decisions[:2] == ["approved", "approved"], decisions
    assert decisions[2:] == ["escalated", "escalated"], decisions
    assert "drift score" in ledger[2]["reason"]

    # normative coverage of the monitoring event. Schema version 1 (the thesis)
    # attached the bias metric to Art. 10(3); version 2 attaches it to
    # Art. 10(2)(f) and names the field supports_requirements.
    from canonical import CURRENT_SCHEMA_VERSION
    from simulator import requirements_of
    bias = "Art.10(3)" if CURRENT_SCHEMA_VERSION == 1 else "Art.10(2)(f)"
    assert requirements_of(ledger[0]) == sorted(
        [bias, "Art.12", "Art.14", "Art.15", "Art.72"])

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
    ledger = _ledger(tmp_path)

    # 65 valid rows: 20 of reference, two batches of 20, five left over
    assert len(ledger) == 2
    assert stats == {"batches": 2, "unusable": len(bad), "wrong_width": 2,
                     "reference_rows": 20, "left_over": 5}
    report = oracle.verify_chain()
    assert report.valid == report.total == 2


def _messages():
    rng = random.Random(3)
    # Drift grows from row 10 without saturating, so every batch has its own score:
    # a row shifted between batches changes the recorded reasons.
    return [{"csv_data": ",".join(f"{rng.gauss(10 + max(0, i - 10) * 0.025, 1):.3f}" for _ in range(3))}
            for i in range(130)]


def _summary(folder):
    return [(r["scenario_id"], r["decision"], r["reason"]) for r in _ledger(folder)]


def test_restart_resumes_with_the_same_reference(tmp_path, monkeypatch):
    """A bridge stopped mid-stream and started again records exactly what an
    uninterrupted bridge records: same batches, same decisions, same scores."""
    whole, split = tmp_path / "whole", tmp_path / "split"
    monkeypatch.setattr(bridge, "OUT_DIR", str(whole))
    bridge.run(iter(_messages()))
    monkeypatch.setattr(bridge, "OUT_DIR", str(split))
    bridge.run(iter(_messages()[:47]))          # stops inside the second batch
    state = bridge.load_state()
    assert len(state["reference"]) == 20 and state["batch_n"] == 1 and len(state["batch"]) == 7
    oracle = bridge.run(iter(_messages()[47:]))
    assert _summary(split) == _summary(whole)
    assert oracle.verify_chain().valid == len(_summary(whole)) == 5
    assert len({reason for _, _, reason in _summary(whole)}) == 5   # five distinct scores


def test_messages_delivered_again_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(bridge, "OUT_DIR", str(tmp_path))
    positioned = [(("phd_kafka", 0, i), m) for i, m in enumerate(_messages())]
    bridge.run(iter(positioned[:60]))
    bridge.run(iter(positioned[30:]))           # Kafka redelivers 30-59 after a restart
    whole = tmp_path / "whole"
    monkeypatch.setattr(bridge, "OUT_DIR", str(whole))
    bridge.run(iter(positioned))
    monkeypatch.setattr(bridge, "OUT_DIR", str(tmp_path))
    assert _summary(tmp_path) == _summary(whole)


def _crash_on(monkeypatch, target, attribute, when):
    """Make target.attribute raise the first time when(*args) holds."""
    original = getattr(target, attribute)
    fired = {"done": False}

    def wrapper(*args, **kwargs):
        if not fired["done"] and when(*args, **kwargs):
            fired["done"] = True
            raise RuntimeError("simulated stop")
        return original(*args, **kwargs)
    monkeypatch.setattr(target, attribute, wrapper)


def _whole(tmp_path, monkeypatch):
    whole = tmp_path / "whole"
    monkeypatch.setattr(bridge, "OUT_DIR", str(whole))
    bridge.run(iter(_messages()))
    return _summary(whole)


def test_a_batch_complete_before_a_stop_is_recorded_once(tmp_path, monkeypatch):
    """Stop between saving the complete batch and recording it: the restart
    records it, once."""
    expected = _whole(tmp_path, monkeypatch)
    run_dir = tmp_path / "run"
    monkeypatch.setattr(bridge, "OUT_DIR", str(run_dir))
    from simulator import ComplianceOracle
    _crash_on(monkeypatch, ComplianceOracle, "process_mlops_event",
              lambda self, event: event["scenario_id"].endswith("batch-0002"))
    with pytest.raises(RuntimeError):
        bridge.run(iter(_messages()[:70]))
    assert bridge.load_state()["pending"]["batch_n"] == 2
    monkeypatch.undo()
    monkeypatch.setattr(bridge, "OUT_DIR", str(run_dir))
    bridge.run(iter(_messages()[60:]))         # rows 60-69 were already taken
    assert _summary(run_dir) == expected


def test_a_batch_recorded_before_the_state_was_cleared_is_not_recorded_twice(tmp_path, monkeypatch):
    """Stop after recording a batch, before the state says so: the restart
    finds it in the ledger and does not record it again."""
    expected = _whole(tmp_path, monkeypatch)
    run_dir = tmp_path / "run"
    monkeypatch.setattr(bridge, "OUT_DIR", str(run_dir))
    def after_record(state):
        # The save that clears pending after batch 2 was recorded.
        return state.get("pending") is None and state["batch_n"] == 2
    _crash_on(monkeypatch, bridge, "save_state", after_record)
    with pytest.raises(RuntimeError):
        bridge.run(iter(_messages()[:70]))
    assert bridge.load_state()["pending"]["batch_n"] == 2
    monkeypatch.undo()
    monkeypatch.setattr(bridge, "OUT_DIR", str(run_dir))
    bridge.run(iter(_messages()[60:]))
    assert _summary(run_dir) == expected
