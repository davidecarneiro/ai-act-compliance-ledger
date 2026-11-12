"""Batch anchoring (WP7): Merkle tree of RFC 9162, signed batch anchors, and
inclusion proofs; and the fixtures the Go tests read are current."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import batch_anchor as ba  # noqa: E402
import merkle  # noqa: E402
from canonical import SCHEMA_V2  # noqa: E402
from keys import load_or_create_key  # noqa: E402
from simulator import ComplianceOracle  # noqa: E402

CHAINCODE = ROOT.parent / "fabric_migration" / "chaincode"

# RFC 6962 reference data (certificate-transparency test leaves and roots).
CT_LEAVES = [b"", b"\x00", b"\x10", b"\x20\x21", b"\x30\x31", b"\x40\x41\x42\x43",
             bytes(range(0x50, 0x58)), bytes(range(0x60, 0x70))]
CT_ROOTS = [
    "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d",
    "fac54203e7cc696cf0dfcb42c92a1d9dbaf70ad9e621f4bd8d98662f00e3c125",
    "aeb6bcfe274b70a14fb067a5e5578264db0fa9b51af5e0ba159158f329e06e77",
    "d37ee418976dd95753c1c73862b9398fa2a2cf9b4ff0fdfe8b30cd95209614b7",
    "4e3bbb1f7b478dcfe71fb631631519a3bca12c9aefca1612bfce4c13a86264d4",
    "76e67dadbcdf1e10e1b74ddc608abd2f98dfb16fbce75277b5232a127f2087ef",
    "ddb89be403809e325750d3d263cd78929c2942b7942a34b77e122c9594a74c8c",
    "5dc9da79a70659a9ad559cb701ded9a2ab9d823aad2f4960cfe370eff4604328",
]


def test_roots_match_the_rfc6962_reference_values():
    for n in range(1, 9):
        assert merkle.root(CT_LEAVES[:n]).hex() == CT_ROOTS[n - 1]


@pytest.mark.parametrize("n", list(range(1, 41)))
def test_every_inclusion_proof_verifies_and_only_for_its_leaf(n):
    entries = [hashlib.sha256(str(i).encode()).digest() for i in range(n)]
    root = merkle.root(entries)
    for i in range(n):
        path = merkle.inclusion_path(i, entries)
        assert merkle.verify_inclusion(entries[i], i, n, path, root)
        assert len(path) <= max(1, n).bit_length()
        if n > 1:
            assert not merkle.verify_inclusion(entries[(i + 1) % n], i, n, path, root)
            assert not merkle.verify_inclusion(entries[i], (i + 1) % n, n, path, root)
    assert not merkle.verify_inclusion(entries[0], n, n, [], root)


@pytest.fixture()
def ledger(tmp_path):
    key = load_or_create_key("anchor-test", keys_dir=tmp_path / "keys")
    (tmp_path / "policies.json").write_text(json.dumps({
        "min_precision": 0.8, "max_demographic_parity_diff": 0.05,
        "require_human_approval_for_high_risk": True, "drift_alert_threshold": 0.15}))
    oracle = ComplianceOracle(policy_file=tmp_path / "policies.json",
                              ledger_file=tmp_path / "ledger.jsonl", issuer_key=key,
                              schema_version=SCHEMA_V2)
    oracle.reset_ledger()
    records = []
    for i in range(30):
        records.append(oracle.process_mlops_event({
            "scenario_id": f"s{i}", "event_type": "model_validation", "artifact_id": f"m{i}",
            "artifact_type": "model", "pipeline_stage": "validation", "risk_level": "high",
            "human_approval": True, "metrics": {"precision": 0.9, "demographic_parity_diff": 0.01}}))
    return records, key


def test_anchors_verify_against_the_ledger(ledger):
    records, key = ledger
    anchors = ba.make_anchors(records, 7, "t", key)
    assert [a["statement"]["size"] for a in anchors] == [7, 7, 7, 7, 2]
    assert ba.verify_batches(records, anchors, key.public_key)["valid"]


def test_anchors_catch_alteration_reordering_and_truncation(ledger):
    records, key = ledger
    anchors = ba.make_anchors(records, 7, "t", key)
    altered = copy.deepcopy(records)
    altered[3]["record_hash"] = "0" * 64
    assert not ba.verify_batches(altered, anchors, key.public_key)["valid"]
    swapped = records[:3] + [records[4], records[3]] + records[5:]
    assert not ba.verify_batches(swapped, anchors, key.public_key)["valid"]
    report = ba.verify_batches(records[:25], anchors, key.public_key)
    assert not report["valid"] and "truncated" in report["issues"][0]
    # Truncation after the last anchor is not seen: the window of the scheme.
    assert ba.verify_batches(records[:28], anchors[:4], key.public_key)["valid"]


def test_anchor_signature_and_contiguity(ledger):
    records, key = ledger
    anchors = ba.make_anchors(records, 7, "t", key)
    forged = copy.deepcopy(anchors)
    forged[1]["statement"]["merkle_root"] = "0" * 64
    assert not ba.verify_batches(records, forged, key.public_key)["valid"]
    assert not ba.verify_batches(records, [anchors[0], anchors[2]], key.public_key)["valid"]


def test_inclusion_proofs_for_every_record(ledger):
    records, key = ledger
    for n in (1, 7, 10, 30):
        anchors = ba.make_anchors(records, n, "t", key)
        for seq in range(1, len(records) + 1):
            proof = ba.inclusion_proof(records, seq, n, "t")
            anchor = anchors[(seq - 1) // n]["statement"]
            result = ba.verify_record_inclusion(records[seq - 1], proof, anchor)
            assert result == {"included": True, "seq": seq}
    altered = copy.deepcopy(records[5])
    altered["decision"] = "rejected"
    proof = ba.inclusion_proof(records, 6, 7, "t")
    anchor = ba.make_anchors(records, 7, "t", key)[0]["statement"]
    assert not ba.verify_record_inclusion(altered, proof, anchor)["included"]


def test_proof_size_grows_with_the_logarithm_of_the_batch(ledger):
    records, _key = ledger
    sizes = {n: ba.proof_size_bytes(ba.inclusion_proof(records, 1, n, "t")) for n in (1, 2, 4, 8, 16)}
    assert sizes[1] < sizes[2] < sizes[4] < sizes[8] < sizes[16]
    for n in (2, 4, 8, 16):                                   # one hash per doubling
        assert len(ba.inclusion_proof(records, 1, n, "t")["path"]) == n.bit_length() - 1


def test_go_fixtures_are_current():
    sys.path.insert(0, str(CHAINCODE))
    import gen_testdata_anchors as gen
    committed = json.loads((CHAINCODE / "testdata_anchors_v2.json").read_text(encoding="utf-8"))
    assert gen.anchors() == committed
    vectors = json.loads((CHAINCODE / "testdata_merkle_vectors.json").read_text(encoding="utf-8"))
    assert gen.vectors() == vectors
