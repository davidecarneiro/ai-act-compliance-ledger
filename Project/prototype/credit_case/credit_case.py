"""Credit-scoring case on the Statlog German Credit data (WP4 of the article plan).

The protocol is ``Project/protocols/wp4_credit_case.md``, recorded before any
model was trained; this module implements it and nothing else. Two commands::

    python3 credit_case.py pilot   # seed 7: calibrates min_precision, writes policy.json
    python3 credit_case.py run     # seed 42: the case, under the committed policy

Every policy metric that enters the ledger is computed here from the data;
none is typed in. ``recompute_metrics`` recomputes each one from the ledger and
the content-addressed store alone, as a third party holding them would.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import platform
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_FLOOR, Decimal
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

HERE = Path(__file__).resolve().parent
SIM = HERE.parent / "compliance_ledger_sim"
if str(SIM) not in sys.path:
    sys.path.insert(0, str(SIM))

from approvals import sign_approval  # noqa: E402
from artifact_store import ArtifactStore, StoredArtifact, verify_ledger_artifacts  # noqa: E402
from canonical import SCHEMA_V2  # noqa: E402
from keys import load_or_create_key, public_key_hex  # noqa: E402
from ledger_store import read_ledger  # noqa: E402
from paths import EXPERIMENTS_DIR  # noqa: E402
from reexecution import MATCH, reexecute_ledger  # noqa: E402
from simulator import ISSUER_ID_V2, METRIC_THRESHOLD_STAGES, ComplianceOracle  # noqa: E402

# ----------------------------------------------------------------------
# Fixed by the protocol
# ----------------------------------------------------------------------

DATASET_ZIP = HERE.parents[1] / "datasets" / "german_credit" / "statlog_german_credit_data.zip"
ZIP_SHA256 = "e12d9d5def6845c0622634a1cd2ab87fa470668c4298f1ec52a4e403376a435b"
DATA_SHA256 = "b21f3d81db8071257d5ff1deaeba1fd4303b62712e6fcc9715c7a86202cb5871"

COLUMNS = [
    "checking_status", "duration_months", "credit_history", "purpose",
    "credit_amount", "savings", "employment_since", "installment_rate",
    "personal_status_sex", "other_debtors", "residence_since", "property",
    "age", "other_installment_plans", "housing", "existing_credits", "job",
    "dependents", "telephone", "foreign_worker",
]
NUMERICAL = [
    "duration_months", "credit_amount", "installment_rate", "residence_since",
    "age", "existing_credits", "dependents",
]
CATEGORICAL = [c for c in COLUMNS if c not in NUMERICAL]

MAIN_SEED = 42
PILOT_SEED = 7
BATCH_SEED = 42
AGE_THRESHOLD = 25                     # under 25 vs 25 or over
DRIFT_ATTRIBUTE, DRIFT_VALUE = "checking_status", "A11"   # below 0 DM
DRIFT_FIXED_SHARES = (0.50, 0.65, 0.80, 0.95)
BATCH_SIZE = 50
PSI_BINS = 5
PSI_SMOOTHING = 0.5
DECIMALS = 6
CALIBRATION_MARGIN = Decimal("0.05")

POLICY_FILE = HERE / "policy.json"
POLICY_ARCHIVE = HERE / "policies_archive"
KEYS_DIR = HERE / "keys"
APPROVER_ID = "approver-demo"
SCENARIO_ID = "german-credit"
RUNS = ("gc-run-1", "gc-run-2")
OUT_DIR = EXPERIMENTS_DIR / "wp4"

FIXED_POLICY = {
    "max_demographic_parity_diff": 0.10,
    "drift_alert_threshold": 0.25,
    METRIC_THRESHOLD_STAGES: ["validation", "deployment"],
    "require_human_approval_for_high_risk": False,
    "signed_approval_required_for": ["deployment_request"],
}


# ----------------------------------------------------------------------
# Data, partition, models, metrics
# ----------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def read_dataset_bytes(archive: Path = DATASET_ZIP) -> bytes:
    """``german.data`` from the archive, after checking both digests."""
    raw = Path(archive).read_bytes()
    if _sha(raw) != ZIP_SHA256:
        raise ValueError(f"{archive} does not have the digest in PROVENANCE.md")
    data = zipfile.ZipFile(io.BytesIO(raw)).read("german.data")
    if _sha(data) != DATA_SHA256:
        raise ValueError("german.data does not have the digest in PROVENANCE.md")
    return data


def parse_dataset(data: bytes) -> pd.DataFrame:
    """1,000 rows, the 20 attributes and ``good`` (1 = good credit risk)."""
    rows = [line.split() for line in data.decode("ascii").splitlines() if line.strip()]
    if len(rows) != 1000 or any(len(r) != 21 for r in rows):
        raise ValueError("german.data does not have 1,000 rows of 21 fields")
    frame = pd.DataFrame([r[:20] for r in rows], columns=COLUMNS)
    for name in NUMERICAL:
        frame[name] = frame[name].astype(int)
    frame["good"] = [1 if r[20] == "1" else 0 for r in rows]
    return frame


def partition(frame: pd.DataFrame, seed: int) -> Dict[str, List[int]]:
    """Stratified 60/20/20 split of the row indices."""
    index = np.arange(len(frame))
    y = frame["good"].to_numpy()
    train, rest = train_test_split(index, test_size=0.4, stratify=y, random_state=seed)
    validation, test = train_test_split(rest, test_size=0.5, stratify=y[rest], random_state=seed)
    return {
        "train": sorted(int(i) for i in train),
        "validation": sorted(int(i) for i in validation),
        "test": sorted(int(i) for i in test),
    }


def young(frame: pd.DataFrame) -> np.ndarray:
    return (frame["age"] < AGE_THRESHOLD).to_numpy()


def reweighing_weights(group: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Kamiran and Calders (2012): w(g, y) = P(g) P(y) / P(g, y)."""
    weights = np.empty(len(y), dtype=float)
    for g in (False, True):
        for label in (0, 1):
            cell = (group == g) & (y == label)
            if cell.any():
                weights[cell] = (group == g).mean() * (y == label).mean() / cell.mean()
    return weights


