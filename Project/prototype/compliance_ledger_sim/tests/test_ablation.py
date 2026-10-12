"""WP3 ablation: the arms differ only in what they persist, and the
benchmark's rotation is balanced."""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bench_ablation as bench  # noqa: E402
from ablation_arms import (  # noqa: E402
    ARM_NAMES,
    bench_key,
    make_arms,
    verify_anchored,
    verify_arm,
    verify_hash_chain,
    verify_signed,
)
from ledger_store import read_ledger  # noqa: E402


@pytest.fixture()
def arms(tmp_path):
    policy = json.loads(bench.POLICY_FILE.read_text(encoding="utf-8"))
    policy_file = tmp_path / "policies.json"
    policy_file.write_text(json.dumps(policy), encoding="utf-8")
    key = bench_key(tmp_path)
    made = make_arms(tmp_path, policy_file, policy, key, interval=4)
    yield made, key, tmp_path
    for arm in made.values():
        arm.close()


def _run(arms, n=12):
    out = {name: [] for name in ARM_NAMES}
    for i in range(n):
        event = bench.w2_event(i)
        for name, arm in arms.items():
            out[name].append(arm.process(json.loads(json.dumps(event))))
    return out


def test_every_arm_takes_the_same_decision(arms):
    made, _key, _folder = arms
    out = _run(made)
    decisions = {name: [(r["decision"], r.get("rule_id")) for r in rows] for name, rows in out.items()}
    assert decisions["A"] == decisions["B0"] == decisions["B"] == decisions["Bplus"]
    assert {d for d, _ in decisions["A"]} == {"approved", "rejected", "escalated", "recorded"}


def test_b0_differs_from_b_only_by_the_signature(arms):
    made, _key, _folder = arms
    out = _run(made, n=6)
    for b0, b in zip(out["B0"], out["B"]):
        assert "issuer_signature" not in b0 and "issuer_signature" in b
        variable = {"evidence_id", "timestamp", "record_hash", "chain_hash", "parent_hash",
                    "issuer_signature"}
        assert {k: v for k, v in b0.items() if k not in variable} == \
               {k: v for k, v in b.items() if k not in variable}


def test_every_output_verifies_and_anchors_are_published(arms):
    made, key, folder = arms
    _run(made, n=12)
    for arm in made.values():
        arm.close()
    reports = {name: verify_arm(name, folder, key) for name in ARM_NAMES}
    assert all(r["valid"] for r in reports.values()), reports
    assert reports["Bplus"]["anchors"] == 3


def test_what_each_verifier_catches(arms):
    made, key, folder = arms
    _run(made, n=12)
    for arm in made.values():
        arm.close()
    b = read_ledger(folder / "B.jsonl")
    # Change a field: the hash chain sees it.
    changed = [dict(r) for r in b]
    changed[5]["decision"] = "approved" if changed[5]["decision"] != "approved" else "rejected"
    assert not verify_hash_chain(changed)["valid"]
    # Change it and recompute every hash, without the key: only the signature sees it.
    from canonical import record_body_bytes
    from simulator import sha256_hex
    parent = "0" * 64
    for r in changed:
        r["parent_hash"] = parent
        r["record_hash"] = sha256_hex(record_body_bytes(r))
        r["chain_hash"] = sha256_hex((parent + r["record_hash"]).encode("utf-8"))
        parent = r["chain_hash"]
    assert verify_hash_chain(changed)["valid"]
    assert not verify_signed(changed, key)["valid"]
    # Truncate the suffix: only the anchor sees it.
    bplus = read_ledger(folder / "Bplus.jsonl")
    anchors = folder / "external" / "anchors.jsonl"
    assert verify_signed(bplus[:9], key)["valid"]
    assert not verify_anchored(bplus[:9], key, anchors)["valid"]
    assert verify_anchored(bplus[:12], key, anchors)["valid"]


def test_williams_rotation_is_balanced():
    rows = bench.WILLIAMS
    for position in range(4):
        assert sorted(row[position] for row in rows) == [0, 1, 2, 3]
    pairs = [(row[k], row[k + 1]) for row in rows for k in range(3)]
    assert sorted(pairs) == sorted(p for p in itertools.permutations(range(4), 2))


def test_small_benchmark_runs_and_summarises(tmp_path):
    result = bench.paired_rounds("W1", rounds=2, events=8, warmup=2, workdir=tmp_path, interval=4)
    assert len(result["observations"]) == 2 * 8 * 4
    assert all(all(v.values()) for v in result["verification"].values())
    summary = bench.summarise(result, rounds=2)
    assert set(summary["paired_differences"]) == {"B0-A", "B-B0", "B-A", "Bplus-B"}
    assert len(bench.table_t9({"W1": summary})) == 2 + 8
