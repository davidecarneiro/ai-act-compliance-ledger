"""Credit-scoring case (WP4): the pipeline follows the protocol, and the
ledger it produces meets the acceptance criteria."""

from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import credit_case as cc  # noqa: E402
from artifact_store import ArtifactStore, verify_ledger_artifacts  # noqa: E402
from ledger_store import read_ledger  # noqa: E402

COMMITTED_RUNS = sorted((cc.HERE.parents[1] / "experiments" / "article" / "wp4").glob("run_*"))


@pytest.fixture(scope="module")
def frame():
    return cc.parse_dataset(cc.read_dataset_bytes())


@pytest.fixture(scope="module")
def case_run(tmp_path_factory):
    """One complete run of the case under the committed policy."""
    return cc.run(out_dir=tmp_path_factory.mktemp("wp4"))


def test_the_archive_is_checked_against_its_digest(tmp_path):
    copy = tmp_path / "copy.zip"
    with zipfile.ZipFile(copy, "w") as z:
        z.writestr("german.data", cc.read_dataset_bytes())
    with pytest.raises(ValueError):
        cc.read_dataset_bytes(copy)


def test_partition_is_stratified_disjoint_and_seeded(frame):
    parts = cc.partition(frame, cc.MAIN_SEED)
    assert {k: len(v) for k, v in parts.items()} == {"train": 600, "validation": 200, "test": 200}
    every = parts["train"] + parts["validation"] + parts["test"]
    assert sorted(every) == list(range(1000))
    good = frame["good"].to_numpy()
    assert [int(good[parts[k]].sum()) for k in ("train", "validation", "test")] == [420, 140, 140]
    assert parts == cc.partition(frame, cc.MAIN_SEED)
    assert parts != cc.partition(frame, cc.PILOT_SEED)


def test_reweighing_equalises_the_weighted_label_rate(frame):
    rows = frame.iloc[cc.partition(frame, cc.MAIN_SEED)["train"]]
    group, y = cc.young(rows), rows["good"].to_numpy()
    weights = cc.reweighing_weights(group, y)
    rates = [np.average(y[group == g], weights=weights[group == g]) for g in (False, True)]
    assert rates[0] == pytest.approx(rates[1]) == pytest.approx(y.mean())


def test_psi_is_zero_without_shift_and_grows_with_it():
    rng = np.random.default_rng(0)
    reference = rng.uniform(size=200)
    assert cc.psi(reference, reference)["psi"] == 0.0
    assert cc.psi(reference, reference[:50] * 0.3)["psi"] > cc.psi(reference, reference[:50])["psi"]


def test_batches_follow_the_protocol(frame):
    test = cc.partition(frame, cc.MAIN_SEED)["test"]
    batches = cc.draw_batches(frame, test)
    assert len(batches) == 6
    assert all(len(b["indices"]) == cc.BATCH_SIZE == len(set(b["indices"])) for b in batches)
    assert all(set(b["indices"]) <= set(test) for b in batches)
    counts = [b["subgroup_count"] for b in batches]
    assert counts[2:] == [25, 33, 40, 48]           # half up: 32.5 -> 33
    in_group = frame["checking_status"] == cc.DRIFT_VALUE
    assert [int(in_group.iloc[b["indices"]].sum()) for b in batches] == counts
    assert batches == cc.draw_batches(frame, test)


@pytest.mark.parametrize("pilot,expected", [(0.73494, 0.68), (0.80, 0.75), (0.759999, 0.70)])
def test_calibration_rule(pilot, expected):
    assert cc.calibrated_min_precision(pilot) == expected


def test_committed_policy_matches_the_calibration_of_the_committed_pilot():
    pilots = sorted((cc.OUT_DIR).glob("pilot_*.json")) or sorted(
        (cc.HERE.parents[1] / "experiments" / "article" / "wp4").glob("pilot_*.json"))
    pilot = json.loads(pilots[0].read_text(encoding="utf-8"))
    policy = json.loads(cc.POLICY_FILE.read_text(encoding="utf-8"))
    assert policy == pilot["policy"]
    assert policy["min_precision"] == pilot["calibration"]["min_precision"]


def test_the_run_meets_every_acceptance_criterion(case_run):
    summary = json.loads((case_run / "summary.json").read_text(encoding="utf-8"))
    assert all(summary["acceptance"].values()), summary["acceptance"]
    assert len(summary["events"]) == 16
    assert summary["metrics_recomputed"] == {"total": 10, "match": 10}


def test_the_run_reproduces_the_committed_one(case_run):
    if not COMMITTED_RUNS:
        pytest.skip("no committed run")
    mine = json.loads((case_run / "summary.json").read_text(encoding="utf-8"))
    published = json.loads((COMMITTED_RUNS[0] / "summary.json").read_text(encoding="utf-8"))
    assert mine["policy_id"] == published["policy_id"]
    for name in ("decisions", "partition_sizes"):
        assert mine[name] == published[name]
    assert [(e["decision"], e["rule_id"]) for e in mine["events"]] == [
        (e["decision"], e["rule_id"]) for e in published["events"]]
    for version in ("v1", "v2"):
        for metric, value in published["validation_metrics"][version].items():
            assert mine["validation_metrics"][version][metric] == pytest.approx(value, abs=1e-6)
    for a, b in zip(mine["batches"], published["batches"]):
        assert a["psi"] == pytest.approx(b["psi"], abs=1e-6)


def test_a_swapped_model_is_caught(case_run, tmp_path):
    folder = tmp_path / "copy"
    shutil.copytree(case_run, folder)
    ledger = read_ledger(folder / "ledger.jsonl")
    store = ArtifactStore(folder / "store")
    v1, v2 = (r["artifact_hash"] for r in ledger if r["event_type"] == "model_trained")
    # Put the v1 model's bytes where the v2 model should be.
    store.path_for(v2).write_bytes(store.path_for(v1).read_bytes())
    statuses = {a["status"] for a in verify_ledger_artifacts(ledger, store)}
    assert "content-mismatch" in statuses
    checked = cc.recompute_metrics(ledger, store)
    assert not all(m["match"] for m in checked)


def test_metrics_in_the_ledger_are_the_computed_ones(case_run, frame):
    ledger = read_ledger(case_run / "ledger.jsonl")
    parts = cc.partition(frame, cc.MAIN_SEED)
    for version, mitigated in (("v1", False), ("v2", True)):
        expected = cc.policy_metrics(cc.train(frame, parts, mitigated), frame, parts["validation"])
        run_id = cc.RUNS[0] if version == "v1" else cc.RUNS[1]
        recorded = [r["metrics"] for r in ledger
                    if r["run_id"] == run_id and r["event_type"] == "model_validation"]
        assert recorded == [expected]