def new_model() -> Pipeline:
    return Pipeline([
        ("features", ColumnTransformer([
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL),
            ("numerical", StandardScaler(), NUMERICAL),
        ])),
        ("classifier", LogisticRegression(max_iter=1000)),
    ])


def train(frame: pd.DataFrame, parts: Dict[str, List[int]], mitigated: bool) -> Pipeline:
    rows = frame.iloc[parts["train"]]
    model = new_model()
    if mitigated:
        weights = reweighing_weights(young(rows), rows["good"].to_numpy())
        model.fit(rows[COLUMNS], rows["good"], classifier__sample_weight=weights)
    else:
        model.fit(rows[COLUMNS], rows["good"])
    return model


def scores(model: Pipeline, frame: pd.DataFrame, rows: Sequence[int]) -> np.ndarray:
    """Probability of a good risk."""
    classes = list(model.classes_)
    return model.predict_proba(frame.iloc[list(rows)][COLUMNS])[:, classes.index(1)]


def policy_metrics(model: Pipeline, frame: pd.DataFrame, rows: Sequence[int]) -> Dict[str, float]:
    """Precision of the good-risk class and demographic parity difference."""
    subset = frame.iloc[list(rows)]
    predicted = scores(model, frame, rows) >= 0.5
    actual = subset["good"].to_numpy() == 1
    precision = (predicted & actual).sum() / predicted.sum()
    group = young(subset)
    parity = abs(predicted[~group].mean() - predicted[group].mean())
    return {
        "precision": round(float(precision), DECIMALS),
        "demographic_parity_diff": round(float(parity), DECIMALS),
    }


