"""WP7 runner: the prepared inputs verify (in Python and in the Go chaincode),
and measure/summarise work end to end with a stand-in client."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_wp7 as rw  # noqa: E402
import batch_anchor as ba  # noqa: E402  (on the path through run_wp7)
from ledger_store import read_ledger  # noqa: E402
from keys import load_or_create_key  # noqa: E402
from simulator import ISSUER_ID_V2  # noqa: E402

CHAINCODE = HERE.parent / "chaincode"


@pytest.fixture(scope="module")
def prep(tmp_path_factory):
    folder = tmp_path_factory.mktemp("wp7") / "prep"
    rw.prepare(folder, small=True)
    return folder


def _lines(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_rotated_order():
    assert rw.rotated_order(1) == [1, 10, 50, 100, 500]
    assert rw.rotated_order(2) == [10, 50, 100, 500, 1]
    assert rw.rotated_order(3) == [50, 100, 500, 1, 10]


def test_prepared_anchors_and_pairs_verify(prep):
    key = load_or_create_key(ISSUER_ID_V2)
    stream = read_ledger(prep / "stream" / "stream.jsonl")
    for n in (10, 50):
        for r in (1, 2, 3):
            anchors = _lines(prep / f"anchors_n{n}_r{r}.jsonl")
            assert {a["statement"]["stream"] for a in anchors} == {f"n{n}-r{r}"}
            assert ba.verify_batches(stream, anchors, key.public_key)["valid"]
    anchors = {a["statement"]["first_seq"]: a["statement"] for a in _lines(prep / "anchors_n50_r1.jsonl")}
    for pair in _lines(prep / "inclusion_pairs.jsonl"):
        statement = anchors[pair["proof"]["first_seq"]]
        assert ba.verify_record_inclusion(pair["record"], pair["proof"], statement)["included"]
    chain = _lines(prep / "chain_warmup.jsonl") + sum(
        (_lines(prep / f"chain_r{r}.jsonl") for r in (1, 2, 3)), [])
    assert len(chain) == 31 and chain[0]["parent_hash"] == "0" * 64
    assert all(b["parent_hash"] == a["chain_hash"] for a, b in zip(chain, chain[1:]))
    assert len(_lines(prep / "anchors_credit_case.jsonl")) == 16


@pytest.mark.skipif(shutil.which("go") is None, reason="Go not installed")
def test_go_chaincode_accepts_the_prepared_inputs(prep):
    env = {**os.environ, "INTEROP_WP7_PREP": str(prep), "GOFLAGS": "-mod=vendor"}
    run = subprocess.run(["go", "test", "-run", "TestPreparedWP7Inputs", "-v", "."],
                         cwd=CHAINCODE, env=env, capture_output=True, text=True)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    assert "--- PASS: TestPreparedWP7Inputs" in run.stdout


def test_measure_and_summarise_with_a_stand_in_client(prep, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ANCHORBENCH_STATE", str(tmp_path / "state.json"))
    client = [sys.executable, str(HERE / "fake_anchorbench.py")]
    result_path = rw.measure(prep, "validation-fake", client=client, out_dir=tmp_path)
    result = json.loads(result_path.read_text())
    assert result["counts_for_article"] is False
    assert result["governance_check"]["refused"]
    assert result["governance_check"]["code"] == "ENDORSEMENT_POLICY_FAILURE"
    counted = [s for s in result["steps"] if s.get("counted")]
    assert sorted({(s["n"], s["rep"]) for s in counted}) == sorted(
        (n, r) for n in (1, 10, 50) for r in (1, 2, 3))
    exported = list(tmp_path.glob("credit_case_validation-fake_*/onchain_anchors.json"))
    assert exported and len(json.loads(exported[0].read_text())["anchors"]) == 16
    c = json.loads((exported[0].parent / "configuration_c.json").read_text())
    assert c["clean_check"]["valid"] and c["all_as_expected"]
    assert {r["observed"] for r in c["tamper"].values()} == {"detected"}
    assert c["q12"]["answerable"] == "yes" and c["q12"]["answer"]["organisations"] == ["Org1MSP"]

    summary = json.loads(rw.summarise([result_path], out_dir=tmp_path).read_text())
    per_n = summary["runs"][0]["per_n"]
    # 2 ms per call: N = 1 covers 500 records/s, N = 10 about 5,000.
    assert per_n["1"]["throughput_records_per_s"]["median"] == pytest.approx(500, rel=0.01)
    assert per_n["10"]["throughput_records_per_s"]["median"] == pytest.approx(5000, rel=0.01)
    assert per_n["10"]["durable_latency_ms_per_record"]["n"] == 3 * 100
    assert summary["runs"][0]["verify_inclusion_included"] == summary["runs"][0]["verify_inclusion_calls"]


def test_batch_wait():
    assert rw.batch_wait_s(100, 10.0) == {"mean": 4.95, "max": 9.9}
