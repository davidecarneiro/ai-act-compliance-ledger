"""Stability of the case's gate decisions across partitions (WP4 addendum).

Protocol: ``Project/protocols/wp4_supplementary_seed_stability.md`` — post hoc
and exploratory, recorded before this was run. The pipeline of the case is
reused unchanged; only the partition seed varies. Decisions are taken by the
engine's own ``evaluate_event`` under the committed case policy, so each one
is the decision the engine would have recorded.

    python3 seed_stability.py [--first 0] [--count 500]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

import credit_case as cc
from approvals import sign_approval
from canonical import SCHEMA_V2
from simulator import evaluate_event

Z95 = 1.959963984540054


def wilson(successes: int, n: int) -> List[float]:
    """Wilson score interval, 95 %."""
    if n == 0:
        return [float("nan"), float("nan")]
    p = successes / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def distribution(values: Sequence[float]) -> Dict[str, float]:
    a = np.asarray(values, dtype=float)
    q = np.percentile(a, [5, 25, 50, 75, 95])
    return {"p5": round(float(q[0]), 4), "q1": round(float(q[1]), 4),
            "median": round(float(q[2]), 4), "q3": round(float(q[3]), 4),
            "p95": round(float(q[4]), 4)}


def share(flags: Sequence[bool]) -> Dict:
    k, n = int(sum(flags)), len(flags)
    return {"count": k, "n": n, "share": round(k / n, 4), "wilson95": wilson(k, n)}


def _event(stage: str, event_type: str, metrics: Dict, digest: str, run_id: str,
           approval=None) -> Dict:
    e = {
        "event_type": event_type, "artifact_id": "credit-lr", "artifact_type": "model",
        "pipeline_stage": stage, "risk_level": "high", "run_id": run_id,
        "artifact_sha256": digest, "off_chain_ref": f"store/sha256/{digest}",
        "metrics": metrics,
    }
    if approval is not None:
        e["approval"] = approval
    return e


def observe(seed: int, frame, policy: Dict, approver) -> Dict:
    """One partition: metrics, gate decisions and drift alerts."""
    parts = cc.partition(frame, seed)
    young_val = int(cc.young(frame.iloc[parts["validation"]]).sum())
    out: Dict = {"seed": seed, "validation_under_25": young_val}
    for version, mitigated in (("v1", False), ("v2", True)):
        model = cc.train(frame, parts, mitigated)
        digest = sha256(cc._model_bytes(model)).hexdigest()
        run_id = f"seed-{seed}-{version}"
        val = cc.policy_metrics(model, frame, parts["validation"])
        test = cc.policy_metrics(model, frame, parts["test"])
        decision_val = evaluate_event(_event("validation", "model_validation", val, digest, run_id),
                                      policy, SCHEMA_V2)
        decision_test = evaluate_event(_event("validation", "model_validation", test, digest, run_id),
                                       policy, SCHEMA_V2)
        out[version] = {
            "validation": val, "test": test,
            "decision": decision_val[0], "rule_id": decision_val[2],
            "decision_on_test": decision_test[0], "rule_id_on_test": decision_test[2],
        }
        if mitigated:
            approval = sign_approval(approver, cc.APPROVER_ID, digest, run_id)
            deploy = evaluate_event(_event("deployment", "deployment_request", val, digest,
                                           run_id, approval), policy, SCHEMA_V2)
            out["deployment_v2"] = {"decision": deploy[0], "rule_id": deploy[2]}
            reference = cc.scores(model, frame, parts["validation"])
            batches = []
            for batch in cc.draw_batches(frame, parts["test"], cap=True):
                stats = cc.psi(reference, cc.scores(model, frame, batch["indices"]))
                metrics = cc.drift_metrics(stats)
                d = evaluate_event({**_event("post_deploy_monitoring", "monitoring_batch", metrics,
                                             digest, run_id), "artifact_type": "monitoring_report"},
                                   policy, SCHEMA_V2)
                needed = cc._half_up(cc.BATCH_SIZE * batch["target_share"])
                batches.append({"batch": batch["batch"], "target_share": batch["target_share"],
                                "subgroup_count": batch["subgroup_count"],
                                "capped": batch["subgroup_count"] < needed,
                                "psi": stats["psi"], "decision": d[0]})
            out["monitoring"] = batches
    return out


def summarise(observations: List[Dict], policy: Dict) -> Dict:
    summary: Dict = {"partitions": len(observations)}
    summary["validation_under_25"] = distribution([o["validation_under_25"] for o in observations])
    for version in ("v1", "v2"):
        obs = [o[version] for o in observations]
        summary[version] = {
            "validation_precision": distribution([x["validation"]["precision"] for x in obs]),
            "validation_parity": distribution([x["validation"]["demographic_parity_diff"] for x in obs]),
            "test_parity": distribution([x["test"]["demographic_parity_diff"] for x in obs]),
            "passes_validation": share([x["decision"] == "approved" for x in obs]),
            "rejected_on_precision": share([x["rule_id"] == "threshold.precision" for x in obs]),
            "rejected_on_fairness": share([x["rule_id"] == "threshold.fairness" for x in obs]),
            "validation_and_test_agree": share([x["decision"] == x["decision_on_test"] for x in obs]),
        }
    summary["v1_and_v2_differ"] = share([o["v1"]["decision"] != o["v2"]["decision"] for o in observations])
    summary["v2_parity_below_v1"] = share([
        o["v2"]["validation"]["demographic_parity_diff"] < o["v1"]["validation"]["demographic_parity_diff"]
        for o in observations])
    summary["deployment_v2_approved"] = share([o["deployment_v2"]["decision"] == "approved"
                                               for o in observations])
    summary["monitoring_alert_rate"] = [
        {"batch": k + 1,
         "target_share": ("natural" if k < 2 else observations[0]["monitoring"][k]["target_share"]),
         "psi": distribution([o["monitoring"][k]["psi"] for o in observations]),
         "alert": share([o["monitoring"][k]["decision"] == "escalated" for o in observations]),
         "capped": share([o["monitoring"][k]["capped"] for o in observations])}
        for k in range(len(observations[0]["monitoring"]))
    ]
    summary["partitions_with_capped_batches"] = share([
        any(b["capped"] for b in o["monitoring"]) for o in observations])
    summary["main_run_seed_42"] = next(
        ({"v1": o["v1"]["decision"], "v2": o["v2"]["decision"]} for o in observations if o["seed"] == 42),
        None)
    return summary


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--first", type=int, default=0)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    frame = cc.parse_dataset(cc.read_dataset_bytes())
    policy = json.loads(cc.POLICY_FILE.read_text(encoding="utf-8"))
    approver = cc.approver_key()
    seeds = range(args.first, args.first + args.count)
    observations = [observe(s, frame, policy, approver) for s in seeds]
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": "Project/protocols/wp4_supplementary_seed_stability.md",
        "note": "Post hoc and exploratory; the main run's results stand as reported.",
        "environment": cc.environment(),
        "seeds": [args.first, args.first + args.count - 1],
        "policy": policy,
        "summary": summarise(observations, policy),
        "observations": observations,
    }
    out = args.out or cc.OUT_DIR / f"seed_stability_{cc._now()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=1))
    print(f"saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