def psi(reference: np.ndarray, batch: np.ndarray) -> Dict:
    """Population Stability Index over quintile bins of the reference."""
    edges = np.quantile(reference, [i / PSI_BINS for i in range(1, PSI_BINS)])
    ref_counts = np.bincount(np.digitize(reference, edges, right=True), minlength=PSI_BINS)
    batch_counts = np.bincount(np.digitize(batch, edges, right=True), minlength=PSI_BINS)
    r = (ref_counts + PSI_SMOOTHING) / (len(reference) + PSI_SMOOTHING * PSI_BINS)
    b = (batch_counts + PSI_SMOOTHING) / (len(batch) + PSI_SMOOTHING * PSI_BINS)
    value = float(np.sum((b - r) * np.log(b / r)))
    return {
        "psi": round(value, DECIMALS),
        "edges": [float(e) for e in edges],
        "reference_counts": [int(c) for c in ref_counts],
        "batch_counts": [int(c) for c in batch_counts],
    }


def _half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def draw_batches(frame: pd.DataFrame, test: Sequence[int], seed: int = BATCH_SEED) -> List[Dict]:
    """Six batches with an increasing share of the drift subgroup."""
    test = np.array(sorted(test))
    in_group = (frame.iloc[test][DRIFT_ATTRIBUTE] == DRIFT_VALUE).to_numpy()
    sub, rest = test[in_group], test[~in_group]
    natural = len(sub) / len(test)
    rng = np.random.default_rng(seed)
    batches = []
    for k, share in enumerate((natural, natural) + DRIFT_FIXED_SHARES, start=1):
        n_sub = _half_up(BATCH_SIZE * share)
        chosen = np.concatenate([
            rng.choice(sub, n_sub, replace=False),
            rng.choice(rest, BATCH_SIZE - n_sub, replace=False),
        ])
        batches.append({
            "batch": k,
            "target_share": round(share, DECIMALS),
            "subgroup_count": n_sub,
            "indices": sorted(int(i) for i in chosen),
        })
    return batches


def monitoring_report(model_digest: str, partition_digest: str, batch: Dict,
                      reference: np.ndarray, batch_scores: np.ndarray) -> Dict:
    stats = psi(reference, batch_scores)
    return {
        "type": "monitoring_report",
        "batch": batch["batch"],
        "drift": {
            "induced": True,
            "subgroup": f"{DRIFT_ATTRIBUTE} == {DRIFT_VALUE}",
            "target_share": batch["target_share"],
            "subgroup_count": batch["subgroup_count"],
        },
        "model_sha256": model_digest,
        "partition_sha256": partition_digest,
        "reference_partition": "validation",
        "indices": batch["indices"],
        "bins": PSI_BINS,
        "smoothing": PSI_SMOOTHING,
        **stats,
    }


def drift_metrics(report: Dict) -> Dict[str, float]:
    return {"psi": report["psi"], "drift_score": min(report["psi"], 1.0)}


# ----------------------------------------------------------------------
# Artefacts and events
# ----------------------------------------------------------------------

def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _model_bytes(model: Pipeline) -> bytes:
    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return buffer.getvalue()


def load_model(path: Path) -> Pipeline:
    return joblib.load(path)


def event(run_id: str, event_type: str, stage: str, artefact: StoredArtifact,
          artifact_id: str, artifact_type: str, metrics: Optional[Dict] = None,
          approval: Optional[Dict] = None) -> Dict:
    e = {
        "scenario_id": SCENARIO_ID,
        "event_type": event_type,
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "pipeline_stage": stage,
        "risk_level": "high",          # Annex III, point 5(b)
        "run_id": run_id,
        "artifact_sha256": artefact.digest,
        "off_chain_ref": artefact.ref,
    }
    if metrics is not None:
        e["metrics"] = metrics
    if approval is not None:
        e["approval"] = approval
    return e


@dataclass
class CaseRun:
    events: List[Dict]
    partition: Dict[str, List[int]]
    metrics: Dict[str, Dict[str, float]]
    batches: List[Dict]


