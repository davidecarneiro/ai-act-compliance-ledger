"""Append-only ledger store (WP1 of the article plan).

The ``.jsonl`` store appends one line per record and keeps the chain head in a
side file, so an append never reads the ledger. These tests cover the normal
path, the crash cases the head must survive (torn line, record written but not
acknowledged, lost head) and the cases it must refuse (truncation, a line that
does not link).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ledger_store import (  # noqa: E402
    GENESIS_HASH,
    AppendOnlyStore,
    JsonArrayStore,
    LedgerCorrupted,
    open_store,
    read_ledger,
)
from oscal_exporter import to_oscal_sar  # noqa: E402
from scenarios import build_scenarios  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402

POLICY = {
    "min_precision": 0.80,
    "max_demographic_parity_diff": 0.05,
    "require_human_approval_for_high_risk": True,
    "drift_alert_threshold": 0.15,
}


def _workdir() -> Path:
    d = Path(tempfile.gettempdir()) / f"store_test_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "policies.json").write_text(json.dumps(POLICY), encoding="utf-8")
    return d


def _oracle(workdir: Path, name: str = "ledger.jsonl") -> ComplianceOracle:
    return ComplianceOracle(
        policy_file=workdir / "policies.json", ledger_file=workdir / name
    )


def _event(i: int) -> dict:
    return {
        "scenario_id": f"store-{i}",
        "event_type": "model_validation",
        "artifact_id": f"m-{i}",
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {"precision": 0.95, "demographic_parity_diff": 0.01},
    }


def _lines(path: Path) -> list[bytes]:
    return path.read_bytes().splitlines(keepends=True)


# ----------------------------------------------------------------------
# Normal path
# ----------------------------------------------------------------------


def test_suffix_selects_the_store():
    assert isinstance(open_store(Path("x/ledger.jsonl")), AppendOnlyStore)
    assert isinstance(open_store(Path("x/ledger.json")), JsonArrayStore)


def test_append_only_ledger_verifies_and_matches_its_head():
    wd = _workdir()
    oracle = _oracle(wd)
    for event in build_scenarios():
        oracle.process_mlops_event(event)
    path = wd / "ledger.jsonl"
    assert len(_lines(path)) == 6
    report = oracle.verify_chain()
    assert report.valid == report.total == 6
    head = json.loads((wd / "ledger.jsonl.head").read_text())
    records = read_ledger(path)
    assert head == {
        "seq": 6,
        "chain_hash": records[-1]["chain_hash"],
        "offset": path.stat().st_size,
    }
    # The same records, as a JSON array, verify and export like any ledger.
    assert oracle.verify_chain(records).is_valid
    assert "chain_valid" in json.dumps(to_oscal_sar(records))


def test_append_does_not_read_earlier_records():
    # The head, not the file, gives the parent: an append succeeds even after
    # an earlier line was altered, and verification is what reports it.
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(4):
        oracle.process_mlops_event(_event(i))
    path = wd / "ledger.jsonl"
    lines = _lines(path)
    # "approved" and "rejected" have the same length, so this models an
    # in-place edit that leaves the file size, and so the head, consistent.
    assert b'"decision":"approved"' in lines[1]
    lines[1] = lines[1].replace(b'"decision":"approved"', b'"decision":"rejected"')
    path.write_bytes(b"".join(lines))
    oracle.process_mlops_event(_event(4))
    report = oracle.verify_chain()
    assert report.total == 5 and not report.is_valid
    assert report.first_invalid_index == 1


def test_reset_empties_the_ledger_and_the_head():
    wd = _workdir()
    oracle = _oracle(wd)
    oracle.process_mlops_event(_event(0))
    oracle.reset_ledger()
    assert (wd / "ledger.jsonl").read_bytes() == b""
    assert oracle.store.head() == (0, GENESIS_HASH)
    oracle.process_mlops_event(_event(1))
    assert oracle.verify_chain().valid == 1


def test_records_survive_without_fsync_option():
    wd = _workdir()
    store = AppendOnlyStore(wd / "nofsync.jsonl", fsync=False)
    store.ensure()
    oracle = _oracle(wd, "nofsync.jsonl")
    oracle.store = store
    for i in range(3):
        oracle.process_mlops_event(_event(i))
    assert oracle.verify_chain().valid == 3


# ----------------------------------------------------------------------
# Crash cases the head must survive
# ----------------------------------------------------------------------


def test_torn_last_line_is_cut_off_on_the_next_append():
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(3):
        oracle.process_mlops_event(_event(i))
    path = wd / "ledger.jsonl"
    with open(path, "ab") as fh:
        fh.write(b'{"evidence_id":"ev-torn","parent_ha')  # crash mid-write
    assert len(read_ledger(path)) == 3  # readers skip the torn line
    oracle.process_mlops_event(_event(3))
    assert len(_lines(path)) == 4
    assert oracle.verify_chain().valid == 4


def test_record_written_but_not_acknowledged_is_rolled_forward():
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(3):
        oracle.process_mlops_event(_event(i))
    head_path = wd / "ledger.jsonl.head"
    stale = head_path.read_text()
    oracle.process_mlops_event(_event(3))
    head_path.write_text(stale)  # crash after the fsync, before the head
    oracle.process_mlops_event(_event(4))
    report = oracle.verify_chain()
    assert report.valid == report.total == 5
    assert oracle.store.head()[0] == 5


def test_missing_head_is_rebuilt_from_the_file():
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(3):
        oracle.process_mlops_event(_event(i))
    (wd / "ledger.jsonl.head").unlink()
    oracle.process_mlops_event(_event(3))
    assert oracle.verify_chain().valid == 4
    assert oracle.store.head()[0] == 4


# ----------------------------------------------------------------------
# Cases the store must refuse
# ----------------------------------------------------------------------


def test_truncation_is_refused_although_the_prefix_still_verifies():
    # Attack T6 of the plan: removing the last record leaves a chain that
    # verifies. The head is what notices; the store refuses to write on it.
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(4):
        oracle.process_mlops_event(_event(i))
    path = wd / "ledger.jsonl"
    path.write_bytes(b"".join(_lines(path)[:-1]))
    assert oracle.verify_chain().valid == 3  # the chain alone cannot tell
    with pytest.raises(LedgerCorrupted, match="missing from the end"):
        oracle.process_mlops_event(_event(4))


def test_appended_line_that_does_not_link_is_refused():
    wd = _workdir()
    oracle = _oracle(wd)
    for i in range(2):
        oracle.process_mlops_event(_event(i))
    path = wd / "ledger.jsonl"
    first = _lines(path)[0]
    with open(path, "ab") as fh:
        fh.write(first)  # a complete line, but it does not link to the head
    with pytest.raises(LedgerCorrupted, match="does not link"):
        oracle.process_mlops_event(_event(2))


def test_malformed_head_is_refused():
    wd = _workdir()
    oracle = _oracle(wd)
    oracle.process_mlops_event(_event(0))
    (wd / "ledger.jsonl.head").write_text('{"seq": "one"}')
    with pytest.raises(LedgerCorrupted):
        oracle.process_mlops_event(_event(1))


# ----------------------------------------------------------------------
# Concurrency
# ----------------------------------------------------------------------

CHILD = r'''
import sys
from pathlib import Path
sys.path.insert(0, {root!r})
from simulator import ComplianceOracle
oracle = ComplianceOracle(policy_file=Path({policy!r}), ledger_file=Path({ledger!r}))
for i in range({n}):
    oracle.process_mlops_event({{
        "scenario_id": "proc-{tag}-%d" % i,
        "event_type": "model_validation",
        "artifact_id": "m-{tag}-%d" % i,
        "artifact_type": "model",
        "pipeline_stage": "validation",
        "risk_level": "high",
        "human_approval": True,
        "metrics": {{"precision": 0.95, "demographic_parity_diff": 0.01}},
    }})
'''


def test_three_processes_append_without_losing_records():
    wd = _workdir()
    ledger = wd / "ledger.jsonl"
    _oracle(wd)  # creates the file and its head
    n = 15
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD.format(
                root=str(ROOT), policy=str(wd / "policies.json"),
                ledger=str(ledger), n=n, tag=tag)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for tag in ("a", "b", "c")
    ]
    for p in procs:
        err = p.communicate()[1].decode()
        assert p.returncode == 0, err[:800]
    records = read_ledger(ledger)
    assert len(records) == 3 * n
    assert len({r["evidence_id"] for r in records}) == 3 * n
    assert _oracle(wd).verify_chain().valid == 3 * n