def build_events(store: ArtifactStore, seed: int, approver) -> CaseRun:
    """The fixed sequence of the protocol (16 events), with every metric computed."""
    data = read_dataset_bytes()
    frame = parse_dataset(data)
    parts = partition(frame, seed)
    dataset = store.put_bytes(data)
    split = store.put_bytes(_json_bytes({
        "type": "partition", "dataset_sha256": dataset.digest, "seed": seed,
        "proportions": [0.6, 0.2, 0.2], "stratified_by": "label", **parts,
    }))

    events: List[Dict] = []
    metrics: Dict[str, Dict[str, float]] = {}
    models = {}
    for run_id, version, mitigated in ((RUNS[0], "v1", False), (RUNS[1], "v2", True)):
        model = train(frame, parts, mitigated)
        stored = store.put_bytes(_model_bytes(model))
        models[version] = (model, stored)
        metrics[version] = policy_metrics(model, frame, parts["validation"])
        model_id = f"credit-lr-{version}"
        events += [
            event(run_id, "data_ingested", "data_preparation", dataset, "german-credit-data", "dataset"),
            event(run_id, "data_split", "data_preparation", split, f"german-credit-partition-{seed}", "dataset"),
            event(run_id, "model_trained", "training", stored, model_id, "model"),
            event(run_id, "model_validation", "validation", stored, model_id, "model",
                  metrics=dict(metrics[version])),
        ]

    model, stored = models["v2"]
    events.append(event(RUNS[1], "deployment_request", "deployment", stored, "credit-lr-v2",
                        "model", metrics=dict(metrics["v2"])))
    approval = sign_approval(approver, APPROVER_ID, stored.digest, RUNS[1])
    events.append(event(RUNS[1], "deployment_request", "deployment", stored, "credit-lr-v2",
                        "model", metrics=dict(metrics["v2"]), approval=approval))

    reference = scores(model, frame, parts["validation"])
    batches = draw_batches(frame, parts["test"])
    for batch in batches:
        report = monitoring_report(stored.digest, split.digest, batch, reference,
                                   scores(model, frame, batch["indices"]))
        batch["psi"] = report["psi"]
        artefact = store.put_bytes(_json_bytes(report))
        events.append(event(RUNS[1], "monitoring_batch", "post_deploy_monitoring", artefact,
                            f"monitoring-batch-{batch['batch']}", "monitoring_report",
                            metrics=drift_metrics(report)))
    return CaseRun(events=events, partition=parts, metrics=metrics, batches=batches)


# ----------------------------------------------------------------------
# Third-party recomputation
# ----------------------------------------------------------------------

def recompute_metrics(records: Iterable[Dict], store: ArtifactStore) -> List[Dict]:
    """Recompute every metric of the ledger from the ledger and the store.

    The dataset and the partition of a run are the artefacts of its
    ``data_ingested`` and ``data_split`` events; a validation metric is
    recomputed from the model the record names, a drift metric from the batch
    report it names (which names the model and the partition)."""
    records = list(records)
    runs: Dict[str, Dict[str, str]] = {}
    for r in records:
        if r.get("event_type") in ("data_ingested", "data_split"):
            runs.setdefault(r["run_id"], {})[r["event_type"]] = r["artifact_hash"]

    frames: Dict[str, pd.DataFrame] = {}

    def frame_for(digest: str) -> pd.DataFrame:
        if digest not in frames:
            frames[digest] = parse_dataset(store.path_for(digest).read_bytes())
        return frames[digest]

    def json_for(digest: str) -> Dict:
        return json.loads(store.path_for(digest).read_text(encoding="utf-8"))

    results = []
    for index, r in enumerate(records):
        recorded = r.get("metrics") or {}
        if not recorded:
            continue
        run = runs.get(r.get("run_id"), {})
        if "psi" in recorded:
            report = json_for(r["artifact_hash"])
            parts = json_for(report["partition_sha256"])
            frame = frame_for(parts["dataset_sha256"])
            model = load_model(store.path_for(report["model_sha256"]))
            stats = psi(scores(model, frame, parts["validation"]),
                        scores(model, frame, report["indices"]))
            recomputed = drift_metrics(stats)
        else:
            parts = json_for(run["data_split"])
            if parts["dataset_sha256"] != run["data_ingested"]:
                raise ValueError(f"run {r.get('run_id')}: partition names another dataset")
            frame = frame_for(run["data_ingested"])
            model = load_model(store.path_for(r["artifact_hash"]))
            recomputed = policy_metrics(model, frame, parts["validation"])
        results.append({
            "index": index,
            "evidence_id": r.get("evidence_id"),
            "event_type": r.get("event_type"),
            "recorded": recorded,
            "recomputed": recomputed,
            "match": recomputed == recorded,
        })
    return results


# ----------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def environment() -> Dict[str, str]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "joblib": joblib.__version__,
    }


def approver_key():
    """The demonstration approver key, committed so the case regenerates
    under the same policy. In use, the approver alone holds this key."""
    return load_or_create_key(APPROVER_ID, keys_dir=KEYS_DIR)


def calibrated_min_precision(pilot_v2_precision: float) -> float:
    value = (Decimal(str(pilot_v2_precision)) - CALIBRATION_MARGIN).quantize(
        Decimal("0.01"), rounding=ROUND_FLOOR)
    return float(value)


def pilot(force: bool = False, out_dir: Path = OUT_DIR) -> Path:
    """Seed 7: compute the pilot metrics and write the case policy."""
    if POLICY_FILE.exists() and not force:
        raise SystemExit(f"{POLICY_FILE} exists: the policy is fixed after the pilot")
    frame = parse_dataset(read_dataset_bytes())
    parts = partition(frame, PILOT_SEED)
    metrics, drift = {}, []
    for version, mitigated in (("v1", False), ("v2", True)):
        model = train(frame, parts, mitigated)
        metrics[version] = policy_metrics(model, frame, parts["validation"])
        if mitigated:
            reference = scores(model, frame, parts["validation"])
            for batch in draw_batches(frame, parts["test"]):
                stats = psi(reference, scores(model, frame, batch["indices"]))
                drift.append({"batch": batch["batch"], "target_share": batch["target_share"],
                              "psi": stats["psi"]})
    min_precision = calibrated_min_precision(metrics["v2"]["precision"])
    policy = {
        "min_precision": min_precision,
        **FIXED_POLICY,
        "authorised_approvers": {APPROVER_ID: public_key_hex(approver_key())},
    }
    POLICY_FILE.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pilot_{_now()}.json"
    path.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Pilot partition (seed 7), discarded for evaluation. Used only to "
                "calibrate min_precision, as fixed in protocols/wp4_credit_case.md.",
        "protocol": "Project/protocols/wp4_credit_case.md",
        "environment": environment(),
        "partition_seed": PILOT_SEED,
        "validation_metrics": metrics,
        "drift": drift,
        "calibration": {
            "rule": "floor to 0.01 of (pilot v2 validation precision - 0.05)",
            "pilot_v2_precision": metrics["v2"]["precision"],
            "min_precision": min_precision,
        },
        "policy": policy,
    }, indent=1) + "\n", encoding="utf-8")
    print(f"pilot metrics: {metrics}")
    print(f"min_precision = {min_precision}; policy written to {POLICY_FILE}")
    print(f"saved to {path}")
    return path


def run(out_dir: Path = OUT_DIR, seed: int = MAIN_SEED) -> Path:
    """The case under the committed policy; writes a self-contained run folder."""
    if not POLICY_FILE.exists():
        raise SystemExit("no policy.json: run the pilot first")
    from oscal_exporter import to_oscal_sar
    from validate_oscal_schema import SCHEMA_PATH, UnicodeDraft7

    folder = out_dir / f"run_{_now()}"
    folder.mkdir(parents=True)
    store = ArtifactStore(folder / "store")
    oracle = ComplianceOracle(policy_file=POLICY_FILE, ledger_file=folder / "ledger.jsonl",
                              schema_version=SCHEMA_V2)
    case = build_events(store, seed, approver_key())
    records = [oracle.process_mlops_event(e) for e in case.events]

    # Self-contained: the policy as archived, the engine's public key.
    policy_id = records[0]["policy_id"]
    (folder / "policies_archive").mkdir()
    shutil.copy2(POLICY_ARCHIVE / f"{policy_id}.json", folder / "policies_archive")
    shutil.copy2(POLICY_FILE, folder / "policy.json")
    (folder / "keys").mkdir()
    shutil.copy2(SIM / "keys" / f"{ISSUER_ID_V2}.ed25519.pub.pem", folder / "keys")
    shutil.copy2(KEYS_DIR / f"{APPROVER_ID}.ed25519.pub.pem", folder / "keys")

    ledger = read_ledger(folder / "ledger.jsonl")
    chain = oracle.verify_chain(ledger)
    reexecution = reexecute_ledger(ledger, folder / "policies_archive")
    artefacts = verify_ledger_artifacts(ledger, store)
    recomputation = recompute_metrics(ledger, store)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    oscal = {}
    for label, redacted in (("complete", False), ("redacted", True)):
        document = to_oscal_sar(ledger, redacted=redacted)
        name = f"oscal_assessment_results_{label}.json"
        (folder / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        oscal[label] = len(list(UnicodeDraft7(schema).iter_errors(document)))

    decisions: Dict[str, int] = {}
    for r in ledger:
        decisions[r["decision"]] = decisions.get(r["decision"], 0) + 1
    acceptance = {
        "metrics_recomputed": bool(recomputation) and all(m["match"] for m in recomputation),
        "chain_valid": chain.is_valid,
        "artefacts_recomputed": bool(artefacts) and all(a["status"] == "ok" for a in artefacts),
        "reexecution_all_match": reexecution["counts"].get(MATCH, 0) == len(ledger),
        "oscal_valid": all(errors == 0 for errors in oscal.values()),
        "decision_types": all(decisions.get(d, 0) > 0 for d in ("approved", "rejected", "escalated")),
    }

    def dump(name: str, value) -> None:
        (folder / name).write_text(json.dumps(value, indent=1) + "\n", encoding="utf-8")

    dump("reexecution.json", {
        "total": reexecution["total"], "counts": reexecution["counts"],
        "results": [{"evidence_id": r.evidence_id, "status": r.status, "recorded": r.recorded,
                     "recomputed": r.recomputed, "differences": r.differences}
                    for r in reexecution["results"]],
    })
    dump("artefacts.json", artefacts)
    dump("recomputation.json", recomputation)
    dump("summary.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "Project/protocols/wp4_credit_case.md",
        "environment": environment(),
        "partition_seed": seed,
        "batch_seed": BATCH_SEED,
        "policy_id": policy_id,
        "policy_hash": records[0]["policy_hash"],
        "policy": json.loads(POLICY_FILE.read_text(encoding="utf-8")),
        "partition_sizes": {k: len(v) for k, v in case.partition.items()},
        "validation_metrics": case.metrics,
        "batches": [{k: b[k] for k in ("batch", "target_share", "subgroup_count", "psi")}
                    for b in case.batches],
        "events": [{
            "n": i + 1, "run_id": r["run_id"], "event_type": r["event_type"],
            "pipeline_stage": r["pipeline_stage"], "decision": r["decision"],
            "rule_id": r["rule_id"], "metrics": r["metrics"],
            "artifact_hash": r["artifact_hash"],
            "supports_requirements": r["supports_requirements"],
        } for i, r in enumerate(ledger)],
        "decisions": decisions,
        "chain": {"total": chain.total, "valid": chain.valid, "issues": chain.issues},
        "reexecution": reexecution["counts"],
        "artefacts": {s: sum(1 for a in artefacts if a["status"] == s)
                      for s in sorted({a["status"] for a in artefacts})},
        "metrics_recomputed": {"total": len(recomputation),
                               "match": sum(1 for m in recomputation if m["match"])},
        "oscal_schema_errors": oscal,
        "acceptance": acceptance,
    })
    print(json.dumps({"decisions": decisions, "acceptance": acceptance}, indent=1))
    print(f"saved to {folder}")
    return folder


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("pilot", "run"))
    parser.add_argument("--force", action="store_true",
                        help="pilot: overwrite an existing policy.json")
    args = parser.parse_args(argv)
    if args.command == "pilot":
        pilot(force=args.force)
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
